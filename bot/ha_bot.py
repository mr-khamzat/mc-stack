#!/usr/bin/env python3
"""
Home Assistant Telegram Bot — управление умным домом.
Версия 2.0: погода (Open-Meteo), ИИ ассистент (Claude), авто-алерты.
"""
import asyncio
import os
import json
import logging
import subprocess
from datetime import datetime, timezone

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv("/opt/ha-bot/.env")

BOT_TOKEN  = os.environ["BOT_TOKEN"]
ADMIN_ID   = int(os.environ["ADMIN_ID"])
HA_URL     = os.environ["HA_URL"].rstrip("/")
HA_TOKEN   = os.environ["HA_TOKEN"]
HA_HEADERS = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

# Грозный — координаты для Open-Meteo
LAT, LON = 43.31, 45.69
TIMEZONE = "Europe/Moscow"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ── FSM ───────────────────────────────────────────────────────────────────────
class AIChat(StatesGroup):
    active = State()

# ── HA API ────────────────────────────────────────────────────────────────────
async def ha_get(path: str) -> dict | list | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{HA_URL}/api/{path}", headers=HA_HEADERS,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        log.error(f"HA GET {path}: {e}")
    return None

async def ha_post(path: str, data: dict = None) -> dict | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{HA_URL}/api/{path}", headers=HA_HEADERS,
                json=data or {}, timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                return await r.json()
    except Exception as e:
        log.error(f"HA POST {path}: {e}")
    return None

async def ha_state(entity_id: str) -> str:
    d = await ha_get(f"states/{entity_id}")
    return d.get("state", "?") if d else "?"

async def ha_attr(entity_id: str, attr: str, default="?"):
    d = await ha_get(f"states/{entity_id}")
    if d:
        return d.get("attributes", {}).get(attr, default)
    return default

async def ha_call(domain: str, service: str, entity_id: str, extra: dict = None):
    data = {"entity_id": entity_id, **(extra or {})}
    return await ha_post(f"services/{domain}/{service}", data)

# ── Auth ──────────────────────────────────────────────────────────────────────
def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

# ── Погода Open-Meteo ─────────────────────────────────────────────────────────
WMO_CODES = {
    0: "☀️ Ясно", 1: "🌤 В основном ясно", 2: "⛅ Переменная облачность",
    3: "☁️ Пасмурно", 45: "🌫 Туман", 48: "🌫 Изморозь",
    51: "🌦 Мелкий дождь", 53: "🌧 Дождь", 55: "🌧 Сильный дождь",
    61: "🌧 Слабый дождь", 63: "🌧 Дождь", 65: "🌧 Сильный дождь",
    71: "🌨 Снег слабый", 73: "❄️ Снег", 75: "🌨 Сильный снег",
    80: "🌦 Ливень", 81: "🌧 Ливень", 82: "⛈ Сильный ливень",
    95: "⛈ Гроза", 96: "⛈ Гроза с градом", 99: "⛈ Сильная гроза",
}

async def get_weather() -> dict | None:
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
        f"wind_speed_10m,precipitation,weather_code"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
        f"&timezone={TIMEZONE}&forecast_days=3"
    )
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        log.error(f"Open-Meteo: {e}")
    return None

# ── Главная клавиатура ────────────────────────────────────────────────────────
def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🏠 Дом"),        KeyboardButton(text="💡 Свет")],
        [KeyboardButton(text="🌡️ Климат"),     KeyboardButton(text="⚡ Энергия")],
        [KeyboardButton(text="📹 Камеры"),     KeyboardButton(text="🤖 Пылесос")],
        [KeyboardButton(text="🌤 Погода"),     KeyboardButton(text="🔔 Автоматизации")],
        [KeyboardButton(text="📊 Статус"),     KeyboardButton(text="🧠 ИИ Ассистент")],
    ], resize_keyboard=True)

