---
id: tasks.open
title: What is open, and what is next
title_he: מה פתוח ומה הבא בתור
when:
  - מה המצב
  - מה המצב של המשימות
  - מה פתוח
  - מה הבא בתור
  - מה נשאר לעשות
  - על מה עובדים עכשיו
  - אילו משימות פתוחות יש
  - what's the status
  - what is left to do
  - what's next
inputs: {}
reaches_people: false
check: a few lines, each starting with an item key (<PROJECT>-<n>)
---
1. In progress, urgent and high: `./bbox project-pln tasks list --state started | grep -E ' (urgent|high) ' | head -8`
2. Next in line, urgent: `./bbox project-pln tasks list --state backlog | grep -E ' urgent ' | head -5`
3. Answer in at most 13 lines, one per item: its key exactly as the list prints it (each office has its own projects, so the prefix is the office's) and its title — in progress first, then next. Do not copy more than that. An empty or failed answer is said as it is.
