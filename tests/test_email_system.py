"""Email and date-range tests; all databases are temporary and transports are mocked."""
import json
import base64
import io
import urllib.error
import urllib.parse
import urllib.request
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import stats
from app import auth
from app.db import DB
from app.email_service import EmailService, normalize_email, save_email_settings, get_email_settings
from app.securestore import unprotect_secret
from app.ui.email_reports import parse_report_range


class FakeProvider:
    def __init__(self, failures=0):
        self.failures = failures
        self.sent = []

    def send(self, config, to, subject, body, attachment=None):
        if self.failures:
            self.failures -= 1
            raise OSError("temporary simulated network failure")
        self.sent.append((to, subject, body, attachment))


class EmailDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="upasthiti-email-test-")
        self.path = Path(self.temp.name) / "test.db"
        self.ensure_patch = patch("app.db.config.ensure_dirs")
        self.ensure_patch.start()
        self.db = DB(self.path)
        auth.set_password(self.db, "admin", "admin", "temporary-test-password")
        auth.login(self.db, "admin", "temporary-test-password")
        self.class_id = self.db.add_class("Class A", college="Example College", section="A")
        self.alice = self.db.save_student(self.class_id, "A1", "Alice Example", [])
        self.bob = self.db.save_student(self.class_id, "B1", "Bob Example", [])

    def tearDown(self):
        self.db.con.close()
        auth.logout()
        self.ensure_patch.stop()
        self.temp.cleanup()

    def session(self, statuses, date="2026-09-01"):
        records = []
        for student, status in statuses:
            records.append({"student_id": student, "status": status, "confidence": 0, "flags": []})
        return self.db.save_session(self.class_id, {"date": date, "time": "09:00", "faculty": "Dr. Test",
                                                    "subject": "Computing", "period": "1", "mode": "fast"}, records)

    def enable_mail(self):
        self.db.put("email_config", {"provider": "SMTP / Other", "sender": "attendance@example.edu",
                                      "username": "attendance@example.edu", "host": "smtp.example.edu",
                                      "port": 587, "security": "starttls", "secret": "mock-protected"})
        self.db.put("email_enabled", True)
        self.db.put("email_absentee_enabled", True)

    def test_email_normalization_and_validation(self):
        self.assertEqual(normalize_email("  Person+tag@Example.EDU  "), "Person+tag@example.edu")
        for bad in ("", "missing-at.example", "a..b@example.edu", "a@example", "a@example.edu\nBcc:x@y.edu"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_email(bad)

    def test_report_date_range_validation_and_editable_values(self):
        self.assertEqual(parse_report_range("05-09-2026", "28-09-2026"), ("2026-09-05", "2026-09-28"))
        with self.assertRaises(ValueError): parse_report_range("31-02-2026", "01-03-2026")
        with self.assertRaises(ValueError): parse_report_range("02-10-2026", "01-10-2026")

    def test_multiple_recipients_edit_disable_remove_and_duplicate(self):
        a = self.db.add_email_recipient(self.alice, "alice@example.edu", "Student")
        b = self.db.add_email_recipient(self.alice, "parent@example.edu", "Parent")
        self.assertEqual(len(self.db.email_recipients(self.alice)), 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.add_email_recipient(self.alice, "ALICE@example.edu", "Duplicate")
        self.db.update_email_recipient(b, "guardian@example.edu", "Guardian", False)
        self.assertEqual([r["email"] for r in self.db.email_recipients(self.alice, True)], ["alice@example.edu"])
        self.assertTrue(self.db.remove_email_recipient(a))
        self.assertEqual(len(self.db.email_recipients(self.alice)), 1)
        self.db.delete_student(self.class_id, "A1")
        self.assertEqual(self.db.email_recipients(self.alice), [])

    def test_enrollment_can_save_multiple_optional_recipients_and_legacy_students_remain_valid(self):
        sid = self.db.save_student(self.class_id, "NEW1", "New Student", [], email_recipients=[
            {"email": "new1@example.edu", "label": "Student"},
            {"email": "parent@example.edu", "label": "Parent"}])
        self.assertEqual([r["label"] for r in self.db.email_recipients(sid)], ["Student", "Parent"])
        self.assertEqual(self.db.email_recipients(self.bob), [])

    def test_disconnecting_sender_preserves_recipients_and_attendance(self):
        from app.email_service import disconnect_email
        self.enable_mail(); self.db.add_email_recipient(self.alice, "alice@example.edu")
        sid = self.session([(self.alice, "A")])
        disconnect_email(self.db)
        self.assertEqual(self.db.session_rows(sid)[0]["status"], "A")
        self.assertEqual(self.db.email_recipients(self.alice)[0]["email"], "alice@example.edu")
        self.assertFalse(get_email_settings(self.db)["enabled"])

    def test_additive_migration_preserves_existing_student_and_attendance(self):
        legacy = Path(self.temp.name) / "legacy.db"
        raw = sqlite3.connect(legacy)
        raw.executescript("""
          CREATE TABLE students(id INTEGER PRIMARY KEY, class_id INTEGER, code TEXT, name TEXT);
          CREATE TABLE attendance(id INTEGER PRIMARY KEY, session_id INTEGER, student_id INTEGER, status TEXT);
          INSERT INTO students VALUES(8,3,'OLD8','Old Student');
          INSERT INTO attendance VALUES(11,5,8,'A');
        """)
        raw.commit(); raw.close()
        db = DB(legacy)
        try:
            self.assertEqual(db.q("SELECT code FROM students WHERE id=8")[0]["code"], "OLD8")
            self.assertEqual(db.q("SELECT status FROM attendance WHERE id=11")[0]["status"], "A")
            self.assertIn("auto_status", [r["name"] for r in db.q("PRAGMA table_info(attendance)")])
            self.assertEqual(len(db.q("SELECT name FROM sqlite_master WHERE type='table' AND name='student_email_recipients'")), 1)
        finally:
            db.con.close()

    def test_absence_jobs_only_include_final_absent_and_are_idempotent(self):
        self.enable_mail()
        self.db.add_email_recipient(self.alice, "alice@example.edu", "Student")
        self.db.add_email_recipient(self.alice, "parent@example.edu", "Parent")
        no_email = self.db.save_student(self.class_id, "C1", "No Address", [])
        sid = self.session([(self.alice, "A"), (self.bob, "P"), (no_email, "A")])
        provider = FakeProvider()
        service = EmailService(self.db, provider=provider)
        try:
            service.enqueue_absentees(sid)
            self.assertTrue(service.wait_idle(3))
            service.enqueue_absentees(sid)
            self.assertTrue(service.wait_idle(3))
            rows = self.db.list_email_deliveries(20, session_id=sid)
            self.assertEqual(len(rows), 3)
            self.assertEqual(sum(r["status"] == "sent" for r in rows), 2)
            self.assertEqual(sum(r["status"] == "no_recipient" for r in rows), 1)
            self.assertEqual(len(provider.sent), 2)
            self.assertTrue(all("Bob Example" not in sent[2] and "No Address" not in sent[2] for sent in provider.sent))
            self.assertTrue(all("Alice Example" in sent[2] for sent in provider.sent))
        finally:
            service.shutdown()

    def test_notifications_disabled_creates_no_jobs(self):
        self.enable_mail(); self.db.put("email_absentee_enabled", False)
        sid = self.session([(self.alice, "A")])
        service = EmailService(self.db, provider=FakeProvider())
        try:
            result = service.enqueue_absentees(sid)
            self.assertTrue(result["disabled"])
            self.assertEqual(self.db.list_email_deliveries(session_id=sid), [])
        finally:
            service.shutdown()

    def test_failed_send_does_not_undo_attendance_and_retry_never_resends_success(self):
        self.enable_mail(); self.db.add_email_recipient(self.alice, "alice@example.edu")
        sid = self.session([(self.alice, "A")])
        provider = FakeProvider(failures=1)
        service = EmailService(self.db, provider=provider)
        try:
            service.enqueue_absentees(sid); self.assertTrue(service.wait_idle(3))
            row = self.db.list_email_deliveries(session_id=sid)[0]
            self.assertEqual(row["status"], "failed")
            self.assertEqual(self.db.session_rows(sid)[0]["status"], "A")
            self.assertEqual(service.retry_failed([row["id"]]), [row["id"]])
            self.assertTrue(service.wait_idle(3))
            self.assertEqual(self.db.email_delivery(row["id"])["status"], "sent")
            self.assertEqual(self.db.email_delivery(row["id"])["attempts"], 2)
            self.assertEqual(service.retry_failed(), [])
            self.assertEqual(len(provider.sent), 1)
        finally:
            service.shutdown()

    def test_disabled_or_removed_recipient_is_not_sent_after_queue(self):
        import threading
        self.enable_mail(); rid = self.db.add_email_recipient(self.alice, "alice@example.edu")
        sid = self.session([(self.alice, "A")])
        started, release = threading.Event(), threading.Event()
        class BlockingProvider(FakeProvider):
            def send(inner, config, to, subject, body, attachment=None):
                if to == "block@example.edu":
                    started.set(); release.wait(3)
                return super(BlockingProvider, inner).send(config, to, subject, body, attachment)
        provider = BlockingProvider()
        service = EmailService(self.db, provider=provider)
        try:
            blocker = self.db.create_email_delivery({"kind": "test", "status": "pending",
                "dedupe_key": "blocker", "recipient": "block@example.edu"})
            service._submit(blocker["id"])
            self.assertTrue(started.wait(2))
            service.enqueue_absentees(sid)
            self.db.remove_email_recipient(rid)
            release.set()
            self.assertTrue(service.wait_idle(3))
            self.assertEqual([x[0] for x in provider.sent], ["block@example.edu"])
            row = self.db.list_email_deliveries(session_id=sid)[0]
            self.assertEqual(row["status"], "disabled")
        finally:
            release.set()
            service.shutdown()

    def test_manual_student_report_is_scoped_to_selected_student(self):
        self.enable_mail()
        self.db.add_email_recipient(self.alice, "alice@example.edu")
        self.db.add_email_recipient(self.bob, "bob@example.edu")
        self.session([(self.alice, "P"), (self.bob, "A")], "2026-09-02")
        provider = FakeProvider(); service = EmailService(self.db, provider=provider)
        try:
            self.assertEqual(self.db.list_email_deliveries(), [])  # reports are opt-in/manual
            jobs = service.enqueue_student_reports(self.class_id, [self.alice], "2026-09-01", "2026-09-30", campaign="manual-test")
            self.assertEqual(len(jobs), 1); self.assertTrue(service.wait_idle(3))
            self.assertEqual(len(provider.sent), 1)
            self.assertEqual(provider.sent[0][0], "alice@example.edu")
            self.assertIn("Alice Example", provider.sent[0][2])
            self.assertNotIn("Bob Example", provider.sent[0][2])
            self.assertNotIn("bob@example.edu", provider.sent[0][2])
        finally:
            service.shutdown()

    def test_personalized_preview_has_only_students_range_dates_and_subjects(self):
        self.session([(self.alice, "A"), (self.bob, "P")], "2026-09-03")
        service = EmailService(self.db, provider=FakeProvider())
        try:
            preview = service.preview_student_report(self.class_id, self.alice, "2026-09-01", "2026-09-30")
            self.assertEqual(preview["summary"]["absent_dates"], ["2026-09-03"])
            self.assertIn("03 September 2026", preview["body"])
            self.assertIn("Computing", preview["body"])
            self.assertIn("Alice Example", preview["body"])
            self.assertNotIn("Bob Example", preview["body"])
            self.assertNotIn("bob@example.edu", preview["body"])
        finally:
            service.shutdown()

    def test_preview_service_rejects_cross_class_student_and_unauthorized_role(self):
        other_class = self.db.add_class("Other class")
        other = self.db.save_student(other_class, "X1", "Other Person", [])
        service = EmailService(self.db, provider=FakeProvider())
        try:
            with self.assertRaises(ValueError):
                service.preview_student_report(self.class_id, other, "2026-09-01", "2026-09-30")
            auth.logout()
            with self.assertRaises(PermissionError):
                service.preview_student_report(self.class_id, self.alice, "2026-09-01", "2026-09-30")
        finally:
            service.shutdown()

    def test_send_all_creates_separate_personalized_messages_and_summary(self):
        self.enable_mail()
        self.db.add_email_recipient(self.alice, "alice@example.edu", "Student")
        self.db.add_email_recipient(self.alice, "parent@example.edu", "Parent")
        self.db.add_email_recipient(self.bob, "bob@example.edu", "Student")
        self.session([(self.alice, "P"), (self.bob, "A")])
        provider = FakeProvider(); service = EmailService(self.db, provider=provider)
        try:
            summary = service.send_all_summary(self.class_id, "2026-09-01", "2026-09-30")
            self.assertEqual((summary["students"], summary["recipient_addresses"]), (2, 3))
            ids = service.enqueue_student_reports(self.class_id, [self.alice, self.bob],
                                                  "2026-09-01", "2026-09-30", campaign="send-all-test")
            self.assertEqual(len(ids), 3); self.assertTrue(service.wait_idle(3))
            self.assertEqual(len(provider.sent), 3)
            alice_bodies = [body for to, _subject, body, _attachment in provider.sent if to in ("alice@example.edu", "parent@example.edu")]
            bob_bodies = [body for to, _subject, body, _attachment in provider.sent if to == "bob@example.edu"]
            self.assertEqual(len(alice_bodies), 2); self.assertEqual(len(bob_bodies), 1)
            self.assertTrue(all("Alice Example" in body and "Bob Example" not in body for body in alice_bodies))
            self.assertTrue(all("Bob Example" in body and "Alice Example" not in body for body in bob_bodies))
        finally:
            service.shutdown()

    def test_schedule_crud_due_processing_is_idempotent_and_student_scoped(self):
        from datetime import date
        self.enable_mail()
        self.db.add_email_recipient(self.alice, "alice@example.edu")
        self.db.add_email_recipient(self.bob, "bob@example.edu")
        self.session([(self.alice, "P"), (self.bob, "A")])
        today = date.today().isoformat()
        provider = FakeProvider(); service = EmailService(self.db, provider=provider)
        try:
            sid = service.create_schedule(self.class_id, "2026-09-01", "2026-09-30", today)
            self.assertEqual(len(service.process_due_schedules(today)), 2)
            self.assertTrue(service.wait_idle(3))
            self.assertEqual(service.process_due_schedules(today), [])
            self.assertEqual(len(provider.sent), 2)
            self.assertNotIn("Bob Example", next(x[2] for x in provider.sent if x[0] == "alice@example.edu"))
            row = self.db.email_schedules(self.class_id)[0]
            self.assertEqual(row["last_run"], today)
            service.set_schedule_enabled(sid, False)
            self.assertFalse(self.db.email_schedules(self.class_id)[0]["enabled"])
            service.update_schedule(sid, self.class_id, "2026-09-02", "2026-09-29", today, True)
            self.assertEqual(self.db.email_schedules(self.class_id)[0]["report_from"], "2026-09-02")
            service.delete_schedule(sid)
            self.assertEqual(self.db.email_schedules(self.class_id), [])
        finally:
            service.shutdown()

    def test_date_range_shared_report_calculation(self):
        self.session([(self.alice, "P"), (self.bob, "A")], "2026-09-02")
        self.session([(self.alice, "E"), (self.bob, "P")], "2026-10-01")
        rows, held = stats.range_students(self.db, self.class_id, "2026-09-01", "2026-09-30")
        self.assertEqual(held, 1)
        self.assertEqual(next(r for r in rows if r["id"] == self.alice)["pct"], 100.0)
        summary = stats.student_range(self.db, self.alice, "2026-09-01", "2026-09-30")
        self.assertEqual(summary["attended"], 1)
        self.assertEqual(summary["held"], 1)
        from app import reports
        from openpyxl import load_workbook
        out = Path(self.temp.name) / "range.xlsx"
        reports.range_xlsx(self.db, self.class_id, "2026-09-01", "2026-09-30", out)
        wb = load_workbook(out, data_only=True)
        self.assertEqual(wb.active["A4"].value, "Student ID")
        self.assertEqual(wb.active["A5"].value, "A1")

    def test_smtp_transport_uses_tls_and_sends_to_one_recipient(self):
        from unittest.mock import MagicMock
        from app.email_service import SMTPProvider
        smtp = MagicMock()
        cfg = {"configured": True, "enabled": True, "sender": "sender@example.edu",
               "username": "smtp-user", "host": "smtp.example.edu", "port": 587,
               "security": "starttls", "secret": "protected-value"}
        with patch("app.email_service.unprotect_secret", return_value="unit credential"), \
             patch("app.email_service.ssl.create_default_context"), \
             patch("app.email_service.smtplib.SMTP", return_value=smtp) as connect:
            SMTPProvider().send(cfg, "one@example.edu", "Subject", "Body")
        connect.assert_called_once_with("smtp.example.edu", 587, timeout=20)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("smtp-user", "unit credential")
        self.assertEqual(smtp.send_message.call_args.kwargs["to_addrs"], ["one@example.edu"])

    def test_gmail_oauth_connect_uses_loopback_state_and_pkce(self):
        import threading, time
        from app.oauth_email import google_connect
        opened = {}
        def open_browser(url):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            opened.update(query)
            def callback():
                time.sleep(0.05)
                target = opened["redirect_uri"][0] + "?" + urllib.parse.urlencode(
                    {"state": opened["state"][0], "code": "local-mock-code"})
                urllib.request.urlopen(target, timeout=3).read()
            threading.Thread(target=callback, daemon=True).start()
            return True
        with patch("app.oauth_email.webbrowser.open", side_effect=open_browser), \
             patch("app.oauth_email._request_json", return_value={"refresh_token": "local-mock-refresh",
                  "scope": "openid email https://www.googleapis.com/auth/gmail.send"}) as exchange, \
             patch("app.oauth_email.verify_google_id_token", return_value="sender@example.edu"):
            result = google_connect("public-client-id")
        self.assertEqual(result, {"refresh_token": "local-mock-refresh", "email": "sender@example.edu"})
        self.assertEqual(opened["code_challenge_method"], ["S256"])
        self.assertEqual(set(opened["scope"][0].split()), {"openid", "email", "https://www.googleapis.com/auth/gmail.send"})
        self.assertNotIn("https://mail.google.com/", opened["scope"][0])
        self.assertNotIn("https://www.googleapis.com/auth/gmail.readonly", opened["scope"][0])
        self.assertEqual(exchange.call_args.args[1]["code"], "local-mock-code")
        self.assertTrue(exchange.call_args.args[1]["code_verifier"])

    def test_google_identity_token_signature_audience_and_expiry_are_verified(self):
        import time
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from app.oauth_email import verify_google_id_token, OAuthError
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = private.public_key().public_numbers()
        def enc(data): return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
        def uint(value): return enc(value.to_bytes((value.bit_length()+7)//8, "big"))
        header = enc(json.dumps({"alg": "RS256", "kid": "test-key"}).encode())
        claims = {"iss": "https://accounts.google.com", "aud": "desktop-client", "exp": int(time.time())+300,
                  "email": "sender@example.edu", "email_verified": True}
        payload = enc(json.dumps(claims).encode())
        signed = f"{header}.{payload}".encode()
        signature = enc(private.sign(signed, padding.PKCS1v15(), hashes.SHA256()))
        token = f"{header}.{payload}.{signature}"
        with patch("app.oauth_email._request_json", side_effect=[
            {"jwks_uri": "https://www.googleapis.com/oauth2/v3/certs"},
            {"keys": [{"kid": "test-key", "kty": "RSA", "alg": "RS256", "n": uint(public.n), "e": uint(public.e)}]}]):
            self.assertEqual(verify_google_id_token(token, "desktop-client"), "sender@example.edu")
        bad_claims = dict(claims, aud="different-client")
        bad_payload = enc(json.dumps(bad_claims).encode())
        bad_signed = f"{header}.{bad_payload}".encode()
        bad_token = f"{header}.{bad_payload}.{enc(private.sign(bad_signed, padding.PKCS1v15(), hashes.SHA256()))}"
        with patch("app.oauth_email._request_json", side_effect=[
            {"jwks_uri": "https://www.googleapis.com/oauth2/v3/certs"},
            {"keys": [{"kid": "test-key", "kty": "RSA", "alg": "RS256", "n": uint(public.n), "e": uint(public.e)}]}]):
            with self.assertRaises(OAuthError): verify_google_id_token(bad_token, "desktop-client")

    def test_gmail_mismatched_authorized_account_is_not_saved(self):
        from app.email_service import EmailConfigurationError
        self.db.put("email_config", {"provider": "Gmail", "auth_mode": "oauth", "sender": "sender@example.edu",
                                      "client_id": "client-id", "secret": "", "tenant": "common"})
        service = EmailService(self.db, provider=FakeProvider())
        try:
            with patch("app.oauth_email.google_connect", return_value={"refresh_token": "should-not-save",
                                                                         "email": "other@example.edu"}):
                with self.assertRaises(EmailConfigurationError):
                    service.connect_oauth("Gmail", "client-id")
            self.assertEqual(self.db.get("email_config")["secret"], "")
            self.assertEqual(self.db.get("email_config").get("google_account", ""), "")
        finally:
            service.shutdown()

    def test_changing_gmail_sender_invalidates_prior_connection(self):
        config = {"provider": "Gmail", "auth_mode": "oauth", "sender": "sender@example.edu",
                  "client_id": "client-id", "secret": "opaque-dpapi-token", "google_account": "sender@example.edu"}
        self.db.put("email_config", config)
        save_email_settings(self.db, provider="Gmail", sender="new@example.edu", username="new@example.edu",
            host="smtp.gmail.com", port=587, security="starttls", secret="", enabled=False,
            absentee_enabled=False, auth_mode="oauth", client_id="client-id")
        changed = self.db.get("email_config")
        self.assertEqual(changed["secret"], "")
        self.assertEqual(changed["google_account"], "")
        self.assertFalse(get_email_settings(self.db)["configured"])

    def test_microsoft_device_oauth_polls_pending_then_returns_refresh(self):
        from app.oauth_email import microsoft_connect
        polls = []
        def urlopen(request, timeout):
            polls.append(request)
            if len(polls) == 1:
                raise urllib.error.HTTPError(request.full_url, 400, "Pending", {}, io.BytesIO(
                    b'{"error":"authorization_pending"}'))
            class Response:
                def __enter__(self): return self
                def __exit__(self, *_): pass
                def read(self, *_): return b'{"refresh_token":"microsoft-refresh"}'
            return Response()
        with patch("app.oauth_email._request_json", return_value={"device_code": "device-only-code",
             "user_code": "USER-CODE", "verification_uri": "https://login.example/", "expires_in": 30,
             "interval": 1}), patch("app.oauth_email.urllib.request.urlopen", side_effect=urlopen), \
             patch("app.oauth_email.time.sleep"):
            self.assertEqual(microsoft_connect("public-client-id", "common"), "microsoft-refresh")
        form = urllib.parse.parse_qs(polls[0].data.decode())
        self.assertEqual(form["client_id"], ["public-client-id"])
        self.assertEqual(form["device_code"], ["device-only-code"])

    def test_gmail_oauth_sends_one_personalized_message_through_api(self):
        from email import message_from_bytes
        from app.oauth_email import send_oauth
        cfg = {"provider": "Gmail", "auth_mode": "oauth", "configured": True, "enabled": True,
               "sender": "sender@example.edu", "client_id": "public-client", "secret": "protected-refresh"}
        with patch("app.oauth_email.refresh_access_token", return_value=("access-token", "rotated")), \
             patch("app.oauth_email._request_json", return_value={"id": "accepted"}) as send:
            rotated = send_oauth(cfg, "alice@example.edu", "Alice report", "Only Alice's attendance.")
        payload = send.call_args.args[1]
        raw = payload["raw"]
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        message = message_from_bytes(decoded)
        self.assertEqual(message["To"], "alice@example.edu")
        self.assertIn("Only Alice's attendance", message.get_payload(decode=True).decode())
        self.assertEqual(send.call_args.args[0], "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
        self.assertEqual(rotated, "rotated")

    def test_settings_and_report_dialog_render_and_preview(self):
        import customtkinter as ctk
        from app.ui.email_settings import EmailSettingsSection
        from app.ui.email_reports import EmailReportDialog
        self.db.add_email_recipient(self.alice, "alice@example.edu", "Student")
        try:
            root = ctk.CTk()
        except Exception as exc:
            self.skipTest(f"Tk display is unavailable: {exc}")
        dialogs = []
        try:
            with patch("app.auth.current_role", return_value="admin"):
                settings = EmailSettingsSection(root, SimpleNamespace(db=self.db, email_service=None,
                                                                       notify_changed=lambda: None))
                settings.pack(fill="both", expand=True)
                self.assertFalse(settings.enabled.get())
                self.assertEqual(settings.sender.get(), "nagalingeshwara1963@gmail.com")
                self.assertIn("Not connected", settings.connection.cget("text"))
                page = ctk.CTkFrame(root); page.app = SimpleNamespace(db=self.db, class_id=self.class_id,
                    email_service=None); page.year = 2026; page.month = 9
                dialog = EmailReportDialog(page); dialogs.append(dialog)
                root.update()
                dialog.preview()
                self.assertEqual(dialog.send_btn.cget("state"), "normal")
                self.assertIn("Alice Example", dialog.preview_text.cget("text"))
                dialog.to_var.set("31-09-2026")
                self.assertEqual(dialog.send_btn.cget("state"), "disabled")
        finally:
            for dialog in dialogs:
                try: dialog.destroy()
                except Exception: pass
            try:
                for timer in root.tk.call("after", "info"):
                    root.after_cancel(timer)
            except Exception: pass
            root.destroy()

    def test_full_application_build_keeps_existing_pages_and_phone_upload(self):
        from app import auth
        from app.ui.main import App
        auth.set_password(self.db, "admin", "admin", "ephemeral-test-password")
        self.assertEqual(auth.login(self.db, "admin", "ephemeral-test-password"), "admin")
        app = None
        try:
            with patch("app.ui.main.DB", return_value=self.db), patch("app.ui.main.config.ensure_dirs"):
                app = App()
                app.update()
                expected_navigation = ["home", "enroll", "photos", "attendance", "reports",
                                       "email_center", "recovery", "reviews", "settings", "models", "help"]
                self.assertEqual(list(app.nav), expected_navigation)
                self.assertEqual(list(app.pages), expected_navigation)
                self.assertTrue(all(not str(button.cget("text")).lstrip().startswith(("1 ", "2 ", "3 ", "4 "))
                                    for button in app.nav.values()))
                for key in ("enroll", "photos", "attendance", "reports", "settings", "email_center"):
                    self.assertIn(key, app.pages)
                self.assertTrue(hasattr(app, "email_service"))
                self.assertTrue(hasattr(app.pages["enroll"], "manage_emails"))
                self.assertTrue(hasattr(app.pages["photos"], "upload_from_phone"))
                center = app.pages["email_center"]
                center.refresh_students(); app.update()
                self.assertIn("2 students", center.summary.cget("text"))
                center.period.set("Custom")
                center.from_var.set("05-09-2026"); center.to_var.set("28-09-2026")
                self.assertEqual(center._dates(), ("2026-09-05", "2026-09-28"))
                enroll = app.pages["enroll"]
                enroll.add_student_card(); enroll.add_enrollment_email(0)
                enroll.groups[0]["recipients"][0]["email"].set("new@example.edu")
                enroll.groups[0]["recipients"][0]["label"].set("Parent")
                self.assertEqual(enroll.groups[0]["recipients"][0]["label"].get(), "Parent")
        finally:
            if app is not None:
                app.email_service.shutdown()
                try:
                    for timer in app.tk.call("after", "info"):
                        app.after_cancel(timer)
                except Exception: pass
                try:
                    app.destroy()
                except Exception:
                    # Some CTk/Tk builds report already-deleted Tcl commands
                    # while tearing down widgets after a construction smoke test.
                    pass
            auth.logout()

    @unittest.skipUnless(__import__("os").name == "nt", "Windows DPAPI is required")
    def test_saved_smtp_secret_is_protected_for_current_windows_user(self):
        import secrets
        secret = secrets.token_urlsafe(24)
        save_email_settings(self.db, provider="Gmail", sender="sender@example.edu", username="smtp-user",
                            host="smtp.example.edu", port=587, security="starttls", secret=secret,
                            enabled=True, absentee_enabled=False)
        cfg = self.db.get("email_config")
        self.assertNotIn(secret, json.dumps(cfg))
        self.assertEqual(unprotect_secret(cfg["secret"]), secret)
        self.assertTrue(get_email_settings(self.db)["enabled"])


if __name__ == "__main__":
    unittest.main()
