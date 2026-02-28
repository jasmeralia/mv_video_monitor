# ManyVids Video Monitor

Monitors ManyVids creator pages for new video uploads and sends notifications when new content is detected. Runs as a Docker container on a cron schedule.

## Features

- Scrapes multiple creator pages using a headless Chromium browser (Playwright)
- Tracks seen videos in a SQLite database to avoid duplicate notifications
- Supports email, Discord webhook, and Matrix webhook notifications
- Randomized delays between requests to avoid rate limiting
- Retry logic with exponential backoff on scrape failures
- Retries failed notifications on the next run
- Dry-run mode for testing without writing to the database or sending notifications

## Quick Start

1. Copy `config.example.yaml` to a local directory and edit it with your creators and notification settings.
2. Pull and run the container (see [docker-compose.yml](#docker-compose) below).

```bash
docker compose up
```

Logs and the database are written to the `./data` directory.

## Configuration

The monitor is configured via a YAML file. Copy `config.example.yaml` to get started.

The container looks for the config file at `/config/config.yaml` by default. Override this with the `CONFIG_PATH` environment variable.

---

### `creators`

A list of ManyVids creators to monitor.

```yaml
creators:
  - creator_id: "1002990973"       # Numeric ID from the profile URL
    creator_name: "karneli_bandi"  # Slug from the profile URL
    display_name: "Karneli Bandi"  # Human-readable name used in notifications
```

The creator profile URL has the form:
```
https://www.manyvids.com/Profile/{creator_id}/{creator_name}/Store/Videos?sort=newest
```

---

### `scraping`

Controls browser behavior and request pacing.

```yaml
scraping:
  delay_between_creators_min: 30   # Minimum seconds to wait between creator checks
  delay_between_creators_max: 60   # Maximum seconds to wait (actual delay is random in range)
  delay_between_pages_min: 3       # Minimum seconds between paginated requests
  delay_between_pages_max: 8       # Maximum seconds between paginated requests
  page_timeout: 30000              # Playwright page.goto timeout in milliseconds
  max_retries: 3                   # Number of retry attempts per creator on failure
  retry_backoff_base: 10           # Base seconds for exponential backoff (10s, 20s, 40s, ...)
  user_agent: "Mozilla/5.0 ..."    # Browser User-Agent string sent with requests
  headless: true                   # Run browser headlessly (set false for local debugging)
```

---

### `notifications`

Set `type` to one of `"email"`, `"discord"`, or `"matrix"`. To enable multiple notification channels at once, pass a list instead — all listed channels will fire for every notification. Only the sections matching the active type(s) need to be fully configured.

#### Email

```yaml
notifications:
  type: "email"

  email:
    smtp_host: "smtp.example.com"
    smtp_port: 587
    smtp_use_tls: true                        # Use STARTTLS (recommended)
    smtp_user: "user@example.com"
    smtp_password: "password"
    from_address: "manyvids-monitor@example.com"
    from_name: "ManyVids Monitor"
    to_addresses:
      - "recipient@example.com"
      - "another@example.com"
```

#### Discord

```yaml
notifications:
  type: "discord"

  discord:
    webhook_url: "https://discord.com/api/webhooks/..."
```

#### Multiple channels

```yaml
notifications:
  type: ["email", "discord"]

  email:
    smtp_host: "smtp.example.com"
    # ... (full email config)

  discord:
    webhook_url: "https://discord.com/api/webhooks/..."
```

#### Matrix

```yaml
notifications:
  type: "matrix"

  matrix:
    homeserver: "https://matrix.example.com"
    room_id: "!roomid:example.com"
    access_token: "syt_..."
```

---

### `database`

```yaml
database:
  path: "/data/monitor.db"   # Path inside the container; mount /data as a volume
```

---

### `logging`

```yaml
logging:
  level: "INFO"                  # DEBUG, INFO, WARNING, ERROR
  file: "/data/logs/monitor.log" # Log file path inside the container
  max_bytes: 10485760            # Rotate when log reaches this size (10 MB default)
  backup_count: 5                # Number of rotated log files to keep
```

---

## Docker Compose

A `docker-compose.yml` is included in the repository. It mounts two local directories into the container:

| Host path     | Container path | Purpose                        |
|---------------|----------------|--------------------------------|
| `./config`    | `/config`      | Read `config.yaml` from here   |
| `./data`      | `/data`        | Database and log files written here |

Create the directories and drop in your config before starting:

```bash
mkdir -p config data
cp config.example.yaml config/config.yaml
# edit config/config.yaml
docker compose up
```

To run a single check immediately (useful for testing):

```bash
docker compose run --rm monitor
```

To run in dry-run mode (scrapes and logs detected videos, no DB writes or notifications):

```bash
docker compose run --rm -e DRY_RUN=1 monitor
```

---

## Scheduling

The container runs the monitor once and exits. Schedule it with cron or a container orchestrator.

**Cron example** (run daily at 08:00):

```cron
0 8 * * * docker compose -f /path/to/docker-compose.yml run --rm monitor
```

**TrueNAS SCALE**: Add the container via the Apps UI with the same volume mounts, then create a cron job in System > Advanced > Cron Jobs pointing at the `docker compose run` command.

---

## Building from Source

```bash
docker build -t mv_video_monitor .
```

Pre-built images are published to GHCR on every push to `master`:

```
ghcr.io/jasmeralia/mv_video_monitor:master
```

Tagged releases are also published (e.g. `ghcr.io/jasmeralia/mv_video_monitor:1.0.0`).

---

## License

MIT — see [LICENSE.txt](LICENSE.txt).
