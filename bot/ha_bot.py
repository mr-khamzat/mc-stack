#!/usr/bin/env python3
"""
Home Assistant Telegram Bot — управление умным домом.
Версия 3.0: Намаз, TV, Семья, Покупки, Автоматизации (toggle), Inline режим.
"""
import asyncio
import io
import os
import json
import logging
import ssl as _ssl
import subprocess
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
from aiohttp import web as aiohttp_web
try:
    import websockets
    HAS_WS = True
except ImportError:
    HAS_WS = False

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, BufferedInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv("/opt/ha-bot/.env")

BOT_TOKEN  = os.environ["BOT_TOKEN"]
ADMIN_ID   = int(os.environ["ADMIN_ID"])
HA_URL     = os.environ["HA_URL"].rstrip("/")
HA_TOKEN   = os.environ["HA_TOKEN"]
HA_HEADERS = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

WEBAPP_TOKEN = os.environ.get("WEBAPP_TOKEN", "")
WEBAPP_URL   = "https://hub.office.mooo.com/ha-app/"
WEBAPP_DIR   = Path("/opt/ha-bot/webapp")

FAMILY_USERS_FILE = Path("/opt/ha-bot/family_users.json")
DEVICES_FILE      = Path("/opt/ha-bot/devices.json")
SECTIONS_FILE     = Path("/opt/ha-bot/sections.json")

_SECTIONS_DEFAULTS: dict = {
    "cameras":     {"name": "📹 Камеры",      "icon": "📹", "enabled": False, "order": 10},
    "automations": {"name": "🤖 Автоматизации","icon": "🤖", "enabled": False, "order": 11},
    "sensors":     {"name": "📊 Сенсоры",      "icon": "📊", "enabled": False, "order": 12},
    "media":       {"name": "📺 Медиа",        "icon": "📺", "enabled": False, "order": 13},
}

def _sect_load() -> dict:
    if SECTIONS_FILE.exists():
        try:
            return json.loads(SECTIONS_FILE.read_text())
        except Exception as e:
            log.error(f"sections_load: {e}")
    return dict(_SECTIONS_DEFAULTS)

def _sect_save(d: dict):
    try:
        SECTIONS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    except Exception as e:
        log.error(f"sections_save: {e}")

# Weather cache
_weather_cache: dict | None = None
_weather_cache_ts: float = 0.0
_WEATHER_CACHE_TTL = 600  # 10 minutes

# Грозный — координаты для Open-Meteo
LAT, LON  = 43.31, 45.69
TIMEZONE  = "Europe/Moscow"

# Entities
TV_EID    = "media_player.android_tv"
NAMAZ_EID = "timer.namaz_obratnyi_otschet"
SHOP_EID  = "todo.shopping_list"

# Семья — auto-discovered from HA person.* entities (cached 1 hour)
_family_cache: dict = {}       # {display_name: entity_id}
_family_cache_ts: float = 0.0
_FAMILY_CACHE_TTL = 3600

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ── FSM ───────────────────────────────────────────────────────────────────────
class AIChat(StatesGroup):
    active = State()

class ShoppingAdd(StatesGroup):
    waiting = State()

class AddFamilyMember(StatesGroup):
    waiting_name = State()

class DeviceMgmt(StatesGroup):
    rename_wait = State()   # ожидаем новое имя устройства

# ── HA REST API ───────────────────────────────────────────────────────────────
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

async def ha_history(entity_id: str, hours: int = 24, max_points: int = 300) -> list:
    """Returns list of (datetime_msk, float) from HA history API, downsampled to max_points."""
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    data = await ha_get(
        f"history/period/{start}?filter_entity_id={entity_id}&minimal_response=true"
    )
    if not data or not isinstance(data, list) or not data[0]:
        return []
    points = []
    for entry in data[0]:
        try:
            # minimal_response uses last_changed; full entries also have last_updated
            ts_str = entry.get("last_changed") or entry.get("last_updated", "")
            ts  = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(MSK)
            val = float(entry["state"])
            points.append((ts, val))
        except (KeyError, ValueError, TypeError):
            pass
    # Downsample evenly if too many points
    if len(points) > max_points:
        step = len(points) / max_points
        points = [points[int(i * step)] for i in range(max_points)]
    return points

def _make_chart(series: list, title: str, ylabel: str, color: str = "#4fc3f7") -> bytes | None:
    """Generate dark-theme PNG chart with min/max/avg annotations."""
    if not series:
        return None
    times, values = zip(*series)
    values_list = list(values)
    v_min, v_max, v_avg = min(values_list), max(values_list), sum(values_list)/len(values_list)
    v_last = values_list[-1]

    fig, ax = plt.subplots(figsize=(11, 4.5))
    fig.patch.set_facecolor("#0f0f1a")
    ax.set_facecolor("#0f0f1a")

    # Fill + line
    ax.fill_between(times, values, alpha=0.15, color=color)
    ax.plot(times, values, color=color, linewidth=1.8, zorder=3)

    # Current value dot
    ax.scatter([times[-1]], [v_last], color=color, s=50, zorder=5)

    # Horizontal reference lines
    ax.axhline(v_avg, color="#555577", linewidth=0.8, linestyle="--", alpha=0.7)

    # Min/Max/Avg annotations
    x_mid = times[len(times)//2]
    ax.annotate(f"ср: {v_avg:.1f}", xy=(x_mid, v_avg),
                xytext=(0, 6), textcoords="offset points",
                color="#666688", fontsize=8, ha="center")
    ax.annotate(f"▲ {v_max:.1f}", xy=(times[values_list.index(v_max)], v_max),
                xytext=(0, 6), textcoords="offset points",
                color="#ff8888", fontsize=8, ha="center")
    ax.annotate(f"▼ {v_min:.1f}", xy=(times[values_list.index(v_min)], v_min),
                xytext=(0, -12), textcoords="offset points",
                color="#88aaff", fontsize=8, ha="center")

    # Title with current value
    ax.set_title(f"{title}  |  сейчас: {v_last:.1f} {ylabel}",
                 color="#ccccee", fontsize=12, pad=10, loc="left")
    ax.set_ylabel(ylabel, color="#666688", fontsize=9)

    ax.tick_params(colors="#555577", labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=MSK))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
    for spine in ax.spines.values():
        spine.set_edgecolor("#222234")
    ax.grid(axis="y", color="#1e1e2e", linewidth=0.8, alpha=0.9)
    ax.grid(axis="x", color="#1a1a2a", linewidth=0.5, alpha=0.6)
    ax.set_xlim(times[0], times[-1])

    fig.autofmt_xdate(rotation=20)
    fig.tight_layout(pad=1.2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()

# ── HA WebSocket (для todo items) ─────────────────────────────────────────────
async def ha_ws_get_todo_items(entity_id: str) -> list:
    if not HAS_WS:
        return []
    ws_url = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
    ssl_ctx = _ssl.create_default_context()
    try:
        async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("type") != "auth_required":
                return []
            await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
            auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if auth_resp.get("type") != "auth_ok":
                return []
            await ws.send(json.dumps({
                "id": 1, "type": "call_service",
                "domain": "todo", "service": "get_items",
                "service_data": {"entity_id": entity_id},
                "return_response": True,
            }))
            result = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            return (result.get("result", {}).get("response", {})
                    .get(entity_id, {}).get("items", []))
    except Exception as e:
        log.error(f"WS todo {entity_id}: {e}")
    return []

# ── Auth ──────────────────────────────────────────────────────────────────────
def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

def _load_family_users() -> dict:
    try:
        if FAMILY_USERS_FILE.exists():
            return json.loads(FAMILY_USERS_FILE.read_text())
    except Exception:
        pass
    return {}

def _save_family_users(data: dict):
    FAMILY_USERS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def is_family(uid: int) -> bool:
    return str(uid) in _load_family_users()

def is_allowed(uid: int) -> bool:
    return is_admin(uid) or is_family(uid)

def _user_name(uid: int) -> str:
    """Return saved name for a family user or str(uid)."""
    users = _load_family_users()
    return users.get(str(uid), {}).get("name", str(uid))

def family_kb() -> ReplyKeyboardMarkup:
    """Limited keyboard for family members."""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👪 Семья"),  KeyboardButton(text="🌤️ Погода")],
        [KeyboardButton(text="🕌 Намаз"),  KeyboardButton(text="📊 Статус")],
    ], resize_keyboard=True)

# ── Семья — auto-discovery ─────────────────────────────────────────────────────
async def get_family() -> dict:
    """Fetch all person.* entities from HA. Returns {friendly_name: entity_id}."""
    global _family_cache, _family_cache_ts
    now = _time.monotonic()
    if _family_cache and now - _family_cache_ts < _FAMILY_CACHE_TTL:
        return _family_cache
    try:
        all_states = await ha_get("states")
        if isinstance(all_states, list):
            members = {}
            for s in all_states:
                eid = s.get("entity_id", "")
                if eid.startswith("person."):
                    name = (s.get("attributes", {}).get("friendly_name")
                            or eid.split(".")[-1].capitalize())
                    members[name] = eid
            if members:
                _family_cache = members
                _family_cache_ts = now
                return members
    except Exception as e:
        log.error(f"get_family: {e}")
    # fallback to last good cache or hardcoded defaults
    return _family_cache or {
        "Хамзат": "person.khamzat",
        "Айза":   "person.aiza",
        "Сулим":  "person.sulim",
        "Камила": "person.kamila",
    }

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
    global _weather_cache, _weather_cache_ts
    now = _time.monotonic()
    if _weather_cache and now - _weather_cache_ts < _WEATHER_CACHE_TTL:
        return _weather_cache
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
                    data = await r.json()
                    _weather_cache = data
                    _weather_cache_ts = now
                    return data
    except Exception as e:
        log.error(f"Open-Meteo: {e}")
    return _weather_cache  # return stale cache on error

def build_weather_text(data: dict) -> str:
    c      = data.get("current", {})
    daily  = data.get("daily", {})
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
    days      = daily.get("time", [])
    t_max     = daily.get("temperature_2m_max", [])
    t_min     = daily.get("temperature_2m_min", [])
    codes     = daily.get("weather_code", [])
    fc_lines  = []
    for i in range(min(3, len(days))):
        try:
            d = datetime.fromisoformat(days[i])
            icon = WMO_CODES.get(codes[i], "?").split()[0]
            fc_lines.append(f"  {day_names[d.weekday()]} {d.strftime('%d.%m')}: {icon} {t_min[i]:.0f}…{t_max[i]:.0f}°C")
        except Exception:
            pass
    text = (
        f"🌤️ <b>Погода — Грозный</b>\n"
        f"<i>Обновлено: {updated}</i>\n\n"
        f"{cond}\n"
        f"🌡️ <b>{temp}°C</b> (ощущается {feels}°C)\n"
        f"💧 Влажность: {hum}%\n"
        f"💨 Ветер: {wind} км/ч\n"
        f"🌧 Осадки: {precip} мм\n"
    )
    if fc_lines:
        text += "\n📅 <b>Прогноз:</b>\n" + "\n".join(fc_lines)
    return text

_WEATHER_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="🔄 Обновить", callback_data="weather_refresh")
]])

# ── Намаз — время молитв (Aladhan API) ───────────────────────────────────────
MSK = timezone(timedelta(hours=3))

PRAYERS_RU = {
    "Fajr":    ("🌙", "Фаджр"),
    "Dhuhr":   ("🌞", "Зухр"),
    "Asr":     ("🌤️", "Аср"),
    "Maghrib": ("🌅", "Магриб"),
    "Isha":    ("🌃", "Иша"),
}
PRAYERS_ORDER = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]

