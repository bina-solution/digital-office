/**
 * The chat service's abstract API — routes only. One process, every backend.
 *
 * Each request resolves its backend from the SELECTED connection (adapters.resolveActive) rather
 * than from an env var decided at process start. That is the whole point of the layer: selecting a
 * connection changes what an op does, so the UI can offer local chat, WhatsApp and Telegram through
 * one surface exactly as Drive and Mail do.
 *
 * Every op accepts an optional `connection_id` (query param on GET, body field on POST) to override
 * the active pointer for that ONE call — the same per-call override mail exposes, which is what lets
 * a bot answer on the connection a message arrived on rather than on whatever is currently selected.
 *
 * Route paths are the ones the chat client already calls (it was ported from the simulation, whose
 * mock backend defined them): /api/accounts, /api/conversations, /api/conversation/:id, …
 */
const adapters = require('./adapters');
const cc = require('./connections_client');
const bots = require('../bots/chat_bot');
const { ProfileStore } = require('./engine/profiles');
const { makeAuth, keyFrom } = require('./engine/auth');
const engineRoutes = require('./engine/routes');
// Memory storage: an attachment's bytes go straight to the engine's object store, so a temp
// file on this container's disk would only be something to clean up. 50MB matches the relay's
// own Blossom cap — refusing here is a clearer error than a 413 from the engine.
const multer = require('multer');
const memUpload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 50 * 1024 * 1024 } });

/** Backends return a payload, or {payload, status}. One place turns either into a response, so an
 *  op's status code is the BACKEND's decision and nothing in the routing layer can reshape it. */
function reply(res, r) {
  if (r && typeof r === 'object' && 'status' in r && 'payload' in r) return res.status(r.status).json(r.payload);
  return res.json(r);
}

/** A connection that cannot be resolved is a CONFIG fault, not a chat fault: say which connection
 *  and why, so the UI can render an actionable state chip rather than a 500.
 *  `connectionId` is the one that FAILED, which is not always the active one. */
function onAdapterError(res, e, fallbackCid) {
  if (e instanceof adapters.AdapterError) {
    return res.status(e.status).json({ error: e.message, connection_id: e.connectionId || fallbackCid || null });
  }
  console.error('chatapi:', e);
  return res.status(500).json({ error: String((e && e.message) || e) });
}

/**
 * WHICH CONNECTION THIS REQUEST IS ABOUT — and there must be exactly ONE answer to that.
 *
 * `req.actorConnection` comes from withActor, which has already weighed the credential, the named
 * connection and the binding, and has already refused the combinations that are impersonation. Ops
 * routes read THAT rather than re-deriving it, because the second derivation is where they diverge:
 * measured against the live stack, withActor resolved a request carrying user2's key as user2 while
 * this line — seeing no explicit connection_id and no binding — independently fell back to the first
 * admin, and the op ran as the ADMIN. The credential was checked and then ignored.
 *
 * Routes that do not mount withActor (the switcher, probes, bot attachment) are unaffected: the
 * field is simply absent and the old order applies.
 */
const pick = (req) => req.actorConnection
  || (req.body && req.body.connection_id) || req.query.connection_id || null;

/**
 * The private engine's PROFILES, for the connection bar.
 *
 * They are real vault instances now, so connections_client could in principle list them from the
 * vault alone. They are read from OUR database instead because this service owns them: the bar then
 * still offers every identity — and the operator can still switch between them — while the vault is
 * unreachable. Losing the profile list to a credential-store blip would be a strictly worse failure
 * than the one it replaced.
 *
 * Best-effort: a database outage costs the private profiles, not the whole connection list.
 */
