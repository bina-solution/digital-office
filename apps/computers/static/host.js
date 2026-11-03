/* host.js — ONE computer of the herd: its resources, its network, its storage, its SSH access.
 *
 * The owner, 2026-10-21 (DGO-890): "machine app and computers app should merge so every dgo shows his
 * computer in computers and you can see open there the resource view exact or better from what we have
 * now in machine app and network view (inbound and outbound) … all accessible from the vps".
 *
 * WHAT IS HERE. The resource view is machine's own screen, moved: the five tiles, the chart, the details,
 * the services grid, the storage and the cleanup — the same numbers, the same colours, the same words.
 * It is fed by `api/hosts/<where>/machine/api/overview`, which is THIS computer's machine service or, for
 * a linked office's computer, that office's machine through the door (apps/computers/herd.py). Where a
 * computer runs the security app and not machine (the Mac does), the same view is drawn from security's
 * own reading of the machine (`api/host/overview`, machine's shape) and the details say which one spoke.
 * The network view is that computer's security service: who came in, where it went out, its router.
 *
 * Every URL is RELATIVE (the console embeds this app at /a/computers/). `api`, `esc`, `$`, `S`, the
 * dialogs and `binaAsk`/`binaTell` are app.js's; this file adds the page and nothing global but `Host`.
 */
"use strict";

