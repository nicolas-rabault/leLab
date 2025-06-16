import os
import shutil
import logging
import platform
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Define the calibration config paths (shared between features)
CALIBRATION_BASE_PATH_TELEOP = os.path.expanduser(
    "~/.cache/huggingface/lerobot/calibration/teleoperators"
)
CALIBRATION_BASE_PATH_ROBOTS = os.path.expanduser(
    "~/.cache/huggingface/lerobot/calibration/robots"
)
LEADER_CONFIG_PATH = os.path.join(CALIBRATION_BASE_PATH_TELEOP, "so101_leader")
FOLLOWER_CONFIG_PATH = os.path.join(CALIBRATION_BASE_PATH_ROBOTS, "so101_follower") 

# Define port storage path
PORT_CONFIG_PATH = os.path.expanduser("~/.cache/huggingface/lerobot/ports")
LEADER_PORT_FILE = os.path.join(PORT_CONFIG_PATH, "leader_port.txt")
FOLLOWER_PORT_FILE = os.path.join(PORT_CONFIG_PATH, "follower_port.txt")

# Define configuration storage path
CONFIG_STORAGE_PATH = os.path.expanduser("~/.cache/huggingface/lerobot/saved_configs")
LEADER_CONFIG_FILE = os.path.join(CONFIG_STORAGE_PATH, "leader_config.txt")
FOLLOWER_CONFIG_FILE = os.path.join(CONFIG_STORAGE_PATH, "follower_config.txt")

def setup_calibration_files(leader_config: str, follower_config: str):
    """Setup calibration files in the correct locations for teleoperation and recording"""
    # Extract config names from file paths (remove .json extension)
    leader_config_name = os.path.splitext(leader_config)[0]
    follower_config_name = os.path.splitext(follower_config)[0]

    # Log the full paths to check if files exist
    leader_config_full_path = os.path.join(LEADER_CONFIG_PATH, leader_config)
    follower_config_full_path = os.path.join(FOLLOWER_CONFIG_PATH, follower_config)

    logger.info(f"Checking calibration files:")
    logger.info(f"Leader config path: {leader_config_full_path}")
    logger.info(f"Follower config path: {follower_config_full_path}")
    logger.info(f"Leader config exists: {os.path.exists(leader_config_full_path)}")
    logger.info(f"Follower config exists: {os.path.exists(follower_config_full_path)}")

    # Create calibration directories if they don't exist
    leader_calibration_dir = os.path.join(CALIBRATION_BASE_PATH_TELEOP, "so101_leader")
    follower_calibration_dir = os.path.join(CALIBRATION_BASE_PATH_ROBOTS, "so101_follower")
    os.makedirs(leader_calibration_dir, exist_ok=True)
    os.makedirs(follower_calibration_dir, exist_ok=True)

    # Copy calibration files to the correct locations if they're not already there
    leader_target_path = os.path.join(leader_calibration_dir, f"{leader_config_name}.json")
    follower_target_path = os.path.join(follower_calibration_dir, f"{follower_config_name}.json")

    if not os.path.exists(leader_target_path):
        if os.path.exists(leader_config_full_path):
            shutil.copy2(leader_config_full_path, leader_target_path)
            logger.info(f"Copied leader calibration to {leader_target_path}")
        else:
            raise FileNotFoundError(f"Leader calibration file not found: {leader_config_full_path}")
    else:
        logger.info(f"Leader calibration already exists at {leader_target_path}")

    if not os.path.exists(follower_target_path):
        if os.path.exists(follower_config_full_path):
            shutil.copy2(follower_config_full_path, follower_target_path)
            logger.info(f"Copied follower calibration to {follower_target_path}")
        else:
            raise FileNotFoundError(f"Follower calibration file not found: {follower_config_full_path}")
    else:
        logger.info(f"Follower calibration already exists at {follower_target_path}")

    return leader_config_name, follower_config_name


def setup_follower_calibration_file(follower_config: str):
    """Setup follower calibration file in the correct location for replay functionality"""
    # Extract config name from file path (remove .json extension)
    follower_config_name = os.path.splitext(follower_config)[0]

    # Log the full path to check if file exists
    follower_config_full_path = os.path.join(FOLLOWER_CONFIG_PATH, follower_config)

    logger.info(f"Checking follower calibration file:")
    logger.info(f"Follower config path: {follower_config_full_path}")
    logger.info(f"Follower config exists: {os.path.exists(follower_config_full_path)}")

    # Create calibration directory if it doesn't exist
    follower_calibration_dir = os.path.join(CALIBRATION_BASE_PATH_ROBOTS, "so101_follower")
    os.makedirs(follower_calibration_dir, exist_ok=True)

    # Copy calibration file to the correct location if it's not already there
    follower_target_path = os.path.join(follower_calibration_dir, f"{follower_config_name}.json")

    if not os.path.exists(follower_target_path):
        if os.path.exists(follower_config_full_path):
            shutil.copy2(follower_config_full_path, follower_target_path)
            logger.info(f"Copied follower calibration to {follower_target_path}")
        else:
            raise FileNotFoundError(f"Follower calibration file not found: {follower_config_full_path}")
    else:
        logger.info(f"Follower calibration already exists at {follower_target_path}")

    return follower_config_name


