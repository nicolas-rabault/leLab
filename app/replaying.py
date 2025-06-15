from pydantic import BaseModel
from typing import Dict, Any
import threading
import logging

logger = logging.getLogger(__name__)

# Import lerobot replay functionality directly
from lerobot.replay import replay, ReplayConfig, DatasetReplayConfig
from lerobot.common.robots import make_robot_from_config
from lerobot.common.robots.so101_follower import SO101FollowerConfig
from lerobot.common.robots.so100_follower import SO100FollowerConfig

# Import calibration setup from config
from .config import setup_follower_calibration_file

# Simple global state
replay_active = False
replay_thread = None
replay_status = {
    "replay_active": False,
    "status": "idle",
    "error_message": None,
}

class ReplayRequest(BaseModel):
    robot_type: str = "so101_follower"
    robot_port: str = "/dev/tty.usbmodem58760431541"
    robot_id: str = "my_awesome_follower_arm"
    dataset_repo_id: str
    episode: int = 0

def run_replay_directly(request: ReplayRequest):
    """Run the lerobot replay function directly"""
    global replay_active, replay_status
    
    try:
        # Debug logging for all parameters
        logger.info(f"🔍 DEBUG: Replay request received")
        logger.info(f"🔍 DEBUG: robot_type='{request.robot_type}'")
        logger.info(f"🔍 DEBUG: robot_port='{request.robot_port}'")
        logger.info(f"🔍 DEBUG: robot_id='{request.robot_id}'")
        logger.info(f"🔍 DEBUG: dataset_repo_id='{request.dataset_repo_id}'")
        logger.info(f"🔍 DEBUG: episode={request.episode}")
        
        replay_status.update({
            "replay_active": True,
            "status": "running",
            "error_message": None,
        })
        
        logger.info(f"🎬 Starting replay: {request.robot_type} on {request.robot_port}")
        logger.info(f"📁 Dataset: {request.dataset_repo_id}, Episode: {request.episode}")
        
        # Setup calibration file and get the proper config name
        logger.info(f"🔧 Setting up calibration file for robot_id: {request.robot_id}")
        try:
            follower_config_name = setup_follower_calibration_file(request.robot_id)
            logger.info(f"✅ Using follower config name: {follower_config_name}")
        except Exception as calib_error:
            logger.error(f"❌ Calibration setup failed: {calib_error}")
            raise
        
        # Create robot config based on robot type
        logger.info(f"🤖 Creating robot config for type: {request.robot_type}")
        try:
            if request.robot_type == "so101_follower":
                robot_config = SO101FollowerConfig(
                    port=request.robot_port,
                    id=follower_config_name,  # Use processed config name
                )
            elif request.robot_type == "so100_follower":
                robot_config = SO100FollowerConfig(
                    port=request.robot_port,
                    id=follower_config_name,  # Use processed config name
                )
            else:
                raise ValueError(f"Unsupported robot type: {request.robot_type}")
            logger.info(f"✅ Robot config created successfully")
        except Exception as robot_error:
            logger.error(f"❌ Robot config creation failed: {robot_error}")
            raise
        
        # Create dataset config
        logger.info(f"📊 Creating dataset config")
        try:
            dataset_config = DatasetReplayConfig(
                repo_id=request.dataset_repo_id,
                episode=request.episode,
                fps=30
            )
            logger.info(f"✅ Dataset config created successfully")
        except Exception as dataset_error:
            logger.error(f"❌ Dataset config creation failed: {dataset_error}")
            raise
        
        # Create complete replay config
        logger.info(f"⚙️ Creating complete replay config")
        try:
            cfg = ReplayConfig(
                robot=robot_config,
                dataset=dataset_config,
                play_sounds=False  # Disable sounds for web interface
            )
            logger.info(f"✅ Complete replay config created successfully")
        except Exception as config_error:
            logger.error(f"❌ Replay config creation failed: {config_error}")
            raise
        
        # Validate robot connection before replay
        logger.info(f"🔍 Validating robot connection before replay")
        try:
            # Create and test robot connection
            test_robot = make_robot_from_config(robot_config)
            logger.info(f"🤖 Robot created, attempting connection...")
            logger.info(f"🔍 Robot config - Port: {robot_config.port}, ID: {robot_config.id}")
            
            test_robot.connect()
            logger.info(f"✅ Robot connected successfully")
            logger.info(f"🔍 Robot bus info: {type(test_robot.bus).__name__}")
            
            # Check if robot has motors configured
            if hasattr(test_robot, 'bus') and hasattr(test_robot.bus, 'models'):
                if not test_robot.bus.models:
                    logger.error(f"❌ No motors detected on robot bus")
                    raise ValueError("No motors detected on robot bus. Check robot connection and calibration.")
                else:
                    logger.info(f"✅ Robot has {len(test_robot.bus.models)} motors configured")
            
            # Test a simple motor operation to ensure they're working
            try:
                # Try to read current positions to verify motors are responsive
                test_robot.bus.read("Present_Position")
                logger.info(f"✅ Motors are responsive")
            except Exception as motor_test_error:
                logger.error(f"❌ Motors not responsive: {motor_test_error}")
                raise ValueError(f"Motors not responsive: {motor_test_error}")
            
            # Disconnect test connection
            test_robot.disconnect()
            logger.info(f"✅ Robot validation completed successfully")
            
        except ValueError as ve:
            # Re-raise ValueError with original message
            raise ve
        except Exception as validation_error:
            logger.error(f"❌ Robot validation failed: {validation_error}")
            # Provide more specific error message for common issues
            error_msg = str(validation_error)
            if "No such file or directory" in error_msg or "Permission denied" in error_msg:
                raise ValueError(f"Robot port '{request.robot_port}' is not accessible. Check USB connection and permissions.")
            elif "models" in error_msg.lower() or "motor" in error_msg.lower():
                raise ValueError(f"Motor configuration error: {validation_error}")
            else:
                raise ValueError(f"Robot validation failed: {validation_error}")

        # Run the replay directly
        logger.info(f"🚀 Starting lerobot replay function")
        try:
            replay(cfg)
            logger.info(f"✅ Lerobot replay function completed successfully")
        except StopIteration as stop_error:
            logger.error(f"❌ StopIteration error during replay - no motors detected")
            raise ValueError("No motors detected during replay. The robot may have been disconnected or the motors are not properly configured. Please check your robot hardware setup and calibration files.")
        except Exception as replay_error:
            logger.error(f"❌ Lerobot replay function failed: {replay_error}")
            raise
        
        replay_status.update({
            "status": "completed",
            "replay_active": False
        })
        logger.info("✅ Replay completed successfully")
        
    except Exception as e:
        import traceback
        error_msg = str(e)
        full_traceback = traceback.format_exc()
        
        # Enhanced error logging
        logger.error(f"❌ Replay failed with exception type: {type(e).__name__}")
        logger.error(f"❌ Replay error message: '{error_msg}'")
        logger.error(f"❌ Full traceback:\n{full_traceback}")
        
        # Use more descriptive error message if original is empty
        if not error_msg or error_msg.strip() == "":
            error_msg = f"Unknown error of type {type(e).__name__}"
        
        replay_status.update({
            "status": "error",
            "replay_active": False,
            "error_message": error_msg
        })
    finally:
        replay_active = False

