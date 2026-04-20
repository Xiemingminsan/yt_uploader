"""
Local state so we don't re-process files across restarts.
Also tracks when we first saw a file (for TXT grace period logic).
Uses SQLite for zero-config durability.
"""
import sqlite3
import time


class State:
    def __init__(self, db_path):
        self.db_path = db_path
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    file_id TEXT PRIMARY KEY,
                    first_seen REAL NOT NULL,
                    alert_sent INTEGER DEFAULT 0,
                    done INTEGER DEFAULT 0,
                    done_at REAL
                )
            """)

    def _conn(self):
        return sqlite3.connect(self.db_path, isolation_level=None)

    def first_seen(self, file_id):
        """Return timestamp of first sighting. Inserts row if new."""
        now = time.time()
        with self._conn() as c:
            cur = c.execute("SELECT first_seen FROM files WHERE file_id=?", (file_id,))
            row = cur.fetchone()
            if row:
                return row[0]
            c.execute(
                "INSERT INTO files(file_id, first_seen) VALUES(?, ?)",
                (file_id, now),
            )
            return now

    def is_done(self, file_id):
        with self._conn() as c:
            cur = c.execute("SELECT done FROM files WHERE file_id=?", (file_id,))
            row = cur.fetchone()
            return bool(row and row[0])

    def mark_done(self, file_id):
        with self._conn() as c:
            c.execute(
                "UPDATE files SET done=1, done_at=? WHERE file_id=?",
                (time.time(), file_id),
            )

    def alert_sent(self, file_id):
        with self._conn() as c:
            cur = c.execute("SELECT alert_sent FROM files WHERE file_id=?", (file_id,))
            row = cur.fetchone()
            return bool(row and row[0])

    def mark_alert_sent(self, file_id):
        with self._conn() as c:
            c.execute("UPDATE files SET alert_sent=1 WHERE file_id=?", (file_id,))