# HA input_datetime entities for prayer times (manually set by user in HA)
_HA_PRAYER_EIDS = {
    "Fajr":    "input_datetime.namaz_fadzhr",
    "Dhuhr":   "input_datetime.namaz_zukhr",
    "Asr":     "input_datetime.namaz_asr",
    "Maghrib": "input_datetime.namaz_magrib",
    "Isha":    "input_datetime.namaz_isha",
}

_prayer_cache: dict = {"date": None, "timings": None}

async def get_prayer_times() -> dict | None:
    """Получить времена намаза из HA input_datetime сущностей."""
    today = datetime.now(MSK).date().isoformat()
    if _prayer_cache["date"] == today and _prayer_cache["timings"]:
        return _prayer_cache["timings"]
    try:
        results = await asyncio.gather(*[ha_get(f"states/{eid}") for eid in _HA_PRAYER_EIDS.values()])
        timings = {}
        for prayer, d in zip(_HA_PRAYER_EIDS.keys(), results):
            if d:
                # state = "HH:MM:SS" или "HH:MM"
                t = d.get("state", "")[:5]   # берём "HH:MM"
                if t and ":" in t:
                    timings[prayer] = t
        if len(timings) == len(_HA_PRAYER_EIDS):
            _prayer_cache["date"] = today
            _prayer_cache["timings"] = timings
            return timings
    except Exception as e:
        log.error(f"Prayer times from HA: {e}")
    return None

def _namaz_remaining(finishes_at: str) -> str:
    try:
        dt = datetime.fromisoformat(finishes_at.replace("Z", "+00:00"))
        secs = max(0, int((dt - datetime.now(timezone.utc)).total_seconds()))
    except Exception:
        return "?"
    h = secs // 3600; m = (secs % 3600) // 60; s = secs % 60
    if h > 0: return f"{h}ч {m:02d}м"
    if m > 0: return f"{m}м {s:02d}с"
    return f"{s}с"

async def build_namaz_text() -> str:
    now = datetime.now(MSK)
    day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    day_ru   = day_names[now.weekday()]
    date_str = now.strftime("%d.%m")
    time_str = now.strftime("%H:%M")

    header = f"🕌 <b>Намаз</b> — {day_ru}, {date_str}\n🕐 Сейчас: {time_str}\n"
    timings = await get_prayer_times()

    if not timings:
        # Fallback на HA таймер
        d = await ha_get(f"states/{NAMAZ_EID}")
        if not d:
            return header + "\n❌ Расписание недоступно"
        state    = d.get("state", "?")
        finishes = d.get("attributes", {}).get("finishes_at", "")
        if state == "active" and finishes:
            return header + f"\n⏳ До намаза: <b>{_namaz_remaining(finishes)}</b>"
        if state == "idle":
            return header + "\n✅ Намаз совершён"
        return header + f"\nСтатус: {state}"

    lines = []
    next_found = False
    for p_name in PRAYERS_ORDER:
        p_time_str = timings.get(p_name, "")
        if not p_time_str:
            continue
        try:
            p_dt = datetime.strptime(p_time_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day, tzinfo=MSK
            )
        except Exception:
            continue
        icon, ru_name = PRAYERS_RU[p_name]
        diff_min = int((p_dt - now).total_seconds() / 60)

        if diff_min < 0:
            lines.append(f"  ✅ {icon} {ru_name:<8}  {p_time_str}")
        elif not next_found:
            next_found = True
            if diff_min < 60:
                remain = f"через {diff_min} мин"
            else:
                h = diff_min // 60; m = diff_min % 60
                remain = f"через {h}ч {m:02d}м" if m else f"через {h}ч"
            lines.append(f"  ⏰ {icon} <b>{ru_name}</b>   {p_time_str}  ← {remain}")
        else:
            lines.append(f"  🕌 {icon} {ru_name:<8}  {p_time_str}")

    body = "\n".join(lines) if lines else "❌ Данные недоступны"
    return header + "\n" + body

_NAMAZ_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="🔄 Обновить", callback_data="namaz_refresh")
]])

# ── TV helpers ────────────────────────────────────────────────────────────────
async def build_tv_text() -> str:
    d = await ha_get(f"states/{TV_EID}")
    if not d:
        return "📺 <b>Телевизор</b>\n\n❌ Недоступен"
    state = d.get("state", "?")
    attrs = d.get("attributes", {})
    app   = attrs.get("app_name", "")
    vol   = attrs.get("volume_level", None)
    muted = attrs.get("is_volume_muted", False)
    icons = {"playing": "▶️", "paused": "⏸", "idle": "💤", "standby": "📴", "off": "📴"}
    icon  = icons.get(state, "📺")
    vol_str   = f"{int(float(vol)*100)}%" if vol is not None else "?"
    mute_str  = " 🔇" if muted else ""
    text = f"📺 <b>Телевизор</b>\n\n{icon} Статус: <b>{state}</b>\n"
    if app:
        text += f"📱 Приложение: {app}\n"
    text += f"🔊 Громкость: {vol_str}{mute_str}"
    return text

def tv_kb(state: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if state in ("off", "standby", "unavailable"):
        builder.button(text="⚡ Включить ТВ", callback_data="tv:turn_on")
        builder.button(text="🔄 Обновить",    callback_data="tv:refresh")
        builder.adjust(1)
    else:
        builder.button(text="⏯ Play / Pause", callback_data="tv:media_play_pause")
        builder.button(text="⏹ Стоп",         callback_data="tv:media_stop")
        builder.button(text="🔊+",             callback_data="tv:volume_up")
        builder.button(text="🔇 Mute",         callback_data="tv:mute")
        builder.button(text="🔉−",             callback_data="tv:volume_down")
        builder.button(text="🏠 Домой",        callback_data="tv:go_home")
        builder.button(text="📴 Выключить",    callback_data="tv:turn_off")
        builder.button(text="🔄 Обновить",     callback_data="tv:refresh")
        builder.adjust(2, 3, 1, 1)
    return builder.as_markup()

# ── Автоматизации (с кешем для индексации) ────────────────────────────────────
_autos_cache: list = []

async def _fetch_automations() -> list:
    all_states = await ha_get("states")
    if not all_states:
        return []
    return [e for e in all_states if e["entity_id"].startswith("automation.")][:18]

def _build_auto_kb(autos: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, a in enumerate(autos):
        state   = a.get("state", "?")
        name    = a.get("attributes", {}).get("friendly_name", a["entity_id"])
        icon    = "✅" if state == "on" else "🚫"
        display = (name[:26] + "…") if len(name) > 27 else name
        builder.button(text=f"{icon} {display}", callback_data=f"auto:{i}")
    builder.button(text="🔄 Обновить", callback_data="auto:r")
    builder.adjust(1)
    return builder.as_markup()

# ── Главная клавиатура ────────────────────────────────────────────────────────
def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🏡 Дом")],
        [KeyboardButton(text="💡 Свет"),           KeyboardButton(text="⚡ Энергия")],
        [KeyboardButton(text="🌡️ Климат"),         KeyboardButton(text="🌤️ Погода")],
        [KeyboardButton(text="📺 Телевизор"),      KeyboardButton(text="🤖 Пылесос")],
        [KeyboardButton(text="👪 Семья"),           KeyboardButton(text="🛒 Покупки")],
        [KeyboardButton(text="⚙️ Автоматизации"),  KeyboardButton(text="📹 Камеры")],
        [KeyboardButton(text="🛠 Устройства"),      KeyboardButton(text="📊 Статус")],
        [KeyboardButton(text="🕌 Намаз"),           KeyboardButton(text="🧠 ИИ Ассистент")],
        [KeyboardButton(text="🖥️ Панель управления", web_app=WebAppInfo(url=WEBAPP_URL))],
    ], resize_keyboard=True)

# ── /start ────────────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    if is_admin(uid):
        await state.clear()
        await msg.answer(
            "🏠 <b>Home Assistant Bot v3</b>\n\n"
            "Управляй умным домом из Telegram!\n"
            "• 🕌 Намаз таймер\n"
            "• 📺 Управление телевизором\n"
            "• 👪 Местоположение семьи\n"
            "• 🛒 Список покупок\n"
            "• 🧠 ИИ Ассистент",
            parse_mode="HTML",
            reply_markup=main_kb()
        )
        return
    if is_family(uid):
        name = _user_name(uid)
        await msg.answer(f"👋 Привет, {name}!", reply_markup=family_kb())
        return
    # Unknown user — notify admin
    uname  = f"@{msg.from_user.username}" if msg.from_user.username else "—"
    fname  = msg.from_user.full_name or str(uid)
    req_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Добавить", callback_data=f"usr:add:{uid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"usr:rej:{uid}"),
    ]])
    await bot.send_message(
        ADMIN_ID,
        f"👤 <b>Новый запрос доступа</b>\n"
        f"Имя: <b>{fname}</b>\n"
        f"Username: {uname}\n"
        f"ID: <code>{uid}</code>",
        parse_mode="HTML",
        reply_markup=req_kb,
    )
    await msg.answer("⏳ Запрос отправлен администратору. Ожидайте подтверждения.")

@dp.callback_query(F.data.startswith("usr:add:"))
async def usr_add_cb(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    uid = int(cb.data.split(":")[2])
    await state.set_state(AddFamilyMember.waiting_name)
    await state.update_data(target_uid=uid)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"Введите имя для пользователя (ID: <code>{uid}</code>):", parse_mode="HTML")
    await cb.answer()

