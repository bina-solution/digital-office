---
id: n8n.runs
title: What n8n ran in the last hours, what failed, what is still running
title_he: הרצות ה-n8n האחרונות
when:
  - הרצות שרצות עכשיו ב-n8n
  - כמה הרצות נכשלו ב-n8n
  - איזה וורקפלואים נכשלו
  - הרצות שנכשלו ב-n8n
  - יש הרצות תקועות ב-n8n
  - failed n8n executions
inputs: {hours: "the window in hours, a number up to 336: 1 when the person did not say, 24 for a stuck or still-running run, 24 for «today»"}
reaches_people: false
check: 'the executions line with its window, by how they ended, then the workflows that failed most and what still runs, for how long'
---
1. The window's executions, as lines:
   - here: `./bbox any-concurrency executions <hours> | python3 apps/any-concurrency/operatives/runs.py <hours>`
   - linked: `./bbox remote <office> <alias> '/api/executions?hours=<hours>' --timeout 120 | python3 apps/any-concurrency/operatives/runs.py <hours>`
2. Answer with those lines as they are; over a link they start with the office's name. Only runs that started in the window are counted: say the window. If it prints something else (exit 1), the collector did not answer: say so, never "nothing ran".
3. If it says no execution, read whether the collector reads n8n at all, and say that line:
   - here: `./bbox any-concurrency sources | python3 apps/any-concurrency/operatives/runs.py --lane`
   - linked: `./bbox remote <office> <alias> /api/sources --timeout 60 | python3 apps/any-concurrency/operatives/runs.py --lane`
4. This only reads. Re-running, stopping or editing a workflow is not part of it.
