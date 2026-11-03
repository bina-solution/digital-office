---
id: tasks.comment
title: Comment on a work item
title_he: הערה על פריט עבודה
when:
  - הוסף הערה לפריט DGO-123
  - תכתוב בפריט DGO-123 ש
  - תעדכן בפריט DGO-123 ש
  - comment on work item DGO-123
inputs: {ref: "the item, e.g. DGO-123", text: "the comment, as the person said it"}
reaches_people: false
acts: true
check: 'the command prints "commented on DGO-<n>"'
---
1. One command, the text inside single quotes. Every ' in the text — also a geresh, as in מס' or צ'ק — is written as ׳:
   `./bbox project-pln tasks comment <ref> --comment '<text>' --as azaria`
2. Say it was added, with the item's ref — or the error exactly as printed.
