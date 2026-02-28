import logging
import logging.handlers
import yaml
from pathlib import Path


def setup_logging(config: dict) -> None:
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file", "/data/logs/monitor.log")
    max_bytes = log_cfg.get("max_bytes", 10_485_760)
    backup_count = log_cfg.get("backup_count", 5)

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count
    )
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)