@dp.message(StateFilter(AddFamilyMember.waiting_name))
async def usr_add_name(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    data = await state.get_data()
    uid  = data.get("target_uid")
    if not uid:
        await state.clear()
        return
    name = msg.text.strip()
    users = _load_family_users()
    users[str(uid)] = {"name": name, "added_ts": datetime.now().isoformat()}
    _save_family_users(users)
    await state.clear()
    await msg.answer(f"✅ <b>{name}</b> добавлен в семью.", parse_mode="HTML")
    try:
        await bot.send_message(
            uid,
            f"✅ Добро пожаловать, <b>{name}</b>!\nТеперь вы можете использовать бота.",
            parse_mode="HTML",
            reply_markup=family_kb(),
        )
    except Exception:
        pass

@dp.callback_query(F.data.startswith("usr:rej:"))
async def usr_rej_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    uid = int(cb.data.split(":")[2])
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("Отклонено")
    try:
        await bot.send_message(uid, "❌ Ваш запрос отклонён.")
    except Exception:
        pass

@dp.message(Command("users"))
async def cmd_users(msg: Message):
    if not is_admin(msg.from_user.id): return
    users = _load_family_users()
    if not users:
        await msg.answer("Нет добавленных пользователей.")
        return
    builder = InlineKeyboardBuilder()
    for fuid, info in users.items():
        uname = info.get("name", fuid)
        builder.button(text=f"❌ {uname}", callback_data=f"usr:del:{fuid}")
    builder.adjust(1)
    lines = [f"• <b>{v['name']}</b> (ID: <code>{k}</code>)" for k, v in users.items()]
    await msg.answer("👥 <b>Пользователи бота:</b>\n" + "\n".join(lines),
                     parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("usr:del:"))
async def usr_del_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    fuid = cb.data.split(":")[2]
    users = _load_family_users()
    name = users.pop(fuid, {}).get("name", fuid)
    _save_family_users(users)
    await cb.answer(f"Удалён: {name}")
    if not users:
        await cb.message.edit_text("Нет добавленных пользователей.", reply_markup=None)
        return
    builder = InlineKeyboardBuilder()
    for fuid2, info in users.items():
        uname = info.get("name", fuid2)
        builder.button(text=f"❌ {uname}", callback_data=f"usr:del:{fuid2}")
    builder.adjust(1)
    lines = [f"• <b>{v['name']}</b> (ID: <code>{k}</code>)" for k, v in users.items()]
    await cb.message.edit_text("👥 <b>Пользователи бота:</b>\n" + "\n".join(lines),
                               parse_mode="HTML", reply_markup=builder.as_markup())

# ── 📊 Статус ─────────────────────────────────────────────────────────────────
async def build_status_text() -> str:
    results = await asyncio.gather(
        ha_get("states/sensor.moshchnost_vsego_doma"),
        ha_get("states/sensor.elektroenergiia_stoimost_za_den"),
        ha_get("states/sensor.elektroenergiia_prognoz_scheta_za_mesiats"),
        ha_get("states/sensor.temp_detskaia_temperature"),
        ha_get("states/sensor.temp_detskaia_humidity"),
        ha_get("states/binary_sensor.keenetic_gateway_wan_status_2"),
        ha_get(f"states/{TV_EID}"),
        ha_get("states/person.khamzat"),
        ha_get("states/vacuum.pylik"),
        ha_get(f"states/{NAMAZ_EID}"),
    )
    def st(d): return d.get("state", "?") if d else "?"
    def at(d, k): return d.get("attributes", {}).get(k, "?") if d else "?"

    power_d, day_d, prog_d, temp_d, hum_d, inet_d, tv_d, person_d, vac_d, namaz_d = results
    power   = st(power_d)
    day     = st(day_d)
    prog    = st(prog_d)
    temp    = st(temp_d)
    hum     = st(hum_d)
    inet    = "✅ Онлайн" if st(inet_d) == "on" else "❌ Офлайн"
    khamzat = "🏠 Дома" if st(person_d) == "home" else "🚗 Вне дома"
    vac     = st(vac_d)

    tv_state  = st(tv_d)
    tv_detail = ""
    if tv_d and tv_state == "playing":
        tv_detail = f" ({at(tv_d, 'app_name')})"

    namaz_str = ""
    if namaz_d and st(namaz_d) == "active":
        finishes = at(namaz_d, "finishes_at")
        if finishes and finishes != "?":
            rem = _namaz_remaining(str(finishes))
            namaz_str = f"\n🕌 До намаза: <b>{rem}</b>"

    # Fix daily cost if stuck at 0
    try:
        if float(day) < 0.1:
            kwh = await _ha_today_kwh()
            if kwh is not None and kwh > 0:
                try:
                    tariff = max(float(await ha_state("input_number.tarif_den_kvt_ch")), 0.5)
                except Exception:
                    tariff = 5.68
                day = f"{kwh * tariff:.2f}"
    except Exception:
        pass

    return (
        f"📊 <b>Статус дома</b> — {datetime.now().strftime('%H:%M')}\n"
        f"\n⚡ Мощность: <b>{power} Вт</b>"
        f"\n💰 Сегодня: {day} ₽ | Прогноз: {prog} ₽"
        f"\n🌡️ Детская: <b>{temp}°C</b>, влажность {hum}%"
        f"\n🌐 Интернет: {inet}"
        f"\n📺 TV: {tv_state}{tv_detail}"
        f"\n👤 Хамзат: {khamzat}"
        f"\n🤖 Пылесос: {vac}"
        + namaz_str
    )

@dp.message(F.text == "📊 Статус")
async def status_home(msg: Message):
    if not is_allowed(msg.from_user.id): return
    text = await build_status_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="status_refresh")
    ]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "status_refresh")
async def status_refresh(cb: CallbackQuery):
    if not is_allowed(cb.from_user.id): return
    await cb.answer("Обновляю...")
    text = await build_status_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="status_refresh")
    ]])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

# ── 💡 Свет + 🛠 Управление устройствами ─────────────────────────────────────
# Defaults — первый запуск или если devices.json не содержит эти entity
_DEVICES_DEFAULTS: dict = {
    "light.svet_krovat":           {"name": "Кровать",        "icon": "🛏️", "section": "lights", "enabled": True,  "order": 1},
    "switch.vykliuchatel_kukhnia": {"name": "Кухня",          "icon": "🍳", "section": "lights", "enabled": True,  "order": 2},
    "switch.kabinet_svet_pk_left": {"name": "ПК Левый",       "icon": "🖥️", "section": "lights", "enabled": True,  "order": 3},
    "switch.kabinet_svet_pk_right":{"name": "ПК Правый",      "icon": "🖥️", "section": "lights", "enabled": True,  "order": 4},
    "switch.sonoff_100093f84f":    {"name": "Люстра Детская", "icon": "💡", "section": "lights", "enabled": True,  "order": 5},
    "switch.sonoff_1000a60930":    {"name": "Шкаф",           "icon": "🚪", "section": "lights", "enabled": True,  "order": 6},
}

LIGHTS: dict      = {}  # {display_name: (domain, entity_id)} — пересобирается из devices.json
LIGHTS_ICON: dict = {}  # {entity_id: icon}                   — пересобирается из devices.json

# ── devices.json helpers ──────────────────────────────────────────────────────

def _dev_load() -> dict:
    """Загрузить devices.json → dict {entity_id: {name,icon,section,enabled,order}}."""
    if DEVICES_FILE.exists():
        try:
            return json.loads(DEVICES_FILE.read_text())
        except Exception as e:
            log.error(f"devices_load: {e}")
    return {}

def _dev_save(d: dict):
    try:
        DEVICES_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    except Exception as e:
        log.error(f"devices_save: {e}")

def _dev_rebuild_lights(devices: dict):
    """Пересобрать LIGHTS/LIGHTS_ICON из devices (section=lights, enabled=True)."""
    LIGHTS.clear()
    LIGHTS_ICON.clear()
    items = sorted(devices.items(), key=lambda x: x[1].get("order", 99))
    for eid, cfg in items:
        if cfg.get("section") == "lights" and cfg.get("enabled", True):
            domain = eid.split(".")[0]
            name   = cfg.get("name", eid.split(".", 1)[-1])
            icon   = cfg.get("icon", "💡")
            LIGHTS[name]    = (domain, eid)
            LIGHTS_ICON[eid] = icon

def _dev_init():
    """При старте: дополнить devices.json дефолтами, пересобрать LIGHTS."""
    devices = _dev_load()
    changed = False
    for eid, cfg in _DEVICES_DEFAULTS.items():
        if eid not in devices:
            devices[eid] = dict(cfg)
            changed = True
    if changed:
        _dev_save(devices)
    _dev_rebuild_lights(devices)

def _guess_light_icon(name: str, eid: str) -> str:
    s = (name + " " + eid).lower()
    if any(x in s for x in ["кроват", "krovat", "bed", "спальн", "spaln"]):     return "🛏️"
    if any(x in s for x in ["кухн", "kukhn", "kitchen"]):                        return "🍳"
    if any(x in s for x in ["_pk", "pk_", "_пк", "пк_", "монитор"]):            return "🖥️"
    if any(x in s for x in ["люстр", "chandelier"]):                             return "💡"
    if any(x in s for x in ["шкаф", "shkaf", "wardrobe"]):                       return "🚪"
    if any(x in s for x in ["детск", "detsk", "child", "kids"]):                 return "👶"
    if any(x in s for x in ["ванн", "bath"]):                                     return "🚿"
    if any(x in s for x in ["туалет", "toilet"]):                                return "🚽"
    if any(x in s for x in ["лоджи", "lodzhi", "балкон", "balkon", "balcon"]):  return "🌿"
    if any(x in s for x in ["зал", "гостин", "gostinaia", "hall", "living"]):    return "🛋️"
    if any(x in s for x in ["коридор", "corridor"]):                             return "🚶"
    if any(x in s for x in ["кабинет", "kabinet", "office"]):                    return "📋"
    if any(x in s for x in ["прихожа", "prikhozh", "entranc"]):                  return "🚪"
    return "💡"

# MDI icon prefixes that indicate a light/lamp device
_LIGHT_MDI_KEYWORDS = (
    "light", "lamp", "bulb", "ceiling", "chandelier", "led",
    "wall-sconce", "floor-lamp", "string-lights", "spotlight",
)
# Switch entity_id suffixes to skip (auxiliary controls, not actual lights)
_SWITCH_SKIP_SUFFIXES = (
    "do_not_disturb", "power_outage_memory", "flip_indicator_light",
    "child_lock", "led_indicator", "backlight", "indicator",
)

def _is_switch_a_light(attrs: dict, eid: str) -> bool:
    """Return True if a switch entity looks like a light controller."""
    # Skip auxiliary/config switches
    eid_lower = eid.lower()
    if any(eid_lower.endswith(suf) for suf in _SWITCH_SKIP_SUFFIXES):
        return False
    icon = attrs.get("icon", "").lower()
    fn   = attrs.get("friendly_name", "").lower()
    if any(kw in icon for kw in _LIGHT_MDI_KEYWORDS):
        return True
    s = fn + " " + eid_lower
    return any(kw in s for kw in ["свет", "svet", "люстр", "гостин", "спальн",
                                    "лампа", "подсветк", "торшер"])

async def _refresh_lights():
    """Сканировать HA, добавить новые light/switch в devices.json и пересобрать LIGHTS."""
    try:
        states = await ha_get("states")
        if not states:
            return
        devices = _dev_load()
        light_eids = {s["entity_id"] for s in states if s.get("entity_id","").startswith("light.")}
        max_order  = max((v.get("order", 0) for v in devices.values()), default=6)
        added = 0
        for s in states:
            eid   = s.get("entity_id", "")
            attrs = s.get("attributes", {})
            domain = eid.split(".")[0] if "." in eid else ""

            is_light  = domain == "light"
            is_switch = domain == "switch" and _is_switch_a_light(attrs, eid)
            if not (is_light or is_switch):
                continue
            if eid in devices:
                continue  # уже в конфиге (пользователь мог скрыть — не трогаем)
            # Если есть light.X для того же устройства — предпочитаем его
            if is_switch:
                suffix = eid.split(".", 1)[1] if "." in eid else eid
                if any(le.split(".", 1)[1] == suffix for le in light_eids):
                    continue

            fn = attrs.get("friendly_name", eid)
            max_order += 1
            devices[eid] = {
                "name":    fn,
                "icon":    _guess_light_icon(fn, eid),
                "section": "lights",
                "enabled": True,
                "order":   max_order,
            }
            added += 1
            log.info(f"Lights auto-discovery: +{domain} {eid} ({fn})")
        if added:
            _dev_save(devices)
            log.info(f"Lights auto-discovery total: +{added}")
        _dev_rebuild_lights(devices)
    except Exception as e:
        log.error(f"_refresh_lights error: {e}")

