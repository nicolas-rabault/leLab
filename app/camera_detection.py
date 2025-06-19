import logging
from typing import List, Dict, Any
import traceback

logger = logging.getLogger(__name__)


def find_opencv_cameras_fallback() -> List[Dict[str, Any]]:
    """
    Find available OpenCV cameras using direct OpenCV detection.
    
    Returns:
        List of camera information dictionaries
    """
    try:
        import cv2
        
        logger.info("Searching for OpenCV cameras using direct method...")
        cameras = []
        
        # Test only first 5 indices to avoid spam
        for index in range(5):
            cap = cv2.VideoCapture(index)
            
            if cap.isOpened():
                # Get camera properties
                width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                fps = cap.get(cv2.CAP_PROP_FPS)
                backend = cap.get(cv2.CAP_PROP_BACKEND)
                
                # Give camera time to initialize (especially for built-in cameras)
                import time
                time.sleep(0.3)
                
                # Try multiple captures for built-in cameras that may need warmup
                ret, frame = None, None
                for attempt in range(3):
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.sum() > 0:  # Check if not all black
                        break
                    time.sleep(0.2)
                
                if ret and frame is not None:
                    # Capture a preview image immediately
                    import base64
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    preview_image = base64.b64encode(buffer).decode('utf-8')
                    
                    camera_info = {
                        "name": f"Camera {index}",
                        "type": "OpenCV",
                        "id": index,
                        "backend_api": get_backend_name_fallback(backend),
                        "default_stream_profile": {
                            "width": int(width) if width > 0 else 640,
                            "height": int(height) if height > 0 else 480,
                            "fps": float(fps) if fps > 0 else 30.0,
                            "format": "RGB"
                        },
                        "preview_image": preview_image  # Add preview image
                    }
                    cameras.append(camera_info)
                    logger.info(f"Found working camera at index {index} with preview")
                
                cap.release()
        
        logger.info(f"Found {len(cameras)} OpenCV cameras using direct method")
        return cameras
        
    except ImportError:
        logger.error("OpenCV not available for camera detection")
        return []
    except Exception as e:
        logger.error(f"Error in direct camera detection: {e}")
        return []


def get_backend_name_fallback(backend_id: float) -> str:
    """Convert OpenCV backend ID to readable name"""
    backend_names = {
        0: "ANY",
        200: "V4L2",
        700: "AVFOUNDATION", 
        1400: "DSHOW",
        1500: "GSTREAMER",
        1600: "FFMPEG"
    }
    return backend_names.get(int(backend_id), f"UNKNOWN_{int(backend_id)}")


def find_opencv_cameras() -> List[Dict[str, Any]]:
    """
    Find available OpenCV cameras using direct detection (avoiding LeRobot spam).
    
    Returns:
        List of camera information dictionaries
    """
    # Force use of direct detection to avoid the 60-index spam from LeRobot
    logger.info("Using direct OpenCV detection to avoid LeRobot spam...")
    return find_opencv_cameras_fallback()


def find_realsense_cameras() -> List[Dict[str, Any]]:
    """
    Find available RealSense cameras using LeRobot's camera detection.
    
    Returns:
        List of camera information dictionaries
    """
    try:
        # Check if pyrealsense2 is properly available first
        try:
            import pyrealsense2 as rs
        except ImportError:
            logger.info("pyrealsense2 not installed - skipping RealSense camera detection")
            return []
        except Exception as e:
            logger.info(f"pyrealsense2 not available: {e} - skipping RealSense camera detection")
            return []
            
        # Try to import LeRobot RealSense support
        try:
            from lerobot.common.cameras.realsense.camera_realsense import RealSenseCamera
        except ImportError:
            logger.info("LeRobot RealSense support not available - skipping RealSense camera detection")
            return []
        
        logger.info("Searching for RealSense cameras using LeRobot...")
        realsense_cameras = RealSenseCamera.find_cameras()
        
        logger.info(f"Found {len(realsense_cameras)} RealSense cameras")
        return realsense_cameras
        
    except Exception as e:
        logger.info(f"RealSense camera detection skipped: {e}")
        return []


def find_all_cameras(camera_type_filter: str = None) -> List[Dict[str, Any]]:
    """
    Find all available cameras, optionally filtered by type.
    
    Args:
        camera_type_filter: Optional filter ("opencv", "realsense", or None for all)
        
    Returns:
        List of all available cameras matching the filter
    """
    all_cameras = []
    
    if camera_type_filter is None or camera_type_filter.lower() == "opencv":
        all_cameras.extend(find_opencv_cameras())
        
    if camera_type_filter is None or camera_type_filter.lower() == "realsense":
        all_cameras.extend(find_realsense_cameras())
    
    return all_cameras


