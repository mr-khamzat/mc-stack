#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  pack.sh — упаковать deploy-kit для переноса на новый сервер
#  Запускать на основном сервере (где установлен стек)
#  Создаёт: /tmp/mc-stack-deploy.tar.gz
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
CYAN='\033[0;36m'; GREEN='\033[0;32m'; NC='\033[0m'
info() { echo -e "${CYAN}[pack]${NC} $*"; }
ok()   { echo -e "${GREEN}[ok]${NC}   $*"; }

OUT="/tmp/mc-stack-deploy"
rm -rf "$OUT"
mkdir -p "$OUT/bot" "$OUT/rackviz" "$OUT/deploy-kit"

# ── Бот ──────────────────────────────────────────────────────────────────────
info "Копирую файлы бота..."
BOT_SRC="/opt/meshcentral-bot"

# Только нужные файлы (без venv, кешей, секретных данных)
cp "$BOT_SRC/bot.py"              "$OUT/bot/"
cp "$BOT_SRC/keenetic_probe.ps1"  "$OUT/bot/" 2>/dev/null || true
cp "$BOT_SRC/device_probe.ps1"    "$OUT/bot/" 2>/dev/null || true

# Публичные assets (vis-network)
cp "$BOT_SRC/vis-network.min.js"  "$OUT/bot/" 2>/dev/null || true

# Пустые начальные JSON
echo '[]' > "$OUT/bot/keenetic_probes.json"
echo '[]' > "$OUT/bot/alerts_cfg.json"
echo '[]' > "$OUT/bot/mute.json"
echo '{}' > "$OUT/bot/wifi_clients.json"
echo '{}' > "$OUT/bot/uptime.json"

ok "Бот скопирован"

# ── RackViz ──────────────────────────────────────────────────────────────────
info "Копирую исходники RackViz..."
RACK_SRC="/opt/rackviz"

# Backend
cp -r "$RACK_SRC/backend" "$OUT/rackviz/"

# Frontend исходники (не dist — пересоберём на месте)
cp -r "$RACK_SRC/frontend" "$OUT/rackviz/"

# Docker configs
cp "$RACK_SRC/docker-compose.yml" "$OUT/rackviz/"

# Сгенерируем .env шаблон (без реального пароля)
cat > "$OUT/rackviz/.env.template" <<'EOF'
ADMIN_USERNAME=admin
ADMIN_PASSWORD=REPLACE_ME
MC_TOKEN_KEY=REPLACE_ME
DATABASE_URL=sqlite:////app/data/rack.db
EOF

ok "RackViz скопирован"

# ── Deploy kit ────────────────────────────────────────────────────────────────
info "Копирую deploy-kit..."
cp /opt/deploy-kit/deploy.sh  "$OUT/deploy-kit/"
cp /opt/deploy-kit/README.md  "$OUT/deploy-kit/"
chmod +x "$OUT/deploy-kit/deploy.sh"

# Ссылки на поддиректории для deploy.sh
ln -s ../bot     "$OUT/bot_link"    2>/dev/null || true
ln -s ../rackviz "$OUT/rackviz_link" 2>/dev/null || true

ok "Deploy kit скопирован"

# ── Архив ─────────────────────────────────────────────────────────────────────
info "Создаю архив..."
ARCHIVE="/tmp/mc-stack-deploy-$(date +%Y%m%d).tar.gz"
tar -czf "$ARCHIVE" -C /tmp mc-stack-deploy
rm -rf "$OUT"

SIZE=$(du -sh "$ARCHIVE" | cut -f1)
echo
echo "═══════════════════════════════════════════════════"
echo -e "${GREEN}✅ Архив создан: $ARCHIVE ($SIZE)${NC}"
echo "═══════════════════════════════════════════════════"
echo
echo "Скопируй на новый сервер:"
echo "  scp $ARCHIVE root@NEW_SERVER_IP:/tmp/"
echo
echo "На новом сервере:"
echo "  cd /tmp && tar xzf mc-stack-deploy-*.tar.gz"
echo "  cd mc-stack-deploy/deploy-kit"
echo "  bash deploy.sh"
echo
