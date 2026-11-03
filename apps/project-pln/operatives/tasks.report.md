---
id: tasks.report
title: Report a bug or a request as a work item
title_he: דיווח על באג או בקשה כפריט עבודה
when:
  - תפתח באג על
  - תדווח על באג
  - תדווח באג
  - יש באג
  - תפתח פריט עבודה על
  - תפתח משימה חדשה
  - תיצור משימה חדשה
  - תיצור משימה
  - תיצור משימת
  - צור משימה בפליין
  - יצור משימה בפליין
  - report a bug
  - open a bug
  - open a ticket for
inputs: {}
reaches_people: false
acts: true
adds: true
check: the new item's DGO-<n> and its link
---
1. `./bbox project-pln report --said` — exactly that, nothing added: it takes the person's own words from this conversation and makes the item of them.
2. Answer with the item's DGO-<n> and its link first, then one line of what it says. If it printed "NOT in Plane", run the one command it printed, once — never the report again.
