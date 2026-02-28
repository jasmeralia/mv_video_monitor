import asyncio
import logging
import os
import random
import sys
import time
from collections import defaultdict

from .database import Database
from .notifier import create_notifier
from .scraper import ManyVidsScraper
from .utils import load_config, setup_logging

logger = logging.getLogger(__name__)


async def run_monitor(config_path: str, dry_run: bool = False) -> int:
    """
    Main orchestration loop.

    Args:
        config_path: Path to config.yaml
        dry_run: If True, scrape and detect new videos but skip DB writes and notifications

    Returns exit code: 0=success, 1=partial failure, 2=total failure
    """
    config = load_config(config_path)
    setup_logging(config)

    if dry_run:
        logger.info("=== DRY RUN MODE — no DB writes or notifications ===")

    db = Database(config["database"]["path"])
    notifier = create_notifier(config)

    # Sync creators from config into the database
    for c in config["creators"]:
        db.upsert_creator(
            creator_id=c["creator_id"],
            creator_name=c["creator_name"],
            display_name=c.get("display_name"),
        )

    run_id = db.start_run() if not dry_run else None
    creators_checked = 0
    total_new_videos = 0
    notifications_sent = 0
    failed_creators: list[str] = []

    # Step 1: Retry any previously un-notified videos (failed notification from last run)
    if not dry_run:
        unnotified = db.get_unnotified_videos()
        if unnotified:
            logger.info(
                f"Retrying notifications for {len(unnotified)} previously un-notified videos"
            )
            by_creator: dict[str, list[dict]] = defaultdict(list)
            for v in unnotified:
                by_creator[v["creator_id"]].append(v)
            for creator_id, videos in by_creator.items():
                display_name = (
                    videos[0].get("display_name") or videos[0]["creator_name"]
                )
                success = notifier.send_notification(display_name, videos)
                if success:
                    db.mark_videos_notified([v["video_id"] for v in videos])
                    notifications_sent += 1

    # Step 2: Scrape all creators
    creators = db.get_all_creators()
    logger.info(f"Starting monitor run for {len(creators)} creator(s)")

    async with ManyVidsScraper(config) as scraper:
        for i, creator in enumerate(creators):
            creator_id = creator["creator_id"]
            creator_name = creator["creator_name"]
            display_name = creator.get("display_name") or creator_name

            logger.info(
                f"[{i + 1}/{len(creators)}] Checking creator: {creator_name} (id={creator_id})"
            )

            known_ids = db.get_known_video_ids(creator_id) if not dry_run else set()
            result = await scraper.scrape_creator_with_retry(
                creator_id, creator_name, known_ids
            )

            if result.error:
                logger.error(f"Creator {creator_name}: FAILED — {result.error}")
                if not dry_run:
                    db.update_creator_check(creator_id, "error")
                failed_creators.append(creator_name)
                # Delay before next creator even on failure
                if i < len(creators) - 1:
                    await _inter_creator_delay(config)
                continue

            if dry_run:
                logger.info(
                    f"Creator {creator_name}: {len(result.videos)} videos scraped "
                    f"(dry run — skipping DB check)"
                )
            else:
                new_videos = db.insert_new_videos(
                    creator_id,
                    [v.to_dict() for v in result.videos],
                )
                db.update_creator_check(creator_id, "ok")
                creators_checked += 1
                total_new_videos += len(new_videos)

                logger.info(
                    f"Creator {creator_name}: {len(result.videos)} total scraped, "
                    f"{len(new_videos)} new"
                )

                if new_videos:
                    success = notifier.send_notification(display_name, new_videos)
                    if success:
                        db.mark_videos_notified([v["video_id"] for v in new_videos])
                        notifications_sent += 1
                    else:
                        logger.error(
                            f"Creator {creator_name}: notification failed — "
                            "will retry next run"
                        )

            if i < len(creators) - 1:
                await _inter_creator_delay(config)

    # Step 3: Log run summary
    if not dry_run and run_id is not None:
        if not failed_creators:
            status = "success"
        elif creators_checked > 0:
            status = "partial"
        else:
            status = "failed"

        notes = f"Errors: {failed_creators}" if failed_creators else ""
        db.finish_run(
            run_id=run_id,
            creators_checked=creators_checked,
            new_videos=total_new_videos,
            notifications_sent=notifications_sent,
            status=status,
            notes=notes,
        )

        logger.info(
            f"Run complete: {creators_checked}/{len(creators)} creators checked, "
            f"{total_new_videos} new videos, {notifications_sent} notifications sent"
        )
    elif dry_run:
        logger.info("Dry run complete.")

    if failed_creators and creators_checked == 0:
        return 2
    elif failed_creators:
        return 1
    return 0


async def _inter_creator_delay(config: dict) -> None:
    delay = random.uniform(
        config["scraping"]["delay_between_creators_min"],
        config["scraping"]["delay_between_creators_max"],
    )
    logger.debug(f"Waiting {delay:.0f}s before next creator")
    await asyncio.sleep(delay)


def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "/config/config.yaml")
    dry_run = "--dry-run" in sys.argv or os.environ.get("DRY_RUN", "").lower() in (
        "1",
        "true",
    )
    run_once = os.environ.get("RUN_ONCE", "").lower() in ("1", "true")
    poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "86400"))
    poll_jitter = int(os.environ.get("POLL_JITTER_SECONDS", "1800"))

    if run_once:
        exit_code = asyncio.run(run_monitor(config_path, dry_run=dry_run))
        sys.exit(exit_code)

    while True:
        exit_code = asyncio.run(run_monitor(config_path, dry_run=dry_run))
        min_sleep = max(0, poll_interval - poll_jitter)
        max_sleep = poll_interval + poll_jitter
        delay = random.uniform(min_sleep, max_sleep)
        logger.info(
            f"Polling cycle complete (exit={exit_code}). Sleeping {delay:.0f}s "
            f"(range {min_sleep}-{max_sleep}s) before next cycle."
        )
        time.sleep(delay)


if __name__ == "__main__":
    main()
