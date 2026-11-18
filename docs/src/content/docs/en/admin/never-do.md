---
title: What not to do
description: Actions that look fine, return no error, and break an office silently.
---

## Summary

Each of the actions here finishes without an error message. The damage shows up later, and looks like a different problem.

## The list

| Do not | What happens | Instead |
|---|---|---|
| A direct `docker compose` | `compose.yml` holds only the shared network. The command finds zero services and exits successfully, having done nothing. | `./bbox` or `./scripts/dc` |
| `docker compose -f apps/<app>/docker-compose.yml` | A second project opens with the same container names. The next `bbox run` stops on «already in use». | `./bbox run` |
| `docker cp` into a container as a deployment | The change lives only until the container is rebuilt, and `bbox run` rebuilds. | `./bbox update <app>` |
| Edit files in `.generated/` | It is the compiler's output. The next run writes it again. | Change `app.json` or `platform.state.yaml` |
| Docker 29 without `DOCKER_MIN_API_VERSION=1.24` | The office's router starts, reports that it is healthy, and routes nothing. With no error. | Docker 28.x, or Docker 29 with `DOCKER_MIN_API_VERSION=1.24` |
| Back up with a `zip` of the folder | The databases, the automations, the documents and the users are outside the folder. The office will start and know nothing. | `./bbox export` |
| Keep secrets outside `.env` | `.env` does not go into `git`. Other files in the repository do. | `.env` |
| `./bbox reset` to «clean up» | The command **deletes all the data**. | `./bbox stop` keeps the data |

## If it already happened

**Strange container names**, starting with 12 characters followed by `_`: these are leftovers of a second project. Remove them and bring the office up again:

```bash
docker ps -a --format '{{.Names}}' | grep -E '^[0-9a-f]{12}_' | xargs -r docker rm -f
./bbox run
```

The first command deletes containers. It does not delete data in volumes.

## See also

- [For agents](/en/for-agents)
- [Backup](/en/backup)
- [Requirements](/en/start/requirements)
