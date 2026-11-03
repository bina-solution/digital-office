---
id: ollama.models
title: The office's local language models — which it holds, which are loaded now
title_he: המודלים המקומיים של הלשכה
when:
  - אילו מודלים מקומיים יש
  - איזה מודלים יש באולמה
  - מה טעון באולמה עכשיו
  - local models
inputs: {}
reaches_people: false
link: false
check: 'one line per model held (name and size), then the ones loaded now — or that Ollama did not answer'
---
1. The models it holds: `./bbox ollama models`
2. What is in memory now, and until when: `./bbox ollama loaded`
3. Answer one line per model held — its name and size — then the loaded ones. "is not running", an `Error` line or a non-zero exit means Ollama did not answer: say so, never "no models".
4. This only reads. Adding or removing a model (a pull is gigabytes) is the owner's, through `OLLAMA_PULL`.
