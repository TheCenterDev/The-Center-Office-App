/* Minimal service worker: makes the app installable and usable offline
 * for content already visited. __BUILD_ID__ is replaced by
 * scripts/build_site.py with the build timestamp on every deploy, so
 * each new push gets a fresh cache name and old shell files don't get
 * stuck being served forever. */

var CACHE_NAME = "center-office-shell-__BUILD_ID__";
var SHELL_FILES = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./manifest.json",
  "./guides-index.json",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(SHELL_FILES);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names
          .filter(function (name) { return name !== CACHE_NAME; })
          .map(function (name) { return caches.delete(name); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  var req = event.request;
  if (req.method !== "GET") return;

  var url = new URL(req.url);
  var isGuideContent = url.pathname.indexOf("/html/") !== -1 || url.pathname.endsWith("guides-index.json");

  if (isGuideContent) {
    // Network-first: guide/contact content should reflect the latest
    // push to the GitHub repo whenever the phone is online; only fall
    // back to the cached copy when offline.
    event.respondWith(
      fetch(req)
        .then(function (res) {
          var copy = res.clone();
          caches.open(CACHE_NAME).then(function (cache) { cache.put(req, copy); });
          return res;
        })
        .catch(function () { return caches.match(req); })
    );
    return;
  }

  // Cache-first for the app shell itself (rarely changes).
  event.respondWith(
    caches.match(req).then(function (cached) {
      return cached || fetch(req);
    })
  );
});