def lights_kb(states: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for name, (domain, eid) in LIGHTS.items():
        icon = "🟡" if states.get(eid) == "on" else "⚫"
        builder.button(text=f"{icon} {name}", callback_data=f"lt:{domain}:{eid}")
    builder.button(text="💡 Всё вкл",    callback_data="lights_all:on")
    builder.button(text="🌑 Всё выкл",   callback_data="lights_all:off")
    builder.button(text="🛠 Настройки",  callback_data="lights_settings")
    builder.button(text="🔄 Обновить",   callback_data="lights_refresh")
    n = len(LIGHTS)
    builder.adjust(*([2] * (n // 2 + n % 2)), 2, 1, 1)
    return builder.as_markup()

@dp.message(F.text == "💡 Свет")
async def lights_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    states = {e: await ha_state(e) for _, (_, e) in LIGHTS.items()}
    await msg.answer("💡 <b>Управление светом</b>", parse_mode="HTML",
                     reply_markup=lights_kb(states))

@dp.callback_query(F.data.startswith("lt:"))
async def light_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    _, domain, eid = cb.data.split(":", 2)
    state   = await ha_state(eid)
    service = "turn_off" if state == "on" else "turn_on"
    await ha_call(domain, service, eid)
    await cb.answer("Выключаю..." if service == "turn_off" else "Включаю...")
    await asyncio.sleep(0.5)
    states = {e: await ha_state(e) for _, (_, e) in LIGHTS.items()}
    await cb.message.edit_reply_markup(reply_markup=lights_kb(states))

@dp.callback_query(F.data.startswith("lights_all:"))
async def lights_all(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    action = cb.data.split(":")[1]
    for _, (domain, eid) in LIGHTS.items():
        await ha_call(domain, f"turn_{action}", eid)
    await cb.answer("💡 Весь свет включён" if action == "on" else "🌑 Весь свет выключен")
    await asyncio.sleep(1)
    states = {e: await ha_state(e) for _, (_, e) in LIGHTS.items()}
    await cb.message.edit_reply_markup(reply_markup=lights_kb(states))

@dp.callback_query(F.data == "lights_refresh")
async def lights_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    states = {e: await ha_state(e) for _, (_, e) in LIGHTS.items()}
    await cb.message.edit_reply_markup(reply_markup=lights_kb(states))
    await cb.answer("Обновлено")

@dp.callback_query(F.data == "lights_settings")
async def lights_settings(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    devices = _dev_load()
    await cb.message.answer(_devices_main_text(devices), parse_mode="HTML",
                             reply_markup=_devices_main_kb(devices))
    await cb.answer()

@dp.message(Command("lights_sync"))
async def cmd_lights_sync(msg: Message):
    if not is_admin(msg.from_user.id): return
    await _refresh_lights()
    lines = "\n".join(f"  {n}: {eid}" for n, (_, eid) in LIGHTS.items())
    await msg.answer(f"✅ Свет синхронизирован ({len(LIGHTS)} шт):\n{lines}")

# ── 🛠 Управление устройствами (/devices) ─────────────────────────────────────
_SECT_LABELS = {"lights": "💡 Свет", "hidden": "🚫 Скрыто"}

def _devices_main_kb(devices: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = sorted(devices.items(), key=lambda x: x[1].get("order", 99))
    for eid, cfg in items:
        enabled = cfg.get("enabled", True)
        icon    = cfg.get("icon", "💡")
        name    = cfg.get("name", eid)
        dot     = "🟢" if enabled else "⚫"
        builder.button(text=f"{dot} {icon} {name}", callback_data=f"dev:info:{eid}")
    builder.button(text="🔍 Сканировать HA", callback_data="dev:scan")
    builder.button(text="❌ Закрыть",         callback_data="dev:close")
    builder.adjust(2)
    return builder.as_markup()

def _device_info_kb(eid: str, cfg: dict) -> InlineKeyboardMarkup:
    enabled = cfg.get("enabled", True)
    sect    = cfg.get("section", "lights")
    builder = InlineKeyboardBuilder()
    if enabled:
        builder.button(text="🚫 Скрыть",     callback_data=f"dev:hide:{eid}")
    else:
        builder.button(text="✅ Показать",    callback_data=f"dev:show:{eid}")
    builder.button(text="✏️ Переименовать",   callback_data=f"dev:rename:{eid}")
    # Section toggle (currently only lights/hidden)
    other_sect = "hidden" if sect == "lights" else "lights"
    other_label = _SECT_LABELS.get(other_sect, other_sect)
    builder.button(text=f"→ {other_label}", callback_data=f"dev:sect:{eid}:{other_sect}")
    builder.button(text="◀️ Назад",          callback_data="dev:list")
    builder.adjust(2, 1, 1)
    return builder.as_markup()

def _devices_info_text(eid: str, cfg: dict) -> str:
    icon    = cfg.get("icon", "💡")
    name    = cfg.get("name", eid)
    enabled = cfg.get("enabled", True)
    sect    = cfg.get("section", "lights")
    return (
        f"{icon} <b>{name}</b>\n"
        f"<code>{eid}</code>\n\n"
        f"Раздел: <b>{_SECT_LABELS.get(sect, sect)}</b>\n"
        f"Статус: {'✅ Показывается' if enabled else '🚫 Скрыто'}"
    )

def _devices_main_text(devices: dict) -> str:
    enabled = sum(1 for c in devices.values() if c.get("enabled", True))
    hidden  = len(devices) - enabled
    return (
        f"🛠 <b>Управление устройствами</b>\n\n"
        f"Всего: {len(devices)} | ✅ Показывается: {enabled} | 🚫 Скрыто: {hidden}\n\n"
        f"🟢 — устройство видно в боте и мини апп\n"
        f"⚫ — устройство скрыто\n\n"
        f"Тапни устройство для управления:"
    )

@dp.message(Command("devices"))
@dp.message(F.text == "🛠 Устройства")
async def cmd_devices(msg: Message):
    if not is_admin(msg.from_user.id): return
    devices = _dev_load()
    await msg.answer(_devices_main_text(devices), parse_mode="HTML",
                     reply_markup=_devices_main_kb(devices))

@dp.callback_query(F.data == "dev:list")
async def dev_list(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    devices = _dev_load()
    await cb.message.edit_text(_devices_main_text(devices), parse_mode="HTML",
                                reply_markup=_devices_main_kb(devices))
    await cb.answer()

@dp.callback_query(F.data.startswith("dev:info:"))
async def dev_info(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    eid     = cb.data[len("dev:info:"):]
    devices = _dev_load()
    cfg     = devices.get(eid)
    if not cfg:
        await cb.answer("Устройство не найдено"); return
    await cb.message.edit_text(_devices_info_text(eid, cfg), parse_mode="HTML",
                                reply_markup=_device_info_kb(eid, cfg))
    await cb.answer()

@dp.callback_query(F.data.startswith("dev:hide:"))
async def dev_hide(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    eid = cb.data[len("dev:hide:"):]
    devices = _dev_load()
    if eid in devices:
        devices[eid]["enabled"] = False
        _dev_save(devices)
        _dev_rebuild_lights(devices)
    cfg = devices.get(eid, {})
    await cb.message.edit_text(_devices_info_text(eid, cfg), parse_mode="HTML",
                                reply_markup=_device_info_kb(eid, cfg))
    await cb.answer("🚫 Устройство скрыто")

@dp.callback_query(F.data.startswith("dev:show:"))
async def dev_show(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    eid = cb.data[len("dev:show:"):]
    devices = _dev_load()
    if eid in devices:
        devices[eid]["enabled"] = True
        _dev_save(devices)
        _dev_rebuild_lights(devices)
    cfg = devices.get(eid, {})
    await cb.message.edit_text(_devices_info_text(eid, cfg), parse_mode="HTML",
                                reply_markup=_device_info_kb(eid, cfg))
    await cb.answer("✅ Устройство показано")

@dp.callback_query(F.data.startswith("dev:sect:"))
async def dev_sect(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    _, _, eid, new_sect = cb.data.split(":", 3)
    devices = _dev_load()
    if eid in devices:
        devices[eid]["section"] = new_sect
        # При переходе в hidden — отключаем; при lights — включаем
        devices[eid]["enabled"] = (new_sect != "hidden")
        _dev_save(devices)
        _dev_rebuild_lights(devices)
    cfg = devices.get(eid, {})
    await cb.message.edit_text(_devices_info_text(eid, cfg), parse_mode="HTML",
                                reply_markup=_device_info_kb(eid, cfg))
    sect_label = _SECT_LABELS.get(new_sect, new_sect)
    await cb.answer(f"Раздел: {sect_label}")

@dp.callback_query(F.data.startswith("dev:rename:"))
async def dev_rename_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    eid = cb.data[len("dev:rename:"):]
    await state.update_data(rename_eid=eid)
    await state.set_state(DeviceMgmt.rename_wait)
    devices = _dev_load()
    cur_name = devices.get(eid, {}).get("name", eid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"dev:rename_cancel:{eid}")
    ]])
    await cb.message.edit_text(
        f"✏️ Введите новое имя для <b>{cur_name}</b>\n<code>{eid}</code>",
        parse_mode="HTML", reply_markup=kb
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("dev:rename_cancel:"))
async def dev_rename_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    eid = cb.data[len("dev:rename_cancel:"):]
    devices = _dev_load()
    cfg = devices.get(eid, {})
    await cb.message.edit_text(_devices_info_text(eid, cfg), parse_mode="HTML",
                                reply_markup=_device_info_kb(eid, cfg))
    await cb.answer("Отменено")

@dp.message(StateFilter(DeviceMgmt.rename_wait))
async def dev_rename_done(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        await state.clear(); return
    data = await state.get_data()
    eid  = data.get("rename_eid")
    new_name = msg.text.strip()
    await state.clear()
    if not eid or not new_name:
        await msg.answer("❌ Пустое имя — отмена"); return
    devices = _dev_load()
    if eid in devices:
        devices[eid]["name"] = new_name
        _dev_save(devices)
        _dev_rebuild_lights(devices)
    await msg.answer(f"✅ Переименовано → <b>{new_name}</b>", parse_mode="HTML",
                     reply_markup=_device_info_kb(eid, devices.get(eid, {})))

@dp.callback_query(F.data == "dev:scan")
async def dev_scan(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer("🔍 Сканирую HA...")
    await _refresh_lights()
    devices = _dev_load()
    await cb.message.edit_text(_devices_main_text(devices), parse_mode="HTML",
                                reply_markup=_devices_main_kb(devices))

@dp.callback_query(F.data == "dev:close")
async def dev_close(cb: CallbackQuery):
    await cb.message.delete()
    await cb.answer()

# ── 🌡️ Климат ─────────────────────────────────────────────────────────────────
async def build_climate_text() -> str:
    (temp, hum, floor, floor_t), weather_data = await asyncio.gather(
        asyncio.gather(
            ha_state("sensor.temp_detskaia_temperature"),
            ha_state("sensor.temp_detskaia_humidity"),
            ha_state("climate.teplyi_pol_lodzhiia"),
            ha_attr("climate.teplyi_pol_lodzhiia", "current_temperature"),
        ),
        get_weather(),
    )
    rising  = await ha_state("sensor.sun_next_rising")
    setting = await ha_state("sensor.sun_next_setting")

    def fmt_time(iso):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%H:%M")
        except Exception:
            return "?"

    floor_icon  = "🔥" if floor == "heat" else "❄️"
    temp_alert  = ""
    try:
        t = float(temp)
        if t < 18:   temp_alert = " ⚠️ ХОЛОДНО!"
        elif t > 27: temp_alert = " ⚠️ ЖАРКО!"
    except Exception:
        pass

    outdoor_line = ""
    if weather_data:
        outdoor_t = weather_data.get("current", {}).get("temperature_2m")
        if outdoor_t is not None:
            try:
                diff = float(temp) - float(outdoor_t)
                diff_str = f" (+{diff:.0f}° теплее)" if diff > 0 else f" ({diff:.0f}° холоднее)"
            except Exception:
                diff_str = ""
            outdoor_line = f"\n🌤️ На улице: <b>{outdoor_t:.0f}°C</b>{diff_str}"

    return (
        f"🌡️ <b>Климат</b>\n\n"
        f"🏠 Детская: <b>{temp}°C</b>{temp_alert}, влажность {hum}%"
        f"{outdoor_line}\n"
        f"{floor_icon} Тёплый пол (лоджия): <b>{floor}</b>, {floor_t}°C\n"
        f"🌅 Восход: {fmt_time(rising)}  🌇 Закат: {fmt_time(setting)}"
    )

def _climate_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔥 Пол вкл",  callback_data="floor_on"),
            InlineKeyboardButton(text="❄️ Пол выкл", callback_data="floor_off"),
        ],
        [
            InlineKeyboardButton(text="🌡️ Пол +1°",  callback_data="floor_temp:+1"),
            InlineKeyboardButton(text="🌡️ Пол -1°",  callback_data="floor_temp:-1"),
        ],
        [InlineKeyboardButton(text="📈 История темп 24ч", callback_data="temp_chart")],
        [InlineKeyboardButton(text="🔄 Обновить",         callback_data="climate_refresh")],
    ])

@dp.message(F.text == "🌡️ Климат")
async def climate_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    text = await build_climate_text()
    await msg.answer(text, parse_mode="HTML", reply_markup=_climate_kb())

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
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_climate_kb())

@dp.callback_query(F.data == "temp_chart")
async def temp_chart_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer("📈 Строю график температуры...")
    points = await ha_history("sensor.temp_detskaia_temperature", hours=24)
    if not points:
        await cb.message.answer("❌ Нет данных истории в HA")
        return
    img = _make_chart(points, "🌡️ Температура детской — 24 ч", "°C", "#ef5350")
    if not img:
        await cb.message.answer("❌ Не удалось построить график")
        return
    await cb.message.answer_photo(
        BufferedInputFile(img, filename="temp.png"),
        caption="🌡️ <b>Температура детской — 24 ч</b>",
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("floor_temp:"))
async def floor_temp_adjust(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    delta = int(cb.data.split(":")[1])
    d = await ha_get("states/climate.teplyi_pol_lodzhiia")
    if d:
        current = d.get("attributes", {}).get("temperature", 25)
        new_t   = float(current) + delta
        await ha_post("services/climate/set_temperature", {
            "entity_id": "climate.teplyi_pol_lodzhiia", "temperature": new_t
        })
        await cb.answer(f"🌡️ Установлено {new_t}°C")
    else:
        await cb.answer("❌ Не удалось")

# ── ⚡ Энергия ────────────────────────────────────────────────────────────────
async def _ha_today_kwh() -> float | None:
    """Compute today's kWh from dom_energiia_vsego history (from midnight MSK)."""
    try:
        now_msk = datetime.now(MSK)
        midnight = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
        start = midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        data = await ha_get(
            f"history/period/{start}?filter_entity_id=sensor.dom_energiia_vsego&minimal_response=true"
        )
        if not data or not isinstance(data, list) or not data[0]:
            return None
        vals = []
        for x in data[0]:
            try:
                vals.append(float(x["state"]))
            except Exception:
                pass
        if len(vals) < 2:
            return None
        return max(0.0, vals[-1] - vals[0])
    except Exception as e:
        log.warning(f"_ha_today_kwh error: {e}")
        return None

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
    # Fix: if daily cost sensor is stuck at 0, compute from history
    try:
        if float(day) < 0.1:
            kwh = await _ha_today_kwh()
            if kwh is not None and kwh > 0:
                try:
                    tariff = max(float(await ha_state("input_number.tarif_den_kvt_ch")), 0.5)
                except Exception:
                    tariff = 5.68
                day = f"{kwh * tariff:.2f}"
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

def _energy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 График 24ч",  callback_data="energy_chart:24"),
            InlineKeyboardButton(text="📊 График 7д",   callback_data="energy_chart:168"),
        ],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="energy_refresh")],
    ])

@dp.message(F.text == "⚡ Энергия")
async def energy_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    text = await build_energy_text()
    await msg.answer(text, parse_mode="HTML", reply_markup=_energy_kb())

@dp.callback_query(F.data == "energy_refresh")
async def energy_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer("Обновляю...")
    text = await build_energy_text()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_energy_kb())

@dp.callback_query(F.data.startswith("energy_chart:"))
async def energy_chart_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    hours = int(cb.data.split(":")[1])
    label = "24 ч" if hours == 24 else "7 дней"
    await cb.answer(f"📊 Строю график {label}...")
    points = await ha_history("sensor.moshchnost_vsego_doma", hours=hours)
    if not points:
        await cb.message.answer("❌ Нет данных истории в HA")
        return
    img = _make_chart(points, f"⚡ Мощность дома — {label}", "Вт", "#ffd54f")
    if not img:
        await cb.message.answer("❌ Не удалось построить график")
        return
    await cb.message.answer_photo(
        BufferedInputFile(img, filename="energy.png"),
        caption=f"⚡ <b>Мощность дома — {label}</b>",
        parse_mode="HTML"
    )

# ── 🌤️ Погода ─────────────────────────────────────────────────────────────────
@dp.message(F.text == "🌤️ Погода")
async def weather_menu(msg: Message):
    if not is_allowed(msg.from_user.id): return
    await msg.answer("🌤️ Загружаю погоду...")
    data = await get_weather()
    if not data:
        await msg.answer("❌ Погода временно недоступна")
        return
    await msg.answer(build_weather_text(data), parse_mode="HTML", reply_markup=_WEATHER_KB)

@dp.callback_query(F.data == "weather_refresh")
async def weather_refresh(cb: CallbackQuery):
    if not is_allowed(cb.from_user.id): return
    await cb.answer("Загружаю...")
    data = await get_weather()
    if not data:
        await cb.answer("❌ Недоступно")
        return
    await cb.message.edit_text(build_weather_text(data), parse_mode="HTML", reply_markup=_WEATHER_KB)

# ── 🕌 Намаз ──────────────────────────────────────────────────────────────────
@dp.message(F.text == "🕌 Намаз")
async def namaz_menu(msg: Message):
    if not is_allowed(msg.from_user.id): return
    text = await build_namaz_text()
    await msg.answer(text, parse_mode="HTML", reply_markup=_NAMAZ_KB)

@dp.callback_query(F.data == "namaz_refresh")
async def namaz_refresh(cb: CallbackQuery):
    if not is_allowed(cb.from_user.id): return
    await cb.answer("Обновляю...")
    text = await build_namaz_text()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_NAMAZ_KB)

# ── 📺 Телевизор ──────────────────────────────────────────────────────────────
@dp.message(F.text == "📺 Телевизор")
async def tv_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    d     = await ha_get(f"states/{TV_EID}")
    state = d.get("state", "off") if d else "off"
    text  = await build_tv_text()
    await msg.answer(text, parse_mode="HTML", reply_markup=tv_kb(state))

@dp.callback_query(F.data.startswith("tv:"))
async def tv_action(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    action = cb.data.split(":", 1)[1]
    if action == "turn_on":
        await ha_call("media_player", "turn_on", TV_EID)
        await cb.answer("▶️ Включаю...")
    elif action == "turn_off":
        await ha_call("media_player", "turn_off", TV_EID)
        await cb.answer("📴 Выключаю...")
    elif action == "media_play_pause":
        await ha_call("media_player", "media_play_pause", TV_EID)
        await cb.answer("⏯")
    elif action == "media_stop":
        await ha_call("media_player", "media_stop", TV_EID)
        await cb.answer("⏹ Стоп")
    elif action == "volume_up":
        await ha_call("media_player", "volume_up", TV_EID)
        await cb.answer("🔊")
    elif action == "volume_down":
        await ha_call("media_player", "volume_down", TV_EID)
        await cb.answer("🔉")
    elif action == "mute":
        d     = await ha_get(f"states/{TV_EID}")
        muted = d.get("attributes", {}).get("is_volume_muted", False) if d else False
        await ha_post("services/media_player/volume_mute",
                      {"entity_id": TV_EID, "is_volume_muted": not muted})
        await cb.answer("🔇 Mute" if not muted else "🔊 Unmute")
    elif action == "go_home":
        await ha_call("media_player", "select_source", TV_EID, {"source": "Home"})
        await cb.answer("🏠 Домой")
    elif action == "refresh":
        await cb.answer("Обновлено")
    await asyncio.sleep(0.5)
    d     = await ha_get(f"states/{TV_EID}")
    state = d.get("state", "off") if d else "off"
    text  = await build_tv_text()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=tv_kb(state))

# ── 🏡 Дом ────────────────────────────────────────────────────────────────────
@dp.message(F.text == "🏡 Дом")
async def home_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    khamzat, inet, dl, ul, tv, vacuum = await asyncio.gather(
        ha_state("person.khamzat"),
        ha_state("binary_sensor.keenetic_gateway_wan_status_2"),
        ha_state("sensor.keenetic_gateway_download_speed_2"),
        ha_state("sensor.keenetic_gateway_upload_speed_2"),
        ha_state(TV_EID),
        ha_state("vacuum.pylik"),
    )
    p_icon = "🏠" if khamzat == "home" else "🚗"
    i_icon = "✅" if inet == "on" else "❌"
    text = (
        f"🏡 <b>Дом</b>\n\n"
        f"{p_icon} Хамзат: <b>{khamzat}</b>\n"
        f"{i_icon} Интернет: ↓{dl} / ↑{ul} Мбит/с\n"
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
        ha_state(TV_EID),
        ha_state("vacuum.pylik"),
    )
    p_icon = "🏠" if khamzat == "home" else "🚗"
    i_icon = "✅" if inet == "on" else "❌"
    text = (
        f"🏡 <b>Дом</b> ({datetime.now().strftime('%H:%M')})\n\n"
        f"{p_icon} Хамзат: <b>{khamzat}</b>\n"
        f"{i_icon} Интернет: ↓{dl} / ↑{ul} Мбит/с\n"
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
        return "🤖 <b>Пылесос</b>\n\n❌ Недоступен"
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
        await cb.answer("🏠 На базу")
    elif action == "refresh":
        await cb.answer("Обновлено")
    await asyncio.sleep(1)
    text = await build_vacuum_text()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=cb.message.reply_markup)

# ── 👪 Семья ──────────────────────────────────────────────────────────────────
async def build_family_text() -> str:
    family = await get_family()
    person_states = await asyncio.gather(*[ha_get(f"states/{eid}") for eid in family.values()])
    lines = ["👪 <b>Семья</b>\n"]
    for (label, eid), d in zip(family.items(), person_states):
        if not d:
            lines.append(f"👤 {label}: ❓ нет данных")
            continue
        state = d.get("state", "?")
        if state == "home":
            lines.append(f"👤 {label}: 🏠 <b>Дома</b>")
        elif state == "not_home":
            lines.append(f"👤 {label}: 🚗 Вне дома")
        else:
            lines.append(f"👤 {label}: 📍 {state}")
    return "\n".join(lines)

async def _family_kb() -> InlineKeyboardMarkup:
    family = await get_family()
    builder = InlineKeyboardBuilder()
    for label, eid in family.items():
        key = eid.split(".")[-1]       # "khamzat", "aiza", ...
        builder.button(text=f"📍 {label}", callback_data=f"fam_loc:{key}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="family_refresh"))
    return builder.as_markup()

@dp.message(F.text == "👪 Семья")
async def family_menu(msg: Message):
    if not is_allowed(msg.from_user.id): return
    text = await build_family_text()
    await msg.answer(text, parse_mode="HTML", reply_markup=await _family_kb())

@dp.callback_query(F.data == "family_refresh")
async def family_refresh(cb: CallbackQuery):
    if not is_allowed(cb.from_user.id): return
    await cb.answer("Обновляю...")
    text = await build_family_text()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=await _family_kb())

@dp.callback_query(F.data.startswith("fam_loc:"))
async def family_location(cb: CallbackQuery):
    if not is_allowed(cb.from_user.id): return
    key = cb.data.split(":", 1)[1]   # "khamzat"
    eid = f"person.{key}"
    family = await get_family()
    label = next((l for l, e in family.items() if e == eid), eid)
    d = await ha_get(f"states/{eid}")
    if not d:
        await cb.answer("❌ Нет данных", show_alert=True)
        return
    attrs = d.get("attributes", {})
    lat   = attrs.get("latitude")
    lon   = attrs.get("longitude")
    state = d.get("state", "?")
    if lat and lon:
        maps_url = f"https://www.google.com/maps?q={lat},{lon}"
        acc      = attrs.get("gps_accuracy", "?")
        text = (f"📍 <b>{label}</b>\n"
                f"Статус: {'🏠 Дома' if state == 'home' else '🚗 Вне дома' if state == 'not_home' else state}\n"
                f"Координаты: <code>{lat:.5f}, {lon:.5f}</code>\n"
                f"Точность GPS: {acc} м")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗺 Открыть карту", url=maps_url)
        ]])
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await cb.answer()
    else:
        await cb.answer(
            f"📍 {label}: нет координат GPS (статус: {state})",
            show_alert=True
        )

