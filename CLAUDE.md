# ManyVids Creator Monitor - Project Context

## Project Overview
A monitoring script to track new video uploads from specified ManyVids creators and send notifications when new content is detected.

## Requirements

### Functional Requirements
- Monitor approximately 10 ManyVids creators for new video uploads
- Check daily with configurable delays between creator checks (30-60 seconds)
- Track which videos have been seen to identify new uploads
- Send notifications with direct links to new videos
- Initial notification method: Email
- Future notification methods: Discord webhook, Matrix webhook

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

### Known Challenges
1. **Content Protection**: Video titles are blurred for non-logged-in users
   - Data likely available in HTML/JavaScript despite visual obfuscation
   - May be in data attributes, script tags, or API responses
   
2. **Anti-Scraping Measures**: 
   - Likely uses Cloudflare or similar protection
   - May require proper User-Agent and headers
   - Potential rate limiting
   - Possible CAPTCHA challenges

3. **Dynamic Content**:
   - Content loaded via JavaScript
   - Need to wait for DOM rendering
   - May use infinite scroll or pagination

## Architecture Design

### Components

#### 1. Data Storage (SQLite)
```
Tables:
- creators: id, creator_id, creator_name, last_checked
- videos: id, creator_id, video_id, title, url, first_seen
- config: key, value
```

#### 2. Scraper Module
- Playwright-based headless browser
- Configurable delays between requests
- Retry logic with exponential backoff
- Error handling and logging

#### 3. Notification Module (Pluggable)
- Email (initial implementation)
  - SMTP configuration
  - HTML email templates with direct video links
- Webhook interface (future)
  - Discord webhook format
  - Matrix webhook format

#### 4. Scheduler
- Daily execution via cron
- Configurable run time
- Logging of all runs

### Configuration File Structure
```yaml
creators:
  - name: "karneli_bandi"
    id: "1002990973"
  # Add more creators...

scraping:
  delay_between_creators: 45  # seconds
  timeout: 30  # seconds
  user_agent: "Mozilla/5.0 ..."
  max_retries: 3

notifications:
  type: "email"  # or "discord", "matrix"
  
  email:
    smtp_host: "smtp.example.com"
    smtp_port: 587
    smtp_user: "user@example.com"
    smtp_password: "password"
    from_address: "manyvids-monitor@example.com"
    to_addresses:
      - "recipient@example.com"
  
  # Future webhook configs
  discord:
    webhook_url: "https://discord.com/api/webhooks/..."
  
  matrix:
    homeserver: "https://matrix.example.com"
    room_id: "!roomid:example.com"
    access_token: "..."

logging:
  level: "INFO"
  file: "/data/logs/monitor.log"
```

### Directory Structure
```
manyvids-monitor/
├── Dockerfile
├── requirements.txt
├── config.yaml (mounted volume)
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── scraper.py
│   ├── database.py
│   ├── notifier.py
│   └── utils.py
├── data/ (mounted volume)
│   ├── monitor.db
│   └── logs/
└── README.md
```

## Implementation Steps

### Phase 1: Core Scraping (Priority)
1. **Setup Development Environment**
   - Create project structure
   - Initialize git repository
   - Set up virtual environment

2. **Page Structure Analysis**
   - Manually inspect ManyVids creator pages
   - Identify video data location (DOM, script tags, API calls)
   - Document selectors and data extraction methods
   - Test with multiple creators to ensure consistency

3. **Scraper Development**
   - Implement Playwright-based scraper
   - Extract video IDs, titles, and URLs
   - Add delay and retry logic
   - Handle errors gracefully

4. **Database Layer**
   - Create SQLite schema
   - Implement CRUD operations
   - Add migration support for schema changes

### Phase 2: Change Detection & Notifications
1. **Change Detection Logic**
   - Compare newly scraped videos against database
   - Identify truly new videos (not just re-ordered)
   - Update database with new videos

2. **Email Notifications**
   - Create HTML email template
   - Implement SMTP sending
   - Include direct links to new videos
   - Handle multiple new videos per creator

