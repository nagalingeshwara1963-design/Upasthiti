"""Attendance review request policy and role-scoped workflow."""
from datetime import date, datetime, timezone
import time
from . import auth

REASONS = {"I was present", "Wrong attendance status", "Recognition mismatch",
           "Wrong class/subject", "Other"}
ACTIVE = ("Pending", "Under Review", "Escalated")


def _sent_within(row, now, days=10):
    return row["status"] == "sent" and now - float(row["updated_at"]) <= days * 86400 and float(row["updated_at"]) <= now


class ReviewRequestService:
    def __init__(self, db): self.db = db

    def submit(self, session_id, reason, explanation="", now=None):
        if auth.current_role() != "student" or auth.student_must_change_password():
            raise PermissionError("Student login is required.")
        sid = auth.current_student_id()
        if reason not in REASONS: raise ValueError("Choose a listed review reason.")
        explanation = str(explanation or "").strip()
        if len(explanation) > 1000: raise ValueError("Explanation must be 1,000 characters or fewer.")
        rows = self.db.q("""SELECT a.id AS attendance_id,a.status,s.id AS session_id,s.class_id,s.date
                           FROM attendance a JOIN sessions s ON s.id=a.session_id
                           WHERE s.id=? AND a.student_id=?""", (session_id, sid))
        if not rows: raise PermissionError("That attendance entry is not available to this student.")
        attendance = rows[0]
        try: session_day = date.fromisoformat(attendance["date"])
        except (ValueError, TypeError): raise ValueError("The attendance date is invalid; contact an administrator.")
        now = time.time() if now is None else float(now)
        age_days = (datetime.fromtimestamp(now).date() - session_day).days
        within_edit_period = 0 <= age_days <= 30
        if not within_edit_period:
            notice = self.db.q("""SELECT updated_at,status FROM email_deliveries
                WHERE kind='absence' AND student_id=? AND session_id=? ORDER BY updated_at DESC""", (sid, session_id))
            report = self.db.q("""SELECT updated_at,status FROM email_deliveries
                WHERE kind='student_report' AND student_id=? AND status='sent'
                AND report_from<=? AND report_to>=? ORDER BY updated_at DESC""",
                (sid, attendance["date"], attendance["date"]))
            covered = any(_sent_within(r, now) for r in notice + report)
            if not covered or age_days < 0:
                raise PermissionError("The review window has expired. Requests are accepted for 30 days after class, or for 10 days after a successfully sent notice/report covering that date.")
        created, is_new = self.db.create_review_request(sid, session_id, attendance["attendance_id"],
            attendance["status"], reason, explanation, escalated=not within_edit_period)
        return created, is_new

    def list_for_current_user(self, statuses=None):
        role = auth.current_role()
        if role == "student":
            if auth.student_must_change_password(): raise PermissionError("Change the initial password first.")
            return self.db.list_review_requests(student_id=auth.current_student_id(), statuses=statuses)
        if role == "admin": return self.db.list_review_requests(statuses=statuses)
        if role == "faculty":
            return self.db.list_review_requests(class_ids=self.db.faculty_class_ids(auth.current_user()), statuses=statuses)
        raise PermissionError("Sign in to access review requests.")

    def transition(self, request_id, action, reason="", new_attendance_status=None):
        role, actor = auth.current_role(), auth.current_user()
        if role not in ("admin", "faculty"): raise PermissionError("Only authorized staff may review requests.")
        matches = self.db.list_review_requests()
        row = next((r for r in matches if r["id"] == int(request_id)), None)
        if not row: raise ValueError("Review request not found.")
        if role == "faculty":
            if row["class_id"] not in self.db.faculty_class_ids(actor): raise PermissionError("This class is not assigned to your account.")
            if row["status"] == "Escalated": raise PermissionError("Only an administrator may resolve an escalated request.")
            try: age = (date.today() - date.fromisoformat(row["date"])).days
            except ValueError: raise ValueError("The attendance date is invalid.")
            if age > 30 and action not in ("escalate",): raise PermissionError("The faculty edit period has expired; escalate this request to an administrator.")
        status_map = {"start": "Under Review", "keep": "Resolved — Kept", "dismiss": "Dismissed", "escalate": "Escalated"}
        if action == "change":
            if new_attendance_status not in {"P", "A", "L", "E", "OD"}: raise ValueError("Choose a valid attendance status.")
            target = "Resolved — Changed"
        elif action in status_map: target = status_map[action]
        else: raise ValueError("Unknown review action.")
        return self.db.transition_review_request(request_id, target, f"{role}:{actor}", reason, new_attendance_status)

