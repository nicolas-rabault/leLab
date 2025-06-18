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
    FOLLOWER_CONFIG_PATH,
    setup_calibration_files
)

# Global variables for recording state
recording_active = False
recording_thread = None
recording_events = None  # Events dict for controlling recording session
recording_config = None  # Store recording configuration
recording_start_time = None  # Track when recording started
current_episode = 1  # Track current episode number
saved_episodes = 0  # Track how many episodes have been saved
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
    cameras: dict = {}
    test_mode: bool = False  # Skip robot connection for testing


class UploadRequest(BaseModel):
    dataset_repo_id: str
    tags: list[str] = []
    private: bool = False


class DatasetInfoRequest(BaseModel):
    dataset_repo_id: str




def create_record_config(request: RecordingRequest) -> RecordConfig:
    """Create a RecordConfig from the recording request"""
    from lerobot.common.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    
    # Setup calibration files
    leader_config_name, follower_config_name = setup_calibration_files(
        request.leader_config, request.follower_config
    )

    # 🔧 CAMERA CONFIG CONVERSION: Convert frontend camera dict to proper CameraConfig objects
    camera_configs = {}
    for camera_name, camera_data in request.cameras.items():
        if camera_data.get("type") == "opencv":
            # Convert frontend format to OpenCVCameraConfig
            camera_configs[camera_name] = OpenCVCameraConfig(
                index_or_path=camera_data.get("camera_index", 0),
                fps=camera_data.get("fps"),
                width=camera_data.get("width"),
                height=camera_data.get("height"),
            )
            logger.info(f"✅ CAMERA CONFIG: Converted {camera_name} -> OpenCVCameraConfig(index={camera_data.get('camera_index')}, {camera_data.get('width')}x{camera_data.get('height')}@{camera_data.get('fps')}fps)")
        else:
            logger.warning(f"⚠️ CAMERA CONFIG: Unsupported camera type '{camera_data.get('type')}' for {camera_name}")

    # Create robot config
    robot_config = SO101FollowerConfig(
        port=request.follower_port,
        id=follower_config_name,
        cameras=camera_configs,
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
    global recording_active, recording_thread, recording_events, recording_config, recording_start_time, current_episode, saved_episodes, current_phase, phase_start_time

    if recording_active:
        return {"success": False, "message": "Recording is already active"}

    # 🧹 CLEANUP: Reset all global state from previous sessions
    logger.info("🧹 CLEANUP: Resetting all recording state variables")
    recording_active = False
    recording_thread = None
    recording_events = None
    recording_config = None
    recording_start_time = None
    current_episode = 1
    saved_episodes = 0
    current_phase = "preparing"
    phase_start_time = None

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
            global recording_active, recording_start_time, current_phase, phase_start_time, current_episode, saved_episodes
            recording_active = True
            recording_start_time = time.time()  # Set start time when recording actually begins
            
            # Initialize episode counters
            current_episode = 1
            saved_episodes = 0
            
            try:
                logger.info(f"Starting recording worker with events: {recording_events}")
                print(f"🚀 STATUS CHANGE: Recording session started for dataset '{request.dataset_repo_id}'")
                print(f"📋 STATUS CHANGE: Task: '{request.single_task}' - {request.num_episodes} episodes planned")
                
                # 🔓 CRITICAL: Wait for camera streams to be fully released by frontend
                if request.cameras:
                    logger.info(f"🔓 BACKEND: Waiting for camera resources to be released (cameras configured: {list(request.cameras.keys())})")
                    print(f"🔓 STATUS CHANGE: Waiting for camera resources to be released...")
                    time.sleep(2.0)  # Give cameras more time to be fully released
                    logger.info(f"✅ BACKEND: Camera wait period complete, proceeding with robot initialization")
                
                # Use the original record() function but with web-controlled events
                dataset = record_with_web_events(record_config, recording_events)
                logger.info(f"Recording completed successfully. Dataset has {dataset.num_episodes} episodes")
                print(f"🎉 STATUS CHANGE: Recording session completed successfully with {dataset.num_episodes} episodes")
                return {"success": True, "episodes": dataset.num_episodes}
            except Exception as e:
                logger.error(f"❌ CRITICAL ERROR during recording: {e}")
                print(f"❌ STATUS CHANGE: Recording session failed with error: {str(e)}")
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                
                # 🚨 CRITICAL: Set phase to "error" instead of "completed" to distinguish failures
                current_phase = "error"
                recording_active = False
                recording_start_time = None
                phase_start_time = None
                
                return {"success": False, "error": str(e)}
            finally:
                # Only set to completed if no error occurred
                if current_phase != "error":
                    current_phase = "completed"
                    
                recording_active = False
                recording_start_time = None
                phase_start_time = None
                current_episode = 1  # Reset for next session
                saved_episodes = 0  # Reset for next session
                logger.info("🔚 RECORDING SESSION: Setting state to completed - frontend should stop polling")
                print(f"🔚 STATUS CHANGE: Recording session ended")

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
        
        # Update phase to indicate stopping
        current_phase = "stopping"
        phase_start_time = None
        
        logger.info("Stop recording triggered from web interface")
        print("🛑 STATUS CHANGE: Stop recording requested - session will end soon")

        return {
            "success": True,
            "message": "Recording stop requested successfully",
            "session_ending": True  # Signal that session is ending
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
        # Log the current state before setting the flag
        logger.info(f"Exit early requested - Current phase: {current_phase}")
        logger.info(f"Events before setting exit_early: {recording_events}")
        
        # Trigger the exit early event (replaces right arrow key)
        recording_events["exit_early"] = True
        # Also set our tracking flag that won't be reset by record_loop
        recording_events["_exit_early_triggered"] = True
        
        # Log the state after setting the flag
        logger.info(f"Exit early flag set - Events after: {recording_events}")
        logger.info(f"Exit early triggered from web interface (current phase: {current_phase})")

        phase_name = "recording phase" if current_phase == "recording" else "reset phase"
        return {
            "success": True,
            "message": f"Exit early triggered successfully for {phase_name}",
            "current_phase": current_phase,
            "events_state": dict(recording_events)  # Include events state in response
        }

    except Exception as e:
        logger.error(f"Error triggering exit early: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return {"success": False, "message": f"Failed to trigger exit early: {str(e)}"}


def handle_rerecord_episode() -> Dict[str, Any]:
    """Handle rerecord episode request - replaces left arrow key"""
    global recording_events

    if not recording_active or recording_events is None:
        return {"success": False, "message": "No recording session is active"}

    try:
        # Log the current state before setting the flags
        logger.info(f"Re-record episode requested - Events before: {recording_events}")
        
        # Trigger the rerecord episode event (replaces left arrow key)
        recording_events["rerecord_episode"] = True
        recording_events["exit_early"] = True  # Also need to exit current loop
        
        # Log the state after setting the flags
        logger.info(f"Re-record flags set - Events after: {recording_events}")
        logger.info("Re-record episode triggered from web interface")

        return {
            "success": True,
            "message": "Re-record episode requested successfully",
            "events_state": dict(recording_events)  # Include events state in response
        }

    except Exception as e:
        logger.error(f"Error triggering rerecord episode: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return {"success": False, "message": f"Failed to trigger rerecord episode: {str(e)}"}


def handle_recording_status() -> Dict[str, Any]:
    """Handle recording status request"""
    import time
    
    # If recording is not active and phase is completed or error, indicate session has ended
    session_ended = not recording_active and current_phase in ["completed", "error"]
    
    # Log when session has ended to help debug frontend polling
    if session_ended:
        if current_phase == "error":
            logger.info("📡 RECORDING STATUS REQUEST: Session failed with error - frontend should stop polling")
            print("📡 STATUS CHANGE: Frontend is still polling after session error - should stop now")
        else:
            logger.info("📡 RECORDING STATUS REQUEST: Session has ended - frontend should stop polling")
            print("📡 STATUS CHANGE: Frontend is still polling after session end - should stop now")
    
    status = {
        "recording_active": recording_active,
        "current_phase": current_phase,  # "preparing", "recording", "resetting", "completed"
        "session_ended": session_ended,  # New field to indicate session completion
        "available_controls": {
            "stop_recording": recording_active,      # ESC key replacement
            "exit_early": recording_active,          # Right arrow key replacement
            "rerecord_episode": recording_active and current_phase == "recording"  # Only during recording phase
        },
        "message": "Recording session failed with error - check logs" if current_phase == "error" else ("Recording session has ended - stop polling" if session_ended else "Recording status retrieved successfully")
    }
    
    # Add episode information if recording is active
    if recording_active and recording_config:
        status["current_episode"] = current_episode
        status["total_episodes"] = recording_config.num_episodes
        status["saved_episodes"] = saved_episodes  # Track completed episodes
        
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


def handle_get_dataset_info(request: DatasetInfoRequest) -> Dict[str, Any]:
    """Get information about a saved dataset"""
    try:
        # Import LeRobotDataset to load the dataset
        from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
        import time
        
        logger.info(f"Loading dataset {request.dataset_repo_id} to get info")
        
        # Load the dataset from local storage
        dataset = LeRobotDataset(request.dataset_repo_id)
        
        logger.info(f"Dataset loaded with {dataset.num_episodes} episodes")
        
        # Get dataset metadata
        dataset_info = {
            "success": True,
            "dataset_repo_id": request.dataset_repo_id,
            "num_episodes": dataset.num_episodes,
            "single_task": getattr(dataset.meta, 'single_task', 'Unknown task'),
            "fps": dataset.fps,
            "features": list(dataset.features.keys()),
            "total_frames": dataset.total_frames,
            "robot_type": getattr(dataset.meta, 'robot_type', 'Unknown robot'),
        }
        
        # Try to get task information from the first episode if available
        if dataset.num_episodes > 0:
            try:
                first_episode = dataset[0]
                if 'task' in first_episode:
                    dataset_info["single_task"] = first_episode['task'][0] if len(first_episode['task']) > 0 else dataset_info["single_task"]
            except Exception as e:
                logger.warning(f"Could not extract task from first episode: {e}")
        
        logger.info(f"Dataset info retrieved: {dataset_info}")
        return dataset_info
        
    except Exception as e:
        logger.error(f"Error loading dataset {request.dataset_repo_id}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "message": f"Failed to load dataset: {str(e)}"
        }


def handle_upload_dataset(request: UploadRequest) -> Dict[str, Any]:
    """Handle dataset upload to HuggingFace Hub"""
    try:
        # Import LeRobotDataset to load and upload the dataset
        from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
        
        logger.info(f"Loading dataset {request.dataset_repo_id} for upload")
        
        # Load the dataset from local storage
        dataset = LeRobotDataset(request.dataset_repo_id)
        
        logger.info(f"Dataset loaded with {dataset.num_episodes} episodes")
        logger.info(f"Uploading to HuggingFace Hub with tags: {request.tags}, private: {request.private}")
        
        # Upload dataset to HuggingFace Hub
        dataset.push_to_hub(
            tags=request.tags,
            private=request.private
        )
        
        logger.info(f"Dataset {request.dataset_repo_id} uploaded successfully to HuggingFace Hub")
        
        return {
            "success": True,
            "message": f"Dataset {request.dataset_repo_id} uploaded successfully to HuggingFace Hub",
            "dataset_url": f"https://huggingface.co/datasets/{request.dataset_repo_id}",
            "num_episodes": dataset.num_episodes
        }
        
    except Exception as e:
        logger.error(f"Error uploading dataset {request.dataset_repo_id}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "message": f"Failed to upload dataset: {str(e)}"
        }


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
    
    global current_phase, phase_start_time, current_episode, saved_episodes
    
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

    # 🔧 ROBOT CONNECTION: Connect with enhanced error handling for camera conflicts
    try:
        logger.info("🔧 ROBOT CONNECTION: Attempting to connect robot...")
        robot.connect()
        logger.info("✅ ROBOT CONNECTION: Robot connected successfully")
    except Exception as e:
        logger.error(f"❌ ROBOT CONNECTION: Failed to connect robot: {e}")
        # If robot connection fails due to camera conflict, provide clear error
        if "camera" in str(e).lower() or "device" in str(e).lower() or "busy" in str(e).lower():
            logger.error("💡 ROBOT CONNECTION: Camera connection failure - likely camera resource conflict")
            logger.error("💡 ROBOT CONNECTION: Make sure frontend camera streams are released before recording")
        raise
    
    if teleop is not None:
        try:
            logger.info("🔧 TELEOP CONNECTION: Attempting to connect teleoperator...")
            teleop.connect()
            logger.info("✅ TELEOP CONNECTION: Teleoperator connected successfully")
        except Exception as e:
            logger.error(f"❌ TELEOP CONNECTION: Failed to connect teleoperator: {e}")
            raise
    
    # Ensure calibration is properly loaded and applied to the devices
    logger.info(f"Applying calibration to devices")
    
    # Write calibration to motors' memory (similar to teleoperation code)
    if hasattr(robot, 'bus') and robot.calibration is not None:
        try:
            logger.info(f"Writing robot calibration to motors...")
            robot.bus.write_calibration(robot.calibration)
            logger.info(f"Robot calibration applied successfully")
        except Exception as e:
            logger.error(f"Error writing robot calibration: {e}")
    else:
        logger.warning(f"Robot bus or calibration not available - calibration may not be applied")
        
    if teleop is not None and hasattr(teleop, 'bus') and teleop.calibration is not None:
        try:
            logger.info(f"Writing teleop calibration to motors...")
            teleop.bus.write_calibration(teleop.calibration)
            logger.info(f"Teleop calibration applied successfully")
        except Exception as e:
            logger.error(f"Error writing teleop calibration: {e}")
    else:
        logger.warning(f"Teleop bus or calibration not available - calibration may not be applied")

    # Start with episode 1 - but track it properly
    current_episode = 1
    saved_episodes = 0  # Track how many episodes we've actually saved
    
    try:
        while saved_episodes < cfg.dataset.num_episodes:
            # RECORDING PHASE - with dataset (matches original record.py exactly)
            current_phase = "recording"
            phase_start_time = time.time()
            logger.info(f"Starting recording phase for episode {current_episode}")
            logger.info(f"Events state at start of recording phase: {web_events}")
            print(f"🎬 STATUS CHANGE: Starting recording phase for episode {current_episode}/{cfg.dataset.num_episodes}")
            
            log_say(f"Recording episode {current_episode}", cfg.play_sounds)
            
            # Add a tracking flag that won't be reset by record_loop
            web_events["_exit_early_triggered"] = False
            logger.info(f"Recording phase - calling record_loop with events: {web_events}")
            
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
            
            logger.info(f"Recording phase completed - events state: {web_events}")
            
            # Check if exit_early was triggered (use our tracking flag)
            recording_interrupted_by_exit_early = web_events.get("_exit_early_triggered", False)
            if recording_interrupted_by_exit_early:
                logger.info("🟡 RECORDING PHASE INTERRUPTED BY EXIT_EARLY - proceeding to save episode")
                print(f"🟡 STATUS CHANGE: Recording phase interrupted by user - episode {current_episode} data collected")
                # Reset our tracking flag
                web_events["_exit_early_triggered"] = False
            else:
                # Recording completed due to timeout - trigger re-record behavior
                logger.info("⏰ RECORDING PHASE COMPLETED DUE TO TIMEOUT - triggering re-record")
                print(f"⏰ STATUS CHANGE: Recording timeout reached for episode {current_episode} - re-recording")
                web_events["rerecord_episode"] = True

            # Handle rerecord logic first (before saving)
            if web_events["rerecord_episode"]:
                log_say("Re-record episode", cfg.play_sounds)
                print(f"🔄 STATUS CHANGE: Re-recording episode {current_episode} (episode number stays the same)")
                web_events["rerecord_episode"] = False
                web_events["exit_early"] = False
                dataset.clear_episode_buffer()
                
                # Go through reset phase before re-recording (don't increment episode counters)
                # RESET PHASE - without dataset (matches original record.py exactly)
                current_phase = "resetting"
                phase_start_time = time.time()
                logger.info(f"Starting reset phase for re-record of episode {current_episode}")
                logger.info(f"Events state at start of reset phase: {web_events}")
                print(f"🔄 STATUS CHANGE: Starting reset phase for episode {current_episode}")
                
                log_say("Reset the environment", cfg.play_sounds)
                
                # Reset exit_early flag at the start of each phase
                web_events["exit_early"] = False
                logger.info(f"Reset phase - calling record_loop with events: {web_events}")
                
                record_loop(
                    robot=robot,
                    events=web_events,
                    fps=cfg.dataset.fps,
                    teleop=teleop,
                    # NOTE: NO dataset parameter here - matches LeRobot CLI exactly
                    # This means NO recording happens during reset phase
                    control_time_s=cfg.dataset.reset_time_s,
                    single_task=cfg.dataset.single_task,
                    display_data=cfg.display_data,
                )
                
                logger.info(f"Reset phase completed - events state: {web_events}")
                
                # Check if reset was interrupted by exit_early
                if web_events["exit_early"]:
                    logger.info("🟡 RESET PHASE INTERRUPTED BY EXIT_EARLY during re-record")
                    print(f"🟡 STATUS CHANGE: Reset phase interrupted by user during re-record")
                    web_events["exit_early"] = False
                
                # Check if stop recording was requested during re-record reset phase
                if web_events["stop_recording"]:
                    logger.info("🛑 STOP RECORDING requested during re-record reset phase - ending session")
                    print(f"🛑 STATUS CHANGE: Stop recording requested during re-record reset - ending session")
                    break
                
                # Don't increment current_episode or saved_episodes - we're re-recording the same episode
                continue

            # Save episode immediately after recording phase (matches expected flow)
            logger.info(f"💾 Saving episode {current_episode}...")
            print(f"💾 STATUS CHANGE: Saving episode {current_episode}")
            dataset.save_episode()
            logger.info(f"✅ Episode {current_episode} saved successfully")
            print(f"✅ STATUS CHANGE: Episode {current_episode} saved successfully")
            
            # Increment episode counters after successful save
            saved_episodes += 1
            current_episode += 1

            # Check if we should stop recording
            if web_events["stop_recording"]:
                print(f"🛑 STATUS CHANGE: Recording manually stopped by user")
                break

            # Check if we've completed all episodes
            if saved_episodes >= cfg.dataset.num_episodes:
                break

            # Execute reset phase to prepare for next episode
            # Skip reset for the last episode that was just saved
            if saved_episodes < cfg.dataset.num_episodes:
                # RESET PHASE - without dataset (matches original record.py exactly)
                current_phase = "resetting"
                phase_start_time = time.time()
                logger.info(f"Starting reset phase for next episode {current_episode}")
                logger.info(f"Events state at start of reset phase: {web_events}")
                print(f"🔄 STATUS CHANGE: Starting reset phase for episode {current_episode}")
                
                log_say("Reset the environment", cfg.play_sounds)
                
                # Reset exit_early flag at the start of each phase
                web_events["exit_early"] = False
                logger.info(f"Reset phase - calling record_loop with events: {web_events}")
                
                record_loop(
                    robot=robot,
                    events=web_events,
                    fps=cfg.dataset.fps,
                    teleop=teleop,
                    # NOTE: NO dataset parameter here - matches LeRobot CLI exactly
                    # This means NO recording happens during reset phase
                    control_time_s=cfg.dataset.reset_time_s,
                    single_task=cfg.dataset.single_task,
                    display_data=cfg.display_data,
                )
                
                logger.info(f"Reset phase completed - events state: {web_events}")
                
                # Check if reset was interrupted by exit_early
                if web_events["exit_early"]:
                    logger.info("🟡 RESET PHASE INTERRUPTED BY EXIT_EARLY - proceeding to next episode")
                    print(f"🟡 STATUS CHANGE: Reset phase interrupted by user - proceeding to next episode")
                    web_events["exit_early"] = False
                
                # Check if stop recording was requested during reset phase
                if web_events["stop_recording"]:
                    logger.info("🛑 STOP RECORDING requested during reset phase - ending session")
                    print(f"🛑 STATUS CHANGE: Stop recording requested during reset - ending session")
                    break

        # Recording completed
        current_phase = "completed"
        phase_start_time = None
        print(f"🏁 STATUS CHANGE: Recording session completed - all episodes finished")
        log_say("Stop recording", cfg.play_sounds, blocking=True)

    finally:
        robot.disconnect()
        if teleop:
            teleop.disconnect()

    if cfg.dataset.push_to_hub:
        dataset.push_to_hub(tags=cfg.dataset.tags, private=cfg.dataset.private)

    log_say("Exiting", cfg.play_sounds)
    return dataset 
