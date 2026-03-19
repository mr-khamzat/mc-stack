#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════════
# HA Home Bot — Веб-мастер первоначальной настройки
# Порт: 8080 (бот работает на 8766 — нет конфликта портов)
# Открой в браузере: http://<IP>/
# ═══════════════════════════════════════════════════════════════════════════════
import asyncio, os, secrets, subprocess, socket
from pathlib import Path
from aiohttp import web, ClientSession, ClientTimeout

INSTALL_DIR = Path('/opt/ha-bot')
ENV_FILE    = INSTALL_DIR / '.env'
WIZARD_PORT = 8080   # мастер настройки
BOT_PORT    = 8766   # основной бот


def get_server_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


# ── HTML страница настройки ────────────────────────────────────────────────────
def make_setup_html():
    server_ip = get_server_ip()
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HA Home Bot — Настройка</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     background:#07071a;color:#e2e8f0;min-height:100vh;
     display:flex;justify-content:center;padding:20px 16px 80px}}
.wrap{{width:100%;max-width:560px}}
.logo{{text-align:center;padding:32px 0 24px}}
.logo .icon{{font-size:52px}}
.logo h1{{font-size:26px;font-weight:700;margin-top:10px}}
.logo p{{color:#64748b;font-size:14px;margin-top:5px}}
.card{{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
      border-radius:20px;padding:22px 20px;margin-bottom:14px}}
.card-title{{font-size:11px;font-weight:700;color:#6366f1;
            text-transform:uppercase;letter-spacing:1px;margin-bottom:16px}}
.steps{{display:flex;flex-direction:column;gap:13px}}
.step{{display:flex;gap:12px;align-items:flex-start}}
.sn{{width:26px;height:26px;border-radius:50%;
    background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.35);
    display:flex;align-items:center;justify-content:center;
    font-size:12px;font-weight:700;color:#818cf8;flex-shrink:0;margin-top:2px}}
.st{{font-size:13px;color:#94a3b8;line-height:1.55}}
.st b{{color:#e2e8f0}}.st a{{color:#818cf8;text-decoration:none}}
.st code{{color:#c4b5fd;background:rgba(99,102,241,0.12);
          padding:1px 5px;border-radius:4px;font-size:12px}}
.field{{margin-bottom:18px}}
.field:last-child{{margin-bottom:0}}
label{{display:block;font-size:13px;font-weight:600;color:#c4b5fd;margin-bottom:5px}}
.hint{{font-size:12px;color:#60708a;margin-bottom:8px;line-height:1.5}}
.hint a{{color:#818cf8;text-decoration:none}}
.hint code{{color:#c4b5fd;background:rgba(99,102,241,0.10);
            padding:1px 5px;border-radius:4px;font-size:11px}}
input{{width:100%;padding:12px 14px;border-radius:12px;
      border:1px solid rgba(255,255,255,0.10);
      background:rgba(255,255,255,0.06);color:#e2e8f0;
      font-size:14px;font-family:inherit;outline:none;
      transition:border-color .2s}}
input:focus{{border-color:rgba(99,102,241,0.5)}}
input.ok{{border-color:rgba(34,197,94,0.5)!important}}
input.err{{border-color:rgba(239,68,68,0.5)!important}}
.opt{{font-size:10px;background:rgba(99,102,241,0.12);
     border:1px solid rgba(99,102,241,0.25);border-radius:5px;
     padding:1px 6px;color:#818cf8;margin-left:7px;vertical-align:middle}}
.check-btn{{padding:7px 13px;border-radius:8px;
           border:1px solid rgba(99,102,241,0.3);
           background:rgba(99,102,241,0.1);color:#818cf8;
           font-size:12px;cursor:pointer;font-family:inherit;
           margin-top:7px;transition:background .15s}}
.check-btn:hover{{background:rgba(99,102,241,0.2)}}
.check-btn:disabled{{opacity:.4;cursor:not-allowed}}
.fstatus{{font-size:12px;margin-top:6px;min-height:16px}}
.fstatus.ok{{color:#4ade80}}.fstatus.err{{color:#f87171}}
.submit-btn{{width:100%;padding:16px;border-radius:16px;border:none;
            background:linear-gradient(135deg,rgba(99,102,241,.75),rgba(139,92,246,.65));
            color:#fff;font-size:16px;font-weight:700;cursor:pointer;
            font-family:inherit;transition:opacity .2s;margin-top:4px}}
.submit-btn:hover{{opacity:.9}}
.submit-btn:disabled{{opacity:.35;cursor:not-allowed}}
#prog{{display:none;text-align:center;padding:24px 0}}
.spin{{display:inline-block;width:34px;height:34px;
      border:3px solid rgba(99,102,241,.2);border-top-color:#6366f1;
      border-radius:50%;animation:spin .8s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
#prog-text{{margin-top:12px;color:#64748b;font-size:14px}}
.result{{padding:14px 16px;border-radius:12px;margin-top:14px;
        font-size:14px;display:none;line-height:1.6}}
.result.ok{{background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.3);color:#4ade80}}
.result.err{{background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);color:#f87171}}
/* Success page */
#success{{display:none;padding:0 0 20px}}
.success-icon{{text-align:center;font-size:52px;margin-bottom:16px}}
.open-btn{{display:block;width:100%;padding:16px;border-radius:16px;border:none;
           background:linear-gradient(135deg,rgba(34,197,94,.5),rgba(16,185,129,.4));
           color:#4ade80;font-size:16px;font-weight:700;cursor:pointer;
           font-family:inherit;text-decoration:none;text-align:center;margin-bottom:12px}}
.cf-card{{background:rgba(251,191,36,0.06);border:1px solid rgba(251,191,36,0.2);
          border-radius:14px;padding:16px 18px;margin-top:14px}}
.cf-title{{font-size:13px;font-weight:700;color:#fbbf24;margin-bottom:10px}}
.cf-text{{font-size:13px;color:#94a3b8;line-height:1.6}}
.cf-cmd{{background:rgba(0,0,0,0.3);border-radius:8px;padding:10px 12px;
         font-family:monospace;font-size:12px;color:#c4b5fd;
         margin-top:10px;word-break:break-all;cursor:pointer;
         border:1px solid rgba(99,102,241,0.2)}}
.cf-cmd:hover{{background:rgba(99,102,241,0.1)}}
.cf-cmd::after{{content:'  📋';font-size:11px}}
.local-url{{background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);
            border-radius:10px;padding:10px 14px;font-family:monospace;
            font-size:14px;color:#4ade80;margin:10px 0;word-break:break-all}}
</style>
</head>
<body>
<div class="wrap">
  <div class="logo">
    <div class="icon">🏠</div>
    <h1>HA Home Bot</h1>
    <p>Первоначальная настройка</p>
  </div>

  <!-- ── Инструкция ──────────────────────────────────────────────────────── -->
  <div class="card">
    <div class="card-title">📋 Что подготовить</div>
    <div class="steps">
      <div class="step">
        <div class="sn">1</div>
        <div class="st">
          <b>Bot Token</b> — создай бота:<br>
          <a href="https://t.me/BotFather" target="_blank">@BotFather</a> → <b>/newbot</b> → придумай имя → скопируй токен <code>123456789:AAFxxx...</code>
        </div>
      </div>
      <div class="step">
        <div class="sn">2</div>
        <div class="st">
          <b>Твой Telegram ID</b> — напиши <a href="https://t.me/userinfobot" target="_blank">@userinfobot</a>, он пришлёт числовой ID
        </div>
      </div>
      <div class="step">
        <div class="sn">3</div>
        <div class="st">
          <b>URL Home Assistant</b> → <code>http://192.168.1.X:8123</code>
        </div>
      </div>
      <div class="step">
        <div class="sn">4</div>
        <div class="st">
          <b>HA Long-Lived Token</b> → HA → Профиль → <b>Безопасность</b> → <b>Токены долгосрочного доступа</b> → Создать
        </div>
      </div>
    </div>
  </div>

  <!-- ── Форма ───────────────────────────────────────────────────────────── -->
  <div id="form-card" class="card">
    <div class="card-title">⚙️ Настройки</div>

    <div class="field">
      <label>🤖 Telegram Bot Token</label>
      <div class="hint">Получи у <a href="https://t.me/BotFather" target="_blank">@BotFather</a> → /newbot</div>
      <input id="bot-token" type="text" placeholder="123456789:AAFxxxxxxxxxxxxxxxxxxxxxxx" autocomplete="off" spellcheck="false">
      <button class="check-btn" id="btn-ct" onclick="checkToken()">✓ Проверить токен</button>
      <div class="fstatus" id="st-token"></div>
    </div>

    <div class="field">
      <label>👤 Твой Telegram ID</label>
      <div class="hint">Напиши <a href="https://t.me/userinfobot" target="_blank">@userinfobot</a> — числовой ID</div>
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
      <button class="check-btn" id="btn-cha" onclick="checkHA()">✓ Проверить подключение к HA</button>
      <div class="fstatus" id="st-ha"></div>
    </div>

    <div class="field">
      <label>👑 Твой логин в Home Assistant <span class="opt">необязательно</span></label>
      <div class="hint">Username в HA для прав администратора в Mini App. Обычно <code>homeassistant</code>.</div>
      <input id="ha-admin" type="text" placeholder="homeassistant" autocomplete="off">
    </div>
  </div>

  <div id="submit-wrap">
    <button class="submit-btn" onclick="doSetup()">🚀 Сохранить и запустить бота</button>
  </div>

  <div id="prog">
    <div class="spin"></div>
    <div id="prog-text">Проверяем настройки...</div>
  </div>

  <div class="result" id="result"></div>

  <!-- ── Страница успеха ─────────────────────────────────────────────────── -->
  <div id="success">
    <div class="card">
      <div class="success-icon">✅</div>
      <div style="text-align:center;font-size:18px;font-weight:700;margin-bottom:8px">Бот запущен!</div>
      <div style="text-align:center;font-size:14px;color:#64748b;margin-bottom:20px">
        Настройки сохранены, ha-bot запускается...
      </div>

      <div style="font-size:13px;color:#94a3b8;margin-bottom:8px">
        🖥️ Открыть Mini App в браузере (локальная сеть):
      </div>
      <div class="local-url" id="local-url">http://{server_ip}/ha-app/</div>
      <a class="open-btn" id="open-btn" href="http://{server_ip}/ha-app/" target="_blank">
        🌐 Открыть Mini App
      </a>

      <div style="font-size:12px;color:#64748b;margin-bottom:0">
        ⚠️ Если кнопка не открывается — подождите 10–15 секунд, бот ещё запускается.
      </div>
    </div>

    <div class="cf-card">
      <div class="cf-title">📱 Хочешь открывать Mini App прямо из Telegram?</div>
      <div class="cf-text">
        Telegram требует <b>HTTPS</b>. Для доступа из интернета настрой
        <b>Cloudflare Tunnel</b> — бесплатно, без белого IP, 5 минут:
      </div>
      <div class="cf-cmd" onclick="copyCmd(this)">bash &lt;(curl -fsSL https://raw.githubusercontent.com/mr-khamzat/mc-stack/main/install/setup-cloudflare.sh)</div>
      <div style="margin-top:12px;font-size:12px;color:#64748b;line-height:1.6">
        После настройки Cloudflare добавь полученный URL в <code style="color:#c4b5fd">/opt/ha-bot/.env</code> →
        строка <code style="color:#c4b5fd">WEBAPP_URL=https://app.yourdomain.com/ha-app/</code><br>
        Затем: <code style="color:#c4b5fd">systemctl restart ha-bot</code>
      </div>
    </div>

    <div class="card" style="margin-top:14px">
      <div class="card-title">📋 Полезные команды</div>
      <div style="font-size:13px;color:#64748b;line-height:2">
        <code style="color:#c4b5fd">systemctl status ha-bot</code> — статус бота<br>
        <code style="color:#c4b5fd">journalctl -u ha-bot -f</code> — логи в реальном времени<br>
        <code style="color:#c4b5fd">nano /opt/ha-bot/.env</code> — редактировать конфиг<br>
        <code style="color:#c4b5fd">systemctl restart ha-bot</code> — перезапустить бота
      </div>
    </div>
  </div>

</div>
<script>
const $ = id => document.getElementById(id);
const SERVER_IP = '{server_ip}';

async function postJSON(path, data) {{
  const r = await fetch(path, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}});
  return r.json();
}}
function setStatus(id, msg, type) {{
  const el = $(id); if(!el) return;
  el.textContent = msg; el.className = 'fstatus ' + type;
}}
function setInput(id, type) {{
  const el = $(id); if(el) el.className = type;
}}

async function checkToken() {{
  const token = $('bot-token').value.trim();
  if (!token) {{ setStatus('st-token','⚠️ Введи токен','err'); return; }}
  const btn = $('btn-ct'); btn.disabled=true; btn.textContent='⏳...';
  try {{
    const r = await postJSON('/api/check-token', {{token}});
    if (r.ok) {{
      setStatus('st-token','✅ Бот: '+r.name+' (@'+r.username+')','ok');
      setInput('bot-token','ok');
    }} else {{
      setStatus('st-token','❌ '+(r.error||'Неверный токен'),'err');
      setInput('bot-token','err');
    }}
  }} catch(e) {{ setStatus('st-token','❌ Нет интернета','err'); }}
  btn.disabled=false; btn.textContent='✓ Проверить токен';
}}

async function checkHA() {{
  const url   = $('ha-url').value.trim().replace(/\/+$/,'');
  const token = $('ha-token').value.trim();
  if (!url||!token) {{ setStatus('st-ha','⚠️ Введи URL и токен HA','err'); return; }}
  const btn = $('btn-cha'); btn.disabled=true; btn.textContent='⏳...';
  try {{
    const r = await postJSON('/api/check-ha', {{url, token}});
    if (r.ok) {{
      setStatus('st-ha','✅ Home Assistant '+(r.version||'')+' — подключено','ok');
      setInput('ha-url','ok'); setInput('ha-token','ok');
    }} else {{
      setStatus('st-ha','❌ '+(r.error||'Ошибка'),'err');
      setInput('ha-url','err'); setInput('ha-token','err');
    }}
  }} catch(e) {{ setStatus('st-ha','❌ Ошибка: '+e.message,'err'); }}
  btn.disabled=false; btn.textContent='✓ Проверить подключение к HA';
}}

function validate() {{
  const errs=[];
  if (!/^\d+:/.test($('bot-token').value.trim())) errs.push('Неверный Bot Token');
  if (!/^\d{{5,12}}$/.test($('admin-id').value.trim())) errs.push('Admin ID — только цифры');
  if (!/^https?:\/\//.test($('ha-url').value.trim())) errs.push('Неверный URL HA');
  if ($('ha-token').value.trim().length < 10) errs.push('Введи HA Token');
  return errs;
}}

async function doSetup() {{
  const errs = validate();
  if (errs.length) {{
    const el=$('result'); el.className='result err';
    el.innerHTML='❌ '+errs.join('<br>❌ '); el.style.display='';
    return;
  }}
  $('submit-wrap').style.display='none';
  $('result').style.display='none';
  $('prog').style.display='block';

  const payload = {{
    bot_token: $('bot-token').value.trim(),
    admin_id:  $('admin-id').value.trim(),
    ha_url:    $('ha-url').value.trim().replace(/\/+$/,''),
    ha_token:  $('ha-token').value.trim(),
    ha_admin:  $('ha-admin').value.trim()||'homeassistant',
  }};

  try {{
    $('prog-text').textContent='🔍 Проверяю Bot Token...';
    let r = await postJSON('/api/check-token', {{token: payload.bot_token}});
    if (!r.ok) {{ showErr('❌ Bot Token: '+(r.error||'неверный')); return; }}

    $('prog-text').textContent='🔍 Проверяю Home Assistant...';
    r = await postJSON('/api/check-ha', {{url: payload.ha_url, token: payload.ha_token}});
    if (!r.ok) {{ showErr('❌ HA: '+(r.error||'нет подключения')); return; }}

    $('prog-text').textContent='💾 Сохраняю настройки...';
    r = await postJSON('/api/save', payload);
    if (!r.ok) {{ showErr('❌ '+(r.error||'Ошибка сохранения')); return; }}

    // Показываем страницу успеха
    $('prog').style.display='none';
    $('success').style.display='block';

    // Ждём запуска бота и пробуем открыть
    waitForBot();
  }} catch(e) {{
    showErr('❌ Ошибка: '+e.message);
  }}
}}

async function waitForBot() {{
  const btn = $('open-btn');
  const url = 'http://'+SERVER_IP+'/ha-app/api/health';
  for (let i=0; i<20; i++) {{
    await new Promise(res=>setTimeout(res,2000));
    try {{
      const r = await fetch(url, {{signal: AbortSignal.timeout(3000)}});
      if (r.ok) {{
        btn.style.background='linear-gradient(135deg,rgba(34,197,94,.7),rgba(16,185,129,.6))';
        btn.textContent='✅ Открыть Mini App';
        return;
      }}
    }} catch(e) {{}}
  }}
}}

function showErr(msg) {{
  $('prog').style.display='none';
  $('submit-wrap').style.display='';
  const el=$('result'); el.className='result err';
  el.innerHTML=msg; el.style.display='';
}}

function copyCmd(el) {{
  navigator.clipboard?.writeText(el.textContent.replace('  📋','').trim())
    .then(()=>{{ const old=el.textContent; el.textContent='✅ Скопировано!'; setTimeout(()=>el.textContent=old,1500); }});
}}
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
                    return web.json_response({'ok': True,
                        'name': bot.get('first_name', ''),
                        'username': bot.get('username', '')})
                return web.json_response({'ok': False, 'error': res.get('description', 'Неверный токен')})
    except Exception as e:
        return web.json_response({'ok': False, 'error': str(e)})


# ── API: проверка Home Assistant ───────────────────────────────────────────────
async def api_check_ha(request):
    try:
        data  = await request.json()
        url   = data.get('url', '').strip().rstrip('/')
        token = data.get('token', '').strip()
        if not url or not token:
            return web.json_response({'ok': False, 'error': 'Укажи URL и токен'})
        async with ClientSession(timeout=ClientTimeout(total=10)) as s:
            async with s.get(f'{url}/api/',
                             headers={'Authorization': f'Bearer {token}'},
                             ssl=False) as r:
                if r.status == 200:
                    res = await r.json()
                    return web.json_response({'ok': True, 'version': res.get('version', '')})
                elif r.status == 401:
                    return web.json_response({'ok': False, 'error': 'Неверный токен (401 Unauthorized)'})
                else:
                    return web.json_response({'ok': False, 'error': f'HA вернул {r.status}'})
    except Exception as e:
        err = str(e)
        if 'Cannot connect' in err or 'refused' in err.lower():
            err = 'Нет подключения — проверь IP и порт HA'
        elif 'timeout' in err.lower():
            err = 'Таймаут — HA не отвечает'
        return web.json_response({'ok': False, 'error': err})


# ── API: сохранить .env и запустить бота ──────────────────────────────────────
async def api_save(request):
    try:
        data      = await request.json()
        bot_token = data.get('bot_token', '').strip()
        admin_id  = data.get('admin_id',  '').strip()
        ha_url    = data.get('ha_url',    '').strip().rstrip('/')
        ha_token  = data.get('ha_token',  '').strip()
        ha_admin  = data.get('ha_admin',  'homeassistant').strip() or 'homeassistant'

        if not all([bot_token, admin_id, ha_url, ha_token]):
            return web.json_response({'ok': False, 'error': 'Заполни все обязательные поля'})

        webapp_token = secrets.token_hex(16)

        env_content = f"""# ── Обязательные параметры ───────────────────────────────────────────────────
BOT_TOKEN={bot_token}
ADMIN_ID={admin_id}
HA_URL={ha_url}
HA_TOKEN={ha_token}

# ── Mini App ──────────────────────────────────────────────────────────────────
# WEBAPP_URL — нужен HTTPS для Telegram (настрой Cloudflare Tunnel позже)
# Для локального доступа: http://{get_server_ip()}/ha-app/ — работает без этой строки
WEBAPP_URL=
WEBAPP_TOKEN={webapp_token}
WEBAPP_DIR={INSTALL_DIR}/webapp

# HA-логины с правами admin в Mini App (через запятую)
HA_WEBAPP_ADMINS={ha_admin}

# ── Опциональные параметры ────────────────────────────────────────────────────
# Frigate NVR
# FRIGATE_URL=http://192.168.1.100:5000
# Claude AI для команды /ai
# ANTHROPIC_API_KEY=sk-ant-...
"""
        ENV_FILE.write_text(env_content)
        os.chmod(ENV_FILE, 0o600)

        # Запускаем ha-bot в фоне (он на порту 8766, мы на 8080 — нет конфликта)
        subprocess.Popen(['systemctl', 'start', 'ha-bot'], start_new_session=True)

        return web.json_response({'ok': True})
    except Exception as e:
        return web.json_response({'ok': False, 'error': str(e)})


# ── Главная ────────────────────────────────────────────────────────────────────
async def handle_root(request):
    # Если уже настроен — редиректим
    if ENV_FILE.exists():
        env = ENV_FILE.read_text()
        if 'BOT_TOKEN=' in env and len([l for l in env.splitlines()
                                        if l.startswith('BOT_TOKEN=') and len(l) > 12]) > 0:
            return web.HTTPFound(f'http://{get_server_ip()}/ha-app/')
    return web.Response(text=make_setup_html(), content_type='text/html')


async def main():
    app = web.Application()
    app.router.add_get('/',                 handle_root)
    app.router.add_get('/setup',            handle_root)
    app.router.add_post('/api/check-token', api_check_token)
    app.router.add_post('/api/check-ha',    api_check_ha)
    app.router.add_post('/api/save',        api_save)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WIZARD_PORT)
    await site.start()
    print(f'[setup-wizard] http://0.0.0.0:{WIZARD_PORT}/ — open http://{get_server_ip()}/ in browser')
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
