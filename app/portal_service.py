"""Authenticated, student-scoped access to portal data."""
from . import auth, recovery


class StudentPortalService:
    """Student operations always derive the identity from the active session."""

    def __init__(self, db):
        self.db = db

    def _student_id(self):
        if auth.current_role() != "student" or auth.student_must_change_password():
            raise PermissionError("Complete student sign-in before opening the portal.")
        sid = auth.current_student_id()
        if sid is None or not self.db.q("SELECT 1 FROM students WHERE id=? AND active=1", (sid,)):
            auth.logout()
            raise PermissionError("Student account is no longer available.")
        return sid

    def summary(self):
        sid = self._student_id()
        target = self.db.recovery_goal(sid)
        return recovery.student_summary(self.db, sid, target)

    def history(self, start=None, end=None, subject=None, status=None):
        sid = self._student_id()
        from datetime import date
        try:
            if start: date.fromisoformat(start)
            if end: date.fromisoformat(end)
        except (TypeError, ValueError) as exc: raise ValueError("Dates must use YYYY-MM-DD format.") from exc
        if start and end and start > end: raise ValueError("Start date must be on or before end date.")
        sql = """SELECT a.id AS attendance_id,a.status,a.confidence,a.dist,a.edited,
                 ses.id AS session_id,ses.date,ses.time,ses.subject,ses.period
                 FROM attendance a JOIN sessions ses ON ses.id=a.session_id
                 WHERE a.student_id=?"""
        args = [sid]
        if start:
            sql += " AND ses.date>=?"; args.append(start)
        if end:
            sql += " AND ses.date<=?"; args.append(end)
        if subject:
            sql += " AND ses.subject=?"; args.append(subject)
        if status:
            if status not in {"P", "A", "L", "E", "OD"}: raise ValueError("Invalid attendance status.")
            sql += " AND a.status=?"; args.append(status)
        return self.db.q(sql + " ORDER BY ses.date DESC,ses.time DESC,ses.id DESC", args)

    def report_summary(self, start, end):
        sid = self._student_id()
        from datetime import date
        try:
            start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter valid report dates in YYYY-MM-DD format.") from exc
        if start_day > end_day: raise ValueError("The report start date must be on or before its end date.")
        from . import stats
        result = stats.student_range(self.db, sid, start, end)
        result["records"] = self.history(start=start, end=end)
        return result

    def notifications(self, limit=20):
        sid = self._student_id()
        # Do not expose recipients, delivery context, provider failures, or other students.
        rows = self.db.q("""SELECT id,kind,status,session_id,report_from,report_to,updated_at
                          FROM email_deliveries WHERE student_id=? AND status='sent'
                          ORDER BY updated_at DESC,id DESC LIMIT ?""", (sid, max(1, min(int(limit), 100))))
        reviews = self.db.list_review_requests(student_id=sid)
        items = [{"type": "email", **r} for r in rows]
        items += [{"type": "review", "id": r["id"], "status": r["status"],
                   "date": r["date"], "subject": r["subject"], "updated_at": r["updated_at"]}
                  for r in reviews]
        return sorted(items, key=lambda x: x.get("updated_at", 0), reverse=True)[:limit]

    def review_requests(self):
        return self.db.list_review_requests(student_id=self._student_id())

    def set_goal(self, target):
        sid = self._student_id()
        self.db.set_recovery_goal(sid, target)
        return self.summary()
