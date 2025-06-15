import logging
import os
import shutil
from typing import Dict, Any, Callable
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel

# Import the main record functionality to reuse it
from lerobot.record import record, RecordConfig, DatasetRecordConfig
from lerobot.common.robots.so101_follower import SO101FollowerConfig
from lerobot.common.teleoperators.so101_leader import SO101LeaderConfig
from lerobot.common.datasets.lerobot_dataset import LeRobotDataset

# Import for patching the keyboard listener
from lerobot.common.utils import control_utils
import functools

logger = logging.getLogger(__name__)

# Import calibration paths from config (shared constants)
from .config import (
    CALIBRATION_BASE_PATH_TELEOP,
    CALIBRATION_BASE_PATH_ROBOTS,
    LEADER_CONFIG_PATH,
    FOLLOWER_CONFIG_PATH
)

# Global variables for recording state
recording_active = False
recording_thread = None
recording_events = None  # Events dict for controlling recording session
recording_config = None  # Store recording configuration
recording_start_time = None  # Track when recording started
current_episode = 1  # Track current episode number
current_phase = "preparing"  # Track current phase: "preparing", "recording", "resetting", "completed"
phase_start_time = None  # Track when current phase started


class RecordingRequest(BaseModel):
    leader_port: str
    follower_port: str
    leader_config: str
    follower_config: str
    dataset_repo_id: str
    single_task: str
    num_episodes: int = 5
    episode_time_s: int = 30
    reset_time_s: int = 10
    fps: int = 30
    video: bool = True
    push_to_hub: bool = False
    resume: bool = False


def setup_calibration_files(leader_config: str, follower_config: str):
    """Setup calibration files in the correct locations"""
    # Extract config names from file paths (remove .json extension)
    leader_config_name = os.path.splitext(leader_config)[0]
    follower_config_name = os.path.splitext(follower_config)[0]

    # Log the full paths to check if files exist
    leader_config_full_path = os.path.join(LEADER_CONFIG_PATH, leader_config)
    follower_config_full_path = os.path.join(FOLLOWER_CONFIG_PATH, follower_config)

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
        shutil.copy2(leader_config_full_path, leader_target_path)
        logger.info(f"Copied leader calibration to {leader_target_path}")

    if not os.path.exists(follower_target_path):
        shutil.copy2(follower_config_full_path, follower_target_path)
        logger.info(f"Copied follower calibration to {follower_target_path}")

    return leader_config_name, follower_config_name


def create_record_config(request: RecordingRequest) -> RecordConfig:
    """Create a RecordConfig from the recording request"""
    # Setup calibration files
    leader_config_name, follower_config_name = setup_calibration_files(
        request.leader_config, request.follower_config
    )

    # Create robot config
    robot_config = SO101FollowerConfig(
        port=request.follower_port,
        id=follower_config_name,
    )

    # Create teleop config
    teleop_config = SO101LeaderConfig(
        port=request.leader_port,
        id=leader_config_name,
    )

    # Create dataset config
    dataset_config = DatasetRecordConfig(
        repo_id=request.dataset_repo_id,
        single_task=request.single_task,
        num_episodes=request.num_episodes,
        episode_time_s=request.episode_time_s,
        reset_time_s=request.reset_time_s,
        fps=request.fps,
        video=request.video,
        push_to_hub=request.push_to_hub,
    )

    # Create the main record config
    record_config = RecordConfig(
        robot=robot_config,
        teleop=teleop_config,
        dataset=dataset_config,
        resume=request.resume,
        display_data=False,  # Don't display data in API mode
        play_sounds=False,   # Don't play sounds in API mode
    )

    return record_config


def handle_start_recording(request: RecordingRequest, websocket_manager=None) -> Dict[str, Any]:
    """Handle start recording request by using the existing record() function"""
    global recording_active, recording_thread, recording_events, recording_config, recording_start_time, current_episode

    if recording_active:
        return {"success": False, "message": "Recording is already active"}

    try:
        import time
        logger.info(f"Starting recording for dataset: {request.dataset_repo_id}")
        logger.info(f"Task: {request.single_task}")

        # Store recording configuration and reset episode counter
        recording_config = request
        recording_start_time = None  # Will be set when recording actually starts
        current_episode = 1
        current_phase = "preparing"
        phase_start_time = None

        # Initialize recording events for web control (replaces keyboard controls)
        recording_events = {
            "exit_early": False,      # Right arrow key -> "Skip to next episode" button
            "stop_recording": False,  # ESC key -> "Stop recording" button
            "rerecord_episode": False # Left arrow key -> "Re-record episode" button
        }

        # Create the record configuration
        record_config = create_record_config(request)

        # Start recording in a separate thread
        def recording_worker():
            global recording_active, recording_start_time, current_phase, phase_start_time
            recording_active = True
            recording_start_time = time.time()  # Set start time when recording actually begins
            try:
                logger.info(f"Starting recording worker with events: {recording_events}")
                # Use the original record() function but with web-controlled events
                dataset = record_with_web_events(record_config, recording_events)
                logger.info(f"Recording completed successfully. Dataset has {dataset.num_episodes} episodes")
                return {"success": True, "episodes": dataset.num_episodes}
            except Exception as e:
                logger.error(f"Error during recording: {e}")
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                return {"success": False, "error": str(e)}
            finally:
                recording_active = False
                recording_start_time = None
                current_phase = "completed"
                phase_start_time = None

        recording_thread = ThreadPoolExecutor(max_workers=1)
        future = recording_thread.submit(recording_worker)

        return {
            "success": True,
            "message": "Recording started successfully",
            "dataset_id": request.dataset_repo_id,
            "num_episodes": request.num_episodes
        }

    except Exception as e:
        recording_active = False
        logger.error(f"Failed to start recording: {e}")
        return {"success": False, "message": f"Failed to start recording: {str(e)}"}


