function bounded(stage, operation, timeout = 5000) {
  return Promise.race([
    operation,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(`${stage} timed out`)), timeout);
    })
  ]);
}

async function ensureOffscreen() {
  if (await chrome.offscreen.hasDocument()) return;
  await chrome.offscreen.createDocument({
    url: 'offscreen.html',
    reasons: ['WORKERS'],
    justification: 'Maintain the local Browser42 command channel'
  });
}

async function ownerForTab(tabId) {
  const result = await chrome.storage.local.get(`owner_${tabId}`);
  return result[`owner_${tabId}`] || null;
}

async function claimTab(tabId, slug) {
  await chrome.storage.local.set({ [`owner_${tabId}`]: slug });
  try {
    // world: 'MAIN' is MANDATORY: executeScript defaults to the ISOLATED content-script
    // world, where window.name is invisible to the page's MAIN world — which is exactly
    // what group-manager's group_tabs()/owned_page() reads via Playwright CDP. Without
    // MAIN, the ownership tag never lands and every task_start scans 0 tagged tabs for
    // the full 240s deadline ("did not acquire ownership").
    await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: (value) => { window.name = `b42g:${value}`; },
      args: [slug]
    });
  } catch (_) {}
  try {
    await chrome.tabs.sendMessage(tabId, { type: 'browser42-claim', slug });
  } catch (_) {}
}

async function existingSession(slug) {
  const key = `session_${slug}`;
  const stored = (await chrome.storage.local.get(key))[key];
  if (!stored?.tabId) return null;
  try {
    const ownedTabIds = (stored.ownedTabIds || [stored.tabId]);
    const liveTabIds = [];
    for (const tabId of ownedTabIds) {
      try {
        await chrome.tabs.get(tabId);
        liveTabIds.push(tabId);
      } catch (_) {}
    }
    if (!liveTabIds.includes(stored.tabId)) {
      if (!liveTabIds.length) throw new Error('session has no live tabs');
      stored.tabId = liveTabIds[0];
    }
    stored.ownedTabIds = liveTabIds;
    await chrome.storage.local.set({ [key]: stored });
    return {
      tab: await chrome.tabs.get(stored.tabId),
      groupId: stored.groupId,
      session: stored
    };
  } catch (_) {
    await chrome.storage.local.remove([key, ...((stored.ownedTabIds || [stored.tabId]).map(tabId => `owner_${tabId}`))]);
    return null;
  }
}

async function allocate(command) {
  const existing = await existingSession(command.slug);
  const tab = existing
    ? await bounded('tabs.update', chrome.tabs.update(existing.tab.id, {
        url: command.url,
        active: true
      }))
    : await bounded('tabs.create', chrome.tabs.create({
        url: command.url,
        active: true
      }));
  // Tag ownership IMMEDIATELY, before group/claim ops: window.name set on the fresh
  // (still blank, instantly scriptable) document PERSISTS across the navigation to the
  // ad-heavy site, so the runner's ownership scan finds the tab while its renderer is
  // saturated. Without this the scan missed for the whole start loop (flash regression).
  await chrome.storage.local.set({ [`owner_${tab.id}`]: command.slug });
  try {
    // world: 'MAIN' — see claimTab(); the tag must land in the page MAIN world or the
    // runner's MAIN-world window.name ownership scan never finds the tab.
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'MAIN',
      func: (value) => { window.name = `b42g:${value}`; },
      args: [command.slug]
    });
  } catch (_) {}
  let groupId = existing?.groupId;
  if (!Number.isInteger(groupId) || groupId < 0) {
    groupId = await bounded(
      'tabs.group',
      chrome.tabs.group({ tabIds: [tab.id] })
    );
  }
  await bounded('tabGroups.update', chrome.tabGroups.update(groupId, {
    title: command.label,
    color: command.color,
    collapsed: false
  }));
  const generation = existing?.session?.generation || crypto.randomUUID();
  await chrome.storage.local.set({
    [`session_${command.slug}`]: {
      tabId: tab.id,
      groupId,
      policy: command.policy || 'single',
      generation,
      ownedTabIds: existing?.session?.ownedTabIds || [tab.id],
      lastUrl: command.url            // kept current by onUpdated; how frontSession finds the tab after a sleep
    }
  });
  await claimTab(tab.id, command.slug);
  return { ok: true, tabId: tab.id, groupId, generation };
}

async function closeSession(slug) {
  const existing = await existingSession(slug);
  if (!existing) return { ok: true, closed: 0 };
  const tabIds = existing.session.ownedTabIds || [existing.tab.id];
  try { await chrome.tabs.remove(tabIds); } catch (_) {}
  await chrome.storage.local.remove([
    `session_${slug}`,
    ...tabIds.map(tabId => `owner_${tabId}`)
  ]);
  return { ok: true, closed: tabIds.length };
}

