#!/usr/bin/env python3
"""
Start the backend server with WebRTC support enabled.
This script starts both FastAPI and Socket.IO servers for WebRTC signaling.
"""

import sys
import os
import logging
import argparse

# Add the parent directory to the path so we can import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    parser = argparse.ArgumentParser(description="Start LeRobot Lab Backend with WebRTC")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")
    parser.add_argument("--https", action="store_true", help="Enable HTTPS with SSL certificates")
    parser.add_argument("--cert-file", default="certs/cert.pem", help="SSL certificate file path")
    parser.add_argument("--key-file", default="certs/key.pem", help="SSL private key file path")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"], help="Log level")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    
    args = parser.parse_args()
    
    # Set up logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info("🚀 Starting LeRobot Lab Backend with WebRTC support...")
    logger.info(f"📡 WebRTC signaling enabled")
    
    # Determine protocol based on HTTPS setting
    protocol = "https" if args.https else "http"
    logger.info(f"🌐 Server will be available at {protocol}://{args.host}:{args.port}")
    logger.info(f"🔌 Socket.IO endpoint: {protocol}://{args.host}:{args.port}/socket.io/")
    
    if args.https:
        if not os.path.exists(args.cert_file) or not os.path.exists(args.key_file):
            logger.error(f"❌ SSL certificates not found!")
            logger.error(f"   Certificate: {args.cert_file}")
            logger.error(f"   Private key: {args.key_file}")
            logger.error("💡 Generate certificates with: python generate_certs.py")
            sys.exit(1)
        logger.info(f"🔐 HTTPS enabled with certificates:")
        logger.info(f"   Certificate: {args.cert_file}")
        logger.info(f"   Private key: {args.key_file}")
    
    try:
        import uvicorn
        from app.main import main_app
        
        # Run the combined FastAPI + Socket.IO app
        uvicorn_config = {
            "host": args.host,
            "port": args.port,
            "log_level": args.log_level,
            "reload": args.reload
        }
        
        # Add SSL configuration if HTTPS is enabled
        if args.https:
            uvicorn_config.update({
                "ssl_certfile": args.cert_file,
                "ssl_keyfile": args.key_file
            })
        
        uvicorn.run(main_app, **uvicorn_config)
        
    except ImportError as e:
        logger.error(f"❌ Missing dependency: {e}")
        logger.error("📦 Please install required packages:")
        logger.error("   pip install 'fastapi[standard]' uvicorn python-socketio")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
