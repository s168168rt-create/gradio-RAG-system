/* Service Worker — 由 FastAPI 以 /sw.js 提供（scope 必須是根路徑）
 *
 * 策略：
 *  - 頁面導覽：一律走網路（Gradio 的首頁內含每個 session 的設定，不可快取）；
 *    離線時回退 /offline.html。
 *  - /assets/（Gradio 前端，檔名含 hash）：cache-first。
 *  - /pwa/*、/manifest.webmanifest：stale-while-revalidate。
 *  - 其餘（含 /gradio_api/ 的 API、SSE 串流、上傳）一律不攔截，保證問答功能不受快取影響。
 */
const VERSION = 'v1';
const SHELL = `rag-shell-${VERSION}`;
const ASSETS = `rag-assets-${VERSION}`;
const PRECACHE = [
  '/offline.html',
  '/manifest.webmanifest',
  '/pwa/pwa.js',
  '/pwa/icons/icon-192.png',
  '/pwa/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => ![SHELL, ASSETS].includes(k)).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

async function cacheFirst(request) {
  const cache = await caches.open(ASSETS);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res.ok && res.type === 'basic') cache.put(request, res.clone());
  return res;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(request);
  const net = fetch(request)
    .then((res) => { if (res.ok) cache.put(request, res.clone()); return res; })
    .catch(() => hit);
  return hit || net;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(async () => (await caches.match('/offline.html')) || Response.error())
    );
    return;
  }
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(cacheFirst(request));
    return;
  }
  if (url.pathname.startsWith('/pwa/') || url.pathname === '/manifest.webmanifest') {
    event.respondWith(staleWhileRevalidate(request));
  }
});
