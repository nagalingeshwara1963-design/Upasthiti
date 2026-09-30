"""Isolated tests for the phone upload session and workflow handoff hooks."""
import http.client
import io
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from PIL import Image

from app.phone_upload import (
    MAX_FILE_BYTES,
    PhoneUploadError,
    PhoneUploadSession,
    cleanup_stale_sessions,
    make_qr_image,
)
from app.ui.page_enroll import EnrollPage
from app.ui.page_photos import PhotosPage


def image_bytes(fmt="JPEG", color=(20, 80, 140)):
    out = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(out, format=fmt)
    return out.getvalue()


class PhoneUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="upasthiti-phone-test-")
        self.root = Path(self.temp.name)
        self.session = PhoneUploadSession(self.root / "sessions", addresses=["127.0.0.1"], ttl=120)

    def tearDown(self):
        if self.session:
            self.session.close(delete=True)
            self.session.wait_closed(3)
        self.temp.cleanup()

    def request(self, path, data=None, headers=None, method=None):
        endpoint = self.session.endpoints[0]
        url = urlsplit(endpoint["url"])
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=4)
        conn.request(method or ("POST" if data is not None else "GET"), path, body=data, headers=headers or {})
        response = conn.getresponse()
        body = response.read()
        status = response.status
        conn.close()
        return status, body

    def upload(self, name, data, mime="image/jpeg", path=None):
        return self.request(path or f"/{self.session.token}/upload", data,
                            {"Content-Type": mime, "X-Filename": name})

    def test_session_token_is_random_and_qr_renders(self):
        other = PhoneUploadSession(self.root / "sessions", addresses=["127.0.0.1"], ttl=120)
        try:
            self.assertNotEqual(self.session.token, other.token)
            self.assertGreaterEqual(len(self.session.token), 40)
            image = make_qr_image(self.session.endpoints[0]["url"])
            self.assertEqual(image.size, (288, 288))
        finally:
            other.close(delete=True)
            other.wait_closed(3)

    def test_security_log_omits_token_and_filename(self):
        secret_name = "private-student-photo.jpg"
        self.assertEqual(self.upload(secret_name, image_bytes())[0], 201)
        self.session.close(delete=True, reason="test-finished")
        self.assertTrue(self.session.wait_closed(3))
        text = (self.root / "logs" / "phone_upload.log").read_text(encoding="utf-8")
        self.assertIn("session_started", text)
        self.assertIn("photo_accepted", text)
        self.assertIn("session_closed", text)
        self.assertNotIn(self.session.token, text)
        self.assertNotIn(secret_name, text)

    def test_mobile_page_and_authorization(self):
        code, page = self.request(f"/{self.session.token}")
        self.assertEqual(code, 200)
        self.assertIn(b"Take a photo", page)
        self.assertIn(b"Choose photos", page)
        for phrase in (b"Use This Photo", b"Retake", b"Remove", b"Upload selected photos", b"Retry failed uploads", b"Finish Anyway"):
            self.assertIn(phrase, page)
        self.assertEqual(self.request("/")[0], 404)
        self.assertEqual(self.request("/wrong-token")[0], 404)
        self.assertEqual(self.request(f"/{self.session.token}/unrelated")[0], 404)
        self.assertEqual(self.request("/../../Windows/win.ini")[0], 404)

    def test_upload_callback_and_status_are_session_scoped(self):
        received = []
        self.session.set_upload_callback(received.append)
        code, _ = self.upload("class photo.jpg", image_bytes())
        self.assertEqual(code, 201)
        self.assertEqual(received, self.session.paths)
        code, body = self.request(f"/{self.session.token}/status")
        self.assertEqual(code, 200)
        state = __import__("json").loads(body)
        self.assertEqual(state["analysis"]["state"], "waiting")
        self.assertNotIn("path", state["analysis"])

    def test_phone_can_explicitly_request_finish_but_cannot_finish_other_sessions(self):
        self.assertEqual(self.request(f"/{self.session.token}/finish", method="POST")[0], 202)
        self.assertTrue(self.session.status()["finish_requested"])
        self.assertEqual(self.request("/wrong-token/finish", method="POST")[0], 404)

    def test_uploads_jpeg_png_bmp_and_sanitizes_filename(self):
        cases = [("../face one.jpg", "JPEG"), ("phone.png", "PNG"), ("camera.bmp", "BMP")]
        for i, (name, fmt) in enumerate(cases):
            code, body = self.upload(name, image_bytes(fmt, (i * 40, 80, 120)), f"image/{fmt.lower()}")
            self.assertEqual(code, 201, body)
        paths = self.session.paths
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(p.parent == self.session.directory for p in paths))
        self.assertTrue(all(".." not in p.name and "/" not in p.name and "\\" not in p.name for p in paths))
        self.assertEqual(self.session.status()["count"], 3)

    def test_invalid_malformed_and_unsupported_images_rejected(self):
        self.assertEqual(self.upload("bad.jpg", b"not an image")[0], 400)
        self.assertEqual(self.upload("bad.gif", image_bytes("GIF"), "image/gif")[0], 400)
        self.assertEqual(self.session.status()["count"], 0)

    def test_duplicate_submission_rejected(self):
        data = image_bytes()
        self.assertEqual(self.upload("one.jpg", data)[0], 201)
        code, body = self.upload("two.jpg", data)
        self.assertEqual(code, 409)
        self.assertIn(b"already uploaded", body)
        self.assertEqual(self.session.status()["count"], 1)

    def test_oversized_request_rejected_before_body_read(self):
        endpoint = self.session.endpoints[0]
        url = urlsplit(endpoint["url"])
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=4)
        conn.putrequest("POST", f"/{self.session.token}/upload")
        conn.putheader("Content-Length", str(MAX_FILE_BYTES + 1))
        conn.putheader("Content-Type", "image/jpeg")
        conn.endheaders()
        response = conn.getresponse()
        self.assertEqual(response.status, 413)
        response.read(); conn.close()

    def test_missing_token_invalid_token_and_unauthorized_endpoint(self):
        self.assertEqual(self.request("/upload")[0], 404)
        self.assertEqual(self.request("/not-the-token/upload", image_bytes(), {"Content-Type": "image/jpeg"})[0], 404)
        self.assertEqual(self.request(f"/{self.session.token}/download")[0], 404)
        self.assertEqual(self.request(f"/{self.session.token}/upload", image_bytes(),
                                      {"Content-Type": "image/jpeg", "Origin": "http://attacker.invalid"})[0], 404)

    def test_cancel_invalidates_session_and_deletes_files(self):
        self.assertEqual(self.upload("one.jpg", image_bytes())[0], 201)
        directory = self.session.directory
        self.session.close(delete=True)
        self.assertTrue(self.session.wait_closed(3))
        self.assertFalse(directory.exists())
        self.assertFalse(self.session.begin_upload(100))
        with self.assertRaises(PhoneUploadError):
            self.session.accept_upload("late.jpg", image_bytes(color=(1, 2, 3)))

    def test_expiry_invalidates_session_and_cleans_up(self):
        now = [10.0]
        expired = PhoneUploadSession(self.root / "expiry", addresses=["127.0.0.1"], ttl=5, clock=lambda: now[0])
        directory = expired.directory
        now[0] += 6
        self.assertEqual(expired.status()["state"], "expired")
        self.assertFalse(expired.begin_upload(100))
        self.assertTrue(expired.wait_closed(3))
        self.assertFalse(directory.exists())

    def test_file_count_limit(self):
        with patch("app.phone_upload.MAX_SESSION_FILES", 2):
            self.assertEqual(self.upload("one.jpg", image_bytes(color=(1, 2, 3)))[0], 201)
            self.assertEqual(self.upload("two.jpg", image_bytes(color=(2, 3, 4)))[0], 201)
            code, _ = self.upload("three.jpg", image_bytes(color=(3, 4, 5)))
            self.assertEqual(code, 429)

    def test_concurrent_upload_reservations_respect_total_limit(self):
        with patch("app.phone_upload.MAX_SESSION_BYTES", 10):
            self.assertTrue(self.session.begin_upload(8))
            self.assertFalse(self.session.begin_upload(3))
            self.session.end_upload(8)
            self.assertTrue(self.session.begin_upload(3))
            self.session.end_upload(3)

    def test_finish_returns_paths_and_deferred_cleanup(self):
        self.assertEqual(self.upload("one.jpg", image_bytes())[0], 201)
        result = []
        event = threading.Event()
        self.session.close(delete=False, callback=lambda paths, cleanup: (result.append((paths, cleanup)), event.set()))
        self.assertTrue(event.wait(3))
        paths, cleanup = result[0]
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].exists())
        cleanup()
        self.assertFalse(self.session.directory.exists())

    def test_stale_cleanup_only_removes_old_session_directories(self):
        root = self.root / "stale"
        old = root / "phone-upload-old"
        fresh = root / "phone-upload-fresh"
        unrelated = root / "keep-this"
        old.mkdir(parents=True); fresh.mkdir(); unrelated.mkdir()
        import os, time
        os.utime(old, (time.time() - 1000, time.time() - 1000))
        self.assertEqual(cleanup_stale_sessions(root, older_than=100), 1)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists() and unrelated.exists())

    def test_mobile_exif_orientation_is_applied_by_existing_image_loader(self):
        from app.services import imread
        with tempfile.TemporaryDirectory(prefix="upasthiti-orientation-") as temp:
            path = Path(temp) / "rotated.jpg"
            image = Image.new("RGB", (80, 40), (120, 80, 40))
            exif = image.getexif(); exif[274] = 6
            image.save(path, exif=exif)
            decoded = imread(path)
            self.assertIsNotNone(decoded)
            self.assertEqual(decoded.shape[:2], (80, 40))


