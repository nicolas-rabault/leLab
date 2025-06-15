import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useToast } from "@/components/ui/use-toast";
import {
  Play,
  Square,
  ArrowLeft,
  Settings,
  Activity,
  FileText,
  Cpu,
  Database,
  TrendingUp,
  Clock,
  AlertCircle,
  CheckCircle,
  Loader2,
} from "lucide-react";

interface TrainingConfig {
  // Dataset configuration - exact matches from CLI
  dataset_repo_id: string; // --dataset.repo_id
  dataset_revision?: string; // --dataset.revision
  dataset_root?: string; // --dataset.root
  dataset_episodes?: number[]; // --dataset.episodes

  // Policy configuration - only type is configurable at top level
  policy_type: string; // --policy.type (act, diffusion, pi0, smolvla, tdmpc, vqbet, pi0fast, sac, reward_classifier)

  // Core training parameters - exact matches from CLI
  steps: number; // --steps
  batch_size: number; // --batch_size
  seed?: number; // --seed
  num_workers: number; // --num_workers

  // Logging and checkpointing - exact matches from CLI
  log_freq: number; // --log_freq
  save_freq: number; // --save_freq
  eval_freq: number; // --eval_freq
  save_checkpoint: boolean; // --save_checkpoint

  // Output configuration - exact matches from CLI
  output_dir: string; // --output_dir
  resume: boolean; // --resume
  job_name?: string; // --job_name

  // Weights & Biases - exact matches from CLI
  wandb_enable: boolean; // --wandb.enable
  wandb_project?: string; // --wandb.project
  wandb_entity?: string; // --wandb.entity
  wandb_notes?: string; // --wandb.notes
  wandb_run_id?: string; // --wandb.run_id
  wandb_mode?: string; // --wandb.mode (online, offline, disabled)
  wandb_disable_artifact: boolean; // --wandb.disable_artifact

  // Environment and evaluation - exact matches from CLI
  env_type?: string; // --env.type (aloha, pusht, xarm, gym_manipulator, hil)
  env_task?: string; // --env.task
  eval_n_episodes: number; // --eval.n_episodes
  eval_batch_size: number; // --eval.batch_size
  eval_use_async_envs: boolean; // --eval.use_async_envs

  // Policy-specific parameters that are commonly used
  policy_device?: string; // --policy.device
  policy_use_amp: boolean; // --policy.use_amp

  // Optimizer parameters - exact matches from CLI
  optimizer_type?: string; // --optimizer.type (adam, adamw, sgd, multi_adam)
  optimizer_lr?: number; // --optimizer.lr (will use policy default if not set)
  optimizer_weight_decay?: number; // --optimizer.weight_decay
  optimizer_grad_clip_norm?: number; // --optimizer.grad_clip_norm

  // Advanced configuration
  use_policy_training_preset: boolean; // --use_policy_training_preset
  config_path?: string; // --config_path
}

interface TrainingStatus {
  training_active: boolean;
  current_step: number;
  total_steps: number;
  current_loss?: number;
  current_lr?: number;
  grad_norm?: number;
  epoch_time?: number;
  eta_seconds?: number;
  available_controls: {
    stop_training: boolean;
    pause_training: boolean;
    resume_training: boolean;
  };
}

interface LogEntry {
  timestamp: number;
  message: string;
}

