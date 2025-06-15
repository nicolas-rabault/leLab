import os

# Define the calibration config paths (shared between features)
CALIBRATION_BASE_PATH_TELEOP = os.path.expanduser(
    "~/.cache/huggingface/lerobot/calibration/teleoperators"
)
CALIBRATION_BASE_PATH_ROBOTS = os.path.expanduser(
    "~/.cache/huggingface/lerobot/calibration/robots"
)
LEADER_CONFIG_PATH = os.path.join(CALIBRATION_BASE_PATH_TELEOP, "so101_leader")
FOLLOWER_CONFIG_PATH = os.path.join(CALIBRATION_BASE_PATH_ROBOTS, "so101_follower") 
