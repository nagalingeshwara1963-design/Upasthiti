"""Isolated logic and worker tests for laptop-side Smart Capture."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from app.smart_capture import SmartCaptureAnalyzer, summarize_capture


class SmartCaptureTests(unittest.TestCase):
    def test_coverage_distinguishes_confident_uncertain_unknown_and_unobserved(self):
        photos = [
            {"faces": [
                {"student": "A", "confidence": 92, "flags": []},
                {"student": "B", "confidence": 66, "flags": ["weak_match"]},
                {"student": None, "confidence": 0, "flags": ["unknown_face"]}],
             "photo_flags": ["small"]},
            {"faces": [{"student": "A", "confidence": 70, "flags": ["close_call"]}],
             "photo_flags": [], "similar_to_previous": True},
        ]
        result = summarize_capture(photos, total_students=4)
        self.assertEqual(result["detected_faces"], 4)
        self.assertEqual(result["confidently_observed"], 1)
        self.assertEqual(result["uncertain_students"], 1)
        self.assertEqual(result["unknown_faces"], 1)
        self.assertEqual(result["not_yet_observed"], 2)
        self.assertEqual(result["coverage_percent"], 25)
        self.assertTrue(result["another_capture_suggested"])
        self.assertTrue(result["similar_to_previous"])
        self.assertIn("move closer", result["guidance"])
        self.assertNotIn("accuracy", result["guidance"].lower())

    def test_analyzer_reuses_hub_and_gallery_and_fuses_each_photo_once(self):
        class FakeDB:
            def students(self, _class_id):
                return [{"code": "A"}, {"code": "B"}]

        class FakeService:
            db = FakeDB()
            def __init__(self): self.hub_calls = self.gallery_calls = 0
            def selected_model_ids(self): return ["recognizer-a"]
            def get_hub(self):
                self.hub_calls += 1
                return SimpleNamespace(model_names=["Recognizer A"])
            def load_gallery(self, _class_id):
                self.gallery_calls += 1
                return SimpleNamespace(codes=["A", "B"])

        image = np.zeros((80, 100, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory(prefix="upasthiti-smart-capture-") as temp:
            path = Path(temp) / "photo.jpg"
            Image.new("RGB", (100, 80), (100, 100, 100)).save(path)
            service = FakeService()
            updates, finished, result_box = [], threading.Event(), []

            def analyze(_hub, _gallery, photos, **_kwargs):
                label = photos[0]["label"]
                faces = [{"student": "A", "dist": 0.12, "confidence": 88,
                          "flags": [], "quality": {"flags": []}}]
                if label.startswith("Phone"):
                    faces.append({"student": None, "dist": None, "confidence": 0,
                                  "flags": ["unknown_face"], "quality": {"flags": ["small"]}})
                return {"photos": [{"label": label, "checks": [], "faces": faces}]}

            with patch("app.smart_capture.analyse_session", side_effect=analyze):
                analyzer = SmartCaptureAnalyzer(service, 7, "fast", {"t_accept": 0.6},
                    initial_photos=[{"image": image, "label": "Front"}], on_update=updates.append)
                analyzer.submit(path)
                analyzer.finish(lambda result: (result_box.append(result), finished.set()))
                self.assertTrue(finished.wait(5))
                analyzer._thread.join(5)

        self.assertEqual(service.hub_calls, 1)
        self.assertEqual(service.gallery_calls, 1)
        self.assertTrue(result_box[0]["complete"])
        self.assertEqual(len(result_box[0]["result"]["photos"]), 2)
        self.assertEqual(result_box[0]["result"]["students"]["A"]["status"], "P")
        self.assertEqual(result_box[0]["result"]["students"]["B"]["status"], "A")
        final = updates[-1]
        self.assertEqual(final["confidently_observed"], 1)
        self.assertEqual(final["unknown_faces"], 1)
        self.assertEqual(final["not_yet_observed"], 1)
        self.assertEqual(final["photos_analyzed"], 2)


if __name__ == "__main__":
    unittest.main()
