"""Class-scoped staff recovery and deterministic local chat screens."""
import tkinter as tk
import customtkinter as ctk
from .. import auth, chat_assistant, recovery
from . import theme as th


class StaffToolsPage(ctk.CTkFrame):
    def __init__(self, parent, app, kind):
        super().__init__(parent, fg_color=th.BG); self.app, self.kind = app, kind
        self.wrap = ctk.CTkScrollableFrame(self, fg_color=th.BG); self.wrap.pack(fill="both", expand=True, padx=18, pady=14)
        self.refresh()

    def refresh(self):
        for w in self.wrap.winfo_children(): w.destroy()
        if auth.current_role() not in ("admin", "faculty"):
            ctk.CTkLabel(self.wrap, text="Staff sign-in is required.").pack(anchor="w"); return
        cid = self.app.class_id
        if cid is None or not auth.can_access_class(self.app.db, cid):
            ctk.CTkLabel(self.wrap, text="Select a class assigned to your account.").pack(anchor="w"); return
        if self.kind == "recovery": self._recovery(cid)
        else: self._chat(cid)

    def _recovery(self, cid):
        ctk.CTkLabel(self.wrap, text="Attendance Recovery", font=th.font(20, True), text_color=th.TEXT).pack(anchor="w", pady=(0, 10))
        goal = self.app.db.get("limit_critical", 75)
        for student in self.app.db.students(cid):
            try: summary = recovery.student_summary(self.app.db, student["id"], self.app.db.recovery_goal(student["id"]) or goal)
            except ValueError: continue
            item = summary["overall"]
            pct = "No counted sessions" if item["current"] is None else f"{item['current']:.2f}%"
            if item["classes_needed"] is None: plan = "Insufficient session history for a recovery calculation"
            elif item["classes_needed"] == 0: plan = "At or above target"
            else: plan = f"Attend {item['classes_needed']} consecutive counted classes"
            card = th.card(self.wrap); card.pack(fill="x", pady=4)
            ctk.CTkLabel(card, text=f"{student['name'] or student['code']} ({student['code']}) · {pct}\n{item['attended']} attended · {item['absent']} absent · Target {item['target']:g}% · {plan}",
                         text_color=th.TEXT, justify="left", anchor="w").pack(fill="x", padx=12, pady=9)

    def _chat(self, cid):
        ctk.CTkLabel(self.wrap, text="Chat with Upasthiti", font=th.font(20, True), text_color=th.TEXT).pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(self.wrap, text="Local deterministic helper; it uses only the selected authorized class and does not call an external AI service.", text_color=th.GREY, wraplength=780).pack(anchor="w", pady=4)
        entry = ctk.CTkEntry(self.wrap, placeholder_text="Ask about attendance, absences, or at-risk totals", height=40)
        entry.pack(fill="x", pady=8)
        output = ctk.CTkTextbox(self.wrap, height=210); output.pack(fill="x", pady=4)
        assistant = chat_assistant.LocalAssistant(self.app.db)
        def ask():
            answer = assistant.answer(entry.get(), class_id=cid)
            output.insert("end", f"You: {entry.get()}\nUpasthiti: {answer}\n\n"); output.see("end")
        ctk.CTkButton(self.wrap, text="Ask", command=ask).pack(anchor="w")

