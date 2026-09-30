"""End-to-end attendance analysis for one session (one or more group photos)."""
import time
import numpy as np
from . import quality
from .detect import detect_faces
from .match import match_photo, confidence_pct
from .. import config

UNCERTAIN_FLAGS = {"weak_match", "close_call", "models_disagree"}


def aggregate_photo_results(hub, gallery, res_photos, mode="max", cfg=None, seconds=0.0):
    """Fuse already analyzed photos using the existing best-match session rule."""
    codes = gallery.codes
    students = {c: {"status": "A", "dist": None, "confidence": 0.0, "photo": None, "face": None, "flags": []} for c in codes}
    for pi, photo in enumerate(res_photos):
        for fi, face in enumerate(photo["faces"]):
            code = face["student"]
            if code is None: continue
            student = students[code]
            if student["status"] == "A" or face["dist"] < student["dist"]:
                student.update(status="P", dist=face["dist"], confidence=face["confidence"], photo=pi,
                               face=fi, flags=list(face["flags"]))
    uncertain = [code for code, s in students.items() if s["status"] == "P" and UNCERTAIN_FLAGS & set(s["flags"])]
    unknown = [(pi, fi) for pi, photo in enumerate(res_photos) for fi, face in enumerate(photo["faces"]) if face["student"] is None]
    too_blurry = [(pi, fi) for pi, fi in unknown
                  if {"blurry", "small"} & set(res_photos[pi]["faces"][fi]["quality"]["flags"])]
    return {"photos": res_photos, "students": students, "uncertain": uncertain,
            "unknown_faces": unknown, "too_blurry": too_blurry, "mode": mode,
            "models": hub.model_names, "config": dict(cfg or {}), "seconds": seconds}


def _embed_face(hub, img, f, enhance):
    embs = hub.embed(img, f["kps"])
    if enhance and ({"small", "blurry", "dark"} & set(f["quality"]["flags"])):
        try:
            crop, kp = quality.enhance_face_region(img, f["bbox"], f["kps"])
            e2 = hub.embed(crop, kp)
            embs = [(a + b) / (np.linalg.norm(a + b) + 1e-10) for a, b in zip(embs, e2)]
            f["enhanced"] = True
        except Exception:
            pass
    return embs


def analyse_session(hub, gallery, photos, mode="max", cfg=None, enhance=True,
                    progress=None, log=None, preview=None):
    """photos: list of {"label": str, "image": BGR ndarray}.
    Returns a result dict (see bottom). Callbacks: progress(0..1, text), log(text)."""
    cfg = dict(cfg or {})
    log = log or (lambda s: None)
    preview = preview or (lambda stage, pi, image, rows: None)
    progress = progress or (lambda p, t="": None)
    codes = gallery.codes
    res_photos = []
    n = len(photos)
    t0 = time.time()
    for pi, ph in enumerate(photos):
        base = pi / n; span = 1 / n
        img = ph["image"]
        checks = quality.photo_checks(img)
        for lvl, msg in checks: log(f"[{ph['label']}] {msg}")
        work = quality.enhance_photo(img) if any("dark" in m or "contrast" in m.lower() for _, m in checks) and enhance else img
        log(f"[{ph['label']}] Detecting faces ({mode} mode)...")
        faces = detect_faces(hub, work, mode=mode,
                             progress=lambda p, base=base, span=span: progress(base + span * 0.6 * p, "Detecting faces"))
        log(f"[{ph['label']}] {len(faces)} faces found")
        for f in faces:
            f["quality"] = quality.face_quality(work, f["bbox"], f["score"])
        preview("detected", pi, work, [{"bbox": f["bbox"], "student": None} for f in faces])
        embs = []
        for k, f in enumerate(faces):
            embs.append(_embed_face(hub, work, f, enhance))
            progress(base + span * (0.6 + 0.35 * (k + 1) / max(1, len(faces))), "Reading faces")
        if faces and codes:
            Ds = [gallery.distance_matrix(embs, m) for m in range(len(hub.recs))]
            dec = match_photo(Ds, cfg)
        else:
            dec = [{"student_idx": None, "dist": None, "second": None, "flags": ["unknown_face"]} for _ in faces]
        rows = []
        for f, d in zip(faces, dec):
            j = d["student_idx"]
            rows.append({"bbox": f["bbox"], "score": f["score"], "quality": f["quality"],
                         "enhanced": f.get("enhanced", False),
                         "student": codes[j] if j is not None else None,
                         "dist": d["dist"], "confidence": confidence_pct(d["dist"]) if (j is not None and d["dist"] is not None) else 0.0,
                         "second": d["second"], "flags": d["flags"],
                         "embs": embs[len(rows)]})
        res_photos.append({"label": ph["label"], "checks": checks, "faces": rows})
        preview("matched", pi, work, rows)
        progress(base + span, "Matching")
    progress(1.0, "Done")
    elapsed = time.time() - t0
    log(f"Finished in {elapsed:.1f}s")
    return aggregate_photo_results(hub, gallery, res_photos, mode, cfg, elapsed)
