---
id: tasks.done
title: Close a work item as done
title_he: סגור פריט עבודה כבוצע
when:
  - תסגור את הפריט DGO-123
  - סמן את DGO-123 כגמור
  - close work item DGO-123 as done
inputs: {ref: "the item, e.g. DGO-123", proof: "what was done and how it was checked"}
reaches_people: false
acts: true
check: the line shows the item with the state בוצע
---
1. One command, the proof inside single quotes. Every ' in it — also a geresh, as in מס' or צ'ק — is written as ׳:
   `./bbox project-pln tasks done <ref> --comment '<proof>' --as azaria`
2. Say it is closed, with its ref.
