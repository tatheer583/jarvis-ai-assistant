"""Render the native UI offscreen using sample data; no microphone, models or desktop actions."""
import os
import sys
import tempfile
from pathlib import Path
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PyQt5.QtWidgets import QApplication
from Backend.Config import Config, data_directory
from Frontend.GUI import MainWindow
app = QApplication([])
with tempfile.TemporaryDirectory() as temp:
    window = MainWindow(Config(Path(temp)), preview=True)
    window.resize(1160, 820)
    window.show()
    window.chat.clear()
    window.add_message("user", "Find PDF invoices")
    window.add_message("assistant", "I found matching documents. Choose a result by number, or open Files & folders to filter your search.")
    window.set_status("Ready. Microphone is off.")
    output = data_directory() / "diagnostics"
    output.mkdir(exist_ok=True)
    for page, filename in enumerate(["assistant.png", "files.png", "settings.png"]):
        window.go_to(page)
        app.processEvents()
        window.grab().save(str(output / filename))
    print("UI previews:", output)
    window.close()
