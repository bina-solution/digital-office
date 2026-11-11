---
id: claude.ask
title: Hand a task to Claude (bina-claude) and bring back his answer
title_he: העברת משימה לקלוד
when:
  - שאל את קלוד
  - תשאל את קלוד
  - תעביר לקלוד
  - תעביר את זה לקלוד
  - בקש מקלוד
  - תבקש מקלוד
  - תן לקלוד
  - שקלוד יעשה את זה
  - ask claude
  - hand it to claude
inputs: {title: "a short title for the task, in the person's language — words only, no quote marks, $ or backticks", request: "the person's request word for word, then what you already found or tried, if anything"}
reaches_people: false
acts: true
adds: true
link: false
check: 'the output has a «turn 1 ended» line and Claude''s answer above it — or the error exactly as printed'
---
1. Write the request with the file tool to the file /tmp/claude-ask.md: `<request>`, word for word. If you already ran commands for it, add their output under a line «מה כבר נבדק:».
2. Hand it over, with bash — it waits until Claude's turn ends, which can take minutes:
   `if [ -n "$(find /tmp/claude-ask.md -mmin -10 -size +0c 2>/dev/null)" ]; then ./bbox agent --app bina-claude new -t "<title>" -F - < /tmp/claude-ask.md; else echo "NOT SENT: /tmp/claude-ask.md is empty or was not written just now"; fi; rm -f /tmp/claude-ask.md`
3. Give the person Claude's answer as it came (the text after «▶ turn 1»), and the session's id (the line «attached to local_…»).
   - If the bash call timed out, the session goes on: read the answer with `./bbox agent --app bina-claude log <local_… id>`.
   - An error line, or no answer, is said exactly as printed. Never write an answer yourself in Claude's name.
