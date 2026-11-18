---
title: Glossary
description: Every word of the digital office, defined once.
---

## Words

| Word | Hebrew | What it is |
|---|---|---|
| office | לשכה | One computer that runs DGO, with one `.env`. |
| DGO | Digital Office | The digital office: the office's operating system. |
| Console (the centre) | המרכז | The screen that holds all the office's apps, each as a tile. |
| tile | אריח | An app as it appears in the centre. Its address in the centre: `#/m/<id>`. |
| app | אפליקציה | One folder with one `app.json`. |
| layer | שכבה | 0 the compiler (`platform/`), 1 and 2 the base (`platform-base/`), 3 the products (`apps/`). |
| declaration | הצהרה | `app.json` and `platform.state.yaml`: what the office should run. |
| compiler | מהדר | `platform/manager/reconcile.py`: reads the declarations and builds `.generated/`. |
| `.generated/` | | The compiler's output. Not edited, and not committed to `git` by hand. |
| `bbox` | | The office's command. On Windows: `bbox.cmd`. `bbox help` shows every command. |
| four channels | ארבעת הערוצים | Screen, command, HTTP API, event stream. |
| engine | מנוע | The Docker that runs the office. On macOS a virtual machine of its own, on Windows inside WSL. |
| `.env` | | The office's settings and secrets file. Does not go into `git`. |
| sign-in | כניסה | One sign-in for every app. On a new office through `forward-auth` («Identity and sign-in»). |
| connection | חיבור | A key or a sign-in for an outside service, kept in «Connections». |
| App Management | ניהול אפליקציות | The screen that turns apps on and off. |
| enable, disable | להדליק, לכבות | `bbox apps enable` and `bbox apps disable`. The data is always kept. |
| agent | סוכן | The office's agent, «Bina» (`bina-ds`). |
| brief | תדריך | An app's `AGENT.md`: what the agent learns about it. |
| instance | מופע | One office serves several instances. |
| herd | עדר | Several linked offices working as one business. |
| link | קישור | A connection between two offices, through «Office extension» (`dgo-extend`). |
| Office extension (`dgo-extend`) | הרחבת הלשכה | The app that links offices. |
| Computers | מחשבים | The app that knows the herd's computers. |
| edge | קצה | `traefik`: receives every request and passes it to the app. |
| gate | שער | An automatic check of the repository, with a number (for example G7). |

## See also

- [The concepts](/en/concepts)
