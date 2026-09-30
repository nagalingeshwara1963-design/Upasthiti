"""Attendance maths shared by the calendar, dashboard and reports.
Rule: Present and Late count as attended. Excused and Leave/OD are excluded from the
denominator (the student is not held to that session). Absent counts against the student."""
from . import config

ATTENDED = {"P", "L"}
EXCUSED = {"E", "OD"}
LABEL = {"P": "Present", "A": "Absent", "L": "Late", "E": "Excused", "OD": "Leave / OD"}


def pct(attended, total):
    return None if total <= 0 else 100.0 * attended / total


def counts(statuses):
    a = sum(1 for s in statuses if s in ATTENDED)
    ex = sum(1 for s in statuses if s in EXCUSED)
    ab = sum(1 for s in statuses if s == "A")
    return {"attended": a, "excused": ex, "absent": ab, "total": len(statuses), "counted": len(statuses) - ex,
            "pct": pct(a, len(statuses) - ex)}


def level(p, warn=config.LOW_ATTENDANCE_WARN, limit=config.LOW_ATTENDANCE_LIMIT):
    """'ok' | 'warn' | 'critical' | None (no data)."""
    if p is None: return None
    if p < limit: return "critical"
    if p < warn: return "warn"
    return "ok"


def limits(db):
    return db.get("limit_warn", config.LOW_ATTENDANCE_WARN), db.get("limit_critical", config.LOW_ATTENDANCE_LIMIT)


def session_summary(db, sid):
    return counts([r["status"] for r in db.session_rows(sid)])


def day_summary(db, class_id, date):
    sts = []
    for s in db.sessions_on(class_id, date):
        sts += [r["status"] for r in db.session_rows(s["id"])]
    return counts(sts) if sts else None


def month_students(db, class_id, year, month):
    """Per-student totals for a month: list of dicts sorted by code."""
    sess = db.sessions_in_month(class_id, year, month)
    agg = {}
    for s in sess:
        for r in db.session_rows(s["id"]):
            a = agg.setdefault(r["code"], {"code": r["code"], "name": r["name"], "sts": []})
            a["sts"].append(r["status"])
    out = []
    warn, lim = limits(db)
    for c in sorted(agg):
        k = counts(agg[c]["sts"]); k.update(code=c, name=agg[c]["name"], level=level(k["pct"], warn, lim))
        out.append(k)
    return out, len(sess)


def range_students(db, class_id, start, end, include_archived=False):
    """Per-student attendance totals for an inclusive ISO date range."""
    held = db.q("SELECT COUNT(*) AS n FROM sessions WHERE class_id=? AND date>=? AND date<=?", (class_id, start, end))[0]["n"]
    students = db.students(class_id, include_archived=include_archived)
    statuses = {s["id"]: [] for s in students}
    absent_dates = {s["id"]: [] for s in students}
    subjects = {s["id"]: set() for s in students}
    for r in db.q("""SELECT a.student_id,a.status,ses.date,ses.subject FROM attendance a
                      JOIN sessions ses ON ses.id=a.session_id
                      WHERE ses.class_id=? AND ses.date>=? AND ses.date<=?""", (class_id, start, end)):
        statuses.setdefault(r["student_id"], []).append(r["status"])
        if r["status"] == "A": absent_dates.setdefault(r["student_id"], []).append(r["date"])
        if r["subject"]: subjects.setdefault(r["student_id"], set()).add(r["subject"])
    warn, lim = limits(db)
    out = []
    for s in students:
        k = counts(statuses.get(s["id"], []))
        k.update(id=s["id"], code=s["code"], name=s["name"], level=level(k["pct"], warn, lim),
                 absent_dates=absent_dates.get(s["id"], []), subjects=sorted(subjects.get(s["id"], set())))
        out.append(k)
    return out, held


def student_range(db, student_id, start, end):
    """Same summary rule as reports, scoped to one student and inclusive dates."""
    records = db.q(
        """SELECT a.status FROM attendance a JOIN sessions ses ON ses.id=a.session_id
           WHERE a.student_id=? AND ses.date>=? AND ses.date<=? ORDER BY ses.date,ses.time,ses.id""",
        (student_id, start, end))
    statuses = [r["status"] for r in records]
    summary = counts(statuses)
    summary["absent_dates"] = [r["date"] for r in db.q(
        """SELECT ses.date FROM attendance a JOIN sessions ses ON ses.id=a.session_id
           WHERE a.student_id=? AND a.status='A' AND ses.date>=? AND ses.date<=? ORDER BY ses.date,ses.time,ses.id""",
        (student_id, start, end))]
    summary["subjects"] = [r["subject"] for r in db.q(
        """SELECT DISTINCT ses.subject FROM attendance a JOIN sessions ses ON ses.id=a.session_id
           WHERE a.student_id=? AND ses.date>=? AND ses.date<=? AND ses.subject IS NOT NULL AND ses.subject<>''
           ORDER BY ses.subject""", (student_id, start, end))]
    summary["subjects"] = [r["subject"] for r in db.q(
        """SELECT DISTINCT ses.subject FROM attendance a JOIN sessions ses ON ses.id=a.session_id
           WHERE a.student_id=? AND ses.date>=? AND ses.date<=? AND ses.subject IS NOT NULL AND ses.subject<>''
           ORDER BY ses.subject""", (student_id, start, end))]
    rows = db.q("SELECT class_id FROM students WHERE id=?", (student_id,))
    summary["held"] = db.q("SELECT COUNT(*) AS n FROM sessions WHERE class_id=? AND date>=? AND date<=?",
                           (rows[0]["class_id"], start, end))[0]["n"] if rows else 0
    return summary
