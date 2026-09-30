import cv2
from PIL import Image
import customtkinter as ctk

BLUE = "#1565C0"; BLUE_DK = "#0D47A1"; BLUE_LT = "#E3F2FD"
GREEN = "#2E7D32"; RED = "#C62828"; AMBER = "#EF6C00"; GREY = "#5C6370"
BG = "#F0F4F8"; WHITE = "#FFFFFF"; TEXT = "#1A1A2E"; BORDER = "#DDE3EA"


def font(size=13, bold=False, lang="en"):
    fam = "Nirmala UI" if lang in ("kn", "hi") else "Segoe UI"
    return ctk.CTkFont(family=fam, size=size, weight="bold" if bold else "normal")


def to_ctk(bgr, max_w, max_h, box=None, color=(40, 160, 60), boxes=None):
    """BGR ndarray -> CTkImage scaled to fit; optional face box(es) drawn first."""
    img = bgr.copy()
    for b in ([box] if box is not None else []) + list(boxes or []):
        x1, y1, x2, y2 = [int(v) for v in b[:4]]
        c = b[4] if len(b) > 4 else color
        cv2.rectangle(img, (x1, y1), (x2, y2), c, max(2, img.shape[1] // 220))
    h, w = img.shape[:2]
    s = min(max_w / w, max_h / h)
    img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    return ctk.CTkImage(light_image=pil, size=pil.size)


def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=WHITE, corner_radius=12, border_width=1, border_color=BORDER, **kw)
