"""Real Tk creation/render test using an empty temporary data directory."""
from pathlib import Path
import tempfile
import tkinter as tk
from bgagent10.desktop import Desktop

with tempfile.TemporaryDirectory(prefix="bgagent-ui-test-") as directory:
    root = tk.Tk()
    ui = Desktop(root, Path(directory))
    root.update()
    assert len(ui.tabs.tabs()) == 5
    assert ui.metrics["rank"].get() == "—"
    assert ui.live_start_button.instate(["disabled"])
    root.after(350, ui.destroy)
    root.mainloop()
print("PASS: Tk window, 5 tabs, honest empty metrics, blocked live start")