def handle_start_replay(request: ReplayRequest) -> Dict[str, Any]:
    """Handle starting a replay session"""
    global replay_thread, replay_active
    
    if replay_active:
        return {
            "success": False,
            "message": "Replay is already active"
        }
    
    try:
        replay_active = True
        replay_thread = threading.Thread(
            target=run_replay_directly,
            args=(request,),
            daemon=True
        )
        replay_thread.start()
        
        return {
            "success": True,
            "message": "Replay started successfully"
        }
        
    except Exception as e:
        replay_active = False
        logger.error(f"❌ Failed to start replay: {e}")
        return {
            "success": False,
            "message": str(e)
        }

def handle_stop_replay() -> Dict[str, Any]:
    """Handle stopping the current replay session"""
    global replay_active
    
    if not replay_active:
        return {
            "success": False,
            "message": "No active replay session"
        }
    
    # Note: The lerobot replay function doesn't have a built-in stop mechanism
    # since it's designed to run to completion. We can only stop between episodes.
    replay_active = False
    replay_status.update({
        "replay_active": False,
        "status": "stopped"
    })
    
    return {
        "success": True,
        "message": "Replay stop requested (will complete current episode)"
    }

def handle_replay_status() -> Dict[str, Any]:
    """Handle getting the current replay status"""
    return {
        "success": True,
        "status": replay_status.copy()
    }

def handle_replay_logs() -> Dict[str, Any]:
    """Handle getting recent replay logs"""
    return {
        "success": True,
        "logs": []  # Logs are handled by lerobot's logging system
    }

def cleanup():
    """Clean up replay resources"""
    global replay_active
    replay_active = False 
