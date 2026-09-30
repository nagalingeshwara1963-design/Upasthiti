"""Installed-app OAuth flows and API transports for Gmail and Microsoft Graph."""
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from email.message import EmailMessage
from email.utils import formataddr
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .securestore import unprotect_secret

GOOGLE_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_SCOPES = ("openid", "email", GOOGLE_SEND_SCOPE)
MICROSOFT_SCOPE = "https://graph.microsoft.com/Mail.Send offline_access User.Read"
HTTP_TIMEOUT = 25


class OAuthError(RuntimeError):
    pass


def _request_json(url, data=None, headers=None, timeout=HTTP_TIMEOUT):
    headers = headers or {}
    if data is None:
        raw = None
    elif headers.get("Content-Type") == "application/json":
        raw = json.dumps(data).encode("utf-8")
    else:
        raw = urllib.parse.urlencode(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    request = urllib.request.Request(url, data=raw, headers=headers, method="POST" if raw is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read(2_000_000)
            return json.loads(content.decode("utf-8")) if content else {}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read(16_384).decode("utf-8"))
            detail = payload.get("error_description") or payload.get("error", {}).get("message") or payload.get("error")
        except Exception:
            detail = "provider rejected the request"
        raise OAuthError(f"Email provider authorization or submission failed (HTTP {exc.code}): {str(detail)[:250]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OAuthError(f"Email provider connection failed: {type(exc).__name__}.") from None


def google_connect(client_id, client_secret="", progress=None):
    """Authorize Gmail send and return a refresh token plus verified account email."""
    if not client_id.strip(): raise OAuthError("Enter a Google OAuth desktop client ID first.")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    result = {}
    ready = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                result["error"] = "OAuth callback state did not match."
            elif query.get("error"):
                result["error"] = "Google authorization was cancelled or denied."
            else:
                result["code"] = query.get("code", [""])[0]
            body = ("<html><meta charset='utf-8'><title>Upasthiti</title><body>Authorization received. You can close this tab and return to Upasthiti.</body></html>").encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); ready.set()

        def log_message(self, *_):
            return

    server = HTTPServer(("127.0.0.1", 0), Callback)
    server.timeout = 180
    redirect = f"http://127.0.0.1:{server.server_port}/oauth2callback"
    params = {"client_id": client_id.strip(), "redirect_uri": redirect, "response_type": "code",
              "scope": " ".join(GOOGLE_SCOPES), "access_type": "offline", "prompt": "consent select_account",
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    if progress: progress("Opening Google authorization in your browser…")
    try:
        webbrowser.open(url)
        server.handle_request()
    finally:
        server.server_close()
    if not ready.is_set() or not result.get("code"):
        raise OAuthError(result.get("error", "Google authorization timed out or did not return a code."))
    form = {"client_id": client_id.strip(), "code": result["code"], "code_verifier": verifier,
            "redirect_uri": redirect, "grant_type": "authorization_code"}
    if client_secret.strip(): form["client_secret"] = client_secret.strip()
    token = _request_json("https://oauth2.googleapis.com/token", form)
    refresh = token.get("refresh_token")
    if not refresh: raise OAuthError("Google did not return a refresh token. Revoke the prior grant and connect again.")
    granted = set((token.get("scope") or "").split())
    if GOOGLE_SEND_SCOPE not in granted:
        raise OAuthError("Google did not grant the Gmail send permission required by Upasthiti.")
    if granted.intersection({"https://mail.google.com/", "https://www.googleapis.com/auth/gmail.readonly",
                             "https://www.googleapis.com/auth/gmail.modify"}):
        raise OAuthError("Google returned broader Gmail access than Upasthiti requested; no token was saved.")
    email = verify_google_id_token(token.get("id_token", ""), client_id.strip())
    return {"refresh_token": refresh, "email": email}


def verify_google_id_token(id_token, client_id):
    """Verify Google-issued ID token locally and return its verified email claim."""
    try:
        encoded_header, encoded_payload, encoded_signature = id_token.split(".")
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        header = json.loads(decode(encoded_header))
        claims = json.loads(decode(encoded_payload))
        signature = decode(encoded_signature)
    except Exception:
        raise OAuthError("Google did not return a valid account identity token.") from None
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise OAuthError("Google returned an unsupported account identity token.")
    discovery = _request_json("https://accounts.google.com/.well-known/openid-configuration")
    jwks_uri = discovery.get("jwks_uri", "")
    if not jwks_uri.startswith("https://www.googleapis.com/"):
        raise OAuthError("Google identity signing keys could not be verified.")
    keys = _request_json(jwks_uri).get("keys", [])
    jwk = next((key for key in keys if key.get("kid") == header["kid"] and key.get("kty") == "RSA" and key.get("alg", "RS256") == "RS256"), None)
    if jwk is None:
        raise OAuthError("Google identity signing key was not recognized.")
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        def as_int(value):
            raw = decode(value)
            return int.from_bytes(raw, "big")
        public_key = rsa.RSAPublicNumbers(as_int(jwk["e"]), as_int(jwk["n"])).public_key()
        public_key.verify(signature, f"{encoded_header}.{encoded_payload}".encode("ascii"),
                          padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        raise OAuthError("Google account identity could not be cryptographically verified.") from None
    audience = claims.get("aud")
    audience_matches = audience == client_id or (isinstance(audience, list) and client_id in audience)
    try:
        expiry = float(claims.get("exp", 0))
    except (TypeError, ValueError):
        expiry = 0
    if (claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com") or
            not audience_matches or
            (isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != client_id) or
            expiry <= time.time() or
            not claims.get("email_verified") or not claims.get("email")):
        raise OAuthError("Google account identity token was expired, unverified, or issued for another app.")
    return claims["email"].strip()


def microsoft_connect(client_id, tenant="common", progress=None):
    """Microsoft Entra device-code flow; the user completes sign-in in a browser."""
    if not client_id.strip(): raise OAuthError("Enter a Microsoft Entra public-client ID first.")
    tenant = (tenant or "common").strip()
    if any(c.isspace() for c in tenant) or "/" in tenant or "\\" in tenant:
        raise OAuthError("Enter a valid Microsoft tenant ID or 'common'.")
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    device = _request_json(base + "/devicecode", {"client_id": client_id.strip(), "scope": MICROSOFT_SCOPE})
    if progress:
        progress(device.get("message") or f"Open {device.get('verification_uri')} and enter code {device.get('user_code')}.")
    deadline = time.monotonic() + int(device.get("expires_in", 900))
    interval = max(1, int(device.get("interval", 5)))
    while time.monotonic() < deadline:
        time.sleep(interval)
        request = urllib.request.Request(base + "/token",
            data=urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                         "client_id": client_id.strip(), "device_code": device["device_code"]}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                token = json.loads(response.read(65536).decode("utf-8"))
            if token.get("refresh_token"): return token["refresh_token"]
            raise OAuthError("Microsoft sign-in completed without returning a refresh token.")
        except urllib.error.HTTPError as exc:
            try: payload = json.loads(exc.read(16384).decode("utf-8"))
            except Exception: payload = {}
            error = payload.get("error", "")
            if error == "authorization_pending": continue
            if error == "slow_down": interval += 5; continue
            if error in ("authorization_declined", "access_denied", "expired_token"):
                raise OAuthError("Microsoft authorization was cancelled, denied, or expired.") from None
            raise OAuthError(f"Microsoft authorization failed: {str(payload.get('error_description') or error)[:250]}") from None
    raise OAuthError("Microsoft device authorization timed out.")


def refresh_access_token(config):
    """Return (short-lived access token, possibly rotated refresh token)."""
    refresh = unprotect_secret(config["secret"])
    provider = config.get("provider")
    if provider == "Gmail":
        form = {"client_id": config["client_id"], "refresh_token": refresh, "grant_type": "refresh_token"}
        client_secret = config.get("oauth_client_secret", "")
        if client_secret: form["client_secret"] = unprotect_secret(client_secret)
        endpoint = "https://oauth2.googleapis.com/token"
    elif provider == "Outlook/Microsoft":
        tenant = config.get("tenant", "common")
        form = {"client_id": config["client_id"], "refresh_token": refresh,
                "grant_type": "refresh_token", "scope": MICROSOFT_SCOPE}
        endpoint = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    else:
        raise OAuthError("OAuth is not available for the selected provider.")
    token = _request_json(endpoint, form)
    access = token.get("access_token")
    if not access: raise OAuthError("Email provider did not return an access token.")
    return access, token.get("refresh_token")


def send_oauth(config, recipient, subject, body, attachment=None):
    """Send one individual message using Gmail API or Microsoft Graph."""
    access, rotated_refresh = refresh_access_token(config)
    if config["provider"] == "Gmail":
        message = EmailMessage()
        message["From"] = formataddr(("Upasthiti", config["sender"]))
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        if attachment:
            path, filename = attachment
            message.add_attachment(Path(path).read_bytes(), maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=filename)
        raw = base64.urlsafe_b64encode(message.as_bytes()).rstrip(b"=").decode("ascii")
        _request_json("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                      {"raw": raw}, {"Authorization": f"Bearer {access}", "Content-Type": "application/json"})
    else:
        mail = {"subject": subject, "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": recipient}}]}
        if attachment:
            path, filename = attachment
            data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            mail["attachments"] = [{"@odata.type": "#microsoft.graph.fileAttachment", "name": filename,
                                    "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    "contentBytes": data}]
        raw = json.dumps({"message": mail, "saveToSentItems": True}).encode("utf-8")
        request = urllib.request.Request("https://graph.microsoft.com/v1.0/me/sendMail", data=raw,
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                response.read(4096)
        except urllib.error.HTTPError as exc:
            try: payload = json.loads(exc.read(16384).decode("utf-8")); detail = payload.get("error", {}).get("message", "provider rejected the request")
            except Exception: detail = "provider rejected the request"
            raise OAuthError(f"Microsoft Graph submission failed (HTTP {exc.code}): {str(detail)[:250]}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OAuthError(f"Microsoft Graph connection failed: {type(exc).__name__}.") from None
    return rotated_refresh
