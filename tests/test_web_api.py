"""Integration and unit tests for Upasthiti FastAPI web endpoints.

All tests run against temporary SQLite test databases and mock email delivery.
Never uses production data or contacts external network endpoints.
"""
from datetime import date, datetime, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import auth, config, demo_mode, recovery, stats
from app.db import DB
from app.services import Service
from app.web import server
from app.web.server import app, SESSIONS, STAGED_PHOTOS, PHONE_SESSIONS


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="upasthiti-web-test-", ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_web.db"
        self.test_db = DB(self.db_path)
        self.test_svc = Service(self.test_db)

        # Clear global web session maps
        SESSIONS.clear()
        STAGED_PHOTOS.clear()
        PHONE_SESSIONS.clear()

        # Patch server singletons to test db and svc
        self.patch_db = patch.object(server, "db", self.test_db)
        self.patch_svc = patch.object(server, "svc", self.test_svc)
        self.patch_db.start()
        self.patch_svc.start()

        self.client = TestClient(app)

        # Setup test accounts & classes
        auth.set_password(self.test_db, "admin", "admin", "admin_password123")
        auth.set_password(self.test_db, "faculty", "prof_smith", "faculty_pw_456")

        self.class_1 = self.test_db.add_class("Computer Science A")
        self.class_2 = self.test_db.add_class("Mechanical Eng B")

        # Assign class_1 to faculty prof_smith
        self.test_db.set_faculty_classes("prof_smith", [self.class_1])

        # Save test students
        self.student_1 = self.test_db.save_student(self.class_1, "CS-01", "Alice Smith", [])
        self.student_2 = self.test_db.save_student(self.class_1, "CS-02", "Bob Jones", [])
        self.student_3 = self.test_db.save_student(self.class_2, "ME-01", "Charlie Brown", [])

    def tearDown(self):
        self.patch_svc.stop()
        self.patch_db.stop()
        auth.logout()
        try:
            self.test_db.con.close()
        except Exception:
            pass
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _login_admin(self):
        res = self.client.post("/api/auth/login", json={
            "role": "Admin",
            "username": "admin",
            "password": "admin_password123"
        })
        self.assertEqual(res.status_code, 200)
        return res.json()["token"]

    def _login_faculty(self):
        res = self.client.post("/api/auth/login", json={
            "role": "Faculty",
            "username": "prof_smith",
            "password": "faculty_pw_456"
        })
        self.assertEqual(res.status_code, 200)
        return res.json()["token"]

    def _login_student(self):
        res = self.client.post("/api/auth/login", json={
            "role": "Student",
            "student_name": "Alice Smith",
            "student_code": "CS-01",
            "password": "CS-01"
        })
        self.assertEqual(res.status_code, 200)
        token = res.json()["token"]
        # If password change required on first login, update it
        if res.json().get("must_change_password"):
            ch_res = self.client.post("/api/auth/student-change-password",
                                      headers={"Authorization": f"Bearer {token}"},
                                      json={"new_password": "NewStudentPassword789"})
            self.assertEqual(ch_res.status_code, 200)
        return token

    # 1. Unauthenticated Access Tests
    def test_unauthenticated_requests_are_rejected(self):
        res = self.client.get("/api/classes")
        self.assertEqual(res.status_code, 401)

        res = self.client.get("/api/reports/sessions")
        self.assertEqual(res.status_code, 401)

        res = self.client.get("/api/student/portal/summary")
        self.assertEqual(res.status_code, 401)

    # 2. Admin Capabilities & Class Creation
    def test_admin_access_and_class_creation(self):
        token = self._login_admin()
        headers = {"Authorization": f"Bearer {token}"}

        # Check me
        me_res = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.json()["role"], "admin")

        # Admin sees all classes
        c_res = self.client.get("/api/classes", headers=headers)
        self.assertEqual(c_res.status_code, 200)
        self.assertEqual(len(c_res.json()), 2)

        # Create new class
        create_res = self.client.post("/api/classes", headers=headers, json={"name": "Civil Eng C"})
        self.assertEqual(create_res.status_code, 200)
        self.assertTrue(create_res.json()["id"] > 0)

    # 3. Faculty Class Isolation
    def test_faculty_class_isolation(self):
        token = self._login_faculty()
        headers = {"Authorization": f"Bearer {token}"}

        # Faculty sees only assigned class_1
        c_res = self.client.get("/api/classes", headers=headers)
        self.assertEqual(c_res.status_code, 200)
        classes = c_res.json()
        self.assertEqual(len(classes), 1)
        self.assertEqual(classes[0]["id"], self.class_1)

        # Cannot view students in unassigned class_2
        unauth_students = self.client.get(f"/api/classes/{self.class_2}/students", headers=headers)
        self.assertEqual(unauth_students.status_code, 403)

        # Faculty cannot create classes
        new_c = self.client.post("/api/classes", headers=headers, json={"name": "Illegal Class"})
        self.assertEqual(new_c.status_code, 403)

    # 4. Student Isolation & IDOR Protection
    def test_student_isolation_and_idor_protection(self):
        token = self._login_student()
        headers = {"Authorization": f"Bearer {token}"}

        # Me endpoint returns student profile
        me_res = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.json()["role"], "student")
        self.assertEqual(me_res.json()["student_id"], self.student_1)

        # Student cannot list other students in the class
        st_res = self.client.get(f"/api/classes/{self.class_1}/students", headers=headers)
        self.assertEqual(st_res.status_code, 200)
        # Should return ONLY their own row
        students_returned = st_res.json()
        self.assertEqual(len(students_returned), 1)
        self.assertEqual(students_returned[0]["id"], self.student_1)

        # Student cannot access staff sessions endpoint
        rep_res = self.client.get("/api/reports/sessions", headers=headers)
        self.assertEqual(rep_res.status_code, 403)

        # Student cannot access another student's recovery summary
        other_rec = self.client.get(f"/api/recovery/student/{self.student_2}", headers=headers)
        self.assertEqual(other_rec.status_code, 403)

    # 5. Attendance Save & Audited Editing
    def test_attendance_save_and_audited_editing(self):
        admin_token = self._login_admin()
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Save session
        save_res = self.client.post("/api/attendance/save", headers=headers, json={
            "class_id": self.class_1,
            "date": "2026-09-20",
            "time": "10:00",
            "subject": "Algorithms",
            "faculty": "Prof. Smith",
            "period": "1",
            "records": [
                {"student_id": self.student_1, "status": "P"},
                {"student_id": self.student_2, "status": "A"},
            ]
        })
        self.assertEqual(save_res.status_code, 200)
        sid = save_res.json()["session_id"]
        self.assertTrue(sid > 0)

        # Inspect session
        detail_res = self.client.get(f"/api/reports/session/{sid}", headers=headers)
        self.assertEqual(detail_res.status_code, 200)
        records = detail_res.json()["records"]
        self.assertEqual(len(records), 2)

        # Edit attendance status (Student 2 changed from A to P)
        edit_res = self.client.post(f"/api/reports/session/{sid}/status",
                                    headers=headers,
                                    data={"student_id": str(self.student_2), "status": "P"})
        self.assertEqual(edit_res.status_code, 200)
        self.assertTrue(edit_res.json()["changed"])

        # Check audit log in DB
        edits = self.test_db.edits_for(sid)
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["old"], "A")
        self.assertEqual(edits[0]["new"], "P")

    # 6. Student Review Request Submission & Faculty Resolution
    def test_student_review_request_lifecycle(self):
        # 1. Create session where student_1 was marked absent
        session_id = self.test_db.save_session(self.class_1, {
            "date": date.today().isoformat(),
            "time": "11:00",
            "subject": "Networks",
            "faculty": "Prof. Smith",
            "period": "2",
            "created_at": time.time(),
        }, [
            {"student_id": self.student_1, "status": "A"},
            {"student_id": self.student_2, "status": "P"},
        ])

        # 2. Student logs in and submits review claim
        student_token = self._login_student()
        st_headers = {"Authorization": f"Bearer {student_token}"}

        sub_res = self.client.post("/api/review_requests/submit", headers=st_headers, json={
            "session_id": session_id,
            "reason": "I was present",
            "explanation": "I was in the second row.",
        })
        self.assertEqual(sub_res.status_code, 200)
        self.assertTrue(sub_res.json()["is_new"])

        # 3. Faculty logs in and views review queue
        faculty_token = self._login_faculty()
        fac_headers = {"Authorization": f"Bearer {faculty_token}"}

        queue_res = self.client.get("/api/review_requests", headers=fac_headers)
        self.assertEqual(queue_res.status_code, 200)
        requests = queue_res.json()
        self.assertEqual(len(requests), 1)
        req_id = requests[0]["id"]
        self.assertEqual(requests[0]["reason"], "I was present")

        # 4. Faculty approves and changes status to 'P'
        trans_res = self.client.post(f"/api/review_requests/{req_id}/transition", headers=fac_headers, json={
            "action": "change",
            "new_status": "P",
            "reason": "Verified on back row photo evidence."
        })
        self.assertEqual(trans_res.status_code, 200)

        # 5. Verify attendance record is now updated to 'P'
        updated_rows = self.test_db.session_rows(session_id)
        s1_row = next(r for r in updated_rows if r["student_id"] == self.student_1)
        self.assertEqual(s1_row["status"], "P")

    # 7. Recovery Assistant & Deterministic Calculations
    def test_recovery_calculator_endpoint(self):
        res = self.client.post("/api/recovery/calculate", json={
            "attended": 18,
            "absent": 8,
            "target": 75.0,
            "upcoming": 10,
            "attend_next": 8,
            "miss_next": 2
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        plan = data["plan"]
        self.assertEqual(plan["attended"], 18)
        self.assertEqual(plan["absent"], 8)
        self.assertAlmostEqual(plan["current"], 69.23, places=1)
        self.assertTrue(plan["classes_needed"] > 0)
        self.assertIsNotNone(data["what_if"])

    # 8. Phone Upload Session & Smart Capture Flow
    def test_phone_upload_session_and_upload(self):
        token = self._login_admin()
        headers = {"Authorization": f"Bearer {token}"}

        start_res = self.client.post("/api/phone_upload/start", headers=headers, data={
            "class_id": str(self.class_1)
        })
        self.assertEqual(start_res.status_code, 200)
        upload_data = start_res.json()
        upload_token = upload_data["token"]
        self.assertTrue(len(upload_token) >= 32)
        self.assertTrue(upload_data["qr_code"].startswith("data:image/png;base64,"))

        # Check mobile page serves HTML
        page_res = self.client.get(f"/phone_upload/{upload_token}")
        self.assertEqual(page_res.status_code, 200)
        self.assertIn("SMART CAPTURE", page_res.text)

        # Check status initially
        stat_res = self.client.get(f"/phone_upload/{upload_token}/status")
        self.assertEqual(stat_res.status_code, 200)
        self.assertEqual(stat_res.json()["files_count"], 0)

        # Phone finishes session
        finish_res = self.client.post(f"/phone_upload/{upload_token}/finish")
        self.assertEqual(finish_res.status_code, 200)

    # 9. Isolated Demo Mode Entry & Exit
    def test_demo_mode_isolation(self):
        # Enter demo mode without initial auth
        demo_res = self.client.post("/api/demo/enter")
        self.assertEqual(demo_res.status_code, 200)
        demo_token = demo_res.json()["token"]
        headers = {"Authorization": f"Bearer {demo_token}"}

        # Check profile
        me_res = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me_res.status_code, 200)
        self.assertTrue(me_res.json()["is_demo"])

        # Demo classes should include Sample Class
        c_res = self.client.get("/api/classes", headers=headers)
        self.assertEqual(c_res.status_code, 200)
        class_names = [c["name"] for c in c_res.json()]
        self.assertTrue(any("DEMO" in name or "Sample Class" in name for name in class_names))

        # Exit demo mode
        exit_res = self.client.post("/api/demo/exit", headers=headers)
        self.assertEqual(exit_res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
