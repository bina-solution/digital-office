---
id: computers.herd
title: The herd — what runs on which office, and what is out of place
title_he: מצב העדר — מה רץ באיזו לשכה
when:
  - מה רץ בכל לשכה
  - מצב העדר
  - מה מצב העדר
  - איפה רצה כל אפליקציה
  - מה צריך לעבור לשכה
  - herd status
inputs: {}
reaches_people: false
link: false
check: 'what it marks, the offices it could not read, and its last line'
---
1. `./bbox computers herd` — once (it reads every office over the links: a minute or more). Exit 1 means it found differences, exit 2 that it could not read.
2. Answer with everything it marks, one line each (what should move and where, what is stopped, missing, left over or runs twice, what is unknown), and name every office it says it did `not read`.
3. Say "the herd matches its plan" only when its last line says so AND no office was `not read`: an office that was not read is not a match.
4. This only reads. Moving an app is the owner's decision, on the apps screen.
