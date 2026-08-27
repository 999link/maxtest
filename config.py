import os
from pathlib import Path

# Auto-load .env from repo root when running via python directly.
# This lets you keep BOT_TOKEN, ADMINS, PROXY_URL etc in a .env file without
# exporting them manually in the shell.
def _load_dotenv_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                # remove surrounding quotes if present
                if len(val) >= 2 and ((val[0] == val[-1]) and val[0] in "'\""):
                    val = val[1:-1]
                # do not override existing environment variables
                if key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        return
    except Exception:
        # don't crash on malformed .env; ignore and continue
        return

# try .env next to this file, or one level up
try:
    _here = Path(__file__).resolve()
    _candidates = [
        _here.parent / ".env",
        _here.parent.parent / ".env",
    ]
    for _p in _candidates:
        if _p.exists():
            _load_dotenv_file(_p)
            break
except Exception:
    pass

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# ADMINS can be provided as comma-separated env var, e.g. "12345,67890"
ADMINS_ENV = os.environ.get("ADMINS", "")
if ADMINS_ENV:
    try:
        ADMINS = [int(x) for x in ADMINS_ENV.split(",") if x.strip()]
    except ValueError:
        ADMINS = []
else:
    # fallback to a single admin id from previous default (can be overridden via env)
    ADMINS = [8754414647]

# Optional global proxy for pymax/http traffic. Can be empty or like "http://127.0.0.1:8080"
PROXY_URL = os.environ.get("PROXY_URL", "")

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
