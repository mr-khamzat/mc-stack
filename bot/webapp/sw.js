// Service Worker — Умный Дом PWA
const CACHE = 'smarthome-v28';

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
        keys.filter(function(k) { return k !== CACHE; }).map(function(k) {
          return caches.delete(k);
        })
      );
    }).then(function() { return clients.claim(); })
  );
});

// ── Push notification handler ──────────────────────────────────────────────
self.addEventListener('push', function(e) {
  var data = {};
  try { data = e.data.json(); } catch(_) { data = { title: 'Умный Дом', body: e.data ? e.data.text() : '' }; }

  var isCall = data.tag === 'incoming-call';

  // Для входящего звонка — сначала отправляем сообщение открытым вкладкам
  // чтобы они сразу показали UI звонка без задержки
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
      body:    data.body   || '',
      icon:    '/ha-app/icon-192.png',
      badge:   '/ha-app/icon-192.png',
      data:    { url: data.url || '/ha-app/', tag: data.tag },
      vibrate: isCall ? [200, 100, 200, 100, 200] : [100, 50, 100],
      tag:     data.tag || 'ha-notify',
      renotify: true,
      requireInteraction: isCall,  // звонок — не скрывается автоматически
    })
  );
});

// ── Клик по уведомлению ────────────────────────────────────────────────────
self.addEventListener('notificationclick', function(e) {
  e.notification.close();
  var url     = (e.notification.data && e.notification.data.url) || '/ha-app/';
  var tag     = (e.notification.data && e.notification.data.tag) || '';
  var isCall  = tag === 'incoming-call';

  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(cs) {
      var appClient = null;
      for (var c of cs) {
        if (c.url.includes('/ha-app/')) { appClient = c; break; }
      }

      if (appClient) {
        // Приложение уже открыто — отправляем сообщение и фокусируем
        if (isCall) {
          appClient.postMessage({ type: 'incoming-call' });
        }
        return appClient.focus();
      } else {
        // Приложение закрыто — открываем, при звонке передаём флаг через URL
        var openUrl = isCall ? url + (url.includes('?') ? '&' : '?') + 'incoming_call=1' : url;
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
