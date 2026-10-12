from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, unquote_plus
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DEFAULT_MONGO_URI, DATABASE_NAME


def _sanitize_mongo_uri(raw_uri: str) -> str:
    """
    Repairs common MongoDB Atlas URI issues in Render environment variables:
    1. Strips accidental 'MONGO_URI=' prefix or surrounding quotes/spaces.
    2. URL-encodes special characters (@, ?, &, :, /) inside username/password.
    3. Drops malformed query options (missing '=value') that trigger
       `pymongo.errors.InvalidURI: MongoDB URI options are key=value pairs`.
    """
    uri = (raw_uri or "").strip().strip('"').strip("'")
    if uri.upper().startswith("MONGO_URI="):
        uri = uri.split("=", 1)[1].strip().strip('"').strip("'")
    if not uri or "://" not in uri:
        return DEFAULT_MONGO_URI

    scheme, rest = uri.split("://", 1)

    # Separate credentials from host using the LAST '@' (hostname never contains '@')
    if "@" in rest:
        userinfo, host_and_path = rest.rsplit("@", 1)
        if ":" in userinfo:
            user_raw, pass_raw = userinfo.split(":", 1)
            if pass_raw.startswith("<") and pass_raw.endswith(">"):
                pass_raw = pass_raw[1:-1]
            user_enc = quote_plus(unquote_plus(user_raw))
            pass_enc = quote_plus(unquote_plus(pass_raw))
            userinfo_clean = f"{user_enc}:{pass_enc}"
        else:
            userinfo_clean = quote_plus(unquote_plus(userinfo))
        prefix = f"{scheme}://{userinfo_clean}@"
    else:
        host_and_path = rest
        prefix = f"{scheme}://"

    # Validate query string options so pymongo never raises InvalidURI
    if "?" in host_and_path:
        host_part, query_part = host_and_path.split("?", 1)
        if "/" not in host_part:
            host_part = f"{host_part}/"
        valid_pairs = []
        for token in query_part.replace(";", "&").split("&"):
            token = token.strip()
            if not token or "=" not in token:
                continue
            k, v = token.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                valid_pairs.append(f"{k}={v}")
        if valid_pairs:
            return f"{prefix}{host_part}?{'&'.join(valid_pairs)}"
        return f"{prefix}{host_part}"

    return f"{prefix}{host_and_path}"


# Global flag indicating whether remote MongoDB is reachable & authenticated
_mongo_available = True
client: Optional[AsyncIOMotorClient] = None
db = None

try:
    _clean_uri = _sanitize_mongo_uri(MONGO_URI)
    client = AsyncIOMotorClient(_clean_uri, serverSelectionTimeoutMS=5000)
    db = client[DATABASE_NAME]
