# 🏠 HA Bot — Telegram Mini App для Home Assistant

Telegram-бот + Mini App (веб-приложение внутри Telegram) для управления умным домом через Home Assistant.
Весь интерфейс — внутри Telegram, никаких сторонних приложений.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![aiohttp](https://img.shields.io/badge/aiohttp-3.x-green) ![HA](https://img.shields.io/badge/Home%20Assistant-2024+-orange)

---

## ✨ Возможности

| Раздел | Что умеет |
|--------|-----------|
| 🔔 Статус | Мощность, температура, интернет, энергозатраты |
| 💡 Устройства | Управление светом, розетками; кастомные разделы |
| 📹 Камеры | Просмотр через Frigate: стрим, события, видеоклипы |
| 🎬 Сцены | Создание сцен + автоматизации по времени/событию |
| 👨‍👩‍👧 Семья | Местоположение, статус «дома/не дома» |
| 🖥️ Мониторинг | CPU / RAM / Диск / Uptime — VPS **и** HA-сервера |
| 📋 История | Журнал событий HA (logbook) |
| 📂 Разделы | Управление всеми разделами: скрыть, переместить, создать |

---

## 📋 Требования

### Обязательно
- **VPS** — Ubuntu 20.04+, от 512 МБ RAM, публичный IP
- **Home Assistant** — любая установка, доступная по **HTTPS** с VPS
- **Telegram Bot** — создать через [@BotFather](https://t.me/BotFather)
- **Python 3.10+** на VPS
- **Nginx** + **SSL-сертификат** (certbot) для вашего домена

### Опционально (расширенные функции)
- **Frigate NVR** — камеры, события, видеоклипы
- **System Monitor** (интеграция HA) — мониторинг железа HA-сервера
- **Yandex Weather** / Open-Meteo — погода в приложении

---

## 🚀 Установка пошагово

### Шаг 1 — Создайте Telegram-бота

1. Откройте [@BotFather](https://t.me/BotFather) → `/newbot`
2. Придумайте имя и username (например `MyHomeBot`)
3. Сохраните **BOT_TOKEN** (вид: `123456789:AABBccddeeff...`)
4. Создайте Mini App: `/newapp` → выберите бота → укажите URL вашего сервера (шаг 6)

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
pip3 install aiohttp aiogram psutil python-dateutil
```

### Шаг 5 — Создайте файл конфигурации `.env`

```bash
cp /tmp/mc-stack/bot/webapp/.env.example /opt/ha-bot/.env
nano /opt/ha-bot/.env   # заполните своими данными
```

Минимальный набор переменных:

```env
# Токен бота от @BotFather
BOT_TOKEN=123456789:AABB_ВАШ_ТОКЕН

# Ваш Telegram ID (узнать: @userinfobot)
ADMIN_ID=123456789

# Home Assistant — внешний HTTPS-адрес, доступный с VPS
HA_URL=https://your-ha.yourdomain.com

# Long-Lived Access Token из HA:
# HA → Профиль → Security → Long-Lived Access Tokens → Создать
HA_TOKEN=eyJhbGciOiJIUzI1NiIs...

# Секретный токен для API мини апс (любые 32+ случайных символа)
# python3 -c "import secrets; print(secrets.token_hex(16))"
WEBAPP_TOKEN=сгенерируйте_случайную_строку_32_символа

# ⚠️ ОБЯЗАТЕЛЬНО: публичный HTTPS URL мини апс (ваш домен + /ha-app/)
# Без этой переменной кнопка "Панель управления" не появится!
WEBAPP_URL=https://YOUR_DOMAIN/ha-app/

# HA-логины пользователей с правами admin в мини апс (через запятую)
HA_WEBAPP_ADMINS=your_ha_username
```

> **Как получить HA_TOKEN:**
> Home Assistant → Профиль (аватар снизу слева) → прокрутить вниз → **Долгосрочные токены доступа** → Создать токен → скопировать

> **⚠️ WEBAPP_URL — критически важно!**
> Это ваш личный URL. Без него бот не покажет кнопку Mini App.
> Пример: `https://hub.mydomain.com/ha-app/`
> Каждый деплой использует свой URL — он нигде не захардкожен в коде.

### Шаг 6 — Настройте Nginx

```bash
cat > /etc/nginx/sites-available/ha-bot << 'EOF'
server {
    listen 443 ssl;
    server_name your-vps.example.com;  # ← замените на ваш домен

    ssl_certificate     /etc/letsencrypt/live/your-vps.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-vps.example.com/privkey.pem;

    # Все запросы /ha-app/ → бот (порт 8766)
    location /ha-app/ {
        proxy_pass http://127.0.0.1:8766;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
EOF

ln -sf /etc/nginx/sites-available/ha-bot /etc/nginx/sites-enabled/ha-bot
nginx -t && systemctl reload nginx
```

### Шаг 7 — SSL-сертификат

```bash
certbot --nginx -d your-vps.example.com
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

### Шаг 9 — Проверка

```bash
# Статус
systemctl status ha-bot

# Логи (Ctrl+C для выхода)
journalctl -u ha-bot -f

# Тест API
curl https://your-vps.example.com/ha-app/
```

---

## ⚙️ Первый запуск Mini App

1. Напишите `/start` вашему боту в Telegram
2. Нажмите кнопку **🏠 Умный Дом** — откроется Mini App
3. В BotFather настройте кнопку меню: `/setmenubutton` → выберите бота → введите URL

---

## 📁 Структура файлов

```
/opt/ha-bot/
├── bot.py              # Бэкенд: aiohttp-сервер + Telegram-хендлеры
├── webapp/
│   └── index.html      # Весь фронтенд (HTML + CSS + JS в одном файле)
├── .env                # Конфигурация (⚠️ никогда не коммитить в git!)
├── devices.json        # Настройки устройств (создаётся автоматически)
├── sections.json       # Конфигурация разделов (создаётся автоматически)
└── activity_log.json   # История действий (создаётся автоматически)
```

---

## 🔧 Настройка устройств и разделов

После запуска откройте Mini App:

1. Нажмите **📂 Разделы** (вкладка Устройства)
2. Здесь отображаются **все разделы** приложения:
   - **Встроенные** (Статус, Семья, Энергия и т.д.) — можно скрыть
   - **Разделы устройств** (Камеры, Свет и т.д.) — полное управление
3. Нажмите **✏️ Изменить** → **➕ Добавить** → выберите устройство из HA

---

## 📹 Камеры (Frigate)

1. Установите [Frigate NVR](https://frigate.video/) на сервере с HA
2. HA → Настройки → Интеграции → **Frigate** → установить
3. Камеры появятся в разделе Камеры автоматически

---

## 📊 Мониторинг HA-сервера (CPU/RAM/Диск/Uptime)

1. HA → Настройки → Устройства и службы → **Добавить интеграцию**
2. Найдите **System Monitor** → установить
3. Данные появятся в блоке 🖥️ Сервер

> Или установите через API (пример в `bot.py`, функция `_web_server_stats`).

---

## 🌐 Архитектура

```
Telegram ←→ Telegram Servers ←→ Бот на VPS (aiohttp, порт 8766)
                                      ↓
                              Nginx (HTTPS :443)
                              └── /ha-app/ → 127.0.0.1:8766
                                      ↓
                              HA REST API ←→ Home Assistant
```

**Авторизация Mini App:**
1. Пользователь открывает Mini App → видит форму входа
2. Вводит логин/пароль от **своего** Home Assistant
3. Бот проверяет через HA login_flow API
4. При успехе — выдаёт `WEBAPP_TOKEN` для API-запросов
5. Токен сохраняется в localStorage (сессия не истекает)

**Управление доступом:**
- Только пользователи с аккаунтом в **вашем** HA могут войти
- `HA_WEBAPP_ADMINS` — список логинов с полным доступом (admin)
- Остальные — viewer, admin может ограничить что им видно
- Через раздел **🔐 Администрирование** admin настраивает права каждого

**Безопасность:**
- URL мини апс берётся из `WEBAPP_URL` в `.env` — не хардкожен в коде
- `WEBAPP_TOKEN` генерируется вами — не хранится в репозитории
- Без правильного логина/пароля HA — доступа нет
- `.env` файл **никогда не коммитить** в git!

---

## 🛠️ Полезные команды

```bash
# Перезапустить бота
systemctl restart ha-bot

# Логи последних 50 строк
journalctl -u ha-bot -n 50

# Обновить код
cd /tmp/mc-stack && git pull
cp bot/ha_bot.py /opt/ha-bot/bot.py
cp bot/webapp/index.html /opt/ha-bot/webapp/index.html
systemctl restart ha-bot

# Бэкап настроек
cp /opt/ha-bot/devices.json ~/devices_backup_$(date +%Y%m%d).json
cp /opt/ha-bot/sections.json ~/sections_backup_$(date +%Y%m%d).json
```

---

## ❓ Частые вопросы

**Q: Mini App не открывается / белый экран**
A: Откройте DevTools → Console. Проверьте что nginx проксирует `/ha-app/` на порт 8766.

**Q: Ошибка авторизации**
A: `WEBAPP_TOKEN` в `.env` должен совпадать. После изменения — перезапустить сервис.

**Q: Устройства HA не видны**
A: `HA_URL` должен быть внешним HTTPS-адресом, доступным с VPS. Токен — с правами admin.

**Q: Камеры пустые**
A: Нужна интеграция Frigate в HA. Без неё раздел Камеры не работает.

**Q: Мониторинг HA показывает «Нет данных»**
A: Добавьте интеграцию **System Monitor** в HA (см. выше).

**Q: SSL не обновляется автоматически**
A: Убедитесь что certbot.timer активен: `systemctl status certbot.timer`

---

## 🤝 Участие в проекте

Pull Request'ы приветствуются! Для крупных изменений — сначала создайте Issue.

**Структура кода:**
- `ha_bot.py` — бэкенд: aiohttp-сервер, Telegram-хендлеры, API-эндпоинты
- `webapp/index.html` — весь фронтенд в одном файле (HTML + CSS + JS)

---

## 📄 Лицензия

MIT
