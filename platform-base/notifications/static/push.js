/* notifications — «התראות בטלפון הזה»: the card that lets a person have the office's severe notices ring
   their phone (push.py, sw.js). It draws itself above the KPI strip and needs nothing from the page but
   the theme tokens (and BinaNav's icons when the page has them). Every address is relative, so it works at
   the app's own host and inside the console at /a/alerts/.

   Its states, each with ONE thing to do: push off on this office (no card) · not signed in · this browser
   cannot (iPhone: add to the home screen first) · inside another site's frame (open in a tab — a browser
   asks for a permission only from the page itself) · blocked (how to allow again) · off (allow) · on (a test,
   stop, the person's other devices) · a failure said in a sentence, next to what failed. */
(function () {
  "use strict";
  // the office's language when the page loads bina-lang.js, its Hebrew when it does not (as bina-nav.js)
  function tt(he, en) {
    try { return (typeof window !== "undefined" && window.L) ? window.L(he, en) : he; } catch (e) { return he; }
  }
  function ic(name) {
    try { return (window.BinaNav && window.BinaNav.svg) ? window.BinaNav.svg(name) : ""; } catch (e) { return ""; }
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  var ua = navigator.userAgent || "";
  var ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  var phone = /Android|iPhone|iPod|Mobile/.test(ua);
  var where = phone ? tt("בטלפון הזה", "on this phone") : tt("במכשיר הזה", "on this device");
  var standalone = (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true;
  var supported = window.isSecureContext && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  var st = { key: "", person: "", reg: null, sub: null, devices: [], busy: false, said: "", saidBad: false, hidden: false };
  try { st.hidden = localStorage.getItem("push-card-hidden") === "1"; } catch (e) { /* no storage: shown */ }

  function crossFramed() {
    if (window.top === window) return false;
    try { return window.top.location.origin !== location.origin; } catch (e) { return true; }
  }
  function keyBytes(k) {
    var s = (k + "===".slice((k.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function api(path, body) {
    var o = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    o.credentials = "same-origin";
    return fetch(path, o).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.message || (tt("השרת ענה ", "The server answered ") + r.status)); e.status = r.status; throw e; }
        return j;
      });
    });
  }

  var card = document.createElement("section");
  card.className = "push-card";
  card.id = "pushCard";
  card.setAttribute("aria-live", "polite");
  card.setAttribute("aria-label", tt("התראות לטלפון", "Notices on your phone"));
  var reopen = null;

  function mount() {
    var hud = document.getElementById("hud");
    if (hud && hud.parentNode) hud.parentNode.insertBefore(card, hud);
    else document.body.insertBefore(card, document.body.firstChild);
    var acts = document.querySelector(".pg-actions");
    if (acts) {
      reopen = document.createElement("button");
      reopen.type = "button";
      reopen.className = "btn ghost push-reopen";
      reopen.innerHTML = ic("bell") + "<span>" + esc(tt("לטלפון", "Phone")) + "</span>";
      reopen.title = tt("התראות חמורות בטלפון", "Severe notices on your phone");
      reopen.addEventListener("click", function () { setHidden(false); });
      acts.insertBefore(reopen, acts.firstChild);
    }
  }
  function setHidden(h) {
    st.hidden = h;
    try { if (h) localStorage.setItem("push-card-hidden", "1"); else localStorage.removeItem("push-card-hidden"); } catch (e) { /* fine */ }
    draw();
    if (!h) { var b = card.querySelector("button"); if (b) b.focus(); }
  }

  function state() {
    if (!st.person) return "anon";
    if (!supported) return ios && !standalone ? "ios" : "unsupported";
    if (crossFramed()) return "framed";
    if (Notification.permission === "denied") return "denied";
    if (st.sub && st.devices.some(function (d) { return d.this; })) return "on";
    return "off";
  }

  function btn(id, label, cls, icon) {
    return '<button type="button" class="btn push-btn ' + (cls || "") + '" data-push="' + id + '">' + (icon ? ic(icon) : "") +
      "<span>" + esc(label) + "</span></button>";
  }

  function draw() {
    if (!card.isConnected) return;
    var s = state();
    card.hidden = st.hidden;
    if (reopen) reopen.hidden = !st.hidden;
    if (st.hidden) return;
    var title = s === "on" ? tt("הטלפון הזה מקבל את התראות המשרד", "This phone gets the office's notices")
                           : tt("התראות חמורות", "Severe notices") + " " + where;
    if (s === "on" && !phone) title = tt("המכשיר הזה מקבל את התראות המשרד", "This device gets the office's notices");
    var text = "", acts = "";
    if (s === "anon") {
      text = tt("לא זוהה משתמש מחובר — פתח את הדף דרך המשרד.", "No signed-in person — open this page through the office.");
    } else if (s === "ios") {
      text = tt("באייפון: פתח את הדף ב-Safari, «שתף» ← «הוסף למסך הבית», פתח אותו משם ואפשר כאן.",
                "On an iPhone: open this page in Safari, Share → Add to Home Screen, open it from there and allow here.");
    } else if (s === "unsupported") {
      text = tt("הדפדפן הזה לא יכול לקבל התראות. בטלפון אנדרואיד: Chrome או Samsung Internet.",
                "This browser cannot receive notices. On an Android phone: Chrome or Samsung Internet.");
    } else if (s === "framed") {
      text = tt("דפדפן מבקש רשות רק מהדף עצמו — פתח אותו בלשונית משלו ואפשר שם.",
                "A browser asks for permission only from the page itself — open it in its own tab and allow there.");
      acts = btn("tab", tt("פתח בלשונית", "Open in a tab"), "push-pri", "share");
    } else if (s === "denied") {
      text = tt("ההתראות חסומות לאתר הזה. לפתיחה: סמל המנעול ליד הכתובת ← «הרשאות» ← «התראות» ← «אפשר», ואז רענן את הדף.",
                "Notices are blocked for this site. To allow: the lock by the address → Permissions → Notifications → Allow, then reload.");
    } else if (s === "off") {
      text = tt("כשמשהו חמור קורה במשרד — שירות נפל, המעבד בקצה, גיבוי נכשל — הטלפון יצלצל, גם כשהמשרד סגור.",
                "When something severe happens in the office — a service down, the CPU at its limit, a failed backup — your phone rings, even with the office closed.");
      acts = btn("on", tt("אפשר", "Allow") + " " + where, "push-pri", "bell") + btn("later", tt("לא עכשיו", "Not now"), "ghost");
    } else {
      text = tt("שירות שנפל, מעבד בקצה, גיבוי שנכשל — מצלצלים כאן. כשזה חוזר לתקין, ההתראה מתעדכנת בשקט.",
                "A service down, the CPU at its limit, a failed backup ring here; when it is fine again the notice updates quietly.");
      acts = btn("test", tt("שלח בדיקה", "Send a test"), "push-pri", "bell") + btn("stop", tt("הפסק", "Stop") + " " + where, "ghost");
    }
    var others = st.devices.filter(function (d) { return !d.this; });
    var list = others.length ? '<details class="push-devs"><summary>' + esc(tt("המכשירים האחרים שלך", "Your other devices")) +
      ' <span class="num">' + others.length + "</span></summary><ul>" + others.map(function (d) {
        return '<li><span>' + esc(d.label) + '</span><button type="button" class="btn ghost push-btn" data-push="drop" data-id="' + d.id + '">' +
          esc(tt("הסר", "Remove")) + "</button></li>";
      }).join("") + "</ul></details>" : "";
    card.innerHTML =
      '<div class="push-ic" aria-hidden="true">' + ic("bell") + "</div>" +
      '<div class="push-main"><h2 class="push-t">' + esc(title) + "</h2>" +
      '<p class="push-x">' + esc(text) + "</p>" +
      (st.said ? '<p class="push-said' + (st.saidBad ? " bad" : "") + '" role="' + (st.saidBad ? "alert" : "status") + '">' + esc(st.said) + "</p>" : "") +
      (acts ? '<div class="push-acts">' + acts + "</div>" : "") + list + "</div>" +
      (s === "on" || s === "off" ? '<button type="button" class="push-close" data-push="later" aria-label="' + esc(tt("הסתר", "Hide")) + '" title="' +
        esc(tt("הסתר", "Hide")) + '">' + (ic("x") || "×") + "</button>" : "");
    card.dataset.state = s;
    card.querySelectorAll("[data-push]").forEach(function (b) {
      b.disabled = st.busy;
      b.addEventListener("click", function () { act(b.getAttribute("data-push"), b); });
    });
  }

  function say(text, bad) { st.said = text || ""; st.saidBad = !!bad; }

  function refresh() {
    var ep = st.sub ? st.sub.endpoint : "";
    return api("api/push/devices?endpoint=" + encodeURIComponent(ep)).then(function (j) {
      st.devices = j.devices || [];
    }, function () { st.devices = []; });
  }

  function save(sub) {
    return api("api/push/subscribe", { subscription: sub.toJSON() });
  }

  function act(what, el) {
    if (st.busy) return;
    if (what === "later") return setHidden(true);
    if (what === "tab") { window.open(location.href, "_blank", "noopener"); return; }
    st.busy = true; say(""); draw();
    var run;
    if (what === "on") {
      run = Notification.requestPermission().then(function (p) {
        if (p !== "granted") throw new Error(p === "denied" ? tt("הבקשה נדחתה בדפדפן.", "The browser said no.")
                                                            : tt("לא ניתנה רשות — נסה שוב.", "No permission was given — try again."));
        return (st.reg ? Promise.resolve(st.reg) : navigator.serviceWorker.register("sw.js", { scope: "./" }).then(function () {
          return navigator.serviceWorker.ready;
        })).then(function (reg) {
          st.reg = reg;
          return reg.pushManager.getSubscription().then(function (old) {
            return old || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(st.key) });
          });
        });
      }).then(function (sub) {
        st.sub = sub;
        return save(sub);
      }).then(refresh).then(function () { say(tt("מוכן. לחץ «שלח בדיקה» כדי לשמוע איך זה נשמע.", "Done. Press «Send a test» to hear it.")); });
    } else if (what === "test") {
      run = api("api/push/test", { endpoint: st.sub ? st.sub.endpoint : "" }).then(function (j) {
        if (j.sent) say(tt("נשלחה בדיקה — היא תגיע בעוד רגע.", "A test was sent — it arrives in a moment."));
        else if (j.gone) { st.sub = null; say(tt("הטלפון כבר לא רשום אצל שירות ההתראות — אפשר שוב.", "The push service no longer knows this phone — allow again."), true); }
        else say(tt("שירות ההתראות לא קיבל את הבדיקה — נסה שוב בעוד דקה.", "The push service did not take the test — try again in a minute."), true);
      }).then(refresh);
    } else if (what === "stop") {
      var sub = st.sub;
      run = api("api/push/unsubscribe", { endpoint: sub ? sub.endpoint : "" }).then(function () {
        return sub ? sub.unsubscribe().catch(function () { return false; }) : true;
      }).then(function () { st.sub = null; }).then(refresh).then(function () { say(tt("הופסק. הטלפון הזה לא יצלצל.", "Stopped. This phone will not ring.")); });
    } else if (what === "drop") {
      run = api("api/push/unsubscribe", { id: Number(el.getAttribute("data-id")) }).then(refresh);
    } else {
      run = Promise.resolve();
    }
    run.catch(function (e) {
      say((e && e.message) ? e.message : tt("הפעולה נכשלה.", "The action failed."), true);
    }).then(function () { st.busy = false; draw(); });
  }

  function start() {
    api("api/push/key").then(function (k) {
      if (!k.enabled) return;                         // push is off on this office: no card at all
      st.person = k.person || "";
      if (!k.ready) { say(tt("ההתראות לטלפון אינן זמינות כרגע בשרת.", "Phone notices are not available on the server right now."), true); }
      st.key = k.key || "";
      mount();
      draw();
      if (!st.person || !supported || crossFramed()) return;
      return navigator.serviceWorker.getRegistration("./").then(function (reg) {
        st.reg = reg || null;
        return reg ? reg.pushManager.getSubscription() : null;
      }).then(function (sub) {
        st.sub = sub || null;
        // a phone that is subscribed tells the server again on each visit (a lost row is repaired)
        return sub ? save(sub).catch(function () { return null; }) : null;
      }).then(refresh).then(draw);
    }).catch(function () { /* no push API on this server: the page is the notices, as before */ });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
