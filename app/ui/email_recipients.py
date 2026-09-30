"""Administrator-only editor for normalized per-student email recipients."""
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from .. import auth
from ..email_service import normalize_email
from . import theme as th


class StudentEmailDialog(ctk.CTkToplevel):
    def __init__(self, page, student):
        super().__init__(page)
        if auth.current_role() != "admin":
            messagebox.showwarning("Upasthiti", "Only an administrator can manage student email recipients.", parent=page)
            self.destroy()
            return
        self.page, self.app, self.student = page, page.app, student
        self.title("Email recipients")
        self.geometry("580x470")
        self.minsize(480, 350)
        self.transient(page.winfo_toplevel())
        self.configure(fg_color=th.BG)
        c = th.card(self); c.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(c, text=f"Email recipients — {student['name'] or student['code']} ({student['code']})",
                     font=th.font(15, True), text_color=th.TEXT).pack(anchor="w", padx=14, pady=(12, 8))
        self.rows = ctk.CTkScrollableFrame(c, fg_color=th.BG); self.rows.pack(fill="both", expand=True, padx=10)
        actions = ctk.CTkFrame(c, fg_color="transparent"); actions.pack(fill="x", padx=12, pady=10)
        ctk.CTkButton(actions, text="+ Add Email", fg_color=th.BLUE, command=lambda: self.edit()).pack(side="left")
        self.status = ctk.CTkLabel(c, text="", text_color=th.GREEN, anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 8))
        self.render()

    def render(self):
        for w in self.rows.winfo_children(): w.destroy()
        for rec in self.app.email_service.list_student_recipients(self.student["id"]):
            row = th.card(self.rows); row.pack(fill="x", pady=4)
            label = rec["label"] or "Recipient"
            ctk.CTkLabel(row, text=f"{label} — {rec['email']}\n{'Enabled' if rec['enabled'] else 'Disabled'}",
                         text_color=th.TEXT if rec["enabled"] else th.GREY, justify="left").pack(side="left", padx=9, pady=8, expand=True, fill="x")
            ctk.CTkButton(row, text="Edit", width=50, command=lambda r=rec: self.edit(r)).pack(side="right", padx=2)
            ctk.CTkButton(row, text="Remove", width=65, fg_color=th.RED,
                          command=lambda r=rec: self.remove(r)).pack(side="right", padx=2)
            ctk.CTkButton(row, text="Disable" if rec["enabled"] else "Enable", width=65,
                          fg_color=th.BLUE_LT, text_color=th.BLUE,
                          command=lambda r=rec: self.toggle(r)).pack(side="right", padx=2)
        if not self.app.email_service.list_student_recipients(self.student["id"]):
            ctk.CTkLabel(self.rows, text="No email recipients configured.", text_color=th.GREY).pack(pady=24)

    def edit(self, recipient=None):
        win = ctk.CTkToplevel(self)
        win.title("Edit recipient" if recipient else "Add recipient")
        win.geometry("390x270"); win.transient(self); win.grab_set()
        ctk.CTkLabel(win, text="Email address").pack(anchor="w", padx=18, pady=(18, 3))
        email = tk.StringVar(value=recipient["email"] if recipient else "")
        ctk.CTkEntry(win, textvariable=email, width=340).pack(padx=18)
        ctk.CTkLabel(win, text="Label (optional, e.g. Student, Parent, Guardian)").pack(anchor="w", padx=18, pady=(12, 3))
        label = tk.StringVar(value=recipient["label"] if recipient else "")
        ctk.CTkEntry(win, textvariable=label, width=340).pack(padx=18)
        enabled = tk.BooleanVar(value=bool(recipient["enabled"]) if recipient else True)
        ctk.CTkCheckBox(win, text="Recipient enabled", variable=enabled).pack(anchor="w", padx=18, pady=12)
        def save():
            try:
                address = normalize_email(email.get())
                if recipient:
                    duplicate = [r for r in self.app.email_service.list_student_recipients(self.student["id"])
                                 if r["id"] != recipient["id"] and r["email"].casefold() == address.casefold()]
                    if duplicate: raise ValueError("This recipient is already listed for this student.")
                    self.app.email_service.update_student_recipient(self.student["id"], recipient["id"], address, label.get().strip(), enabled.get())
                    message = "Recipient updated."
                else:
                    self.app.email_service.add_student_recipient(self.student["id"], address, label.get().strip(), enabled.get())
                    message = "Recipient added."
                self.status.configure(text=message); self.render(); win.destroy()
            except ValueError as exc:
                messagebox.showwarning("Upasthiti", str(exc), parent=win)
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    messagebox.showwarning("Upasthiti", "This recipient is already listed for this student.", parent=win)
                else:
                    messagebox.showerror("Upasthiti", "Could not save this recipient.", parent=win)
        ctk.CTkButton(win, text="Save", fg_color=th.BLUE, command=save).pack(pady=6)

    def toggle(self, recipient):
        enabled = not bool(recipient["enabled"])
        self.app.email_service.update_student_recipient(self.student["id"], recipient["id"], recipient["email"], recipient["label"], enabled)
        self.status.configure(text="Recipient enabled." if enabled else "Recipient disabled.")
        self.render()

    def remove(self, recipient):
        if not messagebox.askyesno("Upasthiti", f"Remove {recipient['email']} from this student?", parent=self): return
        self.app.email_service.remove_student_recipient(self.student["id"], recipient["id"])
        self.status.configure(text="Recipient removed.")
        self.render()