except Exception as _uri_err:
    print(f"⚠️ Notice: Env MONGO_URI invalid ({_uri_err}), using verified DEFAULT_MONGO_URI.")
    try:
        client = AsyncIOMotorClient(DEFAULT_MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
    except Exception as _fallback_err:
        print(f"⚠️ [DB Fallback] MongoDB unavailable ({_fallback_err}). Switching to In-Memory store.")
        _mongo_available = False
        client = None
        db = None


def _switch_to_default_mongo() -> bool:
    """If env MONGO_URI had old/bad credentials on Render, switch to verified DEFAULT_MONGO_URI."""
    global client, db, _clean_uri
    if _clean_uri == DEFAULT_MONGO_URI:
        return False
    try:
        print("🔄 Switching from env MONGO_URI to verified DEFAULT_MONGO_URI...")
        _clean_uri = DEFAULT_MONGO_URI
        client = AsyncIOMotorClient(DEFAULT_MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client[DATABASE_NAME]
        for col in ALL_COLLECTIONS:
            col._motor_col = db[col.name]
        return True
    except Exception as e:
        print(f"⚠️ Failed to switch to DEFAULT_MONGO_URI: {e}")
        return False


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
        if _mongo_available and self._col._motor_col is not None:
            try:
                motor_cursor = self._col._motor_col.find(self._query, *self._args, **self._kwargs)
                return await motor_cursor.to_list(length)
            except Exception as e:
                if _switch_to_default_mongo():
                    try:
                        motor_cursor = self._col._motor_col.find(self._query, *self._args, **self._kwargs)
                        return await motor_cursor.to_list(length)
                    except Exception:
                        pass
                print(f"⚠️ [DB Fallback] MongoDB error on '{self._col.name}.find.to_list': {e}")
                _mongo_available = False

        matched = [doc for doc in self._col._memory_docs if _doc_matches(doc, self._query)]
        if length is None or length < 0:
            return [dict(d) for d in matched]
        return [dict(d) for d in matched[:length]]


class ResilientCollection:
    def __init__(self, name: str):
        self.name = name
        self._motor_col = db[name] if db is not None else None
        self._memory_docs: List[Dict[str, Any]] = []

    async def create_index(self, *args, **kwargs):
        global _mongo_available
        if _mongo_available and self._motor_col is not None:
            try:
                return await self._motor_col.create_index(*args, **kwargs)
            except Exception as e:
                if _switch_to_default_mongo():
                    try:
                        return await self._motor_col.create_index(*args, **kwargs)
                    except Exception as e2:
                        e = e2
                print(f"⚠️ [DB Fallback] MongoDB unavailable on '{self.name}.create_index' ({e}). Using in-memory store.")
                _mongo_available = False
        return "in_memory_index"

    async def find_one(self, query: Dict[str, Any], *args, **kwargs) -> Optional[Dict[str, Any]]:
        global _mongo_available
        if _mongo_available and self._motor_col is not None:
            try:
                return await self._motor_col.find_one(query, *args, **kwargs)
            except Exception as e:
                if _switch_to_default_mongo():
                    try:
                        return await self._motor_col.find_one(query, *args, **kwargs)
                    except Exception:
                        pass
                print(f"⚠️ [DB Fallback] MongoDB error on '{self.name}.find_one': {e}")
                _mongo_available = False

        for doc in self._memory_docs:
            if _doc_matches(doc, query):
                return dict(doc)
        return None

    async def insert_one(self, doc: Dict[str, Any], *args, **kwargs) -> _InsertOneResult:
        global _mongo_available
        if _mongo_available and self._motor_col is not None:
            try:
                return await self._motor_col.insert_one(doc, *args, **kwargs)
            except Exception as e:
                if _switch_to_default_mongo():
                    try:
                        return await self._motor_col.insert_one(doc, *args, **kwargs)
                    except Exception:
                        pass
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
        if _mongo_available and self._motor_col is not None:
            try:
                return await self._motor_col.update_one(query, update, upsert=upsert, *args, **kwargs)
            except Exception as e:
                if _switch_to_default_mongo():
                    try:
                        return await self._motor_col.update_one(query, update, upsert=upsert, *args, **kwargs)
                    except Exception:
                        pass
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


# Collections
users_collection = ResilientCollection("users")          # Mobile users (client devices)
admins_collection = ResilientCollection("admins")        # Master controllers / admins
devices_collection = ResilientCollection("devices")      # Registered device codes and presence
otps_collection = ResilientCollection("otps")            # Dynamic OTP verification records
support_collection = ResilientCollection("support")      # Support tickets
settings_collection = ResilientCollection("settings")    # Terms, App links, Charges, etc.
plans_collection = ResilientCollection("plans")          # Plans catalog

ALL_COLLECTIONS = [
    users_collection,
    admins_collection,
    devices_collection,
    otps_collection,
    support_collection,
    settings_collection,
    plans_collection,
]


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
            print(f"✅ MongoDB Atlas connected successfully to database: '{DATABASE_NAME}'")
        else:
            print("✅ FastAPI initialized with Resilient In-Memory Database Fallback")
    except Exception as e:
        print(f"⚠️ Database initialization notice ({e}) — continuing with In-Memory Fallback.")
