// The office's folder is where a new session opens, from the first sign-in on (DGO-1920). The owner, 2026-11-17:
// «i want that myDgo to be the default folder when i come in after login and start a new session».
//
// The app opens its New page on the place the LAST session was started from (`startedFrom`, read in its own UI
// code); after a first sign-in it has none, and shows «No folder». So once per NEW account — signed in, with no
// session in a folder yet — the adapter hands the app the office through the app's own door (desktop/drive `home`:
// claude://code/new?folder=…). The app asks «Trust this workspace?» once; the session the person starts there makes
// the office the app's own default. An account that has any session started in a folder (any folder; the app's
// scratch workspace is none, below) is not new, and an account at work this minute is waited for: a restart of the
// adapter never moves a working screen to the New page. One handed once is not handed again (the state file).
import fs from "node:fs";
import path from "node:path";

// Which account the app is signed in with (its own config; the uuid is no secret), or null.
export function currentAccount(desk) {
  try {
    const c = JSON.parse(fs.readFileSync(path.join(desk, ".config", "Claude", "config.json"), "utf8"));
    return typeof c.lastKnownAccountUuid === "string" && c.lastKnownAccountUuid ? c.lastKnownAccountUuid : null;
  } catch {
    return null;
  }
}

// Whether the account has worked here in a folder: any session record of it (the app keeps them per account) that
// was started somewhere other than the app's own scratch workspace. A session started with no folder chosen runs
// in `<home>/.config/Claude/scratch-workspaces/…`. That is the «No folder» screen this module exists to replace,
// not a place the person picked. Examplex's office, 2026-11-18 (DGO-2002): the owner, offered no folder, started one
// there; counted as work, his account would never have been handed the office. Matched by the segment, not by
// `desk`: the record holds the path as the desktop's container sees it (/config/…), not this one's.
const SCRATCH = /\/\.config\/Claude\/scratch-workspaces\//;
export function hasSessions(desk, account) {
  return fs.globSync(path.join(desk, ".config/Claude/claude-code-sessions", account, "*", "local_*.json")).some((f) => {
    try {
      return !SCRATCH.test(String(JSON.parse(fs.readFileSync(f, "utf8")).cwd || ""));
    } catch {
      return true;                                // a record it cannot read counts as work: never move that screen
    }
  });
}

// Whether the account is at work now: a session record of it written in the last `quiet` ms. The app rewrites a
// record as its session runs, so a person typing into a scratch session is not moved to the New page mid-turn; the
// hand-off waits for a quiet minute (DGO-2002's second reader).
export function atWork(desk, account, now = Date.now(), quiet = 5 * 60000) {
  return fs.globSync(path.join(desk, ".config/Claude/claude-code-sessions", account, "*", "local_*.json")).some((f) => {
    try {
      return now - fs.statSync(f).mtimeMs < quiet;
    } catch {
      return true;
    }
  });
}

// What to do now: { hand: account } or { hand: null, why }.
export function decide({ signedIn, account, handed, worked, busy }) {
  if (signedIn !== true) return { hand: null, why: "not signed in" };
  if (!account) return { hand: null, why: "no account known yet" };
  if (handed.includes(account)) return { hand: null, why: "handed the office once already" };
  if (worked) return { hand: null, why: "not a new account: it has sessions" };
  if (busy) return { hand: null, why: "at work this minute: the next quiet one" };
  return { hand: account };
}

export function createHomeFolder({ desk, folders, stateFile, signedIn, drive, log = console.error, every = 60000 }) {
  const load = () => { try { return JSON.parse(fs.readFileSync(stateFile, "utf8")).handed || []; } catch { return []; } };
  async function tick() {
    const handed = load();
    const account = currentAccount(desk);
    const signed = signedIn();
    // the records are read only for an account that could still be handed the office, never every minute
    const open = signed === true && !!account && !handed.includes(account);
    const d = decide({ signedIn: signed, account, handed, worked: open && hasSessions(desk, account),
                       busy: open && atWork(desk, account) });
    if (!d.hand) return d;
    try {
      await drive(["home", folders[0]]);
      fs.writeFileSync(stateFile, JSON.stringify({ handed: [...handed, d.hand] }) + "\n");
      log(`[home-folder] the New page was opened on ${folders[0]} for the newly signed-in account`);
    } catch (e) {
      log(`[home-folder] could not open the New page on the office yet (${e.message}); the next minute tries again`);
    }
    return d;
  }
  return { tick, start: () => setInterval(() => { tick().catch(() => {}); }, every).unref() };
}
