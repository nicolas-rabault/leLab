import logging
import os
import shutil
import select
import sys
import termios
import tty
import time
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel

from lerobot.common.teleoperators.so101_leader import SO101LeaderConfig, SO101Leader
from lerobot.common.robots.so101_follower import SO101FollowerConfig, SO101Follower
from lerobot.teleoperate import teleoperate, TeleoperateConfig

# Import calibration paths and functions from config (shared constants)
from .config import (
    CALIBRATION_BASE_PATH_TELEOP,
    CALIBRATION_BASE_PATH_ROBOTS,
    LEADER_CONFIG_PATH,
    FOLLOWER_CONFIG_PATH,
    setup_calibration_files
)

logger = logging.getLogger(__name__)

# Global variables for teleoperation state
teleoperation_active = False
teleoperation_thread = None
current_robot = None
current_teleop = None


class TeleoperateRequest(BaseModel):
    leader_port: str
    follower_port: str
    leader_config: str
    follower_config: str


def setup_keyboard():
    """Set up keyboard for non-blocking input"""
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setraw(sys.stdin.fileno())
    return old_settings


def restore_keyboard(old_settings):
    """Restore keyboard settings"""
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def check_quit_key():
    """Check if 'q' key was pressed"""
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        key = sys.stdin.read(1)
        return key.lower() == "q"
    return False


def get_joint_positions_from_robot(robot) -> Dict[str, float]:
    """
    Extract current joint positions from the robot and convert to URDF joint format.

    Args:
        robot: The robot instance (SO101Follower)

    Returns:
        Dictionary mapping URDF joint names to radian values
    """
    try:
        # Get the current observation from the robot
        observation = robot.get_observation()

        # Map robot motor names to URDF joint names
        # Based on the motor configuration in SO101Follower and URDF joint names
        motor_to_urdf_mapping = {
            "shoulder_pan": "Rotation",  # Base rotation
            "shoulder_lift": "Pitch",  # Shoulder pitch
            "elbow_flex": "Elbow",  # Elbow flexion
            "wrist_flex": "Wrist_Pitch",  # Wrist pitch
            "wrist_roll": "Wrist_Roll",  # Wrist roll
            "gripper": "Jaw",  # Gripper/jaw
        }

        joint_positions = {}

        # Extract joint positions and convert degrees to radians
        for motor_name, urdf_joint_name in motor_to_urdf_mapping.items():
            motor_key = f"{motor_name}.pos"
            if motor_key in observation:
                # Convert degrees to radians for the URDF viewer
                angle_degrees = observation[motor_key]
                angle_radians = angle_degrees * (3.14159 / 180.0)
                joint_positions[urdf_joint_name] = angle_radians
            else:
                logger.warning(f"Motor {motor_key} not found in observation")
                joint_positions[urdf_joint_name] = 0.0

        return joint_positions

    except Exception as e:
        logger.error(f"Error getting joint positions: {e}")
        return {
            "Rotation": 0.0,
            "Pitch": 0.0,
            "Elbow": 0.0,
            "Wrist_Pitch": 0.0,
            "Wrist_Roll": 0.0,
            "Jaw": 0.0,
        }