async function statusSession(slug) {
  const existing = await existingSession(slug);
  if (!existing) return { ok: true, session: null };
  return {
    ok: true,
    session: {
      tabId: existing.session.tabId,
      groupId: existing.session.groupId,
      generation: existing.session.generation,
      ownedTabIds: existing.session.ownedTabIds || [existing.session.tabId]
    }
  };
}

async function claimSession(command) {
  // Authoritative ownership: the runner asks us to claim the EXACT tabId that
  // allocate() returned. Never guess by URL — under parallel same-URL starts a
  // guess can adopt a sibling task's tab (cross-task mutation).
  const tabId = command.tabId;
  try {
    await chrome.tabs.get(tabId);
  } catch (_) {
    return { ok: false, error: `tab ${tabId} is not live` };
  }
  await claimTab(tabId, command.slug);
  return { ok: true, tabId };
}

async function knownSlugs() {
  const all = await chrome.storage.local.get(null);
  return new Set(Object.keys(all).filter(key => key.startsWith('session_')).map(key => key.slice('session_'.length)));
}

async function recoverSession(slug, stored, command) {
  // After an idle sleep Chrome comes back from --restore-last-session with NEW tab ids and no
  // window.name tag (group-manager's cmd_await documents it), so the stored session points at
  // nothing. The tab itself is back — in its restored GROUP (Chrome restores a group's title and
  // colour) and at its last address. After a wake EVERY restored tab is ownerless, and two sessions
  // on one address (two WhatsApp pairings) must never swap tabs, so the rule is, in this order:
  //   1. the restored group whose title is this slug — the group IS the name on the strip;
  //   2. else by address — the session's last known URL, then the record's start URL — among tabs
  //      that have no owner and sit in no group titled with ANOTHER known session's slug; the exact
  //      address first, then the origin; and only when exactly ONE tab remains.
  // Two tabs with nothing to tell them apart are answered as "lost", never with a guess.
  const others = await knownSlugs();
  others.delete(slug);
  const titleOf = async (tab) => {
    if (!Number.isInteger(tab.groupId) || tab.groupId < 0) return '';
    try { return (await chrome.tabGroups.get(tab.groupId)).title || ''; } catch (_) { return ''; }
  };
  const wanted = [stored?.lastUrl, command.url].filter(Boolean);
  const free = [];
  for (const tab of await chrome.tabs.query({})) {
    const owner = await ownerForTab(tab.id);
    if (owner && owner !== slug) continue;                 // another session's LIVE tab
    const title = await titleOf(tab);
    if (title && others.has(title)) continue;              // another session's RESTORED tab
    free.push({ tab, title });
  }
  let chosen = null;
  const named = free.filter(entry => entry.title === slug);
  if (named.length) {
    chosen = named.find(entry => wanted.includes(entry.tab.url)) || named[0];
  } else {
    const originOf = (url) => { try { return new URL(url).origin; } catch (_) { return null; } };
    for (const url of wanted) {
      const exact = free.filter(entry => entry.tab.url === url);
      if (exact.length > 1) return null;                   // ambiguous: say so, do not guess
      if (exact.length === 1) { chosen = exact[0]; break; }
      const origin = originOf(url);
      const same = origin ? free.filter(entry => originOf(entry.tab.url) === origin) : [];
      if (same.length === 1) { chosen = same[0]; break; }
    }
  }
  if (!chosen) return null;
  const found = chosen.tab;
  // Session restore brings the group back too (new id, same name); reuse it rather than add one,
  // and a group that has a name of its own keeps it — the record's label is for a group made here.
  const groupId = (Number.isInteger(found.groupId) && found.groupId >= 0)
    ? found.groupId
    : await bounded('tabs.group', chrome.tabs.group({ tabIds: [found.id] }));
  try {
    await chrome.tabGroups.update(groupId, {
      title: chosen.title || command.label || slug,
      ...(command.color && !chosen.title ? { color: command.color } : {}),
      collapsed: false
    });
  } catch (_) {}
  const owned = named.length ? (await chrome.tabs.query({ groupId })).map(tab => tab.id) : [found.id];
  const session = {
    tabId: found.id,
    groupId,
    policy: stored?.policy || 'single',
    generation: stored?.generation || crypto.randomUUID(),
    ownedTabIds: owned.length ? owned : [found.id],
    lastUrl: found.url
  };
  await chrome.storage.local.set({ [`session_${slug}`]: session });
  for (const id of session.ownedTabIds) await claimTab(id, slug);
  return { tab: found, groupId, session, recovered: true };
}

async function frontSession(command) {
  // The human hand-off (handoff.py, DGO-571): bring THIS group's tab to the front of the one shared
  // window — never a new window — and open its group on the strip, so the person who follows the
  // hand-off link lands on the page that needs him, with the group's name above it.
  const slug = command.slug;
  const key = `session_${slug}`;
  const stored = (await chrome.storage.local.get(key))[key];   // read BEFORE existingSession can drop it
  const existing = (await existingSession(slug)) || (await recoverSession(slug, stored, command));
  if (!existing) {
    return { ok: false, error: { code: 'tab_lost', message: `no live tab for ${slug}, and none at its last address` } };
  }
  const tab = await bounded('tabs.update', chrome.tabs.update(existing.tab.id, { active: true }));
  try { await chrome.windows.update(tab.windowId, { focused: true }); } catch (_) {}
  if (Number.isInteger(existing.groupId) && existing.groupId >= 0) {
    try { await chrome.tabGroups.update(existing.groupId, { collapsed: false }); } catch (_) {}
  }
  return { ok: true, tabId: tab.id, groupId: existing.groupId, windowId: tab.windowId, recovered: Boolean(existing.recovered) };
}

