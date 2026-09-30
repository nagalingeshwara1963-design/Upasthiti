# Upasthiti (उपस्थिति)
### AI-Powered Automated Face-Recognition Classroom Attendance Management System

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: Academic Research](https://img.shields.io/badge/License-Academic%20Research-green.svg)](app/ui/page_misc.py)
[![Platform: Windows | Web | Mobile](https://img.shields.io/badge/platform-Windows%20%7C%20Web%20%7C%20Mobile-blueviolet.svg)](#)
[![Tests: 77 Passed](https://img.shields.io/badge/tests-77%20passed%2C%200%20failed-brightgreen.svg)](#)

---

## 🌐 LIVE UPASHTITHI DEMO

> **Click the link below to immediately open and experience Upasthiti in your web browser:**

### 👉 **[Open Upasthiti Live Application](https://nagalingeshwara1963-design.github.io/Upasthiti/)** 👈

*Compatible with Windows Chrome, Microsoft Edge, macOS Safari, Android Chrome, and iOS Safari.*

---

## 📌 Architecture & Distinctions

| Environment | Link / Target | Description |
| :--- | :--- | :--- |
| **Live Interactive Web App** | [Open Upasthiti Web](https://nagalingeshwara1963-design.github.io/Upasthiti/) | Full browser edition with faithful desktop parity, interactive face detection, reports, and student portal. |
| **GitHub Source Code** | [GitHub Repository](https://github.com/nagalingeshwara1963-design/Upasthiti) | Complete Python backend, desktop UI, biometric pipelines, and unit tests. |
| **Local Windows Desktop App** | `Start_Upasthiti.bat` | Offline-first native Windows application with CustomTkinter GUI. |
| **Local Web Backend** | `Start_Web_Upasthiti.bat` | High-performance FastAPI server running on `http://localhost:8000`. |
| **Cloud Container Deploy** | [Render.com / Hugging Face](README_DEPLOY_WEB.md) | Dockerized backend with automatic port binding and model pre-loading. |

---

## 🌟 Core Features

- **True Desktop & Web Parity**: The web application preserves the exact navigation, terminology, workflows, institutional blue theme (`#0D47A1`), and business rules of the desktop edition.
- **AI Face Recognition Pipeline**: Dual-engine neural inference using YuNet / SCRFD face detection and SFace / Buffalo_L 512-D embedding extraction with cosine similarity matching.
- **Classroom Group Photo Attendance**: Process classroom photos with multi-face detection, automated illumination/blur diagnostics, and colored review boxes (Green = Confident, Amber = Uncertain, Red = Unknown).
- **Interactive Human Review Dialog**: Review uncertain matches and confirm absences with fast status toggles (`Present`, `Absent`, `Late`, `Excused`, `Leave / OD`) and keyboard shortcuts.
- **Smart Phone / QR Upload**: Instant mobile capture without cables—scan a short-lived QR code from any mobile phone on the network to upload classroom photos directly.
- **Dedicated Student Portal**: Strict privacy isolation (IDOR-protected). Students log in to view ONLY their own attendance history, percentage, subject-wise breakdown, and recovery guidance.
- **Student Review Requests**: Allows students to submit attendance mismatch claims within the institutional 30-day window or 10-day notice window with full faculty audit logging.
- **Deterministic Attendance Recovery Assistant**: Mathematical projection answering how many consecutive classes are needed to reach 75% or how many classes can safely be missed.
- **Email Center**: Student-scoped report dispatches, personalized previewing before sending, and automated absence notifications via secure SMTP (Gmail App Password).
- **Isolated Demo Mode**: Allows instant demonstration with synthetic student rosters and mock attendance even when hardware or model weights are offline.

---

## 🚀 Running Locally

### Option 1: Desktop Edition (Offline-First Native GUI)
1. Double-click **`Setup_Upasthiti.bat`** (first-time only) to create the Python environment and download model weights.
2. Double-click **`Start_Upasthiti.bat`** to launch the desktop application.

### Option 2: Web Edition (FastAPI Browser Server)
1. Double-click **`Start_Web_Upasthiti.bat`**.
2. Your browser will automatically open to:
   ```text
   http://localhost:8000
   ```
3. To open it on your mobile phone on the same Wi-Fi, visit:
   ```text
   http://<YOUR_COMPUTER_IP>:8000
   ```

---

## ☁️ Deploying to the Cloud

Upasthiti is fully containerized with a production `Dockerfile` and `render.yaml`.

### Deploy Free to Render.com:
1. Log in to [Render.com](https://render.com) with GitHub.
2. Click **New +** &rarr; **Web Service**.
3. Connect repository: `nagalingeshwara1963-design/Upasthiti`.
4. Runtime: **Docker** (Render will auto-detect `Dockerfile`).
5. Click **Create Web Service**. Render provides a public HTTPS web URL (`https://upasthiti-xxx.onrender.com`).

*For Hugging Face Spaces Docker instructions, see [README_DEPLOY_WEB.md](README_DEPLOY_WEB.md).*

---

## 🧪 Testing & Verification

Run the comprehensive unit and integration test suite across desktop, engine, and web API:

```bash
venv\Scripts\python.exe -m unittest discover -s tests -v
```

**Results:**
- Ran **77 tests** across email, gallery, phone upload, recovery, smart capture, and web API.
- **77 Passed, 0 Failed, 0 Skipped (100% OK)**.

---

## 🔒 Privacy, Security & Biometrics

- Biometric face embeddings and raw student images are never committed to version control.
- Passwords are encrypted with PBKDF2-SHA256 (310,000 iterations).
- Student data is strictly isolated server-side: students cannot query or access any other student's records by manipulating API requests.
- Sensitive email credentials (App Passwords) are secured using Windows DPAPI encryption and are never exposed over the network or in frontend code.
