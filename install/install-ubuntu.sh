#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# HA Home Bot — Установка на Ubuntu 22.04 / 24.04 (VPS / VM / голый сервер)
# ═══════════════════════════════════════════════════════════════════════════════
# Запускать: от root на Ubuntu
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/install-ubuntu.sh)
#
# Что делает:
#   1. Устанавливает Python 3.11+, git, nginx и все зависимости
#   2. Клонирует репозиторий, копирует файлы в /opt/ha-bot
#   3. Создаёт Python venv и устанавливает пакеты
#   4. Генерирует VAPID ключи для Web Push
#   5. Настраивает nginx (порт 80 → бот:8766)
#   6. Создаёт systemd сервисы ha-bot и ha-bot-setup
#   7. Запускает мастер настройки → открой http://<IP>/ в браузере
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()   { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()     { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
header() { echo -e "\n${BOLD}${BLUE}══════════════════════════════════════════${NC}"; echo -e "${BOLD}  $*${NC}"; echo -e "${BOLD}${BLUE}══════════════════════════════════════════${NC}\n"; }

[[ $EUID -eq 0 ]] || error "Запусти от root: sudo bash install-ubuntu.sh"

REPO_URL="https://github.com/mr-khamzat/mc-stack.git"
INSTALL_DIR="/opt/ha-bot"
REPO_TMP="/tmp/mc-stack-install"
BOT_PORT=8766

header "🏠 HA Home Bot — Установка на Ubuntu"

SERVER_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "x.x.x.x")

echo -e "${BOLD}Сервер:${NC} $SERVER_IP"
echo -e "${BOLD}После установки открой в браузере:${NC}"
echo -e "  ${CYAN}http://${SERVER_IP}/${NC}"
echo -e "  (страница настройки — введи токены там)"
echo ""

# ── Шаг 1: Системные пакеты ───────────────────────────────────────────────────
header "📦 Шаг 1/5 — Системные пакеты"

info "Обновляем apt..."
apt-get update -qq

info "Устанавливаем зависимости..."
apt-get install -y -qq \
    python3 python3-pip python3-venv python3-dev \
    git curl wget ca-certificates nginx openssh-server \
    build-essential libffi-dev libssl-dev pkg-config

# ── SSH: включаем root-логин ───────────────────────────────────────────────────
info "Настраиваем SSH..."
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/'       /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl enable ssh
systemctl restart ssh
ok "SSH включён (root-доступ разрешён)"

# Проверяем версию Python (нужен 3.11+)
PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
info "Python: $PY_VER"

if [[ $PY_MAJOR -lt 3 || ($PY_MAJOR -eq 3 && $PY_MINOR -lt 11) ]]; then
    warn "Python $PY_VER слишком старый. Устанавливаем 3.11..."
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv python3.11-dev
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
    ok "Python 3.11 установлен"
fi

ok "Системные пакеты готовы"

# ── Шаг 2: Файлы бота ─────────────────────────────────────────────────────────
header "📥 Шаг 2/5 — Загрузка файлов"

rm -rf "$REPO_TMP"
info "Клонируем репозиторий..."
git clone --depth=1 "$REPO_URL" "$REPO_TMP"

info "Копируем файлы в $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -r "$REPO_TMP/bot/." "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/webapp" "$INSTALL_DIR/photos" "$INSTALL_DIR/voices" \
         "$INSTALL_DIR/backups" "$INSTALL_DIR/avatars/ha"

rm -rf "$REPO_TMP"
ok "Файлы скопированы в $INSTALL_DIR"

# ── Шаг 3: Python окружение ───────────────────────────────────────────────────
header "🐍 Шаг 3/5 — Python окружение"

info "Создаём виртуальное окружение..."
python3 -m venv "$INSTALL_DIR/venv"

info "Устанавливаем пакеты (1-2 минуты)..."
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet \
    aiogram aiohttp python-dotenv psutil \
    matplotlib pywebpush websockets cryptography

ok "Python пакеты установлены"

# ── VAPID ключи ───────────────────────────────────────────────────────────────
info "Генерируем VAPID ключи (Web Push)..."
"$INSTALL_DIR/venv/bin/python3" - << 'PYEOF'
import sys
sys.path.insert(0, '/opt/ha-bot/venv/lib/python{}.{}/site-packages'.format(*sys.version_info[:2]))
try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    import base64
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key  = private_key.public_key()
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()
    )
    with open('/opt/ha-bot/vapid_private.pem', 'wb') as f: f.write(pem)
    pub_bytes = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint
    )
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()
    with open('/opt/ha-bot/vapid_public.txt', 'w') as f: f.write(pub_b64)
    print("  VAPID ключи созданы OK")
