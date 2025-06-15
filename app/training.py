import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
import json
import queue
import os
import signal
import psutil

logger = logging.getLogger(__name__)

class TrainingRequest(BaseModel):
    # Dataset configuration - exact matches from CLI
    dataset_repo_id: str  # --dataset.repo_id
    dataset_revision: Optional[str] = None  # --dataset.revision
    dataset_root: Optional[str] = None  # --dataset.root
    dataset_episodes: Optional[List[int]] = None  # --dataset.episodes
    
    # Policy configuration - only type is configurable at top level
    policy_type: str = "act"  # --policy.type (act, diffusion, pi0, smolvla, tdmpc, vqbet, pi0fast, sac, reward_classifier)
    
    # Core training parameters - exact matches from CLI
    steps: int = 10000  # --steps
    batch_size: int = 8  # --batch_size
    seed: Optional[int] = 1000  # --seed
    num_workers: int = 4  # --num_workers
    
    # Logging and checkpointing - exact matches from CLI
    log_freq: int = 250  # --log_freq
    save_freq: int = 1000  # --save_freq
    eval_freq: int = 0  # --eval_freq
    save_checkpoint: bool = True  # --save_checkpoint
    
    # Output configuration - exact matches from CLI
    output_dir: str = "outputs/train"  # --output_dir
    resume: bool = False  # --resume
    job_name: Optional[str] = None  # --job_name
    
    # Weights & Biases - exact matches from CLI
    wandb_enable: bool = False  # --wandb.enable
    wandb_project: Optional[str] = None  # --wandb.project
    wandb_entity: Optional[str] = None  # --wandb.entity
    wandb_notes: Optional[str] = None  # --wandb.notes
    wandb_run_id: Optional[str] = None  # --wandb.run_id
    wandb_mode: Optional[str] = "online"  # --wandb.mode (online, offline, disabled)
    wandb_disable_artifact: bool = False  # --wandb.disable_artifact
    
    # Environment and evaluation - exact matches from CLI
    env_type: Optional[str] = None  # --env.type (aloha, pusht, xarm, gym_manipulator, hil)
    env_task: Optional[str] = None  # --env.task
    eval_n_episodes: int = 10  # --eval.n_episodes
    eval_batch_size: int = 50  # --eval.batch_size
    eval_use_async_envs: bool = False  # --eval.use_async_envs
    
    # Policy-specific parameters that are commonly used
    policy_device: Optional[str] = "cuda"  # --policy.device
    policy_use_amp: bool = False  # --policy.use_amp
    
    # Optimizer parameters - exact matches from CLI
    optimizer_type: Optional[str] = "adam"  # --optimizer.type (adam, adamw, sgd, multi_adam)
    optimizer_lr: Optional[float] = None  # --optimizer.lr (will use policy default if not set)
    optimizer_weight_decay: Optional[float] = None  # --optimizer.weight_decay
    optimizer_grad_clip_norm: Optional[float] = None  # --optimizer.grad_clip_norm
    
    # Advanced configuration
    use_policy_training_preset: bool = True  # --use_policy_training_preset
    config_path: Optional[str] = None  # --config_path

class TrainingStatus(BaseModel):
    training_active: bool = False
    current_step: int = 0
    total_steps: int = 0
    current_loss: Optional[float] = None
    current_lr: Optional[float] = None
    grad_norm: Optional[float] = None
    epoch_time: Optional[float] = None
    eta_seconds: Optional[float] = None
    available_controls: Dict[str, bool] = {
        "stop_training": False,
        "pause_training": False,
        "resume_training": False
    }

