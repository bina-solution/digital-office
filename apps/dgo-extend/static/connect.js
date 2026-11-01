// connect.js — the pairing screens of dgo-extend: show a code, scan a code, paste a code.
//
// The three doors in ai/context/dgo-extend-plan.md §8 all produce the SAME object — a pairing offer
// — and this file is built around that: one encoder, one parser, one summary, three ways to get the
// text in. What the screen must never do is invent a secret: the offer carries public material only
// (office id, identity public key, ephemeral public key, endpoints, a rendezvous id, an expiry), it
// is what a photographed QR would leak, and the grant itself is written on the server.
//
// THE SERVER CONTRACT this page speaks (pair_api.py owns it; the format is pairing.py's):
//
//   POST api/pair/offer            {direction}          → {rendezvous_id, text, offer, expires_at}
//   GET  api/pair/offer/<rid>                            → {state, code?, peer?, expires_at}
//                                                          state: waiting | claimed | confirmed | expired
//   POST api/pair/reply            {text}               → {state, rendezvous_id, code, peer}
//   POST api/pair/offer/<rid>/confirm  {code}            → {ok, link:{…}}
//   POST api/pair/claim            {text, direction}     → {rendezvous_id, code, peer, reply_text, expires_at}
//   POST api/pair/claim/<rid>      {confirm:true, code}  → {ok, link:{…}}
//
// TWO CODES, BOTH VISUAL. The joining office shows an OFFER; the hosting office reads it and shows a
// REPLY; the joining office reads that back. Nothing crosses a network during a pairing, so it works
// between two machines that accept no inbound connection at all — the only network fact a pairing
// carries is where the tunnel will be dialed afterwards.
//
// WHY THE CODE IS SHOWN ON BOTH SCREENS BEFORE ANY WRITE: the same ECDH-derived six digits rendered
// independently on the two machines is what turns "someone scanned a QR" into "these two people are
// looking at the same link". A tap that agreed without it would approve whatever the camera
// delivered, so each office writes only on its own operator's confirmation.
"use strict";

// ── the codes: one format, three doors ──────────────────────────────────────────────────────────
// `DGOPAIR1:` + base64url(JSON) is an OFFER and `DGOPAIRR1:` + base64url(JSON) is a REPLY — exactly
// what apps/dgo-extend/pairing.py writes and reads (`offer_text` / `reply_text`); the gate runs both
// languages against each other (tests/pair_contract.py), because the first version of this page spoke
// a format of its own and nothing noticed. The SAME string is displayed as six whitespace-separated
// groups so a person can read it aloud or type it. The prefix is the version: a future format is
// `DGOPAIR2:` and an old reader refuses it by name instead of mis-parsing it.
var OFFER_PREFIX = "DGOPAIR1:";
var REPLY_PREFIX = "DGOPAIRR1:";
var OFFER_GROUPS = 6;
var OFFER_TTL_S = 600;                       // an offer lives ten minutes
// the fields of the WIRE offer a reader must find (pairing.parse_offer refuses the same ones)
var OFFER_FIELDS = ["offer_id", "office", "identity", "ephemeral", "expires_at"];

