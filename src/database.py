import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id TEXT NOT NULL UNIQUE,
    creator_name TEXT NOT NULL,
    display_name TEXT,
    last_checked TIMESTAMP,
    last_check_status TEXT,
    consecutive_errors INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    url TEXT NOT NULL,
    price_regular TEXT,
    duration TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notified_at TIMESTAMP,
    UNIQUE(creator_id, video_id),
    FOREIGN KEY (creator_id) REFERENCES creators(creator_id)
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    run_finished_at TIMESTAMP,
    creators_checked INTEGER DEFAULT 0,
    new_videos_found INTEGER DEFAULT 0,
    notifications_sent INTEGER DEFAULT 0,
    status TEXT,
    notes TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(SCHEMA)
        logger.debug(f"Database initialized at {self.db_path}")

    # --- Creator operations ---

    def upsert_creator(
        self,
        creator_id: str,
        creator_name: str,
        display_name: Optional[str] = None,
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO creators (creator_id, creator_name, display_name)
                VALUES (?, ?, ?)
                ON CONFLICT(creator_id) DO UPDATE SET
                    creator_name = excluded.creator_name,
                    display_name = COALESCE(excluded.display_name, display_name)
                """,
                (creator_id, creator_name, display_name),
            )

    def get_all_creators(self) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM creators ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def update_creator_check(self, creator_id: str, status: str) -> None:
        now = _now()
        with self._get_conn() as conn:
            if status == "ok":
                conn.execute(
                    """
                    UPDATE creators
                    SET last_checked = ?, last_check_status = ?, consecutive_errors = 0
                    WHERE creator_id = ?
                    """,
                    (now, status, creator_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE creators
                    SET last_checked = ?, last_check_status = ?,
                        consecutive_errors = consecutive_errors + 1
                    WHERE creator_id = ?
                    """,
                    (now, status, creator_id),
                )

    # --- Video operations ---

    def get_known_video_ids(self, creator_id: str) -> set[str]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT video_id FROM videos WHERE creator_id = ?",
                (creator_id,),
            ).fetchall()
            return {r["video_id"] for r in rows}

    def insert_new_videos(self, creator_id: str, videos: list[dict]) -> list[dict]:
        """
        Insert videos not already in the DB. Returns only the newly inserted ones.
        Uses INSERT OR IGNORE for idempotency.
        """
        newly_inserted = []
        with self._get_conn() as conn:
            for v in videos:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO videos
                        (creator_id, video_id, title, slug, url, price_regular, duration)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        creator_id,
                        v["video_id"],
                        v["title"],
                        v["slug"],
                        v["url"],
                        v.get("price_regular"),
                        v.get("duration"),
                    ),
                )
                if cursor.rowcount > 0:
                    newly_inserted.append(v)
        return newly_inserted

    def mark_videos_notified(self, video_ids: list[str]) -> None:
        now = _now()
        with self._get_conn() as conn:
            conn.executemany(
                "UPDATE videos SET notified_at = ? WHERE video_id = ?",
                [(now, vid) for vid in video_ids],
            )

    def get_unnotified_videos(self) -> list[dict]:
        """
        Returns videos that were inserted but never successfully notified.
        Joins creators to get display_name for grouping by notifier.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT v.*, c.display_name, c.creator_name
                FROM videos v
                JOIN creators c USING (creator_id)
                WHERE v.notified_at IS NULL
                ORDER BY v.creator_id, v.first_seen
                """
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Run log operations ---

    def start_run(self) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO run_log (run_started_at) VALUES (?)",
                (_now(),),
            )
            return cursor.lastrowid

    def finish_run(
        self,
        run_id: int,
        creators_checked: int,
        new_videos: int,
        notifications_sent: int,
        status: str,
        notes: str = "",
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE run_log SET
                    run_finished_at = ?,
                    creators_checked = ?,
                    new_videos_found = ?,
                    notifications_sent = ?,
                    status = ?,
                    notes = ?
                WHERE id = ?
                """,
                (_now(), creators_checked, new_videos, notifications_sent, status, notes, run_id),
            )
