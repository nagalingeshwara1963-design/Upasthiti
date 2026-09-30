import os, time, threading
from datetime import datetime
import cv2, numpy as np
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from . import theme as th
from .. import config
from ..i18n import T, lang
from ..services import imread

MODES = {"Maximum accuracy": "max", "Balanced": "balanced", "Fast": "fast"}
FLAG_TXT = {"weak_match": "match is weak", "close_call": "looks similar to another student", "models_disagree": "the two face models disagree",
            "resolved_by_assignment": "conflict with another face resolved", "unknown_face": "no student matched"}
STATUSES = ["Present", "Absent", "Late", "Excused", "Leave / OD"]
CODE = {"Present": "P", "Absent": "A", "Late": "L", "Excused": "E", "Leave / OD": "OD"}
from PIL import Image, ImageTk


def finish_alert(text):
    try:
        import winsound; winsound.MessageBeep()
    except Exception:
        pass
    try:
        from winotify import Notification
        Notification(app_id="Upasthiti", title="Upasthiti", msg=text).show()
    except Exception:
        pass


class AttendancePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG)
        self.app = app; self.result = None; self.running = False
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
        left = th.card(self, width=380); left.grid(row=0, column=0, sticky="ns", padx=(16, 8), pady=12); left.grid_propagate(False)
        ctk.CTkLabel(left, text=T("session_details"), font=th.font(15, True, lang()), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(14, 6))
        now = datetime.now()
        self.date = tk.StringVar(value=now.strftime("%Y-%m-%d")); self.tm = tk.StringVar(value=now.strftime("%H:%M"))
        r = ctk.CTkFrame(left, fg_color="transparent"); r.pack(fill="x", padx=16)
        for lab, var, w in ((T("date"), self.date, 150), (T("time"), self.tm, 90)):
            f = ctk.CTkFrame(r, fg_color="transparent"); f.pack(side="left", padx=(0, 10))
            ctk.CTkLabel(f, text=lab, text_color=th.GREY, font=th.font(11, False, lang())).pack(anchor="w")
            ctk.CTkEntry(f, textvariable=var, width=w).pack()
        self.combos = {}
        for key, kind in (("faculty", "faculty"), ("subject", "subject"), ("period", "period")):
            ctk.CTkLabel(left, text=T(key) + "   (type once, pick later)", text_color=th.GREY, font=th.font(11, False, lang())).pack(anchor="w", padx=16, pady=(8, 0))
            cb = ctk.CTkComboBox(left, values=[""], width=340); cb.set(""); cb.pack(padx=16); self.combos[kind] = cb
        ctk.CTkLabel(left, text=T("accuracy"), text_color=th.GREY, font=th.font(11, False, lang())).pack(anchor="w", padx=16, pady=(12, 0))
        self.mode = ctk.CTkOptionMenu(left, values=list(MODES), width=340, fg_color=th.BLUE, button_color=th.BLUE_DK); self.mode.pack(padx=16)
        self.auto = ctk.CTkCheckBox(left, text=T("automatic_threshold"), fg_color=th.BLUE, command=self.upd_thr); self.auto.select(); self.auto.pack(anchor="w", padx=16, pady=(12, 2))
        self.slider = ctk.CTkSlider(left, from_=0.40, to=0.80, number_of_steps=40, width=340, command=lambda v: self.upd_thr()); self.slider.set(0.60); self.slider.pack(padx=16)
        self.thr_lbl = ctk.CTkLabel(left, text="", text_color=th.GREY, wraplength=340, justify="left", font=th.font(11)); self.thr_lbl.pack(anchor="w", padx=16, pady=(2, 8))
        self.photo_lbl = ctk.CTkLabel(left, text="", text_color=th.GREY); self.photo_lbl.pack(anchor="w", padx=16)
        ctk.CTkButton(left, text="＋ " + T("add_photos"), height=32, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                      command=lambda: app.show("photos")).pack(fill="x", padx=16, pady=6)
        self.run_btn = ctk.CTkButton(left, text="▶  " + T("run"), height=48, fg_color=th.GREEN, hover_color="#1B5E20", font=th.font(15, True, lang()), command=self.start)
        self.run_btn.pack(fill="x", padx=16, pady=(6, 16), side="bottom")
        right = ctk.CTkFrame(self, fg_color="transparent"); right.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=12)
        right.grid_rowconfigure(0, weight=1); right.grid_columnconfigure(0, weight=1)
        pv = th.card(right); pv.grid(row=0, column=0, sticky="nsew"); pv.grid_propagate(False)
        self.preview = ctk.CTkLabel(pv, text=T("live_preview_placeholder"), text_color=th.GREY); self.preview.pack(expand=True, fill="both", padx=6, pady=6)
        pr = th.card(right); pr.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.stage_lbl = ctk.CTkLabel(pr, text=T("ready_status"), text_color=th.BLUE, font=th.font(13, True)); self.stage_lbl.pack(anchor="w", padx=14, pady=(10, 2))
        self.bar = ctk.CTkProgressBar(pr, height=12, progress_color=th.BLUE); self.bar.set(0); self.bar.pack(fill="x", padx=14)
        self.logbox = ctk.CTkTextbox(pr, height=110, fg_color="#F7F9FB", text_color=th.TEXT, font=("Consolas", 11)); self.logbox.pack(fill="x", padx=14, pady=10)
        self.upd_thr()

    # ---- helpers ----
    def refresh(self):
        for kind, cb in self.combos.items():
            cb.configure(values=self.app.db.list_values(kind) or [""])
        n = len(self.app.staged)
        self.photo_lbl.configure(text=f"📷 {n} group photo(s) ready" if n else "⚠ No group photos added yet", text_color=th.GREEN if n else th.AMBER)
        self.upd_thr()

    def upd_thr(self):
        cid = self.app.class_id
        if self.auto.get() and cid:
            try:
                cfg, info = self.app.svc.matching_config(cid, True)
            except Exception as exc:
                self.thr_lbl.configure(text=str(exc))
                self.slider.configure(state="disabled")
                return
            self.thr_lbl.configure(text=f"Suggested threshold {cfg['t_accept']:.2f} - {info['basis']}")
            self.slider.set(cfg["t_accept"]); self.slider.configure(state="disabled")
        else:
            self.slider.configure(state="normal")
            self.thr_lbl.configure(text=f"Manual threshold {self.slider.get():.2f} (lower = stricter)")

    def log(self, s):
        self.logbox.insert("end", s + "\n"); self.logbox.see("end")

    def draw(self, image, rows, matched):
        boxes = []
        for r in rows:
            b = r["bbox"]
            if not matched: col = (230, 150, 30)
            elif r.get("student") is None: col = (140, 140, 140)
            elif set(r.get("flags", [])) & {"weak_match", "close_call", "models_disagree"}: col = (0, 140, 240)
            else: col = (60, 160, 40)
            boxes.append((*b, col))
        im = th.to_ctk(image, self.preview.winfo_width() - 20 or 800, self.preview.winfo_height() - 20 or 480, boxes=boxes)
        self.preview.configure(image=im, text=""); self.preview._img = im

    # ---- run ----
    def start(self):
        cid = self.app.class_id
        if not cid: messagebox.showinfo("Upasthiti", "Select a class first."); return
        if not self.app.staged: messagebox.showinfo("Upasthiti", "Add at least one group photo first."); return
        if self.running: return
        if not self.app.db.students(cid): messagebox.showinfo("Upasthiti", "This class has no enrolled students yet."); return
        self.running = True; self.run_btn.configure(state="disabled", text=T("running_status"))
        self.logbox.delete("1.0", "end"); self.bar.set(0)
        try:
            cfg, info = self.app.svc.matching_config(cid, bool(self.auto.get()), float(self.slider.get()))
        except Exception as exc:
            messagebox.showerror("Upasthiti", str(exc), parent=self)
            return
        mode = MODES[self.mode.get()]
        cached = getattr(self.app, "smart_capture_result", None)
        signature = tuple((s["zone"].get() or s["label"], id(s["image"])) for s in self.app.staged)
        config_key = (mode, tuple(sorted(cfg.items())))
        if (cached and cached.get("complete") and cached.get("class_id") == cid and
                cached.get("signature") == signature and cached.get("mode_config_key") == config_key and
                tuple(cached.get("model_ids", ())) == tuple(self.app.svc.selected_model_ids())):
            self.running = True; self.run_btn.configure(state="disabled", text="Opening review…")
            self.stage_lbl.configure(text="Using the completed laptop Smart Capture analysis…")
            self.app.smart_capture_result = None
            self.done(cached["result"], cfg, mode)
            return
        self.app.smart_capture_result = None
        photos = [{"label": s["zone"].get() or s["label"], "image": s["image"]} for s in self.app.staged]
        post = self.app.post
        def work():
            try:
                res = self.app.svc.run_session(cid, photos, mode, cfg,
                    progress=lambda p, t="": post(lambda: (self.bar.set(min(1, p)), self.stage_lbl.configure(text=f"{t}  {int(p*100)}%"))),
                    log=lambda s: post(lambda: self.log(s)),
                    preview=lambda st, pi, im, rows: post(lambda: self.draw(im, rows, st == "matched")))
                post(lambda: self.done(res, cfg, mode))
            except Exception as e:
                post(lambda: (self.log(f"ERROR: {e}"), messagebox.showerror("Upasthiti", str(e)), self.reset_btn()))
        threading.Thread(target=work, daemon=True).start()

    def reset_btn(self):
        self.running = False; self.run_btn.configure(state="normal", text="▶  " + T("run"))

    def watch_email_deliveries(self, delivery_ids):
        rows = [self.app.db.email_delivery(i) for i in delivery_ids]
        rows = [r for r in rows if r]
        if any(r["status"] in ("pending", "sending") for r in rows):
            self.after(700, lambda: self.watch_email_deliveries(delivery_ids))
            return
        failed = [r for r in rows if r["status"] == "failed"]
        if failed and self.winfo_exists():
            messagebox.showwarning("Attendance saved; email delivery issue",
                f"Attendance is saved. {len(failed)} absence email(s) failed to submit. Review Settings → Email for details and retry.",
                parent=self.winfo_toplevel())

    def done(self, res, cfg, mode):
        self.result = res; self.reset_btn()
        P = sum(1 for s in res["students"].values() if s["status"] == "P")
        self.stage_lbl.configure(text=f"Done in {res['seconds']:.0f}s - {P} present, {len(res['students']) - P} absent, {len(res['uncertain'])} to check")
        finish_alert(f"Attendance ready: {P} present")
        ReviewDialog(self, res, cfg, mode)


