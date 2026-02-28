# CHANGELOD

## 2026-02-28

### Runtime and scheduling
- Switched from cron-oriented one-shot execution to an internal polling loop.
- Monitor now runs immediately at startup, then sleeps for `POLL_INTERVAL_SECONDS +/- POLL_JITTER_SECONDS`.
- Added optional `RUN_ONCE=1` behavior for manual single-run execution.
- Updated Compose restart policy to `unless-stopped`.

### CI quality gates
- Added GitHub Actions lint/type-check job before Docker publish:
  - `ruff check src`
  - `ruff format --check src`
  - `mypy src`
- Docker image publish now depends on passing lint/type checks.

### Notifications and scraping improvements
- Discord:
  - Added robust HTTP error logging with response body for diagnosis.
  - Added realistic browser-like request headers.
  - Added embed truncation protection to avoid oversized payload failures.
- Email:
  - Added creator-page link and creator-name hyperlink in email header.
  - Added per-video section labels (`Regular` vs `Mobile`).
  - Added thumbnail rendering with ManyVids image proxy URL normalization.
  - Kept direct per-video ManyVids links.
- Scraper:
  - Added support for scraping both regular and mobile sections (`vertical=1` and `vertical=2`).
  - Added extraction of `thumbnail_url` and section `video_type` metadata per video.
  - Enforced section labeling based on source section to distinguish regular/mobile reliably.
- Database:
  - Added `video_type` and `thumbnail_url` columns.
  - Added schema migration logic for existing databases.

### Versioning
- Added application version support in `src/version.py` with:
  - `__version__` default.
  - `APP_VERSION` environment override.
- Startup logs now include the active monitor version.
