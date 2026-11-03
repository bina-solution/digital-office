---
id: dgo.links
title: The linked offices — is each link up
title_he: מצב הקישורים ללשכות האחרות
when:
  - מה מצב הקישורים
  - הלשכות מחוברות
  - האם ה-HP מחובר
  - יש קשר ללשכה
  - are the offices linked
inputs: {}
reaches_people: false
link: false
check: 'for each linked office: answers up or down, and its handshake'
---
1. `./bbox dgo link status` — exactly that.
2. For each office marked `link` (skip one marked `-`), answer one line: its name, `answers:` (up, down or unknown), the `handshake:` it prints (how long ago, never, or not measured, and "the tunnel is DEAD" when it says so), and its `path:` line when there is one.
3. If it prints that dgo-extend is not answering, say exactly that. Why a link went down is in `./bbox dgo link history` — read it only when asked why.
4. Never bring a link up or down, pair or unpair from this. A link that does not heal by itself is a report (`tasks.report`), not an action.