class ReviewDialog(ctk.CTkToplevel):
    def __init__(self, page, res, cfg, mode):
        super().__init__(page)
        self.page, self.res, self.cfg, self.mode = page, res, cfg, mode
        self.title("Review and save"); self.geometry("860x650"); self.minsize(640, 480); self.transient(page.winfo_toplevel())
        app = page.app; cid = app.class_id
        self.students = {s["code"]: s for s in app.db.students(cid)}
        self.vars = {}
        self.manual_matches = {} # code -> {"photo_idx", "face_idx"}
        self._order = []        # codes in on-screen order, for keyboard navigation
        self._cards = {}        # code -> card frame (for highlight)
        self._sel = -1
        head = ctk.CTkFrame(self, fg_color=th.WHITE); head.pack(fill="x")
        P = sum(1 for s in res["students"].values() if s["status"] == "P")
        ctk.CTkLabel(head, text=f"{P} present   |   {len(res['students']) - P} absent   |   {len(res['uncertain'])} to check", font=th.font(15, True), text_color=th.TEXT).pack(anchor="w", padx=18, pady=12)
        body = ctk.CTkScrollableFrame(self, fg_color=th.BG); body.pack(fill="both", expand=True, padx=8, pady=6)
        if res["uncertain"]:
            ctk.CTkLabel(body, text="⚠  " + T("review") + " - the system is not fully sure", font=th.font(14, True), text_color=th.AMBER).pack(anchor="w", padx=10, pady=(8, 2))
            for code in res["uncertain"]: self.row(body, code, True)
        absent = [c for c, s in res["students"].items() if s["status"] == "A"]
        ctk.CTkLabel(body, text=f"Absent students ({len(absent)}) - confirm, or change to Late / Excused / Leave", font=th.font(14, True), text_color=th.TEXT).pack(anchor="w", padx=10, pady=(14, 2))
        if not absent: ctk.CTkLabel(body, text=T("everyone_found"), text_color=th.GREEN).pack(anchor="w", padx=14)
        for code in absent: self.row(body, code, False)
        foot = ctk.CTkFrame(self, fg_color=th.WHITE); foot.pack(fill="x")
        ctk.CTkButton(foot, text="💾  " + T("save"), height=42, fg_color=th.GREEN, hover_color="#1B5E20", font=th.font(14, True, lang()), command=self.save).pack(side="right", padx=14, pady=10)
        ctk.CTkButton(foot, text=T("cancel_btn"), height=42, fg_color=th.GREY, command=self.destroy).pack(side="right", padx=4)
        ctk.CTkLabel(foot, text=T("keyboard_hint"),
                    text_color=th.GREY, font=th.font(11)).pack(side="left", padx=14)
        self._bind_keys()
        if self._order: self._select(0)
        self.after(150, self.grab_set)

    def _bind_keys(self):
        for key, fn in (("<Up>", lambda e: self._move(-1)), ("<Down>", lambda e: self._move(1)),
                        ("<Return>", lambda e: self._cycle(1)), ("<KP_Enter>", lambda e: self._cycle(1)),
                        ("<space>", lambda e: self._toggle_pa()), ("<Escape>", lambda e: self.destroy())):
            self.bind_all(key, fn, add="+")
        self.bind("<Destroy>", lambda e: self._unbind_keys() if e.widget is self else None)

    def _unbind_keys(self):
        for key in ("<Up>", "<Down>", "<Return>", "<KP_Enter>", "<space>", "<Escape>"):
            try: self.unbind_all(key)
            except Exception: pass

    def _select(self, idx):
        if not self._order: return
        idx = max(0, min(len(self._order) - 1, idx))
        if 0 <= self._sel < len(self._order):
            prev = self._cards.get(self._order[self._sel])
            if prev: prev.configure(border_color=th.BORDER, border_width=1)
        self._sel = idx
        code = self._order[idx]
        card = self._cards.get(code)
        if card:
            card.configure(border_color=th.BLUE, border_width=2)
            try:
                card._parent_canvas.yview_moveto(max(0, idx - 1) / max(1, len(self._order)))
            except Exception:
                pass  # auto-scroll is a nice-to-have; never let it break navigation

    def _move(self, delta):
        if self._sel < 0: self._select(0)
        else: self._select(self._sel + delta)

    def _cycle(self, delta):
        if not (0 <= self._sel < len(self._order)): return
        code = self._order[self._sel]; v = self.vars[code]
        i = STATUSES.index(v.get()) if v.get() in STATUSES else 0
        v.set(STATUSES[(i + delta) % len(STATUSES)])

    def _toggle_pa(self):
        if not (0 <= self._sel < len(self._order)): return
        code = self._order[self._sel]; v = self.vars[code]
        v.set("Absent" if v.get() == "Present" else "Present")

    def row(self, parent, code, uncertain):
        s = self.res["students"][code]; st = self.students.get(code, {"name": ""})
        c = th.card(parent); c.pack(fill="x", padx=6, pady=4)
        self._order.append(code); self._cards[code] = c
        if uncertain:
            try:
                ph = self.res["photos"][s["photo"]]; x1, y1, x2, y2 = [int(v) for v in ph["faces"][s["face"]]["bbox"]]
                src = self.page.app.staged[s["photo"]]["image"]; m = int((x2 - x1) * 0.3)
                crop = src[max(0, y1 - m):y2 + m, max(0, x1 - m):x2 + m]
                im = th.to_ctk(crop, 90, 90); l = ctk.CTkLabel(c, image=im, text=""); l._img = im; l.pack(side="left", padx=10, pady=8)
            except Exception: pass
        info = ctk.CTkFrame(c, fg_color="transparent"); info.pack(side="left", padx=6, pady=8, fill="x", expand=True)
        ctk.CTkLabel(info, text=f"{st['name'] or code}", font=th.font(13, True), text_color=th.TEXT).pack(anchor="w")
        sub = code if not uncertain else f"{code}   confidence {s['confidence']:.0f}%   ({', '.join(FLAG_TXT.get(f, f) for f in s['flags'] if f != 'resolved_by_assignment') or 'ok'})"
        ctk.CTkLabel(info, text=sub, text_color=th.GREY, font=th.font(11)).pack(anchor="w")
        v = tk.StringVar(value="Present" if uncertain else "Absent"); self.vars[code] = v
        
        right_frame = ctk.CTkFrame(c, fg_color="transparent")
        right_frame.pack(side="right", padx=12)
        
        if not uncertain:
            ctk.CTkButton(right_frame, text=T("point_in_photo"), width=110, height=26, fg_color=th.BLUE,
                          command=lambda c=code: self.point_in_photo(c)).pack(side="left", padx=10)
        
        ctk.CTkOptionMenu(right_frame, values=STATUSES, variable=v, width=130, fg_color=th.BLUE_LT, text_color=th.BLUE, button_color=th.BLUE_LT).pack(side="left")

    def point_in_photo(self, code):
        if not self.res["photos"]: return
        PointDialog(self, code)

    def save(self):
        page = self.page; app = page.app; cid = app.class_id
        chosen = {code: CODE[self.vars[code].get()] for code in self.vars}
        for kind, cb in page.combos.items(): app.db.add_list_value(kind, cb.get())
        meta = {"date": page.date.get(), "time": page.tm.get(), "faculty": page.combos["faculty"].get(), "subject": page.combos["subject"].get(),
                "period": page.combos["period"].get(), "mode": self.mode, "threshold": self.cfg["t_accept"], "photos": [s["zone"].get() for s in app.staged]}
        sid = app.svc.save_session(cid, meta, self.res, app.staged, chosen)
        email_notice = ""
        try:
            delivery = app.email_service.enqueue_absentees(sid)
            if not delivery["disabled"] and delivery["queued"]:
                email_notice = f"\n\nAbsent-student email queued in the background ({delivery['queued']} recipient(s))."
                page.after(900, lambda ids=delivery["delivery_ids"]: page.watch_email_deliveries(ids))
        except Exception as exc:
            email_notice = f"\n\nAttendance was saved, but email queueing failed: {str(exc)[:240]}"
        
        # Save manual matches to continuous learning
        student_names = {s["code"]: s["name"] for s in app.db.students(cid)}
        for mcode, mm in self.manual_matches.items():
            if chosen.get(mcode) == "P":  # only if they kept it present
                try:
                    face = self.res["photos"][mm["photo_idx"]]["faces"][mm["face_idx"]]
                    emb = face["embs"]
                    x1, y1, x2, y2 = [int(v) for v in face["bbox"]]
                    src_img = app.staged[mm["photo_idx"]]["image"]
                    m = int(max(x2 - x1, y2 - y1) * 0.25)
                    crop = src_img[max(0, y1 - m):y2 + m, max(0, x1 - m):x2 + m]
                    app.svc.add_face_to_student(cid, mcode, student_names.get(mcode, mcode), emb, crop)
                except Exception as e:
                    print("could not learn pointed face:", e)

        self.res["session_id"] = sid; app.last_result = self.res
        self.destroy(); messagebox.showinfo("Upasthiti", f"Attendance saved (session {sid}). You can open it from Reports.{email_notice}")
        page.refresh(); app.notify_changed()


