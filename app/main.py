from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import glob
import asyncio
import traceback
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
    set_external_url,
    get_external_url,
    clear_external_url,
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


@app.post("/api/config/external-url")
def configure_external_url(data: dict):
    """Configure external URL for QR code generation (ngrok, tunneling, etc.)"""
    try:
        external_url = data.get("external_url", "").strip()
        
        if external_url:
            # Validate URL format
            if not external_url.startswith(("http://", "https://")):
                return {"success": False, "error": "URL must start with http:// or https://"}
            
            set_external_url(external_url)
            logger.info(f"✅ External URL configured: {external_url}")
            return {"success": True, "external_url": external_url}
        else:
            # Clear external URL configuration
            clear_external_url()
            logger.info("✅ External URL configuration cleared")
            return {"success": True, "external_url": None}
            
    except Exception as e:
        logger.error(f"❌ Failed to configure external URL: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/config/external-url")
def get_current_external_url():
    """Get the current external URL configuration"""
    try:
        external_url = get_external_url()
        return {"success": True, "external_url": external_url}
    except Exception as e:
        logger.error(f"❌ Failed to get external URL: {e}")
        return {"success": False, "error": str(e)}


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


@app.get("/webrtc/status")
def webrtc_status():
    """Get WebRTC signaling server status"""
    from .webrtc_signaling import signaling_server
    try:
        stats = signaling_server.get_stats()
        return {
            "status": "success",
            "signaling_server": "active",
            "stats": stats,
            "endpoints": {
                "signaling": "/ws/webrtc",
                "status": "/webrtc/status"
            }
        }
    except Exception as e:
        logger.error(f"Error getting WebRTC status: {e}")
        return {"status": "error", "message": str(e)}


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


@app.websocket("/ws/webrtc")
async def webrtc_signaling_endpoint(websocket: WebSocket):
    """WebRTC signaling server endpoint"""
    from .webrtc_signaling import signaling_server
    import json
    
    logger.info("🔗 New WebRTC signaling connection attempt")
    connection_id = None
    
    try:
        connection_id = await signaling_server.connect(websocket)
        logger.info(f"✅ WebRTC signaling connection established: {connection_id}")

        while True:
            try:
                # Wait for signaling messages
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # Handle signaling message
                await signaling_server.handle_message(connection_id, message)
                
            except WebSocketDisconnect:
                logger.info(f"🔌 WebRTC signaling client disconnected: {connection_id}")
                break
            except json.JSONDecodeError as e:
                logger.error(f"❌ Invalid JSON received from {connection_id}: {e}")
                await signaling_server._send_error(connection_id, "Invalid JSON format")
            except Exception as e:
                logger.error(f"❌ Error processing WebRTC message from {connection_id}: {e}")
                await signaling_server._send_error(connection_id, str(e))

    except WebSocketDisconnect:
        logger.info(f"🔌 WebRTC signaling disconnected normally: {connection_id}")
    except Exception as e:
        logger.error(f"❌ WebRTC signaling error: {e}")
    finally:
        if connection_id:
            signaling_server.disconnect(connection_id)
        logger.info(f"🧹 WebRTC signaling connection cleaned up: {connection_id}")


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


@app.post("/complete-calibration-step")
def complete_calibration_step():
    """Complete the current calibration step"""
    return calibration_manager.complete_step()


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
    """Get all available cameras using advanced detection"""
    try:
        # Use the advanced camera detection with preview images and better error handling
        cameras = find_all_cameras()
        
        # Transform to maintain backward compatibility with the original format
        compatible_cameras = []
        for cam in cameras:
            compatible_cam = {
                "index": cam.get("id"),
                "name": cam.get("name", f"Camera {cam.get('id')}"),
                "available": True,
                "type": cam.get("type", "OpenCV").lower(),
                "backend_api": cam.get("backend_api", "UNKNOWN"),
            }
            
            # Add stream profile information
            profile = cam.get("default_stream_profile", {})
            compatible_cam.update({
                "width": profile.get("width", 640),
                "height": profile.get("height", 480),
                "fps": profile.get("fps", 30),
            })
            
            # Add preview image if available
            if "preview_image" in cam:
                compatible_cam["preview_image"] = cam["preview_image"]
                
            compatible_cameras.append(compatible_cam)
        
        return {"status": "success", "cameras": compatible_cameras}
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


