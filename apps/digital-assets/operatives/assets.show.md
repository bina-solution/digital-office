---
id: assets.show
title: What the business shows the world — its website's texts and its identity, slot by slot
title_he: הנכסים הדיגיטליים — מה כתוב באתר ובזהות העסק
when:
  - מה כתוב באתר
  - מה הטקסטים של האתר
  - הנכסים הדיגיטליים
  - מה התיאור של העסק
  - website texts
inputs: {word: "one word of what was asked about, to narrow, with no quote mark in it — or nothing"}
reaches_people: false
check: one line per slot — what it is | its key | what it holds now
---
1. The website's texts are not files here: they are in the digital-assets app, and this one command, whole, prints them. The website's texts are `content`; for the name, the logo and the descriptions write `identity` instead:
   - here: `python3 apps/digital-assets/operatives/slots.py content '<word>'`
   - linked: `python3 apps/digital-assets/operatives/slots.py content '<word>' --via <office> <alias>`
2. Answer with those lines, nothing added. A failed answer (exit 1) is said as it is.
