"""
Frontend-only script for LeLab
Clones and runs the frontend development server
"""

import os
import subprocess
import logging
import webbrowser
import time
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_REPO_URL = "https://github.com/amtellezfernandez/lelab-frontend-dev.git"
FRONTEND_DIR_NAME = "lelab-frontend-dev"


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


def start_frontend_dev_server(frontend_path):
    """Start the frontend development server"""
    logger.info("🎨 Starting Vite frontend development server...")

    try:
        # Start the dev server
        process = subprocess.Popen(["npm", "run", "dev"], cwd=frontend_path)

        # Wait a moment for server to start
        time.sleep(3)

        # Auto-open browser
        logger.info("🌐 Opening browser...")
        webbrowser.open("http://localhost:8080")

        # Wait for the process
        process.wait()

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to start frontend server: {e}")
        return False
    except FileNotFoundError:
        logger.error("❌ npm not found. Please install Node.js and npm")
        return False
    except KeyboardInterrupt:
        logger.info("🛑 Frontend server stopped by user")
        if process:
            process.terminate()
        return True


def main():
    """Main function to run frontend only"""
    logger.info("🎨 Starting LeLab frontend development server...")

    # Get or clone frontend
    frontend_path = get_frontend_path()
    if not frontend_path:
        frontend_path = clone_frontend()
        if not frontend_path:
            logger.error("❌ Failed to get frontend repository")
            return

    # Install dependencies
    if not install_frontend_deps(frontend_path):
        logger.error("❌ Failed to install frontend dependencies")
        return

    # Start dev server
    start_frontend_dev_server(frontend_path)


if __name__ == "__main__":
    main()
