/* cad.js (cad-api: static/) — the caps as digital replicas, for a person (DGO-1091).
 *
 * The gallery lists /api/caps. A cap's page builds the same job three ways from one form: /quote (pieces, sheets,
 * BOM, cost, the rules it took for granted), /model?format=glb (the cap folded, shown here) and ?format=step (a
 * download for FreeCAD or the shop). The sizes live in the page's address, so a link opens that very cap.
 * Colours come from the office's tokens; the 3D scene's lights and metals are numbers (three.js takes no token).
 */

const api = (path, body) => fetch(path, body === undefined ? {} : {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
}).then(async (r) => {
  if (r.ok) return r;
  let said = '';
  try { said = (await r.json()).detail; } catch (e) { /* not JSON: the status says it */ }
  throw new Error(said || `the CAD service answered ${r.status}`);
});

const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') n.textContent = v; else if (v !== undefined && v !== null) n.setAttribute(k, v);
  }
  for (const k of kids) n.append(k);
  return n;
};

const GROUP = { brick: 'over the crown (brick)', flue: 'over a flue or a chase' };

// a size to open each cap with when its link carries none — the shop's own examples where there is one (DGO-1076)
const DEMO = {
  tee: { L: 24, W: 24 }, turtle: { L: 30, W: 20 }, standard: { L: 30, W: 24 }, pitched: { L: 36, W: 24 },
};
const demo = (id) => DEMO[id] || { L: 30, W: 24 };

export async function gallery(box, shop) {
  try {
    const d = await (await api('/api/caps')).json();
    if (shop && d.shop) shop.textContent = d.shop;
    box.replaceChildren(...d.caps.map((c) => el('a', { class: 'card', href: `/caps/${encodeURIComponent(c.id)}` },
      el('h2', { text: c.title }),
      el('span', { class: 'chip', text: GROUP[c.group] || c.group }),
      el('span', { class: 'chip', text: `${c.params.length} sizes and options` }),
      el('p', { class: 'src', text: c.source || '' }))));
  } catch (e) {
    box.replaceChildren(el('p', { class: 'err', text: `The caps did not load: ${e.message}` }));
  }
}

const money = (c) => `$${(c / 100).toFixed(2)}`;
const inch = (v) => (Math.round(v * 100) / 100).toString();

function fieldFor(p, value) {
  const id = `f_${p.key}`;
  let input;
  if (p.kind === 'choice') {
    input = el('select', { id, name: p.key });
    for (const o of p.options) input.append(el('option', { value: o, text: o }));
    input.value = value ?? p.default;
  } else if (p.kind === 'list') {
    input = el('input', { id, name: p.key, type: 'text', placeholder: '[{"d": 8, "x": 0, "y": 0}]' });
    input.value = value ? (typeof value === 'string' ? value : JSON.stringify(value)) : '';
  } else {
    input = el('input', { id, name: p.key, type: 'number', step: 'any', min: p.min, max: p.max, required: p.default === null ? '' : null });
    input.value = value ?? (p.default ?? '');
  }
  const unit = p.unit ? ` (${p.unit})` : '';
  return el('label', { for: id, class: p.kind === 'list' ? 'wide' : null }, `${p.label}${unit}`, input);
}

function readForm(form, cap) {
  const params = {};
  for (const p of cap.params) {
    const v = form.elements[p.key].value.trim();
    if (v === '') continue;
    if (p.kind === 'choice') params[p.key] = v;
    else if (p.kind === 'list') params[p.key] = JSON.parse(v);
    else params[p.key] = Number(v);
  }
  return { params, material: form.elements.material.value };
}

function writeAddress(job) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(job.params)) q.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
  q.set('material', job.material);
  history.replaceState(null, '', `${location.pathname}?${q}`);
}

function table(node, head, rows) {
  node.replaceChildren(el('tr', {}, ...head.map(([t, cls]) => el('th', { class: cls, text: t }))),
    ...rows.map((r) => el('tr', {}, ...r.map(([t, cls]) => el('td', { class: cls, text: t })))));
}

