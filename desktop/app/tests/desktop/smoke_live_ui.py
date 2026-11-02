"""Read-only integration with the real live module; never starts a session."""
from pathlib import Path
import tempfile
import tkinter as tk
from bgagent10.desktop import Desktop

with tempfile.TemporaryDirectory(prefix="bgagent-live-ui-test-") as directory:
    root = tk.Tk()
    ui = Desktop(root, Path(directory))
    ui.preflight()
    result = ui.task[0].result(timeout=15)
    assert result.get("state") == "blocked", result
    assert result.get("ok") is False, result
    ui.task[2](result)
    ui.task = None
    assert ui.live_start_button.instate(["disabled"])
    ui.refresh_data()
    summary = ui.task[0].result(timeout=15)
    assert isinstance(summary, dict), summary
    ui.task = None
    ui.destroy()
print("PASS: real live preflight blocked; actual empty live-data summary read; no real game actions")
