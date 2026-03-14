# 🏠 HA Bot — Telegram Mini App для Home Assistant

Telegram-бот + полноценное веб-приложение (Mini App) внутри Telegram для управления умным домом через Home Assistant. Никаких сторонних приложений — всё прямо в Telegram.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![aiohttp](https://img.shields.io/badge/aiohttp-3.x-green) ![HA](https://img.shields.io/badge/Home%20Assistant-2024+-orange) ![SQLite](https://img.shields.io/badge/SQLite-3.x-lightgrey)

---

## ✨ Что умеет

### Разделы Mini App

| Раздел | Описание |
|--------|----------|
| 🔔 **Статус** | Мощность потребления, температура в комнатах, состояние интернета, затраты на энергию |
| 👨‍👩‍👧 **Семья** | Карта местоположения членов семьи, статус «дома / не дома» через `person.*` из HA |
| 🚶 **Присутствие** | История приходов и уходов по геозонам HA |
| 🚪 **У двери** | Журнал распознавания лиц через Frigate: фото, имя, камера, время — с fullscreen просмотром |
| ⚡ **Энергия** | Статистика потребления, графики за день/неделю/месяц |
| 💡 **Устройства** | Управление светом, розетками, климатом, ТВ, пылесосом — любыми entity из HA |
| 📹 **Камеры** | Просмотр потока Frigate, снимки по событиям, видеоклипы с детекцией |
| 🎬 **Сцены** | Запуск и создание сцен HA, автоматизации по расписанию |
| 🔔 **Алерты** | Уведомления об отключении света, интернета, движении |
| 🖥️ **Мониторинг** | CPU / RAM / Диск / Uptime VPS-сервера и HA-сервера в реальном времени |
| 📋 **История** | Журнал событий HA (logbook) с фильтрацией |
| 🔐 **Администрирование** | Только для admin: управление пользователями и их правами доступа |

### Система доступа (multi-user)

- Вход через **логин и пароль вашего Home Assistant** — никаких отдельных аккаунтов
- Два уровня прав: **admin** и **viewer**
- Admin видит все разделы и управляет правами других пользователей
- Viewer видит только то, что разрешил admin — настраивается per-user
- Имя пользователя и аватар подтягиваются из профиля HA автоматически
- Сессия сохраняется в localStorage браузера — не нужно входить каждый раз

---

## 📋 Требования

### Обязательно
- **VPS** — Ubuntu 20.04+, от 512 МБ RAM, публичный IP, домен с HTTPS
- **Home Assistant** — любая установка, доступная по **HTTPS** с VPS
- **Telegram Bot** — создать через [@BotFather](https://t.me/BotFather)
- **Python 3.10+** на VPS
- **Nginx** + **SSL-сертификат** (certbot) для вашего домена

### Опционально (расширенные функции)
- **Frigate NVR** — камеры, события, видеоклипы, распознавание лиц у двери
- **System Monitor** (интеграция HA) — мониторинг CPU/RAM/диска HA-сервера
- **Yandex Weather** / Open-Meteo — погода в приложении

---

## 🚀 Установка пошагово

### Шаг 1 — Создайте Telegram-бота

1. Откройте [@BotFather](https://t.me/BotFather) → `/newbot`
2. Придумайте имя и username (например `MyHomeBot`)
3. Сохраните **BOT_TOKEN** (вид: `123456789:AABBccddeeff...`)

### Шаг 2 — Подготовьте VPS

```bash
# Обновление системы
apt update && apt upgrade -y

# Зависимости
apt install -y python3 python3-pip nginx certbot python3-certbot-nginx git

# Директория проекта
mkdir -p /opt/ha-bot/webapp
```

### Шаг 3 — Скачайте код

```bash
git clone https://github.com/mr-khamzat/mc-stack.git /tmp/mc-stack
cp /tmp/mc-stack/bot/ha_bot.py /opt/ha-bot/bot.py
cp /tmp/mc-stack/bot/webapp/index.html /opt/ha-bot/webapp/index.html
```

### Шаг 4 — Установите Python-зависимости

```bash
pip3 install aiohttp aiogram psutil python-dateutil aiosqlite
```

### Шаг 5 — Создайте файл конфигурации `.env`

```bash
cp /tmp/mc-stack/bot/webapp/.env.example /opt/ha-bot/.env
nano /opt/ha-bot/.env
```

Заполните все переменные (описание каждой ниже):

```env
# ─── Telegram ───────────────────────────────────────────────────────────────
# Токен бота от @BotFather
BOT_TOKEN=7123456789:AAF-ВАШ_ТОКЕН

# Ваш Telegram user ID (узнать: @userinfobot)
ADMIN_ID=123456789

# ─── Home Assistant ─────────────────────────────────────────────────────────
# Внешний HTTPS-адрес HA, доступный с VPS (без слэша в конце)
HA_URL=https://homeassistant.yourdomain.com

# Long-Lived Access Token из HA:
# HA → Профиль (аватар снизу слева) → Security → Long-Lived Access Tokens → Создать
HA_TOKEN=eyJhbGciOiJIUzI1NiIs...

# ─── Mini App ───────────────────────────────────────────────────────────────
# Секретный токен для API мини апс (любая случайная строка, min 32 символа)
# Генерация: python3 -c "import secrets; print(secrets.token_hex(16))"
WEBAPP_TOKEN=сгенерированная_случайная_строка_32_символа

# ⚠️ ОБЯЗАТЕЛЬНО: публичный HTTPS URL мини апс (ваш домен + /ha-app/)
# Telegram требует HTTPS! Именно этот URL открывается в мини апс.
# Без этой переменной кнопка "Панель управления" в боте не появится!
WEBAPP_URL=https://YOUR_DOMAIN/ha-app/

# Локальный путь к папке с webapp (обычно не менять)
WEBAPP_DIR=/opt/ha-bot/webapp

# ─── Права доступа ──────────────────────────────────────────────────────────
# HA-логины с правами admin в мини апс (через запятую, без пробелов)
# Остальные пользователи получат роль viewer
HA_WEBAPP_ADMINS=your_ha_username
```

> **Почему WEBAPP_URL не захардкожен в коде?**
> Каждый разворачивает бот на своём домене. URL берётся только из `.env` — так ваш личный адрес не попадает в репозиторий. Без `WEBAPP_URL` кнопка Mini App в боте не отобразится.

### Шаг 6 — Настройте SSL-сертификат

```bash
certbot --nginx -d your-vps.example.com
```

### Шаг 7 — Настройте Nginx

```bash
cat > /etc/nginx/sites-available/ha-bot << 'EOF'
server {
    listen 443 ssl;
    server_name your-vps.example.com;  # ← ваш домен

    ssl_certificate     /etc/letsencrypt/live/your-vps.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-vps.example.com/privkey.pem;

    # Mini App и API: все запросы /ha-app/ → бот (порт 8766)
    location /ha-app/ {
        proxy_pass http://127.0.0.1:8766;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/ha-bot /etc/nginx/sites-enabled/ha-bot
nginx -t && systemctl reload nginx
```

### Шаг 8 — Создайте systemd-сервис

```bash
cat > /etc/systemd/system/ha-bot.service << 'EOF'
[Unit]
Description=Home Assistant Telegram Mini App Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ha-bot
EnvironmentFile=/opt/ha-bot/.env
ExecStart=/usr/bin/python3 /opt/ha-bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ha-bot
systemctl start ha-bot
```

### Шаг 9 — Подключите Mini App к боту (BotFather)

1. Откройте [@BotFather](https://t.me/BotFather) → `/newapp`
2. Выберите вашего бота
3. Введите название приложения (например: `Smart Home`)
4. Загрузите иконку 640×640 (или любое фото)
5. В поле **Web App URL** введите ваш `WEBAPP_URL` из `.env`
6. Сохраните Short Name (например `home`)

Также настройте кнопку меню:
- BotFather → `/setmenubutton` → выберите бота → введите `WEBAPP_URL`

### Шаг 10 — Проверка

```bash
# Статус сервиса
systemctl status ha-bot

# Живые логи
journalctl -u ha-bot -f

# Тест доступности
curl -I https://your-vps.example.com/ha-app/
```

---

## ⚙️ Первый вход в Mini App

1. Напишите `/start` вашему боту в Telegram
2. Нажмите кнопку **🏠 Панель управления** — откроется Mini App
3. На экране входа введите **логин и пароль от вашего Home Assistant**
4. После входа — ваше имя и аватар подтянутся из профиля HA автоматически

> Mini App использует ваши учётные данные HA для аутентификации.
> Никаких отдельных паролей создавать не нужно.

---

## 👥 Управление пользователями (Admin)

### Как добавить пользователя

Пользователь просто открывает Mini App и вводит свои логин/пароль от HA. При первом входе он автоматически получает роль **viewer**.

### Как настроить права (Admin панель)

1. Войдите в Mini App под admin-аккаунтом
2. Прокрутите вниз до раздела **🔐 Администрирование**
3. Нажмите на имя пользователя
4. Включите/выключите нужные разделы
5. Нажмите **Сохранить**

Разделы, доступные для управления:
- 👨‍👩‍👧 Семья / 🚶 Присутствие / 🚪 У двери
- ⚡ Энергия / 💡 Устройства (свет, климат, ТВ, пылесос)
- 🎬 Сцены / 🔔 Алерты

Viewer видит только разрешённые разделы. Admin всегда видит всё.

---

## 📁 Структура файлов

```
/opt/ha-bot/
├── bot.py              # Бэкенд: aiohttp-сервер + Telegram-хендлеры + API
├── webapp/
│   └── index.html      # Весь фронтенд (HTML + CSS + JS в одном файле)
├── .env                # Конфигурация (⚠️ никогда не коммитить в git!)
├── ha_bot.db           # SQLite база: пользователи, лица, история активности
└── (devices.json)      # Старый формат устройств (если есть — совместимость)
```

---

## 📹 Камеры и распознавание лиц (Frigate)

### Базовые камеры

1. Установите [Frigate NVR](https://frigate.video/) на сервере с HA
2. HA → Настройки → Интеграции → **Frigate** → установить
3. Камеры и события появятся в разделе **📹 Камеры**

### Распознавание лиц (У двери)

Если в Frigate настроено распознавание лиц (`double_take` или нативное):

1. При обнаружении лица — запись попадает в базу данных бота
2. Раздел **🚪 У двери** показывает: фото, имя, камера, время
3. Нажмите на миниатюру — фото откроется на весь экран

---

## 📊 Мониторинг серверов

### HA-сервер (CPU/RAM/Диск/Uptime)

1. HA → Настройки → Устройства и службы → **Добавить интеграцию**
2. Найдите **System Monitor** → установить
3. Данные появятся в блоке **🖥️ Сервер**

### VPS-сервер

Данные о VPS (где запущен бот) собираются автоматически через `psutil`.

---

## 🌐 Архитектура

```
Пользователь → Telegram → Telegram Servers
                                ↓
                         Бот на VPS (aiohttp, 127.0.0.1:8766)
                                ↓
                     Nginx (HTTPS :443, /ha-app/ → :8766)
                                ↓
                      HA REST API / login_flow API
                                ↓
                         Home Assistant
```

### Как работает авторизация

1. Пользователь открывает Mini App → видит форму входа
2. Вводит **логин и пароль от своего Home Assistant**
3. Бот проверяет через HA `login_flow` API (стандартный механизм HA)
4. При успехе — бот выдаёт `WEBAPP_TOKEN` для последующих API-запросов
5. Имя пользователя читается из `/auth/current_user` (Bearer токен HA)
6. Аватар берётся из `person.{username}` entity в HA (если настроен)
7. Токен и данные сохраняются в `localStorage` — повторный вход не нужен

### База данных (SQLite)

Файл `ha_bot.db` создаётся автоматически при первом запуске:

| Таблица | Содержимое |
|---------|-----------|
| `webapp_users` | username, display_name, role, permissions, last_login |
| `faces_log` | ts, person, event_id, camera — журнал распознанных лиц |
| `activity_log` | История действий пользователей |

### Безопасность

- `WEBAPP_URL` берётся только из `.env` — не хранится в коде репозитория
- `WEBAPP_TOKEN` генерируется вами — не хранится в репозитории
- Без правильного логина/пароля HA — доступа к Mini App нет
- Admin не может задать права другому admin — только viewer-ам
- `.env` файл **никогда не коммитить** в git (добавлен в `.gitignore`)

---

## 🛠️ Полезные команды

```bash
# Перезапустить бот
systemctl restart ha-bot

# Живые логи
journalctl -u ha-bot -f

# Последние 50 строк логов
journalctl -u ha-bot -n 50

# Обновить код из репозитория
cd /tmp/mc-stack && git pull
cp bot/ha_bot.py /opt/ha-bot/bot.py
cp bot/webapp/index.html /opt/ha-bot/webapp/index.html
systemctl restart ha-bot

# Бэкап базы данных
cp /opt/ha-bot/ha_bot.db ~/ha_bot_backup_$(date +%Y%m%d).db
```

---

## ❓ Частые вопросы

**Q: Mini App не открывается / белый экран**
A: Проверьте что `WEBAPP_URL` в `.env` указывает на ваш домен с HTTPS. Откройте DevTools → Console — там будет ошибка. Убедитесь что nginx проксирует `/ha-app/` на порт 8766.

**Q: Кнопка «Панель управления» не появляется в боте**
A: `WEBAPP_URL` в `.env` не заполнен или пустой. Заполните и перезапустите сервис.

**Q: Ошибка при входе «Ошибка подключения к HA»**
A: Проверьте `HA_URL` — он должен быть внешним HTTPS-адресом, доступным с VPS. Проверьте командой: `curl -k https://ваш-ha-адрес/api/`

**Q: Вхожу под правильным логином/паролем HA, но ошибка авторизации**
A: `HA_TOKEN` (Long-Lived Access Token) должен иметь права admin в HA. Пересоздайте токен.

**Q: Устройства HA не отображаются**
A: `HA_TOKEN` в `.env` должен быть с правами администратора HA.

**Q: Пользователь видит разделы, которые я ему запретил**
A: После изменения прав в Admin панели пользователю нужно выйти и войти снова (или перезагрузить Mini App).

**Q: Раздел «У двери» не обновляется**
A: Требуется интеграция Frigate с настроенным распознаванием лиц. Бот должен получать события от Frigate через HA webhook.

**Q: Камеры пустые / «Нет данных»**
A: Нужна интеграция Frigate в HA. Без неё раздел Камеры не работает.

**Q: Мониторинг HA-сервера показывает «Нет данных»**
A: Добавьте интеграцию **System Monitor** в HA (см. раздел выше).

**Q: SSL-сертификат не обновляется автоматически**
A: `systemctl status certbot.timer` — должен быть active. Если нет: `systemctl enable certbot.timer && systemctl start certbot.timer`

**Q: Хочу использовать на нескольких серверах / с несколькими ботами**
A: Каждый инстанс — отдельный `.env` с уникальным `WEBAPP_TOKEN` и `WEBAPP_URL`.

---

## 🤝 Участие в проекте

Pull Request'ы приветствуются! Для крупных изменений — сначала создайте Issue.

**Структура кода:**
- `bot/ha_bot.py` — бэкенд: aiohttp-сервер, Telegram-хендлеры, API-эндпоинты, SQLite
- `bot/webapp/index.html` — весь фронтенд в одном файле (HTML + CSS + JS)
- `bot/webapp/.env.example` — шаблон конфигурации

---

## 📄 Лицензия

MIT
