---
id: office.status
title: The office's own state
title_he: מצב הלשכה
when:
  - מה מצב הלשכה
  - הכל עובד
  - כמה קונטיינרים רצים
  - is everything up
  - office status
inputs: {}
reaches_people: false
check: the containers line (up / total, healthy) and the problems it names
---
1. `./bbox status | head -12`
2. Answer with the containers line (up / total, healthy) and each problem it names, one line each.
