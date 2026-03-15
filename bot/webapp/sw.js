// Service Worker — Умный Дом PWA
const CACHE = 'smarthome-v19';

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
  e.waitUntil(
    self.registration.showNotification(data.title || 'Умный Дом', {
      body:    data.body   || '',
      icon:    '/ha-app/manifest.json',
      badge:   '/ha-app/manifest.json',
      data:    { url: data.url || '/ha-app/' },
      vibrate: [100, 50, 100],
      tag:     data.tag || 'ha-notify',
      renotify: true,
    })
  );
});

self.addEventListener('notificationclick', function(e) {
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || '/ha-app/';
  e.waitUntil(clients.matchAll({ type: 'window' }).then(function(cs) {
    for (var c of cs) { if (c.url.includes('/ha-app/') && 'focus' in c) return c.focus(); }
    return clients.openWindow(url);
  }));
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
