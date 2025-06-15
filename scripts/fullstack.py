"""
Fullstack script for LeLab
Runs both backend and frontend development servers
Frontend starts detached first, then backend
"""

import os
import subprocess
import logging
import webbrowser
import time
import signal
import sys
import threading
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_REPO_URL = "https://github.com/amtellezfernandez/lelab-frontend-dev.git"
FRONTEND_DIR_NAME = "lelab-frontend-dev"

# Global variables to track processes
frontend_process = None
backend_process = None


def get_frontend_path():
    """Get the path to the frontend directory"""
    # Check if frontend exists in parent directory (same level as leLab)
    parent_dir = Path(__file__).parent.parent.parent
    frontend_path = parent_dir / FRONTEND_DIR_NAME

    if frontend_path.exists():
        logger.info(f"✅ Found existing frontend at: {frontend_path}")
        return frontend_path

    return None


def clone_frontend():
    """Clone the frontend repository"""
    parent_dir = Path(__file__).parent.parent.parent
    frontend_path = parent_dir / FRONTEND_DIR_NAME

    logger.info(f"📥 Cloning frontend repository to: {frontend_path}")

    try:
        subprocess.run(
            ["git", "clone", FRONTEND_REPO_URL, str(frontend_path)],
            check=True,
            cwd=parent_dir,
        )
        logger.info("✅ Frontend repository cloned successfully")
        return frontend_path
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to clone frontend repository: {e}")
        return None
    except FileNotFoundError:
        logger.error("❌ git not found. Please install git")
        return None


def install_frontend_deps(frontend_path):
    """Install frontend dependencies"""
    logger.info("📦 Installing frontend dependencies...")

    try:
        subprocess.run(["npm", "install"], check=True, cwd=frontend_path)
        logger.info("✅ Frontend dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to install frontend dependencies: {e}")
        return False
    except FileNotFoundError:
        logger.error("❌ npm not found. Please install Node.js and npm")
        return False


def start_frontend_detached(frontend_path):
    """Start the frontend development server detached"""
    global frontend_process
    logger.info("🎨 Starting Vite frontend development server (detached)...")

    try:
        # Start frontend detached
        frontend_process = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=frontend_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent
        )

        logger.info(f"✅ Frontend server started (PID: {frontend_process.pid})")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to start frontend server: {e}")
        return False


def wait_for_frontend_ready():
    """Wait for frontend server to be ready"""
    logger.info("⏳ Waiting for frontend server to be ready...")

    import socket
    import errno

    max_attempts = 30  # 30 seconds max
    for attempt in range(max_attempts):
        try:
            # Try to connect to the frontend port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("localhost", 8080))  # Vite default port
            sock.close()

            if result == 0:
                logger.info("✅ Frontend server is ready!")
                return True

        except Exception:
            pass

        time.sleep(1)
        if attempt % 5 == 0:
            logger.info(f"⏳ Still waiting for frontend... ({attempt}s)")

    logger.warning("⚠️ Frontend server didn't respond within 30 seconds")
    return False


def start_backend_detached():
    """Start the backend server detached"""
    global backend_process
    logger.info("🚀 Starting FastAPI backend server (detached)...")

    try:
        backend_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--reload",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent
        )

        logger.info(f"✅ Backend server started (PID: {backend_process.pid})")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to start backend server: {e}")
        return False


def wait_for_backend_ready():
    """Wait for backend server to be ready"""
    logger.info("⏳ Waiting for backend server to be ready...")

    import socket

    max_attempts = 15  # 15 seconds max
    for attempt in range(max_attempts):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("localhost", 8000))
            sock.close()

            if result == 0:
                logger.info("✅ Backend server is ready!")
                return True

        except Exception:
            pass

        time.sleep(1)
        if attempt % 5 == 0:
            logger.info(f"⏳ Still waiting for backend... ({attempt}s)")

    logger.warning("⚠️ Backend server didn't respond within 15 seconds")
    return False


def is_process_running(process):
    """Check if a process is still running"""
    if process is None:
        return False
    try:
        return process.poll() is None
    except:
        return False


def cleanup_processes():
    """Clean up all processes"""
    global backend_process, frontend_process

    logger.info("🛑 Shutting down servers...")

    processes_to_kill = []

    if backend_process:
        processes_to_kill.append(("Backend", backend_process))

    if frontend_process:
        processes_to_kill.append(("Frontend", frontend_process))

    for name, process in processes_to_kill:
        try:
            if is_process_running(process):
                logger.info(f"🔄 Stopping {name} server (PID: {process.pid})...")

                # Try to kill the process group (handles child processes)
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except:
                    process.terminate()

                # Wait for graceful shutdown
                try:
                    process.wait(timeout=5)
                    logger.info(f"✅ {name} server stopped gracefully")
                except subprocess.TimeoutExpired:
                    logger.warning(
                        f"⚠️ {name} server didn't stop gracefully, force killing..."
                    )
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except:
                        process.kill()
                    logger.info(f"✅ {name} server force stopped")
        except Exception as e:
            logger.error(f"❌ Error stopping {name}: {e}")

    logger.info("✅ All servers stopped")


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info("\n🛑 Received shutdown signal...")
    cleanup_processes()
    sys.exit(0)


def main():
    """Main function to run both backend and frontend"""
    logger.info("🚀 Starting LeLab fullstack development servers...")

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Get or clone frontend
        frontend_path = get_frontend_path()
        if not frontend_path:
            frontend_path = clone_frontend()
            if not frontend_path:
                logger.error("❌ Failed to get frontend repository")
                return

        # Install frontend dependencies
        if not install_frontend_deps(frontend_path):
            logger.error("❌ Failed to install frontend dependencies")
            return

        # Step 1: Start frontend detached
        if not start_frontend_detached(frontend_path):
            logger.error("❌ Failed to start frontend server")
            return

        # Step 2: Wait for frontend to be ready
        if not wait_for_frontend_ready():
            logger.error("❌ Frontend server not ready")
            cleanup_processes()
            return

        # Step 3: Start backend detached
        if not start_backend_detached():
            logger.error("❌ Failed to start backend server")
            cleanup_processes()
            return

        # Step 4: Wait for backend to be ready
        if not wait_for_backend_ready():
            logger.error("❌ Backend server not ready")
            cleanup_processes()
            return

        # Step 5: Open browser
        logger.info("🌐 Opening browser...")
        webbrowser.open("http://localhost:8080")

        # Success!
        logger.info("✅ Both servers are running!")
        logger.info("📱 Backend: http://localhost:8000")
        logger.info("🌐 Frontend: http://localhost:8080")
        logger.info("🛑 Press Ctrl+C to stop both servers")

        # Keep the script running and monitor processes
        while True:
            time.sleep(5)

            # Check if processes are still running
            if not is_process_running(frontend_process):
                logger.error("❌ Frontend process died")
                break
            if not is_process_running(backend_process):
                logger.error("❌ Backend process died")
                break

    except KeyboardInterrupt:
        logger.info("\n🛑 Received interrupt signal")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
    finally:
        cleanup_processes()


if __name__ == "__main__":
    main()
