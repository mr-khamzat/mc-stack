// Service Worker — Friends PWA
const CACHE = 'friends-v2';
const SHELL = [
  '/friends/',
  '/friends/manifest.json',
  '/friends/icon-192.png',
  '/friends/icon-512.png',
];

self.addEventListener('install', function(e) {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(function(cache) { return cache.addAll(SHELL); })
  );
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.filter(function(k) { return k !== CACHE; }).map(function(k) { return caches.delete(k); }));
    }).then(function() { return clients.claim(); })
  );
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
      icon:    '/friends/icon-192.png',
      badge:   '/friends/icon-192.png',
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

// ── Fetch: network-first, fallback to cache ────────────────────────────────
self.addEventListener('fetch', function(e) {
  if (e.request.url.includes('/friends/api/')) return;
  e.respondWith(
    fetch(e.request).then(function(resp) {
      // Cache successful GET responses for the shell
      if (e.request.method === 'GET' && resp.status === 200) {
        var clone = resp.clone();
        caches.open(CACHE).then(function(cache) { cache.put(e.request, clone); });
      }
      return resp;
    }).catch(function() {
      return caches.match(e.request);
    })
  );
});
