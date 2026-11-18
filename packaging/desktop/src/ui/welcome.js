// The first run's behaviour. `window.dgo` is the app's bridge (src/preload-shell.js); the simulation
// (sim/index.html) hands the same calls in as `parent.dgoSim`, so the screens it shows are these files.
'use strict';
(async function () {
  const dgo = window.dgo || window.parent.dgoSim;
  const t = window.dgoWords(dgo.locale);
  const $ = (id) => document.getElementById(id);
  document.documentElement.dir = t.dir;
  document.documentElement.lang = t.dir === 'rtl' ? 'he' : 'en';
  for (const k of ['title', 'tagline', 'connectTitle', 'connectText', 'localTitle']) $(k).textContent = t[k];
  document.title = t.title;
  $('addrLabel').textContent = t.address;
  $('connect').textContent = t.connect;
  $('foot').textContent = t.version(dgo.version);

  const list = await dgo.offices();
  if (list.offices.length) {
    $('back').hidden = false;
    $('back').textContent = t.back;
    $('back').onclick = () => dgo.back();
  }

  // ── connect to an office ──
  const said = (text, cls) => { $('connectSaid').textContent = text; $('connectSaid').className = `said ${cls || ''}`; };
  $('connectForm').onsubmit = async (e) => {
    e.preventDefault();
    $('connect').disabled = true;
    said(t.checking);
    const r = await dgo.probe($('addr').value);
    if (r.error) said(t.err[r.error] || r.error, 'bad');
    else if (r.kind === 'not-office') said(t.notOffice, 'bad');
    else { said(t.found(r.origin), 'ok'); await dgo.connect(r.origin); }
    $('connect').disabled = false;
  };

  // ── the office on this computer ──
  const lines = $('localLines');
  function showLocal(s) {
    const dot = $('localDot'), btn = $('localBtn');
    dot.className = `dot ${s.running ? 'on' : s.starting ? 'wait' : ''}`;
    $('localState').textContent = s.running ? t.localOn : s.starting ? t.starting : s.installed ? t.localOff : t.localNone;
    btn.hidden = !!s.starting;
    btn.textContent = s.running ? t.open : s.installed ? t.start : t.install;
    btn.onclick = s.running ? () => dgo.connect(s.origin) : s.installed ? () => dgo.local.start() : () => dgo.local.install();
  }
  $('localState').textContent = t.localChecking;
  dgo.on('local-state', showLocal);
  dgo.on('local-line', (line) => {
    lines.hidden = false;
    lines.textContent += `${line}\n`;
    lines.scrollTop = lines.scrollHeight;
  });
  showLocal(await dgo.local.status());
})();
