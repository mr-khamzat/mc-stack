#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════════
# HA Home Bot — Веб-мастер первоначальной настройки
# Запускается автоматически если .env не заполнен
# Открой в браузере: http://<IP сервера>/
# ═══════════════════════════════════════════════════════════════════════════════
import asyncio, os, secrets, subprocess
from pathlib import Path
from aiohttp import web, ClientSession, ClientTimeout

INSTALL_DIR = Path('/opt/ha-bot')
ENV_FILE    = INSTALL_DIR / '.env'
PORT        = 8766

# ── HTML страница настройки ────────────────────────────────────────────────────
SETUP_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HA Home Bot — Настройка</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     background:#07071a;color:#e2e8f0;min-height:100vh;
     display:flex;justify-content:center;padding:20px 16px 80px}
.wrap{width:100%;max-width:560px}
.logo{text-align:center;padding:36px 0 28px}
.logo .icon{font-size:56px}
.logo h1{font-size:26px;font-weight:700;margin-top:12px}
.logo p{color:#64748b;font-size:14px;margin-top:6px}
.card{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
      border-radius:20px;padding:22px 20px;margin-bottom:14px}
.card-title{font-size:11px;font-weight:700;color:#6366f1;
            text-transform:uppercase;letter-spacing:1px;margin-bottom:18px}
.steps{display:flex;flex-direction:column;gap:14px}
.step{display:flex;gap:12px;align-items:flex-start}
.sn{width:26px;height:26px;border-radius:50%;
    background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.35);
    display:flex;align-items:center;justify-content:center;
    font-size:12px;font-weight:700;color:#818cf8;flex-shrink:0;margin-top:2px}
.st{font-size:13px;color:#94a3b8;line-height:1.55}
.st b{color:#e2e8f0}.st a{color:#818cf8;text-decoration:none}
.st code{color:#c4b5fd;background:rgba(99,102,241,0.12);
          padding:1px 5px;border-radius:4px;font-size:12px}
.field{margin-bottom:18px}
.field:last-child{margin-bottom:0}
label{display:block;font-size:13px;font-weight:600;color:#c4b5fd;margin-bottom:5px}
.hint{font-size:12px;color:#60708a;margin-bottom:8px;line-height:1.5}
.hint a{color:#818cf8;text-decoration:none}
input{width:100%;padding:12px 14px;border-radius:12px;
      border:1px solid rgba(255,255,255,0.10);
      background:rgba(255,255,255,0.06);color:#e2e8f0;
      font-size:14px;font-family:inherit;outline:none;
      transition:border-color .2s}
input:focus{border-color:rgba(99,102,241,0.5)}
input.ok {border-color:rgba(34,197,94,0.5)!important}
input.err{border-color:rgba(239,68,68,0.5)!important}
.opt{font-size:10px;background:rgba(99,102,241,0.12);
     border:1px solid rgba(99,102,241,0.25);border-radius:5px;
     padding:1px 6px;color:#818cf8;margin-left:7px;vertical-align:middle}
.check-btn{padding:6px 12px;border-radius:8px;
           border:1px solid rgba(99,102,241,0.3);
           background:rgba(99,102,241,0.1);color:#818cf8;
           font-size:12px;cursor:pointer;font-family:inherit;
           margin-top:7px;transition:background .15s}
.check-btn:hover{background:rgba(99,102,241,0.2)}
.check-btn:disabled{opacity:.4;cursor:not-allowed}
.fstatus{font-size:12px;margin-top:6px;min-height:16px}
.fstatus.ok {color:#4ade80}
.fstatus.err{color:#f87171}
.submit-btn{width:100%;padding:16px;border-radius:16px;border:none;
            background:linear-gradient(135deg,rgba(99,102,241,.75),rgba(139,92,246,.65));
            color:#fff;font-size:16px;font-weight:700;cursor:pointer;
            font-family:inherit;transition:opacity .2s;margin-top:4px;
            letter-spacing:.2px}
.submit-btn:hover{opacity:.9}
.submit-btn:disabled{opacity:.35;cursor:not-allowed}
.result{padding:14px 16px;border-radius:12px;margin-top:14px;
        font-size:14px;display:none;line-height:1.5}
.result.ok {background:rgba(34,197,94,.08); border:1px solid rgba(34,197,94,.3); color:#4ade80}
.result.err{background:rgba(239,68,68,.08); border:1px solid rgba(239,68,68,.3); color:#f87171}
#prog{display:none;text-align:center;padding:24px 0}
.spin{display:inline-block;width:34px;height:34px;
      border:3px solid rgba(99,102,241,.2);border-top-color:#6366f1;
      border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
#prog-text{margin-top:12px;color:#64748b;font-size:14px}
</style>
</head>
<body>
<div class="wrap">

  <div class="logo">
    <div class="icon">🏠</div>
    <h1>HA Home Bot</h1>
    <p>Первоначальная настройка</p>
  </div>

  <!-- Инструкция по получению токенов -->
  <div class="card">
    <div class="card-title">📋 Что нужно подготовить</div>
    <div class="steps">
      <div class="step">
        <div class="sn">1</div>
        <div class="st">
          <b>Bot Token</b> — создай бота:<br>
          Открой <a href="https://t.me/BotFather" target="_blank">@BotFather</a> → команда <b>/newbot</b> → придумай имя → скопируй токен вида <code>123456789:AAFxxx...</code>
        </div>
      </div>
      <div class="step">
        <div class="sn">2</div>
        <div class="st">
          <b>Твой Telegram ID</b> — числовой идентификатор:<br>
          Напиши <a href="https://t.me/userinfobot" target="_blank">@userinfobot</a> → он пришлёт твой ID (6–10 цифр)
        </div>
      </div>
      <div class="step">
        <div class="sn">3</div>
        <div class="st">
          <b>Адрес Home Assistant</b> — локальный URL:<br>
          <code>http://192.168.1.X:8123</code> или <code>http://homeassistant.local:8123</code>
        </div>
      </div>
      <div class="step">
        <div class="sn">4</div>
        <div class="st">
          <b>HA Long-Lived Token</b> — токен доступа к API:<br>
          Открой HA → кликни на своё имя (Профиль) → вкладка <b>Безопасность</b> → раздел <b>«Токены долгосрочного доступа»</b> → кнопка <b>«Создать токен»</b>
        </div>
      </div>
    </div>
  </div>

  <!-- Форма настройки -->
  <div class="card">
    <div class="card-title">⚙️ Настройки бота</div>

    <div class="field">
      <label>🤖 Telegram Bot Token</label>
      <div class="hint">Получи у <a href="https://t.me/BotFather" target="_blank">@BotFather</a> → /newbot</div>
      <input id="bot-token" type="text" placeholder="123456789:AAFxxxxxxxxxxxxxxxxxxxxxxx" autocomplete="off" spellcheck="false">
      <button class="check-btn" id="btn-check-token" onclick="checkToken()">✓ Проверить токен</button>
      <div class="fstatus" id="st-token"></div>
    </div>

    <div class="field">
      <label>👤 Твой Telegram ID</label>
      <div class="hint">Числовой ID — узнай у <a href="https://t.me/userinfobot" target="_blank">@userinfobot</a></div>
      <input id="admin-id" type="text" placeholder="293633093" inputmode="numeric" autocomplete="off">
      <div class="fstatus" id="st-admin-id"></div>
    </div>

    <div class="field">
      <label>🏠 URL Home Assistant</label>
      <div class="hint">Например: <code>http://192.168.1.100:8123</code></div>
      <input id="ha-url" type="text" placeholder="http://192.168.1.100:8123" autocomplete="off">
      <div class="fstatus" id="st-ha-url"></div>
    </div>

    <div class="field">
      <label>🔑 HA Long-Lived Access Token</label>
      <div class="hint">HA → Профиль → Безопасность → Токены долгосрочного доступа → Создать</div>
      <input id="ha-token" type="password" placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." autocomplete="off" spellcheck="false">
      <button class="check-btn" id="btn-check-ha" onclick="checkHA()">✓ Проверить подключение к HA</button>
      <div class="fstatus" id="st-ha"></div>
    </div>

    <div class="field">
      <label>👑 Твой логин в Home Assistant <span class="opt">необязательно</span></label>
      <div class="hint">Username в HA — даёт права администратора в Mini App. Обычно: <code>homeassistant</code> или твоё имя пользователя.</div>
      <input id="ha-admin" type="text" placeholder="homeassistant" autocomplete="off">
    </div>

    <div class="field">
      <label>🌐 URL Mini App для Telegram <span class="opt">необязательно</span></label>
      <div class="hint">
        Нужен HTTPS. Оставь пустым — мини-приложение будет работать в локальной сети.<br>
        Позже настрой Cloudflare Tunnel: <code>bash setup-cloudflare.sh</code><br>
        Пример: <code>https://app.yourdomain.com/ha-app/</code>
      </div>
      <input id="webapp-url" type="text" placeholder="https://app.yourdomain.com/ha-app/" autocomplete="off">
    </div>
  </div>

  <button class="submit-btn" id="submit-btn" onclick="doSetup()">
    🚀 Сохранить и запустить бота
  </button>

  <div id="prog">
    <div class="spin"></div>
    <div id="prog-text">Проверяем настройки...</div>
  </div>

  <div class="result" id="result"></div>

</div>
<script>
const $ = id => document.getElementById(id);

function setStatus(id, msg, type) {
  const el = $(id);
  if (el) { el.textContent = msg; el.className = 'fstatus ' + type; }
}
function setInput(id, type) {
  const el = $(id);
  if (el) el.className = type;
}

async function postJSON(path, data) {
  const r = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  return r.json();
}

async function checkToken() {
  const token = $('bot-token').value.trim();
  if (!token) { setStatus('st-token','⚠️ Введи токен','err'); return; }
  const btn = $('btn-check-token');
  btn.disabled = true; btn.textContent = '⏳ Проверяю...';
  try {
    const r = await postJSON('/api/check-token', {token});
    if (r.ok) {
      setStatus('st-token', '✅ Бот найден: ' + r.name + ' (@' + r.username + ')', 'ok');
      setInput('bot-token', 'ok');
    } else {
      setStatus('st-token', '❌ ' + (r.error || 'Неверный токен'), 'err');
      setInput('bot-token', 'err');
    }
  } catch(e) {
    setStatus('st-token', '❌ Нет интернета или ошибка соединения', 'err');
  }
  btn.disabled = false; btn.textContent = '✓ Проверить токен';
}

async function checkHA() {
  const url   = $('ha-url').value.trim().replace(/\/+$/, '');
  const token = $('ha-token').value.trim();
  if (!url || !token) { setStatus('st-ha', '⚠️ Введи URL и токен HA', 'err'); return; }
  const btn = $('btn-check-ha');
  btn.disabled = true; btn.textContent = '⏳ Подключаюсь...';
  try {
    const r = await postJSON('/api/check-ha', {url, token});
    if (r.ok) {
      setStatus('st-ha', '✅ Home Assistant ' + (r.version || '') + ' — подключено', 'ok');
      setInput('ha-url',   'ok');
      setInput('ha-token', 'ok');
    } else {
      setStatus('st-ha', '❌ ' + (r.error || 'Ошибка подключения'), 'err');
      setInput('ha-url',   'err');
      setInput('ha-token', 'err');
    }
  } catch(e) {
    setStatus('st-ha', '❌ Ошибка: ' + e.message, 'err');
  }
  btn.disabled = false; btn.textContent = '✓ Проверить подключение к HA';
}

function validate() {
  const errs = [];
  const token = $('bot-token').value.trim();
  if (!token || !/^\d+:/.test(token)) errs.push('Неверный формат Bot Token (должен начинаться с цифр и двоеточия)');
  if (!/^\d{5,12}$/.test($('admin-id').value.trim())) errs.push('Admin ID должен быть числом (5–12 цифр)');
  const haUrl = $('ha-url').value.trim();
  if (!haUrl || !/^https?:\/\//.test(haUrl)) errs.push('Неверный URL Home Assistant');
  if ($('ha-token').value.trim().length < 10) errs.push('Введи HA Long-Lived Token');
  return errs;
}

async function doSetup() {
  const errs = validate();
  if (errs.length) {
    showResult('err', '❌ ' + errs.join('<br>❌ '));
    return;
  }
  $('submit-btn').style.display = 'none';
  $('result').style.display = 'none';
  $('prog').style.display = 'block';

  const payload = {
    bot_token:  $('bot-token').value.trim(),
    admin_id:   $('admin-id').value.trim(),
    ha_url:     $('ha-url').value.trim().replace(/\/+$/, ''),
    ha_token:   $('ha-token').value.trim(),
    ha_admin:   $('ha-admin').value.trim() || 'homeassistant',
    webapp_url: $('webapp-url').value.trim(),
  };

  try {
    $('prog-text').textContent = '🔍 Проверяю токен Telegram...';
    let r = await postJSON('/api/check-token', {token: payload.bot_token});
    if (!r.ok) { showError('❌ Bot Token не работает: ' + (r.error||'')); return; }

    $('prog-text').textContent = '🔍 Проверяю подключение к Home Assistant...';
    r = await postJSON('/api/check-ha', {url: payload.ha_url, token: payload.ha_token});
    if (!r.ok) { showError('❌ Не могу подключиться к HA: ' + (r.error||'')); return; }

    $('prog-text').textContent = '💾 Сохраняю настройки...';
    r = await postJSON('/api/save', payload);
    if (!r.ok) { showError('❌ ' + (r.error||'Ошибка сохранения')); return; }

    $('prog-text').textContent = '🚀 Запускаю бота... (подождите 5 секунд)';
    await new Promise(res => setTimeout(res, 5000));
    window.location.href = '/ha-app/';

  } catch(e) {
    showError('❌ Ошибка: ' + e.message);
  }
}

function showError(msg) {
  $('prog').style.display = 'none';
  $('submit-btn').style.display = '';
  showResult('err', msg);
}
function showResult(type, html) {
  const el = $('result');
  el.className = 'result ' + type;
  el.innerHTML = html;
  el.style.display = '';
}
</script>
</body>
</html>"""


# ── API: проверка токена Telegram ──────────────────────────────────────────────
async def api_check_token(request):
    try:
        data  = await request.json()
        token = data.get('token', '').strip()
        if not token or ':' not in token:
            return web.json_response({'ok': False, 'error': 'Неверный формат токена'})
        async with ClientSession(timeout=ClientTimeout(total=8)) as s:
            async with s.get(f'https://api.telegram.org/bot{token}/getMe') as r:
                res = await r.json()
                if res.get('ok'):
                    bot = res['result']
                    return web.json_response({
                        'ok': True,
                        'name':     bot.get('first_name', ''),
                        'username': bot.get('username', ''),
                    })
                return web.json_response({'ok': False, 'error': res.get('description', 'Неверный токен')})
    except Exception as e:
        return web.json_response({'ok': False, 'error': f'Ошибка: {e}'})


# ── API: проверка Home Assistant ───────────────────────────────────────────────
async def api_check_ha(request):
    try:
        data  = await request.json()
        url   = data.get('url', '').strip().rstrip('/')
        token = data.get('token', '').strip()
        if not url or not token:
            return web.json_response({'ok': False, 'error': 'Укажи URL и токен'})
        async with ClientSession(timeout=ClientTimeout(total=10)) as s:
            async with s.get(
                f'{url}/api/',
                headers={'Authorization': f'Bearer {token}'},
                ssl=False
            ) as r:
                if r.status == 200:
                    res = await r.json()
                    return web.json_response({'ok': True, 'version': res.get('version', '')})
                elif r.status == 401:
                    return web.json_response({'ok': False, 'error': 'Неверный токен HA (401 Unauthorized)'})
                else:
                    return web.json_response({'ok': False, 'error': f'HA вернул статус {r.status}'})
    except Exception as e:
        err = str(e)
        if 'Cannot connect' in err or 'refused' in err.lower():
            err = 'Не могу подключиться — проверь IP-адрес и порт HA'
        elif 'timeout' in err.lower():
            err = 'Таймаут — HA не отвечает, проверь адрес'
        return web.json_response({'ok': False, 'error': err})


# ── API: сохранить .env и запустить бота ──────────────────────────────────────
async def api_save(request):
    try:
        data       = await request.json()
        bot_token  = data.get('bot_token',  '').strip()
        admin_id   = data.get('admin_id',   '').strip()
        ha_url     = data.get('ha_url',     '').strip().rstrip('/')
        ha_token   = data.get('ha_token',   '').strip()
        ha_admin   = data.get('ha_admin',   'homeassistant').strip() or 'homeassistant'
        webapp_url = data.get('webapp_url', '').strip().rstrip('/')

        if not all([bot_token, admin_id, ha_url, ha_token]):
            return web.json_response({'ok': False, 'error': 'Заполни все обязательные поля'})

        webapp_token = secrets.token_hex(16)

        # Нормализуем WEBAPP_URL
        if webapp_url and not webapp_url.endswith('/ha-app/'):
            webapp_url = webapp_url.rstrip('/') + '/ha-app/'

        env_content = f"""# ── Обязательные параметры ───────────────────────────────────────────────────
BOT_TOKEN={bot_token}
ADMIN_ID={admin_id}
HA_URL={ha_url}
HA_TOKEN={ha_token}

# ── Mini App ──────────────────────────────────────────────────────────────────
# Публичный HTTPS URL (нужен для Telegram Mini App)
# Оставь пустым — настрой Cloudflare Tunnel позже (setup-cloudflare.sh)
WEBAPP_URL={webapp_url}
WEBAPP_TOKEN={webapp_token}
WEBAPP_DIR={INSTALL_DIR}/webapp

# HA-логины с правами admin в Mini App (через запятую)
HA_WEBAPP_ADMINS={ha_admin}

# ── Опциональные параметры ────────────────────────────────────────────────────
# Домены для проверки SSL (если не задано — берётся из WEBAPP_URL)
# SSL_CHECK_DOMAINS=yourdomain.com

# Frigate NVR (если используется видеонаблюдение)
# FRIGATE_URL=http://192.168.1.100:5000

# WebRTC TURN сервер (для звонков через разные сети)
# SERVER_IP=1.2.3.4
# TURN_SECRET=change_me_turn_secret

# Claude AI для команды /ai
# ANTHROPIC_API_KEY=sk-ant-...
"""
        ENV_FILE.write_text(env_content)
        os.chmod(ENV_FILE, 0o600)

        # Запускаем ha-bot, останавливаем себя через 3 сек
        subprocess.Popen(['systemctl', 'start', 'ha-bot'])
        asyncio.get_event_loop().call_later(4, _stop_self)

        return web.json_response({'ok': True})
    except Exception as e:
        return web.json_response({'ok': False, 'error': str(e)})


def _stop_self():
    subprocess.Popen(['systemctl', 'stop', 'ha-bot-setup'])


# ── Главная ────────────────────────────────────────────────────────────────────
async def handle_root(request):
    # Если уже настроен — редиректим в Mini App
    if ENV_FILE.exists() and ENV_FILE.stat().st_size > 100:
        env = ENV_FILE.read_text()
        if 'BOT_TOKEN=' in env and not 'BOT_TOKEN=\n' in env:
            return web.HTTPFound('/ha-app/')
    return web.Response(text=SETUP_HTML, content_type='text/html')


async def main():
    app = web.Application()
    app.router.add_get('/',                    handle_root)
    app.router.add_get('/setup',               handle_root)
    app.router.add_post('/api/check-token',    api_check_token)
    app.router.add_post('/api/check-ha',       api_check_ha)
    app.router.add_post('/api/save',           api_save)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f'[setup-wizard] Listening on http://0.0.0.0:{PORT}/')
    print(f'[setup-wizard] Open in browser: http://<server-ip>/')
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