# ── 🛒 Покупки ─────────────────────────────────────────────────────────────────
def _shop_kb(items: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        name    = item.get("summary", "?")
        status  = item.get("status", "needs_action")
        done_cb = f"shop:done:{name[:40]}"
        del_cb  = f"shop:del:{name[:40]}"
        icon    = "☑️" if status == "completed" else "🔲"
        display = (name[:30] + "…") if len(name) > 31 else name
        builder.button(text=f"{icon} {display}", callback_data=done_cb)
        builder.button(text="🗑",                callback_data=del_cb)
    builder.button(text="➕ Добавить",   callback_data="shop:add")
    builder.button(text="🧹 Очистить",  callback_data="shop:clear")
    builder.button(text="🔄 Обновить",  callback_data="shop:refresh")
    if items:
        builder.adjust(*([2] * len(items)), 1, 2)
    else:
        builder.adjust(1, 2)
    return builder.as_markup()

async def build_shopping_text(items: list) -> str:
    if not items:
        return "🛒 <b>Список покупок</b>\n\n📭 Список пуст"
    total   = len(items)
    done    = sum(1 for i in items if i.get("status") == "completed")
    pending = total - done
    lines   = [f"🛒 <b>Список покупок</b> ({pending} не куплено)\n"]
    for item in items:
        name   = item.get("summary", "?")
        status = item.get("status", "needs_action")
        icon   = "✅" if status == "completed" else "🔲"
        lines.append(f"{icon} {name}")
    return "\n".join(lines)

@dp.message(F.text == "🛒 Покупки")
async def shopping_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    items = await ha_ws_get_todo_items(SHOP_EID)
    text  = await build_shopping_text(items)
    await msg.answer(text, parse_mode="HTML", reply_markup=_shop_kb(items))

@dp.callback_query(F.data == "shop:refresh")
async def shop_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer("Обновляю...")
    items = await ha_ws_get_todo_items(SHOP_EID)
    text  = await build_shopping_text(items)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_shop_kb(items))

