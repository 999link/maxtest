import os
from pathlib import Path

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_TOKEN_HERE")
ADMINS = {int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip()}

BASE_DIR = Path(__file__).parent
WORK_DIR = BASE_DIR / "sessions"
DB_PATH = BASE_DIR / "accounts.json"
WORK_DIR.mkdir(exist_ok=True)

# Актуальные версии клиента MAX (обновлять вручную!)
MAX_APK_VERSION = "26.29.1"
MAX_WEB_VERSION = "26.6.24"

SESSION_PROFILES: dict[str, dict] = {
    "ANDROID": {
        "device_type": "ANDROID",
        "app_version": MAX_APK_VERSION,
        "os_version": "Android 14",
        "device_name": "Pixel 7",
        "screen": "1080x2400 2.6x",
        "locale": "ru",
        "timezone": "Europe/Moscow",
    },
    "WEB": {
        "device_type": "WEB",
        "app_version": MAX_WEB_VERSION,
        "os_version": "Linux",
        "device_name": "Chrome 139 / maxlab",
        "screen": "1920x1080 1.0x",
        "locale": "ru",
        "timezone": "Europe/Moscow",
    },
}

DEFAULT_PROFILE = "WEB"


def build_user_agent(profile: str, overrides: dict | None = None) -> dict:
    """Собирает UA-словарь по имени профиля."""
    base = dict(SESSION_PROFILES[profile.upper()])
    if overrides:
        base.update(overrides)
    return base