class PointDialog(ctk.CTkToplevel):
    def __init__(self, parent, code):
        super().__init__(parent)
        self.parent = parent
        self.code = code
        self.title(f"Point out {code}")
        self.geometry("900x700")
        self.transient(parent)
        
        self.photo_idx = 0
        self.photos = parent.res["photos"]
        
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkButton(top, text=T("prev_btn"), width=60, command=self.prev_photo).pack(side="left", padx=5)
        self.lbl_idx = ctk.CTkLabel(top, text=f"Photo 1 of {len(self.photos)}")
        self.lbl_idx.pack(side="left", padx=10)
        ctk.CTkButton(top, text=T("next_btn"), width=60, command=self.next_photo).pack(side="left", padx=5)
        
        ctk.CTkLabel(top, text=T("click_face_hint"), text_color=th.BLUE).pack(side="left", padx=20)
        
        self.canvas = tk.Canvas(self, bg="#222", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_click)
        
        self.load_photo()
        self.grab_set()

    def prev_photo(self):
        if self.photo_idx > 0:
            self.photo_idx -= 1
            self.load_photo()
            
    def next_photo(self):
        if self.photo_idx < len(self.photos) - 1:
            self.photo_idx += 1
            self.load_photo()

    def load_photo(self):
        self.lbl_idx.configure(text=f"Photo {self.photo_idx + 1} of {len(self.photos)}")
        src = self.parent.page.app.staged[self.photo_idx]["image"]
        self.img_cv = src
        # Resize to fit canvas approx
        cw, ch = self.winfo_width() or 900, self.winfo_height() or 600
        h, w = src.shape[:2]
        self.scale = min(cw/w, ch/h) if w > 0 and h > 0 else 1.0
        nw, nh = int(w * self.scale), int(h * self.scale)
        resized = cv2.resize(src, (nw, nh))
        
        # draw boxes
        for i, f in enumerate(self.photos[self.photo_idx]["faces"]):
            bx = [int(v * self.scale) for v in f["bbox"]]
            col = (0,255,0) if f.get("student") else (0,0,255)
            cv2.rectangle(resized, (bx[0], bx[1]), (bx[2], bx[3]), col, 2)
            
        resized_rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        self.tk_img = ImageTk.PhotoImage(image=Image.fromarray(resized_rgb))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)

    def on_click(self, event):
        x, y = event.x / self.scale, event.y / self.scale
        # Find closest face
        best_i = -1
        best_d = float('inf')
        for i, f in enumerate(self.photos[self.photo_idx]["faces"]):
            bx = f["bbox"]
            cx, cy = (bx[0]+bx[2])/2, (bx[1]+bx[3])/2
            d = (cx - x)**2 + (cy - y)**2
            if d < best_d and bx[0] <= x <= bx[2] and bx[1] <= y <= bx[3]:
                best_d = d
                best_i = i
                
        if best_i >= 0:
            self.parent.manual_matches[self.code] = {"photo_idx": self.photo_idx, "face_idx": best_i}
            self.parent.vars[self.code].set("Present")
            messagebox.showinfo("Face Selected", "Face mapped to student! Will be saved on submit.")
            self.destroy()
