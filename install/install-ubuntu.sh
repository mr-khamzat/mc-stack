#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# HA Home Bot — Установка на Ubuntu (VPS / голый сервер / VM)
# ═══════════════════════════════════════════════════════════════════════════════
# Запускать: на Ubuntu 22.04 или 24.04 от root
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/install-ubuntu.sh)
#
# Что делает:
#   1. Устанавливает Python 3.11+, git, curl и всё нужное
#   2. Запускает setup.sh — бот + Mini App + systemd сервис
#   3. Устанавливает nginx как реверс-прокси (порт 80 → бот:8766)
#      → Mini App доступен в локальной сети по http://IP/ha-app/
#   4. (Опционально) настраивает Cloudflare Tunnel для HTTPS из интернета
#
# После установки:
#   • Локальная сеть:  http://<IP>/ha-app/          (HTTP, для разработки)
#   • Из интернета:    https://<домен>/ha-app/       (HTTPS через Cloudflare)
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()   { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()     { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
ask()    { echo -e "${YELLOW}[?]${NC}     $*"; }
header() { echo -e "\n${BOLD}${BLUE}══════════════════════════════════════════${NC}"; echo -e "${BOLD}  $*${NC}"; echo -e "${BOLD}${BLUE}══════════════════════════════════════════${NC}\n"; }

# ── Проверки ──────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || error "Запусти от root: sudo bash install-ubuntu.sh"

# Проверяем Ubuntu
if ! grep -qi ubuntu /etc/os-release 2>/dev/null; then
    warn "Дистрибутив не определён как Ubuntu. Продолжаем..."
fi

UBUNTU_VER=$(grep -oP 'VERSION_ID="\K[^"]+' /etc/os-release 2>/dev/null || echo "unknown")
info "Система: Ubuntu $UBUNTU_VER"

BOT_PORT=8766
INSTALL_DIR="/opt/ha-bot"

header "🏠 HA Home Bot — Установка на Ubuntu"

echo -e "${BOLD}Что будет установлено:${NC}"
echo -e "  • Python 3.11+, git, nginx"
echo -e "  • HA Home Bot + Mini App в /opt/ha-bot"
echo -e "  • Systemd сервис ha-bot (автозапуск)"
echo -e "  • nginx: http://$(hostname -I | awk '{print $1}')/ha-app/ → бот:$BOT_PORT"
echo ""

# ── Шаг 1: curl + базовые зависимости ────────────────────────────────────────
header "📦 Шаг 1/3 — Системные пакеты"

info "Обновляем apt..."
apt-get update -qq

info "Устанавливаем curl, nginx и базовые пакеты..."
apt-get install -y -qq curl nginx

ok "Базовые пакеты готовы"

# ── Шаг 2: Основная установка бота ───────────────────────────────────────────
header "🤖 Шаг 2/3 — Установка бота"

SETUP_URL="https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/setup.sh"
info "Запускаем setup.sh..."
bash <(curl -fsSL "$SETUP_URL")

# ── Шаг 3: Настройка nginx ────────────────────────────────────────────────────
header "🌐 Шаг 3/3 — nginx реверс-прокси"

SERVER_IP=$(hostname -I | awk '{print $1}')

# Конфиг nginx
cat > /etc/nginx/sites-available/ha-bot << EOF
# HA Home Bot — nginx реверс-прокси
# Доступ: http://${SERVER_IP}/ha-app/
server {
    listen 80;
    server_name _;

    # Логи
    access_log /var/log/nginx/ha-bot.access.log;
    error_log  /var/log/nginx/ha-bot.error.log;

    # Mini App и API бота
    location /ha-app/ {
        proxy_pass         http://127.0.0.1:${BOT_PORT}/ha-app/;
        proxy_http_version 1.1;

        # WebSocket / SSE поддержка
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;

        # Без буферизации (нужно для SSE)
        proxy_buffering    off;
        proxy_cache        off;

        # Таймауты для долгих SSE соединений
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Редирект с корня
    location = / {
        return 302 /ha-app/;
    }
}
EOF

# Включаем сайт
ln -sf /etc/nginx/sites-available/ha-bot /etc/nginx/sites-enabled/ha-bot

# Отключаем default если есть (занимает порт 80)
rm -f /etc/nginx/sites-enabled/default

# Проверяем конфиг
nginx -t && ok "nginx конфиг валиден"

# Запускаем / перезапускаем nginx
systemctl enable nginx
systemctl restart nginx

if systemctl is-active --quiet nginx; then
    ok "nginx запущен!"
else
    warn "nginx не запустился. Логи:"
    journalctl -u nginx -n 20 --no-pager
fi

# ── Итог ──────────────────────────────────────────────────────────────────────
header "✅ Установка завершена"

SERVER_IP=$(hostname -I | awk '{print $1}')

echo -e "${BOLD}Mini App доступен:${NC}"
echo ""
echo -e "  ${CYAN}http://${SERVER_IP}/ha-app/${NC}   ← локальная сеть (HTTP)"
echo ""
echo -e "${YELLOW}⚠️  Для Telegram Mini App нужен HTTPS!${NC}"
echo -e "  Настрой Cloudflare Tunnel для доступа из интернета:"
echo -e "  ${YELLOW}bash <(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/setup-cloudflare.sh)${NC}"
echo ""
echo -e "${BOLD}Проверка:${NC}"
echo -e "  ${YELLOW}curl http://localhost/ha-app/api/health${NC}"
echo ""
echo -e "${BOLD}Управление:${NC}"
echo -e "  ${CYAN}systemctl status ha-bot${NC}      — статус бота"
echo -e "  ${CYAN}journalctl -u ha-bot -f${NC}      — логи бота"
echo -e "  ${CYAN}systemctl status nginx${NC}        — статус nginx"
echo -e "  ${CYAN}nano ${INSTALL_DIR}/.env${NC}          — конфиг бота"
echo ""
echo -e "Документация: ${CYAN}https://github.com/mr-khamzat/mc-stack${NC}"