def handle_stop_recording() -> Dict[str, Any]:
    """Handle stop recording request - replaces ESC key"""
    global recording_active, recording_thread, recording_events, current_phase, phase_start_time

    if not recording_active or recording_events is None:
        return {"success": False, "message": "No recording session is active"}

    try:
        # Trigger the stop recording event (replaces ESC key)
        recording_events["stop_recording"] = True
        recording_events["exit_early"] = True
        
        # Update phase to completed immediately
        current_phase = "completed"
        phase_start_time = None
        
        logger.info("Stop recording triggered from web interface")

        return {
            "success": True,
            "message": "Recording stop requested successfully",
        }

    except Exception as e:
        logger.error(f"Error stopping recording: {e}")
        return {"success": False, "message": f"Failed to stop recording: {str(e)}"}


def handle_exit_early() -> Dict[str, Any]:
    """Handle exit early request - replaces right arrow key"""
    global recording_events, current_phase

    if not recording_active or recording_events is None:
        return {"success": False, "message": "No recording session is active"}

    try:
        # Trigger the exit early event (replaces right arrow key)
        recording_events["exit_early"] = True
        
        logger.info(f"Exit early triggered from web interface (current phase: {current_phase})")
        logger.info(f"Recording events state: {recording_events}")

        phase_name = "recording phase" if current_phase == "recording" else "reset phase"
        return {
            "success": True,
            "message": f"Exit early triggered successfully for {phase_name}",
        }

    except Exception as e:
        logger.error(f"Error triggering exit early: {e}")
        return {"success": False, "message": f"Failed to trigger exit early: {str(e)}"}


def handle_rerecord_episode() -> Dict[str, Any]:
    """Handle rerecord episode request - replaces left arrow key"""
    global recording_events

    if not recording_active or recording_events is None:
        return {"success": False, "message": "No recording session is active"}

    try:
        # Trigger the rerecord episode event (replaces left arrow key)
        recording_events["rerecord_episode"] = True
        recording_events["exit_early"] = True
        
        logger.info("Re-record episode triggered from web interface")

        return {
            "success": True,
            "message": "Re-record episode requested successfully",
        }

    except Exception as e:
        logger.error(f"Error triggering rerecord episode: {e}")
        return {"success": False, "message": f"Failed to trigger rerecord episode: {str(e)}"}


def handle_recording_status() -> Dict[str, Any]:
    """Handle recording status request"""
    import time
    
    status = {
        "recording_active": recording_active,
        "current_phase": current_phase,  # "preparing", "recording", "resetting", "completed"
        "available_controls": {
            "stop_recording": recording_active,      # ESC key replacement
            "exit_early": recording_active,          # Right arrow key replacement
            "rerecord_episode": recording_active and current_phase == "recording"  # Only during recording phase
        },
        "message": "Recording status retrieved successfully"
    }
    
    # Add episode information if recording is active
    if recording_active and recording_config:
        status["current_episode"] = current_episode
        status["total_episodes"] = recording_config.num_episodes
        
        # Add session start time if available
        if recording_start_time:
            status["session_start_time"] = recording_start_time
            status["session_elapsed_seconds"] = int(time.time() - recording_start_time)
        
        # Add phase timing information
        if phase_start_time:
            status["phase_start_time"] = phase_start_time
            status["phase_elapsed_seconds"] = int(time.time() - phase_start_time)
            
            # Add phase time limits
            if current_phase == "recording":
                status["phase_time_limit_s"] = recording_config.episode_time_s
            elif current_phase == "resetting":
                status["phase_time_limit_s"] = recording_config.reset_time_s
    
    return status


# For backward compatibility, in case we want to add frame modifications later
def add_custom_frame_modifier(modifier_func: Callable[[Dict[str, Any]], Dict[str, Any]]):
    """Placeholder for future custom frame modifications"""
    logger.info("Custom frame modifier registered (not yet implemented in simplified version)")


def add_timestamp_modifier():
    """Placeholder for timestamp modifier"""
    logger.info("Timestamp modifier registered (not yet implemented in simplified version)")


