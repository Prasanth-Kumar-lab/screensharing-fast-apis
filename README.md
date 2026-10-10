# Screen Sharing & Remote Control Fast APIs

FastAPI backend with MongoDB Compass integration (`screensharing_db`). Replaces Firebase Realtime Database and standard OTP with high-performance REST APIs and WebSockets.

---

## 🚀 Running the Server

From the directory:
```bash
cd "C:\Users\bunny\StudioProjects\Screen sharing\Screensharing fast apis"
py main.py
```
Or with Uvicorn directly:
```bash
py -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive Swagger Documentation is accessible at:
👉 **`http://localhost:8000/docs`**

---

## 🗄️ MongoDB Compass Database

- **Host**: `mongodb://localhost:27017`
- **Database Name**: `screensharing_db` (Visible directly in MongoDB Compass)
- **Collections**:
  - `users`: User profiles (Client devices to be controlled)
  - `admins`: Master controllers
  - `devices`: Registered device pairing codes & presence status
  - `otps`: Dynamic OTP records
  - `settings`: App configuration, terms & links
  - `plans`: Unrestricted access plans

---

## 🔑 Key Features Implemented

1. **Dynamic OTP with Snackbar Display**:
   - `POST /api/auth/send-otp`: Generates dynamic 6-digit OTP code and returns it in the API response JSON (`otp: "123456"`) so your mobile app can immediately pop up a Snackbar with the code.
   - `POST /api/auth/verify-otp`: Validates the code and issues a 30-day JWT Bearer Access Token.
2. **Access Token / Bearer Token Security**:
   - All protected routes use `Authorization: Bearer <token>`.
3. **Unrestricted Device Connection**:
   - No `isVerified` or `isPurchased` roadblocks or plan limits.
   - Master can connect to user devices directly via `POST /api/admin/connect-device`.
4. **WebRTC Signaling via WebSockets (Replacing Firebase RTDB)**:
   - Endpoint: `ws://<server-ip>:8000/ws/signaling/{room_code}/{role}` (`role` = `user` or `master`)
   - Handles real-time events:
     - `connection-request`, `connection-accepted`, `connection-declined`
     - `start-sharing`, `stop-sharing`
     - `offer`, `answer` (SDP exchange)
     - `ice-candidate`
     - `remote-input` (tap, longpress, swipe coordinates)
     - `remote-system-action` (back, home, recent)
     - `quality-feedback`
