/**
 * A stand-in for the chat database — a Map that understands exactly the statements
 * chatapi/engine/profiles.js issues, and nothing else.
 *
 * Deliberately THROWS on an unrecognised statement rather than answering `{rows: []}`. An empty
 * result set is what a working query against an empty table looks like, so a silent fallback would
 * let a broken statement pass every test in the file while failing against Postgres.
 *
 * Shared by the profile tests and the reconciler tests so both agree on what the storage does.
 */
function fakeChatDb() {
  const profiles = new Map();

  const run = async (text, params = []) => {
    const q = text.replace(/\s+/g, ' ').trim();

    // `chat_users` had handlers here. The table is retired: a profile is no longer also a person
    // row, because conversations moved to the relay where a person IS a pubkey. A double that still
    // answered for it would let a re-introduced write pass its tests and fail against the database.
    if (/^INSERT INTO public\.chat_profiles/.test(q)) {
      // `pubkey` is the profile's identity on the relay, minted with the key. The double must carry
      // it or publicProfile() reports null and every caller that resolves an author back to a
      // profile silently sees a stranger.
      const [id, name, admin, keyHash, pubkey] = params;
      if (profiles.has(id)) return { rows: [], rowCount: 0 };            // ON CONFLICT DO NOTHING
      const row = {
        id, display_name: name, is_admin: admin, key_hash: keyHash, pubkey: pubkey || null,
        status: 'active', instance_id: null, created_at: new Date(Date.now() + profiles.size),
      };
      profiles.set(id, row);
      return { rows: [row], rowCount: 1 };
    }
    if (/^SELECT .*FROM public\.chat_profiles WHERE pubkey = \$1/.test(q)) {
      const r = [...profiles.values()].find((p) => p.pubkey === params[0]);
      return { rows: r ? [r] : [] };
    }
    // setPubkey: a BACKFILL, guarded so it can never overwrite an identity. The query spans lines,
    // hence [\s\S]* rather than a bare .* — a dot does not cross a newline.
    if (/^UPDATE public\.chat_profiles SET pubkey = \$2[\s\S]*pubkey IS NULL/.test(q)) {
      const r = profiles.get(params[0]);
      if (!r || r.pubkey) return { rows: [], rowCount: 0 };               // refuses to overwrite
      r.pubkey = params[1];
      return { rows: [r], rowCount: 1 };
    }
    if (/^UPDATE public\.chat_profiles SET pubkey/.test(q)) {            // resetIdentity
      const r = profiles.get(params[0]);
      if (r) r.pubkey = params[1];
      return { rows: r ? [r] : [], rowCount: r ? 1 : 0 };
    }
    if (/^SELECT count\(\*\)::int AS n FROM public\.chat_profiles/.test(q)) {
      return { rows: [{ n: [...profiles.values()].filter((p) => p.is_admin && p.status === 'active').length }] };
    }
    if (/^SELECT .*FROM public\.chat_profiles WHERE id = \$1/.test(q)) {
      const r = profiles.get(params[0]);
      return { rows: r ? [r] : [] };
    }
    if (/^SELECT .*FROM public\.chat_profiles WHERE key_hash = \$1/.test(q)) {
      const r = [...profiles.values()].find((p) => p.key_hash === params[0]);
      return { rows: r ? [r] : [] };
    }
    if (/^SELECT .*FROM public\.chat_profiles WHERE instance_id = \$1/.test(q)) {
      const r = [...profiles.values()].find((p) => p.instance_id === params[0]);
      return { rows: r ? [r] : [] };
    }
    if (/^SELECT .*FROM public\.chat_profiles WHERE is_admin = true/.test(q)) {
      const r = [...profiles.values()]
        .filter((p) => p.is_admin && p.status === 'active')
        .sort((a, b) => a.created_at - b.created_at)[0];
      return { rows: r ? [r] : [] };
    }
    if (/^SELECT .*FROM public\.chat_profiles ORDER BY/.test(q)) {
      return {
        rows: [...profiles.values()]
          .sort((a, b) => Number(b.is_admin) - Number(a.is_admin) || a.created_at - b.created_at),
      };
    }
    if (/^UPDATE public\.chat_profiles SET instance_id/.test(q)) {
      const r = profiles.get(params[0]);
      if (r) r.instance_id = params[1];
      return { rows: r ? [r] : [] };
    }
    if (/^UPDATE public\.chat_profiles SET key_hash/.test(q)) {
      const r = profiles.get(params[0]);
      if (r) r.key_hash = params[1];
      return { rows: r ? [r] : [] };
    }
    if (/^UPDATE public\.chat_profiles SET /.test(q)) {
      const r = profiles.get(params[0]);
      if (r) {
        const sets = q.slice(q.indexOf('SET ') + 4, q.indexOf(' WHERE ')).split(', ');
        for (const assign of sets) {
          const [col, placeholder] = assign.split(' = ');
          r[col.trim()] = params[Number(placeholder.trim().slice(1)) - 1];
        }
      }
      return { rows: r ? [r] : [] };
    }
    if (/^DELETE FROM public\.chat_profiles/.test(q)) {
      return { rows: [], rowCount: profiles.delete(params[0]) ? 1 : 0 };
    }
    throw new Error(`fakeChatDb: unhandled statement — ${q.slice(0, 90)}`);
  };

  return {
    SCHEMA: 'public',
    ensureSchema: async () => true,
    query: run,
    tx: async (fn) => fn({ query: run }),
    close: async () => {},
    _profiles: profiles,
  };
}

module.exports = { fakeChatDb };
