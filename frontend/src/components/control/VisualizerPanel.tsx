import React from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import UrdfViewer from "../UrdfViewer";
import UrdfProcessorInitializer from "../UrdfProcessorInitializer";

interface VisualizerPanelProps {
  onGoBack: () => void;
  className?: string;
}

const VisualizerPanel: React.FC<VisualizerPanelProps> = ({
  onGoBack,
  className,
}) => {
  return (
    <div
      className={cn(
        "w-full lg:w-1/2 p-2 sm:p-4 space-y-4 flex flex-col",
        className
      )}
    >
      <div className="bg-gray-900 rounded-lg p-4 flex-1 flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <img
              src="/lovable-uploads/5e648747-34b7-4d8f-93fd-4dbd00aeeefc.png"
              alt="LiveLab Logo"
              className="h-8 w-8"
            />
            <h2 className="text-xl font-bold text-white">LiveLab</h2>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onGoBack}
            className="text-gray-400 hover:text-white hover:bg-gray-800"
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
        </div>
        <div className="flex-1 bg-black rounded border border-gray-800 min-h-[50vh] lg:min-h-0">
          {/* <Canvas camera={{ position: [5, 3, 5], fov: 50 }}>
            <ambientLight intensity={0.4} />
            <directionalLight position={[10, 10, 5]} intensity={1} />
            <RobotArm />
            <OrbitControls enablePan={true} enableZoom={true} enableRotate={true} />
          </Canvas> */}
          <UrdfProcessorInitializer />
          <UrdfViewer />
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {[1, 2, 3, 4].map((cam) => (
          <div
            key={cam}
            className="aspect-video bg-gray-900 rounded border border-gray-700 flex items-center justify-center"
          >
            <span className="text-gray-400 text-sm">Camera {cam}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default VisualizerPanel;
