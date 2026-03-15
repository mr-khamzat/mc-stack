#!/usr/bin/env python3
"""
HA Home Bot — Telegram-бот + Mini App для управления умным домом
================================================================

Этот файл — единственный бэкенд всего проекта. Он делает две вещи
одновременно в одном процессе:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. TELEGRAM BOT (библиотека aiogram 3.x)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Работает через Long Polling — постоянно спрашивает Telegram API
   "есть ли новые сообщения?". Это не требует внешнего IP и сертификата.

   Команды пользователя:
     /start     — приветствие, показать главное меню
     /status    — полный статус дома (свет, климат, энергия, семья)
     /lights    — управление светом (кнопки вкл/выкл для каждого)
     /climate   — температура, влажность, тёплый пол
     /energy    — потребление за день/месяц, фазы, прогноз
     /weather   — погода и прогноз на 3 дня (Open-Meteo API)
     /namaz     — время молитв из HA, таймер
     /cameras   — камеры Frigate: снимок, события, клипы
     /family    — где находятся члены семьи (person.* в HA)
     /shopping  — список покупок (todo.* в HA)
     /vacuum    — управление роботом-пылесосом
     /tv        — управление телевизором
     /scenes    — сцены: Спать / Уходим / Кино / создать своё
     /ai        — чат с Claude AI
     /devices   — настройка устройств (иконка, раздел, название)
     /users     — управление пользователями (только admin)
     /invite    — создать ссылку-приглашение
     /backup    — экспортировать конфигурацию
     /app       — открыть Mini App

   Фоновые задачи (запускаются при старте):
     alert_loop()           — каждую минуту проверяет алерты
     _ha_state_watch_loop() — слушает WebSocket HA, рассылает SSE
     _frigate_event_loop()  — следит за новыми событиями Frigate

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. HTTP WEB-СЕРВЕР (библиотека aiohttp, порт 8766)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Слушает только на 127.0.0.1:8766 (не доступен снаружи напрямую).
   Nginx проксирует внешние запросы на него через /ha-app/*.

   Основные эндпоинты:
     GET  /ha-app/                → отдаёт index.html с токеном
     GET  /ha-app/api/health      → проверка работоспособности
     GET  /ha-app/api/status      → JSON со всем состоянием дома
     GET  /ha-app/api/events      → SSE поток реальных изменений HA
     POST /ha-app/api/action      → вызвать сервис HA
     GET  /ha-app/api/devices     → список устройств
     POST /ha-app/api/devices     → изменить устройство
     GET  /ha-app/api/sections    → разделы панели
     POST /ha-app/api/sections    → изменить раздел
     GET  /ha-app/api/scenes      → список сцен
     POST /ha-app/api/scenes      → создать/обновить сцену
     DELETE /ha-app/api/scenes/{id} → удалить сцену
     POST /ha-app/api/scenes/{id}/run → запустить сцену
     GET  /ha-app/api/alerts      → конфиг алертов
     POST /ha-app/api/alerts      → сохранить конфиг алертов
     GET  /ha-app/api/activity    → журнал активности
     GET  /ha-app/api/frigate/*   → проксирование Frigate с авторизацией
     GET  /ha-app/api/server-stats → CPU/RAM/Disk/Uptime
     GET  /ha-app/api/energy/hourly → почасовое потребление
     GET  /ha-app/api/logbook     → логбук HA
     GET/POST /ha-app/api/night-mode → ночной режим

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КОНФИГУРАЦИЯ (.env файл):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   BOT_TOKEN         — токен бота от @BotFather
   ADMIN_ID          — Telegram ID главного администратора
   HA_URL            — внешний URL Home Assistant (https://...)
   HA_TOKEN          — long-lived токен HA
   WEBAPP_TOKEN      — секрет для авторизации запросов Mini App
   ANTHROPIC_API_KEY — (опционально) ключ Claude API для /ai

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ХРАНЕНИЕ ДАННЫХ:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Все данные хранятся в SQLite БД /opt/ha-bot/ha_bot.db.
   Таблицы: devices, sections, scenes, config,
            activity_log, faces_log, family_users.
   При первом запуске автоматически мигрирует данные из JSON файлов.

Версия: 3.5  |  Язык: Python 3.11+  |  Лицензия: MIT
"""
import asyncio
import hashlib
import hmac
import io
import os
import json
import logging
import sqlite3
import socket
import ssl as _ssl
import subprocess
import time as _time
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import parse as urlparse

import psutil
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

# ── Загрузка конфигурации из .env ─────────────────────────────────────────────
load_dotenv("/opt/ha-bot/.env")

BOT_TOKEN  = os.environ["BOT_TOKEN"]
ADMIN_ID   = int(os.environ["ADMIN_ID"])
HA_URL     = os.environ["HA_URL"].rstrip("/")
HA_TOKEN   = os.environ["HA_TOKEN"]
HA_HEADERS = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

WEBAPP_TOKEN = os.environ.get("WEBAPP_TOKEN", "")
WEBAPP_URL   = os.environ.get("WEBAPP_URL", "").rstrip("/") + "/"  # читается из .env!
WEBAPP_DIR   = Path(os.environ.get("WEBAPP_DIR", "/opt/ha-bot/webapp"))
# Логины HA-пользователей с ролью admin в мини апс (из .env, через запятую)
_HA_WEBAPP_ADMINS = {u.strip().lower() for u in os.environ.get("HA_WEBAPP_ADMINS", "").split(",") if u.strip()}

FAMILY_USERS_FILE  = Path("/opt/ha-bot/family_users.json")
PHOTOS_DIR         = Path("/opt/ha-bot/photos")
PHOTOS_DIR.mkdir(exist_ok=True)
VOICES_DIR         = Path("/opt/ha-bot/voices")
VOICES_DIR.mkdir(exist_ok=True)

# ── VAPID keys (Web Push) ──────────────────────────────────────────────────────
VAPID_PRIVATE_PEM_FILE = Path("/opt/ha-bot/vapid_private.pem")
VAPID_PUBLIC_FILE      = Path("/opt/ha-bot/vapid_public.txt")
VAPID_PUBLIC_KEY: str  = VAPID_PUBLIC_FILE.read_text().strip() if VAPID_PUBLIC_FILE.exists() else ""
VAPID_CLAIMS = {"sub": "https://hub.office.mooo.com"}

# ── Пути к файлам данных ───────────────────────────────────────────────────────
DB_FILE            = Path("/opt/ha-bot/ha_bot.db")      # SQLite (основное хранилище)
# Legacy JSON пути — используются только для первичной миграции в SQLite
DEVICES_FILE       = Path("/opt/ha-bot/devices.json")
SECTIONS_FILE      = Path("/opt/ha-bot/sections.json")
ACTIVITY_LOG_FILE  = Path("/opt/ha-bot/activity_log.json")
ALERTS_CONFIG_FILE = Path("/opt/ha-bot/alerts_config.json")
SCENES_FILE        = Path("/opt/ha-bot/scenes.json")
FACES_LOG_FILE     = Path("/opt/ha-bot/faces_log.json")
NIGHT_MODE_FILE    = Path("/opt/ha-bot/night_mode.json")

# ── SQLite: глобальное подключение + блокировка для записи ────────────────────
_DB: sqlite3.Connection | None = None
_DB_LOCK = threading.Lock()

def _db() -> sqlite3.Connection:
    global _DB
    if _DB is None:
        _DB = sqlite3.connect(str(DB_FILE), check_same_thread=False)
        _DB.row_factory = sqlite3.Row
        _DB.execute("PRAGMA journal_mode=WAL")
        _DB.execute("PRAGMA synchronous=NORMAL")
        _DB.execute("PRAGMA foreign_keys=ON")
    return _DB

def _db_init():
    """Создать таблицы и выполнить однократную миграцию из JSON."""
    c = _db()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            entity_id TEXT PRIMARY KEY,
            name      TEXT NOT NULL DEFAULT '',
            icon      TEXT NOT NULL DEFAULT '📦',
            section   TEXT NOT NULL DEFAULT 'lights',
            enabled   INTEGER NOT NULL DEFAULT 1,
            ord       INTEGER NOT NULL DEFAULT 99
        );
        CREATE TABLE IF NOT EXISTS sections (
            id      TEXT PRIMARY KEY,
            name    TEXT NOT NULL DEFAULT '',
            icon    TEXT NOT NULL DEFAULT '📦',
            enabled INTEGER NOT NULL DEFAULT 1,
            ord     INTEGER NOT NULL DEFAULT 99,
            hidden  INTEGER NOT NULL DEFAULT 0,
            builtin INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS scenes (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            icon       TEXT NOT NULL DEFAULT '🎬',
            entities   TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            ts     TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS faces_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT NOT NULL,
            person   TEXT NOT NULL,
            event_id TEXT NOT NULL,
            camera   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS family_users (
            user_id TEXT PRIMARY KEY,
            data    TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT NOT NULL,
            endpoint  TEXT NOT NULL UNIQUE,
            p256dh    TEXT NOT NULL,
            auth      TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS shopping_assignments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            item_text   TEXT NOT NULL,
            list_entity TEXT NOT NULL DEFAULT '',
            assigned_to TEXT NOT NULL,
            assigned_by TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            notified_at TEXT,
            done        INTEGER NOT NULL DEFAULT 0
        );
CREATE TABLE IF NOT EXISTS family_statuses (
    username     TEXT PRIMARY KEY,
    status_emoji TEXT NOT NULL DEFAULT '😊',
    status_text  TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS family_note (
    id         INTEGER PRIMARY KEY DEFAULT 1,
    content    TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS family_reactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user  TEXT NOT NULL,
    to_user    TEXT NOT NULL,
    reaction   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cooking_schedule (
    date       TEXT PRIMARY KEY,
    username   TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS shopping_item_meta (
    item_uid  TEXT PRIMARY KEY,
    item_text TEXT NOT NULL DEFAULT '',
    priority  INTEGER NOT NULL DEFAULT 0,
    quantity  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS shopping_quick_items (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE,
    emoji TEXT NOT NULL DEFAULT '',
    ord   INTEGER NOT NULL DEFAULT 99
);
CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    text       TEXT NOT NULL,
    remind_at  TEXT NOT NULL,
    is_global  INTEGER NOT NULL DEFAULT 0,
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    edited     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS photos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    filename   TEXT NOT NULL UNIQUE,
    caption    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
    """)
    c.commit()
    # Schema migrations
    for migration in [
        "ALTER TABLE activity_log ADD COLUMN username TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE chat_messages ADD COLUMN msg_type TEXT NOT NULL DEFAULT 'text'",
        "ALTER TABLE chat_messages ADD COLUMN voice_file TEXT NOT NULL DEFAULT ''",
        """CREATE TABLE IF NOT EXISTS call_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user    TEXT NOT NULL,
            to_user      TEXT NOT NULL,
            call_type    TEXT NOT NULL DEFAULT 'audio',
            started_at   TEXT NOT NULL,
            answered_at  TEXT,
            ended_at     TEXT,
            duration_sec INTEGER,
            status       TEXT NOT NULL DEFAULT 'missed'
        )""",
    ]:
        try:
            c.execute(migration)
            c.commit()
        except Exception:
            pass
    _db_migrate()

def _db_migrate():
    """Однократная миграция данных из JSON файлов в SQLite."""
    c = _db()
    # devices.json
    if c.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0 and DEVICES_FILE.exists():
        try:
            data = json.loads(DEVICES_FILE.read_text())
            for eid, cfg in data.items():
                c.execute("INSERT OR IGNORE INTO devices VALUES (?,?,?,?,?,?)",
                    (eid, cfg.get("name",""), cfg.get("icon","📦"),
                     cfg.get("section","lights"), int(cfg.get("enabled",True)),
                     cfg.get("order",99)))
            c.commit()
            log.info(f"DB migrate: {len(data)} devices from JSON")
        except Exception as e:
            log.error(f"DB migrate devices: {e}")
    # sections.json
    if c.execute("SELECT COUNT(*) FROM sections").fetchone()[0] == 0 and SECTIONS_FILE.exists():
        try:
            data = json.loads(SECTIONS_FILE.read_text())
            for sid, cfg in data.items():
                c.execute("INSERT OR IGNORE INTO sections VALUES (?,?,?,?,?,?,?)",
                    (sid, cfg.get("name",""), cfg.get("icon","📦"),
                     int(cfg.get("enabled",True)), cfg.get("order",99),
                     int(cfg.get("hidden",False)), int(cfg.get("builtin",False))))
            c.commit()
            log.info(f"DB migrate: {len(data)} sections from JSON")
        except Exception as e:
            log.error(f"DB migrate sections: {e}")
    # alerts_config.json
    if c.execute("SELECT COUNT(*) FROM config WHERE key='alerts'").fetchone()[0] == 0 \
            and ALERTS_CONFIG_FILE.exists():
        try:
            c.execute("INSERT OR IGNORE INTO config VALUES ('alerts',?)",
                      (ALERTS_CONFIG_FILE.read_text(),))
            c.commit()
            log.info("DB migrate: alerts config from JSON")
        except Exception as e:
            log.error(f"DB migrate alerts: {e}")
    # activity_log.json
    if c.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 0 \
            and ACTIVITY_LOG_FILE.exists():
        try:
            data = json.loads(ACTIVITY_LOG_FILE.read_text())
            for entry in data:
                c.execute("INSERT INTO activity_log (ts,action,detail) VALUES (?,?,?)",
                    (entry.get("ts",""), entry.get("action",""), entry.get("detail","")))
            c.commit()
            log.info(f"DB migrate: {len(data)} activity entries from JSON")
        except Exception as e:
            log.error(f"DB migrate activity_log: {e}")
    # faces_log.json
    if c.execute("SELECT COUNT(*) FROM faces_log").fetchone()[0] == 0 \
            and FACES_LOG_FILE.exists():
        try:
            data = json.loads(FACES_LOG_FILE.read_text())
            for entry in data:
                c.execute("INSERT INTO faces_log (ts,person,event_id,camera) VALUES (?,?,?,?)",
                    (entry.get("ts",""), entry.get("person",""),
                     entry.get("event_id",""), entry.get("camera","")))
            c.commit()
            log.info(f"DB migrate: {len(data)} face entries from JSON")
        except Exception as e:
            log.error(f"DB migrate faces_log: {e}")
    # scenes.json
    if c.execute("SELECT COUNT(*) FROM scenes").fetchone()[0] == 0 and SCENES_FILE.exists():
        try:
            data = json.loads(SCENES_FILE.read_text())
            for sid, cfg in data.items():
                c.execute("INSERT OR IGNORE INTO scenes VALUES (?,?,?,?,?)",
                    (sid, cfg.get("name",""), cfg.get("icon","🎬"),
                     json.dumps(cfg.get("entities",{}), ensure_ascii=False),
                     cfg.get("created_at","")))
            c.commit()
            log.info(f"DB migrate: {len(data)} scenes from JSON")
        except Exception as e:
            log.error(f"DB migrate scenes: {e}")
    # family_users.json
    if c.execute("SELECT COUNT(*) FROM family_users").fetchone()[0] == 0 \
            and FAMILY_USERS_FILE.exists():
        try:
            data = json.loads(FAMILY_USERS_FILE.read_text())
            for uid, udata in data.items():
                c.execute("INSERT OR IGNORE INTO family_users VALUES (?,?)",
                    (str(uid), json.dumps(udata, ensure_ascii=False)))
            c.commit()
            log.info(f"DB migrate: {len(data)} family users from JSON")
        except Exception as e:
            log.error(f"DB migrate family_users: {e}")
    # night_mode.json
    if c.execute("SELECT COUNT(*) FROM config WHERE key='night_mode'").fetchone()[0] == 0 \
            and NIGHT_MODE_FILE.exists():
        try:
            c.execute("INSERT OR IGNORE INTO config VALUES ('night_mode',?)",
                      (NIGHT_MODE_FILE.read_text(),))
            c.commit()
            log.info("DB migrate: night_mode from JSON")
        except Exception as e:
            log.error(f"DB migrate night_mode: {e}")

_ALERTS_DEFAULTS = {
    "power_threshold":   3000,
    "temp_min":          18,
    "temp_max":          27,
    "quiet_hours_start": 23,
    "quiet_hours_end":   7,
    "enabled": {
        "power":   True,
        "temp":    True,
        "person":  True,
        "namaz":   True,
        "morning": True,
        "frigate": True,
        "inet":    True,
    }
}

def _alerts_load() -> dict:
    try:
        row = _db().execute("SELECT value FROM config WHERE key='alerts'").fetchone()
        if row:
            data = json.loads(row[0])
            cfg = dict(_ALERTS_DEFAULTS)
            cfg.update(data)
            cfg["enabled"] = {**_ALERTS_DEFAULTS["enabled"], **data.get("enabled", {})}
            return cfg
    except Exception as e:
        log.error(f"alerts_load: {e}")
    return dict(_ALERTS_DEFAULTS)

def _alerts_save(cfg: dict):
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("INSERT OR REPLACE INTO config VALUES ('alerts',?)",
                      (json.dumps(cfg, ensure_ascii=False),))
            c.commit()
    except Exception as e:
        log.error(f"alerts_save: {e}")

# ── Сцены / Режимы ────────────────────────────────────────────────────────────
_SCENES_DEFAULTS = {
    "sleep": {
        "name": "Спать",
        "icon": "🌙",
        "description": "Выключить весь свет",
        "actions": [
            {"entity_id": "light.svet_krovat",            "service": "light.turn_off"},
            {"entity_id": "switch.vykliuchatel_kukhnia",  "service": "switch.turn_off"},
            {"entity_id": "switch.kabinet_svet_pk_left",  "service": "switch.turn_off"},
            {"entity_id": "switch.kabinet_svet_pk_right", "service": "switch.turn_off"},
            {"entity_id": "switch.sonoff_100093f84f",     "service": "switch.turn_off"},
            {"entity_id": "switch.sonoff_1000a60930",     "service": "switch.turn_off"},
        ]
    },
    "away": {
        "name": "Уходим",
        "icon": "🚗",
        "description": "Всё выключить",
        "actions": [
            {"entity_id": "light.svet_krovat",            "service": "light.turn_off"},
            {"entity_id": "switch.vykliuchatel_kukhnia",  "service": "switch.turn_off"},
            {"entity_id": "switch.kabinet_svet_pk_left",  "service": "switch.turn_off"},
            {"entity_id": "switch.kabinet_svet_pk_right", "service": "switch.turn_off"},
            {"entity_id": "switch.sonoff_100093f84f",     "service": "switch.turn_off"},
            {"entity_id": "switch.sonoff_1000a60930",     "service": "switch.turn_off"},
            {"entity_id": "media_player.android_tv",      "service": "media_player.turn_off"},
        ]
    },
    "movie": {
        "name": "Кино",
        "icon": "🎬",
        "description": "Приглушить свет, включить TV",
        "actions": [
            {"entity_id": "light.svet_krovat",            "service": "light.turn_on",
             "extra": {"brightness_pct": 30}},
            {"entity_id": "switch.vykliuchatel_kukhnia",  "service": "switch.turn_off"},
            {"entity_id": "switch.sonoff_100093f84f",     "service": "switch.turn_off"},
            {"entity_id": "media_player.android_tv",      "service": "media_player.turn_on"},
        ]
    },
    "evening": {
        "name": "Вечер",
        "icon": "🌆",
        "description": "Мягкий вечерний свет",
        "actions": [
            {"entity_id": "light.svet_krovat",            "service": "light.turn_on",
             "extra": {"brightness_pct": 60, "color_temp": 400}},
            {"entity_id": "switch.sonoff_100093f84f",     "service": "switch.turn_on"},
            {"entity_id": "switch.vykliuchatel_kukhnia",  "service": "switch.turn_on"},
        ]
    },
}

def _scenes_load() -> dict:
    try:
        rows = _db().execute("SELECT id,name,icon,entities,created_at FROM scenes").fetchall()
        if rows:
            return {r["id"]: {"name": r["name"], "icon": r["icon"],
                              "entities": json.loads(r["entities"] or "{}"),
                              "created_at": r["created_at"]} for r in rows}
    except Exception as e:
        log.error(f"scenes_load: {e}")
    return dict(_SCENES_DEFAULTS)

def _scenes_save(scenes: dict):
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("DELETE FROM scenes")
            for sid, cfg in scenes.items():
                c.execute("INSERT INTO scenes VALUES (?,?,?,?,?)",
                    (sid, cfg.get("name",""), cfg.get("icon","🎬"),
                     json.dumps(cfg.get("entities",{}), ensure_ascii=False),
                     cfg.get("created_at","")))
            c.commit()
    except Exception as e:
        log.error(f"scenes_save: {e}")

_BOT_START_TIME   = _time.time()
_BOT_VERSION      = "3.5"

# Status API cache (5 sec TTL)
_status_cache: dict = {"ts": 0.0, "data": None}
_STATUS_CACHE_TTL   = 5

_SECTIONS_DEFAULTS: dict = {
    # Встроенные разделы — можно скрыть, нельзя удалить или переименовать
    "status":     {"name": "🔔 Статус",       "icon": "🔔",  "enabled": True,  "order": 1,  "builtin": True},
    "family":     {"name": "👨‍👩‍👧 Семья",      "icon": "👨‍👩‍👧", "enabled": True,  "order": 2,  "builtin": True},
    "presence":   {"name": "🏠 Присутствие",  "icon": "🏠",  "enabled": True,  "order": 3,  "builtin": True},
    "faces":      {"name": "🙂 Лица",         "icon": "🙂",  "enabled": True,  "order": 4,  "builtin": True},
    "energy":     {"name": "⚡ Энергия",      "icon": "⚡",  "enabled": True,  "order": 5,  "builtin": True},
    "lights":     {"name": "💡 Свет",         "icon": "💡",  "enabled": True,  "order": 6,  "builtin": True},
    "climate":    {"name": "🌡️ Климат",       "icon": "🌡️", "enabled": True,  "order": 7,  "builtin": True},
    "tv":         {"name": "📺 TV",           "icon": "📺",  "enabled": True,  "order": 8,  "builtin": True},
    "vacuum":     {"name": "🤖 Пылесос",      "icon": "🤖",  "enabled": True,  "order": 9,  "builtin": True},
    "prayers":    {"name": "🕌 Намаз",        "icon": "🕌",  "enabled": True,  "order": 10, "builtin": True},
    "weather":    {"name": "🌤️ Погода",       "icon": "🌤️", "enabled": True,  "order": 11, "builtin": True},
    "scenes":     {"name": "🎬 Сцены",        "icon": "🎬",  "enabled": True,  "order": 12, "builtin": True},
    "alerts":     {"name": "🔔 Алерты",       "icon": "🔔",  "enabled": True,  "order": 13, "builtin": True},
    "nightmode":  {"name": "🌙 Ночной режим", "icon": "🌙",  "enabled": True,  "order": 14, "builtin": True},
    "server":     {"name": "🖥️ Сервер",       "icon": "🖥️", "enabled": True,  "order": 15, "builtin": True},
    "logbook":    {"name": "📋 История HA",   "icon": "📋",  "enabled": True,  "order": 16, "builtin": True},
    "activity":   {"name": "📊 Активность",   "icon": "📊",  "enabled": True,  "order": 17, "builtin": True},
    # Динамические разделы — полное редактирование (добавлять устройства, менять иконку и название)
    "cameras":    {"name": "📹 Камеры",        "icon": "📹", "enabled": True,  "order": 20},
    "automations":{"name": "🤖 Автоматизации", "icon": "🤖", "enabled": False, "order": 21},
    "sensors":    {"name": "📊 Сенсоры",       "icon": "📊", "enabled": False, "order": 22},
    "media":      {"name": "📺 Медиа",         "icon": "📺", "enabled": False, "order": 23},
}

def _sect_load() -> dict:
    saved: dict = {}
    try:
        rows = _db().execute("SELECT id,name,icon,enabled,ord,hidden,builtin FROM sections").fetchall()
        for r in rows:
            saved[r["id"]] = {"name": r["name"], "icon": r["icon"],
                              "enabled": bool(r["enabled"]), "order": r["ord"],
                              "hidden": bool(r["hidden"]), "builtin": bool(r["builtin"])}
    except Exception as e:
        log.error(f"sections_load: {e}")
    # Мёрдж: дефолты дают структуру, сохранённые значения имеют приоритет
    result: dict = {}
    for k, v in _SECTIONS_DEFAULTS.items():
        result[k] = {**v, **saved.get(k, {})}
    # Добавляем пользовательские разделы которых нет в дефолтах
    for k, v in saved.items():
        if k not in result:
            result[k] = dict(v)
    return result

def _sect_save(d: dict):
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("DELETE FROM sections")
            for sid, cfg in d.items():
                c.execute("INSERT INTO sections VALUES (?,?,?,?,?,?,?)",
                    (sid, cfg.get("name",""), cfg.get("icon","📦"),
                     int(cfg.get("enabled",True)), cfg.get("order",99),
                     int(cfg.get("hidden",False)), int(cfg.get("builtin",False))))
            c.commit()
    except Exception as e:
        log.error(f"sections_save: {e}")

# ── Кеш погоды ────────────────────────────────────────────────────────────────
# Погода обновляется не чаще чем раз в 10 минут чтобы не спамить Open-Meteo API
_weather_cache: dict | None = None
_weather_cache_ts: float = 0.0
_WEATHER_CACHE_TTL = 600  # TTL кеша погоды: 600 сек = 10 минут

# ── Координаты для Open-Meteo ──────────────────────────────────────────────────
# Open-Meteo — бесплатный API погоды без ключей, работает по координатам
LAT, LON  = 43.31, 45.69   # Грозный (Чечня)
TIMEZONE  = "Europe/Moscow"  # Часовой пояс для отображения времени

# ── ID сущностей Home Assistant ───────────────────────────────────────────────
# Замени на реальные entity_id из своего HA (Настройки → Устройства → Объекты)
TV_EID    = "media_player.android_tv"            # Телевизор
NAMAZ_EID = "timer.namaz_obratnyi_otschet"       # Таймер намаза
SHOP_EID  = "todo.shopping_list"                 # Список покупок

# ── Кеш списка членов семьи ────────────────────────────────────────────────────
# Список person.* сущностей обновляется раз в час — они меняются редко
_family_cache: dict = {}       # {отображаемое_имя: entity_id}
_family_cache_ts: float = 0.0
_FAMILY_CACHE_TTL = 120        # TTL кеша семьи: 2 минуты (авто-обнаружение новых person.*)

# ── Логгер ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Telegram Bot и Dispatcher ──────────────────────────────────────────────────
# MemoryStorage — хранит FSM-состояния в памяти (сбрасываются при рестарте бота)
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ── FSM (конечные автоматы для многошаговых диалогов) ─────────────────────────
# FSM (Finite State Machine) — механизм aiogram для диалогов из нескольких шагов.
# Например: /ai → пользователь пишет вопрос → бот отвечает (до /exit).
# Каждый класс описывает набор состояний одного диалога.

class AIChat(StatesGroup):
    """Состояния для режима AI-чата (команда /ai).
    active — пользователь в режиме диалога с Claude AI."""
    active = State()

class ShoppingAdd(StatesGroup):
    """Состояния для добавления товара в список покупок.
    waiting — ждём текст нового товара от пользователя."""
    waiting = State()

class AddFamilyMember(StatesGroup):
    """Состояния для добавления члена семьи.
    waiting_name — ждём имя нового члена семьи."""
    waiting_name = State()

class DeviceMgmt(StatesGroup):
    """Состояния для управления устройствами.
    rename_wait — ждём новое название устройства от пользователя."""
    rename_wait = State()   # ожидаем новое имя устройства

# ── Home Assistant REST API ────────────────────────────────────────────────────
# Все функции ha_* — обёртки над HTTP запросами к HA API.
# HA_URL и HA_TOKEN берутся из .env файла.
# Документация HA REST API: https://developers.home-assistant.io/docs/api/rest/

def _ha_cs(**kw) -> aiohttp.ClientSession:
    """ClientSession с IPv4-only (Keenetic NDNS не поддерживает IPv6)."""
    connector = aiohttp.TCPConnector(family=socket.AF_INET)
    return aiohttp.ClientSession(connector=connector, **kw)

async def ha_get(path: str) -> dict | list | None:
    """Выполнить GET запрос к HA REST API.

    Используется для получения состояния сущностей, истории, логбука и т.д.

    Аргументы:
        path: путь после /api/, например "states/light.kitchen"

    Возвращает:
        Ответ HA как dict/list, или None если запрос не удался.

    Пример:
        data = await ha_get("states/sensor.temperature")
        # data = {"state": "22.5", "attributes": {...}, ...}
    """
    try:
        async with _ha_cs() as s:
            async with s.get(
                f"{HA_URL}/api/{path}", headers=HA_HEADERS,
                timeout=aiohttp.ClientTimeout(total=10), ssl=False
            ) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        log.error(f"HA GET {path}: {e}")
    return None

async def ha_post(path: str, data: dict = None) -> dict | None:
    """Выполнить POST запрос к HA REST API.

    Используется для вызова сервисов HA (включить свет, запустить автоматизацию...).

    Аргументы:
        path: путь после /api/, например "services/light/turn_on"
        data: тело запроса как словарь Python

    Возвращает:
        Ответ HA как dict, или None если запрос не удался.
    """
    try:
        async with _ha_cs() as s:
            async with s.post(
                f"{HA_URL}/api/{path}", headers=HA_HEADERS,
                json=data or {}, timeout=aiohttp.ClientTimeout(total=10), ssl=False
            ) as r:
                return await r.json()
    except Exception as e:
        log.error(f"HA POST {path}: {e}")
    return None

async def ha_state(entity_id: str) -> str:
    """Получить текущее состояние сущности HA в виде строки.

    Аргументы:
        entity_id: ID сущности, например "light.kitchen"

    Возвращает:
        Строку состояния: "on", "off", "22.5", "home", "unavailable"...
        Возвращает "?" если сущность не найдена или HA недоступен.
    """
    d = await ha_get(f"states/{entity_id}")
    return d.get("state", "?") if d else "?"

async def ha_attr(entity_id: str, attr: str, default="?"):
    """Получить значение атрибута сущности HA.

    Аргументы:
        entity_id: ID сущности, например "climate.floor_heating"
        attr: имя атрибута, например "current_temperature"
        default: что вернуть если атрибут не найден (по умолчанию "?")

    Пример:
        temp = await ha_attr("climate.floor_heating", "current_temperature", 0)
    """
    d = await ha_get(f"states/{entity_id}")
    if d:
        return d.get("attributes", {}).get(attr, default)
    return default

async def ha_call(domain: str, service: str, entity_id: str, extra: dict = None):
    """Вызвать сервис HA для управления устройством.

    Аргументы:
        domain:    домен сервиса: "light", "switch", "climate", "media_player"...
        service:   имя сервиса: "turn_on", "turn_off", "toggle"...
        entity_id: ID сущности которой управляем
        extra:     дополнительные параметры (например brightness, temperature...)

    Пример:
        await ha_call("light", "turn_on", "light.kitchen", {"brightness": 200})
        await ha_call("switch", "toggle", "switch.fan")
    """
    data = {"entity_id": entity_id, **(extra or {})}
    return await ha_post(f"services/{domain}/{service}", data)

async def ha_history(entity_id: str, hours: int = 24, max_points: int = 300) -> list:
    """Получить историю значений сущности HA для построения графика.

    Запрашивает HA History API и возвращает список точек для matplotlib.
    Данные прореживаются до max_points точек чтобы не строить график из 10000 точек.

    Аргументы:
        entity_id:  ID сущности, например "sensor.power_total"
        hours:      за сколько часов брать историю (по умолчанию 24)
        max_points: максимальное количество точек на графике (по умолчанию 300)

    Возвращает:
        Список кортежей [(datetime_в_МСК, float_значение), ...]
        Пустой список если история недоступна или сущность не числовая.
    """
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
    """Построить PNG-график на тёмном фоне с аннотациями min/max/avg.

    Используется для отправки графиков температуры, мощности, влажности в Telegram.
    Библиотека matplotlib рисует в буфер памяти (не сохраняет файл на диск).

    Аргументы:
        series: список кортежей [(datetime, float), ...] из ha_history()
        title:  заголовок графика, например "Температура детской"
        ylabel: подпись оси Y, например "°C" или "Вт"
        color:  цвет линии в hex, по умолчанию голубой "#4fc3f7"

    Возвращает:
        PNG изображение как bytes, или None если series пустой.
    """
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
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = _ssl.CERT_NONE
    try:
        async with websockets.connect(ws_url, ssl=ssl_ctx, family=socket.AF_INET) as ws:
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

# ── Авторизация и роли пользователей ──────────────────────────────────────────
# Система ролей:
#   owner  — главный администратор (ADMIN_ID из .env), полный доступ
#   admin  — администратор добавленный через /invite, полный доступ
#   viewer — только просмотр, не может управлять устройствами
#
# Проверки вызываются в начале каждого обработчика команды.

def is_admin(uid: int) -> bool:
    """Проверить: является ли пользователь главным администратором.

    Главный admin — это тот чей ADMIN_ID указан в .env файле.
    Только он может управлять другими пользователями через /users.
    """
    return uid == ADMIN_ID

def _get_user_role(uid: int) -> str:
    """Получить роль пользователя из базы данных.

    Возвращает: 'owner' | 'admin' | 'viewer' | None (если не зарегистрирован).
    """
    if uid == ADMIN_ID:
        return "owner"
    users = _load_family_users()
    info = users.get(str(uid))
    if info:
        return info.get("role", "viewer")
    return None

def is_bot_admin(uid: int) -> bool:
    """Проверить: может ли пользователь управлять устройствами.

    True для owner и admin ролей. Viewers не могут управлять.
    """
    return uid == ADMIN_ID or _get_user_role(uid) == "admin"

def is_viewer(uid: int) -> bool:
    """Проверить: пользователь имеет только роль viewer (только просмотр)."""
    return _get_user_role(uid) == "viewer"

def _load_family_users() -> dict:
    """Загрузить всех пользователей бота из SQLite.

    Возвращает словарь {telegram_id_строка: {role, name, invited_by, ...}}.
    """
    try:
        rows = _db().execute("SELECT user_id, data FROM family_users").fetchall()
        return {r["user_id"]: json.loads(r["data"]) for r in rows}
    except Exception as e:
        log.error(f"load_family_users: {e}")
    return {}

def _save_family_users(data: dict):
    """Сохранить всех пользователей бота в SQLite.

    Полностью заменяет содержимое таблицы family_users.

    Аргументы:
        data: словарь {telegram_id_строка: {role, name, ...}}
    """
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("DELETE FROM family_users")
            for uid, udata in data.items():
                c.execute("INSERT INTO family_users VALUES (?,?)",
                    (str(uid), json.dumps(udata, ensure_ascii=False)))
            c.commit()
    except Exception as e:
        log.error(f"save_family_users: {e}")

def is_family(uid: int) -> bool:
    """Проверить: зарегистрирован ли пользователь в боте (любая роль)."""
    return str(uid) in _load_family_users()

def is_allowed(uid: int) -> bool:
    """Проверить: разрешён ли доступ к боту (admin или зарегистрированный пользователь)."""
    return is_admin(uid) or is_family(uid)

def _user_name(uid: int) -> str:
    """Получить отображаемое имя пользователя бота по его Telegram ID.

    Возвращает сохранённое имя из БД, или строку с ID если пользователь не найден.
    """
    users = _load_family_users()
    return users.get(str(uid), {}).get("name", str(uid))

def family_kb() -> ReplyKeyboardMarkup:
    """Создать ограниченную клавиатуру для пользователей с ролью viewer/family.

    Viewers видят только базовые кнопки — нет управления устройствами.
    """
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👪 Семья"),  KeyboardButton(text="🌤️ Погода")],
        [KeyboardButton(text="🕌 Намаз"),  KeyboardButton(text="📊 Статус")],
    ], resize_keyboard=True)

# ── Список членов семьи — авто-обнаружение из HA ─────────────────────────────
async def get_family() -> dict:
    """Получить всех членов семьи из HA (все person.* сущности).

    Автоматически находит всех людей настроенных в HA — не нужно
    прописывать имена вручную. Результат кешируется на 1 час.

    Возвращает словарь {отображаемое_имя: entity_id}, например:
        {"Хамзат": "person.khamzat", "Айза": "person.aiza"}
    """
    global _family_cache, _family_cache_ts
    now = _time.monotonic()
    if _family_cache and now - _family_cache_ts < _FAMILY_CACHE_TTL:
        return _family_cache
    prev_keys = set(_family_cache.keys())
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
                new_keys = set(members.keys())
                _family_cache = members
                _family_cache_ts = now
                # Если состав семьи изменился — уведомить всех SSE-клиентов
                if new_keys != prev_keys:
                    log.info(f"Family members changed: {prev_keys} → {new_keys}")
                    payload = json.dumps({"type": "family_members_changed", "members": list(new_keys)}, ensure_ascii=False)
                    global _sse_clients
                    dead = set()
                    for _q in _sse_clients:
                        try: _q.put_nowait(payload)
                        except asyncio.QueueFull: dead.add(_q)
                    _sse_clients -= dead
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

# ── Журнал активности ─────────────────────────────────────────────────────────
def _activity_log(action: str, detail: str = "", username: str = ""):
    """Append event to activity_log table, keep last 200 entries."""
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("INSERT INTO activity_log (ts,action,detail,username) VALUES (?,?,?,?)",
                (datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S"), action, detail, username))
            c.execute("DELETE FROM activity_log WHERE id NOT IN "
                      "(SELECT id FROM activity_log ORDER BY id DESC LIMIT 200)")
            c.commit()
    except Exception as e:
        log.error(f"activity_log: {e}")


def _faces_log(person: str, event_id: str, camera: str):
    """Append face detection to faces_log table, keep last 200 entries."""
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("INSERT INTO faces_log (ts,person,event_id,camera) VALUES (?,?,?,?)",
                (datetime.now(MSK).isoformat(), person, event_id, camera))
            c.execute("DELETE FROM faces_log WHERE id NOT IN "
                      "(SELECT id FROM faces_log ORDER BY id DESC LIMIT 200)")
            c.commit()
    except Exception as e:
        log.error(f"faces_log: {e}")


def _validate_tg_initdata(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData HMAC. Returns parsed params or None."""
    try:
        params = dict(urlparse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = params.pop("hash", "")
        if not received_hash:
            return None
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed   = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, received_hash):
            return None
        if _time.time() - int(params.get("auth_date", 0)) > 86400:
            return None
        return params
    except Exception as e:
        log.error(f"tg_initdata: {e}")
        return None


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
        [KeyboardButton(text="💡 Свет"),     KeyboardButton(text="⚡ Энергия"),  KeyboardButton(text="🌡️ Климат")],
        [KeyboardButton(text="📺 Телевизор"),KeyboardButton(text="🤖 Пылесос"),  KeyboardButton(text="🛒 Покупки")],
        [KeyboardButton(text="🏡 Дом"),      KeyboardButton(text="👪 Семья"),    KeyboardButton(text="🌤️ Погода")],
        [KeyboardButton(text="📹 Камеры"),   KeyboardButton(text="⚙️ Автоматизации"), KeyboardButton(text="🕌 Намаз")],
        [KeyboardButton(text="📊 Статус"),   KeyboardButton(text="🛠 Устройства"), KeyboardButton(text="🧠 ИИ Ассистент")],
        [KeyboardButton(text="🖥️ Панель управления", web_app=WebAppInfo(url=WEBAPP_URL))],
    ], resize_keyboard=True)

# ── /start ────────────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    uid  = msg.from_user.id
    args = (msg.text or "").split(maxsplit=1)
    deep = args[1] if len(args) > 1 else ""

    # Handle invite deep link
    if deep.startswith("inv_"):
        code = deep[4:]
        inv  = _invite_codes.get(code)
        if inv and (_time.time() - inv["ts"]) < 86400:
            del _invite_codes[code]
            role  = inv["role"]
            fname = msg.from_user.full_name or str(uid)
            users = _load_family_users()
            users[str(uid)] = {"name": fname, "role": role, "added_ts": datetime.now().isoformat()}
            _save_family_users(users)
            _activity_log("user_joined_invite", f"{fname} [{role}]")
            kb = main_kb() if role == "admin" else family_kb()
            await msg.answer(
                f"✅ <b>Доступ получен!</b>\n"
                f"Добро пожаловать, {fname}!\nРоль: {role}",
                parse_mode="HTML", reply_markup=kb
            )
            await bot.send_message(ADMIN_ID, f"✅ {fname} (ID: {uid}) присоединился по инвайт [{role}]")
            return
        else:
            await msg.answer("❌ Ссылка недействительна или истекла.")
            return

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
        users = _load_family_users()
        info  = users.get(str(uid), {})
        name  = info.get("name", str(uid))
        role  = info.get("role", "viewer")
        kb    = main_kb() if role == "admin" else family_kb()
        await msg.answer(f"👋 Привет, {name}!", reply_markup=kb)
        return
    # Unknown user — notify admin with role selection
    uname  = f"@{msg.from_user.username}" if msg.from_user.username else "—"
    fname  = msg.from_user.full_name or str(uid)
    req_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👁️ Viewer",     callback_data=f"usr:approve:{uid}:viewer"),
        InlineKeyboardButton(text="👑 Бот-Админ",  callback_data=f"usr:approve:{uid}:admin"),
        InlineKeyboardButton(text="❌ Отклонить",  callback_data=f"usr:rej:{uid}"),
    ]])
    await bot.send_message(
        ADMIN_ID,
        f"👤 <b>Новый запрос доступа</b>\n"
        f"Имя: <b>{fname}</b>\n"
        f"Username: {uname}\n"
        f"ID: <code>{uid}</code>\n\n"
        f"<i>Viewer — только просмотр\nБот-Админ — полный доступ</i>",
        parse_mode="HTML",
        reply_markup=req_kb,
    )
    await msg.answer("⏳ Запрос отправлен администратору. Ожидайте подтверждения.")