# ── /start ────────────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        await msg.answer("⛔ Доступ запрещён")
        return
    await state.clear()
    await msg.answer(
        "🏠 <b>Home Assistant Bot v2</b>\n\n"
        "Управление умным домом — выбери раздел:\n"
        "🧠 <b>ИИ Ассистент</b> — спрашивай что угодно голосом",
        parse_mode="HTML",
        reply_markup=main_kb()
    )

# ── 📊 Статус ─────────────────────────────────────────────────────────────────
async def build_status_text() -> str:
    # Параллельно запрашиваем всё
    results = await asyncio.gather(
        ha_get("states/sensor.moshchnost_vsego_doma"),
        ha_get("states/sensor.elektroenergiia_stoimost_za_den"),
        ha_get("states/sensor.elektroenergiia_prognoz_scheta_za_mesiats"),
        ha_get("states/sensor.temp_detskaia_temperature"),
        ha_get("states/sensor.temp_detskaia_humidity"),
        ha_get("states/binary_sensor.keenetic_gateway_wan_status_2"),
        ha_get("states/media_player.android_tv"),
        ha_get("states/person.khamzat"),
        ha_get("states/vacuum.pylik"),
    )
    def st(d): return d.get("state", "?") if d else "?"
    def at(d, k): return d.get("attributes", {}).get(k, "?") if d else "?"

    power_d, day_d, prog_d, temp_d, hum_d, inet_d, tv_d, person_d, vac_d = results
    power = st(power_d)
    day   = st(day_d)
    prog  = st(prog_d)
    temp  = st(temp_d)
    hum   = st(hum_d)
    inet  = "✅ Онлайн" if st(inet_d) == "on" else "❌ Офлайн"
    tv    = st(tv_d)
    khamzat = "🏠 Дома" if st(person_d) == "home" else "🚗 Вне дома"
    vac   = st(vac_d)

    # TV details
    tv_detail = ""
    if tv_d and st(tv_d) == "playing":
        app = at(tv_d, "app_name")
        tv_detail = f" ({app})"

    lines = [
        f"📊 <b>Статус дома</b> — {datetime.now().strftime('%H:%M')}\n",
        f"⚡ Мощность: <b>{power} Вт</b>",
        f"💰 Сегодня: {day} ₽ | Прогноз: {prog} ₽",
        f"🌡️ Детская: <b>{temp}°C</b>, влажность {hum}%",
        f"🌐 Интернет: {inet}",
        f"📺 TV: {tv}{tv_detail}",
        f"👤 Хамзат: {khamzat}",
        f"🤖 Пылесос: {vac}",
    ]
    return "\n".join(lines)

@dp.message(F.text == "📊 Статус")
async def status_home(msg: Message):
    if not is_admin(msg.from_user.id): return
    text = await build_status_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="status_refresh")
    ]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "status_refresh")
async def status_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer("Обновляю...")
    text = await build_status_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="status_refresh")
    ]])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

# ── 💡 Свет ───────────────────────────────────────────────────────────────────
LIGHTS = {
    "Кровать":        ("light",  "light.svet_krovat"),
    "Кухня":          ("switch", "switch.vykliuchatel_kukhnia"),
    "ПК Левый":       ("switch", "switch.kabinet_svet_pk_left"),
    "ПК Правый":      ("switch", "switch.kabinet_svet_pk_right"),
    "Люстра Детская": ("switch", "switch.sonoff_100093f84f"),
    "Шкаф":           ("switch", "switch.sonoff_1000a60930"),
}

