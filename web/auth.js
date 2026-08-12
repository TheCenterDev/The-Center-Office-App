/* Login + per-account settings sync for the mobile site, backed by
 * Firebase Authentication (who can sign in) and Firestore (everyone's
 * name/role/preferences, one document per person keyed by their
 * lowercased email -- same key the desktop app's users.json already
 * uses, so the two stay conceptually in sync even though they don't
 * share a live connection).
 *
 * Account creation is deliberately NOT self-service: there is no
 * sign-up form anywhere in this app. A brand new staff member gets
 * access in two manual steps done by an existing Admin/Director:
 *   1. Firebase console -> Authentication -> Add user (email + a
 *      temporary password) -- this is what lets them sign in at all.
 *   2. This app's Team page (Settings -> Team, admin/director only)
 *      -> Add person -- this is what gives them a name/role/
 *      preferences record, without which they can sign in but the app
 *      has no idea who they are or what they're allowed to see.
 * See README.md's "Mobile / web access" section for the full writeup.
 *
 * Exposes a single global, window.CenterAuth, that web/app.js drives.
 */
(function () {
  "use strict";

  if (!window.firebase || !window.FIREBASE_CONFIG) {
    console.error("Firebase SDK or config missing -- auth.js cannot run.");
    return;
  }

  firebase.initializeApp(window.FIREBASE_CONFIG);
  var auth = firebase.auth();
  var db = firebase.firestore();

  var PERSONAL_SETTING_KEYS = ["theme", "font_scale", "default_page", "sidebar_expanded"];
  var DEFAULT_PREFERENCES = {
    theme: "light",
    font_scale: "normal",
    default_page: "home",
    sidebar_expanded: true,
  };
  var ROLES = ["staff", "admin", "director"];

  var readyCallbacks = [];
  var current = null; // { user, profile } or null when signed out
  var profileUnsub = null;

  function emailKey(email) {
    return String(email || "").trim().toLowerCase();
  }

  function isAdminOrDirector(profile) {
    return !!profile && (profile.role === "admin" || profile.role === "director");
  }

  function notifyReady() {
    readyCallbacks.forEach(function (cb) {
      try { cb(current); } catch (e) { console.error(e); }
    });
  }

  function watchProfile(user) {
    if (profileUnsub) { profileUnsub(); profileUnsub = null; }
    var key = emailKey(user.email);
    profileUnsub = db.collection("users").doc(key).onSnapshot(
      function (snap) {
        var data = snap.exists ? snap.data() : null;
        var profile = data
          ? Object.assign({ email: key, name: data.name || user.email, role: data.role || "staff" },
              { preferences: Object.assign({}, DEFAULT_PREFERENCES, data.preferences || {}) })
          : null;
        current = { user: user, profile: profile };
        notifyReady();
      },
      function (err) {
        console.error("Profile listener failed:", err);
        current = { user: user, profile: null };
        notifyReady();
      }
    );
  }

  auth.onAuthStateChanged(function (user) {
    if (user) {
      watchProfile(user);
    } else {
      if (profileUnsub) { profileUnsub(); profileUnsub = null; }
      current = null;
      notifyReady();
    }
  });

  var CenterAuth = {
    ROLES: ROLES,
    PERSONAL_SETTING_KEYS: PERSONAL_SETTING_KEYS,

    /** cb(state) fires immediately with the current state, then again
     * every time auth or the signed-in user's own profile changes.
     * state is null when signed out, otherwise { user, profile }
     * (profile is null if no Firestore users/{email} doc exists yet --
     * i.e. step 2 above hasn't happened for this account). */
    onReady: function (cb) {
      readyCallbacks.push(cb);
      cb(current);
    },

    signIn: function (email, password) {
      return auth.signInWithEmailAndPassword(String(email).trim(), password);
    },

    signOut: function () {
      return auth.signOut();
    },

    sendPasswordReset: function (email) {
      return auth.sendPasswordResetEmail(String(email).trim());
    },

    isAdminOrDirector: isAdminOrDirector,

    /** Merge a partial preferences object into the signed-in user's own
     * profile. Firestore syncs this to every other device/tab that has
     * this app open in real time via the onSnapshot listener above. */
    updatePreferences: function (partial) {
      if (!current || !current.user) return Promise.reject(new Error("Not signed in"));
      var key = emailKey(current.user.email);
      var next = {};
      Object.keys(partial || {}).forEach(function (k) {
        if (PERSONAL_SETTING_KEYS.indexOf(k) !== -1) next["preferences." + k] = partial[k];
      });
      if (Object.keys(next).length === 0) return Promise.resolve();
      return db.collection("users").doc(key).set(
        Object.fromEntries(Object.entries(next).map(function (pair) { return pair; })),
        { merge: true }
      ).catch(function () {
        // Fallback for older browsers without Object.fromEntries.
        var nested = { preferences: {} };
        Object.keys(partial).forEach(function (k) {
          if (PERSONAL_SETTING_KEYS.indexOf(k) !== -1) nested.preferences[k] = partial[k];
        });
        return db.collection("users").doc(key).set(nested, { merge: true });
      });
    },

    /** Admin/Director only (also enforced server-side by
     * firestore.rules -- this check is just so the UI can hide/disable
     * things sensibly). Lists every profile for the Team page. */
    listUsers: function () {
      return db.collection("users").orderBy("name").get().then(function (snap) {
        var out = [];
        snap.forEach(function (doc) {
          var data = doc.data();
          out.push({ email: doc.id, name: data.name || doc.id, role: data.role || "staff" });
        });
        return out;
      });
    },

    /** Admin/Director only. Creates or updates a person's app profile
     * (name + role). Does NOT create their Firebase Auth login -- that
     * still has to be done once via the Firebase console (step 1
     * above); this only controls what the app knows about them. */
    upsertUser: function (email, fields) {
      var key = emailKey(email);
      var payload = {};
      if (fields.name !== undefined) payload.name = fields.name;
      if (fields.role !== undefined) payload.role = fields.role;
      return db.collection("users").doc(key).set(payload, { merge: true });
    },

    deleteUser: function (email) {
      return db.collection("users").doc(emailKey(email)).delete();
    },
  };

  window.CenterAuth = CenterAuth;
})();
