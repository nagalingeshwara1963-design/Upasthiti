import calendar, os, shutil, subprocess, sys
from datetime import date, datetime
import cv2
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from . import theme as th
from .. import config, reports, reportstore, stats, auth
from ..i18n import T, lang

LVL_BG = {"ok": "#E8F5E9", "warn": "#FFF3E0", "critical": "#FDECEA", None: th.WHITE}
LVL_FG = {"ok": th.GREEN, "warn": th.AMBER, "critical": th.RED, None: th.TEXT}
ST_COL = {"P": th.GREEN, "L": th.AMBER, "A": th.RED, "E": th.GREY, "OD": th.GREY}
ST_OPTS = [("P", "Present"), ("A", "Absent"), ("L", "Late"), ("E", "Excused"), ("OD", "Leave / OD")]


def open_file(path):
    try:
        if sys.platform.startswith("win"): os.startfile(path)
        elif sys.platform == "darwin": subprocess.Popen(["open", path])
        else: subprocess.Popen(["xdg-open", path])
    except Exception: pass


def export(db, builder, args, default_name, ext):
    """Build the file, then let the user choose where to save it."""
    out = config.REPORTS_DIR / "exports"; out.mkdir(parents=True, exist_ok=True)
    tmp = out / default_name
    try:
        builder(db, *args, tmp, lang())
    except Exception as e:
        messagebox.showerror("Upasthiti", f"Could not create the report:\n{e}"); return
    kind = "Word document" if ext == ".docx" else "Excel workbook"
    dst = filedialog.asksaveasfilename(title="Save report", initialfile=default_name, defaultextension=ext, filetypes=[(kind, f"*{ext}")])
    if dst:
        shutil.copy(str(tmp), dst)
        if messagebox.askyesno("Upasthiti", "Report saved. Open it now?"): open_file(dst)


class ReportsPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG)
        self.app = app
        t = date.today(); self.year, self.month = t.year, t.month; self.sel = t.isoformat()
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
        self.left = th.card(self, width=540); self.left.grid(row=0, column=0, sticky="ns", padx=(16, 8), pady=12); self.left.grid_propagate(False)
        self.right = ctk.CTkScrollableFrame(self, fg_color=th.BG); self.right.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=12)
        self.refresh()

    # ---------------- public ----------------
    def refresh(self):
        self.draw_left(); self.draw_right()

    def open_date(self, iso, session_id=None):
        y, m, _ = [int(x) for x in iso.split("-")]
        self.year, self.month, self.sel = y, m, iso; self.refresh()
        if session_id: SessionView(self, session_id)

    # ---------------- calendar ----------------
    def shift(self, delta):
        m = self.month + delta; y = self.year
        if m < 1: m, y = 12, y - 1
        if m > 12: m, y = 1, y + 1
        self.month, self.year = m, y; self.refresh()

    def draw_left(self):
        for w in self.left.winfo_children(): w.destroy()
        cid = self.app.class_id; db = self.app.db
        head = ctk.CTkFrame(self.left, fg_color="transparent"); head.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkButton(head, text="◀", width=36, height=34, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB", command=lambda: self.shift(-1)).pack(side="left")
        ctk.CTkLabel(head, text=f"{calendar.month_name[self.month]} {self.year}", font=th.font(18, True), text_color=th.TEXT).pack(side="left", expand=True)
        ctk.CTkButton(head, text="▶", width=36, height=34, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB", command=lambda: self.shift(1)).pack(side="right")
        grid = ctk.CTkFrame(self.left, fg_color="transparent"); grid.pack(padx=12, pady=4)
        for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
            ctk.CTkLabel(grid, text=d, text_color=th.GREY, font=th.font(11, True), width=70).grid(row=0, column=i, pady=(0, 4))
        warn, lim = stats.limits(db) if cid else (80, 75)
        today = date.today().isoformat()
        for r, week in enumerate(calendar.Calendar(0).monthdayscalendar(self.year, self.month), 1):
            for c, d in enumerate(week):
                if d == 0: continue
                iso = f"{self.year:04d}-{self.month:02d}-{d:02d}"
                summ = stats.day_summary(db, cid, iso) if cid else None
                n = len(db.sessions_on(cid, iso)) if cid else 0
                lv = stats.level(summ["pct"], warn, lim) if summ else None
                selected = iso == self.sel
                txt = f"{d}\n" + (f"● {n}" if n else " ")
                b = ctk.CTkButton(grid, text=txt, width=70, height=56, corner_radius=8, font=th.font(13, True),
                                  fg_color=th.BLUE if selected else LVL_BG[lv], text_color="white" if selected else LVL_FG[lv],
                                  hover_color="#BBDEFB", border_width=2 if iso == today else 1, border_color=th.BLUE if iso == today else th.BORDER,
                                  command=lambda iso=iso: self.pick(iso))
                b.grid(row=r, column=c, padx=2, pady=2)
        leg = ctk.CTkFrame(self.left, fg_color="transparent"); leg.pack(pady=(8, 0))
        for lv, txt in (("ok", f"≥ {warn}%"), ("warn", f"{lim}–{warn}%"), ("critical", f"< {lim}%")):
            ctk.CTkLabel(leg, text="  " + txt + "  ", fg_color=LVL_BG[lv], text_color=LVL_FG[lv], corner_radius=6, font=th.font(11, True)).pack(side="left", padx=4)
        m = th.card(self.left); m.pack(fill="x", padx=14, pady=14)
        ctk.CTkLabel(m, text=f"Monthly summary - {calendar.month_name[self.month]}", font=th.font(13, True), text_color=th.TEXT).pack(anchor="w", padx=12, pady=(10, 4))
        row = ctk.CTkFrame(m, fg_color="transparent"); row.pack(anchor="w", padx=10, pady=(0, 10))
        nm = f"monthly_{self.year}-{self.month:02d}"
        ctk.CTkButton(row, text=T("word_btn"), width=100, height=32, fg_color=th.BLUE, command=lambda: self.need_class() and export(db, reports.month_docx, (cid, self.year, self.month), nm + ".docx", ".docx")).pack(side="left", padx=3)
        ctk.CTkButton(row, text=T("excel_btn"), width=100, height=32, fg_color=th.GREEN, command=lambda: self.need_class() and export(db, reports.month_xlsx, (cid, self.year, self.month), nm + ".xlsx", ".xlsx")).pack(side="left", padx=3)
        if auth.current_role() != "student":
            ctk.CTkButton(row, text="Email Attendance Report", width=190, height=32,
                          fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB",
                          command=self.email_report).pack(side="left", padx=6)

    def email_report(self):
        if not self.need_class(): return
        from .email_reports import EmailReportDialog
        EmailReportDialog(self)

    def need_class(self):
        if not self.app.class_id: messagebox.showinfo("Upasthiti", "Select a class first."); return False
        return True

    def pick(self, iso):
        self.sel = iso; self.refresh()

    # ---------------- right side ----------------
    def draw_right(self):
        for w in self.right.winfo_children(): w.destroy()
        cid = self.app.class_id; db = self.app.db
        if not cid:
            ctk.CTkLabel(self.right, text=T("select_class_first"), text_color=th.GREY, font=th.font(14)).pack(pady=60); return
        sess = db.sessions_on(cid, self.sel)
        pretty = datetime.strptime(self.sel, "%Y-%m-%d").strftime("%A, %d %B %Y")
        ctk.CTkLabel(self.right, text=pretty, font=th.font(18, True), text_color=th.TEXT).pack(anchor="w")
        if sess:
            nm = f"daily_{self.sel}"
            top = ctk.CTkFrame(self.right, fg_color="transparent"); top.pack(fill="x", pady=(4, 6))
            ctk.CTkLabel(top, text=T("whole_day_label"), text_color=th.GREY).pack(side="left", padx=(0, 6))
            ctk.CTkButton(top, text=T("day_word_btn"), width=110, height=30, fg_color=th.BLUE, command=lambda: export(db, reports.day_docx, (cid, self.sel), nm + ".docx", ".docx")).pack(side="left", padx=3)
            ctk.CTkButton(top, text=T("day_excel_btn"), width=110, height=30, fg_color=th.GREEN, command=lambda: export(db, reports.day_xlsx, (cid, self.sel), nm + ".xlsx", ".xlsx")).pack(side="left", padx=3)
        if not sess:
            ctk.CTkLabel(self.right, text=T("no_attendance_this_date"), text_color=th.GREY).pack(anchor="w", pady=10)
        warn, lim = stats.limits(db)
        for s in sess:
            k = stats.session_summary(db, s["id"]); lv = stats.level(k["pct"], warn, lim)
            c = th.card(self.right); c.pack(fill="x", pady=5)
            row = ctk.CTkFrame(c, fg_color="transparent"); row.pack(fill="x", padx=14, pady=12)
            info = ctk.CTkFrame(row, fg_color="transparent"); info.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(info, text=f"{s['time']}   {s['subject'] or '-'}   {s['period'] or ''}", font=th.font(14, True), text_color=th.TEXT).pack(anchor="w")
            ctk.CTkLabel(info, text=f"{s['faculty'] or '-'}   |   {k['attended']} attended, {k['absent']} absent" + (f", {k['excused']} excused/OD" if k["excused"] else ""), text_color=th.GREY, font=th.font(12)).pack(anchor="w")
            ctk.CTkLabel(row, text="-" if k["pct"] is None else f"{k['pct']:.0f}%", fg_color=LVL_BG[lv], text_color=LVL_FG[lv], corner_radius=8, width=64, height=34, font=th.font(15, True)).pack(side="right", padx=(8, 0))
            b = ctk.CTkFrame(c, fg_color="transparent"); b.pack(anchor="w", padx=12, pady=(0, 12))
            ctk.CTkButton(b, text=T("view_btn"), width=90, height=30, fg_color=th.BLUE, command=lambda sid=s["id"]: SessionView(self, sid)).pack(side="left", padx=3)
            nm = f"attendance_{self.sel}_{(s['subject'] or 'session')}_{s['id']}".replace(" ", "_")
            ctk.CTkButton(b, text=T("word_btn"), width=90, height=30, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB", command=lambda sid=s["id"], nm=nm: export(db, reports.session_docx, (sid,), nm + ".docx", ".docx")).pack(side="left", padx=3)
            ctk.CTkButton(b, text=T("excel_btn"), width=90, height=30, fg_color=th.BLUE_LT, text_color=th.BLUE, hover_color="#BBDEFB", command=lambda sid=s["id"], nm=nm: export(db, reports.session_xlsx, (sid,), nm + ".xlsx", ".xlsx")).pack(side="left", padx=3)
        # low attendance this month
        rows, n = stats.month_students(db, cid, self.year, self.month)
        low = [r for r in rows if r["level"] in ("warn", "critical")]
        c = th.card(self.right); c.pack(fill="x", pady=(14, 5))
        ctk.CTkLabel(c, text=f"Low attendance in {calendar.month_name[self.month]}\n(limit {lim}%, warning {warn}%)", font=th.font(14, True), text_color=th.TEXT, justify="left").pack(anchor="w", padx=14, pady=(12, 4))
        if not n: ctk.CTkLabel(c, text=T("no_sessions_this_month"), text_color=th.GREY).pack(anchor="w", padx=14, pady=(0, 12))
        elif not low: ctk.CTkLabel(c, text=T("everyone_above_warning"), text_color=th.GREEN).pack(anchor="w", padx=14, pady=(0, 12))
        for r in sorted(low, key=lambda r: r["pct"]):
            line = ctk.CTkFrame(c, fg_color="transparent"); line.pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(line, text=f"{r['name'] or r['code']}   ({r['code']})", text_color=th.TEXT).pack(side="left")
            ctk.CTkLabel(line, text=f"{r['pct']:.1f}%", fg_color=LVL_BG[r["level"]], text_color=LVL_FG[r["level"]], corner_radius=6, width=64, font=th.font(12, True)).pack(side="right")
        ctk.CTkLabel(c, text="", height=4).pack()


class SessionView(ctk.CTkToplevel):
    """In-app view of one saved session: boxed photos, attendance list, edits, downloads."""
    def __init__(self, page, sid):
        super().__init__(page)
        self.page, self.sid = page, sid; self.db = page.app.db
        self.title(f"Session {sid}"); self.geometry("980x680"); self.minsize(760, 520); self.configure(fg_color=th.BG)
        self.transient(page.winfo_toplevel())
        self.build()
        self.after(150, self.focus_force)

    def build(self):
        for w in self.winfo_children(): w.destroy()
        s = self.db.session(self.sid); rows = self.db.session_rows(self.sid); k = stats.counts([r["status"] for r in rows])
        if not s or auth.current_role() not in ("admin", "faculty") or not auth.can_access_class(self.db, s["class_id"]):
            messagebox.showwarning("Upasthiti", "Your account is not authorized for this session.", parent=self)
            self.destroy(); return
        head = ctk.CTkFrame(self, fg_color=th.WHITE, corner_radius=0); head.pack(fill="x")
        ctk.CTkLabel(head, text=f"{s['class_name']}   |   {s['date']} {s['time']}   |   {s['subject'] or '-'}  {s['period'] or ''}   |   {s['faculty'] or '-'}", font=th.font(14, True), text_color=th.TEXT, wraplength=440, justify="left").pack(side="left", fill="x", expand=True, padx=16, pady=12)
        ctk.CTkLabel(head, text="-" if k["pct"] is None else f"{k['pct']:.0f}%", fg_color=LVL_BG[stats.level(k["pct"], *stats.limits(self.db))], text_color=th.TEXT, corner_radius=8, width=64, font=th.font(15, True)).pack(side="right", padx=16)
        ctk.CTkButton(head, text=T("excel_btn"), width=90, height=32, fg_color=th.GREEN, command=lambda: export(self.db, reports.session_xlsx, (self.sid,), f"attendance_{s['date']}_{self.sid}.xlsx", ".xlsx")).pack(side="right", padx=4)
        ctk.CTkButton(head, text=T("word_btn"), width=90, height=32, fg_color=th.BLUE, command=lambda: export(self.db, reports.session_docx, (self.sid,), f"attendance_{s['date']}_{self.sid}.docx", ".docx")).pack(side="right", padx=4)
        body = ctk.CTkFrame(self, fg_color="transparent"); body.pack(fill="both", expand=True, padx=12, pady=10)
        body.grid_columnconfigure(0, weight=3); body.grid_columnconfigure(1, weight=2); body.grid_rowconfigure(0, weight=1)
        left = ctk.CTkScrollableFrame(body, fg_color=th.BG); left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        bundle = reportstore.load(self.sid)
        if not bundle["images"]:
            ctk.CTkLabel(left, text=T("no_photos_stored"), text_color=th.GREY).pack(pady=30)
        for ip in bundle["images"]:
            im = cv2.imread(ip)
            if im is None: continue
            ci = th.to_ctk(im, 640, 460); l = ctk.CTkLabel(left, image=ci, text=""); l._img = ci; l.pack(pady=6)
        ctk.CTkLabel(left, text=T("box_colour_legend"), text_color=th.GREY, font=th.font(11), wraplength=620).pack(pady=(0, 8))
        right = ctk.CTkScrollableFrame(body, fg_color=th.WHITE, corner_radius=12); right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        editable = auth.can_edit_session(s["created_at"], s["date"], self.db, s["class_id"])
        subtitle = T("attendance_list_edit_hint") if editable else T("attendance_list_readonly")
        ctk.CTkLabel(right, text=subtitle, font=th.font(13, True), text_color=th.TEXT if editable else th.GREY).pack(anchor="w", padx=10, pady=(10, 4))
        names = [n for _, n in ST_OPTS]; code_of = {n: c for c, n in ST_OPTS}
        for r in rows:
            line = ctk.CTkFrame(right, fg_color="transparent"); line.pack(fill="x", padx=8, pady=2)
            ctk.CTkLabel(line, text=(r["name"] or r["code"]), width=110, anchor="w", font=th.font(12, True), text_color=th.TEXT).pack(side="left")
            ctk.CTkLabel(line, text=r["code"][-6:], width=60, anchor="w", text_color=th.GREY, font=th.font(11)).pack(side="left")
            if r["status"] == "P" and r["confidence"]:
                ctk.CTkLabel(line, text=f"{r['confidence']:.0f}%", width=40, text_color=th.GREY, font=th.font(11)).pack(side="left")
            cur = dict(ST_OPTS)[r["status"]]
            if editable:
                om = ctk.CTkOptionMenu(line, values=names, width=112, height=26, fg_color=th.BLUE_LT, text_color=ST_COL.get(r["status"], th.TEXT), button_color=th.BLUE_LT,
                                       command=lambda v, r=r: self.change(r, code_of[v]))
                om.set(cur); om.pack(side="right", padx=2)
            else:
                ctk.CTkLabel(line, text=cur, width=100, height=26, text_color=ST_COL.get(r["status"], th.TEXT), font=th.font(12, True)).pack(side="right", padx=2)
            if r["edited"]: ctk.CTkLabel(line, text="✎", text_color=th.AMBER).pack(side="right")
        ed = self.db.edits_for(self.sid)
        if ed:
            ctk.CTkLabel(right, text=T("edit_log_title"), font=th.font(13, True), text_color=th.TEXT).pack(anchor="w", padx=10, pady=(14, 2))
            for e in ed:
                when = datetime.fromtimestamp(e["at"]).strftime("%d %b %H:%M")
                ctk.CTkLabel(right, text=f"{when}  {e['name'] or e['code']}: {stats.LABEL.get(e['old'], e['old'])} → {stats.LABEL.get(e['new'], e['new'])}  ({e['by_user']})", text_color=th.GREY, font=th.font(11), wraplength=380, justify="left").pack(anchor="w", padx=10)

    def change(self, r, new):
        s = self.db.session(self.sid)
        if not auth.can_edit_session(s["created_at"], s["date"], self.db, s["class_id"]):
            messagebox.showwarning("Upasthiti", T("edit_locked"), parent=self)
            self.build(); return
        if new == r["status"]: return
        if not messagebox.askyesno("Upasthiti", f"Change {r['name'] or r['code']} from {stats.LABEL[r['status']]} to {stats.LABEL[new]}?\nThis change will be logged.", parent=self):
            self.build(); return
        operator = auth.current_user() or getattr(self.page.app, "user_name", "admin")
        self.db.change_status(self.sid, r["student_id"], new, by_user=operator)
        self.build(); self.page.refresh(); self.page.app.notify_changed()
