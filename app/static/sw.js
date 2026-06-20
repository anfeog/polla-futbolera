// Service worker mínimo para que la app sea instalable (PWA).
// IMPORTANTE: solo gestiona /static/ (íconos, logos, JS). Las páginas (HTML)
// van directo a la red por el navegador, así una página NUNCA queda en blanco
// si el SW falla o no hay caché (bug anterior: devolvía undefined sin red).
const CACHE = 'polla-2026-v3';

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

  let url;
  try { url = new URL(e.request.url); } catch (_) { return; }

  // Solo interceptar recursos estáticos. Todo lo demás (navegación, páginas)
  // lo maneja el navegador normalmente -> nunca pantalla en blanco.
  if (url.pathname.indexOf('/static/') === -1) return;

  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return resp;
      })
      .catch(() => caches.match(e.request))
  );
});
