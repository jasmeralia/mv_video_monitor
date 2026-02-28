import os

__version__ = "1.1.0"


def get_app_version() -> str:
    """Return deployed app version, allowing runtime override via environment."""
    return os.environ.get("APP_VERSION", __version__).strip() or __version__
