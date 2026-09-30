"""Short-lived, token-protected HTTP photo uploads from phones on the local network."""
from __future__ import annotations

import hashlib
import http.server
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import tempfile
import threading
import time
import warnings
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image, UnidentifiedImageError
from .mobile_capture import MOBILE_PAGE

SESSION_TTL_SECONDS = 15 * 60
MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_SESSION_FILES = 40
MAX_SESSION_BYTES = 200 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
SUPPORTED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "BMP": ".bmp"}
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,}$")
_LOG_LOCK = threading.Lock()


class PhoneUploadError(RuntimeError):
    """Safe-to-display problem starting or using a phone upload session."""


def make_qr_image(url, size=288):
    """Render a local upload URL as a QR image using the installed OpenCV build."""
    import cv2
    matrix = cv2.QRCodeEncoder_create().encode(url)
    matrix = cv2.copyMakeBorder(matrix, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    matrix = cv2.resize(matrix, (size, size), interpolation=cv2.INTER_NEAREST)
    return Image.fromarray(matrix)


def discover_lan_addresses():
    """Find private IPv4 addresses; UDP route probing sends no packet."""
    found = set()
    try:
        found.update(x[4][0] for x in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM))
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    usable = []
    for value in found:
        try:
            addr = ipaddress.ip_address(value)
        except ValueError:
            continue
        if addr.version == 4 and addr.is_private and not (addr.is_loopback or addr.is_link_local or addr.is_unspecified or addr.is_multicast or addr.is_reserved):
            usable.append(str(addr))
    return sorted(set(usable), key=lambda x: (not x.startswith("192.168."), x))


def cleanup_stale_sessions(base_dir, older_than=SESSION_TTL_SECONDS + 5 * 60, now=None):
    """Remove only old app-owned phone-upload directories in this configured root."""
    root = Path(base_dir)
    if not root.exists():
        return 0
    now = time.time() if now is None else now
    removed = 0
    for child in root.glob("phone-upload-*"):
        try:
            if child.is_dir() and now - child.stat().st_mtime > older_than:
                shutil.rmtree(child)
                removed += 1
        except OSError:
            continue
    return removed


