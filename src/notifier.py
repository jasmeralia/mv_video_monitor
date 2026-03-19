import json
import logging
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

import requests
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36"
)


def _section_label(video: dict) -> str:
    video_type = str(video.get("video_type", "")).strip().lower()
    if video_type == "mobile":
        return "Mobile"
    return "Regular"


def _creator_page_url(videos: list[dict]) -> str | None:
    if not videos:
        return None
    creator_id = videos[0].get("creator_id")
    creator_name = videos[0].get("creator_name")
    if not creator_id or not creator_name:
        return None
    return (
        f"https://www.manyvids.com/Profile/{creator_id}/{creator_name}"
        "/Store/Videos?sort=newest"
    )


def _email_thumbnail_url(video: dict) -> str | None:
    """Normalize thumbnail URL to MV's image proxy for broader email-client compatibility."""
    raw = video.get("thumbnail_url")
    if not raw:
        return None
    url = str(raw).strip()
    if not url:
        return None
    if "img.manyvids.com/o/v1/" in url:
        return url
    encoded = urllib.parse.quote(url, safe="")
    return f"https://img.manyvids.com/o/v1/{encoded}?w=600&q=80"


def _discord_thumbnail_url(video: dict) -> str | None:
    # Reuse normalized image URL to maximize hotlink success for Discord.
    return _email_thumbnail_url(video)


class BaseNotifier(ABC):
    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Identifier for this notification channel (e.g. 'email', 'discord')."""
        ...

    @abstractmethod
    def send_notification(
        self, creator_display_name: str, new_videos: list[dict]
    ) -> bool:
        """Send notification for new videos. Returns True on success."""
        ...


class EmailNotifier(BaseNotifier):
    @property
    def channel_name(self) -> str:
        return "email"

    def __init__(self, config: dict):
        self.smtp_host = config["smtp_host"]
        self.smtp_port = config["smtp_port"]
        self.use_tls = config.get("smtp_use_tls", True)
        self.smtp_user = config["smtp_user"]
        self.smtp_password = config["smtp_password"]
        self.from_address = config["from_address"]
        self.from_name = config.get("from_name", "ManyVids Monitor")
        self.to_addresses = config["to_addresses"]

    def send_notification(
        self, creator_display_name: str, new_videos: list[dict]
    ) -> bool:
        count = len(new_videos)
        subject = (
            f"[ManyVids] {count} new video{'s' if count != 1 else ''} "
            f"from {creator_display_name}"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_address}>"
        msg["To"] = ", ".join(self.to_addresses)

        text_body = self._build_text_email(creator_display_name, new_videos)
        html_body = self._build_html_email(creator_display_name, new_videos)

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                if self.use_tls:
                    smtp.starttls()
                smtp.login(self.smtp_user, self.smtp_password)
                smtp.sendmail(self.from_address, self.to_addresses, msg.as_string())
            logger.info(
                f"Email sent for {count} new videos from {creator_display_name}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send email for {creator_display_name}: {e}")
            return False

    def _build_text_email(self, creator: str, videos: list[dict]) -> str:
        creator_url = _creator_page_url(videos)
        lines = [
            f"{len(videos)} new video{'s' if len(videos) != 1 else ''} from {creator}",
            "",
        ]
        if creator_url:
            lines.append(f"Creator page: {creator_url}")
            lines.append("")
        for v in videos:
            lines.append(f"  [{_section_label(v)}] {v['title']}")
            meta = []
            if v.get("duration"):
                meta.append(v["duration"])
            if v.get("price_regular"):
                meta.append(f"${v['price_regular']}")
            else:
                meta.append("Free")
            if meta:
                lines.append(f"    {' | '.join(meta)}")
            lines.append(f"    {v['url']}")
            lines.append("")
        lines.append(
            f"Detected: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        return "\n".join(lines)

    def _build_html_email(self, creator: str, videos: list[dict]) -> str:
        count = len(videos)
        creator_url = _creator_page_url(videos)
        video_rows = ""
        for v in videos:
            meta_parts = []
            meta_parts.append(_section_label(v))
            if v.get("duration"):
                meta_parts.append(escape(v["duration"]))
            if v.get("price_regular"):
                meta_parts.append(f"${escape(v['price_regular'])}")
            else:
                meta_parts.append("Free")
            meta_html = "  &nbsp;|&nbsp;  ".join(meta_parts)
            thumbnail_url = _email_thumbnail_url(v)
            if thumbnail_url:
                thumb_html = (
                    f'<a href="{escape(v["url"])}" '
                    'style="display:block;line-height:0;">'
                    f'<img src="{escape(thumbnail_url)}" alt="" width="180" '
                    'style="display:block;border-radius:6px;border:0;'
                    'width:180px;height:auto;"/>'
                    "</a>"
                )
            else:
                thumb_html = ""

            video_rows += f"""
            <tr>
              <td style="padding: 12px 8px; border-bottom: 1px solid #eee; width: 190px; vertical-align: top;">
                {thumb_html}
              </td>
              <td style="padding: 12px 8px; border-bottom: 1px solid #eee; vertical-align: top;">
                <a href="{escape(v["url"])}"
                   style="font-size: 15px; color: #d63031; text-decoration: none; font-weight: bold;">
                  {escape(v["title"])}
                </a><br>
                <span style="color: #636e72; font-size: 13px;">{meta_html}</span>
              </td>
            </tr>"""

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        creator_header_link = ""
        creator_name_html = escape(creator)
        if creator_url:
            creator_name_html = (
                f'<a href="{escape(creator_url)}" '
                'style="color:#2d3436;text-decoration:none;">'
                f"{escape(creator)}"
                "</a>"
            )
            creator_header_link = (
                f'<p style="margin-top: 0; margin-bottom: 16px;">'
                f'<a href="{escape(creator_url)}" '
                'style="color: #0984e3; text-decoration: none;">'
                "Open creator page on ManyVids"
                "</a></p>"
            )
        return f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2d3436; margin-bottom: 4px;">
    {count} New Video{"s" if count != 1 else ""} from {creator_name_html}
  </h2>
  {creator_header_link}
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 16px;">
    {video_rows}
  </table>
  <p style="color: #b2bec3; font-size: 12px; margin-top: 20px;">
    Detected: {timestamp}
  </p>
</body>
</html>"""


