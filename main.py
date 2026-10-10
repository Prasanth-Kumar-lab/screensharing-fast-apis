import random
import string
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json

from config import MONGO_URI, DATABASE_NAME, SERVER_HOST, SERVER_PORT
from database import (
    init_db_indexes,
    users_collection,
    admins_collection,
    devices_collection,
    otps_collection,
    support_collection,
    settings_collection,
    plans_collection,
)
from auth import create_access_token, get_current_user
from schemas import (
    SendOtpRequest,
    VerifyOtpRequest,
    MasterRegisterRequest,
    UserRegisterRequest,
    CheckCodeRequest,
    ConnectDeviceRequest,
    UpdateDeviceRequest,
    SupportTicketRequest,
)
from signaling import signaling_manager

app = FastAPI(
    title="Screen Sharing & Remote Control Fast APIs",
    description="Custom FastAPI backend with MongoDB Compass integration replacing Firebase Realtime Database and standard OTP verification.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def generate_random_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))

def generate_device_code(length: int = 6) -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choices(chars, k=length))

def serialize_doc(doc: dict) -> dict:
    if not doc:
        return {}
    res = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            res[k] = str(v)
        elif isinstance(v, datetime):
            res[k] = v.isoformat()
        elif isinstance(v, dict):
            res[k] = serialize_doc(v)
        elif isinstance(v, list):
            res[k] = [serialize_doc(i) if isinstance(i, dict) else (str(i) if isinstance(i, ObjectId) else i) for i in v]
        else:
            res[k] = v
    if "_id" in res and "id" not in res:
        res["id"] = res["_id"]
    return res

@app.on_event("startup")
async def on_startup():
    await init_db_indexes()

@app.get("/", summary="Root health check")
@app.get("/health", summary="Health check endpoint for Render and uptime monitors")
async def health_check():
    return {
        "status": "healthy",
        "service": "Screen Sharing Fast APIs",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ==============================================================================
# 1. AUTHENTICATION & DYNAMIC OTP (Sent in response for UI Snackbar)
# ==============================================================================

@app.post("/api/auth/send-otp", summary="Generate dynamic OTP and return in response for snackbar display")
async def send_otp(req: SendOtpRequest):
    phone = req.phoneNumber.strip()
    otp_code = generate_random_otp(6)
    
    # Store dynamic OTP in MongoDB
    await otps_collection.update_one(
        {"phoneNumber": phone},
        {"$set": {
            "phoneNumber": phone,
            "otp": otp_code,
            "role": req.role,
            "createdAt": datetime.now(timezone.utc)
        }},
        upsert=True
    )
    
    return {
        "success": True,
        "message": f"OTP sent successfully. Enter OTP: {otp_code}",
        "otp": otp_code,  # Displayed in UI snackbar
        "phoneNumber": phone
    }

@app.post("/api/auth/verify-otp", summary="Verify OTP and return access token without restrictions")
async def verify_otp(req: VerifyOtpRequest):
    phone = req.phoneNumber.strip()
    stored = await otps_collection.find_one({"phoneNumber": phone})
    
    if not stored or stored.get("otp") != req.otp.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OTP code"
        )
    
    role = req.role or stored.get("role", "user")
    
    # Check if already registered
    if role == "master":
        account = await admins_collection.find_one({"phoneNumber": phone})
    else:
        account = await users_collection.find_one({"phoneNumber": phone})
        
    is_registered = account is not None
    user_id = str(account["_id"]) if account else phone
    
    token = create_access_token({
        "sub": user_id,
        "phoneNumber": phone,
        "role": role,
    })
    
    # If account exists, update last login & fcmToken
    if account:
        col = admins_collection if role == "master" else users_collection
        update_data = {"lastLogin": datetime.now(timezone.utc), "isOnline": True}
        if req.fcmToken:
            update_data["fcmToken"] = req.fcmToken
        await col.update_one({"_id": account["_id"]}, {"$set": update_data})

    return {
        "success": True,
        "message": "OTP verified successfully",
        "accessToken": token,
        "token": token,
        "isRegistered": is_registered,
        "role": role
    }

# ==============================================================================
# 2. COMPLETE REGISTRATION (No strict check / fully unlocked)
# ==============================================================================

