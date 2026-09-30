"""Glue between the UI and the engine: model loading, enrollment import/save, session run."""
import os, shutil, threading
from pathlib import Path
import cv2
import numpy as np
from . import config, auth
from .engine.gallery import Gallery, enroll_photo, group_photos
from .engine.models import normalize
from .engine.pipeline import analyse_session
from . import reportstore

NEED = {"buffalo_l": ["det_10g.onnx", "w600k_r50.onnx"], "antelopev2": ["glintr100.onnx", "scrfd_10g_bnkps.onnx"]}


def deepface_available():
    try:
        import deepface  # noqa: F401
        return True
    except Exception:
        return False


def imread(path):
    """cv2.imread that also works with non-ASCII Windows paths."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def models_status():
    return {p: all((config.MODELS_DIR / p / f).exists() for f in fs) for p, fs in NEED.items()}


class Service:
    def __init__(self, db):
        self.db = db
        self.hub = None
        self._lock = threading.Lock()

    def _require_class_access(self, class_id):
        if auth.current_role() not in ("admin", "faculty") or not auth.can_access_class(self.db, class_id):
            raise PermissionError("Your account is not authorized for this class.")

    def selected_model_ids(self):
        ids = self.db.get("model_ids", config.DEFAULT_MODEL_IDS)
        # never silently run on zero recognisers - fall back to the shipped default
        return ids if ids else config.DEFAULT_MODEL_IDS

    def set_model_ids(self, ids):
        self.db.put("model_ids", list(ids))
        self.reload_models()

    def reload_models(self):
        """Force the next get_hub() call to rebuild with the current selection."""
        with self._lock:
            self.hub = None

    def get_hub(self):
        with self._lock:
            if self.hub is None:
                st = models_status()
                if not st.get("buffalo_l"):
                    raise RuntimeError("Face detection model is not installed. Run Setup_Upasthiti.bat (or setup_models.py).")
                from .engine.models import ModelHub
                self.hub = ModelHub(config.MODELS_DIR, model_ids=self.selected_model_ids())
            return self.hub

    # ---------- galleries ----------
    def gallery_path(self, class_id):
        return config.DATA / "galleries" / f"class_{class_id}.json"

    def _recognizer_metadata(self):
        ids = self.hub.model_ids if self.hub is not None else self.selected_model_ids()
        return [{"id": mid, "version": config.MODEL_REGISTRY[mid]["embedding_version"]} for mid in ids]

    def load_gallery(self, class_id):
        p = self.gallery_path(class_id)
        recognizers = self._recognizer_metadata()
        if p.exists():
            gallery = Gallery.load(p)
            gallery.require_compatible(recognizers)
            return gallery
        return Gallery(len(recognizers), recognizers)

    def save_gallery(self, class_id, g):
        p = self.gallery_path(class_id); p.parent.mkdir(parents=True, exist_ok=True); g.save(p)

    # ---------- enrollment ----------
    def import_photos(self, paths, progress=None):
        """Detect + embed each photo, then group photos of the same person.
        Returns (records, groups, failed). record = {path, embs, info}."""
        hub = self.get_hub()
        records, failed = [], []
        for i, p in enumerate(paths):
            img = imread(p)
            if img is None:
                failed.append({"path": p, "reason": "unreadable"})
            else:
                embs, info = enroll_photo(hub, img)
                if embs is None:
                    failed.append({"path": p, "reason": "no_face", "image": img})
                else:
                    records.append({"path": p, "embs": embs, "info": info, "image": img})
            if progress: progress((i + 1) / len(paths))
        groups = group_photos([r["embs"][0] for r in records]) if records else []
        return records, [[records[i] for i in g] for g in groups], failed

    def save_enrollment(self, class_id, students):
        self._require_class_access(class_id)
        """students: list of {code, name, photos:[record]}. Adds to the gallery and copies photos."""
        if auth.current_role() not in ("admin", "faculty"):
            raise PermissionError("Only authorized staff can save student enrollment.")
        self.get_hub()
        g = self.load_gallery(class_id)
        cname = self.db.q("SELECT name FROM classes WHERE id=?", (class_id,))[0]["name"]
        outdir = config.DATA / "enroll" / f"class_{class_id}"
        outdir.mkdir(parents=True, exist_ok=True)
        for s in students:
            saved = []
            for n, r in enumerate(s["photos"], 1):
                dst = outdir / f"{s['code']}_{len(list(outdir.glob(s['code'] + '_*'))) + 1}.jpg"
                cv2.imwrite(str(dst), r["image"], [cv2.IMWRITE_JPEG_QUALITY, 95]); saved.append(dst)
                g.add(s["code"], s["name"], r["embs"])
            self.db.save_student(class_id, s["code"], s["name"], saved,
                                 email_recipients=s.get("email_recipients", ()))
        self.save_gallery(class_id, g)
        return g

    def find_similar_students(self, class_id, threshold=0.45, exclude_code=None):
        """Pairs of enrolled students whose faces are unusually close (closer than any
        genuine same-person gap we've measured). Flags likely duplicate enrollments or
        true lookalikes (twins) so more distinguishing photos can be added for both.
        exclude_code: skip pairs not involving this code (used right after adding one
        student, so we only warn about that student rather than re-scanning everyone)."""
        g = self.load_gallery(class_id)
        codes = g.codes
        pairs = []
        for i in range(len(codes)):
            for j in range(i + 1, len(codes)):
                c1, c2 = codes[i], codes[j]
                if exclude_code and exclude_code not in (c1, c2):
                    continue
                best = None
                for m in range(g.n_models):
                    E1 = np.stack([e[m] for e in g.students[c1]["embs"]])
                    E2 = np.stack([e[m] for e in g.students[c2]["embs"]])
                    d = float(1.0 - (E1 @ E2.T).max())   # closest pair of photos across the two students
                    best = d if best is None else min(best, d)
                if best is not None and best <= threshold:
                    pairs.append((c1, c2, best))
        return sorted(pairs, key=lambda x: x[2])

    def remove_student(self, class_id, code):
        self._require_class_access(class_id)
        path = self.gallery_path(class_id)
        if path.exists():
            # Removal is safe even for a legacy gallery: preserve its unknown metadata
            # and embeddings for other students, but remove this student's match entry.
            try:
                g = Gallery.load(path)
                g.students.pop(code, None)
                self.save_gallery(class_id, g)
            except Exception:
                # The corrupt/incompatible gallery cannot be used for matching; allow
                # archival to proceed, then require a safe rebuild before attendance.
                pass
        self.db.archive_student(class_id, code)

    def rebuild_class_gallery(self, class_id):
        """Re-embed every active student's saved photos; replace only after all succeed."""
        self._require_class_access(class_id)
        hub = self.get_hub()
        recognizers = self._recognizer_metadata()
        gallery = Gallery(len(recognizers), recognizers)
        for student in self.db.students(class_id):
            embedded = 0
            for path in self.db.student_photos(class_id, student["code"]):
                image = imread(path)
                if image is None:
                    continue
                embeddings, _info = enroll_photo(hub, image)
                if embeddings is not None:
                    gallery.add(student["code"], student["name"], embeddings)
                    embedded += 1
            if not embedded:
                raise RuntimeError(
                    f"Could not rebuild {student['code']}: no saved enrollment photo produced a usable face. "
                    "The existing gallery was left unchanged."
                )
        self.save_gallery(class_id, gallery)
        return gallery

    def rebuild_student_gallery(self, class_id, code):
        self._require_class_access(class_id)
        """Re-reads all remaining photo files for a student and updates the gallery embeddings."""
        g = self.load_gallery(class_id)
        if code not in g.students: return
        paths = self.db.student_photos(class_id, code)
        hub = self.get_hub()
        new_embs = []
        for p in paths:
            img = imread(p)
            if img is not None:
                embs, _ = enroll_photo(hub, img)
                if embs is not None:
                    new_embs.append([normalize(e) for e in embs])
        if new_embs:
            g.students[code]["embs"] = new_embs
        else:
            g.students.pop(code, None)
        self.save_gallery(class_id, g)

    def add_face_to_student(self, class_id, code, name, embs, crop_img):
        """Adds a single new face (from a group photo) to the student's gallery and saves the crop."""
        self._require_class_access(class_id)
        g = self.load_gallery(class_id)
        outdir = config.DATA / "enroll" / f"class_{class_id}"
        outdir.mkdir(parents=True, exist_ok=True)
        # Find next index
        existing = list(outdir.glob(f"{code}_*.jpg"))
        dst = outdir / f"{code}_{len(existing) + 1}.jpg"
        cv2.imwrite(str(dst), crop_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        
        self.db.run("INSERT INTO enroll_photos(student_id,path) SELECT id, ? FROM students WHERE class_id=? AND code=?", (str(dst), class_id, code))
        g.add(code, name, embs)
        self.save_gallery(class_id, g)


    # ---------- attendance ----------
    def matching_config(self, class_id, automatic=True, manual_accept=0.60):
        self._require_class_access(class_id)
        g = self.load_gallery(class_id)
        if automatic:
            t, info = g.suggest_threshold(0, default=config.T_ACCEPT)
        else:
            t, info = manual_accept, {"basis": "set manually"}
        return {"t_accept": t, "t_reject": t + (config.T_REJECT - config.T_ACCEPT)}, info

    def run_session(self, class_id, photos, mode, cfg, progress=None, log=None, preview=None):
        self._require_class_access(class_id)
        hub = self.get_hub()
        g = self.load_gallery(class_id)
        if not g.codes:
            raise RuntimeError("This class has no enrolled students yet.")
        return analyse_session(hub, g, photos, mode=mode, cfg=cfg, progress=progress, log=log, preview=preview)

    def save_session(self, class_id, meta, res, staged, chosen):
        """chosen: {student_code: 'P'|'A'|'L'|'E'|'OD'} final decisions (missing = system result)."""
        self._require_class_access(class_id)
        students = {s["code"]: s for s in self.db.students(class_id)}
        recs = []
        for code, s in res["students"].items():
            auto = "P" if s["status"] == "P" else "A"
            recs.append({"student_id": students[code]["id"], "status": chosen.get(code, auto), "auto_status": auto,
                         "confidence": s["confidence"], "dist": s["dist"], "flags": s["flags"]})
        sid = self.db.save_session(class_id, meta, recs)
        try:
            reportstore.save_artifacts(sid, res, staged)
        except Exception as e:
            print("could not save report images:", e)
        return sid
