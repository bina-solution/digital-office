/* data.js — what the screens show and what they do: loading each view (one request in flight per
   view; a slow answer for a folder the person already left is dropped, not drawn), the live
   refresh (files an app or an agent adds appear by themselves), and every action on files and
   folders. The screens call these; none of them talks to the server on its own. */
(function () {
  "use strict";
  const { state, set, api, L, tell, ask, go, copyText, contentUrl } = F;
  let ctl = null;

  const folderById = () => { const m = {}; state.folders.forEach((f) => (m[f.id] = f)); return m; };
  const folderPath = (id) => {
    const m = folderById(), out = [], seen = new Set();
    while (id && m[id] && !seen.has(id)) { seen.add(id); out.unshift(m[id]); id = m[id].parent || ""; }
    return out;
  };
  const childFolders = (id) => state.folders.filter((f) => (f.parent || "") === (id || ""));

  async function loadFolders() {
    const d = await api("api/folders");
    set({ folders: (d.folders || []).map((f) => ({ ...f, kind: "folder" })), connection: d.connection || null });
  }
  async function loadStorage() { try { set({ storage: await api("api/storage") }); } catch (e) { /* the meter waits */ } }
  async function loadOpenWith() {
    try { const d = await api("extensions?slot=open-with"); set({ openWith: d.extensions || [] }); }
    catch (e) { set({ openWith: [] }); }
  }

  const MEDIA = { photos: "visual", videos: "video", music: "audio" };
  const keyOf = (r) => [r.view, r.id || "", r.q || ""].join("␟");

  async function loadList(force) {
    const r = state.route, key = keyOf(r);
    if (r.view === "open") return;
    if (!force && state.list.key === key && !state.list.error && !state.list.loading) return;
    if (ctl) ctl.abort();
    ctl = new AbortController();
    const signal = ctl.signal;
    if (state.list.key !== key) set({ list: { key, files: [], folders: [], loading: true, error: "" }, sel: [], anchor: null });
    try {
      let d;
      if (r.view === "folder") {
        d = await api("api/files?folder=" + encodeURIComponent(r.id || ""), { signal });
        d.folders = childFolders(r.id);
      } else if (r.view === "recent" || r.view === "starred") {
        d = await api("api/files?view=" + r.view, { signal });
        d.folders = r.view === "starred" ? state.folders.filter((f) => f.starred) : [];
      } else if (r.view === "trash") {
        d = await api("api/files?trash=1", { signal });
        d.folders = (d.folders || []).map((f) => ({ ...f, kind: "folder" }));
      } else if (r.view === "search") {
        d = (r.q || "").trim().length > 1 ? await api("api/search?q=" + encodeURIComponent(r.q.trim()), { signal }) : { files: [], folders: [] };
        d.folders = (d.folders || []).map((f) => ({ ...f, kind: "folder" }));
      } else if (MEDIA[r.view]) {
        d = await api("api/media?kind=" + MEDIA[r.view], { signal });
        d.folders = [];
      } else {
        d = await api("api/files?view=added&limit=30", { signal });
        d.folders = childFolders("");
      }
      if (signal.aborted) return;
      set({ list: { key, files: d.files || [], folders: d.folders || [], loading: false, error: "" } });
    } catch (e) {
      if (e.name === "AbortError") return;
      set({ list: { key, files: state.list.key === key ? state.list.files : [], folders: state.list.key === key ? state.list.folders : [], loading: false, error: e.message } });
    }
  }

  async function refresh() {
    try { await loadFolders(); } catch (e) { /* the list says why */ }
    await loadList(true);
    loadStorage();
  }

  /* live: a cheap question every 15 s while the page is in view — "did anything change?" */
  let rev = null;
  async function watch() {
    if (document.visibilityState === "visible" && !state.viewer) {
      try {
        const d = await api("api/changes");
        if (rev !== null && d.rev !== rev) refresh();
        rev = d.rev;
        F.sawBuild(d.build);
      } catch (e) { /* offline for a moment; the next tick asks again */ }
    }
    setTimeout(watch, 15000);
  }
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && rev !== null) refresh(); });

  /* ── actions ─────────────────────────────────────────────────────────────── */
  const ids = (items) => items.map((i) => i.id);
  const names = (items) => items.length === 1 ? "«" + items[0].name + "»" : L(items.length + " פריטים", items.length + " items");
  async function run(fn, ok) {
    try { const out = await fn(); if (ok) tell(ok); await refresh(); return out; }
    catch (e) { tell(e.message, "bad"); }
  }

  async function newFolder(parent) {
    const name = await ask({ title: L("תיקייה חדשה", "New folder"), input: { value: L("תיקייה ללא שם", "Untitled folder") },
      ok: L("יצירה", "Create") });
    if (name == null || !String(name).trim()) return;
    return run(() => api("api/folders", { body: { name: String(name).trim(), parent: parent || "" } }), L("התיקייה נוצרה", "Folder created"));
  }
  async function rename(it) {
    const name = await ask({ title: L("שינוי שם", "Rename"), input: { value: it.name }, ok: L("שמירה", "Save") });
    if (name == null || !String(name).trim() || name === it.name) return;
    return run(() => api("api/rename", { body: { id: it.id, name: String(name).trim() } }), L("השם עודכן", "Renamed"));
  }
  const move = (items, to) => run(() => api("api/move", { body: { ids: ids(items), to: to || "" } }),
    L(names(items) + " הועבר", names(items) + " moved"));
  const trash = (items) => run(() => api("api/trash", { body: { ids: ids(items) } }),
    L(names(items) + " הועבר לאשפה", names(items) + " moved to trash"));
  const restore = (items) => run(() => api("api/trash", { body: { ids: ids(items), restore: true } }),
    L(names(items) + " שוחזר", names(items) + " restored"));
  async function destroy(items) {
    const size = items.reduce((s, i) => s + (Number(i.size) || 0), 0);
    if (!(await ask({ title: L("למחוק לצמיתות?", "Delete forever?"), danger: true, ok: L("מחיקה לצמיתות", "Delete forever"),
      body: L("אי אפשר לשחזר אחרי המחיקה.", "This cannot be undone."),
      facts: [[L("מה", "What"), names(items)], [L("גודל", "Size"), F.fmtSize(size)]] }))) return;
    return run(() => api("api/delete", { body: { ids: ids(items) } }), L("נמחק לצמיתות", "Deleted forever"));
  }
  async function emptyTrash() {
    const all = [...state.list.folders, ...state.list.files];
    if (all.length) return destroy(all);
  }
  const star = (items, on) => run(() => api("api/star", { body: { ids: ids(items), starred: on } }));
  function download(it) {
    const a = document.createElement("a");
    a.href = contentUrl(it.id, true); a.download = it.name; document.body.appendChild(a); a.click(); a.remove();
  }
  const copyLink = (it) => copyText(it.link, L("הקישור הועתק — מי שמקבל אותו יכול להוריד את הקובץ", "Link copied — anyone who has it can download the file"));
  async function copyPath(it) {
    try {
      const p = it.kind === "folder" ? (await api("api/folder/" + encodeURIComponent(it.id) + "/path")).path
                                     : (await api("api/file/" + encodeURIComponent(it.id))).file.path;
      copyText(p, L("הנתיב הועתק — כך סוכן מוצא את הקובץ: ", "Path copied — this is how an agent finds it: ") + p);
    } catch (e) { tell(e.message, "bad"); }
  }

  F.data = { loadFolders, loadStorage, loadOpenWith, loadList, refresh, watch, folderById, folderPath, childFolders,
    newFolder, rename, move, trash, restore, destroy, emptyTrash, star, download, copyLink, copyPath };
})();