@dp.callback_query(F.data.startswith("usr:approve:"))
async def usr_approve_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    # Format: usr:approve:{uid}:{role}
    parts = cb.data.split(":")
    uid  = int(parts[2])
    role = parts[3] if len(parts) > 3 else "viewer"

    # Try to get user's Telegram name from the request message text
    fname = str(uid)
    try:
        text = cb.message.text or ""
        for line in text.splitlines():
            if line.startswith("Имя:"):
                fname = line.replace("Имя:", "").strip()
                break
    except Exception:
        pass

    users = _load_family_users()
    users[str(uid)] = {"name": fname, "role": role, "added_ts": datetime.now().isoformat()}
    _save_family_users(users)
    _activity_log("user_approved", f"{fname} [{role}]")

    role_label = "👑 Бот-Админ" if role == "admin" else "👁️ Viewer"
    await cb.message.edit_text(
        cb.message.text + f"\n\n✅ <b>Принят как {role_label}</b>",
        parse_mode="HTML", reply_markup=None
    )
    await cb.answer(f"Добавлен как {role}")

    # Notify new user
    kb = main_kb() if role == "admin" else family_kb()
    role_desc = "полный доступ к боту" if role == "admin" else "доступ к просмотру данных дома"
    try:
        await bot.send_message(
            uid,
            f"✅ <b>Добро пожаловать, {fname}!</b>\n"
            f"Вам выдан {role_desc}.",
            parse_mode="HTML",
            reply_markup=kb,
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

def _users_text(users: dict) -> str:
    if not users:
        return "Нет пользователей."
    role_icon = {"admin": "👑", "viewer": "👁️"}
    lines = []
    for k, v in users.items():
        icon = role_icon.get(v.get("role", "viewer"), "👤")
        lines.append(f"{icon} <b>{v.get('name', k)}</b> — {v.get('role','viewer')} (ID: <code>{k}</code>)")
    return "👥 <b>Пользователи бота:</b>\n" + "\n".join(lines)

def _users_kb(users: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for fuid, info in users.items():
        name = info.get("name", fuid)
        role = info.get("role", "viewer")
        # Toggle role button
        new_role  = "admin" if role == "viewer" else "viewer"
        role_icon = "👁️→👑" if role == "viewer" else "👑→👁️"
        builder.button(text=f"{role_icon} {name}", callback_data=f"usr:role:{fuid}:{new_role}")
        builder.button(text="❌", callback_data=f"usr:del:{fuid}")
    builder.adjust(2)
    return builder.as_markup()

@dp.message(Command("users"))
async def cmd_users(msg: Message):
    if not is_admin(msg.from_user.id): return
    users = _load_family_users()
    await msg.answer(
        _users_text(users) + "\n\n<i>Кнопка 👁️→👑 / 👑→👁️ меняет роль\n❌ — удалить</i>",
        parse_mode="HTML",
        reply_markup=_users_kb(users) if users else None
    )

@dp.callback_query(F.data.startswith("usr:role:"))
async def usr_role_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    parts    = cb.data.split(":")
    fuid     = parts[2]
    new_role = parts[3]
    users    = _load_family_users()
    if fuid in users:
        old_role = users[fuid].get("role", "viewer")
        users[fuid]["role"] = new_role
        _save_family_users(users)
        name = users[fuid].get("name", fuid)
        _activity_log("user_role_changed", f"{name}: {old_role}→{new_role}")
        await cb.answer(f"Роль изменена: {new_role}")
        # Notify user of role change
        kb = main_kb() if new_role == "admin" else family_kb()
        try:
            await bot.send_message(
                int(fuid),
                f"🔄 Ваша роль изменена: <b>{new_role}</b>",
                parse_mode="HTML", reply_markup=kb
            )
        except Exception:
            pass
    await cb.message.edit_text(
        _users_text(users) + "\n\n<i>Кнопка 👁️→👑 / 👑→👁️ меняет роль\n❌ — удалить</i>",
        parse_mode="HTML", reply_markup=_users_kb(users)
    )

# ── /invite — одноразовая ссылка ──────────────────────────────────────────────
import secrets as _secrets
_invite_codes: dict = {}  # {code: {"role": "viewer"|"admin", "ts": float}}

@dp.message(Command("invite"))
async def cmd_invite(msg: Message):
    if not is_admin(msg.from_user.id): return
    parts = (msg.text or "").split()
    role  = "viewer"
    if len(parts) > 1 and parts[1] in ("viewer", "admin"):
        role = parts[1]
    code = _secrets.token_urlsafe(8)
    _invite_codes[code] = {"role": role, "ts": _time.time()}
    # Get bot username for link
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=inv_{code}"
    await msg.answer(
        f"🔗 <b>Ссылка-приглашение [{role}]</b>\n"
        f"Действует 24 часа:\n\n<code>{link}</code>\n\n"
        "Отправь эту ссылку пользователю.",
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("usr:del:"))
async def usr_del_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    fuid  = cb.data.split(":")[2]
    users = _load_family_users()
    info  = users.pop(fuid, {})
    name  = info.get("name", fuid)
    _save_family_users(users)
    _activity_log("user_deleted", name)
    await cb.answer(f"Удалён: {name}")
    try:
        await bot.send_message(int(fuid), "❌ Ваш доступ к боту отозван.")
    except Exception:
        pass
    await cb.message.edit_text(
        _users_text(users) + ("\n\n<i>Кнопка 👁️→👑 / 👑→👁️ меняет роль\n❌ — удалить</i>" if users else ""),
        parse_mode="HTML",
        reply_markup=_users_kb(users) if users else None
    )

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
    "light.svet_krovat":           {"name": "Кровать",        "icon": "🛏️", "section": "lights",   "enabled": True,  "order": 1},
    "switch.vykliuchatel_kukhnia": {"name": "Кухня",          "icon": "🍳", "section": "lights",   "enabled": True,  "order": 2},
    "switch.kabinet_svet_pk_left": {"name": "ПК Левый",       "icon": "🖥️", "section": "lights",   "enabled": True,  "order": 3},
    "switch.kabinet_svet_pk_right":{"name": "ПК Правый",      "icon": "🖥️", "section": "lights",   "enabled": True,  "order": 4},
    "switch.sonoff_100093f84f":    {"name": "Люстра Детская", "icon": "💡", "section": "lights",   "enabled": True,  "order": 5},
    "switch.sonoff_1000a60930":    {"name": "Шкаф",           "icon": "🚪", "section": "lights",   "enabled": True,  "order": 6},
    # Frigate cameras
    "camera.cam_a6810678":                        {"name": "Камера лофт", "icon": "📹", "section": "cameras", "enabled": True, "order": 10},
    "switch.cam_a6810678_detect":                 {"name": "Детекция",   "icon": "🔍", "section": "cameras", "enabled": True, "order": 11},
    "switch.cam_a6810678_recordings":             {"name": "Запись",     "icon": "🎬", "section": "cameras", "enabled": True, "order": 12},
    "switch.cam_a6810678_snapshots":              {"name": "Снимки",     "icon": "📸", "section": "cameras", "enabled": True, "order": 13},
    "sensor.cam_a6810678_person_count":           {"name": "Людей",     "icon": "👤", "section": "cameras", "enabled": True, "order": 14},
    "sensor.cam_a6810678_all_count":              {"name": "Объектов",  "icon": "📦", "section": "cameras", "enabled": True, "order": 15},
}

LIGHTS: dict      = {}  # {display_name: (domain, entity_id)} — пересобирается из devices.json
LIGHTS_ICON: dict = {}  # {entity_id: icon}                   — пересобирается из devices.json

# ── devices.json helpers ──────────────────────────────────────────────────────

def _dev_load() -> dict:
    """Загрузить устройства из SQLite → dict {entity_id: {name,icon,section,enabled,order}}."""
    try:
        rows = _db().execute("SELECT entity_id,name,icon,section,enabled,ord FROM devices").fetchall()
        return {r["entity_id"]: {"name": r["name"], "icon": r["icon"],
                                  "section": r["section"], "enabled": bool(r["enabled"]),
                                  "order": r["ord"]} for r in rows}
    except Exception as e:
        log.error(f"devices_load: {e}")
    return {}

def _dev_save(d: dict):
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("DELETE FROM devices")
            for eid, cfg in d.items():
                c.execute("INSERT INTO devices VALUES (?,?,?,?,?,?)",
                    (eid, cfg.get("name",""), cfg.get("icon","📦"),
                     cfg.get("section","lights"), int(cfg.get("enabled",True)),
                     cfg.get("order",99)))
            c.commit()
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
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
    states = {e: await ha_state(e) for _, (_, e) in LIGHTS.items()}
    await msg.answer("💡 <b>Управление светом</b>", parse_mode="HTML",
                     reply_markup=lights_kb(states))

@dp.callback_query(F.data.startswith("lt:"))
async def light_toggle(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
    action = cb.data.split(":")[1]
    for _, (domain, eid) in LIGHTS.items():
        await ha_call(domain, f"turn_{action}", eid)
    await cb.answer("💡 Весь свет включён" if action == "on" else "🌑 Весь свет выключен")
    await asyncio.sleep(1)
    states = {e: await ha_state(e) for _, (_, e) in LIGHTS.items()}
    await cb.message.edit_reply_markup(reply_markup=lights_kb(states))

@dp.callback_query(F.data == "lights_refresh")
async def lights_refresh(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
    text = await build_climate_text()
    await msg.answer(text, parse_mode="HTML", reply_markup=_climate_kb())

@dp.callback_query(F.data.in_({"floor_on", "floor_off", "climate_refresh"}))
async def climate_basic(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
async def _ha_kwh_since(start_dt) -> float | None:
    """Compute kWh from dom_energiia_vsego since start_dt (aware datetime in any tz)."""
    try:
        start = start_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
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
        log.warning(f"_ha_kwh_since error: {e}")
        return None

async def _ha_today_kwh() -> float | None:
    """kWh за сегодня (с полуночи МСК)."""
    now_msk = datetime.now(MSK)
    return await _ha_kwh_since(now_msk.replace(hour=0, minute=0, second=0, microsecond=0))

async def _ha_week_kwh() -> float | None:
    """kWh за последние 7 дней."""
    from datetime import timedelta
    now_msk = datetime.now(MSK)
    week_ago = (now_msk - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    return await _ha_kwh_since(week_ago)

async def _ha_month_kwh() -> float | None:
    """kWh с 1-го числа текущего месяца (МСК)."""
    now_msk = datetime.now(MSK)
    month_start = now_msk.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return await _ha_kwh_since(month_start)

async def build_energy_text() -> str:
    import calendar as _cal
    (power, v1, v2, v3, tariff_s), (kwh_today, kwh_month) = await asyncio.gather(
        asyncio.gather(
            ha_state("sensor.moshchnost_vsego_doma"),
            ha_state("sensor.vvod_1_moshchnost"),
            ha_state("sensor.vvod_2_moshchnost"),
            ha_state("sensor.vvod_3_moshchnost"),
            ha_state("input_number.tarif_den_kvt_ch"),
        ),
        asyncio.gather(_ha_today_kwh(), _ha_month_kwh()),
    )
    power_alert = ""
    try:
        if float(power) > 3000:
            power_alert = " ⚠️"
    except Exception:
        pass
    try:
        tariff = max(float(tariff_s), 0.5)
    except Exception:
        tariff = 5.5

    day   = f"{kwh_today * tariff:.2f}" if kwh_today else "—"
    month = f"{kwh_month * tariff:.0f}" if kwh_month else "—"
    forecast = "—"
    try:
        now_msk   = datetime.now(MSK)
        day_num   = now_msk.day
        days_in_m = _cal.monthrange(now_msk.year, now_msk.month)[1]
        if kwh_month and day_num > 0:
            forecast = f"{kwh_month / day_num * days_in_m * tariff:.0f}"
    except Exception:
        pass

    return (
        f"⚡ <b>Энергия</b>\n\n"
        f"🏠 Общая мощность: <b>{power} Вт{power_alert}</b>\n"
        f"  ├ Ввод 1: {v1} Вт\n"
        f"  ├ Ввод 2: {v2} Вт\n"
        f"  └ Ввод 3: {v3} Вт\n\n"
        f"💰 Сегодня: <b>{day} ₽</b>  ({round(kwh_today,2) if kwh_today else '—'} кВт⋅ч)\n"
        f"💰 Месяц:   {month} ₽  ({round(kwh_month,1) if kwh_month else '—'} кВт⋅ч)\n"
        f"📈 Прогноз: {forecast} ₽  (тариф {tariff} ₽/кВт⋅ч)"
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
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
    text = await build_energy_text()
    await msg.answer(text, parse_mode="HTML", reply_markup=_energy_kb())

@dp.callback_query(F.data == "energy_refresh")
async def energy_refresh(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
    await cb.answer("Обновляю...")
    text = await build_energy_text()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_energy_kb())

@dp.callback_query(F.data.startswith("energy_chart:"))
async def energy_chart_cb(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
    d     = await ha_get(f"states/{TV_EID}")
    state = d.get("state", "off") if d else "off"
    text  = await build_tv_text()
    await msg.answer(text, parse_mode="HTML", reply_markup=tv_kb(state))

@dp.callback_query(F.data.startswith("tv:"))
async def tv_action(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
    items = await ha_ws_get_todo_items(SHOP_EID)
    text  = await build_shopping_text(items)
    await msg.answer(text, parse_mode="HTML", reply_markup=_shop_kb(items))

@dp.callback_query(F.data == "shop:refresh")
async def shop_refresh(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
    await cb.answer("Обновляю...")
    items = await ha_ws_get_todo_items(SHOP_EID)
    text  = await build_shopping_text(items)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_shop_kb(items))

@dp.callback_query(F.data == "shop:add")
async def shop_add_start(cb: CallbackQuery, state: FSMContext):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
    await state.set_state(ShoppingAdd.waiting)
    await cb.answer()
    await cb.message.answer(
        "🛒 Введи название товара:\n<i>(или /cancel для отмены)</i>",
        parse_mode="HTML"
    )

@dp.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    if not is_allowed(msg.from_user.id): return
    current = await state.get_state()
    await state.clear()
    if current:
        await msg.answer("❌ Отменено", reply_markup=main_kb())
    else:
        await msg.answer("🏠 Главное меню", reply_markup=main_kb())

@dp.message(StateFilter(ShoppingAdd.waiting))
async def shop_add_item(msg: Message, state: FSMContext):
    if not is_bot_admin(msg.from_user.id): return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
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
_LABEL_MAP = {"person": "👤 Человек", "car": "🚗 Авто", "dog": "🐕 Собака", "cat": "🐱 Кот", "face": "😶 Лицо"}

def _cameras_kb(event_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    evt_label = f"📋 События детекции ({event_count})" if event_count else "📋 Нет событий"
    builder.button(text=evt_label,            callback_data="fri:events:0")
    builder.button(text="🔄 Обновить",        callback_data="fri:refresh")
    builder.button(text="📹 HA Камеры",       url=f"{HA_URL}/lovelace/cameras")
    builder.button(text="🎞 Frigate",          url=f"{HA_URL}/ccab4aaf_frigate-fa")
    builder.adjust(2)
    return builder.as_markup()

@dp.message(F.text == "📹 Камеры")
async def cameras_menu(msg: Message):
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
    evts = list(reversed(_frigate_events[-20:]))
    await msg.answer(
        "📹 <b>Камеры</b>\n\n"
        f"🎥 Лофт · cam_a6810678\n"
        f"📦 Событий в кеше: <b>{len(_frigate_events)}</b>\n\n"
        "<i>Нажми «События детекции» чтобы увидеть список</i>",
        parse_mode="HTML",
        reply_markup=_cameras_kb(len(_frigate_events)),
        disable_web_page_preview=True
    )

@dp.callback_query(F.data == "fri:refresh")
async def fri_refresh(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
    await cb.message.edit_text(
        "📹 <b>Камеры</b>\n\n"
        f"🎥 Лофт · cam_a6810678\n"
        f"📦 Событий в кеше: <b>{len(_frigate_events)}</b>\n\n"
        "<i>Нажми «События детекции» чтобы увидеть список</i>",
        parse_mode="HTML",
        reply_markup=_cameras_kb(len(_frigate_events)),
    )
    await cb.answer("Обновлено")

@dp.callback_query(F.data.startswith("fri:events:"))
async def fri_events(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
    page = int(cb.data.split(":")[2])
    per_page = 8
    evts = list(reversed(_frigate_events))  # newest first
    total = len(evts)
    if not evts:
        await cb.answer("Нет событий")
        await cb.message.edit_text("📹 <b>Нет событий детекции</b>", parse_mode="HTML",
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                        InlineKeyboardButton(text="◀️ Назад", callback_data="fri:back")
                                    ]]))
        return
    chunk = evts[page * per_page:(page + 1) * per_page]
    lines = []
    builder = InlineKeyboardBuilder()
    for i, e in enumerate(chunk):
        label   = _LABEL_MAP.get(e.get("label",""), f"📦 {e.get('label','')}")
        camera  = e.get("camera","?")
        score   = e.get("score", 0)
        ts_str  = datetime.fromtimestamp(e.get("ts", 0), tz=MSK).strftime("%d.%m %H:%M")
        eid     = e.get("id","")
        lines.append(f"{label} · <b>{score}%</b> · {camera[:12]} · {ts_str}")
        if eid:
            builder.button(text=f"📸 #{page*per_page+i+1}", callback_data=f"fri:snap:{eid[:50]}")
    builder.adjust(4)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Пред", callback_data=f"fri:events:{page-1}"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton(text="След ▶️", callback_data=f"fri:events:{page+1}"))
    nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data="fri:back"))
    if nav:
        builder.row(*nav)
    text = (f"📋 <b>События детекции</b> (стр. {page+1}, всего {total})\n\n"
            + "\n".join(lines)
            + "\n\n<i>📸 — снимок конкретного события</i>")
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await cb.answer()

@dp.callback_query(F.data.startswith("fri:snap:"))
async def fri_snap(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
    eid_prefix = cb.data[len("fri:snap:"):]
    # Find event by ID prefix
    entry = next((e for e in _frigate_events if e.get("id","").startswith(eid_prefix)), None)
    if not entry:
        await cb.answer("❌ Событие не найдено"); return
    snap_url = entry.get("snapshot_url","")
    label    = _LABEL_MAP.get(entry.get("label",""), entry.get("label","?"))
    camera   = entry.get("camera","?")
    score    = entry.get("score", 0)
    ts_str   = datetime.fromtimestamp(entry.get("ts", 0), tz=MSK).strftime("%d.%m.%Y %H:%M:%S")
    caption  = f"📸 <b>Детекция Frigate</b>\n{label} · {score}%\n📷 {camera}\n🕐 {ts_str}"
    # Also offer clip button via existing /send endpoint
    eid_full = entry.get("id","")
    clip_kb  = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎬 Скачать клип", callback_data=f"fri:clip:{eid_full[:50]}")
    ]]) if eid_full else None
    if snap_url:
        try:
            async with _ha_cs() as sess:
                async with sess.get(snap_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await cb.message.answer_photo(
                            BufferedInputFile(data, "snap.jpg"),
                            caption=caption, parse_mode="HTML", reply_markup=clip_kb
                        )
                        await cb.answer()
                        return
        except Exception as e:
            log.warning(f"fri_snap download: {e}")
    await cb.message.answer(caption, parse_mode="HTML", reply_markup=clip_kb)
    await cb.answer()

@dp.callback_query(F.data.startswith("fri:clip:"))
async def fri_clip(cb: CallbackQuery):
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
    eid_prefix = cb.data[len("fri:clip:"):]
    entry = next((e for e in _frigate_events if e.get("id","").startswith(eid_prefix)), None)
    if not entry:
        await cb.answer("❌ Событие не найдено"); return
    eid_full = entry.get("id","")
    clip_url = f"{HA_URL}/api/frigate/notifications/{eid_full}/clip.mp4"
    await cb.answer("🎬 Скачиваю клип...")
    try:
        async with _ha_cs() as sess:
            async with sess.get(clip_url, headers=HA_HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    camera  = entry.get("camera","cam")
                    label   = _LABEL_MAP.get(entry.get("label",""), entry.get("label",""))
                    ts_str  = datetime.fromtimestamp(entry.get("ts", 0), tz=MSK).strftime("%d.%m %H:%M")
                    await cb.message.answer_video(
                        BufferedInputFile(data, f"clip_{eid_full[:8]}.mp4"),
                        caption=f"🎬 {label} · {camera} · {ts_str}", parse_mode="HTML"
                    )
                    return
        await cb.message.answer("❌ Не удалось скачать клип (возможно слишком старое)")
    except Exception as e:
        await cb.message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data == "fri:back")
async def fri_back(cb: CallbackQuery):
    await cb.message.edit_text(
        "📹 <b>Камеры</b>\n\n"
        f"🎥 Лофт · cam_a6810678\n"
        f"📦 Событий в кеше: <b>{len(_frigate_events)}</b>\n\n"
        "<i>Нажми «События детекции» чтобы увидеть список</i>",
        parse_mode="HTML",
        reply_markup=_cameras_kb(len(_frigate_events)),
    )
    await cb.answer()

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
    if not is_bot_admin(msg.from_user.id):
        if is_allowed(msg.from_user.id): await msg.answer("🚫 Только просмотр")
        return
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
    if not is_bot_admin(cb.from_user.id):
        await cb.answer("🚫 Только просмотр", show_alert=True); return
    await state.clear()
    await cb.message.edit_text("✅ Вышел из режима ИИ")
    await cb.message.answer("🏠 Главное меню:", reply_markup=main_kb())
    await cb.answer()

@dp.message(StateFilter(AIChat.active))
async def ai_chat(msg: Message, state: FSMContext):
    if not is_bot_admin(msg.from_user.id): return
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
    "person_khamzat":          None,   # kept for compat
    "person_khamzat_notif_ts": None,
    "persons":                 {},     # {entity_id: state} для всех членов семьи
    "namaz_notified_prayer":   None,   # kept for compat
    "namaz_done_keys":         set(),  # {"2026-03-09_Asr_15", ...} — отправленные уведомления
    "namaz_done_day":          None,   # дата для сброса namaz_done_keys
    "last_briefing_day":       None,
    "last_weekly_report":      None,   # "week_10_2026"
    "last_monthly_report":     None,   # "2026-03"
    "all_away":                False,  # все ушли из дома
    "all_away_notif_ts":       None,
    "inet_down":               False,
    "inet_down_ts":            None,   # datetime UTC когда интернет упал
    "last_recognized_face":    None,   # последнее распознанное лицо
    "person_img_ts":           None,   # последний timestamp image.cam_a6810678_person
}

async def alert_loop():
    """Фоновая задача: проверка алертов каждую минуту.

    Запускается при старте бота через asyncio.create_task().
    Первые 10 секунд ждёт — даёт боту полностью инициализироваться.
    После этого каждые 60 секунд вызывает _check_alerts().

    Все алерты настраиваются через Mini App → раздел "Алерты",
    или через /ha-app/api/alerts.
    """
    await asyncio.sleep(10)   # Ждём инициализацию бота
    while True:
        try:
            await _check_alerts()
        except Exception as e:
            log.error(f"Alert loop error: {e}")
        await asyncio.sleep(60)   # Проверяем каждую минуту

async def _check_alerts():
    """Проверить все условия алертов и отправить уведомления при необходимости.

    Запрашивает все нужные сущности из HA за один раз (asyncio.gather),
    затем проверяет каждое условие. Использует _alert_state для дедупликации
    — чтобы один и тот же алерт не приходил каждую минуту.

    Типы алертов (настраиваются в alerts_config):
      - power:   мощность > порога (Вт)
      - temp:    температура вне диапазона (°C)
      - person:  Frigate обнаружил человека
      - namaz:   напоминание о молитве (15 мин и 5 мин)
      - morning: утренняя сводка в 7:30 МСК
      - inet:    падение/восстановление интернета
      - frigate: любое событие детекции Frigate
    """
    family = await get_family()  # {name: entity_id}
    person_eids = list(family.values()) or ["person.khamzat"]
    gather_items = [
        ha_get("states/sensor.moshchnost_vsego_doma"),
        ha_get("states/sensor.temp_detskaia_temperature"),
        ha_get("states/person.khamzat"),
        ha_get("states/binary_sensor.keenetic_gateway_wan_status_2"),
        ha_get("states/image.cam_a6810678_person"),
        *[ha_get(f"states/{eid}") for eid in person_eids],
    ]
    results = await asyncio.gather(*gather_items)
    power_d     = results[0]
    temp_d      = results[1]
    person_d    = results[2]
    inet_d      = results[3]
    person_img_d = results[4]
    all_persons = results[5:]  # parallel to person_eids

    acfg = _alerts_load()
    now_h = datetime.now(MSK).hour
    # Quiet hours check
    qs, qe = acfg["quiet_hours_start"], acfg["quiet_hours_end"]
    in_quiet = (qs > qe and (now_h >= qs or now_h < qe)) or (qs < qe and qs <= now_h < qe)

    # ⚡ Высокая мощность
    if acfg["enabled"].get("power", True) and not in_quiet:
        try:
            power = float(power_d.get("state", 0)) if power_d else 0
            thr = acfg["power_threshold"]
            if power > thr and not _alert_state["power_high"]:
                _alert_state["power_high"] = True
                await bot.send_message(ADMIN_ID, f"⚡ <b>Высокая нагрузка!</b> {power:.0f} Вт (порог {thr} Вт)", parse_mode="HTML")
            elif power <= thr and _alert_state["power_high"]:
                _alert_state["power_high"] = False
        except Exception as e:
            log.error(f"Alert power check: {e}")

    # 🌡️ Температура детской
    if acfg["enabled"].get("temp", True):
        try:
            temp = float(temp_d.get("state", 20)) if temp_d else 20
            t_min, t_max = acfg["temp_min"], acfg["temp_max"]
            if temp < t_min and not _alert_state["temp_low"]:
                _alert_state["temp_low"] = True
                await bot.send_message(ADMIN_ID, f"🥶 <b>Холодно в детской!</b> {temp}°C (мин {t_min}°C)", parse_mode="HTML")
            elif temp >= t_min:
                _alert_state["temp_low"] = False
            if temp > t_max and not _alert_state["temp_high"]:
                _alert_state["temp_high"] = True
                await bot.send_message(ADMIN_ID, f"🥵 <b>Жарко в детской!</b> {temp}°C (макс {t_max}°C)", parse_mode="HTML")
            elif temp <= t_max:
                _alert_state["temp_high"] = False
        except Exception as e:
            log.error(f"Alert temp check: {e}")

    # 🏠 Приход/уход всех членов семьи
    if acfg["enabled"].get("person", True):
        try:
            now_utc = datetime.now(timezone.utc)
            family_names = {v: k for k, v in family.items()}  # {entity_id: name}
            for eid, d in zip(person_eids, all_persons):
                state = d.get("state", "?") if d else "?"
                prev  = _alert_state["persons"].get(eid)
                if prev is not None and prev != state:
                    name = family_names.get(eid, eid.split(".")[-1].capitalize())
                    if state == "home":
                        await bot.send_message(ADMIN_ID, f"🏠 <b>{name}</b> дома!", parse_mode="HTML")
                        _activity_log("person_home", name)
                    elif prev == "home":
                        await bot.send_message(ADMIN_ID, f"🚗 <b>{name}</b> ушёл(а)", parse_mode="HTML")
                        _activity_log("person_away", name)
                _alert_state["persons"][eid] = state
            # backwards compat
            _alert_state["person_khamzat"] = _alert_state["persons"].get("person.khamzat",
                person_d.get("state", "?") if person_d else "?")
        except Exception as e:
            log.error(f"Alert person check: {e}")

    # 🏠 Geofencing — все ушли / первый вернулся
    if acfg["enabled"].get("person", True):
        try:
            family_names_geo = {v: k for k, v in family.items()}
            person_states = [d.get("state", "?") if d else "?" for d in all_persons]
            anyone_home = any(s == "home" for s in person_states)
            prev_all_away = _alert_state["all_away"]
            if not anyone_home and not prev_all_away:
                # Everyone just left
                _alert_state["all_away"] = True
                last_ts = _alert_state["all_away_notif_ts"]
                now_utc = datetime.now(timezone.utc)
                cooldown_ok = last_ts is None or (now_utc - last_ts).total_seconds() > 1800
                if cooldown_ok:
                    _alert_state["all_away_notif_ts"] = now_utc
                    away_kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🚗 Режим Уходим", callback_data="scene:run:away")
                    ]])
                    cap = "🏃 <b>Все ушли из дома!</b>"
                    try:
                        img_d = await ha_get("states/image.cam_a6810678_person")
                        if img_d:
                            tok = img_d.get("attributes", {}).get("access_token", "")
                            snap_url = f"{HA_URL}/api/image_proxy/image.cam_a6810678_person?token={tok}"
                            async with _ha_cs() as sess:
                                async with sess.get(snap_url, headers=HA_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as r:
                                    if r.status == 200:
                                        img_bytes = await r.read()
                                        await bot.send_photo(ADMIN_ID, BufferedInputFile(img_bytes, "geofence.jpg"),
                                                             caption=cap, parse_mode="HTML", reply_markup=away_kb)
                                        _activity_log("geofence_all_away", "snapshot sent")
                                        return
                    except Exception:
                        pass
                    await bot.send_message(ADMIN_ID, cap, parse_mode="HTML", reply_markup=away_kb)
                    _activity_log("geofence_all_away", "text only")
            elif anyone_home and prev_all_away:
                _alert_state["all_away"] = False
                # Кто первый вернулся?
                first_home = next(
                    (family_names_geo.get(eid, eid.split(".")[-1].capitalize())
                     for eid, s in zip(person_eids, person_states) if s == "home"),
                    None
                )
                if first_home:
                    home_kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="💡 Режим Вечер", callback_data="scene:run:evening")
                    ]])
                    await bot.send_message(ADMIN_ID,
                        f"🏠 <b>{first_home}</b> дома!\nВключить сцену?",
                        parse_mode="HTML", reply_markup=home_kb)
                    _activity_log("geofence_first_home", first_home)
        except Exception as e:
            log.error(f"Alert geofence check: {e}")

    # 🌐 Интернет — падение/восстановление
    if acfg["enabled"].get("inet", True):
        try:
            inet_state = inet_d.get("state", "unknown") if inet_d else "unknown"
            prev_inet = _alert_state["inet_down"]
            if inet_state in ("off", "unavailable") and not prev_inet:
                _alert_state["inet_down"] = True
                _alert_state["inet_down_ts"] = datetime.now(timezone.utc)
                now_msk_str = datetime.now(MSK).strftime("%H:%M")
                await bot.send_message(ADMIN_ID,
                    f"🔴 <b>Интернет упал!</b>\n⏰ {now_msk_str}",
                    parse_mode="HTML")
                _activity_log("inet_down", now_msk_str)
            elif inet_state == "on" and prev_inet:
                _alert_state["inet_down"] = False
                down_ts = _alert_state["inet_down_ts"]
                if down_ts:
                    secs = int((datetime.now(timezone.utc) - down_ts).total_seconds())
                    if secs < 60:
                        dur_str = f"{secs}с"
                    elif secs < 3600:
                        dur_str = f"{secs // 60}м {secs % 60:02d}с"
                    else:
                        dur_str = f"{secs // 3600}ч {(secs % 3600) // 60}м"
                    await bot.send_message(ADMIN_ID,
                        f"🟢 <b>Интернет восстановлен!</b>\n⏱ Простой: {dur_str}",
                        parse_mode="HTML")
                    _activity_log("inet_up", dur_str)
                else:
                    await bot.send_message(ADMIN_ID, "🟢 <b>Интернет восстановлен!</b>", parse_mode="HTML")
                _alert_state["inet_down_ts"] = None
        except Exception as e:
            log.error(f"Alert inet check: {e}")

    # 👤 Детекция человека камерой (через image entity)
    if acfg["enabled"].get("camera", True) and not in_quiet:
        try:
            img_ts = person_img_d.get("state", "") if person_img_d else ""
            prev_ts = _alert_state["person_img_ts"]
            if img_ts and img_ts not in ("unavailable", "unknown", "") and img_ts != prev_ts:
                _alert_state["person_img_ts"] = img_ts
                if prev_ts is not None:  # skip initial state on startup
                    img_tok = (person_img_d.get("attributes", {}).get("access_token", "")
                               if person_img_d else "")
                    img_url = f"{HA_URL}/api/image_proxy/image.cam_a6810678_person?token={img_tok}" if img_tok else ""
                    caption = "📷 <b>Человек у камеры!</b>\nОбнаружено Frigate."
                    sent = False
                    if img_url:
                        try:
                            async with _ha_cs() as sess:
                                async with sess.get(img_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                                    if resp.status == 200:
                                        data = await resp.read()
                                        await bot.send_photo(ADMIN_ID,
                                            BufferedInputFile(data, "person.jpg"),
                                            caption=caption, parse_mode="HTML")
                                        sent = True
                        except Exception as img_err:
                            log.warning(f"Person detect photo: {img_err}")
                    if not sent:
                        await bot.send_message(ADMIN_ID, caption, parse_mode="HTML")
                    _activity_log("person_detected", "cam_a6810678")
                else:
                    _alert_state["person_img_ts"] = img_ts
        except Exception as e:
            log.error(f"Alert person detect check: {e}")

    # 📸 Распознавание лиц — только через webhook /frigate/person-identified от HA автоматизации

    # 🕌 Намаз — уведомление за 15 мин (с кнопкой) и за 5 мин (финальное)
    try:
        now_msk = datetime.now(MSK)
        # Сброс ключей уведомлений в новый день
        today_str = now_msk.date().isoformat()
        if _alert_state["namaz_done_day"] != today_str:
            _alert_state["namaz_done_day"] = today_str
            _alert_state["namaz_done_keys"] = set()
        timings = await get_prayer_times() if acfg["enabled"].get("namaz", True) else None
        timings = timings or {}
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
                icon, ru_name = PRAYERS_RU[p_name]
                # 15-минутное предупреждение (от 6 до 15 минут)
                if 5 < diff_min <= 15:
                    key15 = f"{today_str}_{p_name}_15"
                    if key15 not in _alert_state["namaz_done_keys"]:
                        _alert_state["namaz_done_keys"].add(key15)
                        kb = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="✅ Понял", callback_data=f"namaz_ok:{p_name}"),
                        ]])
                        await bot.send_message(
                            ADMIN_ID,
                            f"🕌 <b>Через {diff_min} мин — {ru_name}!</b>\n"
                            f"{icon} Время намаза: <b>{p_time_str}</b>",
                            parse_mode="HTML", reply_markup=kb
                        )
                    break
                # 5-минутное финальное предупреждение
                elif 0 < diff_min <= 5:
                    key5 = f"{today_str}_{p_name}_5"
                    if key5 not in _alert_state["namaz_done_keys"]:
                        _alert_state["namaz_done_keys"].add(key5)
                        await bot.send_message(
                            ADMIN_ID,
                            f"⏰ <b>Через {diff_min} мин — {ru_name}!</b>\n"
                            f"{icon} Пора на намаз!",
                            parse_mode="HTML"
                        )
                    break
    except Exception as e:
        log.error(f"Alert namaz check: {e}")

    # 🌅 Утренняя сводка в 07:30 МСК
    now = datetime.now(MSK)
    if acfg["enabled"].get("morning", True) and now.hour == 7 and 28 <= now.minute <= 32:
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

    # 📅 Ежемесячный отчёт — 1-е число месяца 09:00 МСК
    if now.day == 1 and now.hour == 9 and now.minute < 1:
        month_key = now.strftime("%Y-%m")
        if _alert_state["last_monthly_report"] != month_key:
            _alert_state["last_monthly_report"] = month_key
            await _send_monthly_report()

