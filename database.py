from typing import Any, Dict, List, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DATABASE_NAME

# Strip accidental surrounding quotes/whitespace from env var
_clean_uri = MONGO_URI.strip().strip('"').strip("'")
client = AsyncIOMotorClient(_clean_uri, serverSelectionTimeoutMS=4000)
db = client[DATABASE_NAME]

# Global flag indicating whether remote MongoDB is reachable & authenticated
_mongo_available = True


class _InsertOneResult:
    def __init__(self, inserted_id: Any):
        self.inserted_id = inserted_id


class _UpdateResult:
    def __init__(self, matched_count: int, modified_count: int, upserted_id: Any = None):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


def _doc_matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    if not query:
        return True
    for k, v in query.items():
        if k == "$or" and isinstance(v, list):
            if not any(_doc_matches(doc, sub_q) for sub_q in v):
                return False
            continue

        if isinstance(v, dict):
            if "$exists" in v:
                exists = k in doc and doc[k] is not None
                if exists != bool(v["$exists"]):
                    return False
                continue

        if v is None:
            if doc.get(k) is not None:
                return False
            continue

        doc_val = doc.get(k)
        if doc_val is None:
            return False

        if isinstance(doc_val, ObjectId) or isinstance(v, ObjectId):
            if str(doc_val) != str(v):
                return False
        elif doc_val != v:
            return False
    return True


class _ResilientCursor:
    def __init__(self, col: "ResilientCollection", query: Dict[str, Any], args, kwargs):
        self._col = col
        self._query = query
        self._args = args
        self._kwargs = kwargs

    async def to_list(self, length: Optional[int] = None) -> List[Dict[str, Any]]:
        global _mongo_available
        if _mongo_available:
            try:
                motor_cursor = self._col._motor_col.find(self._query, *self._args, **self._kwargs)
                return await motor_cursor.to_list(length)
            except Exception as e:
                print(f"⚠️ [DB Fallback] MongoDB error on '{self._col.name}.find.to_list': {e}")
                _mongo_available = False

        matched = [doc for doc in self._col._memory_docs if _doc_matches(doc, self._query)]
        if length is None or length < 0:
            return [dict(d) for d in matched]
        return [dict(d) for d in matched[:length]]


class ResilientCollection:
    """
    Wraps an AsyncIOMotorCollection and automatically falls back to an in-memory
    collection if MongoDB Atlas authentication or connectivity fails on Render.
    """

    def __init__(self, name: str):
        self.name = name
        self._motor_col = db[name]
        self._memory_docs: List[Dict[str, Any]] = []

    async def create_index(self, *args, **kwargs):
        global _mongo_available
        if _mongo_available:
            try:
                return await self._motor_col.create_index(*args, **kwargs)
            except Exception as e:
                print(f"⚠️ [DB Fallback] MongoDB unavailable on '{self.name}.create_index' ({e}). Using in-memory store.")
                _mongo_available = False
        return "in_memory_index"

    async def find_one(self, query: Dict[str, Any], *args, **kwargs) -> Optional[Dict[str, Any]]:
        global _mongo_available
        if _mongo_available:
            try:
                return await self._motor_col.find_one(query, *args, **kwargs)
            except Exception as e:
                print(f"⚠️ [DB Fallback] MongoDB error on '{self.name}.find_one': {e}")
                _mongo_available = False

        for doc in self._memory_docs:
            if _doc_matches(doc, query):
                return dict(doc)
        return None

    async def insert_one(self, doc: Dict[str, Any], *args, **kwargs) -> _InsertOneResult:
        global _mongo_available
        if _mongo_available:
            try:
                return await self._motor_col.insert_one(doc, *args, **kwargs)
            except Exception as e:
                print(f"⚠️ [DB Fallback] MongoDB error on '{self.name}.insert_one': {e}")
                _mongo_available = False

        new_doc = dict(doc)
        if "_id" not in new_doc or new_doc["_id"] is None:
            new_doc["_id"] = ObjectId()
        self._memory_docs.append(new_doc)
        return _InsertOneResult(new_doc["_id"])

    async def update_one(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        upsert: bool = False,
        *args,
        **kwargs,
    ) -> _UpdateResult:
        global _mongo_available
        if _mongo_available:
            try:
                return await self._motor_col.update_one(query, update, upsert=upsert, *args, **kwargs)
            except Exception as e:
                print(f"⚠️ [DB Fallback] MongoDB error on '{self.name}.update_one': {e}")
                _mongo_available = False

        set_fields = update.get("$set", {})
        for doc in self._memory_docs:
            if _doc_matches(doc, query):
                doc.update(set_fields)
                return _UpdateResult(matched_count=1, modified_count=1)

        if upsert:
            new_doc: Dict[str, Any] = {}
            for k, v in query.items():
                if not k.startswith("$") and not isinstance(v, dict):
                    new_doc[k] = v
            new_doc.update(set_fields)
            if "_id" not in new_doc or new_doc["_id"] is None:
                new_doc["_id"] = ObjectId()
            self._memory_docs.append(new_doc)
            return _UpdateResult(matched_count=0, modified_count=0, upserted_id=new_doc["_id"])

        return _UpdateResult(matched_count=0, modified_count=0)

    def find(self, query: Optional[Dict[str, Any]] = None, *args, **kwargs):
        return _ResilientCursor(self, query or {}, args, kwargs)


# Collections (automatically resilient to MongoDB Atlas auth/connection issues)
users_collection = ResilientCollection("users")          # Mobile users (client devices)
admins_collection = ResilientCollection("admins")        # Master controllers / admins
devices_collection = ResilientCollection("devices")      # Registered device codes and presence
otps_collection = ResilientCollection("otps")            # Dynamic OTP verification records
support_collection = ResilientCollection("support")      # Support tickets
settings_collection = ResilientCollection("settings")    # Terms, App links, Charges, etc.
plans_collection = ResilientCollection("plans")          # Plans catalog


async def init_db_indexes():
    try:
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
        if _mongo_available:
            print(f"✅ MongoDB connected successfully to database: '{DATABASE_NAME}'")
        else:
            print("✅ FastAPI initialized with Resilient In-Memory Database Fallback")
    except Exception as e:
        print(f"⚠️ Database initialization notice ({e}) — continuing with In-Memory Fallback.")
