import os, threading
import cv2, numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from . import theme as th
from ..i18n import T, lang
from ..engine import quality
from ..services import imread

ZONES = ["Front", "Left", "Centre", "Right", "Back", "Whole class"]


def dhash(img, n=8):
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (n + 1, n), interpolation=cv2.INTER_AREA)
    return (g[:, 1:] > g[:, :-1]).flatten()


class PhotosPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG)
        self.app = app
        top = th.card(self); top.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkButton(top, text="🖼  " + T("browse"), height=40, fg_color=th.BLUE, font=th.font(13, True, lang()), command=self.browse).pack(side="left", padx=12, pady=12)
        ctk.CTkButton(top, text="📱  Upload from Phone", height=40, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                      command=self.upload_from_phone).pack(side="left", padx=4)
        ctk.CTkButton(top, text="📷  " + T("webcam"), height=40, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB", command=self.webcam).pack(side="left", padx=4)
        self.enh = ctk.CTkCheckBox(top, text=T("auto_enhance_checkbox"), fg_color=th.BLUE); self.enh.select(); self.enh.pack(side="left", padx=18)
        ctk.CTkButton(top, text=T("clear_all_btn"), width=80, height=32, fg_color="#FDECEA", text_color=th.RED, hover_color="#F9D0CB", command=self.clear).pack(side="right", padx=12)
        self.body = ctk.CTkScrollableFrame(self, fg_color=th.BG); self.body.pack(fill="both", expand=True, padx=10, pady=2)
        bot = th.card(self); bot.pack(fill="x", padx=16, pady=(6, 12))
        self.count = ctk.CTkLabel(bot, text="", text_color=th.GREY); self.count.pack(side="left", padx=14, pady=10)
        ctk.CTkButton(bot, text=T("continue_attendance_btn"), height=40, fg_color=th.GREEN, hover_color="#1B5E20", font=th.font(13, True, lang()),
                      command=lambda: self.app.show("attendance")).pack(side="right", padx=12, pady=10)
        self.render()

    def refresh(self): self.render()

    def upload_from_phone(self):
        if not self.app.class_id:
            messagebox.showinfo("Smart Capture", "Select a class before starting a phone capture session.", parent=self)
            return
        if not self.app.db.students(self.app.class_id):
            messagebox.showinfo("Smart Capture", "Enroll students in the selected class before using live capture guidance.", parent=self)
            return
        from .phone_upload import PhoneUploadDialog
        from .page_attendance import MODES
        attendance = self.app.pages.get("attendance")
        mode = MODES.get(attendance.mode.get(), "balanced")
        try:
            cfg, _ = self.app.svc.matching_config(self.app.class_id, bool(attendance.auto.get()), float(attendance.slider.get()))
        except Exception as exc:
            messagebox.showerror("Smart Capture", str(exc), parent=self)
            return
        existing = [{"image": item["image"], "label": item["zone"].get() or item["label"]}
                    for item in self.app.staged]
        context = {"service": self.app.svc, "class_id": self.app.class_id,
                   "mode": mode, "config": cfg, "initial_photos": existing}
        self._pending_smart_result = None
        PhoneUploadDialog(self, self._phone_upload_received, capture_context=context,
                          on_analysis=self._phone_analysis_complete)

    def _phone_analysis_complete(self, result):
        self._pending_smart_result = result

    def _phone_upload_received(self, paths, cleanup):
        try:
            result = getattr(self, "_pending_smart_result", None)
            cached = {str(item["path"]): item for item in (result or {}).get("items", []) if item.get("path")}
            for path in paths:
                item = cached.get(str(path))
                if item:
                    self.add_image(item["image"], os.path.basename(str(path)), str(path),
                                   checks=item["checks"], image_hash=item["hash"])
                else:
                    self.add_path(path)
            if result and result.get("complete") and len(result.get("items", [])) == len(self.app.staged):
                for i, staged in enumerate(self.app.staged):
                    label = staged["zone"].get() or staged["label"]
                    result["result"]["photos"][i]["label"] = label
                signature = tuple((s["zone"].get() or s["label"], id(s["image"])) for s in self.app.staged)
                result["signature"] = signature
                result["mode_config_key"] = (result["mode"], tuple(sorted(result["config"].items())))
                self.app.smart_capture_result = result
            else:
                self.app.smart_capture_result = None
            self.render()
        finally:
            cleanup()
            self._pending_smart_result = None

    # ---- adding ----
    def browse(self):
        paths = filedialog.askopenfilenames(title="Select group photos", filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp"), ("All", "*.*")])
        for p in paths: self.add_path(p)
        self.render()

    def add_path(self, path):
        img = imread(path)
        if img is None:
            messagebox.showwarning("Upasthiti", f"Could not read {os.path.basename(str(path))}"); return
        self.add_image(img, os.path.basename(str(path)), str(path))

    def add_image(self, img, label, path="", checks=None, image_hash=None):
        checks = list(quality.photo_checks(img)) if checks is None else list(checks)
        h = dhash(img) if image_hash is None else image_hash
        if image_hash is None:
            for s in self.app.staged:
                if int((s["hash"] != h).sum()) <= 5:
                    checks.append(("warn", f"Looks the same as “{s['label']}” (duplicate?)."))
        n = len(self.app.staged) + 1
        self.app.staged.append({"label": label, "path": path, "image": img, "checks": checks, "hash": h,
                                "zone": tk.StringVar(value=ZONES[(n - 1) % len(ZONES)] if n <= len(ZONES) else f"Zone {n}")})

    def clear(self):
        if self.app.staged and messagebox.askyesno("Upasthiti", "Remove all group photos from this session?"):
            self.app.staged.clear(); self.render()

    def webcam(self):
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened(): raise RuntimeError("Could not open the camera.")
        except Exception as e:
            messagebox.showerror("Upasthiti", str(e)); return
        win = ctk.CTkToplevel(self); win.title("Webcam"); win.geometry("820x640"); win.attributes("-topmost", True)
        lbl = ctk.CTkLabel(win, text=""); lbl.pack(padx=10, pady=10)
        last = {"f": None, "run": True}
        def loop():
            if not last["run"]: return
            ok, f = cap.read()
            if ok:
                last["f"] = f; im = th.to_ctk(f, 780, 520); lbl.configure(image=im); lbl._img = im
            win.after(40, loop)
        def snap():
            if last["f"] is not None:
                self.add_image(last["f"].copy(), f"webcam_{len(self.app.staged)+1}.jpg"); self.render()
        def close():
            last["run"] = False; cap.release(); win.destroy()
        row = ctk.CTkFrame(win, fg_color="transparent"); row.pack()
        ctk.CTkButton(row, text=T("capture_btn"), height=40, fg_color=th.BLUE, command=snap).pack(side="left", padx=8)
        ctk.CTkButton(row, text=T("done_btn"), height=40, fg_color=th.GREY, command=close).pack(side="left", padx=8)
        win.protocol("WM_DELETE_WINDOW", close); loop()

    # ---- list ----
    def render(self):
        for w in self.body.winfo_children(): w.destroy()
        st = self.app.staged
        if not st:
            ctk.CTkLabel(self.body, text=T("no_group_photos_yet"),
                         text_color=th.GREY, font=th.font(14, False, lang())).pack(pady=60)
        for i, s in enumerate(list(st)):
            c = th.card(self.body); c.pack(fill="x", padx=6, pady=6)
            s.setdefault("_thumb", th.to_ctk(s["image"], 260, 170))
            ctk.CTkLabel(c, image=s["_thumb"], text="").pack(side="left", padx=12, pady=12)
            mid = ctk.CTkFrame(c, fg_color="transparent"); mid.pack(side="left", fill="both", expand=True, padx=8, pady=10)
            h, w = s["image"].shape[:2]
            ctk.CTkLabel(mid, text=f"{s['label']}    {w}x{h}", font=th.font(13, True), text_color=th.TEXT).pack(anchor="w")
            zr = ctk.CTkFrame(mid, fg_color="transparent"); zr.pack(anchor="w", pady=6)
            ctk.CTkLabel(zr, text=T("zone"), text_color=th.GREY).pack(side="left", padx=(0, 6))
            ctk.CTkComboBox(zr, values=ZONES, variable=s["zone"], width=170).pack(side="left")
            if not s["checks"]:
                ctk.CTkLabel(mid, text=T("quality_good"), text_color=th.GREEN).pack(anchor="w")
            for lvl, msg in s["checks"]:
                ctk.CTkLabel(mid, text="⚠ " + msg, text_color=th.AMBER, wraplength=560, justify="left").pack(anchor="w")
            ctk.CTkButton(c, text="✕", width=34, height=34, fg_color="#FDECEA", text_color=th.RED, hover_color="#F9D0CB",
                          command=lambda i=i: (self.app.staged.pop(i), self.render())).pack(side="right", padx=12)
        self.count.configure(text=f"{len(st)} photo(s) ready" if st else "")
