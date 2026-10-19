/**
 * cost-meter — the browser half: the composer's price pill and its settings card.
 *
 * WHAT IT REPLACES, AND HOW. The harness's own footer row is `StatsPills`
 * (`@deepseek-ai/dsh-client-ui-chat`), registered into the `conversation.composer.dock` slot with
 * id `stats`: a "2 סבבים" pill and a "1.9 מיליון" token pill beside it. We do not touch that
 * component — it is not ours to re-render. Instead:
 *
 *   1. this plugin registers a `CostPill` into the SAME dock slot;
 *   2. the pill is portalled into the harness's own stats row (`[data-composer-stats]`), appended as
 *      its last child, so the row reads `turns · price` with the harness's own centring and gap;
 *   3. one CSS rule hides the harness's TOKEN pill — and only while ours has something to show
 *      (`html[data-bina-cost="ready"]`). A missing projection therefore leaves the token pill exactly
 *      as it was, instead of leaving a hole where a number used to be.
 *
 * The rule matches that pill by the icon the harness draws in it (the database cylinder — an
 * `ellipse`; the turns pill's gauge has none), not by position: a positional rule would hide
 * whatever the harness renders LAST after any rebuild, which is the wrong pill on the worst day.
 * The coupling is to one icon inside one pinned harness version (package.json pins every
 * `@deepseek-ai/*` package), and its failure mode is both pills showing rather than none.
 *
 * The portal is the same technique `plugins/voice` uses for the microphone button, and it is
 * deliberate: the harness owns the row's geometry, spacing and theme, and we want the price to
 * inherit all three rather than to sit in a second row of its own.
 *
 * The pill's own CSS is ported from `StatsPills.module.css` (the `pill`/`anchor`/`label` rules) —
 * the harness's class names are hashed per build, so the declarations are what can be copied, with
 * the office's own class names, and the harness's own CSS variables for every colour.
 */
