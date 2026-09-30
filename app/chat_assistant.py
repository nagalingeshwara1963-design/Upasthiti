"""Small deterministic, offline Upasthiti helper; it never executes user SQL."""
import re
from . import auth, recovery, stats
from .portal_service import StudentPortalService


class LocalAssistant:
    def __init__(self, db): self.db = db

    def answer(self, question, class_id=None):
        text = str(question or "").strip().casefold()
        if not text: return "Ask about attendance, recovery, subjects, or a review request."
        role = auth.current_role()
        if role not in ("student", "faculty", "admin"): return "Please sign in first."
        if role == "student":
            portal = StudentPortalService(self.db)
            try: summary = portal.summary()
            except (PermissionError, ValueError) as exc: return str(exc)
            overall = summary["overall"]
            if any(k in text for k in ("miss", "safe", "skip")):
                value = overall["safe_to_miss"]
                return "There is not enough recorded attendance to calculate this yet." if value is None else f"Based on recorded attendance and the {overall['target']:g}% target, you can miss {value} more counted classes and remain at or above target."
            if any(k in text for k in ("how many", "reach", "recover", "target", "consecutive")):
                value = overall["classes_needed"]
                return "There is not enough recorded attendance to calculate recovery yet." if value is None else f"Your recorded attendance is {overall['current']:.2f}%. Attend the next {value} counted classes to reach {overall['target']:g}% or higher."
            if "subject" in text:
                return "\n".join(f"{r['subject']}: {r['current']:.2f}%" if r["current"] is not None else f"{r['subject']}: no counted classes yet" for r in summary["subjects"]) or "No subject attendance is recorded yet."
            if "review" in text:
                requests = portal.review_requests()
                return "You have no review requests." if not requests else "Your review requests: " + ", ".join(f"{r['subject']} on {r['date']}: {r['status']}" for r in requests[:5])
            return f"Your recorded attendance is {overall['current']:.2f}% ({overall['attended']} attended, {overall['absent']} absent) against a {overall['target']:g}% target." if overall["current"] is not None else "No counted attendance is recorded yet."
        if class_id is None or not auth.can_access_class(self.db, class_id):
            return "Select a class assigned to your account to ask about class attendance."
        if not any(word in text for word in ("attendance", "absent", "present", "class", "risk", "recovery")):
            return "I can summarize recorded attendance for the selected class."
        try: start, end = stats.range_students(self.db, class_id, "0001-01-01", "9999-12-31")
        except Exception: return "I could not read attendance for that class. Check the class selection and try again."
        if "absent" in text:
            rows = sorted((r for r in start if r["absent"]), key=lambda r: (-r["absent"], r["code"]))
            return "Students with recorded absences: " + ", ".join(f"{r['name'] or r['code']} ({r['absent']})" for r in rows[:10]) if rows else "No absences are recorded for this class."
        at_risk = [r for r in start if r["level"] in ("warn", "critical")]
        return f"The selected class has {len(start)} students and {sum(r['counted'] for r in start)} recorded student-session marks. {len(at_risk)} students are below the configured warning threshold."

