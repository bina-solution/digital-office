/* viewer.js — every file opens in place, full screen, with its neighbours a swipe or an arrow away.
   One frame (top bar · stage · prev/next) and one viewer per kind, each loading its library only
   when a file of that kind is opened (pdf.js, SheetJS, docx-preview, highlight.js, marked +
   DOMPurify, Online3DViewer, epub.js, fflate — vendored under vendor/, versioned by folder).
   A kind with no viewer here says so and offers the apps that open it, then the download.
   Nothing a file contains runs on this page: html is drawn in a sandboxed frame with no scripts,
   svg only as an <img>, markdown through DOMPurify. */
(function () {
  "use strict";
  const { html, hooks, state, set, L, ic, fmtSize, fmtWhen, fmtDur, contentUrl, thumbUrl, BASE } = F;
  const T = F.types;
  const V = "vendor/";

  const loaded = {};
  function script(src) {
    return (loaded[src] = loaded[src] || new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = BASE + V + src; s.onload = res;
      s.onerror = () => { delete loaded[src]; rej(new Error(L("רכיב התצוגה לא נטען", "The viewer could not be loaded"))); };
      document.head.appendChild(s);
    }));
  }
  const esm = (src) => (loaded[src] = loaded[src] || import(BASE + V + src));
  const bytes = async (it) => { const r = await fetch(contentUrl(it.id)); if (!r.ok) throw new Error(window.binaSaid(r.status)); return r.arrayBuffer(); };
  /* a text file, its first 2 MB at most: enough to read, never enough to hang a phone */
  const MAXTEXT = 2 * 1024 * 1024;
  async function text(it) {
    const r = await fetch(contentUrl(it.id), Number(it.size) > MAXTEXT ? { headers: { Range: "bytes=0-" + (MAXTEXT - 1) } } : {});
    if (!r.ok && r.status !== 206) throw new Error(window.binaSaid(r.status));
    const buf = await r.arrayBuffer();
    let s;
    try { s = new TextDecoder("utf-8", { fatal: true }).decode(buf); } catch (e) { s = new TextDecoder("windows-1255").decode(buf); }
    return { s, cut: Number(it.size) > MAXTEXT };
  }

  /* run an async loader inside a component: {busy, error, value} */
  function useLoad(fn, deps) {
    const [st, setSt] = hooks.useState({ busy: true });
    hooks.useEffect(() => {
      let off = false;
      setSt({ busy: true });
      fn().then((value) => !off && setSt({ value }), (e) => !off && setSt({ error: e.message || String(e) }));
      return () => (off = true);
    }, deps);
    return st;
  }
  const Spin = () => html`<div class="vw-spin" role="status" aria-label=${L("טוען", "Loading")}></div>`;
  function Msg({ it, icon, title, text: t, children }) {
    return html`<div class="vw-msg">
      <div class="ring">${ic(icon || (it ? T.icon(it) : "file"), "xl")}</div>
      <b>${title}</b>${t && html`<div>${t}</div>`}
      <div class="det-acts center">${children}</div>
    </div>`;
  }
  /* a failure is said in the office's words; the engine's own sentence stays one hover away */
  const Failed = ({ it, error }) => html`<div title=${error || ""}><${Msg} it=${it} icon="alert" title=${L("לא הצלחנו להציג את הקובץ", "This file could not be shown")}
    text=${L("אפשר להוריד אותו ולפתוח במכשיר, או לנסות שוב בעוד רגע.", "You can download it and open it on your device, or try again in a moment.")}>
    <button class="btn" onClick=${() => F.data.download(it)}>${ic("download", "sm")}${L("הורדה", "Download")}</button></${Msg}></div>`;

  /* ── image: zoom, pan, pinch, wheel, double-tap ─────────────────────── */
  function ZoomImage({ src, alt, onFail }) {
    const box = hooks.useRef(), img = hooks.useRef(), z = hooks.useRef({ s: 1, x: 0, y: 0, fit: 1 });
    const [ready, setReady] = hooks.useState(false);
    const apply = () => { const { s, x, y } = z.current; if (img.current) img.current.style.transform = `translate(${x}px,${y}px) scale(${s})`; };
    function fit() {
      const b = box.current, i = img.current; if (!b || !i || !i.naturalWidth) return;
      const s = Math.min(b.clientWidth / i.naturalWidth, b.clientHeight / i.naturalHeight, 1);
      z.current = { s, fit: s, x: -i.naturalWidth * s / 2, y: -i.naturalHeight * s / 2 }; apply();
    }
    hooks.useEffect(() => { const ro = new ResizeObserver(fit); ro.observe(box.current); return () => ro.disconnect(); }, []);
    function zoomAt(f, cx, cy) {
      const b = box.current.getBoundingClientRect(), c = z.current;
      const px = cx - b.left - b.width / 2, py = cy - b.top - b.height / 2;
      const s = Math.max(c.fit, Math.min(c.s * f, 8)), k = s / c.s;
      z.current = { ...c, s, x: px - (px - c.x) * k, y: py - (py - c.y) * k }; apply();
    }
    const pts = new Map();
    let last = null;
    const down = (e) => { box.current.setPointerCapture(e.pointerId); pts.set(e.pointerId, e); box.current.classList.add("drag"); };
    function move(e) {
      if (!pts.has(e.pointerId)) return;
      const prev = pts.get(e.pointerId); pts.set(e.pointerId, e);
      if (pts.size === 2) {
        const [a, b] = [...pts.values()], d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
        if (last) zoomAt(d / last, (a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
        last = d;
      } else if (z.current.s > z.current.fit) {
        z.current.x += e.clientX - prev.clientX; z.current.y += e.clientY - prev.clientY; apply();
      }
    }
    const up = (e) => { pts.delete(e.pointerId); if (pts.size < 2) last = null; if (!pts.size) box.current.classList.remove("drag"); };
    return html`<div class="zoom" ref=${box} onPointerDown=${down} onPointerMove=${move} onPointerUp=${up} onPointerCancel=${up}
      onWheel=${(e) => { e.preventDefault(); zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY); }}
      onDblClick=${(e) => (z.current.s > z.current.fit * 1.05 ? fit() : zoomAt(2.5, e.clientX, e.clientY))}
      data-zoomed=${ready ? "1" : "0"}>
      ${!ready && html`<${Spin} />`}
      <img ref=${img} src=${src} alt=${alt || ""} draggable="false" onLoad=${() => { setReady(true); fit(); }} onError=${onFail} />
    </div>`;
  }
  function ImageView({ it }) {
    const [bad, setBad] = hooks.useState(false);
    if (bad) return html`<${Failed} it=${it} error=${L("הדפדפן לא מצליח לצייר את התמונה", "The browser cannot draw this image")} />`;
    return html`<${ZoomImage} src=${contentUrl(it.id)} alt=${it.name} onFail=${() => setBad(true)} />`;
  }
  /* heic, tiff, raw, psd…: the server draws it (the same picture as the thumbnail, larger) */
  function PreviewView({ it }) {
    const [bad, setBad] = hooks.useState(false);
    if (bad) return html`<${Msg} it=${it} title=${L("אין עדיין תצוגה לקובץ הזה", "No preview for this file yet")}
      text=${L("השרת לא הכין תמונה שלו. אפשר להוריד אותו או לפתוח באפליקציה מתאימה.", "The server has no picture of it. Download it or open it with an app.")}>
      <${OpenWithButtons} it=${it} /></${Msg}>`;
    return html`<${ZoomImage} src=${thumbUrl(it, 2048)} alt=${it.name} onFail=${() => setBad(true)} />`;
  }

  /* ── video: the browser's own player (keyboard, full screen, picture-in-picture) ── */
  function VideoView({ it }) {
    const [bad, setBad] = hooks.useState(false);
    if (bad) return html`<${Msg} it=${it} icon="film" title=${L("הדפדפן לא מנגן את סוג הווידאו הזה", "This browser cannot play this video")}
      text=${L("סרטוני AVI, WMV ו־FLV צריכים המרה. אפשר להוריד את הקובץ.", "AVI, WMV and FLV need converting. You can download it.")}>
      <${OpenWithButtons} it=${it} /></${Msg}>`;
    return html`<video key=${it.id} src=${contentUrl(it.id)} poster=${T.hasThumb(it) ? thumbUrl(it, 1024) : ""} controls autoplay playsinline
      preload="metadata" onError=${() => setBad(true)}></video>`;
  }

  /* ── audio: the shared player, big ─────────────────────────────────── */
  function AudioView({ it, items }) {
    const p = F.useStore((s) => s.player);
    hooks.useEffect(() => {
      const cur = F.player.cur();
      if (!cur || cur.id !== it.id) {
        const queue = items.filter((x) => T.isMedia(x) === "audio");
        F.player.play(queue, Math.max(0, queue.findIndex((x) => x.id === it.id)));
      }
    }, [it.id]);
    const playing = p.queue[p.index] && p.queue[p.index].id === it.id;
    return html`<div class="audio-stage">
      <div class="art"><${F.player.Cover} it=${it} big /></div>
      <div class="side">
        <div class="meta"><b><bdi>${F.player.titleOf(it)}</bdi></b><span class="muted">${F.player.artistOf(it)}</span></div>
        <${F.player.Wave} it=${it} time=${playing ? p.time : 0} duration=${playing ? p.duration : 0} tall />
        <div class="times"><span class="num">${fmtDur(playing ? p.time : 0)}</span><span class="num">${fmtDur(playing ? p.duration : 0)}</span></div>
        <div class="ctl">
          <button class="icbtn" title=${L("15 שניות אחורה", "Back 15 seconds")} onClick=${() => F.player.skip(-15)}>${ic("back15")}</button>
          <button class="big" title=${p.playing && playing ? L("השהיה", "Pause") : L("ניגון", "Play")} onClick=${F.player.toggle}>${ic(p.playing && playing ? "pause" : "play", "lg")}</button>
          <button class="icbtn" title=${L("15 שניות קדימה", "Forward 15 seconds")} onClick=${() => F.player.skip(15)}>${ic("fwd15")}</button>
        </div>
      </div>
    </div>`;
  }

  /* ── pdf ───────────────────────────────────────────────────────────── */
  function PdfView({ it }) {
    const host = hooks.useRef();
    const [scale, setScale] = hooks.useState(0);
    const st = useLoad(async () => {
      const pdfjs = await esm("pdfjs-6.4.299/pdf.min.mjs");
      pdfjs.GlobalWorkerOptions.workerSrc = BASE + V + "pdfjs-6.4.299/pdf.worker.min.mjs";
      // a document of ordinary size arrives through the page's own request (the console's proxy, the
      // session); a very large one is streamed by pdf.js in ranges instead of held whole
      const src = Number(it.size) < 40 * 1024 * 1024 ? { data: new Uint8Array(await bytes(it)) } : { url: contentUrl(it.id) };
      return pdfjs.getDocument({ ...src, cMapUrl: BASE + V + "pdfjs-6.4.299/cmaps/", cMapPacked: true,
        standardFontDataUrl: BASE + V + "pdfjs-6.4.299/standard_fonts/", isEvalSupported: false }).promise;
    }, [it.id]);
    hooks.useEffect(() => {
      const doc = st.value, el = host.current;
      if (!doc || !el) return;
      let off = false;
      el.innerHTML = "";
      const width = Math.min(el.clientWidth - 24, 1000) * (scale || 1);
      const io = new IntersectionObserver((ents) => ents.forEach(async (en) => {
        if (!en.isIntersecting || en.target.dataset.done) return;
        en.target.dataset.done = "1";
        const page = await doc.getPage(Number(en.target.dataset.n));
        if (off) return;
        const base = page.getViewport({ scale: 1 }), s = width / base.width, dpr = Math.min(window.devicePixelRatio || 1, 2);
        const vp = page.getViewport({ scale: s * dpr }), c = document.createElement("canvas");
        c.width = vp.width; c.height = vp.height;
        en.target.appendChild(c);
        await page.render({ canvas: c, viewport: vp }).promise.catch(() => {});
      }), { root: el, rootMargin: "800px 0px" });
      (async () => {
        const first = await doc.getPage(1), ratio = first.getViewport({ scale: 1 });
        for (let n = 1; n <= doc.numPages && !off; n++) {
          const d = document.createElement("div");
          d.className = "page"; d.dataset.n = n;
          d.style.width = width + "px"; d.style.aspectRatio = ratio.width + " / " + ratio.height;
          el.appendChild(d); io.observe(d);
        }
      })();
      return () => { off = true; io.disconnect(); };
    }, [st.value, scale]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    return html`<div class="vstack"><div class="doc-pane" ref=${host}>${st.busy && html`<${Spin} />`}</div>
      ${st.value && html`<div class="sheet-tabs center">
        <button class="btn sm ghost" title=${L("הקטנה", "Zoom out")} onClick=${() => setScale(Math.max(0.5, (scale || 1) - 0.25))}>${ic("zoom-out", "sm")}</button>
        <span class="vcount mid">${F.count(st.value.numPages, ["עמוד אחד", "1 page"], ["עמודים", "pages"])}</span>
        <button class="btn sm ghost" title=${L("הגדלה", "Zoom in")} onClick=${() => setScale(Math.min(3, (scale || 1) + 0.25))}>${ic("zoom-in", "sm")}</button>
      </div>`}</div>`;
  }

  /* ── word (docx) ───────────────────────────────────────────────────── */
  function DocxView({ it }) {
    const host = hooks.useRef();
    const st = useLoad(async () => {
      await script("jszip-3.10.2/jszip.min.js");
      await script("docx-preview-0.4.1/docx-preview.min.js");
      return new Blob([await bytes(it)]);
    }, [it.id]);
    hooks.useEffect(() => {
      if (!st.value || !host.current) return;
      host.current.innerHTML = "";
      window.docx.renderAsync(st.value, host.current, null, { inWrapper: true, breakPages: true, experimental: true, useBase64URL: true })
        .catch((e) => (host.current.textContent = e.message));
    }, [st.value]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    return html`<div class="docx-host" ref=${host}>${st.busy && html`<${Spin} />`}</div>`;
  }

  /* ── sheets: xlsx, xls, ods, csv, tsv, numbers ──────────────────────── */
  function SheetView({ it }) {
    const [tab, setTab] = hooks.useState(0);
    const st = useLoad(async () => {
      await script("xlsx-0.20.3/xlsx.full.min.js");
      const ext = T.extOf(it.name);
      if (ext === "csv" || ext === "tsv") {
        const { s } = await text(it);
        return window.XLSX.read(s, { type: "string", FS: ext === "tsv" ? "\t" : undefined, raw: false });
      }
      return window.XLSX.read(await bytes(it), { type: "array", cellDates: true, dense: true });
    }, [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    const wb = st.value, name = wb.SheetNames[Math.min(tab, wb.SheetNames.length - 1)];
    const rows = window.XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, raw: false, defval: "", blankrows: false }).slice(0, 5000);
    const cols = Math.min(200, rows.reduce((m, r) => Math.max(m, r.length), 0));
    const colName = (i) => { let s = ""; for (i++; i; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + ((i - 1) % 26)) + s; return s; };
    return html`<div class="vstack">
      <div class="sheet-wrap"><table class="xl" dir="auto">
        <thead><tr><th></th>${Array.from({ length: cols }, (_, i) => html`<th key=${i}>${colName(i)}</th>`)}</tr></thead>
        <tbody>${rows.map((r, ri) => html`<tr key=${ri}><th>${ri + 1}</th>${Array.from({ length: cols }, (_, ci) => html`<td key=${ci} title=${r[ci]}>${r[ci]}</td>`)}</tr>`)}</tbody>
      </table></div>
      ${wb.SheetNames.length > 1 && html`<div class="sheet-tabs">${wb.SheetNames.map((n, i) =>
        html`<button key=${n} class=${"chip" + (i === tab ? " on" : "")} onClick=${() => setTab(i)}>${n}</button>`)}</div>`}
    </div>`;
  }

  /* ── text, code, data ──────────────────────────────────────────────── */
  const LANG = { js: "javascript", mjs: "javascript", jsx: "javascript", ts: "typescript", tsx: "typescript", py: "python", rb: "ruby",
    rs: "rust", kt: "kotlin", cs: "csharp", cpp: "cpp", hpp: "cpp", h: "c", c: "c", go: "go", java: "java", php: "php",
    swift: "swift", sql: "sql", sh: "bash", bat: "dos", ps1: "powershell", css: "css", json: "json", xml: "xml", html: "xml",
    htm: "xml", yaml: "yaml", yml: "yaml", toml: "ini", ini: "ini", conf: "ini", cfg: "ini", env: "bash", tex: "latex", md: "markdown", ipynb: "json" };
  function CodeView({ it }) {
    const [wrap, setWrap] = hooks.useState(false), [reveal, setReveal] = hooks.useState(false);
    const ext = T.extOf(it.name), lang = LANG[ext];
    const st = useLoad(async () => {
      const t = await text(it);
      if (ext === "json" || ext === "ipynb") { try { t.s = JSON.stringify(JSON.parse(t.s), null, 2); } catch (e) { /* as it is */ } }
      if (lang && t.s.length < 600000) { try { await script("hljs-11.12.0/highlight.min.js"); } catch (e) { /* plain */ } }
      return t;
    }, [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    let src = st.value.s;
    if (ext === "env" && !reveal) src = src.replace(/^(\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*)(.+)$/gm, (m, k, v) => k + "•".repeat(Math.min(12, v.length)));
    let body;
    if (window.hljs && lang && window.hljs.getLanguage(lang) && src.length < 600000) {
      body = window.hljs.highlight(src, { language: lang, ignoreIllegals: true }).value;
    } else body = src.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
    const lines = body.split("\n").map((l) => '<span class="ln">' + (l || " ") + "</span>").join("");
    return html`<div class="vstack">
      <div class="sheet-tabs">
        <button class=${"chip" + (wrap ? " on" : "")} onClick=${() => setWrap(!wrap)}>${ic("wrap", "sm")}${L("גלישת שורות", "Wrap lines")}</button>
        ${ext === "env" && html`<button class=${"chip" + (reveal ? " on" : "")} onClick=${() => setReveal(!reveal)}>${ic("eye", "sm")}${L("הצגת ערכים", "Show values")}</button>`}
        ${st.value.cut && html`<span class="vcount">${L("מוצגים 2 MB ראשונים", "Showing the first 2 MB")}</span>`}
      </div>
      <pre class=${"code" + (wrap ? " wrap" : "")} dangerouslySetInnerHTML=${{ __html: lines }}></pre>
    </div>`;
  }
  function TextView({ it }) {
    const st = useLoad(() => text(it), [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    return html`<div class="doc-pane"><div class="textdoc pre" dir="auto">${st.value.s}</div></div>`;
  }
  function MdView({ it }) {
    const [src, setSrc] = hooks.useState(false);
    const st = useLoad(async () => {
      const t = await text(it);
      await script("marked-18.1.2/marked.umd.js"); await script("dompurify-3.4.17/purify.min.js");
      return { ...t, html: window.DOMPurify.sanitize(window.marked.parse(t.s)) };
    }, [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    return html`<div class="vstack">
      <div class="sheet-tabs"><button class=${"chip" + (src ? " on" : "")} onClick=${() => setSrc(!src)}>${ic("code", "sm")}${L("מקור", "Source")}</button></div>
      <div class="doc-pane">${src ? html`<div class="textdoc pre" dir="auto">${st.value.s}</div>`
        : html`<div class="textdoc md" dir="auto" dangerouslySetInnerHTML=${{ __html: st.value.html }}></div>`}</div>
    </div>`;
  }
  /* a web page: drawn in a frame that may run nothing and reach nothing */
  function HtmlView({ it }) {
    const [src, setSrc] = hooks.useState(false);
    const st = useLoad(() => text(it), [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    return html`<div class="vstack">
      <div class="sheet-tabs"><button class=${"chip" + (src ? " on" : "")} onClick=${() => setSrc(!src)}>${ic("code", "sm")}${L("קוד המקור", "Source")}</button>
        <span class="vcount">${L("מוצג בלי סקריפטים", "Shown without scripts")}</span></div>
      ${src ? html`<${CodeView} it=${it} />` : html`<iframe class="html-frame" sandbox="" referrerpolicy="no-referrer" srcdoc=${st.value.s} title=${it.name}></iframe>`}
    </div>`;
  }

  /* ── zip: what is inside, and any single entry to take out ─────────── */
  function ZipView({ it }) {
    const st = useLoad(async () => {
      await script("fflate-0.8.3/fflate.umd.js");
      const buf = new Uint8Array(await bytes(it));
      const out = [];
      await new Promise((res, rej) => {
        const uz = new window.fflate.Unzip((f) => { out.push({ name: f.name, size: f.originalSize, f }); });
        uz.register(window.fflate.UnzipInflate);
        try { uz.push(buf, true); res(); } catch (e) { rej(e); }
      });
      return { entries: out, buf };
    }, [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    const take = (name) => {
      const u = window.fflate.unzipSync(st.value.buf, { filter: (f) => f.name === name });
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([u[name]])); a.download = name.split("/").pop(); a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    };
    const files = st.value.entries.filter((e) => !e.name.endsWith("/"));
    return html`<div class="doc-pane"><div class="zipl"><div class="list">
      ${files.map((e) => html`<div class="lr zip" key=${e.name}>
        <div class="th">${ic(T.icon({ name: e.name }), "sm")}</div>
        <div class="name"><div class="fname"><${F.Name} name=${e.name} /></div></div>
        <div class="c-size num">${e.size != null ? fmtSize(e.size) : ""}</div>
        <button class="rowact show" title=${L("הוצאה והורדה", "Extract and download")} onClick=${() => take(e.name)}>${ic("download", "sm")}</button>
      </div>`)}
      ${!files.length && html`<div class="empty"><b>${L("הארכיון ריק", "The archive is empty")}</b></div>`}
    </div></div></div>`;
  }

  /* ── 3D models ─────────────────────────────────────────────────────── */
  function ModelView({ it }) {
    const host = hooks.useRef();
    const st = useLoad(async () => { await script("o3dv-0.18.0/o3dv.min.js"); return new File([await bytes(it)], it.name); }, [it.id]);
    hooks.useEffect(() => {
      if (!st.value || !host.current) return;
      const css = getComputedStyle(host.current), rgb = (v) => { const m = (css.getPropertyValue(v).trim().match(/[0-9a-f]{2}/gi) || ["cc", "cc", "cc"]).map((x) => parseInt(x, 16)); return m; };
      const [r, g, b] = rgb("--surface-2"), [r2, g2, b2] = rgb("--olive");
      const OV = window.OV;
      const viewer = new OV.EmbeddedViewer(host.current, { backgroundColor: new OV.RGBAColor(r, g, b, 255),
        defaultColor: new OV.RGBColor(r2, g2, b2) });
      viewer.LoadModelFromFileList([st.value]);
      return () => { try { viewer.Destroy(); } catch (e) { /* gone */ } };
    }, [st.value]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    return html`<div class="o3d" ref=${host}>${st.busy && html`<${Spin} />`}</div>`;
  }

  /* ── e-book ────────────────────────────────────────────────────────── */
  function EpubView({ it }) {
    const host = hooks.useRef(), book = hooks.useRef();
    const st = useLoad(async () => { await script("jszip-3.10.2/jszip.min.js"); await script("epubjs-0.3.93/epub.min.js"); return bytes(it); }, [it.id]);
    hooks.useEffect(() => {
      if (!st.value || !host.current) return;
      const b = window.ePub(st.value), r = b.renderTo(host.current, { width: "100%", height: "100%", spread: "auto" });
      r.display(); book.current = r;
      return () => { try { b.destroy(); } catch (e) { /* gone */ } };
    }, [st.value]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    return html`<div class="vstack">
      <div class="epub-host" ref=${host}>${st.busy && html`<${Spin} />`}</div>
      <div class="sheet-tabs center">
        <button class="btn sm" onClick=${() => book.current && book.current.prev()}>${ic("chevron", "sm")}${L("הקודם", "Previous")}</button>
        <button class="btn sm" onClick=${() => book.current && book.current.next()}>${L("הבא", "Next")}${ic("chevron", "sm flip")}</button>
      </div>
    </div>`;
  }

  /* ── fonts ─────────────────────────────────────────────────────────── */
  function FontView({ it }) {
    const fam = "f" + it.id.replace(/[^a-z0-9]/gi, "");
    const st = useLoad(async () => { const f = new FontFace(fam, await bytes(it)); await f.load(); document.fonts.add(f); return true; }, [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    return html`<div class="doc-pane"><div class="fontprev textdoc" style=${"font-family:" + fam}>
      <div class="big">אבג דהו זחט · Aa Bb Cc</div>
      <div class="l2">הלשכה הדיגיטלית — The quick brown fox jumps over the lazy dog</div>
      <div class="l3">0123456789 · ! ? ₪ $ % & ( ) [ ] { }</div>
      <div class="l4">${"אבגדהוזחטיכלמנסעפצקרשת ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz"}</div>
    </div></div>`;
  }

  /* ── contact, event, email, torrent: small parsers, shown as cards ─── */
  const unfold = (s) => s.replace(/\r?\n[ \t]/g, "");
  function props(s) {
    return unfold(s).split(/\r?\n/).map((l) => { const i = l.indexOf(":"); if (i < 0) return null;
      const [k, ...ps] = l.slice(0, i).split(";"); return { k: k.toUpperCase(), p: ps.join(";"), v: l.slice(i + 1).replace(/\\n/g, "\n").replace(/\\,/g, ",") }; }).filter(Boolean);
  }
  function VcfView({ it }) {
    const st = useLoad(() => text(it), [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    const cards = st.value.s.split(/BEGIN:VCARD/i).slice(1).map((c) => props(c));
    return html`<div class="doc-pane">${cards.map((c, i) => {
      const g = (k) => c.filter((x) => x.k === k).map((x) => x.v);
      return html`<div class="cardview" key=${i}>
        <div class="det-h"><span class="th">${ic("user", "sm")}</span><b>${g("FN")[0] || g("N")[0] || L("איש קשר", "Contact")}</b></div>
        <dl class="facts">
          ${g("ORG").map((v) => html`<dt>${L("ארגון", "Organization")}</dt><dd>${v.replace(/;/g, " ")}</dd>`)}
          ${g("TEL").map((v) => html`<dt>${L("טלפון", "Phone")}</dt><dd class="num"><a href=${"tel:" + v}>${v}</a></dd>`)}
          ${g("EMAIL").map((v) => html`<dt>${L("אימייל", "Email")}</dt><dd><a href=${"mailto:" + v}>${v}</a></dd>`)}
          ${g("ADR").map((v) => html`<dt>${L("כתובת", "Address")}</dt><dd>${v.split(";").filter(Boolean).join(", ")}</dd>`)}
          ${g("NOTE").map((v) => html`<dt>${L("הערה", "Note")}</dt><dd>${v}</dd>`)}
        </dl></div>`;
    })}</div>`;
  }
  function IcsView({ it }) {
    const st = useLoad(() => text(it), [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    const when = (v) => { const m = /^(\d{4})(\d\d)(\d\d)(T(\d\d)(\d\d))?/.exec(v || ""); if (!m) return v || "";
      const d = new Date(Date.UTC(+m[1], m[2] - 1, +m[3], +(m[5] || 0), +(m[6] || 0)));
      return d.toLocaleString(L("he-IL", "en-US"), m[4] ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }); };
    const evs = st.value.s.split(/BEGIN:VEVENT/i).slice(1).map((c) => props(c.split(/END:VEVENT/i)[0]));
    return html`<div class="doc-pane">${evs.map((e, i) => {
      const g = (k) => (e.find((x) => x.k === k) || {}).v || "";
      return html`<div class="cardview" key=${i}>
        <div class="det-h"><span class="th">${ic("calendar", "sm")}</span><b>${g("SUMMARY") || L("אירוע", "Event")}</b></div>
        <dl class="facts"><dt>${L("מתי", "When")}</dt><dd>${when(g("DTSTART"))}${g("DTEND") && " — " + when(g("DTEND"))}</dd>
          ${g("LOCATION") && html`<dt>${L("איפה", "Where")}</dt><dd>${g("LOCATION")}</dd>`}
          ${g("DESCRIPTION") && html`<dt>${L("תיאור", "Description")}</dt><dd class="pre">${g("DESCRIPTION")}</dd>`}</dl></div>`;
    })}</div>`;
  }
  function EmlView({ it }) {
    const st = useLoad(async () => {
      const { s } = await text(it);
      const cut = s.search(/\r?\n\r?\n/), head = props(s.slice(0, cut)), body = s.slice(cut).trim();
      await script("dompurify-3.4.17/purify.min.js");
      const plain = /content-type:\s*text\/html/i.test(s.slice(0, cut)) ? window.DOMPurify.sanitize(body) : null;
      return { head, body, plain };
    }, [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    const g = (k) => (st.value.head.find((x) => x.k === k) || {}).v || "";
    return html`<div class="doc-pane"><div class="cardview wide">
      <div class="det-h"><span class="th">${ic("mail", "sm")}</span><b>${g("SUBJECT") || L("ללא נושא", "No subject")}</b></div>
      <dl class="facts"><dt>${L("מאת", "From")}</dt><dd>${g("FROM")}</dd><dt>${L("אל", "To")}</dt><dd>${g("TO")}</dd><dt>${L("תאריך", "Date")}</dt><dd>${g("DATE")}</dd></dl>
      ${st.value.plain != null ? html`<iframe class="html-frame mailframe" sandbox="" srcdoc=${st.value.plain}></iframe>`
        : html`<div dir="auto" class="pre">${st.value.body.slice(0, 20000)}</div>`}
    </div></div>`;
  }
  function TorrentView({ it }) {
    const st = useLoad(async () => {
      const b = new Uint8Array(await bytes(it)); let i = 0; const td = new TextDecoder();
      function dec() {
        const c = b[i];
        if (c === 100) { i++; const o = {}; while (b[i] !== 101) { const k = td.decode(dec()); o[k] = dec(); } i++; return o; }
        if (c === 108) { i++; const a = []; while (b[i] !== 101) a.push(dec()); i++; return a; }
        if (c === 105) { const e = b.indexOf(101, i); const n = Number(td.decode(b.slice(i + 1, e))); i = e + 1; return n; }
        const col = b.indexOf(58, i), len = Number(td.decode(b.slice(i, col))); i = col + 1 + len; return b.slice(col + 1, i);
      }
      return dec();
    }, [it.id]);
    if (st.error) return html`<${Failed} it=${it} error=${st.error} />`;
    if (st.busy) return html`<${Spin} />`;
    const td = new TextDecoder(), info = st.value.info || {}, files = info.files || [{ path: [info.name], length: info.length }];
    return html`<div class="doc-pane"><div class="cardview">
      <div class="det-h"><span class="th">${ic("magnet", "sm")}</span><b><bdi>${info.name ? td.decode(info.name) : it.name}</bdi></b></div>
      <dl class="facts"><dt>${L("קבצים", "Files")}</dt><dd class="num">${files.length}</dd>
        <dt>${L("גודל", "Size")}</dt><dd class="num">${fmtSize(files.reduce((s, f) => s + (f.length || 0), 0))}</dd>
        ${st.value.announce && html`<dt>Tracker</dt><dd class="mono">${td.decode(st.value.announce)}</dd>`}</dl>
      <div class="list">${files.slice(0, 500).map((f, k) => html`<div class="lr tor" key=${k}>
        <div class="name"><div class="fname"><${F.Name} name=${(f.path || []).map((p) => td.decode(p)).join("/")} /></div></div><div class="c-size num">${fmtSize(f.length)}</div></div>`)}</div>
    </div></div>`;
  }

  /* ── what opens nothing here: the apps that do, and the download ───── */
  function OpenWithButtons({ it }) {
    const apps = F.ui.openWithFor(it);
    return html`${apps.map((x) => html`<button class="btn primary" key=${x.app} onClick=${() => F.ui.launch(x, it)}>${ic("external", "sm")}${L("פתיחה ב", "Open in ")}${x.spec.label || x.app}</button>`)}
      <button class="btn" onClick=${() => F.data.download(it)}>${ic("download", "sm")}${L("הורדה", "Download")}</button>`;
  }
  const NOVIEW = {
    office: L("מסמך Word ישן, RTF, ODT או Pages", "An older Word, RTF, ODT or Pages document"),
    slides: L("מצגת", "A presentation"), disk: L("ארכיון", "An archive"), cad: L("שרטוט CAD", "A CAD drawing"),
    db: L("מסד נתונים", "A database"), program: L("תוכנה — קבצים כאלה לעולם לא מורצים כאן", "A program — files like this never run here"),
  };
  function NoView({ it }) {
    const k = T.kindOf(it);
    return html`<${Msg} it=${it} title=${it.name} text=${(NOVIEW[k] || T.label(it)) + " · " + fmtSize(it.size) + " · " +
      (F.ui.openWithFor(it).length ? L("אפשר לפתוח אותו באפליקציה:", "Open it with an app:") : L("אין לו עדיין תצוגה מובנית — אפשר להוריד אותו.", "There is no built-in view for it yet — download it."))}>
      <${OpenWithButtons} it=${it} /></${Msg}>`;
  }

  const VIEWERS = { image: ImageView, preview: PreviewView, video: VideoView, audio: AudioView, pdf: PdfView, docx: DocxView,
    sheet: SheetView, code: CodeView, text: TextView, md: MdView, html: HtmlView, zip: ZipView, model: ModelView, epub: EpubView,
    font: FontView, vcf: VcfView, ics: IcsView, eml: EmlView, torrent: TorrentView };

  /* ── the frame ─────────────────────────────────────────────────────── */
  function open(items, index) {
    const files = items.filter((x) => x.kind !== "folder");
    const it = items[index];
    const i = Math.max(0, files.findIndex((x) => x.id === (it && it.id)));
    set({ viewer: { items: files, index: i }, menu: null });
    const r = state.route;
    if (r.view === "folder" && files[i]) F.setUrl({ ...r, file: files[i].id }, true);
  }
  function close() {
    const r = state.route;
    set({ viewer: null });
    if (r.view === "folder") F.setUrl({ ...r, file: undefined }, true);
    if (r.view === "open") F.go({ view: "home" }, { replace: true });
  }
  function step(d) {
    const v = state.viewer; if (!v) return;
    const i = v.index + d;
    if (i < 0 || i >= v.items.length) return;
    set({ viewer: { ...v, index: i } });
    const r = state.route;
    if (r.view === "folder") F.setUrl({ ...r, file: v.items[i].id }, true);
  }
  function Viewer() {
    const v = F.useStore((s) => s.viewer);
    const touch = F.useStore((s) => s.size.touch);
    const tiny = F.useStore((s) => !!s.size.tiny);
    const sw = hooks.useRef(null);
    /* in a widget window a photo's or a video's bar lies on the picture and steps aside while nothing
       moves; a move or a touch brings it back, a hand on the bar keeps it */
    const [idle, setIdle] = hooks.useState(false);
    const idleT = hooks.useRef(0);
    const wake = (e) => {
      clearTimeout(idleT.current);
      setIdle(false);
      if (e && e.target && e.target.closest && e.target.closest(".vw-top,.vw-nav")) return;
      idleT.current = setTimeout(() => setIdle(true), 2600);
    };
    hooks.useEffect(() => { if (v) wake(); return () => clearTimeout(idleT.current); }, [v && v.index, !!v]);
    hooks.useEffect(() => {
      if (!v) return;
      const rtl = document.dir === "rtl";
      const key = (e) => {
        if (e.target.closest && e.target.closest("input,textarea,[contenteditable]")) return;
        if (e.key === "Escape" && !document.querySelector(".bask")) { e.preventDefault(); close(); }
        if (e.key === "ArrowLeft") step(rtl ? 1 : -1);
        if (e.key === "ArrowRight") step(rtl ? -1 : 1);
      };
      addEventListener("keydown", key);
      return () => removeEventListener("keydown", key);
    }, [!!v]);
    if (!v) return null;
    const it = v.items[v.index];
    if (!it) return null;
    const kind = T.kindOf(it), Comp = VIEWERS[T.viewerOf(it)] || NoView, dark = kind === "image" || kind === "raster" || kind === "video";
    const rtl = document.dir === "rtl";
    const startSwipe = (e) => { if (e.pointerType === "touch") sw.current = { x: e.clientX, y: e.clientY, t: Date.now() }; };
    const endSwipe = (e) => {
      const s = sw.current; sw.current = null;
      if (!s || document.querySelector('.zoom[data-zoomed="1"] img[style*="scale(1."]')) return;
      const dx = e.clientX - s.x, dy = e.clientY - s.y;
      if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5 && Date.now() - s.t < 600) step((dx > 0) === rtl ? 1 : -1);
    };
    return html`<div class=${"vw" + (dark ? " dark" : "")} role="dialog" aria-modal="true" aria-label=${it.name}
      data-idle=${tiny && dark && idle ? "" : null} onPointerMove=${tiny ? wake : null} onPointerDown=${tiny ? wake : null}>
      <div class="vw-top">
        <button class="icbtn" title=${L("סגירה (Esc)", "Close (Esc)")} onClick=${close}>${ic("x")}</button>
        <div class="vw-title"><b title=${it.name}><${F.Name} name=${it.name} /></b>
          <span>${[T.label(it), fmtSize(it.size), v.items.length > 1 ? L(`${v.index + 1} מתוך ${v.items.length}`, `${v.index + 1} of ${v.items.length}`) : ""].filter(Boolean).join(" · ")}</span></div>
        ${F.ui.openWithFor(it).slice(0, 1).map((x) => html`<button class="btn sm hide-n hide-t" key=${x.app} onClick=${() => F.ui.launch(x, it)}>${ic("external", "sm")}${x.spec.label || x.app}</button>`)}
        <button class="icbtn hide-t" title=${L("הורדה", "Download")} onClick=${() => F.data.download(it)}>${ic("download")}</button>
        <button class="icbtn hide-n hide-t" title=${L("העתקת קישור לשיתוף", "Copy share link")} onClick=${() => F.data.copyLink(it)}>${ic("link")}</button>
        <button class="icbtn" title=${L("עוד", "More")} onClick=${(e) => F.ui.openMenu(F.ui.actionsFor([it], "viewer"), e)}>${ic("more")}</button>
      </div>
      <div class="vw-stage" onPointerDown=${startSwipe} onPointerUp=${endSwipe}>
        ${v.index > 0 && !touch && html`<button class="vw-nav prev" title=${L("הקודם", "Previous")} onClick=${() => step(-1)}>${ic("chevron", rtl ? "" : "flip")}</button>`}
        <div class="vw-pane center" key=${it.id}><${Comp} it=${it} items=${v.items} /></div>
        ${v.index < v.items.length - 1 && !touch && html`<button class="vw-nav next" title=${L("הבא", "Next")} onClick=${() => step(1)}>${ic("chevron", rtl ? "flip" : "")}</button>`}
      </div>
    </div>`;
  }

  F.viewer = { open, close, step, Viewer, VIEWERS };
})();
