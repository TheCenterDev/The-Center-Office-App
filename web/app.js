/* The Center — Office Tools (mobile web)
 *
 * Gated behind Firebase sign-in (see auth.js) -- nothing below renders
 * until CenterAuth reports a signed-in user with a Firestore profile.
 * Once signed in: fetches guides-index.json (generated at build time
 * by scripts/build_site.py from the same html/ folder the desktop app
 * reads) and renders a sidebar + document viewer. Guide content is
 * shown in a same-origin <iframe> pointed at the mirrored copy under
 * ./html/ -- same-origin means we can read the iframe's own
 * scrollHeight to auto-size it, and it renders the guide's real
 * HTML/CSS exactly as authored, no custom parser needed.
 */

(function () {
  "use strict";

  var FONT_SCALES = { small: 0.9, normal: 1.0, large: 1.15, xlarge: 1.3 };
  var THEME_LABELS = { light: "Light", dark: "Dark", eye_comfort: "Eye Comfort", system: "System" };
  var FONT_LABELS = { small: "Small", normal: "Normal", large: "Large", xlarge: "Extra Large" };

  var state = {
    docs: [],       // [{file, title, isProgram, hidden, text}]
    activeFile: null,
    homeFile: null,
    view: "doc",    // "doc" | "settings" | "team"
    profile: null,
    appStarted: false,
  };

  var els = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els.loginScreen = document.getElementById("login-screen");
    els.loginForm = document.getElementById("login-form");
    els.loginEmail = document.getElementById("login-email");
    els.loginPassword = document.getElementById("login-password");
    els.loginError = document.getElementById("login-error");
    els.loginForgot = document.getElementById("login-forgot");
    els.loginSubmit = document.getElementById("login-submit");

    els.app = document.getElementById("app");
    els.sidebar = document.getElementById("sidebar");
    els.scrim = document.getElementById("sidebar-scrim");
    els.hamburger = document.getElementById("hamburger");
    els.navList = document.getElementById("nav-list");
    els.searchInput = document.getElementById("search-input");
    els.contentFrame = document.getElementById("content-frame");
    els.loading = document.getElementById("loading");
    els.emptyState = document.getElementById("empty-state");
    els.settingsView = document.getElementById("settings-view");
    els.teamView = document.getElementById("team-view");
    els.topbarTitle = document.getElementById("topbar-title");
    els.footerUserName = document.getElementById("footer-user-name");
    els.settingsNavBtn = document.getElementById("settings-nav-btn");
    els.teamNavBtn = document.getElementById("team-nav-btn");

    els.hamburger.addEventListener("click", function () { toggleSidebar(true); });
    els.scrim.addEventListener("click", function () { toggleSidebar(false); });
    els.searchInput.addEventListener("input", function () { renderNav(els.searchInput.value); });
    window.addEventListener("hashchange", routeFromHash);

    els.loginForm.addEventListener("submit", handleLoginSubmit);
    els.loginForgot.addEventListener("click", handleForgotPassword);
    els.settingsNavBtn.addEventListener("click", function () { toggleSidebar(false); showSettings(); });
    els.teamNavBtn.addEventListener("click", function () { toggleSidebar(false); showTeam(); });

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("./sw.js").catch(function () {
        /* offline install just won't work this session -- not fatal */
      });
    }

    if (window.CenterAuth) {
      window.CenterAuth.onReady(handleAuthState);
    } else {
      els.loginError.textContent = "Couldn't load sign-in. Check your connection and reload.";
    }
  }

  // ------------------------------------------------------------- auth --

  function handleAuthState(authState) {
    if (!authState || !authState.user) {
      state.appStarted = false;
      els.loginScreen.classList.remove("hidden");
      els.app.classList.add("hidden");
      return;
    }

    if (!authState.profile) {
      // Signed in to Firebase, but no Firestore users/{email} profile
      // yet -- an Admin/Director hasn't set them up in the Team page.
      els.loginScreen.classList.remove("hidden");
      els.app.classList.add("hidden");
      els.loginError.textContent =
        "Your login works, but you don't have a profile yet. Ask an Admin or Director to add you on the Team page.";
      return;
    }

    els.loginScreen.classList.add("hidden");
    els.app.classList.remove("hidden");
    els.loginError.textContent = "";

    state.profile = authState.profile;
    applyProfile(authState.profile);

    if (!state.appStarted) {
      state.appStarted = true;
      startApp();
    } else if (state.view === "settings") {
      renderSettingsView(); // re-render so a change made on another device shows up live
    }
  }

  function applyProfile(profile) {
    var prefs = profile.preferences || {};
    var theme = prefs.theme || "light";
    if (theme === "system") {
      theme = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
    }
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.setProperty("--font-scale", FONT_SCALES[prefs.font_scale] || 1);
    els.footerUserName.textContent = profile.name || profile.email;
    var canManageTeam = window.CenterAuth.isAdminOrDirector(profile);
    els.teamNavBtn.style.display = canManageTeam ? "" : "none";
  }

  function handleLoginSubmit(e) {
    e.preventDefault();
    els.loginError.textContent = "";
    els.loginSubmit.disabled = true;
    els.loginSubmit.textContent = "Signing in…";
    window.CenterAuth.signIn(els.loginEmail.value, els.loginPassword.value)
      .then(function () {
        // Force an immediate re-check of the current state rather than
        // waiting on the profile listener to fire again -- signing in
        // again while already signed in as the same account resolves
        // right away without necessarily producing a fresh listener
        // event, which used to leave the screen looking stuck with no
        // visible feedback at all.
        handleAuthState(window.CenterAuth.getState());
      })
      .catch(function (err) {
        els.loginError.textContent = friendlyAuthError(err);
      })
      .then(function () {
        els.loginSubmit.disabled = false;
        els.loginSubmit.textContent = "Sign in";
      });
  }

  function handleForgotPassword() {
    var email = els.loginEmail.value.trim();
    if (!email) {
      els.loginError.textContent = "Enter your email above first, then tap Forgot password?.";
      return;
    }
    window.CenterAuth.sendPasswordReset(email)
      .then(function () {
        els.loginError.textContent = "Password reset email sent to " + email + ".";
      })
      .catch(function (err) {
        els.loginError.textContent = friendlyAuthError(err);
      });
  }

  function friendlyAuthError(err) {
    var code = err && err.code;
    if (code === "auth/invalid-email") return "That email address doesn't look right.";
    if (code === "auth/user-not-found" || code === "auth/wrong-password" || code === "auth/invalid-credential") {
      return "Email or password is incorrect.";
    }
    if (code === "auth/too-many-requests") return "Too many attempts. Wait a bit and try again.";
    return (err && err.message) || "Something went wrong signing in.";
  }

  // ------------------------------------------------------------- app --

  function startApp() {
    fetch("./guides-index.json", { cache: "no-cache" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state.docs = data.docs || [];
        state.homeFile = data.homeFile || null;
        renderNav("");
        routeFromHash();
      })
      .catch(function (err) {
        showPanel("empty");
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

    var homeBtn = makeNavButton("Home", null, false, state.view === "doc" && state.activeFile === null);
    els.navList.appendChild(homeBtn);

    var docs = visibleDocs();
    if (q) {
      docs = docs.filter(function (d) {
        return d.title.toLowerCase().indexOf(q) !== -1 ||
          (d.text || "").toLowerCase().indexOf(q) !== -1;
      });
    }

    docs.forEach(function (d) {
      var btn = makeNavButton(d.title, d.file, d.isProgram, state.view === "doc" && state.activeFile === d.file);
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

  function showPanel(which) {
    // which is "loading" | "empty" | "frame" | "settings" | "team"
    els.loading.style.display = which === "loading" ? "block" : "none";
    els.emptyState.style.display = which === "empty" ? "block" : "none";
    els.contentFrame.style.display = which === "frame" ? "block" : "none";
    els.settingsView.style.display = which === "settings" ? "block" : "none";
    els.teamView.style.display = which === "team" ? "block" : "none";
  }

  function showHome() {
    state.view = "doc";
    state.activeFile = null;
    els.topbarTitle.textContent = "The Center";
    renderNav(els.searchInput.value);
    if (state.homeFile) {
      loadIframe(state.homeFile);
    } else {
      showPanel("empty");
      els.emptyState.textContent = "No Home page found.";
    }
  }

  function showDoc(file, title) {
    state.view = "doc";
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
    showPanel("loading");

    var frame = els.contentFrame;
    frame.onload = function () {
      showPanel("frame");
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

  // --------------------------------------------------------- settings --

  function showSettings() {
    state.view = "settings";
    els.topbarTitle.textContent = "Settings";
    renderNav(els.searchInput.value);
    showPanel("settings");
    renderSettingsView();
  }

  function renderSettingsView() {
    var profile = state.profile;
    if (!profile) return;
    var prefs = profile.preferences || {};

    els.settingsView.innerHTML = "";

    var account = section("Account");
    account.appendChild(row(labelSpan(profile.name), labelSpan(profile.email, true)));
    account.appendChild(row(labelSpan("Role"), labelSpan(capitalize(profile.role))));
    els.settingsView.appendChild(account);

    var appearance = section("Appearance");
    appearance.appendChild(row(
      labelSpan("Theme"),
      select(["light", "dark", "eye_comfort", "system"], THEME_LABELS, prefs.theme || "light", function (v) {
        window.CenterAuth.updatePreferences({ theme: v });
      })
    ));
    appearance.appendChild(row(
      labelSpan("Text size"),
      select(["small", "normal", "large", "xlarge"], FONT_LABELS, prefs.font_scale || "normal", function (v) {
        window.CenterAuth.updatePreferences({ font_scale: v });
      })
    ));
    els.settingsView.appendChild(appearance);

    var account2 = section("");
    var signOutBtn = document.createElement("button");
    signOutBtn.type = "button";
    signOutBtn.className = "btn btn-danger";
    signOutBtn.style.width = "100%";
    signOutBtn.textContent = "Sign out";
    signOutBtn.addEventListener("click", function () {
      window.CenterAuth.signOut().then(function () { window.location.reload(); });
    });
    account2.appendChild(signOutBtn);
    els.settingsView.appendChild(account2);
  }

  // ------------------------------------------------------------- team --

  function showTeam() {
    state.view = "team";
    els.topbarTitle.textContent = "Team";
    renderNav(els.searchInput.value);
    showPanel("team");
    renderTeamView();
  }

  function renderTeamView() {
    els.teamView.innerHTML = "";
    var listSection = section("Team");
    var list = document.createElement("ul");
    list.className = "team-list";
    listSection.appendChild(list);
    els.teamView.appendChild(listSection);

    var addSection = section("Add or update a person");
    var noteP = document.createElement("p");
    noteP.className = "login-help";
    noteP.style.margin = "0 0 12px";
    noteP.textContent = "This sets their name and role in the app. It does not create their sign-in -- do that once in the Firebase console (Authentication → Add user) first.";
    addSection.appendChild(noteP);

    var emailInput = document.createElement("input");
    emailInput.type = "email";
    emailInput.placeholder = "name@thecentercc.com";
    emailInput.style.width = "100%";
    emailInput.style.marginBottom = "8px";

    var nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.placeholder = "Full name";
    nameInput.style.width = "100%";
    nameInput.style.marginBottom = "8px";

    var roleSelectEl = select(
      window.CenterAuth.ROLES, { staff: "Staff", admin: "Admin", director: "Director" }, "staff", null
    );
    roleSelectEl.style.width = "100%";
    roleSelectEl.style.marginBottom = "12px";

    [emailInput, nameInput, roleSelectEl].forEach(function (el) { addSection.appendChild(el); });

    var statusP = document.createElement("p");
    statusP.className = "login-help";
    statusP.style.margin = "8px 0 0";
    addSection.appendChild(statusP);

    var saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "btn btn-primary";
    saveBtn.style.width = "100%";
    saveBtn.textContent = "Save";
    saveBtn.addEventListener("click", function () {
      var email = emailInput.value.trim();
      var name = nameInput.value.trim();
      if (!email || !name) {
        statusP.textContent = "Enter both an email and a name.";
        return;
      }
      window.CenterAuth.upsertUser(email, { name: name, role: roleSelectEl.value })
        .then(function () {
          statusP.textContent = "Saved.";
          emailInput.value = "";
          nameInput.value = "";
          loadTeamList(list);
        })
        .catch(function (err) {
          statusP.textContent = (err && err.message) || "Couldn't save.";
        });
    });
    addSection.appendChild(saveBtn);
    els.teamView.appendChild(addSection);

    loadTeamList(list);
  }

  function loadTeamList(list) {
    list.innerHTML = "<li>Loading…</li>";
    window.CenterAuth.listUsers()
      .then(function (users) {
        list.innerHTML = "";
        if (users.length === 0) {
          list.innerHTML = "<li>No one's been added yet.</li>";
          return;
        }
        users.forEach(function (u) {
          var li = document.createElement("li");
          var nameSpan = document.createElement("span");
          nameSpan.textContent = u.name + " — " + u.email;
          var roleSpan = document.createElement("span");
          roleSpan.className = "team-role";
          roleSpan.textContent = u.role;
          li.appendChild(nameSpan);
          li.appendChild(roleSpan);
          list.appendChild(li);
        });
      })
      .catch(function (err) {
        list.innerHTML = "<li>Couldn't load the team list: " + escapeHtml((err && err.message) || "") + "</li>";
      });
  }

  // ------------------------------------------------------------ helpers --

  function section(title) {
    var div = document.createElement("div");
    div.className = "panel-section";
    if (title) {
      var h2 = document.createElement("h2");
      h2.textContent = title;
      div.appendChild(h2);
    }
    return div;
  }

  function row(a, b) {
    var div = document.createElement("div");
    div.className = "panel-row";
    div.appendChild(a);
    if (b) div.appendChild(b);
    return div;
  }

  function labelSpan(text, muted) {
    var span = document.createElement("span");
    if (muted) span.style.color = "var(--text-muted)";
    span.textContent = text;
    return span;
  }

  function select(values, labels, current, onChange) {
    var sel = document.createElement("select");
    values.forEach(function (v) {
      var opt = document.createElement("option");
      opt.value = v;
      opt.textContent = labels[v] || v;
      if (v === current) opt.selected = true;
      sel.appendChild(opt);
    });
    if (onChange) {
      sel.addEventListener("change", function () { onChange(sel.value); });
    }
    return sel;
  }

  function capitalize(s) {
    s = String(s || "");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }
})();
