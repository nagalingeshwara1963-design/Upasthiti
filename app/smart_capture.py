"""Laptop-side incremental analysis and conservative guidance for phone captures."""
from __future__ import annotations

import logging
import queue
import threading
import time

import cv2
import numpy as np

from .services import imread
from .engine.pipeline import UNCERTAIN_FLAGS, aggregate_photo_results, analyse_session

log = logging.getLogger(__name__)


def summarize_capture(photos, total_students, analysis_errors=0):
    """Summarize evidence; coverage is unique confident identities / enrolled students."""
    observations = {}
    detected = unknown = 0
    flags = set()
    similar = False
    for photo in photos:
        detected += len(photo.get("faces", []))
        flags.update(photo.get("photo_flags", []))
        similar = similar or bool(photo.get("similar_to_previous"))
        for face in photo.get("faces", []):
            identity = face.get("student")
            if identity is None:
                unknown += 1
                continue
            prior = observations.get(identity)
            candidate = {"confidence": float(face.get("confidence") or 0),
                         "uncertain": bool(UNCERTAIN_FLAGS & set(face.get("flags", [])))}
            if prior is None or candidate["confidence"] > prior["confidence"]:
                observations[identity] = candidate
    confident = sum(not item["uncertain"] for item in observations.values())
    uncertain = sum(item["uncertain"] for item in observations.values())
    total = max(0, int(total_students))
    not_observed = max(0, total - len(observations))
    percentage = round(confident * 100 / total) if total else 0
    recommendations = []
    if "blurry" in flags: recommendations.append("Some faces look blurry; hold the phone steady.")
    if "small" in flags: recommendations.append("Some faces are small; move closer if practical.")
    if "dark" in flags: recommendations.append("The image is dark; improve the lighting if possible.")
    if not recommendations and (not_observed or uncertain or unknown):
        recommendations.append("Capture another photo from a different angle if useful.")
    if analysis_errors:
        recommendations.append("Some photos could not be analyzed; finish to continue with the normal review workflow.")
    elif not recommendations:
        recommendations.append("Current captures include clear identity evidence. Review uncertain faces before saving.")
    return {"state": "ready" if not analysis_errors else "partial",
            "photos_analyzed": len(photos), "detected_faces": detected,
            "confidently_observed": confident, "uncertain_students": uncertain,
            "unknown_faces": unknown, "not_yet_observed": not_observed,
            "total_students": total, "coverage_percent": percentage,
            "another_capture_suggested": bool(not_observed or uncertain or unknown or analysis_errors),
            "similar_to_previous": similar, "analysis_errors": int(analysis_errors),
            "guidance": " ".join(recommendations)}