class DiscordNotifier(BaseNotifier):
    @property
    def channel_name(self) -> str:
        return "discord"

    def __init__(self, config: dict):
        self.webhook_url = config["webhook_url"]

    def _post_json_payload(self, payload: dict) -> bool:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": DISCORD_WEBHOOK_UA,
            },
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status in (200, 204)
            except urllib.error.HTTPError as e:
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = "<unable to read response body>"
                if e.code == 429 and attempt < 2:
                    retry_after = 1.0
                    try:
                        parsed = json.loads(err_body)
                        retry_after = float(parsed.get("retry_after", 1))
                    except Exception:
                        retry_after = 1.0
                    logger.warning(
                        f"Discord webhook rate-limited (429), retrying in {retry_after:.2f}s"
                    )
                    time.sleep(max(0.1, retry_after))
                    continue
                logger.error(
                    f"Discord webhook HTTP failure: {e.code} {e.reason}; response={err_body}"
                )
                return False
            except Exception as e:
                logger.error(f"Discord webhook request failed: {e}")
                return False
        return False

    def _download_thumbnail(self, url: str) -> bytes | None:
        try:
            resp = requests.get(
                url,
                timeout=5,
                headers={"User-Agent": DISCORD_WEBHOOK_UA},
            )
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.warning(f"Failed to download thumbnail for Discord embed: {e}")
            return None

    def _post_multipart_payload(self, payload: dict, image_bytes: bytes) -> bool:
        for attempt in range(3):
            try:
                resp = requests.post(
                    self.webhook_url,
                    data={"payload_json": json.dumps(payload)},
                    files={"files[0]": ("thumbnail.jpg", image_bytes, "image/jpeg")},
                    headers={
                        "Accept": "application/json",
                        "User-Agent": DISCORD_WEBHOOK_UA,
                    },
                    timeout=10,
                )
                if resp.status_code == 429 and attempt < 2:
                    retry_after = 1.0
                    try:
                        retry_after = float(resp.json().get("retry_after", 1))
                    except Exception:
                        retry_after = 1.0
                    logger.warning(
                        f"Discord webhook rate-limited (429), retrying in {retry_after:.2f}s"
                    )
                    time.sleep(max(0.1, retry_after))
                    continue
                if resp.status_code not in (200, 204):
                    logger.error(
                        f"Discord webhook HTTP failure: {resp.status_code}; "
                        f"response={resp.text}"
                    )
                    return False
                return True
            except Exception as e:
                logger.error(f"Discord webhook multipart request failed: {e}")
                return False
        return False

    def send_notification(
        self, creator_display_name: str, new_videos: list[dict]
    ) -> bool:
        sent = 0
        for v in new_videos:
            meta = []
            meta.append(_section_label(v))
            if v.get("duration"):
                meta.append(v["duration"])
            if v.get("price_regular"):
                meta.append(f"${v['price_regular']}")
            else:
                meta.append("Free")
            meta_str = " | ".join(meta)
            embed: dict[str, object] = {
                "title": f"{creator_display_name} - [{_section_label(v)}] {v['title']}",
                "url": v["url"],
                "color": 0xD63031,
                "description": meta_str,
                "footer": {
                    "text": (
                        f"Detected: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                    )
                },
            }
            image_bytes: bytes | None = None
            thumb_url = _discord_thumbnail_url(v)
            if thumb_url:
                image_bytes = self._download_thumbnail(thumb_url)
                if image_bytes:
                    embed["image"] = {"url": "attachment://thumbnail.jpg"}

            payload: dict[str, object] = {
                "embeds": [embed],
            }
            success = (
                self._post_multipart_payload(payload, image_bytes)
                if image_bytes
                else self._post_json_payload(payload)
            )
            if not success:
                logger.error(
                    f"Failed to send Discord notification for {creator_display_name} "
                    f"video_id={v.get('video_id')}"
                )
                return False
            sent += 1

        logger.info(
            f"Discord notification sent for {sent} new videos from {creator_display_name}"
        )
        return True


class MatrixNotifier(BaseNotifier):
    """Stub — implement when needed."""

    @property
    def channel_name(self) -> str:
        return "matrix"

    def __init__(self, config: dict):
        self.homeserver = config.get("homeserver", "")
        self.room_id = config.get("room_id", "")
        self.access_token = config.get("access_token", "")

    def send_notification(
        self, creator_display_name: str, new_videos: list[dict]
    ) -> bool:
        logger.warning("Matrix notifier not yet implemented")
        return False


def _build_single_notifier(notif_type: str, notif_config: dict) -> BaseNotifier:
    if notif_type == "email":
        return EmailNotifier(notif_config["email"])
    elif notif_type == "discord":
        return DiscordNotifier(notif_config["discord"])
    elif notif_type == "matrix":
        return MatrixNotifier(notif_config["matrix"])
    else:
        raise ValueError(f"Unknown notification type: {notif_type!r}")


def create_notifiers(config: dict) -> list[BaseNotifier]:
    notif_config = config["notifications"]
    notif_type = notif_config["type"]

    if isinstance(notif_type, list):
        return [_build_single_notifier(t, notif_config) for t in notif_type]
    return [_build_single_notifier(notif_type, notif_config)]
