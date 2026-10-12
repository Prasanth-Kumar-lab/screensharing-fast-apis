import os

# MongoDB Configuration
DEFAULT_MONGO_URI = "mongodb+srv://prasanthkumartera_db_user:VwUlBKW6Jx47cD66@cluster0.im2fcm0.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
MONGO_URI = os.getenv("MONGO_URI", DEFAULT_MONGO_URI)
DATABASE_NAME = os.getenv("DATABASE_NAME", "screensharing_db")

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "screenshare_super_secret_jwt_key_2026_antigravity_token")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

# Signaling & WebRTC Settings
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.getenv("PORT", 8000))
