from typing import Dict, List, Any
from fastapi import WebSocket
import json

class SignalingManager:
    def __init__(self):
        # Mapping roomCode -> {"user": WebSocket, "master": WebSocket, "info": dict}
        self.active_rooms: Dict[str, Dict[str, Any]] = {}

    async def connect(self, room_code: str, role: str, websocket: WebSocket):
        await websocket.accept()
        if room_code not in self.active_rooms:
            self.active_rooms[room_code] = {"user": None, "master": None, "info": {"online": True}}
        
        self.active_rooms[room_code][role] = websocket
        self.active_rooms[room_code]["info"]["online"] = True
        print(f"🔌 [{role.upper()}] connected to room '{room_code}'")

    def disconnect(self, room_code: str, role: str):
        if room_code in self.active_rooms:
            self.active_rooms[room_code][role] = None
            if self.active_rooms[room_code]["user"] is None and self.active_rooms[room_code]["master"] is None:
                del self.active_rooms[room_code]
            else:
                if role == "user":
                    self.active_rooms[room_code]["info"]["online"] = False
        print(f"❌ [{role.upper()}] disconnected from room '{room_code}'")

    async def relay_message(self, room_code: str, sender_role: str, message: dict):
        if room_code not in self.active_rooms:
            return

        target_role = "master" if sender_role == "user" else "user"
        target_ws: WebSocket = self.active_rooms[room_code].get(target_role)

        if target_ws:
            await target_ws.send_text(json.dumps(message))
        else:
            print(f"⚠️ Target '{target_role}' not yet connected in room '{room_code}'")

signaling_manager = SignalingManager()
