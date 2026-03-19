#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
HA News Trigger Daemon — демон обновления новостей через Home Assistant
═══════════════════════════════════════════════════════════════════════════════

Назначение:
  Этот демон работает в фоне и следит за специальным переключателем
  (input_boolean) в Home Assistant. Как только переключатель включается —
  запускает скрипт обновления новостей, потом выключает переключатель обратно.

Схема работы:
  HA: input_boolean.news_refresh_trigger → ON
          ↓ (WebSocket event)
  Daemon: запускает ha_news_update.py
          ↓
  ha_news_update.py: получает RSS → обновляет HA helpers → новости в Mini App
          ↓
  Daemon: выключает триггер обратно (OFF)

Зачем так сделано:
  Кнопка "Обновить новости" в Mini App нажимает переключатель в HA.
  Это позволяет запускать обновление как из Mini App, так и из автоматизации HA
  (например по расписанию каждые 30 минут).

✏️ ЧТО МЕНЯТЬ:
  TRIGGER      — entity_id переключателя в HA. Создать: Настройки → Помощники
                 → Переключатель. По умолчанию: input_boolean.news_refresh_trigger
  NEWS_SCRIPT  — путь к скрипту обновления новостей (ha_news_update.py)
  RECONNECT_DELAY — задержка переподключения при обрыве (секунды)

Запуск:
  systemd сервис ha-news-trigger (смотри ha-news-trigger.service)
  Переменные окружения: HA_URL и HA_TOKEN из /opt/ha-bot/.env
═══════════════════════════════════════════════════════════════════════════════
"""
import asyncio, json, subprocess, time, sys, os

# ── Конфигурация ───────────────────────────────────────────────────────────────
HA_URL   = os.environ["HA_URL"].rstrip("/")       # URL Home Assistant из .env
HA_TOKEN = os.environ["HA_TOKEN"]                  # Токен HA из .env

# WebSocket URL — автоматически строится из HA_URL (https→wss, http→ws)
HA_WS    = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"

# ✏️ МЕНЯТЬ: entity_id переключателя-триггера в HA
TRIGGER  = "input_boolean.news_refresh_trigger"

# ✏️ МЕНЯТЬ: путь к скрипту обновления новостей
NEWS_SCRIPT = "/opt/meshcentral-bot/ha_news_update.py"

# Задержка переподключения при обрыве соединения с HA (секунды)
RECONNECT_DELAY = 10


# ── Утилиты ────────────────────────────────────────────────────────────────────
def log(msg):
    """Вывести строку лога с временной меткой в stdout (читается через journalctl)."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Управление триггером ───────────────────────────────────────────────────────
def turn_off_trigger(ws_send_func=None):
    """Выключить триггер в HA через REST API (не через WebSocket).

    Вызывается сразу после обнаружения события trigger→ON.
    Использует синхронный urllib (не asyncio) — вызывается из executor.

    ✏️ Менять не нужно. Если хочешь другой триггер — измени TRIGGER выше.
    """
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


# ── Запуск обновления новостей ─────────────────────────────────────────────────
def run_news_update():
    """Запустить ha_news_update.py как subprocess и логировать вывод.

    Выполняется в отдельном потоке (run_in_executor) чтобы не блокировать
    основной цикл событий asyncio.

    Таймаут: 120 секунд. Если скрипт завис — убивается принудительно.
    Последние 5 строк вывода выводятся в лог для диагностики.
    """
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


# ── Основной цикл: WebSocket к HA ─────────────────────────────────────────────
async def listen():
    """Подключиться к HA WebSocket и ждать событий переключения TRIGGER.

    Порядок работы:
      1. Подключаемся к WebSocket HA (/api/websocket)
      2. Авторизуемся токеном HA_TOKEN
      3. Подписываемся на все события state_changed
      4. Фильтруем только события от TRIGGER entity_id
      5. При state → "on": сбрасываем триггер + запускаем обновление новостей

    Если соединение разрывается — выбрасывается исключение и
    main() переподключается через RECONNECT_DELAY секунд.
    """
    import websockets
    log(f"Connecting to {HA_WS}")
    async with websockets.connect(HA_WS, ping_interval=30, open_timeout=20) as ws:

        # Шаг 1: получить приглашение auth_required
        msg = json.loads(await asyncio.wait_for(ws.recv(), 15))
        assert msg.get("type") == "auth_required"

        # Шаг 2: отправить токен авторизации
        await ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert msg.get("type") == "auth_ok", f"auth failed: {msg}"
        log("Auth OK ✓")

        # Шаг 3: подписаться на все изменения состояний
        await ws.send(json.dumps({
            "id": 1,
            "type": "subscribe_events",
            "event_type": "state_changed"   # любое изменение любой сущности
        }))
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert msg.get("success"), f"subscribe failed: {msg}"
        log(f"Subscribed to state_changed. Watching {TRIGGER}...")

        # Шаг 4: слушать события в бесконечном цикле
        async for raw in ws:
            try:
                msg = json.loads(raw)

                # Пропустить всё что не является событием
                if msg.get("type") != "event":
                    continue

                data = msg.get("event", {}).get("data", {})
                eid  = data.get("entity_id", "")

                # Интересует только наш триггер
                if eid != TRIGGER:
                    continue

                new_state = (data.get("new_state") or {}).get("state", "")

                if new_state == "on":
                    log(f"Trigger fired! ({TRIGGER} → on)")
                    # Сначала сбрасываем триггер (чтобы не сработал повторно),
                    # потом запускаем обновление новостей в отдельном потоке
                    turn_off_trigger()
                    asyncio.get_event_loop().run_in_executor(None, run_news_update)

            except Exception as e:
                log(f"Event processing error: {e}")


# ── Точка входа ────────────────────────────────────────────────────────────────
async def main():
    """Бесконечный цикл с автоматическим переподключением.

    При обрыве WebSocket соединения — ждёт RECONNECT_DELAY секунд и пробует снова.
    Никогда не падает — только логирует ошибки.
    """
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