def lights_kb(states: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for name, (domain, eid) in LIGHTS.items():
        state = states.get(eid, "?")
        icon = "🟡" if state == "on" else "⚫"
        builder.button(text=f"{icon} {name}", callback_data=f"lt:{domain}:{eid}")
    builder.button(text="💡 Всё вкл",  callback_data="lights_all:on")
    builder.button(text="🌑 Всё выкл", callback_data="lights_all:off")
    builder.button(text="🔄 Обновить", callback_data="lights_refresh")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()

@dp.message(F.text == "💡 Свет")
async def lights_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    states = {}
    for _, (domain, eid) in LIGHTS.items():
        states[eid] = await ha_state(eid)
    await msg.answer("💡 <b>Управление светом</b>", parse_mode="HTML",
                     reply_markup=lights_kb(states))

@dp.callback_query(F.data.startswith("lt:"))
async def light_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    _, domain, eid = cb.data.split(":", 2)
    state = await ha_state(eid)
    service = "turn_off" if state == "on" else "turn_on"
    await ha_call(domain, service, eid)
    await cb.answer(f"{'Выключаю' if service == 'turn_off' else 'Включаю'}...")
    await asyncio.sleep(0.5)
    states = {e: await ha_state(e) for _, (d, e) in LIGHTS.items()}
    await cb.message.edit_reply_markup(reply_markup=lights_kb(states))

@dp.callback_query(F.data.startswith("lights_all:"))
async def lights_all(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    action = cb.data.split(":")[1]
    for _, (domain, eid) in LIGHTS.items():
        await ha_call(domain, f"turn_{action}", eid)
    await cb.answer(f"{'💡 Весь свет включён' if action == 'on' else '🌑 Весь свет выключен'}")
    await asyncio.sleep(1)
    states = {e: await ha_state(e) for _, (d, e) in LIGHTS.items()}
    await cb.message.edit_reply_markup(reply_markup=lights_kb(states))

@dp.callback_query(F.data == "lights_refresh")
async def lights_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    states = {e: await ha_state(e) for _, (d, e) in LIGHTS.items()}
    await cb.message.edit_reply_markup(reply_markup=lights_kb(states))
    await cb.answer("Обновлено")

# ── 🌡️ Климат ─────────────────────────────────────────────────────────────────
async def build_climate_text() -> str:
    temp, hum, floor, floor_t = await asyncio.gather(
        ha_state("sensor.temp_detskaia_temperature"),
        ha_state("sensor.temp_detskaia_humidity"),
        ha_state("climate.teplyi_pol_lodzhiia"),
        ha_attr("climate.teplyi_pol_lodzhiia", "current_temperature"),
    )
    rising  = await ha_state("sensor.sun_next_rising")
    setting = await ha_state("sensor.sun_next_setting")

    def fmt_time(iso):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%H:%M")
        except Exception:
            return "?"

    floor_icon = "🔥" if floor == "heat" else "❄️"
    temp_alert = ""
    try:
        t = float(temp)
        if t < 18:
            temp_alert = " ⚠️ ХОЛОДНО!"
        elif t > 27:
            temp_alert = " ⚠️ ЖАРКО!"
    except Exception:
        pass

    return (
        f"🌡️ <b>Климат</b>\n\n"
        f"🏠 Детская: <b>{temp}°C</b>{temp_alert}, влажность {hum}%\n"
        f"{floor_icon} Тёплый пол (лоджия): <b>{floor}</b>, {floor_t}°C\n"
        f"🌅 Восход: {fmt_time(rising)}  🌇 Закат: {fmt_time(setting)}"
    )

@dp.message(F.text == "🌡️ Климат")
async def climate_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    text = await build_climate_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔥 Пол вкл",  callback_data="floor_on"),
            InlineKeyboardButton(text="❄️ Пол выкл", callback_data="floor_off"),
        ],
        [
            InlineKeyboardButton(text="🌡️ Пол +1°",  callback_data="floor_temp:+1"),
            InlineKeyboardButton(text="🌡️ Пол -1°",  callback_data="floor_temp:-1"),
        ],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="climate_refresh")],
    ])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.in_({"floor_on", "floor_off", "climate_refresh"}))
async def climate_basic(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    if cb.data == "floor_on":
        await ha_call("climate", "turn_on", "climate.teplyi_pol_lodzhiia")
        await cb.answer("🔥 Тёплый пол включён")
    elif cb.data == "floor_off":
        await ha_call("climate", "turn_off", "climate.teplyi_pol_lodzhiia")
        await cb.answer("❄️ Тёплый пол выключен")
    else:
        await cb.answer("Обновлено")
    await asyncio.sleep(0.5)
    text = await build_climate_text()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=cb.message.reply_markup)

