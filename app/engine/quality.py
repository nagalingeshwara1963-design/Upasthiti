"""Per-photo and per-face quality checks + enhancement for small/blurry faces."""
import cv2
import numpy as np

BLUR_MIN = 25.0        # variance of Laplacian on a 96x96 face crop (calibrated by benchmark)
SMALL_PX = 40
DARK_MEAN = 55


def photo_checks(img):
    """Checks run when a group photo is added. Returns list of (level, message)."""
    out = []
    h, w = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if min(h, w) < 720:
        out.append(("warn", f"Low resolution ({w}x{h}). Back-row faces may not be readable."))
    if cv2.Laplacian(cv2.resize(g, (960, int(960 * h / w))), cv2.CV_64F).var() < 40:
        out.append(("warn", "Photo looks blurry."))
    m = float(g.mean())
    if m < 70:
        out.append(("warn", f"Photo is dark (brightness {m:.0f}/255). Enhancement can help."))
    elif m > 200:
        out.append(("warn", f"Photo is over-exposed (brightness {m:.0f}/255)."))
    if float(g.std()) < 35:
        out.append(("warn", "Low contrast."))
    return out


def face_quality(img, bbox, score):
    x1, y1, x2, y2 = [int(v) for v in bbox]
    H, W = img.shape[:2]
    crop = img[max(0, y1):min(H, y2), max(0, x1):min(W, x2)]
    size = int(min(x2 - x1, y2 - y1))
    if crop.size == 0:
        return {"size": size, "blur": 0.0, "brightness": 0.0, "flags": ["empty"]}
    g = cv2.cvtColor(cv2.resize(crop, (96, 96), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(g, cv2.CV_64F).var())
    bright = float(g.mean())
    flags = []
    if size < SMALL_PX: flags.append("small")
    if blur < BLUR_MIN: flags.append("blurry")
    if bright < DARK_MEAN: flags.append("dark")
    if score < 0.6: flags.append("low_confidence_detection")
    return {"size": size, "blur": blur, "brightness": bright, "flags": flags}


def enhance_face_region(img, bbox, kps, target=256):
    """Crop around the face, upscale and unsharp-mask. Returns (crop, kps_in_crop)."""
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    m = 0.6
    cx1 = int(max(0, x1 - m * w)); cy1 = int(max(0, y1 - m * h))
    cx2 = int(min(img.shape[1], x2 + m * w)); cy2 = int(min(img.shape[0], y2 + m * h))
    crop = img[cy1:cy2, cx1:cx2]
    s = max(1.0, target / max(1, min(crop.shape[:2])))
    up = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_LANCZOS4)
    blur = cv2.GaussianBlur(up, (0, 0), 2.0)
    sharp = cv2.addWeighted(up, 1.8, blur, -0.8, 0)
    lab = cv2.cvtColor(sharp, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(l)
    out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    k = (np.asarray(kps) - np.array([cx1, cy1])) * s
    return out, k


def enhance_photo(img):
    """Brightness / contrast rescue for dark or flat classroom photos."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