def _difference_hash(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    return small[:, 1:] > small[:, :-1]


class SmartCaptureAnalyzer:
    """Serialize per-photo laptop analysis while reusing the application's cached hub."""
    def __init__(self, service, class_id, mode, cfg, initial_photos=(), on_update=None):
        self.service, self.class_id = service, class_id
        self.mode, self.cfg = mode, dict(cfg)
        self.model_ids = tuple(service.selected_model_ids())
        self.on_update = on_update or (lambda _status: None)
        self._queue = queue.Queue()
        self._lock = threading.RLock()
        self._accepting = True
        self._cancelled = False
        self._finish_callback = None
        self._photos, self._items, self._hashes = [], [], []
        self._elapsed = 0.0
        self._upload_number = len(initial_photos)
        self._errors = 0
        self._summary = {"state": "waiting", "photos_analyzed": 0, "detected_faces": 0,
                         "confidently_observed": 0, "uncertain_students": 0,
                         "unknown_faces": 0, "not_yet_observed": 0,
                         "total_students": len(service.db.students(class_id)),
                         "coverage_percent": 0, "another_capture_suggested": False,
                         "analysis_errors": 0, "guidance": "Waiting for a photo."}
        for item in initial_photos:
            self._queue.put((item["image"], item["label"], None, True))
        self._thread = threading.Thread(target=self._work, name="UpasthitiSmartCapture", daemon=True)
        self._thread.start()
        if initial_photos:
            self._publish({**self._summary, "state": "analyzing", "guidance": "Analyzing the existing session photos on the laptop."})

    def submit(self, path):
        with self._lock:
            if not self._accepting or self._cancelled:
                return False
            self._upload_number += 1
            self._queue.put((str(path), f"Phone capture {self._upload_number}", str(path), False))
            self._summary = {**self._summary, "state": "analyzing", "guidance": "Photo received. Analyzing on the laptop."}
        self._publish(self._summary)
        return True

    def snapshot(self):
        with self._lock: return dict(self._summary)

    def _publish(self, summary):
        with self._lock: self._summary = dict(summary)
        try: self.on_update(dict(summary))
        except Exception: log.exception("Could not publish smart capture status")

    def finish(self, callback):
        with self._lock:
            if self._cancelled:
                return
            self._accepting = False
            self._finish_callback = callback
            self._queue.put(None)

    def cancel(self):
        with self._lock:
            self._cancelled = True
            self._accepting = False
            while True:
                try: self._queue.get_nowait()
                except queue.Empty: break
            self._queue.put(None)

    def _work(self):
        hub = gallery = None
        total = self._summary["total_students"]
        while True:
            task = self._queue.get()
            if task is None: break
            source, label, path, initial = task
            with self._lock:
                if self._cancelled: continue
            try:
                if hub is None:
                    self._publish({**self.snapshot(), "state": "analyzing", "guidance": "Loading the laptop recognition models."})
                    hub = self.service.get_hub()
                    if tuple(self.service.selected_model_ids()) != self.model_ids:
                        raise RuntimeError("The selected recognition models changed during capture.")
                    gallery = self.service.load_gallery(self.class_id)
                    if not gallery.codes:
                        raise RuntimeError("This class has no enrolled face templates yet.")
                image = source if isinstance(source, np.ndarray) else imread(source)
                if image is None:
                    raise ValueError("Photo could not be decoded")
                image_hash = _difference_hash(image)
                similar = any(int(np.count_nonzero(image_hash != prior)) <= 5 for prior in self._hashes)
                started = time.monotonic()
                result = analyse_session(hub, gallery, [{"label": label, "image": image}],
                                         mode=self.mode, cfg=self.cfg)
                self._elapsed += time.monotonic() - started
                photo = result["photos"][0]
                with self._lock:
                    if self._cancelled: break
                checks = list(photo.get("checks", []))
                photo["photo_flags"] = [flag for face in photo["faces"] for flag in face["quality"]["flags"]]
                messages = [message.casefold() for _, message in checks]
                if any("blurry" in message for message in messages): photo["photo_flags"].append("blurry")
                if any("dark" in message for message in messages): photo["photo_flags"].append("dark")
                if any("low resolution" in message for message in messages): photo["photo_flags"].append("small")
                if similar: checks.append(("warn", "Looks similar to an earlier capture (duplicate?)."))
                photo["checks"] = checks
                photo["similar_to_previous"] = similar
                self._hashes.append(image_hash)
                self._photos.append(photo)
                self._items.append({"path": path, "label": label, "image": image, "initial": initial,
                                    "checks": checks, "hash": image_hash})
                combined = aggregate_photo_results(hub, gallery, self._photos, self.mode, self.cfg, self._elapsed)
                self._publish(summarize_capture(combined["photos"], total, self._errors))
            except Exception as exc:
                log.error("Smart capture photo analysis failed; error_type=%s", type(exc).__name__)
                self._errors += 1
                self._publish(summarize_capture(self._photos, total, self._errors))
        with self._lock:
            if self._cancelled: return
            callback = self._finish_callback
        if callback:
            output = None
            if hub is not None and gallery is not None and self._photos:
                output = {"class_id": self.class_id, "mode": self.mode, "config": self.cfg,
                          "model_ids": self.model_ids, "items": list(self._items),
                          "result": aggregate_photo_results(hub, gallery, self._photos, self.mode, self.cfg, self._elapsed),
                          "complete": self._errors == 0}
            callback(output)