class WorkflowHandoffTests(unittest.TestCase):
    def test_enrollment_handoff_uses_existing_import_queue(self):
        received = {}
        class Fake:
            def start_import(self, paths, append=True, cleanup=None):
                received.update(paths=paths, append=append, cleanup=cleanup)
        paths = [Path("phone-a.jpg"), Path("phone-b.jpg")]
        EnrollPage._phone_upload_received(Fake(), paths, lambda: None)
        self.assertEqual(received["paths"], paths)
        self.assertTrue(received["append"])
        self.assertIsNotNone(received["cleanup"])

    def test_group_photo_handoff_uses_existing_add_path_pipeline(self):
        received = []
        cleaned = []
        class Fake:
            app = SimpleNamespace(staged=[], smart_capture_result=None)
            def add_path(self, path): received.append(path)
            def render(self): received.append("render")
        paths = [Path("group-a.jpg"), Path("group-b.jpg")]
        PhotosPage._phone_upload_received(Fake(), paths, lambda: cleaned.append(True))
        self.assertEqual(received, paths + ["render"])
        self.assertEqual(cleaned, [True])


class PhoneUploadDialogTests(unittest.TestCase):
    def test_dialog_qr_and_status_updates(self):
        import customtkinter as ctk
        from types import SimpleNamespace
        from app.ui.phone_upload import PhoneUploadDialog
        with tempfile.TemporaryDirectory(prefix="upasthiti-phone-ui-") as temp:
            session = PhoneUploadSession(Path(temp) / "sessions", addresses=["127.0.0.1"], ttl=120)
            root = None
            try:
                try:
                    root = ctk.CTk()
                except Exception as exc:
                    session.close(delete=True); session.wait_closed(3)
                    self.skipTest(f"Tk display is unavailable: {exc}")
                parent = ctk.CTkFrame(root)
                parent.app = SimpleNamespace(post=lambda fn: fn())
                with patch("app.ui.phone_upload.PhoneUploadSession", return_value=session):
                    dialog = PhoneUploadDialog(parent, lambda paths, cleanup: None)
                root.update()
                self.assertEqual(dialog.status_label.cget("text"), "Waiting for phone")
                session.mark_connected()
                dialog._tick()
                self.assertIn("Phone connected", dialog.status_label.cget("text"))
                dialog.cancel()
                root.update()
                self.assertTrue(session.wait_closed(3))
            finally:
                if root is not None:
                    try:
                        for timer in root.tk.call("after", "info"):
                            root.after_cancel(timer)
                    except Exception:
                        pass
                    root.destroy()
                session.close(delete=True)
                session.wait_closed(3)


if __name__ == "__main__":
    unittest.main()
