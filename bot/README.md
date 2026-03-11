# 🏠 HA Home Bot — Telegram-бот для управления умным домом

Полнофункциональный Telegram-бот для управления Home Assistant с встроенным
Telegram Mini App (WebApp). Одновременно работает как обычный бот с командами
и как веб-приложение прямо внутри Telegram.

---

## 📋 Содержание

- [Что умеет](#что-умеет)
- [Архитектура](#архитектура)
- [Структура файлов](#структура-файлов)
- [Требования](#требования)
- [Установка](#установка)
- [Настройка .env](#настройка-env)
- [Настройка nginx](#настройка-nginx)
- [Команды бота](#команды-бота)
- [Mini App (WebApp)](#mini-app-webapp)
- [API эндпоинты](#api-эндпоинты)
- [База данных SQLite](#база-данных-sqlite)
- [Алерты и уведомления](#алерты-и-уведомления)
- [Frigate (камеры)](#frigate-камеры)
- [Семья и геолокация](#семья-и-геолокация)
- [Управление пользователями](#управление-пользователями)
- [Systemd юнит](#systemd-юнит)
- [Запуск через Docker](#запуск-через-docker)

---

## Что умеет

### Telegram Bot
| Функция | Описание |
|---------|----------|
| 💡 Управление светом | Включение/выключение каждого светильника по отдельности и все сразу |
| 🌡️ Климат | Температура и влажность в помещениях, управление тёплым полом |
| ⚡ Энергия | Потребление по фазам, стоимость за день/месяц, прогноз, история графиком |
| 📹 Камеры (Frigate) | Снимок, последние события детекции, скачать клип |
| 👨‍👩‍👧 Семья | Геолокация всех членов семьи в реальном времени |
| 🕌 Намаз | Время молитв из HA, таймер, напоминание за 15 и 5 минут |
| 🛒 Список покупок | Просмотр, добавление и вычёркивание через HA todo.* |
| 🤖 Пылесос | Запуск уборки, возврат на базу, мониторинг статуса |
| 📺 Телевизор | Включение, выключение, регулировка громкости |
| 🎬 Сцены | Создание и запуск сцен (Спать, Уходим, Кино, Вечер…) |
| 🔔 Алерты | Настраиваемые уведомления по мощности, температуре, движению |
| 📊 Отчёты | Еженедельный и ежемесячный отчёт по энергопотреблению |
| 🌅 Утренняя сводка | Каждый день в 7:30 МСК: семья дома, намаз, погода, расход |
| 🌐 Интернет | Алерт при падении и восстановлении интернет-соединения |
| 🤖 AI чат | Диалог с Claude API прямо в боте |
| 💾 Backup/Restore | Экспорт и импорт конфигурации через Telegram |

### Mini App (WebApp)
- Панель управления всем умным домом в реальном времени (SSE push)
- Управление любым устройством из HA одним касанием
- Сцены с расписанием (можно создавать прямо в интерфейсе)
- Журнал активности
- Настройка разделов и порядка устройств
- Ночной режим
- История распознавания лиц
- Статистика потребления энергии, почасовые графики
- Статус сервера (CPU, RAM, Disk, Uptime)
- Логбук HA — последние события

---

## Архитектура

```
Telegram App
    │
    ├── Telegram Bot API (Long Polling, aiogram 3.x)
    │       └── Команды: /status /lights /energy /climate ...
    │
    └── Mini App WebApp (HTTPS, через nginx)
            └── GET /ha-app/ → index.html
                GET /ha-app/api/status → JSON статус умного дома
                GET /ha-app/api/events → SSE real-time поток
                POST /ha-app/api/action → управление устройством

Сервер (VPS или домашний):
    ┌─────────────────────────────────────────┐
    │  bot.py                                  │
    │  ├── aiogram — Telegram bot polling      │
    │  ├── aiohttp — HTTP сервер :8766         │
    │  ├── Background loops:                   │
    │  │   ├── alert_loop() — проверка алертов │
    │  │   ├── _ha_state_watch_loop() — HA WS  │
    │  │   └── _frigate_event_loop() — камеры  │
    │  └── SQLite ha_bot.db — данные           │
    │                                          │
    │  nginx → /ha-app/* → :8766               │
    └─────────────────────────────────────────┘
            │
            │  HTTPS API
            ▼
    Home Assistant (локальная сеть или облако)
    ├── REST API /api/*
    ├── WebSocket /api/websocket
    └── Frigate NVR /api/frigate/*
```

---

## Структура файлов

```
/opt/ha-bot/
├── bot.py                  ← Основной код бота (5000+ строк)
├── .env                    ← Конфигурация (токены, URL)
├── ha_bot.db               ← SQLite база данных (основное хранилище)
├── webapp/
│   └── index.html          ← Mini App (Single Page Application)
├── # Устаревшие JSON-файлы (автоматически мигрируются в SQLite):
├── devices.json            ← (legacy) Конфигурация устройств
├── sections.json           ← (legacy) Конфигурация разделов
├── activity_log.json       ← (legacy) Журнал активности
├── alerts_config.json      ← (legacy) Настройки алертов
├── scenes.json             ← (legacy) Сцены
└── faces_log.json          ← (legacy) Лог распознавания лиц
```

---

## Требования

```
Python 3.11+
pip пакеты (requirements.txt):
  aiogram>=3.4
  aiohttp>=3.9
  python-dotenv
  psutil
  matplotlib
  websockets
  anthropic          ← для AI чата (опционально)
```

### Установка зависимостей

```bash
pip install aiogram aiohttp python-dotenv psutil matplotlib websockets anthropic
```

---

## Установка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/mr-khamzat/ha-home-bot.git /opt/ha-bot

# 2. Создать .env файл (см. раздел ниже)
nano /opt/ha-bot/.env

# 3. Запустить бота
python3 /opt/ha-bot/bot.py

# Или через systemd (см. раздел Systemd юнит)
```

---

## Настройка .env

Создай файл `/opt/ha-bot/.env` и заполни все параметры:

```env
# ── Telegram ───────────────────────────────────────────────────────────────────
# Токен бота от @BotFather (обязательно)
BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Твой Telegram ID — можно узнать у @userinfobot (обязательно)
ADMIN_ID=293633093

# ── Home Assistant ─────────────────────────────────────────────────────────────
# Внешний URL твоего Home Assistant (с https://, без слеша в конце)
HA_URL=https://ha.example.com

# Long-lived токен HA: Профиль → Безопасность → Токены долгосрочного доступа
HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6...

# ── Mini App ───────────────────────────────────────────────────────────────────
# Случайный секретный токен для авторизации запросов к API (придумай сам)
# Команда для генерации: python3 -c "import secrets; print(secrets.token_hex(32))"
WEBAPP_TOKEN=ваш_секретный_токен_32_символа

# ── Claude AI (опционально — для команды /ai) ──────────────────────────────────
# API ключ от console.anthropic.com
ANTHROPIC_API_KEY=sk-ant-...
```

### Где получить токены

| Параметр | Где взять |
|----------|-----------|
| `BOT_TOKEN` | Telegram → @BotFather → /newbot |
| `ADMIN_ID` | Telegram → @userinfobot |
| `HA_TOKEN` | HA → Профиль (внизу) → Токены долгосрочного доступа → Создать |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys |

---

## Настройка nginx

Бот запускает HTTP-сервер на порту `8766` (только `127.0.0.1`).
Nginx проксирует внешние запросы на него.

Добавь в конфигурацию nginx своего домена:

```nginx
# SSE-поток — долгий таймаут, без буферизации
location ^~ /ha-app/api/events {
    proxy_pass         http://127.0.0.1:8766;
    proxy_http_version 1.1;
    proxy_set_header   Connection "";
    proxy_read_timeout 3600s;
    proxy_buffering    off;
    proxy_cache        off;
    add_header Cache-Control "no-cache" always;
}

# Основное приложение
location ^~ /ha-app {
    proxy_pass         http://127.0.0.1:8766;
    proxy_http_version 1.1;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 60s;
    proxy_buffering    off;
    # X-Frame-Options НЕ ставим — нужен для работы Telegram WebApp
    add_header Cache-Control "no-cache" always;
}
```

> **Важно**: не ставь `X-Frame-Options: DENY` для `/ha-app` — Telegram
> открывает Mini App в iframe и он перестанет работать.

---

## Команды бота

| Команда | Что делает |
|---------|-----------|
| `/start` | Приветствие, регистрация, открыть главное меню |
| `/status` | Полный статус дома: свет, климат, энергия, семья |
| `/lights` | Управление светом (включить/выключить каждый светильник) |
| `/lights_sync` | Сканировать HA и добавить новые устройства |
| `/climate` | Температура, влажность, тёплый пол |
| `/energy` | Потребление: сегодня, месяц, прогноз, фазы |
| `/weather` | Погода и прогноз на 3 дня (Open-Meteo) |
| `/namaz` | Время молитв + таймер намаза |
| `/cameras` | Камеры: снимок, последние события Frigate |
| `/family` | Геолокация членов семьи (person.* в HA) |
| `/shopping` | Список покупок из HA todo-листа |
| `/vacuum` | Управление роботом-пылесосом |
| `/tv` | Управление телевизором |
| `/scenes` | Сцены: список, запуск, создание |
| `/ai` | Войти в режим AI-чата с Claude |
| `/devices` | Управление устройствами: иконки, разделы, переименование |
| `/users` | (Только admin) Управление пользователями |
| `/invite` | Создать ссылку-приглашение для нового пользователя |
| `/backup` | Экспортировать конфигурацию (devices + activity log) |
| `/restore` | Импортировать конфиг (отправь JSON-файл в ответ) |
| `/app` | Открыть Mini App (WebApp) |

---

## Mini App (WebApp)

Mini App — это одностраничное веб-приложение (`webapp/index.html`),
которое открывается прямо внутри Telegram.

### Как открыть

1. Написать боту `/app` — появится кнопка «Открыть панель»
2. Или кнопка «🖥️ Открыть панель» в главном меню
3. Прямая ссылка: `https://твой-домен/ha-app/`

### Разделы Mini App

| Раздел | Что показывает |
|--------|---------------|
| 🔔 Статус | Мощность, интернет, климат, время намаза |
| 👨‍👩‍👧 Семья | Кто дома, кто где — реальное время |
| 💡 Свет | Переключение каждого светильника, всё сразу |
| ⚡ Энергия | Фазы, стоимость, прогресс-бары, почасовой график |
| 🌡️ Климат | Температура по комнатам, тёплый пол |
| 📺 TV | Статус, название медиа, громкость |
| 🕌 Намаз | Расписание молитв, таймер |
| 🌤️ Погода | Текущая + прогноз на 3 дня |
| 🎬 Сцены | Кнопки быстрого запуска, создание новых сцен |
| 📊 Активность | Журнал действий (кто что включал) |
| 📹 Камеры | Последние события детекции, снимок |
| 🖥️ Сервер | CPU/RAM/Disk VPS, Uptime |
| 📋 История HA | Логбук последних событий HA |
| 🙂 Лица | История распознавания лиц Frigate |
| 🌙 Ночной режим | Автоматическое выключение по расписанию |

### Реальное время (SSE)

Приложение подписывается на поток `GET /ha-app/api/events` — это SSE
(Server-Sent Events). Бот слушает WebSocket HA и при изменении любой
сущности мгновенно отправляет обновление в браузер. Никакого polling,
страница обновляется в реальном времени.

---

## API эндпоинты

Все эндпоинты требуют токен. Передаётся через:
- Cookie: `session_token=ТОКЕН`
- Query param: `?token=ТОКЕН`
- Telegram WebApp initData (автоматически при открытии из Telegram)

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/ha-app/` | Mini App HTML |
| GET | `/ha-app/api/health` | Проверка работоспособности (без авторизации) |
| GET | `/ha-app/api/status` | Полный статус умного дома (кеш 5 сек) |
| GET | `/ha-app/api/events` | SSE real-time поток изменений |
| POST | `/ha-app/api/action` | Вызвать сервис HA (`service`, `entity_id`) |
| GET | `/ha-app/api/devices` | Список всех устройств |
| POST | `/ha-app/api/devices` | Обновить конфигурацию устройства |
| GET | `/ha-app/api/sections` | Список разделов Mini App |
| POST | `/ha-app/api/sections` | Обновить порядок/видимость разделов |
| GET | `/ha-app/api/scenes` | Список сцен |
| POST | `/ha-app/api/scenes` | Создать/обновить сцену |
| POST | `/ha-app/api/scenes/{id}/run` | Запустить сцену |
| DELETE | `/ha-app/api/scenes/{id}` | Удалить сцену |
| GET | `/ha-app/api/alerts` | Конфигурация алертов |
| POST | `/ha-app/api/alerts` | Сохранить конфигурацию алертов |
| GET | `/ha-app/api/activity` | Последние 50 записей журнала |
| POST | `/ha-app/api/activity/clear` | Очистить журнал |
| GET | `/ha-app/api/night-mode` | Настройки ночного режима |
| POST | `/ha-app/api/night-mode` | Сохранить ночной режим |
| GET | `/ha-app/api/server-stats` | Статистика VPS и HA-сервера |
| GET | `/ha-app/api/ha/entities` | Все entity из HA по домену |
| POST | `/ha-app/api/ha/scan` | Запустить сканирование устройств |
| GET | `/ha-app/api/energy/hourly` | Почасовое потребление |
| GET | `/ha-app/api/logbook` | Логбук HA |
| GET | `/ha-app/api/presence-stats` | Статистика присутствия |
| GET | `/ha-app/api/frigate/events` | Последние события детекции |
| GET | `/ha-app/api/frigate/recordings` | Последние записи |
| GET | `/ha-app/api/frigate/clip/{id}` | Прокси для клипа события |
| GET | `/ha-app/api/frigate/thumb/{id}` | Прокси для превью |
| POST | `/ha-app/api/frigate/send` | Отправить клип в Telegram |
| GET | `/ha-app/api/frigate/faces/history` | История распознавания лиц |
| POST | `/ha-app/api/auth/telegram` | Авторизация через Telegram initData |

---

## База данных SQLite

Все данные хранятся в `/opt/ha-bot/ha_bot.db` (WAL режим).

### Таблицы

```sql
-- Устройства умного дома: иконка, раздел, порядок, включено/выключено из UI
CREATE TABLE devices (
    entity_id TEXT PRIMARY KEY,   -- ID сущности HA, напр. "light.svet_krovat"
    name      TEXT,               -- Отображаемое имя, напр. "Кровать"
    icon      TEXT,               -- Эмодзи-иконка, напр. "🛏️"
    section   TEXT,               -- Раздел: "lights", "cameras", или id кастомного
    enabled   INTEGER,            -- 1 = показывать в UI, 0 = скрыть
    ord       INTEGER             -- Порядок в списке (меньше = выше)
);

-- Разделы панели управления
CREATE TABLE sections (
    id      TEXT PRIMARY KEY,    -- Уникальный ID раздела, напр. "cameras"
    name    TEXT,                -- Отображаемое имя, напр. "📹 Камеры"
    icon    TEXT,                -- Эмодзи
    enabled INTEGER,             -- Активен ли раздел
    ord     INTEGER,             -- Порядок в меню
    hidden  INTEGER,             -- Скрыт пользователем (1/0)
    builtin INTEGER              -- Встроенный (нельзя удалить) (1/0)
);

-- Сцены: набор действий, запускаемых кнопкой
CREATE TABLE scenes (
    id         TEXT PRIMARY KEY,  -- UUID сцены
    name       TEXT,              -- Название, напр. "Спать"
    icon       TEXT,              -- Эмодзи, напр. "🌙"
    entities   TEXT,              -- JSON: список действий [{service, entity_id, ...}]
    created_at TEXT               -- Дата создания ISO
);

-- Конфигурация (ключ-значение JSON): alerts, night_mode
CREATE TABLE config (
    key   TEXT PRIMARY KEY,
    value TEXT                   -- JSON строка
);

-- Журнал активности: кто что делал
CREATE TABLE activity_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT,                 -- Метка времени "2026-03-11 20:00:00"
    action TEXT,                 -- Действие, напр. "webapp:light.turn_on"
    detail TEXT                  -- Детали, напр. "light.svet_krovat"
);

-- Журнал распознавания лиц Frigate
CREATE TABLE faces_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT,
    person   TEXT,               -- Имя распознанного человека
    event_id TEXT,               -- ID события Frigate
    camera   TEXT                -- Имя камеры
);

-- Пользователи бота с ролями
CREATE TABLE family_users (
    user_id TEXT PRIMARY KEY,    -- Telegram ID (строка)
    data    TEXT                 -- JSON: {role, name, invited_by, ...}
);
```

---

## Алерты и уведомления

Система алертов работает как фоновая задача `alert_loop()` — проверяет
состояние каждую минуту. Настраиваются через Mini App или `/ha-app/api/alerts`.

### Типы алертов

| Алерт | Условие | Описание |
|-------|---------|----------|
| `power` | Мощность > порога (Вт) | Высокое потребление электроэнергии |
| `temp` | Температура вне диапазона | Слишком холодно или жарко |
| `person` | Детекция движения Frigate | Кто-то у двери / в кадре |
| `namaz` | За 15 мин / 5 мин до молитвы | Напоминание о намазе |
| `morning` | 07:30 МСК каждый день | Утренняя сводка |
| `frigate` | Событие детекции Frigate | Уведомление с фото |
| `inet` | binary_sensor интернета | Падение/восстановление интернета |

### Тихие часы

В настройках алертов можно задать тихие часы (`quiet_hours_start` / `quiet_hours_end`).
В эти часы power и temp алерты не отправляются.

### Формат настроек алертов

```json
{
    "power_threshold": 4000,
    "temp_min": 18,
    "temp_max": 27,
    "quiet_hours_start": 23,
    "quiet_hours_end": 7,
    "enabled": {
        "power": true,
        "temp": true,
        "person": true,
        "namaz": true,
        "morning": true,
        "frigate": true,
        "inet": true
    }
}
```

---

## Frigate (камеры)

Интеграция с [Frigate NVR](https://frigate.video/) — open-source система
видеонаблюдения с детекцией объектов через ИИ.

### Что поддерживается

- Получение снимков с камер в реальном времени
- Список последних событий детекции (person, car, dog...)
- Скачивание клипов событий
- Уведомления при детекции (с фото в Telegram)
- Распознавание лиц — уведомление когда видит знакомого человека
- История лиц в Mini App

### Настройка Frigate в HA

Frigate должен быть установлен как дополнение HA или отдельно.
Бот обращается к нему через HA API (`/api/frigate/*`).

### Переменные для Frigate в bot.py

```python
FRIGATE_ENTRY_ID = "01KK75FZXWFAADKHF38W5EJ1XM"  # ID интеграции Frigate в HA
```

Найти ID можно в HA: Настройки → Устройства и сервисы → Frigate → URL интеграции.

---

## Семья и геолокация

Бот отслеживает все `person.*` сущности в HA.

### Как настроить в HA

1. HA → Настройки → Люди → Добавить человека
2. Привязать к нему `device_tracker.*` (приложение HA на телефоне)
3. Включить зоны (Дом, Работа, Офис...)

Бот будет показывать:
- Кто дома / кто не дома
- GPS координаты (кнопка «Открыть карту» → Google Maps)
- Статистику присутствия в Mini App

---

## Управление пользователями

Бот поддерживает несколько пользователей с разными ролями.

### Роли

| Роль | Доступ |
|------|--------|
| `admin` | Полный доступ, управление пользователями |
| `family` | Просмотр и управление устройствами |
| `viewer` | Только просмотр статуса |

### Как добавить пользователя

1. Отправить боту `/invite` — получишь одноразовую ссылку
2. Пользователь переходит по ссылке и пишет боту
3. Admin получает запрос и одобряет/отклоняет

### Команды управления пользователями

```
/users          — список пользователей
/invite         — создать приглашение
/users → роль  — сменить роль пользователя
/users → удалить — удалить пользователя
```

---

## Systemd юнит

Создай файл `/etc/systemd/system/ha-bot.service`:

```ini
[Unit]
Description=Home Assistant Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ha-bot
ExecStart=/usr/bin/python3 /opt/ha-bot/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable ha-bot
systemctl start ha-bot

# Логи
journalctl -u ha-bot -f
```

---

## Запуск через Docker

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc libffi-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "bot.py"]
```

```yaml
# docker-compose.yml
version: "3.8"
services:
  ha-bot:
    build: .
    restart: unless-stopped
    ports:
      - "127.0.0.1:8766:8766"
    volumes:
      - ./ha_bot.db:/app/ha_bot.db
      - ./webapp:/app/webapp
    env_file:
      - .env
```

```bash
docker compose up -d
docker compose logs -f ha-bot
```

---

## Переменные окружения — полный список

| Переменная | Обязательная | Описание |
|-----------|:---:|---------|
| `BOT_TOKEN` | ✅ | Токен Telegram бота |
| `ADMIN_ID` | ✅ | Telegram ID главного администратора |
| `HA_URL` | ✅ | URL Home Assistant (https://...) |
| `HA_TOKEN` | ✅ | Long-lived токен HA |
| `WEBAPP_TOKEN` | ✅ | Секрет для авторизации Mini App |
| `ANTHROPIC_API_KEY` | ❌ | Ключ Claude API для команды /ai |

---

## Лицензия

MIT — используй свободно, форкай, улучшай.

---

## Вопросы и поддержка

Открывай [Issues](https://github.com/mr-khamzat/ha-home-bot/issues) на GitHub.
