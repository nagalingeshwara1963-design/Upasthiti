"""Gallery identity and safe rebuild tests use synthetic vectors and images."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app import config
from app.engine.gallery import Gallery, GalleryCompatibilityError
from app.db import DB
from app.services import Service


class GalleryCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="upasthiti-gallery-")
        self.root = Path(self.temp.name)
        self.ensure_patch = patch("app.db.config.ensure_dirs")
        self.ensure_patch.start()
        self.db = DB(self.root / "test.db")
        self.class_id = self.db.add_class("Gallery Class")

    def tearDown(self):
        self.db.con.close()
        self.ensure_patch.stop()
        self.temp.cleanup()

    def test_legacy_gallery_is_rejected_with_safe_rebuild_instruction(self):
        path = self.root / "legacy.json"
        path.write_text(json.dumps({"n_models": 2, "students": {}}), encoding="utf-8")
        gallery = Gallery.load(path)
        expected = [
            {"id": "insightface_buffalo_rec", "version": "w600k_r50-v1"},
            {"id": "insightface_antelope", "version": "glintr100-v1"},
        ]
        with self.assertRaises(GalleryCompatibilityError) as raised:
            gallery.require_compatible(expected)
        self.assertIn("Rebuild Recognition Gallery", str(raised.exception))

    def test_service_refuses_to_load_legacy_embeddings_for_attendance(self):
        service = self._service(["insightface_buffalo_rec", "insightface_antelope"])
        path = self.root / "galleries" / f"class_{self.class_id}.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"n_models": 2, "students": {}}), encoding="utf-8")
        with patch("app.services.config.DATA", self.root):
            with self.assertRaisesRegex(GalleryCompatibilityError, "cannot be identified safely"):
                service.load_gallery(self.class_id)

    def test_recognizer_identity_order_and_version_must_match(self):
        recognizers = [
            {"id": "insightface_buffalo_rec", "version": "w600k_r50-v1"},
            {"id": "insightface_antelope", "version": "glintr100-v1"},
        ]
        gallery = Gallery(2, recognizers)
        path = self.root / "gallery.json"
        gallery.save(path)
        loaded = Gallery.load(path)
        loaded.require_compatible(recognizers)
        with self.assertRaises(GalleryCompatibilityError):
            loaded.require_compatible(list(reversed(recognizers)))
        changed = [dict(item) for item in recognizers]
        changed[0]["version"] = "w600k_r50-v2"
        with self.assertRaises(GalleryCompatibilityError):
            loaded.require_compatible(changed)
        loaded.recognizers = ["unparseable"]
        with self.assertRaisesRegex(GalleryCompatibilityError, "invalid recognizer metadata"):
            loaded.require_compatible(recognizers)

    def _service(self, active_ids):
        service = Service(self.db)
        service.hub = SimpleNamespace(model_ids=active_ids)
        return service

    def test_class_rebuild_reembeds_every_student_and_atomically_replaces_legacy_gallery(self):
        self.db.save_student(self.class_id, "S-1", "Student One", ["one.jpg"])
        self.db.save_student(self.class_id, "S-2", "Student Two", ["two.jpg"])
        service = self._service(["insightface_buffalo_rec", "insightface_antelope"])
        path = self.root / "galleries" / f"class_{self.class_id}.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"n_models": 2, "students": {}}), encoding="utf-8")
        vector_a = np.array([1.0, 0.0], dtype=np.float32)
        vector_b = np.array([0.0, 1.0], dtype=np.float32)
        with patch("app.services.config.DATA", self.root), \
             patch("app.services.auth.current_role", return_value="admin"), \
             patch("app.services.auth.can_access_class", return_value=True), \
             patch("app.services.imread", return_value=np.zeros((2, 2, 3))), \
             patch("app.services.enroll_photo", side_effect=[([vector_a, vector_b], {}), ([vector_b, vector_a], {})]):
            rebuilt = service.rebuild_class_gallery(self.class_id)
        self.assertEqual(rebuilt.codes, ["S-1", "S-2"])
        reopened = Gallery.load(path)
        reopened.require_compatible(service._recognizer_metadata())
        self.assertEqual(reopened.codes, ["S-1", "S-2"])

    def test_failed_class_rebuild_keeps_existing_gallery_unchanged(self):
        self.db.save_student(self.class_id, "S-1", "Student One", ["one.jpg"])
        self.db.save_student(self.class_id, "S-2", "Student Two", ["two.jpg"])
        service = self._service(["insightface_buffalo_rec", "insightface_antelope"])
        path = self.root / "galleries" / f"class_{self.class_id}.json"
        path.parent.mkdir(parents=True)
        original = json.dumps({"n_models": 2, "students": {"legacy": {"name": "Old", "embs": []}}})
        path.write_text(original, encoding="utf-8")
        image = np.zeros((2, 2, 3))
        with patch("app.services.config.DATA", self.root), \
             patch("app.services.auth.current_role", return_value="admin"), \
             patch("app.services.auth.can_access_class", return_value=True), \
             patch("app.services.imread", side_effect=[image, None]), \
             patch("app.services.enroll_photo", return_value=([np.ones(2), np.ones(2)], {})):
            with self.assertRaisesRegex(RuntimeError, "existing gallery was left unchanged"):
                service.rebuild_class_gallery(self.class_id)
        self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
