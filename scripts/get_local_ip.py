import socket

hostname = socket.gethostname()
ip = socket.gethostbyname(hostname)
print(f"\nYour LAN IP: {ip}")
print(f"\nPaste this into frontend/mobile/.env.development:")
print(f"EXPO_PUBLIC_API_URL=http://{ip}:8000")
print(f"\nAnd into FastAPI .env CORS_ORIGINS:")
print(f"CORS_ORIGINS=http://localhost:3000,http://{ip}:3000")
