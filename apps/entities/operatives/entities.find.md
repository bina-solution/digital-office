---
id: entities.find
title: Who a customer, supplier or contact is — the details the office keeps
title_he: «ישויות» — פרטי לקוח, ספק, חברה או איש קשר
when:
  - מה הפרטים של הלקוח
  - פרטי הספק
  - מה הח״פ של
  - מה הטלפון של
  - מי איש הקשר אצל
  - מי הלקוחות שלנו
  - רשימת הספקים
  - customer details
  - supplier details
inputs: {word: "the name, number or phone that was asked about, with no quote mark in it — or a role (customer, supplier, company, salesperson, contact) for a list"}
reaches_people: false
link: false
check: lines that start with ent_ — id | kind | name | roles | key — or the fields of one entity
---
1. A role asked for as a list (our customers, the suppliers): `./bbox entities list <role>`. Anything else: `./bbox entities list --q '<word>'`.
2. Exactly one line came back and its details were asked for: `./bbox entities show <its ent_ id>`; the block a document would print: `./bbox entities party <id>`.
3. Answer with those lines as they are. No line is said as «לא נמצא ב«ישויות»», never a guessed detail; a failed command is said as it is.
4. This only reads. Adding or changing a person or an organization is `./bbox entities add|set|role` — only when the owner or a document shows the detail.
