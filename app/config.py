import os
import shutil
import logging

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
