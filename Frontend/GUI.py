"""Jarvis local desktop interface. All AI, indexing, and microphone work runs off the GUI thread."""
from __future__ import annotations
import ctypes
import html
import importlib.util
import os
import shutil
import sys
import threading
import time
import wave
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QSize, QProcess, pyqtSignal, QRectF
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QStackedWidget, QLineEdit, QTextBrowser, QListWidget, QListWidgetItem,
    QComboBox, QSpinBox, QCheckBox, QFormLayout, QGroupBox, QScrollArea, QPlainTextEdit,
    QFileDialog, QMessageBox, QSystemTrayIcon, QMenu, QProgressBar,
)
from Backend.Config import Config, PROJECT_DIR
from Frontend.theme import STYLE

def label(text, style="Muted", wrap=True):
    widget = QLabel(text)
    widget.setObjectName(style)
    widget.setWordWrap(wrap)
    return widget

def button(text, callback=None, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("Primary")
    if callback:
        widget.clicked.connect(callback)
    return widget

class CoreVisual(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(170, 170)
        self.angle = 0
        self.level = 0
        self.active = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(60)

    def _tick(self):
        if self.active:
            self.angle = (self.angle + 2) % 360
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#263d4c"), 1))
        painter.drawEllipse(QRectF(10, 10, 150, 150))
        painter.setPen(QPen(QColor("#6ee7cf" if self.active else "#456576"), 3))
        painter.drawArc(QRectF(18, 18, 134, 134), int(self.angle * 16), 115 * 16)
        painter.drawArc(QRectF(18, 18, 134, 134), int((self.angle + 180) * 16), 115 * 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#16303a"))
        painter.drawEllipse(QRectF(38, 38, 94, 94))
        painter.setPen(QPen(QColor("#92f3dc"), 4, Qt.SolidLine, Qt.RoundCap))
        for i, base in enumerate([13, 23, 34, 23, 13]):
            height = base + (self.level / 7 if self.active else 0)
            x = 61 + i * 12
            painter.drawLine(int(x), int(85-height/2), int(x), int(85+height/2))

class MainWindow(QMainWindow):
    task_done = pyqtSignal(str, str)
    files_found = pyqtSignal(list)

    def __init__(self, config: Config, controller=None, *, preview=False):
        super().__init__()
        self.config, self.controller, self.preview = config, controller, preview
        self._quitting = False
        self._jobs = []
        self._hotkey = False
        self._recording = False
        self.setWindowTitle("Jarvis · Local Desktop Assistant")
        self.resize(1160, 820)
        self.setMinimumSize(880, 670)
        self.setWindowIcon(QIcon(str(PROJECT_DIR / "Frontend/Graphics/jarvis-local.svg")))
        self.setStyleSheet(STYLE)
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(205)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 28, 20, 22)
        brand = label("J A R V I S", "Heading")
        side.addWidget(brand)
        side.addWidget(label("LOCAL DESKTOP ASSISTANT", "Eyebrow"))
        side.addSpacing(36)
        self.pages = QStackedWidget()
        self.nav = []
        for i, name in enumerate(["Assistant", "Files & folders", "Settings"]):
            nav = button(name)
            nav.setObjectName("Nav")
            nav.setCheckable(True)
            nav.clicked.connect(lambda checked, page=i: self.go_to(page))
            side.addWidget(nav)
            self.nav.append(nav)
        side.addStretch()
        side.addWidget(label("ON YOUR COMPUTER", "Eyebrow"))
        side.addWidget(label("No cloud AI connection.\nYour voice and chat stay local."))
        side.addSpacing(16)
        side.addWidget(button("Command guide", lambda: self._guide()))
        side.addWidget(label("Ctrl + Alt + J\nListen to one command", "Muted"))
        layout.addWidget(sidebar)
        layout.addWidget(self.pages, 1)
        self.pages.addWidget(self._assistant_page())
        self.pages.addWidget(self._files_page())
        self.pages.addWidget(self._settings_page())
        self.go_to(0)
        self.task_done.connect(self._task_finished)
        self.files_found.connect(self._fill_files)
        if controller:
            controller.message.connect(self.add_message)
            controller.status.connect(self.set_status)
            controller.level.connect(self.set_level)
            controller.busy_changed.connect(self._busy_changed)
            controller.mic_changed.connect(self._mic_changed)
            controller.index_changed.connect(self.index_status.setText)
            controller.result.connect(self._show_result)
            controller.notification.connect(self._notify)
            controller.quit_requested.connect(self.quit_app)
            for entry in controller.services.memory()["history"]:
                self.add_message(entry["role"], entry["content"])
            self.index_status.setText(f"{controller.assistant.index.count():,} files and folders indexed")
        if not self.chat.toPlainText().strip():
            self.add_message("assistant", "Welcome to your local workspace. Ask me to open a file, find a document, or set a reminder. Use Settings to prepare offline voice and chat.")
        if not preview:
            self._setup_tray()
            QTimer.singleShot(500, self.refresh_devices)
            QTimer.singleShot(700, self._register_hotkey)
        self.refresh_model_status()

    def _page(self, title, subtitle):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(30, 27, 30, 22)
        outer.setSpacing(16)
        outer.addWidget(label(title, "Title"))
        outer.addWidget(label(subtitle))
        return page, outer

    def _assistant_page(self):
        page, outer = self._page("Your desktop. At your command.", "A personal assistant that runs on your computer.")
        card = QFrame()
        card.setObjectName("Card")
        hero = QHBoxLayout(card)
        hero.setContentsMargins(15, 8, 22, 8)
        self.core = CoreVisual()
        hero.addWidget(self.core)
        controls = QVBoxLayout()
        controls.addWidget(label("READY WHEN YOU ARE", "Eyebrow"))
        self.status_label = label("Ready. Microphone is off.", "Status")
        self.status_label.setMinimumHeight(42)
        controls.addWidget(self.status_label)
        controls.addWidget(label("Say “Jarvis, open downloads” or type a request below."))
        row = QHBoxLayout()
        self.mic_button = button("Start listening", self.toggle_mic, True)
        self.mic_button.setCheckable(True)
        self.mic_button.setAccessibleName("Toggle hands-free microphone")
        row.addWidget(self.mic_button)
        self.once_button = button("Listen once", self.listen_once)
        row.addWidget(self.once_button)
        row.addWidget(button("Stop", self.stop_speech))
        controls.addLayout(row)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setValue(0)
        self.meter.setTextVisible(False)
        controls.addWidget(self.meter)
        hero.addLayout(controls, 1)
        outer.addWidget(card)
        quick = QHBoxLayout()
        quick.addWidget(button("Open downloads", lambda: self.send_text("open downloads")))
        quick.addWidget(button("Find a file", lambda: self.go_to(1)))
        quick.addWidget(button("Set a reminder", lambda: self._prefill("remind me in 10 minutes to ")))
        outer.addLayout(quick)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        self.chat.setAccessibleName("Conversation")
        self.chat.setStyleSheet("QTextBrowser { border: none; background: transparent; padding: 2px; }")
        outer.addWidget(self.chat, 1)
        self.choices = QListWidget()
        self.choices.setMaximumHeight(155)
        self.choices.hide()
        self.choices.itemClicked.connect(lambda item: self.send_text(f"choose {self.choices.row(item)+1}"))
        outer.addWidget(self.choices)
        compose = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask Jarvis to open, find, search, or remind…")
        self.input.setAccessibleName("Message to Jarvis")
        self.input.returnPressed.connect(self.send_text)
        self.send_button = button("Send", self.send_text, True)
        compose.addWidget(self.input, 1)
        compose.addWidget(self.send_button)
        outer.addLayout(compose)
        self.model_status = label("", "Muted")
        outer.addWidget(self.model_status)
        return page

    def _files_page(self):
        page, outer = self._page("Find it. Open it.", "Search filenames on this computer. Add folders in Settings.")
        row = QHBoxLayout()
        self.file_query = QLineEdit()
        self.file_query.setPlaceholderText("A filename, part of a name, or a complete path")
        self.file_query.returnPressed.connect(self.search_files)
        self.file_kind = QComboBox()
        for text, key in [("All files", ""), ("Folders", "folder"), ("PDFs", "pdf"), ("Documents", "document"),
                          ("Images", "image"), ("Videos", "video"), ("Audio", "audio"), ("Spreadsheets", "spreadsheet")]:
            self.file_kind.addItem(text, key)
        row.addWidget(self.file_query, 1)
        row.addWidget(self.file_kind)
        row.addWidget(button("Search", self.search_files, True))
        outer.addLayout(row)
        self.index_status = label("File index ready.")
        line = QHBoxLayout()
        line.addWidget(self.index_status, 1)
        line.addWidget(button("Refresh index", lambda: self.controller and self.controller.refresh_index()))
        outer.addLayout(line)
        self.file_results = QListWidget()
        self.file_results.setAccessibleName("File search results")
        self.file_results.itemActivated.connect(self.open_selected_file)
        outer.addWidget(self.file_results, 1)
        row = QHBoxLayout()
        row.addWidget(button("Open selected", self.open_selected_file, True))
        row.addWidget(button("Show in folder", self.reveal_selected))
        row.addWidget(button("Give it a voice name", self.alias_selected))
        row.addStretch()
        outer.addLayout(row)
        outer.addWidget(label("Use a short voice name for files you open often, such as “my budget” or “school notes”."))
        return page

    def _settings_page(self):
        page, outer = self._page("Make Jarvis yours.", "Control your microphone, voice, local models, and searchable folders.")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        content = QVBoxLayout(inner)
        content.setContentsMargins(0, 0, 12, 0)
        cfg = self.config.settings
        group = QGroupBox("Listening")
        form = QFormLayout(group)
        self.language = QComboBox()
        for title, key in [("English + Urdu · automatic", "auto"), ("English", "en"), ("Urdu", "ur")]:
            self.language.addItem(title, key)
        self.language.setCurrentIndex(max(0, self.language.findData(cfg.language)))
        self.device = QComboBox()
        self.device.addItem("Windows default microphone", None)
        self.wake = QLineEdit(cfg.wake_word)
        self.require_wake = QCheckBox("Require the wake word during hands-free listening")
        self.require_wake.setChecked(cfg.require_wake_word)
        self.noise = QComboBox()
        for title in ["Light", "Balanced", "Strong", "Very strong"]:
            self.noise.addItem(title)
        self.noise.setCurrentIndex(cfg.vad_aggressiveness)
        form.addRow("Language", self.language)
        form.addRow("Microphone", self.device)
        form.addRow("", button("Refresh microphones & voices", self.refresh_devices))
        form.addRow("Wake word", self.wake)
        form.addRow("", self.require_wake)
        form.addRow("Noise filtering", self.noise)
        content.addWidget(group)
        group = QGroupBox("Speaking")
        form = QFormLayout(group)
        self.voice_provider = QComboBox()
        self.voice_provider.addItem("Windows voice · works offline", "windows")
        self.voice_provider.addItem("My personal voice · local English model", "pocket")
        self.voice_provider.setCurrentIndex(max(0, self.voice_provider.findData(cfg.voice_provider)))
        self.voice = QComboBox()
        self.voice.addItem("Windows default voice", "")
        self.voice_rate = QSpinBox()
        self.voice_rate.setRange(-10, 10)
        self.voice_rate.setValue(cfg.voice_rate)
        self.voice_volume = QSpinBox()
        self.voice_volume.setRange(0, 100)
        self.voice_volume.setValue(cfg.voice_volume)
        self.speech_on = QCheckBox("Speak responses aloud")
        self.speech_on.setChecked(cfg.speech_enabled)
        self.voice_sample = label(Path(cfg.voice_reference).name if cfg.voice_reference else "No personal voice recording selected.")
        form.addRow("Voice engine", self.voice_provider)
        form.addRow("Windows voice", self.voice)
        form.addRow("Speed", self.voice_rate)
        form.addRow("Volume", self.voice_volume)
        form.addRow("", self.speech_on)
        sample_row = QHBoxLayout()
        sample_row.addWidget(button("Choose my recording…", self.choose_voice))
        self.record_button = button("Record 12 seconds", self.record_voice)
        sample_row.addWidget(self.record_button)
        form.addRow("My voice", sample_row)
        form.addRow("", self.voice_sample)
        form.addRow("", label("Use a clear recording of your own voice. Personal voice currently speaks English. Urdu output requires an installed Urdu Windows voice."))
        form.addRow("", button("Save & test voice", self.test_voice))
        content.addWidget(group)
        group = QGroupBox("Local models")
        form = QVBoxLayout(group)
        self.models_detail = label("")
        form.addWidget(self.models_detail)
        form.addWidget(label("A one-time download prepares speech and chat (about 1.3 GB). They then work without an internet connection or API keys."))
        self.download_button = button("Download speech & chat models", lambda: self.download_models(False), True)
        self.voice_download_button = button("Set up personal voice", lambda: self.download_models(True))
        form.addWidget(self.download_button)
        form.addWidget(self.voice_download_button)
        form.addWidget(button("Choose an existing local model…", self.choose_model))
        self.setup_log = QPlainTextEdit()
        self.setup_log.setReadOnly(True)
        self.setup_log.setMaximumHeight(130)
        self.setup_log.hide()
        form.addWidget(self.setup_log)
        content.addWidget(group)
        group = QGroupBox("Files & desktop")
        form = QFormLayout(group)
        self.roots = QPlainTextEdit("\n".join(cfg.search_roots))
        self.roots.setMaximumHeight(100)
        form.addRow("Search folders", self.roots)
        form.addRow("", button("Add a folder…", self.add_folder))
        self.tray_setting = QCheckBox("Keep Jarvis running in the tray when its window closes")
        self.tray_setting.setChecked(cfg.close_to_tray)
        form.addRow("", self.tray_setting)
        self.name_setting = QLineEdit(cfg.user_name)
        form.addRow("Your name", self.name_setting)
        form.addRow("", label("Saved locally in " + str(self.config.directory)))
        content.addWidget(group)
        content.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.settings_feedback = label("")
        outer.addWidget(self.settings_feedback)
        outer.addWidget(button("Save settings", self.save_settings, True))
        return page

    def go_to(self, page):
        self.pages.setCurrentIndex(page)
        for i, nav in enumerate(self.nav):
            nav.setChecked(i == page)
        if page == 2:
            self.refresh_model_status()

    def add_message(self, role, text):
        title = "YOU" if role == "user" else "JARVIS"
        color = "#9fb2cd" if role == "user" else "#79e5ce"
        safe = html.escape(str(text)).replace("\n", "<br>")
        self.chat.append(f'<div style="margin-top:14px; margin-bottom:16px"><span style="color:{color};font-size:10pt;font-weight:600">{title}</span><br><span style="color:#e1e9f4;font-size:11pt">{safe}</span></div>')
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def set_status(self, text):
        self.status_label.setText(text)

    def set_level(self, value):
        self.meter.setValue(value)
        self.core.level = value
        self.core.update()

    def send_text(self, text=None):
        if type(text) is not str:
            text = self.input.text()
        text = text.strip()
        if not text:
            return
        self.input.clear()
        self.choices.hide()
        if self.controller:
            self.controller.submit(text)
        self.go_to(0)

    def _prefill(self, text):
        self.go_to(0)
        self.input.setText(text)
        self.input.setFocus()

    def _guide(self):
        from Backend.Assistant import HELP
        self.go_to(0)
        self.add_message("assistant", HELP)

    def toggle_mic(self):
        if self.controller:
            self.controller.voice.set_enabled(self.mic_button.isChecked())

    def listen_once(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if self.controller:
            self.controller.speaker.stop()
            self.controller.voice.set_enabled(True, once=True)

    def stop_speech(self):
        if self.controller:
            self.controller.speaker.stop()
            self.controller.stop()
        self.set_status("Stopped speaking.")

    def _mic_changed(self, enabled):
        self.mic_button.blockSignals(True)
        self.mic_button.setChecked(enabled)
        self.mic_button.setText("Pause microphone" if enabled else "Start listening")
        self.mic_button.blockSignals(False)
        self.core.active = enabled
        self.core.update()

    def _busy_changed(self, busy):
        self.send_button.setEnabled(not busy)
        self.once_button.setEnabled(not busy)
        self.core.active = busy or bool(self.controller and self.controller.voice.enabled.is_set())
        self.core.update()

    def _show_result(self, result):
        self.refresh_model_status()
        choices = (result.data or {}).get("choices")
        if choices:
            self.choices.clear()
            for i, item in enumerate(choices, 1):
                self.choices.addItem(f"{i}. {item['name']}\n{item.get('path', item.get('process', ''))}")
            self.choices.show()
        elif (result.data or {}).get("confirmation"):
            self.choices.clear()
            # Confirmation is a text/voice action, not a numbered file selection.
            self.input.setPlaceholderText("Type yes to confirm, or no to cancel")
        else:
            self.input.setPlaceholderText("Ask Jarvis to open, find, search, or remind…")

    def search_files(self):
        if not self.controller:
            return
        query, kind = self.file_query.text().strip(), self.file_kind.currentData()
        if not query:
            return
        def search():
            try:
                hits = self.controller.services.files(query, kind)
                self.files_found.emit(hits)
            except Exception as exc:
                self.task_done.emit("error", str(exc))
        threading.Thread(target=search, daemon=True).start()

    def _fill_files(self, results):
        self.file_results.clear()
        for result in results:
            item = QListWidgetItem(result["name"] + "\n" + result["path"])
            item.setData(Qt.UserRole, result)
            self.file_results.addItem(item)
        if not results:
            self.file_results.addItem("No matches. Refresh the index or add the containing folder in Settings.")

    def open_selected_file(self, item=None):
        item = item if isinstance(item, QListWidgetItem) else self.file_results.currentItem()
        if item and item.data(Qt.UserRole):
            self.send_text("open file " + item.data(Qt.UserRole)["path"])

    def reveal_selected(self):
        item = self.file_results.currentItem()
        if item and item.data(Qt.UserRole):
            path = Path(item.data(Qt.UserRole)["path"])
            if path.exists():
                self.controller.submit("open file " + str(path.parent))

    def alias_selected(self):
        from PyQt5.QtWidgets import QInputDialog
        item = self.file_results.currentItem()
        if not item or not item.data(Qt.UserRole):
            return
        name, ok = QInputDialog.getText(self, "Voice name", "What should you call this file?")
        if ok and name.strip():
            aliases = dict(self.config.settings.aliases)
            aliases[name.strip().casefold()] = item.data(Qt.UserRole)["path"]
            if self.controller:
                self.controller.services.update_settings({"aliases": aliases})
            else:
                self._update_settings({"aliases": aliases})
            self.index_status.setText(f'Saved. Say “Jarvis, open {name.strip()}”.')

    def refresh_devices(self):
        from Backend.VoiceInput import microphones
        from Backend.VoiceOutput import installed_voices
        try:
            devices = microphones()
            voices = installed_voices()
            self.device.clear()
            self.device.addItem("Windows default microphone", None)
            for item in devices:
                self.device.addItem(item["name"], item["id"])
            self.device.setCurrentIndex(max(0, self.device.findData(self.config.settings.microphone_device)))
            self.voice.clear()
            self.voice.addItem("Windows default voice", "")
            for item in voices:
                self.voice.addItem(item["name"], item["id"])
            self.voice.setCurrentIndex(max(0, self.voice.findData(self.config.settings.voice_id)))
        except Exception as exc:
            self.settings_feedback.setText(f"Audio devices unavailable: {exc}")

    def _update_settings(self, values):
        if self.controller:
            return self.controller.services.update_settings(values)
        return self.config.update(values)

    def save_settings(self):
        try:
            roots = [line.strip().strip('"') for line in self.roots.toPlainText().splitlines() if line.strip()]
            if not roots or any(not Path(os.path.expandvars(root)).is_dir() for root in roots):
                raise ValueError("Choose at least one existing search folder.")
            updater = self._update_settings
            updater({
                "language": self.language.currentData(), "microphone_device": self.device.currentData(),
                "wake_word": self.wake.text().strip() or "jarvis", "require_wake_word": self.require_wake.isChecked(),
                "vad_aggressiveness": self.noise.currentIndex(), "voice_provider": self.voice_provider.currentData(),
                "voice_id": self.voice.currentData() or "", "voice_rate": self.voice_rate.value(),
                "voice_volume": self.voice_volume.value(), "speech_enabled": self.speech_on.isChecked(),
                "search_roots": roots, "close_to_tray": self.tray_setting.isChecked(),
                "user_name": self.name_setting.text().strip() or "User",
            })
            if self.controller:
                self.controller.voice.set_enabled(False)
                self.controller.refresh_index()
            self.settings_feedback.setText("Saved. Start listening again to use your new microphone settings.")
            return True
        except Exception as exc:
            self.settings_feedback.setText(str(exc))
            return False

    def test_voice(self):
        if self.save_settings() and self.controller:
            self.controller.speaker.say("Hello. I am Jarvis, your local desktop assistant.", force=True)

    def choose_voice(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a recording of your own voice", "", "WAV audio (*.wav)")
        if not path:
            return
        try:
            with wave.open(path, "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
                if not 5 <= duration <= 40:
                    raise ValueError("Choose a clear 5 to 40 second WAV recording of your own voice.")
            destination = self.config.directory / "voices" / ("my-voice-" + str(time.time_ns()) + ".wav")
            destination.parent.mkdir(exist_ok=True)
            shutil.copy2(path, destination)
            self._update_settings({"voice_reference": str(destination)})
            self.voice_sample.setText(destination.name)
        except Exception as exc:
            self.settings_feedback.setText(str(exc))

    def record_voice(self):
        if self._recording:
            return
        self._recording = True
        self.record_button.setEnabled(False)
        if self.controller:
            self.controller.voice.set_enabled(False)
            self.controller.speaker.stop()
        self.voice_sample.setText("Recording for 12 seconds. Read: “Hello, I am recording my voice for my personal Jarvis assistant. I use it to find my files and organize my day.”")
        def record():
            try:
                import sounddevice as sd
                import numpy as np
                audio = sd.rec(12 * 24000, samplerate=24000, channels=1, dtype="int16", device=self.config.settings.microphone_device)
                sd.wait()
                if float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))) < 100:
                    raise ValueError("The recording was too quiet. Move closer to the microphone and try again.")
                folder = self.config.directory / "voices"
                folder.mkdir(exist_ok=True)
                path = folder / ("my-voice-" + str(time.time_ns()) + ".wav")
                with wave.open(str(path), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(24000)
                    output.writeframes(audio.tobytes())
                self.task_done.emit("voice", str(path))
            except Exception as exc:
                self.task_done.emit("error", str(exc))
        threading.Thread(target=record, daemon=True).start()

    def _task_finished(self, kind, message):
        if self._recording:
            self._recording = False
            self.record_button.setEnabled(True)
        if kind == "voice":
            self._update_settings({"voice_reference": message})
            self.voice_sample.setText("Saved: " + Path(message).name)
        else:
            self.settings_feedback.setText(message)

    def refresh_model_status(self):
        cfg = self.config.settings
        speech = (Path(cfg.whisper_path) / "model.bin").is_file()
        chat = Path(cfg.llm_path).is_file()
        self.model_status.setText(f"ON DEVICE   ·   Speech {'ready' if speech else 'needs setup'}   ·   Chat {'ready' if chat else 'needs setup'}")
        self.models_detail.setText(f"Offline speech: {'ready' if speech else 'not installed'}\nLocal chat: {'ready' if chat else 'not installed'}")

    def choose_model(self):
        choice = QMessageBox(self)
        choice.setWindowTitle("Choose local model")
        choice.setText("Which model would you like to choose?")
        speech = choice.addButton("Speech model folder", QMessageBox.ActionRole)
        chat = choice.addButton("Chat GGUF file", QMessageBox.ActionRole)
        choice.addButton(QMessageBox.Cancel)
        choice.exec_()
        if choice.clickedButton() == speech:
            path = QFileDialog.getExistingDirectory(self, "Choose a faster-whisper model folder")
            if path and (Path(path) / "model.bin").is_file() and (Path(path) / "tokenizer.json").is_file():
                self._update_settings({"whisper_path": path})
            elif path:
                self.settings_feedback.setText("The folder needs model.bin and tokenizer.json.")
        elif choice.clickedButton() == chat:
            path, _ = QFileDialog.getOpenFileName(self, "Choose local chat model", "", "GGUF model (*.gguf)")
            if path:
                self._update_settings({"llm_path": path})
        self.refresh_model_status()

    def download_models(self, voice=False):
        if self._jobs:
            self.settings_feedback.setText("A setup job is already running.")
            return
        text = ("This installs the optional personal voice engine and downloads its local model. It may require several GB. Continue?"
                if voice else "Download the local speech and chat models, about 1.3 GB? After setup they run offline.")
        if QMessageBox.question(self, "Prepare local models", text) != QMessageBox.Yes:
            return
        self.download_button.setEnabled(False)
        self.voice_download_button.setEnabled(False)
        self.setup_log.show()
        self.setup_log.setPlainText("Preparing local models…")
        python = str(Path(sys.executable).with_name("python.exe")) if os.name == "nt" else sys.executable
        script = str(PROJECT_DIR / "scripts/download_models.py")
        steps = []
        if voice and importlib.util.find_spec("pocket_tts") is None:
            steps.append(["-m", "pip", "install", "--timeout", "120", "pocket-tts"])
        steps.append(["-X", "utf8", script] + (["--voice"] if voice else []))
        self._run_setup_steps(python, steps)

    def _run_setup_steps(self, python, steps):
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        self._jobs.append(process)
        process.readyReadStandardOutput.connect(lambda: self.setup_log.appendPlainText(bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()))
        def finished(code, status):
            if process in self._jobs:
                self._jobs.remove(process)
            process.deleteLater()
            if code == 0 and len(steps) > 1:
                self._run_setup_steps(python, steps[1:])
                return
            self.download_button.setEnabled(True)
            self.voice_download_button.setEnabled(True)
            self.refresh_model_status()
            self.settings_feedback.setText("Local model setup finished." if code == 0 else "Setup did not finish. Read the details above; you can retry.")
        process.finished.connect(finished)
        process.errorOccurred.connect(lambda error: self.settings_feedback.setText("Could not start setup. Run scripts/setup_local.ps1."))
        process.start(python, steps[0])

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add a folder to the file index")
        if folder:
            existing = self.roots.toPlainText().strip()
            self.roots.setPlainText(existing + ("\n" if existing else "") + folder)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        menu.addAction("Show Jarvis", lambda: (self.showNormal(), self.raise_(), self.activateWindow()))
        menu.addAction("Listen once", self.listen_once)
        menu.addAction("Pause microphone", lambda: self.controller and self.controller.voice.set_enabled(False))
        menu.addSeparator()
        menu.addAction("Quit Jarvis", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Jarvis · Local desktop assistant")
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def _notify(self, text):
        if hasattr(self, "tray") and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage("Jarvis reminder", text, QSystemTrayIcon.Information, 10000)

    def _register_hotkey(self):
        if os.name == "nt":
            self._hotkey = bool(ctypes.windll.user32.RegisterHotKey(int(self.winId()), 1, 0x0001 | 0x0002 | 0x4000, ord("J")))
            ctypes.windll.user32.RegisterHotKey(int(self.winId()), 2, 0x0001 | 0x0002 | 0x4000, 0x1B)

    def nativeEvent(self, eventType, message):
        if os.name == "nt":
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == 2 and self.controller:
                self.controller.stop()
                return True, 0
            if msg.message == 0x0312 and msg.wParam == 1:
                self.listen_once()
                return True, 0
        return super().nativeEvent(eventType, message)

    def closeEvent(self, event):
        if not self._quitting and not self.preview and self.config.settings.close_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
            return
        event.accept()
        if os.name == "nt":
            ctypes.windll.user32.UnregisterHotKey(int(self.winId()), 1)
            ctypes.windll.user32.UnregisterHotKey(int(self.winId()), 2)
        if self.controller:
            self.controller.close()
        for process in self._jobs:
            process.terminate()
        if hasattr(self, "tray"):
            self.tray.hide()

    def quit_app(self):
        self._quitting = True
        self.close()
        QApplication.instance().quit()

def GraphicalUserInterface():
    from Backend.Controller import Controller
    from PyQt5.QtCore import QLockFile
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    app.setQuitOnLastWindowClosed(False)
    config = Config()
    lock = QLockFile(str(config.directory / "desktop.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "Jarvis is running", "Jarvis is already running. Open it from the system tray.")
        return 0
    controller = Controller(config)
    window = MainWindow(config, controller)
    window.show()
    app.aboutToQuit.connect(controller.close)
    result = app.exec_()
    lock.unlock()
    return result

if __name__ == "__main__":
    sys.exit(GraphicalUserInterface())
