import asyncio
import platform
import logging
import os
import random
import sys
import time
from collections import defaultdict
from importlib.metadata import PackageNotFoundError, version as package_version

from .database import Database
from .notifier import BaseNotifier, create_notifiers
from .scraper import ManyVidsScraper
from .settings import settings
from .utils import load_config, setup_logging
from .version import get_app_version

logger = logging.getLogger(__name__)
_RUNTIME_INFO_LOGGED = False


def _safe_package_version(name: str) -> str:
    try:
        return package_version(name)
    except PackageNotFoundError:
        return "not-installed"


def _log_runtime_debug_info() -> None:
    logger.info("Runtime debug info:")
    logger.info(f"  app_version={get_app_version()}")
    logger.info(f"  python_version={platform.python_version()}")
    logger.info(f"  python_implementation={platform.python_implementation()}")
    logger.info(f"  python_executable={sys.executable}")
    logger.info(f"  platform={platform.platform()}")
    logger.info(f"  playwright_version={_safe_package_version('playwright')}")


async def _send_channel_notifications(
    creator_display_name: str,
    videos: list[dict],
    notifiers: list[BaseNotifier],
    db: Database,
    discord_delay: float,
    last_discord_at: list[float],
) -> int:
    """
    Send pending notifications per channel for a set of videos.

    Each video dict must contain a 'missing_channels' key listing the channels
    that still need notification. For new videos (not from the retry path),
    callers should set missing_channels to the full list of active channels.

    Discord is sent one video at a time with a configurable delay between calls.
    Email (and other channels) are sent as a batch per creator.

    Returns the number of successful individual notification sends.
    """
    sent = 0
    for notifier in notifiers:
        channel = notifier.channel_name
        pending = [v for v in videos if channel in v.get("missing_channels", [])]
        if not pending:
            continue

        if channel == "discord":
            for v in pending:
                elapsed = time.monotonic() - last_discord_at[0]
                if elapsed < discord_delay:
                    await asyncio.sleep(discord_delay - elapsed)
                ok = notifier.send_notification(creator_display_name, [v])
                last_discord_at[0] = time.monotonic()
                if ok:
                    db.mark_video_notified(v["video_id"], channel)
                    sent += 1
                else:
                    logger.error(
                        f"Discord notification failed for "
                        f"{creator_display_name} video_id={v.get('video_id')}"
                    )
        else:
            ok = notifier.send_notification(creator_display_name, pending)
            if ok:
                for v in pending:
                    db.mark_video_notified(v["video_id"], channel)
                sent += 1
            else:
                logger.error(
                    f"{channel} notification failed for {creator_display_name}"
                )

    return sent


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
    global _RUNTIME_INFO_LOGGED
    if not _RUNTIME_INFO_LOGGED:
        _log_runtime_debug_info()
        _RUNTIME_INFO_LOGGED = True

    if dry_run:
        logger.info("=== DRY RUN MODE — no DB writes or notifications ===")

    db = Database(config["database"]["path"])
    notifiers = create_notifiers(config)
    active_channels = [n.channel_name for n in notifiers]
    discord_delay = (
        config.get("notifications", {})
        .get("discord", {})
        .get("delay_between_notifications", 10.0)
    )

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

    # Tracks the monotonic time of the last Discord send, shared across all loops.
    last_discord_at: list[float] = [0.0]

    # Step 1: Retry any previously un-notified videos
    if not dry_run:
        unnotified = db.get_unnotified_videos(active_channels)
        if unnotified:
            logger.info(
                f"Retrying notifications for {len(unnotified)} previously un-notified video(s)"
            )
            by_creator: dict[str, list[dict]] = defaultdict(list)
            for v in unnotified:
                by_creator[v["creator_id"]].append(v)
            for creator_id, videos in by_creator.items():
                display_name = (
                    videos[0].get("display_name") or videos[0]["creator_name"]
                )
                sent = await _send_channel_notifications(
                    display_name, videos, notifiers, db, discord_delay, last_discord_at
                )
                notifications_sent += sent

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

            known_titles = db.get_known_titles(creator_id) if not dry_run else set()
            result = await scraper.scrape_creator_with_retry(
                creator_id, creator_name, known_titles
            )

            if result.error:
                logger.error(f"Creator {creator_name}: FAILED — {result.error}")
                if not dry_run:
                    db.update_creator_check(creator_id, "error")
                failed_creators.append(creator_name)
                if i < len(creators) - 1:
                    await _inter_creator_delay(config)
                continue

            if dry_run:
                logger.info(
                    f"Creator {creator_name}: {len(result.videos)} videos scraped "
                    f"(dry run — skipping DB check)"
                )
            else:
                scraped_video_dicts = [
                    {
                        **v.to_dict(),
                        "creator_id": creator_id,
                        "creator_name": creator_name,
                    }
                    for v in result.videos
                ]
                new_videos = db.insert_new_videos(
                    creator_id,
                    scraped_video_dicts,
                )
                db.update_creator_check(creator_id, "ok")
                creators_checked += 1
                total_new_videos += len(new_videos)

                logger.info(
                    f"Creator {creator_name}: {len(result.videos)} total scraped, "
                    f"{len(new_videos)} new"
                )

                if new_videos:
                    # Mark all active channels as pending for each new video
                    for v in new_videos:
                        v["missing_channels"] = active_channels
                    sent = await _send_channel_notifications(
                        display_name,
                        new_videos,
                        notifiers,
                        db,
                        discord_delay,
                        last_discord_at,
                    )
                    notifications_sent += sent

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
    config_path = settings.config_path
    dry_run = "--dry-run" in sys.argv or settings.dry_run
    run_once = settings.run_once
    poll_interval = settings.poll_interval_seconds
    poll_jitter = settings.poll_jitter_seconds

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
