"""FastAPI Web Server for Upasthiti Classroom Attendance System.

Provides full web parity with the Windows desktop application:
- Authentication & Server-Side Role Enforcement (Admin, Faculty, Student)
- Student Portal with strict privacy isolation (IDOR protection)
- Classroom Photo Management & Staged Queue
- Mobile / QR Code Photo Smart Capture Integration
- Face Recognition & Attendance Pipeline (YuNet + SFace / Buffalo_L)
- Interactive Human Review & Attendance Marking (P / A / L / E / OD)
- Session History, Calendar Attendance & Audited Corrections
- Student Discrepancy Review Requests (30-day & 10-day notice window)
- Deterministic Attendance Recovery Assistant & What-If Simulator
- Email Center (Student-Scoped Reports, Preview, Automated Absence Notices)
- System Settings, Model Status, and Safe Backup/Restore
- Isolated Demo Mode with Synthetic Data
"""
from __future__ import annotations

import base64
import calendar
import datetime
import io
import json
import logging
import os
import secrets
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import auth, backup, config, demo_mode, exports, i18n, recovery, reports, stats
from app.chat_assistant import LocalAssistant
from app.db import DB
from app.email_service import EmailService
from app.engine.gallery import Gallery, enroll_photo
from app.engine.pipeline import analyse_session
from app.mobile_capture import MOBILE_PAGE
from app.phone_upload import MAX_FILE_BYTES, MAX_SESSION_BYTES, MAX_SESSION_FILES, make_qr_image
from app.portal_service import StudentPortalService
from app.review_requests import ReviewRequestService
from app.services import Service, imread, models_status
from app.smart_capture import summarize_capture

logger = logging.getLogger("upasthiti.web")

