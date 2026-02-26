#!/usr/bin/env python3
"""
AmneziaWG Telegram Management Bot — Full Edition v2
Features: GeoIP, history, graphs, alerts, auto-delete, schedule, backup, invites
"""

import asyncio, json, os, re, subprocess, io, logging, time, shutil, secrets
import glob as glob_mod
import speedtest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

import aiohttp
import psutil
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, BufferedInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import qrcode

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ─── Config ───────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")
BOT_TOKEN = os.environ["BOT_TOKEN"]

AWG_CONF = "/opt/amnezia-awg-data/awg/wg0.conf"
AWG_DIR = "/opt/amnezia-awg-data/awg"
AWG_CONTAINER = "amnezia-awg"
DATA_DIR = "/opt/awg-bot"
DATA_FILE = f"{DATA_DIR}/clients.json"
ADMIN_FILE = f"{DATA_DIR}/admin.json"
LOG_FILE = f"{DATA_DIR}/audit.log"
BACKUP_DIR = f"{DATA_DIR}/backups"
HISTORY_FILE = f"{DATA_DIR}/history.json"
TRAFFIC_FILE = f"{DATA_DIR}/traffic_daily.json"
INVITES_FILE = f"{DATA_DIR}/invites.json"

SERVER_PUB_KEY = Path(f"{AWG_DIR}/server_public.key").read_text().strip()
SERVER_ENDPOINT = os.environ.get("SERVER_ENDPOINT", "144.31.89.167:9443")
SUBNET = "10.8.1"
DNS = "1.1.1.1"  # через тоннель — РКН не блокирует

# ─── WG (standard WireGuard for Keenetic) ────────────────────────────
WG_CONF = "/etc/amnezia/amneziawg/wg0.conf"
WG_IFACE = "wg0"
WG_SUBNET = "10.8.2"
WG_DNS = "1.1.1.1"  # через тоннель
WG_MTU = 1420
WG_PORT = 51820
WG_SERVER_ENDPOINT = os.environ.get("WG_SERVER_ENDPOINT", "144.31.89.167:51820")
_wg_pub_key_cache = ""
def _wg_server_pub() -> str:
    global _wg_pub_key_cache
    if not _wg_pub_key_cache:
        r = subprocess.run(["awg", "show", WG_IFACE, "public-key"], capture_output=True, text=True)
        _wg_pub_key_cache = r.stdout.strip() if r.returncode == 0 else ""
    return _wg_pub_key_cache

SERVERS = {
    "awg": {"label": "AmneziaWG (обход DPI)", "icon": "🛡", "iface": "wg0", "conf": AWG_CONF,
            "subnet": SUBNET, "dns": DNS, "mtu": 1240, "endpoint": SERVER_ENDPOINT},
}

MAX_BACKUPS = 10
CLIENTS_PER_PAGE = 8
CONFIG_AUTO_DELETE_SEC = 120
AUTO_DELETE_EXPIRED_DAYS = 7
MAX_HISTORY = 1000
TRAFFIC_KEEP_DAYS = 90
NOTIFY_CHECK_INTERVAL = 30
DAILY_REPORT_HOUR = 9
ALERT_CPU = 90
ALERT_RAM = 90
ALERT_DISK = 90

AWG_PARAMS = {
    "Jc": 3, "Jmin": 10, "Jmax": 50,
    "S1": 98, "S2": 91,
    "H1": 162950687, "H2": 1315283315,
    "H3": 1788245491, "H4": 1755245957,
}

# ─── udp2raw ──────────────────────────────────────────────────────────
UDP2RAW_SERVICE = "udp2raw"          # systemd unit name
UDP2RAW_PORT    = 4443               # TCP port that udp2raw listens on
UDP2RAW_KEY     = "3a74b69f6f34123c62d6b882adf87cc68d8578b726236582b895d1d1480014e2"
SERVER_IP       = "144.31.89.167"
_udp2raw_was_down = False            # watchdog state

BTN_CLIENTS   = "👥 Клиенты"
BTN_STATS     = "📊 Статистика"
BTN_ADD       = "➕ Новый клиент"
BTN_SERVER    = "🖥 Сервер"
BTN_SPEEDTEST = "⚡ Спидтест"
BTN_TOOLS     = "🔧 Инструменты"
BTN_VLESS     = "🔐 VLESS панель"
BTN_CANCEL    = "❌ Отмена"
RESERVED_TEXTS = {BTN_CANCEL, BTN_CLIENTS, BTN_STATS, BTN_ADD, BTN_SERVER, BTN_SPEEDTEST, BTN_TOOLS, BTN_VLESS}

# ─── Remnawave config ─────────────────────────────────────────────────
REMNAWAVE_URL   = "https://panelwin.mooo.com/api"
REMNAWAVE_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1dWlkIjoiNzEyYTI1NGUtOTk2OC00MGYxLTgzNzctZjgyODVmZWFlNmQ1IiwidXNlcm5hbWUiOm51bGwsInJvbGUiOiJBUEkiLCJpYXQiOjE3NzE0ODYyMDgsImV4cCI6MTA0MTEzOTk4MDh9.MwW_yE97OJfeTsSm2MX526n05WHDHmnxfF86qXy3S-c"
VLESS_PER_PAGE  = 8

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("awg-bot")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

_peer_online: dict[str, bool] = {}
_last_daily_report: str = ""
_geo_cache: dict[str, dict] = {}
_last_alert: dict[str, float] = {}  # alert_type -> timestamp


# ─── States ───────────────────────────────────────────────────────────

class AddClient(StatesGroup):
    waiting_server = State()
    waiting_name = State()

class SetExpiry(StatesGroup):
    waiting = State()

class SetLimit(StatesGroup):
    waiting = State()

class RenameClient(StatesGroup):
    waiting_name = State()

class AddVlessUser(StatesGroup):
    waiting_name = State()


# ─── Keyboards ────────────────────────────────────────────────────────

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_CLIENTS), KeyboardButton(text=BTN_STATS)],
        [KeyboardButton(text=BTN_ADD),     KeyboardButton(text=BTN_SERVER)],
        [KeyboardButton(text=BTN_SPEEDTEST), KeyboardButton(text=BTN_TOOLS)],
        [KeyboardButton(text=BTN_VLESS)],
    ],
    resize_keyboard=True, is_persistent=True,
)

CANCEL_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
    resize_keyboard=True,
)


def client_list_inline(clients: dict, page: int = 0) -> InlineKeyboardMarkup | None:
    stats = get_awg_stats()
    names = sorted(clients.keys())
    if not names:
        return None
    total_pages = max(1, (len(names) + CLIENTS_PER_PAGE - 1) // CLIENTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * CLIENTS_PER_PAGE
    page_names = names[start:start + CLIENTS_PER_PAGE]
    buttons = []
    for name in page_names:
        c = clients[name]
        icon = "⏸" if c.get("disabled") or c.get("_scheduled_off") else ("🟢" if _is_online(c, stats) else "⚪")
        srv_icon = SERVERS.get(c.get("server", "awg"), SERVERS["awg"])["icon"]
        buttons.append([InlineKeyboardButton(text=f"{icon}{srv_icon} {name}", callback_data=f"cl:{name}")])
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"page:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"page:{page+1}"))
        buttons.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def client_detail_inline(name: str, client: dict) -> InlineKeyboardMarkup:
    disabled = client.get("disabled", False)
    t_text = "▶️ Вкл" if disabled else "⏸ Выкл"
    t_cb = f"enable:{name}" if disabled else f"disable:{name}"
    sched_icon = "📅" if client.get("schedule") else "🕐"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Конфиг", callback_data=f"conf:{name}"),
         InlineKeyboardButton(text="📱 QR", callback_data=f"qr:{name}")],
        [InlineKeyboardButton(text="🌐 Keenetic", callback_data=f"keen:{name}")],
        [InlineKeyboardButton(text=t_text, callback_data=t_cb),
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{name}")],
        [InlineKeyboardButton(text="✏️ Имя", callback_data=f"rename:{name}"),
         InlineKeyboardButton(text="🔄 Ключи", callback_data=f"rekey:{name}")],
        [InlineKeyboardButton(text="⏰ Срок", callback_data=f"expiry:{name}"),
         InlineKeyboardButton(text="📦 Лимит", callback_data=f"limit:{name}")],
        [InlineKeyboardButton(text="📜 История", callback_data=f"hist:{name}"),
         InlineKeyboardButton(text=f"{sched_icon} Расписание", callback_data=f"sched:{name}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_list")],
    ])


# ─── Admin / Audit ───────────────────────────────────────────────────

def load_admin() -> dict:
    try:
        with open(ADMIN_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_admin(d):
    with open(ADMIN_FILE, "w") as f:
        json.dump(d, f, indent=2)

def is_admin(uid: int) -> bool:
    d = load_admin()
    if not d.get("admin_id"):
        return True  # не заблокирован ещё — первый пользователь станет суперадмином
    if d["admin_id"] == uid:
        return True
    return str(uid) in d.get("admins", {})

def is_superadmin(uid: int) -> bool:
    d = load_admin()
    return not d.get("admin_id") or d["admin_id"] == uid

def lock_admin(uid: int, uname: str):
    d = load_admin()
    if not d.get("admin_id"):
        d.update(admin_id=uid, username=uname, locked_at=datetime.now(timezone.utc).isoformat())
        if "admins" not in d:
            d["admins"] = {}
        save_admin(d)
        return True
    return False

def get_admin_id() -> int | None:
    return load_admin().get("admin_id")

def get_subadmins() -> dict:
    return load_admin().get("admins", {})

def add_subadmin(uid: int, uname: str, added_by: int) -> bool:
    d = load_admin()
    if not d.get("admin_id"):
        return False
    if "admins" not in d:
        d["admins"] = {}
    d["admins"][str(uid)] = {
        "username": uname,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "added_by": added_by,
    }
    save_admin(d)
    return True

def remove_subadmin(uid: int) -> bool:
    d = load_admin()
    if str(uid) in d.get("admins", {}):
        del d["admins"][str(uid)]
        save_admin(d)
        return True
    return False

def audit(uid: int, action: str, detail: str = ""):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] uid={uid} | {action} | {detail}\n")


# ─── Backup ──────────────────────────────────────────────────────────

def create_backup(reason: str = ""):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for src, prefix in [(DATA_FILE, "clients"), (AWG_CONF, "awg0")]:
        if os.path.exists(src):
            shutil.copy2(src, f"{BACKUP_DIR}/{prefix}_{ts}.json" if "client" in prefix else f"{BACKUP_DIR}/{prefix}_{ts}.conf")
    for ext in ("*.json", "*.conf"):
        files = sorted(glob_mod.glob(f"{BACKUP_DIR}/{ext}"), key=os.path.getmtime)
        while len(files) > MAX_BACKUPS:
            os.remove(files.pop(0))


# ─── Data helpers ─────────────────────────────────────────────────────

