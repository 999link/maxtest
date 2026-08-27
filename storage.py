import json
import asyncio
from typing import Any
from config import DB_PATH, build_user_agent, DEFAULT_PROFILE

_lock = asyncio.Lock()


def _read() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {}
    try:
        return json.loads(DB_PATH.read_text("utf-8"))
    except json.JSONDecodeError:
        return {}


def _write(data: dict) -> None:
    DB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


async def save_account(tg_id: int, *, phone: str, token: str,
                       profile: str, user_agent: dict | None = None,
                       extra: dict | None = None) -> None:
    profile = profile.upper()
    async with _lock:
        data = _read()
        rec = data.setdefault(str(tg_id), {"sessions": {}, "active": profile})
        rec["sessions"][profile] = {
            "phone": phone,
            "token": token,
            "profile": profile,
            "user_agent": user_agent or build_user_agent(profile),
            "extra": extra or {},
        }
        rec["active"] = profile
        _write(data)


async def get_account(tg_id: int, profile: str | None = None) -> dict | None:
    async with _lock:
        rec = _read().get(str(tg_id))
        if not rec:
            return None
        key = (profile or rec.get("active") or DEFAULT_PROFILE).upper()
        return rec["sessions"].get(key)


async def list_sessions(tg_id: int) -> dict[str, dict]:
    async with _lock:
        return (_read().get(str(tg_id)) or {}).get("sessions", {})


async def set_active(tg_id: int, profile: str) -> bool:
    async with _lock:
        data = _read()
        rec = data.get(str(tg_id))
        if not rec or profile.upper() not in rec["sessions"]:
            return False
        rec["active"] = profile.upper()
        _write(data)
        return True


async def drop_account(tg_id: int, profile: str | None = None) -> None:
    async with _lock:
        data = _read()
        rec = data.get(str(tg_id))
        if not rec:
            return
        if profile:
            rec["sessions"].pop(profile.upper(), None)
            if not rec["sessions"]:
                data.pop(str(tg_id), None)
        else:
            data.pop(str(tg_id), None)
        _write(data)
