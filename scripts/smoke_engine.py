"""Check the real stdio engine in an isolated profile, without desktop input or audio."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent.parent

def smoke(executable=None):
    with tempfile.TemporaryDirectory(prefix="jarvis-smoke-") as folder:
        Path(folder, "settings.json").write_text(json.dumps({
            "_schema_version": 1, "search_roots": [], "listen_on_startup": False,
            "speech_enabled": False, "user_name": "Owner \uc544 \u0627\u0631\u062f\u0648"}), encoding="utf-8")
        command = [str(executable), "--engine", "--no-listen"] if executable else [sys.executable, "-B", str(ROOT / "Main.py"), "--engine", "--no-listen"]
        env = dict(os.environ, JARVIS_DATA_DIR=folder, PYTHONIOENCODING="cp1252")
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        messages, errors = queue.Queue(), []
        def stdout():
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    messages.put({"invalid_stdout": True})
        def stderr():
            for line in process.stderr:
                errors.append(line.rstrip())
                del errors[:-20]
        threading.Thread(target=stdout, daemon=True).start()
        threading.Thread(target=stderr, daemon=True).start()
        def wait_for(predicate, timeout=45):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    item = messages.get(timeout=0.2)
                except queue.Empty:
                    if process.poll() is not None:
                        raise RuntimeError("Engine exited: " + str(process.returncode) + "; " + " | ".join(errors))
                    continue
                if item.get("invalid_stdout"):
                    raise RuntimeError("Non-JSON output on engine transport")
                if predicate(item):
                    return item["data"]
            raise TimeoutError("Engine protocol timed out; " + " | ".join(errors))
        def send(payload):
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        def request(identifier, op, **fields):
            send(dict(id=identifier, op=op, **fields))
            reply = wait_for(lambda item: item.get("event") == "response" and item.get("data", {}).get("id") == identifier)
            if "error" in reply:
                raise RuntimeError(reply["error"])
            return reply["value"]
        try:
            wait_for(lambda item: item.get("event") == "ready")
            snapshot = request(1, "connect", no_listen=True)
            assert snapshot["settings"]["user_name"] == "Owner \uc544 \u0627\u0631\u062f\u0648"
            assert snapshot["security"]["owner_authenticated"] is False
            assert snapshot["provider"]["online"] is False
            assert snapshot["listening"] is False
            # The result event can arrive before the request acknowledgement.
            send({"id": 2, "op": "command", "text": "what time is it"})
            acknowledgement = result = None
            for _ in range(100):
                packet = wait_for(lambda item: item.get("event") in {"response", "result"})
                if packet.get("id") == 2:
                    acknowledgement = packet
                elif packet.get("action") == "time":
                    result = packet
                if acknowledgement and result:
                    break
            assert acknowledgement and acknowledgement.get("value", {}).get("accepted") is True, acknowledgement
            assert result and result["success"] is True, result
            assert request(3, "emergency")["stopped"] is True
            updated = request(4, "settings", values={"assistant_name": "Jarvis \u0627\u0631\u062f\u0648"})
            assert updated["assistant_name"] == "Jarvis \u0627\u0631\u062f\u0648"
            send({"op": "quit"})
            process.stdin.close()
            process.wait(timeout=15)
            assert process.returncode == 0, process.returncode
            print("PASS: startup, multilingual UTF-8 IPC, local time command, offline state, microphone paused, emergency, clean exit")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            process.stdout.close()
            process.stderr.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args()
    smoke(args.executable.resolve() if args.executable else None)
