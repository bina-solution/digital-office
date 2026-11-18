---
title: Ask Bina
description: Give the office's agent, «Bina», a task and follow it, from the screen or from the terminal.
---

## Why

«Bina» (`bina-ds`) is the office's agent. It does not only answer: it acts in the apps that are on. Each app teaches it how to operate it, in its brief `AGENT.md`.

## Before you start

- «Bina» is on. On a new install it is on.
- You signed in as the owner. «Bina» is for administrators only.
- A key for a language-model service, kept in «Connections». «Bina» knows three: DeepSeek, OpenAI and Anthropic. It is an outside service, and the key is yours.

## From the screen

1. Open the «Azaria» tile in the centre, in the «Main» group.
2. Write the request in your own words. For example: «Find me the file doc.pdf in Files».

![«Bina» in the middle of a task, with the steps it takes](TODO-shot: bina-ds, a conversation with a request to find a file in «Files», demo office, desktop 1440x900, light and dark theme)

## From the terminal

1. **A new task, and follow it to the end:**

   ```bash
   ./bbox agent new -F "Find me the file doc.pdf in Files"
   ```

   `-F` stays attached until the agent's queue is done. Ctrl-C detaches, and the task continues.

2. **Every conversation:**

   ```bash
   ./bbox agent list
   ```

3. **Follow a conversation:**

   ```bash
   ./bbox agent follow <id>
   ```

   `<id>` can be the start of the id, if it is unique.

4. **Add a message to a conversation:**

   ```bash
   ./bbox agent send <id> "The files from last month too"
   ```

5. **Stop:**

   ```bash
   ./bbox agent cancel <id>
   ```

More: `./bbox agent --help`.

## With a file

```bash
./bbox agent new -f ./doc.pdf -F "What does this file say?"
```

## How to check it worked

```bash
./bbox agent doctor
```

The command goes through every step from the terminal to the agent, with timings. When everything is healthy, `./bbox agent list` shows the conversation you opened.

## When something does not work

The codes `bbox agent` exits with:

| Code | Meaning |
|---|---|
| 0 | Fine |
| 1 | Error |
| 2 | Wrong usage |
| 3 | The agent does not answer, or the time ran out |
| 4 | Not found |
| 5 | Permission |
| 6 | The id is not unique |
| 130 | Stopped with Ctrl-C |

## See also

- [Files](/en/use/files)
- [The first hour](/en/start/first-hour)
