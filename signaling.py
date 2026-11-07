import asyncio
from typing import Dict, Any, Optional, Set
from fastapi import WebSocket
import json


def _normalize_role(role: str) -> str:
    r = (role or "").strip().lower()
    if r.startswith("master"):
        return "master"
    return "user"


class SignalingManager:
    def __init__(self):
        self.active_rooms: Dict[str, Dict[str, Any]] = {}

    async def connect(self, room_code: str, role: str, websocket: WebSocket):
        await websocket.accept()
        norm_role = _normalize_role(role)
        if room_code not in self.active_rooms:
            self.active_rooms[room_code] = {
                "user": None,
                "master": None,
                "user_sockets": set(),
                "master_sockets": set(),
                "info": {"online": True, "is_sharing": False, "is_locked": False},
                "sending_frame": False,
                "latest_frame": None,
                "sending_audio_user": False,
                "audio_queue_user": asyncio.Queue(maxsize=40),
                "sending_audio_master": False,
                "audio_queue_master": asyncio.Queue(maxsize=40),
            }

        room = self.active_rooms[room_code]
        sockets_key = f"{norm_role}_sockets"
        if sockets_key not in room or not isinstance(room[sockets_key], set):
            room[sockets_key] = set()
        room[sockets_key].add(websocket)

        # Keep primary pointer on main socket (or fallback if none)
        if role.lower() in ("user", "master") or room.get(norm_role) is None:
            room[norm_role] = websocket

        if norm_role == "user":
            room["info"]["online"] = True
        room["sending_frame"] = False
        room[f"sending_audio_{norm_role}"] = False
        print(f"🔌 [{role.upper()} -> {norm_role.upper()}] connected to room '{room_code}' (active={len(room[sockets_key])})")

        if norm_role == "user" and room.get("master_sockets"):
            resume_msg = json.dumps({
                "event": "resume-stream",
                "type": "resume-stream",
                "roomCode": room_code,
            })
            for m_ws in list(room["master_sockets"]):
                try:
                    await m_ws.send_text(resume_msg)
                except Exception:
                    pass

    def disconnect(self, room_code: str, role: str, websocket: Optional[WebSocket] = None) -> bool:
        """
        Removes the disconnected socket from the role's active socket set.
        Returns True only if NO sockets remain for that normalized role.
        """
        norm_role = _normalize_role(role)
        if room_code in self.active_rooms:
            room = self.active_rooms[room_code]
            sockets_key = f"{norm_role}_sockets"
            sock_set: Set[WebSocket] = room.get(sockets_key, set())
            if websocket is not None:
                sock_set.discard(websocket)
            else:
                sock_set.clear()

            if room.get(norm_role) is websocket:
                room[norm_role] = next(iter(sock_set), None)

            if sock_set:
                print(f"ℹ️ [{role.upper()}] socket closed in room '{room_code}', {len(sock_set)} '{norm_role}' socket(s) still active")
                return False

            room[norm_role] = None
            if not room.get("user_sockets") and not room.get("master_sockets"):
                del self.active_rooms[room_code]
            else:
                if norm_role == "user":
                    room["info"]["online"] = False
        print(f"❌ [{role.upper()}] all '{norm_role}' sockets disconnected from room '{room_code}'")
        return True

    async def _send_to_role(self, room: Dict[str, Any], target_role: str, payload: str | bytes):
        sockets_key = f"{target_role}_sockets"
        targets: Set[WebSocket] = set(room.get(sockets_key, set()))
        primary = room.get(target_role)
        if primary is not None:
            targets.add(primary)
        if not targets:
            return

        dead = []
        for ws in targets:
            try:
                if isinstance(payload, (bytes, bytearray)):
                    await ws.send_bytes(payload)
                else:
                    await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        if dead:
            sock_set: Set[WebSocket] = room.get(sockets_key, set())
            for d in dead:
                sock_set.discard(d)
                if room.get(target_role) is d:
                    room[target_role] = next(iter(sock_set), None)

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
                await self._send_to_role(room, target_role, payload)
        finally:
            if room_code in self.active_rooms:
                self.active_rooms[room_code]["sending_frame"] = False

    async def relay_frame(self, room_code: str, sender_role: str, raw_payload: str | bytes):
        room = self.active_rooms.get(room_code)
        if not room:
            return
        norm_sender = _normalize_role(sender_role)
        target_role = "master" if norm_sender == "user" else "user"
        if not room.get(f"{target_role}_sockets") and not room.get(target_role):
            return
        room["latest_frame"] = raw_payload
        if not room.get("sending_frame"):
            asyncio.create_task(self._drain_latest_frame(room_code, target_role))

    async def _drain_audio_queue(self, room_code: str, target_role: str):
        room = self.active_rooms.get(room_code)
        sending_key = f"sending_audio_{target_role}"
        queue_key = f"audio_queue_{target_role}"
        if not room or room.get(sending_key):
            return
        room[sending_key] = True
        try:
            queue: Optional[asyncio.Queue] = room.get(queue_key)
            while room_code in self.active_rooms and queue and not queue.empty():
                payload = await queue.get()
                await self._send_to_role(room, target_role, payload)
        finally:
            if room_code in self.active_rooms:
                self.active_rooms[room_code][sending_key] = False

    async def relay_audio(self, room_code: str, sender_role: str, raw_payload: str):
        room = self.active_rooms.get(room_code)
        if not room:
            return
        norm_sender = _normalize_role(sender_role)
        target_role = "master" if norm_sender == "user" else "user"
        if not room.get(f"{target_role}_sockets") and not room.get(target_role):
            return
        queue_key = f"audio_queue_{target_role}"
        queue: Optional[asyncio.Queue] = room.get(queue_key)
        if queue is None:
            queue = asyncio.Queue(maxsize=40)
            room[queue_key] = queue

        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(raw_payload)
        except asyncio.QueueFull:
            pass

        sending_key = f"sending_audio_{target_role}"
        if not room.get(sending_key):
            asyncio.create_task(self._drain_audio_queue(room_code, target_role))

    async def relay_message(self, room_code: str, sender_role: str, message: dict):
        if room_code not in self.active_rooms:
            return

        room = self.active_rooms[room_code]
        norm_sender = _normalize_role(sender_role)
        msg_type = message.get("event") or message.get("type")
        if msg_type in ("start-sharing", "offer", "video-frame", "resume-stream"):
            room["info"]["is_sharing"] = True
        elif msg_type == "stop-sharing":
            room["info"]["is_sharing"] = False
        elif msg_type == "screen-state":
            room["info"]["is_locked"] = bool(message.get("isLocked"))

        if msg_type == "video-frame":
            await self.relay_frame(room_code, norm_sender, json.dumps(message))
            return
        if msg_type == "audio-chunk":
            await self.relay_audio(room_code, norm_sender, json.dumps(message))
            return

        target_role = "master" if norm_sender == "user" else "user"
        await self._send_to_role(room, target_role, json.dumps(message))


signaling_manager = SignalingManager()
