# Changelog

All notable changes to this project are documented in this file.

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
