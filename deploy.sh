#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  MeshCentral Stack — Deploy Kit
#  Разворачивает: MeshCentral Bot + RackViz + NetMap на чистом Ubuntu 22/24
#  Использование: bash deploy.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ─── Проверка root ──────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Запусти скрипт от root: sudo bash deploy.sh"
[[ "$(uname -s)" == "Linux" ]] || die "Только Linux"

echo
echo "═══════════════════════════════════════════════════"
echo "   MeshCentral Stack — Setup"
echo "═══════════════════════════════════════════════════"
echo

# ─── Ввод конфигурации ──────────────────────────────────────────────────────
read -rp "Telegram Bot Token (от @BotFather): " BOT_TOKEN
[[ -n "$BOT_TOKEN" ]] || die "Токен не введён"

read -rp "Telegram Admin Chat ID (твой user ID): " ADMIN_CHAT_ID
[[ -n "$ADMIN_CHAT_ID" ]] || die "Chat ID не введён"

read -rp "MeshCentral URL (напр. https://hub.office.mooo.com): " MC_URL
MC_URL="${MC_URL%/}"
[[ -n "$MC_URL" ]] || die "MC URL не введён"

read -rp "MeshCentral WSS (напр. wss://hub.office.mooo.com:443): " MC_WSS
[[ -n "$MC_WSS" ]] || die "MC WSS не введён"

read -rp "MeshCentral Логин (admin): " MC_LOGIN
MC_LOGIN="${MC_LOGIN:-admin}"

read -rsp "MeshCentral Пароль: " MC_PASS
echo
[[ -n "$MC_PASS" ]] || die "Пароль не введён"

read -rsp "MeshCentral Login Token Key (из --logintokenkey): " MC_TOKEN_KEY
echo

read -rsp "RackViz Admin пароль (придумай): " RACK_PASS
echo
[[ -n "$RACK_PASS" ]] || die "Пароль RackViz не введён"

read -rp "IP или домен этого сервера (для nginx): " SERVER_HOST
[[ -n "$SERVER_HOST" ]] || die "Хост не введён"

read -rp "Порт для HTTP доступа к RackViz [8080]: " RACK_HTTP_PORT
RACK_HTTP_PORT="${RACK_HTTP_PORT:-8080}"

echo
info "Конфигурация принята. Начинаю установку..."
echo

# ─── 1. Зависимости ─────────────────────────────────────────────────────────
info "Устанавливаю системные зависимости..."
apt-get update -qq
apt-get install -y -qq \
    curl wget git nginx python3 python3-pip python3-venv \
    nodejs npm ca-certificates gnupg lsb-release

# Docker
if ! command -v docker &>/dev/null; then
    info "Устанавливаю Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
fi
ok "Docker готов"

# meshctrl — нужен для связи с MeshCentral
if ! command -v meshctrl &>/dev/null; then
    info "Устанавливаю meshctrl..."
    npm install -g meshcentral 2>/dev/null || true
    # Создаём wrapper если meshctrl не в PATH
    MC_MESHCTRL="$(npm root -g)/meshcentral/meshctrl"
    if [[ -f "$MC_MESHCTRL" ]]; then
        ln -sf "$MC_MESHCTRL" /usr/local/bin/meshctrl
    fi
fi
ok "meshctrl готов"

# ─── 2. Директории ──────────────────────────────────────────────────────────
info "Создаю директории..."
DEPLOY_DIR="$(dirname "$(realpath "$0")")"
BOT_DIR="/opt/meshcentral-bot"
RACK_DIR="/opt/rackviz"
mkdir -p "$BOT_DIR/public" "$RACK_DIR/data"

# ─── 3. MeshCentral Bot ──────────────────────────────────────────────────────
info "Настраиваю MeshCentral Bot..."

# Копируем файлы бота
cp -r "$DEPLOY_DIR/bot/"* "$BOT_DIR/"

# .env
cat > "$BOT_DIR/.env" <<EOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_CHAT_IDS=${ADMIN_CHAT_ID}
MC_URL=${MC_URL}
MC_WSS=${MC_WSS}
MC_DATA=/opt/meshcentral-bot/mc-data
MC_DIR=/opt/meshcentral-bot/mc-modules
MC_LOGIN=${MC_LOGIN}
MC_PASS=${MC_PASS}
MC_TOKEN_KEY=${MC_TOKEN_KEY}
EOF