@dp.callback_query(F.data.startswith("floor_temp:"))
async def floor_temp_adjust(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    delta = int(cb.data.split(":")[1])
    d = await ha_get("states/climate.teplyi_pol_lodzhiia")
    if d:
        current = d.get("attributes", {}).get("temperature", 25)
        new_t = float(current) + delta
        await ha_post("services/climate/set_temperature", {
            "entity_id": "climate.teplyi_pol_lodzhiia",
            "temperature": new_t
        })
        await cb.answer(f"🌡️ Установлено {new_t}°C")
    else:
        await cb.answer("❌ Не удалось")

# ── ⚡ Энергия ────────────────────────────────────────────────────────────────
async def build_energy_text() -> str:
    power, v1, v2, v3, day, month, prog = await asyncio.gather(
        ha_state("sensor.moshchnost_vsego_doma"),
        ha_state("sensor.vvod_1_moshchnost"),
        ha_state("sensor.vvod_2_moshchnost"),
        ha_state("sensor.vvod_3_moshchnost"),
        ha_state("sensor.elektroenergiia_stoimost_za_den"),
        ha_state("sensor.elektroenergiia_stoimost_za_mesiats"),
        ha_state("sensor.elektroenergiia_prognoz_scheta_za_mesiats"),
    )
    power_alert = ""
    try:
        if float(power) > 3000:
            power_alert = " ⚠️"
    except Exception:
        pass
    return (
        f"⚡ <b>Энергия</b>\n\n"
        f"🏠 Общая мощность: <b>{power} Вт{power_alert}</b>\n"
        f"  ├ Ввод 1: {v1} Вт\n"
        f"  ├ Ввод 2: {v2} Вт\n"
        f"  └ Ввод 3: {v3} Вт\n\n"
        f"💰 Сегодня: <b>{day} ₽</b>\n"
        f"💰 Месяц:   {month} ₽\n"
        f"📈 Прогноз: {prog} ₽"
    )

@dp.message(F.text == "⚡ Энергия")
async def energy_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    text = await build_energy_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="energy_refresh")
    ]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "energy_refresh")
async def energy_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer("Обновляю...")
    text = await build_energy_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="energy_refresh")
    ]])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

# ── 🌤 Погода (Open-Meteo) ────────────────────────────────────────────────────
def build_weather_text(data: dict) -> str:
    """Формирует текст погоды из ответа Open-Meteo."""
    c = data.get("current", {})
    daily = data.get("daily", {})

    temp   = c.get("temperature_2m", "?")
    feels  = c.get("apparent_temperature", "?")
    hum    = c.get("relative_humidity_2m", "?")
    wind   = c.get("wind_speed_10m", "?")
    precip = c.get("precipitation", 0)
    code   = c.get("weather_code", 0)
    cond   = WMO_CODES.get(code, f"Код {code}")

    try:
        updated = datetime.fromisoformat(c.get("time", "")).strftime("%H:%M")
    except Exception:
        updated = "?"

    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    days   = daily.get("time", [])
    t_max  = daily.get("temperature_2m_max", [])
    t_min  = daily.get("temperature_2m_min", [])
    codes  = daily.get("weather_code", [])
    forecast_lines = []
    for i in range(min(3, len(days))):
        try:
            d = datetime.fromisoformat(days[i])
            wcode = WMO_CODES.get(codes[i], "?").split()[0]
            forecast_lines.append(
                f"  {day_names[d.weekday()]} {d.strftime('%d.%m')}: {wcode} {t_min[i]:.0f}…{t_max[i]:.0f}°C"
            )
        except Exception:
            pass

    text = (
        f"🌤 <b>Погода — Грозный</b>\n"
        f"<i>Обновлено: {updated}</i>\n\n"
        f"{cond}\n"
        f"🌡️ <b>{temp}°C</b> (ощущается {feels}°C)\n"
        f"💧 Влажность: {hum}%\n"
        f"💨 Ветер: {wind} км/ч\n"
        f"🌧 Осадки: {precip} мм\n"
    )
    if forecast_lines:
        text += "\n📅 <b>Прогноз:</b>\n" + "\n".join(forecast_lines)
    return text

