const CACHE_NAME = "cat-feeder-v1";
const CORE_ASSETS = [
  "/",
  "/screen",
  "/screen/status",
  "/screen/pets",
  "/manifest.webmanifest",
  "/assets/tuxedo-cat.png",
  "/apple-touch-icon.png"
];

const OFFLINE_HTML = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Offline</title>
    <style>
      body {
        margin: 0;
        font-family: "Optima", "Gill Sans", "Candara", sans-serif;
        background: #f8f2e9;
        color: #1f1b16;
      }
      .shell {
        max-width: 520px;
        margin: 0 auto;
        padding: 2.5rem 1.2rem;
      }
      .card {
        background: #fffdf9;
        border-radius: 18px;
        padding: 1.4rem;
        border: 1px solid #e4d3c3;
        box-shadow: 0 12px 28px rgba(40, 30, 24, 0.16);
      }
      h1 { margin-top: 0; }
      a {
        display: inline-block;
        margin-top: 0.8rem;
        padding: 0.5rem 0.9rem;
        border-radius: 999px;
        border: 1px solid #e4d3c3;
        background: #fffaf4;
        color: #1f1b16;
        text-decoration: none;
        font-weight: 600;
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="card">
        <h1>You are offline</h1>
        <p>The cat feeder dashboard is cached, but updates need a connection.</p>
        <a href="/screen">Back to dashboard</a>
      </div>
    </div>
  </body>
</html>`;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(CORE_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

function cacheFirst(request) {
  return caches.match(request).then((cached) => {
    if (cached) {
      return cached;
    }
    return fetch(request).then((response) => {
      if (response && response.status === 200) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
      }
      return response;
    });
  });
}

function networkFirst(request) {
  return fetch(request)
    .then((response) => {
      if (response && response.status === 200) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
      }
      return response;
    })
    .catch(() =>
      caches.match(request).then((cached) => {
        if (cached) {
          return cached;
        }
        if (request.headers.get("accept")?.includes("text/html")) {
          return new Response(OFFLINE_HTML, {
            headers: { "Content-Type": "text/html; charset=utf-8" }
          });
        }
        return new Response("", { status: 503, statusText: "Offline" });
      })
    );
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
    return;
  }
  if (
    url.pathname.startsWith("/assets/") ||
    url.pathname.endsWith(".png") ||
    url.pathname.endsWith(".webmanifest")
  ) {
    event.respondWith(cacheFirst(request));
    return;
  }
  event.respondWith(networkFirst(request));
});
