/**
 * THE PRIVATE ENGINE'S PROFILE SURFACE — the same five routes mail and drive expose, same names.
 *
 *   GET    /engine/profiles             admin        list
 *   POST   /engine/profiles             admin        create — mints the key AND the vault instance
 *   POST   /engine/profiles/reconcile   admin        force a bootstrap pass (idempotent by design)
 *   PATCH  /engine/profiles/:id         self/admin   rename, promote/demote, suspend/resume
 *   POST   /engine/profiles/:id/key     self/admin   rotate the credential
 *   DELETE /engine/profiles/:id         admin        remove ACCESS, never data
 *
 * Named to match mail's plane (apps/mail/mailapi/service.py) so the console and any automation speak
 * ONE dialect across the three apps. The one deliberate difference is the rotate route: mail's
 * credential IS a mailbox password and its route says `/password`; chat's is an API key and calling
 * it a password would be a lie about what the client does with it.
 *
 * Two things these routes are NOT, and both are deliberate:
 *
 * · They are not the CONNECT WIZARD. Creating an identity and connecting to one are different acts.
 *   You cannot create a user on WhatsApp — you pair a device; nor on Telegram — you register a bot
 *   with BotFather. Engine administration exists only for an engine we run.
 * · They are not bound to whichever connection happens to be selected. They are about the ENGINE, so
 *   they always address the private one. Selecting WhatsApp and then pressing "add profile" must not
 *   quietly mean something else, and must not silently do nothing either.
 *
 * CREATING A PROFILE CREATES ITS CONNECTION, in one operation. Create-then-separately-connect is a
 * step with no decision in it, and it is exactly what made "add a mail user" undiscoverable.
 *
 * THE KEY IS RETURNED EXACTLY ONCE, at creation and at rotation. This service stores only the hash,
 * so there is no second chance to read it — the vault has a copy for clients, and the honest answer
 * to "I lost it" is a rotation.
 */
const { keyFrom } = require('./auth');
const bootstrap = require('./bootstrap');

/** ProfileError carries its own status; anything else is ours and is a 500. */
function fail(res, e) {
  if (e && e.name === 'ProfileError') return res.status(e.status || 400).json({ ok: false, error: e.message });
  console.error('[chat/engine]', e);
  return res.status(500).json({ ok: false, error: String((e && e.message) || e) });
}

/**
 * @param {object} app       express
 * @param {function} guard   the app's session guard
 * @param {object} deps      { profiles, cc, auth, adapters }
 */
