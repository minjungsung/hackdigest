from datetime import datetime
from pathlib import Path
import sqlite3

from .core import KST


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("CREATE TABLE IF NOT EXISTS sent (fingerprint TEXT PRIMARY KEY, sent_at TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests (source TEXT, day TEXT, count INTEGER NOT NULL, PRIMARY KEY(source, day))")
        self.db.commit()

    def seen(self, fingerprint):
        return self.db.execute("SELECT 1 FROM sent WHERE fingerprint = ?", (fingerprint,)).fetchone() is not None

    def mark_sent(self, fingerprints):
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO sent VALUES (?, ?)", [(f, datetime.now(KST).isoformat()) for f in fingerprints])

    def reserve_request(self, source, limit):
        today = datetime.now(KST).date().isoformat()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT count FROM requests WHERE source=? AND day=?", (source, today)).fetchone()
            count = row[0] if row else 0
            if count >= limit:
                raise ValueError("Daily API request budget exhausted")
            self.db.execute("INSERT INTO requests VALUES (?, ?, ?) ON CONFLICT(source, day) DO UPDATE SET count=excluded.count", (source, today, count + 1))

    def close(self):
        self.db.close()