# Python venv
python3 -m venv "$BOT_DIR/venv"
"$BOT_DIR/venv/bin/pip" install -q --upgrade pip
"$BOT_DIR/venv/bin/pip" install -q \
    aiogram==3.25.0 aiohttp requests APScheduler pytz

# Инициализируем пустые JSON-файлы если их нет
for f in keenetic_probes alerts_cfg mute scripts; do
    [[ -f "$BOT_DIR/${f}.json" ]] || echo '[]' > "$BOT_DIR/${f}.json"
done
[[ -f "$BOT_DIR/wifi_clients.json" ]] || echo '{}' > "$BOT_DIR/wifi_clients.json"

# Systemd unit
cat > /etc/systemd/system/meshcentral-bot.service <<EOF
[Unit]
Description=MeshCentral Monitoring Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/meshcentral-bot
ExecStart=/opt/meshcentral-bot/venv/bin/python bot.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mc-bot

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable meshcentral-bot
ok "MeshCentral Bot настроен"

# ─── 4. RackViz ──────────────────────────────────────────────────────────────
info "Настраиваю RackViz..."

cp -r "$DEPLOY_DIR/rackviz/"* "$RACK_DIR/"

cat > "$RACK_DIR/.env" <<EOF
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${RACK_PASS}
MC_TOKEN_KEY=${MC_TOKEN_KEY}
DATABASE_URL=sqlite:////app/data/rack.db
EOF

cd "$RACK_DIR"
docker compose build --no-cache -q
docker compose up -d
ok "RackViz запущен"

# ─── 5. nginx ─────────────────────────────────────────────────────────────────
info "Настраиваю nginx..."

cat > /etc/nginx/sites-available/meshcentral-stack <<EOF
server {
    listen ${RACK_HTTP_PORT};
    server_name ${SERVER_HOST} _;

    # Netmap — через RackViz cookie auth
    location = /netmap {
        auth_request /rack/api/auth/check-cookie;
        error_page 401 = @netmap_login;
        alias /opt/meshcentral-bot/public/netmap.html;
        default_type text/html;
        add_header Cache-Control "no-cache";
    }
    location @netmap_login {
        return 302 http://${SERVER_HOST}:${RACK_HTTP_PORT}/rack/?next=netmap;
    }
    location = /rack/api/auth/check-cookie {
        internal;
        proxy_pass         http://127.0.0.1:8502/api/auth/check-cookie;
        proxy_pass_request_body off;
        proxy_set_header   Content-Length "";
        proxy_set_header   Cookie \$http_cookie;
    }

    # RackViz
    location ^~ /rack {
        proxy_pass         http://127.0.0.1:8503;
        proxy_http_version 1.1;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_read_timeout 60s;
    }

    location / {
        return 200 'MeshCentral Stack is running. Visit /rack for RackViz, /netmap for network map.';
        add_header Content-Type text/plain;
    }
}
EOF

ln -sf /etc/nginx/sites-available/meshcentral-stack /etc/nginx/sites-enabled/meshcentral-stack
nginx -t && systemctl reload nginx
ok "nginx настроен"

# ─── 6. Запуск ───────────────────────────────────────────────────────────────
info "Запускаю сервисы..."
systemctl start meshcentral-bot

echo
echo "═══════════════════════════════════════════════════"
echo -e "${GREEN}✅ Установка завершена!${NC}"
echo "═══════════════════════════════════════════════════"
echo
echo -e "  RackViz:  ${CYAN}http://${SERVER_HOST}:${RACK_HTTP_PORT}/rack/${NC}"
echo -e "  NetMap:   ${CYAN}http://${SERVER_HOST}:${RACK_HTTP_PORT}/netmap${NC}"
echo -e "  Бот:      запущен, проверь /start в Telegram"
echo
echo "  Логи бота:    journalctl -u meshcentral-bot -f"
echo "  Логи RackViz: cd /opt/rackviz && docker compose logs -f"
echo
