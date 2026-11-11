// return.js — the screen a deep link named survives the sign-in (DGO-569).
//
// The part of an address after `#` — the console's `#/m/<app>/<path>` — never reaches a server. The browser
// carries it across the redirects that brought it to this page, but the form's return-to was written by the
// server, which never saw it: a signed-out phone that opened a link to one screen landed on the console's home
// once it had signed in. So it is put back here, on the form's return-to, when that has none. The server
// checks the return-to exactly as before (okReturnTo: the scheme and the host), and a fragment moves no host.
(function () {
  var h = location.hash;
  if (!h || h.length < 2) return;
  var fields = document.querySelectorAll('form input[name="rd"]');
  for (var i = 0; i < fields.length; i++) {
    var f = fields[i];
    if (f.value && f.value.indexOf("#") < 0) f.value += h;
  }
})();
