"""Accuracy benchmark: measures the engine against YOUR labelled photos.

Manifest (JSON):
{"name": "My test",
 "classes": [{"name": "Batch 2",
              "enroll": {"ID001": {"name": "Asha", "photos": ["a1.jpg", "a2.jpg"]}, ...},
              "photos": ["group1.jpg"],
              "present": ["ID001", "ID003"]}]}      # who REALLY is in the photos
Run:  python -m app.tools.benchmark manifest.json
Compares several configurations so you can see what each safeguard adds."""
import json, sys, time
from pathlib import Path
import cv2, numpy as np
from .. import config
from ..engine.models import ModelHub
from ..engine.gallery import Gallery, enroll_photo
from ..engine.detect import detect_faces
from ..engine.quality import face_quality
from ..engine.match import assign


def _embed_all(hub, img, mode):
    faces = detect_faces(hub, img, mode=mode)
    embs = []
    for f in faces:
        f["quality"] = face_quality(img, f["bbox"], f["score"])
        embs.append(hub.embed(img, f["kps"]))
    return faces, embs


def run(manifest_path, mode="max"):
    man = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    hub = ModelHub(config.MODELS_DIR)
    rows = []
    for cls in man["classes"]:
        g = Gallery(len(hub.recs))
        for code, s in cls["enroll"].items():
            for p in s["photos"]:
                im = cv2.imread(p)
                if im is None:
                    print(f"  ! cannot read {p}"); continue
                e, info = enroll_photo(hub, im)
                if e is None:
                    print(f"  ! no face in enrollment photo {p}"); continue
                g.add(code, s.get("name", code), e)
        truth = set(cls["present"]); codes = g.codes
        F_embs = []
        for p in cls["photos"]:
            im = cv2.imread(p)
            if im is None:
                print(f"  ! cannot read {p}"); continue
            _, embs = _embed_all(hub, im, mode)
            F_embs.append(embs)
        def score(name, decide):
            present = set()
            for embs in F_embs:
                if not embs: continue
                Ds = [g.distance_matrix(embs, m) for m in range(len(hub.recs))]
                present |= decide(Ds)
            right = len(present & truth); missed = len(truth - present); fp = len(present - truth)
            rows.append((cls["name"], name, right, len(truth), missed, fp))
        t = config.T_REJECT
        score("Model 1 alone, nearest student", lambda Ds: {codes[int(np.argmin(D[i]))] for D in Ds[:1] for i in range(len(D)) if D[i].min() <= t})
        if len(hub.recs) > 1:
            score("Model 2 alone, nearest student", lambda Ds: {codes[int(np.argmin(D[i]))] for D in Ds[1:2] for i in range(len(D)) if D[i].min() <= t})
            score("Both models fused, nearest student", lambda Ds: {codes[int(np.argmin(np.mean(Ds, 0)[i]))] for i in range(len(Ds[0])) if np.mean(Ds, 0)[i].min() <= t})
        score("Fused + one-face-one-student", lambda Ds: {codes[j] for j in assign(np.mean(Ds, 0), t).values()})
    out = [f"# Upasthiti accuracy benchmark - {man.get('name','')}\n", f"Detection mode: {mode}. Models: {', '.join(hub.model_names)}\n",
           "| Class | Configuration | Present found | Present truth | Missed | False present |", "|---|---|---|---|---|---|"]
    out += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |" for r in rows]
    text = "\n".join(out)
    config.ensure_dirs()
    (config.REPORTS_DIR / f"benchmark_{time.strftime('%Y%m%d_%H%M%S')}.md").write_text(text, encoding="utf-8")
    print(text)
    return rows


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "max")
