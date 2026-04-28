"""
Backend-only script for LeLab
Runs just the FastAPI server with uvicorn
"""

import logging
import uvicorn
import ssl
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_ssl_context(cert_file: str, key_file: str):
    """Create an SSL context optimized for iOS compatibility"""
    try:
        # Create SSL context with iOS-compatible settings
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(cert_file, key_file)
        
        # Set minimum and maximum TLS versions for iOS compatibility
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_context.maximum_version = ssl.TLSVersion.TLSv1_3
        
        # Use iOS-compatible cipher suites
        ssl_context.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS')
        
        # Additional iOS-friendly settings
        ssl_context.check_hostname = False  # For self-signed certificates
        ssl_context.verify_mode = ssl.CERT_NONE  # For self-signed certificates
        
        logger.info("✅ SSL context created with iOS-compatible settings")
        return ssl_context
        
    except Exception as e:
        logger.error(f"❌ Failed to create SSL context: {e}")
        return None


def main():
    """Start the FastAPI backend server only"""
    logger.info("🚀 Starting LeLab FastAPI backend server...")
    
    # Check if SSL certificates exist
    cert_file = "cert.pem"
    key_file = "key.pem"
    
    if os.path.exists(cert_file) and os.path.exists(key_file):
        logger.info("🔒 SSL certificates found, starting HTTPS server...")
        
        # Try to create iOS-compatible SSL context
        ssl_context = create_ssl_context(cert_file, key_file)
        
        if ssl_context:
            logger.info("🍎 Using iOS-compatible SSL configuration")
            uvicorn.run(
                "app.main:app", 
                host="0.0.0.0", 
                port=8000, 
                reload=True, 
                log_level="info",
                ssl_context=ssl_context
            )
        else:
            logger.warning("⚠️ Falling back to basic SSL configuration")
            uvicorn.run(
                "app.main:app", 
                host="0.0.0.0", 
                port=8000, 
                reload=True, 
                log_level="info",
                ssl_keyfile=key_file,
                ssl_certfile=cert_file
            )
    else:
        logger.info("🔓 No SSL certificates found, starting HTTP server...")
        uvicorn.run(
            "app.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info"
        )


if __name__ == "__main__":
    main()
