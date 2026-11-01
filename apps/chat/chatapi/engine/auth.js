/**
 * WHO IS ASKING — the acting profile for one request, and the three rings that gate it.
 *
 * The problem this exists to end: `chat_local-<userId>` was a connection id anyone could name, so
 * "select an identity" was impersonation with nothing to authenticate against. The UI admitted it in
 * a comment. A credential fixes it, and the fix has to be in ONE place or it will be half-applied.
 *
 * THE ACTING PROFILE, in order:
 *
 *   1. a CREDENTIAL, if one is presented — `X-Chat-Profile-Key: <key>`, `Authorization: Bearer <key>`
 *      or `profile_key` in a JSON body. Resolved by HASH against chat_profiles, so the claim cannot
 *      be forged and no field the caller controls decides who they are.
 *   2. otherwise the BINDING — which is the browser path. The whole app sits behind authentik
 *      forward-auth (see apps/chat/docker-compose.yml labels), so reaching this point at all means
 *      the deployment already authenticated a human; the binding then says which profile that
 *      session is acting as. Mapping platform users to profiles is a separate concern by design
 *      (ai/context/app-engine-pattern.md §10) and must not be faked here.
 *
 * AND THE RULE THAT MAKES A CREDENTIAL WORTH HAVING: if a request presents profile B's key while
 * naming profile A's connection, it is REFUSED (403). A credential can only ever act as itself.
 * Without this, a key would be a second way in rather than a constraint, and the impersonation the
 * whole change exists to remove would still be reachable — just with an extra header.
 *
 * `CHAT_ENGINE_REQUIRE_KEY=1` makes a credential mandatory for every engine op, which is what an
 * automation-only deployment wants. Default off: with it on, the browser UI cannot talk to its own
 * engine, because a session is not a credential and pretending otherwise would put a key in the DOM.
 */
const REQUIRE_KEY = /^(1|true|yes)$/i.test(String(process.env.CHAT_ENGINE_REQUIRE_KEY || ''));

class AuthError extends Error {
  constructor(message, status = 403) {
    super(message);
    this.name = 'AuthError';
    this.status = status;
  }
}

/** The credential on this request, or ''. Never read from the query string: a secret in a URL ends
 *  up in access logs, referrers and browser history. */
function keyFrom(req) {
  const h = (req && req.headers) || {};
  const direct = h['x-chat-profile-key'];
  if (direct) return String(direct).trim();
  const m = /^Bearer\s+(.+)$/i.exec(String(h.authorization || ''));
  if (m) return m[1].trim();
  const body = (req && req.body) || {};
  return String(body.profile_key || '').trim();
}

/** The connection this request is about: explicit override > binding > (null, meaning "the default
 *  admin profile", which resolveActive() fills in). */
function connectionFrom(req) {
  const body = (req && req.body) || {};
  const query = (req && req.query) || {};
  return body.connection_id || query.connection_id || null;
}

/**
 * Build the actor resolver. `deps` are injected so the routes, the ops and the tests all share one
 * profile store and one binding reader rather than three that can disagree.
 */
