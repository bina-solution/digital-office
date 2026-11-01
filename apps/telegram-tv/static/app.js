/* telegram-tv — the front end.
 *
 * Shape of the app: three views (home / series / films), one detail screen per series, one player, and
 * a settings drawer. State lives in `state` and in localStorage; everything else is rendering.
 *
 * The parts that are about SMOOTHNESS rather than looks, and why they exist:
 *
 *   openPlayer()    asks the server HOW the file can be played (/api/play) instead of pointing <video>
 *                   at bytes and hoping. The server answers `direct` (browser-native mp4) or `remux`
 *                   (ffmpeg repackaging, when the container or the audio is the problem) or refuses
 *                   with the codec named. A black screen is never an answer to a question.
 *   quality switch  episodes arrive in several qualities; the player starts at the best one and DROPS
 *                   a level by itself if the stream stalls, remembering the choice per series.
 *   prefetch        the next episode is downloaded into the server's local cache while this one plays
 *                   — the only way "next episode" starts instantly on a ~1 MiB/s Telegram link.
 *   resume          position per film id, and "watched" at 92%, so a shelf of 51 episodes shows what
 *                   was seen and what is next instead of a wall of identical cards.
 */
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
/* @bina-ask:start */
var binaAsk, binaTell;
(function () {
  var doc = document;
  var CSS = ".bask{position:fixed;inset:0;z-index:2147483000;display:grid;grid-template:minmax(0,1fr)/minmax(0,1fr);place-items:center;padding:16px;background:var(--scrim)}"
    + ".bask-card{display:flex;flex-direction:column;width:min(440px,100%);max-height:100%;overflow:auto;box-sizing:border-box;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:var(--shadow-lg);font:14px/1.5 var(--font,system-ui,sans-serif);text-align:start;outline:0}"
    + ".bask-card h2{margin:0 0 8px;font-size:16px;font-weight:800;line-height:1.35}"
    + ".bask-read{overflow:auto}.bask-read:not(:empty){min-height:19px}"   // never squeezed to nothing: a line of it stays, and past that the card itself scrolls
    + ".bask-card p{margin:0 0 6px;font-size:13px;color:var(--muted)}"
    + ".bask-read p:last-child{margin:0}"
    + ".bask-facts{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:10px 0 0;padding:10px 12px;background:var(--surface-2);border:1px solid var(--line);border-radius:9px}"
    + ".bask-facts dt{color:var(--muted);font-size:11px;font-weight:600;line-height:1.7}"
    + ".bask-facts dd{margin:0;font-size:12.5px;font-weight:600;overflow-wrap:anywhere;unicode-bidi:plaintext;text-align:right}"
    + ".bask-field{display:grid;gap:5px;margin-top:10px;font-size:12px;font-weight:600;color:var(--muted)}"
    + ".bask-field input{font:inherit;font-size:13px;font-weight:400;height:36px;padding:0 10px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink)}"
    + ".bask-said{margin-top:10px;padding:8px 12px;border-radius:9px;border-inline-start:4px solid var(--red);background:color-mix(in srgb,var(--red) 14%,var(--surface));font-size:12.5px;overflow-wrap:anywhere}"
    + ".bask-said:empty{display:none}"
    + ".bask-acts{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}"
    + ".bask-btn{height:34px;padding:0 16px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--ink);font:inherit;font-size:13px;font-weight:700;cursor:pointer}"
    + ".bask-btn.primary{background:var(--accent);border-color:transparent;color:var(--accent-ink)}"
    + ".bask-btn.danger{background:var(--red);border-color:transparent;color:var(--surface)}"
    + ".bask-btn:disabled{opacity:.5;cursor:default}"
    + ".bask-field input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}"
    + "@media (pointer:coarse){.bask-btn{height:44px}.bask-field input{height:44px}}"
    + "@media (max-height:399px){.bask{padding:8px}.bask-card{padding:12px}.bask-acts{margin-top:10px}}"   // the side menu's own short frame
    + "#bina-tell{position:fixed;inset-block-end:16px;inset-inline-start:16px;z-index:2147483001;display:grid;gap:8px;max-width:min(420px,calc(100vw - 32px))}"
    + ".btell{--c:var(--ok);padding:10px 14px;border-radius:12px;background:color-mix(in srgb,var(--c) 14%,var(--surface));color:var(--ink);border:1px solid color-mix(in srgb,var(--c) 38%,var(--surface));border-inline-start:4px solid var(--c);font:13px/1.45 var(--font,system-ui,sans-serif);box-shadow:var(--shadow-lg);cursor:pointer;text-align:start}"
    + ".btell.warn{--c:var(--lime)}.btell.bad{--c:var(--red)}"   // --ok and --red, not the bare hues: they are the steps that are lifted on the dark ground
    + ".btell small{display:block;margin-top:2px;font-size:11.5px;color:var(--muted);overflow-wrap:anywhere;unicode-bidi:plaintext}"
    + ".btell button{margin-inline-start:12px;padding:0;border:0;background:none;font:inherit;font-weight:800;color:var(--blue);text-decoration:underline;cursor:pointer}";

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function style() {
    if (doc.getElementById("bina-ask-css")) return;
    var s = el("style", "", CSS);
    s.id = "bina-ask-css";
    doc.head.appendChild(s);
  }

  binaAsk = function (q) {
    style();
    return new Promise(function (resolve) {
      var back = doc.activeElement, field = null, must = q.input && q.input.must;
      var scrim = el("div", "bask"), card = el("div", "bask-card"), read = el("div", "bask-read"), said = el("div", "bask-said");
      card.setAttribute("role", "alertdialog");
      card.setAttribute("aria-modal", "true");
      card.setAttribute("dir", "rtl");
      card.setAttribute("tabindex", "-1");
      said.setAttribute("role", "alert");
      card.appendChild(el("h2", "", q.title));
      card.appendChild(read);
      String(q.body || "").split(/\n+/).forEach(function (line) { if (line.trim()) read.appendChild(el("p", "", line)); });
      if (q.facts && q.facts.length) {
        var dl = el("dl", "bask-facts");
        q.facts.forEach(function (f) { dl.appendChild(el("dt", "", f[0])); dl.appendChild(el("dd", "", f[1])); });
        read.appendChild(dl);
      }
      if (q.input) {
        var lab = el("label", "bask-field", q.input.label || "");
        field = el("input");
        field.value = q.input.value || "";
        if (q.input.dir) field.setAttribute("dir", q.input.dir);
        lab.appendChild(field);
        card.appendChild(lab);
      }
      var acts = el("div", "bask-acts"), no = el("button", "bask-btn", q.cancel || "ביטול"),
          yes = el("button", "bask-btn " + (q.danger ? "danger" : "primary"), q.ok || "אישור");
      no.setAttribute("type", "button");
      yes.setAttribute("type", "button");
      acts.appendChild(no);
      acts.appendChild(yes);
      card.appendChild(said);
      card.appendChild(acts);
      scrim.appendChild(card);
      doc.body.appendChild(scrim);

      function fit() { if (must) yes.disabled = field.value.trim() !== must; }
      function home() { (field || (q.danger ? no : yes)).focus(); }
      function done(v) {
        doc.removeEventListener("keydown", key, true);
        scrim.remove();
        if (back && back.focus) back.focus();
        resolve(v);
      }
      function cancel() { if (!no.disabled) done(field ? null : false); }
      function agree() {
        if (yes.disabled) return;
        var v = field ? field.value : true;
        if (!q.run) return done(v);
        yes.disabled = no.disabled = true;                // in flight: busy, and there is nothing left to cancel
        yes.textContent = "מבצע…";
        said.textContent = "";
        card.focus();
        Promise.resolve(v).then(q.run).then(function () { done(v); }, function (e) {
          yes.textContent = q.ok || "אישור";
          yes.disabled = no.disabled = false;
          fit();
          said.textContent = (e && e.message) || "הפעולה נכשלה";
          home();
        });
      }
      function key(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
        else if (e.key === "Enter" && field && doc.activeElement === field) { e.preventDefault(); agree(); }
        else if (e.key === "Tab") {                       // the page behind is not reachable while asked
          var ring = [field, no, yes].filter(function (n) { return n && !n.disabled; });
          var i = ring.indexOf(doc.activeElement);
          e.preventDefault();
          if (ring.length) ring[(i + (e.shiftKey ? ring.length - 1 : 1)) % ring.length].focus();
        }
        else if (/^(Arrow|Page)(Up|Down)$/.test(e.key) && doc.activeElement !== field && read.scrollHeight > read.clientHeight) {
          e.preventDefault();                               // the focus lives on the buttons, outside what scrolls
          read.scrollTop += (/Up$/.test(e.key) ? -1 : 1) * (/^Page/.test(e.key) ? read.clientHeight : 40);
        }
      }
      yes.addEventListener("click", agree);
      no.addEventListener("click", cancel);
      scrim.addEventListener("mousedown", function (e) { if (e.target === scrim) cancel(); });
      if (field) field.addEventListener("input", fit);
      doc.addEventListener("keydown", key, true);
      fit();
      home();
    });
  };

  // The third word is how long the notice stays (ms) — or what more it carries: { ms, more, act, stay }.
  //   more  the service's own sentence, on a line of its own under the notice's words
  //   act   [label, fn] — one way on from the notice (an undo, a refresh): pressing it runs fn and takes the notice down
  //   stay  no clock: the notice is there until it is pressed
  binaTell = function (text, kind, opt) {
    style();
    var o = opt && typeof opt === "object" ? opt : { ms: opt };
    var box = doc.getElementById("bina-tell");
    if (!box) { box = el("div"); box.id = "bina-tell"; doc.body.appendChild(box); }
    var n = el("div", "btell " + (kind || "ok"), text);
    n.setAttribute("role", kind === "bad" ? "alert" : "status");
    n.setAttribute("dir", "rtl");
    if (o.more) n.appendChild(el("small", "", o.more));
    if (o.act) {
      var go = el("button", "", o.act[0]);
      go.setAttribute("type", "button");
      go.addEventListener("click", function (e) { e.stopPropagation(); n.remove(); o.act[1](); });
      n.appendChild(go);
    }
    n.addEventListener("click", function () { n.remove(); });
    box.appendChild(n);
    if (!o.stay) setTimeout(function () { n.remove(); }, o.ms || (kind === "bad" ? 9000 : 5200));
    return n;
  };
})();
/* @bina-ask:end */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  status: null, catalog: null, series: [], films: [], query: "", view: "home",
  seriesDetail: null, season: null, chats: [], scrapers: [], mode: "qr", job: null,
  play: null, heroPick: null,
};