except Exception as e:
    print(f"  Предупреждение: {e} (будут созданы при первом запуске)")
PYEOF

ok "VAPID ключи готовы"

# ── Шаг 4: nginx ──────────────────────────────────────────────────────────────
header "🌐 Шаг 4/5 — nginx реверс-прокси"

WIZARD_PORT=8080

cat > /etc/nginx/sites-available/ha-bot << NGINX
# HA Home Bot — nginx конфиг
# /ha-app/ → ha-bot (порт $BOT_PORT)
# /        → мастер настройки (порт $WIZARD_PORT)
server {
    listen 80 default_server;
    server_name _;

    access_log /var/log/nginx/ha-bot.access.log;
    error_log  /var/log/nginx/ha-bot.error.log;

    # Mini App и API бота — всегда на порту $BOT_PORT
    location /ha-app/ {
        proxy_pass         http://127.0.0.1:${BOT_PORT}/ha-app/;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Мастер настройки — порт $WIZARD_PORT (запускается до ha-bot)
    location / {
        proxy_pass         http://127.0.0.1:${WIZARD_PORT};
        proxy_http_version 1.1;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/ha-bot /etc/nginx/sites-enabled/ha-bot
rm -f /etc/nginx/sites-enabled/default

nginx -t && ok "nginx конфиг валиден"
systemctl enable nginx
systemctl restart nginx
ok "nginx запущен"

# ── Шаг 5: Systemd сервисы ────────────────────────────────────────────────────
header "🔧 Шаг 5/5 — Systemd сервисы"

# Сервис мастера настройки (порт 8080, не конфликтует с ботом на 8766)
cat > /etc/systemd/system/ha-bot-setup.service << EOF
[Unit]
Description=HA Home Bot — Мастер настройки (веб-интерфейс)
After=network-online.target nginx.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/setup_wizard.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Основной сервис бота (запускается после настройки через мастер)
cat > /etc/systemd/system/ha-bot.service << EOF
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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# Включаем ha-bot (но не запускаем — запустится после настройки)
systemctl enable ha-bot

# Запускаем мастер настройки
if [[ -f "$INSTALL_DIR/.env" ]] && grep -q "^BOT_TOKEN=[0-9]" "$INSTALL_DIR/.env" 2>/dev/null; then
    # .env уже заполнен — сразу запускаем бота
    info ".env уже существует — запускаем ha-bot напрямую..."
    systemctl start ha-bot
    ok "ha-bot запущен"
else
    # .env пустой / нет — запускаем мастер настройки
    systemctl enable ha-bot-setup
    systemctl start ha-bot-setup
    ok "Мастер настройки запущен"
fi

# ── Итог ──────────────────────────────────────────────────────────────────────
SERVER_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "x.x.x.x")

echo ""
echo -e "${BOLD}${BLUE}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${BLUE}║          ✅  Установка завершена успешно!            ║${NC}"
echo -e "${BOLD}${BLUE}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BOLD}┌─ Доступ по SSH ───────────────────────────────────────┐${NC}"
echo -e "  Логин:    ${CYAN}root${NC}"
echo -e "  Адрес:    ${CYAN}${SERVER_IP}${NC}   (порт 22)"
echo -e "  Команда:  ${GREEN}ssh root@${SERVER_IP}${NC}"
echo -e "${BOLD}└───────────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "${BOLD}┌─ Настройка бота (шаг 1) ──────────────────────────────┐${NC}"
echo -e "  Открой в браузере:"
echo -e "  ${CYAN}http://${SERVER_IP}/${NC}"
echo -e "  Введи токены → бот запустится автоматически"
echo -e "${BOLD}└───────────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "${BOLD}┌─ Mini App после настройки ────────────────────────────┐${NC}"
echo -e "  Локально:  ${CYAN}http://${SERVER_IP}/ha-app/${NC}"
echo -e "  Telegram:  нужен HTTPS → настрой Cloudflare Tunnel (шаг 2)"
echo -e "${BOLD}└───────────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "${BOLD}┌─ Cloudflare Tunnel (шаг 2, для Telegram) ─────────────┐${NC}"
echo -e "  ${YELLOW}bash <(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/setup-cloudflare.sh)${NC}"
echo -e "${BOLD}└───────────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "${BOLD}Управление:${NC}"
echo -e "  ${CYAN}systemctl status ha-bot${NC}    — статус бота"
echo -e "  ${CYAN}journalctl -u ha-bot -f${NC}    — логи"
echo -e "  ${CYAN}nano ${INSTALL_DIR}/.env${NC}        — конфиг"
