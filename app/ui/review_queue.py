"""Staff review queue; action authorization is enforced by ReviewRequestService."""
import tkinter as tk
from tkinter import messagebox, simpledialog
import customtkinter as ctk
from .. import auth, review_requests
from . import theme as th


class ReviewQueuePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color=th.BG); self.app = app
        self.service = review_requests.ReviewRequestService(app.db)
        self.scroll = ctk.CTkScrollableFrame(self, fg_color=th.BG); self.scroll.pack(fill="both", expand=True, padx=16, pady=12)
        self.status = tk.StringVar(value="All")
        top = ctk.CTkFrame(self.scroll, fg_color="transparent"); top.pack(fill="x")
        ctk.CTkLabel(top, text="Attendance Review Requests", font=th.font(20, True), text_color=th.TEXT).pack(side="left", padx=8)
        ctk.CTkOptionMenu(top, variable=self.status, values=["All", "Pending", "Under Review", "Escalated", "Resolved — Changed", "Resolved — Kept", "Dismissed"], command=lambda _: self.refresh()).pack(side="right", padx=8)
        self.rows = ctk.CTkFrame(self.scroll, fg_color="transparent"); self.rows.pack(fill="x")
        self.refresh()

    def refresh(self):
        for child in self.rows.winfo_children(): child.destroy()
        states = None if self.status.get() == "All" else [self.status.get()]
        try: requests = self.service.list_for_current_user(states)
        except PermissionError as exc:
            ctk.CTkLabel(self.rows, text=str(exc)).pack(anchor="w"); return
        if not requests:
            ctk.CTkLabel(self.rows, text="No requests in this filter.", text_color=th.GREY).pack(anchor="w", padx=8, pady=10); return
        for row in requests:
            card = th.card(self.rows); card.pack(fill="x", padx=4, pady=5)
            details = f"{row['name'] or row['code']} · ID {row['code']}\n{row['date']} · {row['subject'] or 'Unspecified'} · Marked {row['original_status']}\nReason: {row['reason']}\n{row['explanation']}\nStatus: {row['status']}"
            ctk.CTkLabel(card, text=details, justify="left", anchor="w", wraplength=740, text_color=th.TEXT).pack(side="left", fill="x", expand=True, padx=12, pady=10)
            actions = ctk.CTkFrame(card, fg_color="transparent"); actions.pack(side="right", padx=8)
            ctk.CTkButton(actions, text="Start review", width=120, command=lambda rid=row["id"]: self._act(rid, "start")).pack(pady=3)
            ctk.CTkButton(actions, text="Change status", width=120, command=lambda rid=row["id"]: self._change(rid)).pack(pady=3)
            ctk.CTkButton(actions, text="Keep", width=120, command=lambda rid=row["id"]: self._act(rid, "keep")).pack(pady=3)
            ctk.CTkButton(actions, text="Dismiss", width=120, command=lambda rid=row["id"]: self._act(rid, "dismiss")).pack(pady=3)
            if auth.current_role() == "faculty":
                ctk.CTkButton(actions, text="Escalate", width=120, command=lambda rid=row["id"]: self._act(rid, "escalate")).pack(pady=3)

    def _act(self, rid, action):
        reason = simpledialog.askstring("Attendance review", "Resolution note (optional):", parent=self) or ""
        try: self.service.transition(rid, action, reason)
        except (ValueError, PermissionError) as exc: messagebox.showwarning("Upasthiti", str(exc), parent=self)
        self.refresh()

    def _change(self, rid):
        status = simpledialog.askstring("Attendance review", "New status: P, A, L, E, or OD", parent=self)
        if not status: return
        try: self.service.transition(rid, "change", "Attendance updated after human review.", status.strip().upper())
        except (ValueError, PermissionError) as exc: messagebox.showwarning("Upasthiti", str(exc), parent=self)
        self.refresh()