_WEATHER_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="🔄 Обновить", callback_data="weather_refresh")
]])

@dp.message(F.text == "🌤 Погода")
async def weather_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    await msg.answer("🌤 Загружаю погоду...")
    data = await get_weather()
    if not data:
        await msg.answer("❌ Погода временно недоступна")
        return
    await msg.answer(build_weather_text(data), parse_mode="HTML", reply_markup=_WEATHER_KB)

@dp.callback_query(F.data == "weather_refresh")
async def weather_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer("Загружаю...")
    data = await get_weather()
    if not data:
        await cb.answer("❌ Недоступно")
        return
    await cb.message.edit_text(build_weather_text(data), parse_mode="HTML", reply_markup=_WEATHER_KB)

# ── 🏠 Дом ────────────────────────────────────────────────────────────────────
@dp.message(F.text == "🏠 Дом")
async def home_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    khamzat, inet, dl, ul, tv, vacuum = await asyncio.gather(
        ha_state("person.khamzat"),
        ha_state("binary_sensor.keenetic_gateway_wan_status_2"),
        ha_state("sensor.keenetic_gateway_download_speed_2"),
        ha_state("sensor.keenetic_gateway_upload_speed_2"),
        ha_state("media_player.android_tv"),
        ha_state("vacuum.pylik"),
    )
    person_icon = "🏠" if khamzat == "home" else "🚗"
    inet_icon   = "✅" if inet == "on" else "❌"
    text = (
        f"🏠 <b>Дом</b>\n\n"
        f"{person_icon} Хамзат: <b>{khamzat}</b>\n"
        f"{inet_icon} Интернет: ↓{dl} / ↑{ul} Мбит/с\n"
        f"📺 TV: <b>{tv}</b>\n"
        f"🤖 Пылесос: <b>{vacuum}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Обновить новости", callback_data="news_refresh")],
        [InlineKeyboardButton(text="🔄 Обновить",         callback_data="home_refresh")],
    ])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "home_refresh")
async def home_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    khamzat, inet, dl, ul, tv, vacuum = await asyncio.gather(
        ha_state("person.khamzat"),
        ha_state("binary_sensor.keenetic_gateway_wan_status_2"),
        ha_state("sensor.keenetic_gateway_download_speed_2"),
        ha_state("sensor.keenetic_gateway_upload_speed_2"),
        ha_state("media_player.android_tv"),
        ha_state("vacuum.pylik"),
    )
    person_icon = "🏠" if khamzat == "home" else "🚗"
    inet_icon   = "✅" if inet == "on" else "❌"
    text = (
        f"🏠 <b>Дом</b> ({datetime.now().strftime('%H:%M')})\n\n"
        f"{person_icon} Хамзат: <b>{khamzat}</b>\n"
        f"{inet_icon} Интернет: ↓{dl} / ↑{ul} Мбит/с\n"
        f"📺 TV: <b>{tv}</b>\n"
        f"🤖 Пылесос: <b>{vacuum}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Обновить новости", callback_data="news_refresh")],
        [InlineKeyboardButton(text="🔄 Обновить",         callback_data="home_refresh")],
    ])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("Обновлено")

@dp.callback_query(F.data == "news_refresh")
async def news_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await ha_call("input_boolean", "turn_on",  "input_boolean.news_refresh_trigger")
    await asyncio.sleep(0.5)
    await ha_call("input_boolean", "turn_off", "input_boolean.news_refresh_trigger")
    await cb.answer("📰 Новости обновляются...")

