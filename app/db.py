"""SQLite storage for attendance records, settings, student email recipients and delivery history."""
import sqlite3, json, time, threading
from pathlib import Path
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS classes(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
    college TEXT DEFAULT '', year TEXT DEFAULT '', branch TEXT DEFAULT '', section TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL, code TEXT NOT NULL,
    name TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1, archived_at REAL, UNIQUE(class_id, code));
CREATE TABLE IF NOT EXISTS enroll_photos(id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lists(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL, UNIQUE(kind, value));
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL, date TEXT, time TEXT,
    faculty TEXT, subject TEXT, period TEXT, mode TEXT, threshold REAL, created_at REAL, photos_json TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, student_id INTEGER NOT NULL,
    status TEXT NOT NULL, confidence REAL, dist REAL, flags TEXT DEFAULT '', note TEXT DEFAULT '', edited INTEGER DEFAULT 0,
    UNIQUE(session_id, student_id));
CREATE TABLE IF NOT EXISTS edits(id INTEGER PRIMARY KEY, session_id INTEGER, student_id INTEGER, old TEXT, new TEXT,
    by_user TEXT, at REAL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS student_email_recipients(
    id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, email TEXT NOT NULL COLLATE NOCASE,
    label TEXT DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    UNIQUE(student_id, email));
CREATE INDEX IF NOT EXISTS idx_student_email_student ON student_email_recipients(student_id);
CREATE TABLE IF NOT EXISTS email_deliveries(
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE, recipient TEXT NOT NULL DEFAULT '',
    recipient_label TEXT DEFAULT '', student_id INTEGER, student_code TEXT DEFAULT '',
    student_name TEXT DEFAULT '', session_id INTEGER, class_id INTEGER,
    report_from TEXT DEFAULT '', report_to TEXT DEFAULT '', context_json TEXT DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0, permanent INTEGER NOT NULL DEFAULT 0,
    failure TEXT DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_email_delivery_status ON email_deliveries(status, permanent);
CREATE INDEX IF NOT EXISTS idx_email_delivery_session ON email_deliveries(session_id);
CREATE TABLE IF NOT EXISTS email_schedules(
    id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL, report_from TEXT NOT NULL, report_to TEXT NOT NULL,
    send_on TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, last_run TEXT DEFAULT '',
    created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_email_schedule_due ON email_schedules(enabled, send_on, last_run);
CREATE TABLE IF NOT EXISTS student_accounts(
    student_id INTEGER PRIMARY KEY, password_hash TEXT NOT NULL,
    must_change INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS faculty_class_access(
    username TEXT NOT NULL, class_id INTEGER NOT NULL, created_at REAL NOT NULL,
    PRIMARY KEY(username,class_id));
CREATE TABLE IF NOT EXISTS recovery_goals(
    student_id INTEGER PRIMARY KEY, target REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attendance_review_requests(
    id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, session_id INTEGER NOT NULL,
    attendance_id INTEGER NOT NULL, original_status TEXT NOT NULL, status TEXT NOT NULL,
    reason TEXT NOT NULL, explanation TEXT DEFAULT '', created_at REAL NOT NULL,
    updated_at REAL NOT NULL, reviewer TEXT DEFAULT '', resolution TEXT DEFAULT '',
    resolution_reason TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_review_status ON attendance_review_requests(status,created_at);
CREATE INDEX IF NOT EXISTS idx_review_student ON attendance_review_requests(student_id,created_at);
CREATE TABLE IF NOT EXISTS attendance_review_events(
    id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, event TEXT NOT NULL,
    actor TEXT NOT NULL, old_status TEXT DEFAULT '', new_status TEXT DEFAULT '',
    reason TEXT DEFAULT '', at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_review_events_request ON attendance_review_events(request_id,id);
"""


class DB:
    def __init__(self, path=None):
        config.ensure_dirs()
        self.con = sqlite3.connect(str(path or config.DB_PATH), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.con.executescript(SCHEMA)
        cols = [r["name"] for r in self.q("PRAGMA table_info(attendance)")]
        if "auto_status" not in cols:
            self.con.execute("ALTER TABLE attendance ADD COLUMN auto_status TEXT DEFAULT ''")
        student_cols = [r["name"] for r in self.q("PRAGMA table_info(students)")]
        if "active" not in student_cols:
            self.con.execute("ALTER TABLE students ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        if "archived_at" not in student_cols:
            self.con.execute("ALTER TABLE students ADD COLUMN archived_at REAL")
        self.con.commit()

    def q(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def run(self, sql, args=()):
        with self._lock:
            cur = self.con.execute(sql, args); self.con.commit(); return cur.lastrowid

    # settings
    def get(self, key, default=None):
        r = self.q("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(r[0]["value"]) if r else default

    def put(self, key, value):
        self.run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value)))

    # dropdown lists (faculty, subject, period, ...) - type once, pick forever
    def list_values(self, kind):
        return [r["value"] for r in self.q("SELECT value FROM lists WHERE kind=? ORDER BY value", (kind,))]

    def add_list_value(self, kind, value):
        value = (value or "").strip()
        if value:
            self.run("INSERT OR IGNORE INTO lists(kind,value) VALUES(?,?)", (kind, value))

    # classes / students
    def classes(self):
        return self.q("SELECT * FROM classes ORDER BY name")

    def add_class(self, name, college="", year="", branch="", section=""):
        return self.run("INSERT INTO classes(name,college,year,branch,section) VALUES(?,?,?,?,?)",
                        (name.strip(), college, year, branch, section))

    def students(self, class_id, include_archived=False):
        sql = "SELECT * FROM students WHERE class_id=?"
        if not include_archived:
            sql += " AND active=1"
        return self.q(sql + " ORDER BY code", (class_id,))

    def student_active(self, student_id):
        return bool(self.q("SELECT 1 FROM students WHERE id=? AND active=1", (student_id,)))

    def save_student(self, class_id, code, name, photo_paths, email_recipients=()):
        self.run("INSERT INTO students(class_id,code,name,active,archived_at) VALUES(?,?,?,1,NULL) ON CONFLICT(class_id,code) DO UPDATE SET name=excluded.name,active=1,archived_at=NULL",
                 (class_id, code, name))
        sid = self.q("SELECT id FROM students WHERE class_id=? AND code=?", (class_id, code))[0]["id"]
        for p in photo_paths:
            self.run("INSERT INTO enroll_photos(student_id,path) VALUES(?,?)", (sid, str(p)))
        for recipient in email_recipients:
            self.add_email_recipient(sid, recipient["email"], recipient.get("label", ""), recipient.get("enabled", True))
        return sid

    def student_photos(self, class_id, code):
        s = self.q("SELECT id FROM students WHERE class_id=? AND code=?", (class_id, code))
        if not s: return []
        return [r["path"] for r in self.q("SELECT path FROM enroll_photos WHERE student_id=? ORDER BY id", (s[0]["id"],))]

    def delete_enroll_photo(self, class_id, code, path):
        s = self.q("SELECT id FROM students WHERE class_id=? AND code=?", (class_id, code))
        if s:
            self.run("DELETE FROM enroll_photos WHERE student_id=? AND path=?", (s[0]["id"], path))

    def archive_student(self, class_id, code):
        """Deactivate a student without deleting attendance, edit, or review history."""
        s = self.q("SELECT id FROM students WHERE class_id=? AND code=? AND active=1", (class_id, code))
        if s:
            with self._lock:
                try:
                    now = time.time()
                    self.con.execute("UPDATE students SET active=0,archived_at=? WHERE id=?", (now, s[0]["id"]))
                    self.con.execute("DELETE FROM student_email_recipients WHERE student_id=?", (s[0]["id"],))
                    self.con.execute("DELETE FROM student_accounts WHERE student_id=?", (s[0]["id"],))
                    self.con.execute("DELETE FROM recovery_goals WHERE student_id=?", (s[0]["id"],))
                    self.con.commit()
                except Exception:
                    self.con.rollback()
                    raise

    def delete_student(self, class_id, code):
        """Backward-compatible alias; student removal now archives the identity."""
        return self.archive_student(class_id, code)

    # ---- email recipients and delivery history ----
    def email_recipients(self, student_id, enabled_only=False):
        sql = "SELECT * FROM student_email_recipients WHERE student_id=?"
        if enabled_only: sql += " AND enabled=1"
        return self.q(sql + " ORDER BY id", (student_id,))

    def add_email_recipient(self, student_id, email, label="", enabled=True):
        from .email_service import normalize_email
        email = normalize_email(email)
        now = time.time()
        with self._lock:
            cur = self.con.execute("INSERT INTO student_email_recipients(student_id,email,label,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                                   (student_id, email, label, int(bool(enabled)), now, now))
            self.con.commit()
            return cur.lastrowid

    def update_email_recipient(self, recipient_id, email, label, enabled):
        from .email_service import normalize_email
        email = normalize_email(email)
        with self._lock:
            cur = self.con.execute("UPDATE student_email_recipients SET email=?,label=?,enabled=?,updated_at=? WHERE id=?",
                                   (email, label, int(bool(enabled)), time.time(), recipient_id))
            self.con.commit()
            return cur.rowcount > 0

    def remove_email_recipient(self, recipient_id):
        with self._lock:
            cur = self.con.execute("DELETE FROM student_email_recipients WHERE id=?", (recipient_id,))
            self.con.commit()
            return cur.rowcount > 0

    def create_email_delivery(self, values):
        now = time.time()
        fields = ("kind", "status", "dedupe_key", "recipient", "recipient_label", "student_id",
                  "student_code", "student_name", "session_id", "class_id", "report_from", "report_to", "context_json")
        nullable = {"student_id", "session_id", "class_id"}
        vals = [values.get(k, None if k in nullable else ("{}" if k == "context_json" else "")) for k in fields]
        with self._lock:
            self.con.execute("INSERT OR IGNORE INTO email_deliveries(" + ",".join(fields) + ",created_at,updated_at) VALUES(" +
                             ",".join("?" for _ in fields) + ",?,?)", (*vals, now, now))
            self.con.commit()
            row = self.con.execute("SELECT * FROM email_deliveries WHERE dedupe_key=?", (values["dedupe_key"],)).fetchone()
            return dict(row) if row else None

    def email_delivery(self, delivery_id):
        rows = self.q("SELECT * FROM email_deliveries WHERE id=?", (delivery_id,))
        return rows[0] if rows else None

    def update_email_delivery(self, delivery_id, status, failure="", permanent=None, attempt=False):
        with self._lock:
            sql = "UPDATE email_deliveries SET status=?,failure=?,updated_at=?"
            args = [status, failure[:500], time.time()]
            if permanent is not None:
                sql += ",permanent=?"; args.append(int(bool(permanent)))
            if attempt:
                sql += ",attempts=attempts+1"
            sql += " WHERE id=?"; args.append(delivery_id)
            self.con.execute(sql, args); self.con.commit()

    def list_email_deliveries(self, limit=100, session_id=None):
        if session_id is not None:
            return self.q("SELECT * FROM email_deliveries WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, limit))
        return self.q("SELECT * FROM email_deliveries ORDER BY id DESC LIMIT ?", (limit,))

    def student_email_history(self, student_id, limit=20):
        return self.q("SELECT * FROM email_deliveries WHERE student_id=? ORDER BY id DESC LIMIT ?", (student_id, limit))

    # ---- explicit, editable one-shot email schedules ----
    def email_schedules(self, class_id=None):
        if class_id is None:
            return self.q("SELECT es.*,c.name AS class_name FROM email_schedules es JOIN classes c ON c.id=es.class_id ORDER BY send_on,id")
        return self.q("SELECT es.*,c.name AS class_name FROM email_schedules es JOIN classes c ON c.id=es.class_id WHERE es.class_id=? ORDER BY send_on,id", (class_id,))

    def add_email_schedule(self, class_id, report_from, report_to, send_on):
        now = time.time()
        return self.run("INSERT INTO email_schedules(class_id,report_from,report_to,send_on,enabled,last_run,created_at,updated_at) VALUES(?,?,?,?,1,'',?,?)",
                        (class_id, report_from, report_to, send_on, now, now))

    def update_email_schedule(self, schedule_id, class_id, report_from, report_to, send_on, enabled):
        return self.run("UPDATE email_schedules SET class_id=?,report_from=?,report_to=?,send_on=?,enabled=?,last_run='',updated_at=? WHERE id=?",
                        (class_id, report_from, report_to, send_on, int(bool(enabled)), time.time(), schedule_id))

    def set_email_schedule_enabled(self, schedule_id, enabled):
        return self.run("UPDATE email_schedules SET enabled=?,updated_at=? WHERE id=?",
                        (int(bool(enabled)), time.time(), schedule_id))

    def delete_email_schedule(self, schedule_id):
        return self.run("DELETE FROM email_schedules WHERE id=?", (schedule_id,))

    def due_email_schedules(self, today):
        return self.q("SELECT * FROM email_schedules WHERE enabled=1 AND send_on<=? AND last_run<>send_on ORDER BY send_on,id", (today,))

    def mark_email_schedule_run(self, schedule_id, send_on):
        return self.run("UPDATE email_schedules SET last_run=?,updated_at=? WHERE id=? AND last_run<>?",
                        (send_on, time.time(), schedule_id, send_on))

    def retryable_email_deliveries(self, delivery_ids=None):
        if delivery_ids is not None:
            ids = [int(x) for x in delivery_ids]
            if not ids: return []
            return self.q("SELECT * FROM email_deliveries WHERE status='failed' AND permanent=0 AND id IN (" +
                          ",".join("?" for _ in ids) + ") ORDER BY id", ids)
        return self.q("SELECT * FROM email_deliveries WHERE status='failed' AND permanent=0 ORDER BY id")

    def pending_email_deliveries(self):
        return self.q("SELECT * FROM email_deliveries WHERE status='pending' ORDER BY id")

    def recover_email_deliveries(self):
        """Requeue only known-unsent jobs; leave interrupted sends as outcome-unknown."""
        with self._lock:
            self.con.execute("UPDATE email_deliveries SET status='unknown',failure='Previous process ended while delivery was in progress',updated_at=? WHERE status='sending'", (time.time(),))
            self.con.commit()

    # sessions / attendance
    def save_session(self, class_id, meta, records):
        """Save the session and all marks atomically; a partial save is never visible."""
        with self._lock:
            try:
                cur = self.con.execute("INSERT INTO sessions(class_id,date,time,faculty,subject,period,mode,threshold,created_at,photos_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (class_id, meta["date"], meta["time"], meta["faculty"], meta["subject"], meta["period"],
                     meta.get("mode", ""), meta.get("threshold", 0), time.time(), json.dumps(meta.get("photos", []))))
                sid = cur.lastrowid
                self.con.executemany("INSERT INTO attendance(session_id,student_id,status,confidence,dist,flags,note,auto_status,edited) VALUES(?,?,?,?,?,?,?,?,?)",
                    [(sid, r["student_id"], r["status"], r.get("confidence", 0), r.get("dist"), ",".join(r.get("flags", [])),
                      r.get("note", ""), r.get("auto_status", r["status"]), int(r.get("auto_status", r["status"]) != r["status"])) for r in records])
                self.con.commit()
                return sid
            except Exception:
                self.con.rollback()
                raise

    # ---- reading sessions for reports ----
    def session(self, sid):
        r = self.q("SELECT s.*, c.name AS class_name FROM sessions s JOIN classes c ON c.id=s.class_id WHERE s.id=?", (sid,))
        return r[0] if r else None

    def session_rows(self, sid):
        return self.q("SELECT a.*, st.code, st.name FROM attendance a JOIN students st ON st.id=a.student_id WHERE a.session_id=? ORDER BY st.code", (sid,))

    def sessions_on(self, class_id, date):
        return self.q("SELECT * FROM sessions WHERE class_id=? AND date=? ORDER BY time, id", (class_id, date))

    def sessions_in_month(self, class_id, year, month):
        p = f"{year:04d}-{month:02d}-%"
        return self.q("SELECT * FROM sessions WHERE class_id=? AND date LIKE ? ORDER BY date, time, id", (class_id, p))

    def recent_sessions(self, class_id=None, n=6):
        if class_id:
            return self.q("SELECT s.*, c.name AS class_name FROM sessions s JOIN classes c ON c.id=s.class_id WHERE class_id=? ORDER BY created_at DESC LIMIT ?", (class_id, n))
        return self.q("SELECT s.*, c.name AS class_name FROM sessions s JOIN classes c ON c.id=s.class_id ORDER BY created_at DESC LIMIT ?", (n,))

    def change_status(self, sid, student_id, new_status, by_user="admin"):
        if new_status not in {"P", "A", "L", "E", "OD"}:
            raise ValueError("Invalid attendance status.")
        with self._lock:
            try:
                row = self.con.execute("SELECT status FROM attendance WHERE session_id=? AND student_id=?", (sid, student_id)).fetchone()
                if not row or row["status"] == new_status: return False
                now = time.time()
                self.con.execute("INSERT INTO edits(session_id,student_id,old,new,by_user,at) VALUES(?,?,?,?,?,?)", (sid, student_id, row["status"], new_status, by_user, now))
                self.con.execute("UPDATE attendance SET status=?, edited=1 WHERE session_id=? AND student_id=?", (new_status, sid, student_id))
                self.con.commit()
                return True
            except Exception:
                self.con.rollback()
                raise

    # ---- role-scoped account mappings and review requests ----
    def faculty_class_ids(self, username):
        return [r["class_id"] for r in self.q("SELECT class_id FROM faculty_class_access WHERE username=? ORDER BY class_id", (username.casefold(),))]

    def set_faculty_classes(self, username, class_ids):
        username = username.strip().casefold(); now = time.time()
        with self._lock:
            try:
                self.con.execute("DELETE FROM faculty_class_access WHERE username=?", (username,))
                self.con.executemany("INSERT INTO faculty_class_access(username,class_id,created_at) VALUES(?,?,?)",
                                     [(username, int(cid), now) for cid in dict.fromkeys(class_ids)])
                self.con.commit()
            except Exception:
                self.con.rollback(); raise

    def set_recovery_goal(self, student_id, target):
        target = float(target)
        if not 0 <= target <= 100: raise ValueError("Target must be between 0 and 100%.")
        return self.run("INSERT INTO recovery_goals(student_id,target,updated_at) VALUES(?,?,?) ON CONFLICT(student_id) DO UPDATE SET target=excluded.target,updated_at=excluded.updated_at",
                        (student_id, target, time.time()))

    def recovery_goal(self, student_id):
        rows = self.q("SELECT target FROM recovery_goals WHERE student_id=?", (student_id,))
        return rows[0]["target"] if rows else None

    def create_review_request(self, student_id, session_id, attendance_id, original_status, reason, explanation, escalated=False):
        now = time.time(); status = "Escalated" if escalated else "Pending"
        with self._lock:
            try:
                active = self.con.execute("SELECT * FROM attendance_review_requests WHERE student_id=? AND session_id=? AND status IN ('Pending','Under Review','Escalated')", (student_id, session_id)).fetchone()
                if active: return dict(active), False
                cur = self.con.execute("INSERT INTO attendance_review_requests(student_id,session_id,attendance_id,original_status,status,reason,explanation,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (student_id, session_id, attendance_id, original_status, status, reason, explanation[:1000], now, now))
                rid = cur.lastrowid
                self.con.execute("INSERT INTO attendance_review_events(request_id,event,actor,old_status,new_status,reason,at) VALUES(?,?,?,?,?,?,?)",
                    (rid, "submitted", f"student:{student_id}", "", status, reason, now))
                row = self.con.execute("SELECT * FROM attendance_review_requests WHERE id=?", (rid,)).fetchone()
                self.con.commit(); return dict(row), True
            except Exception:
                self.con.rollback(); raise

    def transition_review_request(self, request_id, new_status, actor, reason="", attendance_status=None):
        allowed = {"Under Review", "Resolved — Changed", "Resolved — Kept", "Dismissed", "Escalated"}
        if new_status not in allowed: raise ValueError("Invalid review-request status.")
        with self._lock:
            try:
                row = self.con.execute("SELECT * FROM attendance_review_requests WHERE id=?", (request_id,)).fetchone()
                if not row: raise ValueError("Review request not found.")
                if row["status"] not in ("Pending", "Under Review", "Escalated"): return dict(row)
                if attendance_status is not None:
                    if new_status != "Resolved — Changed": raise ValueError("Attendance can change only when resolving a request as changed.")
                    current = self.con.execute("SELECT status FROM attendance WHERE id=? AND session_id=? AND student_id=?",
                        (row["attendance_id"], row["session_id"], row["student_id"])).fetchone()
                    if not current: raise ValueError("The original attendance entry no longer exists.")
                    if current["status"] != attendance_status:
                        now = time.time()
                        self.con.execute("INSERT INTO edits(session_id,student_id,old,new,by_user,at) VALUES(?,?,?,?,?,?)",
                            (row["session_id"], row["student_id"], current["status"], attendance_status, actor, now))
                        self.con.execute("UPDATE attendance SET status=?,edited=1 WHERE id=?", (attendance_status, row["attendance_id"]))
                now = time.time()
                self.con.execute("UPDATE attendance_review_requests SET status=?,updated_at=?,reviewer=?,resolution=?,resolution_reason=? WHERE id=?",
                    (new_status, now, actor, attendance_status or "", reason[:1000], request_id))
                self.con.execute("INSERT INTO attendance_review_events(request_id,event,actor,old_status,new_status,reason,at) VALUES(?,?,?,?,?,?,?)",
                    (request_id, "resolved" if new_status.startswith("Resolved") else new_status.casefold(), actor, row["status"], new_status, reason[:1000], now))
                updated = self.con.execute("SELECT * FROM attendance_review_requests WHERE id=?", (request_id,)).fetchone()
                self.con.commit(); return dict(updated)
            except Exception:
                self.con.rollback(); raise

    def list_review_requests(self, student_id=None, class_ids=None, statuses=None):
        sql = "SELECT rr.*,s.date,s.time,s.subject,s.period,s.class_id,c.name AS class_name,st.code,st.name FROM attendance_review_requests rr JOIN sessions s ON s.id=rr.session_id JOIN classes c ON c.id=s.class_id JOIN students st ON st.id=rr.student_id WHERE 1=1"
        args = []
        if student_id is not None: sql += " AND rr.student_id=?"; args.append(student_id)
        if class_ids is not None:
            ids = list(class_ids)
            if not ids: return []
            sql += " AND s.class_id IN (" + ",".join("?" for _ in ids) + ")"; args.extend(ids)
        if statuses:
            sql += " AND rr.status IN (" + ",".join("?" for _ in statuses) + ")"; args.extend(statuses)
        return self.q(sql + " ORDER BY CASE rr.status WHEN 'Pending' THEN 0 WHEN 'Escalated' THEN 1 ELSE 2 END,rr.created_at", args)

    def review_events(self, request_id):
        return self.q("SELECT * FROM attendance_review_events WHERE request_id=? ORDER BY id", (request_id,))

    def edits_for(self, sid):
        return self.q("SELECT e.*, st.code, st.name FROM edits e JOIN students st ON st.id=e.student_id WHERE e.session_id=? ORDER BY e.at", (sid,))

    # ---- audit / history ----
    def all_edits(self):
        return self.q("""SELECT e.*, st.code, st.name, s.date, s.time, s.subject, s.period, c.name AS class_name
                          FROM edits e
                          JOIN students st ON st.id = e.student_id
                          JOIN sessions s ON s.id = e.session_id
                          JOIN classes c ON c.id = s.class_id
                          ORDER BY e.at DESC""")

    def student_history(self, class_id, code):
        s = self.q("SELECT id FROM students WHERE class_id=? AND code=?", (class_id, code))
        if not s: return []
        return self.q("""SELECT a.status, a.confidence, a.dist, a.edited, ses.date, ses.time, ses.subject, ses.period, ses.id AS session_id
                          FROM attendance a JOIN sessions ses ON ses.id = a.session_id
                          WHERE a.student_id=? ORDER BY ses.date DESC, ses.time DESC""", (s[0]["id"],))
