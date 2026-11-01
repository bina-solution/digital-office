# research — the evidence behind the blueprints

Six scans, run 2026-09-29 by parallel research agents (WebSearch/WebFetch only, primary sources
first, every timeline row and spec with a URL; walled platforms are marked as such). Each file ends
with a machine-readable YAML appendix that `build_blueprints.py` reads.

| file | what | appendix |
|---|---|---|
| `umbrel.md` | umbrelOS / Umbrel Home / Pro: every channel, 78-row timeline 2019→2026, 18 repeatable units (the 1–7-day X teaser drip, "Introducing X." reveal, 4:3 bento feature cards, beta→GA pairs, the hardware video series), the App Store listing format (`umbrel-app.yml`) | `# blueprint-input` |
| `n8n.md` | n8n: 22 channels, 88-row timeline, 19 units (weekly release train, GitHub-star milestone cards, community templates, integration pages), the 2019 reveal sequence, the 2022/2025 rebrands | `# blueprint-input` |
| `notion.md` | Notion: 84-row timeline (1.0 on Product Hunt 2016-08-09, 2.0 in 2018), 15 units (numbered release notes, Make with Notion, waitlist → GA in 72–173 days), the template-gallery listing (29 fields) | `# blueprint-input` |
| `startup-patterns.md` | the cross-company skeleton from ten more startups: 14 phases, 45 units with timing relative to D0, cadence table, anti-patterns | `# startup-tail-skeleton` |
| `business-types.md` | business-basic (109 slots, Israeli holiday calendar, accessibility statement, tax-invoice rules) and basic-restaurant (71 slots: menus, kashrut certificate, licensing, signage, delivery listings) + 5 future blueprints | `# business-blueprints-input` |
| `../../social-list/research/platforms.md` | every network's profile fields, image sizes, post limits, API coverage, auth and cost, and its terms on automation → the `api` / `browser` / `handoff` split | `# platform-specs` |

Regenerate the blueprints after refreshing any research file:

```bash
python3 apps/digital-assets/research/build_blueprints.py
```

Third-party brand assets were NOT downloaded — the research describes and links them.
