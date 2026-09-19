"""Local filename search. Scans metadata only and skips application caches."""
from __future__ import annotations
import os
import re
import threading
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from Backend.Store import Store

SKIP_DIRECTORIES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "appdata", ".codex", ".cache",
    ".npm", ".nuget", ".gradle", ".rustup", ".cargo", "$recycle.bin", "system volume information",
    "windows", "program files", "program files (x86)", "programdata", "recovery", ".tox",
}
FILE_TYPES = {"pdf": (".pdf",), "document": (".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt"),
              "image": (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"),
              "video": (".mp4", ".mkv", ".avi", ".mov", ".webm"),
              "audio": (".mp3", ".wav", ".flac", ".m4a", ".ogg"),
              "spreadsheet": (".xlsx", ".xls", ".csv"), "presentation": (".pptx", ".ppt", ".odp")}

def normalize_name(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.casefold()).split())

class FileIndex:
    def __init__(self, store: Store):
        self.store = store
        self._scan_lock = threading.Lock()
        self.scanning = False
        self.last_error = ""

    def count(self) -> int:
        with self.store.connect() as db:
            return db.execute("SELECT count(*) FROM files").fetchone()[0]

    def scan(self, roots: list[str], stop: threading.Event | None = None, progress=None) -> int:
        if not self._scan_lock.acquire(False):
            return self.count()
        self.scanning = True
        self.last_error = ""
        marker = uuid.uuid4().hex
        total, batch = 0, []
        cancelled = False
        visited = set()
        try:
            stack = [Path(os.path.expandvars(root)).expanduser() for root in roots]
            while stack:
                if stop is not None and stop.is_set():
                    cancelled = True
                    break
                directory = stack.pop()
                try:
                    real = str(directory.resolve()).casefold()
                    if real in visited:
                        continue
                    visited.add(real)
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.is_symlink():
                                continue
                            try:
                                is_dir = entry.is_dir(follow_symlinks=False)
                                if is_dir and (entry.name.casefold() in SKIP_DIRECTORIES or entry.name.startswith(".")):
                                    continue
                                if is_dir:
                                    stack.append(Path(entry.path))
                                info = entry.stat(follow_symlinks=False)
                                batch.append((entry.path, entry.name, normalize_name(entry.name),
                                              Path(entry.name).suffix.lower(), info.st_mtime, int(is_dir), marker))
                                total += 1
                            except OSError:
                                continue
                            if len(batch) >= 500:
                                self._write_batch(batch)
                                batch.clear()
                                if progress:
                                    progress(total)
                except OSError:
                    continue
            self._write_batch(batch)
            if not cancelled:
                with self.store.connect() as db:
                    db.execute("DELETE FROM files WHERE scan<>?", (marker,))
            if progress:
                progress(total)
            return total
        except Exception as exc:
            self.last_error = str(exc)
            raise
        finally:
            self.scanning = False
            self._scan_lock.release()

    def _write_batch(self, rows):
        if rows:
            with self.store.connect() as db:
                db.executemany("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)", rows)

    def search(self, query: str, *, kind: str = "", limit: int = 8) -> list[dict]:
        query = query.strip().strip('"')
        direct = Path(os.path.expandvars(query)).expanduser()
        try:
            if query and direct.is_absolute() and direct.exists():
                return [{"path": str(direct), "name": direct.name, "is_dir": direct.is_dir(), "score": 1.0}]
        except (ValueError, OSError):
            pass
        key = normalize_name(query)
        words = [word for word in key.split() if word not in {"my", "the", "file", "named", "called"}]
        if not words:
            return []
        key = " ".join(words)
        escaped = [w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for w in words]
        clauses = ["normalized LIKE ? ESCAPE '\\'" for _ in escaped]
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM files WHERE " + " AND ".join(clauses) + " LIMIT 1000",
                              [f"%{w}%" for w in escaped]).fetchall()
            if not rows:
                rows = db.execute("SELECT * FROM files ORDER BY modified DESC LIMIT 10000").fetchall()
        hits = []
        for row in rows:
            item = dict(row)
            if kind == "folder" and not item["is_dir"]:
                continue
            if kind in FILE_TYPES and item["extension"] not in FILE_TYPES[kind]:
                continue
            name = item["normalized"]
            stem = normalize_name(Path(item["name"]).stem)
            score = 1.0 if key in {name, stem} else (0.9 if all(word in name for word in words) else SequenceMatcher(None, key, stem).ratio() * 0.8)
            if score < 0.48:
                continue
            item["score"] = score
            hits.append(item)
        hits.sort(key=lambda hit: (-hit["score"], -hit["modified"], hit["path"]))
        return hits[:limit]
