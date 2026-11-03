---
id: security.summary
title: Who reached the office, and was anything blocked
title_he: מצב האבטחה של הלשכה
when:
  - מה מצב האבטחה
  - מה מצב האבטחה בלשכה
  - אבטחת הלשכה
  - מי ניסה להיכנס ללשכה
  - יש חסימות בלשכה
  - כמה בקשות היו ללשכה
  - security summary
inputs: {hours: "the window in hours, a number; 24 when the person did not say"}
reaches_people: false
check: 'one line with requests, addresses, failed sign-ins, bans and the mode — or that the collector is not reading'
---
1. The window's numbers:
   - here: `curl -s 'http://security:8995/api/summary?hours=<hours>'`
   - linked: `./bbox remote <office> <alias> '/api/summary?hours=<hours>'`
2. First read `health`: if `health.edge.ok` or `health.auth.ok` is not true, say the security collector is not reading — zero then means "not measured", never "quiet".
3. Otherwise answer in one line from its `kpi` and `mode`: requests, addresses (`addrs`), countries, failed sign-ins (`signin_fail`), bans, would-ban, and whether the office observes or enforces. A failed answer is said as it is.
4. Never ban, unban or change the mode from this: those are the owner's, on the security screen.
