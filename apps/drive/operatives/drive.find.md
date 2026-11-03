---
id: drive.find
title: Find a file in the drive by its name
title_he: חיפוש קובץ בדרייב לפי השם
when:
  - תמצא בדרייב את
  - חפש בדרייב
  - איפה הקובץ
  - יש בדרייב קובץ
  - find the file in the drive
inputs: {q: "two letters or more of the file's name, as the person said it; a space is written +"}
reaches_people: false
check: one line per file — created | name | link
---
1. The query is the words the person said for the file's name, as they said them (it is not always an invoice); a space between two words is written +.
2. Search, one line per file:
   - here: `curl -s "http://drive:8975/api/search?q=<q>" | python3 apps/drive/operatives/files.py`
   - linked: `./bbox remote <office> <alias> "/api/search?q=<q>" | python3 apps/drive/operatives/files.py`
3. Answer with those lines, nothing added. "0 files" is "nothing by that name"; a failed answer (exit 1) is said as it is.
