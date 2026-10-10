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
