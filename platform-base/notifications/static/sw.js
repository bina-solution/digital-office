// notifications — the service worker (push.py): an office notice that rings becomes a notification on the
// phone, and a tap opens it. Served next to the page, so its scope is this app: "/" at its own host, and
// "/a/alerts/" inside the console. It caches nothing — no fetch handler — so every page still comes from
// the server exactly as before.
"use strict";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

// Inside the console the scope is /a/<alias>/, and the console opens a module at /#/m/<alias>.
function home() {
  const s = new URL(self.registration.scope);
  const m = s.pathname.match(/\/a\/([^/]+)\/$/);
  return m ? s.origin + "/#/m/" + m[1] : s.href;
}

// The message is the Declarative Web Push form ({web_push: 8030, notification: {title, body, navigate, tag,
// silent}}): an iPhone on iOS 18.4+ can show it by itself; everywhere else this shows it. Every push shows
// a notification — a browser takes the permission away from a site whose pushes show nothing.
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { notification: { body: e.data ? e.data.text() : "" } }; }
  const n = d.notification || {};
  const quiet = !!n.silent;                      // a notice that cleared replaces the alarm without a sound
  const options = {
    body: n.body || "",
    tag: n.tag || "office",
    renotify: !quiet,
    silent: quiet,
    requireInteraction: !quiet && d.level === "error",   // on a computer an alarm stays until it is seen
    vibrate: quiet ? undefined : [300, 120, 300],
    lang: n.lang || "he",
    dir: n.dir || "auto",
    data: { url: n.navigate || "" },
  };
  e.waitUntil(self.registration.showNotification(n.title || "התראה מהמשרד", options));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  let url = home();
  const want = e.notification.data && e.notification.data.url;
  if (want) {
    try {
      const u = new URL(want, self.registration.scope);
      if (u.protocol === "https:" || u.origin === self.location.origin) url = u.href;   // never a javascript: link
    } catch (_) { /* a link that is not a URL: the notices page */ }
  }
  e.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of open) {
      if (w.url === url && "focus" in w) return w.focus();
    }
    return self.clients.openWindow(url);
  })());
});

// The browser renewed this phone's subscription: the server learns the new one (and forgets the old).
self.addEventListener("pushsubscriptionchange", (e) => {
  e.waitUntil((async () => {
    const old = e.oldSubscription;
    let sub = e.newSubscription;
    const key = old && old.options && old.options.applicationServerKey;
    if (!sub && key) sub = await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
    if (!sub) return;
    await fetch(new URL("api/push/subscribe", self.registration.scope).href, {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subscription: sub.toJSON(), replaces: old ? old.endpoint : "" }),
    });
  })());
});