/* ── helpers ──────────────────────────────────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "content-type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  }).catch(binaNoAnswer);       // a service that does not answer is said in words, not «Failed to fetch»
  let data = null;
  try { data = await res.json(); } catch (e) { /* an empty body is a valid answer here */ }
  if (!res.ok) {
    const msg = (data && (data.detail || data.error || data.reason)) || binaSaid(res.status);
    const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    err.status = res.status;
    throw err;
  }
  return data;
}
const fmtDur = (s) => {
  s = Math.round(Number(s) || 0);
  if (!s) return "";
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? h + ":" + String(m).padStart(2, "0") + " שע׳" : m + " דק׳";
};
const fmtClock = (s) => {
  s = Math.max(0, Math.round(Number(s) || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : String(m)) + ":" + String(sec).padStart(2, "0");
};
const fmtSize = (b) => {
  b = Number(b) || 0;
  if (!b) return "";
  const gb = b / 1024 ** 3;
  return gb >= 1 ? gb.toFixed(1) + " GB" : Math.round(b / 1024 ** 2) + " MB";
};
const QUALITY_ORDER = { "2160p": 4, "1440p": 3, "1080p": 2, "720p": 1, "480p": 0, "360p": -1 };
const qualityRank = (label) => (QUALITY_ORDER[label] ?? 99);

/* The player says ONE thing at a time — a quality switch is three lines within two seconds — so a new
   line takes the place of the one before it. The line itself is the office's notice (`binaTell`). */
let said = null;
function say(text, kind) { if (said) said.remove(); said = binaTell(text, kind); }
function banner(text, kind) {
  const el = $("banner");
  if (!text) { el.classList.add("hidden"); return; }
  el.className = "banner" + (kind === "error" ? " error" : "");
  el.textContent = text;
}

/* ── watch history (per browser) ──────────────────────────────────────────────────────────── */
const HIST_KEY = "tv:hist";
function histAll() { try { return JSON.parse(localStorage.getItem(HIST_KEY) || "{}"); } catch (e) { return {}; } }
function histGet(id) { return histAll()[id] || null; }
function histSet(id, patch) {
  try {
    const all = histAll();
    all[id] = Object.assign({}, all[id] || {}, patch, { at: Date.now() });
    const keys = Object.keys(all).sort((a, b) => (all[b].at || 0) - (all[a].at || 0)).slice(0, 200);
    const pruned = {};
    keys.forEach((k) => { pruned[k] = all[k]; });
    localStorage.setItem(HIST_KEY, JSON.stringify(pruned));
  } catch (e) { /* private mode: memory simply is not kept */ }
}
function progressOf(m) {
  const h = histGet(m.id);
  if (!h || !h.t) return 0;
  const d = h.d || m.duration || 0;
  return d ? Math.min(1, h.t / d) : 0;
}
function isWatched(m) {
  const h = histGet(m.id);
  if (h && h.done) return true;
  return progressOf(m) > 0.92;
}

/* ── the four marks this screen draws, as icons ───────────────────────────────────────────────
   They were characters of the font (a play triangle, a star, a check, a cross): drawn by whatever
   font the reader's system has, at the text's baseline, and read aloud by their names. Same drawing
   as the play icon of the page's own buttons (index.html); sized by the text they stand in. */
const GL = (d, line) => '<svg class="gl" viewBox="0 0 24 24" aria-hidden="true" ' + (line
  ? 'fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"'
  : 'fill="currentColor"') + '><path d="' + d + '"/></svg>';
const IC = {
  play: GL("M8 5v14l11-7z"),
  star: GL("M12 2.6l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.5l-5.9 3.1 1.2-6.5-4.8-4.6 6.6-.9z"),
  check: GL("M5 12.5l4.5 4.5L19 7.5", true),
  x: GL("M6 6l12 12M18 6L6 18", true),
};
// the facts under a title, a cell each; a rating is the star and its number
const metaHTML = (m, more) => [esc(m.year || ""), esc(m.quality_label || m.quality || ""),
  m.rating ? IC.star + " " + esc(m.rating) : ""].concat(more.map((x) => esc(x || "")))
  .filter(Boolean).map((x) => "<span>" + x + "</span>").join("");

/* ── cards ────────────────────────────────────────────────────────────────────────────────── */
function cardHTML(item, opts) {
  opts = opts || {};
  const initial = String(item.title || "?").trim().slice(0, 1);
  const p = progressOf(item);
  const watched = isWatched(item);
  const img = '<img data-poster src="' + esc(item.poster || ("api/poster/" + encodeURIComponent(item.id))) +
    '" alt="" loading="lazy" data-fallback="' + esc(initial) + '">';
  const tag = item.quality_label || item.quality || item.year || "";
  return '<button class="card-movie' + (watched ? " watched" : "") + '" type="button" data-id="' + esc(item.id) + '">' +
    '<div class="art">' + (tag ? '<span class="tag">' + esc(tag) + "</span>" : "") +
    (item.rating ? '<span class="rate">' + IC.star + " " + esc(item.rating) + "</span>" : "") + img +
    '<div class="play"><i>' + IC.play + "</i></div>" +
    (opts.showProgress !== false && p > 0.02 && p < 0.95
      ? '<div class="bar"><i style="width:' + (p * 100).toFixed(1) + '%"></i></div>' : "") +
    (watched ? '<span class="tick" title="נצפה">' + IC.check + "</span>" : "") + "</div>" +
    '<div class="name">' + esc(item.title) + "</div>" +
    '<div class="sub">' + esc([item.year, fmtDur(item.duration), fmtSize(item.size)].filter(Boolean).join(" · ")) + "</div>" +
    "</button>";
}

/* Artwork is generated on the server in the background (a frame from the film, ~40s each), so a poster
   can 404 the first time it is asked for. Retrying the image — instead of remembering a failure — is
   what turns a wall of placeholders into a shelf within a couple of minutes. */
document.addEventListener("error", (e) => {
  const img = e.target;
  if (!(img instanceof HTMLImageElement) || !img.dataset.fallback) return;
  const tries = Number(img.dataset.retries || 0);
  if (tries < 3 && !document.hidden) {
    img.dataset.retries = String(tries + 1);
    const src = img.getAttribute("src");
    setTimeout(() => { img.setAttribute("src", src + (src.indexOf("?") >= 0 ? "&" : "?") + "r=" + Date.now()); },
               8000 + tries * 8000);
    return;
  }
  const ph = document.createElement("div");
  ph.className = "ph";
  ph.textContent = img.dataset.fallback || "?";
  img.replaceWith(ph);
}, true);

/* Posters: the server serves an intentional placeholder tile while the real still is being generated
   from the film (a frame costs seconds of ffmpeg). A placeholder is 400px wide, the real still 640 —
   so the client can see the difference and ask again, which is what turns a shelf of placeholders into
   real artwork a minute later without a single broken image. */
function schedulePosterRetry(root, pass) {
  pass = pass || 0;
  if (pass >= 6 || document.hidden) return;
  const pending = [...root.querySelectorAll("img[data-poster]")]
    .filter((img) => img.complete && img.naturalWidth > 0 && img.naturalWidth <= 400);
  if (!pending.length) return;
  setTimeout(() => {
    pending.forEach((img) => {
      const src = img.getAttribute("src").split("&r=")[0].split("?r=")[0];
      img.setAttribute("src", src + (src.indexOf("?") >= 0 ? "&" : "?") + "r=" + Date.now());
    });
    schedulePosterRetry(root, pass + 1);
  }, 20000 + pass * 10000);
}

/* A 16:9 still is generated from the film itself and may not exist for a minute after the first
   visit, so the backdrop is set through an Image probe and falls back to the poster. */
function setBackdrop(el, movie) {
  const backdrop = "api/backdrop/" + encodeURIComponent(movie.id);
  const poster = movie.poster || ("api/poster/" + encodeURIComponent(movie.id));
  const probe = new Image();
  probe.onload = () => { el.style.backgroundImage = 'url("' + backdrop + '")'; };
  probe.onerror = () => { el.style.backgroundImage = 'url("' + poster + '")'; };
  probe.src = backdrop;
}

/* ── HOME ─────────────────────────────────────────────────────────────────────────────────── */
function allKnown() {
  const out = [];
  (state.catalog && state.catalog.rows || []).forEach((r) => r.movies.forEach((m) => out.push(m)));
  state.films.forEach((m) => out.push(m));
  if (state.seriesDetail) flattenEpisodes(state.seriesDetail).forEach((m) => out.push(m));
  return out;
}
function findAnywhere(id) {
  return allKnown().find((m) => m.id === id) || null;
}
function continueWatching(limit) {
  const hist = histAll();
  return Object.keys(hist)
    .filter((id) => hist[id].t > 20 && hist[id].d && hist[id].t < hist[id].d * 0.95)
    .sort((a, b) => (hist[b].at || 0) - (hist[a].at || 0))
    .slice(0, limit || 14)
    .map((id) => findAnywhere(id) || { id: id, title: hist[id].title || id, poster: hist[id].poster,
                                       duration: hist[id].d, quality_label: hist[id].q || "" });
}
function heroFor() {
  const cont = continueWatching(1);
  if (cont.length) return { movie: cont[0], resume: (histGet(cont[0].id) || {}).t || 0 };
  const pick = state.series[0]
    ? null : (state.films[0] || ((state.catalog && state.catalog.rows[0]) ? state.catalog.rows[0].movies[0] : null));
  const m = pick || (state.films[0] || ((state.catalog && state.catalog.rows[0]) ? state.catalog.rows[0].movies[0] : null));
  return m ? { movie: m, resume: 0 } : null;
}
function renderHero() {
  const pick = heroFor();
  const hero = $("hero");
  if (!pick) { hero.classList.add("hidden"); return; }
  hero.classList.remove("hidden");
  const m = pick.movie;
  const ser = m.series_key ? state.series.find((s) => s.series_key === m.series_key) : null;
  setBackdrop($("hero-bg"), m);
  $("hero-kicker").textContent = ser ? "סדרה · " + ser.title
    : (pick.resume ? "ממשיכים מאותה נקודה" : "מתוך הספרייה");
  $("hero-title").textContent = ser ? ser.title : m.title;
  $("hero-meta").innerHTML = metaHTML(m, [fmtDur(m.duration), (ser && m.series) ? m.title : ""]);
  $("hero-desc").textContent = m.description || (ser ? ser.episodes + " פרקים בספרייה" : "");
  $("hero-play-label").textContent = pick.resume ? "המשך מ־" + fmtClock(pick.resume) : "נגן";
  state.heroPick = pick;
  // the banner's still is generated on the server in the background: ask for THIS one first
  api("api/artwork/ensure/" + encodeURIComponent(m.id), { method: "POST" })
    .then((r) => { if (r && r.ready && !state.heroArtworkDone) { state.heroArtworkDone = true; setBackdrop($("hero-bg"), m); } })
    .catch(() => {});
}
function seriesCardHTML(s) {
  const initial = String(s.title || "?").trim().slice(0, 1);
  const img = '<img data-poster src="' + esc(s.poster || ("api/poster/" + encodeURIComponent(s.poster_id || ""))) +
    '" alt="" loading="lazy" data-fallback="' + esc(initial) + '">';
  const seasons = s.season_from === s.season_to ? (s.season_from || 1) + " עונות" : s.season_from + "-" + s.season_to;
  return '<button class="card-movie" type="button" data-series="' + esc(s.series_key) + '">' +
    '<div class="art"><span class="tag">' + esc(s.episodes) + " פרקים</span>" + img +
    '<div class="play"><i>' + IC.play + "</i></div></div>" +
    '<div class="name">' + esc(s.title) + "</div>" +
    '<div class="sub">' + esc(seasons) + "</div></button>";
}
function rowsBySearch() {
  const q = state.query.trim().toLowerCase();
  return ((state.catalog && state.catalog.rows) || []).map((r) => ({
    chat: r.chat,
    movies: r.movies.filter((m) => String(m.title || "").toLowerCase().indexOf(q) >= 0 ||
      String(m.description || "").toLowerCase().indexOf(q) >= 0 ||
      (m.tags || []).join(" ").toLowerCase().indexOf(q) >= 0),
  })).filter((r) => r.movies.length);
}
function renderRows() {
  const rows = ((state.catalog && state.catalog.rows) || []).filter((r) => r.movies.length);
  const cont = continueWatching(14);
  let html = "";
  if (cont.length) {
    html += '<section class="row"><div class="row-head"><h3>המשך צפייה</h3></div>' +
      '<div class="scroller">' + cont.map((m) => cardHTML(m)).join("") + "</div></section>";
  }
  if (state.series.length) {
    html += '<section class="row"><div class="row-head"><h3>סדרות</h3><span class="count">' +
      state.series.length + '</span><button class="more" data-view="series" type="button">הצג הכל</button></div>' +
      '<div class="scroller">' + state.series.slice(0, 20).map(seriesCardHTML).join("") + "</div></section>";
  }
  if (state.films.length) {
    html += '<section class="row"><div class="row-head"><h3>סרטים</h3><span class="count">' +
      state.films.length + '</span><button class="more" data-view="films" type="button">הצג הכל</button></div>' +
      '<div class="scroller">' + state.films.slice(0, 20).map((m) => cardHTML(m)).join("") + "</div></section>";
  }
  const wanted = state.query.trim() ? rowsBySearch() : rows;
  wanted.forEach((r) => {
    html += '<section class="row"><div class="row-head"><h3>' + esc(r.chat.title) + "</h3>" +
      '<span class="count">' + r.movies.length + " סרטים</span></div>" +
      '<div class="scroller">' + r.movies.map((m) => cardHTML(m)).join("") + "</div></section>";
  });
  $("rows").innerHTML = html;
  $("empty").classList.toggle("hidden", Boolean(html));
  bindCards($("rows"));
  schedulePosterRetry($("rows"));
}
function bindCards(root) {
  root.querySelectorAll(".card-movie").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.dataset.series) return openSeries(el.dataset.series);
      playById(el.dataset.id);
    });
  });
  root.querySelectorAll("[data-view]").forEach((el) =>
    el.addEventListener("click", () => setView(el.dataset.view)));
}
function renderFilms() {
  const grid = $("films-grid");
  const list = state.query.trim() ? rowsBySearch().reduce((a, r) => a.concat(r.movies), []) : state.films;
  grid.innerHTML = list.map((m) => cardHTML(m)).join("");
  bindCards(grid);
}
function renderSeriesGrid() {
  const q = state.query.trim().toLowerCase();
  const list = q ? state.series.filter((s) => String(s.title || "").toLowerCase().indexOf(q) >= 0) : state.series;
  $("series-grid").innerHTML = list.map(seriesCardHTML).join("");
  bindCards($("series-grid"));
}

