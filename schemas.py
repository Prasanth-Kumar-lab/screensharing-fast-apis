from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

# Authentication models
class SendOtpRequest(BaseModel):
    phoneNumber: str
    role: Optional[str] = "user"  # "user" or "master"

class VerifyOtpRequest(BaseModel):
    phoneNumber: str
    otp: str
    role: Optional[str] = "user"
    fcmToken: Optional[str] = None

# Master Registration
class MasterRegisterRequest(BaseModel):
    phoneNumber: str
    name: str
    email: str
    termsAccepted: bool = True
    permissions: Optional[List[Dict[str, Any]]] = []
    location: Optional[Dict[str, Any]] = None
    fcmToken: Optional[str] = None

# User Registration
class UserRegisterRequest(BaseModel):
    phoneNumber: str
    name: str
    email: str
    termsAccepted: bool = True
    deviceName: str = "Android Device"
    deviceType: str = "Mobile"
    permissions: Optional[List[Dict[str, Any]]] = []
    location: Optional[Dict[str, Any]] = None
    signatureUrl: Optional[str] = None
    videoAuthUrl: Optional[str] = None
    fcmToken: Optional[str] = None

# Device pairing & connection models
class CheckCodeRequest(BaseModel):
    code: str

class ConnectDeviceRequest(BaseModel):
    code: str

class UpdateDeviceRequest(BaseModel):
    deviceName: str
    deviceType: str

# Support Ticket Model
class SupportTicketRequest(BaseModel):
    title: str
    description: str
    issueType: Optional[str] = "General"
    imageUrl: Optional[str] = None

# Real-time User Device Notification Model
class NotificationEventRequest(BaseModel):
    roomCode: str
    appName: Optional[str] = "App"
    packageName: Optional[str] = ""
    title: Optional[str] = ""
    body: Optional[str] = ""
    subText: Optional[str] = None
    bigText: Optional[str] = None
    category: Optional[str] = "general"
    postTime: Optional[int] = None
    isOngoing: Optional[bool] = False
    extraData: Optional[Dict[str, Any]] = None
