# bina-claude — «בינה קלוד»: Claude inside the office

The official Claude Desktop app (streamed into the console tile «בינה קלוד») and the Claude Code CLI
(the tile «בינה קלוד · מסוף», and the agent.v1 API), signed in to the owner's Claude account. Their
sessions are office data on one volume.

- Every Claude session the office keeps (the desktop app's and the CLI's): `./bbox bina-claude sessions`,
  one conversation: `./bbox bina-claude show <id>` (`--json` on both).
- Ask Claude and wait for the answer: `./bbox bina-claude ask "<text>"`
  (= `./bbox agent --app bina-claude new -F "<text>"`).
- Its API sessions: `./bbox agent --app bina-claude list|show <id>|send <id> "<text>"|follow <id>|log <id>|cancel <id>`.
- Is it up and signed in: `./bbox bina-claude status` (exit 3 = not signed in).
- Signing in is the owner's step (a `בעלים` item): the desktop tile's "Get started", and `/login` in the
  terminal tile. Never type a password or a code for him.
- Claude Code runs with full access to the checkout and the engine, like Azaria, and reaches Azaria with
  `./bbox agent …` from inside its container.
- Never restart bina-claude from a session it is running.