@dp.callback_query(F.data == "shop:add")
async def shop_add_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.set_state(ShoppingAdd.waiting)
    await cb.answer()
    await cb.message.answer(
        "🛒 Введи название товара:\n<i>(или /cancel для отмены)</i>",
        parse_mode="HTML"
    )

@dp.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    current = await state.get_state()
    await state.clear()
    if current:
        await msg.answer("❌ Отменено", reply_markup=main_kb())
    else:
        await msg.answer("🏠 Главное меню", reply_markup=main_kb())

@dp.message(StateFilter(ShoppingAdd.waiting))
async def shop_add_item(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    item_text = (msg.text or "").strip()
    if not item_text or item_text.startswith("/"):
        await state.clear()
        await msg.answer("❌ Отменено", reply_markup=main_kb())
        return
    await state.clear()
    result = await ha_post(f"services/todo/add_item",
                           {"entity_id": SHOP_EID, "item": item_text})
    if result is not None:
        await msg.answer(f"✅ <b>{item_text}</b> добавлен в список", parse_mode="HTML",
                         reply_markup=main_kb())
    else:
        await msg.answer("❌ Не удалось добавить", reply_markup=main_kb())
    # Показываем обновлённый список
    await asyncio.sleep(0.5)
    items = await ha_ws_get_todo_items(SHOP_EID)
    text  = await build_shopping_text(items)
    await msg.answer(text, parse_mode="HTML", reply_markup=_shop_kb(items))

@dp.callback_query(F.data.startswith("shop:done:"))
async def shop_done_item(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    name = cb.data[10:]
    # Toggle: check current status
    items = await ha_ws_get_todo_items(SHOP_EID)
    current_item = next((i for i in items if i.get("summary", "").startswith(name[:40])), None)
    if current_item:
        new_status = "needs_action" if current_item.get("status") == "completed" else "completed"
        await ha_post(f"services/todo/update_item",
                      {"entity_id": SHOP_EID, "item": current_item["summary"], "status": new_status})
        await cb.answer("☑️ Отмечено" if new_status == "completed" else "🔲 Снято")
    else:
        await cb.answer("Не найдено")
    await asyncio.sleep(0.3)
    items = await ha_ws_get_todo_items(SHOP_EID)
    text  = await build_shopping_text(items)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_shop_kb(items))

@dp.callback_query(F.data.startswith("shop:del:"))
async def shop_del_item(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    name = cb.data[9:]
    items = await ha_ws_get_todo_items(SHOP_EID)
    full_name = next((i["summary"] for i in items if i.get("summary", "").startswith(name[:40])), name)
    await ha_post(f"services/todo/remove_item",
                  {"entity_id": SHOP_EID, "item": full_name})
    await cb.answer(f"🗑 Удалено")
    await asyncio.sleep(0.3)
    items = await ha_ws_get_todo_items(SHOP_EID)
    text  = await build_shopping_text(items)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_shop_kb(items))

@dp.callback_query(F.data == "shop:clear")
async def shop_clear(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    # Remove all completed items
    items = await ha_ws_get_todo_items(SHOP_EID)
    done  = [i["summary"] for i in items if i.get("status") == "completed"]
    for name in done:
        await ha_post("services/todo/remove_item", {"entity_id": SHOP_EID, "item": name})
    await cb.answer(f"🧹 Удалено {len(done)} выполненных")
    await asyncio.sleep(0.5)
    items = await ha_ws_get_todo_items(SHOP_EID)
    text  = await build_shopping_text(items)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_shop_kb(items))

# ── ⚙️ Автоматизации (с toggle) ──────────────────────────────────────────────
@dp.message(F.text == "⚙️ Автоматизации")
async def automations_menu(msg: Message):
    global _autos_cache
    if not is_admin(msg.from_user.id): return
    _autos_cache = await _fetch_automations()
    if not _autos_cache:
        await msg.answer("❌ Нет автоматизаций")
        return
    await msg.answer(
        "⚙️ <b>Автоматизации</b>\n\nНажми для включения/выключения:",
        parse_mode="HTML",
        reply_markup=_build_auto_kb(_autos_cache)
    )

@dp.callback_query(F.data.startswith("auto:"))
async def automation_action(cb: CallbackQuery):
    global _autos_cache
    if not is_admin(cb.from_user.id): return
    val = cb.data[5:]

    if val == "r":
        _autos_cache = await _fetch_automations()
        await cb.message.edit_reply_markup(reply_markup=_build_auto_kb(_autos_cache))
        await cb.answer("Обновлено")
        return

    try:
        idx   = int(val)
        entry = _autos_cache[idx]
        eid   = entry["entity_id"]
        state = entry.get("state", "off")
    except (ValueError, IndexError):
        await cb.answer("Ошибка")
        return

    if state == "on":
        await ha_call("automation", "turn_off", eid)
        _autos_cache[idx]["state"] = "off"
        await cb.answer("🚫 Выключено")
    else:
        await ha_call("automation", "turn_on", eid)
        _autos_cache[idx]["state"] = "on"
        await cb.answer("✅ Включено")
    await cb.message.edit_reply_markup(reply_markup=_build_auto_kb(_autos_cache))

# ── 📹 Камеры ─────────────────────────────────────────────────────────────────
@dp.message(F.text == "📹 Камеры")
async def cameras_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📹 Камеры в HA",  url=f"{HA_URL}/lovelace/cameras")],
        [InlineKeyboardButton(text="🎞 Frigate",       url=f"{HA_URL}/ccab4aaf_frigate-fa")],
    ])
    await msg.answer(
        "📹 <b>Камеры</b>\n\n"
        "🎥 <b>Лофт</b> — Frigate (<code>camera.loft</code>)\n"
        f"RTSP: <code>rtsp://admin:010203@192.168.1.194:554/</code>",
        parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True
    )

# ── 🧠 ИИ Ассистент (Claude) ──────────────────────────────────────────────────
async def get_ha_context() -> str:
    power, temp, hum, inet, tv, person, floor, vacuum, namaz_d = await asyncio.gather(
        ha_state("sensor.moshchnost_vsego_doma"),
        ha_state("sensor.temp_detskaia_temperature"),
        ha_state("sensor.temp_detskaia_humidity"),
        ha_state("binary_sensor.keenetic_gateway_wan_status_2"),
        ha_state(TV_EID),
        ha_state("person.khamzat"),
        ha_state("climate.teplyi_pol_lodzhiia"),
        ha_state("vacuum.pylik"),
        ha_get(f"states/{NAMAZ_EID}"),
    )
    light_on = [n for n, (_, e) in LIGHTS.items() if await ha_state(e) == "on"]
    lights_str = ", ".join(light_on) if light_on else "весь выключен"

    namaz_str = ""
    if namaz_d and namaz_d.get("state") == "active":
        finishes = namaz_d.get("attributes", {}).get("finishes_at", "")
        if finishes:
            namaz_str = f"\nДо намаза: {_namaz_remaining(finishes)}"

    return (
        f"Мощность дома: {power} Вт\n"
        f"Температура детской: {temp}°C, влажность {hum}%\n"
        f"Интернет: {'онлайн' if inet == 'on' else 'офлайн'}\n"
        f"TV: {tv}\nХамзат: {person}\n"
        f"Тёплый пол: {floor}\nПылесос: {vacuum}\n"
        f"Свет горит: {lights_str}"
        + namaz_str
    )

async def ask_claude(question: str, context: str) -> str:
    system = (
        "Ты — умный ассистент умного дома. Отвечай коротко и по делу на русском языке. "
        "Текущее состояние дома:\n" + context
    )
    prompt = f"{system}\n\nВопрос: {question}"
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    try:
        proc = await asyncio.create_subprocess_exec(
            "/root/.local/bin/claude", "-p", prompt, "--model", "claude-haiku-4-5",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        result = stdout.decode("utf-8", errors="replace").strip()
        if result:
            return result
        log.error(f"Claude stderr: {stderr.decode('utf-8', errors='replace').strip()}")
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
        "Задавай вопросы о состоянии дома.\n"
        "Примеры:\n"
        "• <i>Какая температура в детской?</i>\n"
        "• <i>Сколько потребляет дом?</i>\n"
        "• <i>Кто дома?</i>\n\n"
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
    context  = await get_ha_context()
    answer   = await ask_claude(question, context)
    await thinking.delete()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Выйти из чата с ИИ", callback_data="ai_exit")
    ]])
    await msg.answer(f"🧠 {answer}", parse_mode="HTML", reply_markup=kb)

# ── 🔍 Inline режим ───────────────────────────────────────────────────────────
@dp.inline_query()
async def inline_handler(query: InlineQuery):
    q       = query.query.strip().lower()
    results = []

    # Статус дома
    if not q or any(k in q for k in ("дом", "статус", "status", "дома")):
        try:
            text = await build_status_text()
            results.append(InlineQueryResultArticle(
                id="status",
                title="📊 Статус дома",
                description="Мощность, температура, интернет, TV",
                input_message_content=InputTextMessageContent(
                    message_text=text, parse_mode="HTML"
                )
            ))
        except Exception:
            pass

    # Погода
    if not q or any(k in q for k in ("погода", "weather", "темп")):
        try:
            data = await get_weather()
            if data:
                results.append(InlineQueryResultArticle(
                    id="weather",
                    title="🌤️ Погода — Грозный",
                    description="Текущая погода и прогноз на 3 дня",
                    input_message_content=InputTextMessageContent(
                        message_text=build_weather_text(data), parse_mode="HTML"
                    )
                ))
        except Exception:
            pass

    # Намаз
    if not q or any(k in q for k in ("намаз", "namaz", "молитва")):
        try:
            text = await build_namaz_text()
            results.append(InlineQueryResultArticle(
                id="namaz",
                title="🕌 Намаз",
                description="Таймер до следующего намаза",
                input_message_content=InputTextMessageContent(
                    message_text=text, parse_mode="HTML"
                )
            ))
        except Exception:
            pass

    # Энергия
    if not q or any(k in q for k in ("энергия", "свет", "мощность", "energy")):
        try:
            text = await build_energy_text()
            results.append(InlineQueryResultArticle(
                id="energy",
                title="⚡ Энергия",
                description="Мощность и стоимость электричества",
                input_message_content=InputTextMessageContent(
                    message_text=text, parse_mode="HTML"
                )
            ))
        except Exception:
            pass

    # Семья
    if not q or any(k in q for k in ("семья", "family", "дома", "хамзат")):
        try:
            text = await build_family_text()
            results.append(InlineQueryResultArticle(
                id="family",
                title="👪 Семья",
                description="Кто дома, кто вне дома",
                input_message_content=InputTextMessageContent(
                    message_text=text, parse_mode="HTML"
                )
            ))
        except Exception:
            pass

    await query.answer(results[:10], cache_time=30, is_personal=True)

