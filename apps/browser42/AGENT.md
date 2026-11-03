# Operating «דפדפן הלשכה» (the `browser42` app, `bbox b42`)

The office's one shared Chromium: one profile and one cookie jar, signed in to the sites the owner
signed in to once. Use it for a site with no API, to read a page as a person sees it, and to hand a
person a screen (a QR code, a sign-in). The owner watches the same browser live in the tile, so every
tab you open is in front of him.

## From the server's shell

```bash
./bbox b42 page https://example.co.il 4000      # open, take the page's text, close (prints the text)
./bbox b42 shot https://example.co.il full      # open, screenshot, close (prints the image's path)
./bbox b42 session                              # this task's stable slug (--fresh for a clean one)
./bbox b42 task start <slug> <url>              # a task: its own tab group, budget and watchdog
./bbox b42 task inspect|read|screenshot <slug>  # what the task's page shows now
./bbox b42 task goto|click|extract <slug> <arg> # act on the page
./bbox b42 task fill|press <slug> <handle> <value>
./bbox b42 task finish <slug>                   # close it; `bbox b42 groups` lists the live ones
./bbox b42 handoff <slug>                       # the one link for a person: that tab in front, awake
./bbox b42 await <slug> "<conditions>" 280      # block until the PAGE says the person finished
./bbox b42 logins sessions                      # which sites the browser is signed in to
./bbox b42 logins list                          # the saved passwords it holds (not sign-ins)
./bbox b42 sleep status|wake                    # the browser sleeps when idle
```

An unknown verb falls through to `state` (app.json `cli.fallback`).

## From another office or a container

The agent door is `POST http://browser42:8766/v1/task` with `{"argv": ["start", "<slug>", "<url>"]}`,
the same words as `bbox b42 task …`. Over a link: `./bbox b42 task --office <office> …`. The live view is
`/a/browser42/` on the console host. `page` and `shot` are `link: false` operatives: they drive THIS
office's browser only.

## Rules

- **It acts as the owner.** A click on a signed-in site is his click. Read freely; anything that
  submits, buys, sends or deletes on a site needs his go-ahead in his own words.
- **Never type a secret.** `fill` puts its value on a command line, in the task's journal and in
  its answer. `task login <slug> facebook` is the one automated sign-in: it leases the credential
  from the connections vault so it never appears. Any other site is signed in by a person, through
  `handoff` and `await`, or autofilled by `logins materialize`.
- **A person is waited for with `await`, never inside a task.** A task dies after 300 s idle or
  1800 s in all (`task-watchdog.py`); a session tab has no clock.
- One command at a time through the runner (300 s budget), at most 6 tabs. Close what you opened
  (`task finish`, `close <slug>`); `gc` reaps groups idle for 24 h.
- These are the owner's to ask for:
  - `logins sync|materialize|harvest` write the credential plane or the browser's password store,
    and stop and restart the browser when it holds that store;
  - `logins export <site>` writes one catalog row;
  - `state dump|load` stop the browser, and `load` replaces the profile;
  - `state reset --yes` erases every sign-in.

## Traps

- A slug is lowercase kebab and fixed for the task's life.
- The usage line in `hooks/await` names `bbox b42 open`, which does not exist — open the tab with
  `group <slug> <url>` (or `task start`), then `await`.
- A stalled task or an exhausted captcha posts a notice to the owner by itself.

Gates: G35 (no incident fixture in the generic browser surfaces), G17 (the agent door the compiler
publishes), its own tests (`test_*.py`).
