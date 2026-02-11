import http.server
import ssl
import socket

server_address = ('0.0.0.0', 8000)
httpd = http.server.HTTPServer(server_address, http.server.SimpleHTTPRequestHandler)

try:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    
    # Get local IP for display
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f"Secure Server running at: https://{local_ip}:8000")
    print(f"(Also accessible at: https://localhost:8000)")
    print("NOTE: You will see a security warning in the browser. Click 'Advanced' -> 'Proceed' to continue.")
    
    httpd.serve_forever()
except FileNotFoundError:
    print("Error: cert.pem or key.pem not found!")
    print("   Run 'python generate_cert.py' first.")