async function listSessions() {
  const all = await chrome.storage.local.get(null);
  const sessions = [];
  for (const [key, value] of Object.entries(all)) {
    if (!key.startsWith('session_')) continue;
    const live = [];
    for (const tabId of (value.ownedTabIds || [value.tabId])) {
      try {
        await chrome.tabs.get(tabId);
        live.push(tabId);
      } catch (_) {}
    }
    if (!live.length) continue;
    sessions.push({
      slug: key.slice('session_'.length),
      tabId: value.tabId,
      groupId: value.groupId,
      generation: value.generation,
      ownedTabIds: live,
      openTabs: live.length
    });
  }
  return { ok: true, sessions };
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== 'browser42-offscreen') return;
  port.onMessage.addListener((command) => {
    const operation = command.action === 'allocate'
      ? allocate(command)
      : command.action === 'close'
        ? closeSession(command.slug)
        : command.action === 'status'
          ? statusSession(command.slug)
          : command.action === 'list'
            ? listSessions()
            : command.action === 'claim'
              ? claimSession(command)
              : command.action === 'front'
                ? frontSession(command)
        : Promise.reject(new Error(`unknown action: ${command.action}`));
    operation.then(
      (result) => port.postMessage({ ...result, requestId: command.requestId }),
      (error) => port.postMessage({
        ok: false,
        error: error.message,
        requestId: command.requestId
      })
    );
  });
});

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.type !== 'browser42-whoami' || sender.tab?.id === undefined) return;
  ownerForTab(sender.tab.id).then((slug) => respond({ slug }));
  return true;
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (!changeInfo.status && !changeInfo.url) return;
  const slug = await ownerForTab(tabId);
  if (!slug) return;
  const key = `session_${slug}`;
  if (changeInfo.url) {
    // Where the anchor tab IS, for the hand-off: after an idle sleep the tab comes back with a new
    // id and no tag, and its last address is the only way frontSession finds it again.
    const current = (await chrome.storage.local.get(key))[key];
    if (current && current.tabId === tabId) {
      current.lastUrl = changeInfo.url;
      await chrome.storage.local.set({ [key]: current });
    }
  }
  if (!changeInfo.status) return;
  await claimTab(tabId, slug);
  if (changeInfo.status !== 'complete') return;
  const session = (await chrome.storage.local.get(key))[key];
  if (session?.pendingParentTabId && session.tabId === tabId) {
    const parentId = session.pendingParentTabId;
    delete session.pendingParentTabId;
    await chrome.storage.local.set({ [key]: session });
    try { await chrome.tabs.remove(parentId); } catch (_) {}
  }
});

chrome.tabs.onCreated.addListener(async (tab) => {
  if (tab.openerTabId === undefined) return;
  const slug = await ownerForTab(tab.openerTabId);
  if (!slug) return;
  const key = `session_${slug}`;
  const session = (await chrome.storage.local.get(key))[key];
  if (!session) return;
  const policy = session.policy || 'single';
  if (policy === 'deny-popup') {
    try { await chrome.tabs.remove(tab.id); } catch (_) {}
    return;
  }
  try {
    const groupId = await chrome.tabs.group({ tabIds: [tab.id], groupId: session.groupId });
    session.groupId = groupId;
    if (policy === 'single') {
      session.pendingParentTabId = session.tabId;
      session.tabId = tab.id;
    }
    session.ownedTabIds = [...new Set([...(session.ownedTabIds || []), tab.id])];
    await chrome.storage.local.set({ [key]: session });
    await claimTab(tab.id, slug);
  } catch (_) {}
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const slug = await ownerForTab(tabId);
  if (!slug) return;
  await chrome.storage.local.remove(`owner_${tabId}`);
  const key = `session_${slug}`;
  const session = (await chrome.storage.local.get(key))[key];
  if (!session) return;
  session.ownedTabIds = (session.ownedTabIds || [session.tabId]).filter(id => id !== tabId);
  if (!session.ownedTabIds.length) {
    await chrome.storage.local.remove(key);
    return;
  }
  if (session.tabId === tabId) session.tabId = session.ownedTabIds[0];
  await chrome.storage.local.set({ [key]: session });
});

chrome.runtime.onInstalled.addListener(ensureOffscreen);
chrome.runtime.onStartup.addListener(ensureOffscreen);
chrome.alarms.create('browser42-offscreen', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(ensureOffscreen);
ensureOffscreen();
