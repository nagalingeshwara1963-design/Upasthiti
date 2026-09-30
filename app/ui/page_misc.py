import customtkinter as ctk
from tkinter import filedialog, messagebox
import tkinter as tk
import time
from . import theme as th
from .. import auth, config
from ..i18n import T, lang
from ..services import models_status

LICENCE_NOTE = ("The two face-model packs below are published by the InsightFace project for non-commercial research use. "
                "The Python code libraries are open source, but the trained model files carry their own terms. "
                "Before selling Upasthiti, confirm the licence terms with the model authors or replace these packs with commercially licensed ones.")


# ─────────────────────────────────────────────────────────────────────────────
class HomePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG); self.app = app
        self.wrap = ctk.CTkScrollableFrame(self, fg_color=th.BG); self.wrap.pack(fill="both", expand=True, padx=12, pady=8)
        self.refresh()

    def refresh(self):
        from datetime import date
        from .. import stats
        for w in self.wrap.winfo_children(): w.destroy()
        db = self.app.db; cid = self.app.class_id; today = date.today().isoformat()
        warn, lim = stats.limits(db)
        n_students = len(db.students(cid)) if cid else 0
        sess = db.sessions_on(cid, today) if cid else []
        day = stats.day_summary(db, cid, today) if cid else None
        rows, nsess = stats.month_students(db, cid, date.today().year, date.today().month) if cid else ([], 0)
        low = sorted([r for r in rows if r["level"] in ("warn", "critical")], key=lambda r: r["pct"])

        if not db.get("onboarding_dismissed", False):
            n_classes = len(db.classes())
            n_sessions_total = db.q("SELECT COUNT(*) c FROM sessions")[0]["c"]
            steps = [
                (T("step_admin_pw"), True),
                (T("step_first_class"), n_classes > 0),
                (T("step_enroll"), n_students > 0),
                (T("step_first_attendance"), n_sessions_total > 0),
            ]
            if not all(done for _, done in steps):
                oc = th.card(self.wrap); oc.pack(fill="x", padx=6, pady=(0, 12))
                head = ctk.CTkFrame(oc, fg_color="transparent"); head.pack(fill="x", padx=14, pady=(12, 4))
                ctk.CTkLabel(head, text=T("getting_started"), font=th.font(15, True), text_color=th.TEXT).pack(side="left")
                ctk.CTkButton(head, text=T("hide_btn"), width=50, height=24, fg_color="transparent", text_color=th.GREY,
                              hover_color=th.BLUE_LT, command=self._dismiss_onboarding).pack(side="right")
                for label, done in steps:
                    r = ctk.CTkFrame(oc, fg_color="transparent"); r.pack(fill="x", padx=14, pady=2)
                    ctk.CTkLabel(r, text=("✔" if done else "☐"), text_color=th.GREEN if done else th.GREY, font=th.font(14, True), width=24).pack(side="left")
                    ctk.CTkLabel(r, text=label, text_color=th.TEXT if not done else th.GREY, font=th.font(13, False, lang())).pack(side="left")
                ctk.CTkFrame(oc, height=6, fg_color="transparent").pack()
            else:
                self._dismiss_onboarding(refresh=False)

        cards = ctk.CTkFrame(self.wrap, fg_color="transparent"); cards.pack(fill="x", padx=6, pady=(6, 0))
        cards.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="stat_card")
        pct_txt = "-" if not day or day["pct"] is None else f"{day['pct']:.0f}%"
        lv = stats.level(day["pct"], warn, lim) if day else None
        col = {"ok": th.GREEN, "warn": th.AMBER, "critical": th.RED, None: th.GREY}[lv]
        stat_items = [
            ("Students in class", n_students, th.BLUE),
            ("Sessions today", len(sess), th.BLUE),
            ("Today's attendance", pct_txt, col),
            ("Below " + str(lim) + "% this month",
             sum(1 for r in low if r["level"] == "critical"),
             th.RED if any(r["level"] == "critical" for r in low) else th.GREEN)
        ]
        for i, (label, val, c) in enumerate(stat_items):
            k = th.card(cards)
            k.grid(row=0, column=i, sticky="ew", padx=6, pady=4)
            ctk.CTkLabel(k, text=str(val), font=th.font(30, True), text_color=c).pack(padx=14, pady=(12, 0))
            ctk.CTkLabel(k, text=label, text_color=th.GREY, font=th.font(12, False, lang())).pack(padx=14, pady=(0, 12))

        q = ctk.CTkFrame(self.wrap, fg_color="transparent"); q.pack(fill="x", padx=6, pady=14)
        q.grid_columnconfigure((0, 1, 2), weight=1, uniform="quick_btn")
        actions = [("attendance", "\u2705", lambda: self.app.show("attendance")),
                   ("photos", "\U0001f4f7", lambda: self.app.show("photos")),
                   ("Capture from Phone", "\U0001f4f1", self._capture_from_phone),
                   ("enroll", "\U0001f9d1\u200d\U0001f393", lambda: self.app.show("enroll")),
                   ("Manage Students", "\U0001f465", self._manage_students),
                   ("reports", "\U0001f4ca", lambda: self.app.show("reports"))]
        for i, (label, icon, command) in enumerate(actions):
            text = T(label) if label in ("attendance", "photos", "enroll", "reports") else label
            ctk.CTkButton(q, text=icon + "  " + text, height=48, corner_radius=12, fg_color=th.WHITE, text_color=th.BLUE, border_width=1,
                          border_color=th.BORDER, hover_color=th.BLUE_LT, font=th.font(13, True, lang()),
                          command=command).grid(row=i // 3, column=i % 3, sticky="ew", padx=6, pady=4)
        cols = ctk.CTkFrame(self.wrap, fg_color="transparent"); cols.pack(fill="both", expand=True, padx=6)
        cols.grid_columnconfigure((0, 1), weight=1, uniform="c")
        a = th.card(cols); a.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)
        ctk.CTkLabel(a, text=T("todays_classes"), font=th.font(15, True), text_color=th.TEXT).pack(anchor="w", padx=14, pady=(12, 6))
        if not sess: ctk.CTkLabel(a, text=T("no_attendance_today"), text_color=th.GREY).pack(anchor="w", padx=14, pady=(0, 14))
        for s in sess:
            k = stats.session_summary(db, s["id"]); l2 = stats.level(k["pct"], warn, lim)
            r = ctk.CTkFrame(a, fg_color="transparent"); r.pack(fill="x", padx=12, pady=3)
            ctk.CTkLabel(r, text=s["time"] + "  " + (s["subject"] or "-") + "  " + (s["period"] or ""), text_color=th.TEXT, font=th.font(13, True)).pack(side="left")
            ctk.CTkButton(r, text=T("open_btn"), width=60, height=26, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB", command=lambda s=s: self.open(s)).pack(side="right", padx=(6, 0))
            pct_s = "-" if k["pct"] is None else f"{k['pct']:.0f}%"
            ctk.CTkLabel(r, text=pct_s, fg_color={"ok": "#E8F5E9", "warn": "#FFF3E0", "critical": "#FDECEA", None: "#EEE"}[l2],
                         text_color={"ok": th.GREEN, "warn": th.AMBER, "critical": th.RED, None: th.GREY}[l2], corner_radius=6, width=54, font=th.font(12, True)).pack(side="right")
        ctk.CTkLabel(a, text="", height=4).pack()
        b = th.card(cols); b.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)
        ctk.CTkLabel(b, text=T("low_attendance_month_label") + str(lim) + T("warning_suffix2") + str(warn) + "%)",
                     font=th.font(15, True), text_color=th.TEXT, wraplength=420, justify="left").pack(anchor="w", padx=14, pady=(12, 6))
        if not nsess: ctk.CTkLabel(b, text=T("no_sessions_month"), text_color=th.GREY).pack(anchor="w", padx=14, pady=(0, 14))
        elif not low: ctk.CTkLabel(b, text=T("everyone_above_warning"), text_color=th.GREEN).pack(anchor="w", padx=14, pady=(0, 14))
        for r in low[:8]:
            line = ctk.CTkFrame(b, fg_color="transparent"); line.pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(line, text=(r["name"] or r["code"]) + "  (" + r["code"][-6:] + ")", text_color=th.TEXT).pack(side="left")
            pct_r = f"{r['pct']:.1f}%"
            ctk.CTkLabel(line, text=pct_r, fg_color="#FDECEA" if r["level"] == "critical" else "#FFF3E0",
                         text_color=th.RED if r["level"] == "critical" else th.AMBER,
                         corner_radius=6, width=60, font=th.font(12, True)).pack(side="right")
        ctk.CTkLabel(b, text="", height=4).pack()
        rc = th.card(self.wrap); rc.pack(fill="x", padx=6, pady=(12, 6))
        ctk.CTkLabel(rc, text=T("recent_reports"), font=th.font(15, True), text_color=th.TEXT).pack(anchor="w", padx=14, pady=(12, 6))
        rec = db.recent_sessions(None, 6)
        if not rec: ctk.CTkLabel(rc, text=T("saved_reports_here"), text_color=th.GREY).pack(anchor="w", padx=14, pady=(0, 14))
        for s in rec:
            k = stats.session_summary(db, s["id"])
            r = ctk.CTkFrame(rc, fg_color="transparent"); r.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(r, text=s["date"] + " " + s["time"] + "   " + s["class_name"] + "   " + (s["subject"] or "-") + "   " + (s["period"] or ""), text_color=th.TEXT).pack(side="left")
            ctk.CTkButton(r, text=T("open_btn"), width=60, height=26, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB", command=lambda s=s: self.open(s)).pack(side="right")
            pct_r2 = "-" if k["pct"] is None else f"{k['pct']:.0f}%"
            ctk.CTkLabel(r, text=pct_r2, text_color=th.GREY, width=50).pack(side="right")
        ctk.CTkLabel(rc, text="", height=4).pack()
        st = models_status()
        if not all(st.values()):
            ctk.CTkLabel(self.wrap, text=T("models_not_installed2"), text_color=th.RED, font=th.font(13, True)).pack(anchor="w", pady=10, padx=8)

    def _dismiss_onboarding(self, refresh=True):
        self.app.db.put("onboarding_dismissed", True)
        if refresh: self.refresh()

    def _capture_from_phone(self):
        self.app.show("photos")
        self.app.pages["photos"].upload_from_phone()

    def _manage_students(self):
        self.app.show("enroll")
        self.app.pages["enroll"].switch_tab("Manage Enrolled")

    def open(self, s):
        cur = self.app.db.q("SELECT name FROM classes WHERE id=?", (s["class_id"],))
        if cur and self.app.class_var.get() != cur[0]["name"]: self.app.class_var.set(cur[0]["name"])
        self.app.show("reports"); self.app.pages["reports"].open_date(s["date"], s["id"])


# ─────────────────────────────────────────────────────────────────────────────
class ModelsPage(ctk.CTkFrame):
    """Pick which recognition model(s) run. Detection (finding faces in the photo) always
    uses InsightFace SCRFD - that part is not swappable. What is swappable is which
    recogniser(s) turn a detected face into something comparable; running more than one
    and voting between them gives extra protection against false matches."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG); self.app = app
        self.wrap = ctk.CTkScrollableFrame(self, fg_color=th.BG); self.wrap.pack(fill="both", expand=True, padx=20, pady=16)
        self._vars = {}
        self.refresh()

    def refresh(self):
        for w in self.wrap.winfo_children(): w.destroy()
        from .. import config
        from ..services import models_status, deepface_available
        from ..engine.models import recogniser_available
        db = self.app.db
        selected = set(self.app.svc.selected_model_ids())

        head = ctk.CTkFrame(self.wrap, fg_color="transparent"); head.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(head, text=T("models_page_title"), font=th.font(20, True, lang()), text_color=th.TEXT).pack(side="left")
        ctk.CTkLabel(head, text=T("insightface_corner_note"), text_color=th.GREY, font=th.font(11)).pack(side="right", anchor="s")
        ctk.CTkLabel(self.wrap, text=T("models_page_desc"),
                    text_color=th.GREY, wraplength=880, justify="left").pack(anchor="w", pady=(0, 14))

        rec_ids = [k for k, v in config.MODEL_REGISTRY.items() if v["kind"] == "recognizer"]
        for mid in rec_ids:
            meta = config.MODEL_REGISTRY[mid]
            available = recogniser_available(mid, config.MODELS_DIR)
            c = th.card(self.wrap); c.pack(fill="x", pady=6)
            row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=16, pady=(12, 4))
            var = tk.BooleanVar(value=mid in selected); self._vars[mid] = var
            cb = ctk.CTkCheckBox(row, text="", variable=var, width=24, state="normal" if available else "disabled")
            cb.pack(side="left")
            title = meta["label"]
            if mid in config.RECOMMENDED_MODEL_IDS: title += "   ⭐ Recommended (best accuracy)"
            elif mid in config.RECOMMENDED_COMMERCIAL_IDS: title += "   ✓ Recommended (commercial-safe)"
            ctk.CTkLabel(row, text=title, font=th.font(14, True), text_color=th.TEXT if available else th.GREY).pack(side="left", padx=(6, 0))
            badge = "✔ Installed" if available else ("Not installed" if meta["family"] == "insightface" else "pip install deepface tf-keras")
            ctk.CTkLabel(row, text=badge, text_color=th.GREEN if available else th.AMBER, font=th.font(11, True)).pack(side="right")
            body = ctk.CTkFrame(c, fg_color="transparent"); body.pack(fill="x", padx=16, pady=(0, 12))
            ctk.CTkLabel(body, text=f"Source: {meta['source']}     Speed: {meta['speed']}     Accuracy: {meta['accuracy']}",
                        text_color=th.GREY, font=th.font(11)).pack(anchor="w")
            lic_color = th.AMBER if "non-commercial" in meta["license"] else th.GREEN
            ctk.CTkLabel(body, text=T("licence_label") + " " + meta["license"], text_color=lic_color, font=th.font(11, True)).pack(anchor="w", pady=(2, 4))
            ctk.CTkLabel(body, text=meta["note"], text_color=th.GREY, font=th.font(11), wraplength=820, justify="left").pack(anchor="w")

        btn_row = ctk.CTkFrame(self.wrap, fg_color="transparent"); btn_row.pack(fill="x", pady=(6, 4))
        ctk.CTkButton(btn_row, text=T("use_recommended_btn"), height=36, fg_color=th.BLUE, hover_color=th.BLUE_DK,
                      command=lambda: self._apply(config.RECOMMENDED_MODEL_IDS)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text=T("use_commercial_btn"), height=36, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                      command=lambda: self._apply(config.RECOMMENDED_COMMERCIAL_IDS)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text=T("save_selection_btn"), height=36, fg_color=th.GREEN, hover_color="#1B5E20",
                      command=self._save).pack(side="left")
        self._status = ctk.CTkLabel(self.wrap, text="", text_color=th.GREEN, font=th.font(12, True)); self._status.pack(anchor="w", pady=(6, 0))

        srow = th.card(self.wrap); srow.pack(fill="x", pady=(16, 16))
        ctk.CTkLabel(srow, text=T("installed_files"), font=th.font(13, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(10, 4))
        for pack, ok in models_status().items():
            r = ctk.CTkFrame(srow, fg_color="transparent"); r.pack(fill="x", padx=16, pady=2)
            ctk.CTkLabel(r, text=("✔ " if ok else "✖ ") + pack, text_color=th.GREEN if ok else th.RED, font=th.font(12, True), width=160, anchor="w").pack(side="left")
        ctk.CTkLabel(srow, text=T("deepface_package") + " " + (T("deepface_pkg_installed") if deepface_available() else T("deepface_pkg_not_installed")),
                    text_color=th.GREEN if deepface_available() else th.RED, font=th.font(12, True)).pack(anchor="w", padx=16, pady=(2, 12))

    def _apply(self, ids):
        for mid, var in self._vars.items(): var.set(mid in ids)
        self._save()

    def _save(self):
        chosen = [mid for mid, var in self._vars.items() if var.get()]
        if not chosen:
            messagebox.showwarning("Upasthiti", "Pick at least one recogniser."); return
        self.app.svc.set_model_ids(chosen)
        self._status.configure(text=T("saved_takes_effect"))
        self.after(3000, lambda: self._status.configure(text=""))


def _int_entry(parent, label_text, default, lo, hi, width=90):
    """Return (frame, tk.StringVar) for a labelled integer entry."""
    f = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(f, text=label_text, text_color=th.GREY, font=th.font(12, False, lang()), anchor="w").pack(anchor="w")
    var = tk.StringVar(value=str(default))

    def _clamp(*_):
        try:
            v = int(var.get())
            clamped = max(lo, min(hi, v))
            if clamped != v:
                var.set(str(clamped))
        except ValueError:
            pass

    e = ctk.CTkEntry(f, textvariable=var, width=width)
    e.pack(anchor="w")
    e.bind("<FocusOut>", _clamp)
    return f, var


class SettingsPage(ctk.CTkFrame):
    """Settings: college info, attendance thresholds, photo retention, account management."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG)
        self.app = app
        self._scroll = ctk.CTkScrollableFrame(self, fg_color=th.BG)
        self._scroll.pack(fill="both", expand=True, padx=16, pady=12)
        self._build()

    def refresh(self):
        for w in self._scroll.winfo_children():
            w.destroy()
        self._build()

    def _build(self):
        db = self.app.db
        from .. import auth

        ctk.CTkLabel(self._scroll, text=T("settings_title"), font=th.font(20, True, lang()),
                     text_color=th.TEXT).pack(anchor="w", pady=(4, 12))

        # ── college info ─────────────────────────────────────────────────────
        cc = th.card(self._scroll); cc.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(cc, text=T("college_section"), font=th.font(14, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(cc, text=T("college_name"), text_color=th.GREY, font=th.font(12, False, lang())).pack(anchor="w", padx=16)
        self._name_var = tk.StringVar(value=db.get("college_name", ""))
        ctk.CTkEntry(cc, textvariable=self._name_var, width=420).pack(anchor="w", padx=16, pady=(0, 8))
        ctk.CTkLabel(cc, text=T("college_logo"), text_color=th.GREY, font=th.font(12, False, lang())).pack(anchor="w", padx=16)
        logo_row = ctk.CTkFrame(cc, fg_color="transparent"); logo_row.pack(anchor="w", padx=16, pady=(0, 14))
        self._logo_var = tk.StringVar(value=db.get("college_logo", ""))
        ctk.CTkEntry(logo_row, textvariable=self._logo_var, width=360).pack(side="left")
        ctk.CTkButton(logo_row, text=T("browse"), width=80, height=30, fg_color=th.BLUE_LT,
                      text_color=th.BLUE, hover_color="#BBDEFB", command=self._browse_logo).pack(side="left", padx=(8, 0))

        # ── attendance thresholds ────────────────────────────────────────────
        ac = th.card(self._scroll); ac.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(ac, text=T("attendance_thresholds_section"), font=th.font(14, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 4))
        thr_row = ctk.CTkFrame(ac, fg_color="transparent"); thr_row.pack(anchor="w", padx=16, pady=(0, 0))
        fw, self._warn_var = _int_entry(thr_row, T("limit_warn_lbl"), db.get("limit_warn", config.LOW_ATTENDANCE_WARN), 0, 100)
        fw.pack(side="left", padx=(0, 24))
        fc, self._crit_var = _int_entry(thr_row, T("limit_crit_lbl"), db.get("limit_critical", config.LOW_ATTENDANCE_LIMIT), 0, 100)
        fc.pack(side="left")
        ctk.CTkLabel(ac, text=T("warning_limit_note"),
                     text_color=th.GREY, font=th.font(11), justify="left").pack(anchor="w", padx=16, pady=(4, 12))

        # ── photo retention ──────────────────────────────────────────────────
        pc = th.card(self._scroll); pc.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(pc, text=T("group_photo_retention_section"), font=th.font(14, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 4))
        pr_row = ctk.CTkFrame(pc, fg_color="transparent"); pr_row.pack(anchor="w", padx=16, pady=(0, 0))
        fp, self._ret_var = _int_entry(pr_row, T("photo_retention"), db.get("photo_retention_days", 30), 1, 365)
        fp.pack(side="left")
        ctk.CTkLabel(pc, text=T("retention_note"),
                     text_color=th.GREY, font=th.font(11), justify="left").pack(anchor="w", padx=16, pady=(4, 12))
        ctk.CTkButton(pc, text="Purge expired group-photo evidence now", fg_color=th.BLUE_LT,
                      text_color=th.BLUE, hover_color="#BBDEFB", command=self._purge_expired_evidence).pack(anchor="w", padx=16, pady=(0, 12))

        # ── save ─────────────────────────────────────────────────────────────
        self._status_lbl = ctk.CTkLabel(self._scroll, text="", text_color=th.GREEN, font=th.font(13, True))
        self._status_lbl.pack(anchor="w", pady=(0, 2))
        ctk.CTkButton(self._scroll, text=T("save_settings"), height=40, fg_color=th.BLUE,
                      hover_color=th.BLUE_DK, font=th.font(14, True, lang()), command=self._save).pack(anchor="w", pady=(0, 16))

        if auth.current_role() == "admin":
            bc = th.card(self._scroll); bc.pack(fill="x", pady=(0, 12))
            ctk.CTkLabel(bc, text="Backup and restore", font=th.font(14, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 4))
            ctk.CTkLabel(bc, text="Backups include the database, enrollment photos, galleries, and saved group-photo evidence. They contain sensitive student data.",
                         text_color=th.GREY, wraplength=760, justify="left").pack(anchor="w", padx=16, pady=4)
            last_at, last_path = db.get("backup_last_at"), db.get("backup_last_path", "")
            last_text = f"Last verified backup: {time.strftime('%Y-%m-%d %H:%M', time.localtime(last_at))} · {last_path}" if last_at and last_path else "Last verified backup: none recorded on this installation."
            ctk.CTkLabel(bc, text=last_text, text_color=th.GREY, wraplength=760, justify="left").pack(anchor="w", padx=16, pady=4)
            actions = ctk.CTkFrame(bc, fg_color="transparent"); actions.pack(anchor="w", padx=16, pady=(4, 12))
            ctk.CTkButton(actions, text="Create verified backup", command=self.app.create_backup).pack(side="left", padx=(0, 8))
            ctk.CTkButton(actions, text="Validate and restore backup", fg_color=th.RED, hover_color="#C62828",
                          command=self.app.restore_backup).pack(side="left")

        # ── accounts (admin only) ────────────────────────────────────────────
        if auth.current_role() == "admin":
            self._build_accounts()
            self._build_repair_tool()
            self._build_audit_export()
            self._build_email()

    def _build_email(self):
        from .email_settings import EmailSettingsSection
        EmailSettingsSection(self._scroll, self.app).pack(fill="x")

    # ── helpers ──────────────────────────────────────────────────────────────
    def _browse_logo(self):
        path = filedialog.askopenfilename(
            title="Select college logo", parent=self,
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")])
        if path:
            self._logo_var.set(path)

    def _save(self):
        db = self.app.db
        try:
            warn = int(self._warn_var.get())
            crit = int(self._crit_var.get())
            ret  = int(self._ret_var.get())
        except ValueError:
            messagebox.showwarning("Upasthiti", "Thresholds and retention days must be whole numbers.", parent=self); return
        if warn < crit:
            messagebox.showwarning("Upasthiti", "Warning threshold must be \u2265 limit threshold.", parent=self); return
        db.put("college_name",         self._name_var.get().strip())
        db.put("college_logo",         self._logo_var.get().strip())
        db.put("limit_warn",           warn)
        db.put("limit_critical",       crit)
        db.put("photo_retention_days", ret)
        self._status_lbl.configure(text=T("saved_ok"))
        self.after(2500, lambda: self._status_lbl.configure(text=""))
        self.app.notify_changed()

    def _purge_expired_evidence(self):
        if not messagebox.askyesno("Upasthiti", "This permanently removes only boxed group-photo evidence older than the configured retention period. Attendance history remains; sessions with active review requests are kept. Continue?", parent=self):
            return
        from .. import reportstore
        try:
            count = reportstore.purge_expired_session_artifacts(self.app.db)
            messagebox.showinfo("Upasthiti", f"Removed {count} expired evidence file(s). Attendance records were not changed.", parent=self)
        except Exception as exc:
            messagebox.showerror("Upasthiti", f"Evidence cleanup failed: {exc}", parent=self)

    # ── manage accounts ───────────────────────────────────────────────────────
    def _build_accounts(self):
        from .. import auth
        mc = th.card(self._scroll); mc.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(mc, text=T("accounts_title"), font=th.font(14, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 6))
        self._acc_frame = ctk.CTkFrame(mc, fg_color="transparent"); self._acc_frame.pack(fill="x", padx=16)
        self._draw_accounts()
        # add faculty
        ctk.CTkFrame(mc, height=1, fg_color=th.BORDER).pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(mc, text=T("add_faculty"), text_color=th.GREY, font=th.font(12, False, lang())).pack(anchor="w", padx=16)
        add_row = ctk.CTkFrame(mc, fg_color="transparent"); add_row.pack(anchor="w", padx=16, pady=(4, 14))
        self._new_user = tk.StringVar(); self._new_pw1 = tk.StringVar(); self._new_pw2 = tk.StringVar()
        ctk.CTkEntry(add_row, textvariable=self._new_user, placeholder_text=T("username"), width=150).pack(side="left", padx=(0, 6))
        ctk.CTkEntry(add_row, textvariable=self._new_pw1,  placeholder_text=T("password"), show="*", width=130).pack(side="left", padx=(0, 6))
        ctk.CTkEntry(add_row, textvariable=self._new_pw2,  placeholder_text=T("confirm_pw"), show="*", width=130).pack(side="left", padx=(0, 6))
        ctk.CTkButton(add_row, text="Add", width=70, height=30, fg_color=th.BLUE, command=self._add_faculty).pack(side="left")
        # change admin password
        ctk.CTkFrame(mc, height=1, fg_color=th.BORDER).pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(mc, text=T("admin_password_label"), text_color=th.GREY, font=th.font(12, False, lang())).pack(anchor="w", padx=16)
        pw_row = ctk.CTkFrame(mc, fg_color="transparent"); pw_row.pack(anchor="w", padx=16, pady=(4, 14))
        self._adm_pw1 = tk.StringVar(); self._adm_pw2 = tk.StringVar()
        ctk.CTkEntry(pw_row, textvariable=self._adm_pw1, placeholder_text=T("new_pw"),     show="*", width=150).pack(side="left", padx=(0, 6))
        ctk.CTkEntry(pw_row, textvariable=self._adm_pw2, placeholder_text=T("confirm_pw"), show="*", width=150).pack(side="left", padx=(0, 6))
        ctk.CTkButton(pw_row, text=T("change_pw"), width=120, height=30, fg_color=th.BLUE, command=self._change_admin_pw).pack(side="left")
        self._build_faculty_assignments(mc)

    def _build_faculty_assignments(self, parent):
        from .. import auth
        users = [u["username"] for u in auth.list_users(self.app.db) if u["role"] == "faculty"]
        ctk.CTkFrame(parent, height=1, fg_color=th.BORDER).pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(parent, text="Faculty class access", font=th.font(13, True), text_color=th.TEXT).pack(anchor="w", padx=16)
        if not users:
            ctk.CTkLabel(parent, text="Create a faculty account before assigning classes.", text_color=th.GREY).pack(anchor="w", padx=16, pady=6)
            return
        self._access_user = tk.StringVar(value=users[0])
        ctk.CTkOptionMenu(parent, values=users, variable=self._access_user,
                          command=lambda _v: self._draw_faculty_assignments()).pack(anchor="w", padx=16, pady=6)
        self._faculty_access_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._faculty_access_frame.pack(fill="x", padx=16)
        self._draw_faculty_assignments()

    def _draw_faculty_assignments(self):
        for child in self._faculty_access_frame.winfo_children(): child.destroy()
        current = set(self.app.db.faculty_class_ids(self._access_user.get()))
        self._faculty_class_vars = {}
        for cls in self.app.db.classes():
            var = tk.BooleanVar(value=cls["id"] in current)
            self._faculty_class_vars[cls["id"]] = var
            ctk.CTkCheckBox(self._faculty_access_frame, text=cls["name"], variable=var).pack(anchor="w", pady=2)
        ctk.CTkButton(self._faculty_access_frame, text="Save class access", command=self._save_faculty_assignments).pack(anchor="w", pady=8)

    def _save_faculty_assignments(self):
        from .. import auth
        if auth.current_role() != "admin": return
        selected = [cid for cid, var in self._faculty_class_vars.items() if var.get()]
        self.app.db.set_faculty_classes(self._access_user.get(), selected)
        messagebox.showinfo("Upasthiti", "Faculty class access saved.", parent=self)
        if auth.current_role() == "faculty": self.app.build("home")

    def _build_repair_tool(self):
        c = th.card(self._scroll); c.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(c, text=T("db_maintenance_title"), font=th.font(14, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(c, text=T("db_maintenance_desc"),
                    text_color=th.GREY, wraplength=760, justify="left").pack(anchor="w", padx=16, pady=(0, 8))
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(anchor="w", padx=16, pady=(0, 4))
        ctk.CTkButton(row, text=T("scan_issues_btn"), width=150, height=32, fg_color=th.BLUE, hover_color=th.BLUE_DK,
                      command=self._scan_repair).pack(side="left", padx=(0, 8))
        self._fix_btn = ctk.CTkButton(row, text=T("fix_issues_btn"), width=150, height=32, fg_color=th.RED, hover_color="#C62828",
                                      state="disabled", command=self._fix_repair)
        self._fix_btn.pack(side="left")
        self._repair_result = ctk.CTkLabel(c, text="", text_color=th.GREY, wraplength=760, justify="left", font=th.font(12))
        self._repair_result.pack(anchor="w", padx=16, pady=(6, 14))
        self._last_issues = None

    def _scan_repair(self):
        from .. import repair
        issues = repair.scan(self.app.db)
        self._last_issues = issues
        if repair.is_clean(issues):
            self._repair_result.configure(text=T("no_issues_found"), text_color=th.GREEN)
            self._fix_btn.configure(state="disabled")
            return
        lines = []
        if issues["orphan_attendance"]:
            lines.append(f"• {len(issues['orphan_attendance'])} attendance record(s) belong to a student that was deleted.")
        if issues["orphan_edits"]:
            lines.append(f"• {len(issues['orphan_edits'])} edit-log entr(y/ies) belong to a deleted student.")
        if issues["missing_photo_files"]:
            lines.append(f"• {len(issues['missing_photo_files'])} enrollment photo(s) are recorded but the file is missing on disk.")
        for m in issues["gallery_mismatch"]:
            if m["stale_in_gallery"]:
                lines.append(f"• {m['class']}: {len(m['stale_in_gallery'])} face-data entr(y/ies) for student(s) no longer in this class.")
            if m["missing_in_gallery"]:
                lines.append(f"• {m['class']}: {len(m['missing_in_gallery'])} enrolled student(s) have no face data "
                             f"({', '.join(m['missing_in_gallery'][:6])}) - add photos for them in Manage Enrolled (not auto-fixable).")
        self._repair_result.configure(text="\n".join(lines), text_color=th.AMBER)
        can_autofix = bool(issues["orphan_attendance"] or issues["orphan_edits"] or issues["missing_photo_files"]
                          or any(m["stale_in_gallery"] for m in issues["gallery_mismatch"]))
        self._fix_btn.configure(state="normal" if can_autofix else "disabled")

    def _fix_repair(self):
        if not self._last_issues: return
        if not messagebox.askyesno("Upasthiti",
                "This permanently removes the leftover records listed above (for example, attendance history "
                "for a student that no longer exists). This cannot be undone. Continue?"):
            return
        from .. import repair
        counts = repair.fix(self.app.db, self._last_issues)
        self._repair_result.configure(
            text=f"Fixed: {counts['orphan_attendance_removed']} attendance record(s), {counts['orphan_edits_removed']} edit "
                 f"log entr(y/ies), {counts['missing_photo_rows_removed']} missing-photo record(s), "
                 f"{counts['stale_gallery_entries_removed']} stale face-data entr(y/ies) removed.",
            text_color=th.GREEN)
        self._fix_btn.configure(state="disabled")
        self.app.notify_changed()

    def _build_audit_export(self):
        c = th.card(self._scroll); c.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(c, text=T("audit_log_title"), font=th.font(14, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(c, text=T("audit_log_desc"),
                    text_color=th.GREY, wraplength=760, justify="left").pack(anchor="w", padx=16, pady=(0, 8))
        row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(anchor="w", padx=16, pady=(0, 14))
        ctk.CTkButton(row, text=T("export_excel_btn"), width=150, height=32, fg_color=th.GREEN, hover_color="#1B5E20",
                      command=lambda: self._export_audit("xlsx")).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text=T("export_csv_btn"), width=150, height=32, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                      command=lambda: self._export_audit("csv")).pack(side="left")

    def _export_audit(self, fmt):
        from .. import exports
        default = "upasthiti_audit_log." + fmt
        dst = filedialog.asksaveasfilename(title="Save audit log", parent=self, initialfile=default,
                                           defaultextension="." + fmt,
                                           filetypes=[("Excel workbook", "*.xlsx")] if fmt == "xlsx" else [("CSV file", "*.csv")])
        if not dst: return
        try:
            (exports.audit_to_xlsx if fmt == "xlsx" else exports.audit_to_csv)(self.app.db, dst)
            messagebox.showinfo("Upasthiti", "Audit log saved.")
        except Exception as e:
            messagebox.showerror("Upasthiti", f"Could not save audit log:\n{e}")

    def _draw_accounts(self):
        from .. import auth
        for w in self._acc_frame.winfo_children(): w.destroy()
        for u in auth.list_users(self.app.db):
            row = ctk.CTkFrame(self._acc_frame, fg_color="transparent"); row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=u["username"] + ("  [admin]" if u["role"] == "admin" else "  [faculty]"),
                         text_color=th.TEXT, width=220, anchor="w").pack(side="left")
            if u["role"] == "faculty":
                ctk.CTkButton(row, text=T("del_account"), width=100, height=26,
                              fg_color="#FDECEA", text_color=th.RED, hover_color="#EF9A9A",
                              command=lambda n=u["username"]: self._del_faculty(n)).pack(side="left", padx=4)

    def _add_faculty(self):
        from .. import auth
        uname = self._new_user.get().strip()
        pw1 = self._new_pw1.get(); pw2 = self._new_pw2.get()
        if not uname: messagebox.showwarning("Upasthiti", "Enter a username.", parent=self); return
        if not pw1:   messagebox.showwarning("Upasthiti", "Enter a password.", parent=self); return
        if pw1 != pw2: messagebox.showwarning("Upasthiti", T("pw_mismatch"), parent=self); return
        auth.set_password(self.app.db, "faculty", uname, pw1)
        self._new_user.set(""); self._new_pw1.set(""); self._new_pw2.set("")
        self._draw_accounts()

    def _del_faculty(self, username):
        from .. import auth
        if not messagebox.askyesno("Upasthiti", "Delete account '" + username + "'?", parent=self): return
        auth.delete_user(self.app.db, username)
        self._draw_accounts()

    def _change_admin_pw(self):
        from .. import auth
        pw1 = self._adm_pw1.get(); pw2 = self._adm_pw2.get()
        if not pw1:    messagebox.showwarning("Upasthiti", "Enter a new password.", parent=self); return
        if pw1 != pw2: messagebox.showwarning("Upasthiti", T("pw_mismatch"), parent=self); return
        auth.set_password(self.app.db, "admin", "admin", pw1)
        self._adm_pw1.set(""); self._adm_pw2.set("")
        messagebox.showinfo("Upasthiti", "Admin password updated.", parent=self)


# ─────────────────────────────────────────────────────────────────────────────


class HelpPage(ctk.CTkFrame):
    """Quick-start steps + FAQ. Static content - update as features change."""

    FAQ = [
        ("How do I add a new class?", "Click '+ New class' at the top right, type a name (e.g. '3106_2023_ME_A' or "
         "just 'ME 3rd Sem A'), and it appears in the Class dropdown."),
        ("How many photos per student should I enroll?", "About 4, ideally with some variation (glasses on/off, "
         "slight angle). More photos let the system learn a better threshold automatically in 3 Attendance."),
        ("The system marked someone absent who was actually present. What do I do?", "Open Reports, find that "
         "session, click View, and change their status there - every change is logged. Or during the review step "
         "right after running attendance, use 'Point in Photo' to click their face directly."),
        ("What does 'Point in Photo' do?", "It lets you click a missed student's face in the photo. That both marks "
         "them present for this session and saves the face so the system recognises them better next time."),
        ("Why does attendance take longer sometimes?", "The 'Maximum accuracy' mode scans the photo at several zoom "
         "levels to catch small or back-row faces. 'Fast' mode is quicker but may miss more."),
        ("Can a faculty member edit attendance after saving?", "Yes, within 30 calendar days from the original session date, and only for an assigned class. After that only the "
         "admin can. Every edit is logged with who made it and when."),
        ("Where are my students' photos and data stored?", "Everything is in the 'data' folder inside the install "
         "folder - never uploaded anywhere. Back it up regularly from Settings."),
        ("Which face-recognition model should I use?", "Go to Models & Licences. 'Use recommended' gives the best "
         "accuracy we have measured. If you plan to sell or commercially deploy the app, use the commercial-safe "
         "combo instead - see the licensing note on that page."),
        ("A student's face isn't being recognised well. What can I do?", "Open Enroll > Manage Enrolled, click "
         "'+ Add Photos' for that student, and add 1-2 more recent photos. This directly improves their match."),
        ("What do the box colours mean on a report photo?", "Green = matched confidently, amber/blue = matched but "
         "uncertain, grey = a face the system could not match to anyone enrolled."),
    ]

    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG); self.app = app
        self.wrap = ctk.CTkScrollableFrame(self, fg_color=th.BG); self.wrap.pack(fill="both", expand=True, padx=20, pady=16)
        self._open = set()
        self.refresh()

    def refresh(self):
        for w in self.wrap.winfo_children(): w.destroy()
        ctk.CTkLabel(self.wrap, text=T("help_page_title"), font=th.font(20, True, lang()), text_color=th.TEXT).pack(anchor="w", pady=(4, 10))
        if auth.current_role() in ("admin", "faculty"):
            ctk.CTkButton(self.wrap, text="Open Chat with Upasthiti", width=220,
                          command=self._open_chat).pack(anchor="w", pady=(0, 12))

        steps = th.card(self.wrap); steps.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(steps, text=T("quick_start_title"), font=th.font(15, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 6))
        for i, (title, desc) in enumerate([
            (T("qs1_title"), T("qs1_desc")),
            (T("qs2_title"), T("qs2_desc")),
            (T("qs3_title"), T("qs3_desc")),
            (T("qs4_title"), T("qs4_desc")),
        ], 1):
            r = ctk.CTkFrame(steps, fg_color="transparent"); r.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(r, text=title, font=th.font(13, True), text_color=th.BLUE, width=140, anchor="w").pack(side="left")
            ctk.CTkLabel(r, text=desc, text_color=th.GREY, wraplength=680, justify="left", anchor="w").pack(side="left", fill="x", expand=True)
        ctk.CTkFrame(steps, height=6, fg_color="transparent").pack()

        faq_card = th.card(self.wrap); faq_card.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(faq_card, text=T("faq_title"), font=th.font(15, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(12, 6))
        for i, (q, a) in enumerate(self.FAQ):
            row = ctk.CTkFrame(faq_card, fg_color="transparent"); row.pack(fill="x", padx=16, pady=2)
            btn = ctk.CTkButton(row, text=("▾ " if i in self._open else "▸ ") + q, anchor="w", fg_color="transparent",
                                text_color=th.TEXT, hover_color=th.BLUE_LT, font=th.font(13, True),
                                command=lambda i=i: self._toggle(i))
            btn.pack(fill="x")
            if i in self._open:
                ctk.CTkLabel(row, text=a, text_color=th.GREY, wraplength=800, justify="left").pack(anchor="w", padx=24, pady=(2, 8))
        ctk.CTkFrame(faq_card, height=6, fg_color="transparent").pack()

    def _toggle(self, i):
        if i in self._open: self._open.discard(i)
        else: self._open.add(i)
        self.refresh()

    def _open_chat(self):
        window = ctk.CTkToplevel(self)
        window.title("Chat with Upasthiti")
        window.geometry("880x620")
        from .staff_tools import StaffToolsPage
        StaffToolsPage(window, self.app, "chat").pack(fill="both", expand=True)


class PlaceholderPage(ctk.CTkFrame):
    def __init__(self, parent, app, key):
        super().__init__(parent, fg_color=th.BG)
        ctk.CTkLabel(self, text=T(key) + "\n\nComing in the next build stage.", font=th.font(16), text_color=th.GREY).pack(expand=True)
