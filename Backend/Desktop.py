"""Windows desktop operations with exact arguments and graceful window closing."""
from __future__ import annotations
import ctypes
import os
import re
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus
from Backend.ActionResult import ActionResult
from Backend.Tasks import checkpoint
from Backend.FileIndex import normalize_name

WEBSITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com",
    "whatsapp": "https://web.whatsapp.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com", "wikipedia": "https://www.wikipedia.org",
    "spotify": "https://open.spotify.com", "linkedin": "https://www.linkedin.com",
}
BUILTIN_APPS = {"notepad": "notepad.exe", "calculator": "calc.exe", "paint": "mspaint.exe",
                "file explorer": "explorer.exe", "explorer": "explorer.exe",
                "task manager": "taskmgr.exe", "command prompt": "cmd.exe"}
FOLDER_NAMES = {"desktop": "Desktop", "documents": "Personal", "pictures": "My Pictures",
                "music": "My Music", "videos": "My Video",
                "downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}

def known_folder(name: str) -> Path | None:
    key = name.lower().removeprefix("my ").removesuffix(" folder")
    if key not in FOLDER_NAMES:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as registry:
            value = winreg.QueryValueEx(registry, FOLDER_NAMES[key])[0]
            return Path(os.path.expandvars(value))
    except (ImportError, OSError):
        return Path.home() / key.title()

from Backend.InputControls import InputControls

class Desktop(InputControls):
    def __init__(self):
        self._apps: dict[str, str] = {}
        self._app_time = 0.0
        self._lock = threading.Lock()
        self.last_external_window = 0

    def apps(self) -> dict[str, str]:
        if time.monotonic() - self._app_time < 300:
            return dict(self._apps)
        result = dict(BUILTIN_APPS)
        for base in (os.environ.get("APPDATA", ""), os.environ.get("PROGRAMDATA", "")):
            if not base:
                continue
            menu = Path(base) / "Microsoft/Windows/Start Menu/Programs"
            try:
                for shortcut in menu.rglob("*.lnk"):
                    result[normalize_name(shortcut.stem)] = str(shortcut)
            except OSError:
                pass
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths") as registry:
                        for i in range(winreg.QueryInfoKey(registry)[0]):
                            name = winreg.EnumKey(registry, i)
                            try:
                                with winreg.OpenKey(registry, name) as item:
                                    value = winreg.QueryValueEx(item, None)[0]
                                    if Path(value.strip('"')).is_file():
                                        result[normalize_name(Path(name).stem)] = value.strip('"')
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        aliases = {"chrome": "google chrome", "edge": "microsoft edge", "word": "word",
                   "excel": "excel", "vs code": "visual studio code", "vscode": "visual studio code"}
        for alias, canonical in aliases.items():
            if canonical in result:
                result[alias] = result[canonical]
        with self._lock:
            self._apps, self._app_time = result, time.monotonic()
        return dict(result)

    def open_path(self, path: str) -> ActionResult:
        try:
            target = Path(os.path.expandvars(path)).expanduser()
            if not target.exists():
                return ActionResult.fail("open", f"That file is unavailable: {target.name}", error="missing_file")
            checkpoint()
            os.startfile(str(target))
            return ActionResult.ok("open", f"Opened {target.name}.", path=str(target))
        except (OSError, AttributeError) as exc:
            return ActionResult.fail("open", f"Windows could not open this file: {exc}", error=type(exc).__name__)

    def open_app(self, target: str) -> ActionResult | None:
        key = normalize_name(target.removeprefix("the ").removesuffix(" app"))
        if key in {"settings", "windows settings"}:
            return self._open_uri("ms-settings:", "Windows Settings")
        folder = known_folder(target)
        if folder:
            return self.open_path(str(folder))
        if key in WEBSITES:
            return self._open_uri(WEBSITES[key], target)
        if re.fullmatch(r"(https?://)?[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/[^\s]*)?", target):
            return self._open_uri(target if target.startswith(("https://", "http://")) else "https://" + target, target)
        app = self.apps().get(key)
        if not app:
            return None
        try:
            if Path(app).is_absolute():
                checkpoint()
                os.startfile(app)
            else:
                checkpoint()
                subprocess.Popen([app], shell=False)
            return ActionResult.ok("open", f"Opened {target}.")
        except OSError as exc:
            return ActionResult.fail("open", f"Could not open {target}: {exc}", error="launch_failed")

    @staticmethod
    def _open_uri(uri: str, label: str) -> ActionResult:
        try:
            if uri.startswith("ms-settings:"):
                checkpoint()
                os.startfile(uri)
            elif not webbrowser.open(uri):
                return ActionResult.fail("open", "Windows did not report an available browser.", error="no_browser")
            return ActionResult.ok("open", f"Opened {label}.")
        except OSError as exc:
            return ActionResult.fail("open", f"Could not open {label}: {exc}")

    def web_search(self, query: str, engine: str = "duckduckgo") -> ActionResult:
        templates = {"duckduckgo": "https://duckduckgo.com/?q=",
                     "google": "https://www.google.com/search?q=",
                     "youtube": "https://www.youtube.com/results?search_query="}
        result = self._open_uri(templates.get(engine, templates["duckduckgo"]) + quote_plus(query), f"{engine} search for {query}")
        return result

    def windows(self) -> list[dict]:
        import psutil
        import win32gui
        import win32process
        items = []
        def collect(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in ({os.getpid()} | set(self.excluded_pids or ())):
                return
            try:
                name = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                name = ""
            items.append({"hwnd": hwnd, "name": title, "process": name, "pid": pid})
        win32gui.EnumWindows(collect, None)
        return items

    def remember_foreground(self):
        try:
            import win32gui
            import win32process
            window = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(window)
            if window and pid not in ({os.getpid()} | set(self.excluded_pids or ())):
                self.last_external_window = window
        except Exception:
            pass

    def matching_windows(self, target: str) -> list[dict]:
        windows = self.windows()
        if target.casefold() in {"current window", "this window", "current file", "active window"}:
            return [item for item in windows if item["hwnd"] == self.last_external_window]
        key = normalize_name(Path(target).stem if "." in target else target)
        return [item for item in windows if key in normalize_name(item["name"]) or
                key == normalize_name(Path(item["process"]).stem)]

    def close_window(self, hwnd: int) -> ActionResult:
        try:
            import win32con
            import win32gui
            import win32process
            if not win32gui.IsWindow(hwnd):
                return ActionResult.fail("close", "That window has already closed.")
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in ({os.getpid()} | set(self.excluded_pids or ())):
                return ActionResult.fail("close", "Use Quit Jarvis to close the assistant.")
            title = win32gui.GetWindowText(hwnd)
            checkpoint()
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            return ActionResult.ok("close", f"Asked {title} to close. Respond to its save prompt if one appears.")
        except Exception as exc:
            return ActionResult.fail("close", f"Could not close that window: {exc}")

    def system(self, command: str, *, confirmed: bool = False) -> ActionResult:
        try:
            checkpoint()
            if command in {"shutdown", "restart", "sleep", "lock"}:
                if not confirmed:
                    return ActionResult.fail("confirm", f"Please confirm {command}.", error="confirmation_required")
                if command in {"shutdown", "restart"}:
                    subprocess.run(["shutdown.exe", "/s" if command == "shutdown" else "/r", "/t", "30"], check=True, timeout=10)
                    return ActionResult.ok("system", f"{command.title()} scheduled in 30 seconds. Say cancel shutdown to abort.")
                if command == "lock":
                    if not ctypes.windll.user32.LockWorkStation():
                        raise OSError("Windows declined the lock request")
                else:
                    if not ctypes.windll.powrprof.SetSuspendState(False, False, False):
                        raise OSError("Windows declined the sleep request")
                return ActionResult.ok("system", f"Requested {command}.")
            if command == "cancel shutdown":
                subprocess.run(["shutdown.exe", "/a"], check=True, timeout=10)
                return ActionResult.ok("system", "Cancelled the pending Windows shutdown or restart.")
            keys = {"volume up": 0xAF, "volume down": 0xAE, "mute": 0xAD, "unmute": 0xAD,
                    "play pause": 0xB3, "next track": 0xB0, "previous track": 0xB1}
            if command in keys:
                if command in {"mute", "unmute"}:
                    from pycaw.pycaw import AudioUtilities
                    AudioUtilities.GetSpeakers().EndpointVolume.SetMute(command == "mute", None)
                else:
                    import win32api
                    import win32con
                    key = keys[command]
                    win32api.keybd_event(key, 0, 0, 0)
                    win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
                return ActionResult.ok("system", f"Done: {command}.")
            if command == "show desktop":
                from Backend.InputControls import send_chord
                send_chord([0x5B, 0x44])
                return ActionResult.ok("system", "Showing your desktop.")
            return ActionResult.fail("system", f"Unknown system action: {command}")
        except Exception as exc:
            return ActionResult.fail("system", f"Windows could not complete {command}: {exc}")
