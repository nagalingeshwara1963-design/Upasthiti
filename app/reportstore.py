"""Saves the visual evidence of a session (boxed photos + result JSON) and reads it back."""
import json, cv2, shutil
from datetime import date, datetime
from pathlib import Path
from . import config

COL_OK, COL_UNSURE, COL_NONE = (60, 160, 40), (0, 140, 240), (140, 140, 140)


def session_dir(sid):
    d = config.REPORTS_DIR / f"session_{sid}"; d.mkdir(parents=True, exist_ok=True); return d


def draw_boxed(img, faces, unsure_flags=("weak_match", "close_call", "models_disagree")):
    """Boxes coloured by outcome, labelled with the last 4 characters of the student ID (ASCII-safe)."""
    out = img.copy(); s = out.shape[1] / 1448.0
    for f in faces:
        x1, y1, x2, y2 = [int(v) for v in f["bbox"]]
        code = f.get("student")
        if code is None: col, txt = COL_NONE, "?"
        elif set(f.get("flags", [])) & set(unsure_flags): col, txt = COL_UNSURE, code[-4:]
        else: col, txt = COL_OK, code[-4:]
        cv2.rectangle(out, (x1, y1), (x2, y2), col, max(2, int(3 * s)))
        fs = 0.5 * s + 0.2
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, fs, 2)
        ty = y1 - 5 if y1 - th - 8 > 0 else y2 + th + 6
        cv2.rectangle(out, (x1, ty - th - 4), (x1 + tw + 6, ty + 4), (255, 255, 255), -1)
        cv2.putText(out, txt, (x1 + 3, ty), cv2.FONT_HERSHEY_SIMPLEX, fs, col, 2, cv2.LINE_AA)
    return out


def save_artifacts(sid, res, staged):
    """staged: list of {label, image}. Writes boxed photos + result.json. Returns list of image paths."""
    d = session_dir(sid); paths = []
    for i, (p, st) in enumerate(zip(res["photos"], staged), 1):
        boxed = draw_boxed(st["image"], p["faces"])
        fp = d / f"photo_{i}.jpg"; cv2.imwrite(str(fp), boxed, [cv2.IMWRITE_JPEG_QUALITY, 88]); paths.append(str(fp))
    slim = {"mode": res.get("mode"), "models": res.get("models"), "seconds": res.get("seconds"),
            "photos": [{"label": p["label"], "checks": [m for _, m in p["checks"]],
                        "faces": [{k: (v if k != "quality" else {"flags": v["flags"]}) for k, v in f.items() if k in ("bbox", "student", "dist", "confidence", "flags", "quality")} for f in p["faces"]]}
                       for p in res["photos"]],
            "uncertain": res.get("uncertain", []), "unknown_faces": len(res.get("unknown_faces", [])), "too_blurry": len(res.get("too_blurry", []))}
    (d / "result.json").write_text(json.dumps(slim), encoding="utf-8")
    return paths


def load(sid):
    d = config.REPORTS_DIR / f"session_{sid}"
    imgs = sorted(d.glob("photo_*.jpg"), key=lambda p: int(p.stem.split("_")[1])) if d.exists() else []
    meta = {}
    if (d / "result.json").exists():
        try: meta = json.loads((d / "result.json").read_text(encoding="utf-8"))
        except Exception: meta = {}
    return {"images": [str(p) for p in imgs], "meta": meta}


def purge_expired_session_artifacts(db, today=None):
    """Purge expired boxed group-photo evidence, never attendance rows or pending-review evidence."""
    days = db.get("photo_retention_days", 30)
    try: days = max(1, min(3650, int(days)))
    except (TypeError, ValueError): days = 30
    today = today or date.today()
    cutoff = today.toordinal() - days
    active = {r["session_id"] for r in db.q("""SELECT DISTINCT session_id FROM attendance_review_requests
        WHERE status IN ('Pending','Under Review','Escalated')""")}
    root = config.REPORTS_DIR.resolve()
    removed = 0
    for session in db.q("SELECT id,date FROM sessions WHERE date IS NOT NULL"):
        if session["id"] in active: continue
        try:
            if date.fromisoformat(session["date"]).toordinal() > cutoff: continue
        except (ValueError, TypeError): continue
        folder = config.REPORTS_DIR / f"session_{int(session['id'])}"
        try:
            resolved = folder.resolve()
            if resolved.parent != root or not resolved.name.startswith("session_") or not resolved.is_dir(): continue
            for child in resolved.iterdir():
                if child.is_file() and (child.name == "result.json" or
                        child.name.startswith("photo_") and child.suffix.lower() in {".jpg", ".jpeg", ".png"}):
                    child.unlink(); removed += 1
            # Leave any unexpected file untouched; remove only if empty.
            try: resolved.rmdir()
            except OSError: pass
        except OSError:
            continue
    return removed
