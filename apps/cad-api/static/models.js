/* models.js (cad-api: static/) — the office's FreeCAD models, each at its own address (FPG-621).
 *
 * /models lists every model the FreeCAD jobs published (newest first); /models/<name> is one of them: the model in 3D
 * (its own glb, its own colours), the renders, the parts list, the steps, the build sheet and every file to download,
 * and where it sits in FreeCAD. The address is the link to give: like an item's, it opens that very model.
 */
import { viewer } from '/static/cad.js?v=2';

const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') n.textContent = v; else if (v !== undefined && v !== null) n.setAttribute(k, v);
  }
  for (const k of kids) n.append(k);
  return n;
};
const enc = encodeURIComponent;
const fileUrl = (m, f) => `/models/${enc(m.name)}/files/${enc(f)}`;
const when = (s) => (s ? new Date(s * 1000).toLocaleString() : '');
// FreeCAD itself: the office's cad app, next to this one (cad-api.<office> → cad.<office>)
const freecadUrl = () => `${location.protocol}//${location.host.replace(/^cad-api\./, 'cad.')}/`;
const STYLE = { 'fpg-standard': 'Standard (the shop’s build)', 'fpg-turtle': 'Turtle Top (the shop’s build)',
                standard: 'Standard (generic)' };

export async function modelsPage(box) {
  try {
    const d = await (await fetch('/api/models')).json();
    if (!d.models.length) { box.replaceChildren(el('p', { class: 'src', text: 'No model has been built yet.' })); return; }
    box.replaceChildren(...d.models.map((m) => el('a', { class: 'card model', href: `/models/${enc(m.name)}` },
      m.files.includes('1-assembled.png') ? el('img', { class: 'thumb', src: fileUrl(m, '1-assembled.png'), alt: '', loading: 'lazy' }) : '',
      el('h2', { text: m.label }),
      el('span', { class: 'chip', text: STYLE[m.style] || m.style }),
      m.material ? el('span', { class: 'chip', text: m.material }) : '',
      el('p', { class: 'src', text: `Built ${when(m.updated)}` }))));
  } catch (e) {
    box.replaceChildren(el('p', { class: 'err', text: `The models did not load: ${e.message}` }));
  }
}

const DOWNLOADS = [['build-sheet.pdf', 'Build sheet (PDF, A3)'], ['.fcstd', 'FreeCAD model'], ['.step', 'STEP (any CAD)'],
                   ['model.glb', '3D (glb)'], ['bom.csv', 'Parts list (CSV)'], ['.flat.dxf', 'Flat patterns (DXF)']];

export async function modelPage() {
  const name = decodeURIComponent(location.pathname.replace(/^\/models\//, ''));
  let m;
  try {
    const r = await fetch(`/api/models/${enc(name)}`);
    if (!r.ok) throw new Error(r.status === 404 ? 'no such model' : `the CAD service answered ${r.status}`);
    m = await r.json();
  } catch (e) {
    document.getElementById('title').textContent = name;
    document.getElementById('view').replaceChildren(el('p', { class: 'err', text: `This model did not load: ${e.message}` }));
    return;
  }
  document.title = `${m.label} — model`;
  document.getElementById('title').textContent = m.label;
  document.getElementById('style').textContent = `${STYLE[m.style] || m.style} · ${m.material} · built ${when(m.updated)}`;

  // the 3D when the build left one, else its render; without WebGL the render stays
  const view = document.getElementById('view');
  const still = m.files.includes('1-assembled.png') ? el('img', { class: 'still', src: fileUrl(m, '1-assembled.png'), alt: m.label }) : '';
  view.replaceChildren(still);
  if (m.files.includes('model.glb')) {
    const state = el('div', { class: 'state', text: 'Loading the 3D…' });
    view.append(state);
    try {
      const show = await viewer(view);
      const buf = await (await fetch(fileUrl(m, 'model.glb'))).arrayBuffer();
      await show(buf, null);
      if (still) still.remove();
      state.textContent = 'Drag to turn it, scroll to zoom.';
    } catch (e) {
      state.textContent = `The 3D did not open here (${e.message}); the render is above.`;
    }
  }

  document.getElementById('renders').replaceChildren(...['1-assembled.png', '2-exploded.png', '3-corner.png', '4-screen-front.png']
    .filter((f) => m.files.includes(f))
    .map((f) => el('a', { href: fileUrl(m, f), target: '_blank' }, el('img', { src: fileUrl(m, f), alt: f, loading: 'lazy' }))));

  const rows = m.bom || [];
  const parts = document.getElementById('parts');
  parts.replaceChildren(el('tr', {}, ...['Part no.', 'Description', 'Material', 'Ga', 'Qty', 'Flat (in)'].map((t, i) =>
    el('th', { class: i >= 3 ? 'num' : null, text: t }))),
  ...rows.map((r) => el('tr', {}, el('td', { text: r.part_no }), el('td', { text: r.description }), el('td', { text: r.material }),
    el('td', { class: 'num', text: r.gauge }), el('td', { class: 'num', text: r.qty }), el('td', { class: 'num', text: r.flat_in }))));
  document.getElementById('steps').replaceChildren(...(m.steps || []).map(([h, b]) => el('li', {}, el('b', { text: h }), ` ${b}`)));

  const dl = document.getElementById('downloads');
  dl.replaceChildren(...DOWNLOADS.flatMap(([suffix, label]) => m.files.filter((f) => f.toLowerCase().endsWith(suffix))
    .map((f) => el('a', { class: 'btn', href: fileUrl(m, f), target: suffix.endsWith('pdf') ? '_blank' : null },
      label + (m.files.filter((x) => x.toLowerCase().endsWith(suffix)).length > 1 ? ` — ${f.split('.')[0].replace(/_/g, ' ')}` : '')))));
  document.getElementById('freecad').href = freecadUrl();
  document.getElementById('path').textContent = m.fcstd ? `${m.freecad_path}/${m.fcstd}` : m.freecad_path;
  document.getElementById('copy').onclick = async () => {
    try { await navigator.clipboard.writeText(location.href); document.getElementById('copy').textContent = 'Link copied'; } catch (e) { /* the address bar has it */ }
  };
}