# ── Фоновые алерты ────────────────────────────────────────────────────────────
_alert_state = {
    "power_high":              False,
    "temp_low":                False,
    "temp_high":               False,
    "person_khamzat":          None,
    "person_khamzat_notif_ts": None,   # datetime UTC последнего уведомления о присутствии
    "namaz_notified_prayer":   None,   # "2026-03-07_Asr"
    "last_briefing_day":       None,
    "last_weekly_report":      None,   # "week_10_2026"
}

async def alert_loop():
    await asyncio.sleep(10)
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

    # ⚡ Высокая мощность
    try:
        power = float(power_d.get("state", 0)) if power_d else 0
        if power > 3000 and not _alert_state["power_high"]:
            _alert_state["power_high"] = True
            await bot.send_message(ADMIN_ID, f"⚡ <b>Высокая нагрузка!</b> {power:.0f} Вт", parse_mode="HTML")
        elif power <= 3000 and _alert_state["power_high"]:
            _alert_state["power_high"] = False
    except Exception as e:
        log.error(f"Alert power check: {e}")

    # 🌡️ Температура детской
    try:
        temp = float(temp_d.get("state", 20)) if temp_d else 20
        if temp < 18 and not _alert_state["temp_low"]:
            _alert_state["temp_low"] = True
            await bot.send_message(ADMIN_ID, f"🥶 <b>Холодно в детской!</b> {temp}°C", parse_mode="HTML")
        elif temp >= 18:
            _alert_state["temp_low"] = False
        if temp > 27 and not _alert_state["temp_high"]:
            _alert_state["temp_high"] = True
            await bot.send_message(ADMIN_ID, f"🥵 <b>Жарко в детской!</b> {temp}°C", parse_mode="HTML")
        elif temp <= 27:
            _alert_state["temp_high"] = False
    except Exception as e:
        log.error(f"Alert temp check: {e}")

    # 🏠 Приход/уход Хамзата (кулдаун 10 мин, чтобы не спамить при колебаниях HA)
    try:
        person = person_d.get("state", "?") if person_d else "?"
        prev   = _alert_state["person_khamzat"]
        if prev is not None and prev != person:
            last_ts = _alert_state["person_khamzat_notif_ts"]
            now_utc = datetime.now(timezone.utc)
            cooldown_ok = (last_ts is None or
                           (now_utc - last_ts).total_seconds() > 600)
            if cooldown_ok:
                if person == "home":
                    await bot.send_message(ADMIN_ID, "🏠 Хамзат <b>дома</b>", parse_mode="HTML")
                    _alert_state["person_khamzat_notif_ts"] = now_utc
                elif prev == "home":
                    await bot.send_message(ADMIN_ID, "🚗 Хамзат <b>ушёл</b>", parse_mode="HTML")
                    _alert_state["person_khamzat_notif_ts"] = now_utc
        _alert_state["person_khamzat"] = person
    except Exception as e:
        log.error(f"Alert person check: {e}")

    # 🕌 Намаз — уведомление за 15 минут по расписанию Aladhan
    try:
        now_msk = datetime.now(MSK)
        timings = await get_prayer_times()
        if timings:
            for p_name in PRAYERS_ORDER:
                p_time_str = timings.get(p_name, "")
                if not p_time_str:
                    continue
                try:
                    p_dt = datetime.strptime(p_time_str, "%H:%M").replace(
                        year=now_msk.year, month=now_msk.month, day=now_msk.day,
                        tzinfo=MSK
                    )
                except Exception:
                    continue
                diff_min = int((p_dt - now_msk).total_seconds() / 60)
                if 0 < diff_min <= 15:
                    notif_key = f"{now_msk.date().isoformat()}_{p_name}"
                    if _alert_state["namaz_notified_prayer"] != notif_key:
                        _alert_state["namaz_notified_prayer"] = notif_key
                        icon, ru_name = PRAYERS_RU[p_name]
                        await bot.send_message(
                            ADMIN_ID,
                            f"🕌 <b>Через {diff_min} мин — {ru_name}!</b>\n"
                            f"{icon} Время: {p_time_str}",
                            parse_mode="HTML"
                        )
                    break  # Уведомляем только ближайший намаз
    except Exception as e:
        log.error(f"Alert namaz check: {e}")

    # 🌅 Утренняя сводка в 8:00
    now = datetime.now()
    if now.hour == 8 and now.minute < 1:
        today = now.date().isoformat()
        if _alert_state["last_briefing_day"] != today:
            _alert_state["last_briefing_day"] = today
            await _send_morning_briefing()

    # 🗓️ Еженедельный отчёт — воскресенье 20:00
    if now.weekday() == 6 and now.hour == 20 and now.minute < 1:
        iso = now.isocalendar()
        week_key = f"week_{iso.week}_{iso.year}"
        if _alert_state["last_weekly_report"] != week_key:
            _alert_state["last_weekly_report"] = week_key
            await _send_weekly_report()

async def _send_morning_briefing():
    try:
        status_text  = await build_status_text()
        weather_data = await get_weather()
        weather_line = ""
        if weather_data:
            c    = weather_data.get("current", {})
            code = c.get("weather_code", 0)
            cond = WMO_CODES.get(code, "").split()[0] if WMO_CODES.get(code) else ""
            temp = c.get("temperature_2m", "?")
            weather_line = f"\n🌤️ Погода: {cond} <b>{temp}°C</b>"

        prayer_line = ""
        timings = await get_prayer_times()
        if timings:
            parts = []
            for p in PRAYERS_ORDER:
                t = timings.get(p, "")
                if t:
                    icon, ru = PRAYERS_RU[p]
                    parts.append(f"{icon}{t}")
            if parts:
                prayer_line = "\n🕌 " + "  ".join(parts)

        await bot.send_message(
            ADMIN_ID,
            f"🌅 <b>Доброе утро!</b>{weather_line}{prayer_line}\n\n{status_text}",
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Morning briefing error: {e}")

async def _send_weekly_report():
    try:
        now = datetime.now(MSK)
        week_num = now.isocalendar().week
        day_d, month_d, prog_d = await asyncio.gather(
            ha_state("sensor.elektroenergiia_stoimost_za_den"),
            ha_state("sensor.elektroenergiia_stoimost_za_mesiats"),
            ha_state("sensor.elektroenergiia_prognoz_scheta_za_mesiats"),
        )
        text = (
            f"🗓️ <b>Еженедельный отчёт — неделя {week_num}</b>\n\n"
            f"⚡ Сегодня: <b>{day_d} ₽</b>\n"
            f"💰 Накоплено за месяц: <b>{month_d} ₽</b>\n"
            f"📈 Прогноз за месяц: <b>{prog_d} ₽</b>"
        )
        points = await ha_history("sensor.moshchnost_vsego_doma", hours=168)
        if points:
            img = _make_chart(points, f"⚡ Мощность дома — неделя {week_num}", "Вт", "#ffd54f")
            if img:
                await bot.send_photo(
                    ADMIN_ID,
                    BufferedInputFile(img, filename="weekly.png"),
                    caption=text,
                    parse_mode="HTML"
                )
                return
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        log.error(f"Weekly report error: {e}")

# ── Web App handlers ──────────────────────────────────────────────────────────
def _check_token(request: aiohttp_web.Request) -> bool:
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {WEBAPP_TOKEN}"

async def _web_index(request: aiohttp_web.Request) -> aiohttp_web.Response:
    path = WEBAPP_DIR / "index.html"
    if not path.exists():
        return aiohttp_web.Response(status=404, text="Not found")
    return aiohttp_web.Response(
        body=path.read_bytes(),
        content_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )

_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}

async def _web_options(request: aiohttp_web.Request) -> aiohttp_web.Response:
    return aiohttp_web.Response(status=204, headers=_CORS_HEADERS)

