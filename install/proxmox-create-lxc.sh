#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# HA Home Bot — Создание LXC контейнера на Proxmox
# ═══════════════════════════════════════════════════════════════════════════════
# Запускать: на хосте Proxmox (не внутри контейнера!)
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/proxmox-create-lxc.sh)
#
# Что делает:
#   1. Скачивает шаблон Ubuntu 24.04 (если не скачан)
#   2. Создаёт LXC контейнер ha-bot (512MB RAM, 8GB диск)
#   3. Запускает контейнер
#   4. Запускает install/setup.sh внутри контейнера
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Цвета для вывода ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
header()  { echo -e "\n${BOLD}${BLUE}══════════════════════════════════${NC}"; echo -e "${BOLD}  $*${NC}"; echo -e "${BOLD}${BLUE}══════════════════════════════════${NC}\n"; }

# ── Проверка что запущен на Proxmox ───────────────────────────────────────────
[[ -f /etc/pve/local/pve-ssl.pem ]] || error "Запусти этот скрипт на хосте Proxmox (не внутри контейнера)!"
command -v pct &>/dev/null         || error "Команда pct не найдена. Это не Proxmox?"

header "🏠 HA Home Bot — Установка на Proxmox"

# ── Настройки контейнера (можно менять) ───────────────────────────────────────
CT_ID="${CT_ID:-200}"           # ID контейнера (менять если 200 уже занят)
CT_HOSTNAME="ha-bot"            # Имя хоста контейнера
CT_RAM=512                      # RAM в MB (минимум 512, рекомендуется 1024)
CT_SWAP=512                     # Swap в MB
CT_DISK=8                       # Диск в GB
CT_CORES=1                      # Количество CPU ядер
CT_BRIDGE="vmbr0"               # Сетевой мост Proxmox
CT_IP="dhcp"                    # IP: "dhcp" или "192.168.1.X/24"
CT_GW=""                        # Шлюз (только если CT_IP не dhcp), например "192.168.1.1"
STORAGE="local-lvm"             # Хранилище для диска контейнера
TEMPLATE_STORAGE="local"        # Хранилище для шаблонов

TEMPLATE_NAME="ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
TEMPLATE_PATH="$TEMPLATE_STORAGE:vztmpl/$TEMPLATE_NAME"

# Пароль root для контейнера (случайный если не задан)
CT_PASSWORD="${CT_PASSWORD:-$(openssl rand -base64 12)}"

# ── Интерактивный ввод ─────────────────────────────────────────────────────────
echo -e "${BOLD}Параметры контейнера:${NC}"
read -rp "  ID контейнера [${CT_ID}]: " _id; CT_ID="${_id:-$CT_ID}"
read -rp "  Storage для диска [${STORAGE}]: " _st; STORAGE="${_st:-$STORAGE}"
read -rp "  RAM MB [${CT_RAM}]: " _ram; CT_RAM="${_ram:-$CT_RAM}"
read -rp "  IP (dhcp или 192.168.1.X/24) [${CT_IP}]: " _ip; CT_IP="${_ip:-$CT_IP}"

if [[ "$CT_IP" != "dhcp" && -z "$CT_GW" ]]; then
    read -rp "  Шлюз (Gateway, например 192.168.1.1): " CT_GW
fi

echo ""
info "CT_ID=$CT_ID | RAM=${CT_RAM}MB | DISK=${CT_DISK}GB | IP=$CT_IP | Storage=$STORAGE"

# ── Проверить не занят ли ID ───────────────────────────────────────────────────
if pct status "$CT_ID" &>/dev/null; then
    error "Контейнер $CT_ID уже существует! Измени CT_ID или удали старый контейнер."
fi

# ── Скачать шаблон Ubuntu 24.04 ───────────────────────────────────────────────
header "📦 Шаблон Ubuntu 24.04"

if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE_NAME"; then
    info "Шаблон не найден, скачиваем..."
    pveam update
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE_NAME" \
        || error "Не удалось скачать шаблон. Проверь имя шаблона командой: pveam available | grep ubuntu-24"
    ok "Шаблон скачан"
else
    ok "Шаблон уже есть"
fi

# ── Создать контейнер ─────────────────────────────────────────────────────────
header "🔧 Создание контейнера LXC #${CT_ID}"

# Формируем параметры сети
if [[ "$CT_IP" == "dhcp" ]]; then
    NET_PARAM="name=eth0,bridge=${CT_BRIDGE},ip=dhcp"
else
    NET_PARAM="name=eth0,bridge=${CT_BRIDGE},ip=${CT_IP},gw=${CT_GW}"
fi

pct create "$CT_ID" "$TEMPLATE_PATH" \
    --hostname "$CT_HOSTNAME" \
    --password "$CT_PASSWORD" \
    --cores "$CT_CORES" \
    --memory "$CT_RAM" \
    --swap "$CT_SWAP" \
    --rootfs "${STORAGE}:${CT_DISK}" \
    --net0 "$NET_PARAM" \
    --unprivileged 1 \
    --features nesting=1 \
    --start 1 \
    --onboot 1 \
    || error "Не удалось создать контейнер"

ok "Контейнер #${CT_ID} создан и запущен"

# ── Ждём пока контейнер загрузится ────────────────────────────────────────────
info "Ждём загрузку контейнера..."
sleep 8

# Проверяем что сеть поднялась
for i in {1..15}; do
    if pct exec "$CT_ID" -- ping -c1 -W2 8.8.8.8 &>/dev/null; then
        ok "Сеть работает"; break
    fi
    [[ $i -eq 15 ]] && warn "Сеть не отвечает, продолжаем всё равно..."
    sleep 2
done

# ── Запустить setup.sh внутри контейнера ─────────────────────────────────────
header "🚀 Запуск установки внутри контейнера"

SETUP_URL="https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/setup.sh"

info "Устанавливаем curl внутри контейнера..."
pct exec "$CT_ID" -- bash -c "apt-get update -qq && apt-get install -y -qq curl"

info "Запускаю setup.sh..."
pct exec "$CT_ID" -- bash -c "curl -fsSL '${SETUP_URL}' | bash"

# ── Итог ──────────────────────────────────────────────────────────────────────
header "✅ Контейнер создан"
echo -e "${BOLD}Данные контейнера:${NC}"
echo -e "  CT ID:    ${CYAN}$CT_ID${NC}"
echo -e "  Пароль:   ${CYAN}$CT_PASSWORD${NC}  (сохрани!)"
CT_REAL_IP=$(pct exec "$CT_ID" -- hostname -I 2>/dev/null | awk '{print $1}')
echo -e "  IP:       ${CYAN}${CT_REAL_IP:-$CT_IP}${NC}"
echo ""
echo -e "Войти в контейнер:"
echo -e "  ${YELLOW}pct exec $CT_ID -- bash${NC}"
echo -e "  или: ${YELLOW}pct enter $CT_ID${NC}"
echo ""
echo -e "После настройки .env перезапустить бота:"
echo -e "  ${YELLOW}pct exec $CT_ID -- systemctl restart ha-bot${NC}"
