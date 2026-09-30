"""Explicit preview-and-send attendance email dialog for the selected class."""
import calendar
from datetime import date, datetime
import uuid
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from .. import auth
from ..email_service import normalize_email, get_email_settings, student_report_template
from .. import stats
from . import theme as th


def parse_report_range(from_text, to_text):
    """Parse the exact inclusive date range shown in the email-report dialog."""
    try:
        start = datetime.strptime(from_text.strip(), "%d-%m-%Y").date()
        end = datetime.strptime(to_text.strip(), "%d-%m-%Y").date()
    except ValueError as exc:
        raise ValueError("Enter real dates in DD-MM-YYYY format.") from exc
    if start > end:
        raise ValueError("From date must be on or before To date.")
    return start.isoformat(), end.isoformat()


class EmailReportDialog(ctk.CTkToplevel):
    def __init__(self, page):
        super().__init__(page)
        self.page, self.app = page, page.app
        self.class_id = self.app.class_id
        self.title("Email Attendance Report")
        self.geometry("720x760"); self.minsize(620, 600)
        self.transient(page.winfo_toplevel())
        self.configure(fg_color=th.BG)
        self._preview_state = None
        self._delivery_ids = []
        self._sending = False
        if auth.current_role() == "student":
            self.destroy(); return
        card = th.card(self); card.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(card, text="Email Attendance Report", font=th.font(18, True), text_color=th.TEXT).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(card, text="Select a report period. Dates are editable and the displayed dates are the dates used.",
                     text_color=th.GREY, wraplength=660, justify="left").pack(anchor="w", padx=16)
        if not self.class_id:
            ctk.CTkLabel(card, text="Select a class first.", text_color=th.RED).pack(padx=16, pady=24)
            return
        today = date.today()
        first = date(page.year, page.month, 1)
        last = date(page.year, page.month, calendar.monthrange(page.year, page.month)[1])
        self.period = tk.StringVar(value="Monthly")
        row = ctk.CTkFrame(card, fg_color="transparent"); row.pack(fill="x", padx=16, pady=(10, 4))
        ctk.CTkLabel(row, text="Period").pack(side="left", padx=(0, 8))
        ctk.CTkOptionMenu(row, values=["Monthly", "Semester", "Custom Date Range"],
                          variable=self.period, command=lambda _v: self.invalidate()).pack(side="left")
        ctk.CTkLabel(row, text="For Semester, enter your organization's dates; none are assumed.",
                     text_color=th.GREY, font=th.font(10)).pack(side="left", padx=10)
        dates = ctk.CTkFrame(card, fg_color="transparent"); dates.pack(fill="x", padx=16, pady=4)
        self.from_var = tk.StringVar(value=first.strftime("%d-%m-%Y"))
        self.to_var = tk.StringVar(value=last.strftime("%d-%m-%Y"))
        ctk.CTkLabel(dates, text="From (DD-MM-YYYY)").pack(side="left")
        ctk.CTkEntry(dates, textvariable=self.from_var, width=130).pack(side="left", padx=6)
        ctk.CTkLabel(dates, text="To (DD-MM-YYYY)").pack(side="left", padx=(8, 0))
        ctk.CTkEntry(dates, textvariable=self.to_var, width=130).pack(side="left", padx=6)
        self.from_var.trace_add("write", lambda *_: self.invalidate())
        self.to_var.trace_add("write", lambda *_: self.invalidate())
        self.kind = tk.StringVar(value="Student reports")
        kindrow = ctk.CTkFrame(card, fg_color="transparent"); kindrow.pack(fill="x", padx=16, pady=(8, 4))
        ctk.CTkLabel(kindrow, text="Email type").pack(side="left", padx=(0, 8))
        self.kind_menu = ctk.CTkOptionMenu(kindrow, values=["Student reports", "Class workbook"],
                                           variable=self.kind, command=lambda _v: self._switch_kind())
        self.kind_menu.pack(side="left")
        self.student_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.student_frame.pack(fill="both", expand=True, padx=16, pady=4)
        controls = ctk.CTkFrame(self.student_frame, fg_color="transparent"); controls.pack(fill="x")
        ctk.CTkButton(controls, text="Select all", width=90, command=lambda: self.select_all(True)).pack(side="left")
        ctk.CTkButton(controls, text="Clear", width=70, fg_color=th.BLUE_LT, text_color=th.BLUE,
                      command=lambda: self.select_all(False)).pack(side="left", padx=6)
        self.students_box = ctk.CTkScrollableFrame(self.student_frame, height=220, fg_color=th.BG)
        self.students_box.pack(fill="both", expand=True, pady=5)
        self.student_vars = {}
        for student in self.app.db.students(self.class_id):
            var = tk.BooleanVar(value=True)
            var.trace_add("write", lambda *_: self.invalidate())
            self.student_vars[student["id"]] = (student, var)
            ctk.CTkCheckBox(self.students_box, text=f"{student['name'] or student['code']} ({student['code']})",
                            variable=var).pack(anchor="w", pady=2)
        self.admin_frame = ctk.CTkFrame(card, fg_color="transparent")
        ctk.CTkLabel(self.admin_frame, text="Administrative recipients (comma or semicolon separated)",
                     text_color=th.GREY).pack(anchor="w")
        self.admin_to = tk.StringVar()
        ctk.CTkEntry(self.admin_frame, textvariable=self.admin_to, width=620,
                     placeholder_text="office@example.edu").pack(anchor="w", pady=4)
        self.admin_to.trace_add("write", lambda *_: self.invalidate())
        ctk.CTkLabel(self.admin_frame, text="The selected class-range Excel workbook is attached. Recipients are entered for this send only.",
                     text_color=th.GREY, font=th.font(10), wraplength=650, justify="left").pack(anchor="w")
        self.preview_text = ctk.CTkLabel(card, text="", text_color=th.TEXT, wraplength=650, justify="left", anchor="w")
        self.preview_text.pack(fill="x", padx=16, pady=8)
        self.status = ctk.CTkLabel(card, text="", text_color=th.GREY, wraplength=650, justify="left")
        self.status.pack(fill="x", padx=16, pady=4)
        actions = ctk.CTkFrame(card, fg_color="transparent"); actions.pack(fill="x", padx=16, pady=(4, 14))
        self.preview_btn = ctk.CTkButton(actions, text="Preview", fg_color=th.BLUE_LT, text_color=th.BLUE,
                                         command=self.preview)
        self.preview_btn.pack(side="left")
        self.send_btn = ctk.CTkButton(actions, text="Send", fg_color=th.GREEN, state="disabled", command=self.send)
        self.send_btn.pack(side="left", padx=6)
        ctk.CTkButton(actions, text="Retry Failed in This Send", fg_color=th.BLUE_LT, text_color=th.BLUE,
                      command=self.retry).pack(side="left", padx=6)
        ctk.CTkButton(actions, text="Cancel", fg_color=th.GREY, command=self.destroy).pack(side="right")

    def _switch_kind(self):
        self.student_frame.pack_forget(); self.admin_frame.pack_forget()
        if self.kind.get() == "Student reports":
            self.student_frame.pack(fill="both", expand=True, padx=16, pady=4)
        else:
            self.admin_frame.pack(fill="x", padx=16, pady=8)
        self.invalidate()

    def select_all(self, value):
        for _, var in self.student_vars.values(): var.set(value)
        self.invalidate()

    def invalidate(self):
        self._preview_state = None
        if hasattr(self, "send_btn"): self.send_btn.configure(state="disabled")
        if hasattr(self, "preview_text"): self.preview_text.configure(text="Changes require a new preview before sending.")

    def _dates(self):
        return parse_report_range(self.from_var.get(), self.to_var.get())

    def _selected_students(self):
        return [(s, v) for s, v in self.student_vars.values() if v.get()]

    def _addresses(self):
        raw = self.admin_to.get().replace(";", ",").split(",")
        values = [x.strip() for x in raw if x.strip()]
        addresses = [normalize_email(x) for x in values]
        if not addresses: raise ValueError("Enter at least one administrative recipient.")
        if len({x.casefold() for x in addresses}) != len(addresses):
            raise ValueError("Remove duplicate administrative addresses.")
        return addresses

    def _state(self):
        start, end = self._dates()
        kind = self.kind.get()
        if kind == "Student reports":
            selected = self._selected_students()
            if not selected: raise ValueError("Select at least one student.")
            ids = [s["id"] for s, _ in selected]
            addrs = sum(len(self.app.db.email_recipients(sid, enabled_only=True)) for sid in ids)
            label = self.period.get()
            preview = f"{label} student reports\nPeriod: {self._fmt(start)} to {self._fmt(end)}\nRecipients: {len(ids)} students, {addrs} enabled email addresses"
            first = selected[0]
            summary = stats.student_range(self.app.db, first[0]["id"], start, end)
            cname = self.app.db.q("SELECT name FROM classes WHERE id=?", (self.class_id,))[0]["name"]
            subject, body = student_report_template(first[0], cname, start, end, summary,
                                                    self.app.db.get("college_name", "") or "Upasthiti")
            return (kind, label, start, end, tuple(ids)), preview + f"\n\nSample for {first[0]['name'] or first[0]['code']}:\nSubject: {subject}\n\n{body}"
        addrs = self._addresses()
        label = self.period.get()
        return (kind, label, start, end, tuple(addrs)), f"{label} class workbook\nPeriod: {self._fmt(start)} to {self._fmt(end)}\nRecipients: {len(addrs)} email addresses\nClass: {self.app.db.q('SELECT name FROM classes WHERE id=?', (self.class_id,))[0]['name']}\n\nThe email will include an Excel attendance summary for this class and date range."

    @staticmethod
    def _fmt(iso):
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%m-%Y")

    def preview(self):
        try:
            state, text = self._state()
            self._preview_state = state
            self.preview_text.configure(text="PREVIEW\n" + text)
            self.status.configure(text="No message has been sent. Review the preview, then click Send.", text_color=th.GREY)
            self.send_btn.configure(state="normal")
        except Exception as exc:
            self._preview_state = None; self.send_btn.configure(state="disabled")
            messagebox.showwarning("Upasthiti", str(exc), parent=self)

    def send(self):
        if self._sending: return
        try:
            state, text = self._state()
            if state != self._preview_state:
                self.invalidate()
                messagebox.showinfo("Upasthiti", "The report changed. Preview it again before sending.", parent=self)
                return
            cfg = get_email_settings(self.app.db)
            if not cfg["configured"]:
                raise ValueError("Email is not configured. Set up a sender account in Settings → Email.")
            if not cfg["enabled"]:
                raise ValueError("Email is disabled. Enable it in Settings → Email before sending.")
            if not messagebox.askyesno("Confirm email send", f"You are about to send:\n\n{text}\n\nContinue?", parent=self): return
            kind, _period, start, end, targets = state
            campaign = uuid.uuid4().hex
            if kind == "Student reports":
                ids = list(targets)
                self._delivery_ids = self.app.email_service.enqueue_student_reports(self.class_id, ids, start, end, campaign)
            else:
                self._delivery_ids = self.app.email_service.enqueue_admin_report(self.class_id, start, end, list(targets), campaign)
            self._sending = True
            self.send_btn.configure(state="disabled"); self.preview_btn.configure(state="disabled")
            self.status.configure(text=f"Queued {len(self._delivery_ids)} delivery record(s). Sending in background…", text_color=th.BLUE)
            self._poll()
        except Exception as exc:
            messagebox.showwarning("Upasthiti", str(exc), parent=self)

    def _poll(self):
        if not self.winfo_exists(): return
        rows = [self.app.db.email_delivery(i) for i in self._delivery_ids]
        rows = [r for r in rows if r]
        active = sum(r["status"] in ("pending", "sending") for r in rows)
        sent = sum(r["status"] == "sent" for r in rows)
        failed = sum(r["status"] == "failed" for r in rows)
        no_recipient = sum(r["status"] == "no_recipient" for r in rows)
        self.status.configure(text=f"{len(rows) - active} / {len(rows)} processed — {sent} provider accepted, {failed} failed, {no_recipient} without a recipient.",
                              text_color=th.RED if failed else th.GREEN)
        if active: self.after(600, self._poll)
        else:
            self._sending = False
            self.preview_btn.configure(state="normal")

    def retry(self):
        if not self._delivery_ids:
            messagebox.showinfo("Upasthiti", "No email batch is available to retry.", parent=self); return
        ids = self.app.email_service.retry_failed(self._delivery_ids)
        if not ids:
            messagebox.showinfo("Upasthiti", "No retryable failures in this send.", parent=self); return
        self._sending = True
        self.status.configure(text=f"Retrying {len(ids)} failed email(s)…", text_color=th.BLUE)
        self._poll()
