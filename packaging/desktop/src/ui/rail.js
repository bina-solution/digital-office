// The office rail's behaviour: draw the offices the app holds, mark the one on screen, switch on a click.
'use strict';
(async function () {
  const dgo = window.dgo || window.parent.dgoSim;
  const t = window.dgoWords(dgo.locale);
  document.documentElement.dir = t.dir;
  const ul = document.getElementById('offices');
  const add = document.getElementById('add');
  add.title = t.addOffice;
  add.setAttribute('aria-label', t.addOffice);
  add.onclick = () => dgo.addOffice();

  function draw({ offices, current }) {
    ul.replaceChildren(...offices.map((o, i) => {
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'office';
      b.title = `${o.local ? t.thisComputer : o.label} · ${o.origin}${i < 9 ? ` · Ctrl+${i + 1}` : ''}`;
      b.setAttribute('aria-label', o.local ? t.thisComputer : o.label);
      if (o.origin === current) b.setAttribute('aria-current', 'true');
      if (o.local) {
        b.append(document.getElementById('mark').content.cloneNode(true));
        const live = document.createElement('span');
        live.className = `live ${o.running ? 'on' : ''}`;
        b.append(live);
      } else {
        b.append(document.createTextNode(o.label.slice(0, 2).toUpperCase()));
      }
      if (o.badge) {
        const n = document.createElement('span');
        n.className = 'badge';
        n.textContent = o.badge > 99 ? '99+' : String(o.badge);
        b.append(n);
      }
      b.onclick = () => dgo.open(o.origin);
      li.append(b);
      return li;
    }));
  }
  dgo.on('offices', draw);
  draw(await dgo.offices());
})();
