"""Deterministic attendance recovery calculations and role-scoped summaries."""
from __future__ import annotations

import math
from . import stats


def plan(attended, absent, target):
    """Calculate exact attendance scenarios using the app's counted-session rule."""
    attended, absent = int(attended), int(absent)
    target = float(target)
    if attended < 0 or absent < 0 or not 0 <= target <= 100:
        raise ValueError("Attendance counts must be non-negative and target must be 0–100%.")
    held = attended + absent
    current = stats.pct(attended, held)
    rate = target / 100
    if not held:
        needed = None
    elif target == 0 or current is not None and current >= target:
        needed = 0
    elif target == 100:
        needed = None
    else:
        needed = math.ceil(max(0, (rate * held - attended) / (1 - rate)) - 1e-12)
    if not held:
        safe_to_miss = None
    elif target == 0:
        safe_to_miss = None
    elif current is None or current < target:
        safe_to_miss = 0
    else:
        safe_to_miss = max(0, math.floor(attended / rate - held + 1e-12))
    return {"attended": attended, "absent": absent, "held": held, "current": current,
            "target": target, "classes_needed": needed, "safe_to_miss": safe_to_miss,
            "level": stats.level(current)}


def what_if(attended, absent, target, upcoming, attend_next, miss_next):
    upcoming, attend_next, miss_next = map(int, (upcoming, attend_next, miss_next))
    if min(upcoming, attend_next, miss_next) < 0 or attend_next + miss_next > upcoming:
        raise ValueError("Upcoming, attend, and miss values must be non-negative, and attend plus miss cannot exceed upcoming.")
    base = plan(attended, absent, target)
    projected = stats.pct(base["attended"] + attend_next,
                          base["held"] + attend_next + miss_next)
    return {"upcoming": upcoming, "attend": attend_next, "miss": miss_next,
            "unassigned": upcoming - attend_next - miss_next,
            "projected": projected, "assumption": "Only the explicitly assigned attend/miss outcomes are included."}


def student_summary(db, student_id, target=None):
    rows = db.q("SELECT id,class_id,code,name FROM students WHERE id=?", (student_id,))
    if not rows:
        raise ValueError("Student was not found.")
    student = rows[0]
    target = float(target if target is not None else db.get("limit_critical", 75))
    recs = db.q("""SELECT a.status,ses.subject,ses.date FROM attendance a
                   JOIN sessions ses ON ses.id=a.session_id WHERE a.student_id=?
                   ORDER BY ses.date,ses.time,ses.id""", (student_id,))
    all_counts = stats.counts([r["status"] for r in recs])
    overall = plan(all_counts["attended"], all_counts["absent"], target)
    subjects = {}
    for row in recs:
        subject = (row["subject"] or "Unspecified").strip() or "Unspecified"
        subjects.setdefault(subject, []).append(row["status"])
    subject_rows = []
    for name, statuses in sorted(subjects.items(), key=lambda pair: pair[0].casefold()):
        counted = stats.counts(statuses)
        result = plan(counted["attended"], counted["absent"], target)
        result.update(subject=name, excused=counted["excused"])
        subject_rows.append(result)
    return {"student": student, "overall": overall, "subjects": subject_rows,
            "recent": recs[-10:][::-1], "absences": [r for r in recs if r["status"] == "A"][-10:][::-1]}
