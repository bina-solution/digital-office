# Operating «שלום בינה» (the `hello-bina` app)

A third-party sample app: one static page (Caddy answering one sentence on every path), behind the
office's SSO, framed at `/a/hello-bina/`. It exists to prove that an app can be installed by
reference from a signed catalog, and it is the worked example in
`ai/context/build-your-first-app.md`. It holds no data, needs no secret, and has no API, no hooks
and no health probe.

## Rules

- **It is retired in the herd** (`apps/computers/herd.yaml`: no office runs it), and it ships off.
  Enable it only when the owner asks, for example to test an install path. Then switch it off again.
- `http://hello-bina:80` answers the same body for every path, so it proves the route and the
  sign-in and nothing more.

Gates: G23 (a gallery app ships disabled). G83 names it in its allowance list (a screen with no
state to address).