# ── 🤖 Пылесос ────────────────────────────────────────────────────────────────
async def build_vacuum_text() -> str:
    d = await ha_get("states/vacuum.pylik")
    if not d:
        return "🤖 <b>Пылесос</b>\n❌ Недоступен"
    state   = d.get("state", "?")
    attrs   = d.get("attributes", {})
    battery = attrs.get("battery_level", "?")
    area    = attrs.get("cleaned_area", "?")
    fan     = attrs.get("fan_speed", "?")
    return (
        f"🤖 <b>Пылесос Pylik</b>\n\n"
        f"Статус: <b>{state}</b>\n"
        f"🔋 Батарея: {battery}%\n"
        f"📐 Площадь: {area} м²\n"
        f"💨 Мощность: {fan}"
    )

@dp.message(F.text == "🤖 Пылесос")
async def vacuum_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    text = await build_vacuum_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="▶️ Старт", callback_data="vac:start"),
            InlineKeyboardButton(text="⏸ Пауза",  callback_data="vac:pause"),
        ],
        [
            InlineKeyboardButton(text="🏠 База",     callback_data="vac:home"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="vac:refresh"),
        ],
    ])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("vac:"))
async def vacuum_actions(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    action = cb.data.split(":")[1]
    if action == "start":
        await ha_call("vacuum", "start", "vacuum.pylik")
        await cb.answer("▶️ Пылесос запущен")
    elif action == "pause":
        await ha_call("vacuum", "pause", "vacuum.pylik")
        await cb.answer("⏸ Пауза")
    elif action == "home":
        await ha_call("vacuum", "return_to_base", "vacuum.pylik")
        await cb.answer("🏠 Возвращается на базу")
    elif action == "refresh":
        await cb.answer("Обновлено")
    await asyncio.sleep(1)
    text = await build_vacuum_text()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=cb.message.reply_markup)

# ── 📹 Камеры ─────────────────────────────────────────────────────────────────
@dp.message(F.text == "📹 Камеры")
async def cameras_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📹 Открыть камеры в HA", url="https://ha-as.khamzat-home.crazedns.ru/lovelace/cameras")],
        [InlineKeyboardButton(text="🎞 Frigate",             url="https://ha-as.khamzat-home.crazedns.ru/ccab4aaf_frigate-fa")],
    ])
    await msg.answer(
        "📹 <b>Камеры</b>\n\n🎥 <b>Лофт</b> — Frigate (camera.loft)\n"
        "RTSP: <code>rtsp://admin:010203@192.168.1.194:554/</code>",
        parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True
    )

# ── 🔔 Автоматизации ──────────────────────────────────────────────────────────
@dp.message(F.text == "🔔 Автоматизации")
async def automations_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    all_states = await ha_get("states")
    if not all_states:
        await msg.answer("❌ Не удалось получить данные")
        return
    autos = [e for e in all_states if e["entity_id"].startswith("automation.")][:20]
    lines = ["🔔 <b>Автоматизации</b>\n"]
    for a in autos:
        state = a.get("state", "?")
        name  = a.get("attributes", {}).get("friendly_name", a["entity_id"])
        icon  = "✅" if state == "on" else "🚫"
        lines.append(f"{icon} {name}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌐 Открыть в HA", url="https://ha-as.khamzat-home.crazedns.ru/config/automation/dashboard")
    ]])
    await msg.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)