@app.post("/api/admin/complete-registration", summary="Register master admin profile")
async def register_master(req: MasterRegisterRequest, current=Depends(get_current_user)):
    phone = req.phoneNumber.strip()
    existing = await admins_collection.find_one({"phoneNumber": phone})
    
    doc = {
        "phoneNumber": phone,
        "name": req.name,
        "email": req.email,
        "role": "master",
        "termsAccepted": req.termsAccepted,
        "permissions": req.permissions,
        "location": req.location,
        "fcmToken": req.fcmToken,
        "isRegistered": True,
        "isVerified": True,
        "planStatus": "active",
        "maxDevicesAllowed": 999,
        "updatedAt": datetime.now(timezone.utc),
    }
    
    if existing:
        await admins_collection.update_one({"_id": existing["_id"]}, {"$set": doc})
        master_id = str(existing["_id"])
    else:
        doc["createdAt"] = datetime.now(timezone.utc)
        res = await admins_collection.insert_one(doc)
        master_id = str(res.inserted_id)

    token = create_access_token({"sub": master_id, "phoneNumber": phone, "role": "master"})
    return {
        "success": True,
        "message": "Master profile registered successfully",
        "token": token,
        "accessToken": token,
        "masterId": master_id
    }

@app.post("/api/auth/complete-registration", summary="Register user client device profile")
async def register_user(req: UserRegisterRequest, current=Depends(get_current_user)):
    phone = req.phoneNumber.strip()
    existing = await users_collection.find_one({"phoneNumber": phone})
    
    # Generate unique device code if not already assigned
    device_code = existing.get("deviceConnectionCode") if existing else None
    if not device_code:
        while True:
            candidate = generate_device_code(6)
            if not await devices_collection.find_one({"deviceConnectionCode": candidate}):
                device_code = candidate
                break

    doc = {
        "phoneNumber": phone,
        "name": req.name,
        "email": req.email,
        "role": "user",
        "deviceName": req.deviceName,
        "deviceType": req.deviceType,
        "deviceConnectionCode": device_code,
        "termsAccepted": req.termsAccepted,
        "permissions": req.permissions,
        "location": req.location,
        "signatureImage": req.signatureUrl,
        "videoAuth": req.videoAuthUrl,
        "fcmToken": req.fcmToken,
        "isRegistered": True,
        "isVerified": True,
        "isOnline": True,
        "updatedAt": datetime.now(timezone.utc),
    }
    
    if existing:
        await users_collection.update_one({"_id": existing["_id"]}, {"$set": doc})
        user_id = str(existing["_id"])
    else:
        doc["createdAt"] = datetime.now(timezone.utc)
        res = await users_collection.insert_one(doc)
        user_id = str(res.inserted_id)

    # Sync device code collection
    await devices_collection.update_one(
        {"deviceConnectionCode": device_code},
        {"$set": {
            "deviceConnectionCode": device_code,
            "userId": user_id,
            "phoneNumber": phone,
            "deviceName": req.deviceName,
            "deviceType": req.deviceType,
            "isOnline": True,
            "updatedAt": datetime.now(timezone.utc)
        }},
        upsert=True
    )

    token = create_access_token({"sub": user_id, "phoneNumber": phone, "role": "user"})
    return {
        "success": True,
        "message": "User registered successfully",
        "token": token,
        "accessToken": token,
        "deviceConnectionCode": device_code,
        "userId": user_id
    }

# ==============================================================================
# 3. PROFILES & SETTINGS
# ==============================================================================

