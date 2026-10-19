/* ═══════════════════════════════════════════════════════════════════════════════════════════════
   bina-said.js — what a failed request is CALLED when the service sent no sentence of its own.

   Every screen has a request helper, and eight of them ended the same way:

       body.error || "HTTP " + r.status

   A service that is down is exactly the service that cannot send a sentence, so that is when the
   owner read «HTTP 502» — the wire's word for it — in red, on a Hebrew screen. Two screens said
   «תשובה שאינה JSON»; three more printed whatever `fetch` throws ("Failed to fetch"). Measured
   2026-10-07: 20 places in 8 files. A status is not something a person can act on; what happened is.

   USE:
       const r = await fetch(url, opt).catch(binaNoAnswer);     // never rejects: status 0 = nothing answered
       const body = await r.json().catch(() => ({}));
       if (!r.ok) throw new Error(body.error || binaSaid(r.status));

   The service's own sentence always wins. The status still reaches whoever debugs: it is in the
   browser's network panel, where it belongs.

   COPIED, NOT LINKED (see bina-page.css for why): every screen carries this block verbatim and
   gate G27 fails the build when a copy stops matching. Edit HERE, then:

       python3 scripts/refactor/theme-token-lint.py --fix
   ═══════════════════════════════════════════════════════════════════════════════════════════════ */
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
