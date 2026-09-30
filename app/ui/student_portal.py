"""Dedicated student interface. All reads/writes go through scoped services."""
import tkinter as tk
from tkinter import messagebox, simpledialog
import customtkinter as ctk
from .. import auth, chat_assistant, portal_service, review_requests
from . import theme as th


class StudentPortalPage(ctk.CTkFrame):
    NAV = (("Home", "home"), ("My Attendance", "attendance"), ("Recovery Assistant", "recovery"),
           ("My Reports", "reports"), ("Review Requests", "reviews"), ("Notifications", "notifications"),
           ("Profile", "profile"), ("Chat with Upasthiti", "chat"))

    def __init__(self, master, app):
        super().__init__(master, fg_color=th.BG)
        self.app = app
        self.portal = portal_service.StudentPortalService(app.db)
        self.reviews = review_requests.ReviewRequestService(app.db)
        self.assistant = chat_assistant.LocalAssistant(app.db)
        self.screen = "home"
        head = ctk.CTkFrame(self, fg_color=th.WHITE, corner_radius=12)
        head.pack(fill="x", padx=24, pady=(20, 12))
        student = app.db.q("SELECT name FROM students WHERE id=?", (auth.current_student_id(),))
        ctk.CTkLabel(head, text=f"Welcome, {student[0]['name'] if student else 'Student'}", font=th.font(21, True), text_color=th.TEXT).pack(side="left", padx=18, pady=16)
        ctk.CTkButton(head, text="Log out", width=90, command=app.logout).pack(side="right", padx=18)
        self.nav = ctk.CTkFrame(self, fg_color="transparent")
        self.nav.pack(fill="x", padx=20)
        for title, key in self.NAV:
            ctk.CTkButton(self.nav, text=title, width=136, height=34, command=lambda k=key: self.show(k)).pack(side="left", padx=3, pady=4)
        self.body = ctk.CTkScrollableFrame(self, fg_color=th.BG)
        self.body.pack(fill="both", expand=True, padx=24, pady=12)
        self.show("home")

    def refresh(self): self.show(self.screen)

    def _clear(self):
        for child in self.body.winfo_children(): child.destroy()

    def _label(self, text, size=14, bold=False):
        ctk.CTkLabel(self.body, text=text, font=th.font(size, bold), text_color=th.TEXT, anchor="w", justify="left", wraplength=900).pack(fill="x", pady=5)

    def _list(self, rows, render, empty, parent=None):
        parent = parent or self.body
        if not rows:
            ctk.CTkLabel(parent, text=empty, font=th.font(14), text_color=th.TEXT, anchor="w").pack(fill="x", pady=5); return
        for row in rows:
            card = ctk.CTkFrame(parent, fg_color=th.WHITE, corner_radius=8)
            card.pack(fill="x", pady=4)
            render(card, row)

    def show(self, key):
        self.screen = key; self._clear()
        try:
            if key in ("home", "recovery"):
                summary = self.portal.summary(); overall = summary["overall"]
                self._label("My Attendance", 20, True)
                self._label(f"Overall: {overall['current']:.2f}%" if overall["current"] is not None else "Overall: no counted attendance yet")
                self._label(f"Classes counted: {overall['held']} · Present/late: {overall['attended']} · Absent: {overall['absent']} · Target: {overall['target']:g}%")
                if key == "recovery":
                    needed = overall["classes_needed"]
                    self._label("Recovery Assistant", 18, True)
                    self._label("Insufficient attendance history to calculate a plan." if needed is None else f"Attend {needed} consecutive counted classes to reach the target." if needed else "You are at or above your target.")
                    safe = overall["safe_to_miss"]
                    self._label("Safe-to-miss classes: not available yet." if safe is None else f"Safe-to-miss classes at this target: {safe}.")
                    self._label("Subject-wise attendance", 15, True)
                    for item in summary["subjects"]:
                        self._label(f"{item['subject']}: {item['current']:.2f}% · {item['attended']} attended · {item['absent']} absent" if item["current"] is not None else f"{item['subject']}: no counted attendance")
                    goal = ctk.CTkEntry(self.body, placeholder_text="Attendance goal (0–100%)")
                    goal.pack(anchor="w", pady=5)
                    ctk.CTkButton(self.body, text="Save my goal", command=lambda: self._save_goal(goal.get())).pack(anchor="w")
                    upcoming = ctk.CTkEntry(self.body, placeholder_text="Upcoming classes"); upcoming.pack(anchor="w", pady=(12, 3))
                    attend = ctk.CTkEntry(self.body, placeholder_text="Plan to attend"); attend.pack(anchor="w", pady=3)
                    miss = ctk.CTkEntry(self.body, placeholder_text="Plan to miss"); miss.pack(anchor="w", pady=3)
                    result = ctk.CTkLabel(self.body, text="Scenario uses only the attend/miss values you enter."); result.pack(anchor="w", pady=4)
                    def calculate():
                        try:
                            from ..recovery import what_if
                            value = what_if(overall["attended"], overall["absent"], overall["target"], upcoming.get(), attend.get(), miss.get())
                            result.configure(text=f"Projected attendance: {value['projected']:.2f}%" if value["projected"] is not None else "No counted classes in this scenario.")
                        except (ValueError, TypeError) as exc: result.configure(text=str(exc))
                    ctk.CTkButton(self.body, text="Calculate scenario", command=calculate).pack(anchor="w")
                else:
                    self._label(f"Recent absences: {len(summary['absences'])} · Subjects needing attention: {sum(1 for s in summary['subjects'] if s['level'] in ('warn','critical'))}")
                    self._label("Recent attendance", 16, True)
                    self._list(summary["recent"], lambda box, row: ctk.CTkLabel(box, text=f"{row['date']} · {row['subject'] or 'Unspecified'} · {row['status']}").pack(anchor="w", padx=12, pady=8), "No attendance history yet.")
            elif key == "attendance":
                self._label("My Attendance", 20, True)
                all_rows = self.portal.history()
                filters = ctk.CTkFrame(self.body, fg_color="transparent"); filters.pack(fill="x", pady=5)
                start = ctk.CTkEntry(filters, placeholder_text="From YYYY-MM-DD", width=150); start.pack(side="left", padx=3)
                end = ctk.CTkEntry(filters, placeholder_text="To YYYY-MM-DD", width=150); end.pack(side="left", padx=3)
                subjects = sorted({r["subject"] for r in all_rows if r["subject"]})
                subject = tk.StringVar(value="All subjects")
                ctk.CTkOptionMenu(filters, variable=subject, values=["All subjects", *subjects], width=170).pack(side="left", padx=3)
                status = tk.StringVar(value="All statuses")
                ctk.CTkOptionMenu(filters, variable=status, values=["All statuses", "P", "A", "L", "E", "OD"], width=125).pack(side="left", padx=3)
                result = ctk.CTkFrame(self.body, fg_color="transparent"); result.pack(fill="x")
                def draw_history():
                    for child in result.winfo_children(): child.destroy()
                    try: rows = self.portal.history(start.get().strip() or None, end.get().strip() or None,
                        None if subject.get() == "All subjects" else subject.get(),
                        None if status.get() == "All statuses" else status.get())
                    except ValueError as exc:
                        ctk.CTkLabel(result, text=str(exc), text_color=th.RED).pack(anchor="w"); return
                    self._list(rows, lambda box, row: self._attendance_row(box, row), "No attendance records match these filters.", result)
                ctk.CTkButton(filters, text="Filter", width=70, command=draw_history).pack(side="left", padx=3)
                rows = all_rows
                self._list(rows, lambda box, row: self._attendance_row(box, row), "No attendance history yet.", result)
            elif key == "reports":
                self._label("My Reports", 20, True)
                self._label("This summary is private to your signed-in account. For a date range, enter inclusive ISO dates (YYYY-MM-DD).")
                start = ctk.CTkEntry(self.body, placeholder_text="From YYYY-MM-DD"); start.pack(anchor="w", pady=3)
                end = ctk.CTkEntry(self.body, placeholder_text="To YYYY-MM-DD"); end.pack(anchor="w", pady=3)
                result = ctk.CTkLabel(self.body, text=""); result.pack(anchor="w", pady=5)
                def report():
                    try:
                        item = self.portal.report_summary(start.get().strip(), end.get().strip())
                        result.configure(text=f"{item['attended']} attended · {item['absent']} absent · {item['pct']:.2f}%" if item['pct'] is not None else "No counted records in this period.")
                    except (ValueError, PermissionError) as exc: result.configure(text=str(exc))
                ctk.CTkButton(self.body, text="Show my report", command=report).pack(anchor="w")
            elif key == "reviews":
                self._label("My Review Requests", 20, True)
                rows = self.portal.history()
                self._list(rows, lambda box, row: self._review_row(box, row), "There are no absent entries to request review for.")
                self._label("Request review from a listed attendance row; submitting a request does not change attendance.")
                self._list(self.portal.review_requests(), lambda box, row: ctk.CTkLabel(box, text=f"{row['date']} · {row['subject']} · {row['status']}").pack(anchor="w", padx=12, pady=8), "You have no review requests.")
            elif key == "notifications":
                self._label("My Notifications", 20, True)
                self._list(self.portal.notifications(), lambda box, row: ctk.CTkLabel(box, text=f"{row.get('kind', row.get('type','Update'))} · {row.get('status','')} · {row.get('updated_at','')}").pack(anchor="w", padx=12, pady=8), "No notifications yet.")
            elif key == "profile":
                sid = auth.current_student_id()
                row = self.app.db.q("SELECT name,code FROM students WHERE id=?", (sid,))[0]
                self._label("My Profile", 20, True); self._label(f"Name: {row['name']}\nStudent ID: {row['code']}\nPassword: stored as a salted one-way hash; it is never displayed.")
            elif key == "chat":
                self._label("Chat with Upasthiti", 20, True)
                self._label("Local, deterministic attendance help. Questions and attendance data are not sent to an external AI service.")
                entry = ctk.CTkEntry(self.body, placeholder_text="Ask about attendance or recovery"); entry.pack(fill="x", pady=5)
                answer = ctk.CTkTextbox(self.body, height=150); answer.pack(fill="x", pady=5)
                def ask(): answer.delete("1.0", "end"); answer.insert("end", self.assistant.answer(entry.get()))
                ctk.CTkButton(self.body, text="Ask", command=ask).pack(anchor="w")
        except (PermissionError, ValueError) as exc:
            self._label(str(exc))

    def _attendance_row(self, box, row):
        ctk.CTkLabel(box, text=f"{row['date']} · {row['subject'] or 'Unspecified'} · {row['status']}").pack(side="left", padx=12, pady=8)
    def _review_row(self, box, row):
        ctk.CTkLabel(box, text=f"{row['date']} · {row['subject'] or 'Unspecified'} · Marked {row['status']}").pack(side="left", padx=12, pady=8)
        ctk.CTkButton(box, text="Request review", width=120, command=lambda r=row: self._submit_review(r)).pack(side="right", padx=8, pady=5)
    def _submit_review(self, row):
        reason = simpledialog.askstring("Attendance review", "Reason: I was present / Wrong attendance status / Recognition mismatch / Wrong class/subject / Other", parent=self)
        if not reason: return
        if reason.strip() not in review_requests.REASONS:
            messagebox.showwarning("Upasthiti", "Enter one of the listed reasons.", parent=self); return
        explanation = simpledialog.askstring("Attendance review", "Optional explanation (up to 1,000 characters):", parent=self) or ""
        try:
            _, made = self.reviews.submit(row["session_id"], reason.strip(), explanation)
            messagebox.showinfo("Upasthiti", "Review request submitted." if made else "An active review request already exists for this session.", parent=self)
            self.show("reviews")
        except (PermissionError, ValueError) as exc: messagebox.showwarning("Upasthiti", str(exc), parent=self)
    def _save_goal(self, value):
        try: self.portal.set_goal(float(value)); messagebox.showinfo("Upasthiti", "Your recovery target is saved.", parent=self); self.show("recovery")
        except (ValueError, PermissionError) as exc: messagebox.showwarning("Upasthiti", str(exc), parent=self)
