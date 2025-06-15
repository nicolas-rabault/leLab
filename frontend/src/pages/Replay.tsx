import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/use-toast";
import {
  Play,
  Square,
  ArrowLeft,
  Settings,
  Activity,
  FileText,
  CheckCircle,
  AlertCircle,
  Loader2,
} from "lucide-react";

interface ReplayConfig {
  robot_type: string;
  robot_port: string;
  robot_id: string;
  dataset_repo_id: string;
  episode: number;
}

interface ReplayStatus {
  replay_active: boolean;
  status: string;
  robot_type?: string;
  robot_port?: string;
  robot_id?: string;
  dataset_repo_id?: string;
  episode?: number;
  error_message?: string;
  start_time?: number;
  logs: string[];
}

interface LogEntry {
  timestamp: number;
  message: string;
}

const Replay = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const logContainerRef = useRef<HTMLDivElement>(null);

  const [replayConfig, setReplayConfig] = useState<ReplayConfig>({
    robot_type: "",
    robot_port: "/dev/tty.usbmodem58760431541",
    robot_id: "",
    dataset_repo_id: "",
    episode: 0,
  });

  const [replayStatus, setReplayStatus] = useState<ReplayStatus>({
    replay_active: false,
    status: "idle",
    logs: [],
  });

  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isStartingReplay, setIsStartingReplay] = useState(false);
  const [activeTab, setActiveTab] = useState<"config" | "monitoring">("config");

  // Config discovery state
  const [followerConfigs, setFollowerConfigs] = useState<string[]>([]);
  const [isLoadingConfigs, setIsLoadingConfigs] = useState(false);

  // Available robot types mapping
  const robotTypes = [
    { value: "so101_follower", label: "SO101 Follower", model: "SO101" },
    { value: "so100_follower", label: "SO100 Follower", model: "SO100" },
  ];

  // Load available configs
  const loadConfigs = async () => {
    setIsLoadingConfigs(true);
    try {
      const response = await fetch("http://localhost:8000/get-configs");
      const data = await response.json();
      setFollowerConfigs(data.follower_configs || []);
    } catch (error) {
      toast({
        title: "Error Loading Configs",
        description: "Could not load calibration configs from the backend.",
        variant: "destructive",
      });
    } finally {
      setIsLoadingConfigs(false);
    }
  };

  // Load configs on component mount
  useEffect(() => {
    loadConfigs();
  }, []);

  // Poll for replay status and logs
  useEffect(() => {
    const pollInterval = setInterval(async () => {
      try {
        // Get status
        const statusResponse = await fetch(
          "http://localhost:8000/replay-status"
        );
        if (statusResponse.ok) {
          const statusData = await statusResponse.json();
          if (statusData.success) {
            setReplayStatus(statusData.status);
          }
        }

        // Get logs if replay is active
        if (replayStatus.replay_active) {
          const logsResponse = await fetch("http://localhost:8000/replay-logs");
          if (logsResponse.ok) {
            const logsData = await logsResponse.json();
            if (logsData.success && logsData.logs && logsData.logs.length > 0) {
              // Convert log strings to log entries with timestamps
              const newLogEntries = logsData.logs.map(
                (logMessage: string, index: number) => ({
                  timestamp: Date.now() + index,
                  message: logMessage,
                })
              );
              setLogs(newLogEntries);
            }
          }
        }
      } catch (error) {
        console.error("Error polling replay status:", error);
      }
    }, 1000);

    return () => clearInterval(pollInterval);
  }, [replayStatus.replay_active]);

  // Auto-scroll logs
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const handleStartReplay = async () => {
    if (!replayConfig.dataset_repo_id.trim()) {
      toast({
        title: "Error",
        description: "Dataset repository ID is required",
        variant: "destructive",
      });
      return;
    }

    // Validate repo ID format (no spaces, proper HuggingFace format)
    const repoIdRegex =
      /^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?\/[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$/;
    if (!repoIdRegex.test(replayConfig.dataset_repo_id.trim())) {
      toast({
        title: "Invalid Repository ID",
        description:
          "Repository ID must be in format 'username/dataset-name' with no spaces",
        variant: "destructive",
      });
      return;
    }

    if (!replayConfig.robot_id) {
      toast({
        title: "Error",
        description: "Robot ID (calibration config) is required",
        variant: "destructive",
      });
      return;
    }

    if (!replayConfig.robot_type) {
      toast({
        title: "Error",
        description: "Robot type is required",
        variant: "destructive",
      });
      return;
    }

    setIsStartingReplay(true);
    setLogs([]); // Clear previous logs

    try {
      const response = await fetch("http://localhost:8000/start-replay", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(replayConfig),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        toast({
          title: "Replay Started",
          description: data.message || "Replay session started successfully",
        });
        setActiveTab("monitoring");
      } else {
        toast({
          title: "Error Starting Replay",
          description: data.message || "Failed to start replay session",
          variant: "destructive",
        });
      }
    } catch (error) {
      toast({
        title: "Connection Error",
        description: "Could not connect to the backend server",
        variant: "destructive",
      });
    } finally {
      setIsStartingReplay(false);
    }
  };

  const handleStopReplay = async () => {
    try {
      const response = await fetch("http://localhost:8000/stop-replay", {
        method: "POST",
      });

      const data = await response.json();

      if (response.ok && data.success) {
        toast({
          title: "Replay Stopped",
          description: data.message || "Replay session stopped successfully",
        });
      } else {
        toast({
          title: "Error Stopping Replay",
          description: data.message || "Failed to stop replay session",
          variant: "destructive",
        });
      }
    } catch (error) {
      toast({
        title: "Connection Error",
        description: "Could not connect to the backend server",
        variant: "destructive",
      });
    }
  };

  const updateConfig = <T extends keyof ReplayConfig>(
    key: T,
    value: ReplayConfig[T]
  ) => {
    setReplayConfig((prev) => ({ ...prev, [key]: value }));
  };

  const getStatusColor = () => {
    switch (replayStatus.status) {
      case "running":
        return "text-green-500";
      case "completed":
        return "text-blue-500";
      case "error":
        return "text-red-500";
      case "starting":
        return "text-yellow-500";
      default:
        return "text-gray-400";
    }
  };

  const getStatusText = () => {
    switch (replayStatus.status) {
      case "idle":
        return "Ready to start replay";
      case "starting":
        return "Starting replay...";
      case "running":
        return "Replay in progress";
      case "completed":
        return "Replay completed";
      case "error":
        return `Error: ${replayStatus.error_message || "Unknown error"}`;
      default:
        return replayStatus.status;
    }
  };

  const getStatusIcon = () => {
    switch (replayStatus.status) {
      case "running":
        return <Loader2 className="w-4 h-4 animate-spin" />;
      case "completed":
        return <CheckCircle className="w-4 h-4" />;
      case "error":
        return <AlertCircle className="w-4 h-4" />;
      default:
        return <Activity className="w-4 h-4" />;
    }
  };

  return (
    <div className="min-h-screen bg-black text-white p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <Button
              variant="outline"
              onClick={() => navigate("/")}
              className="border-gray-700 bg-gray-800 hover:bg-gray-700"
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Home
            </Button>
            <h1 className="text-3xl font-bold">Dataset Replay</h1>
          </div>
          <div className={`flex items-center space-x-2 ${getStatusColor()}`}>
            {getStatusIcon()}
            <span className="text-sm font-medium">{getStatusText()}</span>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex space-x-1 bg-gray-900 p-1 rounded-lg">
          <button
            onClick={() => setActiveTab("config")}
            className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
              activeTab === "config"
                ? "bg-orange-500 text-white"
                : "text-gray-400 hover:text-white hover:bg-gray-800"
            }`}
          >
            <Settings className="w-4 h-4 mr-2 inline" />
            Configuration
          </button>
          <button
            onClick={() => setActiveTab("monitoring")}
            className={`flex-1 py-2 px-4 rounded-md text-sm font-medium transition-colors ${
              activeTab === "monitoring"
                ? "bg-orange-500 text-white"
                : "text-gray-400 hover:text-white hover:bg-gray-800"
            }`}
          >
            <Activity className="w-4 h-4 mr-2 inline" />
            Monitoring
          </button>
        </div>

        {/* Configuration Tab */}
        {activeTab === "config" && (
          <div className="space-y-6">
            <Card className="bg-gray-900 border-gray-800">
              <CardHeader>
                <CardTitle className="text-white flex items-center">
                  <Settings className="w-5 h-5 mr-2" />
                  Replay Configuration
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Robot Configuration */}
                  <div className="space-y-4">
                    <h3 className="text-lg font-semibold text-gray-300">
                      Robot Configuration
                    </h3>
                    <div className="space-y-4">
                      <div>
                        <Label className="text-gray-300">Robot Type</Label>
                        <Select
                          value={replayConfig.robot_type}
                          onValueChange={(value) =>
                            updateConfig("robot_type", value)
                          }
                        >
                          <SelectTrigger className="bg-gray-800 border-gray-700 text-white">
                            <SelectValue placeholder="Select robot type" />
                          </SelectTrigger>
                          <SelectContent className="bg-gray-800 border-gray-700">
                            {robotTypes.map((robotType) => (
                              <SelectItem
                                key={robotType.value}
                                value={robotType.value}
                                className="text-white hover:bg-gray-700"
                              >
                                {robotType.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-gray-500 mt-1">
                          Select the robot type that matches your hardware
                        </p>
                      </div>
                      <div>
                        <Label className="text-gray-300">Robot Port</Label>
                        <Input
                          value={replayConfig.robot_port}
                          onChange={(e) =>
                            updateConfig("robot_port", e.target.value)
                          }
                          className="bg-gray-800 border-gray-700 text-white"
                          placeholder="/dev/tty.usbmodem58760431541"
                        />
                      </div>
                      <div>
                        <Label className="text-gray-300">
                          Robot ID (Calibration Config)
                        </Label>
                        <Select
                          value={replayConfig.robot_id}
                          onValueChange={(value) =>
                            updateConfig("robot_id", value)
                          }
                        >
                          <SelectTrigger className="bg-gray-800 border-gray-700 text-white">
                            <SelectValue
                              placeholder={
                                isLoadingConfigs
                                  ? "Loading configs..."
                                  : "Select robot config"
                              }
                            />
                          </SelectTrigger>
                          <SelectContent className="bg-gray-800 border-gray-700">
                            {followerConfigs.map((config) => (
                              <SelectItem
                                key={config}
                                value={config}
                                className="text-white hover:bg-gray-700"
                              >
                                {config}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <p className="text-xs text-gray-500 mt-1">
                          Select from available follower calibration configs
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Dataset Configuration */}
                  <div className="space-y-4">
                    <h3 className="text-lg font-semibold text-gray-300">
                      Dataset Configuration
                    </h3>
                    <div className="space-y-4">
                      <div>
                        <Label className="text-gray-300">
                          Dataset Repository ID{" "}
                          <span className="text-red-400">*</span>
                        </Label>
                        <Input
                          value={replayConfig.dataset_repo_id}
                          onChange={(e) =>
                            updateConfig("dataset_repo_id", e.target.value)
                          }
                          className="bg-gray-800 border-gray-700 text-white"
                          placeholder="your-hf-user/dataset-name"
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          HuggingFace repository ID (format:
                          username/dataset-name, no spaces)
                        </p>
                      </div>
                      <div>
                        <Label className="text-gray-300">Episode Number</Label>
                        <Input
                          type="number"
                          value={replayConfig.episode}
                          onChange={(e) =>
                            updateConfig(
                              "episode",
                              parseInt(e.target.value) || 0
                            )
                          }
                          className="bg-gray-800 border-gray-700 text-white"
                          min="0"
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Choose which episode to replay (0-based index)
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Control Buttons */}
                <div className="flex space-x-4 pt-4 border-t border-gray-800">
                  <Button
                    onClick={handleStartReplay}
                    disabled={replayStatus.replay_active || isStartingReplay}
                    className="bg-green-500 hover:bg-green-600 text-white"
                  >
                    {isStartingReplay ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Play className="w-4 h-4 mr-2" />
                    )}
                    Start Replay
                  </Button>
                  <Button
                    onClick={handleStopReplay}
                    disabled={!replayStatus.replay_active}
                    variant="destructive"
                  >
                    <Square className="w-4 h-4 mr-2" />
                    Stop Replay
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Monitoring Tab */}
        {activeTab === "monitoring" && (
          <div className="space-y-6">
            <Card className="bg-gray-900 border-gray-800">
              <CardHeader>
                <CardTitle className="text-white flex items-center">
                  <FileText className="w-5 h-5 mr-2" />
                  Replay Logs
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div
                  ref={logContainerRef}
                  className="bg-black p-4 rounded-lg h-96 overflow-y-auto font-mono text-sm"
                >
                  {logs.length === 0 ? (
                    <div className="text-gray-500 text-center py-8">
                      No logs available. Start a replay session to see logs.
                    </div>
                  ) : (
                    logs.map((log, index) => (
                      <div key={index} className="mb-1">
                        <span className="text-gray-500">
                          {new Date(log.timestamp).toLocaleTimeString()}
                        </span>
                        <span className="ml-2 text-green-400">
                          {log.message}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Status Information */}
            {replayStatus.replay_active && (
              <Card className="bg-gray-900 border-gray-800">
                <CardHeader>
                  <CardTitle className="text-white flex items-center">
                    <Activity className="w-5 h-5 mr-2" />
                    Current Replay Session
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <p className="text-gray-400 text-sm">Robot Type</p>
                      <p className="text-white font-medium">
                        {replayStatus.robot_type}
                      </p>
                    </div>
                    <div>
                      <p className="text-gray-400 text-sm">Dataset</p>
                      <p className="text-white font-medium">
                        {replayStatus.dataset_repo_id}
                      </p>
                    </div>
                    <div>
                      <p className="text-gray-400 text-sm">Episode</p>
                      <p className="text-white font-medium">
                        {replayStatus.episode}
                      </p>
                    </div>
                    <div>
                      <p className="text-gray-400 text-sm">Status</p>
                      <p className={`font-medium ${getStatusColor()}`}>
                        {getStatusText()}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default Replay;