/* ── SERIES ───────────────────────────────────────────────────────────────────────────────── */
function flattenEpisodes(detail) {
  return (detail.seasons || []).reduce((a, s) => a.concat(s.episodes.reduce((b, e) => b.concat(e.variants), [])), []);
}
async function openSeries(key) {
  try {
    const d = await api("api/series/" + encodeURIComponent(key));
    state.seriesDetail = d;
    state.season = d.seasons[0] ? d.seasons[0].season : 0;
    const first = d.seasons[0].episodes[0].variants[0];
    setBackdrop($("series-bg"), first);
    $("series-title").textContent = d.title;
    $("series-meta").innerHTML = [d.episodes + " פרקים", d.seasons.length > 1 ? d.seasons.length + " עונות" : ""]
      .filter(Boolean).map((x) => "<span>" + esc(x) + "</span>").join("");
    const next = nextEpisodeAfter(null);
    $("series-play").onclick = () => next && playEpisode(d, next);
    renderSeasons();
    setView("series-detail");
  } catch (e) {
    say("לא ניתן לפתוח את הסדרה: " + e.message, "bad");
  }
}
function renderSeasons() {
  const d = state.seriesDetail;
  $("seasons").innerHTML = d.seasons.map((s) =>
    '<button class="season-btn' + (s.season === state.season ? " active" : "") + '" data-season="' + s.season +
    '" type="button">' + (s.season ? "עונה " + s.season : "ללא עונה") + "</button>").join("");
  $("seasons").querySelectorAll(".season-btn").forEach((b) =>
    b.addEventListener("click", () => { state.season = Number(b.dataset.season); renderSeasons(); renderEpisodes(); }));
  renderEpisodes();
}
function renderEpisodes() {
  const d = state.seriesDetail;
  const season = d.seasons.find((s) => s.season === state.season) || d.seasons[0];
  $("episodes").innerHTML = season.episodes.map((e) => {
    const best = e.variants[0];
    const p = progressOf(best);
    const watched = isWatched(best);
    const still = best.poster ? '<img src="' + esc(best.poster) + '" alt="" loading="lazy">' : "";
    return '<div class="ep" data-ep="' + e.episode + '"><div class="still">' + still +
      '<span class="num">' + esc(e.label) + "</span>" +
      (p > 0.02 && p < 0.95 ? '<div class="bar"><i style="width:' + (p * 100).toFixed(1) + '%"></i></div>' : "") +
      '</div><div class="info"><h4>' + esc(e.label) + (watched ? ' <span class="seen" title="נצפה">' + IC.check + "</span>" : "") + "</h4><p>" +
      esc(best.description || [fmtDur(best.duration), fmtSize(best.size)].filter(Boolean).join(" · ")) +
      '</p></div><div class="side"><div class="qual">' +
      e.variants.map((v) => '<button class="qual-btn' + (v.id === best.id ? " active" : "") +
        '" data-play="' + esc(v.id) + '" type="button">' + esc(v.quality_label || fmtSize(v.size)) + "</button>").join("") +
      '</div><button class="go" data-play="' + esc(best.id) + '" type="button" aria-label="נגן" title="נגן את ' +
      esc(e.label) + '">' + IC.play + "</button></div></div>";
  }).join("");
  $("episodes").querySelectorAll("[data-play]").forEach((el) =>
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const ep = Number(el.closest(".ep").dataset.ep);
      const entry = season.episodes.find((x) => x.episode === ep);
      const variant = entry.variants.find((v) => v.id === el.dataset.play) || entry.variants[0];
      playEpisode(d, entry, variant);
    }));
}
function nextEpisodeAfter(id) {
  const d = state.seriesDetail;
  if (!d) return null;
  const flat = d.seasons.reduce((a, s) => a.concat(s.episodes), []);
  let at = 0;
  if (id) {
    const idx = flat.findIndex((e) => e.variants.some((v) => v.id === id));
    at = idx + 1;
  }
  for (let i = Math.max(0, at); i < flat.length; i++) if (!isWatched(flat[i].variants[0])) return flat[i];
  return flat[Math.max(0, Math.min(at, flat.length - 1))] || null;
}

