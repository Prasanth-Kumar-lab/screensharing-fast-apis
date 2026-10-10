import os

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "screensharing_db")

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "screenshare_super_secret_jwt_key_2026_antigravity_token")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

# Signaling & WebRTC Settings
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.getenv("PORT", 8000))