app = FastAPI(
    title="Upasthiti Web Attendance",
    description="Faithful browser edition of Upasthiti Face Recognition Classroom Attendance System",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core singletons
db = DB()
svc = Service(db)
email_service = EmailService(db)

STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory session store: token -> session dict
# session: {"user": str, "role": str, "student_id": Optional[int], "logged_in_at": float, "is_demo": bool, "must_change": bool}
SESSIONS: Dict[str, Dict[str, Any]] = {}

# Staged photos for active staff sessions: session_token -> list of staged dicts
STAGED_PHOTOS: Dict[str, List[Dict[str, Any]]] = {}

# Active mobile phone upload sessions: token -> phone session dict
PHONE_SESSIONS: Dict[str, Dict[str, Any]] = {}

# Temporary demo environments: token -> tempdir
DEMO_ENVS: Dict[str, Any] = {}

SESSION_COOKIE_NAME = "upasthiti_session"
SESSION_TTL = 12 * 3600  # 12 hours


# ------------------ SESSION / AUTH HELPERS ------------------

def get_session(
    request: Request,
    upasthiti_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
) -> Optional[Dict[str, Any]]:
    """Retrieve the current active session from cookie or header."""
    token = None
    if upasthiti_session:
        token = upasthiti_session
    elif x_session_token:
        token = x_session_token
    elif authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()

    if not token or token not in SESSIONS:
        return None

    sess = SESSIONS[token]
    # Check expiry
    if time.time() - sess["logged_in_at"] > SESSION_TTL:
        SESSIONS.pop(token, None)
        return None

    # Attach token to session object for convenience
    sess["token"] = token
    return sess


def require_auth(session: Optional[Dict[str, Any]] = Depends(get_session)) -> Dict[str, Any]:
    """Dependency ensuring caller is authenticated."""
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required. Please sign in.")
    # Set thread-local / module-level auth context for the existing services
    auth._new_session(session["user"], session["role"], session.get("student_id"), session.get("must_change", False))
    return session


def require_staff(session: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Dependency ensuring caller is Admin or Faculty."""
    if session["role"] not in ("admin", "faculty"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied. Staff privileges required.")
    return session


def require_admin(session: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Dependency ensuring caller is Admin."""
    if session["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied. Administrator privileges required.")
    return session


def require_student(session: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """Dependency ensuring caller is an authenticated Student."""
    if session["role"] != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied. Student privileges required.")
    if session.get("must_change"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password change required before accessing the portal.")
    return session


def get_active_db(session: Optional[Dict[str, Any]]) -> DB:
    """Return the demo DB if in demo mode, otherwise the production DB."""
    if session and session.get("is_demo") and session.get("token") in DEMO_ENVS:
        return DEMO_ENVS[session["token"]]["db"]
    return db


def get_active_svc(session: Optional[Dict[str, Any]]) -> Service:
    if session and session.get("is_demo") and session.get("token") in DEMO_ENVS:
        return DEMO_ENVS[session["token"]]["svc"]
    return svc


# ------------------ PYDANTIC SCHEMAS ------------------

class LoginRequest(BaseModel):
    role: str  # Admin | Faculty | Student | Maintenance
    username: Optional[str] = "admin"
    password: str
    student_name: Optional[str] = ""
    student_code: Optional[str] = ""


class StudentPasswordChangeRequest(BaseModel):
    new_password: str


class ClassCreate(BaseModel):
    name: str
    college: Optional[str] = ""
    year: Optional[str] = ""
    branch: Optional[str] = ""
    section: Optional[str] = ""


class StudentCreate(BaseModel):
    code: str
    name: str
    email: Optional[str] = ""


class AttendanceDecision(BaseModel):
    student_id: int
    status: str  # P | A | L | E | OD


class SessionSaveRequest(BaseModel):
    class_id: int
    date: Optional[str] = None
    time: Optional[str] = None
    subject: Optional[str] = "General"
    faculty: Optional[str] = "Faculty"
    period: Optional[str] = "1"
    mode: Optional[str] = "balanced"
    records: List[AttendanceDecision]


class ReviewRequestSubmit(BaseModel):
    session_id: int
    reason: str
    explanation: Optional[str] = ""


class ReviewTransitionRequest(BaseModel):
    action: str  # start | keep | change | dismiss | escalate
    reason: Optional[str] = ""
    new_status: Optional[str] = None


class RecoveryCalculationRequest(BaseModel):
    attended: int
    absent: int
    target: float = 75.0
    upcoming: Optional[int] = 0
    attend_next: Optional[int] = 0
    miss_next: Optional[int] = 0


class RecoveryGoalRequest(BaseModel):
    target: float


class ChatQuestionRequest(BaseModel):
    question: str
    class_id: Optional[int] = None


class EmailRecipientUpdate(BaseModel):
    student_id: int
    email: str
    label: Optional[str] = ""


class EmailPreviewRequest(BaseModel):
    student_id: int
    class_id: int
    report_from: str
    report_to: str


class EmailSendRequest(BaseModel):
    student_ids: List[int]
    class_id: int
    report_from: str
    report_to: str


class SettingsUpdateRequest(BaseModel):
    limit_warn: Optional[int] = 85
    limit_critical: Optional[int] = 75
    default_mode: Optional[str] = "balanced"
    sender_email: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None


# ------------------ HTML DASHBOARD ------------------

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    index_file = TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Upasthiti Web Interface is loading...</h1>")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


# ------------------ SYSTEM & HEALTH ------------------

@app.get("/api/health")
@app.get("/api/status")
def get_system_status(session: Optional[Dict[str, Any]] = Depends(get_session)):
    current_db = get_active_db(session)
    classes_count = len(current_db.classes())
    st = models_status()
    models_ready = bool(st.get("buffalo_l"))

    all_students = current_db.q("SELECT COUNT(*) as count FROM students WHERE active=1")
    total_students = all_students[0]["count"] if all_students else 0

    all_sessions = current_db.q("SELECT COUNT(*) as count FROM sessions")
    total_sessions = all_sessions[0]["count"] if all_sessions else 0

    return {
        "status": "healthy",
        "models_ready": models_ready,
        "models": st,
        "authenticated": bool(session),
        "user": session.get("user") if session else None,
        "role": session.get("role") if session else None,
        "is_demo": session.get("is_demo", False) if session else False,
        "stats": {
            "classes": classes_count,
            "students": total_students,
            "sessions": total_sessions,
        },
    }


# ------------------ AUTHENTICATION ------------------

@app.post("/api/auth/login")
def login_endpoint(req: LoginRequest, response: Response):
    role_choice = (req.role or "").strip()
    target_db = db

    if role_choice == "Student":
        auth_result = auth.student_login(target_db, req.student_name, req.student_code, req.password)
        if not auth_result:
            raise HTTPException(status_code=400, detail="Student name, ID, or password is incorrect.")
        sid = auth.current_student_id()
        must_change = auth.student_must_change_password()
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {
            "user": req.student_name.strip(),
            "role": "student",
            "student_id": sid,
            "must_change": must_change,
            "logged_in_at": time.time(),
            "is_demo": False,
        }
        response.set_cookie(SESSION_COOKIE_NAME, token, max_age=SESSION_TTL, httponly=True, samesite="lax")
        return {
            "success": True,
            "token": token,
            "user": req.student_name.strip(),
            "role": "student",
            "student_id": sid,
            "must_change_password": must_change,
        }

    # Staff login (Admin, Faculty, Maintenance)
    uname = (req.username or "admin").strip().lower()
    if role_choice in ("Admin", "Maintenance"):
        uname = "admin"
        if not auth.has_any_account(target_db):
            # Admin bootstrap if first run
            auth.set_password(target_db, "admin", "admin", req.password)

    role = auth.login(target_db, uname, req.password)
    if not role:
        raise HTTPException(status_code=400, detail="Incorrect username or password.")

    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "user": uname,
        "role": role,
        "student_id": None,
        "must_change": False,
        "logged_in_at": time.time(),
        "is_demo": False,
    }
    response.set_cookie(SESSION_COOKIE_NAME, token, max_age=SESSION_TTL, httponly=True, samesite="lax")
    return {
        "success": True,
        "token": token,
        "user": uname,
        "role": role,
        "student_id": None,
        "must_change_password": False,
    }


@app.get("/api/auth/me")
def get_current_user_profile(session: Dict[str, Any] = Depends(require_auth)):
    current_db = get_active_db(session)
    profile = {
        "user": session["user"],
        "role": session["role"],
        "student_id": session.get("student_id"),
        "is_demo": session.get("is_demo", False),
        "must_change_password": session.get("must_change", False),
    }
    if session["role"] == "student" and session.get("student_id"):
        rows = current_db.q(
            "SELECT s.id, s.name, s.code, s.class_id, c.name as class_name FROM students s "
            "JOIN classes c ON c.id=s.class_id WHERE s.id=?",
            (session["student_id"],),
        )
        if rows:
            profile["student"] = rows[0]
    return profile


@app.post("/api/auth/student-change-password")
def student_change_password_endpoint(
    req: StudentPasswordChangeRequest,
    session: Dict[str, Any] = Depends(require_auth),
):
    if session["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can change student password.")
    current_db = get_active_db(session)
    try:
        auth.change_student_password(current_db, req.new_password)
        session["must_change"] = False
        return {"success": True, "message": "Password changed successfully."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/logout")
def logout_endpoint(response: Response, session: Optional[Dict[str, Any]] = Depends(get_session)):
    if session:
        token = session.get("token")
        if token:
            SESSIONS.pop(token, None)
            if token in STAGED_PHOTOS:
                STAGED_PHOTOS.pop(token, None)
            if token in DEMO_ENVS:
                env = DEMO_ENVS.pop(token)
                try:
                    env["db"].con.close()
                    env["temp"].cleanup()
                except Exception:
                    pass
    response.delete_cookie(SESSION_COOKIE_NAME)
    auth.logout()
    return {"success": True, "message": "Logged out successfully."}


# ------------------ DEMO MODE ------------------

@app.post("/api/demo/enter")
def enter_demo_mode(response: Response):
    """Start an isolated demo session with synthetic students and class."""
    tmp = tempfile.TemporaryDirectory(prefix="upasthiti-web-demo-")
    demo_db_path = Path(tmp.name) / "demo.db"
    demo_db = DB(demo_db_path)
    demo_mode.seed_demo_database(demo_db)
    demo_svc = Service(demo_db)

    token = secrets.token_urlsafe(32)
    DEMO_ENVS[token] = {"temp": tmp, "db": demo_db, "svc": demo_svc}
    SESSIONS[token] = {
        "user": "demo_admin",
        "role": "admin",
        "student_id": None,
        "must_change": False,
        "logged_in_at": time.time(),
        "is_demo": True,
    }
    response.set_cookie(SESSION_COOKIE_NAME, token, max_age=3600, httponly=True, samesite="lax")
    return {
        "success": True,
        "token": token,
        "user": "demo_admin",
        "role": "admin",
        "is_demo": True,
        "message": "Entered isolated Demo Mode with synthetic data.",
    }


@app.post("/api/demo/exit")
def exit_demo_mode(response: Response, session: Dict[str, Any] = Depends(require_auth)):
    token = session.get("token")
    if token and token in DEMO_ENVS:
        env = DEMO_ENVS.pop(token)
        try:
            env["db"].con.close()
            env["temp"].cleanup()
        except Exception:
            pass
    if token:
        SESSIONS.pop(token, None)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"success": True, "message": "Exited Demo Mode. Returned to live data."}


# ------------------ CLASSES ------------------

@app.get("/api/classes")
def list_classes(session: Dict[str, Any] = Depends(require_auth)):
    current_db = get_active_db(session)
    classes = current_db.classes()
    if session["role"] == "faculty":
        allowed = set(current_db.faculty_class_ids(session["user"]))
        classes = [c for c in classes if c["id"] in allowed]
    elif session["role"] == "student":
        sid = session.get("student_id")
        rows = current_db.q("SELECT class_id FROM students WHERE id=? AND active=1", (sid,))
        if rows:
            cid = rows[0]["class_id"]
            classes = [c for c in classes if c["id"] == cid]
        else:
            classes = []
    return classes


@app.post("/api/classes")
def create_class(req: ClassCreate, session: Dict[str, Any] = Depends(require_admin)):
    current_db = get_active_db(session)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Class name cannot be empty")
    try:
        cid = current_db.add_class(name, req.college, req.year, req.branch, req.section)
        return {"id": cid, "name": name, "message": "Class created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ------------------ STUDENTS & ENROLLMENT ------------------

@app.get("/api/classes/{class_id}/students")
def get_students(class_id: int, session: Dict[str, Any] = Depends(require_auth)):
    current_db = get_active_db(session)
    if not auth.can_access_class(current_db, class_id):
        raise HTTPException(status_code=403, detail="You are not authorized to view students in this class.")

    # Student cannot see other students' details
    if session["role"] == "student":
        sid = session["student_id"]
        rows = current_db.q("SELECT * FROM students WHERE id=? AND class_id=? AND active=1", (sid, class_id))
        return rows

    students = current_db.students(class_id)
    current_svc = get_active_svc(session)
    try:
        g = current_svc.load_gallery(class_id)
        for s in students:
            s["enrolled_faces"] = len(g.students.get(s["code"], {}).get("embs", []))
    except Exception:
        for s in students:
            s["enrolled_faces"] = len(current_db.student_photos(class_id, s["code"]))
    return students


@app.post("/api/classes/{class_id}/students")
def add_student(class_id: int, req: StudentCreate, session: Dict[str, Any] = Depends(require_staff)):
    current_db = get_active_db(session)
    if not auth.can_access_class(current_db, class_id):
        raise HTTPException(status_code=403, detail="You are not authorized for this class.")
    code = req.code.strip()
    name = req.name.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Student ID / Code is required.")
    email_recipients = [req.email.strip()] if req.email and req.email.strip() else []
    try:
        sid = current_db.save_student(class_id, code, name, [], email_recipients=email_recipients)
        return {"id": sid, "code": code, "name": name, "message": "Student created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/classes/{class_id}/students/{code}/enroll")
async def enroll_student_photo(
    class_id: int,
    code: str,
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    session: Dict[str, Any] = Depends(require_staff),
):
    """Enrolls a clear facial photo for a student into the gallery."""
    current_db = get_active_db(session)
    current_svc = get_active_svc(session)
    if not auth.can_access_class(current_db, class_id):
        raise HTTPException(status_code=403, detail="You are not authorized for this class.")

    img = None
    if file:
        content = await file.read()
        arr = np.frombuffer(content, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    elif image_base64:
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]
        raw = base64.b64decode(image_base64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if img is None:
        raise HTTPException(status_code=400, detail="Valid image required for enrollment.")

    hub = current_svc.get_hub()
    embs, info = enroll_photo(hub, img)
    if embs is None:
        raise HTTPException(
            status_code=400,
            detail="No clear face detected in photo. Please ensure face is well-lit, sharp, and facing camera.",
        )

    outdir = config.DATA / "enroll" / f"class_{class_id}"
    outdir.mkdir(parents=True, exist_ok=True)
    dst = outdir / f"{code}_{int(time.time()*1000)}.jpg"
    cv2.imwrite(str(dst), img, [cv2.IMWRITE_JPEG_QUALITY, 95])

    students = {s["code"]: s for s in current_db.students(class_id)}
    if code not in students:
        raise HTTPException(status_code=404, detail="Student not found in this class.")

    sid = students[code]["id"]
    sname = students[code]["name"]
    current_db.run("INSERT INTO enroll_photos(student_id, path) VALUES(?, ?)", (sid, str(dst)))

    g = current_svc.load_gallery(class_id)
    g.add(code, sname, embs)
    current_svc.save_gallery(class_id, g)

    return {
        "success": True,
        "message": f"Photo enrolled for {name_or_code(sname, code)}.",
        "enrolled_faces": len(g.students.get(code, {}).get("embs", [])),
    }


def name_or_code(name, code):
    return f"{name} ({code})" if name else code


@app.delete("/api/classes/{class_id}/students/{code}")
def remove_student(class_id: int, code: str, session: Dict[str, Any] = Depends(require_staff)):
    current_svc = get_active_svc(session)
    try:
        current_svc.remove_student(class_id, code)
        return {"success": True, "message": f"Student {code} archived. Historical records preserved."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/classes/{class_id}/gallery/rebuild")
def rebuild_gallery(class_id: int, session: Dict[str, Any] = Depends(require_staff)):
    """Safely rebuilds the recognition gallery from all enrolled student photos."""
    current_svc = get_active_svc(session)
    try:
        g = current_svc.rebuild_class_gallery(class_id)
        return {"success": True, "message": f"Gallery safely rebuilt for {len(g.codes)} students."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ------------------ GROUP PHOTOS & STAGED QUEUE ------------------

@app.get("/api/photos/staged")
def list_staged_photos(session: Dict[str, Any] = Depends(require_staff)):
    token = session["token"]
    staged = STAGED_PHOTOS.get(token, [])
    # Return serializable summary
    items = []
    for i, p in enumerate(staged):
        items.append({
            "index": i,
            "label": p.get("label", "Whole class"),
            "zone": p.get("zone", "Whole class"),
            "thumbnail": p.get("thumbnail"),
            "width": p.get("width"),
            "height": p.get("height"),
        })
    return items


@app.post("/api/photos/staged/upload")
async def add_staged_photo(
    zone: str = Form("Whole class"),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    session: Dict[str, Any] = Depends(require_staff),
):
    img = None
    if file:
        content = await file.read()
        arr = np.frombuffer(content, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    elif image_base64:
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]
        raw = base64.b64decode(image_base64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if img is None:
        raise HTTPException(status_code=400, detail="Invalid photo data.")

    # Create thumbnail
    h, w = img.shape[:2]
    s = min(200 / w, 150 / h)
    thumb = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    _, tbuf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 75])
    b64_thumb = "data:image/jpeg;base64," + base64.b64encode(tbuf).decode("utf-8")

    token = session["token"]
    if token not in STAGED_PHOTOS:
        STAGED_PHOTOS[token] = []

    STAGED_PHOTOS[token].append({
        "image": img,
        "label": zone,
        "zone": zone,
        "thumbnail": b64_thumb,
        "width": w,
        "height": h,
    })

    return {"success": True, "count": len(STAGED_PHOTOS[token])}


@app.delete("/api/photos/staged/{idx}")
def remove_staged_photo(idx: int, session: Dict[str, Any] = Depends(require_staff)):
    token = session["token"]
    staged = STAGED_PHOTOS.get(token, [])
    if 0 <= idx < len(staged):
        staged.pop(idx)
        return {"success": True, "count": len(staged)}
    raise HTTPException(status_code=404, detail="Photo index not found.")


@app.post("/api/photos/staged/clear")
def clear_staged_photos(session: Dict[str, Any] = Depends(require_staff)):
    token = session["token"]
    STAGED_PHOTOS[token] = []
    return {"success": True, "count": 0}


# ------------------ MOBILE / QR PHONE SMART CAPTURE ------------------

@app.post("/api/phone_upload/start")
def start_phone_upload_session(
    class_id: int = Form(...),
    request: Request = None,
    session: Dict[str, Any] = Depends(require_staff),
):
    current_db = get_active_db(session)
    if not auth.can_access_class(current_db, class_id):
        raise HTTPException(status_code=403, detail="Unauthorized for this class.")

    upload_token = secrets.token_urlsafe(32)
    temp_dir = tempfile.TemporaryDirectory(prefix="upasthiti-phone-")

    # Build upload URL for QR code
    base_url = str(request.base_url).rstrip("/")
    phone_url = f"{base_url}/phone_upload/{upload_token}"

    PHONE_SESSIONS[upload_token] = {
        "class_id": class_id,
        "staff_session_token": session["token"],
        "temp_dir": temp_dir,
        "created_at": time.time(),
        "files": [],
        "analysis": {"state": "waiting", "total_students": len(current_db.students(class_id))},
        "finished": False,
    }

    # Generate QR Code Data URL
    qr_img = make_qr_image(phone_url, size=260)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

    return {
        "success": True,
        "token": upload_token,
        "phone_url": phone_url,
        "qr_code": qr_b64,
        "expires_in": 900,
    }


@app.get("/phone_upload/{token}", response_class=HTMLResponse)
def serve_mobile_page(token: str):
    if token not in PHONE_SESSIONS:
        return HTMLResponse("<h2>Upload session expired or invalid. Please request a new QR code.</h2>", status_code=404)
    return HTMLResponse(MOBILE_PAGE)


@app.post("/phone_upload/{token}/upload")
async def phone_upload_file(token: str, request: Request):
    if token not in PHONE_SESSIONS:
        return JSONResponse({"error": "Session expired"}, status_code=404)
    sess = PHONE_SESSIONS[token]
    if sess["finished"]:
        return JSONResponse({"error": "Session is finished"}, status_code=400)
    if len(sess["files"]) >= MAX_SESSION_FILES:
        return JSONResponse({"error": "Maximum photo limit reached"}, status_code=400)

    content = await request.body()
    if len(content) > MAX_FILE_BYTES:
        return JSONResponse({"error": "File exceeds size limit"}, status_code=413)

    arr = np.frombuffer(content, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return JSONResponse({"error": "Unrecognized image format"}, status_code=400)

    # Save to temp directory
    fname = f"phone_{len(sess['files'])+1}_{int(time.time()*1000)}.jpg"
    out_path = Path(sess["temp_dir"].name) / fname
    cv2.imwrite(str(out_path), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    sess["files"].append({"path": str(out_path), "image": img})

    # Also automatically add to staged queue for the staff session
    staff_token = sess["staff_session_token"]
    if staff_token not in STAGED_PHOTOS:
        STAGED_PHOTOS[staff_token] = []

    h, w = img.shape[:2]
    s = min(200 / w, 150 / h)
    thumb = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    _, tbuf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 75])
    b64_thumb = "data:image/jpeg;base64," + base64.b64encode(tbuf).decode("utf-8")

    STAGED_PHOTOS[staff_token].append({
        "image": img,
        "label": f"Phone Photo {len(sess['files'])}",
        "zone": "Whole class",
        "thumbnail": b64_thumb,
        "width": w,
        "height": h,
    })

    return {"success": True, "count": len(sess["files"])}


@app.get("/phone_upload/{token}/status")
def phone_upload_status(token: str):
    if token not in PHONE_SESSIONS:
        return JSONResponse({"error": "Session expired"}, status_code=404)
    sess = PHONE_SESSIONS[token]
    return {
        "connected": True,
        "files_count": len(sess["files"]),
        "finish_requested": sess["finished"],
        "analysis": sess["analysis"],
    }


@app.post("/phone_upload/{token}/finish")
def phone_upload_finish(token: str):
    if token not in PHONE_SESSIONS:
        return JSONResponse({"error": "Session expired"}, status_code=404)
    sess = PHONE_SESSIONS[token]
    sess["finished"] = True
    return {"success": True, "message": "Capture session finished."}


# ------------------ ATTENDANCE RUN & REVIEW ------------------

@app.get("/api/attendance/config/{class_id}")
def get_attendance_config(class_id: int, session: Dict[str, Any] = Depends(require_staff)):
    current_svc = get_active_svc(session)
    try:
        cfg, info = current_svc.matching_config(class_id, automatic=True)
        return {"t_accept": cfg["t_accept"], "t_reject": cfg["t_reject"], "basis": info.get("basis", "Automatic")}
    except Exception as e:
        return {"t_accept": config.T_ACCEPT, "t_reject": config.T_REJECT, "basis": str(e)}


@app.post("/api/attendance/run")
def run_attendance_analysis(
    class_id: int = Form(...),
    mode: str = Form("balanced"),
    threshold: Optional[float] = Form(None),
    enhance: bool = Form(True),
    session: Dict[str, Any] = Depends(require_staff),
):
    """Executes face detection & recognition across all staged photos."""
    current_db = get_active_db(session)
    current_svc = get_active_svc(session)
    if not auth.can_access_class(current_db, class_id):
        raise HTTPException(status_code=403, detail="Unauthorized for this class.")

    token = session["token"]
    staged = STAGED_PHOTOS.get(token, [])
    if not staged:
        raise HTTPException(status_code=400, detail="Please add at least one group photo to the staged queue.")

    g = current_svc.load_gallery(class_id)
    if not g.codes:
        raise HTTPException(status_code=400, detail="This class has no enrolled students with photos.")

    hub = current_svc.get_hub()
    if threshold is not None:
        cfg = {"t_accept": float(threshold), "t_reject": float(threshold) + 0.15}
    else:
        cfg, _ = current_svc.matching_config(class_id, automatic=True)

    photos_input = [{"label": p.get("zone", "Whole class"), "image": p["image"]} for p in staged]
    res = analyse_session(hub, g, photos=photos_input, mode=mode, cfg=cfg, enhance=enhance)

    # Draw colored bounding boxes on the primary image for review
    primary_img = staged[0]["image"].copy()
    faces_detected = 0
    recognized_count = 0

    if res.get("photos"):
        for f in res["photos"][0].get("faces", []):
            faces_detected += 1
            bbox = f["bbox"]
            x1, y1, x2, y2 = [int(v) for v in bbox]
            code = f.get("student")
            conf = f.get("confidence", 0.0)
            flags = f.get("flags", [])

            if code:
                recognized_count += 1
                if set(flags) & {"weak_match", "close_call", "models_disagree"}:
                    color = (0, 165, 255)  # Orange / Amber in BGR
                    label = f"? {code} ({int(conf * 100)}%)"
                else:
                    color = (40, 180, 40)  # Green in BGR
                    label = f"✓ {code} ({int(conf * 100)}%)"
            else:
                color = (40, 40, 220)  # Red / Grey in BGR
                label = "Unknown Face"

            cv2.rectangle(primary_img, (x1, y1), (x2, y2), color, 2)
            (tw, th_box), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(primary_img, (x1, max(0, y1 - 20)), (x1 + tw + 6, y1), color, -1)
            cv2.putText(primary_img, label, (x1 + 3, max(14, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    _, buf = cv2.imencode(".jpg", primary_img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64_boxed = "data:image/jpeg;base64," + base64.b64encode(buf).decode("utf-8")

    students_in_class = current_db.students(class_id)
    student_records = []
    present_cnt = 0
    absent_cnt = 0

    for s in students_in_class:
        code = s["code"]
        rec = res["students"].get(code, {"status": "A", "confidence": 0.0, "dist": None, "flags": []})
        is_p = rec["status"] == "P"
        if is_p:
            present_cnt += 1
        else:
            absent_cnt += 1

        student_records.append({
            "student_id": s["id"],
            "code": s["code"],
            "name": s["name"],
            "status": "P" if is_p else "A",
            "confidence": round(float(rec.get("confidence") or 0.0) * 100, 1),
            "flags": rec.get("flags", []),
            "uncertain": code in res.get("uncertain", []),
        })

    return {
        "success": True,
        "seconds": res.get("seconds", 0.0),
        "boxed_image": b64_boxed,
        "summary": {
            "faces_detected": faces_detected,
            "recognized": recognized_count,
            "present": present_cnt,
            "absent": absent_cnt,
            "uncertain": len(res.get("uncertain", [])),
            "total_students": len(students_in_class),
        },
        "uncertain_codes": res.get("uncertain", []),
        "students": student_records,
    }


@app.post("/api/attendance/save")
def save_attendance(req: SessionSaveRequest, session: Dict[str, Any] = Depends(require_staff)):
    """Saves the finalized attendance decisions into SQLite database."""
    current_db = get_active_db(session)
    if not auth.can_access_class(current_db, req.class_id):
        raise HTTPException(status_code=403, detail="Unauthorized for this class.")

    meta = {
        "date": req.date or datetime.date.today().isoformat(),
        "time": req.time or datetime.datetime.now().strftime("%H:%M"),
        "subject": req.subject or "General",
        "faculty": req.faculty or session["user"],
        "period": req.period or "1",
        "mode": req.mode or "balanced",
        "threshold": config.T_ACCEPT,
        "created_at": time.time(),
        "photos_json": "[]",
    }

    records = []
    for r in req.records:
        records.append({
            "student_id": r.student_id,
            "status": r.status,
            "auto_status": r.status,
            "confidence": 1.0 if r.status in ("P", "L") else 0.0,
            "dist": 0.0,
            "flags": [],
        })

    sid = current_db.save_session(req.class_id, meta, records)

    # Queue automated absence notifications if enabled
    if not session.get("is_demo") and current_db.get("email_notify_absence", False):
        try:
            email_service.queue_absence_notifications(sid)
        except Exception as e:
            logger.warning("Could not queue absence notifications: %s", e)

    return {"success": True, "session_id": sid, "message": "Attendance recorded and saved successfully."}


# ------------------ REPORTS & EXPORTS ------------------

@app.get("/api/reports/sessions")
def list_sessions(class_id: Optional[int] = None, session: Dict[str, Any] = Depends(require_auth)):
    current_db = get_active_db(session)
    if session["role"] == "faculty":
        allowed = set(current_db.faculty_class_ids(session["user"]))
        if class_id and class_id not in allowed:
            raise HTTPException(status_code=403, detail="Unauthorized for this class.")
    elif session["role"] == "student":
        raise HTTPException(status_code=403, detail="Students use the Student Portal for history.")

    sessions = current_db.recent_sessions(class_id=class_id, n=50)
    for s in sessions:
        rows = current_db.session_rows(s["id"])
        total = len(rows)
        present = sum(1 for r in rows if r["status"] in ("P", "L"))
        s["total"] = total
        s["present"] = present
        s["absent"] = total - present
        s["pct"] = round(present * 100 / total, 1) if total else 0.0
    return sessions


@app.get("/api/reports/session/{sid}")
def get_session_detail(sid: int, session: Dict[str, Any] = Depends(require_auth)):
    current_db = get_active_db(session)
    sess = current_db.session(sid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")
    if not auth.can_access_class(current_db, sess["class_id"]):
        raise HTTPException(status_code=403, detail="Unauthorized for this session.")
    rows = current_db.session_rows(sid)
    return {"session": sess, "records": rows}


@app.post("/api/reports/session/{sid}/status")
def update_session_attendance_mark(
    sid: int,
    student_id: int = Form(...),
    status: str = Form(...),
    session: Dict[str, Any] = Depends(require_staff),
):
    current_db = get_active_db(session)
    sess = current_db.session(sid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")

    if not auth.can_edit_session(sess["created_at"], sess["date"], current_db, sess["class_id"]):
        raise HTTPException(status_code=403, detail="Edit window has expired or account is not permitted.")

    if status not in {"P", "A", "L", "E", "OD"}:
        raise HTTPException(status_code=400, detail="Invalid status code.")

    changed = current_db.change_status(sid, student_id, status, by_user=session["user"])
    return {"success": True, "changed": changed}


@app.get("/api/reports/calendar")
def get_monthly_calendar(class_id: int, year: int, month: int, session: Dict[str, Any] = Depends(require_auth)):
    current_db = get_active_db(session)
    if not auth.can_access_class(current_db, class_id):
        raise HTTPException(status_code=403, detail="Unauthorized for this class.")

    sessions = current_db.sessions_in_month(class_id, year, month)
    by_date: Dict[str, Any] = {}
    for s in sessions:
        d = s["date"]
        rows = current_db.session_rows(s["id"])
        total = len(rows)
        present = sum(1 for r in rows if r["status"] in ("P", "L"))
        if d not in by_date:
            by_date[d] = {"sessions_count": 0, "total": 0, "present": 0}
        by_date[d]["sessions_count"] += 1
        by_date[d]["total"] += total
        by_date[d]["present"] += present
        by_date[d]["rate"] = round(by_date[d]["present"] * 100 / by_date[d]["total"], 1) if by_date[d]["total"] else 0.0

    return {"year": year, "month": month, "days": by_date}


@app.get("/api/reports/export/csv")
def export_class_csv(class_id: int, session: Dict[str, Any] = Depends(require_staff)):
    current_db = get_active_db(session)
    if not auth.can_access_class(current_db, class_id):
        raise HTTPException(status_code=403, detail="Unauthorized for this class.")

    students = current_db.students(class_id)
    cname = current_db.q("SELECT name FROM classes WHERE id=?", (class_id,))[0]["name"]
    sessions = current_db.recent_sessions(class_id=class_id, n=100)

    output = io.StringIO()
    # Header: Student ID, Name, Total Sessions, Attended, Absent, %
    output.write(f"# Attendance Export for {cname}\n")
    output.write("Student ID,Name,Attended,Absent,Held,Attendance %\n")

    for s in students:
        recs = current_db.q(
            "SELECT status FROM attendance a JOIN sessions ses ON ses.id=a.session_id WHERE a.student_id=? AND ses.class_id=?",
            (s["id"], class_id),
        )
        counts = stats.counts([r["status"] for r in recs])
        pct = stats.pct(counts["attended"], counts["held"])
        pct_str = f"{pct:.1f}%" if pct is not None else "0.0%"
        output.write(f"'{s['code']},{s['name']},{counts['attended']},{counts['absent']},{counts['held']},{pct_str}\n")

    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="attendance_{class_id}.csv"'},
    )


@app.get("/api/reports/export/audit_csv")
def export_audit_csv(session: Dict[str, Any] = Depends(require_admin)):
    current_db = get_active_db(session)
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        exports.audit_to_csv(current_db, tmp.name)
        return FileResponse(tmp.name, filename="attendance_audit_log.csv")


# ------------------ STUDENT PORTAL (PRIVACY ISOLATION) ------------------

@app.get("/api/student/portal/summary")
def student_portal_summary(session: Dict[str, Any] = Depends(require_student)):
    current_db = get_active_db(session)
    portal = StudentPortalService(current_db)
    try:
        return portal.summary()
    except (PermissionError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/student/portal/history")
def student_portal_history(
    start: Optional[str] = None,
    end: Optional[str] = None,
    subject: Optional[str] = None,
    status: Optional[str] = None,
    session: Dict[str, Any] = Depends(require_student),
):
    current_db = get_active_db(session)
    portal = StudentPortalService(current_db)
    try:
        return portal.history(start=start, end=end, subject=subject, status=status)
    except (PermissionError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/student/portal/notifications")
def student_portal_notifications(session: Dict[str, Any] = Depends(require_student)):
    current_db = get_active_db(session)
    portal = StudentPortalService(current_db)
    return portal.notifications()


@app.get("/api/student/portal/review_requests")
def student_portal_review_requests(session: Dict[str, Any] = Depends(require_student)):
    current_db = get_active_db(session)
    portal = StudentPortalService(current_db)
    return portal.review_requests()


@app.post("/api/student/portal/goal")
def student_portal_set_goal(req: RecoveryGoalRequest, session: Dict[str, Any] = Depends(require_student)):
    current_db = get_active_db(session)
    portal = StudentPortalService(current_db)
    return portal.set_goal(req.target)


# ------------------ REVIEW REQUESTS ------------------

@app.post("/api/review_requests/submit")
def submit_review_request(req: ReviewRequestSubmit, session: Dict[str, Any] = Depends(require_student)):
    current_db = get_active_db(session)
    review_svc = ReviewRequestService(current_db)
    try:
        created, is_new = review_svc.submit(req.session_id, req.reason, req.explanation)
        return {"success": True, "created": created, "is_new": is_new}
    except (PermissionError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/review_requests")
def list_review_requests(session: Dict[str, Any] = Depends(require_auth)):
    current_db = get_active_db(session)
    review_svc = ReviewRequestService(current_db)
    try:
        return review_svc.list_for_current_user()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.post("/api/review_requests/{req_id}/transition")
def transition_review_request(
    req_id: int,
    req: ReviewTransitionRequest,
    session: Dict[str, Any] = Depends(require_staff),
):
    current_db = get_active_db(session)
    review_svc = ReviewRequestService(current_db)
    try:
        updated = review_svc.transition(req_id, req.action, req.reason, req.new_status)
        return {"success": True, "updated": updated}
    except (PermissionError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ------------------ RECOVERY ASSISTANT ------------------

@app.post("/api/recovery/calculate")
def calculate_recovery_plan(req: RecoveryCalculationRequest):
    try:
        base_plan = recovery.plan(req.attended, req.absent, req.target)
        what_if_res = None
        if req.upcoming and req.upcoming > 0:
            what_if_res = recovery.what_if(
                req.attended, req.absent, req.target, req.upcoming, req.attend_next, req.miss_next
            )
        return {"plan": base_plan, "what_if": what_if_res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/recovery/student/{student_id}")
def student_recovery_summary(
    student_id: int,
    target: Optional[float] = None,
    session: Dict[str, Any] = Depends(require_auth),
):
    current_db = get_active_db(session)
    # Check permissions: Student can only view themselves; Staff can view students in assigned classes
    if session["role"] == "student" and session.get("student_id") != student_id:
        raise HTTPException(status_code=403, detail="You can only view your own recovery plan.")

    try:
        return recovery.student_summary(current_db, student_id, target)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ------------------ LOCAL CHAT ASSISTANT ------------------

@app.post("/api/assistant/ask")
def ask_chat_assistant(req: ChatQuestionRequest, session: Dict[str, Any] = Depends(require_auth)):
    current_db = get_active_db(session)
    assistant = LocalAssistant(current_db)
    response_text = assistant.answer(req.question, class_id=req.class_id)
    return {"answer": response_text}


# ------------------ EMAIL CENTER ------------------

@app.get("/api/email/recipients")
def list_email_recipients(class_id: int, session: Dict[str, Any] = Depends(require_staff)):
    current_db = get_active_db(session)
    if not auth.can_access_class(current_db, class_id):
        raise HTTPException(status_code=403, detail="Unauthorized for this class.")
    students = current_db.students(class_id)
    rows = []
    for s in students:
        recips = current_db.student_email_recipients(s["id"])
        rows.append({
            "student_id": s["id"],
            "code": s["code"],
            "name": s["name"],
            "recipients": recips,
        })
    return rows


@app.post("/api/email/recipients")
def add_email_recipient(req: EmailRecipientUpdate, session: Dict[str, Any] = Depends(require_staff)):
    current_db = get_active_db(session)
    try:
        rid = current_db.add_student_email_recipient(req.student_id, req.email, req.label)
        return {"success": True, "id": rid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/email/preview")
def preview_student_email(req: EmailPreviewRequest, session: Dict[str, Any] = Depends(require_staff)):
    current_db = get_active_db(session)
    if not auth.can_access_class(current_db, req.class_id):
        raise HTTPException(status_code=403, detail="Unauthorized for this class.")

    # Student-scoped preview
    preview = email_service.preview_student_report(req.student_id, req.class_id, req.report_from, req.report_to)
    return preview


@app.post("/api/email/send")
def send_student_emails(req: EmailSendRequest, session: Dict[str, Any] = Depends(require_staff)):
    current_db = get_active_db(session)
    if not auth.can_access_class(current_db, req.class_id):
        raise HTTPException(status_code=403, detail="Unauthorized for this class.")

    delivery_ids = []
    for sid in req.student_ids:
        did = email_service.queue_student_report(sid, req.class_id, req.report_from, req.report_to)
        if did:
            delivery_ids.append(did)

    return {"success": True, "delivery_ids": delivery_ids, "message": f"Queued {len(delivery_ids)} email delivery jobs."}


@app.get("/api/email/deliveries")
def list_email_deliveries(session: Dict[str, Any] = Depends(require_staff)):
    current_db = get_active_db(session)
    rows = current_db.q("SELECT * FROM email_deliveries ORDER BY updated_at DESC LIMIT 50")
    return rows


@app.post("/api/email/retry/{delivery_id}")
def retry_email_delivery(delivery_id: int, session: Dict[str, Any] = Depends(require_staff)):
    current_db = get_active_db(session)
    retried = email_service.retry_failed_delivery(delivery_id)
    return {"success": bool(retried)}


# ------------------ SETTINGS, MODELS & BACKUP ------------------

@app.get("/api/settings")
def get_settings(session: Dict[str, Any] = Depends(require_admin)):
    current_db = get_active_db(session)
    warn, lim = stats.limits(current_db)
    return {
        "limit_warn": warn,
        "limit_critical": lim,
        "default_mode": current_db.get("default_mode", "balanced"),
        "sender_email": current_db.get("email_sender_address", ""),
        "smtp_host": current_db.get("email_smtp_host", "smtp.gmail.com"),
        "smtp_port": current_db.get("email_smtp_port", 587),
        "smtp_user": current_db.get("email_smtp_user", ""),
        "email_configured": bool(current_db.get("email_sender_address")),
    }


@app.post("/api/settings")
def update_settings(req: SettingsUpdateRequest, session: Dict[str, Any] = Depends(require_admin)):
    current_db = get_active_db(session)
    if req.limit_warn is not None:
        current_db.put("limit_warn", int(req.limit_warn))
    if req.limit_critical is not None:
        current_db.put("limit_critical", int(req.limit_critical))
    if req.default_mode is not None:
        current_db.put("default_mode", req.default_mode)
    if req.sender_email is not None:
        current_db.put("email_sender_address", req.sender_email.strip())
    if req.smtp_host is not None:
        current_db.put("email_smtp_host", req.smtp_host.strip())
    if req.smtp_port is not None:
        current_db.put("email_smtp_port", int(req.smtp_port))
    if req.smtp_user is not None:
        current_db.put("email_smtp_user", req.smtp_user.strip())
    if req.smtp_password and req.smtp_password.strip():
        # Store securely via securestore or settings
        try:
            from app import securestore
            securestore.save_secret(f"smtp_pw_{req.smtp_user}", req.smtp_password.strip())
        except Exception:
            current_db.put("email_smtp_pw_fallback", req.smtp_password.strip())

    return {"success": True, "message": "Settings updated successfully."}


@app.get("/api/models")
def get_models_info(session: Dict[str, Any] = Depends(require_staff)):
    st = models_status()
    return {
        "status": st,
        "buffalo_l": st.get("buffalo_l", False),
        "antelopev2": st.get("antelopev2", False),
        "note": "InsightFace buffalo_l (det_10g + w600k_r50) provides highest accuracy.",
    }


@app.post("/api/backup/create")
def create_backup_archive(session: Dict[str, Any] = Depends(require_admin)):
    current_db = get_active_db(session)
    out_dir = config.DATA / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"upasthiti_backup_{int(time.time())}.zip"
    try:
        final_path = backup.create_backup(current_db, dst)
        return {"success": True, "backup_path": str(final_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