/* ── views ────────────────────────────────────────────────────────────────────────────────── */
function setView(view) {
  state.view = view;
  const show = (id, on) => $(id).classList.toggle("hidden", !on);
  show("view-home", view === "home");
  show("view-series", view === "series");
  show("view-films", view === "films");
  show("series-view", view === "series-detail");
  document.querySelectorAll(".bnv-item[data-view]").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.view === view));
  window.scrollTo({ top: 0 });
}

/* ── the player ───────────────────────────────────────────────────────────────────────────── */
const P = { video: null, hideTimer: null, nextCountdown: null, autoDowngraded: false, stallTimer: null };
function savedQuality(seriesKey) {
  try { return localStorage.getItem("tv:q:" + (seriesKey || "")) || ""; } catch (e) { return ""; }
}
function saveQuality(seriesKey, label) {
  try { localStorage.setItem("tv:q:" + (seriesKey || ""), label); } catch (e) { /* ignore */ }
}
function pickVariant(variants, seriesKey) {
  const saved = savedQuality(seriesKey);
  if (saved) {
    const hit = variants.find((v) => (v.quality_label || "") === saved);
    if (hit) return hit;
  }
  // best quality first — the player drops a level by itself if the stream stalls
  return variants.slice().sort((a, b) => qualityRank(b.quality_label) - qualityRank(a.quality_label))[0];
}
function episodeEntryFor(movie) {
  const d = state.seriesDetail;
  if (!d || !movie.series_key || d.series_key !== movie.series_key) return null;
  for (const s of d.seasons) for (const e of s.episodes) if (e.variants.some((v) => v.id === movie.id)) return e;
  return null;
}
async function playById(id, start) {
  const m = findAnywhere(id);
  if (!m) { say("הפריט לא נמצא בספרייה", "bad"); return; }
  const h = histGet(id);
  const fallback = { id: id, title: (h && h.title) || id, poster: h && h.poster, duration: (h && h.d) || 0,
                     series_key: (h && h.seriesKey) || "", stream: "api/stream/" + id };
  const movie = m || fallback;
  if (movie.series_key && (!state.seriesDetail || state.seriesDetail.series_key !== movie.series_key)) {
    try { state.seriesDetail = await api("api/series/" + encodeURIComponent(movie.series_key)); } catch (e) {}
  }
  const entry = episodeEntryFor(movie);
  if (entry) return playEpisode(state.seriesDetail, entry, movie, start);
  return openPlayer(movie, { variants: [movie], start: start });
}
function playEpisode(detail, entry, variant, start) {
  const chosen = variant || pickVariant(entry.variants, detail.series_key);
  const flat = detail.seasons.reduce((a, s) => a.concat(s.episodes), []);
  const idx = flat.findIndex((e) => e.season === entry.season && e.episode === entry.episode);
  openPlayer(chosen, {
    variants: entry.variants, seriesKey: detail.series_key, seriesTitle: detail.title,
    entryLabel: entry.label, start: start,
    playlist: flat.slice(idx + 1).map((e) => ({ entry: e, variants: e.variants })),
  });
}
async function openPlayer(movie, opts) {
  opts = opts || {};
  const video = P.video = $("video");
  state.play = Object.assign({ movie: movie }, opts);
  const h = histGet(movie.id);
  const start = opts.start != null ? opts.start : (h && h.t && !h.done ? h.t : 0);
  $("player").classList.remove("hidden");
  $("player").setAttribute("aria-hidden", "false");
  $("p-title").textContent = opts.seriesTitle ? opts.seriesTitle + " — " + (opts.entryLabel || movie.title) : movie.title;
  $("p-sub").textContent = [movie.year, movie.quality_label || movie.quality, fmtSize(movie.size)]
    .filter(Boolean).join(" · ");
  $("p-badges").innerHTML = "";
  showSpinner("מאתחל…");
  renderQualityButtons();
  $("p-next-card").classList.add("hidden");
  P.autoDowngraded = false;
  try {
    const res = await api("api/play/" + encodeURIComponent(movie.id) + (start ? "?t=" + Math.floor(start) : ""));
    state.play.res = res;
    const probe = res.probe || {};
    const badges = [];
    if (probe.height) badges.push(probe.height + "p");
    if (probe.video) badges.push(String(probe.video).toUpperCase());
    if (probe.audio) badges.push(String(probe.audio).toUpperCase());
    badges.push(res.mode === "direct" ? "ישיר" : "remux");
    if (probe.policy && probe.policy.risky_video) badges.push("HEVC — תלוי בחומרה");
    $("p-badges").innerHTML = badges.map((b) =>
      '<span class="' + (b.indexOf("HEVC") >= 0 ? "warn" : "") + '">' + esc(b) + "</span>").join("");
    video.src = res.url + (res.url.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
    await video.play().catch(() => { /* autoplay may be blocked; the controls are right there */ });
    hideSpinner();
    armNextEpisode();
    prefetchNext();
  } catch (e) {
    hideSpinner();
    say("לא ניתן לנגן: " + e.message, "bad");
  }
}
function showSpinner(text) { $("p-spinner-text").textContent = text || "טוען…"; $("p-spinner").classList.remove("hidden"); }
function hideSpinner() { $("p-spinner").classList.add("hidden"); }
function renderQualityButtons() {
  const s = state.play;
  const group = $("p-quality-group");
  if (!s || !s.variants || s.variants.length < 2) { group.innerHTML = ""; return; }
  group.innerHTML = s.variants.map((v) => '<button type="button" data-q="' + esc(v.id) + '" class="' +
    (v.id === s.movie.id ? "active" : "") + '">' + esc(v.quality_label || fmtSize(v.size)) + "</button>").join("");
  group.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", async () => {
    const target = s.variants.find((v) => v.id === b.dataset.q);
    if (!target || target.id === s.movie.id) return;
    const at = P.video.currentTime || 0;
    saveQuality(s.seriesKey || "", target.quality_label || "");
    say("עובר ל-" + (target.quality_label || fmtSize(target.size)));
    await openPlayer(target, Object.assign({}, s, { movie: target, start: at }));
  }));
}
function armNextEpisode() {
  const s = state.play;
  const next = s && s.playlist && s.playlist[0];
  $("p-next").classList.toggle("hidden", !next);
  if (!next) return;
  $("p-next-title").textContent = next.entry.label;
  $("p-next-go").onclick = () => playEpisode(state.seriesDetail, next.entry, pickVariant(next.variants, s.seriesKey));
}
function prefetchNext() {
  const s = state.play;
  const next = s && s.playlist && s.playlist[0];
  if (!next) return;
  const small = next.variants.slice().sort((a, b) => (a.size || 0) - (b.size || 0))[0];
  api("api/prefetch/" + encodeURIComponent(small.id), { method: "POST" }).catch(() => {});
}
function closePlayer() {
  const video = P.video;
  if (!video) return;
  const s = state.play;
  if (s && video.currentTime > 10) {
    histSet(s.movie.id, { t: Math.round(video.currentTime), d: Math.round(video.duration || 0),
      title: s.entryLabel || s.movie.title, poster: s.movie.poster, series: s.seriesTitle || "" });
  }
  video.pause();
  video.removeAttribute("src");
  video.load();
  $("player").classList.add("hidden");
  $("player").setAttribute("aria-hidden", "true");
  clearInterval(P.nextCountdown);
  state.play = null;
  renderRows();
}
function togglePlay() {
  const v = P.video;
  if (!v) return;
  if (v.paused) v.play().catch(() => {}); else v.pause();
}
function seekBy(delta) {
  const v = P.video;
  if (!v || !isFinite(v.duration)) return;
  v.currentTime = Math.max(0, Math.min(v.duration - 1, v.currentTime + delta));
}
function updateBar() {
  const v = P.video;
  if (!v) return;
  const d = v.duration || 0;
  const pct = d ? (v.currentTime / d) * 100 : 0;
  $("p-played").style.width = pct + "%";
  $("p-knob").style.insetInlineStart = pct + "%";
  try {
    if (v.buffered.length && d) $("p-buffer").style.width = ((v.buffered.end(v.buffered.length - 1) / d) * 100) + "%";
  } catch (e) { /* buffered can throw while switching sources */ }
  $("p-time").textContent = fmtClock(v.currentTime) + " / " + fmtClock(d);
  const ic = v.paused ? '<path d="M8 5v14l11-7z"/>' : '<path d="M7 5h4v14H7z"/><path d="M13 5h4v14h-4z"/>';
  $("p-play-ic").innerHTML = ic;
  $("p-play2-ic").innerHTML = ic;
}
function armAutoHide() {
  const el = $("player");
  el.classList.remove("hide-ui");
  clearTimeout(P.hideTimer);
  P.hideTimer = setTimeout(() => { if (P.video && !P.video.paused) el.classList.add("hide-ui"); }, 3200);
}
["mousemove", "click", "touchstart"].forEach((ev) =>
  $("player").addEventListener(ev, armAutoHide, { passive: true }));

