#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# HA Home Bot — Установка внутри Ubuntu 22.04 / 24.04 (LXC или VPS)
# ═══════════════════════════════════════════════════════════════════════════════
# Запускать: внутри LXC контейнера или на VPS
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/setup.sh)
#
# Что делает:
#   1. Устанавливает Python 3.11+ и зависимости
#   2. Клонирует репозиторий, копирует файлы в /opt/ha-bot
#   3. Создаёт Python venv и устанавливает pip-пакеты
#   4. Спрашивает ключевые настройки и создаёт .env
#   5. Генерирует VAPID ключи для Web Push
#   6. Создаёт systemd сервис ha-bot
#   7. (Опционально) настраивает Cloudflare Tunnel
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Цвета ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()   { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()     { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
ask()    { echo -e "${YELLOW}[?]${NC}     $*"; }
header() { echo -e "\n${BOLD}${BLUE}══════════════════════════════════════════${NC}"; echo -e "${BOLD}  $*${NC}"; echo -e "${BOLD}${BLUE}══════════════════════════════════════════${NC}\n"; }

# ── Проверка root ──────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || error "Запусти от root: sudo bash setup.sh"

# ── Константы ─────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/mr-khamzat/mc-stack.git"
INSTALL_DIR="/opt/ha-bot"
REPO_TMP="/tmp/mc-stack-install"
SERVICE_NAME="ha-bot"

header "🏠 HA Home Bot — Установка"

# ── Шаг 1: Системные пакеты ───────────────────────────────────────────────────
header "📦 Шаг 1/6 — Системные пакеты"

info "Обновляем список пакетов..."
apt-get update -qq

info "Устанавливаем зависимости..."
apt-get install -y -qq \
    python3 python3-pip python3-venv python3-dev \
    git curl wget ca-certificates \
    build-essential libffi-dev libssl-dev \
    pkg-config

# Проверяем версию Python
PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
info "Python: $PY_VER"

# Нужен 3.11+
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [[ $PY_MAJOR -lt 3 || ($PY_MAJOR -eq 3 && $PY_MINOR -lt 11) ]]; then
    warn "Python $PY_VER — слишком старый. Устанавливаем 3.11..."
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv python3.11-dev
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
    ok "Python 3.11 установлен"
fi

ok "Системные пакеты готовы"

# ── Шаг 2: Клонирование репозитория ──────────────────────────────────────────
header "📥 Шаг 2/6 — Загрузка файлов"

rm -rf "$REPO_TMP"
info "Клонируем репозиторий..."
git clone --depth=1 "$REPO_URL" "$REPO_TMP"

info "Копируем файлы в $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -r "$REPO_TMP/bot/." "$INSTALL_DIR/"

# Создаём вспомогательные папки
mkdir -p "$INSTALL_DIR/webapp"
mkdir -p "$INSTALL_DIR/photos"
mkdir -p "$INSTALL_DIR/voices"
mkdir -p "$INSTALL_DIR/backups"
mkdir -p "$INSTALL_DIR/avatars/ha"

rm -rf "$REPO_TMP"
ok "Файлы скопированы в $INSTALL_DIR"

# ── Шаг 3: Python окружение и зависимости ────────────────────────────────────
header "🐍 Шаг 3/6 — Python окружение"

info "Создаём виртуальное окружение..."
python3 -m venv "$INSTALL_DIR/venv"

info "Устанавливаем Python пакеты (может занять 1-2 минуты)..."
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet \
    aiogram \
    aiohttp \
    python-dotenv \
    psutil \
    matplotlib \
    pywebpush \
    websockets \
    cryptography

ok "Python пакеты установлены"

# ── Шаг 4: Генерация VAPID ключей (Web Push) ─────────────────────────────────
header "🔑 Шаг 4/6 — VAPID ключи (Web Push)"

info "Генерируем ключи..."
"$INSTALL_DIR/venv/bin/python3" - << 'PYEOF'
import os, sys
sys.path.insert(0, '/opt/ha-bot/venv/lib/python{}.{}/site-packages'.format(*sys.version_info[:2]))
try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    import base64, json

    # Генерируем VAPID ключи
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key  = private_key.public_key()

    # Приватный ключ в PEM
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()
    )
    with open('/opt/ha-bot/vapid_private.pem', 'wb') as f:
        f.write(pem)

    # Публичный ключ в Base64url (для VAPID)
    pub_bytes = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint
    )
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()
    with open('/opt/ha-bot/vapid_public.txt', 'w') as f:
        f.write(pub_b64)
    print(f"  Публичный VAPID ключ: {pub_b64[:32]}...")
    print("  OK")
except Exception as e:
    print(f"  Предупреждение: {e}")
    print("  VAPID ключи будут созданы при первом запуске бота")
PYEOF

ok "VAPID ключи готовы"

# ── Шаг 5: Создание .env файла ────────────────────────────────────────────────
header "⚙️  Шаг 5/6 — Конфигурация (.env)"

echo ""
echo -e "${BOLD}Введи настройки бота. Нужны:${NC}"
echo -e "  • Telegram Bot Token  — получить у ${CYAN}@BotFather${NC} → /newbot"
echo -e "  • Твой Telegram ID    — узнать у ${CYAN}@userinfobot${NC}"
echo -e "  • URL Home Assistant  — например https://homeassistant.local:8123"
echo -e "  • HA Long-Lived Token — HA → Профиль → Security → Long-Lived Access Tokens"
echo ""

# BOT_TOKEN
while true; do
    ask "Telegram Bot Token (формат 123456789:AAF...):"; read -r BOT_TOKEN
    [[ "$BOT_TOKEN" =~ ^[0-9]+: ]] && break
    warn "Неверный формат. Должен начинаться с цифр и двоеточия."
