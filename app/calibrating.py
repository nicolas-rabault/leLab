"""
Calibration module for the web interface.

This module provides calibration functionality similar to the CLI calibrate.py,
but adapted for the web interface with real-time status updates.
"""

import logging
import threading
import time
import subprocess
import sys
import io
import queue
import re
from dataclasses import asdict, dataclass
from typing import Optional, Dict, Any
from pprint import pformat

from lerobot.common.robots import (
    Robot,
    RobotConfig,
    make_robot_from_config,
)
from lerobot.common.teleoperators import (
    Teleoperator,
    TeleoperatorConfig,
    make_teleoperator_from_config,
)
from lerobot.common.utils.utils import init_logging

logger = logging.getLogger(__name__)


@dataclass
class CalibrationStatus:
    """Status information for calibration process"""
    calibration_active: bool = False
    status: str = "idle"  # "idle", "connecting", "calibrating", "completed", "error", "stopping"
    device_type: Optional[str] = None
    error: Optional[str] = None
    message: str = ""
    console_output: str = ""


@dataclass
class CalibrationRequest:
    """Request parameters for starting calibration"""
    device_type: str  # "robot" or "teleop"
    port: str
    config_file: str


class CalibrationManager:
    """Manages calibration process for the web interface"""

    def __init__(self):
        self.status = CalibrationStatus()
        self.device: Optional[Robot | Teleoperator] = None
        self.calibration_thread: Optional[threading.Thread] = None
        self.stop_calibration = False
        self._status_lock = threading.Lock()
        self._input_queue = queue.Queue(maxsize=100)  # Larger queue to prevent blocking
        self._output_buffer = io.StringIO()
        self._input_ready = threading.Event()  # Signal when input is available
        
        # Initialize logging
        init_logging()

    def get_status(self) -> CalibrationStatus:
        """Get current calibration status"""
        with self._status_lock:
            return self.status

    def _update_status(self, **kwargs):
        """Update calibration status thread-safely"""
        with self._status_lock:
            for key, value in kwargs.items():
                if hasattr(self.status, key):
                    setattr(self.status, key, value)

    def start_calibration(self, request: CalibrationRequest) -> Dict[str, Any]:
        """Start calibration process"""
        try:
            if self.status.calibration_active:
                return {"success": False, "message": "Calibration already active"}

            # Reset status
            self._update_status(
                calibration_active=True,
                status="connecting",
                device_type=request.device_type,
                error=None,
                message=f"Starting calibration for {request.device_type}"
            )

            # Start calibration in a separate thread
            self.calibration_thread = threading.Thread(
                target=self._calibration_worker,
                args=(request,),
                daemon=True
            )
            self.stop_calibration = False
            self._input_ready.clear()  # Clear any pending input signals
            self.calibration_thread.start()

            return {"success": True, "message": "Calibration started"}

        except Exception as e:
            logger.error(f"Error starting calibration: {e}")
            self._update_status(
                calibration_active=False,
                status="error",
                error=str(e),
                message="Failed to start calibration"
            )
            return {"success": False, "message": str(e)}

    def stop_calibration_process(self) -> Dict[str, Any]:
        """Stop calibration process"""
        try:
            if not self.status.calibration_active:
                return {"success": False, "message": "No calibration active"}

            self.stop_calibration = True
            self._update_status(
                status="stopping",
                message="Stopping calibration..."
            )

            # Wait for thread to finish
            if self.calibration_thread and self.calibration_thread.is_alive():
                self.calibration_thread.join(timeout=5.0)

            return {"success": True, "message": "Calibration stopped"}

        except Exception as e:
            logger.error(f"Error stopping calibration: {e}")
            return {"success": False, "message": str(e)}

    def send_input(self, input_text: str) -> Dict[str, Any]:
        """Send input to the calibration process"""
        try:
            logger.info(f"🔵 SEND_INPUT called with: '{input_text}' (repr: {repr(input_text)})")
            
            if not self.status.calibration_active:
                logger.warning("🔴 No calibration active when trying to send input")
                return {"success": False, "message": "No calibration active"}
            
            # Ensure we have a newline for Enter
            if input_text == "" or input_text == "\n":
                input_text = "\n"
                logger.info(f"🔵 Converted to newline: {repr(input_text)}")
            
            # Add input to queue with immediate timeout to prevent blocking
            try:
                self._input_queue.put_nowait(input_text)
                self._input_ready.set()  # Signal that input is available
                logger.info(f"🟢 Input queued successfully: '{input_text}' (repr: {repr(input_text)})")
                logger.info(f"🔵 Queue size after adding: {self._input_queue.qsize()}")
                logger.info(f"🔵 Input ready event set: {self._input_ready.is_set()}")
            except queue.Full:
                # If queue is full, clear it and add the new input
                logger.warning("🟡 Input queue was full, clearing and adding new input")
                cleared_count = 0
                try:
                    while True:
                        self._input_queue.get_nowait()
                        cleared_count += 1
                except queue.Empty:
                    pass
                logger.info(f"🟡 Cleared {cleared_count} items from queue")
                self._input_queue.put_nowait(input_text)
                self._input_ready.set()  # Signal that input is available
                logger.info(f"🟢 Input queued after clearing: '{input_text}' (repr: {repr(input_text)})")
            
            return {"success": True, "message": f"Input sent: {repr(input_text)}"}
            
        except Exception as e:
            logger.error(f"🔴 Error sending input: {e}")
            return {"success": False, "message": str(e)}

    def _calibration_worker(self, request: CalibrationRequest):
        """Worker thread for calibration process"""
        try:
            logger.info(f"Starting calibration worker for {request.device_type}")
            
            # Create device configuration
            if request.device_type == "robot":
                from lerobot.common.robots.so101_follower import SO101FollowerConfig
                config = SO101FollowerConfig(
                    port=request.port,
                    id=request.config_file
                )
            elif request.device_type == "teleop":
                from lerobot.common.teleoperators.so101_leader import SO101LeaderConfig
                config = SO101LeaderConfig(
                    port=request.port,
                    id=request.config_file
                )
            else:
                raise ValueError(f"Unknown device type: {request.device_type}")

            self._update_status(
                status="connecting",
                message="Connecting to device..."
            )

            # Create and connect device
            if request.device_type == "robot":
                self.device = make_robot_from_config(config)
            else:
                self.device = make_teleoperator_from_config(config)

            logger.info("Connecting to device...")
            self.device.connect(calibrate=False)

            if self.stop_calibration:
                self._cleanup_and_finish("Calibration cancelled")
                return

            self._update_status(
                status="calibrating",
                message="Calibrating device... Please move all joints through their full range of motion."
            )

            logger.info("Starting calibration...")
            
            # Interactive calibration with output capture
            self._run_interactive_calibration()

            if self.stop_calibration:
                self._cleanup_and_finish("Calibration cancelled")
                return

            logger.info("Calibration completed successfully")
            self._cleanup_and_finish("Calibration completed successfully", status="completed")

        except Exception as e:
            logger.error(f"Calibration error: {e}")
            self._update_status(
                status="error",
                error=str(e),
                message=f"Calibration failed: {e}"
            )
            self._cleanup_device()



    def _run_interactive_calibration(self):
        """Run calibration with interactive input/output capture"""
        
        # Create a custom input function that reads from our queue
        original_input = __builtins__['input'] if 'input' in __builtins__ else input
        
        def custom_input(prompt=""):
            # Add prompt to console output if there is one
            if prompt:
                console_capture.write(prompt)
                console_capture.flush()
            
            logger.info(f"🔵 CUSTOM_INPUT: Waiting for input... (prompt: '{prompt}')")
            logger.info(f"🔵 Queue size at start: {self._input_queue.qsize()}")
            logger.info(f"🔵 Input ready event state: {self._input_ready.is_set()}")
            
            # Use event-based approach for immediate response
            wait_count = 0
            while not self.stop_calibration:
                wait_count += 1
                if wait_count % 100 == 0:  # Log every 1 second (100 * 10ms)
                    logger.info(f"🔵 Still waiting for input... (wait count: {wait_count})")
                    logger.info(f"🔵 Queue size: {self._input_queue.qsize()}")
                    logger.info(f"🔵 Event state: {self._input_ready.is_set()}")
                
                # First check if there's already something in the queue
                try:
                    user_input = self._input_queue.get_nowait()
                    logger.info(f"🟢 Found input in queue: '{user_input}' (repr: {repr(user_input)})")
                    result = user_input.rstrip('\n')
                    logger.info(f"🟢 RETURNING INPUT: '{result}' (repr: {repr(result)})")
                    return result
                except queue.Empty:
                    pass
                
                # Wait for input signal with very short timeout
                if self._input_ready.wait(timeout=0.01):  # 10ms timeout
                    logger.info(f"🟢 Input event triggered! Queue size: {self._input_queue.qsize()}")
                    self._input_ready.clear()  # Clear the signal immediately
                    try:
                        # Try to get input immediately
                        user_input = self._input_queue.get_nowait()
                        logger.info(f"🟢 RECEIVED INPUT: '{user_input}' (repr: {repr(user_input)})")
                        
                        # Always strip newline - input() should return empty string for Enter
                        result = user_input.rstrip('\n')
                        logger.info(f"🟢 RETURNING INPUT: '{result}' (repr: {repr(result)})")
                        return result
                    except queue.Empty:
                        # Signal was set but queue is empty
                        logger.warning(f"🟡 Event was set but queue is empty")
                        continue
                # If no input signal, continue waiting
            
            logger.info("🔴 Input cancelled due to stop_calibration")
            return ""  # Return empty if stopped
        
        # Capture stdout
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        
        class ConsoleCapture:
            def __init__(self, manager):
                self.manager = manager
                self.lines = []
                self.current_line = ""
                self.cursor_line = 0  # Track cursor position for line updates
                self.last_update = 0  # Track last update time for throttling
            
            def write(self, text):
                # Also write to original stdout for logging
                original_stdout.write(text)
                
                if not text:
                    return
                
                # Handle various ANSI escape sequences before cleaning
                
                # Check for cursor up sequences (move cursor up N lines)
                cursor_up_pattern = re.compile(r'\x1B\[(\d+)?A')
                cursor_up_matches = cursor_up_pattern.findall(text)
                
                # Check for cursor position sequences (move to specific line/column)
                cursor_pos_pattern = re.compile(r'\x1B\[(\d+);(\d+)H')
                cursor_pos_matches = cursor_pos_pattern.findall(text)
                
                # Check for erase line sequences
                erase_line_pattern = re.compile(r'\x1B\[K')
                has_erase_line = erase_line_pattern.search(text)
                
                # Remove all ANSI escape sequences for clean text
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                cleaned_text = ansi_escape.sub('', text)
                
                # Handle cursor movements and line clearing
                # Cursor up movements (common in progress updates)
                for match in cursor_up_matches:
                    lines_up = int(match) if match else 1
                    # Move cursor up and potentially overwrite previous lines
                    if self.lines and lines_up > 0:
                        # Remove the last few lines that will be overwritten
                        for _ in range(min(lines_up, len(self.lines))):
                            if self.lines:
                                self.lines.pop()
                        self.current_line = ""
                
                # Handle cursor position moves (absolute positioning)
                for line_str, col_str in cursor_pos_matches:
                    target_line = int(line_str) - 1  # Convert to 0-based
                    # Clear lines beyond the target line
                    if target_line < len(self.lines):
                        self.lines = self.lines[:target_line]
                        self.current_line = ""
                
                # Handle line erase sequences
                if has_erase_line:
                    # Clear the current line
                    self.current_line = ""
                
                # Process the cleaned text
                i = 0
                while i < len(cleaned_text):
                    char = cleaned_text[i]
                    
                    if char == '\r':
                        # Carriage return - go back to start of current line
                        self.current_line = ""
                    elif char == '\n':
                        # New line - add current line to lines and start new
                        self.lines.append(self.current_line)
                        self.current_line = ""
                    elif char == '\b':
                        # Backspace - remove last character
                        if self.current_line:
                            self.current_line = self.current_line[:-1]
                    else:
                        # Regular character - add to current line
                        self.current_line += char
                    
                    i += 1
                
                # Update console output with throttling for performance
                import time
                current_time = time.time()
                
                # Update immediately for important changes, throttle for frequent updates
                should_update = (
                    current_time - self.last_update > 0.02 or  # Max 50 updates per second (faster!)
                    '\n' in text or  # Always update on new lines
                    '\r' in text or  # Always update on carriage returns
                    len(text) > 5   # Always update for substantial text (lower threshold)
                )
                
                if should_update:
                    output_lines = self.lines.copy()
                    if self.current_line:
                        output_lines.append(self.current_line)
                    
                    console_output = '\n'.join(output_lines)
                    # Use a separate thread for status updates to prevent blocking input
                    import threading
                    def update_status():
                        self.manager._update_status(console_output=console_output)
                    
                    threading.Thread(target=update_status, daemon=True).start()
                    self.last_update = current_time
            
            def flush(self):
                original_stdout.flush()
                # Force update console output on flush
                output_lines = self.lines.copy()
                if self.current_line:
                    output_lines.append(self.current_line)
                
                console_output = '\n'.join(output_lines)
                self.manager._update_status(console_output=console_output)
                import time
                self.last_update = time.time()
        
        console_capture = ConsoleCapture(self)
        
        try:
            # Replace input and stdout
            __builtins__['input'] = custom_input
            sys.stdout = console_capture
            sys.stderr = console_capture
            
            # Add initial message to console
            self._update_status(console_output="Starting calibration...\n")
            
            # Run the actual calibration
            self.device.calibrate()
            
        finally:
            # Restore original functions
            __builtins__['input'] = original_input
            sys.stdout = original_stdout
            sys.stderr = original_stderr

    def _cleanup_and_finish(self, message: str, status: str = "completed"):
        """Clean up and finish calibration"""
        self._cleanup_device()
        # Clear input queue
        while not self._input_queue.empty():
            try:
                self._input_queue.get_nowait()
            except queue.Empty:
                break
        self._update_status(
            calibration_active=False,
            status=status,
            message=message
        )

    def _cleanup_device(self):
        """Clean up device connection"""
        try:
            if self.device:
                logger.info("Disconnecting device...")
                self.device.disconnect()
                self.device = None
        except Exception as e:
            logger.error(f"Error disconnecting device: {e}")


# Global calibration manager instance
calibration_manager = CalibrationManager() 
