"""Class-scoped email workspace for private student reports and explicit schedules."""
import calendar
from datetime import date, datetime
import threading
import uuid
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from .. import auth
from ..email_service import get_email_settings, student_report_template
from .. import stats
from ..i18n import T, lang
from .email_reports import parse_report_range
from . import theme as th


def _iso_text(value):
    return datetime.strptime(value, "%d-%m-%Y").date().isoformat()


def _display_date(value):
    return datetime.strptime(value, "%Y-%m-%d").strftime("%d-%m-%Y")


class EmailCenterPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG)
        self.app = app
        today = date.today()
        first = date(today.year, today.month, 1)
        last = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        self.period = tk.StringVar(value="Monthly")
        self.month = tk.StringVar(value=today.strftime("%B %Y"))
        self.from_var = tk.StringVar(value=first.strftime("%d-%m-%Y"))
        self.to_var = tk.StringVar(value=last.strftime("%d-%m-%Y"))
        self.send_on = tk.StringVar(value=today.strftime("%d-%m-%Y"))
        self.search = tk.StringVar()
        self._selected_students = set()
        self._busy = False
        self._delivery_ids = []
        self._make_layout()

    def _make_layout(self):
        head = th.card(self); head.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(head, text="Email Center", font=th.font(19, True), text_color=th.TEXT).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(head, text="Choose the class in the application header. Each student report is generated and sent separately to that student's enabled recipients.",
                     wraplength=950, justify="left", text_color=th.GREY).pack(anchor="w", padx=14, pady=(0, 8))
        row = ctk.CTkFrame(head, fg_color="transparent"); row.pack(fill="x", padx=14, pady=(0, 10))
        self.period_menu = ctk.CTkOptionMenu(row, values=["Monthly", "Semester", "Custom"], variable=self.period,
                                             command=lambda _v: self._dates_changed())
        self.period_menu.pack(side="left", padx=(0, 8))
        months = self._month_values()
        self.month_menu = ctk.CTkOptionMenu(row, values=months, variable=self.month, command=self._month_selected)
        self.month_menu.pack(side="left", padx=4)
        ctk.CTkLabel(row, text="From (DD-MM-YYYY)").pack(side="left", padx=(12, 4))
        self.from_entry = ctk.CTkEntry(row, textvariable=self.from_var, width=125); self.from_entry.pack(side="left")
        ctk.CTkLabel(row, text="To").pack(side="left", padx=(8, 4))
        self.to_entry = ctk.CTkEntry(row, textvariable=self.to_var, width=125); self.to_entry.pack(side="left")
        ctk.CTkButton(row, text="📅", width=32, command=lambda: self._calendar(self.from_var)).pack(side="left", padx=(2, 0))
        ctk.CTkButton(row, text="📅", width=32, command=lambda: self._calendar(self.to_var)).pack(side="left", padx=(2, 6))
        self.range_status = ctk.CTkLabel(row, text="", text_color=th.GREY); self.range_status.pack(side="left", padx=10)
        self.from_var.trace_add("write", lambda *_: self._dates_changed())
        self.to_var.trace_add("write", lambda *_: self._dates_changed())

        actions = ctk.CTkFrame(head, fg_color="transparent"); actions.pack(fill="x", padx=14, pady=(0, 10))
        self.summary = ctk.CTkLabel(actions, text="", text_color=th.GREY, anchor="w")
        self.summary.pack(side="left", expand=True, fill="x")
        self.search_entry = ctk.CTkEntry(actions, textvariable=self.search, width=190, placeholder_text="Search name or student ID")
        self.search_entry.pack(side="left", padx=6)
        self.search.trace_add("write", lambda *_: self.refresh_students())
        self.send_selected_btn = ctk.CTkButton(actions, text="Send Selected", fg_color=th.BLUE, command=self.send_selected, state="disabled")
        self.send_selected_btn.pack(side="right", padx=4)
        self.send_all_btn = ctk.CTkButton(actions, text="Send All Personalized Reports", fg_color=th.GREEN,
                                          command=self.send_all)
        self.send_all_btn.pack(side="right", padx=4)

        self.students = ctk.CTkScrollableFrame(self, fg_color=th.BG)
        self.students.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.schedule_card = th.card(self); self.schedule_card.pack(fill="x", padx=16, pady=(0, 12))
        self._draw_schedules()

    def _month_values(self):
        today = date.today(); vals = []
        for offset in range(-24, 13):
            y, m = today.year, today.month + offset
            y += (m - 1) // 12; m = (m - 1) % 12 + 1
            vals.append(date(y, m, 1).strftime("%B %Y"))
        return vals

    def _month_selected(self, value):
        try:
            chosen = datetime.strptime(value, "%B %Y").date()
        except ValueError:
            return
        end = date(chosen.year, chosen.month, calendar.monthrange(chosen.year, chosen.month)[1])
        self.from_var.set(chosen.strftime("%d-%m-%Y")); self.to_var.set(end.strftime("%d-%m-%Y"))

    def _calendar(self, target):
        try: chosen = datetime.strptime(target.get(), "%d-%m-%Y").date()
        except ValueError: chosen = date.today()
        state = {"year": chosen.year, "month": chosen.month}
        win = ctk.CTkToplevel(self); win.title("Choose date"); win.geometry("280x300"); win.transient(self.winfo_toplevel())
        heading = ctk.CTkFrame(win, fg_color="transparent"); heading.pack(fill="x", padx=8, pady=8)
        title = ctk.CTkLabel(heading, text=""); title.pack(side="left", expand=True)
        grid = ctk.CTkFrame(win, fg_color="transparent"); grid.pack(fill="both", expand=True, padx=8, pady=8)
        def draw():
            for child in grid.winfo_children(): child.destroy()
            month_date = date(state["year"], state["month"], 1)
            title.configure(text=month_date.strftime("%B %Y"))
            for col, day in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
                ctk.CTkLabel(grid, text=day, width=32).grid(row=0, column=col, padx=1, pady=1)
            for day in range(1, calendar.monthrange(state["year"], state["month"])[1] + 1):
                row, col = divmod(day + month_date.weekday() - 1, 7)
                ctk.CTkButton(grid, text=str(day), width=32, height=30,
                    command=lambda d=day: (target.set(date(state["year"], state["month"], d).strftime("%d-%m-%Y")), win.destroy())).grid(row=row+1, column=col, padx=1, pady=1)
        def move(delta):
            idx = state["year"] * 12 + state["month"] - 1 + delta
            state["year"], month0 = divmod(idx, 12); state["month"] = month0 + 1; draw()
        ctk.CTkButton(heading, text="‹", width=32, command=lambda: move(-1)).pack(side="left")
        ctk.CTkButton(heading, text="›", width=32, command=lambda: move(1)).pack(side="right")
        draw()

    def _dates_changed(self):
        if hasattr(self, "month_menu"):
            if self.period.get() == "Monthly": self.month_menu.pack(side="left", padx=4)
            else: self.month_menu.pack_forget()
        try:
            parse_report_range(self.from_var.get(), self.to_var.get())
            self.range_status.configure(text="Valid range", text_color=th.GREEN)
            if hasattr(self, "students"):
                self.refresh_students()
        except ValueError:
            self.range_status.configure(text="Enter valid From / To dates", text_color=th.RED)
            if hasattr(self, "students"):
                for w in self.students.winfo_children(): w.destroy()
            if hasattr(self, "send_all_btn"): self.send_all_btn.configure(state="disabled")

    def refresh(self):
        self._dates_changed()
        self._draw_schedules()

    def _dates(self):
        return parse_report_range(self.from_var.get(), self.to_var.get())

    def refresh_students(self):
        for widget in self.students.winfo_children(): widget.destroy()
        cid = self.app.class_id
        if not cid:
            ctk.CTkLabel(self.students, text="Select a class first.", text_color=th.GREY).pack(pady=35)
            self.send_all_btn.configure(state="disabled"); return
        try:
            start, end = self._dates()
            rows = self.app.email_service.email_center_students(cid, start, end)
        except Exception as exc:
            ctk.CTkLabel(self.students, text=str(exc), text_color=th.RED).pack(pady=20)
            self.send_all_btn.configure(state="disabled"); return
        all_rows = rows
        needle = self.search.get().strip().casefold()
        rows = [r for r in rows if needle in (r["name"] or "").casefold() or needle in r["code"].casefold()]
        addresses = sum(len(r["recipients"]) for r in all_rows)
        disabled = sum(len(self.app.db.email_recipients(r["id"])) - len(r["recipients"]) for r in rows)
        with_email = sum(bool(r["recipients"]) for r in rows)
        prev = sum(1 for r in rows for h in r["history"] if h["status"] == "sent")
        self.summary.configure(text=f"{len(rows)} students · {with_email} with recipients · {len(rows)-with_email} without · {addresses} enabled addresses · {disabled} disabled · {prev} recent provider-accepted sends")
        self.send_all_btn.configure(state="normal" if all_rows else "disabled")
        self.send_selected_btn.configure(state="normal" if any(r["id"] in self._selected_students and r["recipients"] for r in rows) else "disabled")
        if not rows:
            ctk.CTkLabel(self.students, text="No students are enrolled in this class.", text_color=th.GREY).pack(pady=30)
        if not rows and needle:
            ctk.CTkLabel(self.students, text="No students match this search.", text_color=th.GREY).pack(pady=30)
        for student in rows:
            self._student_card(student, cid, start, end)

    def _student_card(self, student, class_id, start, end):
        card = th.card(self.students); card.pack(fill="x", padx=6, pady=4)
        photo = ctk.CTkFrame(card, width=90, height=90, fg_color="#EEF2F7", corner_radius=8)
        photo.pack(side="left", padx=10, pady=8); photo.pack_propagate(False)
        loaded = None
        path = student.get("photo")
        if path:
            try:
                import cv2
                image = cv2.imread(path)
                if image is not None: loaded = th.to_ctk(image, 88, 88)
            except Exception:
                loaded = None
        if loaded:
            label = ctk.CTkLabel(photo, image=loaded, text=""); label.image = loaded; label.pack(expand=True)
        else:
            ctk.CTkLabel(photo, text="No photo", text_color=th.GREY, font=th.font(10)).pack(expand=True)
        details = ctk.CTkFrame(card, fg_color="transparent"); details.pack(side="left", fill="both", expand=True, padx=5, pady=8)
        selected = tk.BooleanVar(value=student["id"] in self._selected_students)
        def toggle_selection(sid=student["id"], var=selected):
            if var.get(): self._selected_students.add(sid)
            else: self._selected_students.discard(sid)
            self.send_selected_btn.configure(state="normal" if self._selected_students else "disabled")
        ctk.CTkCheckBox(card, text="", variable=selected, command=toggle_selection, width=24,
                        state="normal" if student["recipients"] else "disabled").pack(side="left", padx=(6, 0))
        name = student["name"] or student["code"]
        pct = "—" if student["pct"] is None else f"{student['pct']:.2f}%"
        ctk.CTkLabel(details, text=f"{name}  ·  {student['code']}", text_color=th.TEXT, font=th.font(14, True)).pack(anchor="w")
        ctk.CTkLabel(details, text=f"Attendance {pct} · Present {student['attended']} · Absent {student['absent']} · Recipients {len(student['recipients'])}",
                     text_color=th.GREY, font=th.font(11)).pack(anchor="w", pady=2)
        state = "No recipient configured" if not student["recipients"] else ("; ".join(f"{r['kind']}: {r['status']}" for r in student["history"][:2]) or "No prior email history")
        ctk.CTkLabel(details, text=state, text_color=th.RED if not student["recipients"] else th.GREY,
                     font=th.font(10)).pack(anchor="w")
        btns = ctk.CTkFrame(card, fg_color="transparent"); btns.pack(side="right", padx=10)
        ctk.CTkButton(btns, text="Preview", width=78, fg_color=th.BLUE_LT, text_color=th.BLUE,
                      command=lambda s=student: self.preview_student(class_id, s["id"], start, end)).pack(pady=3)
        ctk.CTkButton(btns, text="Send", width=78, fg_color=th.GREEN, state="normal" if student["recipients"] else "disabled",
                      command=lambda s=student: self.send_student(class_id, s["id"], start, end)).pack(pady=3)

    def preview_student(self, class_id, student_id, start, end):
        try:
            report = self.app.email_service.preview_student_report(class_id, student_id, start, end)
        except Exception as exc:
            messagebox.showwarning("Upasthiti", str(exc), parent=self); return
        win = ctk.CTkToplevel(self); win.title("Personalized attendance email preview"); win.geometry("620x620")
        win.transient(self.winfo_toplevel())
        card = th.card(win); card.pack(fill="both", expand=True, padx=14, pady=14)
        student = report["student"]
        ctk.CTkLabel(card, text=f"{student['name'] or student['code']} · {student['code']}",
                     font=th.font(16, True), text_color=th.TEXT).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(card, text=f"Recipients: {', '.join(r['email'] for r in report['recipients']) or 'No recipient configured'}",
                     wraplength=560, justify="left", text_color=th.GREY).pack(anchor="w", padx=14)
        ctk.CTkLabel(card, text=f"Subject: {report['subject']}", wraplength=560, justify="left",
                     text_color=th.TEXT).pack(anchor="w", padx=14, pady=6)
        body = ctk.CTkTextbox(card, wrap="word"); body.pack(fill="both", expand=True, padx=14, pady=8)
        body.insert("1.0", report["body"]); body.configure(state="disabled")
        row = ctk.CTkFrame(card, fg_color="transparent"); row.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkButton(row, text="Send Email", fg_color=th.GREEN,
                      state="normal" if report["recipients"] else "disabled",
                      command=lambda: (win.destroy(), self.send_student(class_id, student_id, start, end))).pack(side="left")
        ctk.CTkButton(row, text="Cancel", fg_color=th.GREY, command=win.destroy).pack(side="right")

    def _sender_ready(self):
        cfg = get_email_settings(self.app.db)
        if not cfg["configured"]:
            raise ValueError("Add or connect a sender in Settings → Email first.")
        if not cfg["enabled"]:
            raise ValueError("Enable Email in Settings → Email first.")

    def send_student(self, class_id, student_id, start, end):
        if self._busy: return
        try:
            self._sender_ready()
            report = self.app.email_service.preview_student_report(class_id, student_id, start, end)
            if not report["recipients"]: raise ValueError("No enabled recipient is configured for this student.")
            text = f"Student: {report['student']['name'] or report['student']['code']} ({report['student']['code']})\nPeriod: {_display_date(start)} → {_display_date(end)}\nRecipients: {len(report['recipients'])}\nSubject: {report['subject']}"
            if not messagebox.askyesno("Confirm personalized email", text + "\n\nSend this student's report separately to the listed recipients?", parent=self): return
            self._delivery_ids = self.app.email_service.enqueue_student_reports(class_id, [student_id], start, end, uuid.uuid4().hex)
            self._busy = True; self._poll_deliveries("Student report"); self.send_all_btn.configure(state="disabled")
        except Exception as exc:
            messagebox.showwarning("Upasthiti", str(exc), parent=self)

    def send_all(self):
        if self._busy: return
        try:
            self._sender_ready(); start, end = self._dates(); cid = self.app.class_id
            summary = self.app.email_service.send_all_summary(cid, start, end)
            if not summary["recipient_addresses"]: raise ValueError("No enrolled students have enabled email recipients.")
            info = (f"Class: {self.app.db.q('SELECT name FROM classes WHERE id=?', (cid,))[0]['name']}\nPeriod: {_display_date(start)} → {_display_date(end)}\n"
                    f"Students: {summary['students']}\nStudents with recipients: {summary['with_recipients']}\nStudents without recipients: {summary['without_recipients']}\n"
                    f"Enabled recipient addresses: {summary['recipient_addresses']}\nDisabled recipients: {summary['disabled_recipients']}\nPrevious successful sends for this exact period: {summary['previous_successes']}\n"
                    f"Students without recipients: {', '.join(summary['missing_codes'][:20]) or 'None'}\n\n"
                    "Each student will receive a separate personalized message only at their own addresses. Continue?")
            if not messagebox.askyesno("Confirm Send All", info, parent=self): return
            ids = [s["id"] for s in self.app.db.students(cid)]
            campaign = uuid.uuid4().hex
            self._busy = True; self.send_all_btn.configure(state="disabled")
            self.summary.configure(text="Preparing separate student-specific delivery jobs…")
            def queue_batch():
                try:
                    deliveries = self.app.email_service.enqueue_student_reports(cid, ids, start, end, campaign)
                    self.app.post(lambda result=deliveries: self._batch_queued(result, "Send All"))
                except Exception as exc:
                    self.app.post(lambda message=str(exc)[:300]: self._batch_queue_failed(message))
            threading.Thread(target=queue_batch, name="UpasthitiEmailBatch", daemon=True).start()
        except Exception as exc:
            messagebox.showwarning("Upasthiti", str(exc), parent=self)

    def send_selected(self):
        if self._busy: return
        try:
            self._sender_ready(); start, end = self._dates(); cid = self.app.class_id
            rows = self.app.email_service.email_center_students(cid, start, end)
            ids = [r["id"] for r in rows if r["id"] in self._selected_students and r["recipients"]]
            if not ids: raise ValueError("Select at least one student with an enabled recipient.")
            if not messagebox.askyesno("Confirm selected reports", f"Send separate personalized reports for {len(ids)} selected students? Each report goes only to its student's enabled recipients.", parent=self): return
            self._busy = True; self.send_selected_btn.configure(state="disabled"); self.send_all_btn.configure(state="disabled")
            self.summary.configure(text="Preparing separate student-specific delivery jobs…")
            def queue_batch():
                try:
                    deliveries = self.app.email_service.enqueue_student_reports(cid, ids, start, end, uuid.uuid4().hex)
                    self.app.post(lambda result=deliveries: self._batch_queued(result, "Selected reports"))
                except Exception as exc:
                    self.app.post(lambda message=str(exc)[:300]: self._batch_queue_failed(message))
            threading.Thread(target=queue_batch, name="UpasthitiEmailSelected", daemon=True).start()
        except Exception as exc:
            messagebox.showwarning("Upasthiti", str(exc), parent=self)

    def _batch_queued(self, delivery_ids, label):
        if not self.winfo_exists(): return
        self._delivery_ids = delivery_ids
        self.summary.configure(text=f"Queued {len(delivery_ids)} individual delivery records; sending in background…")
        self._poll_deliveries(label)

    def _batch_queue_failed(self, message):
        if not self.winfo_exists(): return
        self._busy = False
        self.send_all_btn.configure(state="normal")
        messagebox.showwarning("Upasthiti", message, parent=self)

    def _poll_deliveries(self, label):
        rows = [self.app.db.email_delivery(i) for i in self._delivery_ids]
        rows = [r for r in rows if r]
        if any(r["status"] in ("pending", "sending") for r in rows):
            self.summary.configure(text=f"{label}: processing {len(rows)} individual delivery records…")
            self.after(600, lambda: self._poll_deliveries(label)); return
        sent = sum(r["status"] == "sent" for r in rows)
        failed = sum(r["status"] == "failed" for r in rows)
        no_recipient = sum(r["status"] == "no_recipient" for r in rows)
        self.summary.configure(text=f"{label}: {sent} provider accepted · {failed} failed · {no_recipient} without recipient. Sent does not confirm inbox delivery.")
        self._busy = False; self.refresh_students()

    def _draw_schedules(self):
        if not hasattr(self, "schedule_card"): return
        for w in self.schedule_card.winfo_children(): w.destroy()
        if auth.current_role() == "admin":
            ctk.CTkLabel(self.schedule_card, text="Scheduled student reports", font=th.font(13, True), text_color=th.TEXT).pack(anchor="w", padx=14, pady=(10, 2))
            ctk.CTkLabel(self.schedule_card, text="Schedules run only while Upasthiti is open and the computer is on. No schedule is active unless you create one.",
                         text_color=th.GREY, font=th.font(10), wraplength=850).pack(anchor="w", padx=14)
            row = ctk.CTkFrame(self.schedule_card, fg_color="transparent"); row.pack(fill="x", padx=14, pady=6)
            ctk.CTkLabel(row, text="Send on (DD-MM-YYYY)").pack(side="left")
            ctk.CTkEntry(row, textvariable=self.send_on, width=130).pack(side="left", padx=6)
            ctk.CTkButton(row, text="Schedule current class/range", fg_color=th.BLUE, command=self.create_schedule).pack(side="left", padx=6)
        cid = self.app.class_id
        try: schedules = self.app.db.email_schedules(cid) if cid else []
        except Exception: schedules = []
        if cid and not schedules:
            ctk.CTkLabel(self.schedule_card, text="No scheduled reports for this class.", text_color=th.GREY).pack(anchor="w", padx=14, pady=4)
        for schedule in schedules:
            line = ctk.CTkFrame(self.schedule_card, fg_color="transparent"); line.pack(fill="x", padx=14, pady=3)
            ctk.CTkLabel(line, text=f"{schedule['class_name']} · {_display_date(schedule['report_from'])} → {_display_date(schedule['report_to'])} · Send {_display_date(schedule['send_on'])} · {'Enabled' if schedule['enabled'] else 'Disabled'}",
                         text_color=th.TEXT, anchor="w").pack(side="left", fill="x", expand=True)
            if auth.current_role() == "admin":
                ctk.CTkButton(line, text="Edit", width=52, command=lambda s=schedule: self.edit_schedule(s)).pack(side="right", padx=2)
                ctk.CTkButton(line, text="Disable" if schedule["enabled"] else "Enable", width=70, fg_color=th.BLUE_LT,
                              text_color=th.BLUE, command=lambda s=schedule: self.toggle_schedule(s)).pack(side="right", padx=2)
                ctk.CTkButton(line, text="Delete", width=55, fg_color=th.RED,
                              command=lambda s=schedule: self.remove_schedule(s)).pack(side="right", padx=2)

    def create_schedule(self):
        try:
            if not self.app.class_id: raise ValueError("Select a class first.")
            start, end = self._dates(); due = _iso_text(self.send_on.get())
            if not messagebox.askyesno("Create scheduled report", f"Schedule personalized reports for {_display_date(start)} → {_display_date(end)}, to run on {_display_date(due)}?\n\nEach student's data is sent only to that student's enabled recipients.", parent=self): return
            self.app.email_service.create_schedule(self.app.class_id, start, end, due)
            self._draw_schedules()
        except Exception as exc: messagebox.showwarning("Upasthiti", str(exc), parent=self)

    def edit_schedule(self, schedule):
        win = ctk.CTkToplevel(self); win.title("Edit scheduled report"); win.geometry("430x310"); win.transient(self.winfo_toplevel())
        classes = self.app.db.classes(); class_by_name = {row["name"]: row["id"] for row in classes}
        class_var = tk.StringVar(value=schedule["class_name"])
        ctk.CTkLabel(win, text="Class").pack(anchor="w", padx=18, pady=(12, 2))
        ctk.CTkOptionMenu(win, values=list(class_by_name) or [schedule["class_name"]], variable=class_var).pack(anchor="w", padx=18)
        vars_ = [tk.StringVar(value=_display_date(schedule[k])) for k in ("report_from", "report_to", "send_on")]
        for label, var in zip(("Report From", "Report To", "Send On"), vars_):
            ctk.CTkLabel(win, text=f"{label} (DD-MM-YYYY)").pack(anchor="w", padx=18, pady=(10, 2)); ctk.CTkEntry(win, textvariable=var, width=220).pack(anchor="w", padx=18)
        enabled = tk.BooleanVar(value=bool(schedule["enabled"])); ctk.CTkCheckBox(win, text="Enabled", variable=enabled).pack(anchor="w", padx=18, pady=10)
        def save():
            try:
                start, end = parse_report_range(vars_[0].get(), vars_[1].get()); due = _iso_text(vars_[2].get())
                self.app.email_service.update_schedule(schedule["id"], class_by_name[class_var.get()], start, end, due, enabled.get())
                win.destroy(); self._draw_schedules()
            except Exception as exc: messagebox.showwarning("Upasthiti", str(exc), parent=win)
        ctk.CTkButton(win, text="Save changes", fg_color=th.BLUE, command=save).pack(pady=8)

    def toggle_schedule(self, schedule):
        self.app.email_service.set_schedule_enabled(schedule["id"], not bool(schedule["enabled"])); self._draw_schedules()

    def remove_schedule(self, schedule):
        if messagebox.askyesno("Delete schedule", "Delete this scheduled report?", parent=self):
            self.app.email_service.delete_schedule(schedule["id"]); self._draw_schedules()
