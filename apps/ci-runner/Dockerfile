# ci-runner's screen, API and CLI — the standard library only. ONE Python base across every first-party service
# (see platform-base/machine/Dockerfile for why 3.12 and not a per-service tag).
FROM python:3.12-slim
WORKDIR /app
# Every module of the app, not a list of names: a list silently drops the next module someone adds.
COPY *.py ./
# the job door's named jobs (door.py reads it beside itself; without it the door runs nothing)
COPY jobs.json ./
COPY static/ ./static/
EXPOSE 8988
CMD ["python", "server.py"]
