# The leaderboard harness (DGO-1351)

Measures the models of an office machine's Ollama for bina-solutions.co.il/ai-leaderboard/: the same questions in
Hebrew and in English (Belebele, Global-MMLU), translation both ways (FLORES-200, chrF), and a private set of Hebrew
office tasks; a 95% bootstrap interval on every score; speed in its own pass on a quiet machine. The why of each
choice is the docstring of `harness.py`; the public account is /ai-leaderboard/methodology/.

```sh
python3 harness.py fetch  DIR                      # sample the public sets once (seed 20261105) → DIR/sets/
python3 harness.py run    DIR MODEL… --url URL     # answers → DIR/runs/<model>.jsonl (resumable)
python3 harness.py speed  DIR MODEL… --url URL     # speed, with the load average each run began under
python3 harness.py score  DIR                      # → DIR/results.json
sh run-all.sh DIR MODEL…                           # the whole pass on the machine that holds the models
```

- **Where it runs:** on the machine whose models it measures — in the herd that is the Dell (`apps/computers/herd.yaml`
  puts `ollama` there), never the Mac's engine. The 2026-11-05 run: `/mnt/dgo-data/dgo/leaderboard` on the Dell.
- **What it changes:** nothing but its own directory. It pulls no model (`../AGENT.md`: a pull needs the owner's
  go-ahead) and loads the office's resident model again when it ends.
- **The private set** (`DIR/private/office.jsonl`, 40 items) is never committed here and never published: this
  repository is the source of a public release. It lives on the measuring machine's data disk.
- **Results** go to `apps/digital-assets/content/leaderboard/results.json`; `../../digital-assets/content/export_site.py`
  turns them into the page.
