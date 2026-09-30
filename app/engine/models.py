"""Model hub: one SCRFD face detector (always InsightFace buffalo_l) plus one or more
independent recognisers, chosen by the user in Settings > Models. Recognisers can mix
InsightFace (ONNX, fast, non-commercial research licence) and DeepFace (VGG-Face / ArcFace,
free for commercial use) - both are given the same aligned 112x112 face crop, so they can
be compared and voted on the same footing (see engine/match.py)."""
import numpy as np
from pathlib import Path


def normalize(v):
    v = np.asarray(v, dtype=np.float32).ravel()
    return v / (np.linalg.norm(v) + 1e-10)


class _InsightRecogniser:
    """Wraps one InsightFace recognition model (already loaded)."""
    def __init__(self, rec_model):
        self._rec = rec_model

    def get(self, img, face):
        return self._rec.get(img, face)


class _DeepFaceRecogniser:
    """Wraps a DeepFace model (VGG-Face / ArcFace) behind the same .get(img, face)
    interface the InsightFace recognisers use, so both kinds can sit in the same list.
    Alignment uses InsightFace's own 112x112 5-point crop for a fair, identical input."""
    def __init__(self, model_name):
        from deepface import DeepFace  # noqa: F401  (import check - raises if not installed)
        self.model_name = model_name
        self._DeepFace = DeepFace

    def get(self, img, face):
        from insightface.utils import face_align
        crop = face_align.norm_crop(img, face.kps, image_size=112)
        rep = self._DeepFace.represent(crop, model_name=self.model_name,
                                       detector_backend="skip", enforce_detection=False)
        return np.asarray(rep[0]["embedding"], dtype=np.float32)


def _deepface_available():
    try:
        import deepface  # noqa: F401
        return True
    except Exception:
        return False


def recogniser_available(model_id, models_dir):
    """Whether the files/packages a given recogniser needs are present."""
    from .. import config
    meta = config.MODEL_REGISTRY.get(model_id)
    if not meta:
        return False
    if meta["family"] == "insightface":
        pack = "buffalo_l" if model_id == "insightface_buffalo_rec" else "antelopev2"
        files = {"buffalo_l": "w600k_r50.onnx", "antelopev2": "glintr100.onnx"}[pack]
        return (Path(models_dir) / pack / files).exists()
    if meta["family"] == "deepface":
        return _deepface_available()
    return False


class ModelHub:
    """model_ids: list of keys from config.MODEL_REGISTRY, e.g.
    ["insightface_buffalo_rec", "insightface_antelope"]. At least one is required."""
    def __init__(self, models_dir, model_ids=None, providers=None):
        from .. import config
        from insightface.app import FaceAnalysis
        from insightface.app.common import Face
        self._Face = Face
        model_ids = model_ids or config.DEFAULT_MODEL_IDS
        providers = providers or self._pick_providers()
        root = str(Path(models_dir).parent if Path(models_dir).name == "models" else models_dir)

        # Detector: always SCRFD from buffalo_l, loaded once regardless of recogniser choice.
        need_buffalo_rec = "insightface_buffalo_rec" in model_ids
        det_app = FaceAnalysis(name="buffalo_l", root=root, providers=providers,
                               allowed_modules=["detection", "recognition"] if need_buffalo_rec else ["detection"])
        det_app.prepare(ctx_id=0 if "CUDAExecutionProvider" in providers else -1, det_size=(640, 640))
        self.det = det_app.models["detection"]

        self.recs = []       # list of (label, recogniser_obj)
        self._skipped = []   # model_ids that could not be loaded, with reason
        for mid in model_ids:
            meta = config.MODEL_REGISTRY.get(mid)
            if not meta:
                self._skipped.append((mid, "unknown model id")); continue
            try:
                if mid == "insightface_buffalo_rec":
                    self.recs.append((meta["label"], _InsightRecogniser(det_app.models["recognition"])))
                elif mid == "insightface_antelope":
                    a2 = FaceAnalysis(name="antelopev2", root=root, providers=providers,
                                      allowed_modules=["detection", "recognition"])
                    a2.prepare(ctx_id=0 if "CUDAExecutionProvider" in providers else -1, det_size=(640, 640))
                    self.recs.append((meta["label"], _InsightRecogniser(a2.models["recognition"])))
                elif mid == "deepface_vggface":
                    self.recs.append((meta["label"], _DeepFaceRecogniser("VGG-Face")))
                elif mid == "deepface_arcface":
                    self.recs.append((meta["label"], _DeepFaceRecogniser("ArcFace")))
                else:
                    self._skipped.append((mid, "not wired up")); continue
            except Exception as e:
                self._skipped.append((mid, str(e)))
        if not self.recs:
            raise RuntimeError("No recognition model could be loaded. Check Settings > Models.")
        self.providers = providers
        self.model_ids = [m for m in model_ids if m not in {s for s, _ in self._skipped}]

    @staticmethod
    def _pick_providers():
        try:
            import onnxruntime as ort
            av = ort.get_available_providers()
            return [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in av] or ["CPUExecutionProvider"]
        except Exception:
            return ["CPUExecutionProvider"]

    @property
    def model_names(self):
        return [n for n, _ in self.recs]

    def embed(self, img, kps):
        """One normalised embedding per recogniser, aligned with the 5 SCRFD landmarks."""
        f = self._Face(kps=np.asarray(kps, dtype=np.float32))
        return [normalize(rec.get(img, f)) for _, rec in self.recs]