def find_available_ports():
    """Find all available serial ports on the system"""
    try:
        from serial.tools import list_ports  # Part of pyserial library
    except ImportError:
        raise ImportError("pyserial library is required. Install it with: pip install pyserial")

    if platform.system() == "Windows":
        # List COM ports using pyserial
        ports = [port.device for port in list_ports.comports()]
    else:  # Linux/macOS
        # List /dev/tty* ports for Unix-based systems
        ports = [str(path) for path in Path("/dev").glob("tty*")]
    return sorted(ports)


def find_robot_port(robot_type="robot"):
    """
    Find the port for a robot by detecting the difference when disconnecting/reconnecting
    
    Args:
        robot_type (str): Type of robot ("leader" or "follower" or generic "robot")
    
    Returns:
        str: The detected port
    """
    logger.info(f"Finding port for {robot_type}")
    
    # Get initial ports
    ports_before = find_available_ports()
    logger.info(f"Ports before disconnecting: {ports_before}")
    
    # This function returns the port detection logic, but the actual user interaction
    # should be handled by the frontend
    return {
        "ports_before": ports_before,
        "robot_type": robot_type
    }


def detect_port_after_disconnect(ports_before):
    """
    Detect the port after disconnection by comparing with ports before
    
    Args:
        ports_before (list): List of ports before disconnection
    
    Returns:
        str: The detected port
    """
    time.sleep(0.5)  # Allow some time for port to be released
    ports_after = find_available_ports()
    ports_diff = list(set(ports_before) - set(ports_after))
    
    logger.info(f"Ports after disconnecting: {ports_after}")
    logger.info(f"Port difference: {ports_diff}")
    
    if len(ports_diff) == 1:
        port = ports_diff[0]
        logger.info(f"Detected port: {port}")
        return port
    elif len(ports_diff) == 0:
        raise OSError("Could not detect the port. No difference was found.")
    else:
        raise OSError(f"Could not detect the port. More than one port was found ({ports_diff}).")


def save_robot_port(robot_type, port):
    """
    Save the robot port to a file for future use
    
    Args:
        robot_type (str): "leader" or "follower"
        port (str): The port to save
    """
    # Create port config directory if it doesn't exist
    os.makedirs(PORT_CONFIG_PATH, exist_ok=True)
    
    port_file = LEADER_PORT_FILE if robot_type == "leader" else FOLLOWER_PORT_FILE
    
    with open(port_file, 'w') as f:
        f.write(port)
    
    logger.info(f"Saved {robot_type} port: {port}")


def get_saved_robot_port(robot_type):
    """
    Get the saved robot port from file
    
    Args:
        robot_type (str): "leader" or "follower"
    
    Returns:
        str or None: The saved port, or None if not found
    """
    port_file = LEADER_PORT_FILE if robot_type == "leader" else FOLLOWER_PORT_FILE
    
    if os.path.exists(port_file):
        with open(port_file, 'r') as f:
            port = f.read().strip()
            logger.info(f"Retrieved saved {robot_type} port: {port}")
            return port
    
    logger.info(f"No saved port found for {robot_type}")
    return None


def get_default_robot_port(robot_type):
    """
    Get the default port for a robot, checking saved ports first
    
    Args:
        robot_type (str): "leader" or "follower"
    
    Returns:
        str: The default port to use
    """
    saved_port = get_saved_robot_port(robot_type)
    if saved_port:
        return saved_port
    
    # Fallback to common default ports
    if platform.system() == "Windows":
        return "COM3"  # Common Windows default
    else:
        return "/dev/ttyUSB0"  # Common Linux/macOS default


def save_robot_config(robot_type: str, config_name: str):
    """Save the robot configuration to a file for future use"""
    try:
        # Create the config storage directory if it doesn't exist
        os.makedirs(CONFIG_STORAGE_PATH, exist_ok=True)
        
        # Determine the config file path
        if robot_type.lower() == "leader":
            config_file_path = LEADER_CONFIG_FILE
        elif robot_type.lower() == "follower":
            config_file_path = FOLLOWER_CONFIG_FILE
        else:
            logger.error(f"Unknown robot type: {robot_type}")
            return False
            
        # Write the config name to file
        with open(config_file_path, 'w') as f:
            f.write(config_name.strip())
            
        logger.info(f"Saved {robot_type} configuration: {config_name}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving {robot_type} configuration: {e}")
        return False


def get_saved_robot_config(robot_type: str):
    """Get the saved robot configuration from file"""
    try:
        # Determine the config file path
        if robot_type.lower() == "leader":
            config_file_path = LEADER_CONFIG_FILE
        elif robot_type.lower() == "follower":
            config_file_path = FOLLOWER_CONFIG_FILE
        else:
            logger.error(f"Unknown robot type: {robot_type}")
            return None
            
        # Read the config name from file
        if os.path.exists(config_file_path):
            with open(config_file_path, 'r') as f:
                config_name = f.read().strip()
                if config_name:
                    logger.info(f"Found saved {robot_type} configuration: {config_name}")
                    return config_name
                    
        logger.info(f"No saved {robot_type} configuration found")
        return None
        
    except Exception as e:
        logger.error(f"Error reading saved {robot_type} configuration: {e}")
        return None


def get_default_robot_config(robot_type: str, available_configs: list):
    """Get the default configuration for a robot, checking saved configs first"""
    saved_config = get_saved_robot_config(robot_type)
    if saved_config and saved_config in available_configs:
        return saved_config
    
    # Return first available config as fallback
    if available_configs:
        return available_configs[0]
    
    return None