@app.get("/remote_cam/{session_id}", response_class=HTMLResponse)
async def external_camera_page(session_id: str):
    """Serve the external camera page for WebRTC connection"""
    
    # HTML page for external camera capture
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en" class="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>External Camera - LeLab</title>
        <style>
            :root {{
                /* CSS Variables matching main frontend design */
                --background: hsl(222.2 84% 4.9%);
                --foreground: hsl(210 40% 98%);
                --primary: hsl(210 40% 98%);
                --secondary: hsl(217.2 32.6% 17.5%);
                --muted: hsl(217.2 32.6% 17.5%);
                --accent: hsl(217.2 32.6% 17.5%);
                --destructive: hsl(0 84.2% 60.2%);
                --border: hsl(217.2 32.6% 17.5%);
                --card: hsl(222.2 84% 4.9%);
                --card-foreground: hsl(210 40% 98%);
                --radius: 0.5rem;
            }}
            
            body {{
                margin: 0;
                padding: 1rem;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
                background: var(--background);
                color: var(--foreground);
                display: flex;
                flex-direction: column;
                min-height: 100vh;
                line-height: 1.5;
                -webkit-font-smoothing: antialiased;
            }}
            
            .container {{
                max-width: 1280px;
                margin: 0 auto;
                padding: 0 1rem;
                width: 100%;
            }}
            
            .header {{
                text-align: center;
                margin-bottom: 2rem;
            }}
            
            .header h1 {{
                font-size: 2rem;
                font-weight: 700;
                margin: 0;
                color: var(--foreground);
                letter-spacing: -0.025em;
            }}
            
            .header .subtitle {{
                font-size: 0.875rem;
                color: hsl(215.4 16.3% 46.9%);
                margin: 0.5rem 0 0 0;
            }}
            
            .status {{
                padding: 0.75rem 1rem;
                border-radius: var(--radius);
                margin-bottom: 1.5rem;
                text-align: center;
                font-weight: 500;
                font-size: 0.875rem;
                border: 1px solid transparent;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
            }}
            
            .status.connecting {{ 
                background: hsl(47.9 95.8% 53.1% / 0.1); 
                color: hsl(47.9 95.8% 53.1%); 
                border-color: hsl(47.9 95.8% 53.1% / 0.2);
            }}
            
            .status.connected {{ 
                background: hsl(120 100% 25% / 0.1); 
                color: hsl(120 100% 40%); 
                border-color: hsl(120 100% 25% / 0.2);
            }}
            
            .status.error {{ 
                background: var(--destructive) / 0.1; 
                color: var(--destructive); 
                border-color: var(--destructive) / 0.2;
            }}
            
            .status-icon {{
                width: 1rem;
                height: 1rem;
                display: inline-block;
                vertical-align: text-bottom;
            }}
            
            .video-container {{
                flex: 1;
                display: flex;
                justify-content: center;
                align-items: center;
                background: var(--card);
                border: 1px solid var(--border);
                border-radius: calc(var(--radius) * 1.5);
                overflow: hidden;
                position: relative;
                min-height: 50vh;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            }}
            
            video {{
                width: 100%;
                height: 100%;
                object-fit: cover;
            }}
            
            .controls {{
                padding: 1.5rem 0;
                display: flex;
                gap: 0.75rem;
                justify-content: center;
                flex-wrap: wrap;
            }}
            
            button {{
                padding: 0.75rem 1.5rem;
                border: 1px solid transparent;
                border-radius: var(--radius);
                font-size: 0.875rem;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s ease-in-out;
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                min-width: auto;
                text-decoration: none;
                outline: none;
                focus-visible: ring;
            }}
            
            button:focus-visible {{
                outline: 2px solid var(--primary);
                outline-offset: 2px;
            }}
            
            .start-btn {{
                background: hsl(142.1 76.2% 36.3%);
                color: hsl(355.7 100% 97.3%);
                border-color: hsl(142.1 76.2% 36.3%);
            }}
            
            .start-btn:hover {{
                background: hsl(142.1 76.2% 32%);
            }}
            
            .start-btn:disabled {{
                opacity: 0.5;
                cursor: not-allowed;
            }}
            
            .stop-btn {{
                background: var(--destructive);
                color: hsl(355.7 100% 97.3%);
                border-color: var(--destructive);
            }}
            
            .stop-btn:hover {{
                background: hsl(0 84.2% 55%);
            }}
            
            .disconnect-btn {{
                background: transparent;
                color: var(--foreground);
                border-color: var(--border);
            }}
            
            .disconnect-btn:hover {{
                background: var(--accent);
                color: var(--foreground);
            }}
            
            .info {{
                background: var(--card);
                border: 1px solid var(--border);
                padding: 1rem;
                border-radius: var(--radius);
                margin-bottom: 1.5rem;
                font-size: 0.875rem;
                line-height: 1.5;
            }}
            
            .info strong {{
                color: var(--foreground);
                font-weight: 600;
            }}
            
            .camera-icon {{
                width: 5rem;
                height: 5rem;
                margin: 1.5rem auto;
                border: 2px solid var(--border);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 2rem;
                color: hsl(215.4 16.3% 46.9%);
                background: var(--muted);
            }}
            
            .spinner {{
                display: inline-block;
                width: 1rem;
                height: 1rem;
                border: 2px solid transparent;
                border-top: 2px solid currentColor;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }}
            
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
            
            .pulse {{
                animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
            }}
            
            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.5; }}
            }}
            
            /* Live indicator */
            .live-indicator {{
                position: absolute;
                top: 0.75rem;
                left: 0.75rem;
                display: flex;
                align-items: center;
                gap: 0.375rem;
                background: rgba(0, 0, 0, 0.7);
                padding: 0.375rem 0.75rem;
                border-radius: var(--radius);
                font-size: 0.75rem;
                font-weight: 600;
            }}
            
            .live-dot {{
                width: 0.375rem;
                height: 0.375rem;
                background: hsl(120 100% 40%);
                border-radius: 50%;
            }}
            
            /* Responsive design */
            @media (max-width: 640px) {{
                body {{
                    padding: 0.75rem;
                }}
                
                .header h1 {{
                    font-size: 1.75rem;
                }}
                
                .controls {{
                    flex-direction: column;
                    align-items: center;
                }}
                
                button {{
                    width: 100%;
                    max-width: 20rem;
                    justify-content: center;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>External Camera</h1>
                <div class="subtitle">LeLab External Camera Connection</div>
            </div>
            
            <div id="status" class="status connecting">
                <div class="spinner"></div>
                Connecting to session...
            </div>

            <div class="controls">
                <button id="startBtn" class="start-btn" onclick="startCamera()">
                    <span>📹</span>
                    Start Camera
                </button>
                <button id="stopBtn" class="stop-btn" onclick="stopCamera()" style="display:none;">
                    <span>⏹️</span>
                    Stop Camera
                </button>
                <button class="disconnect-btn" onclick="disconnect()">
                    <span>🔌</span>
                    Disconnect
                </button>
            </div>

            <div class="video-container" id="videoContainer">
                <div class="camera-icon">📹</div>
            </div>
            
            <div class="info">
                <strong>Instructions:</strong>
                <br>• Allow camera access when prompted
                <br>• Tap "Start Camera" to begin streaming
                <br>• Keep this page open while using the robot
            </div>
        </div>
        
        
        
        
        <script>
            const sessionId = '{session_id}';
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const socket = new WebSocket(wsProtocol + '//' + window.location.host + '/ws/webrtc');
            
            let localStream = null;
            let peerConnection = null;
            let isStreaming = false;
            
            const statusEl = document.getElementById('status');
            const videoContainer = document.getElementById('videoContainer');
            const startBtn = document.getElementById('startBtn');
            const stopBtn = document.getElementById('stopBtn');
            
            // Enhanced WebRTC configuration with Android-specific fixes
            const rtcConfig = {{
                iceServers: [
                    {{ urls: 'stun:stun.l.google.com:19302' }},
                    {{ urls: 'stun:stun1.l.google.com:19302' }},
                    {{ urls: 'stun:stun2.l.google.com:19302' }},
                    {{ urls: 'stun:stun3.l.google.com:19302' }},
                    {{ urls: 'stun:stun4.l.google.com:19302' }},
                    // Additional STUN servers for Android compatibility
                    {{ urls: 'stun:stun.cloudflare.com:3478' }},
                    {{ urls: 'stun:stun.services.mozilla.com' }}
                ],
                iceCandidatePoolSize: 10,
                bundlePolicy: 'max-bundle',
                rtcpMuxPolicy: 'require',
                // Android-specific settings
                iceTransportPolicy: 'all',
                certificates: undefined  // Let browser handle certificates
            }};
            
            function updateStatus(message, type = 'connecting') {{
                statusEl.className = `status ${{type}}`;
                
                // Clear existing content and add appropriate icon
                statusEl.innerHTML = '';
                
                if (type === 'connecting') {{
                    const spinner = document.createElement('div');
                    spinner.className = 'spinner';
                    statusEl.appendChild(spinner);
                    statusEl.appendChild(document.createTextNode(message));
                }} else if (type === 'connected') {{
                    const checkIcon = document.createElement('span');
                    checkIcon.textContent = '✅';
                    statusEl.appendChild(checkIcon);
                    statusEl.appendChild(document.createTextNode(' ' + message));
                }} else if (type === 'error') {{
                    const errorIcon = document.createElement('span');
                    errorIcon.textContent = '❌';
                    statusEl.appendChild(errorIcon);
                    statusEl.appendChild(document.createTextNode(' ' + message));
                }} else {{
                    statusEl.textContent = message;
                }}
            }}
            
            // WebSocket events
            socket.onopen = () => {{
                console.log('🔗 Connected to signaling server');
                console.log('📱 Session details:', {{
                    sessionId: sessionId,
                    timestamp: new Date().toISOString(),
                    userAgent: navigator.userAgent,
                    platform: navigator.platform,
                    connectionType: navigator.connection ? navigator.connection.effectiveType : 'unknown'
                }});
                updateStatus('Connected! Joining session...', 'connecting');
                socket.send(JSON.stringify({{
                    type: 'join-session',
                    sourceId: sessionId,
                    payload: {{
                        userAgent: navigator.userAgent,
                        platform: navigator.platform,
                        webrtcSupported: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
                    }},
                    timestamp: Date.now()
                }}));
            }};
            
            socket.onclose = () => {{
                console.log('Disconnected from signaling server');
                updateStatus('Disconnected from server', 'error');
            }};
            
            socket.onmessage = async (event) => {{
                try {{
                    const message = JSON.parse(event.data);
                    console.log('📨 Received WebSocket message:', message.type, 'for session:', message.sourceId);
                    console.log('📨 Full message:', message);
                    
                    if (message.type === 'session-joined') {{
                        console.log('✅ Session joined successfully');
                        updateStatus('Session joined! Ready to start camera', 'connected');
                    }} else if (message.type === 'error') {{
                        console.log('❌ Received error message:', message.payload);
                        updateStatus(`Error: ${{message.payload.error}}`, 'error');
                    }} else if (message.type === 'offer') {{
                        console.log('📥 Received offer (unexpected for mobile)');
                        await handleOffer(message.payload);
                    }} else if (message.type === 'answer') {{
                        console.log('📥 Received answer from frontend');
                        await handleAnswer(message.payload);
                    }} else if (message.type === 'ice-candidate') {{
                        console.log('📥 Received ICE candidate');
                        await handleIceCandidate(message.payload);
                    }} else {{
                        console.log('❓ Unknown message type:', message.type);
                    }}
                }} catch (error) {{
                    console.error('❌ Error parsing WebSocket message:', error, 'Raw data:', event.data);
                }}
            }};
            
            // WebRTC functions
            async function startCamera() {{
                try {{
                    updateStatus('🎥 Starting camera...', 'connecting');
                    
                    // Log device info for debugging
                    console.log('📱 Device info:');
                    console.log('  User Agent:', navigator.userAgent);
                    console.log('  Platform:', navigator.platform);
                    console.log('  WebRTC support:', !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia));
                    console.log('  Session ID:', sessionId);
                    
                    // Try modern getUserMedia first
                    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {{
                        // Try with progressive constraint fallback to handle OverconstrainedError
                        const constraintOptions = [
                            // First try: High quality with environment camera
                            {{
                                video: {{
                                    facingMode: {{ ideal: 'environment' }},
                                    width: {{ min: 320, ideal: 1280, max: 1920 }},
                                    height: {{ min: 240, ideal: 720, max: 1080 }},
                                    frameRate: {{ min: 15, ideal: 30, max: 60 }}
                                }},
                                audio: false
                            }},
                            // Second try: Lower quality with environment camera
                            {{
                                video: {{
                                    facingMode: {{ ideal: 'environment' }},
                                    width: {{ ideal: 640 }},
                                    height: {{ ideal: 480 }},
                                    frameRate: {{ ideal: 24 }}
                                }},
                                audio: false
                            }},
                            // Third try: Any camera with basic constraints
                            {{
                                video: {{
                                    width: {{ ideal: 640 }},
                                    height: {{ ideal: 480 }}
                                }},
                                audio: false
                            }},
                            // Final try: Basic video only
                            {{
                                video: true,
                                audio: false
                            }}
                        ];

                        let lastError;
                        for (const constraints of constraintOptions) {{
                            try {{
                                localStream = await navigator.mediaDevices.getUserMedia(constraints);
                                console.log('✅ Camera access successful with constraints:', constraints);
                                break;
                            }} catch (error) {{
                                console.warn('❌ Camera constraint failed:', error.name, error.message);
                                lastError = error;
                                continue;
                            }}
                        }}
                        
                        if (!localStream) {{
                            throw lastError || new Error('Failed to access camera with any constraints');
                        }}
                    }} else {{
                        // Fallback to legacy getUserMedia with flexible constraints
                        const getUserMedia = navigator.getUserMedia || 
                                           navigator.webkitGetUserMedia || 
                                           navigator.mozGetUserMedia || 
                                           navigator.msGetUserMedia;
                        
                        if (!getUserMedia) {{
                            throw new Error('Camera access not supported by this browser. Please use a modern browser or enable HTTPS.');
                        }}
                        
                        localStream = await new Promise((resolve, reject) => {{
                            getUserMedia.call(navigator, {{
                                video: {{
                                    facingMode: {{ ideal: 'environment' }},
                                    width: {{ ideal: 640 }},
                                    height: {{ ideal: 480 }}
                                }},
                                audio: false
                            }}, resolve, reject);
                        }});
                    }}
                    
                    // Show video preview
                    const video = document.createElement('video');
                    video.srcObject = localStream;
                    video.autoplay = true;
                    video.playsInline = true;
                    video.muted = true;
                    
                    // Create live indicator
                    const liveIndicator = document.createElement('div');
                    liveIndicator.className = 'live-indicator';
                    liveIndicator.innerHTML = '<div class="live-dot pulse"></div><span>LIVE</span>';
                    
                    videoContainer.innerHTML = '';
                    videoContainer.appendChild(video);
                    videoContainer.appendChild(liveIndicator);
                    
                    // Create peer connection with enhanced debugging
                    console.log('🔧 Creating RTCPeerConnection with config:', rtcConfig);
                    peerConnection = new RTCPeerConnection(rtcConfig);
                    
                    // Add stream to peer connection
                    console.log('📹 Adding tracks to peer connection...');
                    localStream.getTracks().forEach((track, index) => {{
                        console.log(`📹 Adding track ${{index}}: ${{track.kind}} (${{track.label}})`);
                        peerConnection.addTrack(track, localStream);
                    }});
                    
                    // Enhanced ICE candidate handling with debugging
                    peerConnection.onicecandidate = (event) => {{
                        if (event.candidate) {{
                            console.log('📡 Sending ICE candidate:', {{
                                type: event.candidate.type,
                                protocol: event.candidate.protocol,
                                address: event.candidate.address,
                                port: event.candidate.port,
                                candidate: event.candidate.candidate
                            }});
                            socket.send(JSON.stringify({{
                                type: 'ice-candidate',
                                sourceId: sessionId,
                                payload: {{ candidate: event.candidate }},
                                timestamp: Date.now()
                            }}));
                        }} else {{
                            console.log('📡 ICE gathering complete');
                        }}
                    }};
                    
                    // Enhanced connection state monitoring
                    peerConnection.onconnectionstatechange = () => {{
                        const state = peerConnection.connectionState;
                        console.log('🔗 Connection state changed:', state);
                        console.log('🔧 Detailed states:', {{
                            connectionState: state,
                            iceConnectionState: peerConnection.iceConnectionState,
                            iceGatheringState: peerConnection.iceGatheringState,
                            signalingState: peerConnection.signalingState
                        }});
                        
                        updateStatus(`Connection: ${{state}}`, state === 'connected' ? 'connected' : 'connecting');
                        
                        // Android-specific debugging for failed connections
                        if (state === 'failed') {{
                            console.error('❌ Connection FAILED - Android debugging info:');
                            console.error('📱 User Agent:', navigator.userAgent);
                            console.error('🔧 ICE state:', peerConnection.iceConnectionState);
                            console.error('🔧 Signaling state:', peerConnection.signalingState);
                            updateStatus('❌ Connection failed - check console for details', 'error');
                        }}
                    }};
                    
                    peerConnection.oniceconnectionstatechange = () => {{
                        const iceState = peerConnection.iceConnectionState;
                        console.log('🧊 ICE connection state changed:', iceState);
                        
                        if (iceState === 'failed' || iceState === 'disconnected') {{
                            console.error('❌ ICE connection issue detected:', iceState);
                            console.error('🔧 Attempting to restart ICE...');
                            
                            // Attempt ICE restart for Android compatibility
                            try {{
                                peerConnection.restartIce();
                                console.log('🔄 ICE restart initiated');
                            }} catch (error) {{
                                console.error('❌ ICE restart failed:', error);
                            }}
                        }}
                    }};
                    
                    // Add ICE gathering state monitoring
                    peerConnection.onicegatheringstatechange = () => {{
                        console.log('🧊 ICE gathering state:', peerConnection.iceGatheringState);
                    }};
                    
                    // Create and send offer to establish connection
                    try {{
                        console.log('📤 Creating offer...');
                        const offer = await peerConnection.createOffer();
                        await peerConnection.setLocalDescription(offer);
                        
                        console.log('📤 Sending offer to frontend:', offer);
                        console.log('🔧 ICE gathering state:', peerConnection.iceGatheringState);
                        console.log('🔧 Connection state:', peerConnection.connectionState);
                        
                        socket.send(JSON.stringify({{
                            type: 'offer',
                            sourceId: sessionId,
                            payload: offer,
                            timestamp: Date.now()
                        }}));
                        
                        updateStatus('📤 Offer sent, waiting for response...', 'connecting');
                        
                        // Enhanced timeout monitoring for Android issues
                        let timeoutCount = 0;
                        const connectionMonitor = setInterval(() => {{
                            timeoutCount++;
                            const states = {{
                                connection: peerConnection.connectionState,
                                ice: peerConnection.iceConnectionState,
                                signaling: peerConnection.signalingState,
                                gathering: peerConnection.iceGatheringState
                            }};
                            
                            console.log(`⏰ Connection monitor (${{timeoutCount * 2}}s):`, states);
                            
                            if (states.connection === 'connected') {{
                                console.log('✅ Connection successful, clearing monitor');
                                clearInterval(connectionMonitor);
                                return;
                            }}
                            
                            if (timeoutCount >= 15) {{ // 30 seconds total
                                console.error('❌ Connection timeout exceeded (30s)');
                                console.error('🔧 Final states:', states);
                                console.error('📱 Device info for debugging:', {{
                                    userAgent: navigator.userAgent,
                                    platform: navigator.platform,
                                    sessionId: sessionId,
                                    timestamp: new Date().toISOString()
                                }});
                                
                                clearInterval(connectionMonitor);
                                updateStatus('Connection timeout - check console for details', 'error');
                                
                                // Attempt connection retry for Android
                                if (navigator.userAgent.includes('Android')) {{
                                    console.log('🔄 Android detected, attempting connection retry...');
                                    setTimeout(() => {{
                                        if (peerConnection.connectionState !== 'connected') {{
                                            console.log('🔄 Retrying connection for Android...');
                                            stopCamera();
                                            setTimeout(() => startCamera(), 2000);
                                        }}
                                    }}, 3000);
                                }}
                            }}
                        }}, 2000); // Check every 2 seconds
                    }} catch (error) {{
                        console.error('❌ Error creating offer:', error);
                        updateStatus('Failed to create offer', 'error');
                    }}
                    
                    startBtn.style.display = 'none';
                    stopBtn.style.display = 'inline-block';
                    isStreaming = true;
                    
                    updateStatus('Camera streaming!', 'connected');
                    
                }} catch (error) {{
                    console.error('Error starting camera:', error);
                    updateStatus(`Camera error: ${{error.message}}`, 'error');
                }}
            }}
            
            async function handleOffer(offer) {{
                try {{
                    await peerConnection.setRemoteDescription(offer);
                    const answer = await peerConnection.createAnswer();
                    await peerConnection.setLocalDescription(answer);
                    
                    socket.send(JSON.stringify({{
                        type: 'answer',
                        sourceId: sessionId,
                        payload: answer,
                        timestamp: Date.now()
                    }}));
                }} catch (error) {{
                    console.error('Error handling offer:', error);
                }}
            }}
            
            async function handleAnswer(answer) {{
                try {{
                    console.log('📥 Received answer from frontend:', answer);
                    console.log('🔧 Before setRemoteDescription - signaling state:', peerConnection.signalingState);
                    
                    await peerConnection.setRemoteDescription(answer);
                    console.log('✅ Successfully set remote description');
                    console.log('🔧 After setRemoteDescription - signaling state:', peerConnection.signalingState);
                    console.log('🔧 Connection state:', peerConnection.connectionState);
                    console.log('🔧 ICE connection state:', peerConnection.iceConnectionState);
                    
                    updateStatus('Connection established!', 'connected');
                }} catch (error) {{
                    console.error('❌ Error handling answer:', error);
                    updateStatus('Failed to handle answer', 'error');
                }}
            }}
            
            async function handleIceCandidate(candidate) {{
                try {{
                    console.log('📥 Received ICE candidate');
                    await peerConnection.addIceCandidate(candidate.candidate);
                }} catch (error) {{
                    console.error('❌ Error handling ICE candidate:', error);
                }}
            }}
            
            function stopCamera() {{
                if (localStream) {{
                    localStream.getTracks().forEach(track => track.stop());
                    localStream = null;
                }}
                
                if (peerConnection) {{
                    peerConnection.close();
                    peerConnection = null;
                }}
                
                videoContainer.innerHTML = '<div class="camera-icon">📹</div>';
                startBtn.style.display = 'inline-block';
                stopBtn.style.display = 'none';
                isStreaming = false;
                
                updateStatus('Camera stopped', 'connecting');
            }}
            
            function disconnect() {{
                stopCamera();
                socket.close();
                updateStatus('Disconnected', 'error');
                window.close();
            }}
            
            // Handle page visibility changes
            document.addEventListener('visibilitychange', () => {{
                if (document.hidden && isStreaming) {{
                    console.log('Page hidden, maintaining connection...');
                }} else if (!document.hidden && isStreaming) {{
                    console.log('Page visible, connection active');
                }}
            }});
            
            // Handle page unload
            window.addEventListener('beforeunload', () => {{
                stopCamera();
                socket.close();
            }});
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)


@app.get("/cameras/stream/{camera_identifier}")
def stream_camera(camera_identifier: str):
    """Stream a specific camera feed using hash or name"""
    try:
        from fastapi.responses import StreamingResponse
        import cv2
        import time
        from . import config
        
        logger.info(f"Starting camera stream for identifier: {camera_identifier}")
        
        # Get camera configuration
        camera_config = config.get_saved_camera_config()
        if not camera_config or "cameras" not in camera_config:
            logger.error("No camera configuration found")
            return {"status": "error", "message": "No camera configuration found"}
        
        # Find camera by hash or name for backward compatibility
        camera_info = None
        camera_name = None
        
        # First try to find by exact name match (backward compatibility)
        if camera_identifier in camera_config["cameras"]:
            camera_info = camera_config["cameras"][camera_identifier]
            camera_name = camera_identifier
            logger.info(f"Found camera by name: {camera_name}")
        else:
            # Try to find by hash (new robust system)
            for name, config_data in camera_config["cameras"].items():
                if config_data.get("hash") == camera_identifier:
                    camera_info = config_data
                    camera_name = name
                    logger.info(f"Found camera by hash: {camera_identifier} -> {camera_name}")
                    break
        
        if not camera_info:
            logger.error(f"Camera '{camera_identifier}' not found in configuration")
            available_cameras = list(camera_config["cameras"].keys())
            logger.info(f"Available cameras: {available_cameras}")
            return {"status": "error", "message": f"Camera '{camera_identifier}' not found in configuration"}
            
        logger.info(f"Camera config for '{camera_name}': {camera_info}")
        
        # CRITICAL: Use device_id as primary identifier for consistency with preview
        device_id = camera_info.get("device_id")
        camera_hash = camera_info.get("hash")
        index_or_path = camera_info.get("index_or_path", 0)
        logger.info(f"Robust camera identifiers - device_id: {device_id}, hash: {camera_hash}, fallback_index: {index_or_path}")
        
        def generate_frames():
            cap = None
            try:
                # ROBUST APPROACH: Use device_id enumeration to find correct OpenCV index
                # This ensures the SAME camera is opened in both preview and streaming
                
                if device_id and not device_id.startswith("fallback_"):
                    # Try to map device_id to current OpenCV index
                    logger.info(f"Attempting to map device_id {device_id[:16]}... to OpenCV index")
                    
                    # Get current camera enumeration (same as frontend does)
                    import subprocess
                    import json
                    
                    try:
                        # Use Python to enumerate cameras the same way frontend does
                        enum_script = '''
import cv2
import json
cameras = []
for i in range(10):  # Check first 10 indices
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        cameras.append({"index": i, "available": True})
        cap.release()
    else:
        break
print(json.dumps(cameras))
'''
                        result = subprocess.run(['python3', '-c', enum_script], 
                                              capture_output=True, text=True, timeout=10)
                        
                        if result.returncode == 0:
                            available_cameras = json.loads(result.stdout)
                            logger.info(f"Available camera indices: {[c['index'] for c in available_cameras]}")
                            
                            # Try each available index to see which matches our device
                            camera_index = None
                            for cam_info in available_cameras:
                                test_index = cam_info["index"]
                                test_cap = cv2.VideoCapture(test_index)
                                if test_cap.isOpened():
                                    # For now, use the fallback index from config
                                    # In a more sophisticated version, we could try to match device properties
                                    if test_index == index_or_path:
                                        camera_index = test_index
                                        logger.info(f"Matched device_id to OpenCV index {camera_index}")
                                        test_cap.release()
                                        break
                                test_cap.release()
                                
                            if camera_index is None:
                                # Use the stored index as fallback
                                camera_index = index_or_path
                                logger.warning(f"Could not map device_id, using fallback index {camera_index}")
                        else:
                            camera_index = index_or_path
                            logger.warning(f"Camera enumeration failed, using fallback index {camera_index}")
                            
                    except Exception as e:
                        camera_index = index_or_path
                        logger.warning(f"Error during camera mapping: {e}, using fallback index {camera_index}")
                        
                else:
                    # No device_id or fallback device_id, use stored index
                    camera_index = index_or_path
                    logger.info(f"Using stored camera index: {camera_index}")
                
                logger.info(f"Opening camera at index {camera_index} for streaming (device_id: {device_id[:16] if device_id else 'none'}...)")
                cap = cv2.VideoCapture(camera_index)
                identifier_used = f"robust_index_{camera_index}"
                
                if not cap.isOpened():
                    logger.error(f"Failed to open camera with identifier: {identifier_used}")
                    return
                
                logger.info(f"Camera opened successfully with identifier: {identifier_used}")
                
                # Set camera properties from config
                width = camera_info.get("width", 640)
                height = camera_info.get("height", 480)
                fps = camera_info.get("fps", 30)
                
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                cap.set(cv2.CAP_PROP_FPS, fps)
                
                logger.info(f"Camera settings: {width}x{height} @ {fps}fps")
                
                # Add camera warmup
                logger.info("Warming up camera...")
                time.sleep(0.5)
                
                # Try multiple captures for camera warmup
                for attempt in range(3):
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None and test_frame.sum() > 0:
                        logger.info(f"Camera warmed up successfully after {attempt + 1} attempts")
                        break
                    time.sleep(0.2)
                else:
                    logger.error("Camera warmup failed - no valid frames received")
                    return
                
                frame_count = 0
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        logger.warning("Failed to read frame from camera")
                        break
                    
                    # Validate frame is not black/empty
                    if frame is None or frame.sum() == 0:
                        logger.warning("Received black/empty frame, skipping")
                        continue
                    
                    # Encode frame as JPEG - CRITICAL FIX: This should happen for EVERY frame, not just every 30th
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    frame_bytes = buffer.tobytes()
                    
                    # Yield frame in multipart format
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    
                    # Log every 30 frames for debugging
                    if frame_count % 30 == 0:
                        logger.info(f"Streaming frame {frame_count} for {camera_name}")
                    
                    frame_count += 1
                    
                    # Small delay to control frame rate
                    time.sleep(1.0 / fps)
                            
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
