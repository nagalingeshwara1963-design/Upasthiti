"""Low-memory queued email delivery and reusable Upasthiti email templates."""
import json
import queue
import re
import smtplib
import ssl
import tempfile
import threading
import uuid
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from . import stats
from . import auth
from .securestore import protect_secret, unprotect_secret

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_\x60{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
PROVIDERS = {
    "Gmail": ("smtp.gmail.com", 587, "starttls"),
    "Outlook/Microsoft": ("smtp.office365.com", 587, "starttls"),
}


class EmailConfigurationError(RuntimeError):
    pass


class EmailPermanentError(RuntimeError):
    """A delivery failure that cannot be fixed by retrying the unchanged job."""
    pass


def normalize_email(value):
    value = (value or "").strip()
    if not value or len(value) > 254 or "\r" in value or "\n" in value or not EMAIL_RE.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or ".." in local or local.startswith(".") or local.endswith("."):
        raise ValueError("Enter a valid email address.")
    return local + "@" + domain.lower()


def get_email_settings(db):
    cfg = db.get("email_config", {}) or {}
    provider = cfg.get("provider", "Gmail")
    cfg.setdefault("provider", provider)
    cfg.setdefault("auth_mode", "oauth" if provider in ("Gmail", "Outlook/Microsoft") else "smtp")
    cfg["enabled"] = bool(db.get("email_enabled", False))
    cfg["absentee_enabled"] = bool(db.get("email_absentee_enabled", False))
    if cfg.get("provider") == "Gmail" and cfg["auth_mode"] == "oauth":
        try:
            sender_matches = normalize_email(cfg.get("sender", "")).casefold() == normalize_email(cfg.get("google_account", "")).casefold()
        except ValueError:
            sender_matches = False
        cfg["configured"] = bool(sender_matches and cfg.get("client_id") and cfg.get("secret"))
    elif cfg.get("provider") == "Outlook/Microsoft" and cfg["auth_mode"] == "oauth":
        cfg["configured"] = bool(cfg.get("sender") and cfg.get("client_id") and cfg.get("secret"))
    else:
        cfg["configured"] = bool(cfg.get("sender") and cfg.get("host") and cfg.get("secret"))
    return cfg


def save_email_settings(db, *, provider, sender, username, host, port, security, secret, enabled, absentee_enabled,
                        auth_mode="smtp", client_id="", client_secret="", tenant="common"):
    if auth.current_role() != "admin":
        raise PermissionError("Only an administrator can configure the sender account.")
    sender = normalize_email(sender)
    username = (username or sender).strip()
    if not username or len(username) > 254 or any(c in username for c in "\r\n"):
        raise ValueError("Enter a valid SMTP login name.")
    if provider not in ("Gmail", "Outlook/Microsoft", "SMTP / Other"):
        raise ValueError("Choose a supported SMTP provider.")
    host = (host or "").strip()
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("SMTP port must be between 1 and 65535.")
    if security not in ("starttls", "ssl"):
        raise ValueError("Choose STARTTLS or SSL/TLS.")
    previous = db.get("email_config", {}) or {}
    auth_mode = (auth_mode or "smtp").lower()
    if auth_mode not in ("smtp", "oauth"):
        raise ValueError("Choose OAuth or SMTP authentication.")
    oauth_provider = provider in ("Gmail", "Outlook/Microsoft")
    if provider == "Outlook/Microsoft" and auth_mode != "oauth":
        raise ValueError("Microsoft accounts require OAuth in this version.")
    if auth_mode == "smtp" and (not host or any(c.isspace() for c in host) or "\r" in host or "\n" in host):
        raise ValueError("Enter a valid SMTP server name.")
    if auth_mode == "oauth" and not oauth_provider:
        raise ValueError("OAuth is supported for Gmail and Microsoft accounts only.")
    client_id = (client_id or "").strip()
    same_auth = (previous.get("provider") == provider and
                 previous.get("auth_mode", "oauth" if previous.get("provider") in ("Gmail", "Outlook/Microsoft") else "smtp") == auth_mode and
                 (auth_mode != "oauth" or (previous.get("client_id") == client_id and
                                            (provider != "Outlook/Microsoft" or previous.get("tenant", "common") == (tenant or "common")) and
                                            (provider != "Gmail" or previous.get("sender", "").casefold() == sender.casefold()))))
    encrypted = protect_secret(secret) if secret else (previous.get("secret", "") if same_auth else "")
    old_client_secret = previous.get("oauth_client_secret", "") if same_auth else ""
    protected_client_secret = protect_secret(client_secret) if client_secret else old_client_secret
    if auth_mode == "oauth" and not client_id and enabled:
        raise ValueError("Enter the OAuth public-client ID from your provider's app registration.")
    if enabled and not encrypted:
        raise ValueError("Connect the sender account or enter an SMTP credential before enabling email.")
    if enabled and provider == "Gmail" and auth_mode == "oauth":
        try:
            verified_account = normalize_email(previous.get("google_account", "")) if same_auth else ""
        except ValueError:
            verified_account = ""
        if verified_account.casefold() != sender.casefold():
            raise ValueError("Click Connect Gmail and authorize the configured sender account before enabling email.")
    if enabled and auth_mode == "smtp" and not host:
        raise ValueError("Enter the SMTP server before enabling email.")
    if absentee_enabled and not enabled:
        raise ValueError("Enable Email before turning on automatic absentee notifications.")
    if tenant and (any(c.isspace() for c in tenant) or "/" in tenant or "\\" in tenant):
        raise ValueError("Enter a valid Microsoft tenant ID or 'common'.")
    db.put("email_config", {"provider": provider, "sender": sender, "username": username,
                            "host": host, "port": port, "security": security, "secret": encrypted,
                            "auth_mode": auth_mode, "client_id": client_id, "oauth_client_secret": protected_client_secret,
                            "tenant": tenant or "common",
                            "google_account": previous.get("google_account", "") if same_auth else ""})
    db.put("email_enabled", bool(enabled))
    db.put("email_absentee_enabled", bool(absentee_enabled))


def disconnect_email(db):
    if auth.current_role() != "admin":
        raise PermissionError("Only an administrator can remove the sender account.")
    db.put("email_config", {})
    db.put("email_enabled", False)
    db.put("email_absentee_enabled", False)


def absentee_template(student, session, college, percentage):
    subject = f"Attendance Absence Notification - {college or 'Upasthiti'}"
    lines = [f"Dear {student['name'] or student['code']},", f"Student ID: {student['code']}", "",
             "You were marked absent for the following class:"]
    for label, key in (("Date", "date"), ("Subject", "subject"), ("Faculty", "faculty"),
                       ("Class", "class_name"), ("Section", "section"), ("Period", "period")):
        value = session.get(key)
        if value:
            lines.append(f"{label}: {value}")
    if percentage is not None:
        lines.append(f"Your current attendance is {percentage:.2f}%.")
    lines += ["", "If you believe this record is incorrect, please contact the concerned faculty or department.",
              "", "Regards,", college or "Upasthiti", "Upasthiti"]
    return subject, "\n".join(lines)


def student_report_template(student, class_name, start, end, summary, college):
    subject = f"Attendance Report - {student['name'] or student['code']} - {start} to {end}"
    pct = "Not available" if summary["pct"] is None else f"{summary['pct']:.2f}%"
    lines = [f"Dear {student['name'] or student['code']},", f"Student ID: {student['code']}", "",
             "Your attendance summary:", f"Period: {_display_date(start)} to {_display_date(end)}", f"Class: {class_name}",
             f"Classes held: {summary.get('held', summary['total'])}", f"Present: {summary['attended']}",
             f"Absent: {summary['absent']}", f"Attendance: {pct}"]
    if summary.get("subjects"):
        lines.insert(-1, "Subjects: " + ", ".join(summary["subjects"]))
    if summary.get("absent_dates"):
        lines += ["", "Absent dates:"] + [_display_date(d) for d in summary["absent_dates"]]
    lines += ["", "Regards,", college or "Upasthiti", "Upasthiti"]
    return subject, "\n".join(lines)


def _display_date(iso):
    from datetime import date
    return date.fromisoformat(iso).strftime("%d %B %Y")


def administrative_report_template(class_name, start, end, college):
    subject = f"Attendance Report - {class_name} - {start} to {end}"
    body = (f"Attached is the attendance summary for {class_name}, covering {start} to {end}.\n\n"
            f"Regards,\n{college or 'Upasthiti'}\nUpasthiti")
    return subject, body


class SMTPProvider:
    """A synchronous, bounded-time SMTP transport; called only by the worker thread."""
    def send(self, config, to, subject, body, attachment=None):
        if not config.get("configured") or not config.get("enabled"):
            raise EmailConfigurationError("Email sender is not configured and enabled in Settings.")
        message = EmailMessage()
        message["From"] = formataddr(("Upasthiti", config["sender"]))
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        if attachment:
            path, filename = attachment
            data = Path(path).read_bytes()
            message.add_attachment(data, maintype="application",
                                  subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  filename=filename)
        secret = unprotect_secret(config["secret"])
        context = ssl.create_default_context()
        smtp = None
        try:
            if config["security"] == "ssl":
                smtp = smtplib.SMTP_SSL(config["host"], int(config["port"]), timeout=20, context=context)
                smtp.ehlo()
            else:
                smtp = smtplib.SMTP(config["host"], int(config["port"]), timeout=20)
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(config["username"], secret)
            smtp.send_message(message, from_addr=config["sender"], to_addrs=[to])
        finally:
            if smtp is not None:
                try: smtp.quit()
                except Exception: smtp.close()


class EmailProvider:
    """Routes provider API submissions or SMTP submissions behind one transport interface."""
    def __init__(self):
        self.smtp = SMTPProvider()

    def send(self, config, to, subject, body, attachment=None):
        if not config.get("configured") or not config.get("enabled"):
            raise EmailConfigurationError("Email sender is not configured and enabled in Settings.")
        if attachment and Path(attachment[0]).stat().st_size > 2 * 1024 * 1024:
            raise EmailPermanentError("Report attachment exceeds the 2 MiB email attachment limit; export it manually or shorten the date range.")
        if config.get("auth_mode") == "oauth":
            from .oauth_email import send_oauth
            return send_oauth(config, to, subject, body, attachment)
        self.smtp.send(config, to, subject, body, attachment)
        return None


class EmailService:
    """Single daemon worker backed by SQLite delivery records; no work runs in the UI thread."""
    def __init__(self, db, post=None, provider=None, disabled=False):
        self.db, self.post = db, post or (lambda fn: fn())
        self.provider = provider or EmailProvider()
        self.disabled = bool(disabled)
        self._queue = queue.Queue()
        db.recover_email_deliveries()
        self._thread = threading.Thread(target=self._work, name="UpasthitiEmailWorker", daemon=True)
        self._thread.start()
        for row in db.pending_email_deliveries():
            self._submit(row["id"])

    @staticmethod
    def _authorize(*roles):
        if auth.current_role() not in roles:
            raise PermissionError("Your account is not authorized to perform this email action.")

    def _authorize_class(self, class_id):
        if not auth.can_access_class(self.db, class_id):
            raise PermissionError("Your account is not authorized for this class.")

    def _require_sender(self):
        if self.disabled:
            raise EmailConfigurationError("Outbound email is disabled in Demo Mode.")
        cfg = get_email_settings(self.db)
        if not cfg["configured"]:
            raise EmailConfigurationError("Add or connect a sender account in Settings → Email first.")
        if not cfg["enabled"]:
            raise EmailConfigurationError("Enable Email in Settings → Email first.")

    def email_center_students(self, class_id, start, end):
        self._authorize("admin", "faculty")
        self._authorize_class(class_id)
        self._validate_report_range(start, end)
        summaries, _held = stats.range_students(self.db, class_id, start, end)
        ids = [s["id"] for s in summaries]
        if not ids: return []
        marks = ",".join("?" for _ in ids)
        recipient_rows = self.db.q(f"SELECT * FROM student_email_recipients WHERE enabled=1 AND student_id IN ({marks}) ORDER BY student_id,id", ids)
        recipients = {}
        for rec in recipient_rows: recipients.setdefault(rec["student_id"], []).append(rec)
        history_rows = self.db.q(f"""SELECT * FROM (
            SELECT d.*,ROW_NUMBER() OVER(PARTITION BY student_id ORDER BY id DESC) AS rn
            FROM email_deliveries d WHERE class_id=? AND student_id IN ({marks})) WHERE rn<=5 ORDER BY student_id,id DESC""",
            [class_id, *ids])
        histories = {}
        for row in history_rows: histories.setdefault(row["student_id"], []).append(row)
        photos = self.db.q(f"""SELECT e.student_id,e.path FROM enroll_photos e JOIN (
            SELECT student_id,MIN(id) AS id FROM enroll_photos WHERE student_id IN ({marks}) GROUP BY student_id
            ) first ON first.id=e.id""", ids)
        photo_by_student = {r["student_id"]: r["path"] for r in photos}
        result = []
        for student in summaries:
            student["recipients"] = recipients.get(student["id"], [])
            student["history"] = histories.get(student["id"], [])
            student["photo"] = photo_by_student.get(student["id"], "")
            result.append(student)
        return result

    def list_student_recipients(self, student_id):
        self._authorize("admin")
        if not self.db.q("SELECT 1 FROM students WHERE id=? AND active=1", (student_id,)):
            raise ValueError("Student was not found.")
        return self.db.email_recipients(student_id)

    def add_student_recipient(self, student_id, email, label="", enabled=True):
        self._authorize("admin")
        if not self.db.q("SELECT 1 FROM students WHERE id=? AND active=1", (student_id,)):
            raise ValueError("Student was not found.")
        return self.db.add_email_recipient(student_id, email, label, enabled)

    def update_student_recipient(self, student_id, recipient_id, email, label, enabled):
        self._authorize("admin")
        if not self.db.q("SELECT 1 FROM student_email_recipients WHERE id=? AND student_id=?", (recipient_id, student_id)):
            raise ValueError("Recipient does not belong to this student.")
        return self.db.update_email_recipient(recipient_id, email, label, enabled)

    def remove_student_recipient(self, student_id, recipient_id):
        self._authorize("admin")
        if not self.db.q("SELECT 1 FROM student_email_recipients WHERE id=? AND student_id=?", (recipient_id, student_id)):
            raise ValueError("Recipient does not belong to this student.")
        return self.db.remove_email_recipient(recipient_id)

    def preview_student_report(self, class_id, student_id, start, end):
        """Return one student's report only; never accept a class-wide data payload."""
        self._authorize("admin", "faculty")
        self._authorize_class(class_id)
        self._validate_report_range(start, end)
        rows = self.db.q("SELECT id,code,name FROM students WHERE id=? AND class_id=? AND active=1", (student_id, class_id))
        if not rows:
            raise ValueError("The selected student does not belong to the selected class.")
        summary = stats.student_range(self.db, student_id, start, end)
        class_row = self.db.q("SELECT name FROM classes WHERE id=?", (class_id,))
        if not class_row:
            raise ValueError("Select a valid class.")
        subject, body = student_report_template(rows[0], class_row[0]["name"], start, end, summary,
                                               self.db.get("college_name", "") or "Upasthiti")
        return {"student": rows[0], "summary": summary, "recipients": self.db.email_recipients(student_id, True),
                "subject": subject, "body": body}

    def send_all_summary(self, class_id, start, end):
        self._authorize("admin", "faculty")
        self._authorize_class(class_id)
        self._validate_report_range(start, end)
        students = self.email_center_students(class_id, start, end)
        active = [s for s in students if s["recipients"]]
        missing = [s for s in students if not s["recipients"]]
        all_recipients = {s["id"]: self.db.email_recipients(s["id"]) for s in students}
        succeeded = self.db.q("SELECT COUNT(*) AS n FROM email_deliveries WHERE class_id=? AND kind='student_report' AND report_from=? AND report_to=? AND status='sent'",
                              (class_id, start, end))[0]["n"]
        return {"students": len(students), "with_recipients": len(active), "without_recipients": len(missing),
                "recipient_addresses": sum(len(s["recipients"]) for s in active),
                "disabled_recipients": sum(1 for rows in all_recipients.values() for r in rows if not r["enabled"]),
                "previous_successes": succeeded,
                "missing_codes": [s["code"] for s in missing]}

    def _submit(self, delivery_id):
        # Duplicate queue entries are harmless: the worker checks persisted job state.
        self._queue.put(delivery_id)

    def enqueue_absentees(self, session_id):
        self._authorize("admin", "faculty")
        if self.disabled: return {"queued": 0, "disabled": True, "delivery_ids": []}
        cfg = get_email_settings(self.db)
        if not cfg["enabled"] or not cfg["absentee_enabled"]:
            return {"queued": 0, "disabled": True, "delivery_ids": []}
        session = self.db.session(session_id)
        if not session:
            raise ValueError("Saved attendance session was not found.")
        self._authorize_class(session["class_id"])
        absent = [r for r in self.db.session_rows(session_id) if r["status"] == "A"]
        made = []
        for row in absent:
            recipients = self.db.email_recipients(row["student_id"], enabled_only=True)
            if not recipients:
                d = self.db.create_email_delivery({
                    "kind": "absence", "status": "no_recipient",
                    "dedupe_key": f"absence:{session_id}:{row['student_id']}:none",
                    "student_id": row["student_id"], "student_code": row["code"],
                    "student_name": row["name"] or "", "session_id": session_id,
                    "class_id": session["class_id"]})
                made.append(d["id"])
            for recipient in recipients:
                d = self.db.create_email_delivery({
                    "kind": "absence", "status": "pending",
                    "dedupe_key": f"absence:{session_id}:{row['student_id']}:{recipient['email'].casefold()}",
                    "recipient": recipient["email"], "recipient_label": recipient["label"],
                    "student_id": row["student_id"], "student_code": row["code"],
                    "student_name": row["name"] or "", "session_id": session_id,
                    "class_id": session["class_id"]})
                made.append(d["id"])
                if d["status"] == "pending": self._submit(d["id"])
        return {"queued": sum(1 for i in made if self.db.email_delivery(i)["status"] in ("pending", "sending")),
                "disabled": False, "delivery_ids": made}

    def enqueue_student_reports(self, class_id, student_ids, start, end, campaign=None):
        self._authorize("admin", "faculty")
        self._authorize_class(class_id)
        self._require_sender()
        self._validate_report_range(start, end)
        campaign = campaign or uuid.uuid4().hex
        made = []
        for student_id in student_ids:
            rows = self.db.q("SELECT id,code,name FROM students WHERE id=? AND class_id=? AND active=1", (student_id, class_id))
            if not rows: continue
            student = rows[0]
            recipients = self.db.email_recipients(student_id, enabled_only=True)
            if not recipients:
                d = self.db.create_email_delivery({
                    "kind": "student_report", "status": "no_recipient",
                    "dedupe_key": f"report:{campaign}:student:{student_id}:none",
                    "student_id": student_id, "student_code": student["code"],
                    "student_name": student["name"] or "", "class_id": class_id,
                    "report_from": start, "report_to": end,
                    "context_json": json.dumps({"student_id": student_id})})
                made.append(d["id"])
            for recipient in recipients:
                d = self.db.create_email_delivery({
                    "kind": "student_report", "status": "pending",
                    "dedupe_key": f"report:{campaign}:student:{student_id}:{recipient['email'].casefold()}",
                    "recipient": recipient["email"], "recipient_label": recipient["label"],
                    "student_id": student_id, "student_code": student["code"],
                    "student_name": student["name"] or "", "class_id": class_id,
                    "report_from": start, "report_to": end,
                    "context_json": json.dumps({"student_id": student_id})})
                made.append(d["id"])
                if d["status"] == "pending": self._submit(d["id"])
        return made

    def enqueue_admin_report(self, class_id, start, end, recipients, campaign=None):
        self._authorize("admin", "faculty")
        self._authorize_class(class_id)
        self._require_sender()
        self._validate_report_range(start, end)
        campaign = campaign or uuid.uuid4().hex
        classes = self.db.q("SELECT name FROM classes WHERE id=?", (class_id,))
        if not classes: raise ValueError("Select a valid class.")
        made = []
        for address in recipients:
            address = normalize_email(address)
            d = self.db.create_email_delivery({
                "kind": "admin_report", "status": "pending",
                "dedupe_key": f"admin-report:{campaign}:{class_id}:{address.casefold()}",
                "recipient": address, "class_id": class_id, "report_from": start, "report_to": end,
                "context_json": json.dumps({"class_name": classes[0]["name"]})})
            made.append(d["id"])
            if d["status"] == "pending": self._submit(d["id"])
        return made

    def send_test_email(self, recipient):
        self._authorize("admin")
        if self.disabled: raise EmailConfigurationError("Outbound email is disabled in Demo Mode.")
        cfg = get_email_settings(self.db)
        if not cfg["configured"]:
            raise EmailConfigurationError("Add or connect a sender account in Settings → Email first.")
        recipient = normalize_email(recipient)
        d = self.db.create_email_delivery({"kind": "test", "status": "pending",
                                           "dedupe_key": f"test:{uuid.uuid4().hex}", "recipient": recipient})
        self._submit(d["id"])
        return d["id"]

    def connect_oauth(self, provider, client_id, client_secret="", tenant="common", progress=None):
        """Run provider authorization in a caller-owned background thread and persist refresh token."""
        self._authorize("admin")
        if self.disabled: raise EmailConfigurationError("Email account changes are disabled in Demo Mode.")
        from .oauth_email import google_connect, microsoft_connect
        if provider == "Gmail":
            cfg = self.db.get("email_config", {}) or {}
            expected = normalize_email(cfg.get("sender", ""))
            identity = google_connect(client_id, client_secret, progress)
            account = normalize_email(identity["email"])
            if account.casefold() != expected.casefold():
                raise EmailConfigurationError(f"Google authorized {account}, but the configured sender is {expected}. No new token was saved. Change the sender or reconnect with the matching Gmail account.")
            refresh = identity["refresh_token"]
        elif provider == "Outlook/Microsoft":
            refresh = microsoft_connect(client_id, tenant, progress)
            account = ""
        else:
            raise EmailConfigurationError("OAuth is supported for Gmail and Microsoft accounts only.")
        cfg = self.db.get("email_config", {}) or {}
        if cfg.get("provider") != provider or cfg.get("client_id") != client_id.strip() or cfg.get("auth_mode") != "oauth":
            raise EmailConfigurationError("Email provider settings changed while authorization was in progress; connect again.")
        cfg["secret"] = protect_secret(refresh)
        if provider == "Gmail": cfg["google_account"] = account
        if client_secret:
            cfg["oauth_client_secret"] = protect_secret(client_secret)
        self.db.put("email_config", cfg)
        return account if provider == "Gmail" else True

    def retry_failed(self, delivery_ids=None):
        self._authorize("admin", "faculty")
        if self.disabled: raise EmailConfigurationError("Outbound email is disabled in Demo Mode.")
        rows = self.db.retryable_email_deliveries(delivery_ids)
        if auth.current_role() == "faculty":
            assigned = set(self.db.faculty_class_ids(auth.current_user()))
            rows = [r for r in rows if r.get("class_id") in assigned]
        for row in rows:
            self.db.update_email_delivery(row["id"], "pending", failure="")
            self._submit(row["id"])
        return [r["id"] for r in rows]

    def create_schedule(self, class_id, report_from, report_to, send_on):
        self._authorize("admin")
        if self.disabled: raise EmailConfigurationError("Email schedules are disabled in Demo Mode.")
        self._authorize_class(class_id)
        self._require_sender()
        self._validate_schedule_dates(report_from, report_to, send_on)
        if not self.db.q("SELECT 1 FROM classes WHERE id=?", (class_id,)):
            raise ValueError("Select a valid class.")
        return self.db.add_email_schedule(class_id, report_from, report_to, send_on)

    def update_schedule(self, schedule_id, class_id, report_from, report_to, send_on, enabled):
        self._authorize("admin")
        if self.disabled: raise EmailConfigurationError("Email schedules are disabled in Demo Mode.")
        self._authorize_class(class_id)
        if enabled: self._require_sender()
        self._validate_schedule_dates(report_from, report_to, send_on)
        if not self.db.q("SELECT 1 FROM classes WHERE id=?", (class_id,)):
            raise ValueError("Select a valid class.")
        return self.db.update_email_schedule(schedule_id, class_id, report_from, report_to, send_on, enabled)

    def set_schedule_enabled(self, schedule_id, enabled):
        self._authorize("admin")
        return self.db.set_email_schedule_enabled(schedule_id, enabled)

    def delete_schedule(self, schedule_id):
        self._authorize("admin")
        return self.db.delete_email_schedule(schedule_id)

    @staticmethod
    def _validate_report_range(start, end):
        from datetime import date
        try:
            a, b = date.fromisoformat(start), date.fromisoformat(end)
        except (TypeError, ValueError) as exc:
            raise ValueError("Report dates must be valid YYYY-MM-DD dates.") from exc
        if a > b:
            raise ValueError("Report From must be on or before To.")

    @staticmethod
    def _validate_schedule_dates(report_from, report_to, send_on):
        from datetime import date
        try:
            start, end, due = (date.fromisoformat(v) for v in (report_from, report_to, send_on))
        except (TypeError, ValueError) as exc:
            raise ValueError("Schedule dates must be valid YYYY-MM-DD dates.") from exc
        if start > end:
            raise ValueError("Report From must be on or before To.")
        if due < date.today():
            raise ValueError("Send On must be today or a future date.")

    def process_due_schedules(self, today=None):
        """Submit enabled schedules when the desktop app is running; repeated polling is idempotent."""
        from datetime import date
        if self.disabled or auth.current_role() != "admin":
            return []
        cfg = get_email_settings(self.db)
        if not cfg["configured"] or not cfg["enabled"]:
            return []
        today = today or date.today().isoformat()
        made = []
        for schedule in self.db.due_email_schedules(today):
            campaign = f"schedule:{schedule['id']}:{schedule['send_on']}:{schedule['report_from']}:{schedule['report_to']}"
            made.extend(self.enqueue_student_reports(schedule["class_id"],
                         [s["id"] for s in self.db.students(schedule["class_id"])],
                         schedule["report_from"], schedule["report_to"], campaign=campaign))
            self.db.mark_email_schedule_run(schedule["id"], schedule["send_on"])
        return made

    def _render(self, job):
        college = self.db.get("college_name", "") or "Upasthiti"
        if job["kind"] == "test":
            return "Upasthiti test email", "This test message confirms that the configured Upasthiti email sender can submit mail.", None
        if job["kind"] == "absence":
            settings = get_email_settings(self.db)
            if not settings["enabled"] or not settings["absentee_enabled"]:
                raise EmailConfigurationError("Automatic absence notifications are disabled.")
            students = self.db.q("SELECT id,code,name FROM students WHERE id=? AND active=1", (job["student_id"],))
            live = self.db.q("SELECT 1 FROM student_email_recipients WHERE student_id=? AND email=? COLLATE NOCASE AND enabled=1",
                             (job["student_id"], job["recipient"]))
            if not students: raise EmailConfigurationError("Student was archived before notification delivery.")
            if not live: raise EmailConfigurationError("Recipient was disabled or removed before delivery.")
            session = self.db.session(job["session_id"])
            row = next((r for r in self.db.session_rows(job["session_id"]) if r["student_id"] == job["student_id"]), None)
            if not session or not row or row["status"] != "A":
                raise EmailConfigurationError("Attendance is no longer marked absent; notification cancelled.")
            section = self.db.q("SELECT section FROM classes WHERE id=?", (session["class_id"],))
            session["section"] = section[0]["section"] if section and section[0]["section"] else ""
            history = self.db.q("SELECT status FROM attendance WHERE student_id=?", (job["student_id"],))
            summary = stats.counts([r["status"] for r in history])
            subject, body = absentee_template(students[0], session, college, summary["pct"])
            return subject, body, None
        if job["kind"] == "student_report":
            student = self.db.q("SELECT id,code,name FROM students WHERE id=? AND class_id=? AND active=1",
                                (job["student_id"], job["class_id"]))
            live = self.db.q("SELECT 1 FROM student_email_recipients WHERE student_id=? AND email=? COLLATE NOCASE AND enabled=1",
                             (job["student_id"], job["recipient"]))
            if not student or not live: raise EmailConfigurationError("Student or recipient is no longer available.")
            summary = stats.student_range(self.db, job["student_id"], job["report_from"], job["report_to"])
            class_name = self.db.q("SELECT name FROM classes WHERE id=?", (job["class_id"],))[0]["name"]
            subject, body = student_report_template(student[0], class_name, job["report_from"], job["report_to"], summary, college)
            return subject, body, None
        if job["kind"] == "admin_report":
            from . import reports
            class_name = json.loads(job["context_json"]).get("class_name", "Class")
            temp = tempfile.NamedTemporaryFile(prefix="upasthiti-email-report-", suffix=".xlsx", delete=False)
            temp.close()
            try:
                reports.range_xlsx(self.db, job["class_id"], job["report_from"], job["report_to"], temp.name)
            except Exception:
                try: Path(temp.name).unlink(missing_ok=True)
                except OSError: pass
                raise
            subject, body = administrative_report_template(class_name, job["report_from"], job["report_to"], college)
            return subject, body, (temp.name, f"attendance_{job['report_from']}_to_{job['report_to']}.xlsx")
        raise EmailConfigurationError("Unsupported email job type.")

    def _work(self):
        while True:
            delivery_id = self._queue.get()
            if delivery_id is None:
                self._queue.task_done()
                return
            try:
                job = self.db.email_delivery(delivery_id)
                if not job or job["status"] != "pending": continue
                if self.disabled:
                    self.db.update_email_delivery(delivery_id, "disabled", "Outbound email is disabled in Demo Mode.", permanent=True)
                    continue
                self.db.update_email_delivery(delivery_id, "sending", failure="", attempt=True)
                temp_attachment = None
                try:
                    cfg = get_email_settings(self.db)
                    if job["kind"] == "test" and cfg["configured"]:
                        cfg["enabled"] = True
                    subject, body, attachment = self._render(job)
                    temp_attachment = attachment[0] if attachment else None
                    rotated_refresh = self.provider.send(cfg, job["recipient"], subject, body, attachment)
                    self.db.update_email_delivery(delivery_id, "sent")
                    if rotated_refresh:
                        try:
                            latest = self.db.get("email_config", {}) or {}
                            latest["secret"] = protect_secret(rotated_refresh)
                            self.db.put("email_config", latest)
                        except Exception:
                            pass
                except Exception as exc:
                    code = getattr(exc, "smtp_code", None)
                    permanent = isinstance(exc, EmailPermanentError) or (
                        isinstance(exc, smtplib.SMTPRecipientsRefused) and bool(exc.recipients) and all(
                            isinstance(value[0], int) and 500 <= value[0] < 600 for value in exc.recipients.values())) or (
                        getattr(exc, "code", None) in (400, 404, 422) or getattr(exc, "smtp_code", None) in (550, 551, 553))
                    reason = str(exc).replace("\r", " ").replace("\n", " ")[:500] or type(exc).__name__
                    if isinstance(exc, EmailConfigurationError) and ("disabled or removed" in str(exc) or "no longer available" in str(exc) or "Student was deleted" in str(exc)):
                        self.db.update_email_delivery(delivery_id, "disabled", reason, permanent=True)
                    elif isinstance(exc, EmailConfigurationError) and "notifications are disabled" in str(exc):
                        self.db.update_email_delivery(delivery_id, "disabled", reason, permanent=True)
                    elif isinstance(exc, EmailConfigurationError) and "no longer marked absent" in str(exc):
                        self.db.update_email_delivery(delivery_id, "cancelled", reason, permanent=True)
                    else:
                        self.db.update_email_delivery(delivery_id, "failed", reason, permanent=permanent)
                finally:
                    if temp_attachment:
                        try: Path(temp_attachment).unlink(missing_ok=True)
                        except OSError: pass
            except Exception:
                # A corrupt transient job must not terminate the single delivery worker.
                try: self.db.update_email_delivery(delivery_id, "failed", "Email worker error; inspect application diagnostics.")
                except Exception: pass
            finally:
                self._queue.task_done()

    def wait_idle(self, timeout=10):
        """Test helper; never call from the UI thread."""
        import time
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def shutdown(self, timeout=1):
        """Stop a test-owned worker; application shutdown may leave the daemon to exit."""
        self._queue.put(None)
        self._thread.join(timeout)