function drawSheets(box, sheets) {
  const NS = 'http://www.w3.org/2000/svg';
  box.replaceChildren(...sheets.map((s, i) => {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${s.w} ${s.h}`);
    svg.setAttribute('width', 160);
    svg.setAttribute('height', Math.round(160 * s.h / s.w));
    for (const p of s.placed) {
      const r = document.createElementNS(NS, 'rect');
      for (const [k, v] of Object.entries({ x: p.x, y: p.y, width: p.w, height: p.h, class: 'piece' })) r.setAttribute(k, v);
      const t = document.createElementNS(NS, 'title');
      t.textContent = `${p.name}: ${inch(p.w)} × ${inch(p.h)} in${p.rotated ? ' (turned)' : ''}`;
      r.append(t);
      svg.append(r);
    }
    return el('div', { class: 'sheet' }, svg, el('div', { class: 'src', text: `Sheet ${i + 1}: ${s.w} × ${s.h} in, ${s.placed.length} pieces` }));
  }));
}

function showQuote(q) {
  const c = q.cost;
  document.getElementById('price').replaceChildren(document.createTextNode(c.price),
    el('small', { text: ` — cost ${c.cost} × ${c.markup}` }));
  document.getElementById('priceWhy').textContent =
    `${c.sheet_charge === 'whole' ? 'Whole sheets' : 'The share of the sheets used'} (whole sheets: ${c.price_whole_sheets}; ` +
    `the share used: ${c.price_used_share}). The multiplier: ${c.price_source}. Price list ${c.price_list}.`;
  table(document.getElementById('cost'), [['Item'], ['Qty', 'num'], ['Each', 'num'], ['Cost', 'num'], ['Where the number comes from']],
    c.lines.map((l) => [[l.item], [`${l.qty} ${l.unit}`, 'num'], [money(l.each_cents), 'num'], [money(l.cents), 'num'], [l.source, 'why']]));
  const b = q.bom;
  // sheet_fill is the sheets' fills added up, so it is averaged here; copper's thickness is in ounces, not a gauge
  table(document.getElementById('bom'), [['What'], ['How much', 'num']], [
    [[`Sheets of ${b.metal}, ${b.gauge} ${b.metal === 'copper' ? 'oz' : 'ga'}`],
      [`${b.sheets} (filled ${Math.round(100 * b.sheet_fill / Math.max(1, b.sheets))}%)`, 'num']],
    [['Mesh'], [`${inch(b.mesh_in2 / 144)} ft²`, 'num']],
    [['Rivets'], [String(b.rivets), 'num']],
    [['Caulk'], [`${b.caulk_tubes} tube`, 'num']],
    [['Bends'], [String(b.bends), 'num']],
    [[`Shop hours — ${b.hours_why}`], [String(b.hours), 'num']],
  ]);
  table(document.getElementById('parts'), [['Piece'], ['Qty', 'num'], ['Blank (in)', 'num'], ['Bends', 'num'], ['Note']],
    q.parts.map((p) => [[p.name], [String(p.qty), 'num'], [`${inch(p.blank[0])} × ${inch(p.blank[1])}`, 'num'], [String(p.bends), 'num'], [p.note || '', 'why']]));
  drawSheets(document.getElementById('sheets'), q.sheets);
  document.getElementById('notes').replaceChildren(...(q.notes.length ? q.notes : ['No rule was taken for granted.'])
    .map((n) => el('li', { class: /^ASSUMED/.test(n) ? 'assumed' : null, text: n })));
  document.getElementById('errors').textContent = (q.errors || []).join(' · ');
}

const METAL = { galvanized: 0xb8bec4, galvalume: 0xa9b0b5, stainless: 0xc9ccce, copper: 0xb87333,
                prepainted: 0x2e2f30, paintgrip: 0x8d9296, bonderized: 0x6e7378 };

export async function viewer(box) {
  const THREE = await import('three');
  const { OrbitControls } = await import('/static/vendor/jsm/controls/OrbitControls.js');
  const { GLTFLoader } = await import('/static/vendor/jsm/loaders/GLTFLoader.js');
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  box.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue('--surface-2').trim() || 'white');
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x666666, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 2.4);
  sun.position.set(60, 120, 80);
  scene.add(sun);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  const fit = () => {
    const w = box.clientWidth, h = box.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(fit).observe(box);
  fit();
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
  let current = null;
  return (buffer, metal) => new Promise((resolve, reject) => new GLTFLoader().parse(buffer, '', (gltf) => {
    if (current) scene.remove(current);
    current = gltf.scene;
    // metal === null: the file's own materials (a FreeCAD model paints each part its metal, the fasteners theirs)
    if (metal !== null) {
      const mat = new THREE.MeshStandardMaterial({ color: METAL[metal] ?? METAL.galvanized, metalness: 0.75, roughness: 0.35, side: THREE.DoubleSide });
      current.traverse((o) => { if (o.isMesh) o.material = mat; });
    } else {
      current.traverse((o) => { if (o.isMesh && o.material) { o.material.side = THREE.DoubleSide; o.material.metalness = 0.6; o.material.roughness = 0.4; } });
    }
    scene.add(current);
    const box3 = new THREE.Box3().setFromObject(current);
    const size = box3.getSize(new THREE.Vector3()).length() || 1;
    const centre = box3.getCenter(new THREE.Vector3());
    controls.target.copy(centre);
    camera.position.copy(centre).add(new THREE.Vector3(size * 0.75, size * 0.55, size * 0.95));
    camera.near = size / 100; camera.far = size * 20; camera.updateProjectionMatrix();
    resolve();
  }, reject));
}

function save(blob, name) {
  const a = el('a', { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

// what a failed build leaves on screen: nothing that belongs to other sizes than the address now says
function clearQuote() {
  document.getElementById('price').textContent = '—';
  document.getElementById('priceWhy').textContent = '';
  for (const k of ['cost', 'bom', 'parts', 'sheets', 'notes']) document.getElementById(k).replaceChildren();
}

export async function capPage() {
  // the server takes a cap's name in any case and with spaces around it (caps.get), so the page does too
  const id = decodeURIComponent(location.pathname.split('/').filter(Boolean).pop()).trim().toLowerCase();
  const state = document.getElementById('viewState');
  let d;
  try {
    d = await (await api('/api/caps')).json();
  } catch (e) {
    document.getElementById('title').textContent = 'The caps did not load';
    state.textContent = e.message;
    return;
  }
  const cap = d.caps.find((c) => c.id === id);
  if (!cap) { document.getElementById('title').textContent = `No cap named ${id}`; return; }
  document.title = `${cap.title} — digital replica`;
  document.getElementById('title').textContent = cap.title;
  document.getElementById('group').textContent = GROUP[cap.group] || cap.group;
  document.getElementById('source').textContent = `Where its rules come from: ${cap.source}`;

  const q = new URLSearchParams(location.search);
  const start = { ...demo(id) };
  for (const p of cap.params) if (q.has(p.key)) start[p.key] = q.get(p.key);
  const form = document.getElementById('form');
  form.replaceChildren(...cap.params.map((p) => fieldFor(p, start[p.key])));
  const metal = el('select', { id: 'f_material', name: 'material' });
  for (const m of d.materials || []) metal.append(el('option', { value: m.key, text: `${m.key} — ${m.w} × ${m.h} in at ${money(m.cents)}${/^ASSUMED/.test(m.source) ? ' (assumed)' : ''}` }));
  metal.value = q.get('material') || 'galvanized';
  form.append(el('label', { for: 'f_material', class: 'wide' }, 'metal (the price list\'s sheet)', metal));

  // the 3D is one part of the page: without WebGL (or an import map) the price, the pieces and the sheets still show
  let show = null;
  try {
    show = await viewer(document.getElementById('view'));
  } catch (e) {
    state.textContent = `3D cannot be shown in this browser (${e.message}); everything else below is the same.`;
  }
  const buttons = ['build', 'step', 'glb'].map((b) => document.getElementById(b));
  const build = async () => {
    let job;
    try { job = readForm(form, cap); } catch (e) { state.textContent = `The sizes do not read: ${e.message}`; return; }
    buttons.forEach((b) => { b.disabled = true; });
    if (show) state.textContent = 'Building the model…';
    try {
      showQuote(await (await api(`/api/caps/${id}/quote`, job)).json());
      writeAddress(job);                   // the address names what is on screen, never sizes that did not build
      if (show) {
        const glb = await (await api(`/api/caps/${id}/model?format=glb`, job)).arrayBuffer();
        await show(glb, job.material);
        state.textContent = `${cap.title}, ${job.params.L} × ${job.params.W} in, ${job.material} — drag to turn, scroll to zoom.`;
      }
    } catch (e) {
      clearQuote();
      state.textContent = `Not built: ${e.message}`;
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
    }
  };
  // a download is of the sizes the form shows now, whether or not Build was pressed after the last change
  const download = (format) => async () => {
    try {
      const j = readForm(form, cap);
      const r = await api(`/api/caps/${id}/model?format=${format}`, j);
      save(await r.blob(), `cap-${id}-${j.params.L}x${j.params.W}.${format}`);
    } catch (e) { state.textContent = `No ${format.toUpperCase()}: ${e.message}`; }
  };
  document.getElementById('build').addEventListener('click', build);
  form.addEventListener('submit', (e) => { e.preventDefault(); build(); });
  // the form has no submit button of its own, so Enter in a field would do nothing
  form.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); build(); } });
  document.getElementById('step').addEventListener('click', download('step'));
  document.getElementById('glb').addEventListener('click', download('glb'));
  document.getElementById('link').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(location.href); state.textContent = 'The link to this cap is copied.'; }
    catch (e) { state.textContent = location.href; }
  });
  build();
}
