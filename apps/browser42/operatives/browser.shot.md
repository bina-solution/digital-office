---
id: browser.shot
title: Photograph a web page in the office browser
title_he: צילום מסך של אתר בדפדפן הלשכה
when:
  - פתח את הדפדפן על האתר ושלח לי צילום מסך
  - תצלם לי את האתר
  - צילום מסך של האתר
  - screenshot of the page
  - open the office browser on a site and send me a screenshot
inputs: {url: "the address, e.g. bina-solutions.co.il", full: "add `full` for the whole page"}
reaches_people: false
acts: true
link: false
check: the command prints a path ending in screenshots/page.png
---
1. `./bbox b42 shot '<url>'` — or `./bbox b42 shot '<url>' full` for the whole page. It takes up to a minute and a half.
2. Give the printed path. The live view is the console tile «דפדפן הלשכה».
3. A line `could not open <url>: … page_load_failed … <ERROR>` means the page does not load from this office's network: say so, with the error.
