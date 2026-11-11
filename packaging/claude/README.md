# packaging/claude — הלשכה הדיגיטלית DGO as a Claude plugin

Ask Claude «תתקין לי לשכה דיגיטלית» (or "install DGO") and it installs the office on your own computer: Linux,
macOS or Windows, then hands you the first-admin link. The owner's request, DGO-1802: an agent that is asked to
install the digital office must find the way by itself.

## Use it

In Claude Code:

```
/plugin marketplace add bina-solution/digital-office
/plugin install digital-office@digital-office
```

The marketplace is `.claude-plugin/marketplace.json` at the repository's root, and this folder is its one plugin.
In claude.ai or the Claude apps, upload `skills/install-dgo/` as a skill. Its front matter holds only `name` and
`description`, which is what an upload accepts.

## What is here

| Path | What it is |
|---|---|
| `.claude-plugin/plugin.json` | the plugin's manifest |
| `skills/install-dgo/SKILL.md` | the install skill: the commands of the install guide (`docs/src/content/docs/he/start/`) and of the public README, the steps only the person takes (sudo, the reboot after `wsl --install`, opening the `/setup` link), and what the agent never does (type a password, print `.env`, pass the first-admin link on) |

When the install guide or the README changes a command, this skill changes in the same commit.
