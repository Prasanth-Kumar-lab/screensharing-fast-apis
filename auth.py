from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_DAYS

security = HTTPBearer()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    token = credentials.credentials
    payload = decode_access_token(token)

    # Enforce Single Device Login: Invalidate session if another device logged in with the same account
    token_session_id = payload.get("sessionId")
    if token_session_id:
        user_id = payload.get("sub")
        role = payload.get("role", "user")
        phone = payload.get("phoneNumber")

        try:
            from database import admins_collection, users_collection
            from bson import ObjectId

            col = admins_collection if role == "master" else users_collection
            query = []
            if user_id and ObjectId.is_valid(user_id):
                query.append({"_id": ObjectId(user_id)})
            if phone:
                query.append({"phoneNumber": phone})

            if query:
                account = await col.find_one({"$or": query})
                if account:
                    active_session = account.get("currentSessionId")
                    if active_session and active_session != token_session_id:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="SESSION_SUPERSEDED: Your account has been logged in on another device. Only a single device is allowed to login and use this account.",
                            headers={"WWW-Authenticate": "Bearer"},
                        )
        except HTTPException:
            raise
        except Exception:
            pass

    return payload