class TrainingManager:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.status = TrainingStatus()
        self.log_queue = queue.Queue()
        self.log_thread: Optional[threading.Thread] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self._stop_monitoring = threading.Event()
        
    def start_training(self, request: TrainingRequest) -> Dict[str, Any]:
        """Start a training session"""
        if self.status.training_active:
            return {"success": False, "message": "Training is already active"}
        
        try:
            # Create output directory
            output_path = Path(request.output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Build the training command
            cmd = self._build_training_command(request)
            logger.info(f"Starting training with command: {' '.join(cmd)}")
            
            # Start the training process
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                env=os.environ.copy()
            )
            
            # Update status
            self.status.training_active = True
            self.status.total_steps = request.steps
            self.status.current_step = 0
            self.status.available_controls = {
                "stop_training": True,
                "pause_training": False,  # Not implemented in LeRobot
                "resume_training": False
            }
            
            # Start monitoring threads
            self._start_monitoring()
            
            return {"success": True, "message": "Training started successfully"}
            
        except Exception as e:
            logger.error(f"Failed to start training: {e}")
            return {"success": False, "message": f"Failed to start training: {str(e)}"}
    
    def stop_training(self) -> Dict[str, Any]:
        """Stop the current training session"""
        if not self.status.training_active:
            return {"success": False, "message": "No training session is active"}
        
        try:
            if self.process and self.process.poll() is None:
                # Try graceful shutdown first
                self.process.terminate()
                
                # Wait for a bit, then force kill if necessary
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("Training process didn't terminate gracefully, forcing kill")
                    self.process.kill()
                    self.process.wait()
            
            self._stop_monitoring_threads()
            self._reset_status()
            
            return {"success": True, "message": "Training stopped successfully"}
            
        except Exception as e:
            logger.error(f"Failed to stop training: {e}")
            return {"success": False, "message": f"Failed to stop training: {str(e)}"}
    
    def get_status(self) -> TrainingStatus:
        """Get current training status"""
        # Check if process is still running
        if self.process and self.process.poll() is not None:
            # Process has ended
            if self.status.training_active:
                self._stop_monitoring_threads()
                self._reset_status()
        
        return self.status
    
    def get_logs(self) -> list:
        """Get recent training logs"""
        logs = []
        try:
            while not self.log_queue.empty():
                logs.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        return logs
    
    def _build_training_command(self, request: TrainingRequest) -> list:
        """Build the training command from the request parameters - only using actual CLI parameters"""
        cmd = ["python", "-m", "lerobot.scripts.train"]
        
        # Dataset configuration
        cmd.extend(["--dataset.repo_id", request.dataset_repo_id])
        if request.dataset_revision:
            cmd.extend(["--dataset.revision", request.dataset_revision])
        if request.dataset_root:
            cmd.extend(["--dataset.root", request.dataset_root])
        if request.dataset_episodes:
            cmd.extend(["--dataset.episodes"] + [str(ep) for ep in request.dataset_episodes])
        
        # Policy type
        cmd.extend(["--policy.type", request.policy_type])
        
        # Core training parameters
        cmd.extend(["--steps", str(request.steps)])
        cmd.extend(["--batch-size", str(request.batch_size)])
        cmd.extend(["--num-workers", str(request.num_workers)])
        
        if request.seed is not None:
            cmd.extend(["--seed", str(request.seed)])
        
        # Policy device and AMP
        if request.policy_device:
            cmd.extend(["--policy.device", request.policy_device])
        if request.policy_use_amp:
            cmd.append("--policy.use_amp")
        
        # Logging and checkpointing
        cmd.extend(["--log-freq", str(request.log_freq)])
        cmd.extend(["--save-freq", str(request.save_freq)])
        cmd.extend(["--eval-freq", str(request.eval_freq)])
        
        if request.save_checkpoint:
            cmd.append("--save_checkpoint")
        
        # Output configuration
        cmd.extend(["--output-dir", request.output_dir])
        if request.resume:
            cmd.append("--resume")
        if request.job_name:
            cmd.extend(["--job-name", request.job_name])
        
        # Weights & Biases
        if request.wandb_enable:
            cmd.append("--wandb.enable")
            if request.wandb_project:
                cmd.extend(["--wandb.project", request.wandb_project])
            if request.wandb_entity:
                cmd.extend(["--wandb.entity", request.wandb_entity])
            if request.wandb_notes:
                cmd.extend(["--wandb.notes", request.wandb_notes])
            if request.wandb_run_id:
                cmd.extend(["--wandb.run_id", request.wandb_run_id])
            if request.wandb_mode:
                cmd.extend(["--wandb.mode", request.wandb_mode])
            if request.wandb_disable_artifact:
                cmd.append("--wandb.disable_artifact")
        
        # Environment configuration
        if request.env_type:
            cmd.extend(["--env.type", request.env_type])
        if request.env_task:
            cmd.extend(["--env.task", request.env_task])
        
        # Evaluation configuration
        cmd.extend(["--eval.n_episodes", str(request.eval_n_episodes)])
        cmd.extend(["--eval.batch_size", str(request.eval_batch_size)])
        if request.eval_use_async_envs:
            cmd.append("--eval.use_async_envs")
        
        # Optimizer configuration
        if request.optimizer_type:
            cmd.extend(["--optimizer.type", request.optimizer_type])
        if request.optimizer_lr is not None:
            cmd.extend(["--optimizer.lr", str(request.optimizer_lr)])
        if request.optimizer_weight_decay is not None:
            cmd.extend(["--optimizer.weight_decay", str(request.optimizer_weight_decay)])
        if request.optimizer_grad_clip_norm is not None:
            cmd.extend(["--optimizer.grad_clip_norm", str(request.optimizer_grad_clip_norm)])
        
        # Advanced options
        if request.use_policy_training_preset:
            cmd.append("--use_policy_training_preset")
        if request.config_path:
            cmd.extend(["--config_path", request.config_path])
        
        return cmd
    
    def _start_monitoring(self):
        """Start monitoring threads for process output and status"""
        self._stop_monitoring.clear()
        
        # Start log monitoring thread
        self.log_thread = threading.Thread(
            target=self._monitor_logs,
            daemon=True
        )
        self.log_thread.start()
        
        # Start status monitoring thread
        self.monitor_thread = threading.Thread(
            target=self._monitor_status,
            daemon=True
        )
        self.monitor_thread.start()
    
    def _stop_monitoring_threads(self):
        """Stop all monitoring threads"""
        self._stop_monitoring.set()
        
        if self.log_thread and self.log_thread.is_alive():
            self.log_thread.join(timeout=2)
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2)
    
    def _monitor_logs(self):
        """Monitor training process logs"""
        if not self.process:
            return
        
        try:
            for line in iter(self.process.stdout.readline, ''):
                if self._stop_monitoring.is_set():
                    break
                
                if line.strip():
                    # Parse training information from log line
                    self._parse_log_line(line.strip())
                    
                    # Add to log queue (keep last 1000 lines)
                    if self.log_queue.qsize() >= 1000:
                        try:
                            self.log_queue.get_nowait()
                        except queue.Empty:
                            pass
                    
                    self.log_queue.put({
                        "timestamp": time.time(),
                        "message": line.strip()
                    })
        
        except Exception as e:
            logger.error(f"Error monitoring logs: {e}")
    
    def _monitor_status(self):
        """Monitor training process status"""
        while not self._stop_monitoring.is_set() and self.process:
            try:
                # Check if process is still running
                if self.process.poll() is not None:
                    # Process has ended
                    break
                
                # Update available controls
                self.status.available_controls["stop_training"] = True
                
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error monitoring status: {e}")
                break
    
    def _parse_log_line(self, line: str):
        """Parse training metrics from log line"""
        try:
            # Look for training metrics in the log line
            if "step:" in line.lower() and "loss:" in line.lower():
                # Extract step number
                if "step:" in line:
                    step_part = line.split("step:")[1].split()[0]
                    try:
                        self.status.current_step = int(step_part.replace(",", ""))
                    except ValueError:
                        pass
                
                # Extract loss
                if "loss:" in line:
                    loss_part = line.split("loss:")[1].split()[0]
                    try:
                        self.status.current_loss = float(loss_part)
                    except ValueError:
                        pass
                
                # Extract learning rate
                if "lr:" in line:
                    lr_part = line.split("lr:")[1].split()[0]
                    try:
                        self.status.current_lr = float(lr_part)
                    except ValueError:
                        pass
                
                # Extract gradient norm
                if "grdn:" in line:
                    grdn_part = line.split("grdn:")[1].split()[0]
                    try:
                        self.status.grad_norm = float(grdn_part)
                    except ValueError:
                        pass
                
                # Calculate ETA
                if self.status.current_step > 0 and self.status.total_steps > 0:
                    progress = self.status.current_step / self.status.total_steps
                    if progress > 0:
                        # Rough estimate based on current progress
                        remaining_steps = self.status.total_steps - self.status.current_step
                        # This is a very rough estimate - would need more sophisticated timing
                        self.status.eta_seconds = remaining_steps * 0.5  # Assume 0.5s per step
        
        except Exception as e:
            logger.debug(f"Error parsing log line '{line}': {e}")
    
    def _reset_status(self):
        """Reset training status"""
        self.status = TrainingStatus()
        self.process = None

# Global training manager instance
training_manager = TrainingManager()

# Handler functions for FastAPI endpoints
def handle_start_training(request: TrainingRequest) -> Dict[str, Any]:
    """Handle start training request"""
    return training_manager.start_training(request)

def handle_stop_training() -> Dict[str, Any]:
    """Handle stop training request"""
    return training_manager.stop_training()

def handle_training_status() -> TrainingStatus:
    """Handle training status request"""
    return training_manager.get_status()

def handle_training_logs() -> Dict[str, Any]:
    """Handle training logs request"""
    logs = training_manager.get_logs()
    return {"logs": logs} 
