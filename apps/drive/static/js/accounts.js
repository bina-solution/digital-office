/* accounts.js — every drive of the office in ONE app (DGO-1390). A drive is a connection: a profile of the
   office's own storage, a Google account (signed in with Google), a Google service account. The side lists
   them all, and choosing one shows its files. The screen sends that drive with every call and the address
   names it (`?drive=`, absent for the office's default), so looking at a Google account never moves what
   the office's agents and automations work on — that default is an act of its own («ברירת המחדל של
   הסוכנים», POST connections/select). «חיבור חשבון» connects another one, a step at a time: the provider,
   the way, its details, a real check, then it opens. «ניהול פרופילים» is the office storage's identities. */
(function () {
  "use strict";
  const { html, hooks, state, set, L, ic, api, tell, ask, copyText } = F;

  const LOCAL = "drive_local", GOOGLE = "drive_google_oauth", SA = "drive_google_service_account";
  const kindOf = (c) => (!c ? "" : c.protocol === LOCAL ? "local" : c.protocol === SA ? "sa" : c.protocol === GOOGLE ? "google" : "other");
  const KIND = {
    local:  { icon: "drive", he: "אחסון הלשכה", en: "Office storage" },
    google: { icon: "cloud", he: "Google Drive", en: "Google Drive" },
    sa:     { icon: "cloud", he: "Google Drive · חשבון שירות", en: "Google Drive · service account" },
    other:  { icon: "drive", he: "כונן", en: "Drive" },
  };
  const kindHe = (c) => { const k = KIND[kindOf(c)] || KIND.other; return L(k.he, k.en); };
  /* a drive is called what a person knows it by: a profile by its name, an account by its address */
  const nameOf = (c) => (!c ? "" : kindOf(c) === "local" ? (c.label || c.profile_id || c.id) : (c.account_hint || c.label || c.id));
  const enc = encodeURIComponent;

  async function load() {
    try {
      const d = await api("connections");
      set({ drives: { list: d.connections || [], active: d.active || null, acting: d.acting_profile || null, loaded: true, error: "" } });
    } catch (e) {
      set({ drives: { ...state.drives, loaded: true, error: e.message } });
    }
  }
  const currentId = () => state.route.drive || state.drives.active || "";
  const current = () => state.drives.list.find((c) => c.id === currentId()) || null;
  const isDefault = (c) => !!c && c.id === state.drives.active;
  const isAdmin = () => !!(state.drives.acting && state.drives.acting.is_admin);

  /* open a drive at its home: the address names it unless it is the office's default */
  function open(c) {
    const drive = isDefault(c) ? "" : c.id;
    set({ drawer: false });
    if ((state.route.drive || "") === drive) return;
    set({ folders: [], storage: null, connection: null, sel: [], details: false });
    F.go({ view: "home", drive });
  }

  /* ── one drive's actions (its ⋮ in the side) ────────────────────────────── */
  function actions(c) {
    const out = [{ icon: KIND[kindOf(c)].icon, label: L("פתיחה", "Open"), run: () => open(c) },
      { icon: "refresh", label: L("בדיקת החיבור", "Check the connection"), run: () => probe(c) }];
    if (!isDefault(c)) out.push({ icon: "bot", label: L("ברירת המחדל של הסוכנים", "Make it the agents' default"), run: () => makeDefault(c) });
    if (kindOf(c) === "local" && isAdmin()) out.push({ sep: true }, { icon: "users", label: L("ניהול פרופילים", "Manage profiles"), run: () => set({ dialog: { type: "profiles" } }) });
    if (kindOf(c) !== "local") out.push({ sep: true }, { icon: "trash", label: L("ניתוק החשבון", "Disconnect the account"), danger: true, run: () => remove(c) });
    return out;
  }
  async function probe(c) {
    try {
      const r = await api("connections/" + enc(c.id) + "/probe");
      if (r.ok) tell(L("החיבור תקין · ", "The connection works · ") + nameOf(c));
      else tell(r.reason || L("החיבור אינו עובד", "The connection does not work"), "bad");
    } catch (e) { tell(e.message, "bad"); }
  }
  async function makeDefault(c) {
    const was = state.drives.list.find((x) => x.id === state.drives.active);
    if (!(await ask({ title: L("ברירת המחדל של הסוכנים?", "The agents' default?"), ok: L("הגדרה", "Set"),
      body: L("סוכן, אוטומציה או פקודה שלא ציינו כונן יעבדו מול הכונן הזה. מה שמוצג בחלון הזה לא משתנה.",
              "An agent, an automation or a command that names no drive will work on this one. This window stays as it is."),
      facts: [[L("כונן", "Drive"), nameOf(c) + " · " + kindHe(c)], ...(was ? [[L("עד עכשיו", "Until now"), nameOf(was)]] : [])],
      run: () => api("connections/select", { body: { id: c.id } }) }))) return;
    const shown = currentId();
    await load();
    // the window keeps showing what it showed: «no drive in the address» now means the new default
    F.go({ ...state.route, drive: shown === state.drives.active ? "" : shown }, { replace: true });
    tell(L("ברירת המחדל של הסוכנים: ", "The agents' default: ") + nameOf(c));
  }
  async function remove(c) {
    if (!(await ask({ danger: true, title: L(`לנתק את «${nameOf(c)}»?`, `Disconnect «${nameOf(c)}»?`), ok: L("ניתוק", "Disconnect"),
      body: L("הקבצים בחשבון עצמו לא נמחקים — רק החיבור של הלשכה אליו מוסר. אפשר לחבר אותו שוב בכל רגע.",
              "Nothing is deleted from the account itself — only the office's connection to it. It can be connected again at any time."),
      facts: [[L("כונן", "Drive"), kindHe(c)], [L("חשבון", "Account"), nameOf(c)]],
      run: () => api("connections/" + enc(c.id), { method: "DELETE" }) }))) return;
    if (currentId() === c.id) F.go({ view: "home", drive: "" });
    await load();
    tell(L("החשבון נותק", "Disconnected"));
  }

  /* ── the side's section: every drive, then «חיבור חשבון» ────────────────── */
  function Section() {
    const ds = F.useStore((s) => s.drives);
    const cur = F.useStore((s) => s.route.drive) || ds.active;
    return html`<div class="nav-h">${L("כוננים", "Drives")}</div>
      ${ds.list.map((c) => html`<div key=${c.id} class=${"nav-i drv" + (c.id === cur ? " on" : "") + (c.status === "needs_action" ? " warn" : "")} data-drive=${kindOf(c)}>
        <button class="drv-pick" onClick=${() => open(c)} aria-current=${c.id === cur ? "true" : null}
          title=${[nameOf(c), kindHe(c), isDefault(c) ? L("ברירת המחדל של הסוכנים", "The agents' default") : "", c.reason || ""].filter(Boolean).join(" · ")}>
          ${ic(c.status === "needs_action" ? "alert" : KIND[kindOf(c)].icon)}
          <span class="lbl"><bdi class="drv-n" dir="auto">${nameOf(c)}</bdi><span class="drv-k">${kindHe(c)}</span></span>
          ${isDefault(c) && html`<span class="drv-def" aria-label=${L("ברירת המחדל של הסוכנים", "The agents' default")}>${ic("bot", "sm")}</span>`}</button>
        <button class="drv-more" title=${L("פעולות על הכונן: בדיקה, ברירת מחדל, ניתוק", "Drive actions: check, default, disconnect")}
          onClick=${(e) => F.ui.openMenu(actions(c), e, nameOf(c))}>${ic("more", "sm")}</button>
      </div>`)}
      ${ds.loaded && !ds.list.length && html`<div class="nav-i muted static" title=${ds.error || ""}>${ic("alert", "sm")}<span class="lbl">${ds.error ? L("רשימת הכוננים לא נטענה", "The drives did not load") : L("אין כוננים מחוברים", "No drives connected")}</span></div>`}
      <button class="nav-i drv-add" data-place="connect-google" title=${L("הקבצים שלכם ב־Google Drive, כאן בלשכה — בהתחברות עם Google או בשיתוף תיקייה", "Your Google Drive files, here in the office — by signing in with Google or by sharing a folder")}
        onClick=${() => { set({ drawer: false }); set({ dialog: { type: "connect", provider: "google_drive" } }); }}>${ic("cloud")}<span class="lbl">${L("חיבור Google Drive", "Connect Google Drive")}</span></button>
      <button class="nav-i drv-add" data-place="connect" title=${L("חיבור Google Drive או פרופיל של אחסון הלשכה", "Connect Google Drive or an office storage profile")}
        onClick=${() => { set({ drawer: false }); set({ dialog: { type: "connect" } }); }}>${ic("plus")}<span class="lbl">${L("חיבור חשבון", "Connect an account")}</span></button>`;
  }

  /* ── «חיבור חשבון»: provider → way → details → check ────────────────────── */
  const STEPS = [["ספק", "Provider"], ["אופן החיבור", "How"], ["פרטים", "Details"], ["בדיקה", "Check"]];
  const Steps = ({ at }) => html`<ol class="steps" aria-label=${L("שלבי החיבור", "Steps")}>${STEPS.map((s, i) => html`
    <li key=${i} class=${i === at ? "on" : i < at ? "done" : ""} aria-current=${i === at ? "step" : null}>
      <span class="n">${i < at ? ic("check", "sm") : i + 1}</span><span class="t">${L(s[0], s[1])}</span></li>`)}</ol>`;
  /* a sentence that carries an address: the address is one left-to-right token, never split by the line's Hebrew */
  const said = (t) => (typeof t !== "string" ? t : t.split(/(https?:\/\/[^\s]+)/).map((s, i) => (i % 2 ? html`<bdi class="mono" dir="ltr">${s}</bdi>` : s)));
  const Callout = ({ kind, icon, title, children }) => html`<div class=${"callout " + kind} role=${kind === "bad" ? "alert" : "status"}>
    ${ic(icon || (kind === "ok" ? "ok" : kind === "bad" ? "alert" : "info"))}<div><b>${title}</b>${children && html`<div class="sub">${said(children)}</div>`}</div></div>`;
  const PICON = { "hard-drive": "drive", server: "drive", cloud: "cloud", mail: "mail" };
  /* where a refused sign-in is fixed, under its sentence: the page the credential plane names (DGO-1634) */
  const helpLink = (url) => /^https:\/\//.test(url || "") && html`<a class="cw-link" href=${url} target="_blank" rel="noopener">
    ${ic("external", "sm")}${L("למסך מזהי ההתחברות ב־Google Cloud", "Google Cloud's credentials page")}</a>`;

  /* a provider people reach in ONE screen («חיבור Google Drive»): an outside one that has a sign-in way —
     its ways side by side, the sign-in first and the shared address beside it */
  const quick = (p) => !!p && !p.private && (p.auth_methods || []).some((m) => m.start_url);

  function ConnectDialog() {
    const d = F.useStore((s) => s.dialog);
    const drives = F.useStore((s) => s.drives);
    const on = !!d && d.type === "connect";
    const [st, setSt] = hooks.useState({ step: "loading" });
    const live = hooks.useRef({});
    const stop = () => { const w = live.current; if (w.timer) clearInterval(w.timer); if (w.onMsg) removeEventListener("message", w.onMsg); live.current = {}; };
    const want = on ? d.provider || "" : "";
    hooks.useEffect(() => {
      if (!on) return stop;
      setSt({ step: "loading" });
      api("providers").then((r) => {
        const provs = r.providers || [], p = want && provs.find((x) => x.id === want);
        if (want && !p) return setSt({ step: "error", provs, error: L("Google Drive אינו זמין בלשכה הזו — המנוע שלו אינו פועל.", "Google Drive is not available in this office — its engine is not running.") });
        setSt(p ? { step: quick(p) ? "quick" : "method", prov: p, provs } : { step: "provider", provs });
      }).catch((e) => setSt({ step: "error", error: e.message }));
      return stop;
    }, [on, want]);
    if (!on) return null;
    const close = () => { stop(); set({ dialog: null }); };
    const go = (patch) => setSt((s) => ({ ...s, ...patch }));
    const provs = st.provs || [];

    function pickProvider(p) {
      const ms = p.auth_methods || [];
      if (quick(p)) return go({ step: "quick", prov: p, waiting: false, error: "", share: null });
      if (ms.length === 1) return pickMethod(p, ms[0]);
      go({ step: "method", prov: p });
    }
    function pickMethod(p, m) {
      if (m.protocol === LOCAL) return go({ step: "local", prov: p, meth: m });
      if (m.start_url) return go({ step: "oauth", prov: p, meth: m, waiting: false, error: "" });
      go({ step: "form", prov: p, meth: m, values: {}, error: "" });
    }
    /* where «חזרה» goes from a way: the provider's one screen when it has one, else its list of ways */
    const backOf = (p) => (quick(p) ? "quick" : (p.auth_methods || []).length > 1 ? "method" : "provider");

    /* «שיתוף תיקייה עם הלשכה»: what the office's address at the provider was given — the folders and files
       at its top (a shared folder IS the top of such a drive). Asked when the person says they shared. */
    async function checkShare(acct) {
      go({ share: { busy: true } });
      try {
        const [fo, fi] = await Promise.all([api("api/folders", { drive: acct.id }), api("api/files?folder=", { drive: acct.id })]);
        const top = (fo.folders || []).filter((f) => !f.parent).map((f) => ({ name: f.name, folder: true }))
          .concat((fi.files || []).map((f) => ({ name: f.name })));
        go({ share: { checked: true, found: top } });
      } catch (e) { go({ share: { checked: true, found: [], error: e.message } }); }
    }

    /* The provider's window: opened by the click itself (a window opened later is a blocked pop-up), then
       sent to the address the office's credential plane signed — or closed, when the provider would refuse
       it. It comes back to this app's return page (the method's own: …/start → …/return), which says so
       here (a message) — and the list is asked too, in case the window could not say it. */
    function startOauth(meth) {
      stop();
      const m = meth || st.meth;
      go({ meth: m });
      const before = new Set(state.drives.list.map((c) => c.id));
      const ret = new URL(String(m.start_url).replace(/\/start$/, "/return"), document.baseURI).href;
      const w = window.open("", "dgo-google", "popup,width=520,height=720");
      go({ waiting: true, error: "", help: "", blocked: false });
      api(m.start_url + "?check=1&ret=" + enc(ret)).then((r) => {
        // the consent is this browser's (DGO-1418): the return page — this origin — hands this back to finish it.
        // One slot per consent (its state), so a second one at once — the mail's, another tab — never takes this one.
        try {
          for (let i = localStorage.length - 1; i >= 0; i--) {   // an abandoned consent's slot goes once its state expired
            const k = localStorage.key(i) || "";
            if (k.indexOf("dgo-oauth-bind:") !== 0) continue;
            try {
              const p = (k.slice(15).split(".")[1] || "").replace(/-/g, "+").replace(/_/g, "/");
              const t = JSON.parse(atob(p + "===".slice(0, (4 - p.length % 4) % 4))).t;
              if (!(t * 1000 > Date.now())) localStorage.removeItem(k);
            } catch (e) { localStorage.removeItem(k); }
          }
          if (r.bind) localStorage.setItem("dgo-oauth-bind:" + (new URL(r.authorize_url, location.href).searchParams.get("state") || ""), r.bind);
        } catch (e) { /* the return page says it then */ }
        if (w && !w.closed) w.location.href = r.authorize_url; else go({ blocked: r.authorize_url });
        const finish = async (made) => {
          stop();
          await load();
          const fresh = state.drives.list.find((c) => (made || []).some((x) => x.id === c.id) && c.protocol !== LOCAL)
            || state.drives.list.find((c) => !before.has(c.id) && c.protocol === m.protocol);
          if (fresh) verify(fresh, st.prov); else go({ waiting: false, error: L("החשבון לא נמצא ברשימה אחרי האישור", "The account is not in the list after the consent") });
        };
        const onMsg = (e) => {
          if (e.origin !== location.origin || !e.data || e.data.type !== "dgo:oauth") return;
          if (e.data.ok) finish(e.data.made); else { stop(); go({ waiting: false, error: e.data.error || L("החשבון לא חובר", "Not connected") }); }
        };
        addEventListener("message", onMsg);
        let tries = 0;
        const timer = setInterval(async () => {
          tries += 1;
          try {
            const c = await api("connections");
            if ((c.connections || []).some((x) => !before.has(x.id) && x.protocol === m.protocol)) return finish([]);
          } catch (e) { /* the next tick asks again */ }
          if (tries > 100) { stop(); go({ waiting: false, error: L("לא התקבל אישור מ־Google בתוך חמש דקות", "No consent came back from Google within five minutes") }); }
        }, 3000);
        live.current = { timer, onMsg };
      // a refusal names where it is fixed (connections' help_url: Google Cloud's credentials page, DGO-1634)
      }).catch((e) => { if (w && !w.closed) w.close(); go({ waiting: false, error: e.message, help: (e.body && e.body.help_url) || "" }); });
    }

    async function submitForm(e) {
      e.preventDefault();
      const m = st.meth, fields = m.fields || (m.needs || []).map((n) => ({ name: n, label: n }));
      const secret = {};
      for (const f of fields) secret[f.name] = String((st.values || {})[f.name] || "").trim();
      if (Object.values(secret).some((v) => !v)) return go({ error: L("יש למלא את כל השדות", "Fill in every field") });
      go({ busy: true, error: "" });
      try {
        const r = await api("connections", { body: { protocol: m.protocol, label: st.prov.name, secret } });
        await load();
        verify(state.drives.list.find((c) => c.id === r.id) || { id: r.id, protocol: m.protocol, label: st.prov.name }, st.prov);
      } catch (err) { go({ busy: false, error: err.message }); }
    }
    function readFile(name, file) {
      if (!file) return;
      const rd = new FileReader();
      rd.onload = () => go({ values: { ...(st.values || {}), [name]: String(rd.result || "") }, error: "" });
      rd.onerror = () => go({ error: L("הקובץ לא נקרא", "The file could not be read") });
      rd.readAsText(file);
    }

    /* the check is the same probe /readyz runs: a connection is verified, never just "added" */
    async function verify(conn, prov) {
      setSt((s) => ({ ...s, step: "verify", conn, prov: prov || s.prov, result: null }));
      let r;
      try { r = await api("connections/" + enc(conn.id) + "/probe"); } catch (e) { r = { ok: false, reason: e.message }; }
      setSt((s) => ({ ...s, step: "verify", conn: { ...conn, account_hint: r.account_hint || conn.account_hint }, result: r }));
    }
    async function dropFailed() {
      try { await api("connections/" + enc(st.conn.id), { method: "DELETE" }); } catch (e) { tell(e.message, "bad"); return; }
      await load();
      go({ step: "provider", conn: null, result: null });
    }

    const at = { provider: 0, method: 1, oauth: 2, form: 2, local: 2, verify: 3 }[st.step];
    let body = null, foot = null;
    if (st.step === "loading") body = html`<div class="cw-wait">${ic("clock")}<span>${L("טוען ספקים…", "Loading providers…")}</span></div>`;
    else if (st.step === "error") {
      body = html`<${Callout} kind="bad" title=${L("רשימת הספקים לא נטענה", "The providers did not load")}>${st.error}</${Callout}>`;
      foot = html`<button class="btn sm" onClick=${close}>${L("סגירה", "Close")}</button>`;
    } else if (st.step === "provider") {
      body = html`<div class="cw-cards">${provs.map((p, i) => html`<button key=${i} class="cw-card" data-provider=${p.id} onClick=${() => pickProvider(p)}>
          <span class="pic">${ic(PICON[p.icon] || "drive")}</span>
          <span class="pt">${p.name}${p.builtin && html`<span class="tag">${L("מובנה", "Built in")}</span>`}</span>
          <span class="pd">${p.description || ""}</span></button>`)}</div>`;
      foot = html`<button class="btn sm ghost" onClick=${close}>${L("ביטול", "Cancel")}</button>`;
    } else if (st.step === "method") {
      body = html`<div class="cw-lead">${L("חיבור ", "Connecting ")}${st.prov.name}${L(" — כל אפשרות אומרת מה היא דורשת ומה תאפשר.", " — each way says what it needs and what it allows.")}</div>
        <div class="cw-cards one">${(st.prov.auth_methods || []).map((m, i) => html`<button key=${i} class="cw-card" data-method=${m.id} onClick=${() => pickMethod(st.prov, m)}>
          <span class="pt">${m.label}${m.recommended && html`<span class="tag">${L("מומלץ", "Recommended")}</span>`}</span>
          <span class="pd">${m.can || ""}</span></button>`)}</div>`;
      foot = html`<button class="btn sm" onClick=${() => go({ step: "provider" })}>${L("חזרה", "Back")}</button>`;
    } else if (st.step === "oauth") {
      const m = st.meth;
      body = html`<div class="cw-lead">${m.explain || ""}</div>
        <div class="cw-note">${ic("lock", "sm")}<span>${L("הסיסמה נכתבת רק בחלון של Google — היא לעולם אינה עוברת דרך הלשכה.", "The password is typed only in Google's window — it never passes through the office.")}</span></div>
        ${st.waiting && html`<div class="cw-wait" role="status"><span class="spin">${ic("clock")}</span><span>${L("ממתין לאישור בחלון של Google… אם החלון נסגר — לא נוצר חיבור.", "Waiting for the consent in Google's window… if it was closed, nothing was connected.")}</span></div>`}
        ${st.blocked && html`<${Callout} kind="warn" icon="external" title=${L("הדפדפן חסם את החלון", "The browser blocked the window")}>
          <a class="cw-link" href=${st.blocked} target="_blank" rel="opener">${L("פתיחת החלון של Google", "Open Google's window")}</a></${Callout}>`}
        ${st.error && html`<${Callout} kind="bad" title=${L("ההתחברות ל־Google לא נפתחה", "Google's sign-in did not open")}>${said(st.error)}${helpLink(st.help)}</${Callout}>`}`;
      foot = html`<button class="btn sm primary" onClick=${() => startOauth(st.meth)} title=${L("נפתח חלון של Google", "Opens Google's window")}>${ic("external", "sm")}${st.waiting ? L("פתיחה מחדש", "Open again") : L("התחברות עם Google", "Sign in with Google")}</button>
        <button class="btn sm" onClick=${() => { stop(); go({ step: backOf(st.prov), waiting: false, error: "" }); }}>${L("חזרה", "Back")}</button>`;
    } else if (st.step === "form") {
      const m = st.meth, fields = m.fields || (m.needs || []).map((n) => ({ name: n, label: n }));
      body = html`<form id="cwForm" class="cw-form" onSubmit=${submitForm}>
        ${m.explain && html`<div class="cw-lead">${m.explain}</div>`}
        ${fields.map((f) => html`<label key=${f.name} class="cw-field"><span class="fl">${f.label || f.name}
            ${f.type === "textarea" && html`<span class="cw-file">${ic("upload", "sm")}${L("בחירת קובץ JSON", "Choose a JSON file")}
              <input type="file" accept=".json,application/json,text/plain" onChange=${(e) => readFile(f.name, e.target.files && e.target.files[0])} /></span>`}</span>
          ${f.type === "textarea"
            ? html`<textarea dir="ltr" rows="7" spellcheck="false" value=${(st.values || {})[f.name] || ""} onInput=${(e) => go({ values: { ...(st.values || {}), [f.name]: e.target.value } })}></textarea>`
            : html`<input dir="ltr" autocomplete="off" type=${/password/i.test(f.name) ? "password" : "text"} value=${(st.values || {})[f.name] || ""} onInput=${(e) => go({ values: { ...(st.values || {}), [f.name]: e.target.value } })} />`}
        </label>`)}
        ${m.help_url && html`<a class="cw-link" href=${m.help_url} target="_blank" rel="noopener">${ic("external", "sm")}${L("מהיכן משיגים את זה?", "Where does this come from?")}</a>`}
        ${st.error && html`<${Callout} kind="bad" title=${L("החיבור לא נוצר", "Not connected")}>${st.error}</${Callout}>`}
      </form>`;
      foot = html`<button class="btn sm primary" type="submit" form="cwForm" disabled=${st.busy}>${st.busy ? L("בודק…", "Checking…") : L("המשך לבדיקה", "Continue to the check")}</button>
        <button class="btn sm" onClick=${() => go({ step: backOf(st.prov), error: "" })}>${L("חזרה", "Back")}</button>`;
    } else if (st.step === "quick") {
      /* «חיבור Google Drive» in one screen: sign in (all of the account's Drive), or share a folder with the
         office's own address (works without the sign-in) — each says what it needs and what it gives */
      const p = st.prov, ms = p.auth_methods || [];
      const so = ms.find((m) => m.start_url), sh = ms.find((m) => m.share);
      const addr = sh && drives.list.find((c) => c.protocol === sh.protocol && c.status !== "needs_action" && c.account_hint);
      const sv = st.share || {}, found = sv.found || [];
      body = html`<div class="cw-lead">${p.description || ""}</div>
        ${so && html`<section class="cw-way" data-way="signin" aria-label=${so.label}>
          <div class="cw-way-h"><b>${so.label}</b>${so.recommended && html`<span class="tag">${L("מומלץ", "Recommended")}</span>`}</div>
          <div class="cw-way-d">${so.can || ""}</div>
          <div class="cw-note">${ic("lock", "sm")}<span>${L("הסיסמה נכתבת רק בחלון של Google — היא לעולם אינה עוברת דרך הלשכה.", "The password is typed only in Google's window — it never passes through the office.")}</span></div>
          ${st.waiting && html`<div class="cw-wait" role="status"><span class="spin">${ic("clock")}</span><span>${L("ממתין לאישור בחלון של Google… אם החלון נסגר — לא נוצר חיבור.", "Waiting for the consent in Google's window… if it was closed, nothing was connected.")}</span></div>`}
          ${st.blocked && html`<${Callout} kind="warn" icon="external" title=${L("הדפדפן חסם את החלון", "The browser blocked the window")}>
            <a class="cw-link" href=${st.blocked} target="_blank" rel="opener">${L("פתיחת החלון של Google", "Open Google's window")}</a></${Callout}>`}
          ${st.error && html`<${Callout} kind="bad" title=${L("ההתחברות ל־Google לא נפתחה", "Google's sign-in did not open")}>${said(st.error)}${helpLink(st.help)}</${Callout}>
            ${sh && html`<div class="cw-way-d">${ic("arrow-down", "sm")} ${L("בינתיים אפשר בדרך השנייה, כאן למטה — היא עובדת בלי ההתחברות.", "Meanwhile the second way, below, works without the sign-in.")}</div>`}`}
          <div class="cw-way-a"><button class="btn sm primary" data-act="signin" onClick=${() => startOauth(so)}>${ic("external", "sm")}${st.waiting ? L("פתיחה מחדש", "Open again") : so.label}</button></div>
        </section>`}
        ${sh && html`<section class="cw-way" data-way="share" aria-label=${L("שיתוף תיקייה עם הלשכה", "Share a folder with the office")}>
          <div class="cw-way-h"><b>${L("שיתוף תיקייה עם הלשכה", "Share a folder with the office")}</b></div>
          <div class="cw-way-d">${sh.can || ""}</div>
          ${addr ? html`<ol class="cw-steps">
              <li><span>${L("מעתיקים את הכתובת של הלשכה ב־Google:", "Copy the office's address at Google:")}</span>
                <div class="copyline"><code title=${addr.account_hint}>${addr.account_hint}</code><button class="icbtn" data-act="copy-address" title=${L("העתקה", "Copy")}
                  onClick=${() => copyText(addr.account_hint, L("הכתובת הועתקה", "The address was copied"))}>${ic("copy", "sm")}</button></div></li>
              <li><span>${L("ב־Google Drive: לחיצה ימנית על התיקייה › «שיתוף» › מדביקים את הכתובת › «עורך» › «שליחה».", "In Google Drive: right-click the folder › Share › paste the address › Editor › Send.")}</span>
                <a class="cw-link" href="https://drive.google.com/drive/my-drive" target="_blank" rel="noopener">${ic("external", "sm")}${L("פתיחת Google Drive", "Open Google Drive")}</a></li>
              <li><span>${L("חוזרים לכאן ובודקים מה הגיע.", "Come back here and check what arrived.")}</span></li></ol>
            ${sv.checked && !sv.error && (found.length
              ? html`<${Callout} kind="ok" title=${found.length === 1 ? L("הגיע פריט אחד ששותף עם הלשכה", "One shared item arrived")
                  : L(`הגיעו ${found.length} פריטים ששותפו עם הלשכה`, `${found.length} shared items arrived`)}>${found.slice(0, 4).map((f) => f.name).join(" · ")}${found.length > 4 ? " …" : ""}</${Callout}>`
              : html`<${Callout} kind="warn" title=${L("עוד לא הגיע דבר", "Nothing has arrived yet")}>${L("אחרי השיתוף ב־Google Drive זה לוקח עד דקה. בודקים שוב בעוד רגע.", "After sharing in Google Drive it takes up to a minute. Check again in a moment.")}</${Callout}>`)}
            ${sv.error && html`<${Callout} kind="bad" title=${L("הבדיקה לא הצליחה", "The check failed")}>${sv.error}</${Callout}>`}
            <div class="cw-way-a"><button class="btn sm" data-act="check-share" disabled=${sv.busy} onClick=${() => checkShare(addr)}>${ic("refresh", "sm")}${sv.busy ? L("בודק…", "Checking…") : L("בדיקה — מה שותף?", "Check — what was shared?")}</button>
              ${found.length > 0 && html`<button class="btn sm primary" data-act="open-shared" onClick=${() => { close(); open(addr); }}>${ic("cloud", "sm")}${L("פתיחת מה ששותף", "Open what was shared")}</button>`}</div>`
          : html`<div class="cw-way-d">${L("לשם כך ללשכה צריכה כתובת משלה ב־Google (חשבון שירות). מוסיפים אותה פעם אחת — מי שמנהל את הלשכה, עם קובץ ה־JSON שלה.", "For this the office needs an address of its own at Google (a service account). It is added once — by whoever runs the office, with its JSON file.")}</div>
            <div class="cw-way-a"><button class="btn sm" data-act="add-address" onClick=${() => pickMethod(p, sh)}>${ic("plus", "sm")}${L("הוספת הכתובת של הלשכה", "Add the office's address")}</button></div>`}
        </section>`}`;
      foot = html`<button class="btn sm" onClick=${() => { stop(); go({ step: "provider", waiting: false, error: "", share: null }); }}>${L("חשבון מסוג אחר", "Another kind of account")}</button>
        <button class="btn sm ghost" onClick=${close}>${L("סגירה", "Close")}</button>`;
    } else if (st.step === "local") {
      const locals = drives.list.filter((c) => c.protocol === LOCAL);
      body = html`${Callout({ kind: "ok", title: L("האחסון של הלשכה מובנה בה", "The office's storage is built in"), children: L("לכל פרופיל דרייב משלו — בחרו איזה לפתוח.", "Each profile has its own drive — choose which to open.") })}
        <div class="cw-cards one">${locals.map((c) => html`<button key=${c.id} class="cw-card" onClick=${() => { close(); open(c); }}
          title=${c.profile_id ? L("פרופיל ", "Profile ") + c.profile_id : undefined}>
          <span class="pt"><bdi>${nameOf(c)}</bdi>${c.is_admin && html`<span class="tag">${L("מנהל", "Admin")}</span>`}${isDefault(c) && html`<span class="tag">${L("ברירת מחדל", "Default")}</span>`}</span></button>`)}</div>`;
      foot = html`${isAdmin() && html`<button class="btn sm" onClick=${() => set({ dialog: { type: "profiles" } })}>${ic("users", "sm")}${L("ניהול פרופילים", "Manage profiles")}</button>`}
        <button class="btn sm" onClick=${() => go({ step: "provider" })}>${L("חזרה", "Back")}</button>`;
    } else if (st.step === "verify") {
      const r = st.result, c = st.conn;
      if (!r) body = html`<div class="cw-wait" role="status"><span class="spin">${ic("clock")}</span><span>${L("בודק את החיבור מול ", "Checking the connection with ")}${(st.prov && st.prov.name) || kindHe(c)}…</span></div>`;
      else if (r.ok) {
        body = html`<${Callout} kind="ok" title=${L("החשבון מחובר", "Connected")}>${L("הבדיקה עברה — הכונן זמין בלשכה, בחלון, לסוכנים ובשורת הפקודה.", "The check passed — the drive is in the office: here, for the agents and on the command line.")}</${Callout}>
          <dl class="cw-facts"><dt>${L("חשבון", "Account")}</dt><dd><bdi>${nameOf(c)}</bdi></dd><dt>${L("סוג", "Kind")}</dt><dd>${kindHe(c)}</dd></dl>`;
        // an address others share folders with (a service account): its next step is the sharing itself
        const shares = st.prov && quick(st.prov) && (st.prov.auth_methods || []).some((m) => m.share && m.protocol === c.protocol);
        foot = shares
          ? html`<button class="btn sm primary" onClick=${() => go({ step: "quick", share: null })}>${ic("users", "sm")}${L("להמשך: שיתוף תיקייה עם הכתובת", "Next: share a folder with the address")}</button>
            <button class="btn sm" onClick=${close}>${L("סגירה", "Close")}</button>`
          : html`<button class="btn sm primary" onClick=${() => { const fresh = state.drives.list.find((x) => x.id === c.id) || c; close(); open(fresh); }}>${ic(KIND[kindOf(c)].icon, "sm")}${L("פתיחת הכונן", "Open the drive")}</button>
          <button class="btn sm" onClick=${close}>${L("סגירה", "Close")}</button>`;
      } else {
        body = html`<${Callout} kind="bad" title=${L("החיבור נוצר אך אינו עובד", "Connected, but it does not work")}>${r.reason || L("הבדיקה נכשלה", "The check failed")}</${Callout}>`;
        foot = html`<button class="btn sm primary" onClick=${() => verify(c, st.prov)}>${ic("refresh", "sm")}${L("בדיקה חוזרת", "Check again")}</button>
          <button class="btn sm" onClick=${close}>${L("סגירה", "Close")}</button>
          <button class="btn sm danger" onClick=${dropFailed} title=${L("הקבצים בחשבון לא נמחקים", "Nothing in the account is deleted")}>${ic("trash", "sm")}${L("הסרת החיבור", "Remove the connection")}</button>`;
      }
    }
    const title = st.prov && st.step !== "provider" ? L("חיבור ", "Connect ") + st.prov.name : L("חיבור חשבון", "Connect an account");
    return html`<div class="dlg-scrim" onMouseDown=${(e) => e.target === e.currentTarget && close()}>
      <div class="dlg cw" role="dialog" aria-modal="true" aria-label=${title} onKeyDown=${(e) => e.key === "Escape" && close()}>
        <div class="dlg-h"><b>${title}</b><button class="icbtn" title=${L("סגירה", "Close")} onClick=${close}>${ic("x")}</button></div>
        ${at != null && html`<${Steps} at=${at} />`}
        <div class="dlg-b cw-b">${body}</div>
        ${foot && html`<div class="dlg-f">${foot}</div>`}
      </div></div>`;
  }

  /* ── «ניהול פרופילים»: the office storage's identities (its admin only) ─── */
  function ProfilesDialog() {
    const d = F.useStore((s) => s.dialog);
    const on = !!d && d.type === "profiles";
    const [st, setSt] = hooks.useState({ view: "list", loading: true });
    const reload = () => api("engine/profiles").then((r) => setSt({ view: "list", list: r.profiles || [], me: r.acting_as || null }))
      .catch((e) => setSt({ view: "list", error: e.message, list: [] }));
    hooks.useEffect(() => { if (on) { setSt({ view: "list", loading: true }); reload(); } }, [on]);
    if (!on) return null;
    const close = () => set({ dialog: null });
    const base = (id) => "engine/profiles/" + enc(id);
    const patch = (id, body) => api(base(id), { method: "PATCH", body });
    async function act(p, what) {
      if (what === "open") {
        const c = state.drives.list.find((x) => x.id === p.connection_id);
        if (!c) return tell(L("לפרופיל אין חיבור", "This profile has no connection"), "warn");
        close(); return open(c);
      }
      if (what === "rename") {
        const name = await ask({ title: L("שם לתצוגה", "Display name"), ok: L("שמירה", "Save"), input: { label: L("השם שיוצג לפרופיל", "The profile's name"), value: p.display_name, dir: "auto" } });
        if (!name || name === p.display_name) return;
        try { await patch(p.id, { display_name: String(name).trim() }); } catch (e) { return tell(e.message, "bad"); }
      }
      if (what === "suspend") {
        try { await patch(p.id, { status: p.status === "active" ? "suspended" : "active" }); } catch (e) { return tell(e.message, "bad"); }
      }
      if (what === "key") {
        let got = null;
        if (!(await ask({ danger: true, title: L(`מפתח חדש ל«${p.display_name}»?`, `A new key for «${p.display_name}»?`), ok: L("החלפה", "Replace"),
          body: L("כל מי שמחזיק את המפתח הישן יפסיק לעבוד מיד.", "Whoever holds the old key stops working at once."),
          run: async () => { got = await api(base(p.id) + "/key", { body: {} }); } }))) return;
        await load(); return setSt((s) => ({ ...s, view: "key", key: got, title: L("המפתח הוחלף", "The key was replaced") }));
      }
      if (what === "rm") {
        if (!(await ask({ danger: true, title: L(`להסיר את הגישה של «${p.display_name}»?`, `Remove «${p.display_name}»'s access?`), ok: L("הסרה", "Remove"),
          body: L("הקבצים לא נמחקים: הם נשארים שייכים למזהה הזה ויופיעו שוב אם ייווצר פרופיל באותו מזהה.", "Nothing is deleted: the files stay with this id and come back if a profile with the same id is created."),
          facts: [[L("פרופיל", "Profile"), p.display_name], [L("מזהה", "Id"), p.id]],
          run: () => api(base(p.id), { method: "DELETE" }) }))) return;
        tell(L("הגישה הוסרה", "Access removed"));
      }
      await load(); reload();
    }
    async function create(e) {
      e.preventDefault();
      const id = String(st.id || "").trim().toLowerCase(), display_name = String(st.name || "").trim() || id;
      if (!/^[a-z0-9][a-z0-9_-]{0,31}$/.test(id)) return setSt((s) => ({ ...s, error: L("מזהה באנגלית, ספרות, _ או - (עד 32 תווים)", "An id of English letters, digits, _ or - (up to 32)") }));
      setSt((s) => ({ ...s, busy: true, error: "" }));
      try {
        const r = await api("engine/profiles", { body: { id, display_name, admin: !!st.admin } });
        await load();
        setSt((s) => ({ ...s, view: "key", key: r, title: L("הפרופיל נוצר", "The profile was created"), busy: false }));
      } catch (err) { setSt((s) => ({ ...s, busy: false, error: err.message })); }
    }
    let body, foot;
    if (st.view === "key") {
      const key = (st.key && st.key.key) || "";
      body = html`${Callout({ kind: "ok", title: st.title, children: L("המפתח מוצג פעם אחת בלבד — הלשכה שומרת רק את טביעתו. שמרו אותו עכשיו.", "The key is shown once — the office keeps only its fingerprint. Save it now.") })}
        ${st.key && st.key.warning && Callout({ kind: "warn", title: st.key.warning })}
        <div class="cw-key mono" dir="ltr">${key}</div>`;
      foot = html`<button class="btn sm primary" onClick=${() => copyText(key, L("המפתח הועתק", "Key copied"))}>${ic("copy", "sm")}${L("העתקה", "Copy")}</button>
        <button class="btn sm" onClick=${() => { setSt({ view: "list", loading: true }); reload(); }}>${L("סיום", "Done")}</button>`;
    } else if (st.view === "new") {
      body = html`<form id="pfForm" class="cw-form" onSubmit=${create}>
        <label class="cw-field"><span class="fl">${L("מזהה (באנגלית, בלי רווחים)", "Id (English, no spaces)")}</span>
          <input dir="ltr" autocomplete="off" placeholder="user3" value=${st.id || ""} onInput=${(e) => setSt((s) => ({ ...s, id: e.target.value }))} /></label>
        <label class="cw-field"><span class="fl">${L("שם לתצוגה", "Display name")}</span>
          <input dir="auto" value=${st.name || ""} onInput=${(e) => setSt((s) => ({ ...s, name: e.target.value }))} /></label>
        <label class="cw-check"><input type="checkbox" checked=${!!st.admin} onChange=${(e) => setSt((s) => ({ ...s, admin: e.target.checked }))} /><span>${L("הרשאות מנהל", "Admin rights")}</span></label>
        <div class="cw-lead">${L("הפרופיל והחיבור שלו נוצרים יחד, עם דרייב ריק משלו.", "The profile and its connection are made together, with an empty drive of its own.")}</div>
        ${st.error && Callout({ kind: "bad", title: L("הפרופיל לא נוצר", "Not created"), children: st.error })}</form>`;
      foot = html`<button class="btn sm primary" type="submit" form="pfForm" disabled=${st.busy}>${st.busy ? L("יוצר…", "Creating…") : L("יצירה", "Create")}</button>
        <button class="btn sm" onClick=${() => setSt((s) => ({ ...s, view: "list", error: "" }))}>${L("חזרה", "Back")}</button>`;
    } else {
      const list = st.list || [];
      body = st.loading ? html`<div class="cw-wait">${ic("clock")}<span>${L("טוען…", "Loading…")}</span></div>`
        : st.error ? Callout({ kind: "bad", title: L("אין הרשאה לנהל פרופילים", "No permission to manage profiles"), children: st.error })
        : html`<div class="pf-list">${list.map((p) => html`<div key=${p.id} class="pf-row">
            <span class="pf-ic">${ic("user")}</span>
            <span class="pf-n"><bdi>${p.display_name}</bdi>
              ${p.is_admin && html`<span class="tag">${L("מנהל", "Admin")}</span>`}
              ${p.status !== "active" && html`<span class="tag warn">${L("מושעה", "Suspended")}</span>`}
              ${p.id === st.me && html`<span class="tag">${L("זה אתה", "You")}</span>`}
              <span class="pf-id mono" title=${p.connection_id || ""}>${p.id}</span></span>
            <button class="icbtn" title=${L("פעולות על הפרופיל", "Profile actions")} onClick=${(e) => F.ui.openMenu([
              { icon: "drive", label: L("פתיחת הדרייב שלו", "Open its drive"), disabled: !p.connection_id, run: () => act(p, "open") },
              { icon: "edit", label: L("שינוי שם", "Rename"), run: () => act(p, "rename") },
              { icon: "key", label: L("מפתח חדש", "A new key"), run: () => act(p, "key") },
              { icon: "lock", label: p.status === "active" ? L("השעיה", "Suspend") : L("החזרה לפעילות", "Reactivate"), run: () => act(p, "suspend") },
              { sep: true },
              { icon: "trash", label: L("הסרת הגישה", "Remove access"), danger: true, run: () => act(p, "rm") },
            ], e, p.display_name)}>${ic("more")}</button></div>`)}</div>
          <div class="cw-lead">${L("הסרת פרופיל מסירה את הגישה בלבד — הקבצים שלו נשמרים.", "Removing a profile removes its access only — its files stay.")}</div>`;
      foot = html`<button class="btn sm primary" onClick=${() => setSt((s) => ({ ...s, view: "new", id: "", name: "", admin: false, error: "" }))}>${ic("plus", "sm")}${L("פרופיל חדש", "New profile")}</button>
        <button class="btn sm" onClick=${close}>${L("סגירה", "Close")}</button>`;
    }
    return html`<div class="dlg-scrim" onMouseDown=${(e) => e.target === e.currentTarget && close()}>
      <div class="dlg cw" role="dialog" aria-modal="true" aria-label=${L("ניהול פרופילים", "Manage profiles")} onKeyDown=${(e) => e.key === "Escape" && close()}>
        <div class="dlg-h"><b>${L("ניהול פרופילים", "Manage profiles")}</b><button class="icbtn" title=${L("סגירה", "Close")} onClick=${close}>${ic("x")}</button></div>
        <div class="dlg-b cw-b">${body}</div><div class="dlg-f">${foot}</div></div></div>`;
  }

  const Dialogs = () => html`<${ConnectDialog} /><${ProfilesDialog} />`;

  F.drives = { load, open, current, currentId, isDefault, kindOf, kindHe, nameOf, actions, Section, Dialogs };
})();
