from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import glob
import asyncio
from typing import List, Dict, Any
import threading
import queue
from pathlib import Path
from . import config

# Import our custom recording functionality
from .recording import (
    RecordingRequest,
    UploadRequest,
    DatasetInfoRequest,
    handle_start_recording,
    handle_stop_recording,
    handle_exit_early,
    handle_rerecord_episode,
    handle_recording_status,
    handle_upload_dataset,
    handle_get_dataset_info,
)

# Import our custom teleoperation functionality
from .teleoperating import (
    TeleoperateRequest,
    handle_start_teleoperation,
    handle_stop_teleoperation,
    handle_teleoperation_status,
    handle_get_joint_positions,
)

# Import our custom calibration functionality
from .calibrating import CalibrationRequest, calibration_manager

# Import our custom training functionality
from .training import (
    TrainingRequest,
    handle_start_training,
    handle_stop_training,
    handle_training_status,
    handle_training_logs,
)

# Import our custom replay functionality
from .replaying import (
    ReplayRequest,
    handle_start_replay,
    handle_stop_replay,
    handle_replay_status,
    handle_replay_logs,
)

# Import camera detection functionality
from .camera_detection import (
    find_all_cameras,
    find_opencv_cameras,
    find_realsense_cameras,
    test_camera_configuration,
    create_camera_config_for_lerobot,
    get_camera_summary,
    capture_image_from_camera
)


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables for WebSocket connections
connected_websockets: List[WebSocket] = []


app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Create static directory if it doesn't exist
os.makedirs("app/static", exist_ok=True)

# Mount the static directory
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Get the path to the lerobot root directory (3 levels up from this script)
LEROBOT_PATH = str(Path(__file__).parent.parent.parent.parent)
logger.info(f"LeRobot path: {LEROBOT_PATH}")

# Import shared configuration constants
from .config import (
    CALIBRATION_BASE_PATH_TELEOP,
    CALIBRATION_BASE_PATH_ROBOTS,
    LEADER_CONFIG_PATH,
    FOLLOWER_CONFIG_PATH,
    find_available_ports,
    find_robot_port,
    detect_port_after_disconnect,
    save_robot_port,
    get_saved_robot_port,
    get_default_robot_port,
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.broadcast_queue = queue.Queue()
        self.broadcast_thread = None
        self.is_running = False

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            f"WebSocket connected. Total connections: {len(self.active_connections)}"
        )

        # Start broadcast thread if not running
        if not self.is_running:
            self.start_broadcast_thread()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                f"WebSocket disconnected. Total connections: {len(self.active_connections)}"
            )

        # Stop broadcast thread if no connections
        if not self.active_connections and self.is_running:
            self.stop_broadcast_thread()

    def start_broadcast_thread(self):
        """Start the background thread for broadcasting data"""
        if self.is_running:
            return

        self.is_running = True
        self.broadcast_thread = threading.Thread(
            target=self._broadcast_worker, daemon=True
        )
        self.broadcast_thread.start()
        logger.info("📡 Broadcast thread started")

    def stop_broadcast_thread(self):
        """Stop the background thread"""
        self.is_running = False
        if self.broadcast_thread:
            self.broadcast_thread.join(timeout=1.0)
            logger.info("📡 Broadcast thread stopped")

    def _broadcast_worker(self):
        """Background worker thread for broadcasting WebSocket data"""
        import asyncio

        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            while self.is_running:
                try:
                    # Get data from queue with timeout
                    data = self.broadcast_queue.get(timeout=0.1)
                    if data is None:  # Poison pill to stop
                        break

                    # Broadcast to all connections
                    if self.active_connections:
                        loop.run_until_complete(self._send_to_all_connections(data))

                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error in broadcast worker: {e}")

        finally:
            loop.close()

    async def _send_to_all_connections(self, data: Dict[str, Any]):
        """Send data to all active WebSocket connections"""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.error(f"Error sending data to WebSocket: {e}")
                disconnected.append(connection)

        # Remove disconnected connections
        for connection in disconnected:
            self.disconnect(connection)

    def broadcast_joint_data_sync(self, data: Dict[str, Any]):
        """Thread-safe method to queue data for broadcasting"""
        if self.is_running and self.active_connections:
            try:
                self.broadcast_queue.put_nowait(data)
            except queue.Full:
                logger.warning("Broadcast queue is full, dropping data")


