"""
MeshCentral integration via meshctrl subprocess.
Mounts /opt/meshcentral read-only as /meshcentral inside container.
Uses the same login-token approach as meshcentral-bot.
"""
import asyncio
import json
import logging
import os
import time

log = logging.getLogger(__name__)

MC_DIR   = os.getenv("MC_DIR", "/meshcentral")
MC_WSS   = os.getenv("MC_WSS", "wss://hub.office.mooo.com:443")
MESHCTRL = f"{MC_DIR}/node_modules/meshcentral/meshctrl.js"
MC_MAIN  = f"{MC_DIR}/node_modules/meshcentral/meshcentral.js"

_token: str = ""
_token_ts: float = 0
TOKEN_TTL = 3600  # regenerate every hour

_devices_cache: list = []
_devices_ts: float = 0
DEVICES_TTL = 30  # 30 seconds


async def _login_token() -> str:
    """Get login token key — from env (pre-generated) or via node subprocess."""
    global _token, _token_ts
    if _token and (time.time() - _token_ts) < TOKEN_TTL:
        return _token

    # Prefer pre-generated key from .env (avoids MongoDB dependency inside Docker)
    env_key = os.getenv("MC_TOKEN_KEY", "")
    if env_key:
        _token, _token_ts = env_key, time.time()
        return _token

    # Fallback: generate via node (only works when MC MongoDB is accessible)
    try:
        proc = await asyncio.create_subprocess_exec(
            "node", MC_MAIN, "--logintokenkey",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=MC_DIR,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        tok = stdout.decode().strip()
        if tok and len(tok) > 20:
            _token, _token_ts = tok, time.time()
        return _token
    except Exception as e:
        log.error(f"login_token: {e}")
        return _token


def _extract_json(raw: str, start_char: str = "[") -> object:
    idx = raw.find(start_char)
    if idx == -1:
        idx = raw.find("{")
    if idx == -1:
        return None
    try:
        return json.loads(raw[idx:])
    except Exception:
        return None


async def list_agents() -> list[dict]:
    """List all MC agents with name, id, online status, group."""
    global _devices_cache, _devices_ts
    if _devices_cache and (time.time() - _devices_ts) < DEVICES_TTL:
        return _devices_cache

    token = await _login_token()
    if not token:
        return _devices_cache

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", MESHCTRL, "ListDevices",
            "--url", MC_WSS,
            "--loginkey", token,
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        raw  = stdout.decode(errors="replace")
        data = _extract_json(raw, "[")
        if isinstance(data, list):
            _devices_cache = data
            _devices_ts    = time.time()
            return data
    except Exception as e:
        log.error(f"list_agents: {e}")
    return _devices_cache


async def get_agent_details(node_id: str) -> dict:
    """Get full device info via meshctrl deviceinfo."""
    token = await _login_token()
    if not token:
        return {}
    try:
        proc = await asyncio.create_subprocess_exec(
            "node", MESHCTRL, "deviceinfo",
            "--url", MC_WSS,
            "--loginkey", token,
            "--id", node_id,
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        raw  = stdout.decode(errors="replace")
        data = _extract_json(raw, "{")
        if isinstance(data, dict):
            return data
    except Exception as e:
        log.error(f"get_agent_details {node_id}: {e}")
    return {}


def load_wifi_neighbors() -> list[dict]:
    """Load network neighbors from wifi_clients.json (from netmap/keenetic probe)."""
    path = os.getenv("WIFI_CLIENTS_FILE", "/wifi_clients/wifi_clients.json")
    try:
        with open(path) as f:
            data = json.load(f)
        result = []
        for location, info in data.items():
            for client in info.get("clients", []):
                result.append({
                    "location":   location,
                    "ip":         client.get("ip", ""),
                    "mac":        client.get("mac", ""),
                    "name":       client.get("name") or client.get("hostname") or "",
                    "type":       client.get("type", "LAN"),
                    "iface":      client.get("iface", ""),
                    "updated":    info.get("updated", ""),
                })
        return result
    except Exception as e:
        log.debug(f"wifi_neighbors: {e}")
        return []
