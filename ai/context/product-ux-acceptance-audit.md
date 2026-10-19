# Product UX acceptance audit — walk the product as a REAL user

The owner's standing requirement. This is the acceptance gate before the client migration, and it
is deliberately NOT a technical health check: `/readyz` going 200 says nothing about whether a
human can use the thing. Walk it as **a business owner who has never seen the system**, on a real
screen, through the real hostname (`console.bbox.dev.bina-solutions.co.il` — never an IP, never a
tunnel), with the client's real connected account.

## The rule that makes this honest

**Judge the experience, not the endpoint.** A screen that renders is not a screen that works. For
every journey below, the question is: *could a business owner do this alone, without me, without
reading anything, without asking what a "protocol" is?* Anything that needs explaining is a defect.

Report each finding as: what a user tried → what happened → why it's wrong → severity.
Screenshot everything. Assume nothing renders correctly until seen.

## The four journeys

### 1. התקנה / onboarding — the first five minutes
Fresh eyes on `מסך התקנה`. Does it say what the system needs and why? Is every "requires you" step
actually actionable? Follow the **guided connect flow** end to end (provider → method → provide →
verify → done): can a user tell WHICH account got connected? Does a failure explain the fix?
⚠ Known: the wizard once reported a PLACEHOLDER Google client as **healthy** (`probe: present` can't
tell a placeholder from a real key) — verify that's gone, it silently misled the customer.

### 2. דרייב — like a drive, not like a sync tool
Folders, files, preview, upload, move, trash, search — with the client's real 600 folders and real
Hebrew names. Is navigation obvious? Does the account bar say which Google account is active?
⚠ The rail (`drive-bs`/`drive-gdoc` + סנכרון/בתהליך/סונכרן/כשל) belongs to INDOX via extension
slots — it must LOOK like it belongs, while drive stays sync-blind (§5b).

### 3. מייל — "the future mail app of Israel"
The real bar. Real Hebrew mail from `person9@example.com`: list, read, search, labels, attachments.
- **Bidi is the #1 killer**: latin addresses (`person10@example.com`) inside RTL Hebrew lines.
- Marketing HTML (AliExpress-grade wide tables) must not blow out the reading pane or leak into the
  shell.
- Thousands of messages: does it stay fast?
- Screen usage: is the reading pane usable, or a cramped strip?

### 4. מסמכים נכנסים / INDOX — does the pipeline read as TRUE?
Dashboard + table against the migrated 45,839 documents. Do the numbers reconcile with the legacy
distribution? Is a stuck document explained, or just a status word? Can a user tell what the system
is doing right now, and what needs THEM?

## Cross-cutting (check on every screen)

- **375 / 768 / 1280 / 1600** — measure overflow, don't eyeball it. (`.acct-warn` overflowed 186px
  @640 while looking fine at desktop; a `nowrap` flex item's min-content width is the whole string.)
- **RTL-native, not RTL-retrofitted.** **Lucide icons only — zero emoji.** Console design language.
- **No dead ends**: every action resolves to a visible state. Every silent no-op is a P1 — that
  exact shape shipped twice (the console→connections 404 CTA; "connected ✓, injected into 0").
- Hebrew everywhere a user reads; errors say what to DO.

## Why this gate exists

Ten bugs on 2026-07-16 were invisible to CI and to a local box, and the worst ones were **silent**:
a green checkmark over a broken thing. CI proves the machine is up. **This audit proves the product
is usable** — it is the only check aimed at the human.

Related: [[platform-service-contract]] §4b/§4c/§5, [[fresh-vps-staging-bringup]],
[[hacohen-legacy-migration-spec]].
