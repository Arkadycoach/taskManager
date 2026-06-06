/**
 * Service Worker — Task Manager PWA
 * Обеспечивает офлайн-доступ к оболочке приложения
 */
const CACHE   = 'taskmanager-v2';
const OFFLINE = '/offline.html';

// Файлы для кэширования при установке
const PRECACHE = [
  '/',
  '/manifest.json',
  '/icons/icon-192.png',
  '/css/base.css',
  '/css/components.css',
  '/css/modals.css',
  '/css/sidebar.css',
  '/css/details.css',
  '/css/responsive.css',
  '/js/state.js',
  '/js/utils.js',
  '/js/api.js',
  '/js/app.js',
  '/js/events.js',
  '/js/modules/rich-editor.js',
  '/js/modules/filters.js',
  '/js/modules/render.js',
  '/js/modules/tasks.js',
  '/js/modules/modals.js',
  '/js/modules/sidebar.js',
  '/js/modules/details.js',
  '/js/modules/notifications.js',
];

// ── Install: precache shell ────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => {
        // addAll fails if any item 404s — use individual adds
        return Promise.allSettled(PRECACHE.map(url => c.add(url).catch(() => {})));
      })
      .then(() => self.skipWaiting())
  );
});

// ── Activate: clean old caches ─────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: network-first for API, cache-first for assets ──
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // API calls → всегда network (не кэшировать)
  if (url.pathname.startsWith('/tasks') ||
      url.pathname.startsWith('/subtasks') ||
      url.pathname.startsWith('/comments') ||
      url.pathname.startsWith('/webhook')) {
    return; // браузер делает запрос напрямую
  }

  // Assets → cache-first, fallback network
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request)
        .then(res => {
          if (res && res.status === 200 && e.request.method === 'GET') {
            const clone = res.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone));
          }
          return res;
        })
        .catch(() => caches.match('/'));
    })
  );
});