def add_debug_info_modifier():
    """Placeholder for debug info modifier"""
    logger.info("Debug info modifier registered (not yet implemented in simplified version)")


def record_with_web_events(cfg: RecordConfig, web_events: dict) -> LeRobotDataset:
    """
    Implement recording with phase tracking - exactly mirrors original record() function behavior
    """
    import time
    from lerobot.common.utils.utils import log_say
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.common.datasets.utils import hw_to_dataset_features
    from lerobot.common.robots import make_robot_from_config
    from lerobot.common.teleoperators import make_teleoperator_from_config
    from lerobot.common.utils.control_utils import sanity_check_dataset_name, sanity_check_dataset_robot_compatibility
    from lerobot.common.policies.factory import make_policy
    from lerobot.common.datasets.image_writer import safe_stop_image_writer
    
    global current_phase, phase_start_time, current_episode
    
    # Import the record_loop function from lerobot.record
    from lerobot.record import record_loop
    
    robot = make_robot_from_config(cfg.robot)
    teleop = make_teleoperator_from_config(cfg.teleop) if cfg.teleop is not None else None

    action_features = hw_to_dataset_features(robot.action_features, "action", cfg.dataset.video)
    obs_features = hw_to_dataset_features(robot.observation_features, "observation", cfg.dataset.video)
    dataset_features = {**action_features, **obs_features}

    if cfg.resume:
        dataset = LeRobotDataset(
            cfg.dataset.repo_id,
            root=cfg.dataset.root,
        )
        if hasattr(robot, "cameras") and len(robot.cameras) > 0:
            dataset.start_image_writer(
                num_processes=cfg.dataset.num_image_writer_processes,
                num_threads=cfg.dataset.num_image_writer_threads_per_camera * len(robot.cameras),
            )
        sanity_check_dataset_robot_compatibility(dataset, robot, cfg.dataset.fps, dataset_features)
    else:
        sanity_check_dataset_name(cfg.dataset.repo_id, cfg.policy)
        dataset = LeRobotDataset.create(
            cfg.dataset.repo_id,
            cfg.dataset.fps,
            root=cfg.dataset.root,
            robot_type=robot.name,
            features=dataset_features,
            use_videos=cfg.dataset.video,
            image_writer_processes=cfg.dataset.num_image_writer_processes,
            image_writer_threads=cfg.dataset.num_image_writer_threads_per_camera * len(robot.cameras),
        )

    # Load pretrained policy
    policy = None if cfg.policy is None else make_policy(cfg.policy, ds_meta=dataset.meta)

    robot.connect()
    if teleop is not None:
        teleop.connect()

    # Start with episode 1 - this mirrors dataset.num_episodes from original
    current_episode = 1
    
    try:
        for recorded_episodes in range(cfg.dataset.num_episodes):
            # RECORDING PHASE - with dataset (matches original record.py exactly)
            current_phase = "recording"
            phase_start_time = time.time()
            logger.info(f"Starting recording phase for episode {current_episode}")
            
            log_say(f"Recording episode {current_episode}", cfg.play_sounds)
            record_loop(
                robot=robot,
                events=web_events,
                fps=cfg.dataset.fps,
                teleop=teleop,
                policy=policy,
                dataset=dataset,
                control_time_s=cfg.dataset.episode_time_s,
                single_task=cfg.dataset.single_task,
                display_data=cfg.display_data,
            )

            # Execute a few seconds without recording to give time to manually reset the environment
            # Skip reset for the last episode to be recorded (matches original exactly)
            if not web_events["stop_recording"] and (
                (recorded_episodes < cfg.dataset.num_episodes - 1) or web_events["rerecord_episode"]
            ):
                # RESET PHASE - without dataset (matches original record.py exactly)
                current_phase = "resetting"
                phase_start_time = time.time()
                logger.info(f"Starting reset phase for episode {current_episode}")
                
                log_say("Reset the environment", cfg.play_sounds)
                record_loop(
                    robot=robot,
                    events=web_events,
                    fps=cfg.dataset.fps,
                    teleop=teleop,
                    control_time_s=cfg.dataset.reset_time_s,
                    single_task=cfg.dataset.single_task,
                    display_data=cfg.display_data,
                )

            # Handle rerecord logic (matches original exactly)
            if web_events["rerecord_episode"]:
                log_say("Re-record episode", cfg.play_sounds)
                web_events["rerecord_episode"] = False
                web_events["exit_early"] = False
                dataset.clear_episode_buffer()
                continue

            # Save episode and increment (matches original exactly)
            dataset.save_episode()
            current_episode += 1

            if web_events["stop_recording"]:
                break

        # Recording completed
        current_phase = "completed"
        phase_start_time = None
        log_say("Stop recording", cfg.play_sounds, blocking=True)

    finally:
        robot.disconnect()
        if teleop:
            teleop.disconnect()

    if cfg.dataset.push_to_hub:
        dataset.push_to_hub(tags=cfg.dataset.tags, private=cfg.dataset.private)

    log_say("Exiting", cfg.play_sounds)
    return dataset 
