/* FairBon service worker — offline shell, API stays network-only. */
var CACHE = "fairbon-v28";
var SHELL = [
  "./",
  "./css/styles.css",
  "./js/state.js",
  "./js/api.js",
  "./js/platform.js",
  "./js/views/prices.js",
  "./js/views/list.js",
  "./js/views/overview.js",
  "./js/views/receipts.js",
  "./js/demo-receipt.js",
  "./js/components/scan-progress.js",
  "./js/components/add-sheet.js",
  "./js/app.js",
  "./icons/favicon.ico",
  "./fonts/inter-variable.woff2",
  "./fonts/outfit-variable.woff2",
  "./manifest.webmanifest"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      // cache: "reload" bypasses the HTTP cache so a new worker always
      // stores the freshly deployed files, never a stale copy.
      return cache.addAll(SHELL.map(function (url) {
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
  if (event.request.method !== "GET" || url.pathname.indexOf("/api/") === 0) {
    return; // never cache API responses
  }
  event.respondWith(
    caches.match(event.request).then(function (cached) {
      return cached || fetch(event.request).then(function (response) {
        var copy = response.clone();
        caches.open(CACHE).then(function (cache) { cache.put(event.request, copy); });
        return response;
      }).catch(function () {
        return caches.match("./");
      });
    })
  );
});
