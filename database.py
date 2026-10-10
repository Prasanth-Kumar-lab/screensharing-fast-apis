from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DATABASE_NAME

client = AsyncIOMotorClient(MONGO_URI)
db = client[DATABASE_NAME]

# Collections
users_collection = db["users"]          # Mobile users (client devices)
admins_collection = db["admins"]        # Master controllers / admins
devices_collection = db["devices"]      # Registered device codes and presence
otps_collection = db["otps"]            # Dynamic OTP verification records
support_collection = db["support"]      # Support tickets
settings_collection = db["settings"]    # Terms, App links, Charges, etc.
plans_collection = db["plans"]          # Plans catalog

async def init_db_indexes():
    # Unique indexes
    await users_collection.create_index("phoneNumber", unique=True)
    await admins_collection.create_index("phoneNumber", unique=True)
    await devices_collection.create_index("deviceConnectionCode", unique=True)
    await otps_collection.create_index("phoneNumber")
    
    # Initialize default settings if not exists
    existing_settings = await settings_collection.find_one({"_id": "app_settings"})
    if not existing_settings:
        await settings_collection.insert_one({
            "_id": "app_settings",
            "termsAndCondition": "Terms and conditions for screen sharing.",
            "privacyPolicy": "Privacy policy details.",
            "about": "Remote Screen Sharing Application.",
            "charges": {"gst": "18", "platFormFree": "0"},
            "appLinks": {
                "title": "Screen Sharing System",
                "subTitle": "Connect & Share effortlessly",
                "applink": "https://example.com/download",
                "buttonText": "Download Now"
            }
        })
    print(f"MongoDB connected successfully to database: '{DATABASE_NAME}'")
