#!/usr/bin/env python3
"""
Home Assistant Telegram Bot — управление умным домом с кнопками.
"""
import asyncio
import os
import json
import logging
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv("/opt/ha-bot/.env")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID  = int(os.environ["ADMIN_ID"])
HA_URL    = os.environ["HA_URL"].rstrip("/")
HA_TOKEN  = os.environ["HA_TOKEN"]
HA_HEADERS = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

# ── HA API ────────────────────────────────────────────────────────────────────
async def ha_get(path: str) -> dict | list | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{HA_URL}/api/{path}", headers=HA_HEADERS, ssl=False, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        log.error(f"HA GET {path}: {e}")
    return None

async def ha_post(path: str, data: dict = None) -> dict | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{HA_URL}/api/{path}", headers=HA_HEADERS, json=data or {}, ssl=False, timeout=aiohttp.ClientTimeout(total=10)) as r:
                return await r.json()
    except Exception as e:
        log.error(f"HA POST {path}: {e}")
    return None

async def ha_state(entity_id: str) -> str:
    d = await ha_get(f"states/{entity_id}")
    return d.get("state", "?") if d else "?"

async def ha_call(domain: str, service: str, entity_id: str, extra: dict = None):
    data = {"entity_id": entity_id, **(extra or {})}
    return await ha_post(f"services/{domain}/{service}", data)

# ── Auth ──────────────────────────────────────────────────────────────────────
def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

# ── Главная клавиатура ────────────────────────────────────────────────────────
def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🏠 Дом"),        KeyboardButton(text="💡 Свет")],
        [KeyboardButton(text="🌡️ Климат"),     KeyboardButton(text="⚡ Энергия")],
        [KeyboardButton(text="📹 Камеры"),     KeyboardButton(text="🤖 Пылесос")],
        [KeyboardButton(text="🌤 Погода"),     KeyboardButton(text="🔔 Автоматизации")],
        [KeyboardButton(text="📊 Статус"),     KeyboardButton(text="⚙️ Настройки")],
    ], resize_keyboard=True)

# ── /start ────────────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.answer("⛔ Доступ запрещён")
        return
    await msg.answer(
        "🏠 <b>Home Assistant Bot</b>\n\nУправление умным домом — выбери раздел:",
        parse_mode="HTML",
        reply_markup=main_kb()
    )

# ── 📊 Статус — общий обзор дома ──────────────────────────────────────────────
@dp.message(F.text == "📊 Статус")
async def status_home(msg: Message):
    if not is_admin(msg.from_user.id): return

    entities = {
        "Мощность дома":   "sensor.moshchnost_vsego_doma",
        "Стоимость/день":  "sensor.elektroenergiia_stoimost_za_den",
        "Прогноз/месяц":   "sensor.elektroenergiia_prognoz_scheta_za_mesiats",
        "Температура дет.":"sensor.temp_detskaia_temperature",
        "Влажность дет.":  "sensor.temp_detskaia_humidity",
        "Интернет":        "binary_sensor.keenetic_gateway_wan_status_2",
        "TV":              "media_player.android_tv",
        "Хамзат":          "person.khamzat",
    }

    lines = ["📊 <b>Статус дома</b>\n"]
    for name, eid in entities.items():
        state = await ha_state(eid)
        icon = "✅" if state in ("on", "home", "playing", "Connected") else (
               "⚠️" if state in ("unavailable", "unknown") else "ℹ️")
        lines.append(f"{icon} <b>{name}</b>: <code>{state}</code>")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="status_refresh")
    ]])
    await msg.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "status_refresh")
async def status_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer("Обновляю...")
    entities = {
        "Мощность дома":   "sensor.moshchnost_vsego_doma",
        "Стоимость/день":  "sensor.elektroenergiia_stoimost_za_den",
        "Прогноз/месяц":   "sensor.elektroenergiia_prognoz_scheta_za_mesiats",
        "Температура дет.":"sensor.temp_detskaia_temperature",
        "Влажность дет.":  "sensor.temp_detskaia_humidity",
        "Интернет":        "binary_sensor.keenetic_gateway_wan_status_2",
        "TV":              "media_player.android_tv",
        "Хамзат":          "person.khamzat",
    }
    lines = [f"📊 <b>Статус дома</b> (обновлено {datetime.now().strftime('%H:%M:%S')})\n"]
    for name, eid in entities.items():
        state = await ha_state(eid)
        icon = "✅" if state in ("on", "home", "playing", "Connected") else (
               "⚠️" if state in ("unavailable", "unknown") else "ℹ️")
        lines.append(f"{icon} <b>{name}</b>: <code>{state}</code>")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="status_refresh")
    ]])
    await cb.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)

