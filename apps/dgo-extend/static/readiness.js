/* readiness — "can that office open what we send it", in the words the card shows.

   The server measures it (`GET /api/link/readiness`: its console's `/mount.js` served as CODE, and
   `shell` in its «מחשבים» manifest) and this file turns one office's answer into the two pills on its
   card. It is a separate file for one reason: the mapping is the part a person reads, and it can be
   executed in node (`tests/readiness-selftest.mjs`) — a screen that says "undefined" about another
   office is worse than one that says nothing, and that is not something to find by eye.

   The words, and why each is its own:
     · נפתח במלואו        — it has the code; nothing to do
     · דורש עדכון אצלה    — it answers and is older than the op: an update there, not a bug here
     · לא עונה            — the door did not answer at all: a link/tunnel state, not a version
     · לא משותף           — it does not publish that app to us: a sharing state, not a version either
*/
(function () {
  "use strict";
  var WORD = { ok: "נפתח במלואו", old: "דורש עדכון אצלה", down: "לא עונה", none: "לא משותף" };
  //: Which colour a state gets: green only for ok, amber for "an update there", red for anything the
  //: link or the sharing did — the card already uses these three pill styles.
  var CLS = { ok: "ok", old: "warn", down: "bad", none: "bad" };

  function word(v) { return WORD[v] || WORD.none; }
  function cls(v) { return CLS[v] || "bad"; }

  /* The two pills of one office: its CONSOLE and its TERMINAL. `esc` is injected (the screen has one,
     the test has a stub) so this file never grows a second escaping rule. */
  function cell(item, esc) {
    var it = item || {};
    var e = esc || function (s) { return String(s); };
    return '<span class="pill ' + cls(it.console) + '" title="הקונסול שלה — האם אפשר להרכיב אותו כאן">קונסול: ' + e(word(it.console)) + '</span> '
      + '<span class="pill ' + cls(it.terminal) + '" title="«מחשבים» שלה — האם יש לה טרמינל על המכונות שתקבל">טרמינל: ' + e(word(it.terminal)) + "</span>";
  }

  var out = { WORD: WORD, CLS: CLS, word: word, cls: cls, cell: cell };
  if (typeof module !== "undefined" && module.exports) module.exports = out;
  if (typeof window !== "undefined") window.DgoReadiness = out;
})();
