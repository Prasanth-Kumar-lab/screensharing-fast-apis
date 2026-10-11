import asyncio
from typing import Dict, Any, Optional
from fastapi import WebSocket
import json


class SignalingManager:
    def __init__(self):
        # Mapping roomCode -> {
        #   "user": WebSocket,
        #   "master": WebSocket,
        #   "info": dict,
        #   "sending_frame": bool,
        #   "latest_frame": Optional[str | bytes]
        # }
        self.active_rooms: Dict[str, Dict[str, Any]] = {}

    async def connect(self, room_code: str, role: str, websocket: WebSocket):
        await websocket.accept()
        if room_code not in self.active_rooms:
            self.active_rooms[room_code] = {
                "user": None,
                "master": None,
                "info": {"online": True},
                "sending_frame": False,
                "latest_frame": None,
            }

        self.active_rooms[room_code][role] = websocket
        self.active_rooms[room_code]["info"]["online"] = True
        print(f"🔌 [{role.upper()}] connected to room '{room_code}'")

    def disconnect(self, room_code: str, role: str):
        if room_code in self.active_rooms:
            self.active_rooms[room_code][role] = None
            if (
                self.active_rooms[room_code]["user"] is None
                and self.active_rooms[room_code]["master"] is None
            ):
                del self.active_rooms[room_code]
            else:
                if role == "user":
                    self.active_rooms[room_code]["info"]["online"] = False
        print(f"❌ [{role.upper()}] disconnected from room '{room_code}'")

    async def _drain_latest_frame(self, room_code: str, target_role: str):
        room = self.active_rooms.get(room_code)
        if not room or room.get("sending_frame"):
            return
        room["sending_frame"] = True
        try:
            while room_code in self.active_rooms:
                payload = room.get("latest_frame")
                if payload is None:
                    break
                room["latest_frame"] = None
                target_ws: Optional[WebSocket] = room.get(target_role)
                if not target_ws:
                    break
                try:
                    if isinstance(payload, (bytes, bytearray)):
                        await target_ws.send_bytes(payload)
                    else:
                        await target_ws.send_text(payload)
                except Exception:
                    break
        finally:
            if room_code in self.active_rooms:
                self.active_rooms[room_code]["sending_frame"] = False

    async def relay_frame(self, room_code: str, sender_role: str, raw_payload: str | bytes):
        """
        Zero-buffer latest-frame relay: if the target socket is still busy sending
        the previous video frame, overwrite latest_frame so stale frames never queue up.
        """
        room = self.active_rooms.get(room_code)
        if not room:
            return
        target_role = "master" if sender_role == "user" else "user"
        if not room.get(target_role):
            return
        room["latest_frame"] = raw_payload
        if not room.get("sending_frame"):
            asyncio.create_task(self._drain_latest_frame(room_code, target_role))

    async def relay_message(self, room_code: str, sender_role: str, message: dict):
        if room_code not in self.active_rooms:
            return

        msg_type = message.get("event") or message.get("type")
        if msg_type == "video-frame":
            await self.relay_frame(room_code, sender_role, json.dumps(message))
            return

        target_role = "master" if sender_role == "user" else "user"
        target_ws: Optional[WebSocket] = self.active_rooms[room_code].get(target_role)

        if target_ws:
            try:
                await target_ws.send_text(json.dumps(message))
            except Exception as e:
                print(f"⚠️ Relay error to '{target_role}' in room '{room_code}': {e}")


signaling_manager = SignalingManager()

