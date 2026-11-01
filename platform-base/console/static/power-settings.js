/* power-settings.js — the "חשמל ושינה" card in the console's settings view (הגדרות מסוף).
 *
 * The office runs in a VM on the machine the owner is looking at. When that machine sleeps, the VM
 * stops, and with it every app and every agent until it wakes (measured 2026-09-29: agents spent 28
 * of 43 "running" hours frozen because a MacBook slept ~7 s after its display went off). Here the
 * owner chooses, per situation, whether the office keeps working; a small agent on the machine
 * (packaging/macos/power-agent.py) enforces it and reports what it sees. Policy and status go
 * through the machine service (/a/machine/api/power), which owns host facts.
 *
 * Mounted by desktop.js renderSettings() under the desktop-mode card: BinaPower.render(el).
 * Strings are Hebrew; engine values (thermal names, event causes, guard reasons) go through the
 * maps below and never reach the page raw.
 */
(function () {
  "use strict";

/* @bina-said:start */
var binaSaid = (status) => (!status ? "אין תשובה מהשירות"
  : status < 300 ? "התשובה אינה מה שהמסך ציפה לו — רענן את הדף"
  : status === 401 ? "הכניסה פגה — רענן את הדף" : status === 403 ? "אין הרשאה לפעולה הזאת"
  : status === 404 ? "השירות לא מכיר את הבקשה הזאת"
  : status > 501 && status < 505 ? "השירות אינו זמין כרגע" : status >= 500 ? "השירות נתקל בשגיאה"
  : "הבקשה נדחתה");
// a request that could not even be sent answers like one that was refused, with status 0
var binaNoAnswer = () => ({ ok: false, status: 0, json: async () => ({}), text: async () => "" });
/* @bina-said:end */

  const API = "/a/machine/api/power";
  // an answer that will not parse (the sign-in page, with a 200) is named, not quoted
  const read = (r) => r.json().catch(() => { throw new Error(binaSaid(200)); });
  const POLL_MS = 15000;

  const THERMAL_HE = { nominal: "תקין", fair: "חם מעט", serious: "חם", critical: "חם מאוד" };
  const CAUSE_HE = {
    idle: "המסך כבה / אין פעילות", "lid-closed": "המכסה נסגר", "battery-empty": "הסוללה התרוקנה",
    overheated: "התחממות", menu: "שינה מהתפריט", button: "כפתור ההפעלה",
    "lid-opened": "המכסה נפתח", user: "מקלדת או משטח מגע", other: "אחר",
  };
  const SITUATIONS = [
    { key: "lock", title: "המסך ננעל או כבה", sub: "אף אחד לא ליד המקלדת" },
    { key: "lid", title: "המכסה נסגר", sub: "בלי מסך חיצוני" },
  ];
  const SOURCES = [{ key: "ac", title: "מחובר לחשמל" }, { key: "battery", title: "על סוללה" }];
  const FLOORS = [10, 15, 20, 25, 30, 40, 50];

  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ago = s => {
    if (s == null) return "";
    if (s < 2) return "הרגע";
    if (s < 60) return "לפני " + s + " שניות";
    const m = Math.round(s / 60), h = Math.round(s / 3600);
    return s < 3600 ? (m === 1 ? "לפני דקה" : "לפני " + m + " דקות") : (h === 1 ? "לפני שעה" : "לפני " + h + " שעות");
  };
  const when = at => { const m = /^\d{4}-(\d\d)-(\d\d) (\d\d:\d\d)/.exec(at || ""); return m ? m[2] + "." + m[1] + " " + m[3] : esc(at); };

  function guardHe(g) {
    let m = /^battery below (\d+)%$/.exec(g); if (m) return "הסוללה מתחת ל-" + m[1] + "%";
    m = /^thermal pressure: (\w+)$/.exec(g); if (m) return "עומס חום (" + (THERMAL_HE[m[1]] || m[1]) + ")";
    if (g === "the engine is not running") return "המנוע של הלשכה לא רץ";
    return g;
  }

  function injectCss() {
    if (document.getElementById("bina-power-css")) return;
    const st = document.createElement("style");
    st.id = "bina-power-css";
    // Hairline strips/grids (key over value), the same pattern as the product's fact strips; tokens only.
    st.textContent = [
      ".pw-strip,.pw-matrix,.pw-events{display:grid;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:12px;overflow:hidden}",
      ".pw-strip{grid-template-columns:repeat(4,minmax(0,1fr));margin:2px 0 8px}",
      ".pw-cell{background:var(--surface);padding:9px 12px;min-width:0}",
      ".pw-k{display:block;font-size:11px;color:var(--muted)}",
      ".pw-v{display:block;font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".pw-live{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:0 0 14px}",
      ".pw-matrix{grid-template-columns:minmax(150px,1.1fr) 1fr 1fr}",
      ".pw-matrix>div{background:var(--surface);padding:10px 12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}",
      ".pw-matrix .pw-h{font-size:11px;color:var(--muted);font-weight:700}",
      ".pw-row b{display:block;font-size:13px}.pw-row span{display:block;font-size:12px;color:var(--muted)}",
      ".pw-seg{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:2px;background:var(--surface-2)}",
      ".pw-seg button{font:inherit;font-size:12px;font-weight:700;border:0;background:transparent;color:var(--muted);padding:4px 11px;border-radius:999px;cursor:pointer;min-height:28px}",
      ".pw-seg button[aria-pressed=true]{background:var(--accent);color:var(--accent-ink)}",
      ".pw-seg button[aria-pressed=true][data-v=sleep],.pw-seg button[aria-pressed=true][data-v=off]{background:var(--muted);color:var(--surface)}",
      ".pw-seg[aria-busy=true]{opacity:.6;pointer-events:none}",
      ".pw-idle .pw-matrix,.pw-idle .pw-guards,.pw-idle .pw-strip{opacity:.55}",
      ".pw-guards{margin-top:6px}",
      ".pw-guards .dk-row select{min-height:30px}",
      ".pw-callout{border:1px solid var(--warn);background:var(--warn-soft);border-radius:12px;padding:12px 14px;margin-top:14px;font-size:13px}",
      ".pw-callout.bad{border-color:var(--danger);background:var(--danger-soft)}",
      ".pw-callout h4{margin:0 0 4px;font-size:13px}.pw-callout p{margin:0 0 8px}",
      ".pw-callout pre{direction:ltr;text-align:left;unicode-bidi:isolate;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:11.5px;overflow:auto;max-height:170px;white-space:pre;margin:6px 0 8px}",
      ".pw-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}",
      ".pw-callout details{margin-top:8px;font-size:12px;color:var(--muted)}",
      ".pw-sec{font-size:13px;font-weight:700;margin:18px 0 6px}",
      ".pw-events{list-style:none;margin:0;padding:0}",
      ".pw-events li{background:var(--surface);display:flex;gap:10px;align-items:center;padding:7px 12px;font-size:12.5px;min-width:0}",
      ".pw-events .pw-t{color:var(--muted);min-width:84px}",
      ".pw-events .pw-e{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "@media (max-width:640px){.pw-strip{grid-template-columns:repeat(2,minmax(0,1fr))}",
      " .pw-matrix{grid-template-columns:1fr}.pw-matrix .pw-colh{display:none}",
      " .pw-matrix .pw-src::before{content:attr(data-src);font-size:11px;color:var(--muted);flex-basis:100%}}",
    ].join("\n");
    document.head.appendChild(st);
  }

  function render(host) {
    injectCss();
    const card = document.createElement("div");
    card.className = "wcard dk-set pw";
    card.innerHTML = '<h3>חשמל ושינה</h3><div class="sub">הלשכה רצה במכונה וירטואלית על המחשב הזה. כשהמחשב נכנס לשינה הכל נעצר — גם הסוכנים — עד שהוא מתעורר. כאן בוחרים מה הלשכה עושה בכל מצב.</div><div class="pw-body"><div class="pw-live">טוען את מצב המחשב…</div></div>';
    host.appendChild(card);
    const body = card.querySelector(".pw-body");
    let data = null, saved = null, timer = 0;

    async function load() {
      try {
        const r = await fetch(API, { headers: { Accept: "application/json" }, credentials: "same-origin" }).catch(binaNoAnswer);
        if (!r.ok) throw new Error(binaSaid(r.status));
        data = await read(r);
        draw();
      } catch (e) {
        body.innerHTML = '<div class="pw-callout bad"><h4>לא ניתן לקרוא את מצב החשמל</h4><p>שירות «מכונה»: ' +
          esc(e.message) + ". נסה שוב בעוד רגע.</p></div>";
      }
    }

    async function save(patch, seg) {
      if (seg) seg.setAttribute("aria-busy", "true");
      try {
        const r = await fetch(API + "/policy", {
          method: "PUT", credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(patch),
        }).catch(binaNoAnswer);
        if (!r.ok) throw new Error(binaSaid(r.status));
        data.policy = (await read(r)).policy;
        saved = { ok: true, at: Date.now() };
      } catch (e) {
        saved = { ok: false, at: Date.now(), msg: e.message };
      }
      draw();
    }

    function segHtml(name, value, options) {
      return '<div class="pw-seg" role="group" data-name="' + name + '">' + options.map(o =>
        '<button type="button" data-v="' + o.v + '" aria-pressed="' + (o.v === value) + '" title="' + esc(o.title) + '">' + esc(o.label) + "</button>").join("") + "</div>";
    }

    function draw() {
      if (!card.isConnected) { clearInterval(timer); return; }
      const p = data.policy, s = data.status, agent = data.agent;
      // A Windows host has no power agent YET: that is a fact about the machine, not a fault, and
      // the command that starts the Mac's agent is not what its owner should be told to run.
      const onWindows = agent === "absent" && data.host_os === "windows";
      // What is not enforced does not look in force: the switches stayed bright green right over
      // «ההגדרות לא נאכפות כרגע». They can still be set — they are what the agent will apply.
      card.classList.toggle("pw-idle", agent !== "running");
      const live = agent === "running" ? '<span class="chip healthy">סוכן החשמל פעיל</span><span>עודכן ' + ago(data.age_s) + "</span>"
        : agent === "stale" ? '<span class="chip degraded">סוכן החשמל הפסיק לדווח</span><span>דיווח אחרון ' + ago(data.age_s) + "</span>"
        : onWindows ? '<span class="chip unset">אין סוכן חשמל ל-Windows</span>'
        : '<span class="chip degraded">סוכן החשמל לא רץ</span>';
      const savedHtml = saved && Date.now() - saved.at < 8000
        ? (saved.ok ? '<span class="pill ok">נשמר · חל תוך 15 שניות</span>' : '<span class="chip degraded">השמירה נכשלה</span>') : "";
      let html = "";
      if (s) {
        const pw = s.power || {}, lid = s.lid || {}, th = s.thermal || {};
        html += '<div class="pw-strip">' +
          cell("חשמל", (pw.source === "battery" ? "סוללה" : "מחובר לחשמל") + (pw.percent != null ? ' · <span class="num">' + pw.percent + "%</span>" : "")) +
          cell("מכסה", lid.closed ? "סגור" : "פתוח") +
          cell("מסך", s.screen_locked ? "נעול" : "פעיל") +
          cell("חום", THERMAL_HE[th.name] || "לא ידוע") + "</div>";
      }
      html += '<div class="pw-live">' + live + savedHtml + "</div>";

      // what the office does, per situation × power source
      const eff = s && s.effective, src = eff ? eff.source : null;
      html += '<div class="pw-matrix"><div class="pw-h pw-colh"></div>' + SOURCES.map(c => '<div class="pw-h pw-colh">' + c.title + "</div>").join("");
      SITUATIONS.forEach(sit => {
        html += '<div class="pw-row"><div><b>' + sit.title + "</b><span>" + sit.sub + "</span></div></div>";
        SOURCES.forEach(c => {
          const v = p[sit.key][c.key];
          html += '<div class="pw-src" data-src="' + c.title + '">' + segHtml(sit.key + "." + c.key, v, [
            { v: "run", label: "להמשיך לעבוד", title: "המחשב נשאר ער והלשכה ממשיכה לעבוד" },
            { v: "sleep", label: "לישון", title: "המחשב נכנס לשינה כרגיל והלשכה נעצרת עד שהוא מתעורר" },
          ]) + (src === c.key ? nowChip(sit.key, v, s) : "") + "</div>";
        });
      });
      html += "</div>";

      // guards
      html += '<div class="pw-guards">' +
        '<label class="dk-row"><b>סף סוללה</b><select data-k="battery_floor" title="מתחת לסף הזה, על סוללה, המחשב ישן כרגיל">' +
        FLOORS.map(n => "<option value=\"" + n + "\"" + (p.battery_floor === n ? " selected" : "") + ">" + n + "%</option>").join("") +
        '</select><span class="sub">מתחת לסף, על סוללה, המחשב ישן כרגיל כדי לא להתרוקן</span></label>' +
        '<div class="dk-row"><b>הגנת חום</b>' + segHtml("thermal_guard", p.thermal_guard ? "on" : "off", [
          { v: "on", label: "פעילה", title: "חום קריטי, או חום רב במשך 5 דקות — המחשב ישן כדי להתקרר" },
          { v: "off", label: "כבויה", title: "הלשכה ממשיכה גם כשהמחשב חם מאוד (לא מומלץ עם מכסה סגור)" },
        ]) + '<span class="sub">חום קריטי, או חום רב 5 דקות — המחשב ישן כדי להתקרר</span></div></div>';

      if (eff && eff.guards && eff.guards.length) {
        html += '<div class="pw-callout"><h4>המחשב מורשה לישון עכשיו</h4><p>' + eff.guards.map(guardHe).map(esc).join(" · ") + "</p></div>";
      }
      if (agent !== "running") {
        // The command is a token on a line of its own: inline, the sentence's full stop landed in
        // front of "./" and it read as a path one directory up.
        html += onWindows
          ? '<div class="pw-callout"><h4>במחשב הזה ההגדרות לא נאכפות</h4><p>הלשכה רצה כאן על Windows, ועדיין אין לה סוכן שמונע ' +
            'מהמחשב לישון. מה שקורה כשהמכסה נסגר או כשהמסך ננעל נקבע בהגדרות החשמל של Windows; מה שנבחר כאן יחול ' +
            'כשיהיה סוכן כזה.</p></div>'
          : '<div class="pw-callout bad"><h4>ההגדרות לא נאכפות כרגע</h4><p>סוכן החשמל רץ על המחשב עצמו ומתחיל עם המנוע של הלשכה. ' +
          'בשרת אין שינה, ואין כאן מה להגדיר. במק מפעילים אותו כך:</p>' +
          '<pre class="pw-cmd" dir="ltr">./bbox engine power start</pre></div>';
      }
      const wantsLid = p.lid.ac === "run" || p.lid.battery === "run";
      if (s && wantsLid && !s.lid_permission) {
        html += '<div class="pw-callout"><h4>הרשאה חד-פעמית כדי לעבוד כשהמכסה סגור</h4>' +
          "<p>macOS מכניס את המחשב לשינה כשהמכסה נסגר, ושום תוכנה לא יכולה למנוע את זה בלי הרשאת מנהל. " +
          "ההרשאה מתירה רק שלוש פקודות: הפעלה וכיבוי של מניעת השינה, והכנסה לשינה. בכל הפעלה של המחשב המניעה מתאפסת מעצמה. " +
          "מריצים פעם אחת ב-Terminal (תתבקש סיסמת מנהל):</p><pre>" + esc(s.setup.grant) + "</pre>" +
          '<div class="pw-actions"><button class="btn sm" type="button" data-act="copy" title="מעתיק את הפקודות ללוח">העתק את הפקודות</button>' +
          '<button class="btn ghost sm" type="button" data-act="recheck" title="קורא שוב את מצב ההרשאה מהמחשב">בדוק שוב</button></div>' +
          "<details><summary>חלופה בלי הרשאה, ואיך מבטלים</summary><p>בלי הרשאה: מחובר לחשמל ועם מסך חיצוני, macOS ממשיך לעבוד גם כשהמכסה סגור.</p>" +
          "<p>שים לב: עם מכסה סגור המחשב מתקרר פחות. אל תכניס אותו לתיק כשהלשכה עובדת.</p>" +
          '<p>ביטול ההרשאה:</p><pre>' + esc(s.setup.revoke) + "</pre></details></div>";
      }

      if (s && s.events && s.events.length) {
        html += '<div class="pw-sec">מה קרה לאחרונה' + (s.asleep_last_24h_h != null ? ' · ב-24 השעות האחרונות המחשב ישן <span class="num">' + s.asleep_last_24h_h + "</span> שעות" : "") + "</div>";
        html += '<ul class="pw-events">' + s.events.slice(-6).reverse().map(ev =>
          '<li><span class="pw-t num">' + when(ev.at) + '</span><span class="pw-e">' +
          (ev.kind === "Sleep" ? "נכנס לשינה" : "התעורר") + " — " + esc(CAUSE_HE[ev.cause] || CAUSE_HE.other) +
          (ev.on ? " · " + (ev.on === "battery" ? "סוללה" : "חשמל") : "") + "</span></li>").join("") + "</ul>";
      }
      body.innerHTML = html;
      wire();
    }

    function cell(k, v) { return '<div class="pw-cell"><span class="pw-k">' + k + '</span><span class="pw-v">' + v + "</span></div>"; }

    function nowChip(key, v, s) {
      if (v === "sleep") return '<span class="chip checking">חל עכשיו</span>';
      if (key === "lid" && !s.lid_permission) return '<span class="chip needs_action">ממתין להרשאה</span>';
      return s.effective[key] === "run" ? '<span class="chip healthy">חל עכשיו · ער</span>' : '<span class="chip needs_action">חל עכשיו · מושהה</span>';
    }

    function wire() {
      body.querySelectorAll(".pw-seg").forEach(seg => {
        seg.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
          if (b.getAttribute("aria-pressed") === "true") return;
          const name = seg.dataset.name, v = b.dataset.v;
          if (name === "thermal_guard") return save({ thermal_guard: v === "on" }, seg);
          const [key, src] = name.split(".");
          save({ [key]: { [src]: v } }, seg);
        }));
      });
      const floor = body.querySelector('select[data-k="battery_floor"]');
      if (floor) floor.addEventListener("change", () => save({ battery_floor: Number(floor.value) }));
      const copy = body.querySelector('[data-act="copy"]');
      if (copy) copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(data.status.setup.grant); copy.textContent = "הועתק"; }
        catch (e) { copy.textContent = "סמן והעתק ידנית"; }
      });
      const re = body.querySelector('[data-act="recheck"]');
      if (re) re.addEventListener("click", () => { re.textContent = "בודק…"; setTimeout(load, 16000); });
    }

    load();
    timer = setInterval(() => { if (!card.isConnected) { clearInterval(timer); return; } load(); }, POLL_MS);
  }

  window.BinaPower = { render };
})();
