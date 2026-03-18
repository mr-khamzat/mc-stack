// Service Worker — Умный Дом PWA
const CACHE = 'smarthome-v34';

// ── IndexedDB helpers (хранение HA-токена для reject из SW) ───────────────
const _IDB_NAME  = 'ha-sw';
const _IDB_STORE = 'kv';

function _idbOpen() {
  return new Promise(function(resolve, reject) {
    var req = indexedDB.open(_IDB_NAME, 1);
    req.onupgradeneeded = function(e) { e.target.result.createObjectStore(_IDB_STORE); };
    req.onsuccess  = function(e) { resolve(e.target.result); };
    req.onerror    = function(e) { reject(e.target.error); };
  });
}

function idbGet(key) {
  return _idbOpen().then(function(db) {
    return new Promise(function(resolve) {
      var tx = db.transaction(_IDB_STORE, 'readonly');
      var gr = tx.objectStore(_IDB_STORE).get(key);
      gr.onsuccess = function() { resolve(gr.result || null); };
      gr.onerror   = function() { resolve(null); };
    });
  }).catch(function() { return null; });
}

function idbSet(key, value) {
  return _idbOpen().then(function(db) {
    return new Promise(function(resolve) {
      var tx = db.transaction(_IDB_STORE, 'readwrite');
      tx.objectStore(_IDB_STORE).put(value, key);
      tx.oncomplete = function() { resolve(); };
      tx.onerror    = function() { resolve(); };
    });
  }).catch(function() {});
}

// ── Lifecycle ──────────────────────────────────────────────────────────────
self.addEventListener('install', function(e) {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(function(cache) {
      return cache.addAll(['/ha-app/', '/ha-app']);
    }).catch(function() {})
  );
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE; })
            .map(function(k) { return caches.delete(k); })
      );
    }).then(function() { return clients.claim(); })
  );
});

// ── Сообщения от страницы ──────────────────────────────────────────────────
self.addEventListener('message', function(e) {
  if (!e.data) return;
  if (e.data.type === 'store-ha-token') {
    // Сохраняем { ha_token, ha_username } для reject без открытия приложения
    idbSet('ha_auth', { token: e.data.token, username: e.data.username });
  }
});

// ── Push notification ──────────────────────────────────────────────────────
self.addEventListener('push', function(e) {
  var data = {};
  try { data = e.data.json(); } catch(_) {
    data = { title: 'Умный Дом', body: e.data ? e.data.text() : '' };
  }

  var isCall = data.tag === 'incoming-call';

  // Уведомить открытые вкладки приложения немедленно
  if (isCall) {
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(cs) {
      cs.forEach(function(c) {
        if (c.url.includes('/ha-app/')) {
          c.postMessage({ type: 'incoming-call' });
        }
      });
    });
  }

  e.waitUntil(
    self.registration.showNotification(data.title || 'Умный Дом', {
      body:    data.body || '',
      icon:    '/ha-app/icon-192.png',
      badge:   '/ha-app/icon-192.png',
      data:    {
        url:          data.url || '/ha-app/',
        tag:          data.tag,
        from_user:    data.from_user    || '',
        from_display: data.from_display || '',
      },
      vibrate:            isCall ? [300, 150, 300, 150, 300, 150, 300] : [100, 50, 100],
      tag:                data.tag || 'ha-notify',
      renotify:           true,
      requireInteraction: isCall,
      actions: isCall ? [
        { action: 'answer', title: '📞 Ответить'  },
        { action: 'reject', title: '❌ Отклонить' },
      ] : [],
    })
  );
});

// ── Клик по уведомлению (включая action buttons) ───────────────────────────
self.addEventListener('notificationclick', function(e) {
  e.notification.close();

  var notifData = e.notification.data || {};
  var tag       = notifData.tag      || '';
  var isCall    = tag === 'incoming-call';
  var fromUser  = notifData.from_user || '';
  var action    = e.action || '';   // 'answer', 'reject', или '' (обычный тап)

  // ── Отклонить без открытия приложения ──────────────────────────────────
  if (isCall && action === 'reject') {
    e.waitUntil(
      idbGet('ha_auth').then(function(auth) {
        var tasks = [];
        if (auth && auth.token && fromUser) {
          tasks.push(
            fetch('/ha-app/api/call/signal', {
              method:  'POST',
              headers: {
                'Content-Type':  'application/json',
                'Authorization': 'Bearer ' + auth.token,
                'X-HA-User':     auth.username || '',
              },
              body: JSON.stringify({ to_user: fromUser, type: 'reject', payload: {} }),
            }).catch(function() {})
          );
        }
        // Уведомить открытые вкладки
        tasks.push(
          clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(cs) {
            cs.forEach(function(c) {
              if (c.url.includes('/ha-app/')) {
                c.postMessage({ type: 'call-rejected-by-sw', from_user: fromUser });
              }
            });
          })
        );
        return Promise.all(tasks);
      })
    );
    return;
  }

  // ── Ответить / обычный тап ─────────────────────────────────────────────
  var autoAnswer = isCall && action === 'answer';
  var openUrl    = isCall
    ? '/ha-app/' + (autoAnswer ? '?incoming_call=1&auto_answer=1' : '?incoming_call=1')
    : (notifData.url || '/ha-app/');

  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(cs) {
      var appClient = null;
      for (var i = 0; i < cs.length; i++) {
        if (cs[i].url.includes('/ha-app/')) { appClient = cs[i]; break; }
      }
      if (appClient) {
        if (isCall) {
          appClient.postMessage({ type: 'incoming-call', auto_answer: autoAnswer });
        }
        return appClient.focus();
      } else {
        return clients.openWindow(openUrl);
      }
    })
  );
});

self.addEventListener('fetch', function(e) {
  const url = e.request.url;
  // API и SSE — всегда с сети, не кешировать
  if (url.includes('/ha-app/api/')) return;
  // Остальное — сеть с fallback на кеш
  e.respondWith(
    fetch(e.request).then(function(resp) {
      if (resp.ok && e.request.method === 'GET') {
        const clone = resp.clone();
        caches.open(CACHE).then(function(c) { c.put(e.request, clone); });
      }
      return resp;
    }).catch(function() {
      return caches.match(e.request);
    })
  );
});