/* Stall handling: the honest version of adaptive bitrate. If playback stops advancing while the buffer
   is empty, drop to the smallest variant ONCE and remember it — the alternative, on a link that cannot
   carry the file, is a spinner that never ends. */
function watchForStalls() {
  clearTimeout(P.stallTimer);
  P.stallTimer = setTimeout(async () => {
    const s = state.play;
    if (!s || !s.variants || s.variants.length < 2 || P.autoDowngraded) return;
    const smallest = s.variants.slice().sort((a, b) => (a.size || 0) - (b.size || 0))[0];
    if (smallest.id === s.movie.id) return;
    P.autoDowngraded = true;
    saveQuality(s.seriesKey || "", smallest.quality_label || "");
    say("הקישור לטלגרם איטי — עובר ל-" + (smallest.quality_label || fmtSize(smallest.size)));
    await openPlayer(smallest, Object.assign({}, s, { movie: smallest, start: P.video.currentTime || 0 }));
  }, 9000);
}

/* video events */
const video = $("video");
video.addEventListener("waiting", () => { showSpinner("טוען…"); watchForStalls(); });
video.addEventListener("playing", () => { hideSpinner(); clearTimeout(P.stallTimer); });
video.addEventListener("canplay", hideSpinner);
video.addEventListener("timeupdate", () => {
  const v = P.video, s = state.play;
  updateBar();
  if (!s) return;
  if (v.currentTime > 10 && Math.round(v.currentTime) % 10 === 0) {
    histSet(s.movie.id, { t: Math.round(v.currentTime), d: Math.round(v.duration || 0),
      title: s.entryLabel || s.movie.title, poster: s.movie.poster, series: s.seriesTitle || "" });
  }
  if (v.duration && v.currentTime > v.duration - 30 && s.playlist && s.playlist[0] &&
      $("p-next-card").classList.contains("hidden")) {
    $("p-next-card").classList.remove("hidden");
  }
});
video.addEventListener("ended", () => {
  const s = state.play;
  if (!s) return;
  histSet(s.movie.id, { t: Math.round(video.duration || 0), d: Math.round(video.duration || 0), done: true,
    title: s.entryLabel || s.movie.title, poster: s.movie.poster, series: s.seriesTitle || "" });
  const next = s.playlist && s.playlist[0];
  if (next) playEpisode(state.seriesDetail, next.entry, pickVariant(next.variants, s.seriesKey));
  else closePlayer();
});
video.addEventListener("error", () => {
  const s = state.play;
  hideSpinner();
  if (!s || !s.variants || s.variants.length < 2 || P.autoDowngraded) {
    if (s) say("הקובץ לא ניתן לניגון בדפדפן הזה", "bad");
    return;
  }
  P.autoDowngraded = true;
  const smallest = s.variants.slice().sort((a, b) => (a.size || 0) - (b.size || 0))[0];
  say("מנסה איכות אחרת…");
  openPlayer(smallest, Object.assign({}, s, { movie: smallest, start: P.video.currentTime || 0 }));
});

