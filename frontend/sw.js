/* FairBon service worker — offline shell only.
   Protected pages, API responses and arbitrary GETs are never cached. */
var CACHE = "fairbon-v52";

/* Only these exact, public static assets may be stored in the shell cache. */
var CACHE_ONLY_ASSETS = [
  "/",
  "/css/styles.css",
  "/js/state.js",
  "/js/api.js",
  "/js/platform.js",
  "/js/views/prices.js",
  "/js/views/list.js",
  "/js/views/overview.js",
  "/js/views/receipts.js",
  "/js/demo-receipt.js",
  "/js/components/scan-progress.js",
  "/js/components/add-sheet.js",
  "/js/app.js",
  "/js/legal-theme.js",
  "/icons/favicon.ico",
  "/icons/icon-192.png",
  "/fonts/inter-variable.woff2",
  "/fonts/outfit-variable.woff2",
  "/manifest.webmanifest"
];

/* Paths that must never be cached or served by the worker. */
var NO_CACHE_PATHS = [
  "/admin",
  "/login",
  "/logout",
  "/impressum",
  "/datenschutz",
  "/health"
];

function bypassesCache(url) {
  if (url.pathname.indexOf("/api/") === 0) { return true; }
  for (var i = 0; i < NO_CACHE_PATHS.length; i += 1) {
    var path = NO_CACHE_PATHS[i];
    if (url.pathname === path || url.pathname.indexOf(path + "/") === 0) {
      return true;
    }
  }
  return false;
}

function isShellAsset(pathname) {
  return CACHE_ONLY_ASSETS.indexOf(pathname) >= 0;
}

function mayCache(response) {
  if (!response || !response.ok || response.type !== "basic") { return false; }
  var control = response.headers.get("cache-control") || "";
  return control.indexOf("no-store") < 0 && control.indexOf("no-cache") < 0;
}

function remember(request, response) {
  if (!mayCache(response)) { return; }
  var copy = response.clone();
  caches.open(CACHE).then(function (cache) { cache.put(request, copy); });
}

/* Navigations and the app shell: always prefer the network so a fresh deploy
   or a changed login state is visible immediately; offline falls back. */
function networkFirst(event) {
  return fetch(event.request).then(function (response) {
    remember(event.request, response);
    return response;
  }).catch(function () {
    return caches.match(event.request).then(function (cached) {
      return cached || caches.match("/");
    });
  });
}

/* Explicit static assets may be served from the cache (fast offline shell). */
function cacheFirst(event) {
  return caches.match(event.request).then(function (cached) {
    if (cached) { return cached; }
    return fetch(event.request).then(function (response) {
      remember(event.request, response);
      return response;
    }).catch(function () { return caches.match("/"); });
  });
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(CACHE_ONLY_ASSETS.map(function (url) {
        try { return new Request(url, { cache: "reload" }); }
        catch (e) { return url; }
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (key) {
        return key !== CACHE;
      }).map(function (key) { return caches.delete(key); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);
  if (event.request.method !== "GET" || bypassesCache(url)) {
    return;
  }
  var navigation = event.request.mode === "navigate" || url.pathname === "/";
  if (navigation) {
    event.respondWith(networkFirst(event));
  } else if (isShellAsset(url.pathname)) {
    event.respondWith(cacheFirst(event));
  }
  // Every other GET goes straight to the network, uncached.
});