function register(app, isAuthenticated, opts = {}) {
  const sessionGuard = isAuthenticated || ((req, res, next) => next());
  /**
   * A CREDENTIAL IS AN AUTHENTICATION.
   *
   * The app's own guard is a browser session (basic auth on /api/*, or authentik at the edge). It
   * exists because a human opens this app in a tab. An automation holding a profile key has no
   * session and no business getting one — without this it is answered with a 401 or a 302 to
   * /login, which reads as "the service is down" to anything that is not a browser.
   *
   * The key is not TRUSTED here — it is only a reason to proceed. `withActor` then resolves it by
   * hash and refuses anything it does not recognise, so a bogus key buys a 401 rather than a way
   * past the session guard, and a real one can still only ever act as its own profile.
   */
  const guard = (req, res, next) => (keyFrom(req) ? next() : sessionGuard(req, res, next));

  // Injectable so the route tests can drive the rings without a Postgres, and so ops and routes
  // share ONE store — two would eventually disagree about who is an admin.
  const profiles = opts.profiles || new ProfileStore();
  adapters.useProfiles(profiles);                 // one store, so ops and routes cannot disagree
  const auth = makeAuth({ profiles, cc });
  const { withActor } = auth;

  async function localProfiles() {
    try { return await profiles.list(); } catch { return []; }
  }
  const allInstances = async () => cc.listInstances({ localProfiles: await localProfiles() });

  /** The connection a request means when it names none: the binding, else the first admin profile.
   *  `null` only on a deployment whose reconciler has not finished — which /readyz reports as
   *  "not ready" rather than by silently answering as somebody. */
  async function defaultConnection() {
    const bound = await cc.active();
    if (bound) return bound;
    const admin = await profiles.firstAdmin().catch(() => null);
    return (admin && admin.instance_id) || null;
  }

  // Profile administration. Registered FIRST so nothing below can shadow it.
  engineRoutes.register(app, sessionGuard, { profiles, cc, auth, adapters });

  // ── the op surface, derived from the dispatch table so it cannot drift ──────
  app.get('/api/manifest', guard, withActor, async (req, res) => {
    // `protocols` IS NOT A PROPERTY OF A CONNECTION. It is what this service can ever connect —
    // cc.PROTOCOLS, a constant — and it is the console's ONLY input for "connect a new account".
    //
    // This used to resolve the active connection FIRST and 502 the whole document when that failed,
    // which made one broken account a dead end for the entire service: measured live 2026-09-02, a
    // telegram connection saved without its token ("secret needs {token}") made GET /manifest throw,
    // the console got no `protocols`, the "חיבור חשבון חדש" button was never rendered, and the
    // operator could not reach the wizard to fix or replace the very connection that broke it. The
    // only way out was a database edit.
    //
    // So the static half always answers, and the connection-dependent half (`ops`, derived from the
    // resolved backend) degrades to null with the reason beside it. A caller that needs ops can see
    // it is absent and why; a caller that needs the catalogue is never blocked by someone else's
    // broken credential.
    let cid = null, ops = null, reason = null;
    try {
      const r = await adapters.resolveActive(pick(req));
      cid = r.cid; ops = adapters.opsFor(r.backend);
    } catch (e) {
      cid = (e && e.connectionId) || null;
      reason = String((e && e.message) || e);
    }
    res.json({ connection_id: cid, ops, protocols: cc.PROTOCOLS, ...(reason ? { ops_error: reason } : {}) });
  });

  app.get('/api/readyz', guard, withActor, async (req, res) => {
    // ready = the active connection resolves AND its probe passes. A connection that cannot be
    // RESOLVED is a different failure from one that resolves and is unhealthy, and it must never be
    // answered by probing some other account instead.
    let cid = null;
    try {
      const r = await adapters.resolveActive(pick(req));
      cid = r.cid;
      const p = (await r.backend.probe()) || {};
      res.status(p.ok === false ? 503 : 200).json({ ready: p.ok !== false, connection_id: cid, ...p });
    } catch (e) {
      if (e instanceof adapters.AdapterError) {
        return res.status(e.status).json({ ready: false, reason: e.message, connection_id: e.connectionId, active: await cc.active() });
      }
      onAdapterError(res, e, cid);
    }
  });

  // ── accounts (connections) ─────────────────────────────────────────────────
  app.get('/api/accounts', guard, async (req, res) => {
    try {
      const { instances, reachable, error } = await allInstances();
      const activeId = await defaultConnection();
      const accounts = instances.map((i) => ({
        id: i.id,
        provider: (i.protocol || '').replace(/^chat_/, '') || 'local',
        label: i.label || i.id,
        identity: i.identity || i.account_hint || '',
        color: i.color || 'var(--muted)',
        builtin: Boolean(i.builtin),
        status: i.status || 'ok',
        reason: i.reason || '',
        activeBot: bots.attachedTo(i.id),
      }));
      res.json({ accounts, active: activeId, reachable, ...(error ? { error } : {}) });
    } catch (e) { onAdapterError(res, e); }
  });

  app.post('/api/account/select', guard, async (req, res) => {
    try {
      const id = (req.body && req.body.id) || null;
      const { instances } = await allInstances();
      if (id && !instances.some((i) => i.id === id)) return res.status(404).json({ error: `unknown connection ${id}` });
      await cc.select(id);
      await adapters.forget(id);       // re-resolve on the next op rather than serving a stale backend
      res.json({ ok: true, active: id });
    } catch (e) { onAdapterError(res, e); }
  });

  app.post('/api/account/reconnect', guard, withActor, async (req, res) => {
    try {
      const { cid, backend } = await adapters.resolveActive(pick(req));
      if (typeof backend.reconnect !== 'function') {
        // Honest 501 beats pretending it worked: local chat has nothing to re-pair.
        return res.status(501).json({ ok: false, error: 'this connection has nothing to reconnect', connection_id: cid });
      }
      reply(res, await backend.reconnect());
    } catch (e) { onAdapterError(res, e); }
  });

  /**
   * The connect catalogue — provider-first, exactly the shape mail's GET /providers returns, so the
   * two apps stay ONE dialect and a shared switcher can render either.
   *
   * Derived from cc.PROTOCOLS rather than hand-listed: a protocol this service does not implement
   * cannot be offered, and one that is added joins the catalogue without a second edit. The sim's
   * mock invented five providers (messenger, whatsapp_cloud); offering those here would be a button
   * that can only ever fail, so the catalogue is the truth of what adapters/index.js `build()` knows.
   *
   * `direct` is the field the UI needs and mail's flow implies: whether a credential can be TYPED
   * (Telegram's bot token) or whether the pairing is a browser ceremony that lives in the console's
   * credential plane (WhatsApp's QR). Chat has no route that writes a secret it invented, so a
   * method with direct:false hands over instead of pretending.
   */
  const PROVIDERS = {
    chat_local: {
      id: 'local', name: 'צ׳אט מקומי', icon: 'message', builtin: true,
      description: 'שירות הצ׳אט הפנימי של הפלטפורמה — מובנה, פעיל תמיד, ואינו דורש חיבור.',
      auth_methods: [{
        id: 'builtin', label: 'מובנה — לא נדרש חיבור', protocol: 'chat_local',
        needs: [], recommended: true, direct: false,
        can: 'שיחות פנימיות, קבוצות, קבצים ואזכורים בתוך הפלטפורמה.',
      }],
    },
    chat_wa_baileys: {
      id: 'whatsapp', name: 'וואטסאפ · Baileys', icon: 'whatsapp',
      description: 'מספר וואטסאפ עסקי, מקושר בסריקת קוד QR ממכשירים מקושרים.',
      auth_methods: [{
        id: 'wa_qr', label: 'סריקת קוד QR', protocol: 'chat_wa_baileys',
        needs: [], recommended: true, direct: false,
        can: 'שליחה וקבלה במספר העסקי, קבוצות, מסמכים ותמונות.',
        // The QR is served by THIS service (/api/bot/qr) and proxied by the console's connections
        // screen with the chat-auth basic-auth (platform-base/connections/app.py::_wa_auth) — the
        // one place in the platform where a human pairs a credential.
        explain: 'הקישור נעשה במסך «חיבורים ומפתחות» של הלשכה: שם מוצג קוד ה-QR ונסרק מהטלפון.',
        start_url: '#/m/connections',
      }],
    },
    chat_tg_bot: {
      id: 'telegram', name: 'טלגרם · בוט', icon: 'telegram',
      description: 'בוט טלגרם רשמי עם Bot Token מ-BotFather.',
      auth_methods: [{
        id: 'tg_token', label: 'Bot Token', protocol: 'chat_tg_bot',
        needs: ['token'], recommended: true, direct: true,
        can: 'שליחה וקבלה של הודעות דרך בוט הטלגרם.',
        explain: 'פותחים שיחה עם BotFather בטלגרם, יוצרים בוט ומעתיקים את הטוקן שהוא מחזיר.',
        help_url: 'https://core.telegram.org/bots#botfather',
      }],
    },
  };

  // ONE handler on TWO paths: /api/chat-providers is what the chat client calls (the sim's mock
  // named it), /providers is what the console's connect wizard calls on every platform-service.v1
  // app. Same body, so the two surfaces cannot disagree about which providers exist.
  app.get(['/api/chat-providers', '/providers'], guard, (req, res) => {
    res.json({ providers: cc.PROTOCOLS.map((p) => PROVIDERS[p]).filter(Boolean) });
  });

  /**
   * Add a connection — mail's POST /connections, at the path the client already calls.
   *
   * The secret is FORWARDED, never invented: this service holds no credential of its own and the
   * vault is the single writer. A protocol whose pairing is a browser ceremony (WhatsApp's QR) has
   * no secret to forward, so it is refused HERE with the place that owns it named, rather than being
   * passed on to produce the vault's generic "a non-empty secret{} is required".
   */
  app.post('/api/account/add', guard, async (req, res) => {
    const b = req.body || {};
    const { protocol, label } = b;
    if (!protocol || !label) return res.status(400).json({ ok: false, error: 'protocol and label required' });
    if (!cc.PROTOCOLS.includes(protocol)) {
      return res.status(400).json({ ok: false, error: 'unsupported protocol', protocol, supported: cc.PROTOCOLS });
    }
    if (protocol === cc.LOCAL_PROTOCOL) {
      // An identity on the engine we RUN is created, not connected to — and creating it mints a
      // credential, which is a different act with a different ring. Naming the route that does it
      // beats a generic refusal: this is the one place an operator looks when the wizard says no.
      return res.status(400).json({
        ok: false, protocol,
        error: 'זהות במנוע הפנימי נוצרת במסך «פרופילים במנוע הפנימי», לא באשף החיבורים',
        route: 'POST /engine/profiles',
      });
    }
    const direct = ((PROVIDERS[protocol] || {}).auth_methods || []).some((m) => m.direct);
    const secret = b.secret || {};
    if (!direct && !Object.keys(secret).length) {
      return res.status(400).json({
        ok: false, protocol,
        error: 'החיבור הזה נוצר במסך «חיבורים ומפתחות» של הלשכה (סריקת QR), ולא מכאן',
      });
    }
    try {
      const r = await cc.createInstance(protocol, label, secret, b.account_hint);
      res.status(201).json({ ok: true, ...(r || {}) });
    } catch (e) {
      // status 0 is "the vault is unreachable", which a client cannot act on — say 502.
      if (e instanceof cc.ConnectionsError) return res.status(e.status || 502).json({ ok: false, error: e.message });
      onAdapterError(res, e);
    }
  });

  /**
   * Remove a connection — mail's DELETE /connections/:id.
   *
   * Three things have to happen together or the service lies about itself afterwards: the vault row
   * goes, a pointer left aimed at the dead id is CLEARED (otherwise every op answers 503 against an
   * account the operator believes they removed), and the cached backend is dropped — it holds live
   * sockets against a credential that no longer exists, and the id can be reused by a later instance.
   */
  app.delete('/api/account/:id', guard, async (req, res) => {
    const id = req.params.id;
    // A local instance is a PROFILE. Deleting it is DELETE /engine/profiles/<id>, which is
    // admin-ringed, keeps the person's history and drops the credential — none of which this route
    // does. It used to 404 into the vault for every `chat_local-*` id, which read as a broken button.
    const owned = await profiles.byInstance(id).catch(() => null);
    if (owned) {
      return res.status(400).json({
        ok: false, id, profile_id: owned.id,
        error: `«${owned.display_name}» הוא פרופיל במנוע הפנימי — הסרתו נעשית במסך הפרופילים`,
        route: `DELETE /engine/profiles/${owned.id}`,
      });
    }
    try {
      await cc.deleteInstance(id);
    } catch (e) {
      if (e instanceof cc.ConnectionsError) return res.status(e.status || 502).json({ ok: false, error: e.message, id });
      return onAdapterError(res, e, id);
    }
    if ((await cc.active()) === id) await cc.select(null);
    await adapters.forget(id);
    res.json({ ok: true, id });
  });

  /**
   * Verify ONE connection without selecting it — mail's GET /connections/:id/probe.
   *
   * The same probe /readyz runs, so what the connect flow shows and what n8n trusts cannot disagree.
   * Deliberately NOT `reply()`: a failing probe is a SUCCESSFUL answer to "is this one healthy", and
   * forwarding the backend's 503 here would make an operator's health check read as an outage of
   * this route.
   */
  app.get('/api/account/:id/probe', guard, async (req, res) => {
    const id = req.params.id;
    try {
      const { instances } = await allInstances();
      const inst = instances.filter((i) => i.id === id)[0];
      if (!inst) return res.status(404).json({ ok: false, error: `unknown connection ${id}`, id });
      const r = (await (await adapters.resolveActive(id)).backend.probe()) || {};
      const payload = ('payload' in r) ? r.payload : r;
      const ok = payload.ok !== false;
      res.json({
        ok, id, reason: ok ? '' : (payload.error || payload.reason || ''),
        identity: inst.identity || inst.account_hint || '', protocol: inst.protocol || '',
      });
    } catch (e) {
      if (e instanceof adapters.AdapterError) return res.json({ ok: false, reason: e.message, id });
      onAdapterError(res, e, id);
    }
  });

  // ── bots ───────────────────────────────────────────────────────────────────
  app.get('/api/bots', guard, (req, res) => res.json({ bots: bots.listBots() }));

  // Settings are per (connection, bot): the same bot on a public WhatsApp number and on internal local
  // chat is doing two different jobs. The connection therefore has to be part of every settings call,
  // and it defaults to the active one rather than to "whatever was saved last".
  const forConn = async (req) => (req.body && req.body.connection_id) || req.query.connection_id
    || await defaultConnection();

  app.get('/api/bots/:id/settings', guard, async (req, res) => {
    try {
      const schema = bots.settingsSchema(req.params.id);
      if (!bots.getBot(req.params.id)) return res.status(404).json({ error: `unknown bot ${req.params.id}` });
      const cid = await forConn(req);
      res.json({ bot: req.params.id, connection_id: cid, schema, settings: bots.getSettings(cid, req.params.id) });
    } catch (e) { onAdapterError(res, e); }
  });

  app.put('/api/bots/:id/settings', guard, async (req, res) => {
    try {
      const cid = await forConn(req);
      const values = (req.body && req.body.settings) || {};
      const r = bots.setSettings(cid, req.params.id, values);
      // 400, not 500: a rejected value is the operator's input being wrong, and the message names the
      // field so the UI can point at it rather than showing a generic failure.
      if (!r.ok) return res.status(400).json({ error: r.error, connection_id: cid });
      res.json({ ok: true, bot: req.params.id, connection_id: cid, settings: r.settings });
    } catch (e) { onAdapterError(res, e); }
  });

  /**
   * Reset settings to the bot's declared defaults — the half PUT cannot express.
   *
   * The store holds OVERRIDES only, so "back to default" is a DELETE of the key and not a PUT of the
   * current default value: writing the default back would pin it, and a bot that later changes its
   * own default would keep running the old one on every connection anyone had ever reset.
   *
   * `{keys:[...]}` resets those fields; no body resets the whole (connection, bot) pair.
   */
  app.delete('/api/bots/:id/settings', guard, async (req, res) => {
    try {
      const cid = await forConn(req);
      const keys = (req.body && req.body.keys) || null;
      const r = bots.clearSettings(cid, req.params.id, keys);
      if (!r.ok) return res.status(bots.getBot(req.params.id) ? 400 : 404).json({ error: r.error, connection_id: cid });
      res.json({ ok: true, bot: req.params.id, connection_id: cid, cleared: r.cleared, settings: r.settings });
    } catch (e) { onAdapterError(res, e); }
  });

  app.post('/api/account/bot', guard, async (req, res) => {
    try {
      const id = (req.body && req.body.id) || await defaultConnection();
      const bot = req.body && req.body.bot;
      const r = await bots.attach(id, bot);
      res.json({ ok: true, activeBot: r });
    } catch (e) { res.status(400).json({ ok: false, error: String(e.message || e) }); }
  });

  /**
   * Live updates over Server-Sent Events, so the client stops asking every 8 seconds.
   *
   * SSE and not a WebSocket: this is one-directional (the server tells the client something changed;
   * the client still SENDS over the normal POST routes), it is plain HTTP so it inherits the session
   * guard and the authentik forward-auth already in front of this app with no second auth path, and
   * it reconnects on its own — EventSource retries without a line of client code. A WebSocket would
   * buy bidirectionality this design does not use and cost a second protocol to secure.
   *
   * 501 where the backend cannot push, so the client knows to keep polling rather than sitting on a
   * stream that will never speak.
   */
  app.get('/api/events', guard, withActor, async (req, res) => {
    let cid = null;
    let unsubscribe = null;
    try {
      const r = await adapters.resolveActive(pick(req));
      cid = r.cid;
      if (typeof r.backend.subscribe !== 'function') {
        return res.status(501).json({ error: 'this connection cannot push events', connection_id: cid });
      }

      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        // traefik and any proxy in front will otherwise buffer the stream and deliver nothing until
        // it closes, which looks exactly like a backend that never sends.
        'X-Accel-Buffering': 'no',
      });
      res.write(`event: ready\ndata: ${JSON.stringify({ connection_id: cid })}\n\n`);

      const send = (payload) => {
        // A write to a closed socket throws; the close handler may not have run yet.
        try { res.write(`event: change\ndata: ${JSON.stringify(payload)}\n\n`); } catch { /* client gone */ }
      };
      unsubscribe = await r.backend.subscribe(send);

      // A comment line every 25s. Idle proxies drop a silent connection at 30-60s, and the client
      // would reconnect forever without ever being told why.
      const beat = setInterval(() => { try { res.write(': keep-alive\n\n'); } catch { /* gone */ } }, 25000);
      beat.unref?.();

      // Both events, not just `close`: `close` fires when the client disconnects, `error` when the
      // socket breaks. Missing either leaks a database LISTEN client per dropped browser tab, which
      // is invisible until the connection pool is exhausted hours later.
      const cleanup = () => {
        clearInterval(beat);
        const u = unsubscribe;
        unsubscribe = null;
        if (u) Promise.resolve(u()).catch(() => {});
      };
      req.on('close', cleanup);
      req.on('error', cleanup);
    } catch (e) {
      if (unsubscribe) { try { await unsubscribe(); } catch { /* nothing to undo */ } }
      if (res.headersSent) return res.end();
      onAdapterError(res, e, cid);
    }
  });

  // ── private chat engine: the address book ──────────────────────────────────
  //
  // PEOPLE, not identities. Creating a PROFILE — an identity this deployment can act AS, holding a
  // credential — is POST /engine/profiles (engine/routes.js), and it is a different act with a
  // different ring. What is left here is the contact list: someone to talk TO.
  //
  // The `operator` flag that used to live on this surface is gone. It was a boolean on a PERSON row
  // that granted the right to act as them, with no credential behind it — which is precisely the
  // impersonation this whole change removes. A person is now a profile or not by whether a row
  // exists in chat_profiles, and that row holds a key hash.
  //
  // Deliberately hard-bound to the private engine rather than to whatever connection is selected:
  // "add a contact" while a WhatsApp account is active must not quietly mean something else, and
  // must not silently do nothing either.
  const localBackend = async () => {
    const admin = await profiles.firstAdmin();
    if (!admin || !admin.instance_id) {
      throw new adapters.AdapterError('אין עדיין פרופיל מנהל עם חיבור במנוע הפנימי', 503, null);
    }
    const r = await adapters.resolveActive(admin.instance_id);
    return r.backend;
  };
  const engineOp = (name) => async (req, res, next) => {
    try {
      const backend = await localBackend();
      if (typeof backend[name] !== 'function') {
        return res.status(501).json({ error: `the private chat engine cannot ${name}` });
      }
      req.localBackend = backend;
      next();
    } catch (e) { onAdapterError(res, e, null); }
  };

  app.get('/api/engine/users', guard, withActor, auth.requireProfile, engineOp('listUsers'), async (req, res) => {
    try {
      const [all, list] = await Promise.all([
        req.localBackend.listUsers({ q: req.query.q || '', limit: req.query.limit }),
        profiles.list().catch(() => []),
      ]);
      // Which people are also identities. The admin screen most needs the row it can least infer.
      const byId = new Map(list.map((p) => [p.id, p]));
      const users = ((all && all.users) || []).map((u) => ({
        ...u, profile: byId.has(u.id), is_admin: Boolean(byId.get(u.id) && byId.get(u.id).is_admin),
      }));
      // listUsers excludes the acting identity, so the caller's own row is added back explicitly.
      const me = byId.get(req.actor.id);
      res.json({
        ok: true,
        users: [...(me ? [{ id: me.id, name: me.display_name, handle: '', profile: true, is_admin: me.is_admin, self: true }] : []), ...users],
      });
    } catch (e) { onAdapterError(res, e, null); }
  });

  app.post('/api/engine/users', guard, withActor, auth.requireAdmin, engineOp('createUser'), async (req, res) => {
    try {
      const b = req.body || {};
      const r = await req.localBackend.createUser({ id: b.id, name: b.name, handle: b.handle, color: b.color });
      if (r && r.ok === false) return res.status(400).json(r);
      res.json({ ...r, profile: false, hint: 'זהו איש קשר. כדי ליצור זהות שאפשר לפעול בשמה — POST /engine/profiles' });
    } catch (e) { onAdapterError(res, e, null); }
  });

  // ── starting a conversation ────────────────────────────────────────────────
  // Both ops are OPTIONAL (adapters.PROTOCOL_OPS). A backend that cannot enumerate its address book
  // answers 501 with the reason rather than an empty list, because "nobody to talk to" and "this
  // transport cannot tell you who you can talk to" are different facts and an empty array says the
  // first while meaning the second.
  app.get('/api/users', guard, withActor, async (req, res) => {
    try {
      const { cid, backend } = await adapters.resolveActive(pick(req));
      if (typeof backend.listUsers !== 'function') {
        return res.status(501).json({ error: 'this connection cannot list users', connection_id: cid });
      }
      reply(res, await backend.listUsers({ q: req.query.q || '', limit: req.query.limit }));
    } catch (e) { onAdapterError(res, e); }
  });

  app.post('/api/conversations', guard, withActor, async (req, res) => {
    try {
      const body = req.body || {};
      const { cid, backend } = await adapters.resolveActive(pick(req));

      // One route, two shapes, because the UI's "new chat" is one button.
      //
      // `user_id` decides, and it is checked FIRST because `name` is ambiguous: it is the GROUP's
      // name in one shape and the PEER's display name in the other. Treating any `name` as "group"
      // turned "open a chat with משה" into "create a group called משה" — a silent wrong-thing, since
      // both succeed and both return a conversation id.
      const peer = body.user_id || body.userId;
      const wantsGroup = !peer && Boolean(body.title || body.name);
      if (!peer && !wantsGroup) {
        return res.status(400).json({ error: 'need a user_id for a direct chat, or a title for a group', connection_id: cid });
      }
      const op = wantsGroup ? 'createGroup' : 'createDirect';
      if (typeof backend[op] !== 'function') {
        return res.status(501).json({ error: `this connection cannot ${op}`, connection_id: cid });
      }
      const r = wantsGroup
        ? await backend.createGroup({ name: body.title || body.name, members: body.members, tag: body.tag })
        : await backend.createDirect({ userId: peer, name: body.name, handle: body.handle });

      // A backend that says ok:false is reporting BAD INPUT (no name, self-DM), not a server fault.
      if (r && r.ok === false) return res.status(400).json({ ...r, connection_id: cid });
      res.json({ ...r, connection_id: cid });
    } catch (e) { onAdapterError(res, e); }
  });

  // ── conversations ──────────────────────────────────────────────────────────
  app.get('/api/conversations', guard, withActor, async (req, res) => {
    try {
      const { cid, backend } = await adapters.resolveActive(pick(req));
      const conversations = (await backend.listConversations()) || [];
      res.json({ account: cid, conversations });
    } catch (e) { onAdapterError(res, e); }
  });

  app.get('/api/conversation/:id', guard, withActor, async (req, res) => {
    try {
      const { backend } = await adapters.resolveActive(pick(req));
      const r = await backend.getConversation(req.params.id);
      if (!r) return res.status(404).json({ error: 'no conversation' });
      reply(res, r);
    } catch (e) { onAdapterError(res, e); }
  });

  app.post('/api/conversation/:id/send', guard, withActor, async (req, res) => {
    try {
      const text = ((req.body && req.body.text) || '').trim();
      if (!text) return res.status(400).json({ error: 'empty' });
      const { cid, backend } = await adapters.resolveActive(pick(req));
      const sent = await backend.sendMessage(req.params.id, { text, mentions: req.body.mentions, attachment: req.body.attachment });

      // NO bot reply here, and this is a deliberate divergence from the simulation.
      //
      // The sim's mock answers /send with a bot reply, because in a mock the operator typing IS the
      // only source of traffic and a demo needs something to come back. Reproducing that here would
      // mean the bot replies to what the OPERATOR types — talking to our own staff instead of to the
      // customer. Bots dispatch on INBOUND messages (bots.dispatch, driven by each transport's
      // receive path), which is where a real conversation actually needs answering.
      res.json({ message: (sent && sent.message) || sent });
    } catch (e) { onAdapterError(res, e); }
  });

  /**
   * Send a message WITH A FILE.
   *
   * One route rather than two (`uploadMedia` then `sendMessage`), because a staged blob that never
   * became a message is an orphan nobody owns, and the UI would have to clean it up on every failure
   * path. Here the upload and the send are one call: either the recipient has the file or nothing
   * happened.
   *
   * This did not exist. The backend has had `uploadMedia` throughout and the composer has had a
   * paperclip since the client was ported from the sim, but nothing connected them — the button had
   * no handler at all, so "attach a file" was a control that silently did nothing. Both halves are
   * wired now (the client half is in src/api/ui/chat.ejs).
   *
   * multer's memory storage on purpose: the bytes go straight to the engine's object store, so
   * writing them to this container's disk first would only add a temp file to clean up.
   */
  app.post('/api/conversation/:id/attach', guard, withActor, memUpload.single('file'), async (req, res) => {
    let cid = null;
    try {
      const r = await adapters.resolveActive(pick(req));
      cid = r.cid;
      if (typeof r.backend.uploadMedia !== 'function') {
        return res.status(501).json({ error: 'this connection cannot send files', connection_id: cid });
      }
      if (!req.file || !req.file.buffer || !req.file.buffer.length) {
        return res.status(400).json({ error: 'no file in the request', connection_id: cid });
      }
      // multer decodes the filename as latin1; the rest of this app already converts (see
      // src/api/controller.js), and a Hebrew filename is the common case here rather than the edge.
      const name = Buffer.from(String(req.file.originalname || 'file'), 'latin1').toString('utf8');
      const up = await r.backend.uploadMedia({
        fileName: name, mimeType: req.file.mimetype || null, buffer: req.file.buffer,
      });
      if (!up || !up.ok) return res.status(502).json({ error: (up && up.error) || 'upload failed', connection_id: cid });
      const sent = await r.backend.sendMessage(req.params.id, {
        text: String((req.body && req.body.text) || ''), attachment: up,
      });
      return reply(res, { ...sent, connection_id: cid });
    } catch (e) { return onAdapterError(res, e, cid); }
  });

  /**
   * Fetch an attachment's bytes, THROUGH this service.
   *
   * The browser must not go to the engine directly, for two reasons that both hold regardless of
   * engine: `http://chat-relay:3000` only resolves inside the docker network, and the blob is
   * authenticated with the PROFILE's own credential — which is exactly the thing a browser must
   * never hold. So the service fetches as the resolved profile and streams the result, which also
   * means a file is readable by precisely the identities that can read the conversation.
   */
  app.get('/api/media/:sha', guard, withActor, async (req, res) => {
    let cid = null;
    try {
      const r = await adapters.resolveActive(pick(req));
      cid = r.cid;
      if (typeof r.backend.downloadMedia !== 'function') {
        return res.status(501).json({ error: 'this connection cannot serve files', connection_id: cid });
      }
      const out = await r.backend.downloadMedia(req.params.sha);
      if (!out || !out.ok) return res.status(404).json({ error: (out && out.error) || 'not found', connection_id: cid });
      const name = String(req.query.name || out.name || 'file');
      res.setHeader('Content-Type', out.mime || 'application/octet-stream');
      // RFC 5987, because the common case here is a Hebrew filename and a bare filename= would
      // arrive as mojibake or be dropped entirely.
      res.setHeader('Content-Disposition',
        `attachment; filename*=UTF-8''${encodeURIComponent(name)}`);
      return res.end(out.buffer);
    } catch (e) { return onAdapterError(res, e, cid); }
  });

  app.post('/api/conversation/:id/read', guard, withActor, async (req, res) => {
    try {
      const { backend } = await adapters.resolveActive(pick(req));
      if (typeof backend.markRead !== 'function') return res.json({ ok: false, unsupported: true });
      reply(res, await backend.markRead(req.params.id));
    } catch (e) { onAdapterError(res, e); }
  });

  /**
   * Broadcast — the same text to many conversations, through the ADAPTER.
   *
   * This is the abstract successor to the dashboard's `/api/bot/broadcast`, and it is deliberately
   * not the same op. The legacy one fans out over the WhatsApp SUBSCRIBER table (src/data/subscribers)
   * — a WhatsApp-only concept with no meaning on Telegram or local chat — and n8n's "whatsapp api"
   * workflow calls it, so it stays. This one fans out over CONVERSATIONS, which every backend has.
   *
   * `to:'all'` must be typed. Defaulting an unqualified broadcast to "everyone" is the one mistake
   * here that cannot be taken back, so an empty request is a 400 rather than a mass send.
   *
   * Per-recipient results, never a single ok: a fan-out where four of nine failed is not a success
   * and is not a failure, and collapsing it to one boolean is how nobody finds out which five went.
   */
  app.post('/api/broadcast', guard, withActor, async (req, res) => {
    try {
      const b = req.body || {};
      const text = String(b.text || '').trim();
      if (!text) return res.status(400).json({ ok: false, error: 'empty' });
      const { cid, backend } = await adapters.resolveActive(pick(req));

      let ids = Array.isArray(b.conversation_ids) ? b.conversation_ids.filter(Boolean) : [];
      if (!ids.length) {
        if (b.to !== 'all') {
          return res.status(400).json({
            ok: false, connection_id: cid,
            error: 'נדרש conversation_ids[] או to:"all" — תפוצה לכולם חייבת להיאמר במפורש',
          });
        }
        ids = ((await backend.listConversations()) || []).map((c) => c.id);
      }
      if (!ids.length) return res.status(400).json({ ok: false, error: 'no conversations to send to', connection_id: cid });

      const results = [];
      for (const id of ids) {
        try {
          const sent = await backend.sendMessage(id, { text });
          const payload = (sent && typeof sent === 'object' && 'payload' in sent) ? sent.payload : sent;
          // A backend that answers {ok:false} with a 200 has NOT sent it — the body is the verdict,
          // which is the same rule the client applies to a single send.
          const ok = !(payload && payload.ok === false);
          results.push({ id, ok, ...(ok ? {} : { error: (payload && payload.error) || 'send failed' }) });
        } catch (e) {
          results.push({ id, ok: false, error: String((e && e.message) || e) });
        }
      }
      const sent = results.filter((r) => r.ok).length;
      // 207: some went and some did not, and the caller has to look. 200 would be a lie for a
      // partial fan-out and 500 would be a lie for one bad recipient out of forty.
      res.status(sent === results.length ? 200 : 207)
        .json({ ok: sent === results.length, connection_id: cid, sent, failed: results.length - sent, results });
    } catch (e) { onAdapterError(res, e, pick(req)); }
  });

  /**
   * CHAT EXPORT — the conversation history of the ACTIVE (or named) connection, as a file.
   *
   * Backend-agnostic on purpose. The dashboard's export was `/api/wa-archive/*`, which reads the
   * WhatsApp SQLite archive directly and therefore cannot answer for local chat or Telegram at all.
   * This one uses nothing but the CANONICAL ops (listConversations + getConversation), so it works
   * on every backend that satisfies the contract, and a backend that grows later gets export for
   * free. Those legacy routes stay — they project the archive's own stats/search, which this does
   * not replace.
   *
   *   ?format=json|csv   ?conversation_id=<one thread>   ?limit=<conversations>
   *
   * The contract carries AGE (`mins`), not timestamps, so the absolute time is derived here from this
   * process's clock and named `at_approx` — resolution is one minute and it says so, rather than
   * printing a precise-looking timestamp the service never actually had.
   */
  const CSV_COLS = ['conversation_id', 'conversation', 'handle', 'group', 'message_id',
    'direction', 'sender', 'text', 'at_approx', 'minutes_ago', 'status'];

  /** RFC4180 + a leading apostrophe on anything a spreadsheet would execute. An exported chat is
   *  attacker-influenced text by definition — a customer can type `=cmd|…` into WhatsApp. */
  function csvCell(v) {
    let s = v === null || v === undefined ? '' : String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  app.get('/api/export/conversations', guard, withActor, async (req, res) => {
    try {
      const { cid, backend } = await adapters.resolveActive(pick(req));
      const format = String(req.query.format || 'json').toLowerCase();
      if (format !== 'json' && format !== 'csv') {
        return res.status(400).json({ error: `unsupported format ${format}`, supported: ['json', 'csv'] });
      }
      const one = req.query.conversation_id ? String(req.query.conversation_id) : null;
      const limit = Math.max(1, Math.min(500, Number(req.query.limit) || 200));

      let heads;
      if (one) {
        heads = [{ id: one }];
      } else {
        heads = ((await backend.listConversations()) || []).slice(0, limit);
      }

      const now = Date.now();
      const at = (mins) => new Date(now - (Number(mins) || 0) * 60000).toISOString();
      const out = [];
      for (const h of heads) {
        const r = await backend.getConversation(h.id);
        const conv = (r && typeof r === 'object' && 'payload' in r) ? r.payload : r;
        if (!conv) {
          if (one) return res.status(404).json({ error: 'no conversation', connection_id: cid });
          continue;                              // it vanished between the list and the read
        }
        const c = conv.contact || {};
        out.push({
          id: conv.id || h.id,
          name: c.name || h.name || '',
          handle: c.handle || h.handle || '',
          group: Boolean(c.group || h.group),
          tag: c.tag || h.tag || '',
          messages: (conv.messages || []).map((m) => ({
            id: m.id, dir: m.dir, sender: m.sender || (m.dir === 'out' ? 'me' : (c.name || '')),
            text: m.text, mins: m.mins, at_approx: at(m.mins), status: m.status,
          })),
        });
      }

      const stamp = new Date(now).toISOString().slice(0, 19).replace(/[:T]/g, '-');
      const base = `chat-export_${String(cid).replace(/[^\w.-]/g, '_')}_${stamp}`;
      if (format === 'csv') {
        const lines = [CSV_COLS.join(',')];
        for (const c of out) {
          for (const m of c.messages) {
            lines.push([c.id, c.name, c.handle, c.group, m.id, m.dir, m.sender, m.text,
              m.at_approx, m.mins, m.status].map(csvCell).join(','));
          }
        }
        res.setHeader('Content-Type', 'text/csv; charset=utf-8');
        res.setHeader('Content-Disposition', `attachment; filename="${base}.csv"`);
        // BOM: Excel reads a BOM-less UTF-8 CSV as the local codepage, and every Hebrew name in the
        // file becomes mojibake — the export is unusable for the people it is for.
        return res.send(`﻿${lines.join('\r\n')}\r\n`);
      }
      res.setHeader('Content-Disposition', `attachment; filename="${base}.json"`);
      res.json({
        connection_id: cid,
        exported_at: new Date(now).toISOString(),
        conversations: out,
        messages: out.reduce((n, c) => n + c.messages.length, 0),
      });
    } catch (e) { onAdapterError(res, e, pick(req)); }
  });

  // ── platform-service.v1: the console's dialect ─────────────────────────────
  //
  // The console's top-bar account chip is the shell's control, identical for every service that
  // owns accounts, and it speaks ROOT-level paths with drive/mail's field names:
  //
  //   GET    /connections          -> {active, connections:[{id,protocol,label,account_hint,status}]}
  //   POST   /connections/select   {id}
  //   POST   /connections          {protocol,label,secret}
  //   DELETE /connections/:id
  //   GET    /readyz  ·  GET /manifest  ·  GET /providers
  //
  // Chat already answers every one of these under /api/*, so the chip stayed dark purely over a
  // prefix and three field names. These are ALIASES, not a second implementation: each one
  // delegates to the same cc/adapters calls its /api/* twin uses, and the only thing that differs
  // is the shape on the way out. A parallel implementation would drift, and the failure would be
  // the chip disagreeing with the app about which account is active — the exact confusion the
  // single-active-pointer design exists to prevent.
  //
  // /api/* stays: the chat client is built on it, and the sim's mock defined those paths.

  app.get('/connections', guard, async (req, res) => {
    try {
      const { instances, reachable, error } = await allInstances();
      res.json({
        active: await defaultConnection(),
        reachable,
        connections: instances.map((i) => ({
          id: i.id,
          protocol: i.protocol || cc.LOCAL_PROTOCOL,
          label: i.label || i.id,
          // `account_hint` is the console's name for what the chat UI calls `identity`.
          account_hint: i.identity || i.account_hint || '',
          status: i.status || 'ok',
          builtin: Boolean(i.builtin),
        })),
        ...(error ? { error } : {}),
      });
    } catch (e) { onAdapterError(res, e); }
  });

  app.post('/connections/select', guard, async (req, res) => {
    try {
      const id = (req.body && req.body.id) || null;
      const { instances } = await allInstances();
      if (id && !instances.some((i) => i.id === id)) return res.status(404).json({ error: `unknown connection ${id}` });
      await cc.select(id);
      await adapters.forget(id);
      res.json({ ok: true, active: id });
    } catch (e) { onAdapterError(res, e); }
  });

  app.post('/connections', guard, async (req, res) => {
    try {
      const b = req.body || {};
      const protocol = String(b.protocol || '').trim();
      if (!cc.PROTOCOLS.includes(protocol)) {
        return res.status(400).json({ ok: false, error: `unsupported protocol ${protocol || '(none)'}` });
      }
      if (protocol === cc.LOCAL_PROTOCOL) {
        // Not "needs no connection" — it needs one PER PROFILE, and creating the profile creates it.
        return res.status(400).json({
          ok: false,
          error: 'an identity on the private chat engine is created as a profile, which mints its own connection',
          route: 'POST /engine/profiles',
        });
      }
      const r = await cc.createInstance(protocol, b.label || protocol, b.secret || {}, b.account_hint);
      res.json({ ok: true, ...r });
    } catch (e) {
      if (e instanceof cc.ConnectionsError) return res.status(e.status || 502).json({ ok: false, error: e.message });
      onAdapterError(res, e);
    }
  });

  app.delete('/connections/:id', guard, async (req, res) => {
    const id = req.params.id;
    const owned = await profiles.byInstance(id).catch(() => null);
    if (owned) {
      return res.status(400).json({
        ok: false, id, profile_id: owned.id,
        error: `«${owned.display_name}» הוא פרופיל במנוע הפנימי — הסרתו נעשית במסך הפרופילים`,
        route: `DELETE /engine/profiles/${owned.id}`,
      });
    }
    try {
      await cc.deleteInstance(id);
    } catch (e) {
      if (e instanceof cc.ConnectionsError) return res.status(e.status || 502).json({ ok: false, error: e.message, id });
      return onAdapterError(res, e, id);
    }
    if ((await cc.active()) === id) await cc.select(null);
    await adapters.forget(id);
    res.json({ ok: true, id });
  });

  app.get('/readyz', guard, withActor, async (req, res) => {
    let cid = null;
    try {
      const r = await adapters.resolveActive(pick(req));
      cid = r.cid;
      const p = (await r.backend.probe()) || {};
      res.status(p.ok === false ? 503 : 200).json({ ready: p.ok !== false, connection_id: cid, ...p });
    } catch (e) {
      if (e instanceof adapters.AdapterError) {
        return res.status(e.status).json({ ready: false, reason: e.message, connection_id: e.connectionId, active: await cc.active() });
      }
      onAdapterError(res, e, cid);
    }
  });

  app.get('/manifest', guard, withActor, async (req, res) => {
    // `protocols` IS NOT A PROPERTY OF A CONNECTION. It is what this service can ever connect —
    // cc.PROTOCOLS, a constant — and it is the console's ONLY input for "connect a new account".
    //
    // This used to resolve the active connection FIRST and 502 the whole document when that failed,
    // which made one broken account a dead end for the entire service: measured live 2026-09-02, a
    // telegram connection saved without its token ("secret needs {token}") made GET /manifest throw,
    // the console got no `protocols`, the "חיבור חשבון חדש" button was never rendered, and the
    // operator could not reach the wizard to fix or replace the very connection that broke it. The
    // only way out was a database edit.
    //
    // So the static half always answers, and the connection-dependent half (`ops`, derived from the
    // resolved backend) degrades to null with the reason beside it. A caller that needs ops can see
    // it is absent and why; a caller that needs the catalogue is never blocked by someone else's
    // broken credential.
    let cid = null, ops = null, reason = null;
    try {
      const r = await adapters.resolveActive(pick(req));
      cid = r.cid; ops = adapters.opsFor(r.backend);
    } catch (e) {
      cid = (e && e.connectionId) || null;
      reason = String((e && e.message) || e);
    }
    res.json({ connection_id: cid, ops, protocols: cc.PROTOCOLS, ...(reason ? { ops_error: reason } : {}) });
  });
}

module.exports = { register };