def test_camera_configuration(camera_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Test a camera configuration to ensure it works.
    
    Args:
        camera_info: Camera information dictionary from find_cameras
        
    Returns:
        Test result with success status and details
    """
    try:
        camera_type = camera_info.get("type", "").lower()
        camera_id = camera_info.get("id")
        
        if camera_type == "opencv":
            from lerobot.common.cameras.opencv.camera_opencv import OpenCVCamera
            from lerobot.common.cameras.opencv.configuration_opencv import OpenCVCameraConfig
            from lerobot.common.cameras.configs import ColorMode
            
            config = OpenCVCameraConfig(
                index_or_path=camera_id,
                color_mode=ColorMode.RGB,
            )
            camera = OpenCVCamera(config)
            
        elif camera_type == "realsense":
            from lerobot.common.cameras.realsense.camera_realsense import RealSenseCamera
            from lerobot.common.cameras.realsense.configuration_realsense import RealSenseCameraConfig
            from lerobot.common.cameras.configs import ColorMode
            
            config = RealSenseCameraConfig(
                serial_number_or_name=camera_id,
                color_mode=ColorMode.RGB,
            )
            camera = RealSenseCamera(config)
            
        else:
            return {
                "success": False,
                "error": f"Unsupported camera type: {camera_type}",
                "details": f"Camera type '{camera_type}' is not supported"
            }
        
        # Test connection
        logger.info(f"Testing {camera_type} camera: {camera_id}")
        camera.connect(warmup=False)
        
        # Try to read a frame
        frame = camera.read()
        
        # Disconnect
        camera.disconnect()
        
        return {
            "success": True,
            "message": f"Camera {camera_id} ({camera_type}) tested successfully",
            "frame_shape": frame.shape if frame is not None else None
        }
        
    except Exception as e:
        logger.error(f"Camera test failed for {camera_info}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "error": f"Camera test failed: {str(e)}",
            "details": "Camera may be in use by another application or not properly configured"
        }


def create_camera_config_for_lerobot(camera_info: Dict[str, Any], custom_settings: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Create a camera configuration dictionary suitable for LeRobot robots.
    
    Args:
        camera_info: Camera information from find_cameras
        custom_settings: Optional custom settings to override defaults
        
    Returns:
        Camera configuration dictionary for robot config
    """
    camera_type = camera_info.get("type", "").lower()
    camera_id = camera_info.get("id")
    
    # Get default stream profile
    default_profile = camera_info.get("default_stream_profile", {})
    
    if camera_type == "opencv":
        config = {
            "type": "opencv",
            "index_or_path": camera_id,
            "width": default_profile.get("width", 640),
            "height": default_profile.get("height", 480),
            "fps": default_profile.get("fps", 30),
        }
    elif camera_type == "realsense":
        config = {
            "type": "realsense", 
            "serial_number_or_name": camera_id,
            "width": default_profile.get("width", 640),
            "height": default_profile.get("height", 480),
            "fps": default_profile.get("fps", 30),
            "use_depth": False,  # Default to color only
        }
    else:
        # Fallback to opencv format
        config = {
            "type": "opencv",
            "index_or_path": camera_id,
            "width": 640,
            "height": 480,
            "fps": 30,
        }
    
    # Apply custom settings if provided
    if custom_settings:
        config.update(custom_settings)
        
    return config


def get_camera_summary() -> Dict[str, Any]:
    """
    Get a summary of all available cameras for display purposes.
    
    Returns:
        Summary dictionary with camera counts and basic info
    """
    try:
        all_cameras = find_all_cameras()
        
        opencv_count = sum(1 for cam in all_cameras if cam.get("type", "").lower() == "opencv")
        realsense_count = sum(1 for cam in all_cameras if cam.get("type", "").lower() == "realsense")
        
        return {
            "total_cameras": len(all_cameras),
            "opencv_cameras": opencv_count,
            "realsense_cameras": realsense_count,
            "cameras": all_cameras,
            "success": True
        }
        
    except Exception as e:
        logger.error(f"Error getting camera summary: {e}")
        return {
            "total_cameras": 0,
            "opencv_cameras": 0,
            "realsense_cameras": 0,
            "cameras": [],
            "success": False,
            "error": str(e)
        }


def capture_image_from_camera(camera_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Capture an image from a specific camera and return as base64.
    
    Args:
        camera_info: Camera information dictionary from find_cameras
        
    Returns:
        Result with success status and base64 image data
    """
    try:
        import cv2
        import base64
        
        camera_type = camera_info.get("type", "").lower()
        camera_id = camera_info.get("id")
        
        logger.info(f"Capturing image from {camera_type} camera: {camera_id}")
        logger.info(f"Camera info received: {camera_info}")
        
        # Validate camera_id
        if camera_id is None or camera_id == "":
            return {
                "success": False,
                "error": "Invalid camera ID",
                "details": f"Received camera_id: {camera_id}"
            }
        
        # Ensure camera_id is an integer for OpenCV
        try:
            camera_index = int(camera_id)
        except (ValueError, TypeError):
            return {
                "success": False,
                "error": f"Camera ID must be an integer, got: {camera_id}",
                "details": f"Camera info: {camera_info}"
            }
        
        # For now, use OpenCV directly since LeRobot camera modules may not be available
        if camera_type == "opencv" or True:  # Fallback to OpenCV for all cameras
            cap = cv2.VideoCapture(camera_index)
            
            if not cap.isOpened():
                return {
                    "success": False,
                    "error": f"Cannot open camera at index {camera_index}",
                    "details": "Camera may be in use by another application"
                }
            
            # Give camera time to initialize (especially for built-in cameras)
            import time
            time.sleep(0.5)
            
            # Try multiple captures for built-in cameras that may need warmup
            ret, frame = None, None
            for attempt in range(3):
                ret, frame = cap.read()
                if ret and frame is not None:
                    break
                time.sleep(0.2)
            
            cap.release()
            
            if not ret or frame is None:
                return {
                    "success": False,
                    "error": "Cannot capture frame from camera",
                    "details": "Camera opened but frame capture failed"
                }
            
            # Convert frame to JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            
            # Convert to base64
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            
            return {
                "success": True,
                "image_data": image_base64,
                "message": f"Image captured from camera {camera_index}",
                "frame_shape": frame.shape
            }
        
    except Exception as e:
        logger.error(f"Image capture failed for {camera_info}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "error": f"Image capture failed: {str(e)}",
            "details": "Unexpected error during image capture"
        }