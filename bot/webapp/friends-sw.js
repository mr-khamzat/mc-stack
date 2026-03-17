// Service Worker — Friends PWA
const CACHE = 'friends-v1';

self.addEventListener('install', function(e) {
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(clients.claim());
});

// ── Push notification handler ──────────────────────────────────────────────
self.addEventListener('push', function(e) {
  var data = {};
  try { data = e.data.json(); } catch(_) { data = { title: 'Друзья', body: e.data ? e.data.text() : '' }; }

  var isCall = data.tag === 'fr-incoming-call';

  if (isCall) {
    // Notify open Friends tabs immediately
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(cs) {
      cs.forEach(function(c) {
        if (c.url.includes('/friends/')) {
          c.postMessage({ type: 'incoming-call' });
        }
      });
    });
  }

  e.waitUntil(
    self.registration.showNotification(data.title || 'Друзья', {
      body:    data.body || '',
      icon:    '/ha-app/icon-192.png',
      badge:   '/ha-app/icon-192.png',
      data:    { url: data.url || '/friends/', tag: data.tag },
      vibrate: isCall ? [200, 100, 200, 100, 200] : [100, 50, 100],
      requireInteraction: isCall,
      tag:     data.tag || 'fr-notify',
      actions: isCall ? [
        { action: 'answer', title: '✅ Ответить' },
        { action: 'reject', title: '❌ Отклонить' }
      ] : [],
    })
  );
});

// ── Notification click ─────────────────────────────────────────────────────
self.addEventListener('notificationclick', function(e) {
  e.notification.close();
  var url    = (e.notification.data && e.notification.data.url) || '/friends/';
  var tag    = (e.notification.data && e.notification.data.tag) || '';
  var isCall = tag === 'fr-incoming-call';

  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(cs) {
      var appClient = null;
      for (var c of cs) {
        if (c.url.includes('/friends/')) { appClient = c; break; }
      }
      if (appClient) {
        if (isCall) appClient.postMessage({ type: 'incoming-call' });
        return appClient.focus();
      } else {
        var openUrl = isCall ? '/friends/?incoming_call=1' : url;
        return clients.openWindow(openUrl);
      }
    })
  );
});

self.addEventListener('fetch', function(e) {
  if (e.request.url.includes('/friends/api/')) return;
  e.respondWith(fetch(e.request).catch(function() { return caches.match(e.request); }));
});
