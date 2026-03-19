#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# HA Home Bot — Настройка Cloudflare Tunnel
# ═══════════════════════════════════════════════════════════════════════════════
# Запускать: внутри LXC / VPS после setup.sh
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/setup-cloudflare.sh)
#
# Что делает:
#   1. Устанавливает cloudflared
#   2. Авторизует туннель в Cloudflare (откроет ссылку в браузере)
#   3. Создаёт туннель и DNS запись
#   4. Записывает WEBAPP_URL в /opt/ha-bot/.env
#   5. Запускает cloudflared как systemd сервис
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

[[ $EUID -eq 0 ]] || error "Запусти от root"

INSTALL_DIR="/opt/ha-bot"
CF_CONFIG_DIR="/root/.cloudflared"
TUNNEL_NAME="ha-bot"
BOT_PORT=8766

header "☁️  Cloudflare Tunnel — Настройка"

echo -e "${BOLD}Что нужно:${NC}"
echo -e "  • Аккаунт на ${CYAN}cloudflare.com${NC} (бесплатный)"
echo -e "  • Домен добавленный в Cloudflare"
echo -e "    (даже бесплатный DuckDNS — duckdns.org → добавь в Cloudflare)"
echo ""

# ── Установка cloudflared ─────────────────────────────────────────────────────
header "📦 Установка cloudflared"

ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  CF_ARCH="amd64" ;;
    aarch64) CF_ARCH="arm64" ;;
    armv7*)  CF_ARCH="arm"   ;;
    *)       error "Неизвестная архитектура: $ARCH" ;;
esac

CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}"

if command -v cloudflared &>/dev/null; then
    ok "cloudflared уже установлен: $(cloudflared --version 2>&1 | head -1)"
else
    info "Скачиваем cloudflared ($CF_ARCH)..."
    curl -fsSL -o /usr/local/bin/cloudflared "$CF_URL"
    chmod +x /usr/local/bin/cloudflared
    ok "cloudflared установлен: $(cloudflared --version 2>&1 | head -1)"
fi

# ── Авторизация ───────────────────────────────────────────────────────────────
header "🔐 Авторизация в Cloudflare"

if [[ -f "$CF_CONFIG_DIR/cert.pem" ]]; then
    ok "Уже авторизован (cert.pem существует)"
else
    echo -e "${BOLD}Сейчас откроется ссылка для авторизации.${NC}"
    echo -e "Скопируй её и открой в браузере → войди в Cloudflare → выбери домен."
    echo ""
    cloudflared tunnel login
    ok "Авторизация выполнена"
fi

# ── Создание туннеля ──────────────────────────────────────────────────────────
header "🔧 Создание туннеля"

# Проверяем есть ли уже туннель с таким именем
if cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
    warn "Туннель '$TUNNEL_NAME' уже существует"
    TUNNEL_UUID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}')
    ok "Используем существующий туннель: $TUNNEL_UUID"
