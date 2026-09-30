"""Upasthiti - central paths and defaults. Everything lives under the install folder
(default C:\\Upasthiti). Nothing here points at any older attendance folder."""
import os
from pathlib import Path

APP_NAME = "Upasthiti"
APP_VERSION = "0.1.0-engine"
ROOT = Path(os.environ.get("UPASTHITI_HOME", Path(__file__).resolve().parents[1]))
DATA = ROOT / "data"
MODELS_DIR = DATA / "models"          # insightface packs: buffalo_l, antelopev2
DB_PATH = DATA / "upasthiti.db"
PHOTOS_DIR = DATA / "photos"
REPORTS_DIR = DATA / "reports"
BACKUP_DIR = DATA / "backups"
LOG_DIR = DATA / "logs"
PHONE_UPLOAD_DIR = DATA / "phone_uploads"  # short-lived, token-scoped phone uploads

MODEL_PACKS = {
    "buffalo_l": "https://github.com/deepinsight/insightface/releases/download/model-zoo/buffalo_l.zip",
    "antelopev2": "https://github.com/deepinsight/insightface/releases/download/model-zoo/antelopev2.zip",
}

# Matching defaults (cosine distance; lower = more similar). Calibrated on internal
# test photos - the benchmark tool re-checks them on your own data.
T_ACCEPT = 0.60      # at or below: confident match
T_REJECT = 0.72      # above: not this student
MARGIN_MIN = 0.04    # closest-vs-second-closest gap below this => flag as uncertain

LOW_ATTENDANCE_WARN = 80
LOW_ATTENDANCE_LIMIT = 75

def ensure_dirs():
    for d in (DATA, MODELS_DIR, PHOTOS_DIR, REPORTS_DIR, BACKUP_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Recognition model registry. Detection (finding faces in a photo) is always
# InsightFace SCRFD from the buffalo_l pack - that part is not swappable.
# What IS swappable is which recogniser(s) turn a detected face into a
# comparable "fingerprint". Multiple recognisers can run at once and vote
# (see engine/match.py) for extra reliability against false matches.
MODEL_REGISTRY = {
    "insightface_buffalo_rec": {
        "label": "InsightFace - Buffalo_L (ResNet-50)",
        "family": "insightface", "kind": "recognizer",
        "source": "InsightFace model zoo", "license": "non-commercial research licence",
        "speed": "fast", "accuracy": "very good",
        "embedding_version": "w600k_r50-v1",
        "note": "A fast, highly accurate recogniser with no known false-detection issues in testing.",
    },
    "insightface_antelope": {
        "label": "InsightFace - AntelopeV2 (ResNet-100)",
        "family": "insightface", "kind": "recognizer",
        "source": "InsightFace model zoo", "license": "non-commercial research licence",
        "speed": "medium", "accuracy": "excellent",
        "embedding_version": "glintr100-v1",
        "note": "Larger network than Buffalo_L; slower but sharper on close calls.",
    },
    "deepface_vggface": {
        "label": "DeepFace - VGG-Face",
        "family": "deepface", "kind": "recognizer",
        "source": "DeepFace (Oxford VGG-Face weights)", "license": "free for commercial use",
        "speed": "medium", "accuracy": "fair",
        "embedding_version": "vggface-v1",
        "note": "Can occasionally misread a face region in low-quality enrollment photos. "
                "Best used only alongside a second, independent recogniser.",
    },
    "deepface_arcface": {
        "label": "DeepFace - ArcFace",
        "family": "deepface", "kind": "recognizer",
        "source": "DeepFace (ArcFace weights)", "license": "free for commercial use",
        "speed": "medium", "accuracy": "good",
        "embedding_version": "arcface-v1",
        "note": "Commercially-licensed alternative to the InsightFace recognisers, slightly weaker "
                "on close calls between similar-looking students, but has no licensing question.",
    },
}
# Detection-only pack, always required regardless of which recognisers are picked.
DETECTOR_PACK = "buffalo_l"

# Best accuracy regardless of licence, based on internal benchmarking:
RECOMMENDED_MODEL_IDS = ["insightface_buffalo_rec", "insightface_antelope"]
# Best accuracy using only commercially-licensed recognisers (no InsightFace):
RECOMMENDED_COMMERCIAL_IDS = ["deepface_vggface", "deepface_arcface"]
DEFAULT_MODEL_IDS = RECOMMENDED_MODEL_IDS
