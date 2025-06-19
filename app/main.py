from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import socketio
import os
import logging
import glob
import asyncio
from typing import List, Dict, Any
import threading
import queue
import time
from pathlib import Path
from . import config
from .webrtc_signaling import get_socketio_app

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

# Get Socket.IO app for WebRTC signaling
sio = get_socketio_app()

# Create Socket.IO ASGI app
socket_app = socketio.ASGIApp(sio, app)

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


# ============================================================================
# WEBRTC STREAM MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/webrtc/streams")
def get_active_streams():
    """Get list of all active WebRTC streams"""
    try:
        from .webrtc_signaling import active_streams, stream_buffers
        
        streams = []
        for stream_id, stream_data in active_streams.items():
            stream_copy = stream_data.copy()
            stream_copy['buffer_size'] = len(stream_buffers.get(stream_id, []))
            streams.append(stream_copy)
        
        return {"success": True, "streams": streams}
    except Exception as e:
        logger.error(f"Error getting active streams: {str(e)}")
        return {"success": False, "error": str(e)}

@app.get("/webrtc/streams/{stream_id}")
def get_stream_info(stream_id: str):
    """Get detailed information about a specific stream"""
    try:
        from .webrtc_signaling import active_streams, stream_buffers
        
        if stream_id not in active_streams:
            return {"success": False, "error": "Stream not found"}
        
        stream_info = active_streams[stream_id].copy()
        stream_info['buffer_size'] = len(stream_buffers.get(stream_id, []))
        
        # Add buffer statistics
        if stream_id in stream_buffers and stream_buffers[stream_id]:
            buffer = stream_buffers[stream_id]
            stream_info['buffer_stats'] = {
                'oldest_frame': buffer[0]['timestamp'] if buffer else None,
                'newest_frame': buffer[-1]['timestamp'] if buffer else None,
                'total_frames': len(buffer)
            }
        
        return {"success": True, "stream": stream_info}
    except Exception as e:
        logger.error(f"Error getting stream info for {stream_id}: {str(e)}")
        return {"success": False, "error": str(e)}

@app.get("/webrtc/sessions")
def get_active_sessions():
    """Get list of all active WebRTC sessions"""
    try:
        from .webrtc_signaling import active_sessions
        
        sessions = []
        for webrtc_id, session_data in active_sessions.items():
            session_copy = session_data.copy()
            # Remove sensitive client IDs from public endpoint
            session_copy.pop('desktop_client', None)
            session_copy.pop('phone_client', None)
            sessions.append(session_copy)
        
        return {"success": True, "sessions": sessions}
    except Exception as e:
        logger.error(f"Error getting active sessions: {str(e)}")
        return {"success": False, "error": str(e)}

@app.post("/webrtc/test-stream")
def create_test_stream():
    """Create a test stream for development/testing purposes"""
    try:
        import uuid
        from datetime import datetime
        from .webrtc_signaling import active_streams, stream_buffers
        
        # Generate test stream
        stream_id = str(uuid.uuid4())
        test_webrtc_id = f"test_{int(time.time())}"
        
        # Create test stream entry
        active_streams[stream_id] = {
            'stream_id': stream_id,
            'webrtc_id': test_webrtc_id,
            'created_at': datetime.now().isoformat(),
            'status': 'test_active',
            'metadata': {
                'width': 640,
                'height': 480,
                'fps': 30,
                'codec': 'h264',
                'test': True
            }
        }
        
        # Initialize with test frame data
        stream_buffers[stream_id] = [
            {
                'timestamp': time.time(),
                'data': 'test_frame_data_placeholder',
                'sequence': 0
            }
        ]
        
        logger.info(f"Created test stream: {stream_id}")
        
        return {
            "success": True, 
            "stream_id": stream_id,
            "webrtc_id": test_webrtc_id,
            "message": "Test stream created successfully"
        }
        
    except Exception as e:
        logger.error(f"Error creating test stream: {str(e)}")
        return {"success": False, "error": str(e)}

@app.delete("/webrtc/streams/{stream_id}")
def delete_stream(stream_id: str):
    """Delete a specific stream and its buffer"""
    try:
        from .webrtc_signaling import active_streams, stream_buffers
        
        if stream_id not in active_streams:
            return {"success": False, "error": "Stream not found"}
        
        # Remove stream and buffer
        del active_streams[stream_id]
        if stream_id in stream_buffers:
            del stream_buffers[stream_id]
        
        logger.info(f"Deleted stream: {stream_id}")
        return {"success": True, "message": "Stream deleted successfully"}
        
    except Exception as e:
        logger.error(f"Error deleting stream {stream_id}: {str(e)}")
        return {"success": False, "error": str(e)}


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

# Create a combined app that serves both FastAPI and Socket.IO
# The socket_app already wraps the FastAPI app, so we use it as the main app
main_app = socket_app
