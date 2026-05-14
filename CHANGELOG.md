# Changelog

All notable changes to this project are documented in this file.

## [1.2.2] - 2026-05-14

### Fixed
- Remove unused `os` import from `main.py` (ruff F401).

## [1.2.1] - 2026-03-24

### Fixed
- **Discord explicit content rejection (code 20009)**: When Discord rejects a thumbnail
  attachment because the destination channel is not marked NSFW, the notifier now retries
  the same notification without the image and appends a note to the embed footer explaining
  the removal, rather than failing the notification entirely.

## [1.2.0] - 2026-03-19

### Fixed
- **Duplicate notifications across runs**: Notifications are now tracked per-video
  per-channel in a new `video_notifications` table. Previously, if a Discord send
  partially succeeded mid-batch, no videos in that batch were marked as notified,
  causing all of them to be re-notified on every subsequent run.
- **Duplicate video detection**: The uniqueness constraint on the `videos` table has
  changed from `(creator_id, video_id)` to `(creator_id, title)`. ManyVids lists
  some videos under multiple IDs (regular/mobile variants, different editions with
  the same title); each distinct ID was previously treated as a new video and
  notified separately.

### Changed
- **Per-channel notification tracking**: Each channel (email, discord) is now tracked
  independently. If email succeeds but Discord fails, the next retry only attempts
  Discord — email is not re-sent.
- **Discord notifications sent one at a time with a configurable delay**: A
  `delay_between_notifications` setting (default 10 s, configurable per channel
  under `notifications.discord`) is enforced between every Discord webhook call,
  including across creator boundaries and between the retry pass and the new-video
  pass.
- **Email notifications remain batched per creator**: All new videos for a creator
  are sent in a single email, unchanged from previous behaviour.
- Scraper early-stop now uses known titles instead of known video IDs, consistent
  with the new uniqueness constraint.

### Migration
Existing databases are migrated automatically on first startup:
- The `video_notifications` table is created.
- Previously-notified videos (`notified_at IS NOT NULL`) are marked as notified on
  both `email` and `discord` channels, preventing re-notification.
- The `videos` table is rebuilt with `UNIQUE(creator_id, title)`; duplicate-titled
  rows are deduplicated by keeping the earliest `first_seen`.

## [1.1.7] - 2026-03-09

### Fixed
- Discord embed thumbnails now delivered as multipart file attachments instead
  of hotlinked URLs. The ManyVids image proxy rejects unauthenticated requests
  from Discord's embed fetcher, causing the entire embed to be silently dropped.
  The notifier now downloads the thumbnail locally (5 s timeout, graceful
  fallback to no image on failure) and attaches it as `files[0]` in a
  `multipart/form-data` POST with `"url": "attachment://thumbnail.jpg"`.
- Added `requests` library dependency to support multipart POST encoding.

## [1.1.6] - 2026-03-06

### Changed
- Discord notifications no longer include a plaintext `content` message;
  only the rich embed is sent, eliminating the duplicate plain-text line.

## [1.1.5] - 2026-02-28

### Changed
- Discord notifications now send one webhook call per discovered video
  instead of batching many videos into one request.
- Added Discord 429 rate-limit retry handling (uses `retry_after` when present).
- This reduces message breakage risk on large discovery runs.

## [1.1.4] - 2026-02-28

### Changed
- Discord video embed titles now include creator display name prefix:
  - Format: `{Creator Name} - [Regular|Mobile] {Video Title}`
  - Example: `Ashley Alban - [Regular] Sundress Ass & Feet Tease`

## [1.1.3] - 2026-02-28

### Fixed
- Mobile video classification now uses rendered DOM section metadata:
  - Videos shown in `VerticalVideosSection` are labeled `Mobile`.
  - Resolves misclassification of entries like `Time to worship my feet, boy`.
- Thumbnail enrichment now uses DOM card image URLs as fallback/override, improving
  thumbnail availability in notifications.
- Discord notifications now include per-video embeds with:
  - explicit `Regular` / `Mobile` in embed title
  - per-video thumbnail image when available
  - direct video URL on each embed

## [1.1.2] - 2026-02-28

### Added
- Startup/container runtime debug diagnostics in logs:
  - app version
  - Python version/implementation/executable
  - platform string
  - Playwright package version
- Browser startup diagnostics in logs:
  - Chromium version from the launched Playwright browser
  - active scraper user-agent

## [1.1.1] - 2026-02-28

### Changed
- Standardized project process documentation:
  - Enforced mandatory changelog updates for every change.
  - Enforced mandatory version bumping when releasing code changes.
  - Enforced mandatory creation/push of Git tags for each version.

## [1.1.0] - 2026-02-28

### Added
- Internal polling loop runtime mode (startup run + jittered daily sleep).
- CI quality gates before image publish:
  - `ruff check src`
  - `ruff format --check src`
  - `mypy src`
- Application version support via `src/version.py` and startup version logging.
- Discord notification diagnostics:
  - HTTP error body logging.
  - Browser-like request headers.
  - Embed length protection.
- Video metadata enrichment:
  - Per-video type (`Regular`/`Mobile`).
  - Per-video thumbnail URL capture and persistence.
- Email notification improvements:
  - Creator page links.
  - Direct video links.
  - Thumbnail rendering support.
- Database schema migration support for new video metadata fields.

### Changed
- Docker Compose restart policy changed to `unless-stopped`.
- Scraper now checks both regular and mobile verticals.
- Notification payload now includes creator context for better links.
