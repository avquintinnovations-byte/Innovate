from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import datetime
import socket
import ipaddress

def get_local_ip():
    """Get this machine's local network IP so the cert works when opening via IP on phone."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())

def generate_self_signed_cert():
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"My Company"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])
    
    # Include localhost and this machine's IP so phone can connect via https://YOUR_IP:8000
    san_names = [x509.DNSName(u"localhost"), x509.DNSName(u"127.0.0.1")]
    try:
        local_ip = get_local_ip()
        san_names.append(x509.IPAddress(ipaddress.IPv4Address(local_ip)))
        print(f"Including IP in certificate: {local_ip}")
    except Exception as e:
        print(f"Could not add IP to cert: {e}")
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=10)
    ).add_extension(
        x509.SubjectAlternativeName(san_names),
        critical=False,
    ).sign(key, hashes.SHA256())
    
    # Write our certificate out to disk.
    with open("cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
        
    # Write our key out to disk.
    with open("key.pem", "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    
    print("Certificate (cert.pem) and Key (key.pem) generated successfully.")

if __name__ == "__main__":
    try:
        generate_self_signed_cert()
    except ImportError:
        print("Cryptography library not found. Installing...")
        import subprocess
        subprocess.check_call(["pip", "install", "cryptography"])
        print("Please run this script again.")



