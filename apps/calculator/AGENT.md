# Operating «מחשבון» (the `calculator` app)

A four-operation calculator, one page, one stdlib server (`server.py`, no dependencies). It exists for two
reasons: it is what the office *builds in a minute* in the intro film (the app that is born in the dock while
the person watches), and it is the smallest honest example of the shape every office app has —
`app.json` + `docker-compose.yml` + `Dockerfile` + one page.

- It holds no data, no secret and no connection.
- `/healthz` answers `{"ok":true}`; everything else is `static/index.html`.
- It is enabled and disabled like any app (`./bbox apps enable|disable calculator`), and its arrival in the
  desktop dock is animated (a kind that was not on the row a moment ago).
