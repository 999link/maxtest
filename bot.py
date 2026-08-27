# ---- proxy management commands ----
import urllib.parse
import requests  # make sure requests is installed in the venv


def _normalize_proxy_url(raw: str) -> str:
    """
    Ensure proxy URL is safe: percent-encode username/password if present.
    Accepts forms:
      http://user:pass@host:port
      socks5://user:pass@host:port
      http://host:port
    Returns normalized URL string.
    """
    raw = raw.strip()
    if not raw:
        return raw
    parsed = urllib.parse.urlsplit(raw)
    # if no scheme, assume http
    if not parsed.scheme:
        raw = "http://" + raw
        parsed = urllib.parse.urlsplit(raw)
    username = parsed.username
    password = parsed.password
    if username or password:
        # percent-encode username/password
        user = urllib.parse.quote(username or "", safe="")
        pwd = urllib.parse.quote(password or "", safe="")
        netloc = f"{user}:{pwd}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        new = urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path or "", parsed.query or "", parsed.fragment or ""))
        return new
    return raw


@dp.message(Command("setproxy"))
async def cmd_setproxy(m: Message):
    if not allowed(m.from_user.id):
        return
    text = (m.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Использование: /setproxy http://user:pass@host:port")
    raw_proxy = parts[1].strip()
    proxy = _normalize_proxy_url(raw_proxy)
    # save in accounts.json for active profile
    ok = await storage.set_proxy(m.from_user.id, proxy)
    if not ok:
        return await m.answer("Не удалось сохранить proxy — у вас ещё нет сохранённых сессий. Сначала /login или сохраните сессию.")
    # try to auto-reconnect: if there's a live session, close it and try to restore
    try:
        acct = await storage.get_account(m.from_user.id)
        profile = acct.get('profile') if acct else None
        # close live session if exists
        live = LIVE.get(m.from_user.id)
        if live:
            try:
                await live.close()
            except Exception:
                pass
            LIVE.pop(m.from_user.id, None)
        # try to restore (non-blocking best-effort)
        try:
            new = await restore_session(m.from_user.id, profile=profile)
            if new:
                LIVE[m.from_user.id] = new
        except Exception:
            # ignore restore failures — user can manually /connect
            pass
    except Exception:
        pass
    await m.answer("✅ Proxy сохранён для активного профиля.\nЧтобы применить его к клиенту немедленно, выполните /connect (или сделайте /logout и затем /login).")


@dp.message(Command("unsetproxy"))
async def cmd_unsetproxy(m: Message):
    if not allowed(m.from_user.id):
        return
    removed = await storage.unset_proxy(m.from_user.id)
    if removed:
        await m.answer("✅ Per-profile proxy удалён. Для применения перезапустите сессию (/connect или /logout + /login).")
    else:
        await m.answer("Proxy не найден для активного профиля.")


@dp.message(Command("showproxy"))
async def cmd_showproxy(m: Message):
    if not allowed(m.from_user.id):
        return
    p = await storage.get_proxy(m.from_user.id)
    from config import PROXY_URL
    if p:
        # mask credentials for safety
        def _mask(u: str) -> str:
            try:
                parsed = urllib.parse.urlsplit(u)
                if parsed.username or parsed.password:
                    net = f"{parsed.scheme}://{parsed.hostname}"
                    if parsed.port:
                        net += f":{parsed.port}"
                    return f"{net}  (auth: ****)"
            except Exception:
                pass
            return u
        await m.answer(f"Per-profile proxy: {_mask(p)}")
    elif PROXY_URL:
        await m.answer(f"Per-profile proxy не задан; используется глобальный PROXY_URL (fallback): {PROXY_URL}")
    else:
        await m.answer("Proxy не задан ни для профиля, ни глобально.")


@dp.message(Command("testproxy"))
async def cmd_testproxy(m: Message):
    """
    /testproxy [optional_proxy_url]
    If proxy url provided, test it; otherwise test per-profile or global proxy.
    """
    if not allowed(m.from_user.id):
        return
    parts = (m.text or "").split(maxsplit=1)
    proxy_to_test = None
    if len(parts) > 1:
        proxy_to_test = _normalize_proxy_url(parts[1].strip())
    else:
        proxy_to_test = await storage.get_proxy(m.from_user.id)
        if not proxy_to_test:
            from config import PROXY_URL
            proxy_to_test = PROXY_URL or None
    if not proxy_to_test:
        return await m.answer("Proxy не задан (ни передан в команде, ни в профиле, ни глобально).")
    await m.answer("Проверяю прокси (короткий HTTP GET)...")
    try:
        resp = requests.get("https://api.ipify.org?format=json", proxies={"http": proxy_to_test, "https": proxy_to_test}, timeout=10)
        if resp.status_code == 200:
            await m.answer(f"OK — прокси работает. IP через прокси: {resp.text}")
        else:
            await m.answer(f"Прокси ответил статусом {resp.status_code}: {resp.text[:400]}")
    except Exception as e:
        await m.answer(f"Ошибка при тесте прокси: {e}")