def load_clients() -> dict:
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_clients(clients: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(clients, f, indent=2, ensure_ascii=False)

def next_ip(clients: dict, server: str = "awg") -> str:
    subnet = SERVERS[server]["subnet"]
    used = {c["ip"] for c in clients.values() if c.get("server", "awg") == server}
    used.add(f"{subnet}.1")
    for i in range(2, 255):
        ip = f"{subnet}.{i}"
        if ip not in used:
            return ip
    raise RuntimeError("No free IPs")

def _docker_awg(*args, stdin: bytes = None) -> subprocess.CompletedProcess:
    cmd = ["docker", "exec"]
    if stdin is not None:
        cmd.append("-i")
    cmd.append(AWG_CONTAINER)
    cmd.extend(args)
    return subprocess.run(cmd, input=stdin, capture_output=True)

def gen_keys() -> tuple:
    priv = _docker_awg("wg", "genkey").stdout.decode().strip()
    pub = _docker_awg("wg", "pubkey", stdin=priv.encode()).stdout.decode().strip()
    psk = _docker_awg("wg", "genpsk").stdout.decode().strip()
    return priv, pub, psk

def _restore_awg_params(server: str = "awg"):
    """Re-apply AWG obfuscation params after wg set (which resets them)."""
    if server != "awg":
        return
    p = AWG_PARAMS
    iface = SERVERS[server]["iface"]
    _docker_awg("wg", "set", iface,
                "jc", str(p["Jc"]), "jmin", str(p["Jmin"]), "jmax", str(p["Jmax"]),
                "s1", str(p["S1"]), "s2", str(p["S2"]),
                "h1", str(p["H1"]), "h2", str(p["H2"]),
                "h3", str(p["H3"]), "h4", str(p["H4"]))

def add_peer_to_server(pub, psk, ip, name, server: str = "awg"):
    conf = SERVERS[server]["conf"]
    iface = SERVERS[server]["iface"]
    allowed = f"{ip}/32"
    with open(conf, "a") as f:
        f.write(f"\n# {name}\n[Peer]\nPublicKey = {pub}\nPresharedKey = {psk}\nAllowedIPs = {allowed}\n")
    _docker_awg("wg", "set", iface, "peer", pub, "preshared-key", "/dev/stdin", "allowed-ips", allowed,
                stdin=psk.encode())
    _restore_awg_params(server)

def remove_peer_live(pub, server: str = "awg"):
    iface = SERVERS[server]["iface"]
    _docker_awg("wg", "set", iface, "peer", pub, "remove")
    _restore_awg_params(server)

def restore_peer_live(pub, psk, ip, server: str = "awg"):
    iface = SERVERS[server]["iface"]
    _docker_awg("wg", "set", iface, "peer", pub, "preshared-key", "/dev/stdin", "allowed-ips", f"{ip}/32",
                stdin=psk.encode())
    _restore_awg_params(server)

def remove_peer_from_config(pub, server: str = "awg"):
    conf = SERVERS[server]["conf"]
    lines = Path(conf).read_text().splitlines()
    new, skip = [], False
    for i, line in enumerate(lines):
        if line.strip() == "[Peer]":
            end = len(lines)
            for j in range(i+1, len(lines)):
                if lines[j].strip().startswith("["):
                    end = j; break
            if pub in "\n".join(lines[i:end]):
                if new and new[-1].startswith("#"):
                    new.pop()
                skip = True; continue
        if skip:
            if line.strip().startswith("["):
                skip = False; new.append(line)
            continue
        new.append(line)
    Path(conf).write_text("\n".join(new) + "\n")

def update_peer_comment_in_config(old, new_name, server: str = "awg"):
    conf = SERVERS[server]["conf"]
    t = Path(conf).read_text()
    Path(conf).write_text(t.replace(f"# {old}\n", f"# {new_name}\n"))


# ─── GeoIP ───────────────────────────────────────────────────────────

async def geoip_lookup(ip: str) -> dict:
    """Returns {country, city, country_code} or empty dict."""
    clean_ip = ip.split(":")[0] if ":" in ip and "." in ip else ip
    if clean_ip in _geo_cache:
        cached = _geo_cache[clean_ip]
        if time.time() - cached.get("_ts", 0) < 3600:
            return cached
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
            async with s.get(f"http://ip-api.com/json/{clean_ip}?fields=country,city,countryCode&lang=ru") as r:
                if r.status == 200:
                    data = await r.json()
                    data["_ts"] = time.time()
                    _geo_cache[clean_ip] = data
                    return data
    except Exception:
        pass
    return {}

def geo_flag(code: str) -> str:
    if not code or len(code) != 2:
        return "🌍"
    return chr(0x1F1E6 + ord(code[0]) - ord('A')) + chr(0x1F1E6 + ord(code[1]) - ord('A'))


# ─── Connection history ──────────────────────────────────────────────

def load_history() -> list:
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_history(events: list):
    if len(events) > MAX_HISTORY:
        events = events[-MAX_HISTORY:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(events, f, ensure_ascii=False)

def add_history(event: dict):
    h = load_history()
    event["time"] = datetime.now(timezone.utc).isoformat()
    h.append(event)
    save_history(h)

def get_client_history(name: str, limit: int = 10) -> list:
    return [e for e in load_history() if e.get("client") == name][-limit:]


# ─── Traffic daily snapshots ─────────────────────────────────────────

def load_traffic_daily() -> dict:
    try:
        with open(TRAFFIC_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_traffic_daily(data: dict):
    # Prune old days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=TRAFFIC_KEEP_DAYS)).strftime("%Y-%m-%d")
    data = {k: v for k, v in data.items() if k >= cutoff}
    with open(TRAFFIC_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)

def snapshot_daily_traffic(clients: dict, stats: dict):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = load_traffic_daily()
    snap = {}
    for name, c in clients.items():
        t_rx, t_tx = get_client_traffic(c, stats)
        snap[name] = {"rx": t_rx, "tx": t_tx}
    data[today] = snap
    save_traffic_daily(data)


# ─── Traffic graph generation ────────────────────────────────────────

def generate_traffic_graph(client_name: str | None = None, days: int = 30) -> bytes:
    """Generate bar chart PNG. If client_name is None, show total."""
    data = load_traffic_daily()
    dates_sorted = sorted(data.keys())[-days:]
    if len(dates_sorted) < 2:
        return b""

    dates, rx_daily, tx_daily = [], [], []
    for i, day in enumerate(dates_sorted):
        dates.append(datetime.strptime(day, "%Y-%m-%d"))
        snap = data[day]
        if client_name:
            cur = snap.get(client_name, {"rx": 0, "tx": 0})
        else:
            cur = {"rx": sum(v["rx"] for v in snap.values()), "tx": sum(v["tx"] for v in snap.values())}

        if i > 0:
            prev_snap = data[dates_sorted[i-1]]
            if client_name:
                prev = prev_snap.get(client_name, {"rx": 0, "tx": 0})
            else:
                prev = {"rx": sum(v["rx"] for v in prev_snap.values()), "tx": sum(v["tx"] for v in prev_snap.values())}
            d_rx = max(0, cur["rx"] - prev["rx"])
            d_tx = max(0, cur["tx"] - prev["tx"])
        else:
            d_rx, d_tx = 0, 0

        rx_daily.append(d_rx / (1024**3))  # GB
        tx_daily.append(d_tx / (1024**3))

    fig, ax = plt.subplots(figsize=(10, 4))
    width = 0.8
    ax.bar(dates, rx_daily, width, label="↓ Download", color="#4CAF50", alpha=0.85)
    ax.bar(dates, tx_daily, width, bottom=rx_daily, label="↑ Upload", color="#2196F3", alpha=0.85)
    ax.set_ylabel("GB")
    title = f"Трафик: {client_name}" if client_name else "Трафик: все клиенты"
    ax.set_title(title)
    ax.legend()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    return buf.getvalue()


# ─── Invites ─────────────────────────────────────────────────────────

def load_invites() -> dict:
    try:
        with open(INVITES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_invites(inv: dict):
    with open(INVITES_FILE, "w") as f:
        json.dump(inv, f, indent=2, ensure_ascii=False)

def create_invite(admin_id: int, expiry_days: int, traffic_gb: int | None, client_expiry_days: int | None) -> str:
    token = secrets.token_hex(8)
    inv = load_invites()
    inv[token] = {
        "created": datetime.now(timezone.utc).isoformat(),
        "created_by": admin_id,
        "link_expires": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "max_uses": 1,
        "uses": 0,
        "used_by": [],
        "client_expiry_days": client_expiry_days,
        "traffic_gb": traffic_gb,
    }
    save_invites(inv)
    return token

def use_invite(token: str, user_id: int, username: str) -> dict | str:
    """Returns client dict on success, error string on failure."""
    inv = load_invites()
    i = inv.get(token)
    if not i:
        return "Инвайт не найден."
    if datetime.fromisoformat(i["link_expires"]) < datetime.now(timezone.utc):
        return "Инвайт истёк."
    if i["uses"] >= i["max_uses"]:
        return "Инвайт уже использован."
    if user_id in i["used_by"]:
        return "Вы уже использовали этот инвайт."

    clients = load_clients()
    suffix = secrets.token_hex(2)
    name = f"Guest-{suffix}"
    while name in clients:
        suffix = secrets.token_hex(2)
        name = f"Guest-{suffix}"

    try:
        ip = next_ip(clients)
        priv, pub, psk = gen_keys()
        create_backup("invite")
        add_peer_to_server(pub, psk, ip, name)

        c = {
            "ip": ip, "private_key": priv, "public_key": pub, "psk": psk,
            "created": datetime.now(timezone.utc).isoformat(),
            "disabled": False, "total_rx": 0, "total_tx": 0, "_last_rx": 0, "_last_tx": 0,
            "invited_by": username, "telegram_id": user_id,
        }
        if i.get("client_expiry_days"):
            c["expires"] = (datetime.now(timezone.utc) + timedelta(days=i["client_expiry_days"])).isoformat()
        if i.get("traffic_gb"):
            c["traffic_limit_gb"] = i["traffic_gb"]

        clients[name] = c
        save_clients(clients)

        i["uses"] += 1
        i["used_by"].append(user_id)
        save_invites(inv)
        audit(user_id, "INVITE_USED", f"token={token[:8]}.. name={name}")
        return {"name": name, "client": c}
    except Exception as e:
        return f"Ошибка: {e}"


# ─── Schedule ────────────────────────────────────────────────────────

SCHEDULE_PRESETS = {
    "work_msk": {"label": "Пн-Пт 9-18 МСК", "days": [0,1,2,3,4], "start_utc": 6, "end_utc": 15},
    "work_utc": {"label": "Пн-Пт 9-18 UTC", "days": [0,1,2,3,4], "start_utc": 9, "end_utc": 18},
    "day_msk":  {"label": "Ежедн. 8-22 МСК", "days": [0,1,2,3,4,5,6], "start_utc": 5, "end_utc": 19},
    "off":      {"label": "Без расписания", "days": None, "start_utc": None, "end_utc": None},
}

def is_within_schedule(client: dict) -> bool | None:
    s = client.get("schedule")
    if not s or not s.get("days"):
        return None
    now = datetime.now(timezone.utc)
    if now.weekday() not in s["days"]:
        return False
    start, end = s["start_utc"], s["end_utc"]
    if start <= end:
        return start <= now.hour < end
    return now.hour >= start or now.hour < end


# ─── Persistent traffic ─────────────────────────────────────────────

def update_traffic_counters(clients: dict, stats: dict) -> bool:
    changed = False
    for c in clients.values():
        pub = c.get("public_key", "")
        s = stats.get(pub, {})
        cur_rx, cur_tx = s.get("rx", 0), s.get("tx", 0)
        last_rx, last_tx = c.get("_last_rx", 0), c.get("_last_tx", 0)
        total_rx, total_tx = c.get("total_rx", 0), c.get("total_tx", 0)

        if cur_rx == 0 and cur_tx == 0 and (last_rx > 0 or last_tx > 0):
            c["_last_rx"] = c["_last_tx"] = 0
            changed = True
        elif cur_rx >= last_rx and cur_tx >= last_tx:
            drx, dtx = cur_rx - last_rx, cur_tx - last_tx
            if drx > 0 or dtx > 0:
                c["total_rx"] = total_rx + drx
                c["total_tx"] = total_tx + dtx
                c["_last_rx"] = cur_rx
                c["_last_tx"] = cur_tx
                changed = True
        else:
            c["total_rx"] = total_rx + cur_rx
            c["total_tx"] = total_tx + cur_tx
            c["_last_rx"] = cur_rx
            c["_last_tx"] = cur_tx
            changed = True
    return changed

def get_client_traffic(client: dict, stats: dict) -> tuple[int, int]:
    pub = client.get("public_key", "")
    s = stats.get(pub, {})
    cur_rx, cur_tx = s.get("rx", 0), s.get("tx", 0)
    last_rx, last_tx = client.get("_last_rx", 0), client.get("_last_tx", 0)
    total_rx, total_tx = client.get("total_rx", 0), client.get("total_tx", 0)
    total_rx += max(0, cur_rx - last_rx) if cur_rx >= last_rx else cur_rx
    total_tx += max(0, cur_tx - last_tx) if cur_tx >= last_tx else cur_tx
    return total_rx, total_tx


# ─── Config builders ─────────────────────────────────────────────────

def build_client_conf(client: dict) -> str:
    srv = client.get("server", "awg")
    s = SERVERS[srv]
    pub_key = SERVER_PUB_KEY if srv == "awg" else _wg_server_pub()
    addr = f"{client['ip']}/32"
    iface_section = (
        f"[Interface]\n"
        f"PrivateKey = {client['private_key']}\n"
        f"Address = {addr}\n"
        f"DNS = {s['dns']}\n"
        f"MTU = {s['mtu']}\n"
    )
    if srv == "awg":
        iface_section += (
            f"Jc = {AWG_PARAMS['Jc']}\nJmin = {AWG_PARAMS['Jmin']}\nJmax = {AWG_PARAMS['Jmax']}\n"
            f"S1 = {AWG_PARAMS['S1']}\nS2 = {AWG_PARAMS['S2']}\n"
            f"H1 = {AWG_PARAMS['H1']}\nH2 = {AWG_PARAMS['H2']}\n"
            f"H3 = {AWG_PARAMS['H3']}\nH4 = {AWG_PARAMS['H4']}\n"
        )
    allowed_ips = "0.0.0.0/0"
    return (
        iface_section + f"\n[Peer]\n"
        f"PublicKey = {pub_key}\n"
        f"PresharedKey = {client['psk']}\n"
        f"Endpoint = {s['endpoint']}\n"
        f"AllowedIPs = {allowed_ips}\n"
        f"PersistentKeepalive = 25\n"
    )

def build_keenetic_conf(client: dict, name: str) -> str:
    srv = client.get("server", "awg")
    s = SERVERS[srv]
    pub_key = SERVER_PUB_KEY if srv == "awg" else _wg_server_pub()
    iface = name.lower().replace(" ", "").replace("-", "")[:10]
    if srv == "wg":
        # Standard WireGuard for Keenetic
        return (
            f"! === Keenetic WireGuard: {name} ===\n"
            f"interface Wireguard{iface}\n"
            f'    description "{name} VPN"\n'
            f"    security-level private\n"
            f"    ip address {client['ip']} 255.255.255.255\n"
            f"    ip mtu {s['mtu']}\n"
            f"    wireguard private-key {client['private_key']}\n"
            f"    wireguard listen-port 0\n"
            f"    wireguard peer {pub_key}\n"
            f"        endpoint {s['endpoint']}\n"
            f"        preshared-key {client['psk']}\n"
            f"        allowed-ips 0.0.0.0/0\n"
            f"        persistent-keepalive 25\n    !\n    up\n!\n"
            f"ip route 0.0.0.0/0 Wireguard{iface} auto\n"
            f"ip name-server 1.1.1.1\nip name-server 8.8.8.8\nsystem configuration save\n"
        )
    p = AWG_PARAMS
    return (
        f"! === Keenetic AmneziaWG: {name} ===\n"
        f"interface AmneziaWG{iface}\n"
        f'    description "{name} VPN"\n'
        f"    security-level private\n"
        f"    ip address {client['ip']} 255.255.255.255\n"
        f"    ip mtu {s['mtu']}\n"
        f"    amneziawg private-key {client['private_key']}\n"
        f"    amneziawg listen-port 0\n"
        f"    amneziawg jc {p['Jc']}\n    amneziawg jmin {p['Jmin']}\n    amneziawg jmax {p['Jmax']}\n"
        f"    amneziawg s1 {p['S1']}\n    amneziawg s2 {p['S2']}\n"
        f"    amneziawg h1 {p['H1']}\n    amneziawg h2 {p['H2']}\n"
        f"    amneziawg h3 {p['H3']}\n    amneziawg h4 {p['H4']}\n"
        f"    amneziawg peer {pub_key}\n"
        f"        endpoint {s['endpoint']}\n"
        f"        preshared-key {client['psk']}\n"
        f"        allowed-ips 0.0.0.0/0\n"
        f"        persistent-keepalive 25\n    !\n    up\n!\n"
        f"ip route 0.0.0.0/0 AmneziaWG{iface} auto\n"
        f"ip name-server 1.1.1.1\nip name-server 8.8.8.8\nsystem configuration save\n"
    )


# ─── Helpers ─────────────────────────────────────────────────────────

def make_qr(text: str) -> bytes:
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def get_awg_stats() -> dict:
    peers = {}
    for srv_key, srv in SERVERS.items():
        r = _docker_awg("wg", "show", srv["iface"], "dump")
        r = subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode(errors="replace"), "")
        if r.returncode != 0:
            continue
        for line in r.stdout.strip().splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 8:
                peers[parts[0]] = {
                    "endpoint": parts[2] if parts[2] != "(none)" else "-",
                    "rx": int(parts[5]) if parts[5] else 0,
                    "tx": int(parts[6]) if parts[6] else 0,
                    "handshake": int(parts[4]) if parts[4] and parts[4] != "0" else 0,
                }
    return peers

def _is_online(client: dict, stats: dict) -> bool:
    s = stats.get(client.get("public_key", ""), {})
    hs = s.get("handshake", 0)
    return hs > 0 and (int(time.time()) - hs) < 180

def check_awg_alive() -> bool:
    for srv in SERVERS.values():
        if _docker_awg("wg", "show", srv["iface"]).returncode != 0:
            return False
    return True

def restart_awg() -> bool:
    ok = True
    for srv in SERVERS.values():
        _docker_awg("wg-quick", "down", f"/opt/amnezia/awg/wg0.conf")
        res = _docker_awg("wg-quick", "up", f"/opt/amnezia/awg/wg0.conf")
        if res.returncode != 0:
            ok = False
    return ok

# ─── udp2raw helpers ─────────────────────────────────────────────────

def check_udp2raw_alive() -> bool:
    """True if systemd service is active AND port 4443/tcp is listening."""
    r = subprocess.run(
        ["systemctl", "is-active", UDP2RAW_SERVICE],
        capture_output=True, text=True,
    )
    if r.stdout.strip() != "active":
        return False
    # Also verify port is actually bound
    import socket as _socket
    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", UDP2RAW_PORT)) == 0
    except Exception:
        return False


def restart_udp2raw() -> bool:
    r = subprocess.run(
        ["systemctl", "restart", UDP2RAW_SERVICE],
        capture_output=True,
    )
    return r.returncode == 0


def udp2raw_uptime() -> str:
    """Return human-readable ActiveEnterTimestamp of udp2raw service."""
    r = subprocess.run(
        ["systemctl", "show", UDP2RAW_SERVICE, "--property=ActiveEnterTimestamp"],
        capture_output=True, text=True,
    )
    line = r.stdout.strip()           # e.g.  ActiveEnterTimestamp=Mon 2026-02-24 ...
    if "=" in line:
        ts_str = line.split("=", 1)[1].strip()
        if ts_str:
            try:
                from datetime import datetime as _dt
                ts = _dt.strptime(ts_str[:19], "%a %Y-%m-%d %H:%M")
                delta = _dt.now() - ts
                h, rem = divmod(int(delta.total_seconds()), 3600)
                m = rem // 60
                return f"{h}ч {m}м" if h else f"{m}м"
            except Exception:
                pass
    return "?"


def udp2raw_tcp_instructions(local_port: int = 29999) -> str:
    """Return udp2raw client connection instructions."""
    awg_port = SERVER_ENDPOINT.split(":")[-1] if ":" in SERVER_ENDPOINT else "43824"
    return (
        f"<b>Подключение через TCP (udp2raw)</b>\n"
        f"Используй когда UDP заблокирован провайдером.\n\n"
        f"<b>1. Установить udp2raw на своём устройстве</b>\n"
        f"   github.com/wangyu-/udp2raw  →  releases\n\n"
        f"<b>2. Запустить на клиенте:</b>\n"
        f"<pre>udp2raw -c \\\n"
        f"  -l 127.0.0.1:{local_port} \\\n"
        f"  -r {SERVER_IP}:{UDP2RAW_PORT} \\\n"
        f"  -k {UDP2RAW_KEY} \\\n"
        f"  --raw-mode faketcp \\\n"
        f"  --cipher-mode aes128cbc \\\n"
        f"  --auth-mode simple</pre>\n\n"
        f"<b>3. В конфиге WireGuard/AWG изменить Endpoint:</b>\n"
        f"<pre>Endpoint = 127.0.0.1:{local_port}</pre>\n\n"
        f"<i>Сервер слушает на {SERVER_IP}:{UDP2RAW_PORT}/tcp</i>"
    )


def fmt_bytes(b) -> str:
    b = float(b)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"

def fmt_time(ts: int) -> str:
    if ts == 0: return "—"
    d = int(time.time()) - ts
    if d < 60: return f"{d}с назад"
    if d < 3600: return f"{d//60}м назад"
    if d < 86400: return f"{d//3600}ч назад"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m %H:%M")

def fmt_uptime(s: float) -> str:
    d, s = int(s // 86400), s % 86400
    h, s = int(s // 3600), s % 3600
    m = int(s // 60)
    return f"{d}д {h}ч {m}м" if d else (f"{h}ч {m}м" if h else f"{m}м")

def progress_bar(pct: float, w: int = 10) -> str:
    f = int(pct / 100 * w)
    return "█" * f + "░" * (w - f)

async def _auto_delete(msg, delay=CONFIG_AUTO_DELETE_SEC):
    await asyncio.sleep(delay)
    try: await msg.delete()
    except: pass

async def _alert(admin_id: int, key: str, text: str, cooldown: int = 3600):
    now = time.time()
    if now - _last_alert.get(key, 0) < cooldown:
        return
    _last_alert[key] = now
    try:
        await bot.send_message(admin_id, text, parse_mode="HTML")
    except Exception:
        pass


# ─── /start (with invite support) ───────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    uname = message.from_user.username or message.from_user.first_name or str(uid)
    args = message.text.split(maxsplit=1)
    param = args[1] if len(args) > 1 else ""

    # ── Invite handling ──
    if param.startswith("inv_"):
        token = param[4:]
        result = use_invite(token, uid, uname)
        if isinstance(result, str):
            await message.answer(f"❌ {result}")
            return
        name = result["name"]
        c = result["client"]
        conf = build_client_conf(c)
        await message.answer(
            f"✅ <b>VPN-конфиг создан!</b>\n\n"
            f"📱 Имя: <b>{name}</b>\n"
            f"🌐 IP: <code>{c['ip']}</code>\n\n"
            f"📥 Установите <b>AmneziaWG</b> из App Store / Google Play\n"
            f"📱 Отсканируйте QR или импортируйте файл .conf",
            parse_mode="HTML",
        )
        sent_qr = await message.answer_photo(
            BufferedInputFile(make_qr(conf), filename=f"{name}_qr.png"),
            caption=f"📱 QR: {name}\n\n⚠️ <i>Удалится через {CONFIG_AUTO_DELETE_SEC//60} мин.</i>",
            parse_mode="HTML",
        )
        sent_conf = await message.answer_document(
            BufferedInputFile(conf.encode(), filename=f"{name}.conf"),
            caption=f"📄 Конфиг: {name}\n\n⚠️ <i>Удалится через {CONFIG_AUTO_DELETE_SEC//60} мин.</i>",
            parse_mode="HTML",
        )
        asyncio.create_task(_auto_delete(sent_qr))
        asyncio.create_task(_auto_delete(sent_conf))
        # Notify admin
        admin_id = get_admin_id()
        if admin_id:
            try:
                await bot.send_message(
                    admin_id,
                    f"🔗 <b>Инвайт использован</b>\n\n"
                    f"👤 @{uname} (id: {uid})\n"
                    f"📱 Клиент: <b>{name}</b>\n"
                    f"🌐 IP: <code>{c['ip']}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return

    # ── Normal admin start ──
    locked = lock_admin(uid, uname)
    if not is_admin(uid):
        # Предлагаем запросить доступ
        superadmin_id = get_admin_id()
        await message.answer(
            f"🔒 <b>Доступ закрыт</b>\n\n"
            f"Вы можете запросить доступ у администратора.\n"
            f"Ваш ID: <code>{uid}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📨 Запросить доступ", callback_data=f"req_access:{uid}:{uname[:20]}")
            ]])
        )
        return
    await state.clear()
    audit(uid, "START", f"@{uname}")
    clients = load_clients()
    stats = get_awg_stats()
    online = sum(1 for c in clients.values() if not c.get("disabled") and _is_online(c, stats))

    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n🛡  <b>AmneziaWG Manager v2</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌐 Сервер: <code>{SERVER_ENDPOINT}</code>\n"
        f"👥 Клиентов: <b>{len(clients)}</b>  (🟢 {online} online)\n"
        f"🔒 Обфускация: <b>MAXIMUM</b>\n"
        f"📡 Протокол: AmneziaWG (anti-DPI)\n\n"
    )
    if locked:
        text += "✅ Вы зарегистрированы как <b>администратор</b>.\n\n"
    text += "Используйте клавиатуру внизу 👇"
    await message.answer(text, reply_markup=MAIN_KB, parse_mode="HTML")


# ─── Clients list ────────────────────────────────────────────────────

@router.message(F.text == BTN_CLIENTS)
async def msg_clients(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    await _send_client_list(message)

async def _send_client_list(message, page=0, edit=False):
    clients = load_clients()
    if not clients:
        t = "📭 <b>Нет клиентов</b>\n\nНажмите <b>➕ Новый клиент</b>"
        if edit: await message.edit_text(t, parse_mode="HTML")
        else: await message.answer(t, parse_mode="HTML", reply_markup=MAIN_KB)
        return

    stats = get_awg_stats()
    names = sorted(clients.keys())
    tp = max(1, (len(names) + CLIENTS_PER_PAGE - 1) // CLIENTS_PER_PAGE)
    page = max(0, min(page, tp - 1))
    pnames = names[page*CLIENTS_PER_PAGE:(page+1)*CLIENTS_PER_PAGE]

    text = f"━━━━━━━━━━━━━━━━━━━━━━\n👥  <b>Клиенты</b>"
    if tp > 1: text += f" ({page+1}/{tp})"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for name in pnames:
        c = clients[name]
        t_rx, t_tx = get_client_traffic(c, stats)
        if c.get("disabled") or c.get("_scheduled_off"):
            icon, status = "⏸", "выкл"
        elif _is_online(c, stats):
            icon, status = "🟢", "online"
        else:
            icon, status = "⚪", "offline"
        extra = ""
        if c.get("expires"):
            exp = datetime.fromisoformat(c["expires"])
            if exp < datetime.now(timezone.utc): extra += " ⚠️"
            else: extra += f" ⏰{(exp - datetime.now(timezone.utc)).days}д"
        if c.get("traffic_limit_gb"):
            extra += f" 📦{(t_rx+t_tx)/(1024**3):.1f}/{c['traffic_limit_gb']}GB"
        if c.get("schedule"): extra += " 📅"
        text += f"{icon} <b>{name}</b> — {status}{extra}\n"
        text += f"    <code>{c['ip']}</code>  ↓{fmt_bytes(t_rx)} ↑{fmt_bytes(t_tx)}\n"

    text += "\n📱 Нажмите на клиента:"
    kb = client_list_inline(clients, page)
    if edit: await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else: await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("page:"))
async def cb_page(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    await _send_client_list(cb.message, int(cb.data.split(":")[1]), edit=True)
    await cb.answer()

@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery): await cb.answer()

@router.callback_query(F.data == "back_list")
async def cb_back(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    await _send_client_list(cb.message, edit=True)
    await cb.answer()


# ─── udp2raw callbacks ────────────────────────────────────────────────

@router.callback_query(F.data == "udp2raw:info")
async def cb_udp2raw_info(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    await cb.answer()
    text = udp2raw_tcp_instructions()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Рестарт udp2raw", callback_data="udp2raw:restart")],
    ])
    await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "udp2raw:restart")
async def cb_udp2raw_restart(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    await cb.answer("⏳ Перезапускаю udp2raw…")
    ok = restart_udp2raw()
    if ok:
        up = udp2raw_uptime()
        await cb.message.answer(
            f"✅ <b>udp2raw перезапущен</b>\n"
            f"🔌 Статус: 🟢 Active (:4443/tcp)\n"
            f"⏱ Аптайм: {up}",
            parse_mode="HTML")
    else:
        await cb.message.answer(
            "❌ <b>Не удалось перезапустить udp2raw</b>\n"
            "Проверь: <code>systemctl status udp2raw</code>",
            parse_mode="HTML")


# ─── Statistics ──────────────────────────────────────────────────────

@router.message(F.text == BTN_STATS)
async def msg_stats(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    clients = load_clients()
    stats = get_awg_stats()
    total_rx = total_tx = 0
    text = "━━━━━━━━━━━━━━━━━━━━━━\n📊  <b>Статистика</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for name, c in sorted(clients.items()):
        s = stats.get(c["public_key"], {})
        t_rx, t_tx = get_client_traffic(c, stats)
        total_rx += t_rx; total_tx += t_tx
        icon = "⏸" if c.get("disabled") else ("🟢" if _is_online(c, stats) else "⚪")
        text += f"{icon} <b>{name}</b>\n   ↓ {fmt_bytes(t_rx)}  ↑ {fmt_bytes(t_tx)}\n"
        text += f"   📡 {fmt_time(s.get('handshake',0))}  •  <code>{s.get('endpoint','-')}</code>\n\n"
    if not clients: text += "Нет клиентов.\n\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n📈 <b>Итого:</b> ↓ {fmt_bytes(total_rx)}  ↑ {fmt_bytes(total_tx)}\n    Суммарно: {fmt_bytes(total_rx+total_tx)}"
    await message.answer(text, parse_mode="HTML", reply_markup=MAIN_KB)


# ─── Server ──────────────────────────────────────────────────────────

@router.message(F.text == BTN_SERVER)
async def msg_server(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    up = time.time() - psutil.boot_time()
    l1, l5, l15 = os.getloadavg()
    net = psutil.net_io_counters()
    awg_ok    = check_awg_alive()
    u2r_ok    = check_udp2raw_alive()
    awg_str   = "🟢 Active" if awg_ok   else "🔴 Down"
    u2r_str   = f"🟢 Active (:{UDP2RAW_PORT}/tcp)" if u2r_ok else f"🔴 Down (:{UDP2RAW_PORT}/tcp)"
    u2r_up    = f"  ↑ {udp2raw_uptime()}" if u2r_ok else ""
    clients   = load_clients()
    stats     = get_awg_stats()
    on        = sum(1 for c in clients.values() if not c.get("disabled") and _is_online(c, stats))
    bc        = len(glob_mod.glob(f"{BACKUP_DIR}/clients_*.json"))
    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n🖥  <b>Сервер</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱ Uptime: <b>{fmt_uptime(up)}</b>\n🔄 Load: {l1:.1f}/{l5:.1f}/{l15:.1f}\n\n"
        f"🧠 CPU: {progress_bar(cpu)} <b>{cpu:.0f}%</b>\n"
        f"💾 RAM: {progress_bar(mem.percent)} <b>{mem.percent:.0f}%</b> ({fmt_bytes(mem.used)}/{fmt_bytes(mem.total)})\n"
        f"💿 Disk: {progress_bar(disk.used/disk.total*100)} <b>{disk.used/disk.total*100:.0f}%</b> ({fmt_bytes(disk.used)}/{fmt_bytes(disk.total)})\n\n"
        f"🌐 Net: ↓ {fmt_bytes(net.bytes_recv)}  ↑ {fmt_bytes(net.bytes_sent)}\n\n"
        f"🛡 AWG:    {awg_str}\n"
        f"🔌 udp2raw: {u2r_str}{u2r_up}\n\n"
        f"👥 Клиентов: {len(clients)} (🟢 {on} online)\n"
        f"🔑 UDP порт: {SERVER_ENDPOINT}\n"
        f"🔑 TCP порт: {SERVER_IP}:{UDP2RAW_PORT}\n"
        f"💾 Бэкапов: {bc}"
    )
    srv_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔌 Как подключиться через TCP", callback_data="udp2raw:info")],
        [InlineKeyboardButton(text="🔄 Рестарт udp2raw", callback_data="udp2raw:restart")],
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=srv_kb)
    await message.answer("", reply_markup=MAIN_KB)   # restore main keyboard


# ─── Speedtest ───────────────────────────────────────────────────────

@router.message(F.text == BTN_SPEEDTEST)
async def msg_speedtest(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    audit(message.from_user.id, "SPEEDTEST")
    msg = await message.answer("⚡ <b>Спидтест...</b> (20-40 сек)", parse_mode="HTML")
    try:
        def _run():
            st = speedtest.Speedtest(); st.get_best_server(); st.download(); st.upload(); return st.results.dict()
        d = await asyncio.get_event_loop().run_in_executor(None, _run)
        text = (f"━━━━━━━━━━━━━━━━━━━━━━\n⚡  <b>Спидтест</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"↓ Download: <b>{d['download']/1e6:.1f} Mbps</b>\n↑ Upload: <b>{d['upload']/1e6:.1f} Mbps</b>\n"
                f"🏓 Ping: <b>{d['ping']:.0f} ms</b>\n\n🏢 {d.get('server',{}).get('sponsor','?')}, {d.get('server',{}).get('name','?')}")
        await msg.edit_text(text, parse_mode="HTML")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


# ─── Tools menu ──────────────────────────────────────────────────────

@router.message(F.text == BTN_TOOLS)
async def msg_tools(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    inv = load_invites()
    active = sum(1 for i in inv.values() if i["uses"] < i["max_uses"] and datetime.fromisoformat(i["link_expires"]) > datetime.now(timezone.utc))
    subadmins = get_subadmins()
    buttons = [
        [InlineKeyboardButton(text="🔗 Создать инвайт", callback_data="tool:invite"),
         InlineKeyboardButton(text="📋 Инвайты", callback_data="tool:invites")],
        [InlineKeyboardButton(text="📊 Графики трафика", callback_data="tool:graph")],
        [InlineKeyboardButton(text="💾 Бэкап в Telegram", callback_data="tool:backup")],
    ]
    # Управление пользователями — только суперадмин
    if is_superadmin(message.from_user.id):
        buttons.append([InlineKeyboardButton(text=f"👥 Пользователи бота ({len(subadmins)})", callback_data="tool:admins")])
    await message.answer(
        f"━━━━━━━━━━━━━━━━━━━━━━\n🔧  <b>Инструменты</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 Активных инвайтов: {active}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )


# ─── Create invite ───────────────────────────────────────────────────

@router.callback_query(F.data == "tool:invite")
async def cb_create_invite(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    await cb.message.edit_text(
        "🔗 <b>Создать инвайт</b>\n\nВыберите параметры для гостевого клиента:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🕐 1 день, 5 GB", callback_data="mkinv:1:5"),
             InlineKeyboardButton(text="📅 7 дней, 50 GB", callback_data="mkinv:7:50")],
            [InlineKeyboardButton(text="📆 30 дней, 100 GB", callback_data="mkinv:30:100"),
             InlineKeyboardButton(text="♾ 30 дней, безлим", callback_data="mkinv:30:0")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="tool:back")],
        ]),
        parse_mode="HTML",
    )
    await cb.answer()

@router.callback_query(F.data.startswith("mkinv:"))
async def cb_mkinv(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    parts = cb.data.split(":")
    exp_days = int(parts[1])
    traffic = int(parts[2]) if int(parts[2]) > 0 else None
    token = create_invite(cb.from_user.id, 1, traffic, exp_days)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=inv_{token}"
    audit(cb.from_user.id, "CREATE_INVITE", f"token={token[:8]}.. exp={exp_days}d traffic={traffic}")
    t_str = f"{traffic} GB" if traffic else "безлим"
    await cb.message.edit_text(
        f"✅ <b>Инвайт создан</b>\n\n"
        f"📅 Клиент: {exp_days} дней, {t_str}\n"
        f"🕐 Ссылка действует 24ч, 1 использование\n\n"
        f"🔗 <code>{link}</code>\n\n"
        f"Отправьте эту ссылку пользователю.",
        parse_mode="HTML",
    )
    await cb.answer()

@router.callback_query(F.data == "tool:back")
async def cb_tool_back(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    await cb.message.delete()
    await cb.answer()


@router.callback_query(F.data == "tool:admins")
async def cb_tool_admins(cb: CallbackQuery):
    if not is_superadmin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    subadmins = get_subadmins()
    text = "━━━━━━━━━━━━━━━━━━━━━━\n👥 <b>Пользователи бота</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    buttons = []
    if not subadmins:
        text += "Дополнительных пользователей нет.\n\n"
        text += "Чтобы добавить: попросите человека написать /start боту — придёт запрос."
    else:
        for uid_str, info in subadmins.items():
            uname = info.get("username", uid_str)
            added_at = info.get("added_at", "")[:10]
            text += f"👤 @{uname} (id: <code>{uid_str}</code>)\n   Добавлен: {added_at}\n\n"
            buttons.append([InlineKeyboardButton(
                text=f"🗑 Удалить @{uname}",
                callback_data=f"rmadmin:{uid_str}"
            )])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                                parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("rmadmin:"))
async def cb_remove_admin(cb: CallbackQuery):
    if not is_superadmin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    uid_to_remove = int(cb.data.split(":", 1)[1])
    subadmins = get_subadmins()
    uname = subadmins.get(str(uid_to_remove), {}).get("username", str(uid_to_remove))
    remove_subadmin(uid_to_remove)
    audit(cb.from_user.id, "REMOVE_SUBADMIN", f"uid={uid_to_remove} @{uname}")
    try:
        await bot.send_message(
            uid_to_remove,
            "⛔ <b>Ваш доступ к боту был отозван администратором.</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await cb.answer(f"✅ @{uname} удалён")
    # Обновить список
    await cb_tool_admins(cb)


# ─── List invites ────────────────────────────────────────────────────

@router.callback_query(F.data == "tool:invites")
async def cb_list_invites(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    inv = load_invites()
    now = datetime.now(timezone.utc)
    text = "━━━━━━━━━━━━━━━━━━━━━━\n📋  <b>Инвайты</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    buttons = []
    for token, i in sorted(inv.items(), key=lambda x: x[1]["created"], reverse=True)[:10]:
        exp = datetime.fromisoformat(i["link_expires"])
        expired = exp < now
        used = i["uses"] >= i["max_uses"]
        if expired: status = "⏰ истёк"
        elif used: status = "✅ использован"
        else: status = "🟢 активен"
        t_str = f"{i.get('traffic_gb','♾')} GB" if i.get("traffic_gb") else "♾"
        text += f"{status}  <code>{token[:8]}...</code>  {i.get('client_expiry_days','♾')}д / {t_str}\n"
        if not expired and not used:
            buttons.append([InlineKeyboardButton(text=f"🗑 {token[:8]}...", callback_data=f"delinv:{token}")])
    if not inv: text += "Нет инвайтов.\n"
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="tool:back")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await cb.answer()

@router.callback_query(F.data.startswith("delinv:"))
async def cb_del_invite(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    token = cb.data.split(":", 1)[1]
    inv = load_invites()
    if token in inv:
        del inv[token]
        save_invites(inv)
        audit(cb.from_user.id, "DELETE_INVITE", token[:8])
    await cb.answer("🗑 Удалён", show_alert=True)
    await cb_list_invites(cb)


# ─── Traffic graphs ──────────────────────────────────────────────────

@router.callback_query(F.data == "tool:graph")
async def cb_graph_menu(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    clients = load_clients()
    buttons = [[InlineKeyboardButton(text="📊 Все клиенты", callback_data="graph:_all")]]
    for name in sorted(clients.keys())[:12]:
        buttons.append([InlineKeyboardButton(text=f"📈 {name}", callback_data=f"graph:{name}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="tool:back")])
    await cb.message.edit_text("📊 <b>Графики трафика</b>\n\nВыберите клиента:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await cb.answer()

@router.callback_query(F.data.startswith("graph:"))
async def cb_graph(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    target = cb.data.split(":", 1)[1]
    client_name = None if target == "_all" else target
    data = load_traffic_daily()
    if len(data) < 2:
        await cb.answer("📊 Недостаточно данных (нужно минимум 2 дня)", show_alert=True)
        return
    try:
        img = await asyncio.get_event_loop().run_in_executor(None, generate_traffic_graph, client_name, 30)
        if not img:
            await cb.answer("Нет данных", show_alert=True)
            return
        label = client_name or "все клиенты"
        await cb.message.answer_photo(
            BufferedInputFile(img, filename="traffic.png"),
            caption=f"📊 Трафик за 30 дней: <b>{label}</b>", parse_mode="HTML",
        )
    except Exception as e:
        await cb.message.answer(f"❌ Ошибка графика: {e}")
    await cb.answer()


# ─── Backup to Telegram ─────────────────────────────────────────────

@router.callback_query(F.data == "tool:backup")
async def cb_backup(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    create_backup("manual_telegram")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    files = []
    for path, fname in [(DATA_FILE, f"clients_{ts}.json"), (AWG_CONF, f"awg0_{ts}.conf")]:
        if os.path.exists(path):
            with open(path, "rb") as f:
                files.append((f.read(), fname))
    for data, fname in files:
        sent = await cb.message.answer_document(
            BufferedInputFile(data, filename=fname),
            caption=f"💾 Бэкап: <b>{fname}</b>\n\n⚠️ <i>Удалится через 5 мин.</i>",
            parse_mode="HTML",
        )
        asyncio.create_task(_auto_delete(sent, 300))
    audit(cb.from_user.id, "BACKUP_TELEGRAM")
    await cb.answer("💾 Бэкап отправлен")


# ─── Add client ──────────────────────────────────────────────────────

@router.message(F.text == BTN_ADD)
async def msg_add(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(AddClient.waiting_server)
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡 AmneziaWG (обход DPI)", callback_data="srv:awg")],
    ])
    await message.answer(
        "━━━━━━━━━━━━━━━━━━━━━━\n➕ <b>Новый клиент</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🛡 <b>AmneziaWG</b> — обход DPI, для телефонов/ПК\n"
        "     Порт 43824, подсеть 10.8.1.0/24",
        reply_markup=buttons, parse_mode="HTML")

@router.callback_query(F.data.startswith("srv:"))
async def cb_select_server(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    srv = cb.data.split(":")[1]
    if srv not in SERVERS:
        await cb.answer("❌ Неизвестный сервер", show_alert=True); return
    await state.update_data(server=srv)
    await state.set_state(AddClient.waiting_name)
    s = SERVERS[srv]
    await cb.message.answer(
        f"✏️ <b>Введите имя нового клиента</b>\n\n"
        f"Сервер: {s['icon']} <b>{s['label']}</b>\n"
        f"<i>Примеры: iPhone-Petya, Keenetic-Home</i>",
        reply_markup=CANCEL_KB, parse_mode="HTML")
    await cb.answer()

@router.message(F.text == BTN_CANCEL)
async def msg_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=MAIN_KB)

@router.message(AddClient.waiting_name)
async def process_add(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    name = message.text.strip()
    if not name or len(name) > 30 or name in RESERVED_TEXTS:
        await message.answer("❌ Недопустимое имя (1-30 символов).", reply_markup=CANCEL_KB); return
    clients = load_clients()
    if name in clients:
        await message.answer(f"❌ <b>{name}</b> уже существует.", parse_mode="HTML", reply_markup=CANCEL_KB); return
    data = await state.get_data()
    srv = data.get("server", "awg")
    try:
        ip = next_ip(clients, srv)
        priv, pub, psk = gen_keys()
        create_backup("add_client")
        add_peer_to_server(pub, psk, ip, name, srv)
        clients[name] = {"ip": ip, "private_key": priv, "public_key": pub, "psk": psk,
                          "created": datetime.now(timezone.utc).isoformat(), "disabled": False,
                          "total_rx": 0, "total_tx": 0, "_last_rx": 0, "_last_tx": 0,
                          "server": srv}
        save_clients(clients)
        await state.clear()
        s = SERVERS[srv]
        audit(message.from_user.id, "ADD_CLIENT", f"{name} ip={ip} server={srv}")
        await message.answer(
            f"━━━━━━━━━━━━━━━━━━━━━━\n✅ <b>Клиент создан</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📱 Имя: <b>{name}</b>\n🌐 IP: <code>{ip}</code>\n"
            f"🖥 Сервер: {s['icon']} {s['label']}",
            reply_markup=MAIN_KB, parse_mode="HTML")
        await message.answer(f"Действия для <b>{name}</b>:",
                              reply_markup=client_detail_inline(name, clients[name]), parse_mode="HTML")
    except Exception as e:
        log.error(f"Add client failed: {e}")
        await message.answer(f"❌ Ошибка: {e}", reply_markup=MAIN_KB)
        await state.clear()


# ─── Client detail ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cl:"))
async def cb_detail(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]
    clients = load_clients()
    c = clients.get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return

    stats = get_awg_stats()
    s = stats.get(c["public_key"], {})
    t_rx, t_tx = get_client_traffic(c, stats)
    ep = s.get("endpoint", "-")

    # GeoIP for current endpoint
    geo_str = ""
    if ep != "-":
        geo = await geoip_lookup(ep)
        if geo.get("country"):
            geo_str = f"\n🌍 Гео: {geo_flag(geo.get('countryCode',''))} {geo.get('country','')} {geo.get('city','')}"

    if c.get("disabled") or c.get("_scheduled_off"): status = "⏸ Отключён"
    elif _is_online(c, stats): status = "🟢 Online"
    else: status = "⚪ Offline"

    exp_str = "—"
    if c.get("expires"):
        exp = datetime.fromisoformat(c["expires"])
        if exp < datetime.now(timezone.utc): exp_str = "⚠️ Истёк!"
        else: exp_str = f"{(exp - datetime.now(timezone.utc)).days}д ({exp.strftime('%d.%m.%Y')})"

    lim_str = "—"
    if c.get("traffic_limit_gb"):
        used = (t_rx + t_tx) / (1024**3)
        lim = c["traffic_limit_gb"]
        lim_str = f"{progress_bar(min(used/lim*100,100), 8)} {used:.1f}/{lim} GB"

    sched_str = "—"
    if c.get("schedule"):
        for k, v in SCHEDULE_PRESETS.items():
            if v.get("days") == c["schedule"].get("days") and v.get("start_utc") == c["schedule"].get("start_utc"):
                sched_str = v["label"]; break
        else:
            sched_str = "Настроено"

    srv = c.get("server", "awg")
    srv_info = SERVERS.get(srv, SERVERS["awg"])
    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n📱  <b>{name}</b>  {status}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🖥 Сервер: {srv_info['icon']} {srv_info['label']}\n"
        f"🌐 IP: <code>{c['ip']}</code>\n🔑 Key: <code>{c['public_key'][:24]}...</code>\n"
        f"📅 Создан: {c.get('created','?')[:10]}\n\n"
        f"↓ {fmt_bytes(t_rx)}  ↑ {fmt_bytes(t_tx)}\n"
        f"📡 Handshake: {fmt_time(s.get('handshake',0))}\n🔗 Endpoint: <code>{ep}</code>{geo_str}\n\n"
        f"⏰ Срок: {exp_str}\n📦 Лимит: {lim_str}\n📅 Расписание: {sched_str}"
    )
    await cb.message.edit_text(text, reply_markup=client_detail_inline(name, c), parse_mode="HTML")
    await cb.answer()


# ─── Config / QR / Keenetic ─────────────────────────────────────────

@router.callback_query(F.data.startswith("conf:"))
async def cb_conf(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]; c = load_clients().get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return
    sent = await cb.message.answer_document(
        BufferedInputFile(build_client_conf(c).encode(), filename=f"{name}.conf"),
        caption=f"📄 Конфиг: <b>{name}</b>\n⚠️ <i>Удалится через {CONFIG_AUTO_DELETE_SEC//60} мин.</i>", parse_mode="HTML")
    asyncio.create_task(_auto_delete(sent))
    audit(cb.from_user.id, "SEND_CONF", name); await cb.answer()

@router.callback_query(F.data.startswith("qr:"))
async def cb_qr(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]; c = load_clients().get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return
    sent = await cb.message.answer_photo(
        BufferedInputFile(make_qr(build_client_conf(c)), filename=f"{name}_qr.png"),
        caption=f"📱 QR: <b>{name}</b>\n⚠️ <i>Удалится через {CONFIG_AUTO_DELETE_SEC//60} мин.</i>", parse_mode="HTML")
    asyncio.create_task(_auto_delete(sent)); await cb.answer()

@router.callback_query(F.data.startswith("keen:"))
async def cb_keen(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]; c = load_clients().get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return
    s1 = await cb.message.answer_document(
        BufferedInputFile(build_keenetic_conf(c, name).encode(), filename=f"{name}_keenetic.txt"),
        caption=f"🌐 Keenetic CLI: <b>{name}</b>\n⚠️ <i>Удалится через {CONFIG_AUTO_DELETE_SEC//60} мин.</i>", parse_mode="HTML")
    s2 = await cb.message.answer_document(
        BufferedInputFile(build_client_conf(c).encode(), filename=f"{name}_keenetic.conf"),
        caption=f"📄 Keenetic import: <b>{name}</b>\n⚠️ <i>Удалится через {CONFIG_AUTO_DELETE_SEC//60} мин.</i>", parse_mode="HTML")
    asyncio.create_task(_auto_delete(s1)); asyncio.create_task(_auto_delete(s2)); await cb.answer()


# ─── Enable / Disable ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("disable:"))
async def cb_disable(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]; clients = load_clients(); c = clients.get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return
    srv = c.get("server", "awg")
    remove_peer_live(c["public_key"], srv); c["disabled"] = True; save_clients(clients)
    audit(cb.from_user.id, "DISABLE", name)
    await cb.answer(f"⏸ {name} отключён", show_alert=True)
    cb.data = f"cl:{name}"; await cb_detail(cb)

@router.callback_query(F.data.startswith("enable:"))
async def cb_enable(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]; clients = load_clients(); c = clients.get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return
    srv = c.get("server", "awg")
    restore_peer_live(c["public_key"], c["psk"], c["ip"], srv); c["disabled"] = False; c.pop("_scheduled_off", None)
    save_clients(clients); audit(cb.from_user.id, "ENABLE", name)
    await cb.answer(f"▶️ {name} включён", show_alert=True)
    cb.data = f"cl:{name}"; await cb_detail(cb)


# ─── Delete ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("del:"))
async def cb_del(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]
    await cb.message.edit_text(f"⚠️ Удалить <b>{name}</b>?\n\nЭто необратимо!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data=f"cdel:{name}"),
             InlineKeyboardButton(text="❌ Нет", callback_data=f"cl:{name}")]]),
        parse_mode="HTML"); await cb.answer()

@router.callback_query(F.data.startswith("cdel:"))
async def cb_cdel(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]; clients = load_clients(); c = clients.get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return
    srv = c.get("server", "awg")
    create_backup("delete"); remove_peer_live(c["public_key"], srv); remove_peer_from_config(c["public_key"], srv)
    del clients[name]; save_clients(clients); audit(cb.from_user.id, "DELETE", name)
    await cb.message.edit_text(f"🗑 <b>{name}</b> удалён.", parse_mode="HTML"); await cb.answer()


# ─── Rename ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rename:"))
async def cb_rename(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]
    if name not in load_clients(): await cb.answer("Не найден", show_alert=True); return
    await state.update_data(rename_from=name); await state.set_state(RenameClient.waiting_name)
    await cb.message.edit_text(f"✏️ <b>Переименовать: {name}</b>\n\nВведите новое имя:", parse_mode="HTML")
    await cb.answer()

@router.message(RenameClient.waiting_name)
async def process_rename(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text and message.text.strip() == BTN_CANCEL:
        await state.clear(); await message.answer("Отменено.", reply_markup=MAIN_KB); return
    data = await state.get_data(); old = data.get("rename_from"); new = message.text.strip() if message.text else ""
    if not new or len(new) > 30 or new in RESERVED_TEXTS:
        await message.answer("❌ Недопустимое имя.", reply_markup=CANCEL_KB); return
    clients = load_clients()
    if old not in clients: await state.clear(); await message.answer("❌ Не найден.", reply_markup=MAIN_KB); return
    if new in clients: await message.answer(f"❌ <b>{new}</b> уже есть.", parse_mode="HTML", reply_markup=CANCEL_KB); return
    srv = clients[old].get("server", "awg")
    create_backup("rename"); clients[new] = clients.pop(old); save_clients(clients)
    update_peer_comment_in_config(old, new, srv); await state.clear()
    audit(message.from_user.id, "RENAME", f"{old} -> {new}")
    await message.answer(f"✅ <b>{old}</b> → <b>{new}</b>", parse_mode="HTML", reply_markup=MAIN_KB)


# ─── Rekey ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rekey:"))
async def cb_rekey(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]
    await cb.message.edit_text(
        f"🔄 <b>Перегенерировать ключи: {name}?</b>\n\n⚠️ Старый конфиг перестанет работать!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data=f"crekey:{name}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cl:{name}")]]),
        parse_mode="HTML"); await cb.answer()

@router.callback_query(F.data.startswith("crekey:"))
async def cb_crekey(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]; clients = load_clients(); c = clients.get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return
    try:
        srv = c.get("server", "awg")
        create_backup("rekey"); priv, pub, psk = gen_keys()
        remove_peer_live(c["public_key"], srv); remove_peer_from_config(c["public_key"], srv)
        add_peer_to_server(pub, psk, c["ip"], name, srv)
        c["private_key"] = priv; c["public_key"] = pub; c["psk"] = psk; c["disabled"] = False
        save_clients(clients); audit(cb.from_user.id, "REKEY", name)
        await cb.message.edit_text(
            f"✅ <b>Ключи обновлены: {name}</b>\n\nСкачайте новый конфиг:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📄 Конфиг", callback_data=f"conf:{name}"),
                 InlineKeyboardButton(text="📱 QR", callback_data=f"qr:{name}")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cl:{name}")]]),
            parse_mode="HTML")
    except Exception as e:
        await cb.message.edit_text(f"❌ Ошибка: {e}")
    await cb.answer()


# ─── Client history ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("hist:"))
async def cb_hist(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]
    events = get_client_history(name, 15)
    text = f"━━━━━━━━━━━━━━━━━━━━━━\n📜  <b>История: {name}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    if not events:
        text += "Нет записей.\n"
    else:
        for e in reversed(events):
            ts = e.get("time", "")[:16].replace("T", " ")
            if e["type"] == "connect":
                geo = e.get("geo", "")
                text += f"🟢 {ts}  ← {e.get('endpoint','?')}\n"
                if geo: text += f"    🌍 {geo}\n"
            elif e["type"] == "disconnect":
                dur = e.get("duration_min", 0)
                rx, tx = e.get("rx", 0), e.get("tx", 0)
                text += f"⚪ {ts}  ({dur}м)  ↓{fmt_bytes(rx)} ↑{fmt_bytes(tx)}\n"
    text += f"\nВсего записей: {len(events)}"
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"cl:{name}")]]), parse_mode="HTML")
    await cb.answer()


# ─── Schedule ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sched:"))
async def cb_sched(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]
    c = load_clients().get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return
    current = "Нет"
    if c.get("schedule"):
        for k, v in SCHEDULE_PRESETS.items():
            if v.get("days") == c["schedule"].get("days") and v.get("start_utc") == c["schedule"].get("start_utc"):
                current = v["label"]; break
        else:
            current = "Настроено"
    buttons = []
    for k, v in SCHEDULE_PRESETS.items():
        buttons.append([InlineKeyboardButton(text=v["label"], callback_data=f"ssched:{name}:{k}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"cl:{name}")])
    await cb.message.edit_text(
        f"📅 <b>Расписание: {name}</b>\n\nТекущее: <b>{current}</b>\n\nВыберите режим:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await cb.answer()

@router.callback_query(F.data.startswith("ssched:"))
async def cb_set_sched(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    parts = cb.data.split(":"); name = parts[1]; preset = parts[2]
    clients = load_clients(); c = clients.get(name)
    if not c: await cb.answer("Не найден", show_alert=True); return
    p = SCHEDULE_PRESETS[preset]
    if p["days"] is None:
        c.pop("schedule", None)
        if c.get("_scheduled_off"):
            c.pop("_scheduled_off"); restore_peer_live(c["public_key"], c["psk"], c["ip"])
        msg = "♾ Без расписания"
    else:
        c["schedule"] = {"days": p["days"], "start_utc": p["start_utc"], "end_utc": p["end_utc"]}
        msg = f"📅 {p['label']}"
    save_clients(clients); audit(cb.from_user.id, "SET_SCHEDULE", f"{name} {preset}")
    await cb.message.edit_text(f"✅ <b>{name}</b>\n{msg}", parse_mode="HTML"); await cb.answer()


# ─── Expiry / Limit ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("expiry:"))
async def cb_expiry(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]
    await state.update_data(target_name=name); await state.set_state(SetExpiry.waiting)
    c = load_clients().get(name, {}); cur = c.get("expires", "не установлен")
    await cb.message.edit_text(
        f"⏰ <b>Срок: {name}</b>\n\nТекущий: <code>{cur}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1д", callback_data="exp:1"), InlineKeyboardButton(text="7д", callback_data="exp:7"),
             InlineKeyboardButton(text="30д", callback_data="exp:30")],
            [InlineKeyboardButton(text="90д", callback_data="exp:90"), InlineKeyboardButton(text="♾", callback_data="exp:0")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cl:{name}")]]),
        parse_mode="HTML"); await cb.answer()

@router.callback_query(F.data.startswith("exp:"), SetExpiry.waiting)
async def cb_exp(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = (await state.get_data()).get("target_name"); days = int(cb.data.split(":")[1])
    clients = load_clients(); c = clients.get(name)
    if not c: await cb.answer("Не найден", show_alert=True); await state.clear(); return
    if days == 0:
        c.pop("expires", None); msg = "♾ Безлимит"
    else:
        exp = datetime.now(timezone.utc) + timedelta(days=days)
        c["expires"] = exp.isoformat(); msg = f"⏰ {exp.strftime('%d.%m.%Y')} ({days}д)"
    save_clients(clients); await state.clear(); audit(cb.from_user.id, "SET_EXPIRY", f"{name} {days}d")
    await cb.message.edit_text(f"✅ <b>{name}</b>\n{msg}", parse_mode="HTML"); await cb.answer()

@router.callback_query(F.data.startswith("limit:"))
async def cb_limit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = cb.data.split(":", 1)[1]
    await state.update_data(target_name=name); await state.set_state(SetLimit.waiting)
    c = load_clients().get(name, {}); cur = c.get("traffic_limit_gb", "нет")
    await cb.message.edit_text(
        f"📦 <b>Лимит: {name}</b>\n\nТекущий: <code>{cur} GB</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="5GB", callback_data="lim:5"), InlineKeyboardButton(text="10GB", callback_data="lim:10"),
             InlineKeyboardButton(text="50GB", callback_data="lim:50")],
            [InlineKeyboardButton(text="100GB", callback_data="lim:100"), InlineKeyboardButton(text="♾", callback_data="lim:0")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cl:{name}")]]),
        parse_mode="HTML"); await cb.answer()

@router.callback_query(F.data.startswith("lim:"), SetLimit.waiting)
async def cb_lim(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    name = (await state.get_data()).get("target_name"); gb = int(cb.data.split(":")[1])
    clients = load_clients(); c = clients.get(name)
    if not c: await cb.answer("Не найден", show_alert=True); await state.clear(); return
    if gb == 0:
        c.pop("traffic_limit_gb", None); msg = "♾ Безлимит"
    else:
        c["traffic_limit_gb"] = gb; msg = f"📦 {gb} GB"
    save_clients(clients); await state.clear(); audit(cb.from_user.id, "SET_LIMIT", f"{name} {gb}gb")
    await cb.message.edit_text(f"✅ <b>{name}</b>\n{msg}", parse_mode="HTML"); await cb.answer()


# ─── Background loop ────────────────────────────────────────────────

async def notification_loop():
    global _peer_online, _last_daily_report
    await asyncio.sleep(10)
    save_counter = 0
    _connect_times: dict[str, float] = {}  # pub -> connect timestamp

    while True:
        try:
            admin_id = get_admin_id()
            if not admin_id:
                await asyncio.sleep(NOTIFY_CHECK_INTERVAL); continue

            clients = load_clients()
            stats = get_awg_stats()
            now = datetime.now(timezone.utc)

            # ── Traffic counters ──
            save_counter += 1
            if update_traffic_counters(clients, stats) and save_counter >= 10:
                save_clients(clients); save_counter = 0

            # ── AWG watchdog ──
            if not check_awg_alive():
                log.warning("AWG DOWN! Restarting...")
                await _alert(admin_id, "awg_down", "🔴 <b>AWG упал!</b> Перезапускаю...", 60)
                if restart_awg():
                    await _alert(admin_id, "awg_up", "🟢 AWG перезапущен!", 60)
                else:
                    await _alert(admin_id, "awg_fail", "❌ <b>AWG не удалось перезапустить!</b>", 60)
                await asyncio.sleep(NOTIFY_CHECK_INTERVAL); continue

            # ── udp2raw watchdog ──
            global _udp2raw_was_down
            udp2raw_ok = check_udp2raw_alive()
            if not udp2raw_ok and not _udp2raw_was_down:
                _udp2raw_was_down = True
                log.warning("udp2raw DOWN! Restarting...")
                await _alert(
                    admin_id, "udp2raw_down",
                    f"🔴 <b>udp2raw упал!</b>\n"
                    f"TCP-обёртка на порту {UDP2RAW_PORT} недоступна.\n"
                    f"Клиенты с заблокированным UDP не смогут подключиться.\n\n"
                    f"Перезапускаю сервис...",
                    cooldown=60,
                )
                if restart_udp2raw():
                    await asyncio.sleep(3)
                    if check_udp2raw_alive():
                        _udp2raw_was_down = False
                        await _alert(
                            admin_id, "udp2raw_up",
                            f"🟢 <b>udp2raw перезапущен</b>\n"
                            f"Порт {UDP2RAW_PORT}/tcp снова доступен.",
                            cooldown=0,
                        )
                    else:
                        await _alert(
                            admin_id, "udp2raw_fail",
                            f"❌ <b>udp2raw не удалось перезапустить!</b>\n"
                            f"Проверь: <code>systemctl status {UDP2RAW_SERVICE}</code>",
                            cooldown=3600,
                        )
                else:
                    await _alert(
                        admin_id, "udp2raw_fail",
                        f"❌ <b>udp2raw не удалось перезапустить!</b>",
                        cooldown=3600,
                    )
            elif udp2raw_ok and _udp2raw_was_down:
                _udp2raw_was_down = False
                await _alert(
                    admin_id, "udp2raw_recover",
                    f"🟢 <b>udp2raw восстановлен</b> (порт {UDP2RAW_PORT}/tcp доступен)",
                    cooldown=0,
                )

            # ── Server load alerts ──
            cpu = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory()
            disk = shutil.disk_usage("/")
            if cpu > ALERT_CPU:
                await _alert(admin_id, "cpu", f"🔥 <b>CPU: {cpu:.0f}%</b>", 3600)
            if mem.percent > ALERT_RAM:
                await _alert(admin_id, "ram", f"🔥 <b>RAM: {mem.percent:.0f}%</b>", 3600)
            disk_pct = disk.used / disk.total * 100
            if disk_pct > ALERT_DISK:
                await _alert(admin_id, "disk", f"🔥 <b>Disk: {disk_pct:.0f}%</b>", 3600)

            # ── Per-client checks ──
            for name, c in list(clients.items()):
                pub = c.get("public_key", "")
                online_now = _is_online(c, stats) and not c.get("disabled")
                was_online = _peer_online.get(pub, False)

                # ── Connect ──
                if online_now and not was_online:
                    ep = stats.get(pub, {}).get("endpoint", "-")
                    geo = await geoip_lookup(ep) if ep != "-" else {}
                    geo_str = ""
                    flag = ""
                    cc = geo.get("countryCode", "")
                    if geo.get("country"):
                        flag = geo_flag(cc)
                        geo_str = f"\n    🌍 {flag} {geo.get('country','')} {geo.get('city','')}"

                    # New country alert
                    known = c.get("known_countries", [])
                    if cc and cc not in known:
                        known.append(cc)
                        c["known_countries"] = known
                        save_clients(clients)
                        if len(known) > 1:
                            await _alert(admin_id, f"newgeo_{name}",
                                f"⚠️ <b>{name}</b> — новая страна: {flag} {geo.get('country','')}\n"
                                f"Ранее: {', '.join(known[:-1])}", 0)

                    _connect_times[pub] = time.time()
                    add_history({"client": name, "type": "connect", "endpoint": ep,
                                 "geo": f"{flag} {geo.get('country','')} {geo.get('city','')}" if geo.get("country") else ""})
                    try:
                        await bot.send_message(admin_id,
                            f"🟢 <b>{name}</b> подключился\n   <code>{ep}</code>{geo_str}", parse_mode="HTML")
                    except Exception: pass

                # ── Disconnect ──
                elif not online_now and was_online:
                    t_rx, t_tx = get_client_traffic(c, stats)
                    dur = int((time.time() - _connect_times.pop(pub, time.time())) / 60)
                    add_history({"client": name, "type": "disconnect", "duration_min": dur,
                                 "rx": t_rx, "tx": t_tx})
                    try:
                        await bot.send_message(admin_id,
                            f"⚪ <b>{name}</b> отключился ({dur}м)\n   ↓ {fmt_bytes(t_rx)}  ↑ {fmt_bytes(t_tx)}", parse_mode="HTML")
                    except Exception: pass

                _peer_online[pub] = online_now

                # ── Expiry check ──
                if c.get("expires") and not c.get("disabled"):
                    exp = datetime.fromisoformat(c["expires"])
                    if now > exp:
                        remove_peer_live(pub); c["disabled"] = True; save_clients(clients)
                        try:
                            await bot.send_message(admin_id, f"⏰ <b>{name}</b> — срок истёк, отключён.", parse_mode="HTML")
                        except Exception: pass

                # ── Auto-delete expired ──
                if c.get("expires") and c.get("disabled"):
                    exp = datetime.fromisoformat(c["expires"])
                    if (now - exp).days >= AUTO_DELETE_EXPIRED_DAYS:
                        create_backup("auto_delete")
                        remove_peer_live(pub); remove_peer_from_config(pub)
                        del clients[name]; save_clients(clients)
                        try:
                            await bot.send_message(admin_id,
                                f"🗑 <b>{name}</b> — авто-удалён (истёк {AUTO_DELETE_EXPIRED_DAYS}+ дней назад).", parse_mode="HTML")
                        except Exception: pass
                        continue

                # ── Traffic limit ──
                if c.get("traffic_limit_gb") and not c.get("disabled"):
                    t_rx, t_tx = get_client_traffic(c, stats)
                    if (t_rx + t_tx) >= c["traffic_limit_gb"] * (1024**3):
                        remove_peer_live(pub); c["disabled"] = True; save_clients(clients)
                        try:
                            await bot.send_message(admin_id,
                                f"📦 <b>{name}</b> — лимит {c['traffic_limit_gb']} GB исчерпан, отключён.", parse_mode="HTML")
                        except Exception: pass

                # ── Schedule enforcement ──
                if not c.get("disabled"):
                    within = is_within_schedule(c)
                    if within is False and not c.get("_scheduled_off"):
                        remove_peer_live(pub); c["_scheduled_off"] = True; save_clients(clients)
                    elif within is True and c.get("_scheduled_off"):
                        restore_peer_live(pub, c["psk"], c["ip"]); c.pop("_scheduled_off", None); save_clients(clients)

            # ── Daily report + snapshot ──
            today = now.strftime("%Y-%m-%d")
            if now.hour == DAILY_REPORT_HOUR and _last_daily_report != today:
                _last_daily_report = today
                snapshot_daily_traffic(clients, stats)
                create_backup("daily")

                total_rx = sum(get_client_traffic(c, stats)[0] for c in clients.values())
                total_tx = sum(get_client_traffic(c, stats)[1] for c in clients.values())
                on = sum(1 for c in clients.values() if _is_online(c, stats) and not c.get("disabled"))
                off = sum(1 for c in clients.values() if c.get("disabled"))
                cpu2 = psutil.cpu_percent(interval=0.5)
                mem2 = psutil.virtual_memory()

                report = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n📋 <b>Ежедневный отчёт</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📅 {now.strftime('%d.%m.%Y')}\n\n"
                    f"👥 Клиентов: {len(clients)}\n🟢 Online: {on}\n⏸ Отключено: {off}\n\n"
                    f"📈 Трафик: ↓ {fmt_bytes(total_rx)}  ↑ {fmt_bytes(total_tx)}\n"
                    f"🧠 CPU: {cpu2:.0f}%  💾 RAM: {mem2.percent:.0f}%\n\n🛡 AWG: Active  💾 Бэкап ✅")
                try: await bot.send_message(admin_id, report, parse_mode="HTML")
                except Exception: pass

                # Send backup files weekly (on Mondays)
                if now.weekday() == 0:
                    for path, fname in [(DATA_FILE, f"clients_{today}.json"), (AWG_CONF, f"awg0_{today}.conf")]:
                        if os.path.exists(path):
                            try:
                                with open(path, "rb") as f:
                                    sent = await bot.send_document(admin_id,
                                        BufferedInputFile(f.read(), filename=fname),
                                        caption=f"💾 Еженедельный бэкап: <b>{fname}</b>", parse_mode="HTML")
                                    asyncio.create_task(_auto_delete(sent, 600))
                            except Exception: pass

        except Exception as e:
            log.error(f"Loop error: {e}")

        await asyncio.sleep(NOTIFY_CHECK_INTERVAL)


# ─── Access requests ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("req_access:"))
async def cb_request_access(cb: CallbackQuery):
    parts = cb.data.split(":", 2)
    req_uid = int(parts[1])
    req_uname = parts[2] if len(parts) > 2 else str(req_uid)
    if req_uid != cb.from_user.id:
        await cb.answer("❌", show_alert=True); return
    superadmin_id = get_admin_id()
    if not superadmin_id:
        await cb.answer("❌ Суперадмин не найден", show_alert=True); return
    # Проверим, не одобрен ли уже
    if is_admin(req_uid):
        await cb.answer("✅ У вас уже есть доступ. Напишите /start", show_alert=True); return
    try:
        await bot.send_message(
            superadmin_id,
            f"📨 <b>Запрос на доступ к боту</b>\n\n"
            f"👤 @{req_uname} (id: <code>{req_uid}</code>)\n\n"
            f"Дать этому пользователю доступ?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{req_uid}:{req_uname[:20]}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"deny:{req_uid}:{req_uname[:20]}"),
            ]])
        )
        await cb.message.edit_text(
            f"✅ <b>Запрос отправлен администратору</b>\n\n"
            f"Ожидайте одобрения. После одобрения напишите /start.",
            parse_mode="HTML"
        )
    except Exception as e:
        await cb.answer(f"❌ Ошибка: {e}", show_alert=True)
    await cb.answer()


@router.callback_query(F.data.startswith("approve:"))
async def cb_approve_access(cb: CallbackQuery):
    if not is_superadmin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    parts = cb.data.split(":", 2)
    new_uid = int(parts[1])
    new_uname = parts[2] if len(parts) > 2 else str(new_uid)
    add_subadmin(new_uid, new_uname, cb.from_user.id)
    audit(cb.from_user.id, "APPROVE_ACCESS", f"uid={new_uid} @{new_uname}")
    await cb.message.edit_text(
        f"✅ <b>Доступ одобрен</b>\n\n👤 @{new_uname} (id: <code>{new_uid}</code>)",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            new_uid,
            f"✅ <b>Доступ одобрен!</b>\n\nНапишите /start чтобы начать.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await cb.answer("✅ Пользователь добавлен")


@router.callback_query(F.data.startswith("deny:"))
async def cb_deny_access(cb: CallbackQuery):
    if not is_superadmin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    parts = cb.data.split(":", 2)
    new_uid = int(parts[1])
    new_uname = parts[2] if len(parts) > 2 else str(new_uid)
    audit(cb.from_user.id, "DENY_ACCESS", f"uid={new_uid} @{new_uname}")
    await cb.message.edit_text(
        f"❌ <b>Доступ отклонён</b>\n\n👤 @{new_uname} (id: <code>{new_uid}</code>)",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            new_uid,
            f"❌ <b>В доступе отказано.</b>\n\nОбратитесь к администратору напрямую.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await cb.answer("❌ Отклонено")


# ─── Remnawave / VLESS ───────────────────────────────────────────────

async def remna_get(path: str) -> dict | None:
    headers = {"Authorization": f"Bearer {REMNAWAVE_TOKEN}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(f"{REMNAWAVE_URL}{path}", headers=headers) as r:
                if r.status == 200:
                    return await r.json()
    except Exception as e:
        log.error(f"remna_get {path}: {e}")
    return None

async def remna_post(path: str, data: dict) -> dict | None:
    headers = {"Authorization": f"Bearer {REMNAWAVE_TOKEN}",
                "Content-Type": "application/json", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.post(f"{REMNAWAVE_URL}{path}", headers=headers, json=data) as r:
                return await r.json()
    except Exception as e:
        log.error(f"remna_post {path}: {e}")
    return None

async def remna_patch(data: dict) -> dict | None:
    headers = {"Authorization": f"Bearer {REMNAWAVE_TOKEN}",
                "Content-Type": "application/json", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.patch(f"{REMNAWAVE_URL}/users", headers=headers, json=data) as r:
                return await r.json()
    except Exception as e:
        log.error(f"remna_patch: {e}")
    return None

async def remna_delete(path: str) -> bool:
    headers = {"Authorization": f"Bearer {REMNAWAVE_TOKEN}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.delete(f"{REMNAWAVE_URL}{path}", headers=headers) as r:
                d = await r.json()
                return d.get("response", {}).get("isDeleted", False)
    except Exception as e:
        log.error(f"remna_delete {path}: {e}")
    return False

def vless_status_icon(status: str) -> str:
    return {"ACTIVE": "🟢", "DISABLED": "⏸", "LIMITED": "📦", "EXPIRED": "⏰"}.get(status, "⚪")

def fmt_vless_traffic(used: int, limit: int) -> str:
    used_gb = used / 1024**3
    if limit == 0:
        return f"{used_gb:.2f} GB / ∞"
    limit_gb = limit / 1024**3
    pct = min(used / limit * 100, 100)
    return f"{progress_bar(pct, 8)} {used_gb:.2f}/{limit_gb:.0f} GB"

def vless_list_inline(users: list, page: int = 0) -> InlineKeyboardMarkup:
    total = len(users)
    total_pages = max(1, (total + VLESS_PER_PAGE - 1) // VLESS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_users = users[page * VLESS_PER_PAGE:(page + 1) * VLESS_PER_PAGE]
    buttons = []
    for u in page_users:
        icon = vless_status_icon(u["status"])
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {u['username']}",
            callback_data=f"vu:{u['uuid']}"
        )])
    nav = []
    if total_pages > 1:
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"vpage:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"vpage:{page+1}"))
        if nav:
            buttons.append(nav)
    buttons.append([
        InlineKeyboardButton(text="➕ Добавить", callback_data="vless:add"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="vless:list:0"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def vless_detail_inline(uuid: str, status: str) -> InlineKeyboardMarkup:
    if status == "ACTIVE":
        toggle_btn = InlineKeyboardButton(text="⏸ Отключить", callback_data=f"vdis:{uuid}")
    else:
        toggle_btn = InlineKeyboardButton(text="▶️ Включить", callback_data=f"ven:{uuid}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Подписка", callback_data=f"vsub:{uuid}"),
         InlineKeyboardButton(text="🔄 Обновить", callback_data=f"vu:{uuid}")],
        [toggle_btn,
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"vdel:{uuid}")],
        [InlineKeyboardButton(text="◀️ К списку", callback_data="vless:list:0")],
    ])


@router.message(F.text == BTN_VLESS)
async def msg_vless(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    stats_data = await remna_get("/system/stats")
    if not stats_data:
        await message.answer("❌ Remnawave недоступен", reply_markup=MAIN_KB)
        return
    s = stats_data.get("response", {})
    uc = s.get("users", {}).get("statusCounts", {})
    on = s.get("onlineStats", {}).get("onlineNow", 0)
    total_bytes = int(s.get("nodes", {}).get("totalBytesLifetime", 0))
    nodes = s.get("nodes", {}).get("totalOnline", 0)
    mem = s.get("memory", {})
    mem_pct = round(mem.get("used", 0) / mem.get("total", 1) * 100) if mem.get("total") else 0
    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n🔐 <b>VLESS панель (Remnawave)</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Пользователи: 🟢{uc.get('ACTIVE',0)} ⏸{uc.get('DISABLED',0)} "
        f"📦{uc.get('LIMITED',0)} ⏰{uc.get('EXPIRED',0)}\n"
        f"📡 Онлайн сейчас: <b>{on}</b>\n"
        f"📊 Суммарный трафик: <b>{fmt_bytes(total_bytes)}</b>\n"
        f"🖥 Нод онлайн: <b>{nodes}</b>\n"
        f"💾 RAM: {mem_pct}%\n\n"
        f"🌐 <a href='https://panelwin.mooo.com'>Открыть панель</a>"
    )
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True,
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [InlineKeyboardButton(text="📋 Пользователи", callback_data="vless:list:0"),
                              InlineKeyboardButton(text="➕ Добавить", callback_data="vless:add")],
                         ]))


@router.callback_query(F.data.startswith("vless:list:"))
async def cb_vless_list(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    page = int(cb.data.split(":")[2])
    data = await remna_get("/users?limit=100&offset=0")
    if not data:
        await cb.answer("❌ Ошибка API", show_alert=True); return
    users = data.get("response", {}).get("users", [])
    total = data.get("response", {}).get("total", 0)
    if not users:
        await cb.message.edit_text(
            "📭 <b>Нет пользователей</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="➕ Добавить", callback_data="vless:add")
            ]]),
            parse_mode="HTML"
        )
        await cb.answer(); return
    text = f"━━━━━━━━━━━━━━━━━━━━━━\n🔐 <b>VLESS пользователи</b> ({total})\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    page_users = users[page * VLESS_PER_PAGE:(page + 1) * VLESS_PER_PAGE]
    for u in page_users:
        icon = vless_status_icon(u["status"])
        used = u.get("userTraffic", {}).get("usedTrafficBytes", 0) or 0
        limit = u.get("trafficLimitBytes", 0) or 0
        exp = u.get("expireAt", "")
        exp_str = ""
        if exp and not exp.startswith("2099"):
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            days = (exp_dt - datetime.now(timezone.utc)).days
            exp_str = f" ⏰{days}д" if days >= 0 else " ⚠️истёк"
        text += f"{icon} <b>{u['username']}</b>{exp_str} — {fmt_bytes(used)}\n"
    await cb.message.edit_text(text, reply_markup=vless_list_inline(users, page),
                                parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("vpage:"))
async def cb_vpage(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    page = int(cb.data.split(":")[1])
    data = await remna_get("/users?limit=100&offset=0")
    if not data:
        await cb.answer("❌ Ошибка API", show_alert=True); return
    users = data.get("response", {}).get("users", [])
    total = data.get("response", {}).get("total", 0)
    text = f"━━━━━━━━━━━━━━━━━━━━━━\n🔐 <b>VLESS пользователи</b> ({total})\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    page_users = users[page * VLESS_PER_PAGE:(page + 1) * VLESS_PER_PAGE]
    for u in page_users:
        icon = vless_status_icon(u["status"])
        used = u.get("userTraffic", {}).get("usedTrafficBytes", 0) or 0
        exp = u.get("expireAt", "")
        exp_str = ""
        if exp and not exp.startswith("2099"):
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            days = (exp_dt - datetime.now(timezone.utc)).days
            exp_str = f" ⏰{days}д" if days >= 0 else " ⚠️истёк"
        text += f"{icon} <b>{u['username']}</b>{exp_str} — {fmt_bytes(used)}\n"
    await cb.message.edit_text(text, reply_markup=vless_list_inline(users, page),
                                parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("vu:"))
async def cb_vless_user(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    uuid = cb.data.split(":", 1)[1]
    data = await remna_get(f"/users/{uuid}")
    if not data or "response" not in data:
        # fallback: search in list
        list_data = await remna_get("/users?limit=100&offset=0")
        u = None
        if list_data:
            for user in list_data.get("response", {}).get("users", []):
                if user["uuid"] == uuid:
                    u = user
                    break
        if not u:
            await cb.answer("❌ Пользователь не найден", show_alert=True); return
    else:
        u = data["response"]

    used = u.get("userTraffic", {}).get("usedTrafficBytes", 0) or 0
    limit = u.get("trafficLimitBytes", 0) or 0
    online_at = u.get("userTraffic", {}).get("onlineAt")
    sub_url = u.get("subscriptionUrl", "—")
    status = u.get("status", "UNKNOWN")
    icon = vless_status_icon(status)
    exp = u.get("expireAt", "")
    exp_str = "∞"
    if exp and not exp.startswith("2099"):
        exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        days = (exp_dt - datetime.now(timezone.utc)).days
        exp_str = f"{days}д ({exp_dt.strftime('%d.%m.%Y')})" if days >= 0 else f"⚠️ Истёк ({exp_dt.strftime('%d.%m.%Y')})"
    online_str = "—"
    if online_at:
        try:
            ot = datetime.fromisoformat(online_at.replace("Z", "+00:00"))
            diff = datetime.now(timezone.utc) - ot
            mins = int(diff.total_seconds() // 60)
            if mins < 5: online_str = "🟢 онлайн"
            elif mins < 60: online_str = f"{mins}м назад"
            elif mins < 1440: online_str = f"{mins//60}ч назад"
            else: online_str = f"{mins//1440}д назад"
        except Exception:
            online_str = online_at[:10]
    ua = u.get("subLastUserAgent") or "—"
    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n{icon} <b>{u['username']}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Статус: <b>{status}</b>\n"
        f"📦 Трафик: <b>{fmt_vless_traffic(used, limit)}</b>\n"
        f"⏰ Истекает: <b>{exp_str}</b>\n"
        f"📡 Последний онлайн: <b>{online_str}</b>\n"
        f"📱 Клиент: <code>{ua[:40]}</code>\n\n"
        f"🔗 Подписка:\n<code>{sub_url}</code>"
    )
    await cb.message.edit_text(text, reply_markup=vless_detail_inline(uuid, status),
                                parse_mode="HTML", disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data.startswith("vsub:"))
async def cb_vless_sub(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    uuid = cb.data.split(":", 1)[1]
    list_data = await remna_get("/users?limit=100&offset=0")
    sub_url = None
    if list_data:
        for u in list_data.get("response", {}).get("users", []):
            if u["uuid"] == uuid:
                sub_url = u.get("subscriptionUrl")
                break
    if sub_url:
        await cb.message.answer(
            f"🔗 <b>Ссылка подписки:</b>\n<code>{sub_url}</code>\n\n"
            f"⚠️ <i>Удалится через 2 мин.</i>",
            parse_mode="HTML",
        )
        await cb.answer()
    else:
        await cb.answer("❌ Не найдено", show_alert=True)


@router.callback_query(F.data.startswith("vdis:"))
async def cb_vless_disable(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    uuid = cb.data.split(":", 1)[1]
    result = await remna_patch({"uuid": uuid, "status": "DISABLED"})
    if result and "response" in result:
        await cb.answer("⏸ Пользователь отключён")
        audit(cb.from_user.id, "VLESS_DISABLE", f"uuid={uuid}")
        # Refresh detail
        await cb_vless_user(cb)
    else:
        await cb.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("ven:"))
async def cb_vless_enable(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    uuid = cb.data.split(":", 1)[1]
    result = await remna_patch({"uuid": uuid, "status": "ACTIVE"})
    if result and "response" in result:
        await cb.answer("▶️ Пользователь включён")
        audit(cb.from_user.id, "VLESS_ENABLE", f"uuid={uuid}")
        await cb_vless_user(cb)
    else:
        await cb.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("vdel:"))
async def cb_vless_delete(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    uuid = cb.data.split(":", 1)[1]
    # Ask for confirmation
    await cb.message.edit_text(
        f"⚠️ <b>Удалить пользователя?</b>\n\n<code>{uuid}</code>\n\nЭто действие необратимо!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"vdelok:{uuid}"),
             InlineKeyboardButton(text="❌ Отмена", callback_data=f"vu:{uuid}")],
        ]),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("vdelok:"))
async def cb_vless_delete_ok(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    uuid = cb.data.split(":", 1)[1]
    ok = await remna_delete(f"/users/{uuid}")
    if ok:
        audit(cb.from_user.id, "VLESS_DELETE", f"uuid={uuid}")
        await cb.message.edit_text(
            "✅ <b>Пользователь удалён</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="◀️ К списку", callback_data="vless:list:0")
            ]]),
            parse_mode="HTML"
        )
    else:
        await cb.answer("❌ Ошибка удаления", show_alert=True)
    await cb.answer()


@router.callback_query(F.data == "vless:add")
async def cb_vless_add(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    await state.set_state(AddVlessUser.waiting_name)
    await cb.message.answer(
        "━━━━━━━━━━━━━━━━━━━━━━\n➕ <b>Новый VLESS пользователь</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✏️ Введите имя пользователя (латиница, цифры, _):\n"
        "<i>Примеры: ivan_phone, office_pc, guest1</i>",
        reply_markup=CANCEL_KB, parse_mode="HTML"
    )
    await cb.answer()


@router.message(AddVlessUser.waiting_name)
async def process_vless_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    name = message.text.strip()
    if not name or len(name) > 40 or name in RESERVED_TEXTS:
        await message.answer("❌ Недопустимое имя (1-40 символов).", reply_markup=CANCEL_KB)
        return
    # Validate: only alphanumeric, underscore, dash
    if not re.match(r'^[a-zA-Z0-9_\-]+$', name):
        await message.answer(
            "❌ Только латиница, цифры, _ и -\n<i>Пример: ivan_phone</i>",
            reply_markup=CANCEL_KB, parse_mode="HTML"
        )
        return
    await state.update_data(vless_name=name)
    await message.answer(
        f"✅ Имя: <b>{name}</b>\n\n📅 Выберите срок действия:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 месяц", callback_data="vexp:30"),
             InlineKeyboardButton(text="3 месяца", callback_data="vexp:90")],
            [InlineKeyboardButton(text="6 месяцев", callback_data="vexp:180"),
             InlineKeyboardButton(text="1 год", callback_data="vexp:365")],
            [InlineKeyboardButton(text="♾ Без срока", callback_data="vexp:0")],
        ]),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("vexp:"))