window.__ModuleLoader__.load({
  id: "@bina/dsh-cost-meter",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    const React = require("react");
    const { jsx, jsxs } = require("react/jsx-runtime");
    const { createPortal } = require("react-dom");

    const inject = ["slots", "locale"];

    /** Settings namespace this card edits; the same string the Host registers. */
    const NAMESPACE = "cost-meter";
    /** Projection key the Host publishes; the same string lib/index.js registers. */
    const PROJECTION = "costMeter";

    // ── markup ────────────────────────────────────────────────────────────────────────────────
    /** A coin: two concentric strokes, drawn at the host's 14px so it reads beside the harness's. */
    function IconCoin() {
      return jsxs("svg", {
        viewBox: "0 0 16 16",
        width: 14,
        height: 14,
        "aria-hidden": "true",
        fill: "none",
        children: [
          jsx("circle", { cx: 8, cy: 8, r: 6.25, stroke: "currentColor", strokeWidth: 1.25 }),
          jsx("circle", { cx: 8, cy: 8, r: 2.75, stroke: "currentColor", strokeWidth: 1.25 }),
        ],
      });
    }

    /** The four token rows, in the order the panel shows them. */
    const BUCKET_LABEL = {
      cacheHit: "bucket.cacheHit",
      cacheMiss: "bucket.cacheMiss",
      cacheWrite: "bucket.cacheWrite",
      output: "bucket.output",
    };

    function formatTokens(value) {
      if (value < 1000) return String(value);
      if (value < 1e6) return `${Math.round(value / 100) / 10}K`;
      return `${Math.round(value / 1e5) / 10}M`;
    }

    function formatAmount(amount, currency) {
      const symbol = /^[^\p{L}\p{N}]+$/u.test(currency);
      const text = Math.abs(amount) < 1 ? amount.toFixed(3) : amount.toFixed(2);
      return symbol ? `${currency}${text}` : `${text} ${currency}`;
    }

    // ── the dock: where the price pill lives ───────────────────────────────────────────────────
    /**
     * The harness's stats row, with a holder of ours kept as its last child.
     *
     * WHY A HOLDER AND NOT createPortal(document.body): the pill must sit INSIDE that row to inherit
     * its centring, its gap and its type size. The holder is a plain DOM node React does not own; it
     * is appended LAST so it never becomes the `nextSibling` React inserts its own pills against.
     * @returns the holder element, or null while the harness has no stats row on screen.
     */
    const dock = {
      holder: null,
      ensure() {
        const root = document.querySelector("[data-composer-stats]");
        if (root === null) return null;
        if (this.holder !== null && this.holder.isConnected && this.holder.parentElement === root) return this.holder;
        if (this.holder !== null) this.holder.remove();
        const holder = document.createElement("span");
        holder.className = "bina-cost-holder";
        root.appendChild(holder);
        this.holder = holder;
        return holder;
      },
    };

    /**
     * The composer price pill.
     *
     * Reads the Host's `costMeter` projection — the same `useProjection` the token pill reads — and
     * renders nothing at all when the value is absent (an older Host, a session that has not spent
     * anything, a projection that failed to register). Silence is the honest answer there; the
     * token pill is only hidden while this component is showing money.
     */
    function CostPill({ useProjection, t }) {
      const cost = useProjection(PROJECTION);
      const [host, setHost] = React.useState(null);
      const [open, setOpen] = React.useState(false);
      const ready = cost !== undefined && cost.totalTokens > 0;

      React.useEffect(() => {
        if (!ready) {
          document.documentElement.removeAttribute("data-bina-cost");
          setHost(null);
          return undefined;
        }
        document.documentElement.dataset.binaCost = "ready";
        setHost(dock.ensure());
        const frame = requestAnimationFrame(() => setHost(dock.ensure()));
        return () => {
          cancelAnimationFrame(frame);
          document.documentElement.removeAttribute("data-bina-cost");
          if (dock.holder !== null) {
            dock.holder.remove();
            dock.holder = null;
          }
        };
      }, [ready, cost === undefined ? 0 : cost.totalTokens]);

      if (!ready) return null;
      const pill = jsx(CostPillBody, { cost, t, open, setOpen });
      return host === null ? pill : createPortal(pill, host);
    }

    /** The pill button plus its panel; separated so the portal wraps exactly one element. */
    function CostPillBody({ cost, t, open, setOpen }) {
      const anchorRef = React.useRef(null);
      const label = t("pill.label", { amount: formatAmount(cost.amount, cost.currency) });
      return jsxs("span", {
        ref: anchorRef,
        className: "bina-cost-anchor",
        children: [
          jsx("button", {
            type: "button",
            className: "bina-cost-pill",
            title: t("pill.title", { tokens: formatTokens(cost.totalTokens), amount: formatAmount(cost.amount, cost.currency) }),
            "aria-haspopup": "dialog",
            "aria-expanded": open,
            "aria-label": t("pill.aria", { amount: formatAmount(cost.amount, cost.currency) }),
            onClick: () => setOpen(!open),
            children: jsxs("span", {
              className: "bina-cost-label",
              children: [jsx(IconCoin, {}), formatAmount(cost.amount, cost.currency)],
            }),
          }),
          open && jsx(CostPanel, { cost, t, anchorRef, onClose: () => setOpen(false) }),
        ],
      });
    }

    /**
     * The breakdown, above the pill, as its own element on `document.body`: the composer's own row
     * has `overflow` tuned for one line of text, and a panel inside it would be clipped.
     */
    function CostPanel({ cost, t, anchorRef, onClose }) {
      const ref = React.useRef(null);
      const [style, setStyle] = React.useState(MEASURE);
      React.useEffect(() => {
        const place = () => {
          const anchor = anchorRef.current?.getBoundingClientRect();
          if (anchor === undefined) return;
          const width = Math.min(PANEL.max, window.innerWidth - 16);
          const centred = anchor.left + anchor.width / 2 - width / 2;
          const left = Math.max(8, Math.min(centred, window.innerWidth - width - 8));
          setStyle({ left, width, bottom: window.innerHeight - anchor.top + 8 });
        };
        place();
        window.addEventListener("resize", place);
        return () => window.removeEventListener("resize", place);
      }, [anchorRef]);
      React.useEffect(() => {
        const onPointerDown = (event) => {
          const node = event.target;
          if (node instanceof Node && (ref.current?.contains(node) === true || anchorRef.current?.contains(node) === true)) return;
          onClose();
        };
        const onKeyDown = (event) => {
          if (event.key === "Escape") onClose();
        };
        document.addEventListener("pointerdown", onPointerDown);
        document.addEventListener("keydown", onKeyDown);
        return () => {
          document.removeEventListener("pointerdown", onPointerDown);
          document.removeEventListener("keydown", onKeyDown);
        };
      }, [onClose, anchorRef]);
      const cacheHit = cost.buckets.cacheHit;
      const prompt = cost.buckets.cacheMiss + cost.buckets.cacheWrite;
      const share = cacheHit + prompt > 0 ? Math.round((cacheHit / (cacheHit + prompt)) * 100) : null;
      return createPortal(
        jsxs("div", {
          ref,
          role: "dialog",
          "aria-label": t("panel.title"),
          className: "bina-cost-panel",
          style,
          children: [
            jsxs("div", {
              className: "bina-cost-panel-head",
              children: [
                jsx("span", { className: "bina-cost-panel-title", children: t("panel.title") }),
                jsx("span", { className: "bina-cost-panel-total", children: formatAmount(cost.amount, cost.currency) }),
              ],
            }),
            jsx("div", { className: "bina-cost-rule" }),
            jsx("dl", {
              className: "bina-cost-rows",
              children: cost.rows
                .filter((row) => row.tokens > 0)
                .flatMap((row) => [
                  jsx("dt", { children: t(BUCKET_LABEL[row.bucket]) }, `${row.bucket}-t`),
                  jsxs(
                    "dd",
                    {
                      children: [
                        jsx("span", { className: "bina-cost-tokens", children: t("panel.tokens", { count: formatTokens(row.tokens) }) }),
                        jsx("span", { className: "bina-cost-money", children: formatAmount(row.amount, cost.currency) }),
                      ],
                    },
                    `${row.bucket}-v`,
                  ),
                ]),
            }),
            jsx("div", { className: "bina-cost-rule" }),
            jsxs("p", {
              className: "bina-cost-foot",
              children: [
                jsx("span", { children: t("panel.rate", { rate: cost.rate }) }),
                share !== null && jsx("span", { children: t("panel.cacheHit", { percent: share }) }),
                jsx("span", {
                  children: cost.peakPricing
                    ? t("panel.windows", { peak: formatTokens(cost.peak.tokens), off: formatTokens(cost.offPeak.tokens) })
                    : t("panel.noPeak"),
                }),
                cost.models.length > 0 && jsx("span", { children: t("panel.models", { models: cost.models.join(", ") }) }),
                cost.unpriced.length > 0 &&
                  jsx("span", { className: "bina-cost-warn", children: t("panel.unpriced", { models: cost.unpriced.join(", ") }) }),
              ],
            }),
          ],
        }),
        document.body,
      );
    }

    /** Panel size before its first measurement (one frame, invisible). */
    const MEASURE = { position: "fixed", left: -9999, bottom: 0, width: 320, visibility: "hidden" };
    /** Panel width bounds: readable on a phone, not a wall of text on a desktop. */
    const PANEL = { min: 280, max: 380 };

    // ── the settings card ─────────────────────────────────────────────────────────────────────
    /**
     * One field of the `cost-meter` section: a draft over the stored value, saved explicitly.
     *
     * The Host is the only authority on whether a write was accepted (its schema and validators own
     * the constraints), so a save reads the section back rather than predicting it — and a failed
     * save keeps the draft so it can be corrected instead of retyped.
     */
    function SettingsCard({ scope, t }) {
      const [snapshot, setSnapshot] = React.useState(() => scope.getSnapshot());
      const [drafts, setDrafts] = React.useState({});
      const [busy, setBusy] = React.useState(false);
      const [failed, setFailed] = React.useState(false);
      React.useEffect(() => {
        const update = () => setSnapshot(scope.getSnapshot());
        update();
        return scope.subscribe(update);
      }, [scope]);
      const value = snapshot.value ?? {};
      const field = (key) => (key in drafts ? drafts[key] : format(value[key]));
      const dirty = Object.keys(drafts).filter((key) => {
        const isBoolean = key === "peakPricing";
        const next = isBoolean ? drafts[key] : parse(value, key, drafts[key]);
        return next !== undefined && next !== value[key];
      });
      const set = (key, text) => setDrafts({ ...drafts, [key]: text });
      const save = async () => {
        setBusy(true);
        setFailed(false);
        let landed = true;
        for (const key of dirty) {
          const next = key === "peakPricing" ? drafts[key] : parse(value, key, drafts[key]);
          if (next === undefined) {
            landed = false;
            continue;
          }
          try {
            await scope.set(key, next);
          } catch {
            landed = false;
          }
        }
        if (landed) setDrafts({});
        setBusy(false);
        setFailed(!landed);
        setSnapshot(scope.getSnapshot());
      };
      const reset = (key) => {
        setBusy(true);
        setFailed(false);
        scope
          .unset(key)
          .then(() => {
            // The draft is DROPPED, not emptied: the field re-reads the section, so a cleared
            // override shows the composition value it now inherits instead of a blank box.
            setDrafts((previous) => {
              const next = { ...previous };
              delete next[key];
              return next;
            });
          })
          .catch(() => setFailed(true))
          .finally(() => {
            setBusy(false);
            setSnapshot(scope.getSnapshot());
          });
      };
      const rows = [
        { key: "currency", label: t("card.currency"), hint: t("card.currencyHint"), text: true },
        { key: "usdRate", label: t("card.rate"), hint: t("card.rateHint"), text: false },
      ];
      return jsxs("li", {
        className: "bina-cost-card",
        children: [
          jsxs("div", {
            className: "bina-cost-card-head",
            children: [
              jsx("span", { className: "bina-cost-card-name", children: t("card.title") }),
              jsx("span", { className: "bina-cost-card-desc", children: t("card.description") }),
            ],
          }),
          jsx("div", {
            className: "bina-cost-card-body",
            children: rows.map((row) =>
              jsxs(
                "label",
                {
                  className: "bina-cost-field",
                  children: [
                    jsx("span", { className: "bina-cost-field-label", children: row.label }),
                    jsxs("span", {
                      className: "bina-cost-field-line",
                      children: [
                        jsx("input", {
                          type: "text",
                          inputMode: row.text ? "text" : "decimal",
                          className: "bina-cost-input",
                          value: field(row.key) ?? "",
                          disabled: !snapshot.writable || busy,
                          onChange: (event) => set(row.key, event.target.value),
                        }),
                        jsx("button", {
                          type: "button",
                          className: "bina-cost-link",
                          disabled: !snapshot.writable || busy,
                          onClick: () => reset(row.key),
                          children: t("card.reset"),
                        }),
                      ],
                    }),
                    jsx("span", { className: "bina-cost-field-hint", children: row.hint }),
                  ],
                },
                row.key,
              ),
            ).concat([
              jsxs(
                "label",
                {
                  className: "bina-cost-field",
                  children: [
                    jsxs("span", {
                      className: "bina-cost-field-line",
                      children: [
                        jsx("input", {
                          type: "checkbox",
                          className: "bina-cost-check",
                          checked: "peakPricing" in drafts ? drafts.peakPricing === true : value.peakPricing !== false,
                          disabled: !snapshot.writable || busy,
                          onChange: (event) => setDrafts({ ...drafts, peakPricing: event.target.checked }),
                        }),
                        jsx("span", { className: "bina-cost-field-label", children: t("card.peak") }),
                      ],
                    }),
                    jsx("span", { className: "bina-cost-field-hint", children: t("card.peakHint") }),
                  ],
                },
                "peakPricing",
              ),
            ]),
          }),
          jsxs("div", {
            className: "bina-cost-card-foot",
            children: [
              snapshot.status !== "ready" || !snapshot.writable
                ? jsx("span", { className: "bina-cost-field-hint", children: t("card.readOnly") })
                : null,
              failed ? jsx("span", { className: "bina-cost-warn", children: t("card.failed") }) : null,
              jsx("button", {
                type: "button",
                className: "bina-cost-link",
                disabled: busy || dirty.length === 0,
                onClick: () => setDrafts({}),
                children: t("card.discard"),
              }),
              jsx("button", {
                type: "button",
                className: "bina-cost-save",
                disabled: busy || !snapshot.writable || dirty.length === 0,
                onClick: save,
                children: busy ? t("card.saving") : t("card.save"),
              }),
            ],
          }),
        ],
      });
    }

    /** The draft of one field, as text; booleans never come through here. */
    function format(value) {
      return value === undefined || value === null ? "" : String(value);
    }

    /** A draft back into the type the section declares; undefined when the draft is not a value. */
    function parse(value, key, text) {
      if (typeof text !== "string") return text;
      const trimmed = text.trim();
      if (trimmed === "") return undefined;
      if (typeof value[key] === "number") {
        const parsed = Number(trimmed);
        return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
      }
      return trimmed;
    }

    // ── style ────────────────────────────────────────────────────────────────────────────────
    /**
     * Two blocks. The first is the harness's own pill geometry (ported from
     * `stats-pills.module.css`), so the price looks like the figure it replaced; the second is this
     * plugin's panel and settings card. Every colour is a harness token or an office palette value
     * read through one — a theme switch moves both products together.
     */
    const PANEL_CSS = `
.bina-cost-anchor{min-width:0;display:inline-flex}
.bina-cost-pill{box-sizing:border-box;max-width:100%;color:var(--dsw-alias-label-tertiary);font:inherit;font-variant-numeric:tabular-nums;line-height:inherit;white-space:nowrap;background:0 0;border:none;border-radius:24px;align-items:center;gap:6px;padding:1px 8px;display:inline-flex;cursor:pointer}
.bina-cost-pill:hover,.bina-cost-pill[aria-expanded="true"]{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-secondary)}
.bina-cost-pill svg{flex:none}
.bina-cost-label{display:inline-flex;align-items:center;gap:5px;text-overflow:ellipsis;min-width:0;overflow:hidden}
.bina-cost-holder{display:inline-flex;min-width:0}
html[data-bina-cost="ready"] [data-composer-stats] > span[class*="_anchor"]:has(svg ellipse){display:none}
.bina-cost-panel{position:fixed;z-index:60;box-sizing:border-box;background:var(--dsw-alias-bg-elevated,var(--dsw-alias-bg-base,#fff));color:var(--dsw-alias-label-primary);border:0.5px solid var(--dsw-alias-border-l2);border-radius:12px;box-shadow:var(--dsw-shadow-lg,0 8px 24px rgba(0,0,0,.16));padding:12px;font-size:13px;line-height:1.6;direction:rtl;text-align:right}
.bina-cost-panel-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.bina-cost-panel-title{color:var(--dsw-alias-label-secondary)}
.bina-cost-panel-total{font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}
.bina-cost-rule{height:0.5px;background:var(--dsw-alias-separator-primary);margin:8px 0}
.bina-cost-rows{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:0}
.bina-cost-rows dt{color:var(--dsw-alias-label-secondary)}
.bina-cost-rows dd{display:flex;justify-content:space-between;gap:12px;margin:0;font-variant-numeric:tabular-nums}
.bina-cost-tokens{color:var(--dsw-alias-label-tertiary)}
.bina-cost-money{color:var(--dsw-alias-label-primary)}
.bina-cost-foot{display:flex;flex-direction:column;gap:2px;margin:0;color:var(--dsw-alias-label-tertiary);font-size:12px}
.bina-cost-warn{color:var(--dsw-alias-state-error-primary,#c62828)}
.bina-cost-card{list-style:none;border:0.5px solid var(--dsw-alias-border-l2);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:10px;color:var(--dsw-alias-label-primary)}
.bina-cost-card-head{display:flex;flex-direction:column;gap:2px}
.bina-cost-card-name{font-weight:600}
.bina-cost-card-desc{color:var(--dsw-alias-label-tertiary);font-size:12px}
.bina-cost-card-body{display:flex;flex-direction:column;gap:10px}
.bina-cost-field{display:flex;flex-direction:column;gap:4px}
.bina-cost-field-label{font-size:13px}
.bina-cost-field-line{display:flex;align-items:center;gap:8px}
.bina-cost-field-hint{color:var(--dsw-alias-label-tertiary);font-size:12px}
.bina-cost-input{box-sizing:border-box;width:120px;font:inherit;color:inherit;background:var(--dsw-alias-bg-base,transparent);border:0.5px solid var(--dsw-alias-border-l4);border-radius:8px;padding:4px 8px}
.bina-cost-check{accent-color:var(--dsw-alias-brand-primary)}
.bina-cost-card-foot{display:flex;align-items:center;justify-content:flex-end;gap:12px;flex-wrap:wrap}
.bina-cost-link{color:var(--dsw-alias-label-secondary);background:0 0;border:0;font:inherit;cursor:pointer;padding:4px 2px;border-radius:6px}
.bina-cost-link:hover{background:var(--dsw-alias-interactive-bg-hover)}
.bina-cost-link:disabled{color:var(--dsw-alias-label-tertiary);cursor:default;background:0 0}
.bina-cost-save{background:var(--dsw-alias-button-primary-fill,var(--dsw-alias-brand-primary));color:var(--dsw-alias-label-primary-foreground,#fff);border:0;border-radius:8px;font:inherit;cursor:pointer;padding:5px 14px}
.bina-cost-save:disabled{opacity:.5;cursor:default}
`;

    function installCss() {
      if (typeof document === "undefined" || document.getElementById("bina-cost-css")) return;
      const tag = document.createElement("style");
      tag.id = "bina-cost-css";
      tag.textContent = PANEL_CSS;
      document.head.appendChild(tag);
    }

    // ── dictionaries ─────────────────────────────────────────────────────────────────────────
    const he = {
      "pill.label": "{amount}",
      "pill.aria": "עלות השיחה: {amount}",
      "pill.title": "{tokens} טוקנים · {amount}",
      "panel.title": "עלות השיחה",
      "panel.tokens": "{count} טוקנים",
      "panel.rate": "שער המרה: 1$ = {rate} · מחירי DeepSeek",
      "panel.cacheHit": "פגיעה במטמון {percent}%",
      "panel.windows": "שעות שיא {peak} טוקנים · שעות שפל {off} טוקנים",
      "panel.noPeak": "מחושב לפי מחיר שעות השיא",
      "panel.models": "מודלים: {models}",
      "panel.unpriced": "למודל {models} אין מחיר מפורסם; הוא תומחר לפי מחיר Flash",
      "bucket.cacheHit": "קלט מהמטמון",
      "bucket.cacheMiss": "קלט (לא במטמון)",
      "bucket.cacheWrite": "כתיבה למטמון",
      "bucket.output": "פלט",
      "card.title": "מדד עלות",
      "card.description": "באיזו מטבע מוצגת עלות השיחה, ובאיזה שער ממירים את מחירי הספק.",
      "card.currency": "מטבע",
      "card.currencyHint": "סימן או מילה, למשל ₪ או ILS.",
      "card.rate": "יחידות המטבע לדולר",
      "card.rateHint": "מחירי DeepSeek מפורסמים בדולרים; זה השער שבו הם מוצגים.",
      "card.peak": "חיוב לפי שעות שיא ושפל",
      "card.peakHint": "DeepSeek מחייב חצי מחיר מחוץ לשעות השיא (01:00–04:00 ו־06:00–10:00 UTC).",
      "card.save": "שמירה",
      "card.saving": "שומר…",
      "card.discard": "ביטול השינויים",
      "card.reset": "איפוס",
      "card.readOnly": "בפריסה הזו ההגדרות שמורות לקריאה בלבד.",
      "card.failed": "השמירה לא התקבלה; הערכים נשארו כדי לתקן.",
    };

    const en = {
      "pill.label": "{amount}",
      "pill.aria": "Conversation cost: {amount}",
      "pill.title": "{tokens} tokens · {amount}",
      "panel.title": "Conversation cost",
      "panel.tokens": "{count} tokens",
      "panel.rate": "Rate: $1 = {rate} · DeepSeek prices",
      "panel.cacheHit": "Cache hit {percent}%",
      "panel.windows": "peak {peak} tokens · off-peak {off} tokens",
      "panel.noPeak": "Priced at the peak rate",
      "panel.models": "Models: {models}",
      "panel.unpriced": "{models} has no published price; priced as Flash",
      "bucket.cacheHit": "Cached input",
      "bucket.cacheMiss": "Uncached input",
      "bucket.cacheWrite": "Cache write",
      "bucket.output": "Output",
      "card.title": "Cost meter",
      "card.description": "The currency conversation cost is shown in, and the rate its vendor prices are converted at.",
      "card.currency": "Currency",
      "card.currencyHint": "A symbol or a word, e.g. ₪ or ILS.",
      "card.rate": "Currency units per dollar",
      "card.rateHint": "DeepSeek prices are published in USD; this is the rate they are shown at.",
      "card.peak": "Bill peak and off-peak hours",
      "card.peakHint": "DeepSeek charges half price outside its peak hours (01:00-04:00 and 06:00-10:00 UTC).",
      "card.save": "Save",
      "card.saving": "Saving…",
      "card.discard": "Discard",
      "card.reset": "Reset",
      "card.readOnly": "This deployment keeps settings read-only.",
      "card.failed": "The write was refused; the values stayed so they can be corrected.",
    };

    // ── mount ────────────────────────────────────────────────────────────────────────────────
    function apply(ctx) {
      installCss();
      ctx.effect(() => ctx.locale.register("costMeter", "he", he), "cost-meter: he dictionary");
      ctx.effect(() => ctx.locale.register("costMeter", "en", en), "cost-meter: en dictionary");
      ctx.slots.inject("conversation.composer.dock", () =>
        ctx.slots.register({ name: "conversation.composer.dock", id: "bina-cost", order: 1, locale: "costMeter" }, CostPill),
      );
      ctx.inject(["settingsScope"], (scopeCtx) => {
        const scope = scopeCtx.settingsScope.bind({ namespace: NAMESPACE });
        ctx.slots.inject("settings.plugin.item", () =>
          ctx.slots.register(
            {
              name: "settings.plugin.item",
              key: NAMESPACE,
              locale: "costMeter",
              inject: () => ({ scope }),
            },
            SettingsCard,
          ),
        );
      });
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