manager = ConnectionManager()


@app.get("/")
def read_root():
    return FileResponse("app/static/index.html")


@app.get("/get-configs")
def get_configs():
    # Get all available calibration configs
    leader_configs = [
        os.path.basename(f)
        for f in glob.glob(os.path.join(LEADER_CONFIG_PATH, "*.json"))
    ]
    follower_configs = [
        os.path.basename(f)
        for f in glob.glob(os.path.join(FOLLOWER_CONFIG_PATH, "*.json"))
    ]

    return {"leader_configs": leader_configs, "follower_configs": follower_configs}


@app.post("/move-arm")
def teleoperate_arm(request: TeleoperateRequest):
    """Start teleoperation of the robot arm"""
    return handle_start_teleoperation(request, manager)


@app.post("/stop-teleoperation")
def stop_teleoperation():
    """Stop the current teleoperation session"""
    return handle_stop_teleoperation()


@app.get("/teleoperation-status")
def teleoperation_status():
    """Get the current teleoperation status"""
    return handle_teleoperation_status()


@app.get("/joint-positions")
def get_joint_positions():
    """Get current robot joint positions"""
    return handle_get_joint_positions()


@app.get("/health")
def health_check():
    """Simple health check endpoint to verify server is running"""
    return {"status": "ok", "message": "FastAPI server is running"}


@app.get("/ws-test")
def websocket_test():
    """Test endpoint to verify WebSocket support"""
    return {"websocket_endpoint": "/ws/joint-data", "status": "available"}


@app.websocket("/ws/joint-data")
async def websocket_endpoint(websocket: WebSocket):
    logger.info("🔗 New WebSocket connection attempt")
    try:
        await manager.connect(websocket)
        logger.info("✅ WebSocket connection established")

        while True:
            # Keep the connection alive and wait for messages
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                # Handle any incoming messages if needed
                logger.debug(f"Received WebSocket message: {data}")
            except asyncio.TimeoutError:
                # No message received, continue
                pass
            except WebSocketDisconnect:
                logger.info("🔌 WebSocket client disconnected")
                break

            # Small delay to prevent excessive CPU usage
            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected normally")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
    finally:
        manager.disconnect(websocket)
        logger.info("🧹 WebSocket connection cleaned up")


@app.post("/start-recording")
def start_recording(request: RecordingRequest):
    """Start a dataset recording session"""
    return handle_start_recording(request, manager)


@app.post("/stop-recording")
def stop_recording():
    """Stop the current recording session"""
    return handle_stop_recording()


@app.get("/recording-status")
def recording_status():
    """Get the current recording status"""
    return handle_recording_status()


@app.post("/recording-exit-early")
def recording_exit_early():
    """Skip to next episode (replaces right arrow key)"""
    return handle_exit_early()


@app.post("/recording-rerecord-episode")
def recording_rerecord_episode():
    """Re-record current episode (replaces left arrow key)"""
    return handle_rerecord_episode()


@app.post("/upload-dataset")
def upload_dataset(request: UploadRequest):
    """Upload dataset to HuggingFace Hub"""
    return handle_upload_dataset(request)


@app.post("/dataset-info")
def get_dataset_info(request: DatasetInfoRequest):
    """Get information about a saved dataset"""
    return handle_get_dataset_info(request)


# ============================================================================
# TRAINING ENDPOINTS
# ============================================================================


@app.post("/start-training")
def start_training(request: TrainingRequest):
    """Start a training session"""
    return handle_start_training(request)