async def _send_morning_briefing():
    """Отправить утреннюю сводку в 07:30 МСК.

    Содержит: дату, погоду, кто дома, намаз, потребление энергии.
    Вызывается из _check_alerts() при совпадении времени.
    Дедупликация через _alert_state["morning_done_date"] — отправляется
    только один раз в день, даже если alert_loop сработал несколько раз.
    """
    try:
        now_msk = datetime.now(MSK)
        date_str = now_msk.strftime("%d.%m.%Y")
        day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        day_ru = day_names[now_msk.weekday()]

        # Погода
        weather_data = await get_weather()
        weather_line = ""
        if weather_data:
            c    = weather_data.get("current", {})
            daily = weather_data.get("daily", {})
            code = c.get("weather_code", 0)
            cond = WMO_CODES.get(code, "").split()[0] if WMO_CODES.get(code) else ""
            temp = c.get("temperature_2m", "?")
            t_max = daily.get("temperature_2m_max", [None])[0]
            t_min = daily.get("temperature_2m_min", [None])[0]
            if t_max is not None and t_min is not None:
                weather_line = f"\n🌤️ Погода: {cond} <b>{temp}°C</b> (сегодня {t_min:.0f}…{t_max:.0f}°C)"
            else:
                weather_line = f"\n🌤️ Погода: {cond} <b>{temp}°C</b>"

        # Расписание намаза
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

        # Кто дома
        family = await get_family()
        home_line = ""
        if family:
            try:
                person_results = await asyncio.gather(*[ha_get(f"states/{eid}") for eid in family.values()])
                home_list, away_list = [], []
                for name, d in zip(family.keys(), person_results):
                    if d and d.get("state") == "home":
                        home_list.append(name)
                    else:
                        away_list.append(name)
                if home_list:
                    home_line = f"\n🏠 Дома: <b>{', '.join(home_list)}</b>"
                elif away_list:
                    home_line = f"\n🏠 Все ушли"
            except Exception:
                pass

        # Расход за вчера
        energy_line = ""
        try:
            cost_month = await ha_state("sensor.elektroenergiia_stoimost_za_mesiats")
            cost_prog  = await ha_state("sensor.elektroenergiia_prognoz_scheta_za_mesiats")
            day_num = now_msk.day
            if day_num > 1 and cost_month:
                try:
                    avg_day = float(cost_month) / max(day_num - 1, 1)
                    energy_line = f"\n⚡ Накоплено: <b>{float(cost_month):.0f} ₽</b> (~{avg_day:.0f} ₽/день)"
                    if cost_prog:
                        energy_line += f", прогноз: <b>{float(cost_prog):.0f} ₽</b>"
                except Exception:
                    pass
        except Exception:
            pass

        await bot.send_message(
            ADMIN_ID,
            f"🌅 <b>Доброе утро!</b> {day_ru}, {date_str}"
            f"{weather_line}"
            f"{home_line}"
            f"{energy_line}"
            f"{prayer_line}",
            parse_mode="HTML"
        )
        _activity_log("morning_briefing", date_str)
    except Exception as e:
        log.error(f"Morning briefing error: {e}")

