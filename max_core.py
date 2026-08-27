"""
Слой над pymax: убирает input() из авторизации и даёт асинхронный флоу
request_code -> submit_code -> (submit_2fa) с выбором типа сессии.
Добавлены параметры proxy для возможности задавать прокси на уровне сессии.
"""
from __future__ import annotations

import inspect
import logging
import traceback
import os
from dataclasses import dataclass, field
from typing import Any

from config import WORK_DIR, build_user_agent, DEFAULT_PROFILE, PROXY_URL

log = logging.getLogger("max_core")


class MaxError(Exception):
    def __init__(self, message: str, *, raw: Any = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.raw = raw
        self.code = code

    def pretty(self) -> str:
        head = f"❌ <b>{self.code or 'MaxError'}</b>\n{self.message}"
        if self.raw is not None:
            head += f"\n\n<pre>{_esc(str(self.raw)[:1500])}</pre>"
        return head


class NeedTwoFA(Exception):
    """Сервер запросил второй фактор."""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _import_pymax():
    try:
        import pymax
    except ImportError as e:
        raise MaxError("pymax не установлен: pip install maxapi-python", raw=e)
    return pymax


def _pick(obj: Any, *names: str):
    for n in names:
        fn = getattr(obj, n, None)
        if callable(fn):
            return fn
    return None


async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v


def _msg(e: Exception) -> str:
    return str(e) or type(e).__name__


def _is_2fa(x: Any) -> bool:
    s = str(x).lower()
    return any(k in s for k in ("2fa", "two_factor", "password", "otp_required",
                                "second factor", "login.2fa"))


def _as_dict(x: Any) -> dict:
    if isinstance(x, dict):
        return x
    for attr in ("model_dump", "dict", "__dict__"):
        v = getattr(x, attr, None)
        if callable(v):
            try:
                return v()
            except Exception:
                pass
        elif isinstance(v, dict):
            return dict(v)
    return {"repr": repr(x)}


def _extract_token(res: Any) -> str | None:
    d = _as_dict(res)
    for k in ("token", "tokenAttrs", "auth_token", "authToken",
              "temp_token", "sms_token", "login_token", "access_token"):
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            inner = _extract_token(v)
            if inner:
                return inner
    return None


def _call(fn, *args):
    """Вызывает метод, отбрасывая лишние аргументы, если сигнатура короче."""
    try:
        params = [p for p in inspect.signature(fn).parameters]
    except (TypeError, ValueError):
        return fn(*args)
    return fn(*args[:len(params)])


def _call_signin(fn, temp_token: str | None, code: str):
    """sign_in(token, code) или sign_in(code) — определяем по сигнатуре."""
    try:
        params = list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        params = ["a", "b"]
    if len(params) >= 2 and temp_token:
        return fn(temp_token, code)
    return fn(code)


@dataclass
class MaxSession:
    phone: str
    profile: str = DEFAULT_PROFILE          # "ANDROID" | "WEB"
    ua_overrides: dict | None = None
    user_agent: dict = field(default_factory=dict)
    client: Any = None
    temp_token: str | None = None
    token: str | None = None
    profile_data: dict | None = None
    proxy: str | None = None

    def __post_init__(self):
        self.profile = self.profile.upper()
        self.user_agent = build_user_agent(self.profile, self.ua_overrides)
        # fallback to global PROXY_URL if not provided explicitly
        if not self.proxy:
            self.proxy = PROXY_URL or None

    @property
    def session_file(self) -> str:
        return f"{self.phone.lstrip('+')}_{self.profile.lower()}.db"

    def _build_client(self):
        pymax = _import_pymax()

        headers = None
        try:
            from pymax.payloads import UserAgentPayload
            allowed = inspect.signature(UserAgentPayload).parameters
            headers = UserAgentPayload(**{k: v for k, v in self.user_agent.items()
                                          if k in allowed})
        except Exception as e:
            log.warning("UserAgentPayload недоступен (%s), UA не применён", e)

        cls = getattr(pymax, "MaxClient", None) or getattr(pymax, "Client", None)
        if cls is None:
            raise MaxError("В установленном pymax нет ни MaxClient, ни Client")

        params = inspect.signature(cls).parameters
        kwargs: dict[str, Any] = {"phone": self.phone}
        if "work_dir" in params:
            kwargs["work_dir"] = str(WORK_DIR)
        if "session_name" in params:
            kwargs["session_name"] = self.session_file
        if "headers" in params and headers is not None:
            kwargs["headers"] = headers
        if "device_type" in params:
            kwargs["device_type"] = self.user_agent["device_type"]

        # try to pass proxy to constructor in a few common parameter names
        proxy_to_use = self.proxy
        if proxy_to_use:
            for key in ("proxy", "proxy_url", "proxies", "http_proxy", "https_proxy"):
                if key in params:
                    kwargs[key] = proxy_to_use
                    break
        # If constructor didn't accept proxy, fall back to env var approach
        used_env_proxy = False
        if proxy_to_use and not any(k in kwargs for k in ("proxy", "proxy_url", "proxies", "http_proxy", "https_proxy")):
            # set env vars temporarily
            used_env_proxy = True
            old_http = os.environ.get("HTTP_PROXY")
            old_https = os.environ.get("HTTPS_PROXY")
            os.environ["HTTP_PROXY"] = proxy_to_use
            os.environ["HTTPS_PROXY"] = proxy_to_use

        try:
            self.client = cls(**kwargs)
        finally:
            if proxy_to_use and used_env_proxy:
                # restore env
                if old_http is None:
                    os.environ.pop("HTTP_PROXY", None)
                else:
                    os.environ["HTTP_PROXY"] = old_http
                if old_https is None:
                    os.environ.pop("HTTPS_PROXY", None)
                else:
                    os.environ["HTTPS_PROXY"] = old_https

        return self.client

    async def _connect(self):
        fn = _pick(self.client, "_connect", "connect", "_ws_connect", "open")
        if fn:
            await _maybe_await(fn())

    async def request_code(self) -> str:
        self._build_client()
        try:
            await self._connect()
            fn = _pick(self.client, "send_code", "request_code", "_request_code",
                       "request_sms_code", "_send_code")
            if fn is None:
                methods = ", ".join(sorted(m for m in dir(self.client)
                                           if not m.startswith("__")))
                raise MaxError("Не найден метод запроса кода.\nМетоды клиента:\n"
                               + methods[:1200])
            res = await _maybe_await(_call(fn, self.phone))
            self.temp_token = _extract_token(res) or self.temp_token
            return (f"Код запрошен ({self.profile}, v{self.user_agent['app_version']}).\n"
                    f"<pre>{_esc(str(res)[:800])}</pre>")
        except MaxError:
            raise
        except Exception as e:
            raise MaxError(_msg(e), raw=traceback.format_exc()[-1200:],
                           code=type(e).__name__)

    async def submit_code(self, code: str) -> dict:
        fn = _pick(self.client, "sign_in", "_sign_in", "confirm_code", "login_by_code")
        if fn is None:
            raise MaxError("Не найден метод подтверждения кода (sign_in)")
        try:
            res = await _maybe_await(_call_signin(fn, self.temp_token, code))
        except Exception as e:
            if _is_2fa(e):
                raise NeedTwoFA(_msg(e))
            raise MaxError(_msg(e), raw=traceback.format_exc()[-1200:],
                           code=type(e).__name__)
        if _is_2fa(res):
            raise NeedTwoFA("Требуется второй фактор")
        return self._finalize(res)

    async def submit_2fa(self, password: str) -> dict:
        fn = _pick(self.client, "check_password", "sign_in_2fa", "submit_password",
                   "_check_password", "verify_password")
        if fn is None:
            raise MaxError("В этой версии pymax нет метода 2FA "
                           "(check_password/sign_in_2fa).")
        try:
            res = await _maybe_await(_call(fn, password))
        except Exception as e:
            raise MaxError(_msg(e), raw=traceback.format_exc()[-1200:],
                           code=type(e).__name__)
        return self._finalize(res)

    def _finalize(self, res: Any) -> dict:
        self.token = (_extract_token(res)
                      or getattr(self.client, "token", None)
                      or getattr(self.client, "_token", None))
        if not self.token:
            raise MaxError("Логин прошёл, но токен не найден в ответе", raw=res)
        self.profile_data = _as_dict(res)
        return {"token": self.token, "profile": self.profile,
                "user_agent": self.user_agent, "raw": self.profile_data}

    async def close(self):
        fn = _pick(self.client, "close", "disconnect", "stop", "_close")
        if fn:
            try:
                await _maybe_await(fn())
            except Exception as e:
                log.warning("close(): %s", e)


async def restore_session(phone: str, token: str, profile: str,
                          user_agent: dict | None = None, proxy: str | None = None) -> MaxSession:
    """Поднимает клиент из сохранённого токена — для /me, /dialogs и т.п."""
    s = MaxSession(phone=phone, profile=profile, ua_overrides=user_agent, proxy=proxy)
    s.token = token
    s._build_client()
    for attr in ("token", "_token", "auth_token"):
        if hasattr(s.client, attr):
            try:
                setattr(s.client, attr, token)
            except Exception:
                pass
    await s._connect()
    return s


async def call_method(session: MaxSession, name: str, *args) -> Any:
    """Универсальный вызов метода клиента — ядро «песочницы» для тестов."""
    fn = getattr(session.client, name, None)
    if not callable(fn):
        raise MaxError(f"Метод {name} не найден у клиента")
    try:
        return await _maybe_await(_call(fn, *args))
    except Exception as e:
        raise MaxError(_msg(e), raw=traceback.format_exc()[-1200:],
                       code=type(e).__name__)


def list_methods(session: MaxSession) -> list[str]:
    return sorted(m for m in dir(session.client)
                  if not m.startswith("__") and callable(getattr(session.client, m, None)))
