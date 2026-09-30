"""Classroom face detection: SCRFD on the full photo plus overlapping zoomed tiles,
merged with NMS. Finds small / back-row / blurry faces that a single pass misses."""
import cv2
import numpy as np

MODES = {
    # name: (full-image detector sizes, tile_grids, tile_overlap, det_threshold)
    "fast":     ([960],        [],       0.25, 0.50),
    "balanced": ([640, 1280],  [2],      0.25, 0.45),
    "max":      ([640, 1280],  [2, 3],   0.30, 0.40),
}


def _iou_and_contain(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    aa = (a[2] - a[0]) * (a[3] - a[1]); bb = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (aa + bb - inter + 1e-9), inter / (min(aa, bb) + 1e-9)


def _merge(cands, iou_thr=0.4, contain_thr=0.75):
    cands = sorted(cands, key=lambda c: -c[1])
    kept = []
    for bb, sc, kp in cands:
        dup = False
        for kb, _, _ in kept:
            iou, cont = _iou_and_contain(bb, kb)
            if iou >= iou_thr or cont >= contain_thr:
                dup = True; break
        if not dup:
            kept.append((bb, sc, kp))
    return kept


def detect_faces(hub, img, mode="max", min_size=16, progress=None, full_sizes=None):
    """Returns list of dicts: bbox (x1,y1,x2,y2), kps (5,2), score."""
    sizes, grids, ov, thr = MODES[mode]
    if full_sizes: sizes = full_sizes
    H, W = img.shape[:2]
    cands = []

    def run(im, ox, oy, size=960):
        b, k = hub.det.detect(im, input_size=(size, size), det_thresh=thr)
        if b is None or len(b) == 0:
            return
        for i in range(len(b)):
            bb = b[i, :4] + np.array([ox, oy, ox, oy], dtype=np.float32)
            kp = k[i] + np.array([ox, oy], dtype=np.float32)
            cands.append((bb, float(b[i, 4]), kp))

    steps = len(sizes) + sum(g * g for g in grids)
    done = 0
    for sz in sizes:
        run(img, 0, 0, sz); done += 1
        if progress: progress(done / steps)
    for g in grids:
        tw = int(W / (g - (g - 1) * ov)); th = int(H / (g - (g - 1) * ov))
        sx = (W - tw) / max(1, g - 1); sy = (H - th) / max(1, g - 1)
        for r in range(g):
            for c in range(g):
                x0 = int(round(c * sx)); y0 = int(round(r * sy))
                run(img[y0:y0 + th, x0:x0 + tw], x0, y0)
                done += 1
                if progress: progress(done / steps)
    faces = []
    for bb, sc, kp in _merge(cands):
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        if min(w, h) < min_size:
            continue
        faces.append({"bbox": [float(v) for v in bb], "kps": kp, "score": sc})
    faces.sort(key=lambda f: (round(f["bbox"][1] / 80), f["bbox"][0]))   # rows, then left->right
    return faces