async def cb_vless_expiry(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    days = int(cb.data.split(":")[1])
    await state.update_data(vless_days=days)
    exp_label = f"{days} дней" if days > 0 else "без срока"
    await cb.message.edit_text(
        f"✅ Срок: <b>{exp_label}</b>\n\n📦 Выберите лимит трафика:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="10 GB", callback_data="vtraf:10"),
             InlineKeyboardButton(text="50 GB", callback_data="vtraf:50")],
            [InlineKeyboardButton(text="100 GB", callback_data="vtraf:100"),
             InlineKeyboardButton(text="500 GB", callback_data="vtraf:500")],
            [InlineKeyboardButton(text="♾ Безлимит", callback_data="vtraf:0")],
        ]),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("vtraf:"))
async def cb_vless_traffic(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer("🔒", show_alert=True); return
    gb = int(cb.data.split(":")[1])
    data = await state.get_data()
    name = data.get("vless_name")
    days = data.get("vless_days", 0)
    if not name:
        await cb.answer("❌ Имя не задано", show_alert=True); return
    # Calculate expireAt
    if days > 0:
        exp_dt = datetime.now(timezone.utc) + timedelta(days=days)
        expire_at = exp_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    else:
        expire_at = "2099-12-31T00:00:00.000Z"
    traffic_bytes = gb * 1024**3 if gb > 0 else 0
    payload = {
        "username": name,
        "trafficLimitBytes": traffic_bytes,
        "trafficLimitStrategy": "NO_RESET",
        "expireAt": expire_at,
        "description": f"created by bot",
        "activateAllInbounds": True,
    }
    result = await remna_post("/users", payload)
    await state.clear()
    if result and "response" in result:
        u = result["response"]
        sub_url = u.get("subscriptionUrl", "—")
        traf_str = f"{gb} GB" if gb > 0 else "безлимит"
        exp_str = f"{days} дней" if days > 0 else "без срока"
        audit(cb.from_user.id, "VLESS_ADD", f"name={name} exp={days}d traffic={gb}GB")
        await cb.message.edit_text(
            f"━━━━━━━━━━━━━━━━━━━━━━\n✅ <b>VLESS пользователь создан</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Имя: <b>{name}</b>\n"
            f"📅 Срок: <b>{exp_str}</b>\n"
            f"📦 Трафик: <b>{traf_str}</b>\n\n"
            f"🔗 Подписка:\n<code>{sub_url}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👤 Открыть", callback_data=f"vu:{u['uuid']}"),
                 InlineKeyboardButton(text="◀️ К списку", callback_data="vless:list:0")],
            ]),
            parse_mode="HTML", disable_web_page_preview=True
        )
    else:
        err = result.get("message", "неизвестная ошибка") if result else "нет ответа от API"
        await cb.message.edit_text(f"❌ <b>Ошибка создания:</b> {err}", parse_mode="HTML")
    await cb.answer()


# ─── Main ────────────────────────────────────────────────────────────

async def on_startup():
    asyncio.create_task(notification_loop())
    log.info("Bot started: notifications + watchdog + GeoIP + history + graphs + alerts + schedule + invites")

async def main():
    log.info("AmneziaWG Bot v2 starting...")
    dp.startup.register(on_startup)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
