#!/usr/bin/env python3
"""
Startup script for LeRobot with phone camera support.
This script starts both frontend and backend with HTTPS enabled.
"""

import os
import sys
import subprocess
import time
import socket
from pathlib import Path

def get_local_ip():
    """Get the local network IP address"""
    try:
        # Connect to a remote address (doesn't actually establish connection)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "localhost"

def check_certificates():
    """Check if SSL certificates exist"""
    cert_path = Path("certs/cert.pem")
    key_path = Path("certs/key.pem")
    
    if not cert_path.exists() or not key_path.exists():
        print("❌ SSL certificates not found!")
        print("📋 Run 'python generate_certs.py' first to set up HTTPS")
        return False
    
    print("✅ SSL certificates found")
    return True

def start_backend():
    """Start the FastAPI backend with HTTPS"""
    print("🚀 Starting backend with HTTPS...")
    
    # Start backend with SSL certificates
    backend_cmd = [
        "uvicorn", 
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--ssl-keyfile", "certs/key.pem",
        "--ssl-certfile", "certs/cert.pem",
        "--reload"
    ]
    
    try:
        backend_process = subprocess.Popen(
            backend_cmd,
            cwd=Path("."),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        print("✅ Backend starting...")
        return backend_process
    except Exception as e:
        print(f"❌ Failed to start backend: {e}")
        return None

def start_frontend():
    """Start the Vite frontend with HTTPS"""
    print("🎨 Starting frontend with HTTPS...")
    
    frontend_dir = Path("leLab-space")
    if not frontend_dir.exists():
        print("❌ Frontend directory not found!")
        return None
    
    try:
        # Install dependencies if needed
        if not (frontend_dir / "node_modules").exists():
            print("📦 Installing frontend dependencies...")
            subprocess.run(["npm", "install"], cwd=frontend_dir, check=True)
        
        # Start Vite dev server (will use HTTPS automatically if certificates exist)
        frontend_process = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=frontend_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        print("✅ Frontend starting...")
        return frontend_process
    except Exception as e:
        print(f"❌ Failed to start frontend: {e}")
        return None

def print_access_info():
    """Print access information"""
    local_ip = get_local_ip()
    
    print("\n🎉 LeRobot with Phone Camera Support is running!")
    print("=" * 50)
    print(f"🖥️  Desktop Access:")
    print(f"   https://localhost:5173")
    print(f"   https://{local_ip}:5173")
    print(f"")
    print(f"📱 Mobile Access:")
    print(f"   https://{local_ip}:5173")
    print(f"   (Scan QR codes in camera configuration)")
    print(f"")
    print(f"🔧 API Backend:")
    print(f"   https://localhost:8000")
    print(f"   https://{local_ip}:8000")
    print("=" * 50)
    print("💡 To add a phone camera:")
    print("1. Go to Recording page")
    print("2. Select 'Phone Camera' from dropdown")
    print("3. Give it a name and click 'Add Camera'")
    print("4. Scan the QR code with your phone")
    print("5. Start streaming from your phone")
    print("")
    print("⚠️  Note: You may need to accept SSL certificate warnings")
    print("📋 For trusted certificates, install mkcert and rerun generate_certs.py")
    print("")
    print("🛑 Press Ctrl+C to stop all services")

def main():
    """Main function"""
    print("🚀 Starting LeRobot with Phone Camera Support...")
    
    # Check if we're in the right directory
    if not Path("app").exists():
        print("❌ Please run this script from the LeRobot root directory")
        sys.exit(1)
    
    # Check certificates
    if not check_certificates():
        print("\n🔧 Generating certificates automatically...")
        try:
            subprocess.run([sys.executable, "generate_certs.py"], check=True)
            print("✅ Certificates generated successfully!")
        except subprocess.CalledProcessError:
            print("❌ Failed to generate certificates")
            sys.exit(1)
    
    # Start services
    backend_process = start_backend()
    if not backend_process:
        sys.exit(1)
    
    # Wait a moment for backend to start
    time.sleep(3)
    
    frontend_process = start_frontend()
    if not frontend_process:
        backend_process.terminate()
        sys.exit(1)
    
    # Wait for frontend to be ready
    time.sleep(5)
    
    # Print access information
    print_access_info()
    
    try:
        # Keep running and monitor processes
        while True:
            time.sleep(1)
            
            # Check if processes are still running
            if backend_process.poll() is not None:
                print("❌ Backend process died")
                break
            
            if frontend_process.poll() is not None:
                print("❌ Frontend process died")
                break
                
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        
    finally:
        # Clean up processes
        if backend_process and backend_process.poll() is None:
            backend_process.terminate()
            backend_process.wait()
        
        if frontend_process and frontend_process.poll() is None:
            frontend_process.terminate()
            frontend_process.wait()
        
        print("✅ Shutdown complete")

if __name__ == "__main__":
    main() 
