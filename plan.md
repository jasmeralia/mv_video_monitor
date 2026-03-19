# Plan: Fix Duplicate Notifications, Per-Channel Tracking, and Title Deduplication

## Root Causes Found

1. **Partial-batch failure bug**: `send_notification` sends videos one-by-one to Discord. If video #3 fails, videos #1 and #2 were already sent but `mark_videos_notified` is never called (because overall `success = False`). On the next run, all three are retried — re-notifying #1 and #2.

2. **No inter-notification delay**: Multiple Discord webhook calls fire back-to-back with no gap, increasing rate-limit risk. No gap between creators either.

3. **Title not unique per creator**: ManyVids lists the same video under multiple IDs (regular/mobile variants, and possibly duplicate editions). Each new ID is treated as a new video and notified separately. The `video_type` regex (`"type":"([^"]+)"`) may also be capturing a section/display type from the RSC payload rather than a per-video format type, which could incorrectly label regular videos as "mobile".

---

## Changes

### 1. Per-channel notification tracking (`database.py`)

Add a new table:
```sql
CREATE TABLE IF NOT EXISTS video_notifications (
    video_id TEXT NOT NULL,
    channel  TEXT NOT NULL,   -- 'email', 'discord', 'matrix'
    notified_at TIMESTAMP NOT NULL,
    PRIMARY KEY (video_id, channel)
);
```

Schema migration (runs automatically on startup):
- For every existing `videos` row where `notified_at IS NOT NULL`, insert rows into `video_notifications` for each currently-configured channel. (Conservative: assume previously-notified videos were sent on all active channels.)

Database API changes:
- Replace `mark_videos_notified(video_ids: list[str])` with `mark_video_notified(video_id: str, channel: str)` — marks a single (video, channel) pair immediately after a successful send.
- Replace `get_unnotified_videos()` with `get_unnotified_videos(channels: list[str]) -> list[dict]` — returns videos missing at least one notification for the given channels. Each returned dict includes a `missing_channels: list[str]` key.

The existing `notified_at` column on `videos` is removed (fully replaced by `video_notifications`).

### 2. Restructure notification orchestration (`notifier.py`, `main.py`)

**`notifier.py`:**
- Add a `channel_name: str` property to `BaseNotifier` (returns `"email"`, `"discord"`, `"matrix"`).
- `send_notification(creator_name, videos: list[dict])` **keeps its existing batch interface** — no change to notifier signatures.
- Remove `MultiNotifier` — multi-channel fan-out is now handled in `main.py`.

**`main.py`:**
- Load active notifiers as an ordered list (one per configured channel), not wrapped in `MultiNotifier`.
- Notification orchestration differs by channel type:
  - **Email**: collect all videos for a creator that are unnotified on `email`, call `email.send_notification(creator, batch)` once, mark each video on success.
  - **Discord**: iterate one video at a time, call `discord.send_notification(creator, [video])`, mark immediately on success, sleep `discord_delay` after each call.
- The Discord delay applies globally — between every Discord webhook call, whether in the retry pass or the new-video pass, and across creator boundaries.
- The retry pass (unnotified videos from prior runs) and the new-video pass use the same per-video-per-channel logic. Only missing channels are attempted for each video.

### 3. Configurable inter-notification delay (`config.yaml`, `main.py`)

Add to `config.yaml`:
```yaml
notifications:
  discord:
    webhook_url: "..."
    delay_between_notifications: 10.0   # seconds between Discord webhook calls
```

Default: `10.0` seconds. Read in `main.py` and passed into the notification loop. Email and Matrix are not delayed.

### 4. Title uniqueness per creator (`database.py`, `scraper.py`)

**Database migration:**
- Recreate the `videos` table with `UNIQUE(creator_id, title)` in place of `UNIQUE(creator_id, video_id)`.
- Migration step before recreating: for each `(creator_id, title)` group with multiple rows, keep the one with the earliest `first_seen` and delete the rest. Also clean up any orphaned rows in `video_notifications`.
- `insert_new_videos` continues to use `INSERT OR IGNORE` — the new unique constraint makes same-title videos silently ignored.

**Scraper early-stop:**
- `get_known_video_ids` → `get_known_titles(creator_id: str) -> set[str]`.
- Pass known titles to the scraper; stop paginating when all titles on a page are known.

**Video type detection audit (`scraper.py`):**
- The regex group 6 (`"type":"([^"]+)"`) is labeled "section type" in comments. Audit whether this field in the RSC payload refers to the video's own format type or to the ManyVids page section (e.g. HorizontalVideosSection → "mobile"). If it's a section type rather than a per-video attribute, remove or correct the `video_type` field. Since title uniqueness is now enforced, `video_type` no longer affects deduplication — but fixing it prevents misleading data in the DB.

---

## Migration Safety

- All schema migrations run automatically in `_ensure_schema()` at startup.
- The title-deduplication migration deletes rows — the deleted rows are ones that are duplicates of a retained row (same creator + title), so no notification data is lost that isn't already covered by the retained row.
- The `video_notifications` migration for existing data is conservative: previously-notified videos are marked as notified on all currently-configured channels, ensuring no re-notification of already-seen content.

---

## Files Changed

| File | Change |
|---|---|
| `src/database.py` | New `video_notifications` table; replace `mark_videos_notified`/`get_unnotified_videos`; two migrations |
| `src/notifier.py` | Add `channel_name` property; remove `MultiNotifier` |
| `src/main.py` | Per-channel notification orchestration with channel-specific logic; Discord delay; use revised DB/notifier APIs |
| `src/scraper.py` | Audit/fix `video_type` detection; swap `get_known_video_ids` → `get_known_titles` |
| `config.yaml` | Add `notifications.discord.delay_between_notifications: 2.0` |
| `src/version.py` | Bump version |
| `CHANGELOG.md` | Document changes |