function register(app, sessionGuard, { profiles, cc, auth, adapters }) {
  const { withActor, requireAdmin, requireSelfOrAdmin } = auth;

  /**
   * A CREDENTIAL IS AN AUTHENTICATION.
   *
   * The app's own guard is a browser session (or basic auth on /api/*), and it exists because a
   * human opens this app in a tab. An automation holding a profile key has no session and no
   * business getting one — without this it would be answered with a 302 to /login, which reads as
   * "the service is down" to anything that is not a browser.
   *
   * The key is not trusted here. It is only accepted as a REASON TO PROCEED; `withActor` then
   * resolves it by hash and refuses anything it does not recognise, so a bogus key buys a 401 rather
   * than a way past the session guard.
   */
  const guard = (req, res, next) => (keyFrom(req) ? next() : sessionGuard(req, res, next));

  /** Mint the vault instance for a profile that has just been created or rotated. Returns the id, or
   *  null when the vault is unreachable — which is a DEFERRAL, never a rollback: the profile exists
   *  and the reconciler will finish the job on the next boot rather than the operator losing it. */
  async function vaultInstanceFor(profile, key) {
    try {
      const r = await cc.createInstance(
        cc.LOCAL_PROTOCOL, profile.display_name, { profile_id: profile.id, api_key: key }, profile.id);
      if (!r || !r.id) throw new Error('connections returned no instance id');
      await profiles.setInstance(profile.id, r.id);
      return r.id;
    } catch (e) {
      console.warn(`[chat/engine] profile ${profile.id}: connection deferred — ${e.message}`);
      return null;
    }
  }

  const at = (p) => [`/engine/profiles${p}`, `/api/engine/profiles${p}`];

  app.get(at(''), guard, withActor, requireAdmin, async (req, res) => {
    try {
      res.json({ ok: true, acting_as: req.actor.id, profiles: await profiles.list() });
    } catch (e) { fail(res, e); }
  });

  app.post(at(''), guard, withActor, requireAdmin, async (req, res) => {
    const b = req.body || {};
    try {
      const { profile, key } = await profiles.create({
        id: b.id,
        display_name: b.display_name || b.name,
        is_admin: Boolean(b.is_admin || b.admin),
      });
      const instanceId = await vaultInstanceFor(profile, key);
      res.status(201).json({
        ok: true,
        profile: { ...profile, instance_id: instanceId },
        connection_id: instanceId,
        // Once. There is no route that can show it again.
        key,
        ...(instanceId ? {} : { warning: 'הפרופיל נוצר; החיבור שלו ייווצר כשמאגר החיבורים יחזור' }),
      });
    } catch (e) { fail(res, e); }
  });

  /**
   * Force a reconcile pass — the same one that runs at boot.
   *
   * Exists for the same reason mail's does: idempotence is a claim, and a claim you cannot exercise
   * on a running deployment is a claim nobody checks. Run it twice and the second answer has empty
   * `created`/`repaired`/`removed` lists, which IS the property that makes `bbox run` safe to point
   * at a live company.
   *
   * Registered before `/:id` — otherwise `reconcile` is read as a profile id by the PATCH/DELETE
   * routes below and an operator gets "no such profile: reconcile".
   */
  app.post(at('/reconcile'), guard, withActor, requireAdmin, async (req, res) => {
    try {
      const r = await bootstrap.reconcile({ store: profiles });
      res.status(r.errors && r.errors.length ? 503 : 200).json({ ok: !(r.errors || []).length, ...r });
    } catch (e) { fail(res, e); }
  });

  app.patch(at('/:id'), guard, withActor, requireSelfOrAdmin('id'), async (req, res) => {
    const b = req.body || {};
    try {
      // Only an ADMIN may change an admin flag or a status — those are ring-`admin` operations even
      // when the target is yourself, because "promote myself" is the whole attack.
      if ((b.is_admin !== undefined || b.status !== undefined) && !req.actor.is_admin) {
        return res.status(403).json({ ok: false, error: 'רק מנהל יכול לשנות הרשאות או להשהות פרופיל' });
      }
      const updated = await profiles.update(req.params.id, {
        display_name: b.display_name !== undefined ? b.display_name : b.name,
        is_admin: b.is_admin !== undefined ? Boolean(b.is_admin) : (b.admin !== undefined ? Boolean(b.admin) : undefined),
        status: b.status,
      });
      // A suspended profile must stop serving IMMEDIATELY, not when its cached backend happens to
      // expire — the cache is keyed on the connection id and would otherwise keep answering.
      if (updated.instance_id) await adapters.forget(updated.instance_id);
      res.json({ ok: true, profile: updated });
    } catch (e) { fail(res, e); }
  });

  app.post(at('/:id/key'), guard, withActor, requireSelfOrAdmin('id'), async (req, res) => {
    try {
      const { profile, key } = await profiles.rotate(req.params.id);
      let vaulted = false;
      if (profile.instance_id) {
        // Local FIRST, then the vault. The other order leaves a window in which the vault hands out
        // a key this service does not yet accept, and a client cannot tell that apart from a broken
        // credential. This order locks clients out until the vault catches up, which is visible.
        try { await cc.putSecret(profile.instance_id, { profile_id: profile.id, api_key: key }); vaulted = true; } catch (e) {
          console.warn(`[chat/engine] profile ${profile.id}: key rotated locally, vault not updated — ${e.message}`);
        }
      }
      await adapters.forget(profile.instance_id);
      res.json({
        ok: true, profile, key, vault_updated: vaulted,
        ...(vaulted ? {} : { warning: 'המפתח הוחלף כאן; מאגר החיבורים לא עודכן — שמור את המפתח וסנכרן מאוחר יותר' }),
      });
    } catch (e) { fail(res, e); }
  });

  app.delete(at('/:id'), guard, withActor, requireAdmin, async (req, res) => {
    try {
      const r = await profiles.remove(req.params.id);
      if (r.instance_id) {
        await cc.deleteInstance(r.instance_id).catch((e) =>
          console.warn(`[chat/engine] profile ${r.id}: vault instance not removed — ${e.message}`));
        // A binding left aimed at a removed profile would answer 503 on every op against an identity
        // the operator believes they deleted.
        if ((await cc.active()) === r.instance_id) await cc.select(null);
        await adapters.forget(r.instance_id);
      }
      res.json({ ok: true, id: r.id, removed_connection: r.instance_id || null, data_kept: true });
    } catch (e) { fail(res, e); }
  });

  /** Who am I? The screen that decides whether to OFFER profile management needs an answer that does
   *  not require being an admin to ask. */
  app.get(['/engine/whoami', '/api/engine/whoami'], guard, withActor, (req, res) => {
    res.json({
      ok: true,
      profile: req.actor || null,
      credentialed: Boolean(req.actorCredentialed),
      connection_id: req.actorConnection || null,
      is_admin: Boolean(req.actor && req.actor.is_admin),
      engine: cc.LOCAL_PROTOCOL,
    });
  });
}

module.exports = { register };
