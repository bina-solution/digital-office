/* handoffs.js — an app that needs a PERSON in another app's screen gets him there, and back (DGO-1336).
 *
 * The owner pressed «Continue with Google» in the HP's Claude tile on his phone. Google's account
 * chooser opened in the office browser — in its own display, which nobody was looking at — and he went
 * on looking at «Sign In» (2026-11-04: «זה לא עובד לא פותח לי שום דפדפן»). Nothing told the screen in
 * front of him: the shell's frame is another origin, and it had no way to be told to change tiles.
 *
 * Now the app that holds the screen RECORDS each hand-off (browser42: `bbox b42 open <app> <url>`, one
 * record per errand — who asked, `needed` → `done` | `failed`, a sentence; never an address), and this
 * console reads every such list (`GET /api/handoffs`, app.py; the address is on the tile, compiled from
 * the app's `handoffs` declaration). Asked every few seconds while the page is in view:
 *
 *   · a hand-off `needed` FOR a tile the person can see → he is brought to the screen that needs him,
 *     once per episode — a person who walks away from it is not pulled back;
 *   · that episode `done` while he is still there → back to the app that asked;
 *   · `failed` → back as well, and the sentence that says why, on top (a card he closes) — so a
 *     failure is never only a log line while he watches a spinner.
 *
 * HOW HE IS BROUGHT THERE, as every operating system does it (the owner, 2026-11-06, DGO-1434: «in desktop
 * mode in a new window so both shown, and if not desktop mode it should just switch to the browser … and
 * later even after login it should open back that application»):
 *   · the DESKTOP opens the browser as a window of its own BESIDE the window that asked — that window keeps
 *     its side and gives up half the width (`beside`, below); it says it is waiting, with «show the
 *     browser» and «cancel», and the browser's title says whom it serves. At the end the window the errand
 *     opened goes, and the app is back where it was, in front (desktop.js `handoff`).
 *   · the PHONE (and the classic shell) switches the one frame to the browser, with a fixed way back to the
 *     app above it — one touch, always — and switches back at the end.
 *
 * WHERE HE IS. The shell says it (app.js): on the phone the tile the address names; on the desktop the
 * FOCUSED window, with every open window «in view». The address alone was wrong there: a window on an
 * app's own host is another origin, so a press inside it moves neither the address nor the focus, and a
 * window opened from the dock writes no address at all.
 *
 * `decide` and `beside` are the rules, pure functions, so `test_handoffs.mjs` can hold them.
 */
