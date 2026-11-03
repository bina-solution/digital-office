---
id: diagrams.list
title: The office's architecture diagrams — which exist, and which do not render
title_he: תרשימי הארכיטקטורה של הלשכה
when:
  - איזה תרשימים יש
  - יש תרשים של
  - תרשים של הלשכה
  - תרשימי הארכיטקטורה
  - תראה לי תרשים
  - architecture diagrams
inputs: {}
reaches_people: false
check: 'one line per diagram: its name, title and subtitle — and for one that does not render, the validator''s problems'
---
1. The diagrams the app renders from `apps/archify/diagrams/`:
   - here: `curl -sS --max-time 60 http://archify:8080/api/diagrams`
   - linked: `./bbox remote <office> <alias> /api/diagrams --timeout 60`
2. Over a link, name the office whose diagrams they are; an HTTP status of 400 or more is a failure. Here, a curl error or an answer with no `diagrams` list means archify did not answer. Either way say so, never "no diagrams".
3. Answer one line per entry of `diagrams`: `name`, `title` — `subtitle`. An entry whose `ok` is false is not rendered: say so with its `problems` as they are. Here, one that renders opens at the console's `/a/archify/v/<name>`; a linked office's opens from its «ארכיטקטורה» tile.
4. A diagram states what was measured on one office: say whose. A new or corrected diagram is a source file in git (archify's AGENT.md), never an edit of a rendered page.
