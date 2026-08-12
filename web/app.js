/* The Center — Office Tools (mobile web)
 *
 * Fetches guides-index.json (generated at build time by
 * scripts/build_site.py from the same html/ folder the desktop app
 * reads) and renders a sidebar + document viewer. Guide content is
 * shown in a same-origin <iframe> pointed at the mirrored copy under
 * ./html/ -- same-origin means we can read the iframe's own
 * scrollHeight to auto-size it, and it renders the guide's real
 * HTML/CSS exactly as authored, no custom parser needed.
 */

(function () {
  "use strict";

  var state = {
    docs: [],       // [{file, title, isProgram, hidden, text}]
    activeFile: null,
    homeFile: null,
  };

  var els = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els.sidebar = document.getElementById("sidebar");
    els.scrim = document.getElementById("sidebar-scrim");
    els.hamburger = document.getElementById("hamburger");
    els.navList = document.getElementById("nav-list");
    els.searchInput = document.getElementById("search-input");
    els.contentFrame = document.getElementById("content-frame");
    els.loading = document.getElementById("loading");
    els.emptyState = document.getElementById("empty-state");
    els.topbarTitle = document.getElementById("topbar-title");
    els.contentScroll = document.getElementById("content-scroll");

    els.hamburger.addEventListener("click", function () { toggleSidebar(true); });
    els.scrim.addEventListener("click", function () { toggleSidebar(false); });
    els.searchInput.addEventListener("input", function () { renderNav(els.searchInput.value); });

    window.addEventListener("hashchange", routeFromHash);

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("./sw.js").catch(function () {
        /* offline install just won't work this session -- not fatal */
      });
    }

    fetch("./guides-index.json", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state.docs = data.docs || [];
        state.homeFile = data.homeFile || null;
        renderNav("");
        routeFromHash();
      })
      .catch(function (err) {
        els.emptyState.style.display = "block";
        els.emptyState.textContent = "Couldn't load the guide list. Check your connection and reload.";
        console.error(err);
      });
  }

  function toggleSidebar(open) {
    els.sidebar.classList.toggle("open", open);
    els.scrim.classList.toggle("open", open);
  }

  function visibleDocs() {
    return state.docs.filter(function (d) { return !d.hidden; });
  }

  function renderNav(query) {
    var q = (query || "").trim().toLowerCase();
    els.navList.innerHTML = "";

    var homeBtn = makeNavButton("Home", null, false, state.activeFile === null);
    els.navList.appendChild(homeBtn);

    var docs = visibleDocs();
    if (q) {
      docs = docs.filter(function (d) {
        return d.title.toLowerCase().indexOf(q) !== -1 ||
          (d.text || "").toLowerCase().indexOf(q) !== -1;
      });
    }

    docs.forEach(function (d) {
      var btn = makeNavButton(d.title, d.file, d.isProgram, state.activeFile === d.file);
      els.navList.appendChild(btn);
    });

    if (q && docs.length === 0) {
      var none = document.createElement("div");
      none.className = "badge";
      none.style.padding = "10px 12px";
      none.textContent = "No matches.";
      els.navList.appendChild(none);
    }
  }

  function makeNavButton(title, file, isProgram, active) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "nav-item" + (active ? " active" : "");
    btn.setAttribute("role", "listitem");

    var label = document.createElement("span");
    label.textContent = title;
    btn.appendChild(label);

    if (isProgram) {
      var badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "APP ↗";
      btn.appendChild(badge);
    }

    btn.addEventListener("click", function () {
      toggleSidebar(false);
      if (file === null) {
        window.location.hash = "";
      } else if (isProgram) {
        // Interactive tools navigate the whole page, synchronously,
        // inside this same click handler -- not via the hashchange
        // listener below. Browsers (especially on phones, and inside
        // an installed standalone PWA) block window.open() unless it
        // happens directly inside a user gesture; routing it through
        // an async hashchange event lost that gesture, which is why
        // these tools didn't open at all. A plain same-tab navigation
        // has no such restriction and works the same installed or not.
        openProgram(doc_for(file));
      } else {
        window.location.hash = "#/" + encodeURIComponent(file);
      }
    });
    return btn;
  }

  function doc_for(file) {
    return state.docs.filter(function (d) { return d.file === file; })[0];
  }

  function routeFromHash() {
    var hash = window.location.hash;
    if (!hash || hash === "#" || hash === "#/") {
      showHome();
      return;
    }
    var match = hash.match(/^#\/(.+)$/);
    if (!match) { showHome(); return; }
    var file = decodeURIComponent(match[1]);
    var doc = doc_for(file);
    if (!doc) { showHome(); return; }
    if (doc.isProgram) {
      // Only reached via a direct/bookmarked link to a tool's hash --
      // normal clicks never set this hash to begin with (see above).
      openProgram(doc);
    } else {
      showDoc(doc.file, doc.title);
    }
  }

  function showHome() {
    state.activeFile = null;
    els.topbarTitle.textContent = "The Center";
    renderNav(els.searchInput.value);
    if (state.homeFile) {
      loadIframe(state.homeFile);
    } else {
      els.emptyState.style.display = "block";
      els.emptyState.textContent = "No Home page found.";
    }
  }

  function showDoc(file, title) {
    state.activeFile = file;
    els.topbarTitle.textContent = title;
    renderNav(els.searchInput.value);
    loadIframe(file);
  }

  function openProgram(doc) {
    // Same-tab navigation, not window.open(): a new tab/window has
    // nowhere to go when the site is installed as a standalone
    // home-screen app (there's no browser chrome to hold it), and even
    // in a regular mobile browser tab, window.open() outside a direct
    // synchronous user gesture is routinely popup-blocked. Each tool
    // page gets a "Back to Center Tools" link injected at build time
    // (see scripts/build_site.py) so there's still a way back.
    window.location.href = "./html/" + encodeURIComponent(doc.file);
  }

  function loadIframe(file) {
    els.emptyState.style.display = "none";
    els.loading.style.display = "block";
    els.contentFrame.style.display = "none";

    var frame = els.contentFrame;
    frame.onload = function () {
      els.loading.style.display = "none";
      frame.style.display = "block";
      try {
        var doc = frame.contentDocument;
        resizeFrameToContent(frame, doc);
        interceptFrameNavigation(frame, doc);
        // Re-measure after images/fonts settle.
        setTimeout(function () { resizeFrameToContent(frame, doc); }, 300);
      } catch (e) {
        // Cross-origin or otherwise inaccessible -- leave a sensible
        // default height rather than failing silently.
        frame.style.height = "80vh";
      }
    };
    frame.src = "./html/" + encodeURIComponent(file);
  }

  function resizeFrameToContent(frame, doc) {
    var body = doc && doc.body;
    var html = doc && doc.documentElement;
    if (!body || !html) return;
    var height = Math.max(body.scrollHeight, html.scrollHeight, 200);
    frame.style.height = height + "px";
  }

  function interceptFrameNavigation(frame, doc) {
    if (!doc) return;
    var links = doc.querySelectorAll("a[href]");
    links.forEach(function (a) {
      var href = a.getAttribute("href");
      if (!href) return;
      // http(s) links open in a new tab so the app itself (and its
      // scroll position / nav state) stays put underneath. mailto:
      // links are left alone -- the OS/browser already routes those to
      // whatever mail app or chooser the phone has configured, which is
      // the normal mobile convention (no need to force Gmail's compose
      // URL the way the desktop app does).
      if (href.indexOf("http://") === 0 || href.indexOf("https://") === 0) {
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener");
      }
    });
  }
})();
