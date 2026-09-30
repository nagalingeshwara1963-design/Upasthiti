"""FastAPI Web Server for Upasthiti Classroom Attendance System."""
import base64
import datetime
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, auth
from app.db import DB
from app.services import Service, imread, models_status
from app.engine.pipeline import analyse_session
from app.engine.gallery import enroll_photo

app = FastAPI(
    title="Upasthiti Web Attendance",
    description="Online Face Recognition Classroom Attendance System",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize singletons
db = DB()
svc = Service(db)

# Ensure admin session active for service layer
auth._new_session("admin", "admin")

STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ------------------ PYDANTIC MODELS ------------------
class ClassCreate(BaseModel):
    name: str
    college: Optional[str] = ""
    year: Optional[str] = ""
    branch: Optional[str] = ""
    section: Optional[str] = ""

class StudentCreate(BaseModel):
    code: str
    name: str

class AttendanceDecision(BaseModel):
    student_id: int
    status: str  # 'P', 'A', 'L', 'E', 'OD'

class SessionSaveRequest(BaseModel):
    class_id: int
    date: str
    time: str
    subject: str
    faculty: str
    period: str
    mode: Optional[str] = "balanced"
    records: List[AttendanceDecision]


# ------------------ HTML ROUTE ------------------
@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    index_file = TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Upasthiti Web Interface is loading...</h1>")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


# ------------------ API ROUTES ------------------
@app.get("/api/status")
def get_system_status():
    classes_count = len(db.classes())
    st = models_status()
    models_ready = bool(st.get("buffalo_l"))
    
    # Total students across all classes
    all_students = db.q("SELECT COUNT(*) as count FROM students WHERE active=1")
    total_students = all_students[0]["count"] if all_students else 0
    
    all_sessions = db.q("SELECT COUNT(*) as count FROM sessions")
    total_sessions = all_sessions[0]["count"] if all_sessions else 0
    
    return {
        "status": "healthy",
        "models_ready": models_ready,
        "models": st,
        "stats": {
            "classes": classes_count,
            "students": total_students,
            "sessions": total_sessions
        }
    }


@app.get("/api/classes")
def list_classes():
    return db.classes()


@app.post("/api/classes")
def create_class(req: ClassCreate):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Class name cannot be empty")
    try:
        cid = db.add_class(name, req.college, req.year, req.branch, req.section)
        return {"id": cid, "name": name, "message": "Class created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/classes/{class_id}/students")
def get_students(class_id: int):
    students = db.students(class_id)
    g = svc.load_gallery(class_id)
    for s in students:
        s["enrolled_faces"] = len(g.students.get(s["code"], {}).get("embs", []))
    return students


@app.post("/api/classes/{class_id}/students")
def add_student(class_id: int, req: StudentCreate):
    code = req.code.strip()
    name = req.name.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Student code/ID required")
    try:
        sid = db.save_student(class_id, code, name, [])
        return {"id": sid, "code": code, "name": name, "message": "Student created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/classes/{class_id}/students/{code}/enroll")
async def enroll_student_photo(class_id: int, code: str, file: UploadFile = File(...)):
    """Uploads and embeds an enrollment face photo for a student."""
    content = await file.read()
    arr = np.frombuffer(content, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image file")

    hub = svc.get_hub()
    embs, info = enroll_photo(hub, img)
    if embs is None:
        raise HTTPException(status_code=400, detail="No clear face detected in this photo. Please upload a clear frontal photo.")

    # Save to enroll photos directory
    outdir = config.DATA / "enroll" / f"class_{class_id}"
    outdir.mkdir(parents=True, exist_ok=True)
    dst = outdir / f"{code}_{int(time.time()*1000)}.jpg"
    cv2.imwrite(str(dst), img, [cv2.IMWRITE_JPEG_QUALITY, 95])

    # Add to DB and Gallery
    students = {s["code"]: s for s in db.students(class_id)}
    if code not in students:
        raise HTTPException(status_code=404, detail="Student not found in this class")

    student_id = students[code]["id"]
    student_name = students[code]["name"]
    db.run("INSERT INTO enroll_photos(student_id, path) VALUES(?, ?)", (student_id, str(dst)))

    g = svc.load_gallery(class_id)
    g.add(code, student_name, embs)
    svc.save_gallery(class_id, g)

    return {"message": "Enrollment photo saved and gallery updated successfully", "faces_count": len(g.students.get(code, {}).get("embs", []))}


@app.post("/api/attendance/recognize")
async def recognize_attendance(
    class_id: int = Form(...),
    mode: str = Form("balanced"),
    enhance: bool = Form(True),
    image: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None)
):
    """
    Accepts either an uploaded classroom photo or base64 webcam capture.
    Detects all faces, matches them against enrolled students, and generates a boxed preview image.
    """
    img = None
    if image is not None:
        content = await image.read()
        arr = np.frombuffer(content, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    elif image_base64:
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]
        raw_data = base64.b64decode(image_base64)
        arr = np.frombuffer(raw_data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if img is None:
        raise HTTPException(status_code=400, detail="No valid image provided")

    g = svc.load_gallery(class_id)
    if not g.codes:
        raise HTTPException(status_code=400, detail="No enrolled students found in this class with photos. Please enroll students first.")

    hub = svc.get_hub()
    cfg, _ = svc.matching_config(class_id, automatic=True)

    # Run analysis
    res = analyse_session(
        hub, g,
        photos=[{"label": "Web Photo", "image": img}],
        mode=mode,
        cfg=cfg,
        enhance=enhance
    )

    # Draw bounding boxes and names on a copy of the image
    boxed = img.copy()
    h, w = boxed.shape[:2]
    faces_detected = 0
    recognized_count = 0

    if res.get("photos"):
        for face in res["photos"][0]["faces"]:
            faces_detected += 1
            bbox = face["bbox"]
            x1, y1, x2, y2 = [int(v) for v in bbox]
            code = face.get("student")
            conf = face.get("confidence", 0.0)

            if code:
                recognized_count += 1
                color = (50, 205, 50)  # Lime Green in BGR
                label = f"{code} ({int(conf * 100)}%)"
            else:
                color = (40, 40, 220)  # Red in BGR
                label = "Unknown"

            # Draw box
            cv2.rectangle(boxed, (x1, y1), (x2, y2), color, 2)
            
            # Label background banner
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(boxed, (x1, max(0, y1 - 22)), (x1 + tw + 8, y1), color, -1)
            cv2.putText(boxed, label, (x1 + 4, max(14, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    # Encode boxed image to JPEG base64
    _, buf = cv2.imencode(".jpg", boxed, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64_boxed = "data:image/jpeg;base64," + base64.b64encode(buf).decode("utf-8")

    # Format student roster results
    students_in_class = db.students(class_id)
    student_results = []
    present_count = 0
    absent_count = 0

    for s in students_in_class:
        code = s["code"]
        rec = res["students"].get(code, {"status": "A", "confidence": 0.0, "dist": None, "flags": []})
        is_present = (rec["status"] == "P")
        if is_present:
            present_count += 1
        else:
            absent_count += 1

        student_results.append({
            "student_id": s["id"],
            "code": s["code"],
            "name": s["name"],
            "status": "P" if is_present else "A",
            "confidence": round(rec.get("confidence", 0.0) * 100, 1),
            "flags": rec.get("flags", [])
        })

    return {
        "success": True,
        "boxed_image": b64_boxed,
        "summary": {
            "faces_detected": faces_detected,
            "recognized": recognized_count,
            "present": present_count,
            "absent": absent_count,
            "total_students": len(students_in_class)
        },
        "students": student_results,
        "raw_result": {
            "mode": mode,
            "seconds": res.get("seconds", 0.0)
        }
    }


@app.post("/api/attendance/save")
def save_attendance_session(req: SessionSaveRequest):
    """Commits attendance decisions to the SQLite database."""
    meta = {
        "date": req.date or datetime.date.today().isoformat(),
        "time": req.time or datetime.datetime.now().strftime("%H:%M"),
        "subject": req.subject or "General",
        "faculty": req.faculty or "Admin",
        "period": req.period or "1",
        "mode": req.mode or "balanced",
        "threshold": config.T_ACCEPT,
        "created_at": time.time(),
        "photos_json": "[]"
    }

    records = []
    for r in req.records:
        records.append({
            "student_id": r.student_id,
            "status": r.status,
            "auto_status": r.status,
            "confidence": 1.0 if r.status == "P" else 0.0,
            "dist": 0.0,
            "flags": []
        })

    sid = db.save_session(req.class_id, meta, records)
    return {"success": True, "session_id": sid, "message": "Attendance recorded successfully"}


@app.get("/api/reports/recent")
def get_recent_reports(class_id: Optional[int] = None):
    return db.recent_sessions(class_id=class_id, n=15)


@app.get("/api/reports/session/{sid}")
def get_session_detail(sid: int):
    sess = db.session(sid)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    rows = db.session_rows(sid)
    return {"session": sess, "records": rows}


@app.post("/api/reports/session/{sid}/status")
def update_student_attendance_status(sid: int, student_id: int = Form(...), status: str = Form(...)):
    changed = db.change_status(sid, student_id, status, by_user="web_admin")
    return {"success": True, "changed": changed}


@app.get("/api/reports/calendar")
def get_calendar_attendance(class_id: int, year: int, month: int):
    """Returns sessions and attendance stats grouped by date for monthly calendar view."""
    sessions = db.sessions_in_month(class_id, year, month)
    by_date = {}
    for s in sessions:
        d = s["date"]
        rows = db.session_rows(s["id"])
        total = len(rows)
        present = sum(1 for r in rows if r["status"] == "P")
        pct = round((present / total * 100), 1) if total > 0 else 0
        if d not in by_date:
            by_date[d] = {"sessions_count": 0, "total": 0, "present": 0}
        by_date[d]["sessions_count"] += 1
        by_date[d]["total"] += total
        by_date[d]["present"] += present
        by_date[d]["rate"] = round((by_date[d]["present"] / by_date[d]["total"] * 100), 1) if by_date[d]["total"] > 0 else 0
    return {"year": year, "month": month, "days": by_date}
