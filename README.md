# 🏠 HA Home Bot — Умный дом в Telegram

Telegram-бот + веб-интерфейс (Mini App) для управления умным домом через Home Assistant.

## Что это такое?

Один Python-файл (`ha_bot.py`) запускает одновременно:
- **Telegram бот** — команды, алерты, медиа, управление через кнопки
- **Веб-сервер** — Mini App открывается прямо в Telegram, как приложение

Mini App — это красивый современный интерфейс с анимациями, живым фоном,
PWA (устанавливается на телефон), поддержкой уведомлений и real-time обновлениями.

---

## Скриншоты

> *Добавь сюда скриншоты Mini App и бота*

---

## Возможности

### Telegram бот
| Команда | Что делает |
|---------|-----------|
| `/start` | Главное меню |
| `/app` | Открыть Mini App |
| `/status` | Полный статус дома |
| `/lights` | Управление светом |
| `/climate` | Климат и тёплый пол |
| `/energy` | Потребление электроэнергии |
| `/weather` | Погода на 3 дня |
| `/namaz` | Время молитв |
| `/cameras` | Камеры Frigate |
| `/family` | Где находятся домочадцы |
| `/shopping` | Список покупок |
| `/vacuum` | Робот-пылесос |
| `/tv` | Телевизор |
| `/scenes` | Сцены (Спать, Уходим, Кино...) |
| `/ai` | Чат с Claude AI |
| `/sslcheck` | Проверка SSL сертификатов |
| `/users` | Управление пользователями |
| `/backup` | Бэкап конфига |

### Mini App (веб-интерфейс)
- 💡 Свет — включить/выключить все устройства
- 🌡 Климат — температура, влажность, sparkline-график
- ⚡ Электроэнергия — текущее потребление, фазы, прогноз
- 🌤 Погода — красивый виджет с иконками и прогнозом
- 🕌 Намаз — текущее/следующее время молитвы
- 📷 Камеры — снимки и события Frigate
- 👨‍👩‍👧 Семья — иконки присутствия по геолокации HA
- 🔔 Push-уведомления (Web Push, без приложения)
- 📱 PWA — устанавливается на главный экран телефона
- ☀️ Живой фон — меняется по времени суток
- 🌙 Тёмная/светлая тема

### Фоновые задачи
- Алерты (энергия, климат, устройства) — каждую минуту
- Утренний брифинг — 08:00 (погода, энергия, намаз)
- Авто-бэкап БД в Telegram — каждую ночь в 03:00
- Проверка SSL сертификатов — каждый день в 10:00

---

## Требования

- **Ubuntu 22.04 / 24.04** (VPS или Proxmox VM/LXC)
- **Python 3.11+**
- **Home Assistant** с Long-Lived Token
- **Telegram Bot Token** (создать через @BotFather)
- **HTTPS домен** — нужен для Telegram Mini App
- Минимум ресурсов: 1 CPU, 512 MB RAM, 5 GB диск

---

---

# 🚀 Установка

---

## Вариант 1: VPS (Ubuntu 22.04 / 24.04)

### Шаг 1 — Получить код

```bash
git clone https://github.com/mr-khamzat/mc-stack.git /tmp/mc-stack
cp -r /tmp/mc-stack/bot /opt/ha-bot
```

### Шаг 2 — Установить Python и зависимости

```bash
apt update && apt install -y python3 python3-pip python3-venv git

cd /opt/ha-bot
python3 -m venv venv
source venv/bin/activate

pip install aiogram aiohttp python-dotenv psutil matplotlib \
            pywebpush websockets cryptography
```

### Шаг 3 — Создать .env файл

```bash
cp webapp/.env.example .env
nano .env
```