# ── 🧠 ИИ Ассистент (Claude) ──────────────────────────────────────────────────
async def get_ha_context() -> str:
    """Собираем текущее состояние дома для контекста ИИ."""
    power, temp, hum, inet, tv, person, floor, vacuum = await asyncio.gather(
        ha_state("sensor.moshchnost_vsego_doma"),
        ha_state("sensor.temp_detskaia_temperature"),
        ha_state("sensor.temp_detskaia_humidity"),
        ha_state("binary_sensor.keenetic_gateway_wan_status_2"),
        ha_state("media_player.android_tv"),
        ha_state("person.khamzat"),
        ha_state("climate.teplyi_pol_lodzhiia"),
        ha_state("vacuum.pylik"),
    )
    # Состояние света
    light_states = []
    for name, (_, eid) in LIGHTS.items():
        st = await ha_state(eid)
        if st == "on":
            light_states.append(name)

    lights_str = ", ".join(light_states) if light_states else "весь выключен"
    return (
        f"Мощность дома: {power} Вт\n"
        f"Температура детской: {temp}°C, влажность {hum}%\n"
        f"Интернет: {'онлайн' if inet == 'on' else 'офлайн'}\n"
        f"TV: {tv}\n"
        f"Хамзат: {person}\n"
        f"Тёплый пол: {floor}\n"
        f"Пылесос: {vacuum}\n"
        f"Свет горит: {lights_str}"
    )

async def ask_claude(question: str, context: str) -> str:
    """Вызов Claude через CLI."""
    system = (
        "Ты — умный ассистент умного дома. Отвечай коротко и по делу на русском языке. "
        "Ты можешь помочь управлять устройствами, отвечать на вопросы о состоянии дома, "
        "давать советы. Если пользователь просит включить/выключить что-то — скажи что сделаешь "
        "и предложи использовать кнопки бота. Текущее состояние дома:\n" + context
    )
    prompt = f"{system}\n\nВопрос: {question}"
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)  # Убираем чтобы не было ошибки вложенности
    try:
        proc = await asyncio.create_subprocess_exec(
            "/root/.local/bin/claude", "-p", prompt, "--model", "claude-haiku-4-5",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        result = stdout.decode("utf-8", errors="replace").strip()
        if result:
            return result
        err = stderr.decode("utf-8", errors="replace").strip()
        log.error(f"Claude stderr: {err}")
        return "❌ ИИ временно недоступен"
    except asyncio.TimeoutError:
        return "⏱ Таймаут — попробуй ещё раз"
    except Exception as e:
        log.error(f"Claude error: {e}")
        return f"❌ Ошибка: {e}"

@dp.message(F.text == "🧠 ИИ Ассистент")
async def ai_enter(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    await state.set_state(AIChat.active)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Выйти из чата с ИИ", callback_data="ai_exit")
    ]])
    await msg.answer(
        "🧠 <b>ИИ Ассистент активен</b>\n\n"
        "Задавай вопросы или команды на русском языке.\n"
        "Примеры:\n"
        "• <i>Какая температура в детской?</i>\n"
        "• <i>Сколько потребляет дом?</i>\n"
        "• <i>Что делает пылесос?</i>\n"
        "• <i>Расскажи о состоянии дома</i>\n\n"
        "Для выхода — /start или кнопка ниже",
        parse_mode="HTML", reply_markup=kb
    )

@dp.callback_query(F.data == "ai_exit")
async def ai_exit_cb(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.clear()
    await cb.message.edit_text("✅ Вышел из режима ИИ")
    await cb.message.answer("🏠 Главное меню:", reply_markup=main_kb())
    await cb.answer()

@dp.message(StateFilter(AIChat.active))
async def ai_chat(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    question = msg.text or ""
    if question.startswith("/"):
        await state.clear()
        await msg.answer("🏠 Главное меню:", reply_markup=main_kb())
        return
    thinking = await msg.answer("🧠 Думаю...")
    context = await get_ha_context()
    answer = await ask_claude(question, context)
    await thinking.delete()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Выйти из чата с ИИ", callback_data="ai_exit")
    ]])
    await msg.answer(f"🧠 {answer}", parse_mode="HTML", reply_markup=kb)

# ── Фоновые задачи — авто-алерты ─────────────────────────────────────────────
_alert_state = {
    "power_high": False,
    "temp_low":   False,
    "temp_high":  False,
    "person_khamzat": None,
    "last_briefing_day": None,
}

async def alert_loop():
    """Проверяем каждые 60 сек: мощность, температура, присутствие."""
    await asyncio.sleep(10)  # Даём боту запуститься
    while True:
        try:
            await _check_alerts()
        except Exception as e:
            log.error(f"Alert loop error: {e}")
        await asyncio.sleep(60)