function makeAuth({ profiles, cc }) {
  /**
   * @returns {Promise<{actor: object|null, credentialed: boolean, cid: string|null, target: object|null}>}
   *   `actor`   the profile this request acts as — null when the connection is a REMOTE one, which
   *             has no profile on our engine and is not subject to these rings.
   *   `target`  the profile behind the named connection, if it is one of ours.
   */
  async function resolveActor(req) {
    const key = keyFrom(req);
    let credential = null;
    if (key) {
      credential = await profiles.byKey(key);
      if (!credential) throw new AuthError('אישור הגישה אינו מוכר', 401);
      if (credential.status !== 'active') {
        throw new AuthError(`הפרופיל «${credential.display_name}» מושהה`, 403);
      }
    }

    const named = connectionFrom(req);
    let cid = null;
    let target = null;

    if (credential) {
      /* A CREDENTIAL IS SELF-ADDRESSING, and the BINDING IS NOT CONSULTED.
       *
       * The binding is a browser-session concept: one operator, one tab, one identity selected in
       * the switcher. An automation holding a key has nothing to do with it, and letting it decide
       * would mean a human clicking the switcher silently redirects — or 403s — every automation on
       * the deployment. Measured against the live stack: nothing was bound, so `firstAdmin()` was
       * the fallback, and a request carrying user2's key was answered with the ADMIN's
       * conversations. Two resolvers, one request, and the wrong one won.
       *
       * Naming a connection explicitly is still allowed, and must be your own — that is the check
       * that makes the key a constraint rather than a second way in.
       */
      if (named) {
        target = await profiles.byInstance(named);
        if (!target) {
          throw new AuthError(
            'אישור גישה של פרופיל תקף רק מול המנוע הפנימי, ולא מול חיבור חיצוני', 403);
        }
        if (target.id !== credential.id) {
          throw new AuthError(
            `אישור הגישה שייך לפרופיל «${credential.display_name}» ואינו יכול לפעול בשם «${target.display_name}»`, 403);
        }
        cid = named;
      } else {
        target = credential;
        cid = credential.instance_id;
      }
    } else {
      // The session path: what the switcher points at, and on a fresh deployment the first admin.
      cid = named || (await cc.active()) || null;
      target = cid ? await profiles.byInstance(cid) : await profiles.firstAdmin();
      if (!cid) cid = target ? target.instance_id : null;
    }

    // Strict mode refuses the session path, but ONLY where our engine is what is being addressed —
    // a WhatsApp connection has no profile to hold a key and must not be locked out by this.
    if (REQUIRE_KEY && !credential && (target || !cid)) {
      throw new AuthError('נדרש אישור גישה של פרופיל (CHAT_ENGINE_REQUIRE_KEY)', 401);
    }
    const actor = credential || target;
    return { actor, credentialed: Boolean(credential), cid, target };
  }

  /** Attach `req.actor` for every route below. Never rejects a REMOTE connection: WhatsApp and
   *  Telegram have no profile on our engine and these rings are not about them. */
  function withActor(req, res, next) {
    resolveActor(req).then((r) => {
      req.actor = r.actor;
      req.actorCredentialed = r.credentialed;
      req.actorConnection = r.cid;
      next();
    }, (e) => {
      const status = e instanceof AuthError ? e.status : 500;
      res.status(status).json({ error: String(e.message || e) });
    });
  }

  /** Ring `data`/`self`: an active profile on this engine. */
  function requireProfile(req, res, next) {
    if (!req.actor) {
      return res.status(403).json({ error: 'הפעולה הזו קיימת רק במנוע הפנימי, ולחיבור הנוכחי אין פרופיל בו' });
    }
    return next();
  }

  /** Ring `admin`: create/edit/suspend/delete OTHER profiles. */
  function requireAdmin(req, res, next) {
    if (!req.actor) {
      return res.status(403).json({ error: 'ניהול פרופילים קיים רק במנוע הפנימי' });
    }
    if (!req.actor.is_admin) {
      return res.status(403).json({
        error: `לפרופיל «${req.actor.display_name}» אין הרשאת ניהול פרופילים`,
        profile_id: req.actor.id,
      });
    }
    return next();
  }

  /** Ring `self`: my own profile, or anybody's if I am an admin. */
  function requireSelfOrAdmin(paramName = 'id') {
    return (req, res, next) => {
      if (!req.actor) return res.status(403).json({ error: 'ניהול פרופילים קיים רק במנוע הפנימי' });
      const target = String(req.params[paramName] || '');
      if (req.actor.is_admin || req.actor.id === target) return next();
      return res.status(403).json({
        error: `פרופיל «${req.actor.display_name}» יכול לשנות רק את עצמו`,
        profile_id: req.actor.id,
      });
    };
  }

  return { resolveActor, withActor, requireProfile, requireAdmin, requireSelfOrAdmin, REQUIRE_KEY };
}

module.exports = { makeAuth, AuthError, keyFrom, connectionFrom, REQUIRE_KEY };
