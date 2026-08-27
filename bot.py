import asyncio
import html
import json
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import storage
from config import BOT_TOKEN, ADMINS, SESSION_PROFILES, DEFAULT_PROFILE
from max_core import (MaxError, MaxSession, NeedTwoFA, call_method,
                      list_methods, restore_session)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

dp = Dispatcher(storage=MemoryStorage())

# активные сессии в памяти: tg_id -> MaxSession
LIVE: dict[int, MaxSession] = {}


class Auth(StatesGroup):
    profile = State()
    phone = State()
    code = State()
    twofa = State()


def allowed(uid: int) -> bool:
    return not ADMINS or uid in ADMINS


def code_block(obj, limit: int = 3500) -> str:
    if not isinstance(obj, str):
        try:
            obj = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
        except Exception:
            obj = repr(obj)
    return f"<pre>{html.escape(obj[:limit])}</pre>"


def profile_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"{'📱' if p == 'ANDROID' else '🌐'} {p} · v{cfg['app_version']}",
        callback_data=f"prof:{p}")] for p, cfg in SESSION_PROFILES.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------- базовые команды ----------------

@dp.message(Command("start", "help"))
async def cmd_start(m: Message):
    if not allowed(m.from_user.id):
        return await m.answer("Доступ закрыт.")
    await m.answer(
        "<b>pymax lab</b> — песочница для тестов\n\n"
        "/login — авторизация (выбор ANDROID / WEB)\n"
        "/sessions — сохранённые сессии\n"
        "/use ANDROID|WEB — сделать сессию активной\n"
        "/token — показать токен и user-agent\n"
        "/connect — поднять клиент из сохранённого токена\n"
        "/methods — список методов клиента\n"
        "/call &lt;method&gt; [args...] — вызвать метод\n"
        "/logout [PROFILE] — удалить сессию\n"
        "/cancel — прервать диалог"
    )


@dp.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Отменено.")


# ---------------- авторизация ----------------

@dp.message(Command("login"))
async def cmd_login(m: Message, state: FSMContext):
    if not allowed(m.from_user.id):
        return
    await state.set_state(Auth.profile)
    await m.answer("Выбери тип сессии:", reply_markup=profile_kb())


@dp.callback_query(Auth.profile, F.data.startswith("prof:"))
async def pick_profile(cb: CallbackQuery, state: FSMContext):
    prof = cb.data.split(":", 1)[1]
    await state.update_data(profile=prof)
    await state.set_state(Auth.phone)
    cfg = SESSION_PROFILES[prof]
    await cb.message.edit_text(
        f"Профиль: <b>{prof}</b> · v{cfg['app_version']} · {cfg['os_version']}\n\n"
        "Отправь номер в формате <code>+79991234567</code>")
    await cb.answer()


@dp.message(Auth.phone, F.text)
async def got_phone(m: Message, state: FSMContext):
    phone = m.text.strip().replace(" ", "")
    if not phone.startswith("+") or not phone[1:].isdigit():
        return await m.answer("Формат: <code>+79991234567</code>")

    data = await state.get_data()
    session = MaxSession(phone=phone, profile=data.get("profile", DEFAULT_PROFILE))
    wait = await m.answer("⏳ Запрашиваю код…")
    try:
        info = await session.request_code()
    except MaxError as e:
        await state.clear()
        return await wait.edit_text(e.pretty())

    LIVE[m.from_user.id] = session
    await state.set_state(Auth.code)
    await wait.edit_text(f"✅ {info}\n\nВведи код из MAX:")


@dp.message(Auth.code, F.text)
async def got_code(m: Message, state: FSMContext):
    session = LIVE.get(m.from_user.id)
    if not session:
        await state.clear()
        return await m.answer("Сессия потеряна, начни с /login")

    code = "".join(ch for ch in m.text if ch.isdigit())
    wait = await m.answer("⏳ Проверяю код…")
    try:
        res = await session.submit_code(code)
    except NeedTwoFA:
        await state.set_state(Auth.twofa)
        return await wait.edit_text("🔐 Включена 2FA. Введи пароль:")
    except MaxError as e:
        return await wait.edit_text(e.pretty() + "\n\nПопробуй ещё раз или /cancel")

    await finish_login(m, state, session, res, wait)


@dp.message(Auth.twofa, F.text)
async def got_2fa(m: Message, state: FSMContext):
    session = LIVE.get(m.from_user.id)
    if not session:
        await state.clear()
        return await m.answer("Сессия потеряна, /login")

    wait = await m.answer("⏳ Проверяю пароль…")
    try:
        res = await session.submit_2fa(m.text.strip())
    except MaxError as e:
        return await wait.edit_text(e.pretty() + "\n\nПовтори или /cancel")
    await finish_login(m, state, session, res, wait)


async def finish_login(m: Message, state: FSMContext,
                       session: MaxSession, res: dict, wait: Message):
    await storage.save
