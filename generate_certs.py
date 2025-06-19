#!/usr/bin/env python3
"""
Generate self-signed certificates for local HTTPS development.
Required for phone camera access via WebRTC.
"""

import os
import socket
import subprocess
import sys
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import datetime
import ipaddress


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
        return "127.0.0.1"


def check_mkcert():
    """Check if mkcert is available"""
    try:
        result = subprocess.run(['mkcert', '-version'], 
                              capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def generate_with_mkcert(cert_dir, local_ip):
    """Generate certificates using mkcert (trusted by browsers)"""
    print("🔐 Using mkcert to generate trusted certificates...")
    
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    
    try:
        # Install local CA if not already done
        subprocess.run(['mkcert', '-install'], check=True, timeout=30)
        
        # Generate certificate for localhost and local IP
        cmd = [
            'mkcert', 
            '-cert-file', str(cert_path),
            '-key-file', str(key_path),
            'localhost', 
            '127.0.0.1', 
            local_ip
        ]
        
        result = subprocess.run(cmd, check=True, timeout=30, 
                              capture_output=True, text=True)
        
        print(f"✅ Certificates generated successfully:")
        print(f"   Certificate: {cert_path}")
        print(f"   Private Key: {key_path}")
        print(f"   Valid for: localhost, 127.0.0.1, {local_ip}")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ mkcert failed: {e}")
        print(f"   stdout: {e.stdout}")
        print(f"   stderr: {e.stderr}")
        return False
    except subprocess.TimeoutExpired:
        print("❌ mkcert timed out")
        return False


def generate_self_signed(cert_dir, local_ip):
    """Generate self-signed certificates using Python cryptography library"""
    print("🔐 Generating self-signed certificates...")
    
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    
    try:
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        # Create certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Development"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LeRobot Development"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])
        
        # Build subject alternative names
        san_list = [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]
        
        # Add local IP if it's different from localhost
        if local_ip != "127.0.0.1":
            try:
                san_list.append(x509.IPAddress(ipaddress.IPv4Address(local_ip)))
            except ipaddress.AddressValueError:
                print(f"⚠️ Invalid IP address: {local_ip}")
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        ).sign(private_key, hashes.SHA256())
        
        # Write private key
        with open(key_path, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ))
        
        # Write certificate
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        print(f"✅ Self-signed certificates generated:")
        print(f"   Certificate: {cert_path}")
        print(f"   Private Key: {key_path}")
        print(f"   Valid for: localhost, 127.0.0.1, {local_ip}")
        print("⚠️  Note: Self-signed certificates will show security warnings in browsers")
        print("   Consider installing mkcert for trusted certificates: https://github.com/FiloSottile/mkcert")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to generate self-signed certificate: {e}")
        return False


def main():
    """Main function to generate certificates"""
    print("🚀 Setting up HTTPS certificates for LeRobot phone camera support...")
    
    # Create certs directory
    cert_dir = Path("certs")
    cert_dir.mkdir(exist_ok=True)
    
    # Get local IP
    local_ip = get_local_ip()
    print(f"📡 Detected local IP: {local_ip}")
    
    # Check if certificates already exist
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    
    if cert_path.exists() and key_path.exists():
        response = input("📋 Certificates already exist. Regenerate? (y/N): ").strip().lower()
        if response not in ['y', 'yes']:
            print("✅ Using existing certificates")
            return
    
    # Try mkcert first, fallback to self-signed
    success = False
    
    if check_mkcert():
        success = generate_with_mkcert(cert_dir, local_ip)
    else:
        print("📦 mkcert not found. Install it for trusted certificates:")
        print("   https://github.com/FiloSottile/mkcert")
        print("   Falling back to self-signed certificates...")
    
    if not success:
        success = generate_self_signed(cert_dir, local_ip)
    
    if success:
        print("\n🎉 HTTPS setup complete!")
        print(f"💡 You can now access the frontend via: https://{local_ip}:5173")
        print("📱 Phones on the same Wi-Fi can scan QR codes to connect.")
        
        # Create HTTPS setup guide
        with open("HTTPS_SETUP.md", "w") as f:
            f.write(f"""# HTTPS Setup for Phone Camera Support

## Generated Files
- `certs/cert.pem` - SSL certificate
- `certs/key.pem` - Private key

## Usage
The frontend should automatically use HTTPS when these certificates are present.

## Access URLs
- Desktop: https://localhost:5173
- Mobile: https://{local_ip}:5173

## Security Notes
- These certificates are for development only
- Self-signed certificates will show browser warnings
- For trusted certificates, install mkcert: https://github.com/FiloSottile/mkcert

## Troubleshooting
If you see certificate errors:
1. Accept the security warning in your browser
2. For mobile devices, you may need to manually accept the certificate
3. Consider using mkcert for automatically trusted certificates

Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""")
        print("📝 Created HTTPS_SETUP.md with detailed instructions")
        
    else:
        print("❌ Failed to generate certificates")
        sys.exit(1)


if __name__ == "__main__":
    main() 