### Phase 3: Containerization & Deployment
1. **Docker Container**
   - Create Dockerfile with Playwright dependencies
   - Configure volume mounts for config and data
   - Set up proper user permissions

2. **TrueNAS Deployment**
   - Create container in TrueNAS SCALE
   - Configure persistent storage
   - Set up cron schedule
   - Test end-to-end execution

### Phase 4: Future Enhancements
1. **Webhook Notifications**
   - Implement Discord webhook format
   - Implement Matrix webhook format
   - Add notification type selection logic

2. **Monitoring & Alerts**
   - Add health checks
   - Alert on scraping failures
   - Track success/failure metrics

## Development Notes

### Mandatory Local Validation Policy
- After any code change, always run linting/type checks in the project virtual environment before finishing:
  - `ruff check src`
  - `ruff format --check src`
  - `mypy src`
- Resolve all reported issues before commit/push.
- This is automatic and required on every change unless explicitly told otherwise.

### Mandatory Release Hygiene Policy
- For every change, update `CHANGELOG.md` with an entry describing what changed.
- For every code change release, bump the application version in `src/version.py`.
- For every bumped version, create a Git tag (for example `v1.2.3`) and push it to GitHub.
- These steps are mandatory and performed automatically unless explicitly told otherwise.

### Testing Strategy
- Test scraper with various creators to ensure consistency
- Mock Playwright responses for unit tests
- Test notification delivery before enabling scheduling
- Dry-run mode to verify detection logic without sending notifications

### Security Considerations
- Store SMTP credentials securely (env vars or secrets)
- Don't commit config.yaml with real credentials
- Consider using app passwords for email
- Rate limit to avoid detection/blocking

### Error Handling Priorities
1. Network failures (retry with backoff)
2. Page structure changes (log and alert)
3. Database errors (log and fail safely)
4. Notification failures (log but continue processing other creators)

### Logging Requirements
- Timestamp all operations
- Log each creator check (success/failure)
- Log new videos detected
- Log notification attempts
- Rotate logs to prevent disk fill

## Open Questions to Resolve

1. **Page Structure**: Need to inspect actual ManyVids pages to determine:
   - How video data is stored in HTML/JS
   - Best selectors for extraction
   - Whether login provides better access to data

2. **Video URL Format**: Need to determine:
   - Format of direct video page URLs
   - Whether video IDs are sufficient to construct URLs
   - Example: https://www.manyvids.com/Video/{video_id}/...

3. **Anti-Bot Detection**: Need to test:
   - Whether Cloudflare blocks Playwright
   - Optimal request rate to avoid blocking
   - Whether logged-in session cookies help

4. **Login Strategy**: Decide:
   - Whether to implement login functionality
   - If manual login + cookie export is sufficient
   - Trade-offs of logged vs non-logged scraping

## Resources & References

- Playwright Documentation: https://playwright.dev/python/
- ManyVids (example creator): https://www.manyvids.com/Profile/1002990973/karneli_bandi/Store/Videos?sort=newest
- SMTP Configuration: Reference existing TrueNAS email alerts
- Matrix Webhooks: Reference existing Matrix homeserver setup

## Timeline Estimate

- **Initial Development**: 3-4 hours
  - Page analysis: 1 hour
  - Scraper implementation: 2 hours
  - Database setup: 1 hour

- **Testing & Refinement**: 1-2 hours
  - Multi-creator testing
  - Notification testing
  - Edge case handling

- **Containerization**: 30 minutes
  - Dockerfile creation
  - TrueNAS deployment

- **Total**: ~5-7 hours for MVP

## Success Criteria

- Successfully detects new videos from all monitored creators
- Sends email notifications within 24 hours of upload
- Runs reliably on daily schedule
- No false positives (doesn't re-notify for same videos)
- Handles temporary failures gracefully
- Logs are clear and actionable

## Next Steps (When Ready to Implement)

1. Set up development environment on Windows or WSL
2. Manually inspect ManyVids creator pages in browser dev tools
3. Document page structure and data extraction approach
4. Create initial scraper prototype
5. Test with 2-3 creators before full implementation