@app.post("/stop-training")
def stop_training():
    """Stop the current training session"""
    return handle_stop_training()


@app.get("/training-status")
def training_status():
    """Get the current training status"""
    return handle_training_status()


@app.get("/training-logs")
def training_logs():
    """Get recent training logs"""
    return handle_training_logs()


# ============================================================================
# REPLAY ENDPOINTS
# ============================================================================


@app.post("/start-replay")
def start_replay(request: ReplayRequest):
    """Start a replay session"""
    return handle_start_replay(request)


@app.post("/stop-replay")
def stop_replay():
    """Stop the current replay session"""
    return handle_stop_replay()


@app.get("/replay-status")
def replay_status():
    """Get the current replay status"""
    return handle_replay_status()


@app.get("/replay-logs")
def replay_logs():
    """Get recent replay logs"""
    return handle_replay_logs()


# ============================================================================
# Calibration endpoints
@app.post("/start-calibration")
def start_calibration(request: CalibrationRequest):
    """Start calibration process"""
    return calibration_manager.start_calibration(request)


@app.post("/stop-calibration")
def stop_calibration():
    """Stop calibration process"""
    return calibration_manager.stop_calibration_process()


@app.get("/calibration-status")
def calibration_status():
    """Get current calibration status"""
    from dataclasses import asdict

    status = calibration_manager.get_status()
    return asdict(status)


@app.post("/calibration-input")
def send_calibration_input(data: dict):
    """Send input to the calibration process"""
    input_text = data.get("input", "")
    logger.info(f"🔵 API: Received input request: {repr(input_text)}")
    result = calibration_manager.send_input(input_text)
    logger.info(f"🔵 API: Returning result: {result}")
    return result


