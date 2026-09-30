"""Enrollment gallery: up to N photos per student -> stored embeddings (per recogniser).
Also groups a pile of bulk-imported photos into students automatically."""
import json
import os
import tempfile
import numpy as np
from .models import normalize

GALLERY_FORMAT_VERSION = 2


class GalleryCompatibilityError(RuntimeError):
    """Stored embeddings cannot be safely compared with the active recognisers."""


class Gallery:
    def __init__(self, n_models, recognizers=None, format_version=GALLERY_FORMAT_VERSION):
        self.n_models = n_models
        self.recognizers = recognizers
        self.format_version = format_version
        self.students = {}      # code -> {"name": str, "embs": [ [emb_m0, emb_m1,...], ... ]}

    def add(self, code, name, embs_per_model):
        s = self.students.setdefault(code, {"name": name, "embs": []})
        if name: s["name"] = name
        s["embs"].append([normalize(e) for e in embs_per_model])

    @property
    def codes(self):
        return sorted(self.students)

    def name(self, code):
        return self.students[code]["name"] or code

    def template_scores(self, face_embs, m):
        """Similarity of one face embedding (model m) to every student:
        0.5*best single photo + 0.5*average-photo template. Returns array aligned with self.codes."""
        out = []
        for c in self.codes:
            E = np.stack([e[m] for e in self.students[c]["embs"]])
            sims = E @ face_embs
            cen = normalize(E.mean(0)) @ face_embs
            out.append(0.5 * float(sims.max()) + 0.5 * float(cen))
        return np.array(out)

    def distance_matrix(self, faces_embs, m):
        """faces_embs: list of per-model embedding lists. Returns (F x S) cosine distances."""
        return np.array([1.0 - self.template_scores(fe[m], m) for fe in faces_embs])

    def save(self, path):
        data = {c: {"name": s["name"], "embs": [[e.tolist() for e in row] for row in s["embs"]]}
                for c, s in self.students.items()}
        payload = {"format_version": self.format_version, "n_models": self.n_models,
                   "recognizers": self.recognizers, "students": data}
        path = os.fspath(path)
        directory = os.path.dirname(os.path.abspath(path))
        fd, temporary = tempfile.mkstemp(prefix=".gallery-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        except Exception:
            try: os.unlink(temporary)
            except OSError: pass
            raise

    @classmethod
    def load(cls, path):
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict) or not isinstance(raw.get("n_models"), int) or not isinstance(raw.get("students"), dict):
                raise ValueError("required gallery fields are missing")
            g = cls(raw["n_models"], raw.get("recognizers"), raw.get("format_version", 1))
            for c, s in raw["students"].items():
                embeddings = [[np.array(e, dtype=np.float32) for e in row] for row in s["embs"]]
                if any(len(row) != g.n_models for row in embeddings):
                    raise ValueError("student embedding slots do not match n_models")
                g.students[c] = {"name": s["name"], "embs": embeddings}
            return g
        except GalleryCompatibilityError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise GalleryCompatibilityError(
                "The saved recognition gallery is unreadable or incomplete. Rebuild it from saved enrollment photos in "
                "Enroll → Manage Enrolled → Rebuild Recognition Gallery. The existing file was not changed."
            ) from exc

    def require_compatible(self, recognizers):
        if (self.format_version != GALLERY_FORMAT_VERSION or not isinstance(self.recognizers, list)
                or not self.recognizers):
            raise GalleryCompatibilityError(
                "This gallery predates recognizer metadata, so its embedding slots cannot be identified safely. "
                "Use Enroll → Manage Enrolled → Rebuild Recognition Gallery to regenerate it from saved enrollment photos."
            )
        if not all(isinstance(item, dict) and isinstance(item.get("id"), str)
                   and isinstance(item.get("version"), str) for item in self.recognizers):
            raise GalleryCompatibilityError(
                "This gallery has invalid recognizer metadata and cannot be matched safely. "
                "Use Enroll → Manage Enrolled → Rebuild Recognition Gallery."
            )
        if self.recognizers != recognizers or self.n_models != len(recognizers):
            old = ", ".join(item.get("id", "unknown") for item in self.recognizers)
            new = ", ".join(item.get("id", "unknown") for item in recognizers)
            raise GalleryCompatibilityError(
                f"This gallery was created for recognizers [{old}], but the active recognizers are [{new}]. "
                "The embeddings will not be compared. Use Enroll → Manage Enrolled → Rebuild Recognition Gallery."
            )

    # intra/inter statistics -> data-driven threshold suggestion
    def suggest_threshold(self, m, default=0.60):
        intra, inter = [], []
        codes = self.codes
        for i, c in enumerate(codes):
            E = np.stack([e[m] for e in self.students[c]["embs"]])
            if len(E) > 1:
                d = 1 - E @ E.T
                intra += list(d[np.triu_indices(len(E), 1)])
            for c2 in codes[i + 1:]:
                E2 = np.stack([e[m] for e in self.students[c2]["embs"]])
                inter += list((1 - E @ E2.T).ravel())
        info = {"n_intra": len(intra), "n_inter": len(inter)}
        if len(intra) < 4 or not inter:
            info["basis"] = "default (need 2+ photos per student to learn it)"
            return default, info
        g95 = float(np.percentile(intra, 95)); i05 = float(np.percentile(inter, 5))
        t = float(np.clip((g95 + i05) / 2, 0.35, 0.70))
        info.update({"basis": "learned from enrollment photos", "genuine95": g95, "impostor5": i05})
        return t, info


def enroll_photo(hub, img, min_score=0.5):
    """Best face in an enrollment photo -> (embeddings, info) or (None, reason)."""
    from .detect import detect_faces
    from .quality import face_quality
    faces = detect_faces(hub, img, mode="fast", min_size=40, full_sizes=[640, 960])
    faces = [f for f in faces if f["score"] >= min_score]
    if not faces:
        return None, {"status": "no_face"}
    faces.sort(key=lambda f: -(f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
    f = faces[0]
    q = face_quality(img, f["bbox"], f["score"])
    status = "ok"
    if len(faces) > 1:
        a1 = (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1])
        a2 = (faces[1]["bbox"][2] - faces[1]["bbox"][0]) * (faces[1]["bbox"][3] - faces[1]["bbox"][1])
        if a2 > 0.35 * a1:
            status = "multiple_faces"
    if q["flags"] and status == "ok":
        status = "check_quality"
    return hub.embed(img, f["kps"]), {"status": status, "bbox": f["bbox"], "quality": q, "score": f["score"]}


def group_photos(embs_m0, threshold=0.50):
    """Group photos of the same person. embs_m0: list of normalised embeddings (recogniser 0).
    Average-linkage clustering on cosine distance. Returns list of clusters (lists of indices)."""
    n = len(embs_m0)
    if n == 0: return []
    if n == 1: return [[0]]
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform
    E = np.stack(embs_m0)
    D = np.clip(1 - E @ E.T, 0, 2); np.fill_diagonal(D, 0)
    Z = linkage(squareform(D, checks=False), method="average")
    lab = fcluster(Z, t=threshold, criterion="distance")
    groups = {}
    for i, l in enumerate(lab): groups.setdefault(int(l), []).append(i)
    return sorted(groups.values(), key=lambda g: g[0])