@app.get("/api/admin/profile", summary="Fetch master profile and registered devices")
async def get_master_profile(current=Depends(get_current_user)):
    user_id = current.get("sub")
    phone = current.get("phoneNumber")
    
    admin = await admins_collection.find_one({"$or": [{"_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else None}, {"phoneNumber": phone}]})
    if not admin:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    admin_data = serialize_doc(admin)
    admin_data["maxDevicesAllowed"] = 999
    admin_data["deviceLimitReached"] = False
    admin_data["planStatus"] = "active"
    
    # Fetch paired devices
    paired_docs = await devices_collection.find({"masterId": user_id}).to_list(100)
    admin_data["devices"] = [d.get("deviceConnectionCode") for d in paired_docs]
    admin_data["registeredDevices"] = admin_data["devices"]

    settings_doc = await settings_collection.find_one({"_id": "app_settings"})
    
    return {
        "success": True,
        "message": "Profile fetched successfully",
        "masterProfile": admin_data,
        "settings": serialize_doc(settings_doc)
    }

@app.get("/api/auth/profile", summary="Fetch user client device profile")
async def get_user_profile(current=Depends(get_current_user)):
    user_id = current.get("sub")
    phone = current.get("phoneNumber")
    
    user_doc = await users_collection.find_one({"$or": [{"_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else None}, {"phoneNumber": phone}]})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User profile not found")
        
    settings_doc = await settings_collection.find_one({"_id": "app_settings"})
    return {
        "success": True,
        "message": "Profile fetched successfully",
        "userProfile": serialize_doc(user_doc),
        "settings": serialize_doc(settings_doc)
    }

@app.post("/api/admin/getapplinks")
@app.get("/api/admin/getapplinks")
async def get_app_links():
    settings_doc = await settings_collection.find_one({"_id": "app_settings"})
    return serialize_doc(settings_doc.get("appLinks", {})) if settings_doc else {}

@app.get("/api/settings/terms")
async def get_terms():
    settings_doc = await settings_collection.find_one({"_id": "app_settings"})
    return {"terms": settings_doc.get("termsAndCondition", "") if settings_doc else ""}

# ==============================================================================
# 4. DIRECT DEVICE PAIRING & CONNECTION (Without verified/purchased barriers)
# ==============================================================================

@app.post("/api/admin/check-code", summary="Check device code availability")
async def check_code(req: CheckCodeRequest, current=Depends(get_current_user)):
    code = req.code.strip().toUpperCase() if hasattr(req.code, "toUpperCase") else req.code.strip().upper()
    dev = await devices_collection.find_one({"deviceConnectionCode": code})
    
    if not dev:
        return {"isVaildCode": "No", "connected": False, "thisMaster": False}
        
    master_id = dev.get("masterId")
    current_master_id = current.get("sub")
    
    connected = bool(master_id)
    this_master = (master_id == current_master_id)
    
    return {
        "isVaildCode": "Yes",
        "connected": connected,
        "thisMaster": this_master,
        "deviceName": dev.get("deviceName", "Device"),
        "deviceType": dev.get("deviceType", "Mobile")
    }

@app.post("/api/admin/connect-device", summary="Connect master to user device directly")
async def connect_device(req: ConnectDeviceRequest, current=Depends(get_current_user)):
    code = req.code.strip().upper()
    master_id = current.get("sub")
    
    dev = await devices_collection.find_one({"deviceConnectionCode": code})
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
        
    await devices_collection.update_one(
        {"deviceConnectionCode": code},
        {"$set": {
            "masterId": master_id,
            "connectedAt": datetime.now(timezone.utc),
            "isOnline": True
        }}
    )
    
    return {
        "success": True,
        "message": f"Device {code} paired and connected successfully to master without restrictions",
        "deviceConnectionCode": code
    }

@app.get("/api/admin/devices", summary="Get list of all devices connected to master")
async def list_devices(current=Depends(get_current_user)):
    master_id = current.get("sub")
    
    # Retrieve devices paired to this master or all available devices
    cursor = devices_collection.find({"$or": [{"masterId": master_id}, {"masterId": {"$exists": True}}]})
    device_list = await cursor.to_list(100)
    
    result = []
    for d in device_list:
        result.append({
            "deviceId": d.get("deviceConnectionCode"),
            "deviceName": d.get("deviceName", "Device"),
            "deviceType": d.get("deviceType", "Mobile"),
            "isPrimary": False,
            "status": "active" if d.get("isOnline", True) else "inactive",
            "phoneNumber": d.get("phoneNumber")
        })
        
    return {
        "success": True,
        "devices": result
    }

@app.post("/api/auth/update-device", summary="Update device details from user side")
async def update_device(req: UpdateDeviceRequest, current=Depends(get_current_user)):
    user_id = current.get("sub")
    await users_collection.update_one(
        {"_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else None},
        {"$set": {
            "deviceName": req.deviceName,
            "deviceType": req.deviceType,
            "updatedAt": datetime.now(timezone.utc)
        }}
    )
    await devices_collection.update_one(
        {"userId": user_id},
        {"$set": {
            "deviceName": req.deviceName,
            "deviceType": req.deviceType,
            "updatedAt": datetime.now(timezone.utc)
        }}
    )
    return {"success": True, "message": "Device updated successfully"}

# ==============================================================================
# 5. PLANS & CATALOG (Always unlocked / Free)
# ==============================================================================

@app.post("/api/admin/getactiveplans")
@app.get("/api/admin/getactiveplans")
async def get_active_plans():
    return {
        "success": True,
        "message": "Plans fetched successfully",
        "plansData": [
            {
                "_id": "unlimited_free_plan",
                "planName": "Unlimited Devices Plan",
                "price": "0",
                "numberOfDevices": "999",
                "planDuration": "365",
                "status": "active",
                "priority": "1"
            }
        ],
        "charges": {"gst": "0", "platFormFree": "0"}
    }

# ==============================================================================
# 6. WEBRTC SIGNALING WEBSOCKET (Replaces Firebase Realtime Database)
# ==============================================================================

@app.websocket("/ws/signaling/{room_code}/{role}")
async def websocket_signaling(websocket: WebSocket, room_code: str, role: str):
    """
    WebSocket endpoint handling:
    - connection-request / connection-accepted / connection-declined
    - start-sharing / stop-sharing
    - offer / answer (SDP exchange)
    - ice-candidate
    - remote-input (tap, longpress, swipe)
    - remote-system-action (back, home, recent)
    - quality-feedback
    """
    room_code = room_code.upper()
    await signaling_manager.connect(room_code, role, websocket)
    
    # Update device online state in MongoDB
    if role == "user":
        await devices_collection.update_one(
            {"deviceConnectionCode": room_code},
            {"$set": {"isOnline": True}},
            upsert=True
        )

    try:
        while True:
            text_data = await websocket.receive_text()
            try:
                data = json.loads(text_data)
            except json.JSONDecodeError:
                continue

            # Forward event to peer participant
            await signaling_manager.relay_message(room_code, role, data)

    except WebSocketDisconnect:
        signaling_manager.disconnect(room_code, role)
        if role == "user":
            await devices_collection.update_one(
                {"deviceConnectionCode": room_code},
                {"$set": {"isOnline": False}}
            )

# ==============================================================================
# 7. CALL NOTIFICATION & REMOTE TRANSCRIPTION RELAYS
# ==============================================================================

@app.post("/api/call/notify", summary="User device notifies master of incoming/outgoing call or message")
async def notify_call_event(data: dict):
    """
    Receives call events from user device:
    {
      "roomCode": "C2H6YU",
      "callerName": "John Doe",
      "callerNumber": "+1234567890",
      "type": "incoming_call" | "message",
      "phase": "ringing" | "active" | "ended"
    }
    """
    room_code = data.get("roomCode", "").upper()
    caller_name = data.get("callerName", "Incoming Call")
    caller_number = data.get("callerNumber", "")
    phase = data.get("phase", "ringing")

    # 1. Real-time WebSocket relay to connected Master
    await signaling_manager.relay_message(room_code, "user", {
        "type": "call_alert",
        "data": data
    })

    # 2. Push Notification via FCM to Master (even if Master app is in background or closed)
    try:
        # Find master paired with this device
        dev = await devices_collection.find_one({"deviceConnectionCode": room_code})
        if dev and dev.get("masterId"):
            master_id = dev["masterId"]
            admin = await admins_collection.find_one({
                "$or": [
                    {"_id": ObjectId(master_id) if ObjectId.is_valid(master_id) else None},
                    {"phoneNumber": master_id}
                ]
            })
            if admin and admin.get("fcmToken"):
                master_fcm_token = admin["fcmToken"]
                # Send FCM notification
                try:
                    import firebase_admin
                    from firebase_admin import messaging
                    
                    message = messaging.Message(
                        notification=messaging.Notification(
                            title=f"📞 Incoming Call on {dev.get('deviceName', room_code)}",
                            body=f"{caller_name} ({caller_number}) is {phase}!"
                        ),
                        data={
                            "type": "call_alert",
                            "roomCode": room_code,
                            "callerName": str(caller_name),
                            "callerNumber": str(caller_number),
                            "phase": str(phase)
                        },
                        token=master_fcm_token,
                    )
                    messaging.send(message)
                    print(f"📲 [FCM] Sent call notification to Master: {caller_name}")
                except Exception as fcm_err:
                    print(f"⚠️ [FCM] Notice: Firebase credentials not initialized yet ({fcm_err}). Waiting for google_services.json.")
    except Exception as e:
        print(f"Error checking master FCM: {e}")

    return {"success": True, "message": "Call alert dispatched to master via WebSocket and FCM"}

@app.post("/api/call/transcript-chunk", summary="Stream live transcript segment to master")
async def stream_transcript(data: dict):
    """
    Relays real-time call transcript chunks:
    {
      "roomCode": "C2H6YU",
      "speaker": "Caller" | "User",
      "text": "Hello, how are you?",
      "isFinal": true,
      "timestamp": 12345678
    }
    """
    room_code = data.get("roomCode", "").upper()
    await signaling_manager.relay_message(room_code, "user", {
        "type": "transcript_chunk",
        "data": data
    })
    return {"success": True, "message": "Transcript chunk relayed"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