$("p-close").addEventListener("click", closePlayer);
$("p-play").addEventListener("click", togglePlay);
$("p-play2").addEventListener("click", togglePlay);
$("p-back10").addEventListener("click", () => seekBy(-10));
$("p-fwd10").addEventListener("click", () => seekBy(10));
$("p-next").addEventListener("click", () => {
  const next = state.play && state.play.playlist && state.play.playlist[0];
  if (next) playEpisode(state.seriesDetail, next.entry, pickVariant(next.variants, state.play.seriesKey));
});
$("p-next-go").addEventListener("click", () => $("p-next").click());
$("p-next-cancel").addEventListener("click", () => $("p-next-card").classList.add("hidden"));
$("p-fs").addEventListener("click", () => {
  const el = $("player");
  if (document.fullscreenElement) document.exitFullscreen();
  else if (el.requestFullscreen) el.requestFullscreen().catch(() => {});
});
$("p-pip").addEventListener("click", async () => {
  try {
    if (document.pictureInPictureElement) await document.exitPictureInPicture();
    else await P.video.requestPictureInPicture();
  } catch (e) { say("תמונה בתוך תמונה אינה נתמכת כאן", "warn"); }
});
$("p-bar").addEventListener("click", (e) => {
  const v = P.video;
  if (!v || !isFinite(v.duration)) return;
  const rect = $("p-bar").getBoundingClientRect();
  // RTL: the bar is filled from the right, so the fraction is measured from the right edge
  const frac = Math.min(1, Math.max(0, (rect.right - e.clientX) / rect.width));
  v.currentTime = frac * v.duration;
});
document.addEventListener("keydown", (e) => {
  if ($("player").classList.contains("hidden")) {
    if (e.key === "/" && document.activeElement !== $("q")) { e.preventDefault(); $("q").focus(); }
    if (e.key === "Escape") $("modal").classList.add("hidden");
    return;
  }
  if (e.target.tagName === "INPUT") return;
  const k = e.key.toLowerCase();
  if (k === " " || k === "k") { e.preventDefault(); togglePlay(); }
  else if (e.key === "ArrowLeft") seekBy(10);
  else if (e.key === "ArrowRight") seekBy(-10);
  else if (k === "f") $("p-fs").click();
  else if (k === "n") $("p-next").click();
  else if (k === "escape") closePlayer();
});

/* ── film details ─────────────────────────────────────────────────────────────────────────── */
function openModal(id) {
  const m = findAnywhere(id);
  if (!m) return;
  const p = progressOf(m);
  $("modal-card").innerHTML =
    '<div class="modal-hero" style="background-image:url(\'api/backdrop/' + encodeURIComponent(m.id) + '\')">' +
    '<div class="scrim"></div><button class="icon-btn modal-close" id="modal-x" type="button" ' +
    'aria-label="סגירה" title="סגירה (Esc)">' + IC.x + "</button></div>" +
    '<div class="modal-body"><h2>' + esc(m.title) + "</h2>" +
    '<div class="modal-meta">' + metaHTML(m, [fmtDur(m.duration), fmtSize(m.size)]) + "</div>" +
    '<div class="modal-actions"><button class="btn primary" id="modal-play" type="button">' + IC.play + " " +
    (p > 0.02 ? "המשך צפייה" : "נגן") + '</button>' +
    '<button class="btn ghost" id="modal-prefetch" type="button">שמור במטמון</button></div>' +
    "<p>" + esc(m.description || "") + "</p>" +
    '<div class="kv"><div class="k">צ׳אט</div><div class="num">' + esc(String(m.chat_id)) + "</div>" +
    '<div class="k">מזהה</div><div class="num ltr">' + esc(m.id) + "</div></div></div>";
  $("modal").classList.remove("hidden");
  $("modal").setAttribute("aria-hidden", "false");
  $("modal-x").addEventListener("click", () => $("modal").classList.add("hidden"));
  $("modal-play").addEventListener("click", () => { $("modal").classList.add("hidden"); playById(id); });
  $("modal-prefetch").addEventListener("click", async () => {
    const r = await api("api/prefetch/" + encodeURIComponent(id), { method: "POST" }).catch(() => null);
    // «לא נשמר» (or the service's reason) is a failure and reads as one — it had the look of good news
    say(r && r.cached ? "כבר שמור במטמון" : (r && r.queued ? "נשמר ברקע" : ((r && r.reason) || "לא נשמר")),
        r && (r.cached || r.queued) ? "ok" : "bad");
  });
}