const Training = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const logContainerRef = useRef<HTMLDivElement>(null);

  const [trainingConfig, setTrainingConfig] = useState<TrainingConfig>({
    dataset_repo_id: "",
    policy_type: "act",
    steps: 10000,
    batch_size: 8,
    seed: 1000,
    num_workers: 4,
    log_freq: 250,
    save_freq: 1000,
    eval_freq: 0,
    save_checkpoint: true,
    output_dir: "outputs/train",
    resume: false,
    wandb_enable: false,
    wandb_mode: "online",
    wandb_disable_artifact: false,
    eval_n_episodes: 10,
    eval_batch_size: 50,
    eval_use_async_envs: false,
    policy_device: "cuda",
    policy_use_amp: false,
    optimizer_type: "adam",
    use_policy_training_preset: true,
  });

  const [trainingStatus, setTrainingStatus] = useState<TrainingStatus>({
    training_active: false,
    current_step: 0,
    total_steps: 0,
    available_controls: {
      stop_training: false,
      pause_training: false,
      resume_training: false,
    },
  });

  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isStartingTraining, setIsStartingTraining] = useState(false);
  const [activeTab, setActiveTab] = useState<"config" | "monitoring">("config");

  // Poll for training status and logs
  useEffect(() => {
    const pollInterval = setInterval(async () => {
      if (trainingStatus.training_active) {
        try {
          // Get status
          const statusResponse = await fetch("/training-status");
          if (statusResponse.ok) {
            const status = await statusResponse.json();
            setTrainingStatus(status);
          }

          // Get logs
          const logsResponse = await fetch("/training-logs");
          if (logsResponse.ok) {
            const logsData = await logsResponse.json();
            if (logsData.logs && logsData.logs.length > 0) {
              setLogs((prevLogs) => [...prevLogs, ...logsData.logs]);
            }
          }
        } catch (error) {
          console.error("Error polling training status:", error);
        }
      }
    }, 1000);

    return () => clearInterval(pollInterval);
  }, [trainingStatus.training_active]);

  // Auto-scroll logs
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const handleStartTraining = async () => {
    if (!trainingConfig.dataset_repo_id.trim()) {
      toast({
        title: "Error",
        description: "Dataset repository ID is required",
        variant: "destructive",
      });
      return;
    }

    setIsStartingTraining(true);
    try {
      const response = await fetch("/start-training", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(trainingConfig),
      });

      if (response.ok) {
        const result = await response.json();
        if (result.success) {
          toast({
            title: "Training Started",
            description: "Training session has been started successfully",
          });
          setActiveTab("monitoring");
          setLogs([]);
        } else {
          toast({
            title: "Error",
            description: result.message || "Failed to start training",
            variant: "destructive",
          });
        }
      } else {
        toast({
          title: "Error",
          description: "Failed to start training",
          variant: "destructive",
        });
      }
    } catch (error) {
      console.error("Error starting training:", error);
      toast({
        title: "Error",
        description: "Failed to start training",
        variant: "destructive",
      });
    } finally {
      setIsStartingTraining(false);
    }
  };

  const handleStopTraining = async () => {
    try {
      const response = await fetch("/stop-training", {
        method: "POST",
      });

      if (response.ok) {
        const result = await response.json();
        if (result.success) {
          toast({
            title: "Training Stopped",
            description: "Training session has been stopped",
          });
        } else {
          toast({
            title: "Error",
            description: result.message || "Failed to stop training",
            variant: "destructive",
          });
        }
      }
    } catch (error) {
      console.error("Error stopping training:", error);
      toast({
        title: "Error",
        description: "Failed to stop training",
        variant: "destructive",
      });
    }
  };

  const updateConfig = <T extends keyof TrainingConfig>(
    key: T,
    value: TrainingConfig[T]
  ) => {
    setTrainingConfig((prev) => ({ ...prev, [key]: value }));
  };

  const formatTime = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${hours.toString().padStart(2, "0")}:${minutes
      .toString()
      .padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const getProgressPercentage = () => {
    if (trainingStatus.total_steps === 0) return 0;
    return (trainingStatus.current_step / trainingStatus.total_steps) * 100;
  };

  const getStatusColor = () => {
    if (trainingStatus.training_active) return "text-green-400";
    return "text-gray-400";
  };

  const getStatusText = () => {
    if (trainingStatus.training_active) return "Training Active";
    return "Ready to Train";
  };

  return (
    <div className="min-h-screen bg-gray-950 text-white p-4">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate("/")}
              className="text-gray-400 hover:text-white"
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Home
            </Button>
            <h1 className="text-4xl font-bold text-white">
              Training Dashboard
            </h1>
          </div>

          <div className="flex items-center gap-3">
            <div
              className={`w-2 h-2 rounded-full ${
                trainingStatus.training_active ? "bg-green-400" : "bg-gray-400"
              }`}
            ></div>
            <span className={`font-semibold ${getStatusColor()}`}>
              {getStatusText()}
            </span>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex gap-2 mb-6">
          <Button
            variant={activeTab === "config" ? "default" : "ghost"}
            onClick={() => setActiveTab("config")}
            className="flex items-center gap-2"
          >
            <Settings className="w-4 h-4" />
            Configuration
          </Button>
          <Button
            variant={activeTab === "monitoring" ? "default" : "ghost"}
            onClick={() => setActiveTab("monitoring")}
            className="flex items-center gap-2"
          >
            <Activity className="w-4 h-4" />
            Monitoring
          </Button>
        </div>

        {/* Configuration Tab */}
        {activeTab === "config" && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {/* Dataset Configuration */}
            <Card className="bg-gray-900 border-gray-700">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <Database className="w-5 h-5" />
                  Dataset Configuration
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <Label htmlFor="dataset_repo_id" className="text-gray-300">
                    Dataset Repository ID *
                  </Label>
                  <Input
                    id="dataset_repo_id"
                    value={trainingConfig.dataset_repo_id}
                    onChange={(e) =>
                      updateConfig("dataset_repo_id", e.target.value)
                    }
                    placeholder="e.g., your-username/your-dataset"
                    className="bg-gray-800 border-gray-600 text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    HuggingFace Hub dataset repository ID
                  </p>
                </div>

                <div>
                  <Label htmlFor="dataset_revision" className="text-gray-300">
                    Dataset Revision (optional)
                  </Label>
                  <Input
                    id="dataset_revision"
                    value={trainingConfig.dataset_revision || ""}
                    onChange={(e) =>
                      updateConfig(
                        "dataset_revision",
                        e.target.value || undefined
                      )
                    }
                    placeholder="main"
                    className="bg-gray-800 border-gray-600 text-white"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Git revision (branch, tag, or commit hash)
                  </p>
                </div>

                <div>
                  <Label htmlFor="dataset_root" className="text-gray-300">
                    Dataset Root Directory (optional)
                  </Label>
                  <Input
                    id="dataset_root"
                    value={trainingConfig.dataset_root || ""}
                    onChange={(e) =>
                      updateConfig("dataset_root", e.target.value || undefined)
                    }
                    placeholder="./data"
                    className="bg-gray-800 border-gray-600 text-white"
                  />
                </div>
              </CardContent>
            </Card>

            {/* Policy Configuration */}
            <Card className="bg-gray-900 border-gray-700">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <Cpu className="w-5 h-5" />
                  Policy Configuration
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <Label htmlFor="policy_type" className="text-gray-300">
                    Policy Type
                  </Label>
                  <Select
                    value={trainingConfig.policy_type}
                    onValueChange={(value) =>
                      updateConfig("policy_type", value)
                    }
                  >
                    <SelectTrigger className="bg-gray-800 border-gray-600 text-white">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-gray-800 border-gray-600">
                      <SelectItem value="act">
                        ACT (Action Chunking Transformer)
                      </SelectItem>
                      <SelectItem value="diffusion">
                        Diffusion Policy
                      </SelectItem>
                      <SelectItem value="pi0">PI0</SelectItem>
                      <SelectItem value="smolvla">SmolVLA</SelectItem>
                      <SelectItem value="tdmpc">TD-MPC</SelectItem>
                      <SelectItem value="vqbet">VQ-BeT</SelectItem>
                      <SelectItem value="pi0fast">PI0 Fast</SelectItem>
                      <SelectItem value="sac">SAC</SelectItem>
                      <SelectItem value="reward_classifier">
                        Reward Classifier
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="policy_device" className="text-gray-300">
                    Device
                  </Label>
                  <Select
                    value={trainingConfig.policy_device || "cuda"}
                    onValueChange={(value) =>
                      updateConfig("policy_device", value)
                    }
                  >
                    <SelectTrigger className="bg-gray-800 border-gray-600 text-white">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-gray-800 border-gray-600">
                      <SelectItem value="cuda">CUDA (GPU)</SelectItem>
                      <SelectItem value="cpu">CPU</SelectItem>
                      <SelectItem value="mps">MPS (Apple Silicon)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex items-center space-x-3">
                  <Switch
                    id="policy_use_amp"
                    checked={trainingConfig.policy_use_amp}
                    onCheckedChange={(checked) =>
                      updateConfig("policy_use_amp", checked)
                    }
                  />
                  <Label htmlFor="policy_use_amp" className="text-gray-300">
                    Use Automatic Mixed Precision (AMP)
                  </Label>
                </div>
              </CardContent>
            </Card>

            {/* Training Parameters */}
            <Card className="bg-gray-900 border-gray-700">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <TrendingUp className="w-5 h-5" />
                  Training Parameters
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="steps" className="text-gray-300">
                      Training Steps
                    </Label>
                    <Input
                      id="steps"
                      type="number"
                      value={trainingConfig.steps}
                      onChange={(e) =>
                        updateConfig("steps", parseInt(e.target.value))
                      }
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>

                  <div>
                    <Label htmlFor="batch_size" className="text-gray-300">
                      Batch Size
                    </Label>
                    <Input
                      id="batch_size"
                      type="number"
                      value={trainingConfig.batch_size}
                      onChange={(e) =>
                        updateConfig("batch_size", parseInt(e.target.value))
                      }
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="seed" className="text-gray-300">
                      Random Seed
                    </Label>
                    <Input
                      id="seed"
                      type="number"
                      value={trainingConfig.seed || ""}
                      onChange={(e) =>
                        updateConfig(
                          "seed",
                          e.target.value ? parseInt(e.target.value) : undefined
                        )
                      }
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>

                  <div>
                    <Label htmlFor="num_workers" className="text-gray-300">
                      Number of Workers
                    </Label>
                    <Input
                      id="num_workers"
                      type="number"
                      value={trainingConfig.num_workers}
                      onChange={(e) =>
                        updateConfig("num_workers", parseInt(e.target.value))
                      }
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Optimizer Configuration */}
            <Card className="bg-gray-900 border-gray-700">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <Settings className="w-5 h-5" />
                  Optimizer Configuration
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <Label htmlFor="optimizer_type" className="text-gray-300">
                    Optimizer Type
                  </Label>
                  <Select
                    value={trainingConfig.optimizer_type || "adam"}
                    onValueChange={(value) =>
                      updateConfig("optimizer_type", value)
                    }
                  >
                    <SelectTrigger className="bg-gray-800 border-gray-600 text-white">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-gray-800 border-gray-600">
                      <SelectItem value="adam">Adam</SelectItem>
                      <SelectItem value="adamw">AdamW</SelectItem>
                      <SelectItem value="sgd">SGD</SelectItem>
                      <SelectItem value="multi_adam">Multi Adam</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <Label htmlFor="optimizer_lr" className="text-gray-300">
                      Learning Rate
                    </Label>
                    <Input
                      id="optimizer_lr"
                      type="number"
                      step="0.0001"
                      value={trainingConfig.optimizer_lr || ""}
                      onChange={(e) =>
                        updateConfig(
                          "optimizer_lr",
                          e.target.value
                            ? parseFloat(e.target.value)
                            : undefined
                        )
                      }
                      placeholder="Use policy default"
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>

                  <div>
                    <Label
                      htmlFor="optimizer_weight_decay"
                      className="text-gray-300"
                    >
                      Weight Decay
                    </Label>
                    <Input
                      id="optimizer_weight_decay"
                      type="number"
                      step="0.0001"
                      value={trainingConfig.optimizer_weight_decay || ""}
                      onChange={(e) =>
                        updateConfig(
                          "optimizer_weight_decay",
                          e.target.value
                            ? parseFloat(e.target.value)
                            : undefined
                        )
                      }
                      placeholder="Use policy default"
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>

                  <div>
                    <Label
                      htmlFor="optimizer_grad_clip_norm"
                      className="text-gray-300"
                    >
                      Gradient Clipping
                    </Label>
                    <Input
                      id="optimizer_grad_clip_norm"
                      type="number"
                      value={trainingConfig.optimizer_grad_clip_norm || ""}
                      onChange={(e) =>
                        updateConfig(
                          "optimizer_grad_clip_norm",
                          e.target.value
                            ? parseFloat(e.target.value)
                            : undefined
                        )
                      }
                      placeholder="Use policy default"
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Logging Configuration */}
            <Card className="bg-gray-900 border-gray-700">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <FileText className="w-5 h-5" />
                  Logging & Checkpointing
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <Label htmlFor="log_freq" className="text-gray-300">
                      Log Frequency
                    </Label>
                    <Input
                      id="log_freq"
                      type="number"
                      value={trainingConfig.log_freq}
                      onChange={(e) =>
                        updateConfig("log_freq", parseInt(e.target.value))
                      }
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>

                  <div>
                    <Label htmlFor="save_freq" className="text-gray-300">
                      Save Frequency
                    </Label>
                    <Input
                      id="save_freq"
                      type="number"
                      value={trainingConfig.save_freq}
                      onChange={(e) =>
                        updateConfig("save_freq", parseInt(e.target.value))
                      }
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>

                  <div>
                    <Label htmlFor="eval_freq" className="text-gray-300">
                      Eval Frequency
                    </Label>
                    <Input
                      id="eval_freq"
                      type="number"
                      value={trainingConfig.eval_freq}
                      onChange={(e) =>
                        updateConfig("eval_freq", parseInt(e.target.value))
                      }
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>
                </div>

                <div>
                  <Label htmlFor="output_dir" className="text-gray-300">
                    Output Directory
                  </Label>
                  <Input
                    id="output_dir"
                    value={trainingConfig.output_dir}
                    onChange={(e) => updateConfig("output_dir", e.target.value)}
                    className="bg-gray-800 border-gray-600 text-white"
                  />
                </div>

                <div>
                  <Label htmlFor="job_name" className="text-gray-300">
                    Job Name (optional)
                  </Label>
                  <Input
                    id="job_name"
                    value={trainingConfig.job_name || ""}
                    onChange={(e) =>
                      updateConfig("job_name", e.target.value || undefined)
                    }
                    className="bg-gray-800 border-gray-600 text-white"
                  />
                </div>

                <div className="flex items-center space-x-3">
                  <Switch
                    id="save_checkpoint"
                    checked={trainingConfig.save_checkpoint}
                    onCheckedChange={(checked) =>
                      updateConfig("save_checkpoint", checked)
                    }
                  />
                  <Label htmlFor="save_checkpoint" className="text-gray-300">
                    Save Checkpoints
                  </Label>
                </div>

                <div className="flex items-center space-x-3">
                  <Switch
                    id="resume"
                    checked={trainingConfig.resume}
                    onCheckedChange={(checked) =>
                      updateConfig("resume", checked)
                    }
                  />
                  <Label htmlFor="resume" className="text-gray-300">
                    Resume from Checkpoint
                  </Label>
                </div>
              </CardContent>
            </Card>

            {/* Weights & Biases Configuration */}
            <Card className="bg-gray-900 border-gray-700">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <TrendingUp className="w-5 h-5" />
                  Weights & Biases
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center space-x-3">
                  <Switch
                    id="wandb_enable"
                    checked={trainingConfig.wandb_enable}
                    onCheckedChange={(checked) =>
                      updateConfig("wandb_enable", checked)
                    }
                  />
                  <Label htmlFor="wandb_enable" className="text-gray-300">
                    Enable Weights & Biases Logging
                  </Label>
                </div>

                {trainingConfig.wandb_enable && (
                  <>
                    <div>
                      <Label htmlFor="wandb_project" className="text-gray-300">
                        W&B Project Name
                      </Label>
                      <Input
                        id="wandb_project"
                        value={trainingConfig.wandb_project || ""}
                        onChange={(e) =>
                          updateConfig(
                            "wandb_project",
                            e.target.value || undefined
                          )
                        }
                        placeholder="my-robotics-project"
                        className="bg-gray-800 border-gray-600 text-white"
                      />
                    </div>

                    <div>
                      <Label htmlFor="wandb_entity" className="text-gray-300">
                        W&B Entity (optional)
                      </Label>
                      <Input
                        id="wandb_entity"
                        value={trainingConfig.wandb_entity || ""}
                        onChange={(e) =>
                          updateConfig(
                            "wandb_entity",
                            e.target.value || undefined
                          )
                        }
                        placeholder="your-username"
                        className="bg-gray-800 border-gray-600 text-white"
                      />
                    </div>

                    <div>
                      <Label htmlFor="wandb_notes" className="text-gray-300">
                        W&B Notes (optional)
                      </Label>
                      <Input
                        id="wandb_notes"
                        value={trainingConfig.wandb_notes || ""}
                        onChange={(e) =>
                          updateConfig(
                            "wandb_notes",
                            e.target.value || undefined
                          )
                        }
                        placeholder="Training run notes..."
                        className="bg-gray-800 border-gray-600 text-white"
                      />
                    </div>

                    <div>
                      <Label htmlFor="wandb_mode" className="text-gray-300">
                        W&B Mode
                      </Label>
                      <Select
                        value={trainingConfig.wandb_mode || "online"}
                        onValueChange={(value) =>
                          updateConfig("wandb_mode", value)
                        }
                      >
                        <SelectTrigger className="bg-gray-800 border-gray-600 text-white">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-gray-800 border-gray-600">
                          <SelectItem value="online">Online</SelectItem>
                          <SelectItem value="offline">Offline</SelectItem>
                          <SelectItem value="disabled">Disabled</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="flex items-center space-x-3">
                      <Switch
                        id="wandb_disable_artifact"
                        checked={trainingConfig.wandb_disable_artifact}
                        onCheckedChange={(checked) =>
                          updateConfig("wandb_disable_artifact", checked)
                        }
                      />
                      <Label
                        htmlFor="wandb_disable_artifact"
                        className="text-gray-300"
                      >
                        Disable Artifacts
                      </Label>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Environment & Evaluation Configuration */}
            <Card className="bg-gray-900 border-gray-700">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <Activity className="w-5 h-5" />
                  Environment & Evaluation
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <Label htmlFor="env_type" className="text-gray-300">
                    Environment Type (optional)
                  </Label>
                  <Select
                    value={trainingConfig.env_type || "none"}
                    onValueChange={(value) =>
                      updateConfig(
                        "env_type",
                        value === "none" ? undefined : value
                      )
                    }
                  >
                    <SelectTrigger className="bg-gray-800 border-gray-600 text-white">
                      <SelectValue placeholder="Select environment type" />
                    </SelectTrigger>
                    <SelectContent className="bg-gray-800 border-gray-600">
                      <SelectItem value="none">None</SelectItem>
                      <SelectItem value="aloha">Aloha</SelectItem>
                      <SelectItem value="pusht">PushT</SelectItem>
                      <SelectItem value="xarm">XArm</SelectItem>
                      <SelectItem value="gym_manipulator">
                        Gym Manipulator
                      </SelectItem>
                      <SelectItem value="hil">HIL</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="env_task" className="text-gray-300">
                    Environment Task (optional)
                  </Label>
                  <Input
                    id="env_task"
                    value={trainingConfig.env_task || ""}
                    onChange={(e) =>
                      updateConfig("env_task", e.target.value || undefined)
                    }
                    placeholder="e.g., insertion_human"
                    className="bg-gray-800 border-gray-600 text-white"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="eval_n_episodes" className="text-gray-300">
                      Eval Episodes
                    </Label>
                    <Input
                      id="eval_n_episodes"
                      type="number"
                      value={trainingConfig.eval_n_episodes}
                      onChange={(e) =>
                        updateConfig(
                          "eval_n_episodes",
                          parseInt(e.target.value)
                        )
                      }
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>

                  <div>
                    <Label htmlFor="eval_batch_size" className="text-gray-300">
                      Eval Batch Size
                    </Label>
                    <Input
                      id="eval_batch_size"
                      type="number"
                      value={trainingConfig.eval_batch_size}
                      onChange={(e) =>
                        updateConfig(
                          "eval_batch_size",
                          parseInt(e.target.value)
                        )
                      }
                      className="bg-gray-800 border-gray-600 text-white"
                    />
                  </div>
                </div>

                <div className="flex items-center space-x-3">
                  <Switch
                    id="eval_use_async_envs"
                    checked={trainingConfig.eval_use_async_envs}
                    onCheckedChange={(checked) =>
                      updateConfig("eval_use_async_envs", checked)
                    }
                  />
                  <Label
                    htmlFor="eval_use_async_envs"
                    className="text-gray-300"
                  >
                    Use Asynchronous Environments
                  </Label>
                </div>
              </CardContent>
            </Card>

            {/* Advanced Options */}
            <Card className="bg-gray-900 border-gray-700">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <Settings className="w-5 h-5" />
                  Advanced Options
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <Label htmlFor="config_path" className="text-gray-300">
                    Config Path (optional)
                  </Label>
                  <Input
                    id="config_path"
                    value={trainingConfig.config_path || ""}
                    onChange={(e) =>
                      updateConfig("config_path", e.target.value || undefined)
                    }
                    placeholder="path/to/config.yaml"
                    className="bg-gray-800 border-gray-600 text-white"
                  />
                </div>

                <div className="flex items-center space-x-3">
                  <Switch
                    id="use_policy_training_preset"
                    checked={trainingConfig.use_policy_training_preset}
                    onCheckedChange={(checked) =>
                      updateConfig("use_policy_training_preset", checked)
                    }
                  />
                  <Label
                    htmlFor="use_policy_training_preset"
                    className="text-gray-300"
                  >
                    Use Policy Training Preset
                  </Label>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Monitoring Tab */}
        {activeTab === "monitoring" && (
          <div className="space-y-6">
            {/* Training Progress */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              <Card className="bg-gray-900 border-gray-700">
                <CardContent className="p-6 text-center">
                  <h3 className="text-sm text-gray-400 mb-2">
                    Training Progress
                  </h3>
                  <div className="text-3xl font-bold text-blue-400 mb-2">
                    {trainingStatus.current_step} / {trainingStatus.total_steps}
                  </div>
                  <Progress value={getProgressPercentage()} className="mb-2" />
                  <div className="text-sm text-gray-400">
                    {getProgressPercentage().toFixed(1)}% Complete
                  </div>
                </CardContent>
              </Card>

              <Card className="bg-gray-900 border-gray-700">
                <CardContent className="p-6 text-center">
                  <h3 className="text-sm text-gray-400 mb-2">Current Loss</h3>
                  <div className="text-3xl font-bold text-green-400 mb-2">
                    {trainingStatus.current_loss?.toFixed(4) || "N/A"}
                  </div>
                  <div className="text-sm text-gray-400">Training Loss</div>
                </CardContent>
              </Card>

              <Card className="bg-gray-900 border-gray-700">
                <CardContent className="p-6 text-center">
                  <h3 className="text-sm text-gray-400 mb-2">Learning Rate</h3>
                  <div className="text-3xl font-bold text-orange-400 mb-2">
                    {trainingStatus.current_lr?.toExponential(2) || "N/A"}
                  </div>
                  <div className="text-sm text-gray-400">Current LR</div>
                </CardContent>
              </Card>

              <Card className="bg-gray-900 border-gray-700">
                <CardContent className="p-6 text-center">
                  <h3 className="text-sm text-gray-400 mb-2">ETA</h3>
                  <div className="text-3xl font-bold text-purple-400 mb-2">
                    {trainingStatus.eta_seconds
                      ? formatTime(trainingStatus.eta_seconds)
                      : "N/A"}
                  </div>
                  <div className="text-sm text-gray-400">Estimated Time</div>
                </CardContent>
              </Card>

              <Card className="bg-gray-900 border-gray-700">
                <CardContent className="p-6 text-center">
                  <h3 className="text-sm text-gray-400 mb-2">Gradient Norm</h3>
                  <div className="text-3xl font-bold text-cyan-400 mb-2">
                    {trainingStatus.grad_norm?.toFixed(3) || "N/A"}
                  </div>
                  <div className="text-sm text-gray-400">Gradient Clipping</div>
                </CardContent>
              </Card>

              <Card className="bg-gray-900 border-gray-700">
                <CardContent className="p-6 text-center">
                  <h3 className="text-sm text-gray-400 mb-2">
                    Training Status
                  </h3>
                  <div className="text-2xl font-bold text-yellow-400 mb-2">
                    {trainingStatus.training_active ? "Active" : "Stopped"}
                  </div>
                  <div className="text-sm text-gray-400">Current State</div>
                </CardContent>
              </Card>

              <Card className="bg-gray-900 border-gray-700">
                <CardContent className="p-6 text-center">
                  <h3 className="text-sm text-gray-400 mb-2">Dataset</h3>
                  <div className="text-lg font-bold text-pink-400 mb-2 truncate">
                    {trainingConfig.dataset_repo_id || "Not Set"}
                  </div>
                  <div className="text-sm text-gray-400">Repository ID</div>
                </CardContent>
              </Card>

              <Card className="bg-gray-900 border-gray-700">
                <CardContent className="p-6 text-center">
                  <h3 className="text-sm text-gray-400 mb-2">Policy</h3>
                  <div className="text-lg font-bold text-indigo-400 mb-2 uppercase">
                    {trainingConfig.policy_type}
                  </div>
                  <div className="text-sm text-gray-400">Model Type</div>
                </CardContent>
              </Card>
            </div>

            {/* Training Logs */}
            <Card className="bg-gray-900 border-gray-700">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <FileText className="w-5 h-5" />
                  Training Logs
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div
                  ref={logContainerRef}
                  className="bg-gray-950 rounded-lg p-4 h-96 overflow-y-auto font-mono text-sm"
                >
                  {logs.length === 0 ? (
                    <div className="text-gray-500 text-center py-8">
                      No training logs yet. Start training to see output.
                    </div>
                  ) : (
                    logs.map((log, index) => (
                      <div key={index} className="mb-1">
                        <span className="text-gray-500">
                          {new Date(log.timestamp * 1000).toLocaleTimeString()}
                        </span>
                        <span className="ml-2 text-gray-300">
                          {log.message}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Control Buttons */}
        <div className="fixed bottom-6 right-6 flex gap-3">
          {!trainingStatus.training_active ? (
            <Button
              onClick={handleStartTraining}
              disabled={
                isStartingTraining || !trainingConfig.dataset_repo_id.trim()
              }
              size="lg"
              className="bg-green-500 hover:bg-green-600 text-white font-semibold px-8 py-4 text-lg shadow-lg"
            >
              {isStartingTraining ? (
                <>
                  <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                  Starting...
                </>
              ) : (
                <>
                  <Play className="w-5 h-5 mr-2" />
                  Start Training
                </>
              )}
            </Button>
          ) : (
            <Button
              onClick={handleStopTraining}
              disabled={!trainingStatus.available_controls.stop_training}
              size="lg"
              className="bg-red-500 hover:bg-red-600 text-white font-semibold px-8 py-4 text-lg shadow-lg"
            >
              <Square className="w-5 h-5 mr-2" />
              Stop Training
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};

export default Training;