function b64urlEncode(str) {
  var bytes = new TextEncoder().encode(str);
  var bin = "";
  for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(s) {
  var t = String(s).replace(/-/g, "+").replace(/_/g, "/");
  while (t.length % 4) t += "=";
  var bin = atob(t);
  var bytes = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

function stripSpace(s) {
  return String(s == null ? "" : s).replace(/\s+/g, "");
}

// The display form: the same characters, grouped so a human can carry them across a room without
// losing their place. Grouping is presentation only — `ungroup` is the inverse and the parser always
// ungroups first, so a code that was typed back with different spacing still parses.
function groupText(text, groups) {
  var t = stripSpace(text);
  var n = Math.max(1, groups || OFFER_GROUPS);
  var size = Math.ceil(t.length / n);
  var out = [];
  for (var i = 0; i < t.length; i += size) out.push(t.slice(i, i + size));
  return out.join(" ");
}

// encodeOffer takes the WIRE object (what the server minted) — the page never invents an offer; this
// exists for the simulation and the contract test, which need to produce the text a server would.
function encodeOffer(offer) {
  return OFFER_PREFIX + b64urlEncode(JSON.stringify(offer));
}

// Which of the two codes is this? By prefix, after dropping the display spaces — asked before any
// parsing, because a reply pasted where an offer is expected must be routed, not rejected.
function kindOf(text) {
  var t = stripSpace(text);
  if (t.indexOf(REPLY_PREFIX) === 0) return "reply";
  if (t.indexOf(OFFER_PREFIX) === 0) return "offer";
  return "";
}

// parseOffer is the only reader of the offer on this side, and it fails in Hebrew with the reason —
// an offer that is a screenshot of the wrong thing, truncated, or from a future version must say
// which. It returns the VIEW the screens draw (office_id, fingerprint, endpoints, …) and keeps the
// untouched wire object under `wire`. A reply is never parsed here: its payload is sealed, and the
// server is the one holding the key that opens it.
function parseOffer(text) {
  var t = stripSpace(text);
  if (!t) throw new Error("לא הודבק קוד");
  if (t.indexOf(REPLY_PREFIX) === 0) throw new Error("זה קוד תשובה, לא הצעת הצטרפות");
  if (t.indexOf(OFFER_PREFIX) !== 0) {
    var m = /^(DGOPAIR\d+|dgo\d+):/.exec(t);
    if (m) throw new Error("הקוד בפורמט " + m[1] + " — הגרסה הזו קוראת " + OFFER_PREFIX + " בלבד");
    throw new Error("זה לא קוד הצטרפות — הוא אמור להתחיל ב־" + OFFER_PREFIX);
  }
  var obj;
  try {
    obj = JSON.parse(b64urlDecode(t.slice(OFFER_PREFIX.length)));
  } catch (e) {
    throw new Error("הקוד אינו קריא — כנראה הועתק חסר (חסרים תווים בסוף)");
  }
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) throw new Error("הקוד אינו הצעה תקפה");
  var missing = OFFER_FIELDS.filter(function (f) { return obj[f] === undefined || obj[f] === null || obj[f] === ""; });
  if (missing.length) throw new Error("בהצעה חסרים שדות: " + missing.join(", "));
  var ident = obj.identity || {};
  if (typeof ident !== "object" || !ident.ed25519) throw new Error("בהצעה אין זהות של הלשכה המצטרפת");
  return {
    office_id: String(obj.office),
    label: String(obj.label || obj.office),
    identity_pubkey: String(ident.ed25519),
    fingerprint: String(ident.fingerprint || ""),
    ephemeral_pubkey: String(obj.ephemeral),
    // an office that can only DIAL publishes no address, and that is a legitimate offer
    endpoints: Array.isArray(obj.endpoints) ? obj.endpoints : [],
    rendezvous_id: String(obj.offer_id),
    expires_at: Number(obj.expires_at) || 0,
    direction: obj.direction || "",
    wire: obj
  };
}

function offerExpired(offer, now) {
  var ts = Number(offer && offer.expires_at) || 0;
  if (!ts) return false;
  var t = typeof now === "number" ? now : Date.now() / 1000;
  return ts < t;
}

// The six digits both screens must agree on. Compared as digits, never as a string: one screen may
// render them with a separator and the other without, and that is not a mismatch.
function digitsOf(code) { return String(code == null ? "" : code).replace(/\D/g, ""); }
function codesMatch(a, b) {
  var x = digitsOf(a), y = digitsOf(b);
  return x.length > 0 && x === y;
}

function formatCountdown(seconds) {
  var s = Math.max(0, Math.floor(seconds || 0));
  var m = Math.floor(s / 60);
  return m + ":" + String(s % 60).padStart(2, "0");
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

// A Hebrew sentence that carries a Latin token — a prefix, a route, an id. The token becomes ONE
// left-to-right word (`.tok`), so its own punctuation stays on its own side: unwrapped, the colon of
// `DGOPAIR1:` was drawn on the far side of the word. Split BEFORE escaping, so an entity is never cut.
function hebrewWithTokens(text) {
  var str = String(text == null ? "" : text), out = "", last = 0, m;
  var re = /[A-Za-z][A-Za-z0-9_.\/-]*:?(?: \d[\d.:]*)*/g;
  while ((m = re.exec(str))) {
    out += escapeHtml(str.slice(last, m.index)) + '<span class="tok">' + escapeHtml(m[0]) + "</span>";
    last = m.index + m[0].length;
  }
  return out + escapeHtml(str.slice(last));
}

// A sentence the SERVER worded, in which a `backticked` run is something a person types or looks for
// (a file, a line of configuration, a command). The run becomes one token; nothing else is guessed —
// `hebrewWithTokens` would cut `networkingMode=mirrored` in two at the equals sign.
function ticks(text) {
  return escapeHtml(text).replace(/`([^`]+)`/g, '<span class="tok">$1</span>');
}

// A sentence from the server, whichever way it marks what is to be typed: the server's own marks win
// (a command of several words is ONE token), and a sentence with none is read for Latin runs.
function sentence(text) {
  return /`[^`]+`/.test(String(text == null ? "" : text)) ? ticks(text) : hebrewWithTokens(text);
}

// THE REFUSAL THAT IS A DECISION, not an error: the office already holds a record under the other
// office's name, so the server answers 409 and names `replace` (pair_api._guard_replace). It is taken
// on whichever screen met it — and BOTH screens must offer it: the copy of this that lived inside
// `claim` alone left the JOINING screen with no way forward at all, at the END of the flow, after both
// codes had been exchanged (measured 2026-10-11: the owner pressed אישור and the office's whole answer
// was «כדי להחליף אותה שלחו replace: true» — a protocol instruction, with nothing to press).
// The sentence returned is the platform's own, with that instruction taken off; "" means it is not this.
function replaceRefusal(err) {
  var status = Number((err || {}).status) || 0;
  var message = String((err || {}).message || "");
  if (status !== 409 || !/replace/.test(message)) return "";
  return message.replace(/\s*כדי להחליף[^.]*\.?\s*$/, "").trim();
}

// describeOffer — what a person must see BEFORE agreeing, in the order they need it.
function describeOffer(offer) {
  var eps = (offer.endpoints || []).map(function (e) {
    return typeof e === "string" ? e : [e.host, e.port].filter(Boolean).join(":");
  });
  return {
    office_id: String(offer.office_id || ""),
    fingerprint: String(offer.fingerprint || shortFingerprint(offer.identity_pubkey)),
    endpoints: eps,
    rendezvous_id: String(offer.rendezvous_id || ""),
    expires_at: Number(offer.expires_at) || 0
  };
}

// A fingerprint a person can compare aloud: the first four groups' worth of characters of the
// identity key, uppercase. Not a security boundary on its own — the six-digit code is — it exists so
// two screens can be told apart at a glance.
function shortFingerprint(pub) {
  var s = stripSpace(pub).replace(/^ed25519:/, "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  if (!s) return "";
  return (s.slice(0, 4) + "-" + s.slice(4, 8));
}

// ─────────────────────────────────────────────────────────────────────────────────────────────────
// The browser half. Guarded so the pure half above is testable in node (tests/connect-selftest.mjs).
// ─────────────────────────────────────────────────────────────────────────────────────────────────
var API = {
  OFFER_PREFIX: OFFER_PREFIX, REPLY_PREFIX: REPLY_PREFIX, OFFER_GROUPS: OFFER_GROUPS,
  OFFER_TTL_S: OFFER_TTL_S, OFFER_FIELDS: OFFER_FIELDS, kindOf: kindOf,
  encodeOffer: encodeOffer, parseOffer: parseOffer, groupText: groupText, stripSpace: stripSpace,
  offerExpired: offerExpired, codesMatch: codesMatch, digitsOf: digitsOf,
  formatCountdown: formatCountdown, describeOffer: describeOffer, shortFingerprint: shortFingerprint,
  hebrewWithTokens: hebrewWithTokens, ticks: ticks, sentence: sentence,
  replaceRefusal: replaceRefusal
};
if (typeof module !== "undefined" && module.exports) { module.exports = API; }
if (typeof window !== "undefined") { window.DgoConnect = API; }

if (typeof document !== "undefined") (function () {
  var $ = function (id) { return document.getElementById(id); };
  var esc = escapeHtml;
  var MODES = ["show", "scan", "paste"];
  var mode = "show";
  var NAV = null, QR_LIB = (typeof qrcode === "function") ? qrcode : null;
  // `role` is which office this screen is in THIS pairing: the joiner showed the offer and confirms
  // on the offer's route; the host read it and confirms on the claim's. It decides the confirm route,
  // so it is set where the server answered, never guessed from which panel is open.
  var state = { offer: null, rid: null, timer: null, poll: null, code: null, link: null,
                scanner: null, stream: null, role: null, zoom: 1, cam: null };

  // ── one place every server call goes through, so the "not built yet" answer is one behaviour ──
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
  async function api(path, opts) {
    var r = await fetch(path, opts).catch(binaNoAnswer);
    var body = {};
    try { body = await r.json(); } catch (e) { /* empty body is a legitimate answer */ }
    if (!r.ok) {
      var err = new Error(body.error || binaSaid(r.status));
      err.status = r.status;
      // THE SERVER'S OWN SENTENCE, when it sent one, is about THIS request — a lost claim, a code
      // that does not match, a record that is already here. Only a body-less 404/405/501 is the
      // route itself missing, and only that one should be guessed at.
      err.said = !!body.error;
      throw err;
    }
    return body;
  }
  function post(p, b) {
    return api(p, { method: "POST", headers: { "content-type": "application/json" },
                    body: JSON.stringify(b || {}) });
  }

  function alerts(html, kind) {
    $("alerts").innerHTML = html ? '<div class="callout ' + (kind || "") + '">' + html + "</div>" : "";
  }

  // A 404/405 with NO sentence from the server is not a user error: it is the server half not having
  // landed yet (pairing.py, DGO-33). Saying which endpoint is missing is the difference between a
  // screen an engineer can finish and one that looks broken.
  // …and a 404 that DID carry a sentence is a different thing entirely: the office answered in its own
  // words — «אין כאן בקשת צימוד חיה במזהה הזה (אולי היא פגה, או שהאפליקציה אותחלה)» — and reading that
  // as "this server is an older version" sends the operator looking for a missing command while the
  // real answer was already on the screen (measured 2026-10-11 12:06: the owner pressed אישור nine
  // times against exactly that sentence).
  function notBuilt(e, path) {
    // The office already says, at the top of this page, why it refuses (it has no identity yet):
    // the same sentence a second time, in red, is noise — the first one is brought into view.
    var known = $("selfRefused");
    if (known && e.status === 409) {
      alerts("");
      try { known.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (x) { /* not fatal */ }
      return false;
    }
    var missing = !e.said && (e.status === 404 || e.status === 405 || e.status === 501);
    alerts(missing
      ? "<b>השרת של הלשכה הזאת אינו מכיר את הפעולה.</b> חסרה לו הפקודה <span class='tok'>" +
        esc(path) + "</span> — הוא מריץ גרסה שקודמת לצימוד מהמסך."
      : "<b>הפעולה נכשלה:</b> " + sentence(e.message), missing ? "warn" : "bad");
    return missing;
  }

  // ── the menu: an app DECLARES its menu, the component builds it (DGO-52) ─────────────────────
  function mountNav() {
    if (NAV || typeof BinaNav === "undefined") return NAV;
    var el = $("sideNav"); if (!el) return null;
    NAV = BinaNav.mount(el, {
      id: "dgo-connect",
      brand: { name: "הצטרפות לשכה", sub: "הרחבת הלשכה", avatar: "ה" },
      sections: [
        { id: "way", title: "דרך החיבור", items: [] }
      ],
      footer: { text: "הקוד נוצר בלשכה הזו · עשר דקות" }
    });
    return NAV;
  }

  // icon names the shared menu actually draws (bina-nav's set): an unknown name falls back to a dot
  var WAYS = { show: { label: "הצגת קוד", icon: "grid" }, scan: { label: "סריקה במצלמה", icon: "image" },
               paste: { label: "הדבקת קוד", icon: "edit" },
               useLabel: { label: "סריקה במצלמה", icon: "camera" } };
  var STEP_NAMES = ["בחירת דרך", "הקוד", "קוד אישור", "סיום"];

  function currentStep() {
    if (state.link) return 3;
    if (state.code) return 2;
    if ((mode === "show" && state.rid && state.role === "joiner") || (mode !== "show" && state.offer && state.role !== "joiner")) return 1;
    return 0;
  }

  function renderNav() {
    var nav = mountNav(); if (!nav) return;
    nav.setItems("way", MODES.map(function (m) {
      return { id: m, label: WAYS[m].label, icon: WAYS[m].icon, title: WAYS[m].label,
               active: m === mode, onClick: function () { setMode(m); } };
    }), 0);
  }

  function renderWays() {
    var host = $("ways"); if (!host) return;
    host.innerHTML = MODES.map(function (m) {
      return '<button type="button" class="btn ' + (m === mode ? "" : "ghost") + ' sm" data-way="' + m +
             '" aria-pressed="' + (m === mode) + '">' + esc(WAYS[m].label) + "</button>";
    }).join("");
    Array.prototype.forEach.call(host.querySelectorAll("button"), function (b) {
      b.addEventListener("click", function () { setMode(b.dataset.way); });
    });
  }

  function setMode(m) {
    if (MODES.indexOf(m) < 0) m = "show";
    mode = m;
    renderWays();
    MODES.forEach(function (x) { $("panel" + x[0].toUpperCase() + x.slice(1)).classList.toggle("hidden", x !== m); });
    $("panelDone").classList.toggle("hidden", !state.link);
    if (m !== "scan") stopCamera();
    renderNav();
  }

  function renderSteps() {
    var cur = currentStep();
    var html = "";
    for (var i = 0; i < 3; i++) {
      html += '<span class="cx-step" data-on="' + (i === cur ? 1 : 0) + '" data-done="' + (i < cur ? 1 : 0) + '">' +
              // a step that is behind you carries the office's drawn check, not a text glyph
              '<span class="n">' + (i < cur ? BinaNav.svg("check") : (i + 1)) + "</span>" + esc(STEP_NAMES[i]) + "</span>";
    }
    $("steps").innerHTML = html;
  }

  // ── the QR itself: the encoder is vendored (static/vendor/qrcode), and drawing is a canvas of
  //    modules — no third-party image tag, nothing fetched, so it renders offline as well.
  function drawQr(text, canvas, level) {
    var cv = canvas || $("qr");
    if (!QR_LIB || !text) { cv.classList.add("hidden"); return; }
    // The reply is the longer of the two codes (a sealed grant and a signature), so it is drawn at
    // the LOW correction level: fewer, larger modules read better off a screen than a denser code
    // that could survive damage a screen never has.
    var qr = QR_LIB(0, level || "M");
    qr.addData(text);
    qr.make();
    // A denser code gets a bigger picture, not smaller modules: the offer fits 280px, the reply (about
    // twice the text) is drawn up to 560px so a laptop camera can still resolve one module.
    // AS LARGE AS THE SCREEN ALLOWS. The other office reads this with a camera, across a desk, and
    // the size of one module on THIS screen is what decides whether it can — 280px was a code a
    // laptop camera could see and not read (measured 2026-10-04). Drawn at whole pixels per module
    // (a fractional scale blurs the edges a decoder looks for) and then shown at up to the smaller
    // side of the window.
    var n = qr.getModuleCount(), pad = 4;
    var room = Math.max(280, Math.min(window.innerWidth - 48, window.innerHeight - 120, 900));
    var scale = Math.max(3, Math.floor(room / (n + pad * 2)));
    cv.width = cv.height = (n + pad * 2) * scale;
    var ctx = cv.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.fillStyle = "#000";
    for (var r = 0; r < n; r++) for (var c = 0; c < n; c++) {
      if (qr.isDark(r, c)) ctx.fillRect((c + pad) * scale, (r + pad) * scale, scale, scale);
    }
    cv.classList.remove("hidden");
    cv.style.maxWidth = "100%"; cv.style.height = "auto"; cv.style.imageRendering = "pixelated";
    cv.style.cursor = "zoom-in";
    cv.title = "לחיצה מציגה את הקוד על כל המסך";
    // one click = the code alone, on a white page, as large as the display: what a camera wants
    cv.onclick = function () {
      if (document.fullscreenElement) { document.exitFullscreen(); return; }
      var host = cv.parentElement;
      host.style.background = "#fff";
      (host.requestFullscreen ? host.requestFullscreen() : Promise.reject()).catch(function () {});
    };
    if (!canvas) $("qrEmpty").classList.add("hidden");
  }

  function renderOffer(offer, text) {
    state.offer = offer;
    $("offerText").textContent = groupText(text);
    $("offerTextBox").classList.remove("hidden");
    $("btnCopy").classList.remove("hidden");
    $("btnStopOffer").classList.remove("hidden");
    $("btnOffer").textContent = "קוד חדש";
    drawQr(text);
    var d = describeOffer(offer);
    var left = d.expires_at ? d.expires_at - Date.now() / 1000 : OFFER_TTL_S;
    $("offerState").innerHTML = '<span class="pill ok">הצעה פעילה</span> ' +
      '<span class="cx-timer" id="ttl" data-low="' + (left < 60 ? 1 : 0) + '">' + formatCountdown(left) + "</span>";
    var box = document.createElement("div");
    box.className = "cx-kv";
    box.innerHTML = '<div><div class="k">מזהה הלשכה</div><div class="v mono">' + esc(d.office_id) + "</div></div>" +
      '<div><div class="k">טביעת זהות</div><div class="v mono">' + esc(d.fingerprint) + "</div></div>" +
      '<div><div class="k">כתובת למנהרה</div>' + (d.endpoints.length
        ? '<div class="v mono">' + esc(d.endpoints.join(" · ")) + "</div>"
        : '<div class="v">אין — הלשכה הזאת רק מחייגת</div>') + "</div>" +
      '<div><div class="k">מזהה הזדמנות</div><div class="v mono" title="' + esc(d.rendezvous_id) + '">' +
        esc(d.rendezvous_id.slice(0, 8)) + "</div></div>";
    var prev = $("qrBox").querySelector(".cx-kv"); if (prev) prev.remove();
    $("qrBox").appendChild(box);
    $("showConfirm").innerHTML =
      '<div class="callout"><b>השלב הבא:</b> בלשכה המארחת סורקים את הקוד הזה, והיא מציגה <b>קוד תשובה</b>. ' +
      'את קוד התשובה קוראים כאן — ב„סריקה במצלמה” או ב„הדבקת קוד” — ואז שני המסכים מציגים את אותן שש ספרות.</div>';
    tick();
  }

  function tick() {
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(function () {
      var el = $("ttl"); if (!el || !state.offer || !state.offer.expires_at) return;
      var left = state.offer.expires_at - Date.now() / 1000;
      el.textContent = formatCountdown(left);
      el.dataset.low = left < 60 ? "1" : "0";
      if (left <= 0) { clearInterval(state.timer); expireOffer(); }
    }, 1000);
  }

  function expireOffer() {
    stopPolling();
    $("offerState").innerHTML = '<span class="pill bad">פג תוקף</span>';
    alerts("תוקף הקוד פג — יש להציג קוד חדש.", "warn");
    renderNav();
  }

  // ── show: mint the offer, then WAIT for the other side. The poll is the screen's whole job. ──
  async function mintOffer() {
    var btn = $("btnOffer"); btn.disabled = true;
    alerts("");
    try {
      var res = await post("api/pair/offer", { direction: $("direction").value });
      var text = res.text || res.qr_text || encodeOffer(res.offer);
      // drawn from the TEXT the server minted, through the same parser the other office will use:
      // a field this screen shows is then a field the other screen will read.
      var offer = parseOffer(text);
      state.rid = res.rendezvous_id || offer.rendezvous_id;
      state.role = "joiner";
      renderOffer(offer, text);
      startPolling();
    } catch (e) {
      notBuilt(e, "POST /api/pair/offer");
    } finally { btn.disabled = false; renderNav(); renderSteps(); }
  }

  function startPolling() {
    stopPolling();
    state.poll = setInterval(async function () {
      if (!state.rid) return;
      try {
        var res = await api("api/pair/offer/" + encodeURIComponent(state.rid));
        if (res.state === "claimed" && res.code) {
          stopPolling();
          state.code = res.code;
          state.role = "joiner";
          renderConfirm(res.code, res.peer || {}, "offer");
        } else if (res.state === "expired") {
          expireOffer();
        } else if (res.state === "confirmed") {
          stopPolling();
          done(res.link || {});
        }
      } catch (e) { /* a poll that fails is retried; only the mint is a user-visible failure */ }
    }, 2500);
  }
  function stopPolling() { if (state.poll) clearInterval(state.poll); state.poll = null; }

  // ── the confirmation step, shared by all three doors: the SAME markup and the same rule ──────
  // WHICH PANEL a door reads and writes: the number of this ternary is why a refusal could be
  // answered on one screen and not the other — it is named once, here.
  function panel(side) {
    return $(side === "offer" ? "showConfirm" : (side === "scan" ? "scanOut" : "pasteOut"));
  }

  // ONE refusal, ONE way forward, on BOTH roles: the same decision the host has always been able to
  // take, offered where the refusal was met. The words are the platform's own minus the protocol
  // instruction, which is a thing to SEND and never a thing to read.
  function offerReplace(box, e, retry) {
    var said = replaceRefusal(e);
    if (!said || state.replace || !box) return false;
    box.insertAdjacentHTML("beforeend",
      '<div class="callout warn"><b>' + hebrewWithTokens(said) + "</b>" +
      '<div class="cx-actions"><button class="btn" id="btnReplace" type="button">' +
      "להחליף את הרשומה הקיימת ולהמשיך</button></div></div>");
    $("btnReplace").addEventListener("click", function () { state.replace = true; this.disabled = true; retry(); });
    return true;
  }

  function renderConfirm(code, peer, side, replyText) {
    var box = panel(side);
    var other = side === "offer" ? "pasteOut" : "showConfirm";
    if (other) $(other).innerHTML = "";
    // THE HOST'S HALF: the reply is shown before the six digits, because the other office cannot
    // compute them until it has read it. Public material and a sealed grant — it may be photographed.
    var codeBox =
      '<div class="callout ok" id="confirmBox"><b>קוד האישור</b> — ודאו שהוא זהה בשתי הלשכות לפני האישור.' +
      '<div class="cx-code" id="sasCode">' + esc(digitsOf(code).replace(/(\d{3})(\d{3})/, "$1 $2")) + "</div>" +
      (peer.office_id ? '<div class="small">הלשכה השנייה: <span class="tok">' + esc(peer.office_id) +
        '</span> · טביעת זהות <span class="tok">' + esc(peer.fingerprint || "") + "</span></div>" : "") +
      "</div>" +
      '<div class="cx-actions"><button class="btn" id="btnConfirm" type="button">הקודים זהים — אישור</button>' +
      '<span class="pg-hint">אישור כאן כותב את הקישור ואת המפתחות. אין דרך חזרה חוץ מהסרת הקישור.</span></div>';
    var reply = replyText
      ? '<div class="callout"><b>קוד התשובה</b> — הלשכה המצטרפת סורקת אותו (או מדביקה את הטקסט) במסך הצימוד שלה.' +
        '<div class="cx-actions"><button class="btn ghost sm" id="btnCopyReply" type="button">העתקת קוד התשובה</button></div></div>' +
        '<div class="field"><label>קוד התשובה כטקסט</label><div class="keybox" id="replyText"></div></div>' +
        '<div class="cx-qr"><canvas id="replyQr" width="0" height="0"></canvas></div>'
      : "";
    box.innerHTML = codeBox + reply;
    $("btnConfirm").addEventListener("click", function () { confirmCode(side); });
    if (replyText) {
      $("replyText").textContent = groupText(replyText);
      drawQr(replyText, $("replyQr"), "L");
      $("btnCopyReply").addEventListener("click", async function () {
        try { await navigator.clipboard.writeText(replyText); this.textContent = "הועתק"; }
        catch (e) { this.textContent = "העתקה ידנית"; }
      });
    }
    renderNav(); renderSteps();
    try { $("confirmBox").scrollIntoView({ block: "start", behavior: "smooth" }); } catch (e) {}
  }

  async function confirmCode(side) {
    var btn = $("btnConfirm"); if (btn) btn.disabled = true;
    var path = state.role === "joiner" ? ("api/pair/offer/" + encodeURIComponent(state.rid) + "/confirm")
                                       : ("api/pair/claim/" + encodeURIComponent(state.rid));
    try {
      var res = await post(path, { code: state.code, confirm: true, replace: !!state.replace });
      state.render = res.render || null;
      done(res.link || res);
    } catch (e) {
      if (btn) btn.disabled = false;
      // The joining office meets the same record-already-here refusal the host can answer; before
      // this line it met a dead end (2026-10-11), after both codes had already been exchanged.
      if (offerReplace(panel(side), e, function () { confirmCode(side); })) return;
      notBuilt(e, "POST /" + path);
    }
  }

  function done(link) {
    state.link = link;
    stopPolling(); stopCamera();
    var spent = $("btnConfirm"); if (spent && spent.parentElement) spent.parentElement.remove();
    var r = state.render || {};
    var listens = (link.dial === "host") === (link.role === "joiner");
    // the KEY says which side this office is, the value is only the address: a sentence and an
    // address in one cell was cut at every width (the screenshots of 2026-10-05)
    var relay = link.dial === "relay";
    var tunnelKey = relay ? "המנהרה" : (listens ? "הלשכה הזאת מאזינה בכתובת" : "הלשכה הזאת מחייגת אל");
    var addr = relay ? "" : (link.endpoint || "") + ":" + (link.port || "");
    var dir = { use: "משתמשים כאן באפליקציות שלה", serve: "היא משתמשת באפליקציות מכאן",
                both: "דו־כיווני" }[link.direction] || "";
    $("doneOut").innerHTML =
      '<div class="callout ok"><b>הצימוד נכתב בלשכה הזאת.</b> הקישור עולה כשגם הלשכה השנייה מאשרת את אותו קוד אצלה.</div>' +
      (r.ok === false ? '<div class="callout warn"><b>המנהרה עוד לא רונדרה:</b> ' + esc(r.error || "") + "</div>" : "") +
      '<div class="cx-kv">' +
      '<div><div class="k">לשכה</div><div class="v">' + esc(link.label || link.office || "") +
        ' <span class="mono">' + esc(link.office || "") + "</span></div></div>" +
      '<div><div class="k">טביעת זהות</div><div class="v mono">' + esc(link.fingerprint || "") + "</div></div>" +
      '<div><div class="k">מה הקישור מאפשר</div><div class="v">' + esc(dir) + "</div></div>" +
      '<div><div class="k">' + esc(tunnelKey) + "</div>" + (relay
        ? '<div class="v">דרך לשכה שלישית</div>'
        : '<div class="v"><span class="tok">' + esc(addr) + "</span></div>") + "</div>" +
      "</div>" +
      '<div class="cx-actions"><button class="btn" id="btnDoneList" type="button" ' +
      'title="חוזר לרשימת הלשכות המחוברות — הלשכה הזאת מופיעה שם עם מצב הקישור">לרשימת הלשכות המחוברות</button></div>';
    $("btnDoneList").addEventListener("click", function () { location.href = "./"; });
    $("panelDone").classList.remove("hidden");
    setMode(mode);
    renderNav(); renderSteps();
  }

  // ── scan: the camera stays in this browser. Native BarcodeDetector first (Chrome on the platforms
  //    that have it), the vendored decoder otherwise — the same offer either way.
  async function startCamera() {
    alerts("");
    var video = $("cam");
    try {
      // FULL RESOLUTION, asked for explicitly. The default a browser hands out is 640x480, and a
      // code on another machine's screen across a desk is then ~1 pixel per module — measured
      // 2026-10-04: the laptop's camera saw the other screen plainly and decoded nothing. `ideal`
      // (never `exact`) so a camera that has less still opens.
      state.stream = await navigator.mediaDevices.getUserMedia({ video: {
        facingMode: "environment", width: { ideal: 3840 }, height: { ideal: 2160 }, frameRate: { ideal: 15 } } });
      video.srcObject = state.stream;
      await video.play();
      tuneCamera();
      $("camOff").classList.add("hidden");
      $("camFrame").classList.remove("hidden");
      $("camBox").dataset.on = "1";
      $("camZoomRow").classList.remove("hidden");
      $("btnScan").disabled = true;
      $("btnScanStop").disabled = false;
      $("scanState").innerHTML = '<span class="pill ok">המצלמה פועלת</span>';
      await detectLoop(video);
    } catch (e) {
      cameraFailed(e);
    }
  }

  function cameraFailed(e) {
    stopCamera();
    var insecure = location.protocol !== "https:" && !/^(localhost|127\.|\[::1\])/.test(location.hostname);
    $("camOff").classList.remove("hidden");
    $("camOff").textContent = insecure
      ? "הדפדפן חוסם מצלמה בחיבור לא מאובטח — פתחו את הלשכה ב־https או ב־localhost"
      : "המצלמה לא נדלקה: " + (e && e.name ? e.name : "שגיאה") + " — אפשר לבחור תמונה שצולמה בטלפון";
    $("scanState").innerHTML = '<span class="pill bad">המצלמה כבויה</span>';
  }

  function stopCamera() {
    if (state.scanner) { try { state.scanner.stop(); } catch (e) {} state.scanner = null; }
    if (state.stream) { state.stream.getTracks().forEach(function (t) { t.stop(); }); state.stream = null; }
    var v = $("cam"); if (v) { v.srcObject = null; v.style.transform = ""; }
    state.stopNative = true;
    if ($("camFrame")) $("camFrame").classList.add("hidden");
    if ($("camBox")) $("camBox").dataset.on = "0";
    if ($("camZoomRow")) $("camZoomRow").classList.add("hidden");
    if ($("camOff")) $("camOff").classList.remove("hidden");
    if ($("btnScan")) $("btnScan").disabled = false;
    if ($("btnScanStop")) $("btnScanStop").disabled = true;
  }

  // Continuous focus and exposure where the camera offers them, and its optical/digital zoom as a
  // control: a webcam focused on the person in front of it is not focused on a screen a metre away.
  function tuneCamera() {
    var track = state.stream && state.stream.getVideoTracks()[0];
    if (!track) return;
    var caps = (track.getCapabilities && track.getCapabilities()) || {};
    var adv = {};
    if (caps.focusMode && caps.focusMode.indexOf("continuous") >= 0) adv.focusMode = "continuous";
    if (caps.exposureMode && caps.exposureMode.indexOf("continuous") >= 0) adv.exposureMode = "continuous";
    if (Object.keys(adv).length) track.applyConstraints({ advanced: [adv] }).catch(function () {});
    var set = track.getSettings ? track.getSettings() : {};
    state.cam = { track: track, caps: caps, w: set.width || 0, h: set.height || 0 };
    var z = $("camZoom");
    if (z) {
      // ONE slider, two meanings: the camera's own zoom when it has one, and always the DIGITAL zoom
      // of the scan (the middle of the frame, enlarged before decoding) — which needs no hardware.
      z.min = 1; z.max = 6; z.step = 0.5; z.value = state.zoom || 1;
      z.oninput = function () {
        state.zoom = Number(z.value) || 1;
        $("cam").style.transform = "scale(" + state.zoom + ")";
        if (caps.zoom) {
          var hz = Math.min(caps.zoom.max, Math.max(caps.zoom.min, caps.zoom.min * state.zoom));
          track.applyConstraints({ advanced: [{ zoom: hz }] }).catch(function () {});
        }
      };
      z.oninput();
    }
    scanNote();
  }

  function scanNote(extra) {
    var c = state.cam || {};
    $("scanState").innerHTML = '<span class="pill ok">המצלמה פועלת</span> <span class="pg-hint">' +
      esc((c.w && c.h ? c.w + "×" + c.h : "") + (extra ? " · " + extra : "")) + "</span>";
  }

  // THE SCAN. One frame is tried several ways before the next is taken, because the code is small
  // in the frame far more often than it is blurred: the whole frame first (a code held close), then
  // the frame cut into overlapping tiles and each tile ENLARGED before decoding (a code that is a
  // small square somewhere on another screen), then the zoomed middle. Enlarging helps a decoder the
  // same way moving closer does — its finder-pattern search has a minimum module size.
  function scanRegions(w, h, zoom) {
    var out = [{ x: 0, y: 0, w: w, h: h, up: 1 }];
    if (zoom > 1) {
      var zw = w / zoom, zh = h / zoom;
      out.push({ x: (w - zw) / 2, y: (h - zh) / 2, w: zw, h: zh, up: Math.min(4, zoom) });
    }
    [2, 3].forEach(function (n) {
      var tw = w / n * 1.5, th = h / n * 1.5;                  // 50% overlap: a code on a seam is whole in a neighbour
      for (var r = 0; r < n; r++) for (var c = 0; c < n; c++) {
        var x = Math.min(w - tw, Math.max(0, c * (w / n) - (tw - w / n) / 2));
        var y = Math.min(h - th, Math.max(0, r * (h / n) - (th - h / n) / 2));
        out.push({ x: x, y: y, w: tw, h: th, up: n });
      }
    });
    return out;
  }

  async function detectLoop(video) {
    var native = ("BarcodeDetector" in window) ? new window.BarcodeDetector({ formats: ["qr_code"] }) : null;
    if (!native && typeof QrScanner === "undefined") { cameraFailed({ name: "אין מפענח" }); return; }
    if (!native) { try { QrScanner.WORKER_PATH = "static/vendor/qr-scanner/qr-scanner-worker.min.js"; } catch (e) {} }
    state.stopNative = false;
    state.scanner = { kind: native ? "native" : "vendored", stop: function () { state.stopNative = true; } };
    var canvas = document.createElement("canvas");
    var ctx = canvas.getContext("2d", { willReadFrequently: true });
    var pass = 0;

    async function decode(source) {
      if (native) {
        var found = await native.detect(source);
        return found && found.length ? found[0].rawValue : "";
      }
      try {
        var res = await QrScanner.scanImage(source, { returnDetailedScanResult: true });
        return (res && (res.data || res)) || "";
      } catch (e) { return ""; }                              // "no code in this picture" is not an error
    }

    while (!state.stopNative && state.stream) {
      var w = video.videoWidth, h = video.videoHeight;
      if (w && h) {
        var regions = scanRegions(w, h, state.zoom || 1);
        // the whole frame every pass, plus a few tiles in rotation — a full sweep takes a second or
        // two, and no single pass stalls the page
        var todo = [regions[0]].concat([0, 1, 2, 3].map(function (i) {
          return regions[1 + ((pass * 4 + i) % (regions.length - 1))];
        }));
        pass++;
        for (var i = 0; i < todo.length && !state.stopNative; i++) {
          var g = todo[i];
          try {
            var text = "";
            if (g.up === 1 && native) {
              text = await decode(video);
            } else {
              // capped: an enlarged tile of a 4K frame must not become a 100-megapixel canvas
              var scale = Math.min(g.up, 2400 / Math.max(g.w, g.h));
              canvas.width = Math.round(g.w * scale); canvas.height = Math.round(g.h * scale);
              ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
              ctx.drawImage(video, g.x, g.y, g.w, g.h, 0, 0, canvas.width, canvas.height);
              text = await decode(canvas);
            }
            if (text) return onScanned(text);
          } catch (e) { /* a frame that fails to decode is not an error */ }
        }
        scanNote("מחפש קוד… קרבו את המסך או הגדילו את הקוד אם הוא קטן בתמונה");
      }
      await new Promise(function (r) { setTimeout(r, 120); });
    }
  }

  function onScanned(text) {
    stopCamera();
    $("scanState").innerHTML = '<span class="pill ok">נסרק</span>';
    acceptText(text, "scan");
  }

  // ── paste and scan land in the same place: parse, show what was read, then claim ──────────────
  async function acceptText(text, side) {
    var box = $(side === "scan" ? "scanOut" : "pasteOut");
    if (kindOf(text) === "reply") return acceptReply(text, side);
    var offer;
    try {
      offer = parseOffer(text);
    } catch (e) {
      box.innerHTML = '<div class="callout bad"><b>הקוד לא נקרא:</b> ' + hebrewWithTokens(e.message) + "</div>";
      return;
    }
    if (offerExpired(offer)) {
      box.innerHTML = '<div class="callout warn"><b>תוקף הקוד פג.</b> בקשו מהלשכה השנייה קוד חדש.</div>';
      return;
    }
    state.offer = offer;
    var d = describeOffer(offer);
    box.innerHTML =
      '<div class="callout"><b>נקראה הצעת הצטרפות.</b> זה מה שהיא אומרת — ודאו שזו הלשכה שהתכוונתם אליה.</div>' +
      '<div class="cx-kv">' +
      '<div><div class="k">הלשכה</div><div class="v">' + esc(offer.label || d.office_id) +
        ' <span class="mono">' + esc(d.office_id) + "</span></div></div>" +
      '<div><div class="k">טביעת זהות</div><div class="v mono">' + esc(d.fingerprint) + "</div></div>" +
      '<div><div class="k">כתובת למנהרה</div>' + (d.endpoints.length
        ? '<div class="v mono">' + esc(d.endpoints.join(" · ")) + "</div>"
        : '<div class="v">אין — היא רק מחייגת</div>') + "</div>" +
      '<div><div class="k">פג בעוד</div><div class="v"><span class="num">' +
        esc(formatCountdown(d.expires_at - Date.now() / 1000)) + "</span></div></div>" +
      "</div>" +
      // TWO OFFICES THAT ONLY DIAL cannot be paired, and both facts are on this screen already: the
      // offer names no address, and this office's own answer says it has none either. Said HERE,
      // with why this office cannot be dialed and what would change it — not after another code
      // was made, exchanged and refused.
      (!d.endpoints.length && DIAL_ONLY
        ? '<div class="callout warn" id="noListener"><b>אי אפשר לצמד את שתי הלשכות האלה ישירות.</b> ' +
          "שתיהן רק מחייגות, ואין מי שיקבל את החיוג. <b>הלשכה הזאת:</b> " + ticks(DIAL_ONLY.reason) + " " +
          ticks(DIAL_ONLY.fix) + "</div>"
        : '<div class="cx-actions"><button class="btn" id="btnClaim" type="button">יצירת קוד תשובה וקוד אישור</button></div>');
    var go = $("btnClaim");
    if (go) go.addEventListener("click", function () { claim(text, side); });
    renderNav(); renderSteps();
  }

  async function claim(text, side) {
    var btn = $("btnClaim"); if (btn) btn.disabled = true;
    var box = $(side === "scan" ? "scanOut" : "pasteOut");
    try {
      var res = await post("api/pair/claim",
                           { text: stripSpace(text), direction: $("direction").value, replace: !!state.replace });
      state.rid = res.rendezvous_id;
      state.code = res.code;
      state.role = "host";
      renderConfirm(res.code, res.peer || {}, side, res.reply_text || "");
    } catch (e) {
      if (btn) btn.disabled = false;
      // A record under the other office's name already exists here. Replacing it is a decision, so it
      // is a second, explicit press — never the default of the first one, and never one screen's
      // privilege (the one place this lives is `offerReplace`).
      if (offerReplace(box, e, function () { claim(text, side); })) return;
      notBuilt(e, "POST /api/pair/claim");
    }
  }

  // The JOINER's second step: the host's reply, read back. The server opens it (it holds the offer's
  // ephemeral key), verifies the signature, and answers the six digits this office must show.
  async function acceptReply(text, side) {
    var box = $(side === "scan" ? "scanOut" : "pasteOut");
    box.innerHTML = '<div class="callout">קורא את קוד התשובה…</div>';
    try {
      var res = await post("api/pair/reply", { text: stripSpace(text) });
      stopPolling();
      state.rid = res.rendezvous_id;
      state.code = res.code;
      state.role = "joiner";
      $("showConfirm").innerHTML = "";
      renderConfirm(res.code, res.peer || {}, side);
    } catch (e) {
      box.innerHTML = "";
      notBuilt(e, "POST /api/pair/reply");
    }
  }

  // WHICH OFFICE THIS SCREEN IS. The other operator compares the name and the fingerprint with what
  // their own screen says it read, so both are on the page before any code is. Best effort: a server
  // that predates this answer leaves the line empty.
  // WHETHER THIS OFFICE CAN BE DIALED decides which offices it can be paired with at all, so it is
  // said before any code is shown: an office that only dials needs the OTHER one to be reachable.
  var DIAL_ONLY = null;
  function renderReach() {
    var el = $("reachLine"); if (!el) return;
    el.innerHTML = DIAL_ONLY
      ? '<div class="callout" id="dialOnly"><b>הלשכה הזאת רק מחייגת</b> — אפשר לצמד אותה רק ללשכה שאפשר לחייג אליה. ' +
        ticks(DIAL_ONLY.reason) + " " + ticks(DIAL_ONLY.fix) + "</div>"
      : "";
  }

  async function loadSelf() {
    try {
      var p = await api("api/pair"), h = p.home || {};
      DIAL_ONLY = p.dial_only || null;
      renderReach();
      if (!h.id) return;
      $("selfLine").innerHTML = (h.named
        ? "הלשכה הזאת: <b>" + esc(h.label) + "</b>"
        : 'ללשכה הזאת עוד אין שם — בלשכה השנייה היא תופיע כ־<span class="tok">' + esc(h.id) +
          '</span>. <a class="link" href="./">מתן שם</a>') +
        ' · טביעת זהות <span class="tok">' + esc(h.fingerprint || "") + "</span>";
    } catch (e) {
      // 409 = the office REFUSES in words (it has no identity yet, and the sentence names the
      // command): said here, before a code is asked for and refused. Anything else is an older
      // server, and the line stays empty.
      var el = $("reachLine");
      if (el && e.status === 409 && e.message) {
        el.innerHTML = '<div class="callout warn" id="selfRefused">' + sentence(e.message) + "</div>";
        // ...and the one verb that could only be refused the same way is not offered
        var mint = $("btnOffer");
        if (mint) { mint.disabled = true; mint.title = "ללשכה הזאת עוד אין זהות — ראו למעלה"; }
      }
    }
  }

  // WHAT THIS OFFICE GIVES IN THE LINK BEING MADE — the second half of the owner's decision ("give,
  // take or both; and if give, which apps"). The apps are one declaration for the whole office, so
  // this line states it and sends the person to the office's own card to change it.
  var GIVING = null;
  function renderGiveLine() {
    var el = $("giveLine"); if (!el) return;
    var dir = $("direction").value, g = GIVING;
    if (!g || dir === "use") { el.innerHTML = dir === "use" && g ? "בקישור הזה הלשכה הזאת רק לוקחת — היא לא נותנת אפליקציות." : ""; return; }
    var change = ' <a class="link" href="./">שינוי</a>';
    el.innerHTML = g.mode === "all" ? "הלשכה הזאת נותנת את כל האפליקציות שלה (" + esc(g.count) + ")." + change
      : g.mode === "some" ? "הלשכה הזאת נותנת " + esc(g.count) + " מתוך " + esc(g.total) + " אפליקציות." + change
      : (g.chosen ? "הלשכה הזאת הוגדרה לא לתת דבר — הלשכה השנייה לא תראה אפליקציות שלה." + change
                  : "עם אישור הצימוד הלשכה הזאת תיתן את כל האפליקציות שלה (" + esc(g.total) + "). אפשר לצמצם אחר כך במסך הלשכות.");
  }
  async function loadGiving() {
    try { GIVING = await api("api/pair/giving"); } catch (e) { GIVING = null; }
    renderGiveLine();
  }
  $("direction").addEventListener("change", renderGiveLine);

  // ── wiring ───────────────────────────────────────────────────────────────────────────────────
  $("btnBack").addEventListener("click", function () { location.href = "./"; });
  $("btnOffer").addEventListener("click", mintOffer);
  $("btnStopOffer").addEventListener("click", async function () {
    stopPolling();
    if (state.rid) { try { await post("api/pair/offer/" + encodeURIComponent(state.rid) + "/cancel", {}); } catch (e) {} }
    state.offer = null; state.rid = null; state.code = null; state.role = null;
    $("offerText").textContent = "";
    $("offerTextBox").classList.add("hidden");
    $("btnCopy").classList.add("hidden"); $("btnStopOffer").classList.add("hidden");
    $("btnOffer").textContent = "הצגת קוד";
    var oldFacts = $("qrBox").querySelector(".cx-kv"); if (oldFacts) oldFacts.remove();
    $("qr").classList.add("hidden"); $("qrEmpty").classList.remove("hidden");
    $("offerState").innerHTML = "";
    $("showConfirm").innerHTML = "";
    renderNav(); renderSteps();
  });
  $("btnCopy").addEventListener("click", async function () {
    try { await navigator.clipboard.writeText(stripSpace($("offerText").textContent)); this.textContent = "הועתק"; }
    catch (e) { this.textContent = "העתקה ידנית"; }
  });
  $("btnScan").addEventListener("click", startCamera);
  $("btnScanStop").addEventListener("click", function () { stopCamera(); $("scanState").innerHTML = ""; });
  $("btnPickImage").addEventListener("click", function () { $("fileImg").click(); });
  $("fileImg").addEventListener("change", async function () {
    var f = this.files && this.files[0]; if (!f) return;
    $("scanState").innerHTML = '<span class="pill unset">מפענח תמונה…</span>';
    try {
      if (typeof QrScanner === "undefined") throw new Error("אין מפענח");
      QrScanner.WORKER_PATH = "static/vendor/qr-scanner/qr-scanner-worker.min.js";
      var res = await QrScanner.scanImage(f, { returnDetailedScanResult: true });
      onScanned(res && (res.data || res));
    } catch (e) {
      $("scanState").innerHTML = '<span class="pill bad">לא נמצא קוד בתמונה</span>';
    }
  });
  $("btnParse").addEventListener("click", function () { acceptText($("pasteText").value, "paste"); });

  setMode("show");
  setMode(mode);
  renderSteps();
  loadSelf();
  loadGiving();
})();