/* ── data ─────────────────────────────────────────────────────────────────────────────────── */
async function loadLibrary() {
  const q = state.query.trim();
  const res = await Promise.all([
    api("api/catalog" + (q ? "?q=" + encodeURIComponent(q) : "")),
    api("api/series"),
    api("api/catalog?limit=400"),
  ]);
  state.catalog = res[0];
  state.series = res[1].series || [];
  state.films = (res[2].rows || []).reduce((a, r) => a.concat(r.movies), [])
    .filter((m) => !m.series_key).slice(0, 400);
  state.job = res[0].sync || state.job;
}
function renderChip() {
  const chip = $("chip"), text = $("chip-text"), st = state.status || {}, job = state.job;
  chip.className = "chip";
  if (job && job.state === "running") {
    chip.classList.add("busy");
    const pct = job.total ? Math.round((job.index / job.total) * 100) : 0;
    text.textContent = "סורק " + pct + "%";
    $("syncbar").classList.remove("hidden");
    $("syncbar-fill").style.width = pct + "%";
  } else {
    $("syncbar").classList.add("hidden");
    if (st.ok) {
      const c = st.counts || {};
      text.textContent = (c.movies || 0) + " סרטים · " + state.series.length + " סדרות";
    } else {
      chip.classList.add("bad");
      text.textContent = st.instance ? "החיבור לטלגרם דורש טיפול" : "לא מחובר";
    }
  }
}

/* ── settings ─────────────────────────────────────────────────────────────────────────────── */
function renderAccount() {
  const st = state.status || {};
  $("account-box").innerHTML = [
    ["חשבון", st.ok ? ((st.user && (st.user.name || st.user.username)) || st.label || "מחובר") : "לא מחובר"],
    ["מזהה", st.instance || "—"],
    ["טלפון", st.account_hint || "—"],
    ["ספרייה", ((st.counts || {}).movies || 0) + " סרטים"],
  ].map((kv) => '<div class="k">' + esc(kv[0]) + '</div><div class="num">' + esc(kv[1]) + "</div>").join("");
}
async function renderCache() {
  try {
    const c = await api("api/cache");
    const pct = c.budget_bytes ? Math.min(100, (c.bytes / c.budget_bytes) * 100) : 0;
    $("cache-fill").style.width = pct + "%";
    $("cache-hint").textContent = (c.bytes / 1024 ** 3).toFixed(2) + " / " + (c.budget_bytes / 1024 ** 3).toFixed(1) + " GB";
    $("cache-box").innerHTML = [["קבצים", String(c.files)], ["מוריד כעת", String((c.downloading || []).length)],
      ["בתור", String(c.queued || 0)]]
      .map((kv) => '<div class="k">' + esc(kv[0]) + '</div><div class="num">' + esc(kv[1]) + "</div>").join("");
  } catch (e) { /* the drawer is not worth an error state */ }
}
function renderChats() {
  const filter = ($("chat-filter").value || "").trim().toLowerCase();
  const list = state.chats.filter((c) => !filter || String(c.title || "").toLowerCase().indexOf(filter) >= 0);
  $("chat-count").textContent = state.chats.filter((c) => c.enabled).length + " מתוך " + state.chats.length + " מסומנים";
  $("chat-list").innerHTML = list.length ? list.map((c) =>
    '<div class="chat-row" data-id="' + c.chat_id + '">' +
    '<input type="checkbox" ' + (c.enabled ? "checked" : "") + ' aria-label="' + esc(c.title) + '">' +
    '<div><div class="nm">' + esc(c.title) + "</div>" +
    '<div class="sub2">' + (c.movie_count || 0) + " סרטים · " + esc(c.kind) +
    (c.username ? " · @" + esc(c.username) : "") + (c.has_video ? "" : " · אין וידאו") + "</div></div>" +
    '<div style="display:flex;gap:6px;align-items:center">' +
    '<select aria-label="שיטה">' + state.scrapers.map((s) =>
      '<option value="' + esc(s.id) + '"' + (c.scraper === s.id ? " selected" : "") + ">" + esc(s.label) + "</option>").join("") +
    "</select>" +
    '<input type="number" min="0" step="100" value="' + (c.scan_limit || "") + '" placeholder="400" title="כמה הודעות לסרוק" aria-label="עומק סריקה">' +
    "</div></div>").join("")
    : '<div class="chat-row"><div></div><div class="nm">אין צ׳אטים תואמים</div><div></div></div>';

  $("chat-list").querySelectorAll(".chat-row[data-id]").forEach((row) => {
    const id = row.dataset.id;
    row.querySelector("input[type=checkbox]").addEventListener("change", async (e) => {
      try {
        await api("api/chats/" + id, { method: "POST", body: { enabled: e.target.checked } });
        say(e.target.checked ? "הצ׳אט נוסף לספרייה — הסנכרון רץ" : "הצ׳אט הוסר מהספרייה");
        await refreshAll();
      } catch (err) { say("עדכון נכשל: " + err.message, "bad"); }
    });
    row.querySelector("select").addEventListener("change", async (e) => {
      try {
        await api("api/chats/" + id, { method: "POST", body: { scraper: e.target.value } });
        say("השיטה עודכנה — הסנכרון ירוץ מחדש לצ׳אט הזה");
        await refreshAll();
      } catch (err) { say("עדכון נכשל: " + err.message, "bad"); }
    });
    row.querySelector("input[type=number]").addEventListener("change", async (e) => {
      try {
        await api("api/chats/" + id, { method: "POST", body: { scan_limit: Number(e.target.value) || 0 } });
        say("עומק הסריקה עודכן");
        await refreshAll();
      } catch (err) { say("עדכון נכשל: " + err.message, "bad"); }
    });
  });
}
async function searchDialogs() {
  const q = ($("dialog-filter").value || "").trim();
  const box = $("dialog-results");
  if (!q) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  box.innerHTML = '<div class="chat-row"><div></div><div class="nm">מחפש בטלגרם…</div><div></div></div>';
  try {
    const d = await api("api/dialogs?q=" + encodeURIComponent(q));
    box.innerHTML = d.dialogs.length ? d.dialogs.map((x) =>
      '<div class="chat-row" data-adopt="' + x.chat_id + '">' +
      '<span class="sub2">' + esc(x.kind) + "</span>" +
      '<div><div class="nm">' + esc(x.title) + "</div><div class=\"sub2\">" +
      (x.username ? "@" + esc(x.username) + " · " : "") +
      (x.in_library ? x.movie_count + " סרטים בספרייה" : "לא בספרייה") + "</div></div>" +
      '<button class="btn' + (x.in_library ? " ghost" : " primary") + '" type="button"' +
      (x.in_library ? " disabled" : "") + ">" + (x.in_library ? "בספרייה" : "הוסף") + "</button></div>").join("")
      : '<div class="chat-row"><div></div><div class="nm">לא נמצא</div><div></div></div>';
    box.querySelectorAll("[data-adopt]").forEach((row) => {
      const btn = row.querySelector("button");
      if (btn.disabled) return;
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api("api/chats/adopt", { method: "POST", body: { chat_id: Number(row.dataset.adopt) } });
          say("נוסף לספרייה — הסורק רץ ברקע");
          await refreshAll();
        } catch (e) { say("לא נוסף: " + e.message, "bad"); btn.disabled = false; }
      });
    });
  } catch (e) {
    box.innerHTML = '<div class="chat-row"><div></div><div class="nm">החיפוש נכשל: ' + esc(e.message) + "</div><div></div></div>";
  }
}