# ── 💡 Свет ───────────────────────────────────────────────────────────────────
LIGHTS = {
    "Кровать":          ("light",  "light.svet_krovat"),
    "Кухня":            ("switch", "switch.vykliuchatel_kukhnia"),
    "ПК Левый":         ("switch", "switch.kabinet_svet_pk_left"),
    "ПК Правый":        ("switch", "switch.kabinet_svet_pk_right"),
    "Люстра Детская":   ("switch", "switch.sonoff_100093f84f"),
    "Шкаф":             ("switch", "switch.sonoff_1000a60930"),
}

def lights_kb(states: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for name, (domain, eid) in LIGHTS.items():
        state = states.get(eid, "?")
        icon = "🟡" if state == "on" else "⚫"
        builder.button(text=f"{icon} {name}", callback_data=f"light_toggle:{domain}:{eid}")
    builder.button(text="💡 Всё вкл", callback_data="lights_all_on")
    builder.button(text="🌑 Всё выкл", callback_data="lights_all_off")
    builder.button(text="🔄 Обновить", callback_data="lights_refresh")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()

@dp.message(F.text == "💡 Свет")
async def lights_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    states = {}
    for name, (domain, eid) in LIGHTS.items():
        states[eid] = await ha_state(eid)
    await msg.answer("💡 <b>Управление светом</b>", parse_mode="HTML",
                     reply_markup=lights_kb(states))

@dp.callback_query(F.data.startswith("light_toggle:"))
async def light_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    _, domain, eid = cb.data.split(":", 2)
    state = await ha_state(eid)
    service = "turn_off" if state == "on" else "turn_on"
    await ha_call(domain, service, eid)
    await cb.answer(f"{'Выключаю' if service == 'turn_off' else 'Включаю'}...")
    await asyncio.sleep(0.5)
    states = {}
    for name, (dom, e) in LIGHTS.items():
        states[e] = await ha_state(e)
    await cb.message.edit_reply_markup(reply_markup=lights_kb(states))

@dp.callback_query(F.data == "lights_all_on")
async def lights_all_on(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    for name, (domain, eid) in LIGHTS.items():
        await ha_call(domain, "turn_on", eid)
    await cb.answer("💡 Весь свет включён")
    await asyncio.sleep(1)
    states = {e: await ha_state(e) for _, (d, e) in LIGHTS.items()}
    await cb.message.edit_reply_markup(reply_markup=lights_kb(states))

@dp.callback_query(F.data == "lights_all_off")
async def lights_all_off(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    for name, (domain, eid) in LIGHTS.items():
        await ha_call(domain, "turn_off", eid)
    await cb.answer("🌑 Весь свет выключен")
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
@dp.message(F.text == "🌡️ Климат")
async def climate_menu(msg: Message):
    if not is_admin(msg.from_user.id): return

    temp   = await ha_state("sensor.temp_detskaia_temperature")
    hum    = await ha_state("sensor.temp_detskaia_humidity")
    floor  = await ha_state("climate.teplyi_pol_lodzhiia")
    rising = await ha_state("sensor.sun_next_rising")
    setting= await ha_state("sensor.sun_next_setting")

    def fmt_time(iso):
        try:
            from datetime import timezone
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            local = dt.astimezone()
            return local.strftime("%H:%M")
        except:
            return iso

    text = (
        f"🌡️ <b>Климат</b>\n\n"
        f"🏠 <b>Детская</b>: {temp}°C, влажность {hum}%\n"
        f"🔥 <b>Тёплый пол (лоджия)</b>: {floor}\n"
        f"🌅 Восход: {fmt_time(rising)} | Закат: {fmt_time(setting)}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔥 Пол вкл", callback_data="floor_on"),
            InlineKeyboardButton(text="❄️ Пол выкл", callback_data="floor_off"),
        ],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="climate_refresh")],
    ])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.in_({"floor_on", "floor_off", "climate_refresh"}))
