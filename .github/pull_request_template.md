## What and why

<!-- One subject per pull request. What changes, and the reason. Link the issue: Fixes #… -->

## Proof

<!-- What you ran and what it answered: the command and its output, or a screenshot of the screen (phone and desktop
     for a screen change). "It should work" is not proof. -->

## Checks

- [ ] The tests near the change pass, and `python3 scripts/refactor/run-gates.py --all` turns no gate red
- [ ] No installation fact (a real address, machine, client or secret) is added to the repository
- [ ] Screens: text goes through the language files, colours through `theme-tokens.css`, and right-to-left holds
- [ ] An AI tool helped write this: yes / no — a person still answers for every line
