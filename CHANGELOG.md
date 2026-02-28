# Changelog

All notable changes to this project are documented in this file.

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

