"""Lifecycle test fixture only. Never imported by the application."""
import argparse
import json
from pathlib import Path
import time
from bgagent10.service import atomic_json, read_json

parser = argparse.ArgumentParser()
parser.add_argument("--config")
parser.add_argument("--run-dir")
args = parser.parse_args()
run = Path(args.run_dir)
atomic_json(run / "status.json", {"state": "running", "completed_games": 0})
for _ in range(500):
    command = read_json(run / "control.json", {}).get("command")
    if command in {"pause", "stop"}:
        path = run / "checkpoints" / "fixture-only.pt"
        path.parent.mkdir(exist_ok=True)
        path.write_text("TEST FIXTURE; NOT A TRAINED MODEL", encoding="utf-8")
        atomic_json(run / "status.json", {"state": "paused" if command == "pause" else "stopped", "checkpoint": str(path), "completed_games": 1})
        break
    time.sleep(.02)
else:
    atomic_json(run / "status.json", {"state": "completed"})
