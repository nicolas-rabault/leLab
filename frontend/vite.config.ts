import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: "::",
    port: 8080,
    proxy: {
      "/start-training": "http://localhost:8000",
      "/stop-training": "http://localhost:8000",
      "/training-status": "http://localhost:8000",
      "/training-logs": "http://localhost:8000",
      "/start-recording": "http://localhost:8000",
      "/stop-recording": "http://localhost:8000",
      "/recording-status": "http://localhost:8000",
      "/recording-exit-early": "http://localhost:8000",
      "/recording-rerecord-episode": "http://localhost:8000",
      "/start-calibration": "http://localhost:8000",
      "/stop-calibration": "http://localhost:8000",
      "/calibration-status": "http://localhost:8000",
      "/calibration-input": "http://localhost:8000",
      "/calibration-debug": "http://localhost:8000",
      "/calibration-configs": "http://localhost:8000",
      "/move-arm": "http://localhost:8000",
      "/stop-teleoperation": "http://localhost:8000",
      "/teleoperation-status": "http://localhost:8000",
      "/joint-positions": "http://localhost:8000",
      "/get-configs": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
  plugins: [react(), mode === "development" && componentTagger()].filter(
    Boolean
  ),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));