def handle_start_teleoperation(request: TeleoperateRequest, websocket_manager=None) -> Dict[str, Any]:
    """Handle start teleoperation request"""
    global teleoperation_active, teleoperation_thread, current_robot, current_teleop

    if teleoperation_active:
        return {"success": False, "message": "Teleoperation is already active"}

    try:
        logger.info(f"Starting teleoperation with leader port: {request.leader_port}, follower port: {request.follower_port}")

        # Setup calibration files
        leader_config_name, follower_config_name = setup_calibration_files(
            request.leader_config, request.follower_config
        )

        # Create robot and teleop configs
        robot_config = SO101FollowerConfig(
            port=request.follower_port,
            id=follower_config_name,
        )

        teleop_config = SO101LeaderConfig(
            port=request.leader_port,
            id=leader_config_name,
        )

        # Start teleoperation in a separate thread
        def teleoperation_worker():
            global teleoperation_active, current_robot, current_teleop
            teleoperation_active = True
            
            try:
                logger.info("Initializing robot and teleop device...")
                robot = SO101Follower(robot_config)
                teleop_device = SO101Leader(teleop_config)
                
                current_robot = robot
                current_teleop = teleop_device

                logger.info("Connecting to devices...")
                robot.bus.connect()
                teleop_device.bus.connect()

                # Write calibration to motors' memory
                logger.info("Writing calibration to motors...")
                robot.bus.write_calibration(robot.calibration)
                teleop_device.bus.write_calibration(teleop_device.calibration)

                # Connect cameras and configure motors
                logger.info("Connecting cameras and configuring motors...")
                for cam in robot.cameras.values():
                    cam.connect()
                robot.configure()
                teleop_device.configure()
                logger.info("Successfully connected to both devices")

                logger.info("Starting teleoperation loop...")
                logger.info("Press 'q' to quit teleoperation")

                # Set up keyboard for non-blocking input
                old_settings = setup_keyboard()

                try:
                    want_to_disconnect = False
                    last_broadcast_time = 0
                    broadcast_interval = 0.05  # Broadcast every 50ms (20 FPS)

                    while not want_to_disconnect and teleoperation_active:
                        # Check teleoperation_active flag first (for web stop requests)
                        if not teleoperation_active:
                            logger.info("Teleoperation stopped via web interface")
                            break
                            
                        action = teleop_device.get_action()
                        robot.send_action(action)

                        # Broadcast joint positions to connected WebSocket clients
                        current_time = time.time()
                        if current_time - last_broadcast_time >= broadcast_interval:
                            try:
                                joint_positions = get_joint_positions_from_robot(robot)
                                joint_data = {
                                    "type": "joint_update",
                                    "joints": joint_positions,
                                    "timestamp": current_time,
                                }

                                # Use websocket manager to broadcast the data
                                if websocket_manager and websocket_manager.active_connections:
                                    websocket_manager.broadcast_joint_data_sync(joint_data)

                                last_broadcast_time = current_time
                            except Exception as e:
                                logger.error(f"Error broadcasting joint data: {e}")

                        # Check for keyboard input
                        if check_quit_key():
                            want_to_disconnect = True
                            logger.info("Quit key pressed, stopping teleoperation...")
                            
                        # Small delay to prevent excessive CPU usage and allow for responsive stopping
                        time.sleep(0.001)  # 1ms delay
                finally:
                    # Always restore keyboard settings
                    restore_keyboard(old_settings)
                    robot.disconnect()
                    teleop_device.disconnect()
                    logger.info("Teleoperation stopped")

                return {"success": True, "message": "Teleoperation completed successfully"}

            except Exception as e:
                logger.error(f"Error during teleoperation: {e}")
                return {"success": False, "error": str(e)}
            finally:
                teleoperation_active = False
                current_robot = None
                current_teleop = None

        teleoperation_thread = ThreadPoolExecutor(max_workers=1)
        future = teleoperation_thread.submit(teleoperation_worker)

        return {
            "success": True,
            "message": "Teleoperation started successfully",
            "leader_port": request.leader_port,
            "follower_port": request.follower_port
        }

    except Exception as e:
        teleoperation_active = False
        logger.error(f"Failed to start teleoperation: {e}")
        return {"success": False, "message": f"Failed to start teleoperation: {str(e)}"}


def handle_stop_teleoperation() -> Dict[str, Any]:
    """Handle stop teleoperation request"""
    global teleoperation_active, teleoperation_thread, current_robot, current_teleop

    if not teleoperation_active:
        return {"success": False, "message": "No teleoperation session is active"}

    try:
        logger.info("Stop teleoperation triggered from web interface")
        
        # Stop the teleoperation flag
        teleoperation_active = False
        
        # Force cleanup of robot connections if they exist
        try:
            if current_robot:
                logger.info("Disconnecting robot...")
                current_robot.disconnect()
                
            if current_teleop:
                logger.info("Disconnecting teleop device...")
                current_teleop.disconnect()
        except Exception as cleanup_error:
            logger.warning(f"Error during device cleanup: {cleanup_error}")
        
        # Wait for the thread to finish (with timeout)
        if teleoperation_thread:
            try:
                logger.info("Waiting for teleoperation thread to finish...")
                # Give the thread a moment to finish gracefully
                import time
                time.sleep(0.5)
                
                # Shutdown the thread pool
                teleoperation_thread.shutdown(wait=True, timeout=5.0)
                logger.info("Teleoperation thread stopped")
            except Exception as thread_error:
                logger.warning(f"Error stopping teleoperation thread: {thread_error}")
        
        # Clean up global variables
        current_robot = None
        current_teleop = None
        teleoperation_thread = None
        
        logger.info("Teleoperation stopped successfully")

        return {
            "success": True,
            "message": "Teleoperation stopped successfully",
        }

    except Exception as e:
        logger.error(f"Error stopping teleoperation: {e}")
        return {"success": False, "message": f"Failed to stop teleoperation: {str(e)}"}


def handle_teleoperation_status() -> Dict[str, Any]:
    """Handle teleoperation status request"""
    return {
        "teleoperation_active": teleoperation_active,
        "available_controls": {
            "stop_teleoperation": teleoperation_active,
        },
        "message": "Teleoperation status retrieved successfully"
    }


def handle_get_joint_positions() -> Dict[str, Any]:
    """Handle get current robot joint positions request"""
    global current_robot

    if not teleoperation_active or current_robot is None:
        return {"success": False, "message": "No active teleoperation session"}

    try:
        joint_positions = get_joint_positions_from_robot(current_robot)
        return {
            "success": True,
            "joint_positions": joint_positions,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Error getting joint positions: {e}")
        return {"success": False, "message": f"Failed to get joint positions: {str(e)}"} 
