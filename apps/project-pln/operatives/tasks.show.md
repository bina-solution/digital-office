---
id: tasks.show
title: Show one work item
title_he: הצג פריט עבודה
when:
  - מה זה DGO-123
  - תראה לי את DGO-123
  - מה המצב של DGO-123
  - show DGO-123
inputs: {ref: "the item, e.g. DGO-123"}
reaches_people: false
check: the first line starts with the item's DGO-<n>
---
1. `./bbox project-pln tasks show <ref>`
2. Answer with its title, state and priority, and its link (the last line).