async def _check_alerts():
    power_d, temp_d, person_d = await asyncio.gather(
        ha_get("states/sensor.moshchnost_vsego_doma"),
        ha_get("states/sensor.temp_detskaia_temperature"),
        ha_get("states/person.khamzat"),
    )

    # ⚡ Высокая мощность > 3000 Вт
    try:
        power = float(power_d.get("state", 0)) if power_d else 0
        if power > 3000 and not _alert_state["power_high"]:
            _alert_state["power_high"] = True
            await bot.send_message(ADMIN_ID,
                f"⚡ <b>Высокая нагрузка!</b> {power:.0f} Вт",
                parse_mode="HTML")
        elif power <= 3000 and _alert_state["power_high"]:
            _alert_state["power_high"] = False
    except Exception as e:
        log.error(f"Alert power check: {e}")

    # 🌡️ Температура детской
    try:
        temp = float(temp_d.get("state", 20)) if temp_d else 20
        if temp < 18 and not _alert_state["temp_low"]:
            _alert_state["temp_low"] = True
            await bot.send_message(ADMIN_ID,
                f"🥶 <b>Холодно в детской!</b> {temp}°C",
                parse_mode="HTML")
        elif temp >= 18:
            _alert_state["temp_low"] = False

        if temp > 27 and not _alert_state["temp_high"]:
            _alert_state["temp_high"] = True
            await bot.send_message(ADMIN_ID,
                f"🥵 <b>Жарко в детской!</b> {temp}°C",
                parse_mode="HTML")
        elif temp <= 27:
            _alert_state["temp_high"] = False
    except Exception as e:
        log.error(f"Alert temp check: {e}")

    # 🏠 Приход/уход Хамзата
    try:
        person = person_d.get("state", "?") if person_d else "?"
        prev = _alert_state["person_khamzat"]
        if prev is not None and prev != person:
            if person == "home":
                await bot.send_message(ADMIN_ID, "🏠 Хамзат <b>дома</b>", parse_mode="HTML")
            elif prev == "home":
                await bot.send_message(ADMIN_ID, "🚗 Хамзат <b>ушёл</b>", parse_mode="HTML")
        _alert_state["person_khamzat"] = person
    except Exception as e:
        log.error(f"Alert person check: {e}")

    # 🌅 Утреннее сводка в 8:00
    now = datetime.now()
    if now.hour == 8 and now.minute < 1:
        today = now.date().isoformat()
        if _alert_state["last_briefing_day"] != today:
            _alert_state["last_briefing_day"] = today
            await _send_morning_briefing()

async def _send_morning_briefing():
    """Отправляет утреннюю сводку в 8:00."""
    try:
        status_text = await build_status_text()
        weather_data = await get_weather()
        weather_text = ""
        if weather_data:
            c = weather_data.get("current", {})
            code = c.get("weather_code", 0)
            cond = WMO_CODES.get(code, "").split()[0] if WMO_CODES.get(code) else ""
            temp = c.get("temperature_2m", "?")
            weather_text = f"\n🌤 Погода: {cond} <b>{temp}°C</b>"

        await bot.send_message(
            ADMIN_ID,
            f"🌅 <b>Доброе утро!</b>{weather_text}\n\n{status_text}",
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Morning briefing error: {e}")

# ── Запуск ────────────────────────────────────────────────────────────────────
async def main():
    log.info("HA Bot v2 starting...")
    asyncio.create_task(alert_loop())
    await bot.send_message(
        ADMIN_ID,
        "🏠 <b>Home Assistant Bot v2 запущен!</b>\n"
        "✅ Погода: Open-Meteo (реальная)\n"
        "✅ ИИ Ассистент: Claude\n"
        "✅ Авто-алерты: мощность, температура, присутствие\n"
        "✅ Утренняя сводка в 8:00",
        parse_mode="HTML"
    )
    log.info("Start polling")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