class PhoneUploadSession:
    """A bounded session with a separate HTTP listener for each usable LAN IPv4."""

    def __init__(self, base_dir, addresses=None, ttl=SESSION_TTL_SECONDS, clock=None, on_upload=None):
        # Pillow lazily imports format plugins; initialize them before worker-thread requests.
        Image.init()
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        cleanup_stale_sessions(self.base_dir)
        self.directory = Path(tempfile.mkdtemp(prefix="phone-upload-", dir=str(self.base_dir)))
        self.token = secrets.token_urlsafe(32)
        self._clock = clock or time.monotonic
        self._expires_at = self._clock() + max(1, int(ttl))
        self._lock = threading.RLock()
        self._active = True
        self._expired = False
        self._closing = False
        self._closed = threading.Event()
        self._files, self._hashes, self._servers, self._endpoints = [], set(), [], []
        self._bytes = self._inflight = self._reserved_bytes = 0
        self._connected = False
        self._finish_requested = False
        self._cleanup_callbacks = []
        self._on_upload = on_upload
        self._analysis_status = {"state": "waiting", "photos_analyzed": 0, "detected_faces": 0,
                                 "confidently_observed": 0, "uncertain_students": 0,
                                 "unknown_faces": 0, "not_yet_observed": 0,
                                 "total_students": 0, "coverage_percent": 0,
                                 "another_capture_suggested": False, "analysis_errors": 0,
                                 "guidance": "Waiting for a photo."}
        chosen = list(dict.fromkeys(addresses if addresses is not None else discover_lan_addresses()))
        if not chosen:
            self._remove_directory()
            raise PhoneUploadError("No usable Wi-Fi or Ethernet address was found. Connect this laptop to the same local network as the phone, then try again.")
        for address in chosen[:8]:
            try:
                self._start_listener(address)
            except (OSError, ValueError, PhoneUploadError):
                continue
        if not self._servers:
            self._remove_directory()
            raise PhoneUploadError("Upasthiti could not open a local upload port. A firewall or another network tool may be blocking it; close other sharing tools and try again.")
        self._audit("session_started", listeners=len(self._servers), lifetime_seconds=max(1, int(ttl)))
        threading.Thread(target=self._watch_expiry, name="UpasthitiPhoneUploadExpiry", daemon=True).start()

    def _audit(self, event, **safe_fields):
        """Log bounded operational facts without tokens, filenames, or photo content."""
        log_path = self.base_dir.parent / "logs" / "phone_upload.log"
        try:
            details = " ".join(f"{key}={str(value).replace(chr(10), '_').replace(chr(13), '_')[:64]}"
                               for key, value in safe_fields.items())
            with _LOG_LOCK:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                backup = log_path.with_suffix(log_path.suffix + ".1")
                if log_path.exists() and log_path.stat().st_size > 1_000_000:
                    backup.unlink(missing_ok=True)
                    os.replace(log_path, backup)
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {event} {details}\n")
        except OSError:
            pass

    def _start_listener(self, address):
        ip = ipaddress.ip_address(address)
        # Discovery never returns loopback. Explicit loopback addresses support isolated tests.
        if ip.version != 4 or not (ip.is_private or ip.is_loopback) or ip.is_link_local or ip.is_unspecified:
            raise ValueError("unusable local address")
        session = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.request.settimeout(30)

            def log_message(self, fmt, *args):
                # Do not log request paths: they contain the temporary bearer token.
                return

            def reply(self, code, body=b"", content_type="application/json; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; img-src 'self' blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'")
                self.close_connection = True
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def authorized(self, suffix=None):
                parts = urlsplit(self.path).path.strip("/").split("/")
                if len(parts) != (2 if suffix else 1) or (suffix and parts[1] != suffix):
                    return False
                host = self.headers.get("Host", "")
                expected = f"{address}:{server.server_address[1]}"
                origin = self.headers.get("Origin")
                return (_TOKEN_RE.fullmatch(parts[0]) is not None
                        and secrets.compare_digest(parts[0], session.token)
                        and secrets.compare_digest(host.lower(), expected.lower())
                        and (origin is None or secrets.compare_digest(origin, "http://" + expected)))

            def do_GET(self):
                path = urlsplit(self.path).path
                suffix = "status" if path.count("/") == 2 else None
                if suffix not in (None, "status") or not self.authorized(suffix):
                    session._audit("request_rejected", reason="authorization")
                    self.reply(404, b'{"error":"Not found"}')
                    return
                state = session.status()
                if state["state"] != "active":
                    self.reply(410, b'{"error":"This upload session has ended. Ask the laptop user to start a new session."}')
                    return
                session.mark_connected()
                if suffix == "status":
                    # Only aggregate counts and generic guidance leave the laptop.
                    self.reply(200, json.dumps({"count": state["count"], "state": "active",
                                                "analysis": state["analysis"]}).encode())
                else:
                    self.reply(200, MOBILE_PAGE.encode("utf-8"), "text/html; charset=utf-8")

            def do_POST(self):
                if self.authorized("finish"):
                    if session.request_finish():
                        self.reply(202, b'{"ok":true,"state":"finish_requested"}')
                    else:
                        self.reply(410, b'{"error":"This upload session has ended."}')
                    return
                if not self.authorized("upload"):
                    session._audit("request_rejected", reason="authorization")
                    self.reply(404, b'{"error":"Not found"}')
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    self.reply(411, b'{"error":"A photo with a known size is required."}')
                    return
                if length <= 0 or length > MAX_FILE_BYTES:
                    session._audit("upload_rejected", reason="file_size")
                    self.reply(413, json.dumps({"error": f"Each photo must be smaller than {MAX_FILE_BYTES // (1024*1024)} MB."}).encode())
                    return
                ctype = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if ctype and not (ctype.startswith("image/") or ctype == "application/octet-stream"):
                    session._audit("upload_rejected", reason="content_type")
                    self.reply(415, b'{"error":"Choose a photo in JPEG, PNG, or BMP format."}')
                    return
                if not session.begin_upload(length):
                    state = session.status()
                    if state["state"] == "active":
                        self.reply(429, b'{"error":"This session reached its photo or storage limit. Finish it on the laptop and start another."}')
                    else:
                        self.reply(410, b'{"error":"This upload session has ended. Ask the laptop user to start a new session."}')
                    return
                try:
                    data = self.rfile.read(length)
                    if len(data) != length:
                        self.reply(400, b'{"error":"The photo upload was incomplete. Try again."}')
                        return
                    filename = unquote(self.headers.get("X-Filename", "photo"))
                    try:
                        destination, count = session.accept_upload(filename, data)
                        if session._on_upload:
                            try: session._on_upload(destination)
                            except Exception as exc:
                                session._audit("analysis_queue_failed", error_type=type(exc).__name__)
                    except PhoneUploadError as exc:
                        code = 409 if "already uploaded" in str(exc) else 400
                        session._audit("upload_rejected", reason="duplicate" if code == 409 else "invalid_image")
                        self.reply(code, json.dumps({"error": str(exc)}).encode("utf-8"))
                        return
                    self.reply(201, json.dumps({"ok": True, "count": count}).encode())
                finally:
                    session.end_upload(length)

            def do_PUT(self): self.reply(405, b'{"error":"Method not allowed"}')
            def do_DELETE(self): self.reply(405, b'{"error":"Method not allowed"}')

        server = http.server.HTTPServer((str(ip), 0), Handler)
        thread = threading.Thread(target=server.serve_forever, name="UpasthitiPhoneUpload", daemon=True)
        thread.start()
        self._servers.append((server, thread))
        port = server.server_address[1]
        self._endpoints.append({"address": str(ip), "port": port, "url": f"http://{ip}:{port}/{self.token}"})

    @property
    def endpoints(self):
        return [dict(x) for x in self._endpoints]

    @property
    def paths(self):
        with self._lock:
            return [Path(path) for path in self._files]

    def mark_connected(self):
        with self._lock:
            if self._active:
                self._connected = True

    def _expire_locked(self):
        if self._active and self._clock() >= self._expires_at:
            self._active, self._expired = False, True
            return True
        return False

    def status(self):
        with self._lock:
            expired = self._expire_locked()
            state = "active" if self._active else ("expired" if self._expired else "closed")
            result = {"state": state, "count": len(self._files), "bytes": self._bytes,
                      "expires_in": max(0, int(self._expires_at - self._clock())) if self._active else 0,
                      "connected": self._connected, "uploading": self._inflight > 0,
                      "finish_requested": self._finish_requested,
                      "analysis": dict(self._analysis_status)}
        if expired:
            self.close(delete=True, reason="expired")
        return result

    def set_analysis_status(self, status):
        """Publish aggregate, non-identifying capture analysis to the active phone session."""
        allowed = ("state", "photos_analyzed", "detected_faces", "confidently_observed",
                   "uncertain_students", "unknown_faces", "not_yet_observed", "total_students",
                   "coverage_percent", "another_capture_suggested", "similar_to_previous",
                   "analysis_errors", "guidance")
        safe = {key: status[key] for key in allowed if key in status}
        if "guidance" in safe: safe["guidance"] = str(safe["guidance"])[:260]
        with self._lock:
            self._analysis_status = {**self._analysis_status, **safe}

    def set_upload_callback(self, callback):
        with self._lock:
            self._on_upload = callback

    def request_finish(self):
        with self._lock:
            if not self._active: return False
            self._finish_requested = True
            return True

    def _watch_expiry(self):
        while not self._closed.wait(1):
            if self.status()["state"] != "active":
                return

    def begin_upload(self, length):
        with self._lock:
            expired = self._expire_locked()
            allowed = (self._active and len(self._files) + self._inflight < MAX_SESSION_FILES
                       and self._bytes + self._reserved_bytes + length <= MAX_SESSION_BYTES)
            if allowed:
                self._inflight += 1
                self._reserved_bytes += length
        if expired:
            self.close(delete=True, reason="expired")
        return allowed

    def end_upload(self, length):
        with self._lock:
            self._inflight = max(0, self._inflight - 1)
            self._reserved_bytes = max(0, self._reserved_bytes - length)

    def accept_upload(self, filename, data):
        if self.status()["state"] != "active":
            raise PhoneUploadError("This upload session has ended. Ask the laptop user to start a new session.")
        extension = self._validate_image(data)
        digest = hashlib.sha256(data).hexdigest()
        safe_name = self._safe_filename(filename, extension)
        with self._lock:
            expired = self._expire_locked()
            inactive = not self._active
            if not inactive and digest in self._hashes:
                raise PhoneUploadError("This photo was already uploaded in this session.")
            if not inactive and (len(self._files) >= MAX_SESSION_FILES or self._bytes + len(data) > MAX_SESSION_BYTES):
                raise PhoneUploadError("This session has reached its photo or storage limit. Finish it and start another session.")
            destination = None
            count = 0
            if not inactive:
                destination = self.directory / f"{len(self._files) + 1:03d}_{safe_name}"
                try:
                    with destination.open("xb") as stream:
                        stream.write(data)
                except OSError as exc:
                    raise PhoneUploadError("Upasthiti could not save the photo temporarily. Check the laptop's free disk space, then try again.") from exc
                self._hashes.add(digest)
                self._files.append(destination)
                self._bytes += len(data)
                self._connected = True
                count = len(self._files)
        if expired:
            self.close(delete=True, reason="expired")
        if inactive:
            raise PhoneUploadError("This upload session has ended. Ask the laptop user to start a new session.")
        self._audit("photo_accepted", count=count, size_bytes=len(data), format=extension.lstrip("."))
        return destination, count

    @staticmethod
    def _safe_filename(filename, extension):
        name = str(filename or "photo").replace("\\", "/").split("/")[-1]
        stem = name.rsplit(".", 1)[0] if "." in name else name
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("._-")[:48] or "photo"
        return stem + extension

    @staticmethod
    def _validate_image(data):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    fmt = image.format
                    if fmt not in SUPPORTED_FORMATS:
                        raise PhoneUploadError("Choose a JPEG, PNG, or BMP photo.")
                    if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_IMAGE_PIXELS:
                        raise PhoneUploadError("This photo is too large to process. Choose a smaller image.")
                    image.verify()
                with Image.open(BytesIO(data)) as image:
                    image.load()
                    if image.format != fmt:
                        raise PhoneUploadError("The photo file could not be validated. Choose another image.")
            return SUPPORTED_FORMATS[fmt]
        except PhoneUploadError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise PhoneUploadError("The upload is not a valid JPEG, PNG, or BMP photo.") from exc

    def close(self, delete=True, callback=None, reason="closed"):
        """Invalidate immediately; stop listeners off-thread and then return/clean uploads."""
        with self._lock:
            self._active = False
            if callback:
                self._cleanup_callbacks.append(callback)
            if self._closing:
                return
            self._closing = True
            count = len(self._files)
        self._audit("session_closed", reason=reason, photos=count)

        def shutdown():
            for server, thread in self._servers:
                try:
                    server.shutdown()
                    server.server_close()
                    if thread.is_alive():
                        thread.join(timeout=2)
                except OSError:
                    pass
            with self._lock:
                paths = [Path(path) for path in self._files]
                callbacks, self._cleanup_callbacks = self._cleanup_callbacks, []
            if delete:
                self._remove_directory()
                paths = []
            self._closed.set()
            cleanup = (lambda: self._remove_directory()) if not delete else (lambda: None)
            for done in callbacks:
                try:
                    done(paths, cleanup)
                except Exception:
                    pass

        threading.Thread(target=shutdown, name="UpasthitiPhoneUploadStop", daemon=True).start()

    def wait_closed(self, timeout=None):
        return self._closed.wait(timeout)

    def _remove_directory(self):
        try:
            shutil.rmtree(self.directory)
        except FileNotFoundError:
            pass
        except OSError:
            # Stale-session cleanup can retry if a Windows file handle is still open.
            pass
