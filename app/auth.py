"""Authentication helpers for Upasthiti.

Passwords are stored as versioned PBKDF2-SHA256 hashes. Legacy salted SHA-256
hashes remain verifiable and are upgraded after a successful login.

All users live in the settings table:
    key = "auth_admin"           -> hashed admin password (only one admin)
    key = "auth_faculty_<name>"  -> hashed password for faculty <name>

Session state is module-level (one process, one logged-in user at a time).
The UI reads current_user() / current_role() anywhere after login().
"""
import hashlib, hmac, os, time
from datetime import date, datetime

# ------------ internals --------------------------------------------------
_DB_PREFIX = "auth_"
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60
_session = {"user": None, "role": None, "student_id": None, "must_change": False, "logged_in_at": 0.0}


def _new_session(user, role, student_id=None, must_change=False):
    _session.update(user=user, role=role, student_id=student_id,
                    must_change=bool(must_change), logged_in_at=time.time())


def _make_hash(password):
    """Return a versioned PBKDF2-SHA256 password hash."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def _check_hash(stored, attempt):
    """Return True if *attempt* matches the stored hash string."""
    try:
        if stored.startswith("pbkdf2_sha256$"):
            kind, rounds, salt_hex, dig_hex = stored.split("$", 3)
            iterations = int(rounds)
            if kind != "pbkdf2_sha256" or not 100_000 <= iterations <= 1_000_000: return False
            actual = hashlib.pbkdf2_hmac("sha256", attempt.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
            return hmac.compare_digest(bytes.fromhex(dig_hex), actual)
        salt_hex, dig_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dig_hex)
        actual = hashlib.sha256(salt + attempt.encode("utf-8")).digest()
        # constant-time compare
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


# ------------ public helpers ----------------------------------------------

def has_any_account(db):
    """True if at least one account (admin or faculty) exists in the DB."""
    rows = db.q("SELECT key FROM settings WHERE key LIKE ?", (_DB_PREFIX + "%",))
    return len(rows) > 0


def set_password(db, role, username, password):
    """Create or update the password for *username* with *role*."""
    if role == "admin":
        key = _DB_PREFIX + "admin"
    else:
        key = _DB_PREFIX + "faculty_" + username.strip().lower()
    db.run(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, _make_hash(password)),
    )


def list_users(db):
    """Return a list of {username, role} dicts (excludes the password hash)."""
    rows = db.q("SELECT key FROM settings WHERE key LIKE ?", (_DB_PREFIX + "%",))
    out = []
    for r in rows:
        key = r["key"][len(_DB_PREFIX):]
        if key == "admin":
            out.append({"username": "admin", "role": "admin"})
        elif key.startswith("faculty_"):
            out.append({"username": key[len("faculty_"):], "role": "faculty"})
    return out


def delete_user(db, username):
    """Delete a faculty account (admin cannot be deleted)."""
    key = _DB_PREFIX + "faculty_" + username.strip().lower()
    db.run("DELETE FROM settings WHERE key=?", (key,))


def login(db, username, password):
    """
    Try to log in.  Returns the role string ('admin' | 'faculty') on success,
    or None on failure.  Also sets the module-level session.
    """
    logout()
    uname = username.strip().lower()
    # try admin first
    if uname == "admin":
        row = db.q("SELECT value FROM settings WHERE key=?", (_DB_PREFIX + "admin",))
        if row and _check_hash(row[0]["value"], password):
            if not row[0]["value"].startswith("pbkdf2_sha256$"): set_password(db, "admin", "admin", password)
            _new_session("admin", "admin")
            return "admin"
        return None
    # try faculty
    key = _DB_PREFIX + "faculty_" + uname
    row = db.q("SELECT value FROM settings WHERE key=?", (key,))
    if row and _check_hash(row[0]["value"], password):
        if not row[0]["value"].startswith("pbkdf2_sha256$"): set_password(db, "faculty", uname, password)
        _new_session(uname, "faculty")
        return "faculty"
    return None


def _student_hash(password, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def _student_password_matches(encoded, password):
    try:
        kind, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if kind != "pbkdf2_sha256": return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def student_login(db, student_name, student_code, password):
    """Authenticate one student; the name/code pair is only the initial credential locator."""
    logout()
    name, code = (student_name or "").strip(), (student_code or "").strip()
    if not name or not code or not password: return None
    code_rows = db.q("SELECT id,name,code FROM students WHERE active=1 AND lower(trim(code))=lower(trim(?))", (code,))
    rows = [row for row in code_rows if (row["name"] or "").strip().casefold() == name.casefold()]
    if len(rows) != 1: return None
    student = rows[0]
    account = db.q("SELECT password_hash,must_change FROM student_accounts WHERE student_id=?", (student["id"],))
    if not account:
        # The requested name + ID starter credential is one-time; force replacement before portal access.
        if not hmac.compare_digest(code.casefold(), password.strip().casefold()): return None
        db.run("INSERT INTO student_accounts(student_id,password_hash,must_change,updated_at) VALUES(?,?,1,?)",
               (student["id"], _student_hash(password.strip()), time.time()))
        must_change = True
    else:
        if not _student_password_matches(account[0]["password_hash"], password): return None
        must_change = bool(account[0]["must_change"])
    _new_session(str(student["id"]), "student", student["id"], must_change)
    return "student"


def change_student_password(db, new_password):
    sid = current_student_id()
    if current_role() != "student" or sid is None: raise PermissionError("Student login is required.")
    new_password = str(new_password or "")
    if len(new_password) < 10 or len(new_password) > 256:
        raise ValueError("Choose a password between 10 and 256 characters.")
    db.run("UPDATE student_accounts SET password_hash=?,must_change=0,updated_at=? WHERE student_id=?",
           (_student_hash(new_password), time.time(), sid))
    _session["must_change"] = False


def logout():
    _session.update(user=None, role=None, student_id=None, must_change=False, logged_in_at=0.0)


def current_user():
    _expire_session()
    return _session["user"]


def current_role():
    _expire_session()
    return _session["role"]


def _expire_session():
    if _session["role"] and time.time() - _session["logged_in_at"] > SESSION_MAX_AGE_SECONDS:
        logout()


def current_student_id():
    _expire_session()
    return _session["student_id"] if _session["role"] == "student" else None


def student_must_change_password():
    _expire_session()
    return _session["role"] == "student" and _session["must_change"]


def can_access_class(db, class_id):
    role = current_role()
    if role == "admin": return bool(db.q("SELECT 1 FROM classes WHERE id=?", (class_id,)))
    if role == "faculty": return int(class_id) in db.faculty_class_ids(current_user())
    sid = current_student_id()
    return bool(sid is not None and db.q("SELECT 1 FROM students WHERE id=? AND class_id=? AND active=1", (sid, class_id)))


def is_view_only():
    return current_role() == "student"


def can_edit_session(session_created_at=None, session_date=None, db=None, class_id=None):
    """
    Return True if the currently logged-in user may edit this saved session.
    Admin: always.
    Faculty: only in an assigned class and during the 30 local calendar days after session date.
    Student: never (view-only).
    """
    role = current_role()
    if role == "admin":
        return True
    if role == "faculty":
        if db is not None and class_id is not None and not can_access_class(db, class_id): return False
        try:
            day = date.fromisoformat(session_date) if session_date else datetime.fromtimestamp(session_created_at).date()
            age = (date.today() - day).days
            return 0 <= age <= 30
        except (ValueError, TypeError, OSError):
            return False
    return False