else
    info "Создаём туннель '$TUNNEL_NAME'..."
    CREATE_OUT=$(cloudflared tunnel create "$TUNNEL_NAME" 2>&1)
    echo "$CREATE_OUT"
    TUNNEL_UUID=$(echo "$CREATE_OUT" | grep -oP '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)
    ok "Туннель создан: $TUNNEL_UUID"
fi

# Найти credentials файл
CREDS_FILE=$(find "$CF_CONFIG_DIR" -name "${TUNNEL_UUID}.json" 2>/dev/null | head -1)
[[ -z "$CREDS_FILE" ]] && CREDS_FILE="$CF_CONFIG_DIR/${TUNNEL_UUID}.json"

# ── Ввод домена ───────────────────────────────────────────────────────────────
ask "Твой домен для Mini App (например: app.yourdomain.com):"; read -r CF_HOSTNAME
CF_HOSTNAME="${CF_HOSTNAME,,}"   # нижний регистр
[[ -z "$CF_HOSTNAME" ]] && error "Домен не может быть пустым"

# ── Конфиг туннеля ────────────────────────────────────────────────────────────
mkdir -p "$CF_CONFIG_DIR"
cat > "$CF_CONFIG_DIR/config.yml" << EOF
# Cloudflare Tunnel конфиг для ha-bot
# Туннель: $TUNNEL_NAME ($TUNNEL_UUID)
tunnel: $TUNNEL_NAME
credentials-file: $CREDS_FILE

ingress:
  # Mini App и API бота
  - hostname: $CF_HOSTNAME
    service: http://localhost:$BOT_PORT
    originRequest:
      noTLSVerify: true
  # Все остальные запросы — 404
  - service: http_status:404
EOF

ok "Конфиг туннеля записан: $CF_CONFIG_DIR/config.yml"

# ── DNS запись ────────────────────────────────────────────────────────────────
info "Создаём DNS запись (CNAME) → $CF_HOSTNAME..."
cloudflared tunnel route dns "$TUNNEL_NAME" "$CF_HOSTNAME" \
    || warn "Не удалось создать DNS запись автоматически. Добавь вручную в Cloudflare Dashboard:\n  Тип: CNAME, Имя: $CF_HOSTNAME, Значение: ${TUNNEL_UUID}.cfargotunnel.com"

# ── Systemd сервис ────────────────────────────────────────────────────────────
header "🔧 Systemd сервис для cloudflared"

cloudflared service install \
    && ok "Сервис cloudflared установлен" \
    || warn "cloudflared service install упал, создаём вручную..."

# На всякий случай убеждаемся что сервис правильный
if ! systemctl is-active --quiet cloudflared 2>/dev/null; then
    # Создаём unit файл вручную (бывает нужно в Ubuntu 24.04 LXC)
    cat > /etc/systemd/system/cloudflared.service << EOF
[Unit]
Description=Cloudflare Tunnel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/cloudflared tunnel --config ${CF_CONFIG_DIR}/config.yml run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
fi

systemctl enable cloudflared
systemctl restart cloudflared
sleep 3

if systemctl is-active --quiet cloudflared; then
    ok "cloudflared работает!"
else
    warn "cloudflared не запустился. Логи:"
    journalctl -u cloudflared -n 20 --no-pager
fi

# ── Обновление .env бота ──────────────────────────────────────────────────────
header "📝 Обновление .env бота"

ENV_FILE="$INSTALL_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    WEBAPP_URL="https://${CF_HOSTNAME}/ha-app/"
    # Заменить или добавить WEBAPP_URL в .env
    if grep -q "^WEBAPP_URL=" "$ENV_FILE"; then
        sed -i "s|^WEBAPP_URL=.*|WEBAPP_URL=${WEBAPP_URL}|" "$ENV_FILE"
    else
        echo "WEBAPP_URL=${WEBAPP_URL}" >> "$ENV_FILE"
    fi
    ok ".env обновлён: WEBAPP_URL=${WEBAPP_URL}"

    # Перезапустить бота
    if systemctl is-active --quiet ha-bot; then
        info "Перезапускаем ha-bot..."
        systemctl restart ha-bot
        ok "Бот перезапущен"
    fi
else
    warn ".env не найден в $INSTALL_DIR. Добавь вручную:"
    warn "WEBAPP_URL=https://${CF_HOSTNAME}/ha-app/"
fi

# ── Итог ──────────────────────────────────────────────────────────────────────
header "✅ Cloudflare Tunnel настроен"

echo -e "${BOLD}Mini App доступен по адресу:${NC}"
echo -e "  ${CYAN}https://${CF_HOSTNAME}/ha-app/${NC}"
echo ""
echo -e "${BOLD}Проверка:${NC}"
echo -e "  ${YELLOW}curl https://${CF_HOSTNAME}/ha-app/api/health${NC}"
echo -e "  Должен вернуть: {\"status\": \"ok\", ...}"
echo ""
echo -e "${BOLD}В @BotFather — установить кнопку меню:${NC}"
echo -e "  /mybots → [твой бот] → Bot Settings → Menu Button → Edit Menu Button URL"
echo -e "  URL: ${CYAN}https://${CF_HOSTNAME}/ha-app/${NC}"
echo ""
echo -e "${BOLD}Команды управления туннелем:${NC}"
echo -e "  ${YELLOW}systemctl status cloudflared${NC}    — статус"
echo -e "  ${YELLOW}journalctl -u cloudflared -f${NC}    — логи"
echo -e "  ${YELLOW}cloudflared tunnel list${NC}          — список туннелей"