> Подробнее о каждой переменной — в разделе **[Конфигурация .env](#конфигурация-env)** ниже.

### Шаг 4 — Запустить как systemd сервис

```bash
cat > /etc/systemd/system/ha-bot.service << 'EOF'
[Unit]
Description=HA Home Bot + Mini App
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ha-bot
ExecStart=/opt/ha-bot/venv/bin/python3 /opt/ha-bot/ha_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now ha-bot
```

### Шаг 5 — Проверить

```bash
systemctl status ha-bot
journalctl -u ha-bot -f
```

Если всё ок — бот напишет в Telegram: `✅ Бот запущен`.

---

## Вариант 2: Proxmox (с нуля, для начинающих)

### 2.1 Создать LXC контейнер

В Proxmox веб-интерфейсе:

```
Правый клик на узле → Create CT
  General:
    CT ID: 200 (любой свободный)
    Hostname: ha-bot
    Password: придумай пароль
  Template:
    Скачай: ubuntu-24.04-standard (кнопка Download в Storage → local → CT Templates)
    Template: ubuntu-24.04-standard
  Disk:
    Storage: local-lvm
    Disk size: 8 GB
  CPU: 1 core
  Memory: 512 MB
  Swap: 512 MB
  Network:
    Bridge: vmbr0
    IPv4: DHCP (или статический IP если нужен)
  DNS: использовать настройки хоста
```

Нажми Finish → Start.

### 2.2 Зайти в консоль

В Proxmox: выбери контейнер → Console.

```bash
apt update && apt upgrade -y
```

### 2.3 Установить бота

Точно так же, как на VPS (Шаги 1–5 выше).

### 2.4 Настроить доступ снаружи

Mini App требует HTTPS. Без публичного IP — используй **Cloudflare Tunnel** (бесплатно).

```bash
# Установить cloudflared
curl -L --output /usr/local/bin/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared

# Войти (откроет ссылку — перейди в браузере)
cloudflared tunnel login

# Создать туннель
cloudflared tunnel create ha-bot

# Настроить DNS (замени yourdomain.com на свой домен в Cloudflare)
cloudflared tunnel route dns ha-bot app.yourdomain.com

# Запустить туннель как systemd сервис
cloudflared service install
```

После этого Mini App будет доступен по `https://app.yourdomain.com/ha-app/`.

> **Нет домена?** Зарегистрируй бесплатный на freedns.afraid.org или duckdns.org,
> затем добавь в Cloudflare.

---

---

# 🔗 Настройка URL для Mini App — КРИТИЧЕСКИ ВАЖНО

Telegram Mini App работает только через **HTTPS**. Нужно настроить 3 места:

---

## 1. Переменная WEBAPP_URL в .env

```env
WEBAPP_URL=https://ВАШ_ДОМЕН/ha-app/
```

Примеры:
- `https://app.yourdomain.com/ha-app/` (Cloudflare Tunnel)
- `https://home.yourdomain.com/ha-app/` (nginx на VPS)

⚠️ Важно: должен заканчиваться на `/ha-app/` со слешем!

---

## 2. Кнопка меню бота в @BotFather

```
Открой @BotFather в Telegram
→ /mybots
→ Выбери своего бота
→ Bot Settings
→ Menu Button
→ Edit Menu Button URL

Введи: https://ВАШ_ДОМЕН/ha-app/
```

Теперь в чате с ботом появится кнопка "Открыть приложение" внизу экрана.

---

## 3. nginx (если используешь свой nginx)

Бот слушает порт **8766** только на `127.0.0.1`. Нужно проксировать через nginx:

```nginx
# Добавь в блок server {} своего домена:

# SSE — события реального времени (долгое соединение)
location ^~ /ha-app/api/events {
    proxy_pass         http://127.0.0.1:8766;
    proxy_http_version 1.1;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   Connection "";
    proxy_read_timeout 3600s;
    proxy_buffering    off;
    proxy_cache        off;
    add_header Cache-Control "no-cache" always;
    add_header X-Accel-Buffering "no" always;
}

# Остальные запросы /ha-app
location ^~ /ha-app {
    proxy_pass         http://127.0.0.1:8766;
    proxy_http_version 1.1;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 60s;
    proxy_buffering    off;
    client_max_body_size 20m;
    add_header Cache-Control "no-cache" always;
}
```

```bash
nginx -t && nginx -s reload
```

---

## 4. Проверка

```bash
# Должен вернуть {"status": "ok", ...}
curl https://ВАШ_ДОМЕН/ha-app/api/health
```

---

---

# ⚙️ Конфигурация .env

Файл: `/opt/ha-bot/.env` (скопируй из `webapp/.env.example`)

```env
# ─── Обязательные параметры ───────────────────────────────────────────────────

# Токен бота — получи у @BotFather → /newbot
BOT_TOKEN=7123456789:AAF-REPLACE_WITH_YOUR_BOT_TOKEN

# Твой Telegram ID — узнай у @userinfobot
ADMIN_ID=123456789

# URL Home Assistant (https, без слеша в конце)
HA_URL=https://homeassistant.yourdomain.com

# Long-Lived Token HA:
#   HA → Профиль (внизу слева) → Security → Long-Lived Access Tokens → Create Token
HA_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.REPLACE_WITH_YOUR_HA_TOKEN

# Секретный токен для Mini App API (случайная строка, мин. 16 символов)
# Сгенерировать: python3 -c "import secrets; print(secrets.token_hex(16))"
WEBAPP_TOKEN=REPLACE_WITH_RANDOM_SECRET_TOKEN

# Публичный HTTPS URL мини-апп (ОБЯЗАТЕЛЬНО заканчивается на /ha-app/)
WEBAPP_URL=https://YOUR_DOMAIN/ha-app/

# ─── Опциональные параметры ───────────────────────────────────────────────────

# Папка с файлами веб-апп (обычно не менять)
WEBAPP_DIR=/opt/ha-bot/webapp

# HA-логины пользователей с правами admin в мини-апп (через запятую)
# Остальные пользователи получат роль viewer
HA_WEBAPP_ADMINS=your_ha_username

# Домены для проверки SSL сертификатов (через запятую)
# Если не задано — проверяется только домен из WEBAPP_URL
# SSL_CHECK_DOMAINS=yourdomain.com,sub.yourdomain.com

# Публичный IP сервера (для WebRTC/TURN если используются камеры)
# SERVER_IP=1.2.3.4
# TURN_SECRET=change_me_turn_secret

# URL Frigate (если используется NVR)
# FRIGATE_URL=http://192.168.1.100:5000

# Ключ Claude AI для команды /ai
# ANTHROPIC_API_KEY=sk-ant-REPLACE_WITH_YOUR_KEY
```

---

---

# 📁 Структура файлов

```
/opt/ha-bot/
├── ha_bot.py             # Главный файл — бот + веб-сервер
├── .env                  # Твой конфиг (создать из webapp/.env.example)
├── ha_bot.db             # SQLite база данных (создаётся автоматически)
├── backups/              # Авто-бэкапы БД (создаётся автоматически)
├── vapid_private.pem     # Ключ Web Push (создаётся автоматически)
├── vapid_public.txt      # Публичный VAPID ключ
└── webapp/
    ├── index.html        # Весь Mini App (один HTML файл, ~9000 строк)
    ├── manifest.json     # PWA манифест (иконка, цвет, название)
    ├── sw.js             # Service Worker (Web Push уведомления)
    └── .env.example      # Пример конфига — скопируй в /opt/ha-bot/.env
```

---

---

# 🛠 Управление

```bash
# Статус
systemctl status ha-bot

# Логи в реальном времени
journalctl -u ha-bot -f

# Перезапуск (после изменения ha_bot.py или .env)
systemctl restart ha-bot

# Остановить
systemctl stop ha-bot
```

---

# 🔄 Обновление

```bash
cd /tmp/mc-stack && git pull

# Обновить файлы
cp /tmp/mc-stack/bot/ha_bot.py /opt/ha-bot/ha_bot.py
cp /tmp/mc-stack/bot/webapp/index.html /opt/ha-bot/webapp/index.html
cp /tmp/mc-stack/bot/webapp/sw.js /opt/ha-bot/webapp/sw.js

# Перезапустить
systemctl restart ha-bot
```

---

---

# ❓ FAQ

**Как получить Bot Token?**
Напиши @BotFather → `/newbot` → введи имя и username → скопируй токен.

**Как узнать свой Telegram ID?**
Напиши боту @userinfobot — он ответит твоим числовым ID.

**Как получить HA Long-Lived Token?**
HA → твой профиль (нижний левый угол) → Security → Long-Lived Access Tokens → Create Token.

**Mini App не открывается / белый экран.**
Проверь: `curl https://ВАШ_ДОМЕН/ha-app/api/health`.
Если ошибка — проверь nginx конфиг и убедись что ha-bot запущен.

**Push уведомления не приходят.**
Открой Mini App в браузере (не в Telegram), нажми "Разрешить уведомления".
Web Push работает только через HTTPS и только после явного разрешения.

**Ошибка `BOT_TOKEN` при запуске.**
Убедись что `/opt/ha-bot/.env` существует и содержит `BOT_TOKEN=...`.

**Бот запускается, но не отвечает на команды.**
Проверь `ADMIN_ID` — это должен быть именно числовой ID (не username).
Первая команда `/start` регистрирует тебя как admin.

**Как добавить других пользователей?**
В боте: `/invite` — создать ссылку-приглашение. Или `/users` для управления.

**Где хранятся данные (устройства, сцены, алерты)?**
В SQLite базе `/opt/ha-bot/ha_bot.db`. Автоматически бэкапится в Telegram каждую ночь.

**Как кастомизировать устройства в Mini App?**
В боте: `/devices` — изменить иконку, название, раздел. Или через Mini App в настройках.

---

## Лицензия

MIT — используй, модифицируй, делись.
