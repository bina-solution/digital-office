/* store.js — שכבת הנתונים של הממשק: קריאה מהירה, רענון מאחורי הקלעים, ועבודות עם התקדמות.
 *
 * הבעיה שהיא פותרת, בפעם אחת: חלק מהנתונים חוזרים בשנייה (API של ספק) וחלק בארבעים (דפדפן שנוהג
 * בפאנל של הרשם). מסך שממתין לאיטי שבהם הוא מסך שלא משתמשים בו, ומסך שלא אומר מה קורה הוא מסך
 * שלא מאמינים לו. לכן:
 *
 *   1. res()  — stale-while-revalidate: הערך מהמטמון מוצג מיד (גם אם ישן, עם חיווי גיל), ובקשה
 *               מרעננת אותו ברקע. מסך נצבע תמיד בפחות מ־50ms.
 *   2. run()  — פעולה שאורכת זמן היא JOB: POST שמחזיר 202 + מזהה, ואז SSE עם התקדמות והצלחה.
 *               שום חיבור HTTP לא תלוי בגמר הפעולה. כל קריאה נושאת TOKEN אידמפוטנטי, כך שלחיצה
 *               כפולה, ניסיון חוזר או רענון דף מצטרפים לאותה עבודה במקום לפתוח שנייה.
 *   3. events() — ערוץ אחד לכל המסך: כשמשהו משתנה (עבודה הסתיימה, מטמון בוטל) המסך מרענן בדיוק
 *               את מה שהשתנה, במקום לשאול את הכול כל כמה שניות.
 *
 * שומר רצף: לכל בקשה יש מספר עולה, ולתשובה שמגיעה אחרי תשובה חדשה ממנה כבר אין זכות לכתוב למטמון.
 * בלי זה, קריאה של 40 שניות שחוזרת אחרי רענון ידני דורסת את הערך הטרי — והמסך "נכון" ומוטעה.
 *
 * אין כאן ספרייה חיצונית בכוונה: שלושת הדברים האלה הם כל מה שהממשק צריך, והם ~230 שורות שאפשר
 * לקרוא במקום 40KB של תלויות.
 */
'use strict';

