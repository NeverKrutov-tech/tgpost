import json
import tempfile
import unittest
from pathlib import Path

from src.tg_autopost.performance import PerformanceStore


class TestPerformanceStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "performance.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_empty(self):
        store = PerformanceStore(str(self.path))
        self.assertEqual(store.load(), {})

    def test_append_and_load(self):
        store = PerformanceStore(str(self.path))
        store.append(123, {"views": 100, "forwards": 2, "reactions": 5})
        store.append(124, {"views": 200, "forwards": 0, "reactions": 1})
        data = PerformanceStore(str(self.path)).load()
        self.assertEqual(data["123"]["views"], 100)
        self.assertEqual(data["124"]["forwards"], 0)

    def test_append_preserves_existing(self):
        store = PerformanceStore(str(self.path))
        store.append(123, {"views": 100})
        store.append(124, {"views": 200})
        data = PerformanceStore(str(self.path)).load()
        self.assertEqual(len(data), 2)


if __name__ == "__main__":
    unittest.main()
