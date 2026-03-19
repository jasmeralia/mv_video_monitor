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
    video_type TEXT,
    thumbnail_url TEXT,
    price_regular TEXT,
    duration TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(creator_id, title),
    FOREIGN KEY (creator_id) REFERENCES creators(creator_id)
);

CREATE TABLE IF NOT EXISTS video_notifications (
    video_id TEXT NOT NULL,
    channel  TEXT NOT NULL,
    notified_at TIMESTAMP NOT NULL,
    PRIMARY KEY (video_id, channel)
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
            self._migrate_schema(conn)
        logger.debug(f"Database initialized at {self.db_path}")

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

        if user_version < 1:
            self._migrate_v1(conn)
            conn.execute("PRAGMA user_version = 1")

    def _migrate_v1(self, conn: sqlite3.Connection) -> None:
        """
        - Creates video_notifications table (if not already created by SCHEMA).
        - Rebuilds videos table: removes notified_at, changes UNIQUE from
          (creator_id, video_id) to (creator_id, title).
        - Deduplicates existing rows by (creator_id, title), keeping earliest first_seen.
        - Migrates old notified_at data into video_notifications for email + discord.
        """
        # Ensure video_notifications exists (SCHEMA may have already created it for new DBs)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_notifications (
                video_id TEXT NOT NULL,
                channel  TEXT NOT NULL,
                notified_at TIMESTAMP NOT NULL,
                PRIMARY KEY (video_id, channel)
            )
        """)

        cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(videos)").fetchall()
        }

        if "notified_at" not in cols:
            # Already on new schema (new DB or previously migrated) — nothing to do.
            logger.debug("Migration v1: videos table already on new schema, skipping")
            return

        # Add any missing columns before we read/copy (very old DBs may lack these)
        if "video_type" not in cols:
            conn.execute("ALTER TABLE videos ADD COLUMN video_type TEXT")
        if "thumbnail_url" not in cols:
            conn.execute("ALTER TABLE videos ADD COLUMN thumbnail_url TEXT")

        # Capture video_ids that had successful prior notifications
        old_notified_ids = {
            row[0]
            for row in conn.execute(
                "SELECT video_id FROM videos WHERE notified_at IS NOT NULL"
            ).fetchall()
        }

        # Create replacement table with new constraints
        conn.execute("""
            CREATE TABLE videos_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                slug TEXT NOT NULL,
                url TEXT NOT NULL,
                video_type TEXT,
                thumbnail_url TEXT,
                price_regular TEXT,
                duration TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(creator_id, title),
                FOREIGN KEY (creator_id) REFERENCES creators(creator_id)
            )
        """)

        # Copy data: one row per (creator_id, title), keeping the earliest first_seen
        conn.execute("""
            INSERT INTO videos_new
                (id, creator_id, video_id, title, slug, url, video_type,
                 thumbnail_url, price_regular, duration, first_seen)
            SELECT v.id, v.creator_id, v.video_id, v.title, v.slug, v.url,
                   v.video_type, v.thumbnail_url, v.price_regular, v.duration,
                   v.first_seen
            FROM videos v
            WHERE v.id = (
                SELECT v2.id FROM videos v2
                WHERE v2.creator_id = v.creator_id AND v2.title = v.title
                ORDER BY v2.first_seen ASC
                LIMIT 1
            )
        """)

        # Determine which kept video_ids had prior notifications
        kept_ids = {
            row[0] for row in conn.execute("SELECT video_id FROM videos_new").fetchall()
        }
        ids_to_migrate = kept_ids & old_notified_ids

        conn.execute("DROP TABLE videos")
        conn.execute("ALTER TABLE videos_new RENAME TO videos")

        # Migrate old notifications into video_notifications for email + discord
        now = _now()
        for vid in ids_to_migrate:
            for channel in ("email", "discord"):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO video_notifications (video_id, channel, notified_at)
                    VALUES (?, ?, ?)
                    """,
                    (vid, channel, now),
                )

        logger.info(
            f"Migration v1: rebuilt videos table with UNIQUE(creator_id, title), "
            f"migrated {len(ids_to_migrate)} previously-notified video(s)"
        )

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

    def get_known_titles(self, creator_id: str) -> set[str]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT title FROM videos WHERE creator_id = ?",
                (creator_id,),
            ).fetchall()
            return {r["title"] for r in rows}

    def insert_new_videos(self, creator_id: str, videos: list[dict]) -> list[dict]:
        """
        Insert videos not already in the DB. Returns only the newly inserted ones.
        Uniqueness is enforced on (creator_id, title); same-title videos are ignored.
        """
        newly_inserted = []
        with self._get_conn() as conn:
            for v in videos:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO videos
                        (
                            creator_id,
                            video_id,
                            title,
                            slug,
                            url,
                            video_type,
                            thumbnail_url,
                            price_regular,
                            duration
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        creator_id,
                        v["video_id"],
                        v["title"],
                        v["slug"],
                        v["url"],
                        v.get("video_type"),
                        v.get("thumbnail_url"),
                        v.get("price_regular"),
                        v.get("duration"),
                    ),
                )
                if cursor.rowcount > 0:
                    newly_inserted.append(v)
        return newly_inserted

    def mark_video_notified(self, video_id: str, channel: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO video_notifications (video_id, channel, notified_at)
                VALUES (?, ?, ?)
                """,
                (video_id, channel, _now()),
            )

    def get_unnotified_videos(self, channels: list[str]) -> list[dict]:
        """
        Returns videos missing a notification on at least one of the given channels.
        Each returned dict includes a 'missing_channels' key listing which channels
        have not yet been notified for that video.
        """
        if not channels:
            return []
        placeholders = ",".join("?" * len(channels))
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT v.*, c.display_name, c.creator_name,
                       (
                           SELECT GROUP_CONCAT(vn.channel, ',')
                           FROM video_notifications vn
                           WHERE vn.video_id = v.video_id
                             AND vn.channel IN ({placeholders})
                       ) AS notified_channels_str
                FROM videos v
                JOIN creators c USING (creator_id)
                WHERE (
                    SELECT COUNT(*) FROM video_notifications vn
                    WHERE vn.video_id = v.video_id AND vn.channel IN ({placeholders})
                ) < ?
                ORDER BY v.creator_id, v.first_seen
                """,
                (*channels, *channels, len(channels)),
            ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            notified_str = d.pop("notified_channels_str") or ""
            notified_set = set(notified_str.split(",")) - {""}
            d["missing_channels"] = [ch for ch in channels if ch not in notified_set]
            result.append(d)
        return result

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
                (
                    _now(),
                    creators_checked,
                    new_videos,
                    notifications_sent,
                    status,
                    notes,
                    run_id,
                ),
            )
