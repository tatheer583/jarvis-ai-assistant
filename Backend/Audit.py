"""Metadata-only local audit. Not tamper-proof against the current Windows user."""
import os
import re
import sqlite3
import time
from pathlib import Path

class AuditUnavailable(RuntimeError):
    pass

def protect_directory(path):
    if os.name != "nt":
        path.chmod(0o700)
        return
    import win32api
    import win32con
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    acl = win32security.ACL()
    flags = win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE
    for account in (sid, system):
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, flags, win32con.GENERIC_ALL, account)
    win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, acl, None)

class AuditLog:
    FIELDS = ("task_id", "step_id", "source", "tool", "risk", "outcome", "verification", "code")

    def __init__(self, directory, retention_days=90):
        self.path = Path(directory) / "audit" / "events.sqlite3"
        self.retention_days = retention_days
        self._ready = False

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self._ready:
            protect_directory(self.path.parent)
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, created REAL NOT NULL,
            task_id TEXT, step_id TEXT, source TEXT, tool TEXT,
            risk TEXT, outcome TEXT, verification TEXT, code TEXT)""")
        if not self._ready:
            db.execute("DELETE FROM events WHERE created < ?", (time.time() - self.retention_days * 86400,))
            db.commit()
            self._ready = True
        return db

    def record(self, **metadata):
        # Deliberate allowlist. No arbitrary text, targets, commands, tokens or nested payloads.
        values = []
        for name in self.FIELDS:
            value = str(metadata.get(name, ""))
            values.append(value if re.fullmatch(r"[A-Za-z0-9_.:-]{0,100}", value) else "redacted")
        try:
            db = self._connect()
            try:
                with db:
                    db.execute("INSERT INTO events(created," + ",".join(self.FIELDS) + ") VALUES(" +
                               ",".join("?" for _ in range(9)) + ")", [time.time(), *values])
            finally:
                db.close()
        except Exception as exc:
            raise AuditUnavailable("Security audit could not be written.") from exc

    def recent(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Audit limit must be between 1 and 500")
        db = self._connect()
        try:
            return [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]
        finally:
            db.close()
