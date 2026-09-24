"""SQLite persistence for local chat, file metadata, notes, and reminders."""
from __future__ import annotations
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, name TEXT NOT NULL, normalized TEXT NOT NULL,
                    extension TEXT NOT NULL, modified REAL NOT NULL, is_dir INTEGER NOT NULL, scan TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS files_name ON files(normalized);
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY, text TEXT NOT NULL, due REAL NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY, content TEXT NOT NULL, created REAL NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add_message(self, role: str, content: str):
        if content.strip():
            with self.connect() as db:
                db.execute("INSERT INTO messages(role,content,created) VALUES(?,?,?)", (role, content, time.time()))

    def history(self, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT role,content FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_reminder(self, text: str, due: float) -> int:
        with self.connect() as db:
            return db.execute("INSERT INTO reminders(text,due) VALUES(?,?)", (text, due)).lastrowid

    def reminders(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM reminders WHERE delivered=0 ORDER BY due")]

    def take_due_reminders(self, now: float | None = None) -> list[dict]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM reminders WHERE delivered=0 AND due<=? ORDER BY due", (time.time() if now is None else now,)).fetchall()
            db.executemany("UPDATE reminders SET delivered=1 WHERE id=?", [(r["id"],) for r in rows])
            return [dict(row) for row in rows]

    def cancel_reminder(self, reminder_id: int) -> bool:
        with self.connect() as db:
            return bool(db.execute("UPDATE reminders SET delivered=1 WHERE id=? AND delivered=0", (reminder_id,)).rowcount)

    def add_note(self, content: str) -> int:
        with self.connect() as db:
            return db.execute("INSERT INTO notes(content,created) VALUES(?,?)", (content, time.time())).lastrowid

    def notes(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM notes ORDER BY id DESC LIMIT 20")]