@app.get("/calibration-debug")
def calibration_debug():
    """Debug endpoint to check calibration state"""
    try:
        queue_size = calibration_manager._input_queue.qsize()
        event_set = calibration_manager._input_ready.is_set()
        calibration_active = calibration_manager.status.calibration_active

        return {
            "queue_size": queue_size,
            "event_set": event_set,
            "calibration_active": calibration_active,
            "status": calibration_manager.status.status,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/calibration-configs/{device_type}")
def get_calibration_configs(device_type: str):
    """Get all calibration config files for a specific device type"""
    try:
        if device_type == "robot":
            config_path = FOLLOWER_CONFIG_PATH
        elif device_type == "teleop":
            config_path = LEADER_CONFIG_PATH
        else:
            return {"success": False, "message": "Invalid device type"}

        # Get all JSON files in the config directory
        configs = []
        if os.path.exists(config_path):
            for file in os.listdir(config_path):
                if file.endswith(".json"):
                    config_name = os.path.splitext(file)[0]
                    file_path = os.path.join(config_path, file)
                    file_size = os.path.getsize(file_path)
                    modified_time = os.path.getmtime(file_path)

                    configs.append(
                        {
                            "name": config_name,
                            "filename": file,
                            "size": file_size,
                            "modified": modified_time,
                        }
                    )

        return {"success": True, "configs": configs, "device_type": device_type}

    except Exception as e:
        logger.error(f"Error getting calibration configs: {e}")
        return {"success": False, "message": str(e)}


@app.delete("/calibration-configs/{device_type}/{config_name}")
def delete_calibration_config(device_type: str, config_name: str):
    """Delete a calibration config file"""
    try:
        if device_type == "robot":
            config_path = FOLLOWER_CONFIG_PATH
        elif device_type == "teleop":
            config_path = LEADER_CONFIG_PATH
        else:
            return {"success": False, "message": "Invalid device type"}

        # Construct the file path
        filename = f"{config_name}.json"
        file_path = os.path.join(config_path, filename)

        # Check if file exists
        if not os.path.exists(file_path):
            return {"success": False, "message": "Configuration file not found"}

        # Delete the file
        os.remove(file_path)
        logger.info(f"Deleted calibration config: {file_path}")

        return {
            "success": True,
            "message": f"Configuration '{config_name}' deleted successfully",
        }

    except Exception as e:
        logger.error(f"Error deleting calibration config: {e}")
        return {"success": False, "message": str(e)}


# ============================================================================
# PORT DETECTION ENDPOINTS
# ============================================================================

@app.get("/available-ports")
def get_available_ports():
    """Get all available serial ports"""
    try:
        ports = find_available_ports()
        return {"status": "success", "ports": ports}
    except Exception as e:
        logger.error(f"Error getting available ports: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/available-cameras")
def get_available_cameras():
    """Get all available cameras"""
    try:
        # Try to detect cameras using OpenCV
        import cv2
        cameras = []
        
        # Test up to 10 camera indices
        for i in range(10):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    cameras.append({
                        "index": i,
                        "name": f"Camera {i}",
                        "available": True,
                        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                        "fps": int(cap.get(cv2.CAP_PROP_FPS)),
                    })
                cap.release()
            
        return {"status": "success", "cameras": cameras}
    except ImportError:
        # OpenCV not available, return empty list
        logger.warning("OpenCV not available for camera detection")
        return {"status": "success", "cameras": []}
    except Exception as e:
        logger.error(f"Error detecting cameras: {e}")
        return {"status": "error", "message": str(e), "cameras": []}


@app.post("/start-port-detection")
def start_port_detection(data: dict):
    """Start port detection process for a robot"""
    try:
        robot_type = data.get("robot_type", "robot")
        result = find_robot_port(robot_type)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error starting port detection: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/detect-port-after-disconnect")
def detect_port_after_disconnect_endpoint(data: dict):
    """Detect port after disconnection"""
    try:
        ports_before = data.get("ports_before", [])
        detected_port = detect_port_after_disconnect(ports_before)
        return {"status": "success", "port": detected_port}
    except Exception as e:
        logger.error(f"Error detecting port: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/save-robot-port")
def save_robot_port_endpoint(data: dict):
    """Save a robot port for future use"""
    try:
        robot_type = data.get("robot_type")
        port = data.get("port")
        
        if not robot_type or not port:
            return {"status": "error", "message": "robot_type and port are required"}
        
        save_robot_port(robot_type, port)
        return {"status": "success", "message": f"Port {port} saved for {robot_type}"}
    except Exception as e:
        logger.error(f"Error saving robot port: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/robot-port/{robot_type}")
def get_robot_port(robot_type: str):
    """Get the saved port for a robot type"""
    try:
        saved_port = get_saved_robot_port(robot_type)
        default_port = get_default_robot_port(robot_type)
        return {
            "status": "success", 
            "saved_port": saved_port,
            "default_port": default_port
        }
    except Exception as e:
        logger.error(f"Error getting robot port: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/save-robot-config")
def save_robot_config_endpoint(data: dict):
    """Save a robot configuration for future use"""
    try:
        robot_type = data.get("robot_type")
        config_name = data.get("config_name")
        
        if not robot_type or not config_name:
            return {"status": "error", "message": "Missing robot_type or config_name"}
            
        success = config.save_robot_config(robot_type, config_name)
        
        if success:
            return {"status": "success", "message": f"Configuration saved for {robot_type}"}
        else:
            return {"status": "error", "message": "Failed to save configuration"}
            
    except Exception as e:
        logger.error(f"Error saving robot configuration: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/robot-config/{robot_type}")
def get_robot_config(robot_type: str, available_configs: str = ""):
    """Get the saved configuration for a robot type"""
    try:
        # Parse available configs from query parameter
        available_configs_list = []
        if available_configs:
            available_configs_list = [cfg.strip() for cfg in available_configs.split(",") if cfg.strip()]
        
        saved_config = config.get_saved_robot_config(robot_type)
        default_config = config.get_default_robot_config(robot_type, available_configs_list)
        
        return {
            "status": "success", 
            "saved_config": saved_config,
            "default_config": default_config
        }
    except Exception as e:
        logger.error(f"Error getting robot configuration: {e}")
        return {"status": "error", "message": str(e)}


# Camera detection endpoints
@app.get("/cameras/detect")
def detect_cameras(camera_type: str = None):
    """Detect available cameras, optionally filtered by type (opencv/realsense)"""
    try:
        logger.info(f"Detecting cameras, filter: {camera_type}")
        cameras = find_all_cameras(camera_type_filter=camera_type)
        
        return {
            "status": "success",
            "cameras": cameras,
            "total_found": len(cameras),
            "message": f"Found {len(cameras)} cameras"
        }
    except Exception as e:
        logger.error(f"Error detecting cameras: {e}")
        return {"status": "error", "message": str(e), "cameras": []}


@app.get("/cameras/summary")
def get_cameras_summary():
    """Get a summary of all available cameras"""
    try:
        summary = get_camera_summary()
        return {"status": "success", **summary}
    except Exception as e:
        logger.error(f"Error getting camera summary: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/cameras/test")
def test_camera(camera_info: dict):
    """Test a specific camera configuration"""
    try:
        result = test_camera_configuration(camera_info)
        return {"status": "success" if result["success"] else "error", **result}
    except Exception as e:
        logger.error(f"Error testing camera: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/cameras/capture")
def capture_camera_image(data: dict):
    """Capture an image from a specific camera"""
    try:
        # Extract camera_info from the request data
        camera_info = data.get("camera_info", {})
        logger.info(f"Capture endpoint called with camera_info: {camera_info}")
        
        if not camera_info:
            return {"status": "error", "message": "camera_info is required"}
        
        result = capture_image_from_camera(camera_info)
        logger.info(f"Capture result: success={result.get('success')}, error={result.get('error', 'None')}")
        
        if result.get("success"):
            logger.info(f"Successfully captured image from camera {camera_info.get('id')}")
        else:
            logger.warning(f"Failed to capture from camera {camera_info.get('id')}: {result.get('error')}")
            
        return {"status": "success" if result["success"] else "error", **result}
    except Exception as e:
        logger.error(f"Error capturing image: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


@app.post("/cameras/create-config")
def create_camera_config(data: dict):
    """Create a camera configuration for LeRobot"""
    try:
        camera_info = data.get("camera_info")
        custom_settings = data.get("custom_settings", {})
        
        if not camera_info:
            return {"status": "error", "message": "camera_info is required"}
            
        config = create_camera_config_for_lerobot(camera_info, custom_settings)
        
        return {
            "status": "success",
            "camera_config": config,
            "message": "Camera configuration created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating camera config: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/cameras/config")  
def get_camera_config():
    """Get the saved camera configuration"""
    try:
        camera_config = config.get_default_camera_config()
        return {
            "status": "success",
            "camera_config": camera_config,
            "message": "Camera configuration retrieved successfully"
        }
    except Exception as e:
        logger.error(f"Error getting camera config: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/cameras/config/save")
def save_camera_config_endpoint(data: dict):
    """Save camera configuration"""
    try:
        camera_config = data.get("camera_config")
        
        if not camera_config:
            return {"status": "error", "message": "camera_config is required"}
            
        success = config.save_camera_config(camera_config)
        
        if success:
            return {
                "status": "success", 
                "message": "Camera configuration saved successfully"
            }
        else:
            return {"status": "error", "message": "Failed to save camera configuration"}
            
    except Exception as e:
        logger.error(f"Error saving camera config: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/cameras/config/update")
def update_camera_config_endpoint(data: dict):
    """Update a specific camera in the configuration"""
    try:
        camera_name = data.get("camera_name")
        camera_config = data.get("camera_config")
        
        if not camera_name or not camera_config:
            return {"status": "error", "message": "camera_name and camera_config are required"}
            
        success = config.update_camera_in_config(camera_name, camera_config)
        
        if success:
            return {
                "status": "success",
                "message": f"Camera {camera_name} updated successfully"
            }
        else:
            return {"status": "error", "message": f"Failed to update camera {camera_name}"}
            
    except Exception as e:
        logger.error(f"Error updating camera config: {e}")
        return {"status": "error", "message": str(e)}


@app.delete("/cameras/config/{camera_name}")
def remove_camera_config_endpoint(camera_name: str):
    """Remove a specific camera from the configuration"""
    try:
        success = config.remove_camera_from_config(camera_name)
        
        if success:
            return {
                "status": "success",
                "message": f"Camera {camera_name} removed successfully"
            }
        else:
            return {"status": "error", "message": f"Failed to remove camera {camera_name}"}
            
    except Exception as e:
        logger.error(f"Error removing camera config: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/cameras/stream/{camera_name}")
def stream_camera(camera_name: str):
    """Stream a specific camera feed"""
    try:
        from fastapi.responses import StreamingResponse
        import cv2
        import time
        from . import config
        
        logger.info(f"Starting camera stream for: {camera_name}")
        
        # Get camera configuration
        camera_config = config.get_saved_camera_config()
        if not camera_config or "cameras" not in camera_config:
            logger.error("No camera configuration found")
            return {"status": "error", "message": "No camera configuration found"}
            
        if camera_name not in camera_config["cameras"]:
            logger.error(f"Camera '{camera_name}' not found in configuration")
            available_cameras = list(camera_config["cameras"].keys())
            logger.info(f"Available cameras: {available_cameras}")
            return {"status": "error", "message": f"Camera '{camera_name}' not found in configuration"}
            
        camera_info = camera_config["cameras"][camera_name]
        logger.info(f"Camera config: {camera_info}")
        
        def generate_frames():
            cap = None
            try:
                # Initialize camera based on type
                if camera_info.get("type") == "opencv":
                    camera_index = camera_info.get("index_or_path", 0)
                    logger.info(f"Opening camera at index: {camera_index}")
                    
                    cap = cv2.VideoCapture(camera_index)
                    
                    if not cap.isOpened():
                        logger.error(f"Failed to open camera at index {camera_index}")
                        return
                    
                    logger.info(f"Camera opened successfully at index {camera_index}")
                    
                    # Set camera properties from config
                    width = camera_info.get("width", 640)
                    height = camera_info.get("height", 480)
                    fps = camera_info.get("fps", 30)
                    
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                    cap.set(cv2.CAP_PROP_FPS, fps)
                    
                    logger.info(f"Camera settings: {width}x{height} @ {fps}fps")
                    
                    frame_count = 0
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            logger.warning("Failed to read frame from camera")
                            break
                        
                        if frame_count % 30 == 0:  # Log every 30 frames
                            logger.info(f"Streaming frame {frame_count} for {camera_name}")
                        
                        # Encode frame as JPEG
                        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        frame_bytes = buffer.tobytes()
                        
                        # Yield frame in multipart format
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                        
                        frame_count += 1
                        
                        # Small delay to control frame rate
                        time.sleep(1.0 / fps)
                else:
                    logger.error(f"Unsupported camera type: {camera_info.get('type')}")
                    return
                            
            except Exception as e:
                logger.error(f"Error in camera stream for {camera_name}: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
            finally:
                if cap:
                    cap.release()
                    logger.info(f"Released camera {camera_name}")
        
        return StreamingResponse(
            generate_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame"
        )
        
    except Exception as e:
        logger.error(f"Error setting up camera stream for {camera_name}: {e}")
        return {"status": "error", "message": str(e)}


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources when FastAPI shuts down"""
    logger.info("🔄 FastAPI shutting down, cleaning up...")

    # Stop any active recording - handled by recording module cleanup

    # Clean up replay resources
    from .replaying import cleanup as replay_cleanup

    replay_cleanup()

    if manager:
        manager.stop_broadcast_thread()
    logger.info("✅ Cleanup completed")