const Host = (() => {
  const T = { where: "", tab: "res", grid: null, gridFor: "", timer: 0, gen: 0, chart: null, clean: null,
              win: "24h", detail: null, dgen: 0, gIn: null, gOut: null };

  // ── words and numbers (machine's own) ────────────────────────────────────────────────────────────
  const fmtBytes = (n) => {
    if (!Number.isFinite(n) || n <= 0) return "0 B";
    const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${v >= 10 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${u[i]}`;
  };
  const fmtRate = (n) => fmtBytes(n) + "/s";
  const pctTxt = (n) => (Number.isFinite(n) ? `${n.toFixed(n >= 10 ? 0 : 1)}%` : "—");
  const N = (v) => `<span class="num">${esc(String(v))}</span>`;
  const ago = (s) => (s < 90 ? `לפני ${Math.round(s)} שנ׳` : s < 5400 ? `לפני ${Math.round(s / 60)} דק׳` : `לפני ${Math.round(s / 3600)} שע׳`);
  const tone = (v) => (v >= 90 ? "red" : v >= 75 ? "yellow" : "green");
  const STATUS_HE = { running: "פועל", exited: "הסתיים", created: "נוצר", restarting: "מופעל מחדש", paused: "מושהה", dead: "מת", removing: "מוסר" };
  const HEALTH_HE = { healthy: "תקין", unhealthy: "לא תקין", starting: "מתחיל" };
  const RISK_HE = { low: "נמוך", medium: "בינוני", high: "גבוה" };
  const CLEAN_HE = {
    docker_container_prune: ["ניקוי מכולות שנעצרו", "מסיר מכולות שכבר נעצרו. שירותים שרצים לא נפגעים."],
    docker_image_prune_dangling: ["ניקוי שכבות תמונה יתומות", "מסיר שכבות תמונה בלי תג, שנשארו מבניות חוזרות."],
    docker_builder_prune_all: ["ניקוי מטמון הבנייה", "מסיר את מטמון הבנייה. הבניות הבאות עשויות להימשך יותר."],
    docker_image_prune_all: ["ניקוי תמונות שאינן בשימוש", "מסיר תמונות שאף מכולה לא משתמשת בהן. אפשר למשוך או לבנות אותן שוב."],
  };
  const cleanHe = (o) => CLEAN_HE[o.id] || [o.title || o.id, o.description || ""];
  const KIND_HE = { "public": "ציבורי", "private": "פרטי", remote: "לשכה מקושרת", auth: "כניסה", door: "דלת", none: "ללא נתב",
                    link: "קישור בין לשכות" };
  // a chart names no colour of its own: the palette's line steps, read where they are written
  const tok = (n) => getComputedStyle(document.documentElement).getPropertyValue("--" + n).trim();
  const colors = () => ({ cpu: tok("sky-d"), mem: tok("olive-d"), disk: tok("plum-d"), net: tok("lime-d") });
  const el = (id) => document.getElementById(id);
  const hd = (where) => (S.hd[where] = S.hd[where] || {});

  // ── reads ────────────────────────────────────────────────────────────────────────────────────────
  const read = (where, svc, path, q) => api("api/hosts/" + encodeURIComponent(where) + "/" + svc + "/" + path + (q ? "?" + q : ""));

  /** The resource view's figures: machine's own, or — where machine does not answer — security's reading
   *  of the same machine. Kept in S.hd[where] so the fleet list and this page draw one answer. */
  async function overview(where, brief) {
    const h = hd(where);
    let r = await read(where, "machine", "api/overview", brief ? "brief=1" : "");
    let src = "machine";
    if (!r.ok && r.status !== 401 && r.status !== 403) {
      const s = await read(where, "security", "api/host/overview", brief ? "brief=1" : "");
      if (s.ok) { r = s; src = "security"; }
    }
    if (r.ok && r.d && r.d.cpu) {
      Object.assign(h, { ov: r.d, src, at: Date.now(), err: "" });
      if (!brief) h.full = true;
    } else {
      Object.assign(h, { err: (r.d && r.d.error) || binaSaid(r.status), at: h.at || 0 });
    }
    return h;
  }
  async function summary(where) {
    const h = hd(where);
    const r = await read(where, "security", "api/summary", "hours=24");
    if (r.ok && r.d && r.d.kpi) Object.assign(h, { sum: r.d, sumErr: "", sumStatus: 200, sumAt: Date.now() });
    else Object.assign(h, { sum: null, sumErr: (r.d && r.d.error) || binaSaid(r.status), sumStatus: r.status });
    return h;
  }

  // ── the page ─────────────────────────────────────────────────────────────────────────────────────
  /** `opt` is the network tab's half of the path: its window (`1h|24h|7d`) and the address opened over it. */
  function open(where, tab, opt) {
    const o = opt || {};
    const same = T.where === where;
    T.where = where;
    T.tab = tab || "res";
    T.win = WIN[o.win] ? o.win : "24h";
    T.gen++;
    clearInterval(T.timer);
    const body = el("hBody");
    if (!same || !body || body.dataset.tab !== T.tab || (T.tab === "net" && body.dataset.win !== T.win)) {
      el("vHost").innerHTML = `<div id="hNotice"></div><div id="hBody" data-tab="${esc(T.tab)}" data-win="${esc(T.win)}">${skeleton(T.tab)}</div>`;
      T.grid = null;
      T.gridFor = "";
      dropGrids();
      if (T.tab === "res") wireChart();
    }
    const was = T.detail, d = T.tab === "net" && o.detail ? o.detail : null;
    T.detail = d;
    const shown = was && d && same && was.dir === d.dir && was.ip === d.ip && el("netModal") && !el("netModal").classList.contains("hidden");
    if (d && !shown) openDetail(where, d);
    else if (!d && was) closeDetail();
    tick();
    // the resource figures move every five seconds (machine samples every ten); the rest every half minute
    T.timer = setInterval(() => { if (!document.hidden) tick(); }, T.tab === "res" ? 5000 : 30000);
  }
  function close() { clearInterval(T.timer); T.timer = 0; T.where = ""; T.gen++; if (T.detail) { T.detail = null; closeDetail(); } }

  function skeleton(tab) {
    if (tab === "net") return netSkeleton();
    if (tab === "disk") return diskSkeleton();
    if (tab === "ssh") return '<div id="hSsh"></div>';
    return resSkeleton();
  }

  async function tick() {
    const where = T.where, gen = T.gen;
    if (!where) return;
    if (T.tab === "net") {
      const got = await loadNet(where, T.win);
      if (gen === T.gen) paintNet(where, Object.assign(hd(where), got));
    } else if (T.tab === "disk") {
      const h = await overview(where, false);
      if (where === "local" && h.src === "machine" && !T.clean) {
        const r = await read("local", "machine", "api/cleanup/options");
        T.clean = r.ok && r.d ? (r.d.options || []) : [];
      }
      if (gen === T.gen) paintDisk(where, h);
    } else if (T.tab === "ssh") {
      if (gen === T.gen) paintSsh(where);
    } else {
      const h = await overview(where, false);
      if (gen === T.gen) paintRes(where, h);
    }
    if (gen === T.gen && typeof onHostPainted === "function") onHostPainted(where);
  }

  function notice(html) { const n = el("hNotice"); if (n) n.innerHTML = html || ""; }
  function noResources(h) {
    return alertBox("warn", "<b>המשאבים של המחשב הזה לא נקראו.</b> " + esc(h.err || "אין תשובה") +
      '<div class="small">את המשאבים מספר שירות המכונה של המחשב עצמו, ואם הוא אינו פועל שם — אפליקציית האבטחה שלו. ' +
      "מחשב של לשכה מקושרת נקרא דרך הקישור, ולכן גם קישור שנפל נראה כך.</div>");
  }

  // ── resources (machine's screen) ─────────────────────────────────────────────────────────────────
  function resSkeleton() {
    const tile = (k, id, chip, below, extra = "") => `<div class="tile pg-kpi"><div class="thead"><div><div class="pg-kpi-k">${k}</div>` +
      `<div class="pg-kpi-v skel" id="${id}">00%</div></div><span class="chip" id="${id}Chip">${chip}</span>${extra}</div>${below}</div>`;
    return `<div class="tiles">
      ${tile("מעבד", "hCpu", "עומס —", '<canvas class="spark" id="hSparkCpu"></canvas>')}
      ${tile("זיכרון", "hMem", "—", '<canvas class="spark" id="hSparkMem"></canvas>', '<span class="chip" id="hHostMem" hidden></span>')}
      ${tile("אחסון", "hDisk", "—", '<div class="mbar"><div class="mfill" id="hDiskFill"></div></div>')}
      ${tile("רשת · הורדה", "hNet", "—", '<canvas class="spark" id="hSparkNet"></canvas>')}
      ${tile("מכולות", "hCont", "—", '<div class="mbar"><div class="mfill" id="hContFill"></div></div>')}
    </div>
    <div class="cols cols-7-5">
      <div class="card"><h3>גרף משאבים <span class="legend" id="hLegend"></span></h3>
        <div class="chart-wrap"><canvas class="rchart" id="hChart"></canvas><div class="chart-tip" id="hTip"></div></div></div>
      <div class="card"><h3>פרטי המחשב</h3><div class="kv" id="hInfo"></div></div>
    </div>
    <div class="card"><h3><span>שירותים פעילים</span><span class="small muted" id="hSvcHint"></span></h3><div id="hSvc"></div></div>`;
  }

  function setFill(id, value, state) {
    const n = el(id); if (!n) return;
    const v = Math.max(0, Math.min(100, Number(value) || 0));
    n.style.width = `${v}%`; n.className = "mfill " + (state || tone(v));
  }
  function fitCanvas(cv, cssH) {
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth || cv.parentElement.clientWidth;
    cv.width = Math.round(w * dpr); cv.height = Math.round(cssH * dpr);
    const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h: cssH };
  }
  function drawSpark(id, series, color, max) {
    const cv = el(id); if (!cv) return;
    const { ctx, w, h } = fitCanvas(cv, 34);
    ctx.clearRect(0, 0, w, h);
    if (series.length < 2) return;
    const mx = max || Math.max(1, ...series), last = series.length - 1;
    const X = (i) => 2 + i * (w - 4) / last, Y = (v) => h - 2 - (Math.max(0, Math.min(mx, v)) / mx) * (h - 5);
    ctx.beginPath(); series.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
    ctx.lineTo(X(last), h); ctx.lineTo(X(0), h); ctx.closePath(); ctx.fillStyle = color + "22"; ctx.fill();
    ctx.beginPath(); series.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.lineJoin = "round"; ctx.stroke();
    ctx.beginPath(); ctx.arc(X(last), Y(series[last]), 2.2, 0, 7); ctx.fillStyle = color; ctx.fill();
  }
  function drawChart(history) {
    const cv = el("hChart"); if (!cv) return;
    const C = colors(), { ctx, w, h } = fitCanvas(cv, 230), padB = 18, padT = 8;
    ctx.clearRect(0, 0, w, h); ctx.direction = "ltr";
    ctx.strokeStyle = tok("line"); ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) { const y = padT + (h - padB - padT) * i / 4; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
    ctx.fillStyle = tok("muted"); ctx.font = "10px system-ui"; ctx.textAlign = "left";
    [100, 75, 50, 25, 0].forEach((p, i) => { const y = padT + (h - padB - padT) * i / 4; ctx.fillText(p + "%", 3, y + (i === 0 ? 9 : -2)); });
    const n = history.length;
    if (n < 2) { ctx.textAlign = "center"; ctx.font = "12px system-ui"; ctx.fillText("אוסף נתונים…", w / 2, h / 2); T.chart = null; return; }
    const netMax = Math.max(1, ...history.map((r) => Math.max(r.rx || 0, r.tx || 0)));
    const Y = (v) => padT + (1 - Math.max(0, Math.min(100, v)) / 100) * (h - padB - padT);
    const px = (i) => 2 + i * (w - 4) / (n - 1);
    for (const [key, color] of [["cpu", C.cpu], ["mem", C.mem], ["disk", C.disk]]) {
      ctx.beginPath(); history.forEach((r, i) => (i ? ctx.lineTo(px(i), Y(r[key] || 0)) : ctx.moveTo(px(i), Y(r[key] || 0))));
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.stroke();
      if (key === "cpu") { ctx.lineTo(px(n - 1), h - padB); ctx.lineTo(px(0), h - padB); ctx.closePath(); ctx.fillStyle = color + "14"; ctx.fill(); }
    }
    ctx.setLineDash([4, 3]); ctx.beginPath();
    history.forEach((r, i) => { const y = Y((Math.max(r.rx || 0, r.tx || 0) / netMax) * 100); i ? ctx.lineTo(px(i), y) : ctx.moveTo(px(i), y); });
    ctx.strokeStyle = C.net; ctx.lineWidth = 1.5; ctx.stroke(); ctx.setLineDash([]);
    const hm = (r) => new Date(r.t * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
    ctx.fillStyle = tok("muted"); ctx.font = "10px system-ui";
    ctx.textAlign = "left"; ctx.fillText(hm(history[0]), 3, h - 4);
    ctx.textAlign = "right"; ctx.fillText(hm(history[n - 1]), w - 3, h - 4);
    T.chart = { px, n, history, h };
  }
  function wireChart() {
    const cv = el("hChart"); if (!cv) return;
    cv.addEventListener("mousemove", (ev) => {
      const tip = el("hTip");
      if (!T.chart) { tip.style.opacity = 0; return; }
      const x = ev.clientX - cv.getBoundingClientRect().left, { px, n, history } = T.chart;
      let best = 0, bd = 1e9;
      for (let i = 0; i < n; i++) { const d = Math.abs(px(i) - x); if (d < bd) { bd = d; best = i; } }
      const r = history[best];
      const t = new Date(r.t * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      tip.innerHTML = `<b>${t}</b><span class="r">מעבד ${N(pctTxt(r.cpu))} · זיכרון ${N(pctTxt(r.mem))}</span>` +
        `<span class="r">אחסון ${N(pctTxt(r.disk))}</span><span class="r">הורדה ${N(fmtRate(r.rx))} · העלאה ${N(fmtRate(r.tx))}</span>`;
      tip.style.left = px(best) + "px"; tip.style.top = (T.chart.h * 0.28) + "px"; tip.style.opacity = 1;
    });
    cv.addEventListener("mouseleave", () => { el("hTip").style.opacity = 0; });
  }

  function paintRes(where, h) {
    const d = h.ov;
    if (!d) { notice(noResources(h)); return; }
    notice(h.err ? alertBox("warn", "<b>הקריאה האחרונה נכשלה</b> — " + esc(h.err) + ". מוצגים המספרים מלפני " + esc(ago((Date.now() - h.at) / 1000)) + ".") : "");
    document.querySelectorAll("#hBody .skel").forEach((n) => n.classList.remove("skel"));
    const C = colors(), hist = d.history || [], nr = d.net_rate || { rx: 0, tx: 0 };
    el("hCpu").innerHTML = N(pctTxt(d.cpu.percent)); el("hCpuChip").innerHTML = `עומס ${N(d.cpu.load1 ?? "—")}`;
    el("hMem").innerHTML = N(pctTxt(d.memory.percent));
    el("hMemChip").innerHTML = N(`${fmtBytes(d.memory.used)} / ${fmtBytes(d.memory.total)}`);
    const vh = d.vm_host, hm = el("hHostMem");
    hm.hidden = !vh;
    if (vh) {
      hm.className = "chip" + (vh.short ? " bad" : "");
      hm.innerHTML = `המחשב: ${N(fmtBytes(vh.mem_free))} פנוי`;
      hm.title = `זיכרון פנוי במחשב שמריץ את הלשכה, מתוך ${fmtBytes(vh.mem_total)} · נמדד ${ago(vh.age_s)}.` +
        (vh.short ? " כמעט לא נשאר: כשהוא אוזל, הלשכה כולה מפסיקה לענות." : "");
    }
    const disk = (d.storage || {}).root || {};
    el("hDisk").innerHTML = N(pctTxt(disk.percent)); el("hDiskChip").innerHTML = `${N(fmtBytes(disk.free))} פנוי`; setFill("hDiskFill", disk.percent);
    el("hNet").innerHTML = N(fmtRate(nr.rx)); el("hNetChip").innerHTML = `העלאה ${N(fmtRate(nr.tx))}`;
    const dk = d.docker || {}, total = dk.containers_total || 1;
    el("hCont").innerHTML = N(`${dk.containers_running || 0}/${dk.containers_total || 0}`);
    el("hContChip").innerHTML = dk.containers_unhealthy ? `${N(dk.containers_unhealthy)} לא תקינות` : "כולן תקינות";
    el("hContChip").className = `chip ${dk.containers_unhealthy ? "bad" : "ok"}`;
    setFill("hContFill", (dk.containers_running || 0) / total * 100, dk.containers_unhealthy ? "red" : "green");
    drawChart(hist);
    el("hLegend").innerHTML = [["מעבד", C.cpu, pctTxt(d.cpu.percent)], ["זיכרון", C.mem, pctTxt(d.memory.percent)],
      ["אחסון", C.disk, pctTxt(disk.percent)], ["רשת", C.net, fmtRate(Math.max(nr.rx, nr.tx))]]
      .map(([k, c, v]) => `<span class="li"><span class="sw" style="background:${c}"></span>${k}<b>${v}</b></span>`).join("");
    drawSpark("hSparkCpu", hist.map((r) => r.cpu), C.cpu, 100);
    drawSpark("hSparkMem", hist.map((r) => r.mem), C.mem, 100);
    drawSpark("hSparkNet", hist.map((r) => Math.max(r.rx || 0, r.tx || 0)), C.net);
    const up = d.host.uptime_seconds;
    const upTxt = up ? (up >= 86400 ? `${N((up / 86400).toFixed(1))} ימים` : `${N((up / 3600).toFixed(1))} שעות`) : "—";
    const c = herdComputer(where) || {};
    el("hInfo").innerHTML = [
      ["שם מארח", N(d.host.hostname)], ["מערכת הפעלה", N(d.host.os)], ["ליבה", N(d.host.kernel)],
      ["מעבד", `${N(d.cpu.cores)} ליבות · ${N(d.cpu.model || "—")}`],
      ["עומס", N(`${d.cpu.load1} / ${d.cpu.load5} / ${d.cpu.load15}`)], ["זמן פעילות", upTxt],
      ["לשכה", c.local ? "הלשכה הזאת" : esc(c.label || where)],
      ["המספרים מאת", h.src === "security" ? "אפליקציית האבטחה של המחשב" : "שירות המכונה של המחשב"],
    ].map(([k, v]) => `<div class="k">${k}</div><div class="v">${v || "—"}</div>`).join("");
    paintServices(where, d);
  }

  const SVC_COLS = () => {
    const eh = BinaTable.escapeHtml;
    return [
      // eight columns in 900px: the card's width at the console's, with no sideways scroll
      { key: "name", label: "שירות", width: 175, html: (v, r) => '<span class="svc-name" title="' + eh(r.image) + '">' + eh(v) + "</span>" },
      { key: "status", label: "סטטוס", width: 90, html: (v) => '<span class="status ' + eh(v) + '">' + eh(STATUS_HE[v] || v) + "</span>" },
      { key: "health", label: "תקינות", width: 90, html: (v) => (v ? '<span class="status ' + eh(v) + '">' + eh(HEALTH_HE[v] || v) + "</span>" : '<span class="bt-null">—</span>') },
      { key: "cpu_percent", label: "מעבד", width: 110, align: "end",
        html: (v) => '<span class="num">' + pctTxt(v) + '</span><span class="minibar"><i class="' + tone(v) + '" style="width:' + Math.min(100, v) + '%"></i></span>' },
      { key: "mem_used", label: "זיכרון", width: 120, align: "end",
        html: (v, r) => '<span class="pair"><span class="num">' + fmtBytes(v) + '</span><span class="small num">' + pctTxt(r.mem_pct) + "</span></span>" },
      { key: "net_total", label: "רשת", width: 130, align: "end",
        html: (v, r) => '<span class="small num">↓' + fmtBytes(r.net_rx) + " ↑" + fmtBytes(r.net_tx) + "</span>" },
      { key: "pids", label: "תהליכים", width: 85, align: "end" },
      { key: "restart_count", label: "הפעלות מחדש", width: 100, align: "end" },
    ];
  };
  function paintServices(where, d) {
    const rows = (d.containers || []).map((c) => ({
      name: c.name, status: c.status, health: c.health || "", cpu_percent: c.cpu_percent || 0,
      mem_used: (c.memory && c.memory.used) || 0, mem_pct: (c.memory && c.memory.percent) || 0,
      net_rx: (c.net && c.net.rx) || 0, net_tx: (c.net && c.net.tx) || 0,
      net_total: ((c.net && c.net.rx) || 0) + ((c.net && c.net.tx) || 0),
      pids: c.pids || 0, restart_count: c.restart_count || 0, image: c.image || "",
    })).sort((a, b) => b.cpu_percent - a.cpu_percent);
    // one is said as one (G86): «שירות אחד», never «1 שירותים»
    el("hSvcHint").textContent = rows.length ? `${rows.length === 1 ? "שירות אחד" : rows.length + " שירותים"} · העמוס ביותר ראשון` : "";
    if (typeof BinaTable === "undefined") return;
    if (T.grid && T.gridFor === where) { T.grid.setData(rows); return; }
    el("hSvc").innerHTML = "";
    T.grid = BinaTable.create(el("hSvc"), {
      tableId: "computers:services", rowKey: "name", columns: SVC_COLS(), data: rows, height: 520,
      searchPlaceholder: "סנן שירותים…",
      quickFilters: [
        { key: "running", label: "פועל", fn: (r) => r.status === "running" },
        { key: "exited", label: "הסתיים", fn: (r) => r.status === "exited" },
        { key: "unhealthy", label: "לא תקין", fn: (r) => r.health === "unhealthy" },
      ],
      emptyText: "אין שירותים להצגה", noMatchText: "אין שירותים תואמים לסינון",
    });
    T.gridFor = where;
  }

  // ── network (that computer's security app) ───────────────────────────────────────────────────────
  // The owner, 2026-11-01, over vps1's empty tab: «make sure perfect full inbound and outbound overview and in
  // detail … a reliable cyber visualiser giving you full observability and control». So three depths: the
  // OVERVIEW (the figures, where it comes from, what it reaches — and what this view itself can see: a source
  // that is blind is said, never shown as an empty list), the DETAIL (every address that came in and every
  // destination that was called, in the office's grid), and ONE address opened (its requests, sign-ins and
  // flows). The window and the opened address are the path (`net/7d/in/<ip>`): a reload lands on the same
  // screen. Control — a ban, a rule, enforcement — is the security app's own, one button away.
  const WIN = { "1h": [1, "השעה האחרונה", "שעה"], "24h": [24, "24 השעות האחרונות", "יממה"], "7d": [168, "7 הימים האחרונים", "שבוע"] };
  const winOf = (w) => WIN[w] || WIN["24h"];
  const LIST_LIMIT = 1000;
  const netRoute = (where, win, detail) => "c/" + where + "/net" + (win && win !== "24h" ? "/" + win : "") +
    (detail ? "/" + detail.dir + "/" + detail.ip : "");
  const fmtN = (v) => Number(v || 0).toLocaleString("he-IL");
  const agoLong = (s) => (s >= 172800 ? `לפני ${Math.round(s / 86400)} ימים` : ago(Math.max(0, s)));
  const sinceTs = (ts) => (ts ? agoLong(Date.now() / 1000 - ts) : "—");
  const tm = (ts) => (ts ? new Date(ts * 1000).toLocaleString("he-IL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
  const KIND_TIP = { "public": "אתר או שירות שפתוח לכולם", "private": "אפליקציה של הלשכה, מאחורי הכניסה", remote: "לשכה מקושרת שפתחה כאן אפליקציה",
                     auth: "דף הכניסה של הלשכה", door: "דלת הקישור בין הלשכות", none: "כתובת שאף נתב לא מכיר — בדרך כלל סריקה", link: "התנועה של הקישור בין הלשכות" };
  // what the edge calls a router is an id, not a name: the office's words for the ones that are its own
  const APP_HE = { authentik: "הכניסה של הלשכה", "forward-auth": "הכניסה של הלשכה", "dgo-net": "הקישור בין הלשכות",
                   "dgo-extend-link-door": "דלת הקישור", "@host": "המכונה עצמה" };
  const appText = (a) => {
    const id = String((a && typeof a === "object" ? a.app : a) || ""), title = (a && a.title) || "";
    if (APP_HE[id]) return APP_HE[id];
    if (id.startsWith("site:")) return "אתר · " + id.slice(5);
    return (title && title !== id ? title : id) || "ללא אפליקציה";
  };
  // a name nobody translated stays an identifier, shown as one (mono, left to right)
  const appHtml = (a) => {
    const id = String((a && typeof a === "object" ? a.app : a) || ""), t = appText(a);
    return t === id && !APP_HE[id] ? `<span class="tok">${esc(id)}</span>` : esc(t);
  };
  const PORT_HE = { "22/tcp": "SSH", "25/tcp": "דואר נכנס", "53/udp": "DNS", "53/tcp": "DNS", "80/tcp": "אתרים (HTTP)", "443/tcp": "אתרים (HTTPS)",
                    "443/udp": "אתרים (HTTP/3)", "465/tcp": "דואר (SMTPS)", "587/tcp": "דואר יוצא", "993/tcp": "תיבות דואר (IMAPS)",
                    "3478/udp": "וידאו (TURN)", "10000/udp": "וידאו (Meet)", "0/icmp": "פינג (ICMP)" };
  const STATE_HE = { banned: ["חסומה", "bad"], would: ["הייתה נחסמת", "warn"], trusted: ["נכנסה בשם משתמש", "ok"], allowed: ["ברשימת ההיתר", "ok"],
                     herd: ["לשכה בעדר", "ok"], own: ["המחשב הזה", "ok"], blocked: ["חסום", "bad"] };
  // the link's door writes the OFFICE that came through it where an address would be (`macbook`): that is the
  // herd, not a stranger — and it has no address of its own to open
  const isIp = (v) => /^[0-9.]+$|:/.test(String(v || ""));
  const netState = (r) => STATE_HE[r.state] || (r.ip && !isIp(r.ip) ? ["לשכה מקושרת", "ok"]
    : r.local ? ["פנימית", "unset"] : ["לא מוכרת", "unset"]);
  const pill = ([t, cls]) => `<span class="pill ${cls}">${esc(t)}</span>`;
  const idHtml = (v) => `<span class="tok">${esc(v)}</span>`;

  function netSkeleton() {
    const [, span] = winOf(T.win);
    const k = (label, id) => `<div class="pg-kpi is-zero"><div class="pg-kpi-k">${label}</div><div class="pg-kpi-v num" id="${id}">—</div><span class="sub" id="${id}Sub"></span></div>`;
    const seg = Object.keys(WIN).map((w) => `<button type="button" role="tab" data-net-win="${w}" aria-selected="${w === T.win}" ` +
      `title="הנכנסים והיוצאים של ${esc(WIN[w][1])}">${WIN[w][2]}</button>`).join("");
    const card = (title, id) => `<div class="card"><h3><span>${title}</span><span class="small muted" id="${id}Hint">${span}</span></h3>` +
      `<div id="${id}"><div class="spin">טוען…</div></div></div>`;
    return `<div class="netbar"><div class="seg" role="tablist" aria-label="חלון הזמן">${seg}</div><span class="small muted" id="nAt"></span></div>
      <div class="pg-kpis netkpis">${k("בקשות נכנסות", "nReq")}${k("כתובות", "nAddr")}${k("היו נחסמות", "nWould")}` +
      `${k("כניסות שנכשלו", "nFail")}${k("יעדים יוצאים", "nOut")}</div>
      <div class="facts netsrc" id="nSrc"></div>
      <div class="cols cols-2">${card("מאיפה נכנסים", "nFrom")}${card("מה נפתח מבחוץ", "nReach")}</div>
      ${card("מי נכנס", "nIn")}${card("לאן יוצאים", "nOut2")}
      <div class="card"><h3><span>הרשת והנתב</span><span class="small muted" id="nNetAt"></span></h3><div id="nNet"></div></div>`;
  }
  /** The network tab's reads for one window, RETURNED rather than written: the caller keeps them only if the
   *  screen is still the one that asked (a 24h answer arriving after the switch to 7d is dropped). */
  async function loadNet(where, win) {
    const hrs = winOf(win)[0];
    const [s, i, o, n] = await Promise.all([read(where, "security", "api/summary", "hours=" + hrs),
      read(where, "security", "api/inbound", `hours=${hrs}&limit=${LIST_LIMIT}`),
      read(where, "security", "api/outbound", `hours=${hrs}&limit=${LIST_LIMIT}`), read(where, "security", "api/network")]);
    // this tab's own window: the fleet's row keeps reading the day (`summary`), into its own fields
    const got = s.ok && s.d && s.d.kpi ? { nsum: s.d, nsumErr: "", nsumStatus: 200, nsumAt: Date.now() }
      : { nsum: null, nsumErr: (s.d && s.d.error) || binaSaid(s.status), nsumStatus: s.status };
    return Object.assign(got, {
      inb: i.ok ? (i.d.rows || []) : null, inbErr: i.ok ? "" : (i.d && i.d.error) || binaSaid(i.status),
      outb: o.ok ? (o.d.rows || []) : null, outbErr: o.ok ? "" : (o.d && o.d.error) || binaSaid(o.status),
      ports: o.ok ? (o.d.inbound_ports || []) : null, net: n.ok ? n.d : null,
    });
  }
  const REGION = typeof Intl !== "undefined" && Intl.DisplayNames ? new Intl.DisplayNames(["he"], { type: "region" }) : null;
  const country = (cc) => { try { return REGION ? REGION.of(cc) : cc; } catch (e) { return cc; } };
  const place = (r) => [r.cc ? country(r.cc) : "", r.city].filter(Boolean).join(" · ") || r.local || "";
  function miniTable(cols, rows, empty) {
    if (!rows || !rows.length) return `<div class="spin">${esc(empty)}</div>`;
    return `<table class="table"><thead><tr>${cols.map((c) => `<th>${esc(c[0])}</th>`).join("")}</tr></thead><tbody>` +
      rows.map((r) => `<tr>${cols.map((c) => `<td data-th="${esc(c[0])}"><div class="cell">${c[1](r)}</div></td>`).join("")}</tr>`).join("") +
      "</tbody></table>";
  }
  /** One bar per row, longest first — the storage view's `.pathBar`, so the two read alike. */
  function bars(rows, empty) {
    if (!rows.length) return `<div class="spin">${esc(empty)}</div>`;
    const max = Math.max(1, ...rows.map((r) => r.n || 0));
    return '<div class="netbars">' + rows.map((r) => `<div class="pathBar"><div><div class="pathName" title="${esc(r.tip || r.label)}">${r.html || esc(r.label)}</div>` +
      (r.sub ? `<div class="pathSub">${esc(r.sub)}</div>` : "") + "</div>" +
      `<div class="mbar"><div class="mfill" style="width:${(r.n || 0) / max * 100}%"></div></div><div class="num">${fmtN(r.n)}</div></div>`).join("") + "</div>";
  }
  function dropGrids(keys) {
    (keys || ["gIn", "gOut"]).forEach((key) => { if (T[key]) { try { T[key].destroy(); } catch (e) { /* its DOM is already gone */ } } T[key] = null; });
  }
  /** The office's grid in a card, created once per screen and refreshed in place — sort, search and filter survive. */
  function grid(slot, key, opts, rows) {
    const box = el(slot);
    if (T[key] && T[key + "El"] === box) { T[key].setData(rows); return; }
    if (T[key]) { try { T[key].destroy(); } catch (e) { /* replaced */ } }
    box.innerHTML = "";
    T[key] = BinaTable.create(box, Object.assign({ data: rows, height: 460 }, opts));
    T[key + "El"] = box;
  }
  function paintNet(where, h) {
    const c = herdComputer(where) || {};
    el("nAt").textContent = h.nsumAt ? "עודכן " + new Date(h.nsumAt).toLocaleTimeString("he-IL") : "";
    if (!h.nsum) {
      const missing = h.nsumStatus === 404 || h.nsumStatus === 403;
      notice(alertBox(missing ? "" : "warn", missing
        ? `<b>אפליקציית האבטחה לא פועלת במחשב הזה${c.local ? "" : ", או שהלשכה לא נותנת אותה דרך הקישור"}.</b> ` +
          "את הנכנסים והיוצאים של מחשב רואה האבטחה שרצה עליו. המשאבים והאחסון מוצגים גם בלעדיה."
        : "<b>האבטחה של המחשב לא ענתה.</b> " + esc(h.nsumErr || "")));
      dropGrids();
      el("nSrc").innerHTML = "";
      ["nFrom", "nReach", "nIn", "nOut2", "nNet"].forEach((id) => { el(id).innerHTML = '<div class="spin">אין נתונים.</div>'; });
      return;
    }
    notice(h.nsum.mode === "enforce" ? "" : alertBox("", "<b>מצב צפייה.</b> האבטחה של המחשב רואה ורושמת הכול, ואינה חוסמת עד שעוברים בה לאכיפה."));
    const k = h.nsum.kpi || {};
    const fig = (id, v, sub, state) => {
      const n = el(id), tile = n.parentNode;
      n.textContent = Number(v || 0).toLocaleString("he-IL");
      el(id + "Sub").textContent = sub || "";
      tile.classList.toggle("is-zero", !v);
      if (v && state) tile.dataset.state = state; else delete tile.dataset.state;
    };
    const kinds = k.kinds || {};
    fig("nReq", k.requests, `${Number(kinds["public"] || 0).toLocaleString("he-IL")} ציבורי · ${Number((kinds["private"] || 0) + (kinds.auth || 0)).toLocaleString("he-IL")} פרטי`, "running");
    fig("nAddr", k.addrs, k.countries ? `${k.countries} מדינות` : "", "");
    fig("nWould", (k.bans || 0) + (k.would_ban || 0), k.bans ? `${k.bans} חסומות` : "", "todo");
    fig("nFail", k.signin_fail, `${k.signin_ok || 0} הצליחו`, "failed");
    fig("nOut", k.out_dests, `${Number(k.out_conns || 0).toLocaleString("he-IL")} חיבורים`, "running");
    paintSources(h.nsum);
    paintFrom(h.nsum);
    paintReach(h.nsum, h.ports || []);
    paintInGrid(where, h);
    paintOutGrid(where, h);
    paintRouter(c, h);
  }

  /** What this view can see, and what it cannot: each source the security app reads, said in one cell. */
  function paintSources(s) {
    const hl = s.health || {}, parts = hl.sensor_parts || {};
    const PART_HE = { conntrack: "טבלת החיבורים", sniffer: "המאזין", journal: "יומן המערכת", nft: "חומת האש", volume: "מוני הנפח" };
    const cell = (key, ok, v, tip) => `<div><div class="k">${esc(key)}</div>` +
      `<div class="v ${ok === true ? "ok" : ok === false ? "bad" : "muted"}" title="${esc(tip || v)}">${esc(v)}</div></div>`;
    const e = hl.edge || {}, a = hl.auth || {}, sn = hl.sensor || {}, g = hl.geo || {}, door = hl.door || {};
    const broken = Object.keys(parts).filter((p) => parts[p] && parts[p].ok === false);
    const geoOk = !g.error && Object.keys(g.files || {}).length > 0;
    el("nSrc").innerHTML =
      cell("יומן הקצה (כל בקשה נכנסת)", e.ok, e.ok ? `נקרא · ${fmtN(e.parsed)} שורות` : e.ok === false ? "לא נקרא" : "לא מוגדר", e.error) +
      cell("יומן הכניסות", a.ok, a.ok ? "נקרא" : a.ok === false ? "לא נקרא" : "לא מוגדר", a.error) +
      cell("החיישן במכונה (יוצא, פורטים)", sn.ok && !broken.length,
           !sn.ok ? "לא מדווח" : broken.length ? "חלקי · " + broken.map((p) => PART_HE[p] || p).join(", ") : "פועל · " + ago(sn.age_s || 0),
           broken.map((p) => (PART_HE[p] || p) + ": " + ((parts[p] || {}).error || "")).join(" · ")) +
      cell("מיקום הכתובות", geoOk ? true : g.want === "off" ? null : g.error ? false : null,
           geoOk ? (g.want === "country" ? "מדינה" : "עיר ומדינה") : g.want === "off" ? "כבוי" : g.error ? "לא זמין" : "בהורדה", g.error) +
      cell("יומן דלת הקישור", door.ok, door.ok ? "נקרא" : door.ok === false ? "לא נקרא" : "אין דלת", door.error) +
      cell("מצב", s.mode === "enforce" ? true : null, s.mode === "enforce" ? "אכיפה — חוסמת" : "צפייה — רושמת, לא חוסמת");
  }
  function paintFrom(s) {
    const kinds = (s.kpi || {}).kinds || {};
    const byKind = Object.keys(kinds).map((x) => ({ label: KIND_HE[x] || x, tip: KIND_TIP[x] || x, n: kinds[x] })).sort((a, b) => b.n - a.n);
    const byCc = ((s.top || {}).countries || []).map((r) => ({ label: country(r.cc), tip: r.cc, sub: `${fmtN(r.addrs)} כתובות`, n: r.n }));
    el("nFrom").innerHTML = '<div class="subh">לפי סוג הכניסה</div>' + bars(byKind, "אין בקשות בחלון הזה.") +
      '<div class="subh">לפי מדינה</div>' + bars(byCc, "אין כתובות עם מיקום בחלון הזה.");
  }
  function paintReach(s, ports) {
    const apps = ((s.top || {}).apps || []).map((r) => ({ html: appHtml(r) + (r.office ? ` <span class="small muted">· ${esc(r.office)}</span>` : ""),
      label: appText(r), sub: `${KIND_HE[r.kind] || r.kind} · ${fmtN(r.addrs)} כתובות`, n: r.n }));
    const byPort = ports.map((p) => {
      const key = p.port + "/" + p.proto;
      return { html: (PORT_HE[key] ? esc(PORT_HE[key]) + " " : "") + idHtml(p.proto === "icmp" ? "icmp" : key), label: key,
               sub: `${fmtN(p.addrs)} כתובות · לאחרונה ${sinceTs(p.last)}`, n: p.n };
    });
    el("nReach").innerHTML = '<div class="subh">האפליקציות שנפתחו</div>' + bars(apps, "אף אפליקציה לא נפתחה בחלון הזה.") +
      '<div class="subh">פורטים שקיבלו חיבור מבחוץ</div>' + bars(byPort, "החיישן לא ראה חיבור נכנס בחלון הזה.");
  }

  const IN_COLS = () => [
    { key: "ip", label: "כתובת", width: 125, html: (v) => idHtml(v) },
    { key: "stateTxt", label: "מצב", width: 110, html: (v, r) => pill([v, r.stateCls]) },
    { key: "placeTxt", label: "מקום", width: 120 },
    { key: "org", label: "רשת", width: 140 },
    { key: "appsTxt", label: "מה נפתח", width: 170 },
    { key: "kindsTxt", label: "סוג", width: 150, hidden: true },
    { key: "n", label: "בקשות", width: 75, align: "end", html: (v) => N(fmtN(v)) },
    { key: "fails", label: "נכשלו", width: 60, align: "end", html: (v) => N(fmtN(v)) },
    { key: "last", label: "לאחרונה", width: 90, html: (v) => esc(sinceTs(v)) },
  ];
  function paintInGrid(where, h) {
    const [, span] = winOf(T.win);
    if (!h.inb) { dropGrids(["gIn"]); el("nIn").innerHTML = alertBox("warn", "<b>רשימת הנכנסים לא נקראה.</b> " + esc(h.inbErr || "")); return; }
    const rows = h.inb.map((r) => {
      const [st, cls] = netState(r);
      return Object.assign({}, r, { stateTxt: st, stateCls: cls, placeTxt: place(r) || "לא ידוע", org: r.org || "",
        appsTxt: (r.apps || []).map(appText).join(", "), kindsTxt: (r.kinds || []).map((x) => KIND_HE[x] || x).join(", ") });
    });
    el("nInHint").textContent = span + " · " + (rows.length >= LIST_LIMIT ? `${fmtN(LIST_LIMIT)} הכתובות הפעילות ביותר` : `${fmtN(rows.length)} כתובות`);
    grid("nIn", "gIn", {
      tableId: "computers:net-in", rowKey: "ip", columns: IN_COLS(), searchPlaceholder: "חיפוש כתובת, מקום, רשת או אפליקציה…",
      quickFilters: [
        { key: "fails", label: "עם כישלונות", fn: (r) => r.fails > 0 },
        { key: "stranger", label: "לא מוכרות", fn: (r) => r.state === "seen" && !r.local },
        { key: "would", label: "חסומות או היו נחסמות", fn: (r) => r.state === "would" || r.state === "banned" },
        { key: "public", label: "לאתרים הציבוריים", fn: (r) => (r.kinds || []).indexOf("public") >= 0 },
      ],
      emptyText: "אף כתובת לא נכנסה בחלון הזה.", noMatchText: "אין כתובות תואמות לסינון",
      onRowClick: (r) => go(netRoute(where, T.win, { dir: "in", ip: r.ip })),
    }, rows);
  }
  const OUT_COLS = () => [
    { key: "dstTxt", label: "יעד", width: 180, html: (v, r) => (r.names && r.names.length ? `<b class="ltr">${esc(v)}</b>` : idHtml(v)) },
    { key: "dst", label: "כתובת", width: 130, html: (v) => idHtml(v), hidden: true },
    { key: "placeTxt", label: "מקום", width: 100 },
    { key: "org", label: "רשת", width: 120 },
    { key: "appsTxt", label: "מי פנה", width: 120, html: (v, r) => (r.apps || []).map(appHtml).join(", ") || "—" },
    { key: "portsTxt", label: "פורטים", width: 90, html: (v) => idHtml(v) },
    { key: "n", label: "חיבורים", width: 70, align: "end", html: (v) => N(fmtN(v)) },
    { key: "bytes", label: "נפח ↑ ↓", width: 130, align: "end", html: (v, r) => N(`↑${fmtBytes(r.bytes_out)} ↓${fmtBytes(r.bytes_in)}`) },
    { key: "last", label: "לאחרונה", width: 85, html: (v) => esc(sinceTs(v)) },
  ];
  function paintOutGrid(where, h) {
    const [, span] = winOf(T.win);
    if (!h.outb) { dropGrids(["gOut"]); el("nOut2").innerHTML = alertBox("warn", "<b>רשימת היוצאים לא נקראה.</b> " + esc(h.outbErr || "")); return; }
    const rows = h.outb.map((r) => Object.assign({}, r, {
      // an unnamed address is its own title; what it IS (r.local) is said once, in the place column
      dstTxt: (r.names && r.names[0]) || r.dst, placeTxt: place(r) || "לא ידוע", org: r.org || "",
      appsTxt: (r.apps || []).map(appText).join(", "), portsTxt: (r.ports || []).join(" "), bytes: (r.bytes_out || 0) + (r.bytes_in || 0),
    }));
    el("nOut2Hint").textContent = span + " · " + (rows.length >= LIST_LIMIT ? `${fmtN(LIST_LIMIT)} היעדים הפעילים ביותר` : `${fmtN(rows.length)} יעדים`);
    grid("nOut2", "gOut", {
      tableId: "computers:net-out", rowKey: "dst", columns: OUT_COLS(), searchPlaceholder: "חיפוש שם, כתובת, רשת או אפליקציה…",
      quickFilters: [
        { key: "host", label: "המכונה עצמה", fn: (r) => (r.apps || []).indexOf("@host") >= 0 },
        { key: "apps", label: "אפליקציות", fn: (r) => (r.apps || []).some((a) => a !== "@host") },
        { key: "noname", label: "בלי שם", fn: (r) => !(r.names && r.names.length) },
        { key: "blocked", label: "חסומים", fn: (r) => r.state === "blocked" },
      ],
      emptyText: "המחשב לא פנה החוצה בחלון הזה.", noMatchText: "אין יעדים תואמים לסינון",
      onRowClick: (r) => go(netRoute(where, T.win, { dir: "out", ip: r.dst })),
    }, rows);
  }

  function paintRouter(c, h) {
    const f = (h.net && h.net.facts) || {};
    const routers = ((f.router || {}).routers || []);
    const fact = (k2, v) => `<div><div class="k">${esc(k2)}</div><div class="v" title="${esc(v)}">${esc(v)}</div></div>`;
    el("nNetAt").textContent = f.at ? "עודכן " + ago(Date.now() / 1000 - f.at) : "";
    el("nNet").innerHTML = `<div class="facts">` + fact("כתובת ציבורית", f.public_ip || "לא ידועה") + fact("שער", f.gateway || "—") +
      fact("פורטים פתוחים לכל הרשתות", String(((f.listen || []).filter((p) => p.scope === "all" || p.addr === "0.0.0.0" || p.addr === "::")
        .map((p) => p.port + "/" + p.proto).filter((v, i, a) => a.indexOf(v) === i).length))) +
      routers.map((r) => fact(r.role === "declared" ? "הנתב הפיזי" : "השער הראשון", `${r.ip} · ${((r.http || {}).title) || "—"} · פורטי ניהול ${(r.open || []).join(" ")}`)).join("") +
      "</div>" + (c.local ? `<div class="rowacts" style="margin-top:12px"><button type="button" class="btn ghost sm" data-open-app="security" title="פתיחת אפליקציית האבטחה של המחשב הזה — שם החסימות, הכללים והמפה">פתיחה באבטחה</button></div>` : "");
  }

  // ── one address, opened: everything the computer's security app keeps about it ────────────────────
  async function openDetail(where, d) {
    if (!el("netModal")) return;
    const gen = ++T.dgen;
    el("netTitle").innerHTML = (d.dir === "in" ? "כתובת שנכנסה " : "יעד יוצא ") + idHtml(d.ip);
    el("netBody").innerHTML = '<div class="spin">טוען…</div>';
    openModal("netModal");
    if (!isIp(d.ip)) {
      // opened by a reload or a link, before the list was read: read it here
      let rows = hd(where).inb;
      if (!rows) {
        const got = await loadNet(where, T.win);
        if (gen !== T.dgen) return;
        rows = got.inb || [];
      }
      const row = rows.find((x) => x.ip === d.ip) || {};
      el("netBody").innerHTML = alertBox("", `<b>זו הלשכה ${esc(d.ip)}, שנכנסה דרך הקישור.</b> לקישור אין כתובת משלו כאן — ` +
        "את הכתובת שממנה הלשכה מתחברת רואים בתצוגת הרשת של המחשב שלה.") +
        factsHtml([["בקשות", fmtN(row.n)], ["נכשלו", fmtN(row.fails)], ["מה נפתח", (row.apps || []).map(appText).join(", ") || "—"],
                   ["לאחרונה", sinceTs(row.last)]]);
      return;
    }
    const r = await read(where, "security", (d.dir === "in" ? "api/inbound/" : "api/outbound/") + encodeURIComponent(d.ip));
    if (gen !== T.dgen) return;
    if (!r.ok || !r.d) {
      el("netBody").innerHTML = alertBox("warn", "<b>הפרטים של הכתובת לא נקראו.</b> " + esc((r.d && r.d.error) || binaSaid(r.status)));
      return;
    }
    const c = herdComputer(where) || { local: where === "local" };
    el("netBody").innerHTML = (d.dir === "in" ? inDetail(where, d.ip, r.d) : outDetail(where, d.ip, r.d)) +
      `<div class="rowacts netacts">${c.local
        ? '<button type="button" class="btn sm" data-open-app="security" title="פתיחת אפליקציית האבטחה של המחשב הזה — שם חוסמים כתובת, מוסיפים כלל ועוברים לאכיפה">חסימה וכללים באבטחה</button>'
        : '<span class="small muted">חסימה וכללים — מהלשכה של המחשב עצמו, באפליקציית האבטחה שלה.</span>'}</div>`;
  }
  function closeDetail() {
    T.dgen++;
    if (el("netModal")) closeModal("netModal");
  }
  const factsHtml = (rows) => '<div class="facts netfacts">' + rows.map(([k2, v, raw]) =>
    `<div><div class="k">${esc(k2)}</div><div class="v" title="${raw ? "" : esc(v)}">${raw ? v : esc(v)}</div></div>`).join("") + "</div>";
  const section = (title, html) => `<div class="subh">${esc(title)}</div><div class="scrollbox">${html}</div>`;
  const VERDICT_HE = { ok: ["הצליחה", "ok"], fail: ["נכשלה", "bad"], out: ["יציאה", "unset"] };
  const SRC_HE = { ssh: "SSH", auth: "הכניסה של הלשכה" };
  const BAN_HE = { ban: "נחסמה", unban: "שוחררה", expire: "החסימה פגה" };
  const VIA_HE = { dns: "שאילתת DNS", tls: "שם בחיבור המוצפן", ptr: "רישום הפוך" };

  function inDetail(where, ip, d) {
    const a = d.addr || {}, row = ((hd(where).inb) || []).find((r) => r.ip === ip) || {};
    const trustState = { "signed-in": "trusted", allowed: "allowed", herd: "herd", own: "own" }[d.trust] || "seen";
    const banState = d.ban && d.ban.active ? (d.ban.mode === "enforce" ? "banned" : "would") : "";
    const st = netState({ state: row.state || banState || trustState, local: a.local });
    const days = d.days || [], hits = d.hits || [];
    const total = days.reduce((s, x) => s + (x.n || 0), 0), fails = days.reduce((s, x) => s + (x.fails || 0), 0);
    return factsHtml([
      ["מצב", pill(st), true], ["מה זו", a.local || "כתובת באינטרנט"], ["מקום", place(a) || "לא ידוע"], ["רשת", a.org || "—"],
      ["מספר הרשת", a.asn ? "AS" + a.asn : "—"], ["נכנסה בשם", (a.users || []).join(", ") || "—"],
      ["בקשות · 120 יום", fmtN(total)], ["נכשלו", fmtN(fails)], ["נראתה לראשונה", tm(a.first)], ["לאחרונה", sinceTs(a.last || row.last)],
    ]) + (d.ban && d.ban.active ? alertBox(d.ban.mode === "enforce" ? "bad" : "warn",
      `<b>${d.ban.mode === "enforce" ? "הכתובת חסומה" : "הכתובת הייתה נחסמת"}</b> — ${esc(d.ban.reason || d.ban.jail || "")}` +
      (d.ban.until ? ` · עד ${esc(tm(d.ban.until))}` : "")) : "") +
      section(`הבקשות האחרונות (${fmtN(hits.length)})`, miniTable([
        ["מתי", (x) => N(tm(x.ts))],
        ["אפליקציה", (x) => appHtml({ app: x.app, title: x.title }) + (x.office ? ` <span class="small muted">· ${esc(x.office)}</span>` : "")],
        ["בקשה", (x) => `<span class="tok" title="${esc((x.host || "") + (x.path || ""))}">${esc(((x.method || "") + " " + (x.path || "")).trim() || "—")}</span>`],
        ["תשובה", (x) => (x.status ? pill([String(x.status), x.status >= 500 ? "bad" : x.status >= 400 ? "warn" : "ok"]) : "—")],
        ["משך", (x) => (x.ms != null ? N(Math.round(x.ms) + " ms") : "—")],
      ], hits, "אין בקשות שמורות לכתובת הזאת — כל בקשה נשמרת שלושה ימים, והסיכום היומי 120 יום.")) +
      ((d.signins || []).length ? section("כניסות", miniTable([
        ["מתי", (x) => N(tm(x.ts))], ["דרך", (x) => esc(SRC_HE[x.src] || x.src || "—")],
        ["תוצאה", (x) => pill(VERDICT_HE[x.verdict] || [x.verdict || "—", "unset"])], ["משתמש", (x) => (x.user ? idHtml(x.user) : "—")],
      ], d.signins, "")) : "") +
      ((d.flows || []).length ? section("חיבורים ברמת הרשת", miniTable([
        ["לאחרונה", (x) => N(tm(x.last))], ["כיוון", (x) => esc(x.dir === "in" ? "נכנס" : "יוצא")],
        ["פורט", (x) => idHtml(x.port + "/" + x.proto)], ["חיבורים", (x) => N(fmtN(x.n))],
      ], d.flows, "")) : "") +
      ((d.ban_log || []).length ? section("היסטוריית חסימות", miniTable([
        ["מתי", (x) => N(tm(x.ts))], ["מה קרה", (x) => esc(BAN_HE[x.action] || x.action || "—")],
        ["סיבה", (x) => esc(x.reason || x.jail || "—")], ["מאת", (x) => (x.by ? idHtml(x.by) : "—")],
      ], d.ban_log, "")) : "");
  }
  function outDetail(where, ip, d) {
    const a = d.addr || {}, row = ((hd(where).outb) || []).find((r) => r.dst === ip) || {};
    const flows = d.flows || [], names = d.names || [];
    const sum = (k2) => flows.reduce((s, x) => s + (x[k2] || 0), 0);
    return factsHtml([
      ["שם", (names[0] && names[0].name) || "אין שם ידוע"], ["מה זו", row.local || "כתובת באינטרנט"], ["מקום", place(a) || "לא ידוע"],
      ["רשת", a.org || "—"], ["מספר הרשת", a.asn ? "AS" + a.asn : "—"], ["חסימה", d.blocked ? "חסום" : "פתוח"],
      ["חיבורים · 60 יום", fmtN(sum("n"))], ["נשלח", fmtBytes(row.bytes_out || sum("bytes_out"))], ["התקבל", fmtBytes(row.bytes_in || sum("bytes_in"))],
      ["לאחרונה", sinceTs(row.last || (flows[0] || {}).last)],
    ]) + section(`החיבורים (${fmtN(flows.length)})`, miniTable([
      ["לאחרונה", (x) => N(tm(x.last))], ["מי פנה", (x) => appHtml(x.app)],
      ["פורט", (x) => { const key = x.port + "/" + x.proto; return (PORT_HE[key] ? esc(PORT_HE[key]) + " " : "") + idHtml(key); }],
      ["חיבורים", (x) => N(fmtN(x.n))], ["נשלח", (x) => N(fmtBytes(x.bytes_out))], ["התקבל", (x) => N(fmtBytes(x.bytes_in))],
    ], flows, "אין חיבורים שמורים ליעד הזה — חיבור נשמר 60 יום.")) +
      (names.length ? section("השמות של הכתובת", miniTable([
        ["שם", (x) => `<b class="ltr">${esc(x.name)}</b>`], ["נלמד מ", (x) => esc(VIA_HE[x.via] || x.via || "—")],
        ["פעמים", (x) => N(fmtN(x.n))], ["לאחרונה", (x) => N(tm(x.last))],
      ], names, "")) : "");
  }
  // the opened address belongs to the path: closing it (the button, the scrim, Escape) writes the list's address back
  function detailClosed() {
    if (!T.detail || !el("netModal") || !el("netModal").classList.contains("hidden")) return;
    T.detail = null;
    T.dgen++;
    // replaced, not pushed: Back after a close goes where the list came from, not into the closed address
    showRoute(netRoute(T.where, T.win, null), true);
  }
  document.addEventListener("click", (e) => {
    const w = e.target.closest && e.target.closest("[data-net-win]");
    if (w && T.where) { go(netRoute(T.where, w.dataset.netWin, null)); return; }
    if (T.detail) setTimeout(detailClosed, 0);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && T.detail) setTimeout(detailClosed, 0); });

  // ── storage (machine's) ──────────────────────────────────────────────────────────────────────────
  function diskSkeleton() {
    return `<div class="cols cols-7-5">
        <div class="card"><h3><span>סקירת אחסון</span><span class="small muted" id="dStamp"></span></h3><div id="dBars"><div class="spin">טוען…</div></div></div>
        <div class="card"><h3>אחסון Docker</h3><div class="kv" id="dDocker"></div></div>
      </div>
      <div class="card"><h3><span>ניקוי אחסון</span><span class="small muted" id="dCleanNote"></span></h3><div class="actions-grid" id="dClean"></div></div>`;
  }
  function paintDisk(where, h) {
    const d = h.ov;
    if (!d) { notice(noResources(h)); return; }
    notice("");
    const s = d.storage || {}, tops = s.top_paths || [], max = Math.max(1, ...tops.map((p) => p.size || 0));
    el("dStamp").textContent = s.generated_at ? `עודכן ${new Date(s.generated_at).toLocaleTimeString("he-IL")}` : "";
    el("dBars").innerHTML = tops.length ? tops.map((p) => `
      <div class="pathBar"><div><div class="pathName">${esc(p.label)}</div><div class="path">${esc(p.path || "/")}</div></div>
        <div class="mbar"><div class="mfill" style="width:${(p.size || 0) / max * 100}%"></div></div><div class="num">${fmtBytes(p.size)}</div></div>`).join("")
      : `<div class="spin">${h.src === "security" ? "מדידת התיקיות היא של שירות המכונה, שאינו פועל במחשב הזה." : "המדידה הראשונה של התיקיות רצה ברקע — היא תופיע כאן בעוד רגע."}</div>`;
    const df = s.docker_df || {}, arr = (x) => (Array.isArray(x) ? x : []);
    const imageBytes = arr(df.Images).reduce((a, i) => a + (i.Size || i.VirtualSize || 0), 0);
    const volBytes = arr(df.Volumes).reduce((a, v) => a + ((v.UsageData || {}).Size || 0), 0);
    const reclaim = arr(df.Images).reduce((a, i) => a + (i.Containers === 0 ? (i.Size || i.VirtualSize || 0) : 0), 0);
    el("dDocker").innerHTML = df.error ? `<div class="v muted">${esc(df.error)}</div>` : [["אימג׳ים", `${N(arr(df.Images).length)} · ${N(fmtBytes(imageBytes))}`],
      ["כרכים", `${N(arr(df.Volumes).length)} · ${N(fmtBytes(volBytes))}`], ["מכולות", N(arr(df.Containers).length)],
      ["מטמון בנייה", `${N(arr(df.BuildCache).length)} רשומות`], ["אומדן אימג׳ים לא פעילים", N(fmtBytes(reclaim))]]
      .map(([k, v]) => `<div class="k">${k}</div><div class="v">${v}</div>`).join("");
    const local = where === "local" && h.src === "machine";
    const enabled = local && d.cleanup_enabled;
    el("dCleanNote").textContent = !local ? (where === "local" ? "שירות המכונה אינו פועל כאן" : "מנקים מהלשכה של המחשב עצמו")
      : enabled ? `מותר: ${(d.cleanup_allowed_actions || []).map((id) => cleanHe({ id })[0]).join(", ")}` : "אין פעולות ניקוי מותרות כרגע";
    if (!local) {
      el("dClean").innerHTML = `<div class="spin">${where === "local"
        ? "את הניקוי מריץ שירות המכונה, והוא אינו פועל במחשב הזה — המספרים כאן הם של אפליקציית האבטחה, שרק קוראת."
        : "ניקוי הוא פעולה על המחשב עצמו, ולכן הוא נעשה מהלשכה שלו — כאן מוצג המצב בלבד."}</div>`;
      return;
    }
    el("dClean").innerHTML = (T.clean || []).map((opt) => {
      const on = Boolean(enabled && opt.enabled), [he, what] = cleanHe(opt);
      const why = enabled ? "אינה בין הפעולות שהותרו במחשב הזה" : "פעולה זו אינה מאושרת בתצורה הנוכחית";
      return `<div class="action"><b title="${esc(opt.id)}">${esc(he)}</b><span class="small risk-${esc(opt.risk)}">סיכון ${esc(RISK_HE[opt.risk] || opt.risk)}</span>
        <p>${esc(what)}</p>${on ? "" : `<p>${esc(why)}</p>`}
        <button type="button" class="btn sm" data-clean="${esc(opt.id)}" ${on ? "" : "disabled"} title="${on ? "הרצת הניקוי עכשיו — תישאל לפני שמשהו נמחק" : esc(why)}">${on ? "הרצה" : "מושבת"}</button></div>`;
    }).join("") || '<div class="spin">אין פעולות ניקוי.</div>';
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-clean]");
    if (!b || b.disabled) return;
    const opt = (T.clean || []).find((o) => o.id === b.dataset.clean) || { id: b.dataset.clean };
    const [he, what] = cleanHe(opt);
    if (!await binaAsk({ title: `להריץ את «${he}»?`, body: what, ok: "הרצה", danger: opt.risk === "high",
      facts: [["מחשב", "המחשב הזה"], ["סיכון", RISK_HE[opt.risk] || opt.risk || "—"]] })) return;
    b.disabled = true; b.textContent = "רץ…";
    const r = await api("api/hosts/local/machine/cleanup/" + encodeURIComponent(opt.id), { method: "POST" });
    if (r.ok) { binaTell(`«${he}» הסתיים`, "ok"); T.clean = null; tick(); }
    else { b.disabled = false; b.textContent = "הרצה"; binaTell((r.d && (r.d.error || r.d.detail)) || binaSaid(r.status), "bad"); }
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-open-app]");
    if (!b) return;
    // the console's own address for an app: the shell is the parent frame; standalone, the app's own path
    try { if (window.top !== window && window.top.location) { window.top.location.hash = "#/m/" + b.dataset.openApp; return; } }
    catch (er) { /* a parent on another origin: fall through */ }
    location.href = "../" + b.dataset.openApp + "/";
  });

  // ── access: the computer's SSH instance, when it has one ─────────────────────────────────────────
  function paintSsh(where) {
    const c = sshOf(where);
    if (!c) {
      el("hSsh").innerHTML = alertBox("", "<b>אין למחשב הזה גישת SSH מהלשכה.</b> " +
        "את המשאבים והרשת שלו מספרים השירותים שרצים עליו. כדי להריץ בו פקודה או לבדוק את האבטחה שלו, מוסיפים אותו כשרת ב־SSH.");
      return;
    }
    const st = stateOf(c);
    const acts = (c.state === "needs_action" ? ["auth", "probe"] : c.ok ? ["exec", "audit", "probe"] : ["probe", "auth"]);
    el("hSsh").innerHTML = `<div class="card"><h3><span>גישה ב־SSH</span><span class="pill ${st.cls}">${esc(st.he)}</span></h3>
      <div class="facts">${[["כתובת", c.host], ["משתמש", c.user], ["פורט", String(c.port || 22)], ["שם המארח", c.hostname || "—"],
        ["מערכת", c.os || "—"], ["עומס", shortLoad(c.load)]].map(([k, v]) => `<div><div class="k">${esc(k)}</div><div class="v" title="${esc(v)}">${esc(v)}</div></div>`).join("")}</div>
      ${c.reason ? alertBox(c.state === "needs_action" ? "warn" : "bad", esc(c.reason) + (c.action ? `<div class="small">${esc(c.action)}</div>` : "")) : ""}
      <div class="rowacts" style="margin-top:12px">${acts.map((name, i) => `<button type="button" class="btn sm ${i ? "ghost" : ""}" data-act="${name}" data-id="${esc(c.id)}" title="${esc(ACTS[name].tip)}">${esc(ACTS[name].he)}</button>`).join("")}</div></div>`;
  }

  window.addEventListener("resize", () => { const h = S.hd[T.where]; if (T.tab === "res" && h && h.ov) drawChart(h.ov.history || []); });
  return { open, close, tick, overview, summary, T };
})();
