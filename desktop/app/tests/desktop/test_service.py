import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from bgagent10.service import TrainingService, atomic_json, process_identity, read_json, validate_config


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="bgagent-desktop-test-")
        self.service = TrainingService(self.directory.name, training_module="desktop_fixture_worker")

    def tearDown(self):
        for run in self.service.active_runs():
            self.service.control(run, "stop")
        for child in self.service.children.values():
            child.wait(timeout=15)
        self.directory.cleanup()

    def wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.03)
        self.fail("lifecycle condition timed out")

    def test_config_validation(self):
        self.assertEqual(validate_config({"workers": "2"})["workers"], 2)
        for key, bad in [("workers", 0), ("workers", "1.5"), ("workers", True),
                ("rounds", -1), ("eval_games", 1), ("learning_rate", "nan"),
                ("learning_rate", 0), ("device", "magic"), ("model_preset", "fake"),
                ("seed", 2**40), ("resume_from", "missing.pt")]:
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                validate_config({key: bad})

    def test_atomic_and_partial_evaluation(self):
        run = Path(self.directory.name) / "fixture"
        atomic_json(run / "config.json", {"label": "中文"})
        self.assertEqual(read_json(run / "config.json"), {"label": "中文"})
        (run / "evaluations.jsonl").write_text('{"games": 2}\n{"unfinished":', encoding="utf-8")
        self.assertEqual(self.service.evaluations(run), [{"games": 2}])
        self.assertFalse(list(run.glob("*.tmp")))

    def test_legacy_small_sample_interval_is_marked_without_rewriting(self):
        run = Path(self.directory.name) / "legacy"
        run.mkdir()
        original = json.dumps({"games": 2, "ranks": [8, 8], "mean_rank": 8, "ci_low": 8, "ci_high": 8, "ci_method": "lobby independent normal95; small n exploratory"}) + "\n"
        (run / "evaluations.jsonl").write_text(original, encoding="utf-8")
        record = self.service.evaluations(run)[0]
        self.assertIn("已弃用", record["legacy_ci_warning"])
        self.assertEqual((run / "evaluations.jsonl").read_text(encoding="utf-8"), original)

    def test_pause_resume_stop_and_reattach(self):
        run = self.service.start({})
        self.wait_for(lambda: read_json(run / "status.json", {}).get("state") == "running")
        second = TrainingService(self.directory.name, training_module="desktop_fixture_worker")
        self.assertTrue(second.alive(run))
        with self.assertRaises(RuntimeError):
            second.start({})
        with self.assertRaises(RuntimeError):
            second.resume(run)
        second.control(run, "pause")
        self.wait_for(lambda: not self.service.alive(run))
        self.assertEqual(second.snapshot(run)["state"], "paused")
        checkpoints = second.checkpoints(run)
        self.assertEqual(len(checkpoints), 1)
        resumed = self.service.resume(run, overrides={"rounds": "3"})
        self.assertNotEqual(resumed, run)
        self.assertEqual(read_json(resumed / "config.json")["resume_from"], str(checkpoints[0]))
        self.assertEqual(read_json(resumed / "config.json")["rounds"], 3)
        self.service.control(resumed, "stop")
        self.wait_for(lambda: not self.service.alive(resumed))
        self.assertEqual(self.service.snapshot(resumed)["state"], "stopped")

    def test_pid_reuse_and_abnormal_exit(self):
        run = Path(self.directory.name) / "abnormal"
        atomic_json(run / "config.json", {})
        atomic_json(run / "status.json", {"state": "running"})
        atomic_json(run / "desktop_process.json", {"pid": os.getpid(), "identity": "wrong-creation-time"})
        self.assertIsNotNone(process_identity(os.getpid()))
        self.assertFalse(self.service.alive(run))
        self.assertEqual(self.service.snapshot(run)["state"], "failed")
        self.assertEqual(read_json(run / "status.json")["state"], "running")  # controller never overwrites trainer status

    def test_missing_training_module_reports_process_failure(self):
        self.service.training_module = "bgagent10.intentionally_missing_test_module"
        run = self.service.start({})
        self.wait_for(lambda: not self.service.alive(run))
        self.assertEqual(self.service.snapshot(run)["state"], "failed")
        self.assertIn("intentionally_missing", (run / "process.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
