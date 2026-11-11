/* mount.js — the console, when ANOTHER office's console is showing it (DGO-553).

   This shell is normally served at its own root: `/api/version`, `/a/drive/`, `/?bare=1#/m/x` are all
   absolute paths on ITS origin. A linked office's «המרכז» tile is this same shell served through that
   office's proxy at `/a/console-home.<office>/`, and there an absolute `/api/version` would ask the
   OTHER office's edge a question about ITS apps — the two-consoles-seen-as-one bug the compiler's
   `through_console` comment records from 2026-10-05.

   So: one seam, here, before any other script loads.
     · `document.baseURI` is where the outer console already said this page lives (it injects
       `<base href="/a/console-home.<office>/">` into every proxied page). At home it is `/`.
     · `dgoUrl(path)` prefixes an absolute path with that mount point (and is a no-op at home, so
       nothing about a normal office changes).
     · `fetch` is wrapped once, so every `fetch("/api/…")` in this shell — and in an app that shares
       this file — stays inside the mount.
   Relative URLs and `src`/`href` attributes need none of this: `<base>` already covers them, and
   iframe/asset attributes are rewritten by the outer console's own `_rewrite_abs`. */
(function () {
  "use strict";
  var base = document.baseURI || location.href;
  var u;
  try { u = new URL(base, location.href); } catch (e) { u = null; }
  var mount = (u && u.origin === location.origin && u.pathname && u.pathname !== "/")
    ? u.pathname.replace(/\/+$/, "")
    : "";
  window.DGO_MOUNT = mount;

  window.dgoUrl = function (path) {
    if (!mount || typeof path !== "string" || path.charAt(0) !== "/") return path;
    if (path === mount || path.indexOf(mount + "/") === 0) return path;   // already there
    return mount + path;
  };

  var nativeFetch = window.fetch;
  if (typeof nativeFetch === "function") {
    window.fetch = function (input, init) {
      if (typeof input === "string") return nativeFetch.call(this, window.dgoUrl(input), init);
      if (input && typeof input === "object" && typeof input.url === "string" && input.url.charAt(0) === "/") {
        return nativeFetch.call(this, window.dgoUrl(input.url), init);
      }
      return nativeFetch.call(this, input, init);
    };
  }
})();