/* ── connection wizard ────────────────────────────────────────────────────────────────────── */
function showLoginError(msg) {
  const el = $("login-error");
  el.classList.toggle("hidden", !msg);
  el.textContent = msg || "";
}
function renderLogin(step) {
  const s = step || {};
  const show = (id, on) => $(id).classList.toggle("hidden", !on);
  show("step-qr", s.step === "qr");
  show("step-phone", s.step === "idle" || s.step === "failed" ||
    (s.mode === "phone" && s.step !== "code" && s.step !== "password"));
  show("step-code", s.step === "code");
  show("step-password", s.step === "password");
  $("btn-cancel").classList.toggle("hidden", ["qr", "code", "password"].indexOf(s.step) < 0);
  if (s.qr_svg) $("qr-img").src = s.qr_svg;
  $("qr-hint").textContent = s.hint || "";
  showLoginError(s.error || null);
}
async function pollLogin() {
  const s = await api("api/login/state");
  renderLogin(s);
  if (s.step === "connected") {
    say(s.hint || "החשבון חובר");
    $("connect").classList.add("hidden");
    await refreshAll();
    return;
  }
  if (["qr", "starting"].indexOf(s.step) >= 0) setTimeout(pollLogin, 2000);
}
async function startLogin(mode) {
  showLoginError(null);
  const phone = $("phone").value.replace(/[^\d+]/g, "");
  if (mode === "phone" && !phone) { showLoginError("צריך מספר טלפון עם קידומת מדינה"); return; }
  try {
    const s = await api("api/login/start", { method: "POST", body: {
      mode: mode, phone: phone, api_id: $("api-id").value.trim() || undefined,
      api_hash: $("api-hash").value.trim() || undefined } });
    renderLogin(s);
    if (s.step === "qr") pollLogin();
  } catch (e) { showLoginError(e.message); }
}

/* ── boot ─────────────────────────────────────────────────────────────────────────────────── */
async function refreshAll() {
  state.status = await api("api/status");
  const chats = await api("api/chats");
  state.chats = chats.chats || [];
  state.scrapers = chats.scrapers || [];
  await loadLibrary();
  const connect = !state.status.ok;
  $("connect").classList.toggle("hidden", !connect);
  if (connect) {
    const st = await api("api/login/state").catch(() => ({ step: "idle" }));
    renderLogin(st.step === "idle" ? { step: "idle", mode: state.mode } : st);
    if (["qr", "starting"].indexOf(st.step) >= 0) pollLogin();
  }
  renderChip(); renderAccount(); renderChats();
  renderHero(); renderRows(); renderSeriesGrid(); renderFilms();
  renderCache();
}
let pollMs = 15000;
async function tick() {
  if (document.hidden) return;                     // a background tab does not need to poll at all
  try {
    const before = state.job && state.job.state;
    state.status = await api("api/status");
    state.job = state.status.job;
    renderChip();
    const now = state.job && state.job.state;
    if (before === "running" && now !== "running") {
      const j = state.job || {};
      const more = j.remaining ? " — נותרו " + j.remaining + " צ׳אטים לסבב הבא" : "";
      say(now === "done" ? "הסנכרון הסתיים: " + (j.movies || 0) + " סרטים" + more
                           : "הסנכרון נעצר: " + (j.error || now), now === "done" ? "ok" : "bad");
      await refreshAll();
    }
  } catch (e) { /* a failed poll is not worth a banner; the next one tells the story */ }
  // 3s while a sync or a player is live, 15s when the library is simply sitting there
  const busy = (state.job && state.job.state === "running") ||
               !$("player").classList.contains("hidden");
  const want = busy ? 3000 : 15000;
  if (want !== pollMs) { pollMs = want; schedulePoll(); }
}
function schedulePoll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => { await tick(); schedulePoll(); }, pollMs);
}
let pollTimer = null;

document.querySelectorAll(".bnv-item[data-view]").forEach((b) =>
  b.addEventListener("click", () => setView(b.dataset.view)));
document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
  state.mode = tab.dataset.mode;
  renderLogin({ step: "idle", mode: state.mode });
}));
$("btn-phone").addEventListener("click", () => startLogin("phone"));
$("btn-code").addEventListener("click", async () => {
  try { renderLogin(await api("api/login/code", { method: "POST", body: { code: $("code").value.trim() } })); }
  catch (e) { showLoginError(e.message); }
});
$("btn-password").addEventListener("click", async () => {
  try { renderLogin(await api("api/login/password", { method: "POST", body: { password: $("password").value } })); }
  catch (e) { showLoginError(e.message); }
});
$("btn-cancel").addEventListener("click", async () => { renderLogin(await api("api/login/cancel", { method: "POST" })); });
$("btn-settings").addEventListener("click", () => {
  $("drawer").classList.remove("hidden");
  $("drawer").setAttribute("aria-hidden", "false");
  renderAccount(); renderChats(); renderCache();
});
$("drawer-close").addEventListener("click", () => {
  $("drawer").classList.add("hidden");
  $("drawer").setAttribute("aria-hidden", "true");
});
$("chat-filter").addEventListener("input", renderChats);
$("btn-dialog-search").addEventListener("click", searchDialogs);
$("dialog-filter").addEventListener("keydown", (e) => { if (e.key === "Enter") searchDialogs(); });
$("btn-sync").addEventListener("click", async () => {
  say("הסנכרון רץ ברקע");
  try { state.job = (await api("api/sync", { method: "POST", body: {} })).job; renderChip(); }
  catch (e) { say("הסנכרון לא התחיל: " + e.message, "bad"); }
});
$("btn-full-sync").addEventListener("click", async () => {
  try { state.job = (await api("api/sync", { method: "POST", body: { full: true } })).job; renderChip(); }
  catch (e) { say("הסנכרון לא התחיל: " + e.message, "bad"); }
});
$("btn-relogin").addEventListener("click", () => {
  $("connect").classList.remove("hidden");
  $("connect").scrollIntoView({ block: "start" });
});
$("empty-sync").addEventListener("click", () => $("btn-sync").click());
$("hero-play").addEventListener("click", () => {
  const pick = state.heroPick;
  if (pick) playById(pick.movie.id, pick.resume);
});
$("hero-info").addEventListener("click", () => { if (state.heroPick) openModal(state.heroPick.movie.id); });
$("series-back").addEventListener("click", () => setView("series"));
$("modal").addEventListener("click", (e) => { if (e.target === $("modal")) $("modal").classList.add("hidden"); });

let searchTimer = null;
$("q").addEventListener("input", (e) => {
  state.query = e.target.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { renderRows(); renderSeriesGrid(); renderFilms(); }, 220);
});

function deepLink() {
  // ?play=<movie id>&t=<seconds>  — opens the player straight away
  // ?series=<key>                 — opens one show's page
  const p = new URLSearchParams(location.search);
  const play = p.get("play");
  const series = p.get("series");
  if (series) return openSeries(series);
  if (play) {
    const t = Number(p.get("t") || 0);
    return playById(play, t > 0 ? t : undefined);
  }
  return null;
}

(async function boot() {
  try { await refreshAll(); }
  catch (e) { banner("טעינת האפליקציה נכשלה: " + e.message, "error"); }
  try { await deepLink(); } catch (e) { say("הקישור לא נפתח: " + e.message, "bad"); }
  schedulePoll();
})();