done

# ADMIN_ID
while true; do
    ask "Твой Telegram ID (только цифры, узнать у @userinfobot):"; read -r ADMIN_ID
    [[ "$ADMIN_ID" =~ ^[0-9]+$ ]] && break
    warn "ID должен состоять только из цифр."
done

# HA_URL
ask "URL Home Assistant (например http://192.168.1.28:8123 или https://ha.yourdomain.com):"; read -r HA_URL
HA_URL="${HA_URL%/}"   # убрать слеш в конце

# HA_TOKEN
ask "HA Long-Lived Access Token:"; read -r HA_TOKEN

# WEBAPP_TOKEN — генерируем автоматически
WEBAPP_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")
info "WEBAPP_TOKEN сгенерирован автоматически: ${WEBAPP_TOKEN:0:8}..."

# WEBAPP_URL
echo ""
echo -e "${BOLD}URL для Mini App (нужен HTTPS):${NC}"
echo -e "  Если используешь Cloudflare Tunnel — введи позже."
echo -e "  Пример: https://app.yourdomain.com/ha-app/"
echo -e "  (Оставь пустым — бот запустится, но Mini App не откроется)"
ask "WEBAPP_URL [пропустить]:"; read -r WEBAPP_URL
WEBAPP_URL="${WEBAPP_URL:-}"

# HA_WEBAPP_ADMINS — логин HA для admin прав в Mini App
ask "Логин в Home Assistant для admin-прав в Mini App (обычно 'homeassistant' или твоё имя):"; read -r HA_WEBAPP_ADMINS

# Запись .env
cat > "$INSTALL_DIR/.env" << EOF
# ── Обязательные параметры ────────────────────────────────────────────────────
BOT_TOKEN=${BOT_TOKEN}
ADMIN_ID=${ADMIN_ID}
HA_URL=${HA_URL}
HA_TOKEN=${HA_TOKEN}

# ── Mini App ──────────────────────────────────────────────────────────────────
# Публичный URL где доступен Mini App (обязательно /ha-app/ в конце)
WEBAPP_URL=${WEBAPP_URL}/ha-app/
WEBAPP_TOKEN=${WEBAPP_TOKEN}
WEBAPP_DIR=${INSTALL_DIR}/webapp

# HA-логины с правами admin в Mini App (через запятую)
HA_WEBAPP_ADMINS=${HA_WEBAPP_ADMINS}

# ── Опциональные параметры ────────────────────────────────────────────────────
# Домены для проверки SSL (через запятую, если не задано — из WEBAPP_URL)
# SSL_CHECK_DOMAINS=yourdomain.com

# Frigate NVR (если используется)
# FRIGATE_URL=http://192.168.1.100:5000

# WebRTC TURN сервер (для звонков через разные сети)
# SERVER_IP=1.2.3.4
# TURN_SECRET=change_me_turn_secret

# Claude AI для команды /ai
# ANTHROPIC_API_KEY=sk-ant-...
EOF

ok ".env создан: $INSTALL_DIR/.env"

# ── Шаг 6: Systemd сервис ─────────────────────────────────────────────────────
header "🔧 Шаг 6/6 — Systemd сервис"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=HA Home Bot + Mini App
Documentation=https://github.com/mr-khamzat/mc-stack
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/ha_bot.py
Restart=always
RestartSec=10
# Логи: journalctl -u ha-bot -f
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
ok "Systemd сервис создан и включён"

# ── Проверка запуска ──────────────────────────────────────────────────────────
header "🚀 Первый запуск"

if [[ -n "$BOT_TOKEN" && -n "$HA_URL" ]]; then
    info "Запускаем бота..."
    systemctl start "$SERVICE_NAME" || warn "Не удалось запустить. Проверь: journalctl -u ha-bot -n 30"
    sleep 3
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Бот запущен!"
    else
        warn "Бот не запустился. Смотри логи:"
        journalctl -u "$SERVICE_NAME" -n 20 --no-pager
    fi
fi

# ── Опционально: Cloudflare Tunnel ───────────────────────────────────────────
echo ""
echo -e "${BOLD}Настроить Cloudflare Tunnel? (для Mini App без белого IP)${NC}"
ask "Установить cloudflared? [y/N]:"; read -r _cf
if [[ "${_cf,,}" == "y" ]]; then
    bash <(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/setup-cloudflare.sh) \
        || warn "Cloudflare Tunnel не настроен. Запусти install/setup-cloudflare.sh позже."
fi

# ── Итог ──────────────────────────────────────────────────────────────────────
header "✅ Установка завершена"

echo -e "${BOLD}Что дальше:${NC}"
echo ""
echo -e "1. Открой Telegram и найди своего бота → отправь /start"
echo ""
echo -e "2. Если не настроил WEBAPP_URL — настрой Cloudflare Tunnel:"
echo -e "   ${YELLOW}bash <(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/setup-cloudflare.sh)${NC}"
echo -e "   Потом обнови WEBAPP_URL в .env и перезапусти:"
echo -e "   ${YELLOW}nano ${INSTALL_DIR}/.env && systemctl restart ${SERVICE_NAME}${NC}"
echo ""
echo -e "3. Полезные команды:"
echo -e "   ${CYAN}systemctl status ${SERVICE_NAME}${NC}   — статус"
echo -e "   ${CYAN}journalctl -u ${SERVICE_NAME} -f${NC}   — логи в реальном времени"
echo -e "   ${CYAN}systemctl restart ${SERVICE_NAME}${NC}  — перезапуск"
echo ""
echo -e "4. Конфиг: ${CYAN}${INSTALL_DIR}/.env${NC}"
echo ""
echo -e "Документация: ${CYAN}https://github.com/mr-khamzat/mc-stack${NC}"