(function () {
  "use strict";

  const KEEP = 20;                         // episodes remembered as handled (only the ids)
  // The person is to see the browser within 5 s of his press (DGO-1336): the record is written in ~1 s,
  // the server re-asks an app at most once a second (app.py HANDOFFS_FRESH_S), and this asks every 2 s.
  const EVERY_MS = 2000;
  const STORE = "do-handoffs";

  // A failure nobody was switched for is said only while it is news: a tab opened later, on another device,
  // must not greet the person with an old attempt's card.
  const SAY_FRESH_S = 120;

  // view(here) — where the person is, as the shell says it: {front, seen, addressed}, or older forms.
  //   front     — the tile he works in: the address's on the phone, the focused window's on the desktop
  //   seen      — every tile in view (front first; on the desktop every other open window)
  //   addressed — the tile the address names (where «back» may keep the inner route he pressed from)
  // An array is [front, …seen] and a string is the one tile in front; both mean addressed = front.
  function view(here) {
    if (here && typeof here === "object" && !Array.isArray(here)) {
      const front = typeof here.front === "string" ? here.front : "";
      const seen = [front].concat(Array.isArray(here.seen) ? here.seen : []).filter((x) => typeof x === "string");
      return { front, seen, addressed: typeof here.addressed === "string" ? here.addressed : front };
    }
    const seen = (Array.isArray(here) ? here : [here]).filter((x) => typeof x === "string");
    return { front: seen[0] || "", seen, addressed: seen[0] || "" };
  }

  // decide(list, here, hash, memory) → { action, memory, ended }
  //   list   — /api/handoffs's `handoffs`: [{at, for, slug, state, sentence, id, age}]
  //   here   — where he is (view above)
  //   hash   — the address now (where «back» returns to when it names the asking tile)
  //   memory — { acted: [episode ids], trip: {id, at, slug, for, from, sentence} | null } (what this page did)
  //   action — {go: hash} | {back: hash, say?: sentence} | {say: sentence} | null
  //   ended  — {trip, how: "done" | "failed" | "gone" | "replaced"} when the trip this page was on ended in
  //            this call (`replaced`: another app in view asked while it still waited)
  function decide(list, here, hash, memory) {
    const v = view(here);
    const inView = (id) => !!id && v.seen.includes(id);
    // where «back» goes: the address he pressed from when it names the asking tile, else that tile itself
    const backTo = (h) => (v.addressed === h.for ? hash : "#/m/" + h.for);
    const acted = (memory && Array.isArray(memory.acted) ? memory.acted : []).slice(-KEEP);
    let trip = memory && memory.trip ? memory.trip : null;
    const items = Array.isArray(list) ? list.filter((h) => h && typeof h.id === "string" && h.id) : [];
    const keep = (action, ended) => ({ action, memory: { acted: acted.slice(-KEEP), trip }, ended: ended || null });
    if (trip) {
      // the episode this page switched him for — or a new attempt in the same place (the app asked
      // again: a new episode of the same slug replaces the old record), which this trip now follows
      let h = items.find((x) => x.id === trip.id);
      if (!h) {
        h = items.find((x) => x.at === trip.at && x.slug === trip.slug && x.for === trip.for);
        if (h && !acted.includes(h.id)) {
          acted.push(h.id);
          trip = { ...trip, id: h.id, sentence: h.state === "needed" ? String(h.sentence || "") : trip.sentence || "" };
          // …pressed again FROM THE APP: he walked back from the browser and asked once more, so he is
          // taken there again, with the way back he has now (the second reader of DGO-1336)
          if (h.state === "needed" && inView(h.for) && v.front !== trip.at) {
            trip = { ...trip, from: backTo(h) };
            return keep({ go: "#/m/" + h.at + "/handoff/" + h.slug });
          }
        }
      }
      if (!h) { const was = trip; trip = null; return keep(null, { trip: was, how: "gone" }); }   // nothing to end
      // ANOTHER app in view asks while this trip still waits (a sign-in left open, the browser's record not
      // yet gone): the newer ask wins — one forgotten errand must never block every other app (the second
      // reader of DGO-1434). The old trip ends quietly (`replaced`), and he is taken to the new one.
      // …never while he is working IN the browser for this trip: that is not a forgotten errand
      if (h.state === "needed" && v.front !== trip.at) {
        const other = items.find((x) => x.state === "needed" && x.at && x.slug && !acted.includes(x.id) && inView(x.for) &&
                                        !(x.at === trip.at && x.slug === trip.slug && x.for === trip.for));
        if (other) {
          const was = trip;
          acted.push(other.id);
          trip = { id: other.id, at: other.at, slug: other.slug, for: other.for, from: backTo(other), sentence: String(other.sentence || "") };
          return keep({ go: "#/m/" + other.at + "/handoff/" + other.slug }, { trip: was, how: "replaced" });
        }
      }
      if (h.state === "done" || h.state === "failed") {
        // back only while he is ON the browser: one who went to another window or tile is left there
        // (the second reader of DGO-1434 — on the desktop the browser's window stays open and «in view»)
        const there = v.front === trip.at;
        const was = trip;
        trip = null;
        const say = h.state === "failed" ? (h.sentence || "") : "";
        const ended = { trip: was, how: h.state };
        if (there) return keep(say ? { back: was.from, say } : { back: was.from }, ended);
        return keep(say ? { say } : null, ended);                     // he already left: only the word
      }
      return keep(null);                                            // still needed: he is on it, or chose not to be
    }
    for (const h of items) {
      if (!inView(h.for) || acted.includes(h.id)) continue;
      if (h.state === "needed" && h.at && h.slug) {
        acted.push(h.id);
        trip = { id: h.id, at: h.at, slug: h.slug, for: h.for, from: backTo(h), sentence: String(h.sentence || "") };
        return keep({ go: "#/m/" + h.at + "/handoff/" + h.slug });
      }
      if (h.state === "failed" && h.sentence && Number(h.age) < SAY_FRESH_S) {   // failed before anyone was switched
        acted.push(h.id);
        return keep({ say: h.sentence });
      }
    }
    return keep(null);
  }

  // beside(app, zone) → {app, bro} | null — THE PLACEMENT RULE on the desktop. The window that asked keeps its
  // side (its centre left of the screen's → the left half) and gives up half the width; the browser takes
  // the other half; both whole, neither over the other, the pair centred. Rects are kept as desktop.js keeps
  // a window: {cx, cy, w, h}. app = {cx} (or null: no window asked), zone = {W, top, bottom}. Each half's
  // centre lies inside the focus zone for every width the desktop runs at (≥1024: the flank is at most a
  // quarter of the width, a centre at least W/4 + 8), so neither window is shrunk into a flank.
  const MARGIN = 24, GAP = 16, MAX_W = 1180, MAX_H = 920;
  function beside(app, zone) {
    if (!zone || !(zone.W > 0) || !(zone.bottom > zone.top)) return null;
    const w = Math.min(MAX_W, Math.floor((zone.W - 2 * MARGIN - GAP) / 2));
    const h = Math.min(MAX_H, Math.round(zone.bottom - zone.top - 16));
    if (w < 1 || h < 1) return null;
    const cy = Math.round((zone.top + zone.bottom) / 2);
    const lx = Math.round(zone.W / 2 - GAP / 2 - w / 2), rx = Math.round(zone.W / 2 + GAP / 2 + w / 2);
    const onLeft = !(app && app.cx > zone.W / 2);
    return { app: { cx: onLeft ? lx : rx, cy, w, h }, bro: { cx: onLeft ? rx : lx, cy, w, h } };
  }

  function load() {
    try { return JSON.parse(sessionStorage.getItem(STORE) || "null") || { acted: [], trip: null }; }
    catch (e) { return { acted: [], trip: null }; }
  }
  function save(memory) {
    try { sessionStorage.setItem(STORE, JSON.stringify(memory)); } catch (e) { /* private mode */ }
  }

  // The sentence, as a card the person closes — the shell's own modal, no style of its own.
  function say(sentence) {
    const old = document.querySelector(".modal-ov.handoff-said");
    if (old) old.remove();
    const el = document.createElement("div");
    el.className = "modal-ov handoff-said"; el.setAttribute("role", "alertdialog"); el.setAttribute("aria-live", "assertive");
    const card = document.createElement("div"); card.className = "modal";
    const head = document.createElement("div"); head.className = "modal-h";
    const title = document.createElement("h3"); title.textContent = "לא הושלם";
    const text = document.createElement("span"); text.textContent = sentence;
    const ok = document.createElement("button"); ok.className = "btn"; ok.type = "button"; ok.textContent = "הבנתי";
    ok.onclick = () => el.remove();
    head.appendChild(title); card.append(head, text, ok); el.appendChild(card);
    document.body.appendChild(el);
    ok.focus();
  }

  // start(here, opts) — `here()` is the shell's answer to «where is he» (app.js owns the grammar: view
  // above); opts.name(tile) is a tile's name, for the way back and the browser's title.
  function start(here, opts) {
    const nameOf = (id) => { try { return (opts && typeof opts.name === "function" && opts.name(id)) || id; } catch (e) { return id; } };
    let memory = load(), busy = false;
    // the desktop's hand-off (desktop.js), while the desktop is up; null in the classic shell and on the phone
    const desk = () => (window.BinaDesktop && BinaDesktop.isOn() && BinaDesktop.handoff ? BinaDesktop.handoff : null);
    const where = () => { try { return view(here()); } catch (e) { return view(""); } };

    function tell(text) {
      const D = desk();
      if (D && D.toast) D.toast(text);
      else if (typeof window.binaTell === "function") window.binaTell(text, "ok");
    }
    // there: the browser beside the app (desktop), or the one frame switched to it (phone)
    function go(t, to) {
      const D = desk();
      if (D && D.open({ at: t.at, for: t.for, route: "/handoff/" + t.slug, name: nameOf(t.for), sentence: t.sentence || "", from: t.from })) return;
      if (location.hash !== to) location.hash = to;
    }
    // the end of a trip: back to the app that asked when he is still on the browser, and the marks gone.
    // On the desktop the windows always get their places back (desktop.js end); «back» adds the focus —
    // also when he already went to the asking window himself (its title, the dock), which is the same place.
    function finish(t, how, back) {
      const D = desk();
      if (D && !back && how === "done" && where().front === t.for) back = true;
      if (D) D.end({ at: t.at, for: t.for, back: !!back, from: t.from, how });
      else if (back && t.from && location.hash !== t.from) location.hash = t.from;
      syncBar();
      if (back && how === "done") tell("הושלם בדפדפן הלשכה · חזרה ל" + nameOf(t.for));
    }
    // the person ends it himself: «ביטול» on the desktop's band, the browser's window closed, the phone's way
    // back. He is taken back to the app; the errand itself is the app's (a press there starts a new one).
    function cancel() {
      const t = memory.trip;
      if (!t) return;
      memory = { acted: memory.acted || [], trip: null };
      save(memory);
      finish(t, "cancelled", true);
    }
    // the phone's (and the classic shell's) way back: fixed over the browser's screen while it serves the app
    function syncBar() {
      const wrap = document.getElementById("embedwrap");
      if (!wrap) return;
      const t = memory.trip;
      const on = !!t && !desk() && where().front === t.at;
      let bar = wrap.querySelector(".handoff-back");
      wrap.classList.toggle("has-handoff", on);
      if (!on) { if (bar) bar.remove(); return; }
      if (!bar) {
        bar = document.createElement("div");
        bar.className = "handoff-back";
        const btn = document.createElement("button");
        btn.type = "button"; btn.className = "handoff-back-btn";
        btn.innerHTML = typeof mIcon === "function" ? mIcon("back") : "";
        btn.appendChild(document.createElement("span"));
        btn.addEventListener("click", cancel);
        const pill = document.createElement("span");
        pill.className = "pill need";
        bar.append(btn, pill);
        wrap.insertBefore(bar, wrap.firstChild);
      }
      const name = nameOf(t.for);
      const btn = bar.querySelector(".handoff-back-btn");
      btn.querySelector("span").textContent = name;
      btn.title = "חזרה ל" + name;
      btn.setAttribute("aria-label", btn.title);
      const pill = bar.querySelector(".pill");
      pill.textContent = "עבור " + name;
      pill.title = t.sentence || "";
    }

    async function tick() {
      if (busy || document.hidden) return;
      busy = true;
      try {
        const r = await fetch("/api/handoffs", { cache: "no-store", redirect: "manual" });
        if (!r.ok) return;
        const list = ((await r.json()) || {}).handoffs || [];
        const out = decide(list, where(), location.hash, memory);
        memory = out.memory; save(memory);
        const a = out.action;
        // the old trip's end first: a trip REPLACED by another app's ask gives its windows back before the
        // new one takes its places
        if (out.ended) finish(out.ended.trip, out.ended.how, !!(a && a.back));
        if (a && a.go && memory.trip) go(memory.trip, a.go);
        if (a && a.say) say(a.say);
        syncBar();
      } catch (e) {
        /* an answer that did not come is the next tick's question */
      } finally {
        busy = false;
      }
    }
    if (window.BinaDesktop && BinaDesktop.handoff) BinaDesktop.handoff.onCancel(cancel);
    window.addEventListener("hashchange", syncBar);
    setInterval(tick, EVERY_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
    tick();
  }

  window.BinaHandoffs = { decide, beside, start };
})();
