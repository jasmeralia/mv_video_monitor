import logging
import smtplib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Optional

logger = logging.getLogger(__name__)


class BaseNotifier(ABC):
    @abstractmethod
    def send_notification(self, creator_display_name: str, new_videos: list[dict]) -> bool:
        """Send notification for new videos. Returns True on success."""
        ...


class EmailNotifier(BaseNotifier):
    def __init__(self, config: dict):
        self.smtp_host = config["smtp_host"]
        self.smtp_port = config["smtp_port"]
        self.use_tls = config.get("smtp_use_tls", True)
        self.smtp_user = config["smtp_user"]
        self.smtp_password = config["smtp_password"]
        self.from_address = config["from_address"]
        self.from_name = config.get("from_name", "ManyVids Monitor")
        self.to_addresses = config["to_addresses"]

    def send_notification(self, creator_display_name: str, new_videos: list[dict]) -> bool:
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
            logger.info(f"Email sent for {count} new videos from {creator_display_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email for {creator_display_name}: {e}")
            return False

    def _build_text_email(self, creator: str, videos: list[dict]) -> str:
        lines = [
            f"{len(videos)} new video{'s' if len(videos) != 1 else ''} from {creator}",
            "",
        ]
        for v in videos:
            lines.append(f"  {v['title']}")
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
        lines.append(f"Detected: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        return "\n".join(lines)

    def _build_html_email(self, creator: str, videos: list[dict]) -> str:
        count = len(videos)
        video_rows = ""
        for v in videos:
            meta_parts = []
            if v.get("duration"):
                meta_parts.append(escape(v["duration"]))
            if v.get("price_regular"):
                meta_parts.append(f"${escape(v['price_regular'])}")
            else:
                meta_parts.append("Free")
            meta_html = "  &nbsp;|&nbsp;  ".join(meta_parts)

            video_rows += f"""
            <tr>
              <td style="padding: 12px 8px; border-bottom: 1px solid #eee;">
                <a href="{escape(v['url'])}"
                   style="font-size: 15px; color: #d63031; text-decoration: none; font-weight: bold;">
                  {escape(v['title'])}
                </a><br>
                <span style="color: #636e72; font-size: 13px;">{meta_html}</span>
              </td>
            </tr>"""

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2d3436; margin-bottom: 4px;">
    {count} New Video{'s' if count != 1 else ''} from {escape(creator)}
  </h2>
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 16px;">
    {video_rows}
  </table>
  <p style="color: #b2bec3; font-size: 12px; margin-top: 20px;">
    Detected: {timestamp}
  </p>
</body>
</html>"""


class DiscordNotifier(BaseNotifier):
    """Stub — implement when needed."""

    def __init__(self, config: dict):
        self.webhook_url = config.get("webhook_url", "")

    def send_notification(self, creator_display_name: str, new_videos: list[dict]) -> bool:
        logger.warning("Discord notifier not yet implemented")
        return False


class MatrixNotifier(BaseNotifier):
    """Stub — implement when needed."""

    def __init__(self, config: dict):
        self.homeserver = config.get("homeserver", "")
        self.room_id = config.get("room_id", "")
        self.access_token = config.get("access_token", "")

    def send_notification(self, creator_display_name: str, new_videos: list[dict]) -> bool:
        logger.warning("Matrix notifier not yet implemented")
        return False


def create_notifier(config: dict) -> BaseNotifier:
    notif_type = config["notifications"]["type"]
    if notif_type == "email":
        return EmailNotifier(config["notifications"]["email"])
    elif notif_type == "discord":
        return DiscordNotifier(config["notifications"].get("discord", {}))
    elif notif_type == "matrix":
        return MatrixNotifier(config["notifications"].get("matrix", {}))
    else:
        raise ValueError(f"Unknown notification type: {notif_type!r}")
