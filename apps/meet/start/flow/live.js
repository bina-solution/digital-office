/* meet-flow, live: a meeting while it happens — its captions as they arrive, who is in, whether it records.
   Data: flow/<room>/live.json (meet-start, from prosody's captions door). No network calls but that one. */
(() => {
  const ROOM = window.FLOW_ROOM, $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const hms = (t) => { t = Math.max(0, Math.floor(t)); return `${Math.floor(t / 3600)}:${String(Math.floor(t % 3600 / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`; };
  const clock = (epoch) => new Date(epoch * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
  const HUES = ["sky", "lime", "olive", "plum"], hue = {};
  const hueOf = (name) => hue[name] || (hue[name] = HUES[Object.keys(hue).length % HUES.length]);
  let last = null, follow = true, timer = 0;

  // one paragraph per speaker until someone else speaks; a loudspeaker's echo (the same words from another
  // person within seconds) is dropped — as meet-start does when it files the captions in Plane
  function turns(segs) {
    const kept = [];
    for (const s of segs.filter((x) => String(x.text || "").trim()).sort((a, b) => (a.t || 0) - (b.t || 0))) {
      const w = new Set(String(s.text).split(/\s+/));
      if (w.size >= 4 && kept.slice(-6).some((k) => k.name !== s.name && Math.abs((k.t || 0) - (s.t || 0)) < 8
          && [...w].filter((x) => k.words.has(x)).length >= 0.7 * w.size)) continue;
      kept.push({ ...s, words: w });
    }
    const out = [];
    for (const s of kept) {
      const p = out[out.length - 1];
      if (p && p.name === s.name && (s.t || 0) - p.end < 90) { p.text += " " + String(s.text).trim(); p.end = s.t || p.end; p.final = p.final && !!s.final; }
      else out.push({ t: s.t || 0, end: s.t || 0, name: s.name || "משתתף", text: String(s.text).trim(), final: !!s.final });
    }
    return out;
  }

  function draw(d) {
    last = d;
    const live = !!d.live;
    document.title = `${ROOM} · ${live ? "בשידור חי" : "הסתיימה"} · meet-flow`;
    $("state").textContent = live ? "● בשידור חי" : "הפגישה הסתיימה";
    $("state").className = "state " + (live ? "on" : "off");
    const now = d.now || {};
    // who is in the room now (live), or who was there (ended); a person whose speech is not captioned is said so
    const names = live && (now.names || []).length ? now.names : (d.attendees || []).map((a) => a.name).filter(Boolean);
    const quiet = new Set(d.uncaptioned || []);
    $("people").innerHTML = names.map((n) => `<span class="chip${quiet.has(n) ? " quiet" : ""}" title="${quiet.has(n) ? "בלי כתוביות" : ""}">${esc(n)}</span>`).join("");
    const REC = { on: ["● מוקלטת", "ok"], pending: ["מתחילה להקליט…", "wait"], off: ["לא מוקלטת", "bad"], none: ["לא מוקלטת", "bad"] };
    const [recText, recKind] = live ? (REC[now.recording] || REC.none) : (d.sessions && d.sessions.length ? ["הוקלטה", "ok"] : ["לא הוקלטה", "bad"]);
    $("rec").textContent = recText; $("rec").className = "rec " + recKind;
    const ts = turns(d.segments || []);
    $("count").textContent = `${(d.words || 0).toLocaleString("he-IL")} מילים בכתוביות · ${ts.length} קטעים`;
    const box = $("lines"), atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.innerHTML = ts.length ? ts.map((x) => `<article class="it"><header><b style="color:var(--${hueOf(x.name)}-d)">${esc(x.name)}</b>`
      + `<span class="tm">${d.started ? hms(x.t - d.started) : ""} · ${clock(x.t)}</span>${x.final ? "" : '<span class="wip">…</span>'}</header>`
      + `<p>${esc(x.text)}</p></article>`).join("") : '<p class="empty">עוד אין כתוביות. כל משתתף שמדבר עם כתוביות פעילות יופיע כאן (בדרך כלל באיחור של כדקה).</p>';
    if (follow && atEnd || follow && !box.dataset.once) { box.scrollTop = box.scrollHeight; box.dataset.once = 1; }
    if (!live) {
      $("after").hidden = false;
    }
  }

  function tick() {
    if (last && last.started) $("dur").textContent = hms((last.live ? Date.now() / 1000 : (last.ended || last.started)) - last.started);
  }

  async function poll() {
    try {
      const r = await fetch(`flow/${encodeURIComponent(ROOM)}/live.json`, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        if (d.flow) { location.reload(); return; }        // the processed timeline is ready: the same address shows it
        draw(d);
        $("err").hidden = true;
      } else { $("err").hidden = false; $("err").textContent = `לא הצלחתי לקרוא את הפגישה (${r.status}). מנסה שוב…`; }
    } catch (e) { $("err").hidden = false; $("err").textContent = "אין חיבור לשרת. מנסה שוב…"; }
    clearTimeout(timer);
    timer = setTimeout(poll, last && !last.live ? 30000 : 3000);
  }

  $("lines").addEventListener("scroll", () => { const b = $("lines"); follow = b.scrollHeight - b.scrollTop - b.clientHeight < 40; $("jump").hidden = follow; });
  $("jump").onclick = () => { const b = $("lines"); b.scrollTop = b.scrollHeight; follow = true; $("jump").hidden = true; };
  $("title").textContent = ROOM;
  $("join").href = window.FLOW_MEET ? `${window.FLOW_MEET}/${encodeURIComponent(ROOM)}` : "#";
  setInterval(tick, 1000);
  poll();
})();