async def climate_actions(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    if cb.data == "floor_on":
        await ha_call("climate", "turn_on", "climate.teplyi_pol_lodzhiia")
        await cb.answer("🔥 Тёплый пол включён")
    elif cb.data == "floor_off":
        await ha_call("climate", "turn_off", "climate.teplyi_pol_lodzhiia")
        await cb.answer("❄️ Тёплый пол выключен")
    else:
        await cb.answer("Обновлено")

# ── ⚡ Энергия ────────────────────────────────────────────────────────────────
@dp.message(F.text == "⚡ Энергия")
async def energy_menu(msg: Message):
    if not is_admin(msg.from_user.id): return

    power  = await ha_state("sensor.moshchnost_vsego_doma")
    v1     = await ha_state("sensor.vvod_1_moshchnost")
    v2     = await ha_state("sensor.vvod_2_moshchnost")
    v3     = await ha_state("sensor.vvod_3_moshchnost")
    day    = await ha_state("sensor.elektroenergiia_stoimost_za_den")
    month  = await ha_state("sensor.elektroenergiia_stoimost_za_mesiats")
    prog   = await ha_state("sensor.elektroenergiia_prognoz_scheta_za_mesiats")

    text = (
        f"⚡ <b>Энергия</b>\n\n"
        f"🏠 <b>Общая мощность</b>: {power} Вт\n"
        f"  ├ Ввод 1: {v1} Вт\n"
        f"  ├ Ввод 2: {v2} Вт\n"
        f"  └ Ввод 3: {v3} Вт\n\n"
        f"💰 <b>Сегодня</b>: {day} ₽\n"
        f"💰 <b>Месяц</b>: {month} ₽\n"
        f"📈 <b>Прогноз месяца</b>: {prog} ₽"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="energy_refresh")
    ]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "energy_refresh")
async def energy_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    power  = await ha_state("sensor.moshchnost_vsego_doma")
    v1     = await ha_state("sensor.vvod_1_moshchnost")
    v2     = await ha_state("sensor.vvod_2_moshchnost")
    v3     = await ha_state("sensor.vvod_3_moshchnost")
    day    = await ha_state("sensor.elektroenergiia_stoimost_za_den")
    month  = await ha_state("sensor.elektroenergiia_stoimost_za_mesiats")
    prog   = await ha_state("sensor.elektroenergiia_prognoz_scheta_za_mesiats")
    text = (
        f"⚡ <b>Энергия</b> (обновлено {datetime.now().strftime('%H:%M:%S')})\n\n"
        f"🏠 <b>Общая мощность</b>: {power} Вт\n"
        f"  ├ Ввод 1: {v1} Вт\n"
        f"  ├ Ввод 2: {v2} Вт\n"
        f"  └ Ввод 3: {v3} Вт\n\n"
        f"💰 <b>Сегодня</b>: {day} ₽\n"
        f"💰 <b>Месяц</b>: {month} ₽\n"
        f"📈 <b>Прогноз месяца</b>: {prog} ₽"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data="energy_refresh")
    ]])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("Обновлено")

# ── 🌤 Погода ─────────────────────────────────────────────────────────────────
@dp.message(F.text == "🌤 Погода")
async def weather_menu(msg: Message):
    if not is_admin(msg.from_user.id): return

    d = await ha_get("states/weather.yandex_weather")
    if not d:
        await msg.answer("❌ Погода недоступна")
        return

    state = d.get("state", "?")
    attr  = d.get("attributes", {})
    temp  = attr.get("temperature", "?")
    feels = attr.get("apparent_temperature", "?")
    wind  = attr.get("wind_speed", "?")
    humid = attr.get("humidity", "?")

    text = (
        f"🌤 <b>Погода</b>\n\n"
        f"🌡️ Температура: <b>{temp}°C</b> (ощущается {feels}°C)\n"
        f"💨 Ветер: {wind} м/с\n"
        f"💧 Влажность: {humid}%\n"
        f"☁️ Условия: {state}"
    )
    await msg.answer(text, parse_mode="HTML")

# ── 🏠 Дом ────────────────────────────────────────────────────────────────────
@dp.message(F.text == "🏠 Дом")
async def home_menu(msg: Message):
    if not is_admin(msg.from_user.id): return

    khamzat = await ha_state("person.khamzat")
    inet    = await ha_state("binary_sensor.keenetic_gateway_wan_status_2")
    dl      = await ha_state("sensor.keenetic_gateway_download_speed_2")
    ul      = await ha_state("sensor.keenetic_gateway_upload_speed_2")
    tv      = await ha_state("media_player.android_tv")
    vacuum  = await ha_state("vacuum.pylik")

    def person_icon(s): return "🏠" if s == "home" else "🚗"
    def inet_icon(s):   return "✅" if s == "on" else "❌"

    text = (
        f"🏠 <b>Дом</b>\n\n"
        f"{person_icon(khamzat)} Хамзат: <b>{khamzat}</b>\n"
        f"{inet_icon(inet)} Интернет: ↓{dl} Мбит/с  ↑{ul} Мбит/с\n"
        f"📺 TV: <b>{tv}</b>\n"
        f"🤖 Пылесос: <b>{vacuum}</b>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔔 Обновить новости", callback_data="news_refresh"),
        ],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="home_refresh")],
    ])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "home_refresh")
