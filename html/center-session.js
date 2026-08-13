/* Shared sign-in + database layer for the interactive tools.
 *
 * The problem this solves: the tools are web pages, but the desktop
 * launcher is a Python app. Signing into the launcher told the pages
 * nothing, so every tool asked for a password again even though you'd
 * just logged in.
 *
 * Now the launcher hands its session to the page when it opens it (see
 * _open_program / run_webview_window in launcher.py). The page picks it
 * up and never shows a login at all. On the mobile site there's no
 * launcher, so the page falls back to the normal Firebase sign-in --
 * and because that shares the browser session with the rest of the
 * site, signing into the site already covers the tools too.
 *
 * Either way the tools end up with the same thing: an ID token they can
 * use to read and write the shared database, with firestore.rules
 * applying exactly the permissions that person's account has.
 *
 * Live updates are done by polling every few seconds rather than
 * Firestore's instant listeners. The listeners are part of the Firebase
 * SDK's own auth session, which a handed-over token isn't part of. In
 * exchange for one sign-in instead of two, a change made elsewhere
 * shows up a few seconds later rather than instantly -- for a
 * maintenance list and an onboarding checklist that's a fair trade.
 */
(function () {
  "use strict";

  var API_KEY = "AIzaSyB2rLNc8NaBcWzk_kCyhulEIseXeMbNZEg";
  var PROJECT_ID = "the-center-office-app";
  var FIRESTORE =
    "https://firestore.googleapis.com/v1/projects/" + PROJECT_ID +
    "/databases/(default)/documents";

  var POLL_MS = 5000;

  var handedOver = null;      // session passed in by the desktop launcher
  var cachedToken = "";
  var cachedTokenExpiry = 0;

  // ------------------------------------------------- session handover --

  function readHandover() {
    // The launcher puts the session in the URL fragment (the part after
    // "#"). Fragments are never sent to a server -- and this is a local
    // file anyway -- and it's wiped from the address bar immediately
    // below so it isn't left sitting in view or in history.
    var match = /(?:^|[#&])session=([^&]+)/.exec(window.location.hash || "");
    if (!match) return null;
    try {
      var raw = match[1].replace(/-/g, "+").replace(/_/g, "/");
      var parsed = JSON.parse(decodeURIComponent(escape(window.atob(raw))));
      history.replaceState(null, "", window.location.pathname + window.location.search);
      return parsed && parsed.refreshToken ? parsed : null;
    } catch (e) {
      return null;
    }
  }

  function exchangeRefreshToken() {
    return fetch("https://securetoken.googleapis.com/v1/token?key=" + API_KEY, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "grant_type=refresh_token&refresh_token=" +
        encodeURIComponent(handedOver.refreshToken),
    }).then(function (response) {
      if (!response.ok) {
        throw new Error(
          "This session has expired. Close this window and open the tool " +
          "again from the app."
        );
      }
      return response.json();
    }).then(function (data) {
      cachedToken = data.id_token;
      cachedTokenExpiry = Date.now() + (parseInt(data.expires_in || "3600", 10) * 1000);
      return cachedToken;
    });
  }

  /** An ID token, refreshed when it's close to expiring. */
  function getToken() {
    if (handedOver) {
      // Refresh a minute early so a request never races the expiry.
      if (cachedToken && Date.now() < cachedTokenExpiry - 60000) {
        return Promise.resolve(cachedToken);
      }
      return exchangeRefreshToken();
    }
    var user = window.firebase && firebase.auth().currentUser;
    if (!user) return Promise.reject(new Error("Not signed in."));
    return user.getIdToken();
  }

  // ------------------------------- Firestore's tagged value encoding --

  function fromValue(value) {
    if ("stringValue" in value) return value.stringValue;
    if ("booleanValue" in value) return value.booleanValue;
    if ("integerValue" in value) return parseInt(value.integerValue, 10);
    if ("doubleValue" in value) return value.doubleValue;
    if ("nullValue" in value) return null;
    if ("mapValue" in value) return fromFields(value.mapValue.fields || {});
    if ("arrayValue" in value) {
      return (value.arrayValue.values || []).map(fromValue);
    }
    return null;
  }

  function fromFields(fields) {
    var out = {};
    Object.keys(fields || {}).forEach(function (key) {
      out[key] = fromValue(fields[key]);
    });
    return out;
  }

  function toValue(value) {
    if (typeof value === "boolean") return { booleanValue: value };
    if (typeof value === "number") {
      return Number.isInteger(value)
        ? { integerValue: String(value) }
        : { doubleValue: value };
    }
    if (value === null || value === undefined) return { nullValue: null };
    if (Array.isArray(value)) {
      return { arrayValue: { values: value.map(toValue) } };
    }
    if (typeof value === "object") {
      return { mapValue: { fields: toFields(value) } };
    }
    return { stringValue: String(value) };
  }

  function toFields(data) {
    var out = {};
    Object.keys(data || {}).forEach(function (key) {
      out[key] = toValue(data[key]);
    });
    return out;
  }

  // ------------------------------------------------------------ CRUD --

  function request(path, options) {
    options = options || {};
    return getToken().then(function (token) {
      return fetch(FIRESTORE + path, {
        method: options.method || "GET",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
      });
    }).then(function (response) {
      if (response.status === 404) return null;
      if (!response.ok) {
        return response.text().then(function (text) {
          var message = "";
          try { message = JSON.parse(text).error.message; } catch (e) { message = text; }
          if (response.status === 403 || /PERMISSION_DENIED/.test(message)) {
            throw new Error(
              "Your account doesn't have permission for that. If this is " +
              "unexpected, ask a Director to check your access."
            );
          }
          throw new Error(message || ("Request failed (" + response.status + ")"));
        });
      }
      return response.status === 204 ? {} : response.json();
    });
  }

  function getDoc(collection, id) {
    return request("/" + collection + "/" + encodeURIComponent(id)).then(function (doc) {
      return doc ? fromFields(doc.fields || {}) : null;
    });
  }

  function listCollection(collection) {
    var out = [];
    function page(token) {
      var url = "/" + collection + "?pageSize=300" +
        (token ? "&pageToken=" + encodeURIComponent(token) : "");
      return request(url).then(function (result) {
        if (!result) return out;
        (result.documents || []).forEach(function (doc) {
          var data = fromFields(doc.fields || {});
          data.id = doc.name.split("/").pop();
          out.push(data);
        });
        return result.nextPageToken ? page(result.nextPageToken) : out;
      });
    }
    return page("");
  }

  /* Firestore security rules are a permission check, not a filter. A
   * plain "list this collection" is refused outright if even one
   * document in it isn't readable by you -- which is exactly the case
   * for notes, where most documents belong to other people. The way to
   * read only what you're allowed is to ask a question narrow enough
   * that the rules can approve it, e.g. "notes where author is me".
   * That's what this does. */
  function queryCollection(collection, field, op, value) {
    var body = {
      structuredQuery: {
        from: [{ collectionId: collection }],
        where: {
          fieldFilter: {
            field: { fieldPath: field },
            op: op,
            value: toValue(value),
          },
        },
        limit: 500,
      },
    };
    return getToken().then(function (token) {
      return fetch(FIRESTORE + ":runQuery", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });
    }).then(function (response) {
      if (!response.ok) {
        return response.text().then(function (text) {
          var message = "";
          try { message = JSON.parse(text).error.message; } catch (e) { message = text; }
          throw new Error(message || ("Query failed (" + response.status + ")"));
        });
      }
      return response.json();
    }).then(function (rows) {
      var out = [];
      (rows || []).forEach(function (row) {
        // Rows without a document are read-time markers, not results.
        if (!row.document) return;
        var data = fromFields(row.document.fields || {});
        data.id = row.document.name.split("/").pop();
        out.push(data);
      });
      return out;
    });
  }

  /** Runs several queries and merges them, de-duplicated by id -- a note
   *  can match more than one (your own note addressed to someone else
   *  comes back from both "mine" and "addressed to them"). */
  function queryUnion(queries) {
    return Promise.all(queries.map(function (q) {
      return queryCollection(q.collection, q.field, q.op, q.value);
    })).then(function (results) {
      var seen = {};
      var merged = [];
      results.forEach(function (rows) {
        rows.forEach(function (row) {
          if (seen[row.id]) return;
          seen[row.id] = true;
          merged.push(row);
        });
      });
      return merged;
    });
  }

  function watchQueryUnion(queries, onData, onError) {
    var stopped = false;
    var timer = null;
    var lastSerialised = null;

    function tick() {
      if (stopped) return;
      queryUnion(queries).then(function (rows) {
        if (stopped) return;
        var serialised = JSON.stringify(rows);
        if (serialised !== lastSerialised) {
          lastSerialised = serialised;
          onData(rows);
        }
      }).catch(function (err) {
        if (!stopped && onError) onError(err);
      }).then(function () {
        if (!stopped) timer = setTimeout(tick, POLL_MS);
      });
    }

    tick();
    return function stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }

  function setDoc(collection, id, data, options) {
    var merge = options && options.merge;
    var path = "/" + collection + "/" + encodeURIComponent(id);
    if (merge) {
      // Without an update mask a PATCH replaces the whole document, so
      // merging means naming exactly the fields being written.
      path += "?" + Object.keys(data).map(function (key) {
        return "updateMask.fieldPaths=" + encodeURIComponent(key);
      }).join("&");
    }
    return request(path, { method: "PATCH", body: { fields: toFields(data) } });
  }

  function deleteDoc(collection, id) {
    return request("/" + collection + "/" + encodeURIComponent(id), { method: "DELETE" });
  }

  /** Calls onData now and then every few seconds. Returns a stop function. */
  function watchCollection(collection, onData, onError) {
    var stopped = false;
    var timer = null;
    var lastSerialised = null;

    function tick() {
      if (stopped) return;
      listCollection(collection).then(function (docs) {
        if (stopped) return;
        var serialised = JSON.stringify(docs);
        if (serialised !== lastSerialised) {
          lastSerialised = serialised;
          onData(docs);
        }
      }).catch(function (err) {
        if (!stopped && onError) onError(err);
      }).then(function () {
        if (!stopped) timer = setTimeout(tick, POLL_MS);
      });
    }

    tick();
    return function stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }

  function watchDoc(collection, id, onData, onError) {
    var stopped = false;
    var timer = null;
    var lastSerialised = null;

    function tick() {
      if (stopped) return;
      getDoc(collection, id).then(function (doc) {
        if (stopped) return;
        var serialised = JSON.stringify(doc);
        if (serialised !== lastSerialised) {
          lastSerialised = serialised;
          onData(doc);
        }
      }).catch(function (err) {
        if (!stopped && onError) onError(err);
      }).then(function () {
        if (!stopped) timer = setTimeout(tick, POLL_MS);
      });
    }

    tick();
    return function stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }

  // ----------------------------------------------------------- start --

  handedOver = readHandover();

  window.CenterSession = {
    /** True when the desktop launcher supplied the session, meaning the
     * page must not show a login of its own. */
    isHandedOver: function () { return !!handedOver; },
    /** { email, name, role } as the launcher knows them. */
    user: function () { return handedOver; },
    canEditTemplate: function () {
      var role = handedOver && handedOver.role;
      return role === "admin" || role === "director";
    },
    getToken: getToken,
    getDoc: getDoc,
    listCollection: listCollection,
    queryCollection: queryCollection,
    queryUnion: queryUnion,
    watchQueryUnion: watchQueryUnion,
    setDoc: setDoc,
    deleteDoc: deleteDoc,
    watchCollection: watchCollection,
    watchDoc: watchDoc,
  };
})();
