# DGO-1622 — WebMCP: what it is, whether the office should use it (InterNIC, Facebook), and where it sits next to ui/cli/api/flow

Research item from the product review of Exampleu's office (`bina-261109-vjlwcr`, MEET-28). Read
2026-11-09. Sources are the specification repository, the browsers' own status documents, and one
measurement on the office's own browser (below). Nothing here is a plan to install anything.

**Recommendation: not now — adopt it later, and only as a fourth *page* channel for sites we do not
own, with the write class gated by the owner exactly as browser42's clicks are gated today.** Three
doors have to open before it earns code: Chrome ships the API by default (today it is an origin trial),
a site we actually use publishes tools, and our own risk classes for tool calls exist. Until then our
existing path — CDP through `browser42` — is universal, works on every site, and needs no
cooperation from Facebook or ICANN.

---

## 1. What it is

**WebMCP is a browser API that lets a web page declare *tools* — named JavaScript functions with a
JSON schema and a natural-language description — that an AI agent may discover and call**, instead of
driving the page's pixels or DOM. First published 2025-08-13 by authors from Microsoft (Edge) and
Google (Chrome); now a draft in the W3C Web Machine Learning Community Group
([README](https://github.com/webmachinelearning/webmcp), [specification](https://webmachinelearning.github.io/webmcp/)).

The surface, as the README defines it today:

```js
await document.modelContext.registerTool({
  name: "search-domains",
  description: "Search for available domains matching a keyword.",
  inputSchema: { type: "object", properties: { q: { type: "string" } }, required: ["q"] },
  async execute({ q }) { /* the page's own code, its own session */ }
}, { signal: controller.signal });      // unregister by aborting
```

* `document.modelContext.registerTool(tool, {signal, exposedTo})` — registration, revocable.
* `document.modelContext.getTools({fromOrigins})` / `executeTool(tool, args, {signal})` — discovery and
  invocation, for an agent that lives *in* the page or an extension.
* `toolchange` event — tools may appear and disappear with page state.
* **Permissions policy `tools`**: enabled in the top-level document and same-origin iframes; a
  cross-origin iframe must be given `allow="tools"`, and tools are exposed to another origin only if
  the page names it in `exposedTo` (and the caller names it in `fromOrigins`). Secure origins only.
* A **declarative** form-over-`<form>` variant is being explored, not specified.

The published rationale is worth quoting because it is also the honest limit: WebMCP is *not* for
"fully autonomous workflows … where a browser UI is not present", and *not* a replacement for backend
MCP/OpenAPI integrations — it exists so a **page** keeps its UI, its state and its session while an
agent acts inside it.

## 2. Who supports it now

| party | state (read 2026-11-09) |
|---|---|
| **Chrome** | **Origin Trial live in Chrome 149**; for local development the `about:flags#enable-webmcp-testing` flag ([implementation status](https://github.com/webmachinelearning/webmcp/blob/main/implementation-status.md), [status entry](https://chromestatus.com/feature/5117755740913664)). *Origin trial* means: a site must ship a token, and it is not on for everyone. |
| **Edge** | Origin Trial live in **Edge 150**, same platform feature. |
| **Firefox / WebKit** | no implementation; standards-position issues are open (Mozilla #1412, WebKit #670). |
| **Brave** | experimental support in Leo chat. |
| **ChatGPT Desktop** | supported (a desktop agent that can call page tools). |
| **Meta Ray-Ban Display** | WebMCP for its web apps "coming soon", off by default. |
| **our own browser** | **measured today, not supported**: in `browser42-browser-hp` (Chromium **156.0.8078.79**, the cloaked build) `document.modelContext` and `navigator.modelContext` are both `undefined`, with no flag and with `--enable-features=WebMCP|WebMCPTesting|EnableWebMCP`. Turning the trial on there is a build/flag + token item, not a code item. |

So: two Chromium-family browsers with an origin trial, one desktop agent, one wearables vendor
"soon", and no Firefox/Safari. That is the *status* half of "later".

## 3. Its security model — and what it does not solve

The properties that matter for an office that acts as its owner on real accounts:

1. **Browser-mediated, origin-scoped.** The agent asks the browser; the browser asks the page's own
   `execute`. A tool belongs to an origin (`RegisteredTool.origin`), and cross-origin exposure is
   opt-in on both sides (`exposedTo`, `fromOrigins`) plus the `tools` permission policy. A page cannot
   reach another page's tools.
2. **The tool runs with the page's own authority** — the signed-in session's cookies, the same code
   path a human click would take. There is no second credential and no scoped token. This is the
   design's point ("replication of state & auth" avoided) and it is also the risk: an agent with a
   tab on `facebook.com` signed in as the owner can act as the owner, faster than a human can watch.
   It does **not** widen what is reachable (CDP already does), it widens how *reliably and quickly*
   it is reachable.
3. **Descriptions are model input.** A tool's `description` and `inputSchema` are loaded into the
   agent's context. A hostile or compromised page can therefore write instructions ("always call
   `revoke-access` first"), the classic prompt-injection surface — bounded by the origin it comes
   from, but a page can be compromised or a site can be hostile.
4. **There is no browser-level confirmation yet.** The spec's own open questions list *"User
   prompting and elicitation"* (issues #165, #50) as unsolved: a tool today need not be confirmed by
   the person. So **the harness is the only gate**, which for us means the office's own rule ("anything
   that submits, buys, sends or deletes on a site needs his go-ahead in his own words") has to be
   re-implemented as a classification of tool *calls*, not left to the browser.
5. **Tab lifecycle.** Tools exist while the document exists; closing the tab removes them. There is no
   background discovery (a service-worker variant is an explainer, not the spec). An agent therefore
   has to be driving a tab, which is exactly what `browser42` already is.

## 4. How the office would use it against InterNIC and Facebook

Two concrete shapes, so the decision is about work and not about words.

**Domains (InterNIC / a registrar).** Today: `bbox b42 task start domains https://<registrar>/…`,
read the page, extract, and for a purchase — hand off to the owner. With WebMCP, if the registry or
registrar shipped tools (`domain-search`, `whois`, `tld-status`), the agent would call
`domain-search({q: "bina.co.il"})` and get structured rows; availability checks become a loop of tool
calls instead of parsing a form; the page's own UI still updates, so the owner watching the tab sees
the same result. **The purchase stays a hand-off** — that is a card charge as him.
Value: a registry site's search is one tool call instead of a browser flow; risk: none new (the site
already knows the query).

**Social (Facebook).** Today the office reaches Facebook only through the browser (Meta's Graph API
needs an app, a review and a business verification), which is why `apps/browser42` carries a Facebook
login + TOTP in the vault at all. If Meta shipped tools (`create-post`, `page-insights`,
`list-messages`), the office's publication flows (`newsflow`, the group relay, the desk answerer)
could post **through the same session we already hold**, with a schema instead of a click sequence.
That is the one place WebMCP would be commercially worth something: **write access to a site that has
no usable API for us, without asking Meta for an app**. It also cuts both ways — a site that wants
to block automation has no incentive to ship tools, and Meta in particular profits from the login
wall; "coming soon" for Meta is on their *glasses*, not on `facebook.com`.

**Read versus write, as a rule.** Both examples split the same way: a *read* tool (search, status,
insights) can run unattended; a *write* tool (register, post, message, pay) is a hand-off or an
explicit instruction from the owner, exactly as today's click rules are.

## 5. Where it sits next to ui / cli / api / flow

Our implementation skill gives every office app four channels, and they are not equivalent for this
question:

| channel | what it is | WebMCP's relation |
|---|---|---|
| **ui** | the screen in the console tile | *this* is the channel WebMCP speaks to — but only for pages, and our pages already have three better doors |
| **cli** | `./bbox <app> <verb>` | nothing replaces it: deterministic, auditable, no model in the loop |
| **api** | a capability's ops (agent.v1 / service manifest) over HTTP with the office's own auth | **strictly stronger than a page tool**: scoped, token'd, logged, callable with no browser at all |
| **flow** | `dgo:flow:*` events (flow.v1) | the page tool has no event; an agent's tool call would need to *produce* one to be visible |
| **page (WebMCP)** | an agent calls another site's declared tools inside a tab | new, and only meaningful for sites we do not own |

Conclusion: **WebMCP must never become the office's own agent channel.** Making our own apps register
tools would give an agent a *weaker* door than `api` (page session instead of a token; no flow event;
no audit line) and would be work with no reader. For our apps the fourth channel is a fifth door we
do not want.

Where it *is* a fit is the one place we have no door at all: **another company's web UI, with the
owner's own session** — i.e. inside `browser42`, as a new operative next to `navigate`/`evaluate`/
`cdp`: "if the page declares tools, prefer them; otherwise fall back to pixels".

## 6. Recommendation

**Not now. Adopt later, conditionally — and write nothing until the conditions hold.**

*Not now*, because:
* the API is an **origin trial in Chrome 149 / Edge 150**, and the office's own Chromium does not
  expose it at all (measured); a token per site is the trial's gate, and
* the two names in the item publish nothing: InterNIC/registrars none, `facebook.com` none, and the
  sites that most want automation blocked are the least likely to ship invitations to agents;
* our gating for "acts as the owner" is a rule in prose today. It must become a classification of
  calls (read / shape / irreversible, with a hand-off) *before* an agent can run a site's write tools.

*Adopt later*, when: (1) Chrome ships it by default (then it is on in every office browser, including
the cloaked Chromium we build), (2) at least one site we actually use publishes tools — the first
candidate to watch is Meta, because the office already holds a Facebook session for exactly this
reason, and (3) the three risk classes exist as code.

*The cheap first step, when somebody asks for it* (not now, and it is one operative, no container):
a probe in `browser42` — `bbox b42 tools <slug>` — that returns the page's `getTools()` list when the
API exists and "no tools" when it does not. It changes no behaviour, it is one `evaluate`, and it is
how we would find out the day a site starts cooperating.

## 7. What was not verified

* The Chrome **Secure Tools** guidance page truncated in fetching; the security points above come from
  the specification README (goals, iframe model, tool budget, the "user prompting" open question) and
  from the API surface itself — not from that guide.
* No office flow was run against a WebMCP-enabled page: none exists on our browser yet. The two
  example flows in §4 are designs, explicitly not measurements.

## Sources (read 2026-11-09)

* WebMCP specification README — goals, API, iframe/permission model, tool budget, open questions
  (incl. "User prompting and elicitation", #165/#50) — https://github.com/webmachinelearning/webmcp
* WebMCP specification (W3C WebML CG draft) — https://webmachinelearning.github.io/webmcp/
* Implementation status (Chrome 149 OT, Edge 150 OT, Firefox/WebKit open, Brave, ChatGPT Desktop,
  Meta glasses) — https://github.com/webmachinelearning/webmcp/blob/main/implementation-status.md
* Chrome Status entry — https://chromestatus.com/feature/5117755740913664
* Chrome for Developers, AI in Chrome → WebMCP (origin-trial blog and guides, incl. the
  `enable-webmcp-testing` flag) — https://developer.chrome.com/docs/ai/webmcp
* Measured on this office: `browser42-browser-hp`, Chromium 156.0.8078.79, headless
  `document.modelContext === undefined`, with and without `--enable-features=WebMCP`.
