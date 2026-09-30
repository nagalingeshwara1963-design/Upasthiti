"""Database maintenance: finds and (optionally) fixes data-integrity problems that can
build up over time - a student deleted after their attendance was recorded, an enrollment
photo file moved/deleted outside the app, or a class's saved face data drifting out of
sync with its student list. Never runs automatically; always shown to the admin first."""
import json
from pathlib import Path
from . import config


def scan(db):
    """Returns a dict describing every issue found. Nothing is changed."""
    issues = {"orphan_attendance": [], "orphan_edits": [], "missing_photo_files": [], "gallery_mismatch": []}

    issues["orphan_attendance"] = db.q(
        "SELECT a.id, a.session_id, a.student_id, s.date, s.subject FROM attendance a "
        "LEFT JOIN students st ON st.id = a.student_id "
        "JOIN sessions s ON s.id = a.session_id WHERE st.id IS NULL")

    issues["orphan_edits"] = db.q(
        "SELECT e.id FROM edits e LEFT JOIN students st ON st.id = e.student_id WHERE st.id IS NULL")

    photos = db.q("SELECT ep.id, ep.path, st.code, st.class_id FROM enroll_photos ep JOIN students st ON st.id = ep.student_id")
    issues["missing_photo_files"] = [p for p in photos if not Path(p["path"]).exists()]

    for c in db.classes():
        gpath = config.DATA / "galleries" / f"class_{c['id']}.json"
        db_codes = {s["code"] for s in db.students(c["id"])}
        gal_codes = set()
        if gpath.exists():
            try:
                gal_codes = set(json.loads(gpath.read_text(encoding="utf-8")).get("students", {}).keys())
            except Exception:
                pass
        missing_in_gallery = sorted(db_codes - gal_codes)   # enrolled but no face data - can't be auto-fixed
        stale_in_gallery = sorted(gal_codes - db_codes)     # face data for a student that no longer exists
        if missing_in_gallery or stale_in_gallery:
            issues["gallery_mismatch"].append({"class": c["name"], "class_id": c["id"],
                                               "missing_in_gallery": missing_in_gallery, "stale_in_gallery": stale_in_gallery})
    return issues


def is_clean(issues):
    return not (issues["orphan_attendance"] or issues["orphan_edits"] or issues["missing_photo_files"]
                or any(m["stale_in_gallery"] for m in issues["gallery_mismatch"]))
    # note: missing_in_gallery is a real problem too, but has no automatic fix - it is
    # reported to the admin (re-enroll photos for that student) rather than counted here.


def fix(db, issues):
    """Applies safe, automatic fixes. Returns a count of what was changed.
    Deleting an orphaned attendance row permanently removes that historic entry from
    reports - the caller must warn the admin about this before calling fix()."""
    counts = {"orphan_attendance_removed": 0, "orphan_edits_removed": 0,
             "missing_photo_rows_removed": 0, "stale_gallery_entries_removed": 0}
    for r in issues["orphan_attendance"]:
        db.run("DELETE FROM attendance WHERE id=?", (r["id"],)); counts["orphan_attendance_removed"] += 1
    for r in issues["orphan_edits"]:
        db.run("DELETE FROM edits WHERE id=?", (r["id"],)); counts["orphan_edits_removed"] += 1
    for p in issues["missing_photo_files"]:
        db.run("DELETE FROM enroll_photos WHERE id=?", (p["id"],)); counts["missing_photo_rows_removed"] += 1
    for m in issues["gallery_mismatch"]:
        if not m["stale_in_gallery"]:
            continue
        gpath = config.DATA / "galleries" / f"class_{m['class_id']}.json"
        try:
            data = json.loads(gpath.read_text(encoding="utf-8"))
            for code in m["stale_in_gallery"]:
                data.get("students", {}).pop(code, None)
            gpath.write_text(json.dumps(data), encoding="utf-8")
            counts["stale_gallery_entries_removed"] += len(m["stale_in_gallery"])
        except Exception as e:
            print("could not clean gallery for class", m["class_id"], ":", e)
    return counts
