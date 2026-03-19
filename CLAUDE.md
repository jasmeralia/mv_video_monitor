# ManyVids Creator Monitor - Project Context

## Project Overview
A monitoring script to track new video uploads from specified ManyVids creators and send notifications when new content is detected.

---

## Mandatory Local Validation Policy

After any code change, always run linting/type checks in the project virtual environment before finishing:

1. `ruff check src`
2. `ruff format --check src`
3. `mypy src`

Resolve all reported issues before commit/push. This is automatic and required on every change unless explicitly told otherwise.

## Mandatory Release Hygiene Policy

1. For every change, update `CHANGELOG.md` with an entry describing what changed.
2. For every code change release, bump the application version in `src/version.py`.
3. For every bumped version, create a Git tag (for example `v1.2.3`) and push it to GitHub.

These steps are mandatory and performed automatically unless explicitly told otherwise.

---

## Requirements

### Functional Requirements
- Monitor approximately 10 ManyVids creators for new video uploads
- Check daily with configurable delays between creator checks (30-60 seconds)
- Track which videos have been seen to identify new uploads
- Send notifications with direct links to new videos
- Notification channels: Email, Discord webhook; Matrix webhook (stub, not yet implemented)

### Technical Requirements
- Run as Docker container on TrueNAS SCALE
- Use headless browser (Playwright) to handle JavaScript-rendered content
- Persist data between runs (SQLite database)
- Configurable via external config file
- Scheduled execution via cron

## Target Website Analysis

### Example URL Structure
```
https://www.manyvids.com/Profile/{creator_id}/{creator_name}/Store/Videos?sort=newest
Example: https://www.manyvids.com/Profile/1002990973/karneli_bandi/Store/Videos?sort=newest
```

### Known Characteristics
1. **Content extraction**: Video data is embedded in Next.js RSC streaming payloads (`self.__next_f.push`) inside `<script>` tags. Extracted via regex against the JSON-encoded payload.

2. **Anti-scraping**: Playwright with a realistic Chrome user-agent and webdriver masking has been sufficient so far. No login is required or implemented; the scraper runs anonymously.

3. **Dynamic content**: Page is JavaScript-rendered; scraper waits for the `isVideosStore` RSC payload to appear before reading content.

4. **Duplicate video IDs**: ManyVids lists the same video title under multiple IDs (regular/mobile variants, multiple editions). Uniqueness is enforced by `(creator_id, title)` in the database, not by video ID.

## Architecture Design

### Components

#### 1. Data Storage (SQLite)
```
Tables:
- creators: id, creator_id, creator_name, display_name, last_checked, last_check_status, consecutive_errors
- videos: id, creator_id, video_id, title, slug, url, video_type, thumbnail_url, price_regular, duration, first_seen
          UNIQUE(creator_id, title)
- video_notifications: video_id, channel, notified_at
                       PRIMARY KEY(video_id, channel)
- run_log: id, run_started_at, run_finished_at, creators_checked, new_videos_found, notifications_sent, status, notes
```

#### 2. Scraper Module
- Playwright-based headless browser
- Scrapes both regular (vertical=1) and mobile (vertical=2) page sections
- Configurable delays between pages and creators
- Retry logic with exponential backoff
- Early-stop pagination: stops when all titles on a page are already known

#### 3. Notification Module
- Per-channel notification tracking: each channel (email, discord, matrix) tracked independently
- Email: batched per creator, one email listing all new videos
- Discord: one webhook call per video, with configurable delay between calls (default 10 s), applied globally across all creators
- Matrix: stub only, not yet implemented

#### 4. Scheduler
- Runs in a polling loop with configurable interval and jitter
- Supports `RUN_ONCE=1` for cron-based external scheduling

### Directory Structure
```
mv_video_monitor/
├── Dockerfile
├── requirements.txt
├── config.yaml (mounted volume, gitignored)
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── scraper.py
│   ├── database.py
│   ├── notifier.py
│   ├── utils.py
│   └── version.py
├── data/ (mounted volume)
│   ├── monitor.db
│   └── logs/
└── CHANGELOG.md
```

## Pending Action Items

1. **Matrix webhook implementation** — `MatrixNotifier.send_notification` is currently a stub that logs a warning and returns `False`. Needs a real implementation when Matrix notifications are desired.

2. **Health checks** — No health check endpoint or mechanism exists. Consider adding a heartbeat file write or HTTP endpoint so TrueNAS/container orchestration can detect if the monitor has stalled.

## Development Notes

### Testing Strategy
- Test scraper with various creators to ensure consistency
- Dry-run mode (`--dry-run` flag or `DRY_RUN=1`) to verify detection logic without DB writes or notifications
- Test notification delivery manually before enabling scheduling

### Security Considerations
- Store SMTP credentials and webhook URLs securely (env vars or secrets)
- `config.yaml` is gitignored — do not commit real credentials
- Use app passwords for email

### Error Handling Priorities
1. Network failures (retry with backoff)
2. Page structure changes (log and alert)
3. Database errors (log and fail safely)
4. Notification failures (log but continue; retry on next run per channel)

### Logging Requirements
- Timestamp all operations
- Log each creator check (success/failure)
- Log new videos detected
- Log notification attempts per channel
- Rotate logs to prevent disk fill

## Resources & References

- Playwright Documentation: https://playwright.dev/python/
- ManyVids (example creator): https://www.manyvids.com/Profile/1002990973/karneli_bandi/Store/Videos?sort=newest
- SMTP Configuration: Reference existing TrueNAS email alerts
- Matrix Webhooks: Reference existing Matrix homeserver setup

## Success Criteria

- Successfully detects new videos from all monitored creators
- Sends notifications within 24 hours of upload
- Runs reliably on daily schedule
- No false positives (doesn't re-notify for same videos)
- Handles temporary failures gracefully; retries failed channels on next run
- Logs are clear and actionable