async def _web_status(request: aiohttp_web.Request) -> aiohttp_web.Response:
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        family = await get_family()
        # Build list of custom-section devices (not lights, not hidden)
        devices_cfg = _dev_load()
        sections_cfg = _sect_load()
        custom_sect_eids: list[str] = [
            eid for eid, cfg in devices_cfg.items()
            if cfg.get("section", "lights") not in ("lights", "hidden") and cfg.get("enabled", True)
        ]

        results = await asyncio.gather(
            ha_get("states/sensor.moshchnost_vsego_doma"),
            ha_get("states/sensor.temp_detskaia_temperature"),
            ha_get("states/sensor.temp_detskaia_humidity"),
            ha_get("states/binary_sensor.keenetic_gateway_wan_status_2"),
            ha_get("states/climate.teplyi_pol_lodzhiia"),
            ha_get(f"states/{TV_EID}"),
            ha_get("states/vacuum.pylik"),
            ha_get("states/sensor.elektroenergiia_stoimost_za_den"),
            ha_get("states/sensor.elektroenergiia_stoimost_za_mesiats"),
            *[ha_get(f"states/{eid}") for eid in family.values()],
            *[ha_get(f"states/{eid}") for _, (_, eid) in LIGHTS.items()],
            *[ha_get(f"states/{eid}") for eid in _HA_PRAYER_EIDS.values()],
            *[ha_get(f"states/{eid}") for eid in custom_sect_eids],
        )
        n_fixed = 9
        n_family = len(family)
        n_lights = len(LIGHTS)
        n_prayers = len(_HA_PRAYER_EIDS)
        n_custom = len(custom_sect_eids)
        power_d, temp_d, hum_d, inet_d, floor_d, tv_d, vac_d, cost_day_d, cost_month_d = results[:n_fixed]
        family_results  = results[n_fixed:n_fixed + n_family]
        lights_results  = results[n_fixed + n_family:n_fixed + n_family + n_lights]
        prayer_results  = results[n_fixed + n_family + n_lights:n_fixed + n_family + n_lights + n_prayers]
        custom_results  = results[n_fixed + n_family + n_lights + n_prayers:]

        def st(d): return d.get("state", "?") if d else "?"

        floor_attrs = floor_d.get("attributes", {}) if floor_d else {}
        tv_attrs    = tv_d.get("attributes", {}) if tv_d else {}

        family_data = {}
        for (name, _), d in zip(family.items(), family_results):
            attrs_f = d.get("attributes", {}) if d else {}
            family_data[name] = {
                "state": st(d),
                "lat":   attrs_f.get("latitude"),
                "lon":   attrs_f.get("longitude"),
            }

        lights_data = {}
        for (name, (domain, eid)), d in zip(LIGHTS.items(), lights_results):
            icon = LIGHTS_ICON.get(eid, "💡")
            lights_data[eid] = {"state": st(d), "name": name, "icon": icon, "domain": domain}

        # Prayers: {ru_name: "HH:MM"}
        prayer_names_ru = {"Fajr": "Фаджр", "Dhuhr": "Зухр",
                           "Asr": "Аср", "Maghrib": "Магриб", "Isha": "Иша"}
        prayers_data = {}
        for (prayer_key, _), pd in zip(_HA_PRAYER_EIDS.items(), prayer_results):
            t = st(pd)[:5] if pd else "?"
            prayers_data[prayer_names_ru.get(prayer_key, prayer_key)] = t

        # Weather (cached, non-blocking)
        weather_payload = None
        wd = await get_weather()
        if wd:
            wc = wd.get("current", {})
            wdaily = wd.get("daily", {})
            wcode = wc.get("weather_code", 0)
            try:
                wupdated = datetime.fromisoformat(wc.get("time", "")).strftime("%H:%M")
            except Exception:
                wupdated = "?"
            day_names_w = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            wdays = wdaily.get("time", [])
            wt_max = wdaily.get("temperature_2m_max", [])
            wt_min = wdaily.get("temperature_2m_min", [])
            wcodes = wdaily.get("weather_code", [])
            wforecast = []
            for wi in range(min(3, len(wdays))):
                try:
                    fd = datetime.fromisoformat(wdays[wi])
                    wicon = WMO_CODES.get(wcodes[wi], "?").split()[0]
                    wforecast.append({
                        "label": f"{day_names_w[fd.weekday()]} {fd.strftime('%d.%m')}",
                        "icon": wicon,
                        "min": wt_min[wi],
                        "max": wt_max[wi],
                    })
                except Exception:
                    pass
            weather_payload = {
                "condition": WMO_CODES.get(wcode, f"Код {wcode}"),
                "temp":      wc.get("temperature_2m"),
                "feels_like": wc.get("apparent_temperature"),
                "humidity":  wc.get("relative_humidity_2m"),
                "wind":      wc.get("wind_speed_10m"),
                "precip":    wc.get("precipitation", 0),
                "updated":   wupdated,
                "forecast":  wforecast,
            }

        outdoor_temp = None
        if weather_payload:
            outdoor_temp = weather_payload.get("temp")

        # Daily cost: fix if sensor stuck at 0
        cost_day_raw = st(cost_day_d)
        cost_day_val = cost_day_raw
        try:
            if float(cost_day_raw) < 0.1:
                kwh = await _ha_today_kwh()
                if kwh is not None and kwh > 0:
                    try:
                        tariff = max(float(await ha_state("input_number.tarif_den_kvt_ch")), 0.5)
                    except Exception:
                        tariff = 5.68
                    cost_day_val = f"{kwh * tariff:.2f}"
        except Exception:
            pass

        # Custom sections data: group by section_id
        custom_sections: dict = {}
        for eid, d in zip(custom_sect_eids, custom_results):
            cfg = devices_cfg.get(eid, {})
            sect = cfg.get("section", "other")
            if sect not in custom_sections:
                custom_sections[sect] = {}
            custom_sections[sect][eid] = {
                "state":  st(d),
                "name":   cfg.get("name", eid),
                "icon":   cfg.get("icon", "📦"),
                "domain": eid.split(".")[0] if "." in eid else "unknown",
            }

        # Sections metadata for frontend rendering
        active_sects = []
        for sect_id, sect_cfg in sorted(sections_cfg.items(), key=lambda x: x[1].get("order", 99)):
            if sect_cfg.get("enabled", False) or sect_id in custom_sections:
                active_sects.append({
                    "id":      sect_id,
                    "name":    sect_cfg.get("name", sect_id),
                    "icon":    sect_cfg.get("icon", "📦"),
                    "devices": custom_sections.get(sect_id, {}),
                })

        payload = {
            "power":         st(power_d),
            "temp_detskaia": st(temp_d),
            "humidity":      st(hum_d),
            "internet":      "on" if st(inet_d) == "on" else "off",
            "floor_heating": st(floor_d),
            "floor_setpoint": str(floor_attrs.get("temperature", "?")),
            "floor_temp":    str(floor_attrs.get("current_temperature", "?")),
            "cost_day":      cost_day_val,
            "cost_month":    st(cost_month_d),
            "outdoor_temp":  outdoor_temp,
            "family":        family_data,
            "lights":        lights_data,
            "sections":      active_sects,
            "tv": {
                "state":  st(tv_d),
                "title":  tv_attrs.get("media_title", ""),
                "volume": tv_attrs.get("volume_level"),
                "muted":  tv_attrs.get("is_volume_muted", False),
            },
            "vacuum": {
                "state": st(vac_d),
            },
            "prayers": prayers_data,
            "weather": weather_payload,
        }
        return aiohttp_web.Response(
            text=json.dumps(payload, ensure_ascii=False),
            content_type="application/json",
            headers=_CORS_HEADERS,
        )
    except Exception as e:
        log.error(f"web_status error: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_action(request: aiohttp_web.Request) -> aiohttp_web.Response:
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        service_str = body.get("service", "")   # e.g. "light.turn_on"
        entity_id   = body.get("entity_id", "")
        extra       = body.get("extra") or {}
        if "." not in service_str or not entity_id:
            return aiohttp_web.Response(status=400, text="Bad request", headers=_CORS_HEADERS)
        domain, service = service_str.split(".", 1)
        await ha_call(domain, service, entity_id, extra or None)
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"web_action error: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_devices_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/devices — вернуть конфиг всех устройств."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    devices = _dev_load()
    return aiohttp_web.Response(
        text=json.dumps(devices, ensure_ascii=False),
        content_type="application/json",
        headers=_CORS_HEADERS,
    )

async def _web_devices_post(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/devices — обновить параметры устройства.
    Body: {entity_id, name?, icon?, section?, enabled?}
    """
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        eid  = body.get("entity_id", "")
        if not eid:
            return aiohttp_web.Response(status=400, text="entity_id required", headers=_CORS_HEADERS)
        devices = _dev_load()
        if eid not in devices:
            # Добавляем новую сущность
            max_order = max((v.get("order", 0) for v in devices.values()), default=0) + 1
            devices[eid] = {
                "name":    body.get("name", eid),
                "icon":    body.get("icon", "📦"),
                "section": body.get("section", "hidden"),
                "enabled": body.get("section", "hidden") != "hidden",
                "order":   max_order,
            }
        else:
            for field in ("name", "icon", "section", "enabled", "order"):
                if field in body:
                    devices[eid][field] = body[field]
            # enabled = (section != "hidden")
            if "section" in body:
                devices[eid]["enabled"] = (body["section"] != "hidden")
        _dev_save(devices)
        _dev_rebuild_lights(devices)
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"web_devices_post error: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_sections_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/sections — список всех секций."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    sections = _sect_load()
    return aiohttp_web.Response(
        text=json.dumps(sections, ensure_ascii=False),
        content_type="application/json",
        headers=_CORS_HEADERS,
    )

async def _web_sections_post(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/sections — создать/обновить/удалить секцию.
    Body: {id, name?, icon?, enabled?, order?, delete?}
    """
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body    = await request.json()
        sect_id = body.get("id", "").strip().lower().replace(" ", "_")
        if not sect_id:
            return aiohttp_web.Response(status=400, text="id required", headers=_CORS_HEADERS)
        sections = _sect_load()
        if body.get("delete"):
            sections.pop(sect_id, None)
        else:
            if sect_id not in sections:
                max_ord = max((v.get("order", 0) for v in sections.values()), default=9) + 1
                sections[sect_id] = {"name": body.get("name", sect_id), "icon": body.get("icon", "📦"),
                                     "enabled": True, "order": max_ord}
            else:
                for field in ("name", "icon", "enabled", "order"):
                    if field in body:
                        sections[sect_id][field] = body[field]
        _sect_save(sections)
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"web_sections_post error: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_ha_entities(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/ha_entities — все сущности HA, сгруппированные по домену.
    Параметр ?exclude_known=1 исключает уже добавленные в devices.json.
    """
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        states = await ha_get("states")
        if not states:
            return aiohttp_web.Response(text='{}', content_type="application/json", headers=_CORS_HEADERS)
        exclude_known = request.rel_url.query.get("exclude_known", "0") == "1"
        known = set(_dev_load().keys()) if exclude_known else set()
        grouped: dict = {}
        for s in states:
            eid = s.get("entity_id", "")
            if not eid or eid in known:
                continue
            domain = eid.split(".")[0]
            attrs  = s.get("attributes", {})
            fn     = attrs.get("friendly_name", eid)
            if domain not in grouped:
                grouped[domain] = []
            grouped[domain].append({
                "entity_id": eid,
                "name":      fn,
                "state":     s.get("state", ""),
            })
        for d in grouped:
            grouped[d].sort(key=lambda x: x["name"].lower())
        return aiohttp_web.Response(
            text=json.dumps(grouped, ensure_ascii=False),
            content_type="application/json",
            headers=_CORS_HEADERS,
        )
    except Exception as e:
        log.error(f"web_ha_entities error: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_ha_scan(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/ha_scan — запустить сканирование HA, вернуть новые сущности."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        before = set(_dev_load().keys())
        await _refresh_lights()
        after = _dev_load()
        new_eids = [eid for eid in after if eid not in before]
        result = {eid: after[eid] for eid in new_eids}
        return aiohttp_web.Response(
            text=json.dumps({"found": len(new_eids), "devices": result}, ensure_ascii=False),
            content_type="application/json",
            headers=_CORS_HEADERS,
        )
    except Exception as e:
        log.error(f"web_ha_scan error: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _start_web():
    app = aiohttp_web.Application()
    app.router.add_get("/ha-app/",                  _web_index)
    app.router.add_get("/ha-app",                   _web_index)
    app.router.add_get("/ha-app/api/status",        _web_status)
    app.router.add_post("/ha-app/api/action",       _web_action)
    app.router.add_get("/ha-app/api/devices",       _web_devices_get)
    app.router.add_post("/ha-app/api/devices",      _web_devices_post)
    app.router.add_get("/ha-app/api/ha_scan",       _web_ha_scan)
    app.router.add_get("/ha-app/api/ha_entities",   _web_ha_entities)
    app.router.add_get("/ha-app/api/sections",      _web_sections_get)
    app.router.add_post("/ha-app/api/sections",     _web_sections_post)
    app.router.add_route("OPTIONS", "/ha-app/api/status",       _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/action",       _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/devices",      _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/ha_scan",      _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/ha_entities",  _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/sections",     _web_options)
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    site = aiohttp_web.TCPSite(runner, "127.0.0.1", 8766)
    await site.start()
    log.info("WebApp server started on 127.0.0.1:8766")

# ── /app command ──────────────────────────────────────────────────────────────
@dp.message(Command("app"))
async def cmd_app(msg: Message):
    if not is_admin(msg.from_user.id): return
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(
        text="🖥️ Открыть панель", web_app=WebAppInfo(url=WEBAPP_URL)
    )]], resize_keyboard=True, one_time_keyboard=True)
    await msg.answer("🖥️ Откройте панель управления:", reply_markup=kb)

# ── Запуск ────────────────────────────────────────────────────────────────────
async def main():
    log.info("HA Bot v3.3 starting...")
    _dev_init()            # загрузить devices.json → заполнить LIGHTS/LIGHTS_ICON
    await _refresh_lights()  # сканировать HA, добавить новые устройства
    asyncio.create_task(alert_loop())
    asyncio.create_task(_start_web())
    await bot.send_message(
        ADMIN_ID,
        "🏠 <b>Home Assistant Bot v3.3 запущен!</b>\n"
        "✅ Намаз по Aladhan API, алерт за 15 мин\n"
        "✅ 📊 Графики энергии (24ч / 7 дней)\n"
        "✅ 📈 История температуры (24ч)\n"
        "✅ 🗓️ Еженедельный отчёт (воскресенье 20:00)\n"
        "✅ Телевизор, Семья, Покупки, Автоматизации\n"
        "✅ ИИ Ассистент, Погода, Авто-алерты\n"
        "✅ 🖥️ Telegram Mini App панель управления",
        parse_mode="HTML"
    )
    log.info("Start polling")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