async def home_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    khamzat = await ha_state("person.khamzat")
    inet    = await ha_state("binary_sensor.keenetic_gateway_wan_status_2")
    dl      = await ha_state("sensor.keenetic_gateway_download_speed_2")
    ul      = await ha_state("sensor.keenetic_gateway_upload_speed_2")
    tv      = await ha_state("media_player.android_tv")
    vacuum  = await ha_state("vacuum.pylik")
    def person_icon(s): return "🏠" if s == "home" else "🚗"
    def inet_icon(s):   return "✅" if s == "on" else "❌"
    text = (
        f"🏠 <b>Дом</b> (обновлено {datetime.now().strftime('%H:%M:%S')})\n\n"
        f"{person_icon(khamzat)} Хамзат: <b>{khamzat}</b>\n"
        f"{inet_icon(inet)} Интернет: ↓{dl} Мбит/с  ↑{ul} Мбит/с\n"
        f"📺 TV: <b>{tv}</b>\n"
        f"🤖 Пылесос: <b>{vacuum}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Обновить новости", callback_data="news_refresh")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="home_refresh")],
    ])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("Обновлено")

@dp.callback_query(F.data == "news_refresh")
async def news_refresh_trigger(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await ha_call("input_boolean", "turn_on", "input_boolean.news_refresh_trigger")
    await asyncio.sleep(1)
    await ha_call("input_boolean", "turn_off", "input_boolean.news_refresh_trigger")
    await cb.answer("📰 Новости обновляются...")

# ── 🤖 Пылесос ────────────────────────────────────────────────────────────────
@dp.message(F.text == "🤖 Пылесос")
async def vacuum_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    state = await ha_state("vacuum.pylik")
    d = await ha_get("states/vacuum.pylik")
    battery = d.get("attributes", {}).get("battery_level", "?") if d else "?"
    text = f"🤖 <b>Пылесос</b>\nСостояние: <b>{state}</b>\n🔋 Батарея: {battery}%"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="▶️ Старт", callback_data="vacuum_start"),
            InlineKeyboardButton(text="⏸ Пауза",  callback_data="vacuum_pause"),
        ],
        [
            InlineKeyboardButton(text="🏠 База",   callback_data="vacuum_home"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="vacuum_refresh"),
        ],
    ])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("vacuum_"))
async def vacuum_actions(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    action = cb.data.replace("vacuum_", "")
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

# ── 📹 Камеры ─────────────────────────────────────────────────────────────────
@dp.message(F.text == "📹 Камеры")
async def cameras_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    text = (
        "📹 <b>Камеры</b>\n\n"
        "🎥 <b>Лофт</b>: camera.loft (Frigate)\n"
        "RTSP: <code>rtsp://admin:010203@192.168.1.194:554/</code>\n\n"
        "Для просмотра — открой Home Assistant:\n"
        "<a href='https://ha-as.khamzat-home.crazedns.ru'>Открыть HA</a>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌐 Открыть HA", url="https://ha-as.khamzat-home.crazedns.ru/lovelace/cameras")
    ]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)

# ── 🔔 Автоматизации ──────────────────────────────────────────────────────────
@dp.message(F.text == "🔔 Автоматизации")
async def automations_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    automations = await ha_get("states")
    if not automations:
        await msg.answer("❌ Не удалось получить данные")
        return
    autos = [e for e in automations if e["entity_id"].startswith("automation.")][:15]
    lines = ["🔔 <b>Автоматизации</b>\n"]
    for a in autos:
        state = a.get("state", "?")
        name  = a.get("attributes", {}).get("friendly_name", a["entity_id"])
        icon  = "✅" if state == "on" else "🚫"
        lines.append(f"{icon} {name}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌐 Открыть HA", url="https://ha-as.khamzat-home.crazedns.ru/lovelace/automations")
    ]])
    await msg.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)

# ── ⚙️ Настройки ──────────────────────────────────────────────────────────────
@dp.message(F.text == "⚙️ Настройки")
async def settings_menu(msg: Message):
    if not is_admin(msg.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть HA", url="https://ha-as.khamzat-home.crazedns.ru")],
        [InlineKeyboardButton(text="📊 Дашборд Энергия", url="https://ha-as.khamzat-home.crazedns.ru/lovelace/energy")],
        [InlineKeyboardButton(text="⚙️ Настройки HA",   url="https://ha-as.khamzat-home.crazedns.ru/config")],
    ])
    await msg.answer("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=kb)

# ── Запуск ────────────────────────────────────────────────────────────────────
async def main():
    log.info("HA Bot starting...")
    await bot.send_message(
        ADMIN_ID,
        "🏠 <b>Home Assistant Bot запущен!</b>\nУправляй умным домом из Telegram.",
        parse_mode="HTML"
    )
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