const Store = (() => {
  const cache = new Map();          // key → {value, at, ttl, refreshing, error}
  const watchers = new Map();       // key → Set(callbacks)
  const inflight = new Map();       // key → Promise
  const applied = new Map();        // key → the highest request sequence already written
  let counter = 0;                  // one counter for the whole app
  let es = null;
  const jobs = [];                  // recent jobs, newest first
  const jobWatchers = new Set();

  const nowMs = () => Date.now();
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

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
  async function http(path, opts) {
    const r = await fetch(path, Object.assign({ headers: { 'content-type': 'application/json' } },
      opts || {})).catch(binaNoAnswer);
    // a body that is not data is the sign-in page or the edge's own error page: named by its status
    let body = await r.json().catch(() => ({ error: binaSaid(r.status) })) || {};
    if (!r.ok && !body.error && !body.detail) body = Object.assign({}, body, { error: binaSaid(r.status) });
    return { ok: r.ok, status: r.status, body };
  }

  function notify(key) {
    const w = watchers.get(key);
    if (w) w.forEach((cb) => { try { cb(cache.get(key)); } catch (e) { /* a watcher must never break the store */ } });
  }

  function invalidate(prefix) {
    for (const key of [...cache.keys()]) if (key.startsWith(prefix)) cache.delete(key);
    if (prefix === '') cache.clear();
  }

  /** The read path. Returns the cached value IMMEDIATELY (possibly stale) and revalidates. */
  function res(key, url, opts) {
    opts = opts || {};
    const ttl = (opts.ttl || 120) * 1000;
    const entry = cache.get(key);
    const fresh = entry && nowMs() - entry.at < ttl;

    if (!opts.force && fresh) return Promise.resolve(entry);
    if (!opts.force && entry && opts.staleOk !== false) {
      revalidate(key, url, ttl);                    // serve stale, refresh behind
      return Promise.resolve(entry);
    }
    return revalidate(key, url, ttl);
  }

  function revalidate(key, url, ttl) {
    if (inflight.has(key)) return inflight.get(key);
    const mine = ++counter;
    const p = http(url).then((r) => {
      inflight.delete(key);
      // A response that started BEFORE a newer one landed has no business writing: it is older data
      // arriving later, and honouring it is how a hand-refresh gets silently undone.
      if ((applied.get(key) || 0) > mine) {
        return cache.get(key) || { value: null, ok: false, at: nowMs() };
      }
      applied.set(key, mine);
      const server = (r.body && r.body._cache) || {};
      const entry = {
        value: r.body, url, ok: r.ok, at: nowMs() - (server.age ? server.age * 1000 : 0),
        ttl, refreshing: !!server.refreshing, error: r.ok ? null : (r.body.error || r.status),
      };
      cache.set(key, entry);
      notify(key);
      // The server may be refreshing behind this answer: ask again shortly for the newer value.
      if (server.stale || server.refreshing) {
        setTimeout(() => { if (cache.get(key) === entry) revalidate(key, url, ttl); },
                   server.refreshing ? 4000 : 2000);
      }
      return entry;
    }).catch((e) => {
      // A failed fetch is DATA, not an exception: keep the last good value and say what happened.
      inflight.delete(key);
      const prev = cache.get(key);
      const entry = { value: prev ? prev.value : null, url, ok: false, at: nowMs(), ttl,
                      error: 'הרשת אינה זמינה' };
      cache.set(key, entry);
      notify(key);
      return entry;
    });
    inflight.set(key, p);
    return p;
  }

  function watch(key, cb) {
    if (!watchers.has(key)) watchers.set(key, new Set());
    watchers.get(key).add(cb);
    const e = cache.get(key);
    if (e) cb(e);
    return () => watchers.get(key).delete(cb);
  }

  function peek(key) { return cache.get(key); }

  // ── one event stream for the whole screen ──────────────────────────────────────────────────────
  function events(onEvent) {
    if (onEvent) jobWatchers.add(onEvent);
    if (es) return es;
    try {
      es = new EventSource('api/events');
      es.onmessage = (m) => {
        let ev = null;
        try { ev = JSON.parse(m.data); } catch (e) { return; }
        if (ev.type === 'invalidate') invalidate(ev.prefix || '');
        if (ev.type === 'resource' && ev.key) invalidate(ev.key);
        if (ev.type === 'job') merge(ev);
      };
      es.onerror = () => { /* EventSource reconnects on its own; the UI keeps working */ };
    } catch (e) { /* no SSE (old browser): res() still polls on focus */ }
    return es;
  }

  function merge(ev) {
    const i = jobs.findIndex((j) => j.id === ev.id);
    const merged = Object.assign(i >= 0 ? jobs[i] : { id: ev.id }, ev);
    if (i >= 0) jobs[i] = merged; else jobs.unshift(merged);
    while (jobs.length > 8) jobs.pop();
    jobWatchers.forEach((cb) => { try { cb(merged); } catch (e) {} });
    return merged;
  }

  // ── actions as jobs ────────────────────────────────────────────────────────────────────────────
  /**
   * Run one action. A long action (a panel write) comes back as a job and streams its steps; a short
   * one answers in place. `opts.client` is the idempotency token and defaults to a fresh one per
   * call — pass the SAME token to retry an intent without performing it twice.
   */
  async function run(url, body, opts) {
    opts = opts || {};
    const payload = Object.assign({}, body || {});
    if (!payload.client) payload.client = opts.client || newId();
    const r = await http(url, { method: 'POST', body: JSON.stringify(payload) });
    if (r.status === 202 && r.body && r.body.job) {
      const id = r.body.job;
      const rec = merge({ id, state: 'queued', progress: 0, message: opts.label || 'מתחיל',
                          title: opts.title || '' });
      if (r.body.deduped) rec.message = 'הפעולה הזו כבר רצה — מצטרף אליה';
      follow(id);
      return { queued: true, id, body: r.body, entry: rec };
    }
    if (r.ok) invalidate(opts.invalidates || '');
    return { queued: false, ok: r.ok, body: r.body, status: r.status };
  }

  let idCounter = 0;
  function newId() {
    idCounter += 1;
    return `${Date.now().toString(36)}-${idCounter}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function follow(id) {
    try {
      const s = new EventSource(`api/jobs/${id}/events`);
      s.onmessage = (m) => {
        let j = null;
        try { j = JSON.parse(m.data); } catch (e) { return; }
        merge(Object.assign({ id }, j));
        if (['ok', 'error', 'cancelled'].includes(j.state)) {
          s.close();
          if (j.state === 'ok') invalidate('');
        }
      };
      s.onerror = () => s.close();
    } catch (e) { /* polling fallback */ }
  }

  function activeJobs() { return jobs.filter((j) => ['queued', 'running'].includes(j.state)); }
  function onJob(cb) { jobWatchers.add(cb); }
  function jobById(id) { return jobs.find((j) => j.id === id); }

  // ── presentation helpers ───────────────────────────────────────────────────────────────────────
  const ago = (ts) => {
    if (!ts) return '';
    const s = Math.max(0, Math.floor((nowMs() - ts) / 1000));
    if (s < 10) return 'עכשיו';
    if (s < 60) return `לפני ${s} שניות`;
    if (s < 3600) return `לפני ${Math.floor(s / 60)} דקות`;
    return `לפני ${Math.floor(s / 3600)} שעות`;
  };
  /** Seconds → the way a human counts down a cache: "עוד 42 דק׳", not "2520". */
  const seconds = (n) => {
    if (n == null) return '—';
    if (n <= 0) return 'פג';
    if (n < 60) return `${Math.round(n)} שנ׳`;
    if (n < 3600) return `${Math.round(n / 60)} דק׳`;
    return `${(n / 3600).toFixed(n < 36000 ? 1 : 0)} שע׳`;
  };
  /** "how old is what you are looking at" — the badge that makes a slow source trustworthy. */
  function freshness(entry) {
    if (!entry) return '';
    if (entry.refreshing) return '<span class="fresh">מרענן…</span>';
    if (entry.error) return `<span class="fresh bad">${esc(entry.error)}</span>`;
    return `<span class="fresh">${ago(entry.at)}</span>`;
  }
  const skeleton = (rows) => Array.from({ length: rows || 3 },
    () => '<div class="skel"></div>').join('');

  /** Copy to the clipboard, and SAY SO — a copy button that does not confirm is a button nobody trusts. */
  async function copy(text, el) {
    const value = String(text == null ? '' : text);
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
      else {
        const ta = document.createElement('textarea');
        ta.value = value; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
      }
      if (el) {
        const was = el.textContent;
        el.textContent = 'הועתק';
        el.classList.add('copied');
        setTimeout(() => { el.textContent = was; el.classList.remove('copied'); }, 1200);
      }
      return true;
    } catch (e) { return false; }
  }

  window.addEventListener('focus', () => {
    for (const [key, e] of cache) if (e.url) revalidate(key, e.url, e.ttl);
  });

  return { res, watch, peek, invalidate, events, run, follow, activeJobs, onJob, jobById,
           fresh: freshness, skeleton, ago, seconds, copy, esc, http, newId };
})();
