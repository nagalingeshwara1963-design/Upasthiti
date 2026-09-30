"""Synthetic demo database rooted outside the application's production data tree."""
from datetime import date, timedelta
from pathlib import Path
from . import config, auth
from .db import DB

_PATH_KEYS = ("ROOT", "DATA", "MODELS_DIR", "DB_PATH", "PHOTOS_DIR", "REPORTS_DIR", "BACKUP_DIR", "LOG_DIR", "PHONE_UPLOAD_DIR")


def swap_config_root(root):
    """Temporarily redirect all data paths and return the previous path constants."""
    old = {key: getattr(config, key) for key in _PATH_KEYS}
    config.ROOT = Path(root).resolve(); config.DATA = config.ROOT / "data"
    config.MODELS_DIR = config.DATA / "models"; config.DB_PATH = config.DATA / "upasthiti.db"
    config.PHOTOS_DIR = config.DATA / "photos"; config.REPORTS_DIR = config.DATA / "reports"
    config.BACKUP_DIR = config.DATA / "backups"; config.LOG_DIR = config.DATA / "logs"
    config.PHONE_UPLOAD_DIR = config.DATA / "phone_uploads"
    config.ensure_dirs()
    for directory in (config.DATA, config.MODELS_DIR, config.PHOTOS_DIR, config.REPORTS_DIR,
                      config.BACKUP_DIR, config.LOG_DIR, config.PHONE_UPLOAD_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    return old


def restore_config_paths(paths):
    for key in _PATH_KEYS: setattr(config, key, paths[key])


def seed_demo_database(db):
    """Create synthetic, clearly labelled sample records; no photos or real identities."""
    auth.set_password(db, "admin", "admin", "demo-admin-only")
    auth.set_password(db, "faculty", "demo-faculty", "demo-faculty-only")
    class_id = db.add_class("DEMO · Sample Class")
    db.set_faculty_classes("demo-faculty", [class_id])
    students = [db.save_student(class_id, f"DEMO{i:03}", f"Sample Student {i}", []) for i in range(1, 6)]
    for offset, statuses in ((8, ("P", "P", "A", "P", "A")),
                             (4, ("P", "A", "P", "P", "P")),
                             (0, ("P", "P", "P", "A", "P"))):
        day = (date.today() - timedelta(days=offset)).isoformat()
        db.save_session(class_id, {"date": day, "time": "09:00", "faculty": "Demo Faculty",
            "subject": "Demo Subject", "period": "1", "mode": "demo", "photos": []},
            [{"student_id": sid, "status": status} for sid, status in zip(students, statuses)])
    return {"class_id": class_id, "students": students}


def create_demo_database(root):
    old = swap_config_root(root)
    try:
        db = DB(config.DB_PATH); ids = seed_demo_database(db)
        return db, ids
    except Exception:
        restore_config_paths(old)
        raise