async def _send_weekly_report():
    """Отправить еженедельный отчёт по энергопотреблению (каждый понедельник).

    Показывает: стоимость за день, за месяц, прогноз до конца месяца,
    предполагаемый расход за неделю.
    Вызывается из _check_alerts() по понедельникам в 08:00 МСК.
    """
    try:
        now = datetime.now(MSK)
        week_num = now.isocalendar().week
        day_d, month_d, prog_d = await asyncio.gather(
            ha_state("sensor.elektroenergiia_stoimost_za_den"),
            ha_state("sensor.elektroenergiia_stoimost_za_mesiats"),
            ha_state("sensor.elektroenergiia_prognoz_scheta_za_mesiats"),
        )
        # Fix: if stoimost_za_den stuck at 0, calculate from kWh history
        cost_day = day_d
        try:
            if float(day_d) < 0.1:
                kwh = await _ha_today_kwh()
                if kwh and kwh > 0:
                    try:
                        tariff = max(float(await ha_state("input_number.tarif_den")), 0.5)
                    except Exception:
                        tariff = 5.68
                    cost_day = f"{kwh * tariff:.2f}"
        except Exception:
            pass
        # Fix: calculate real monthly forecast from accumulated / days_passed * days_in_month
        forecast = prog_d
        try:
            month_val = float(month_d)
            day_num = now.day
            if now.month == 12:
                days_in_month = 31
            else:
                days_in_month = (now.replace(month=now.month + 1, day=1) - timedelta(days=1)).day
            if month_val > 0 and day_num > 0:
                forecast = f"{month_val / day_num * days_in_month:.0f}"
        except Exception:
            pass
        text = (
            f"🗓️ <b>Еженедельный отчёт — неделя {week_num}</b>\n\n"
            f"⚡ Сегодня: <b>{cost_day} ₽</b>\n"
            f"💰 Накоплено за месяц: <b>{month_d} ₽</b>\n"
            f"📈 Прогноз за месяц: <b>{forecast} ₽</b>"
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

async def _send_monthly_report():
    """Отправить ежемесячный отчёт по энергопотреблению (1-е число каждого месяца).

    Показывает потребление за прошедший месяц в кВт·ч и в рублях.
    Вызывается из _check_alerts() 1-го числа в 09:00 МСК.
    """
    """Ежемесячный отчёт: 1-е число месяца в 09:00 МСК."""
    try:
        now = datetime.now(MSK)
        # Прошлый месяц
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = first_this - timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_name = last_month_end.strftime("%B %Y")

        month_d, day_d = await asyncio.gather(
            ha_state("sensor.elektroenergiia_stoimost_za_mesiats"),
            ha_state("sensor.elektroenergiia_stoimost_za_den"),
        )

        # История за 30 дней
        points = await ha_history("sensor.moshchnost_vsego_doma", hours=720)

        text = (
            f"📅 <b>Ежемесячный отчёт — {month_name}</b>\n\n"
            f"💰 Накоплено за месяц: <b>{month_d} ₽</b>\n"
            f"⚡ Потребление за сегодня: <b>{day_d} ₽</b>\n\n"
            f"Следующий отчёт — 1-е числа следующего месяца"
        )
        if points:
            img = _make_chart(points, f"⚡ Мощность дома — {month_name}", "Вт", "#60a5fa")
            if img:
                await bot.send_photo(
                    ADMIN_ID,
                    BufferedInputFile(img, filename="monthly.png"),
                    caption=text,
                    parse_mode="HTML"
                )
                _activity_log("monthly_report", month_name)
                return
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
        _activity_log("monthly_report", month_name)
    except Exception as e:
        log.error(f"Monthly report error: {e}")

# ── Web App handlers ──────────────────────────────────────────────────────────
def _check_token(request: aiohttp_web.Request) -> bool:
    """Проверить авторизацию запроса к API.

    Токен передаётся в заголовке Authorization: Bearer ТОКЕН.
    Токен — WEBAPP_TOKEN из .env. Никогда не вшивается в HTML,
    выдаётся только через /auth после верификации Telegram initData.
    """
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {WEBAPP_TOKEN}"

async def _web_index(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/ — отдать HTML страницу Mini App.

    WEBAPP_TOKEN больше НЕ вшивается в HTML — токен выдаётся только через /auth
    после верификации Telegram initData.
    """
    path = WEBAPP_DIR / "index.html"
    if not path.exists():
        return aiohttp_web.Response(status=404, text="Not found")
    html = path.read_text(encoding="utf-8")
    # Inject VAPID public key so frontend can subscribe without extra API call
    inject = f'<script>window.VAPID_PUBLIC_KEY={json.dumps(VAPID_PUBLIC_KEY)};</script>'
    html = html.replace('</head>', inject + '\n</head>', 1)
    return aiohttp_web.Response(
        text=html,
        content_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )

# CORS заголовки для всех API ответов.
# Нужны потому что Telegram открывает Mini App с домена t.me,
# а запросы идут на наш домен — это cross-origin запрос.
_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
}

# In-memory кеш путей аватаров (username → entity_picture path)
_user_avatar_cache: dict[str, str] = {}

async def _web_user_avatar(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/user-avatar/{username} — прокси аватара из HA с bot-токеном."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    username = request.match_info.get("username", "")
    ep = _user_avatar_cache.get(username)
    if not ep:
        # Попробуем загрузить из HA напрямую
        try:
            d = await ha_get(f"states/person.{username.lower()}")
            ep = (d.get("attributes") or {}).get("entity_picture")
            if ep:
                _user_avatar_cache[username] = ep
        except Exception:
            pass
    if not ep:
        return aiohttp_web.Response(status=404, text="No avatar", headers=_CORS_HEADERS)
    url = (HA_URL + ep) if ep.startswith("/") else ep
    try:
        async with _ha_cs() as s:
            r = await s.get(url, headers={"Authorization": f"Bearer {HA_TOKEN}"}, ssl=False)
            if r.status != 200:
                return aiohttp_web.Response(status=r.status, headers=_CORS_HEADERS)
            data = await r.read()
            ct = r.headers.get("Content-Type", "image/jpeg")
            return aiohttp_web.Response(body=data, content_type=ct, headers=_CORS_HEADERS)
    except Exception as e:
        log.warning(f"user_avatar proxy: {e}")
        return aiohttp_web.Response(status=502, text="Proxy error", headers=_CORS_HEADERS)

async def _web_manifest(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/manifest.json — PWA manifest."""
    path = WEBAPP_DIR / "manifest.json"
    if not path.exists():
        return aiohttp_web.Response(status=404, text="Not found")
    return aiohttp_web.Response(
        text=path.read_text(encoding="utf-8"),
        content_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )

async def _web_sw(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/sw.js — Service Worker для PWA."""
    path = WEBAPP_DIR / "sw.js"
    if not path.exists():
        return aiohttp_web.Response(status=404, text="Not found")
    return aiohttp_web.Response(
        text=path.read_text(encoding="utf-8"),
        content_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/ha-app/"},
    )

async def _web_options(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """OPTIONS /ha-app/api/* — CORS preflight запрос.

    Браузер отправляет OPTIONS перед реальным запросом чтобы спросить:
    'можно ли делать cross-origin запросы?' Отвечаем: да, можно.
    """
    return aiohttp_web.Response(status=204, headers=_CORS_HEADERS)

async def _web_health(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/health — проверка работоспособности бота.

    Не требует авторизации — используется для мониторинга.
    Возвращает JSON: {ok, version, uptime, uptime_sec, ha_connected}.
    ha_connected = true если HA API отвечает на GET /api/.
    """
    uptime_sec = int(_time.time() - _BOT_START_TIME)
    h = uptime_sec // 3600; m = (uptime_sec % 3600) // 60; s = uptime_sec % 60
    uptime_str = f"{h}ч {m:02d}м {s:02d}с"
    # Лёгкая проверка HA: GET /api/
    ha_ok = False
    try:
        async with _ha_cs() as sess:
            async with sess.get(
                f"{HA_URL}/api/", headers=HA_HEADERS,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                ha_ok = r.status == 200
    except Exception:
        pass
    payload = {
        "ok":           True,
        "version":      _BOT_VERSION,
        "uptime":       uptime_str,
        "uptime_sec":   uptime_sec,
        "ha_connected": ha_ok,
    }
    return aiohttp_web.Response(
        text=json.dumps(payload, ensure_ascii=False),
        content_type="application/json",
        headers=_CORS_HEADERS,
    )

async def _create_ha_automation(scene_id: str, scene: dict, trigger_override: dict | None = None) -> dict:
    """Create or update a HA automation for the given scene. Returns status dict.
    trigger_override: if provided, use this trigger (for schedule mode).
    """
    auto = scene.get("automation", {})
    name = scene.get("name", scene_id)
    actions = scene.get("actions", [])
    trigger_type = auto.get("trigger_type", "time")

    # Build trigger
    if trigger_override:
        trigger = [trigger_override]
    elif trigger_type == "time":
        trigger_time = auto.get("trigger_time", "07:00")
        # HA wants HH:MM:SS
        if len(trigger_time) == 5:
            trigger_time += ":00"
        trigger = [{"platform": "time", "at": trigger_time}]
    else:
        entity = auto.get("trigger_entity", "")
        state = auto.get("trigger_state", "on")
        if not entity:
            return {"error": "trigger_entity required for state trigger"}
        trigger = [{"platform": "state", "entity_id": entity, "to": state}]

    # Build HA action list from scene actions
    ha_actions = []
    for a in actions:
        eid = a.get("entity_id", "")
        svc = a.get("service", "")
        if not eid or not svc or "." not in svc:
            continue
        domain, service = svc.split(".", 1)
        action_body: dict = {"service": f"{domain}.{service}", "target": {"entity_id": eid}}
        if a.get("extra"):
            action_body["data"] = a["extra"]
        ha_actions.append(action_body)

    if not ha_actions:
        return {"error": "no valid actions"}

    automation_id = f"miniapp_scene_{scene_id}"
    payload = {
        "alias": f"Сцена: {name}",
        "description": f"Создана через Mini App (сцена: {scene_id})",
        "trigger": trigger,
        "condition": [],
        "action": ha_actions,
        "mode": "single",
    }

    try:
        url = f"{HA_URL}/api/config/automation/config/{automation_id}"
        async with _ha_cs() as sess:
            async with sess.post(url, headers=HA_HEADERS, json=payload,
                                 timeout=aiohttp.ClientTimeout(total=15)) as resp:
                body = await resp.text()
                if resp.status in (200, 201):
                    # Reload automations so HA picks up the change
                    try:
                        await ha_call("automation", "reload", "")
                    except Exception:
                        pass
                    log.info(f"HA automation created: {automation_id}")
                    return {"ok": True, "id": automation_id}
                log.warning(f"HA automation create failed {resp.status}: {body[:200]}")
                return {"error": f"HA returned {resp.status}", "detail": body[:200]}
    except Exception as e:
        log.warning(f"_create_ha_automation: {e}")
        return {"error": str(e)}


async def _web_scenes_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/scenes — список сцен."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    return aiohttp_web.Response(
        text=json.dumps(_scenes_load(), ensure_ascii=False),
        content_type="application/json", headers=_CORS_HEADERS)

async def _web_scenes_post(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/scenes — создать/обновить сцену.
    Body: {id, name, icon, description, actions: [{entity_id, service, extra?}]}"""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        scene_id = body.get("id", "").strip()
        if not scene_id:
            return aiohttp_web.Response(status=400, text="id required", headers=_CORS_HEADERS)
        scenes = _scenes_load()
        auto_cfg = body.get("automation", {})
        sched_cfg = body.get("schedule", {})
        scenes[scene_id] = {
            "name":        body.get("name", scene_id),
            "icon":        body.get("icon", "⭐"),
            "description": body.get("description", ""),
            "actions":     body.get("actions", []),
            "automation":  auto_cfg,
            "schedule":    sched_cfg,
        }
        _scenes_save(scenes)
        _activity_log("scene_saved", scene_id)
        # Optionally create/update HA automation
        auto_result = None
        if auto_cfg.get("enabled"):
            auto_result = await _create_ha_automation(scene_id, scenes[scene_id])
        # Optionally create schedule automation
        sched_result = None
        if sched_cfg.get("enabled"):
            sched_time = sched_cfg.get("time", "07:00")
            if len(sched_time) == 5:
                sched_time += ":00"
            days_of_week = sched_cfg.get("days", [0,1,2,3,4,5,6])
            # Map 0-6 (Mon-Sun) to HA weekday names
            HA_DAYS = ["mon","tue","wed","thu","fri","sat","sun"]
            ha_days = [HA_DAYS[d] for d in days_of_week if 0 <= d <= 6]
            trigger_ov = {"platform": "time", "at": sched_time}
            sched_scene = dict(scenes[scene_id])
            # Create schedule automation with weekday condition
            # We'll inline a custom create here to pass condition
            sched_ha_actions = []
            for a in sched_scene.get("actions", []):
                eid = a.get("entity_id", "")
                svc = a.get("service", "")
                if not eid or not svc or "." not in svc:
                    continue
                domain, service = svc.split(".", 1)
                ab: dict = {"service": f"{domain}.{service}", "target": {"entity_id": eid}}
                if a.get("extra"):
                    ab["data"] = a["extra"]
                sched_ha_actions.append(ab)
            if sched_ha_actions and ha_days:
                sched_payload = {
                    "alias": f"Расписание: {sched_scene.get('name', scene_id)}",
                    "description": f"Расписание сцены {scene_id} (Mini App)",
                    "trigger": [{"platform": "time", "at": sched_time}],
                    "condition": [{"condition": "time", "weekday": ha_days}],
                    "action": sched_ha_actions,
                    "mode": "single",
                }
                try:
                    sched_auto_id = f"miniapp_sched_{scene_id}"
                    url = f"{HA_URL}/api/config/automation/config/{sched_auto_id}"
                    async with _ha_cs() as sess:
                        async with sess.post(url, headers=HA_HEADERS, json=sched_payload,
                                             timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status in (200, 201):
                                try:
                                    await ha_call("automation", "reload", "")
                                except Exception:
                                    pass
                                sched_result = {"ok": True, "id": sched_auto_id}
                            else:
                                sched_result = {"error": f"HA returned {resp.status}"}
                except Exception as e:
                    sched_result = {"error": str(e)}
        result = {"ok": True}
        if auto_result:
            result["automation"] = auto_result
        if sched_result:
            result["schedule_automation"] = sched_result
        return aiohttp_web.Response(text=json.dumps(result), content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_scenes_delete(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """DELETE /ha-app/api/scenes/{id} — удалить сцену."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    scene_id = request.match_info.get("scene_id", "")
    scenes = _scenes_load()
    if scene_id in scenes:
        del scenes[scene_id]
        _scenes_save(scenes)
        _activity_log("scene_deleted", scene_id)
    return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                headers=_CORS_HEADERS)

async def _web_scenes_run(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/scenes/{id}/run — запустить сцену."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    scene_id = request.match_info.get("scene_id", "")
    scenes = _scenes_load()
    scene = scenes.get(scene_id)
    if not scene:
        return aiohttp_web.Response(status=404, text="Scene not found", headers=_CORS_HEADERS)
    errors = []
    for action in scene.get("actions", []):
        eid = action.get("entity_id", "")
        svc = action.get("service", "")
        extra = action.get("extra")
        if not eid or not svc or "." not in svc:
            continue
        domain, service = svc.split(".", 1)
        try:
            await ha_call(domain, service, eid, extra)
        except Exception as e:
            errors.append(str(e))
    _activity_log("scene_run", scene.get("name", scene_id))
    # Invalidate status cache
    _status_cache["ts"] = 0.0
    result = {"ok": True, "scene": scene.get("name", scene_id), "actions": len(scene.get("actions", []))}
    if errors:
        result["errors"] = errors
    return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False),
                                content_type="application/json", headers=_CORS_HEADERS)

async def _web_alerts_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/alerts — текущая конфигурация алертов."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    return aiohttp_web.Response(
        text=json.dumps(_alerts_load(), ensure_ascii=False),
        content_type="application/json", headers=_CORS_HEADERS)

async def _web_alerts_post(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/alerts — сохранить конфигурацию алертов."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        cfg  = _alerts_load()
        for key in ("power_threshold", "temp_min", "temp_max", "quiet_hours_start", "quiet_hours_end"):
            if key in body:
                cfg[key] = int(body[key])
        if "enabled" in body and isinstance(body["enabled"], dict):
            cfg["enabled"].update(body["enabled"])
        _alerts_save(cfg)
        _activity_log("alerts_saved", str(cfg))
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_activity(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/activity — последние 50 событий из SQLite."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        rows = _db().execute(
            "SELECT ts,action,detail FROM activity_log ORDER BY id DESC LIMIT 50"
        ).fetchall()
        entries = [{"ts": r["ts"], "action": r["action"], "detail": r["detail"]} for r in rows]
        return aiohttp_web.Response(
            text=json.dumps(entries, ensure_ascii=False),
            content_type="application/json",
            headers=_CORS_HEADERS,
        )
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_activity_clear(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/activity/clear — очистить историю активности."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("DELETE FROM activity_log")
            c.commit()
        return aiohttp_web.Response(
            text=json.dumps({"ok": True}),
            content_type="application/json",
            headers=_CORS_HEADERS,
        )
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

# ── Web Push (VAPID) ──────────────────────────────────────────────────────────

async def push_notify(username: str | None, title: str, body: str, url: str = "/ha-app/") -> int:
    """Send Web Push notification to all subscriptions for username (or all if None).
    Returns count of successful sends."""
    log.info(f"push_notify: called for username={username!r} title={title!r}")
    if not VAPID_PRIVATE_PEM_FILE.exists() or not VAPID_PUBLIC_KEY:
        log.warning("push_notify: VAPID files missing, skipping")
        return 0
    try:
        from pywebpush import webpush, WebPushException
        from py_vapid import Vapid
        vapid = Vapid.from_file(str(VAPID_PRIVATE_PEM_FILE))
    except Exception as e:
        log.error(f"push_notify: vapid load error: {e}")
        return 0

    query = "SELECT endpoint, p256dh, auth FROM push_subscriptions"
    params: list = []
    if username:
        query += " WHERE username=?"
        params.append(username)
    try:
        rows = _db().execute(query, params).fetchall()
    except Exception:
        return 0

    sent = 0
    data = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
    dead_endpoints: list[str] = []
    for row in rows:
        try:
            webpush(
                subscription_info={"endpoint": row["endpoint"],
                                   "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}},
                data=data,
                vapid_private_key=str(VAPID_PRIVATE_PEM_FILE),
                vapid_claims=VAPID_CLAIMS,
                ttl=3600,
            )
            sent += 1
        except Exception as e:
            err_str = str(e)
            if "410" in err_str or "404" in err_str:   # subscription expired
                dead_endpoints.append(row["endpoint"])
            else:
                log.warning(f"push_notify: send error for {row['endpoint'][:40]}: {e}")
    # Remove expired subscriptions
    if dead_endpoints:
        with _DB_LOCK:
            c = _db()
            c.executemany("DELETE FROM push_subscriptions WHERE endpoint=?",
                          [(ep,) for ep in dead_endpoints])
            c.commit()
    return sent


async def _web_push_subscribe(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/push-subscribe — save/refresh browser push subscription."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        username = request.headers.get("X-HA-User", "") or body.get("username", "")
        endpoint = body.get("endpoint", "")
        keys     = body.get("keys", {})
        p256dh   = keys.get("p256dh", "")
        auth     = keys.get("auth", "")
        if not endpoint or not p256dh or not auth:
            return aiohttp_web.Response(status=400, text='{"error":"missing fields"}',
                                        content_type="application/json", headers=_CORS_HEADERS)
        from datetime import datetime as _dt
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        with _DB_LOCK:
            c = _db()
            c.execute("""INSERT INTO push_subscriptions(username,endpoint,p256dh,auth,created_at)
                         VALUES(?,?,?,?,?)
                         ON CONFLICT(endpoint) DO UPDATE SET username=excluded.username,
                           p256dh=excluded.p256dh, auth=excluded.auth, created_at=excluded.created_at""",
                      (username, endpoint, p256dh, auth, now_str))
            c.commit()
        log.info(f"push_subscribe: {username} @ {endpoint[:50]}")
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"push_subscribe: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_push_unsubscribe(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """DELETE /ha-app/api/push-subscribe — remove subscription."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        endpoint = body.get("endpoint", "")
        if endpoint:
            with _DB_LOCK:
                c = _db()
                c.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
                c.commit()
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_vapid_key(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/vapid-key — public VAPID key for browser subscription."""
    return aiohttp_web.Response(
        text=json.dumps({"publicKey": VAPID_PUBLIC_KEY}),
        content_type="application/json", headers=_CORS_HEADERS)


async def _web_shopping_items(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/shopping-items — fetch todo items from HA.
       POST /ha-app/api/shopping-items — add new item to HA todo list.
    """
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    if request.method == "POST":
        try:
            body = await request.json()
            item_text = body.get("item", "").strip()
            if not item_text:
                return aiohttp_web.Response(status=400, text='{"error":"empty item"}',
                                            content_type="application/json", headers=_CORS_HEADERS)
            # Call HA WS to add item
            ws_url = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
            ssl_ctx = _ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = _ssl.CERT_NONE
            import websockets as _ws2
            async with _ws2.connect(ws_url, ssl=ssl_ctx, family=socket.AF_INET) as ws:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get("type") != "auth_required":
                    return aiohttp_web.Response(status=502, text="HA auth failed", headers=_CORS_HEADERS)
                await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
                auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if auth_resp.get("type") != "auth_ok":
                    return aiohttp_web.Response(status=502, text="HA auth failed", headers=_CORS_HEADERS)
                await ws.send(json.dumps({
                    "id": 1, "type": "call_service",
                    "domain": "todo", "service": "add_item",
                    "service_data": {"entity_id": SHOP_EID, "item": item_text},
                }))
                await asyncio.wait_for(ws.recv(), timeout=10)
            return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                        headers=_CORS_HEADERS)
        except Exception as e:
            return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)
    # GET
    try:
        items = await ha_ws_get_todo_items(SHOP_EID)
        return aiohttp_web.Response(
            text=json.dumps(items, ensure_ascii=False),
            content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _ha_todo_complete_item(entity_id: str, item_text: str) -> None:
    """Mark a todo item as completed in Home Assistant via WebSocket."""
    ws_url = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
    ssl_ctx = _ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = _ssl.CERT_NONE
    try:
        async with websockets.connect(ws_url, ssl=ssl_ctx, family=socket.AF_INET) as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg.get("type") != "auth_required":
                return
            await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
            auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if auth_resp.get("type") != "auth_ok":
                return
            await ws.send(json.dumps({
                "id": 1, "type": "call_service",
                "domain": "todo", "service": "update_item",
                "service_data": {"entity_id": entity_id, "item": item_text, "status": "completed"},
            }))
            await asyncio.wait_for(ws.recv(), timeout=10)
    except Exception as e:
        log.warning(f"_ha_todo_complete_item: {e}")


async def _web_shopping_assignments_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/shopping-assignments — active assignments."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        rows = _db().execute(
            "SELECT id,item_text,list_entity,assigned_to,assigned_by,created_at,notified_at,done "
            "FROM shopping_assignments WHERE done=0 ORDER BY id DESC"
        ).fetchall()
        result = [dict(r) for r in rows]
        return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False),
                                    content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


def _get_display_name(username: str) -> str:
    """Lookup user's display_name from webapp_users, fallback to username."""
    if not username:
        return "дом"
    try:
        row = _db().execute(
            "SELECT display_name FROM webapp_users WHERE username=?", (username,)
        ).fetchone()
        return (row[0] or username) if row else username
    except Exception:
        return username


def _shop_push_text(items: list[str], assignee_name: str, assigner_name: str) -> tuple[str, str]:
    """Build push notification title + body for shopping assignment."""
    title = f"🛒 {assignee_name}, купи!"
    if len(items) == 1:
        body = f"• {items[0]}\n\nОт {assigner_name}"
    else:
        # Show up to 5 items, then "и ещё N"
        shown = items[:5]
        rest  = len(items) - len(shown)
        lines = "\n".join(f"• {i}" for i in shown)
        if rest:
            lines += f"\n  и ещё {rest}..."
        body = f"{lines}\n\nОт {assigner_name}"
    return title, body


async def _web_shopping_assignments_post(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/shopping-assignments — create assignment or mark done.
    Body: {action: 'assign'|'assign_batch'|'done', ...}
      assign:       {item_text, list_entity?, assigned_to}
      assign_batch: {items: [...], assigned_to}
      done:         {id}
    """
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        ha_user = request.headers.get("X-HA-User", "")
        action  = body.get("action", "assign")
        from datetime import datetime as _dt
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")

        if action == "assign":
            item_text   = body.get("item_text", "").strip()
            list_entity = body.get("list_entity", "")
            assigned_to = body.get("assigned_to", "")
            if not item_text or not assigned_to:
                return aiohttp_web.Response(status=400, text='{"error":"missing fields"}',
                                            content_type="application/json", headers=_CORS_HEADERS)
            with _DB_LOCK:
                c = _db()
                c.execute(
                    "INSERT INTO shopping_assignments(item_text,list_entity,assigned_to,assigned_by,created_at) VALUES(?,?,?,?,?)",
                    (item_text, list_entity, assigned_to, ha_user, now_str)
                )
                c.commit()
            assignee_name = _get_display_name(assigned_to)
            assigner_name = _get_display_name(ha_user)
            title, notif_body = _shop_push_text([item_text], assignee_name, assigner_name)
            asyncio.create_task(push_notify(assigned_to, title, notif_body, "/ha-app/"))
            return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                        headers=_CORS_HEADERS)

        elif action == "assign_batch":
            items       = [i.strip() for i in body.get("items", []) if str(i).strip()]
            assigned_to = body.get("assigned_to", "")
            if not items or not assigned_to:
                return aiohttp_web.Response(status=400, text='{"error":"missing fields"}',
                                            content_type="application/json", headers=_CORS_HEADERS)
            with _DB_LOCK:
                c = _db()
                for item_text in items:
                    c.execute(
                        "INSERT INTO shopping_assignments(item_text,list_entity,assigned_to,assigned_by,created_at) VALUES(?,?,?,?,?)",
                        (item_text, "", assigned_to, ha_user, now_str)
                    )
                c.commit()
            # One consolidated push notification
            assignee_name = _get_display_name(assigned_to)
            assigner_name = _get_display_name(ha_user)
            title, notif_body = _shop_push_text(items, assignee_name, assigner_name)
            asyncio.create_task(push_notify(assigned_to, title, notif_body, "/ha-app/"))
            return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                        headers=_CORS_HEADERS)

        elif action == "done":
            row_id = body.get("id")
            if row_id is None:
                return aiohttp_web.Response(status=400, text='{"error":"missing id"}',
                                            content_type="application/json", headers=_CORS_HEADERS)
            with _DB_LOCK:
                c = _db()
                row = c.execute(
                    "SELECT item_text, list_entity FROM shopping_assignments WHERE id=?", (row_id,)
                ).fetchone()
                c.execute("UPDATE shopping_assignments SET done=1 WHERE id=?", (row_id,))
                c.commit()
            if row:
                asyncio.create_task(_ha_todo_complete_item(row[1] or SHOP_EID, row[0]))
            return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                        headers=_CORS_HEADERS)

        return aiohttp_web.Response(status=400, text='{"error":"unknown action"}',
                                    content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"shopping_assignments: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


# ── Family extra endpoints ─────────────────────────────────────────────────────

async def _web_family_extra(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/family-extra — statuses, note, cooking, reactions."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        from datetime import datetime as _dt
        c = _db()
        rows = c.execute("SELECT username, status_emoji, status_text, updated_at FROM family_statuses").fetchall()
        statuses = {r[0]: {"emoji": r[1], "text": r[2], "updated_at": r[3]} for r in rows}
        note_row = c.execute("SELECT content, updated_by, updated_at FROM family_note WHERE id=1").fetchone()
        note = {"content": note_row[0], "updated_by": note_row[1], "updated_at": note_row[2]} if note_row else {"content": "", "updated_by": "", "updated_at": ""}
        today = _dt.now().strftime("%Y-%m-%d")
        cook_row = c.execute("SELECT username FROM cooking_schedule WHERE date=?", (today,)).fetchone()
        cooking = {"username": cook_row[0] if cook_row else "", "display_name": _get_display_name(cook_row[0]) if cook_row else ""}
        reactions = [dict(r) for r in c.execute("SELECT from_user, to_user, reaction, created_at FROM family_reactions ORDER BY id DESC LIMIT 20").fetchall()]
        return aiohttp_web.Response(
            text=json.dumps({"statuses": statuses, "note": note, "cooking": cooking, "reactions": reactions}, ensure_ascii=False),
            content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_family_status_post(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/family-status — set my status emoji."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        from datetime import datetime as _dt
        body = await request.json()
        username = request.headers.get("X-HA-User", "")
        if not username:
            return aiohttp_web.Response(status=400, text='{"error":"no user"}', content_type="application/json", headers=_CORS_HEADERS)
        emoji   = body.get("emoji", "😊")[:8]
        text    = body.get("text", "")[:50]
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        with _DB_LOCK:
            c = _db()
            c.execute("INSERT OR REPLACE INTO family_statuses(username, status_emoji, status_text, updated_at) VALUES(?,?,?,?)",
                      (username, emoji, text, now_str))
            c.commit()
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_family_reaction(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/family-reaction — send a reaction push to another user."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        from datetime import datetime as _dt
        body      = await request.json()
        from_user = request.headers.get("X-HA-User", "")
        to_user   = body.get("to_user", "")
        reaction  = body.get("reaction", "🤗")[:80]
        if not to_user:
            return aiohttp_web.Response(status=400, text='{"error":"no to_user"}', content_type="application/json", headers=_CORS_HEADERS)
        # Broadcast to all users
        if to_user == "__all__":
            from_name = _get_display_name(from_user)
            sent = await push_notify(None, f"{from_name}: {reaction}", reaction, "/ha-app/")
            return aiohttp_web.Response(text=json.dumps({"ok": True, "sent": sent}),
                                        content_type="application/json", headers=_CORS_HEADERS)
        # Normalize: HA display name → webapp username (case-insensitive fallback)
        c = _db()
        norm = c.execute(
            "SELECT username FROM webapp_users WHERE username=? OR LOWER(display_name)=LOWER(?)",
            (to_user, to_user)
        ).fetchone()
        if norm:
            to_user = norm[0]
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        with _DB_LOCK:
            c = _db()
            c.execute("INSERT INTO family_reactions(from_user, to_user, reaction, created_at) VALUES(?,?,?,?)",
                      (from_user, to_user, reaction, now_str))
            # keep only last 100
            c.execute("DELETE FROM family_reactions WHERE id NOT IN (SELECT id FROM family_reactions ORDER BY id DESC LIMIT 100)")
            c.commit()
        from_name = _get_display_name(from_user)
        to_name   = _get_display_name(to_user)
        log.info(f"family_reaction: {from_user} → {to_user} ({reaction}), sending push")
        sent = await push_notify(to_user, f"{from_name}: {reaction}", reaction, "/ha-app/")
        log.info(f"family_reaction: push sent={sent} for to_user={to_user!r}")
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_family_note(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET/POST /ha-app/api/family-note — shared family note."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    if request.method == "POST":
        try:
            from datetime import datetime as _dt
            body     = await request.json()
            username = request.headers.get("X-HA-User", "")
            content  = body.get("content", "")[:500]
            now_str  = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            with _DB_LOCK:
                c = _db()
                c.execute("INSERT OR REPLACE INTO family_note(id, content, updated_by, updated_at) VALUES(1,?,?,?)",
                          (content, username, now_str))
                c.commit()
            return aiohttp_web.Response(text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS)
        except Exception as e:
            return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)
    try:
        c = _db()
        row = c.execute("SELECT content, updated_by, updated_at FROM family_note WHERE id=1").fetchone()
        result = {"content": row[0], "updated_by": row[1], "updated_at": row[2]} if row else {"content": "", "updated_by": "", "updated_at": ""}
        return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False), content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_cooking(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET/POST /ha-app/api/cooking — who's cooking today."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    from datetime import datetime as _dt
    today = _dt.now().strftime("%Y-%m-%d")
    if request.method == "POST":
        try:
            body       = await request.json()
            username   = body.get("username", "")
            updated_by = request.headers.get("X-HA-User", "")
            now_str    = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            with _DB_LOCK:
                c = _db()
                if username:
                    c.execute("INSERT OR REPLACE INTO cooking_schedule(date,username,updated_by,updated_at) VALUES(?,?,?,?)",
                              (today, username, updated_by, now_str))
                else:
                    c.execute("DELETE FROM cooking_schedule WHERE date=?", (today,))
                c.commit()
            return aiohttp_web.Response(text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS)
        except Exception as e:
            return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)
    try:
        c = _db()
        row = c.execute("SELECT username FROM cooking_schedule WHERE date=?", (today,)).fetchone()
        username = row[0] if row else ""
        return aiohttp_web.Response(
            text=json.dumps({"username": username, "display_name": _get_display_name(username) if username else ""}, ensure_ascii=False),
            content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_shopping_meta(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET/POST /ha-app/api/shopping-meta — item metadata (priority, quantity)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    if request.method == "POST":
        try:
            body      = await request.json()
            uid       = body.get("uid", "")
            item_text = body.get("item_text", "")
            priority  = int(body.get("priority", 0))
            quantity  = str(body.get("quantity", ""))[:20]
            if not uid:
                return aiohttp_web.Response(status=400, text='{"error":"no uid"}', content_type="application/json", headers=_CORS_HEADERS)
            with _DB_LOCK:
                c = _db()
                c.execute("INSERT OR REPLACE INTO shopping_item_meta(item_uid,item_text,priority,quantity) VALUES(?,?,?,?)",
                          (uid, item_text, priority, quantity))
                c.commit()
            return aiohttp_web.Response(text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS)
        except Exception as e:
            return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)
    try:
        uids = [u.strip() for u in request.rel_url.query.get("uids","").split(",") if u.strip()]
        c = _db()
        result = {}
        if uids:
            placeholders = ",".join("?"*len(uids))
            rows = c.execute(f"SELECT item_uid,priority,quantity FROM shopping_item_meta WHERE item_uid IN ({placeholders})", uids).fetchall()
            for r in rows:
                result[r[0]] = {"priority": r[1], "quantity": r[2]}
        return aiohttp_web.Response(text=json.dumps(result), content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_shopping_quick(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET/POST /ha-app/api/shopping-quick — quick-add items."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    if request.method == "POST":
        try:
            body   = await request.json()
            action = body.get("action", "add")
            with _DB_LOCK:
                c = _db()
                if action == "add":
                    name  = body.get("name","").strip()[:50]
                    emoji = body.get("emoji","")[:4]
                    if not name:
                        return aiohttp_web.Response(status=400, text='{"error":"no name"}', content_type="application/json", headers=_CORS_HEADERS)
                    c.execute("INSERT OR IGNORE INTO shopping_quick_items(name,emoji) VALUES(?,?)", (name, emoji))
                elif action == "delete":
                    item_id = body.get("id")
                    if item_id is not None:
                        c.execute("DELETE FROM shopping_quick_items WHERE id=?", (item_id,))
                c.commit()
            return aiohttp_web.Response(text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS)
        except Exception as e:
            return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)
    try:
        c = _db()
        rows = c.execute("SELECT id,name,emoji FROM shopping_quick_items ORDER BY ord,id").fetchall()
        result = [{"id": r[0], "name": r[1], "emoji": r[2]} for r in rows]
        return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False), content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_shopping_stats(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/shopping-stats."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        from datetime import datetime as _dt
        c = _db()
        month_start = _dt.now().strftime("%Y-%m-01")
        all_rows    = c.execute("SELECT assigned_to,COUNT(*) FROM shopping_assignments WHERE done=1 GROUP BY assigned_to ORDER BY COUNT(*) DESC").fetchall()
        month_rows  = c.execute("SELECT assigned_to,COUNT(*) FROM shopping_assignments WHERE done=1 AND created_at>=? GROUP BY assigned_to ORDER BY COUNT(*) DESC",(month_start,)).fetchall()
        assigner_rows = c.execute("SELECT assigned_by,COUNT(*) FROM shopping_assignments WHERE done=1 GROUP BY assigned_by ORDER BY COUNT(*) DESC").fetchall()
        def enrich(rows):
            return [{"username":r[0],"display_name":_get_display_name(r[0]),"count":r[1]} for r in rows if r[0]]
        result = {"total": sum(r[1] for r in all_rows), "by_buyer": enrich(all_rows), "this_month": enrich(month_rows), "by_assigner": enrich(assigner_rows)}
        return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False), content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_shopping_history(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/shopping-history — recent done assignments."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        c = _db()
        rows = c.execute("SELECT id,item_text,assigned_to,assigned_by,created_at FROM shopping_assignments WHERE done=1 ORDER BY id DESC LIMIT 50").fetchall()
        result = [{"id":r[0],"item_text":r[1],"assigned_to":r[2],"assigned_to_name":_get_display_name(r[2]),"assigned_by":r[3],"assigned_by_name":_get_display_name(r[3]),"created_at":r[4]} for r in rows]
        return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False), content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


# ── SSE (Server-Sent Events) real-time ───────────────────────────────────────
_sse_clients: set = set()  # set of asyncio.Queue

async def _sse_broadcast(entity_id: str, state: str, attrs: dict):
    """Push state update to all connected SSE clients."""
    payload = json.dumps({"entity_id": entity_id, "state": state, "attributes": attrs},
                         ensure_ascii=False)
    dead = set()
    for q in _sse_clients:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.add(q)
    _sse_clients -= dead

def _check_token_qs(request: aiohttp_web.Request) -> bool:
    """Check auth token from Authorization header or ?token= query param."""
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {WEBAPP_TOKEN}":
        return True
    return request.rel_url.query.get("token") == WEBAPP_TOKEN

async def _web_sse(request: aiohttp_web.Request) -> aiohttp_web.StreamResponse:
    """GET /ha-app/api/events — SSE stream of HA state changes."""
    if not _check_token_qs(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    headers = {
        "Content-Type":  "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        **{k: v for k, v in _CORS_HEADERS.items()},
    }
    response = aiohttp_web.StreamResponse(headers=headers)
    await response.prepare(request)
    # Send initial "connected" event
    await response.write(b"event: connected\ndata: {}\n\n")
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_clients.add(queue)
    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=25)
                await response.write(f"data: {payload}\n\n".encode())
            except asyncio.TimeoutError:
                # Keepalive ping
                await response.write(b": ping\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        _sse_clients.discard(queue)
    return response

async def _ha_state_watch_loop():
    """Фоновая задача: подписаться на изменения состояния HA через WebSocket.

    Устанавливает WebSocket соединение с HA (/api/websocket) и подписывается
    на все события state_changed. При получении события:
      1. Обновляет кеш статуса (_status_cache сбрасывается)
      2. Рассылает SSE-событие всем подключённым клиентам Mini App

    Это обеспечивает РЕАЛЬНОЕ ВРЕМЯ в Mini App без polling.
    Браузер не опрашивает сервер каждые N секунд — он получает push-уведомления.

    При обрыве соединения — автоматически переподключается через 5 секунд.
    Требует: библиотека websockets (pip install websockets).
    """
    if not HAS_WS:
        return
    ha_ws = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
    ssl_ctx = _ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = _ssl.CERT_NONE
    watch_eids: set[str] = set()

    while True:
        try:
            async with websockets.connect(ha_ws, ssl=ssl_ctx, ping_interval=20, open_timeout=15, family=socket.AF_INET) as ws:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
                await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
                msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if msg.get("type") != "auth_ok":
                    await asyncio.sleep(15)
                    continue
                # Subscribe to state_changed
                await ws.send(json.dumps({"id": 1, "type": "subscribe_events",
                                          "event_type": "state_changed"}))
                await ws.recv()
                log.info("HA state watch: subscribed to state_changed")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if msg.get("type") != "event":
                            continue
                        evt  = msg.get("event", {})
                        data = evt.get("data", {})
                        eid  = data.get("entity_id", "")
                        new_state = data.get("new_state")
                        if not new_state or not eid:
                            continue
                        state  = new_state.get("state", "")
                        attrs  = new_state.get("attributes", {})
                        # Only broadcast for entities we track (lights, devices, key sensors)
                        devs = _dev_load()
                        relevant = (
                            eid in devs or
                            eid.startswith("light.") or
                            eid.startswith("switch.") or
                            eid == "sensor.moshchnost_vsego_doma" or
                            eid == f"{TV_EID}" or
                            eid.startswith("person.")
                        )
                        if relevant and _sse_clients:
                            # Invalidate status cache on relevant change
                            _status_cache["ts"] = 0.0
                            await _sse_broadcast(eid, state, {
                                "friendly_name": attrs.get("friendly_name", ""),
                            })
                    except Exception:
                        pass
        except Exception as e:
            log.warning(f"HA state watch loop: {e}")
            await asyncio.sleep(10)

async def _web_status(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/status — главный эндпоинт: полный статус умного дома.

    Это самый большой и важный эндпоинт. Возвращает JSON со всем что
    нужно Mini App для отображения: свет, климат, энергия, семья, намаз,
    погода, TV, пылесос, фазы, кастомные разделы.

    Результат кешируется на 5 секунд (_STATUS_CACHE_TTL).
    Кеш сбрасывается при изменении состояния в HA (через _ha_state_watch_loop).

    Все запросы к HA делаются параллельно через asyncio.gather() —
    чтобы не ждать каждый сенсор по очереди.

    Структура ответа:
      power, temp_detskaia, humidity, internet, floor_heating,
      floor_setpoint, floor_temp, cost_day, cost_month, cost_week,
      outdoor_temp, family, lights, sections, phases, tv, vacuum,
      prayers, weather, last_face, cam_person_count, namaz_timer
    """
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    # 5-second cache
    now_ts = _time.time()
    if _status_cache["data"] is not None and (now_ts - _status_cache["ts"]) < _STATUS_CACHE_TTL:
        return aiohttp_web.Response(
            text=_status_cache["data"],
            content_type="application/json",
            headers=_CORS_HEADERS,
        )
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
            ha_get("states/sensor.elektroenergiia_stoimost_za_den"),  # unused, kept for n_fixed count
            ha_get("states/sensor.dom_energiia_vsego"),  # unused, kept for n_fixed count
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
        power_d, temp_d, hum_d, inet_d, floor_d, tv_d, vac_d, cost_day_d, kwh_month_d = results[:n_fixed]
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

        # Добавить webapp-пользователей у которых нет HA person entity
        try:
            ha_names_lower = {n.lower() for n in family_data}
            wb_rows = _db().execute(
                "SELECT username, display_name FROM webapp_users ORDER BY display_name"
            ).fetchall()
            for wb_user, wb_display in wb_rows:
                display = wb_display or wb_user
                if display.lower() not in ha_names_lower and wb_user.lower() not in ha_names_lower:
                    family_data[display] = {"state": "unknown", "lat": None, "lon": None}
        except Exception:
            pass

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

        # Тариф — читаем из HA, fallback 5.5 р/кВт⋅ч (Грозный 2026)
        TARIFF_FALLBACK = 5.5
        try:
            tariff = max(float(await ha_state("input_number.tarif_den_kvt_ch")), 0.5)
        except Exception:
            tariff = TARIFF_FALLBACK

        # Все три периода — из одного источника (dom_energiia_vsego), параллельно
        import calendar as _cal
        kwh_today, kwh_week, kwh_month = await asyncio.gather(
            _ha_today_kwh(),
            _ha_week_kwh(),
            _ha_month_kwh(),
        )

        cost_day_val   = f"{kwh_today * tariff:.0f}" if kwh_today else "—"
        cost_week_val  = f"{kwh_week  * tariff:.0f}" if kwh_week  else None
        cost_month_val = f"{kwh_month * tariff:.0f}" if kwh_month else None

        # Прогноз на месяц: (kWh_month / дней_прошло) × дней_в_месяце × тариф
        cost_forecast_val = None
        try:
            now_msk   = datetime.now(MSK)
            day_num   = now_msk.day
            days_in_m = _cal.monthrange(now_msk.year, now_msk.month)[1]
            if kwh_month and day_num > 0:
                cost_forecast_val = f"{kwh_month / day_num * days_in_m * tariff:.0f}"
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
                    "order":   sect_cfg.get("order", 99),
                    "hidden":  sect_cfg.get("hidden", False),
                    "devices": custom_sections.get(sect_id, {}),
                })

        # Frigate camera counters
        cam_person_d, cam_all_d = await asyncio.gather(
            ha_get("states/sensor.cam_a6810678_person_count"),
            ha_get("states/sensor.cam_a6810678_all_count"),
        )
        try:
            cam_person_cnt = int(float(st(cam_person_d))) if cam_person_d else 0
        except Exception:
            cam_person_cnt = 0
        try:
            cam_all_cnt = int(float(st(cam_all_d))) if cam_all_d else 0
        except Exception:
            cam_all_cnt = 0

        # Energy phases (vvod_1/2/3)
        vvod1_d, vvod2_d, vvod3_d = await asyncio.gather(
            ha_get("states/sensor.vvod_1_moshchnost"),
            ha_get("states/sensor.vvod_2_moshchnost"),
            ha_get("states/sensor.vvod_3_moshchnost"),
        )
        phases_data = [
            {"name": "Фаза 1", "power": st(vvod1_d)},
            {"name": "Фаза 2", "power": st(vvod2_d)},
            {"name": "Фаза 3", "power": st(vvod3_d)},
        ]

        # Namaz timer
        namaz_timer_data = None
        try:
            namaz_d2 = await ha_get(f"states/{NAMAZ_EID}")
            if namaz_d2:
                nattrs = namaz_d2.get("attributes", {})
                namaz_timer_data = {
                    "state":       namaz_d2.get("state", "idle"),
                    "remaining":   nattrs.get("remaining", ""),
                    "duration":    nattrs.get("duration", ""),
                    "finishes_at": nattrs.get("finishes_at", ""),
                }
        except Exception:
            pass

        payload = {
            "power":         st(power_d),
            "temp_detskaia": st(temp_d),
            "humidity":      st(hum_d),
            "internet":      "on" if st(inet_d) == "on" else "off",
            "floor_heating": st(floor_d),
            "floor_setpoint": str(floor_attrs.get("temperature", "?")),
            "floor_temp":    str(floor_attrs.get("current_temperature", "?")),
            "cost_day":      cost_day_val,
            "cost_month":    cost_month_val,
            "cost_forecast": cost_forecast_val,
            "cost_week":     cost_week_val,
            "outdoor_temp":  outdoor_temp,
            "family":        family_data,
            "lights":        lights_data,
            "sections":      active_sects,
            # Видимость ВСЕХ разделов (встроенных и динамических) для фронтенда
            "sections_visibility": {
                k: {"hidden": bool(v.get("hidden", False))}
                for k, v in sections_cfg.items()
            },
            "phases":        phases_data,
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
            "last_face": _alert_state.get("last_recognized_face") or "",
            "cam_person_count": cam_person_cnt,
            "cam_all_count":    cam_all_cnt,
            "namaz_timer":      namaz_timer_data,
        }
        payload_json = json.dumps(payload, ensure_ascii=False)
        _status_cache["ts"]   = _time.time()
        _status_cache["data"] = payload_json
        return aiohttp_web.Response(
            text=payload_json,
            content_type="application/json",
            headers=_CORS_HEADERS,
        )
    except Exception as e:
        log.error(f"web_status error: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_action(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/action — вызвать сервис HA для управления устройством.

    Тело запроса JSON:
      {
        "service":   "light.turn_on",       // домен.сервис
        "entity_id": "light.kitchen",       // ID сущности
        "extra":     {"brightness": 200}    // (опционально) доп. параметры
      }

    Этот эндпоинт вызывается из Mini App когда пользователь нажимает
    кнопку включения/выключения устройства.

    После выполнения сбрасывает кеш статуса — чтобы следующий запрос
    /api/status вернул актуальное состояние.
    """
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        service_str = body.get("service", "")   # напр. "light.turn_on"
        entity_id   = body.get("entity_id", "")
        extra       = body.get("extra") or {}
        if "." not in service_str or not entity_id:
            return aiohttp_web.Response(status=400, text="Bad request", headers=_CORS_HEADERS)
        domain, service = service_str.split(".", 1)
        await ha_call(domain, service, entity_id, extra or None)
        ha_user = request.headers.get("X-HA-User", "")
        _activity_log(f"webapp:{service_str}", entity_id, username=ha_user)
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

FRIGATE_EVENTS_FILE = Path("/opt/ha-bot/frigate_events.json")
_frigate_events: list = []  # in-memory cache of recent Frigate events

def _frigate_events_load() -> list:
    if FRIGATE_EVENTS_FILE.exists():
        try:
            return json.loads(FRIGATE_EVENTS_FILE.read_text())
        except Exception:
            return []
    return []

def _frigate_events_save(evts: list):
    try:
        FRIGATE_EVENTS_FILE.write_text(json.dumps(evts, ensure_ascii=False, indent=2))
    except Exception as e:
        log.error(f"frigate_events_save: {e}")

async def _web_camera_info(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/camera/{entity_id} → stream/snapshot URLs with access_token."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    eid = request.match_info.get("entity_id", "")
    if not eid.startswith("camera."):
        return aiohttp_web.Response(status=400, text="Not a camera entity", headers=_CORS_HEADERS)
    try:
        d = await ha_get(f"states/{eid}")
        if not d:
            return aiohttp_web.Response(status=404, text="Not found", headers=_CORS_HEADERS)
        attrs = d.get("attributes", {})
        tok = attrs.get("access_token", "")
        payload = {
            "entity_id":    eid,
            "name":         attrs.get("friendly_name", eid),
            "state":        d.get("state", ""),
            "stream_url":   f"{HA_URL}/api/camera_proxy_stream/{eid}?token={tok}",
            "snapshot_url": f"{HA_URL}/api/camera_proxy/{eid}?token={tok}",
            "hls_url":      f"{HA_URL}/api/hls/{tok}/index.m3u8",
        }
        return aiohttp_web.Response(text=json.dumps(payload, ensure_ascii=False),
                                    content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_frigate_events(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/frigate/events — последние события детекции Frigate.
    Если кеш пустой — читает клипы через media_source как fallback."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    evts = list(reversed(_frigate_events[-50:]))  # newest first
    # Fallback: if cache empty, build events list from media_source clips
    if not evts and HAS_WS:
        try:
            ha_ws = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
            async with websockets.connect(ha_ws, ping_interval=None, open_timeout=15, family=socket.AF_INET) as ws:
                await ws.recv()
                await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
                msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if msg.get("type") == "auth_ok":
                    await ws.send(json.dumps({
                        "id": 1, "type": "media_source/browse_media",
                        "media_content_id": "media-source://frigate/frigate/event-search/clips/////"
                    }))
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    clips = msg.get("result", {}).get("children", [])
                    for c in clips[:20]:
                        mcid = c.get("media_content_id", "")
                        event_id = mcid.rsplit("/", 1)[-1] if "/" in mcid else ""
                        title = c.get("title", "")
                        # Parse: "2026-03-08 23:08:49 [20s, Person 70%]"
                        label = "person"
                        camera = "cam_a6810678"
                        score = 0
                        ts = 0
                        import re
                        m_lbl = re.search(r'\[.*?(\w+)\s+(\d+)%\]', title, re.I)
                        if m_lbl:
                            label = m_lbl.group(1).lower()
                            score = int(m_lbl.group(2))
                        m_ts = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', title)
                        if m_ts:
                            from datetime import datetime
                            try:
                                ts = int(datetime.strptime(m_ts.group(1), "%Y-%m-%d %H:%M:%S").timestamp())
                            except Exception:
                                pass
                        snap_url = f"{HA_URL}/api/frigate/notifications/{event_id}/snapshot.jpg" if event_id else ""
                        evts.append({
                            "id": event_id, "camera": camera, "label": label,
                            "score": score, "ts": ts, "snapshot_url": snap_url,
                            "event_id": event_id,
                        })
        except Exception as e:
            log.warning(f"frigate_events fallback: {e}")
    # Enrich snapshot URLs from image entity if missing
    for ev in evts:
        if not ev.get("snapshot_url"):
            try:
                img_eid = f"image.{ev['camera']}_{ev['label']}"
                img_d = await ha_get(f"states/{img_eid}")
                if img_d:
                    img_tok = img_d.get("attributes", {}).get("access_token", "")
                    ev["snapshot_url"] = f"{HA_URL}/api/image_proxy/{img_eid}?token={img_tok}"
            except Exception:
                pass
    return aiohttp_web.Response(text=json.dumps(evts, ensure_ascii=False),
                                content_type="application/json", headers=_CORS_HEADERS)


async def _web_frigate_recordings(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/frigate/recordings?camera=cam_a6810678 — последние 6 записей через media_source."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    camera = request.query.get("camera", "cam_a6810678").replace("camera.", "")
    recordings: list = []
    if not HAS_WS:
        return aiohttp_web.Response(text="[]", content_type="application/json", headers=_CORS_HEADERS)
    try:
        ha_ws = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
        async with websockets.connect(ha_ws, ping_interval=None, open_timeout=15, family=socket.AF_INET) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if msg.get("type") != "auth_ok":
                raise Exception("auth failed")
            mid = 1
            # Browse event clips for this camera
            await ws.send(json.dumps({
                "id": mid, "type": "media_source/browse_media",
                "media_content_id": f"media-source://frigate/frigate/event-search/clips/{camera}/////"
            }))
            msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
            clips = msg.get("result", {}).get("children", [])
            mid += 1
            # Take last 6 playable clips (newest first — clips list is already sorted desc)
            playable = [c for c in clips if c.get("can_play")][:6]
            for clip in playable:
                # Extract event_id from media_content_id:
                # media-source://frigate/frigate/event/clips/cam_a6810678/1773000529.669134-l8kcl8
                mcid = clip.get("media_content_id", "")
                event_id = mcid.rsplit("/", 1)[-1] if "/" in mcid else ""
                # Direct clip and snapshot URLs via Frigate notifications API
                clip_url  = f"{HA_URL}/api/frigate/notifications/{event_id}/clip.mp4" if event_id else ""
                snap_url  = f"{HA_URL}/api/frigate/notifications/{event_id}/snapshot.jpg" if event_id else ""
                thumb = clip.get("thumbnail", "")
                if thumb and not thumb.startswith("http"):
                    thumb = HA_URL + thumb
                # Prefer snapshot as thumbnail if no thumb
                if not thumb and snap_url:
                    thumb = snap_url + f"?token={HA_TOKEN}"
                recordings.append({
                    "title":    clip.get("title", ""),
                    "thumbnail": thumb,
                    "url":       clip_url,   # direct MP4 — для видео-плеера и скачивания
                    "event_id":  event_id,
                    "media_content_id": mcid,
                })
    except Exception as e:
        log.warning(f"frigate_recordings: {e}")
    return aiohttp_web.Response(text=json.dumps(recordings, ensure_ascii=False),
                                content_type="application/json", headers=_CORS_HEADERS)


async def _web_frigate_clip_proxy(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/frigate/clip/{event_id} — proxy Frigate clip from HA with auth.
    Supports Range requests for video seeking. Uses ?token= so <video src> works on mobile."""
    if not _check_token_qs(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    event_id = request.match_info.get("event_id", "").strip()
    if not event_id:
        return aiohttp_web.Response(status=400, text="event_id required", headers=_CORS_HEADERS)
    candidate_urls = [
        f"{HA_URL}/api/frigate/notifications/{event_id}/clip.mp4",
        f"{HA_URL}/api/frigate/api/events/{event_id}/clip.mp4",
    ]
    req_headers: dict = {"Authorization": f"Bearer {HA_TOKEN}"}
    if "Range" in request.headers:
        req_headers["Range"] = request.headers["Range"]
    try:
        async with _ha_cs() as sess:
            for clip_url in candidate_urls:
                async with sess.get(clip_url, headers=req_headers,
                                    timeout=aiohttp.ClientTimeout(total=90),
                                    allow_redirects=True) as resp:
                    if resp.status == 404 and clip_url != candidate_urls[-1]:
                        continue
                    data = await resp.read()
                    out_headers = dict(_CORS_HEADERS)
                    out_headers["Content-Type"]  = resp.headers.get("Content-Type", "video/mp4")
                    out_headers["Accept-Ranges"] = "bytes"
                    if "Content-Range" in resp.headers:
                        out_headers["Content-Range"] = resp.headers["Content-Range"]
                    if "Content-Length" in resp.headers:
                        out_headers["Content-Length"] = resp.headers["Content-Length"]
                    return aiohttp_web.Response(status=resp.status, body=data, headers=out_headers)
    except Exception as e:
        log.warning(f"frigate_clip_proxy: {e}")
        return aiohttp_web.Response(status=502, text=str(e), headers=_CORS_HEADERS)


async def _web_frigate_thumb_proxy(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/frigate/thumb/{event_id} — proxy Frigate snapshot with auth.
    Uses ?token= query param so <img src> works without custom headers."""
    if not _check_token_qs(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    event_id = request.match_info.get("event_id", "").strip()
    if not event_id:
        return aiohttp_web.Response(status=400, text="event_id required", headers=_CORS_HEADERS)
    snap_url = f"{HA_URL}/api/frigate/notifications/{event_id}/snapshot.jpg"
    try:
        async with _ha_cs() as sess:
            async with sess.get(snap_url, headers={"Authorization": f"Bearer {HA_TOKEN}"},
                                timeout=aiohttp.ClientTimeout(total=15),
                                ssl=False, allow_redirects=True) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    ct = resp.headers.get("Content-Type", "image/jpeg")
                    out_headers = dict(_CORS_HEADERS)
                    out_headers["Cache-Control"] = "max-age=300"
                    return aiohttp_web.Response(body=data, content_type=ct, headers=out_headers)
                return aiohttp_web.Response(status=resp.status, headers=_CORS_HEADERS)
    except Exception as e:
        log.warning(f"frigate_thumb_proxy: {e}")
        return aiohttp_web.Response(status=502, text=str(e), headers=_CORS_HEADERS)


async def _web_frigate_send(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/frigate/send — скачать снимок/клип и отправить в Telegram."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        camera = body.get("camera", "cam_a6810678").replace("camera.", "")
        label  = body.get("label", "person")
        clip_url = body.get("clip_url", "")  # если передан — отправляем видео
        label_map = {"person": "👤 Человек", "car": "🚗 Авто", "dog": "🐕 Собака", "cat": "🐱 Кот"}
        label_str = label_map.get(label, f"📦 {label}")
        caption = f"📸 <b>Frigate</b> · {label_str}\n📷 {camera}"
        if clip_url:
            # Resolve direct MP4 URL: if HLS m3u8 was passed, extract event_id and use notifications API
            event_id = body.get("event_id", "")
            if event_id:
                clip_url = f"{HA_URL}/api/frigate/notifications/{event_id}/clip.mp4"
            elif "m3u8" in clip_url or "mpegurl" in clip_url.lower():
                return aiohttp_web.Response(status=415, text="HLS stream not downloadable",
                                            headers=_CORS_HEADERS)
            if clip_url.startswith("/"):
                clip_url = HA_URL + clip_url
            ha_headers = {"Authorization": f"Bearer {HA_TOKEN}"}
            log.info(f"frigate_send: downloading {clip_url[:80]}")
            async with _ha_cs() as sess:
                async with sess.get(clip_url, headers=ha_headers,
                                    timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    ct = resp.headers.get("Content-Type", "")
                    log.info(f"frigate_send: status={resp.status} ct={ct}")
                    if resp.status == 200 and ("video" in ct or ct == ""):
                        data = await resp.read()
                        log.info(f"frigate_send: {len(data)} bytes → Telegram")
                        await bot.send_video(
                            ADMIN_ID,
                            BufferedInputFile(data, filename="clip.mp4"),
                            caption=caption, parse_mode="HTML"
                        )
                        return aiohttp_web.Response(
                            text='{"ok":true,"message":"Видео отправлено"}',
                            content_type="application/json", headers=_CORS_HEADERS)
                    body_preview = (await resp.read())[:200]
                    log.warning(f"frigate_send: unexpected {resp.status} {ct}: {body_preview!r}")
            return aiohttp_web.Response(status=502, text="Failed to fetch clip", headers=_CORS_HEADERS)
        # Снимок из image entity
        img_eid = f"image.{camera}_{label}"
        img_d = await ha_get(f"states/{img_eid}")
        if img_d:
            img_tok = img_d.get("attributes", {}).get("access_token", "")
            snap_url = f"{HA_URL}/api/image_proxy/{img_eid}?token={img_tok}"
            async with _ha_cs() as sess:
                async with sess.get(snap_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await bot.send_photo(
                            ADMIN_ID,
                            BufferedInputFile(data, filename="snapshot.jpg"),
                            caption=caption, parse_mode="HTML"
                        )
                        return aiohttp_web.Response(
                            text='{"ok":true,"message":"Фото отправлено"}',
                            content_type="application/json", headers=_CORS_HEADERS)
        return aiohttp_web.Response(status=404, text="No media available", headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"frigate_send: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


_notify_cooldown: dict[str, float] = {}  # camera -> last_notify_time

async def _web_frigate_notify_latest(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/frigate/notify-latest — вызывается из HA автоматизации.
    Дедупликация: одно уведомление на камеру раз в 90 секунд."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
    except Exception:
        body = {}
    camera = body.get("camera", "cam_a6810678")
    label  = body.get("label", "person")
    now = _time.time()
    if now - _notify_cooldown.get(camera, 0) < 90:
        return aiohttp_web.Response(
            text='{"ok":false,"reason":"cooldown"}',
            content_type="application/json", headers=_CORS_HEADERS)
    _notify_cooldown[camera] = now
    asyncio.create_task(_frigate_ha_notify_task(camera, label))
    return aiohttp_web.Response(
        text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS)


async def _frigate_ha_notify_task(camera: str, label: str):
    """Отправить снапшот → ждать 35с → отправить клип."""
    _LABELS = {"person": "👤 Человек", "car": "🚗 Авто", "dog": "🐕 Собака", "cat": "🐱 Кот"}
    label_str = _LABELS.get(label, f"📦 {label}")
    ts_str = datetime.now(MSK).strftime("%H:%M:%S")

    # 1. Снапшот из image entity
    photo_sent = False
    try:
        img_d = await ha_get(f"states/image.{camera}_{label}")
        if img_d:
            img_tok = img_d.get("attributes", {}).get("access_token", "")
            img_url = f"{HA_URL}/api/image_proxy/image.{camera}_{label}?token={img_tok}"
            async with _ha_cs() as sess:
                async with sess.get(img_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await bot.send_photo(
                            ADMIN_ID,
                            BufferedInputFile(data, "snapshot.jpg"),
                            caption=f"📷 <b>{label_str} у камеры!</b>\n🕐 {ts_str}",
                            parse_mode="HTML",
                        )
                        photo_sent = True
    except Exception as e:
        log.error(f"frigate_ha_notify snapshot: {e}")
    if not photo_sent:
        try:
            await bot.send_message(ADMIN_ID,
                f"📷 <b>{label_str} у камеры!</b> · {ts_str}", parse_mode="HTML")
        except Exception:
            pass

    # 2. Подождать: post_capture (30с) + время записи файла на диск
    await asyncio.sleep(50)

    # 3. Найти latest event через media_source WS
    try:
        import re as _re
        ha_ws = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
        async with websockets.connect(ha_ws, ping_interval=None, open_timeout=10, family=socket.AF_INET) as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if msg.get("type") == "auth_required":
                await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
                msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if msg.get("type") != "auth_ok":
                raise RuntimeError("WS auth failed")
            await ws.send(json.dumps({
                "id": 99, "type": "media_source/browse_media",
                "media_content_id": f"media-source://frigate/frigate/event-search/clips/{camera}////"
            }))
            msg = json.loads(await asyncio.wait_for(ws.recv(), 15))
            clips = msg.get("result", {}).get("children", [])
            if not clips:
                return
            latest_mcid = clips[0].get("media_content_id", "")
            event_id = latest_mcid.rsplit("/", 1)[-1] if "/" in latest_mcid else ""
            title = clips[0].get("title", "")  # "2026-03-09 22:19:20 [3s, Person 59%]"
            if not event_id:
                return

            # Парсим timestamp из title чтобы взять recording segment
            event_unix = 0
            m = _re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', title)
            if m:
                try:
                    event_unix = int(
                        datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                        .replace(tzinfo=MSK).timestamp()
                    )
                except Exception:
                    pass

            clip_data = None
            # Приоритет 1: recording segment (включает pre/post capture)
            if event_unix:
                seg_start = event_unix - 15        # 15с до события
                seg_end   = event_unix + 60        # 60с после начала
                for rec_url in [
                    f"{HA_URL}/api/frigate/api/recording/{camera}/start/{seg_start}/end/{seg_end}/",
                    f"{HA_URL}/api/frigate/api/recordings/explore/{camera}",
                ]:
                    try:
                        async with _ha_cs() as sess:
                            async with sess.get(rec_url, headers=HA_HEADERS,
                                                timeout=aiohttp.ClientTimeout(total=120)) as resp:
                                if resp.status == 200:
                                    data_candidate = await resp.read()
                                    if len(data_candidate) > 10_000:  # не пустой файл
                                        clip_data = data_candidate
                                        log.info(f"frigate clip from recording segment: {len(clip_data)} bytes")
                                        break
                    except Exception:
                        pass

            # Приоритет 2: прямой Frigate API events endpoint
            if not clip_data:
                for clip_url in [
                    f"{HA_URL}/api/frigate/api/events/{event_id}/clip.mp4",
                    f"{HA_URL}/api/frigate/notifications/{event_id}/clip.mp4",
                ]:
                    try:
                        async with _ha_cs() as sess:
                            async with sess.get(clip_url, headers=HA_HEADERS,
                                                timeout=aiohttp.ClientTimeout(total=120)) as resp:
                                if resp.status == 200:
                                    clip_data = await resp.read()
                                    log.info(f"frigate clip from {clip_url}: {len(clip_data)} bytes")
                                    break
                    except Exception:
                        pass

            if clip_data:
                await bot.send_video(
                    ADMIN_ID,
                    BufferedInputFile(clip_data, "clip.mp4"),
                    caption=f"🎬 <b>Клип</b> · {label_str}\n{title}",
                    parse_mode="HTML",
                )
                _activity_log("frigate_ha_clip_sent", event_id[:20])
            else:
                log.warning(f"frigate clip: no data for event {event_id}")
    except Exception as e:
        log.error(f"frigate_ha_notify clip: {e}")


async def _web_frigate_person_identified(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/frigate/person-identified — Frigate опознал члена семьи.
    Body: {camera, person, event_id}"""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
    except Exception:
        body = {}
    camera   = body.get("camera", "cam_a6810678")
    person   = body.get("person", "").strip()
    event_id = body.get("event_id", "").strip()
    if not person:
        return aiohttp_web.Response(
            text='{"ok":false,"error":"person required"}',
            content_type="application/json", headers=_CORS_HEADERS)
    asyncio.create_task(_frigate_person_identified_task(camera, person, event_id))
    return aiohttp_web.Response(
        text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS)


async def _frigate_person_identified_task(camera: str, person: str, event_id: str):
    """Отправить фото + подпись с именем опознанного человека."""
    _CAM_NAMES = {"cam_a6810678": "Подъезд"}
    cam_name = _CAM_NAMES.get(camera, camera)
    ts_str   = datetime.now(MSK).strftime("%H:%M")
    caption  = f"👤 <b>{person}</b> у камеры «{cam_name}»\n🕐 {ts_str}"

    photo_sent = False
    if event_id:
        try:
            snap_url = f"{HA_URL}/api/frigate/notifications/{event_id}/snapshot.jpg"
            async with _ha_cs() as sess:
                async with sess.get(snap_url, headers=HA_HEADERS,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await bot.send_photo(
                            ADMIN_ID,
                            BufferedInputFile(data, "snapshot.jpg"),
                            caption=caption,
                            parse_mode="HTML",
                        )
                        photo_sent = True
        except Exception as e:
            log.error(f"person_identified snapshot: {e}")

    if not photo_sent:
        try:
            await bot.send_message(ADMIN_ID, caption, parse_mode="HTML")
        except Exception as e:
            log.error(f"person_identified message: {e}")

    _faces_log(person, event_id, camera)
    _activity_log("frigate_person_identified", f"{person}@{camera}")


# ── Auth через логин/пароль Home Assistant ────────────────────────────────────
async def _web_ha_login(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/ha-login — авторизация через учётные данные HA.

    Проверяет логин/пароль через HA login_flow API.
    Возвращает токен доступа и роль пользователя (admin / viewer).
    """
    try:
        body = await request.json()
    except Exception:
        return aiohttp_web.Response(status=400,
            text='{"ok":false,"error":"bad request"}',
            content_type="application/json", headers=_CORS_HEADERS)

    username = body.get("username", "").strip()
    password = body.get("password", "")
    if not username or not password:
        return aiohttp_web.Response(
            text=json.dumps({"ok": False, "error": "Введите логин и пароль"}),
            content_type="application/json", headers=_CORS_HEADERS)

    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with _ha_cs(timeout=timeout) as s:
            # Шаг 1: начать login flow
            r1 = await s.post(f"{HA_URL}/auth/login_flow",
                json={"handler": ["homeassistant", None],
                      "redirect_uri": HA_URL + "/",
                      "client_id": HA_URL + "/"},
                ssl=False)
            d1 = await r1.json()
            flow_id = d1.get("flow_id")
            if not flow_id:
                raise ValueError("no flow_id")

            # Шаг 2: отправить учётные данные
            r2 = await s.post(f"{HA_URL}/auth/login_flow/{flow_id}",
                json={"username": username, "password": password,
                      "client_id": HA_URL + "/"},
                ssl=False)
            d2 = await r2.json()

            # Шаг 3: получить имя и аватар пользователя из HA (person entity)
            display_name = username
            avatar_url = None
            if d2.get("type") == "create_entry":
                try:
                    r4 = await s.get(f"{HA_URL}/api/states/person.{username.lower()}",
                        headers={"Authorization": f"Bearer {HA_TOKEN}"}, ssl=False)
                    if r4.status == 200:
                        ps = await r4.json()
                        attrs = ps.get("attributes") or {}
                        # friendly_name из person — реальное имя (напр. "Хамзат")
                        display_name = attrs.get("friendly_name") or username
                        ep = attrs.get("entity_picture")
                        if ep:
                            # Кешируем путь, отдаём прокси-URL (без HA credentials в браузере)
                            _user_avatar_cache[username] = ep
                            avatar_url = f"/ha-app/api/user-avatar/{username}"
                except Exception:
                    pass
    except Exception as e:
        log.error(f"ha_login: {e}")
        return aiohttp_web.Response(
            text=json.dumps({"ok": False, "error": "Ошибка подключения к HA"}),
            content_type="application/json", headers=_CORS_HEADERS)

    if d2.get("type") != "create_entry":
        return aiohttp_web.Response(
            text=json.dumps({"ok": False, "error": "Неверный логин или пароль"}),
            content_type="application/json", headers=_CORS_HEADERS)

    # Normalize username to lowercase to avoid duplicate records
    username = username.lower()
    # Роль определяется по списку HA_WEBAPP_ADMINS в .env
    role = "admin" if username in _HA_WEBAPP_ADMINS else "viewer"
    now_str = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")

    # Сохранить / обновить пользователя в webapp_users
    # Права: если уже есть запись — берём сохранённые права, иначе пустые (все по умолчанию)
    try:
        with _DB_LOCK:
            c = _db()
            row = c.execute(
                "SELECT permissions FROM webapp_users WHERE username=?", (username,)
            ).fetchone()
            perms_json = row[0] if row else "{}"
            c.execute("""
                INSERT INTO webapp_users (username, display_name, role, permissions, last_login)
                VALUES (?,?,?,?,?)
                ON CONFLICT(username) DO UPDATE SET
                    display_name=excluded.display_name,
                    role=excluded.role,
                    last_login=excluded.last_login
            """, (username, display_name, role, perms_json, now_str))
            c.commit()
        # Use _user_perms_load to get merged permissions with defaults
        perms = _user_perms_load(username)
    except Exception as e:
        log.warning(f"ha_login webapp_users: {e}")
        perms = dict(_PERM_DEFAULTS)

    log.info(f"ha_login: user '{username}' authenticated, role={role}, name='{display_name}'")
    return aiohttp_web.Response(
        text=json.dumps({"ok": True, "token": WEBAPP_TOKEN, "role": role,
                         "username": username, "display_name": display_name,
                         "avatar_url": avatar_url,
                         "permissions": perms}),
        content_type="application/json", headers=_CORS_HEADERS)


# ── Role Config (permissions for viewer role) ─────────────────────────────────
_PERM_DEFAULTS = {
    "status": True, "family": True, "presence": True,
    "faces": False, "energy": True, "lights": True,
    "climate": True, "tv": True, "vacuum": True,
    "prayers": True, "weather": True, "scenes": True,
    "shopping": True,
    "alerts": False, "nightmode": True, "server": False,
    "logbook": False, "activity": False,
    "devices": False, "cameras": False,
}

def _user_perms_load(username: str) -> dict:
    """Загрузить права конкретного пользователя (или defaults если нет записи)."""
    try:
        c = _db()
        row = c.execute("SELECT permissions FROM webapp_users WHERE username=?", (username,)).fetchone()
        if row:
            data = json.loads(row[0]) if row[0] else {}
            return {**_PERM_DEFAULTS, **data}
    except Exception:
        pass
    return dict(_PERM_DEFAULTS)

def _user_perms_save(username: str, perms: dict):
    """Сохранить права пользователя."""
    with _DB_LOCK:
        c = _db()
        c.execute("UPDATE webapp_users SET permissions=? WHERE username=?",
                  (json.dumps(perms), username))
        c.commit()

async def _web_family_users(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/family-users — список пользователей для назначения покупок (любой авторизованный)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        c = _db()
        rows = c.execute(
            "SELECT username, display_name FROM webapp_users ORDER BY display_name"
        ).fetchall()
        result = [{"username": r[0], "display_name": r[1] or r[0]} for r in rows]
    except Exception:
        result = []
    return aiohttp_web.Response(
        text=json.dumps(result, ensure_ascii=False),
        content_type="application/json", headers=_CORS_HEADERS)


async def _web_webapp_users(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/webapp-users — список пользователей мини апс (admin only)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    if request.headers.get("X-HA-User-Role", "") != "admin":
        return aiohttp_web.Response(status=403, text="Admin only", headers=_CORS_HEADERS)
    try:
        c = _db()
        rows = c.execute(
            "SELECT username, display_name, role, permissions, last_login FROM webapp_users ORDER BY last_login DESC"
        ).fetchall()
        result = [{"username": r[0], "display_name": r[1], "role": r[2],
                   "permissions": json.loads(r[3]) if r[3] else {},
                   "last_login": r[4]} for r in rows]
    except Exception:
        result = []
    return aiohttp_web.Response(
        text=json.dumps(result, ensure_ascii=False),
        content_type="application/json", headers=_CORS_HEADERS)

async def _web_webapp_user_delete(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """DELETE /ha-app/api/webapp-users/{username} — удалить пользователя (admin only)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    if request.headers.get("X-HA-User-Role", "") != "admin":
        return aiohttp_web.Response(status=403, text="Admin only", headers=_CORS_HEADERS)
    username = request.match_info.get("username", "").lower()
    requester = request.headers.get("X-HA-User", "").lower()
    if username == requester:
        return aiohttp_web.Response(status=400, text='{"error":"cannot delete yourself"}',
                                    content_type="application/json", headers=_CORS_HEADERS)
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("DELETE FROM webapp_users WHERE username=?", (username,))
            c.commit()
        log.info(f"webapp_user_delete: '{username}' removed by admin '{requester}'")
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)

async def _web_user_perms_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/user-perms?user=USERNAME — права пользователя."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    target = request.rel_url.query.get("user", "")
    requester = request.headers.get("X-HA-User", "")
    # Свои права — можно всегда, чужие — только admin
    if target != requester and request.headers.get("X-HA-User-Role", "") != "admin":
        return aiohttp_web.Response(status=403, text="Admin only", headers=_CORS_HEADERS)
    perms = _user_perms_load(target) if target else dict(_PERM_DEFAULTS)
    return aiohttp_web.Response(
        text=json.dumps(perms), content_type="application/json", headers=_CORS_HEADERS)

async def _web_user_perms_post(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/user-perms — сохранить права пользователя (admin only)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    if request.headers.get("X-HA-User-Role", "") != "admin":
        return aiohttp_web.Response(status=403, text="Admin only", headers=_CORS_HEADERS)
    try:
        body = await request.json()
    except Exception:
        return aiohttp_web.Response(status=400, text="Bad request", headers=_CORS_HEADERS)
    target = body.get("username", "")
    if not target:
        return aiohttp_web.Response(status=400, text="username required", headers=_CORS_HEADERS)
    perms = {k: bool(body.get(k, v)) for k, v in _PERM_DEFAULTS.items()}
    _user_perms_save(target, perms)
    return aiohttp_web.Response(text='{"ok":true}',
        content_type="application/json", headers=_CORS_HEADERS)

async def _web_activity_log_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/activity-all — full activity log with usernames (admin only)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    if request.headers.get("X-HA-User-Role", "") != "admin":
        return aiohttp_web.Response(status=403, text="Admin only", headers=_CORS_HEADERS)
    try:
        c = _db()
        rows = c.execute(
            "SELECT ts, action, detail, username FROM activity_log ORDER BY id DESC LIMIT 200"
        ).fetchall()
        result = [{"ts": r[0], "action": r[1], "detail": r[2], "username": r[3]} for r in rows]
    except Exception as e:
        result = []
    return aiohttp_web.Response(
        text=json.dumps(result, ensure_ascii=False),
        content_type="application/json", headers=_CORS_HEADERS)


# ── Auth (Telegram WebApp initData) ──────────────────────────────────────────
async def _web_auth_telegram(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/auth — валидация Telegram WebApp initData."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    init_data = body.get("initData", "")
    parsed = _validate_tg_initdata(init_data) if init_data else None
    if not parsed:
        return aiohttp_web.Response(
            status=401,
            text=json.dumps({"ok": False, "error": "invalid"}),
            content_type="application/json", headers=_CORS_HEADERS)
    user_raw = parsed.get("user", "{}")
    user = json.loads(user_raw) if isinstance(user_raw, str) else user_raw
    user_id = int(user.get("id", 0))
    allowed = _load_family_users()
    allowed_ids = {ADMIN_ID} | {int(uid) for uid in allowed.keys()}
    if user_id not in allowed_ids:
        return aiohttp_web.Response(
            status=403,
            text=json.dumps({"ok": False, "error": "forbidden"}),
            content_type="application/json", headers=_CORS_HEADERS)
    return aiohttp_web.Response(
        text=json.dumps({"ok": True, "token": WEBAPP_TOKEN}),
        content_type="application/json", headers=_CORS_HEADERS)


# ── История лиц (Faces History) ───────────────────────────────────────────────
async def _web_frigate_faces_history(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/frigate/faces-history — последние распознавания лиц."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        c = _db()
        rows = c.execute(
            "SELECT ts, person, event_id, camera FROM faces_log "
            "WHERE ts >= datetime('now', '-2 days') ORDER BY id DESC LIMIT 100"
        ).fetchall()
        result = []
        for r in rows:
            event_id = r[2] or ""
            # Use our proxy endpoint so <img> works without auth headers
            snap = (f"/ha-app/api/frigate/thumb/{event_id}" if event_id else "")
            result.append({"ts": r[0], "person": r[1], "event_id": event_id,
                           "camera": r[3], "snapshot_url": snap})
    except Exception as e:
        log.warning(f"faces-history: {e}")
        result = []
    return aiohttp_web.Response(
        text=json.dumps(result, ensure_ascii=False),
        content_type="application/json", headers=_CORS_HEADERS)


# ── Статистика присутствия ────────────────────────────────────────────────────
async def _web_presence_stats(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/presence-stats — время дома за 7 дней."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    family = {
        "Хамзат": "person.khamzat",
        "Айза":   "person.aiza",
        "Сулим":  "person.sulim",
        "Камила": "person.kamila",
    }
    now   = datetime.now(timezone.utc)
    start = (now - timedelta(days=7)).isoformat()
    eids  = ",".join(family.values())
    data, *live_states = await asyncio.gather(
        ha_get(f"history/period/{start}?filter_entity_id={eids}&minimal_response=true"),
        *[ha_get(f"states/{eid}") for eid in family.values()],
    )
    live_map = {eid: (d.get("state") if d else None) for eid, d in zip(family.values(), live_states)}
    result = []
    for name, eid in family.items():
        currently_home = live_map.get(eid) == "home"
        entity_hist = None
        if data and isinstance(data, list):
            for hist in data:
                if hist and hist[0].get("entity_id") == eid:
                    entity_hist = hist
                    break
        # Check if all history states are non-home (no tracker scenario)
        has_real_data = entity_hist and any(e.get("state") == "home" for e in entity_hist)
        if not entity_hist or not has_real_data:
            result.append({
                "name": name, "home_hours": 0, "home_pct": 0,
                "last_seen": None, "currently_home": currently_home,
                "no_tracker": not currently_home,
            })
            continue
        home_secs = 0.0
        prev_ts   = None
        prev_state = None
        for entry in entity_hist:
            ts_str = entry.get("last_changed") or entry.get("last_updated", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                continue
            if prev_ts and prev_state == "home":
                home_secs += (ts - prev_ts).total_seconds()
            prev_ts    = ts
            prev_state = entry.get("state", "")
        if prev_ts and prev_state == "home":
            home_secs += (now - prev_ts).total_seconds()
        total_secs = 7 * 24 * 3600
        home_pct   = round(home_secs / total_secs * 100)
        last_seen  = None
        for entry in reversed(entity_hist):
            if entry.get("state") == "home":
                last_seen = entry.get("last_changed") or entry.get("last_updated")
                break
        result.append({
            "name":       name,
            "home_hours": round(home_secs / 3600, 1),
            "home_pct":   home_pct,
            "last_seen":  last_seen,
            "currently_home": currently_home,
            "no_tracker": False,
        })
    return aiohttp_web.Response(
        text=json.dumps(result, ensure_ascii=False),
        content_type="application/json", headers=_CORS_HEADERS)


# ── Почасовое потребление энергии ─────────────────────────────────────────────
async def _web_energy_hourly(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/energy-hourly — среднее потребление по часам за 24ч (МСК)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    points = await ha_history("sensor.moshchnost_vsego_doma", hours=24, max_points=2000)
    hourly: dict[int, list] = {h: [] for h in range(24)}
    for ts, val in points:
        hourly[ts.hour].append(val)
    result = []
    for h in range(24):
        vals = hourly[h]
        if vals:
            result.append({"hour": h, "avg": round(sum(vals) / len(vals)), "max": round(max(vals))})
        else:
            result.append({"hour": h, "avg": 0, "max": 0})
    return aiohttp_web.Response(
        text=json.dumps(result, ensure_ascii=False),
        content_type="application/json", headers=_CORS_HEADERS)


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
            # Встроенные разделы удалять запрещено
            if sections.get(sect_id, {}).get("builtin"):
                return aiohttp_web.Response(status=403, text="Cannot delete builtin section",
                                            headers=_CORS_HEADERS)
            sections.pop(sect_id, None)
        else:
            if sect_id not in sections:
                max_ord = max((v.get("order", 0) for v in sections.values()), default=9) + 1
                sections[sect_id] = {"name": body.get("name", sect_id), "icon": body.get("icon", "📦"),
                                     "enabled": True, "order": max_ord}
            else:
                for field in ("name", "icon", "enabled", "order", "hidden"):
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

async def _frigate_notify(entry: dict):
    """Отправить уведомление в Telegram о новой детекции Frigate.

    Пытается получить снимок события и отправить его с подписью.
    Если снимок недоступен — отправляет только текст.

    Аргументы:
        entry: словарь события Frigate с полями:
            label       — тип объекта: "person", "car", "dog"...
            score       — уверенность детекции 0..100%
            camera      — имя камеры в Frigate
            start_time  — Unix timestamp начала события
            snapshot_url — URL снимка (через HA/Frigate API)
    """
    label_map = {"person": "👤 Человек", "car": "🚗 Авто", "dog": "🐕 Собака", "cat": "🐱 Кот"}
    label_str = label_map.get(entry.get("label", ""), f"📦 {entry.get('label', '')}")
    camera = entry.get("camera", "")
    score = entry.get("score", 0)
    ts_str = datetime.fromtimestamp(entry.get("ts", 0), tz=MSK).strftime("%H:%M:%S")
    caption = (f"🔔 <b>Детекция Frigate</b>\n"
               f"{label_str} · {score}%\n"
               f"📷 {camera} · {ts_str}")
    snap_url = entry.get("snapshot_url", "")
    if snap_url:
        try:
            async with _ha_cs() as sess:
                async with sess.get(snap_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await bot.send_photo(
                            ADMIN_ID,
                            BufferedInputFile(data, filename="detection.jpg"),
                            caption=caption, parse_mode="HTML"
                        )
                        return
        except Exception as e:
            log.warning(f"Frigate notify photo: {e}")
    try:
        await bot.send_message(ADMIN_ID, caption, parse_mode="HTML")
    except Exception as e:
        log.warning(f"Frigate notify msg: {e}")


async def _frigate_event_loop():
    """Фоновая задача: слушать события Frigate через HA WebSocket.

    Frigate интегрирован в HA и отправляет события через HA event bus.
    Эта задача подписывается на событие "frigate.new_tracking_object"
    и при каждом событии:
      1. Добавляет событие в _frigate_events (список последних 100)
      2. Кеширует список в файл frigate_events.json
      3. Вызывает _frigate_notify() — отправляет уведомление в Telegram

    При обрыве WebSocket соединения — автоматически переподключается.
    Если библиотека websockets не установлена — задача не запускается.
    """
    global _frigate_events
    _frigate_events = _frigate_events_load()
    if not HAS_WS:
        return
    ha_ws = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
    while True:
        try:
            async with websockets.connect(ha_ws, ping_interval=20, open_timeout=15, family=socket.AF_INET) as ws:
                await ws.recv()  # hello
                await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
                msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if msg.get("type") != "auth_ok":
                    log.warning("Frigate WS: auth failed")
                    await asyncio.sleep(30)
                    continue
                # Subscribe to frigate events
                await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "frigate.new_tracking_object"}))
                await ws.recv()
                await ws.send(json.dumps({"id": 2, "type": "subscribe_events", "event_type": "frigate.tracking_object_update"}))
                await ws.recv()
                log.info("Frigate event loop: subscribed to HA events")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if msg.get("type") != "event":
                            continue
                        evt = msg.get("event", {})
                        data = evt.get("data", {})
                        after = data.get("after", data)
                        eid = after.get("id") or after.get("event_id")
                        if not eid:
                            continue
                        camera  = after.get("camera", "")
                        label   = after.get("label", "")
                        score   = after.get("top_score") or after.get("score") or 0
                        ts      = after.get("start_time") or after.get("frame_time") or _time.time()
                        # Fix: use image_proxy with correct entity access_token
                        snapshot_url = ""
                        try:
                            img_eid = f"image.{camera}_{label}"
                            img_d = await ha_get(f"states/{img_eid}")
                            if img_d:
                                img_tok = img_d.get("attributes", {}).get("access_token", "")
                                snapshot_url = f"{HA_URL}/api/image_proxy/{img_eid}?token={img_tok}"
                        except Exception:
                            pass
                        is_new = not any(e.get("id") == eid for e in _frigate_events)
                        entry = {
                            "id": eid, "camera": camera, "label": label,
                            "score": round(float(score) * 100) if score else 0,
                            "ts": int(ts), "snapshot_url": snapshot_url,
                        }
                        # Deduplicate by id
                        _frigate_events = [e for e in _frigate_events if e.get("id") != eid]
                        _frigate_events.append(entry)
                        _frigate_events = _frigate_events[-200:]  # keep last 200
                        _frigate_events_save(_frigate_events)
                        # Auto-notify Telegram for new events with high confidence
                        if is_new and float(score or 0) > 0.5:
                            asyncio.create_task(_frigate_notify(entry))
                    except Exception as e:
                        log.debug(f"Frigate event parse: {e}")
        except Exception as e:
            log.warning(f"Frigate event loop reconnect: {e}")
            await asyncio.sleep(15)

# ── Server Stats (/ha-app/api/server-stats) ───────────────────────────────────
async def _web_server_stats(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/server-stats — CPU/RAM/Disk/uptime + service statuses."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        boot_ts = psutil.boot_time()
        uptime_sec = _time.time() - boot_ts
        uptime_days = int(uptime_sec // 86400)
        load_avg = list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else [0, 0, 0]

        def svc_status(name: str) -> str:
            try:
                r = subprocess.run(["systemctl", "is-active", name],
                                   capture_output=True, text=True, timeout=3)
                return r.stdout.strip() or "unknown"
            except Exception:
                return "unknown"

        def docker_status(container: str) -> str:
            try:
                r = subprocess.run(["docker", "inspect", "--format={{.State.Status}}", container],
                                   capture_output=True, text=True, timeout=5)
                return r.stdout.strip() or "unknown"
            except Exception:
                return "unknown"

        services = {
            "nginx":       svc_status("nginx"),
            "meshcentral": svc_status("meshcentral"),
            "ha-bot":      svc_status("ha-bot"),
            "awg-bot":     svc_status("awg-bot"),
            "remnawave":   docker_status("remnawave"),
            "awg":         docker_status("amnezia-awg"),
        }

        # HA hardware stats via system_monitor sensors
        ha_info: dict = {}
        try:
            ha_root = await ha_get("")
            ha_info["online"] = bool(ha_root)
        except Exception:
            ha_info["online"] = False
        try:
            (s_cpu, s_ram, s_disk, s_boot) = await asyncio.gather(
                ha_get("states/sensor.system_monitor_processor_use"),
                ha_get("states/sensor.system_monitor_memory_usage"),
                ha_get("states/sensor.system_monitor_disk_usage"),
                ha_get("states/sensor.system_monitor_last_boot"),
            )
            def _fv(d):
                try: return round(float(d["state"]), 1)
                except Exception: return None
            ha_info["cpu_percent"]  = _fv(s_cpu)
            ha_info["ram_percent"]  = _fv(s_ram)
            ha_info["disk_percent"] = _fv(s_disk)
            # compute uptime from last_boot timestamp
            if s_boot and s_boot.get("state") not in (None, "unknown", "unavailable"):
                from dateutil import parser as dtparser
                boot_dt = dtparser.parse(s_boot["state"])
                import datetime as _dt
                now_utc = _dt.datetime.now(_dt.timezone.utc)
                boot_dt = boot_dt.astimezone(_dt.timezone.utc) if boot_dt.tzinfo else boot_dt.replace(tzinfo=_dt.timezone.utc)
                uptime_sec_ha = (now_utc - boot_dt).total_seconds()
                ha_info["uptime_days"] = int(uptime_sec_ha // 86400)
        except Exception:
            pass

        payload = {
            "cpu_percent":  round(cpu, 1),
            "ram_percent":  round(ram.percent, 1),
            "ram_used_gb":  round(ram.used / 1024**3, 2),
            "ram_total_gb": round(ram.total / 1024**3, 2),
            "disk_percent": round(disk.percent, 1),
            "disk_used_gb": round(disk.used / 1024**3, 2),
            "disk_total_gb": round(disk.total / 1024**3, 2),
            "uptime_days":  uptime_days,
            "load_avg":     [round(x, 2) for x in load_avg],
            "services":     services,
            "ha":           ha_info,
        }
        return aiohttp_web.Response(
            text=json.dumps(payload, ensure_ascii=False),
            content_type="application/json", headers=_CORS_HEADERS,
        )
    except Exception as e:
        log.error(f"server_stats: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


# ── HA Logbook (/ha-app/api/logbook) ─────────────────────────────────────────
async def _web_logbook(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/logbook?hours=24 — HA logbook events, last 50."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        hours = int(request.query.get("hours", "24"))
        hours = max(1, min(hours, 168))
        start_dt = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        # Domain filter icons
        domain_icons = {
            "light": "💡", "switch": "🔌", "climate": "🌡️",
            "media_player": "📺", "person": "👤", "camera": "📹",
            "vacuum": "🤖", "automation": "🤖", "script": "📜",
            "cover": "🪟", "lock": "🔒", "input_boolean": "☑️",
        }
        _skip_states = {"unavailable", "unknown", "none", ""}
        raw = await ha_get(f"logbook/{start_dt}?entity_id=&limit=200")
        if not isinstance(raw, list):
            raw = []
        events = []
        for entry in raw:
            state = entry.get("state", "")
            if state in _skip_states:
                continue
            eid = entry.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else ""
            icon = domain_icons.get(domain, "📌")
            name = entry.get("name") or entry.get("entity_id", "")
            when_raw = entry.get("when", "")
            try:
                when_dt = datetime.fromisoformat(when_raw.replace("Z", "+00:00")).astimezone(MSK)
                when_str = when_dt.strftime("%H:%M")
            except Exception:
                when_str = when_raw[:5] if when_raw else "?"
            events.append({
                "entity_id": eid,
                "name": name,
                "state": state,
                "when": when_str,
                "when_iso": when_raw,
                "icon": icon,
                "domain": domain,
            })
        # newest first, limit 50
        events = list(reversed(events))[:50]
        return aiohttp_web.Response(
            text=json.dumps(events, ensure_ascii=False),
            content_type="application/json", headers=_CORS_HEADERS,
        )
    except Exception as e:
        log.error(f"logbook: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


# ── Night Mode (/ha-app/api/night-mode) ───────────────────────────────────────
def _night_mode_load() -> dict:
    try:
        row = _db().execute("SELECT value FROM config WHERE key='night_mode'").fetchone()
        if row:
            return json.loads(row[0])
    except Exception as e:
        log.error(f"night_mode_load: {e}")
    return {"enabled": False, "time": "22:00", "check_presence": True, "scene_id": ""}

def _night_mode_save(cfg: dict):
    try:
        with _DB_LOCK:
            c = _db()
            c.execute("INSERT OR REPLACE INTO config VALUES ('night_mode',?)",
                      (json.dumps(cfg, ensure_ascii=False),))
            c.commit()
    except Exception as e:
        log.error(f"night_mode_save: {e}")

async def _web_night_mode_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    cfg = _night_mode_load()
    return aiohttp_web.Response(
        text=json.dumps(cfg, ensure_ascii=False),
        content_type="application/json", headers=_CORS_HEADERS,
    )

async def _web_night_mode_post(request: aiohttp_web.Request) -> aiohttp_web.Response:
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        cfg = _night_mode_load()
        for k in ("enabled", "time", "check_presence", "scene_id"):
            if k in body:
                cfg[k] = body[k]
        _night_mode_save(cfg)

        # Create HA automation if enabled and scene_id provided
        if cfg.get("enabled") and cfg.get("scene_id"):
            scenes = _scenes_load()
            scene_id = cfg["scene_id"]
            scene = scenes.get(scene_id, {"name": scene_id, "actions": []})
            # Build night mode automation
            nm_time = cfg.get("time", "22:00")
            if len(nm_time) == 5:
                nm_time += ":00"
            trigger = [{"platform": "time", "at": nm_time}]
            conditions = []
            if cfg.get("check_presence"):
                conditions = [{"condition": "state", "entity_id": "person.khamzat", "state": "home"}]
            ha_actions = []
            for a in scene.get("actions", []):
                eid = a.get("entity_id", "")
                svc = a.get("service", "")
                if not eid or not svc or "." not in svc:
                    continue
                domain, service = svc.split(".", 1)
                ab: dict = {"service": f"{domain}.{service}", "target": {"entity_id": eid}}
                if a.get("extra"):
                    ab["data"] = a["extra"]
                ha_actions.append(ab)
            if ha_actions:
                payload = {
                    "alias": "Ночной режим (Mini App)",
                    "description": "Автоматизация ночного режима, создана через Mini App",
                    "trigger": trigger,
                    "condition": conditions,
                    "action": ha_actions,
                    "mode": "single",
                }
                try:
                    url = f"{HA_URL}/api/config/automation/config/miniapp_night_mode"
                    async with _ha_cs() as sess:
                        async with sess.post(url, headers=HA_HEADERS, json=payload,
                                             timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status in (200, 201):
                                try:
                                    await ha_call("automation", "reload", "")
                                except Exception:
                                    pass
                except Exception as e:
                    log.warning(f"night_mode_automation: {e}")

        _activity_log("night_mode_saved", str(cfg.get("enabled")))
        return aiohttp_web.Response(
            text='{"ok":true}', content_type="application/json", headers=_CORS_HEADERS,
        )
    except Exception as e:
        log.error(f"night_mode_post: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


# ── Presence notify (HA → webhook) ────────────────────────────────────────────
async def _web_presence_notify(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/presence-notify — called from HA automation."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body    = await request.json()
        person  = body.get("person", "")   # HA display name e.g. "Камила"
        state   = body.get("state", "")    # "home" or "not_home"
        username = body.get("username", "")
        if not person:
            return aiohttp_web.Response(status=400, text='{"error":"no person"}',
                                        content_type="application/json", headers=_CORS_HEADERS)
        # Normalize username from webapp_users
        c = _db()
        if not username:
            row = c.execute(
                "SELECT username FROM webapp_users WHERE username=? OR LOWER(display_name)=LOWER(?)",
                (person, person)
            ).fetchone()
            if row: username = row[0]
        emoji = "🏠" if state == "home" else "🚗"
        verb  = "пришёл(а) домой" if state == "home" else "покинул(а) дом"
        display = _get_display_name(username) if username else person
        title = f"{emoji} {display}"
        notif_body = f"{display} {verb}"
        # Push to everyone except the person themselves
        rows = c.execute(
            "SELECT DISTINCT username FROM push_subscriptions"
        ).fetchall()
        tasks = []
        for row in rows:
            u = row[0]
            if u != username:
                tasks.append(asyncio.create_task(
                    push_notify(u, title, notif_body, "/ha-app/")
                ))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        log.info(f"presence_notify: {display} → {state}, notified {len(tasks)} users")
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"presence_notify: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


# ── TV ADB key commands ────────────────────────────────────────────────────────
_TV_KEY_MAP = {
    "up":     "KEYCODE_DPAD_UP",
    "down":   "KEYCODE_DPAD_DOWN",
    "left":   "KEYCODE_DPAD_LEFT",
    "right":  "KEYCODE_DPAD_RIGHT",
    "ok":     "KEYCODE_DPAD_CENTER",
    "home":   "KEYCODE_HOME",
    "back":   "KEYCODE_BACK",
    "menu":   "KEYCODE_MENU",
    "power":  "KEYCODE_POWER",
    "mute":   "KEYCODE_MUTE",
    "vol_up": "KEYCODE_VOLUME_UP",
    "vol_dn": "KEYCODE_VOLUME_DOWN",
    "play":   "KEYCODE_MEDIA_PLAY_PAUSE",
    "prev":   "KEYCODE_MEDIA_PREVIOUS",
    "next":   "KEYCODE_MEDIA_NEXT",
}

async def _web_tv_key(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/tv/key — send ADB keyevent to Android TV."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body = await request.json()
        key  = body.get("key", "")
        keycode = _TV_KEY_MAP.get(key)
        if not keycode:
            return aiohttp_web.Response(status=400, text='{"error":"unknown key"}',
                                        content_type="application/json", headers=_CORS_HEADERS)
        # Try androidtv.adb_command first, fall back to media_player service
        try:
            await ha_post("services/androidtv/adb_command",
                          {"entity_id": TV_EID, "command": f"input keyevent {keycode}"})
        except Exception:
            # Fallback: map basic keys to media_player services
            fallback = {
                "KEYCODE_DPAD_UP": ("media_player", "media_next_track"),
                "KEYCODE_DPAD_DOWN": ("media_player", "media_previous_track"),
                "KEYCODE_HOME": ("media_player", "select_source", {"source": "Home"}),
                "KEYCODE_MEDIA_PLAY_PAUSE": ("media_player", "media_play_pause"),
            }
            if keycode in fallback:
                fb = fallback[keycode]
                await ha_call(fb[0], fb[1], TV_EID, fb[2] if len(fb) > 2 else {})
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


# ── Reminders ─────────────────────────────────────────────────────────────────
async def _web_reminders(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET/POST /ha-app/api/reminders"""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    username = request.headers.get("X-HA-User", "")
    if request.method == "POST":
        try:
            from datetime import datetime as _dt
            body       = await request.json()
            text       = body.get("text", "")[:200]
            remind_at  = body.get("remind_at", "").replace("T", " ")[:16]  # normalize "YYYY-MM-DDTHH:MM" → "YYYY-MM-DD HH:MM"
            is_global  = int(bool(body.get("is_global", False)))
            if not text or not remind_at:
                return aiohttp_web.Response(status=400, text='{"error":"missing fields"}',
                                            content_type="application/json", headers=_CORS_HEADERS)
            now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            with _DB_LOCK:
                c = _db()
                c.execute(
                    "INSERT INTO reminders(username,text,remind_at,is_global,created_at) VALUES(?,?,?,?,?)",
                    (username, text, remind_at, is_global, now_str)
                )
                rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                c.commit()
            return aiohttp_web.Response(
                text=json.dumps({"ok": True, "id": rid}, ensure_ascii=False),
                content_type="application/json", headers=_CORS_HEADERS)
        except Exception as e:
            return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)
    # GET
    try:
        c = _db()
        rows = c.execute(
            "SELECT id,username,text,remind_at,is_global,done,created_at FROM reminders "
            "WHERE done=0 AND (username=? OR is_global=1) ORDER BY remind_at",
            (username,)
        ).fetchall()
        result = [{"id": r[0], "username": r[1], "text": r[2], "remind_at": r[3],
                   "is_global": bool(r[4]), "done": bool(r[5])} for r in rows]
        return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False),
                                    content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_reminders_delete(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """DELETE /ha-app/api/reminders/{id}"""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        rid      = int(request.match_info["id"])
        username = request.headers.get("X-HA-User", "")
        with _DB_LOCK:
            c = _db()
            # Admin can delete any; user can delete own
            if username in _HA_WEBAPP_ADMINS:
                c.execute("DELETE FROM reminders WHERE id=?", (rid,))
            else:
                c.execute("DELETE FROM reminders WHERE id=? AND username=?", (rid, username))
            c.commit()
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _reminders_check_loop():
    """Background task: check due reminders every 60s and send push."""
    await asyncio.sleep(10)  # initial delay
    while True:
        try:
            from datetime import datetime as _dt
            now = _dt.now().strftime("%Y-%m-%d %H:%M")
            c   = _db()
            rows = c.execute(
                "SELECT id, username, text, is_global FROM reminders "
                "WHERE done=0 AND remind_at<=?", (now,)
            ).fetchall()
            for row in rows:
                rid, uname, text, is_global = row[0], row[1], row[2], row[3]
                title = "⏰ Напоминание"
                body  = text
                if is_global:
                    await push_notify(None, title, body, "/ha-app/")
                else:
                    await push_notify(uname, title, body, "/ha-app/")
                with _DB_LOCK:
                    _db().execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
                    _db().commit()
                log.info(f"reminder fired: id={rid} user={uname!r} text={text!r}")
        except Exception as e:
            log.error(f"reminders_check_loop: {e}")
        await asyncio.sleep(60)


# ── Family Chat ───────────────────────────────────────────────────────────────
async def _sse_broadcast_chat(msg_data: dict):
    """Push chat message to all SSE clients."""
    global _sse_clients
    payload = json.dumps({"type": "chat", "msg": msg_data}, ensure_ascii=False)
    dead = set()
    for q in _sse_clients:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.add(q)
    _sse_clients -= dead


async def _web_chat(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET/POST /ha-app/api/chat"""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    username = request.headers.get("X-HA-User", "")
    if request.method == "POST":
        try:
            from datetime import datetime as _dt
            body = await request.json()
            text = body.get("text", "").strip()[:500]
            if not text:
                return aiohttp_web.Response(status=400, text='{"error":"empty"}',
                                            content_type="application/json", headers=_CORS_HEADERS)
            now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            with _DB_LOCK:
                c = _db()
                c.execute(
                    "INSERT INTO chat_messages(username,text,created_at) VALUES(?,?,?)",
                    (username, text, now_str)
                )
                mid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                c.commit()
            display_name = _get_display_name(username)
            msg_data = {"id": mid, "username": username, "display_name": display_name,
                        "text": text, "created_at": now_str}
            asyncio.create_task(_sse_broadcast_chat(msg_data))
            # Push to others who are not online
            rows = _db().execute(
                "SELECT DISTINCT username FROM push_subscriptions WHERE username!=?", (username,)
            ).fetchall()
            for row in rows:
                asyncio.create_task(push_notify(
                    row[0], f"💬 {display_name}", text, "/ha-app/"
                ))
            return aiohttp_web.Response(
                text=json.dumps({"ok": True, "id": mid}, ensure_ascii=False),
                content_type="application/json", headers=_CORS_HEADERS)
        except Exception as e:
            return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)
    # GET — last N messages
    try:
        limit = min(int(request.rel_url.query.get("limit", "50")), 200)
        c = _db()
        rows = c.execute(
            "SELECT id,username,text,created_at,msg_type,voice_file FROM chat_messages "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        rows = list(reversed(rows))
        result = [{"id": r[0], "username": r[1],
                   "display_name": _get_display_name(r[1]),
                   "text": r[2], "created_at": r[3],
                   "msg_type": r[4] or "text", "voice_file": r[5] or ""} for r in rows]
        return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False),
                                    content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_chat_clear(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """DELETE /ha-app/api/chat — clear all chat messages (admin only)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    role = request.headers.get("X-HA-User-Role", "viewer")
    if role != "admin":
        return aiohttp_web.Response(status=403, text="Admin only", headers=_CORS_HEADERS)
    try:
        with _DB_LOCK:
            c = _db()
            # Collect voice files to delete
            rows = c.execute("SELECT voice_file FROM chat_messages WHERE voice_file!=''").fetchall()
            c.execute("DELETE FROM chat_messages")
            c.commit()
        for (vf,) in rows:
            try:
                (VOICES_DIR / vf).unlink(missing_ok=True)
            except Exception:
                pass
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _chat_cleanup_loop():
    """Delete chat messages older than 3 days every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            from datetime import datetime as _dt, timedelta as _td
            cutoff = (_dt.now() - _td(days=3)).strftime("%Y-%m-%d %H:%M:%S")
            with _DB_LOCK:
                c = _db()
                rows = c.execute(
                    "SELECT voice_file FROM chat_messages WHERE created_at < ? AND voice_file!=''",
                    (cutoff,)
                ).fetchall()
                c.execute("DELETE FROM chat_messages WHERE created_at < ?", (cutoff,))
                c.commit()
            for (vf,) in rows:
                try:
                    (VOICES_DIR / vf).unlink(missing_ok=True)
                except Exception:
                    pass
            # Also clean activity_log and family_reactions older than 3 days
            with _DB_LOCK:
                c = _db()
                c.execute("DELETE FROM activity_log WHERE ts < ?", (cutoff,))
                c.execute("DELETE FROM family_reactions WHERE created_at < ?", (cutoff,))
                c.commit()
        except Exception as e:
            log.warning(f"chat_cleanup_loop: {e}")


# ── Photo Album ───────────────────────────────────────────────────────────────
async def _web_photos_upload(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/photos/upload — multipart file upload."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        import uuid as _uuid
        from datetime import datetime as _dt
        username = request.headers.get("X-HA-User", "")
        reader   = await request.multipart()
        filename = None
        caption  = ""
        async for part in reader:
            if part.name == "photo":
                ext = (part.filename or "img.jpg").rsplit(".", 1)[-1].lower()
                if ext not in ("jpg", "jpeg", "png", "gif", "webp", "heic"):
                    continue
                safe_name = f"{_uuid.uuid4().hex}.{ext}"
                path = PHOTOS_DIR / safe_name
                with open(path, "wb") as f:
                    while True:
                        chunk = await part.read_chunk(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                filename = safe_name
            elif part.name == "caption":
                caption = (await part.read()).decode("utf-8", errors="replace")[:200]
        if not filename:
            return aiohttp_web.Response(status=400, text='{"error":"no file"}',
                                        content_type="application/json", headers=_CORS_HEADERS)
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        with _DB_LOCK:
            c = _db()
            c.execute(
                "INSERT INTO photos(username,filename,caption,created_at) VALUES(?,?,?,?)",
                (username, filename, caption, now_str)
            )
            pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.commit()
        return aiohttp_web.Response(
            text=json.dumps({"ok": True, "id": pid, "filename": filename}, ensure_ascii=False),
            content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"photos_upload: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_photos_list(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/photos"""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        limit = min(int(request.rel_url.query.get("limit", "40")), 100)
        c = _db()
        rows = c.execute(
            "SELECT id,username,filename,caption,created_at FROM photos ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        result = [{"id": r[0], "username": r[1], "display_name": _get_display_name(r[1]),
                   "url": f"/ha-app/api/photos/img/{r[2]}",
                   "caption": r[3], "created_at": r[4]} for r in rows]
        return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False),
                                    content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_photos_serve(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/photos/img/{filename} — serve photo."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    filename = request.match_info.get("filename", "")
    # Sanitize: only allow safe filenames
    if not filename or "/" in filename or ".." in filename:
        return aiohttp_web.Response(status=400, text="Bad filename", headers=_CORS_HEADERS)
    path = PHOTOS_DIR / filename
    if not path.exists():
        return aiohttp_web.Response(status=404, text="Not found", headers=_CORS_HEADERS)
    ext = filename.rsplit(".", 1)[-1].lower()
    ct  = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
           "gif": "image/gif", "webp": "image/webp", "heic": "image/heic"}.get(ext, "image/jpeg")
    return aiohttp_web.Response(body=path.read_bytes(), content_type=ct,
                                headers={**_CORS_HEADERS, "Cache-Control": "max-age=86400"})


async def _web_photos_delete(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """DELETE /ha-app/api/photos/{id}"""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        pid      = int(request.match_info["id"])
        username = request.headers.get("X-HA-User", "")
        c = _db()
        row = c.execute("SELECT username,filename FROM photos WHERE id=?", (pid,)).fetchone()
        if not row:
            return aiohttp_web.Response(status=404, text='{"error":"not found"}',
                                        content_type="application/json", headers=_CORS_HEADERS)
        if row[0] != username and username not in _HA_WEBAPP_ADMINS:
            return aiohttp_web.Response(status=403, text='{"error":"forbidden"}',
                                        content_type="application/json", headers=_CORS_HEADERS)
        try:
            (PHOTOS_DIR / row[1]).unlink(missing_ok=True)
        except Exception:
            pass
        with _DB_LOCK:
            _db().execute("DELETE FROM photos WHERE id=?", (pid,))
            _db().commit()
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


# ── Voice messages ───────────────────────────────────────────────────────────
async def _web_chat_voice_upload(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/chat/voice — upload voice message (webm/ogg/mp4 audio)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        import uuid as _uuid
        from datetime import datetime as _dt
        username = request.headers.get("X-HA-User", "")
        reader   = await request.multipart()
        filename = None
        async for part in reader:
            if part.name == "voice":
                orig_ext = (part.filename or "voice.webm").rsplit(".", 1)[-1].lower()
                ext = orig_ext if orig_ext in ("webm", "ogg", "mp4", "m4a", "aac", "wav") else "webm"
                safe_name = f"{_uuid.uuid4().hex}.{ext}"
                path = VOICES_DIR / safe_name
                with open(path, "wb") as f:
                    while True:
                        chunk = await part.read_chunk(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                filename = safe_name
                break
        if not filename:
            return aiohttp_web.Response(status=400, text='{"error":"no file"}',
                                        content_type="application/json", headers=_CORS_HEADERS)
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        with _DB_LOCK:
            c = _db()
            c.execute(
                "INSERT INTO chat_messages(username,text,created_at,msg_type,voice_file) VALUES(?,?,?,?,?)",
                (username, "", now_str, "voice", filename)
            )
            mid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.commit()
        display = _get_display_name(username)
        msg_data = {"id": mid, "username": username, "display_name": display,
                    "text": "", "msg_type": "voice", "voice_file": filename, "created_at": now_str}
        await _sse_broadcast_chat(msg_data)
        asyncio.create_task(push_notify(None, f"🎤 {display}", "Голосовое сообщение", "/ha-app/"))
        return aiohttp_web.Response(
            text=json.dumps({"ok": True, "id": mid, "filename": filename}, ensure_ascii=False),
            content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"voice_upload: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _web_chat_voice_serve(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/chat/voice/{filename} — serve voice/image file."""
    if not _check_token_qs(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    filename = request.match_info.get("filename", "")
    if not filename or "/" in filename or ".." in filename:
        return aiohttp_web.Response(status=400, text="bad", headers=_CORS_HEADERS)
    path = VOICES_DIR / filename
    if not path.exists():
        return aiohttp_web.Response(status=404, text="not found", headers=_CORS_HEADERS)
    ext = filename.rsplit(".", 1)[-1].lower()
    ct = {"webm": "audio/webm", "ogg": "audio/ogg", "mp4": "audio/mp4",
          "m4a": "audio/mp4", "aac": "audio/aac", "wav": "audio/wav",
          "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
          "webp": "image/webp", "gif": "image/gif", "heic": "image/heic"}.get(ext, "application/octet-stream")
    return aiohttp_web.Response(body=path.read_bytes(), content_type=ct, headers=_CORS_HEADERS)


async def _web_chat_image_upload(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/chat/image — upload image to chat."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        import uuid as _uuid
        from datetime import datetime as _dt
        username = request.headers.get("X-HA-User", "")
        reader   = await request.multipart()
        filename = None
        async for part in reader:
            if part.name == "image":
                orig_name = part.filename or "photo.jpg"
                orig_ext  = orig_name.rsplit(".", 1)[-1].lower()
                ext = orig_ext if orig_ext in ("jpg","jpeg","png","webp","gif","heic") else "jpg"
                safe_name = f"{_uuid.uuid4().hex}.{ext}"
                path = VOICES_DIR / safe_name
                with open(path, "wb") as f:
                    while True:
                        chunk = await part.read_chunk(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                filename = safe_name
                break
        if not filename:
            return aiohttp_web.Response(status=400, text='{"error":"no file"}',
                                        content_type="application/json", headers=_CORS_HEADERS)
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        with _DB_LOCK:
            c = _db()
            c.execute(
                "INSERT INTO chat_messages(username,text,created_at,msg_type,voice_file) VALUES(?,?,?,?,?)",
                (username, "", now_str, "image", filename)
            )
            mid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.commit()
        display = _get_display_name(username)
        msg_data = {"id": mid, "username": username, "display_name": display,
                    "text": "", "msg_type": "image", "voice_file": filename, "created_at": now_str}
        await _sse_broadcast_chat(msg_data)
        asyncio.create_task(push_notify(None, f"📷 {display}", "Фото в чате", "/ha-app/"))
        return aiohttp_web.Response(
            text=json.dumps({"ok": True, "id": mid, "filename": filename}, ensure_ascii=False),
            content_type="application/json", headers=_CORS_HEADERS)
    except Exception as e:
        log.error(f"image_upload: {e}")
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


# ── Call history ──────────────────────────────────────────────────────────────
async def _web_call_history(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/call-history — last 50 calls."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        rows = _db().execute(
            "SELECT id,from_user,to_user,call_type,started_at,answered_at,ended_at,duration_sec,status "
            "FROM call_log ORDER BY id DESC LIMIT 50"
        ).fetchall()
        result = [{"id": r[0], "from_user": r[1], "to_user": r[2], "call_type": r[3],
                   "from_display": _get_display_name(r[1]), "to_display": _get_display_name(r[2]),
                   "started_at": r[4], "answered_at": r[5], "ended_at": r[6],
                   "duration_sec": r[7], "status": r[8]} for r in rows]
    except Exception as e:
        result = []
    return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False),
                                content_type="application/json", headers=_CORS_HEADERS)


# ── Activity Timeline ─────────────────────────────────────────────────────────
async def _web_timeline(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/timeline — unified activity timeline."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        c = _db()
        events = []
        # Activity log
        for r in c.execute(
            "SELECT ts,action,detail,username FROM activity_log ORDER BY id DESC LIMIT 100"
        ).fetchall():
            ts, action, detail, uname = r
            icon, title = _timeline_fmt(action, detail, uname)
            events.append({"ts": ts, "icon": icon, "title": title, "type": action})
        # Call log
        for r in c.execute(
            "SELECT started_at,from_user,to_user,call_type,status,duration_sec FROM call_log ORDER BY id DESC LIMIT 30"
        ).fetchall():
            started, fu, tu, ctype, status, dur = r
            fi = _get_display_name(fu); ti = _get_display_name(tu)
            status_icons = {"answered": "✅", "missed": "📵", "rejected": "❌"}
            cicon = "📹" if ctype == "video" else "📞"
            dur_str = f" ({dur//60}:{dur%60:02d})" if dur else ""
            events.append({"ts": started, "icon": cicon, "type": "call",
                           "title": f"{status_icons.get(status,'📞')} {fi} → {ti}{dur_str}"})
        # Sort all by timestamp DESC
        events.sort(key=lambda x: x["ts"], reverse=True)
        result = events[:80]
    except Exception as e:
        result = []
    return aiohttp_web.Response(text=json.dumps(result, ensure_ascii=False),
                                content_type="application/json", headers=_CORS_HEADERS)


def _timeline_fmt(action: str, detail: str, username: str) -> tuple[str, str]:
    """Format activity_log row into (icon, title) for timeline."""
    name = _get_display_name(username) if username else detail
    m = {
        "person_home":        ("🏠", f"{detail} вернулся домой"),
        "person_away":        ("🚗", f"{detail} ушёл из дома"),
        "bot_start":          ("🤖", "Бот перезапущен"),
        "night_mode_saved":   ("🌙", f"Ночной режим: {detail}"),
        "webapp:turn_on":     ("💡", f"{name} включил {detail}"),
        "webapp:turn_off":    ("💡", f"{name} выключил {detail}"),
        "webapp:vacuum:start":("🤖", f"{name} запустил пылесос"),
        "webapp:scene":       ("🎬", f"{name} активировал сцену {detail}"),
        "user_joined_invite": ("👤", f"Новый пользователь: {detail}"),
        "user_approved":      ("✅", f"Пользователь одобрен: {detail}"),
        "faces_detected":     ("📸", f"Распознано лицо: {detail}"),
    }
    if action in m:
        return m[action]
    if action.startswith("webapp:"):
        svc = action.replace("webapp:", "")
        return ("⚡", f"{name}: {svc} {detail}")
    return ("📋", f"{action}: {detail}")


# ── WebRTC TURN credentials ───────────────────────────────────────────────────
_TURN_SECRET = "ha_turn_secret_2026_kh"
_TURN_HOST   = "144.31.89.167"

async def _web_turn_creds(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/turn-creds — short-lived TURN credentials (RFC 5389 HMAC)."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    import time, hmac, hashlib, base64
    ttl  = 3600  # 1 hour
    ts   = int(time.time()) + ttl
    user = f"{ts}:webrtc"
    sig  = hmac.new(_TURN_SECRET.encode(), user.encode(), hashlib.sha1).digest()
    cred = base64.b64encode(sig).decode()
    data = {
        "urls":       [f"turn:{_TURN_HOST}:3478", f"turn:{_TURN_HOST}:3478?transport=tcp"],
        "username":   user,
        "credential": cred,
    }
    return aiohttp_web.Response(text=json.dumps(data, ensure_ascii=False),
                                content_type="application/json", headers=_CORS_HEADERS)


# ── WebRTC pending calls (missed offer storage) ────────────────────────────────
# {to_user: {from_user, from_display, payload, expires_at}}
_pending_calls: dict = {}
_call_sessions: dict = {}  # call_log_id → {from_user, to_user, answered_at}

async def _web_call_pending(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """GET /ha-app/api/call/pending — check if there's a waiting call offer."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    username = request.headers.get("X-HA-User", "")
    import time as _time
    now = _time.time()
    # Clean up expired
    expired = [u for u, c in _pending_calls.items() if c["expires_at"] < now]
    for u in expired:
        del _pending_calls[u]
    call = _pending_calls.get(username)
    if call and call["expires_at"] > now:
        return aiohttp_web.Response(
            text=json.dumps(call, ensure_ascii=False),
            content_type="application/json", headers=_CORS_HEADERS)
    return aiohttp_web.Response(text='null', content_type="application/json",
                                headers=_CORS_HEADERS)


# ── WebRTC Call Signaling ──────────────────────────────────────────────────────
async def _web_call_signal(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """POST /ha-app/api/call/signal — relay WebRTC signaling via SSE."""
    if not _check_token(request):
        return aiohttp_web.Response(status=401, text="Unauthorized", headers=_CORS_HEADERS)
    try:
        body    = await request.json()
        from_user = request.headers.get("X-HA-User", "")
        to_user   = body.get("to_user", "")
        sig_type  = body.get("type", "")   # offer | answer | ice | reject | hangup
        payload   = body.get("payload", {})
        if not to_user or not sig_type:
            return aiohttp_web.Response(status=400, text='{"error":"missing fields"}',
                                        content_type="application/json", headers=_CORS_HEADERS)
        # Normalize to_user: может прийти кириллица (display_name) вместо webapp username
        row = _db().execute(
            "SELECT username FROM webapp_users WHERE username=? OR LOWER(display_name)=LOWER(?)",
            (to_user, to_user)
        ).fetchone()
        if row:
            to_user = row[0]
        display = _get_display_name(from_user)
        log.info(f"call_signal: {from_user!r} → {to_user!r} type={sig_type!r}")
        event_data = json.dumps({
            "type": "call_signal",
            "from_user": from_user,
            "from_display": display,
            "to_user": to_user,
            "signal_type": sig_type,
            "payload": payload,
        }, ensure_ascii=False)
        global _sse_clients, _pending_calls, _call_sessions
        dead = set()
        for q in _sse_clients:
            try: q.put_nowait(event_data)
            except asyncio.QueueFull: dead.add(q)
        _sse_clients -= dead
        import time as _time
        call_type = payload.get("callType", "audio")
        now_str = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")
        if sig_type == "offer":
            _pending_calls[to_user] = {
                "from_user":    from_user,
                "from_display": display,
                "payload":      payload,
                "call_type":    call_type,
                "expires_at":   _time.time() + 60,
            }
            # Log call start
            with _DB_LOCK:
                c2 = _db()
                c2.execute(
                    "INSERT INTO call_log(from_user,to_user,call_type,started_at,status) VALUES(?,?,?,?,'missed')",
                    (from_user, to_user, call_type, now_str)
                )
                cid = c2.execute("SELECT last_insert_rowid()").fetchone()[0]
                c2.commit()
            _call_sessions[f"{from_user}:{to_user}"] = {"id": cid, "answered_at": None}
            asyncio.create_task(push_notify(to_user, f"📞 {display} звонит", "Входящий звонок", "/ha-app/"))
        elif sig_type == "answer":
            _pending_calls.pop(from_user, None)
            key = f"{to_user}:{from_user}"  # to_user is caller, from_user is callee
            if key in _call_sessions:
                _call_sessions[key]["answered_at"] = now_str
                with _DB_LOCK:
                    c2 = _db()
                    c2.execute("UPDATE call_log SET answered_at=?,status='answered' WHERE id=?",
                               (now_str, _call_sessions[key]["id"]))
                    c2.commit()
        elif sig_type in ("hangup", "reject"):
            _pending_calls.pop(to_user, None)
            key1 = f"{from_user}:{to_user}"
            key2 = f"{to_user}:{from_user}"
            key = key1 if key1 in _call_sessions else key2
            if key in _call_sessions:
                sess = _call_sessions.pop(key)
                dur = None
                if sess["answered_at"]:
                    from datetime import datetime as _dt2
                    try:
                        t0 = _dt2.strptime(sess["answered_at"], "%Y-%m-%d %H:%M:%S")
                        t1 = _dt2.strptime(now_str, "%Y-%m-%d %H:%M:%S")
                        dur = int((t1 - t0).total_seconds())
                    except Exception:
                        pass
                final_status = "rejected" if sig_type == "reject" else ("answered" if dur is not None else "missed")
                with _DB_LOCK:
                    c2 = _db()
                    c2.execute("UPDATE call_log SET ended_at=?,duration_sec=?,status=? WHERE id=?",
                               (now_str, dur, final_status, sess["id"]))
                    c2.commit()
        return aiohttp_web.Response(text='{"ok":true}', content_type="application/json",
                                    headers=_CORS_HEADERS)
    except Exception as e:
        return aiohttp_web.Response(status=500, text=str(e), headers=_CORS_HEADERS)


async def _start_web():
    """Запустить aiohttp веб-сервер для Mini App на 127.0.0.1:8766.

    Регистрирует все HTTP маршруты и запускает сервер.
    Сервер доступен только локально — nginx проксирует внешние запросы.

    Структура маршрутов:
      /ha-app/              — Mini App HTML
      /ha-app/api/health    — проверка работоспособности
      /ha-app/api/status    — состояние умного дома (кеш 5 сек)
      /ha-app/api/events    — SSE поток (real-time обновления)
      /ha-app/api/action    — вызов сервисов HA
      /ha-app/api/devices   — управление устройствами
      /ha-app/api/sections  — управление разделами
      /ha-app/api/scenes    — сцены (CRUD + запуск)
      /ha-app/api/alerts    — конфигурация алертов
      /ha-app/api/activity  — журнал активности
      /ha-app/api/frigate/* — проксирование камер Frigate
      /ha-app/api/server-stats — статистика сервера
      ... и другие
    """
    app = aiohttp_web.Application()
    app.router.add_get("/ha-app/",                  _web_index)
    app.router.add_get("/ha-app",                   _web_index)
    app.router.add_get("/ha-app/manifest.json",     _web_manifest)
    app.router.add_get("/ha-app/sw.js",             _web_sw)
    app.router.add_get("/ha-app/api/health",              _web_health)
    app.router.add_get("/ha-app/api/activity",            _web_activity)
    app.router.add_post("/ha-app/api/activity/clear",     _web_activity_clear)
    app.router.add_route("OPTIONS", "/ha-app/api/activity/clear", _web_options)
    app.router.add_get("/ha-app/api/alerts",              _web_alerts_get)
    app.router.add_post("/ha-app/api/alerts",             _web_alerts_post)
    app.router.add_get("/ha-app/api/scenes",              _web_scenes_get)
    app.router.add_post("/ha-app/api/scenes",             _web_scenes_post)
    app.router.add_delete("/ha-app/api/scenes/{scene_id}", _web_scenes_delete)
    app.router.add_post("/ha-app/api/scenes/{scene_id}/run", _web_scenes_run)
    app.router.add_get("/ha-app/api/events",              _web_sse)
    app.router.add_get("/ha-app/api/status",        _web_status)
    app.router.add_post("/ha-app/api/action",       _web_action)
    app.router.add_get("/ha-app/api/devices",       _web_devices_get)
    app.router.add_post("/ha-app/api/devices",      _web_devices_post)
    app.router.add_get("/ha-app/api/ha_scan",       _web_ha_scan)
    app.router.add_get("/ha-app/api/ha_entities",   _web_ha_entities)
    app.router.add_get("/ha-app/api/sections",                _web_sections_get)
    app.router.add_post("/ha-app/api/sections",               _web_sections_post)
    app.router.add_get("/ha-app/api/camera/{entity_id}",      _web_camera_info)
    app.router.add_get("/ha-app/api/frigate/events",          _web_frigate_events)
    app.router.add_get("/ha-app/api/frigate/recordings",          _web_frigate_recordings)
    app.router.add_get("/ha-app/api/frigate/clip/{event_id}",     _web_frigate_clip_proxy)
    app.router.add_get("/ha-app/api/frigate/thumb/{event_id}",    _web_frigate_thumb_proxy)
    app.router.add_post("/ha-app/api/frigate/send",               _web_frigate_send)
    app.router.add_post("/ha-app/api/frigate/notify-latest",      _web_frigate_notify_latest)
    app.router.add_post("/ha-app/api/frigate/person-identified",  _web_frigate_person_identified)
    app.router.add_get("/ha-app/api/frigate/faces-history",       _web_frigate_faces_history)
    app.router.add_post("/ha-app/api/auth",                       _web_auth_telegram)
    app.router.add_post("/ha-app/api/ha-login",                   _web_ha_login)
    app.router.add_route("OPTIONS", "/ha-app/api/ha-login",       _web_options)
    app.router.add_get("/ha-app/api/presence-stats",              _web_presence_stats)
    app.router.add_get("/ha-app/api/energy-hourly",               _web_energy_hourly)
    app.router.add_get("/ha-app/api/server-stats",                _web_server_stats)
    app.router.add_get("/ha-app/api/logbook",                     _web_logbook)
    app.router.add_get("/ha-app/api/night-mode",                  _web_night_mode_get)
    app.router.add_post("/ha-app/api/night-mode",                 _web_night_mode_post)
    app.router.add_route("OPTIONS", "/ha-app/api/server-stats",  _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/logbook",       _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/night-mode",    _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/frigate/notify-latest",     _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/frigate/person-identified", _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/frigate/faces-history",     _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/auth",                      _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/presence-stats",            _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/energy-hourly",             _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/camera/{entity_id}",   _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/frigate/events",       _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/frigate/recordings",       _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/frigate/clip/{event_id}",  _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/frigate/thumb/{event_id}", _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/frigate/send",             _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/status",       _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/action",       _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/devices",      _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/ha_scan",      _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/ha_entities",  _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/sections",     _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/activity",     _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/alerts",       _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/scenes",            _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/scenes/{scene_id}", _web_options)
    app.router.add_get("/ha-app/api/user-avatar/{username}", _web_user_avatar)
    app.router.add_get("/ha-app/api/family-users",  _web_family_users)
    app.router.add_route("OPTIONS", "/ha-app/api/family-users", _web_options)
    app.router.add_get("/ha-app/api/family-extra",     _web_family_extra)
    app.router.add_post("/ha-app/api/family-status",   _web_family_status_post)
    app.router.add_post("/ha-app/api/family-reaction",  _web_family_reaction)
    app.router.add_get("/ha-app/api/family-note",       _web_family_note)
    app.router.add_post("/ha-app/api/family-note",      _web_family_note)
    app.router.add_get("/ha-app/api/cooking",           _web_cooking)
    app.router.add_post("/ha-app/api/cooking",          _web_cooking)
    app.router.add_get("/ha-app/api/shopping-meta",     _web_shopping_meta)
    app.router.add_post("/ha-app/api/shopping-meta",    _web_shopping_meta)
    app.router.add_get("/ha-app/api/shopping-quick",    _web_shopping_quick)
    app.router.add_post("/ha-app/api/shopping-quick",   _web_shopping_quick)
    app.router.add_get("/ha-app/api/shopping-stats",    _web_shopping_stats)
    app.router.add_get("/ha-app/api/shopping-history",  _web_shopping_history)
    app.router.add_route("OPTIONS", "/ha-app/api/family-extra",     _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/family-status",    _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/family-reaction",  _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/family-note",      _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/cooking",          _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/shopping-meta",    _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/shopping-quick",   _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/shopping-stats",   _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/shopping-history", _web_options)
    app.router.add_get("/ha-app/api/webapp-users",  _web_webapp_users)
    app.router.add_delete("/ha-app/api/webapp-users/{username}", _web_webapp_user_delete)
    app.router.add_get("/ha-app/api/user-perms",    _web_user_perms_get)
    app.router.add_post("/ha-app/api/user-perms",   _web_user_perms_post)
    app.router.add_get("/ha-app/api/activity-all",  _web_activity_log_get)
    app.router.add_route("OPTIONS", "/ha-app/api/webapp-users", _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/user-perms",   _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/activity-all", _web_options)
    # Web Push
    app.router.add_get("/ha-app/api/vapid-key",           _web_vapid_key)
    app.router.add_post("/ha-app/api/push-subscribe",     _web_push_subscribe)
    app.router.add_delete("/ha-app/api/push-subscribe",   _web_push_unsubscribe)
    app.router.add_route("OPTIONS", "/ha-app/api/push-subscribe", _web_options)
    # Shopping assignments
    app.router.add_get("/ha-app/api/shopping-items",           _web_shopping_items)
    app.router.add_post("/ha-app/api/shopping-items",          _web_shopping_items)
    app.router.add_route("OPTIONS", "/ha-app/api/shopping-items", _web_options)
    app.router.add_get("/ha-app/api/shopping-assignments",    _web_shopping_assignments_get)
    app.router.add_post("/ha-app/api/shopping-assignments",   _web_shopping_assignments_post)
    app.router.add_route("OPTIONS", "/ha-app/api/shopping-assignments", _web_options)
    # ── Presence / TV / Reminders / Chat / Photos ──────────────────────────
    app.router.add_post("/ha-app/api/presence-notify",        _web_presence_notify)
    app.router.add_route("OPTIONS", "/ha-app/api/presence-notify", _web_options)
    app.router.add_post("/ha-app/api/tv/key",                 _web_tv_key)
    app.router.add_route("OPTIONS", "/ha-app/api/tv/key",     _web_options)
    app.router.add_get("/ha-app/api/reminders",               _web_reminders)
    app.router.add_post("/ha-app/api/reminders",              _web_reminders)
    app.router.add_delete("/ha-app/api/reminders/{id}",       _web_reminders_delete)
    app.router.add_route("OPTIONS", "/ha-app/api/reminders",  _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/reminders/{id}", _web_options)
    app.router.add_get("/ha-app/api/chat",                    _web_chat)
    app.router.add_post("/ha-app/api/chat",                   _web_chat)
    app.router.add_delete("/ha-app/api/chat",                 _web_chat_clear)
    app.router.add_route("OPTIONS", "/ha-app/api/chat",       _web_options)
    app.router.add_post("/ha-app/api/photos/upload",          _web_photos_upload)
    app.router.add_get("/ha-app/api/photos",                  _web_photos_list)
    app.router.add_get("/ha-app/api/photos/img/{filename}",   _web_photos_serve)
    app.router.add_delete("/ha-app/api/photos/{id}",          _web_photos_delete)
    app.router.add_post("/ha-app/api/chat/voice",             _web_chat_voice_upload)
    app.router.add_post("/ha-app/api/chat/image",             _web_chat_image_upload)
    app.router.add_get("/ha-app/api/chat/voice/{filename}",   _web_chat_voice_serve)
    app.router.add_get("/ha-app/api/call-history",            _web_call_history)
    app.router.add_get("/ha-app/api/timeline",                _web_timeline)
    app.router.add_route("OPTIONS", "/ha-app/api/chat/voice", _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/photos/upload", _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/photos",     _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/photos/img/{filename}", _web_options)
    app.router.add_route("OPTIONS", "/ha-app/api/photos/{id}", _web_options)
    app.router.add_post("/ha-app/api/call/signal",            _web_call_signal)
    app.router.add_route("OPTIONS", "/ha-app/api/call/signal", _web_options)
    app.router.add_get("/ha-app/api/call/pending",            _web_call_pending)
    app.router.add_route("OPTIONS", "/ha-app/api/call/pending", _web_options)
    app.router.add_get("/ha-app/api/turn-creds",              _web_turn_creds)
    app.router.add_route("OPTIONS", "/ha-app/api/turn-creds", _web_options)
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    site = aiohttp_web.TCPSite(runner, "127.0.0.1", 8766)
    await site.start()
    log.info("WebApp server started on 127.0.0.1:8766")

# ── /backup и /restore ────────────────────────────────────────────────────────
@dp.message(Command("backup"))
async def cmd_backup(msg: Message):
    if not is_admin(msg.from_user.id): return
    sent = 0
    # Экспорт devices из SQLite → JSON
    devices = _dev_load()
    if devices:
        content = json.dumps(devices, ensure_ascii=False, indent=2).encode()
        await msg.answer_document(BufferedInputFile(content, filename="devices.json"),
                                  caption="📦 devices.json")
        sent += 1
    # Экспорт activity_log из SQLite → JSON
    rows = _db().execute("SELECT ts,action,detail FROM activity_log ORDER BY id").fetchall()
    if rows:
        entries = [{"ts": r["ts"], "action": r["action"], "detail": r["detail"]} for r in rows]
        content = json.dumps(entries, ensure_ascii=False, indent=2).encode()
        await msg.answer_document(BufferedInputFile(content, filename="activity_log.json"),
                                  caption="📦 activity_log.json")
        sent += 1
    if sent == 0:
        await msg.answer("❌ Нет данных для бекапа")
    else:
        _activity_log("backup", f"sent {sent} files")

@dp.message(Command("restore"))
async def cmd_restore(msg: Message):
    if not is_admin(msg.from_user.id): return
    await msg.answer(
        "📥 Отправь JSON-файл для восстановления.\n"
        "Поддерживаемые файлы: <code>devices.json</code>, <code>sections.json</code>",
        parse_mode="HTML"
    )

@dp.message(F.document)
async def handle_document(msg: Message):
    if not is_admin(msg.from_user.id): return
    doc = msg.document
    if not doc or not doc.file_name or not doc.file_name.endswith(".json"):
        return
    fname = doc.file_name
    if fname not in ("devices.json", "sections.json"):
        await msg.answer(f"⚠️ Неизвестный файл: {fname}\nОжидается devices.json или sections.json")
        return
    try:
        file_info = await bot.get_file(doc.file_id)
        raw = await bot.download_file(file_info.file_path)
        data = json.loads(raw.read())  # validate JSON
        if fname == "devices.json":
            _dev_save(data)
            _dev_init()
            _activity_log("restore", "devices.json")
            await msg.answer(f"✅ <b>devices.json</b> восстановлен ({len(data)} устройств)", parse_mode="HTML")
        elif fname == "sections.json":
            _sect_save(data)
            _activity_log("restore", "sections.json")
            await msg.answer(f"✅ <b>sections.json</b> восстановлен ({len(data)} секций)", parse_mode="HTML")
    except Exception as e:
        await msg.answer(f"❌ Ошибка восстановления: {e}")

# ── /app command ──────────────────────────────────────────────────────────────
@dp.message(Command("app"))
async def cmd_app(msg: Message):
    if not is_admin(msg.from_user.id): return
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(
        text="🖥️ Открыть панель", web_app=WebAppInfo(url=WEBAPP_URL)
    )]], resize_keyboard=True, one_time_keyboard=True)
    await msg.answer("🖥️ Откройте панель управления:", reply_markup=kb)

# ── /link command — прямая ссылка для браузера (ПК, планшет) ─────────────────
@dp.message(Command("link"))
async def cmd_link(msg: Message):
    """Выдать персональную ссылку для открытия мини апс в браузере."""
    uid = msg.from_user.id
    allowed = _load_family_users()
    allowed_ids = {ADMIN_ID} | {int(u) for u in allowed.keys()}
    if uid not in allowed_ids:
        await msg.answer("⛔ Нет доступа")
        return
    # Токен передаётся в URL-фрагменте (#) — не попадает в логи сервера
    link = WEBAPP_URL
    await msg.answer(
        f"🔗 <b>Ссылка для браузера (ПК/планшет):</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Нажми на ссылку или скопируй в браузер. "
        f"После первого открытия браузер запомнит доступ навсегда.",
        parse_mode="HTML"
    )

# ── Inline кнопки: сцены из алертов ───────────────────────────────────────────
@dp.callback_query(F.data.startswith("scene:run:"))
async def cb_scene_run_alert(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    scene_id = cb.data.split(":", 2)[2]
    scenes = _scenes_load()
    scene = scenes.get(scene_id)
    if not scene:
        await cb.answer(f"❌ Сцена '{scene_id}' не найдена", show_alert=True)
        return
    errors = []
    for action in scene.get("actions", []):
        eid = action.get("entity_id", "")
        svc = action.get("service", "")
        extra = action.get("extra")
        if not eid or not svc or "." not in svc:
            continue
        domain, service = svc.split(".", 1)
        try:
            await ha_call(domain, service, eid, extra)
        except Exception as e:
            errors.append(str(e))
    _status_cache["ts"] = 0.0
    _activity_log("scene_run", scene.get("name", scene_id))
    name = scene.get("name", scene_id)
    icon = scene.get("icon", "🎬")
    if errors:
        await cb.answer(f"⚠️ {icon} {name}: частично", show_alert=False)
    else:
        await cb.answer(f"✅ {icon} {name} — включено!", show_alert=False)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

@dp.callback_query(F.data.startswith("namaz_ok:"))
async def cb_namaz_ok(cb: CallbackQuery):
    """Обработчик кнопки 'Понял' в напоминании о намазе.

    Убирает кнопку из сообщения после нажатия — чтобы не было соблазна
    нажать повторно и засорять интерфейс.
    """
    await cb.answer("✅ Принято!", show_alert=False)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

# ── Точка входа — запуск бота ─────────────────────────────────────────────────
async def main():
    """Главная функция: инициализация и запуск бота.

    Порядок запуска:
      1. _db_init()          — создать таблицы SQLite, мигрировать JSON→DB
      2. _dev_init()         — загрузить устройства, собрать LIGHTS dict
      3. _refresh_lights()   — запросить HA, добавить новые устройства
      4. alert_loop()        — фон: проверка алертов каждую минуту
      5. _start_web()        — фон: HTTP сервер Mini App на :8766
      6. _frigate_event_loop() — фон: WebSocket для событий Frigate
      7. _ha_state_watch_loop() — фон: WebSocket для SSE real-time
      8. dp.start_polling()  — основной цикл Telegram bot polling
    """
    log.info(f"HA Bot v{_BOT_VERSION} starting...")
    _db_init()             # создать таблицы SQLite + однократная миграция из JSON
    _dev_init()            # загрузить devices из DB → заполнить LIGHTS/LIGHTS_ICON
    await _refresh_lights()  # сканировать HA, добавить новые устройства
    asyncio.create_task(alert_loop())           # фоновая проверка алертов
    asyncio.create_task(_start_web())           # HTTP сервер Mini App
    asyncio.create_task(_frigate_event_loop())  # слушать события Frigate
    asyncio.create_task(_ha_state_watch_loop()) # SSE real-time обновления
    asyncio.create_task(_reminders_check_loop()) # проверка напоминаний каждые 60с
    asyncio.create_task(_chat_cleanup_loop())    # авто-удаление чата старше 3 дней
    _activity_log("bot_start", f"v{_BOT_VERSION}")
    await bot.send_message(
        ADMIN_ID,
        f"🏠 <b>Home Assistant Bot v{_BOT_VERSION} запущен!</b>\n"
        "✅ 🕌 Намаз: за 15 мин + за 5 мин\n"
        "✅ 🌐 Уведомление о падении интернета\n"
        "✅ 🌅 Утренняя сводка 07:30 МСК\n"
        "✅ 🏠 Трекинг всей семьи + сцены из алертов\n"
        "✅ 📊 Графики энергии / еженедельный отчёт\n"
        "✅ 📹 Frigate детекция + авто-уведомления\n"
        "✅ 💾 /backup /restore конфигов\n"
        "✅ 🖥️ Telegram Mini App панель управления",
        parse_mode="HTML"
    )
    _activity_log("bot_ready", f"v{_BOT_VERSION}")
    log.info("Start polling")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
