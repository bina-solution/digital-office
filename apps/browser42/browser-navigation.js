import UI from "./ui.js";

const button = document.getElementById("browser42_navigation_button");

button.addEventListener("click", () => {
    if (!UI.rfb) return;
    UI.sendKey(0xffc8, "F11");
});

// The hand-off (handoff.py) could not bring the group's tab to the front — it was released, or not
// found after the browser woke — and said so with `?lost=<slug>` (carried here by the Caddyfile's
// /view/ redir). Say it on the viewer, once, in noVNC's own status line, instead of leaving the
// person to hunt. The slug is checked before it is shown; the status line is text, never markup.
const lost = new URLSearchParams(window.location.search).get("lost");
if (lost && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(lost)) {
    setTimeout(() => UI.showStatus(
        `הכרטיסייה של «${lost}» לא נמצאה — אם היא עוד פתוחה, בחר אותה מרצועת הכרטיסיות למעלה`,
        "warn", 15000), 3000);
}

// THE CARD OVER THE SCREEN (DGO-437). When the screen does not connect, noVNC draws its own page as it ships — a
// red English line («Failed to connect to server»), its «Reconnecting…» veil and a Cancel button on a black
// ground — inside a Hebrew office. The office's card stands over it instead (viewer/card.css: the card every tile
// shows when its app has nothing to show): what is not answering, that it asks again by itself and in how many
// seconds, «נסה עכשיו», and what noVNC said, one click away. It READS noVNC's own state — the class ui.js puts on
// <html> (updateVisualState: noVNC_connecting / _connected / _reconnecting / _disconnecting) — and asks again only
// through noVNC's own calls. noVNC retries by itself only a screen that was once up (`reconnect=true` in the
// Caddyfile's /view/ redir; ui.js clears `inhibitReconnect` in connectFinished alone): a FIRST connect that fails
// stays failed, with its Connect button — the owner's screen on this item. So the card keeps the count itself: when
// noVNC waits (`reconnecting`) its own timer tries; when it does not, the card calls UI.connect when the count ends,
// as noVNC's Connect button would. «נסה עכשיו» tries at once. A sign-in that lapsed is said as that, not retried.
// The stylesheet is fetched with the page and applies only while the card stands (`media`), so a screen that
// connects is noVNC's page exactly as before; it is fetched EARLY, because when the browser goes down the file goes
// with it. (When the browser does not answer at all, /view/ gets no page and this never runs: Caddy answers with
// the same card, viewer/screen-down.html.)
{
    const root = document.documentElement;
    const SLOW_MS = 1500;   // a first connect slower than this says «מתחבר» rather than leave a black screen
    const sheet = Object.assign(document.createElement("link"), {
        rel: "stylesheet", media: "not all", href: new URL("browser42-card.css", import.meta.url).href });
    let styled = false;     // the sheet arrived: an image without it (start-browser.sh §4b''') draws no card
    sheet.addEventListener("load", () => { styled = true; if (failures > 0 && state() !== "connecting") arm(); draw(); });
    document.head.appendChild(sheet);

    let failures = 0;       // tries since the screen was last up
    let left = 0;           // whole seconds until the next try
    let leaving = false;    // the person pressed noVNC's own Disconnect: its panel is theirs, no card
    let prev = "idle";      // the state drawn last: a fall is a change INTO waiting or idle from a try or the screen
    let slow = null, tick = null, over = null, said = "";

    const state = () => ["connected", "reconnecting", "connecting", "disconnecting"]
        .find(s => root.classList.contains(`noVNC_${s}`)) || "idle";
    const asking = () => !!document.querySelector("#noVNC_credentials_dlg.noVNC_open");

    const ICON = '<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="20" height="14" ' +
        'rx="2"/><path d="M8 21h8M12 17v4"/></svg>';
    const el = (tag, cls, text) => Object.assign(document.createElement(tag), cls ? { className: cls } : {},
        text !== undefined ? { textContent: text } : {});

    // Ask noVNC for the screen now: its own waiting timer brought forward, or — where it keeps none — the call its
    // Connect button makes. A connect that fails at once (noVNC catches its own `new RFB`) leaves it `disconnected`
    // in the same task, a change the observer never sees (idle to idle): counted here as the failed try it is.
    function connectNow() {
        if (UI.reconnectCallback !== null && UI.reconnectCallback !== undefined) {
            clearTimeout(UI.reconnectCallback);
            UI.reconnectCallback = null;
        }
        if (UI.rfb) return;
        UI.connect(null, UI.reconnectPassword);
        if (!UI.rfb && state() === "idle") { failed(); show("waiting"); }
    }

    // A screen the sign-in refuses (it lapsed while the screen was open) is not a browser that is down: its
    // websocket is refused like any other. So the page's own address is asked once, without following it: an
    // answer that sends elsewhere, or refuses, means the person has to sign in again — said, and not retried.
    async function signedOut() {
        try {
            const r = await fetch(location.href, { cache: "no-store", credentials: "same-origin", redirect: "manual" });
            return r.type === "opaqueredirect" || r.status === 401 || r.status === 403;
        } catch (e) {
            return false;   // nothing answered: the browser (or the office), not the sign-in
        }
    }
    // the sign-in is the WINDOW's: the console around the frame when it is this page's own origin, else this page
    function signInAgain() {
        try { window.top.location.reload(); } catch (e) { location.reload(); }
    }
    let lapsed = false;

    function hide() {
        if (over) { over.remove(); over = null; }
        sheet.media = "not all";
    }

    // kind: "first" (a first connect that is slow) · "trying" (a retry under way) · "waiting" (until the next one)
    function show(kind) {
        if (!styled || asking()) { hide(); return; }
        sheet.media = "all";
        if (!over) {
            over = el("div", "b42 b42-over");
            over.setAttribute("dir", "rtl");
            over.setAttribute("lang", "he");
            const card = el("div", "xn-card");
            const ic = el("span", "xn-ic");
            ic.innerHTML = ICON;
            const now = el("button", "btn");
            now.type = "button";
            now.addEventListener("click", () => (lapsed ? signInAgain() : connectNow()));
            const acts = el("div", "xn-acts");
            acts.append(now);
            const raw = el("details");
            raw.append(el("summary", "", "מה ענה המסך"), el("pre"));
            card.append(ic, el("h2"), el("div", "xn-sub"), el("p"), acts, raw);
            const wall = el("div", "xn");
            wall.append(card);
            over.append(wall);
            document.body.append(over);
        }
        if (lapsed) kind = "signin";
        const first = kind === "first";
        over.querySelector("h2").textContent = first ? "מתחבר למסך של דפדפן הלשכה"
            : kind === "signin" ? "הכניסה לדפדפן הלשכה פגה" : "המסך של דפדפן הלשכה לא מתחבר";
        over.querySelector("p").textContent = first ? "הדפדפן מופעל על המחשב של הלשכה. המסך יעלה בעוד רגע."
            : kind === "signin" ? "הדפדפן עצמו עונה, אבל הכניסה שלך אליו פגה. אחרי כניסה מחדש המסך יחזור לכאן."
            : "הדפדפן של הלשכה לא עונה כרגע. ייתכן שהוא עולה מחדש. המסך יחזור לבד ברגע שהוא יענה.";
        const sub = over.querySelector(".xn-sub");
        const n = `ניסיון ${Math.max(1, first ? 1 : failures + (kind === "trying" ? 1 : 0))}`;
        sub.textContent = kind === "waiting"
            ? `מנסה שוב ${left <= 1 ? "בעוד שנייה" : `בעוד ${left} שניות`} · ${n}`
            : kind === "trying" ? `מנסה עכשיו · ${n}` : kind === "signin" ? "לא מנסה שוב בלי כניסה" : n;
        if (kind === "first" || kind === "trying") {
            const spin = el("span", "b42-spin");
            spin.setAttribute("aria-hidden", "true");
            sub.prepend(spin);
        }
        const now = over.querySelector("button");
        now.textContent = kind === "signin" ? "כניסה מחדש" : "נסה עכשיו";
        now.title = kind === "signin" ? "טוען את הדף מחדש, דרך הכניסה של הלשכה"
            : "מבקש את המסך מהדפדפן עכשיו, בלי לחכות לניסיון הבא";
        over.querySelector(".xn-acts").hidden = first;
        now.disabled = kind === "trying";
        over.querySelector("details").hidden = first || !said;
        over.querySelector("pre").textContent = said ? `noVNC: ${said}` : "";
    }

    function stopWaiting() {
        clearInterval(tick);
        tick = null;
    }

    // One more try failed: wait, then try again. While noVNC waits (`reconnecting`) its own timer fires, at its own
    // delay, and the count only shows it; while it does not (`idle`), the end of the count is the try — and those
    // tries grow apart (5, 10, 20, then every 30 seconds), so a screen that stays away is not asked for forever at
    // the pace of the first minute. Only while the card can stand (its sheet arrived): without it, noVNC's own page
    // stays exactly as it was, Connect button and all.
    function failed() {
        failures += 1;
        // what noVNC said — only when its line is a failure: a screen that closed cleanly (the browser stopped)
        // leaves its last line standing, «Connected (unencrypted) to root@<container>» (measured, the proof walk)
        const line = document.getElementById("noVNC_status");
        said = line && /\bnoVNC_status_(error|warn)\b/.test(line.className) ? (line.textContent || "").trim() : "";
        const base = Math.ceil((parseInt(UI.getSetting("reconnect_delay"), 10) || 5000) / 1000);
        left = state() === "reconnecting" ? base : Math.min(30, base * 2 ** Math.min(failures - 1, 3));
        stopWaiting();
        arm();
    }
    // noVNC's own timer, when it keeps one: a lapsed sign-in asks no more
    function quietNoVNC() {
        if (UI.reconnectCallback === null || UI.reconnectCallback === undefined) return;
        clearTimeout(UI.reconnectCallback);
        UI.reconnectCallback = null;
    }
    // The count, and the question whether the sign-in lapsed. Armed by a failure — or when the sheet arrives after
    // one (the card could not stand before, and its count must not stand still once it does).
    function arm() {
        if (lapsed) { quietNoVNC(); return; }
        if (!styled || tick) return;
        signedOut().then((out) => {
            if (!out) return;
            lapsed = true;
            stopWaiting();
            quietNoVNC();
            show("signin");
        });
        tick = setInterval(() => {
            left -= 1;
            if (left <= 0 && state() === "idle" && !UI.rfb) {
                stopWaiting();
                connectNow();
                return;
            }
            left = Math.max(1, left);
            show("waiting");
        }, 1000);
    }

    function draw() {
        const s = state(), was = prev;
        prev = s;
        clearTimeout(slow); slow = null;
        if (s === "connected") { failures = 0; leaving = false; lapsed = false; stopWaiting(); hide(); return; }
        if (s === "disconnecting") { leaving = true; stopWaiting(); hide(); return; }
        if (s === "connecting") {
            leaving = false;   // a Connect after the person's own Disconnect is a try like any other
            stopWaiting();
            if (failures > 0) show("trying");
            else if (!over) slow = setTimeout(() => { if (state() === "connecting") show("first"); }, SLOW_MS);
            return;
        }
        // waiting or idle. A fall: from a try or from the screen into either. Idle with no fall is before the first
        // connect, or after the person's own Disconnect (noVNC's panel is theirs) — no card then.
        if (s !== was && !leaving && (s === "reconnecting" || was === "connecting" || was === "connected")) failed();
        if (leaving || failures === 0) hide(); else show("waiting");
    }

    new MutationObserver(draw).observe(root, { attributes: true, attributeFilter: ["class"] });
    const dlg = document.getElementById("noVNC_credentials_dlg");
    if (dlg) new MutationObserver(draw).observe(dlg, { attributes: true, attributeFilter: ["class"] });
    draw();
}
