// Service worker mínimo para que la app sea instalable (PWA).
// Estrategia: network-first sin cachear páginas (datos siempre frescos),
// con fallback al caché solo para que no falle si no hay red.
const CACHE = 'polla-2026-v1';

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        // Cachear solo recursos estáticos (íconos, logos) para velocidad
        if (e.request.url.includes('/static/')) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return resp;
      })
      .catch(() => caches.match(e.request))
  );
});
