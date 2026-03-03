#!/usr/bin/env python3
"""
Daemon: watches input_boolean.news_refresh_trigger via HA WebSocket.
When it turns ON → runs ha_news_update.py, then resets boolean to OFF.
"""
import asyncio, json, subprocess, time, sys, os

HA_WS    = "wss://ha-as.khamzat-home.crazedns.ru/api/websocket"
HA_URL   = "https://ha-as.khamzat-home.crazedns.ru"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIyODNjNGZkYjJmZmQ0ZjZhYWIyNDhkODFlMTRmZWQ1MSIsImlhdCI6MTc3MjQ0MzA4NSwiZXhwIjoyMDg3ODAzMDg1fQ.nGHRLmY8aJDa618QsgGQ2iP3Nrn3BEzC8UWLYxZkpJU"
TRIGGER  = "input_boolean.news_refresh_trigger"
NEWS_SCRIPT = "/opt/meshcentral-bot/ha_news_update.py"

RECONNECT_DELAY = 10  # сек между попытками переподключения

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def turn_off_trigger(ws_send_func=None):
    """Turn off the trigger boolean via REST (fire and forget)."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{HA_URL}/api/services/input_boolean/turn_off",
            data=json.dumps({"entity_id": TRIGGER}).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        log(f"  turn_off failed: {e}")

def run_news_update():
    log(f"Running news update...")
    try:
        result = subprocess.run(
            [sys.executable, NEWS_SCRIPT],
            capture_output=True, text=True, timeout=120
        )
        lines = (result.stdout + result.stderr).strip().split("\n")
        for line in lines[-5:]:  # последние 5 строк в лог
            log(f"  > {line}")
        log(f"News update finished (rc={result.returncode})")
    except subprocess.TimeoutExpired:
        log("News update TIMEOUT (120s)")
    except Exception as e:
        log(f"News update ERROR: {e}")

async def listen():
    import websockets
    log(f"Connecting to {HA_WS}")
    async with websockets.connect(HA_WS, ping_interval=30, open_timeout=20) as ws:
        # Auth
        msg = json.loads(await asyncio.wait_for(ws.recv(), 15))
        assert msg.get("type") == "auth_required"
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert msg.get("type") == "auth_ok", f"auth failed: {msg}"
        log("Auth OK ✓")

        # Subscribe to state_changed events
        await ws.send(json.dumps({
            "id": 1,
            "type": "subscribe_events",
            "event_type": "state_changed"
        }))
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert msg.get("success"), f"subscribe failed: {msg}"
        log(f"Subscribed to state_changed. Watching {TRIGGER}...")

        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") != "event":
                    continue
                data = msg.get("event", {}).get("data", {})
                eid  = data.get("entity_id", "")
                if eid != TRIGGER:
                    continue
                new_state = (data.get("new_state") or {}).get("state", "")
                if new_state == "on":
                    log(f"Trigger fired! ({TRIGGER} → on)")
                    # Сброс триггера сразу, новости запускаем в фоне
                    turn_off_trigger()
                    asyncio.get_event_loop().run_in_executor(None, run_news_update)
            except Exception as e:
                log(f"Event processing error: {e}")

async def main():
    while True:
        try:
            await listen()
        except Exception as e:
            log(f"Connection lost: {e}")
            log(f"Reconnecting in {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    log("=== HA News Trigger Daemon started ===")
    asyncio.run(main())
