/**
 * vault-key — the browser half: «בחר מהסודות» on the Models page's provider card.
 *
 * WHERE IT SITS. `@deepseek-ai/dsh-client-ui-settings-models` declares one extension seat on every
 * provider row — the keyed slot `settings.models.provider-card`, keyed by the row's settings
 * namespace — and hands a registrant `{provider, configured, keyConfigured}`. That seat exists for
 * exactly this: an adapter family's companion plugin adding a control the row does not have, without
 * editing the row. Nothing here touches the harness's own components.
 *
 * WHAT IT ADDS. The API-key field on that page can only be PASTED INTO. This row says where the key
 * actually comes from, and lets a person point the reference at one of the office's vault
 * connections instead: «בחר מהסודות» → the office's API-key connections → pick one. The pick writes
 * `vault:<connection-id>` as the reference's value (the same `credentials/set` route the pasted key
 * uses), and the host half (`lib/index.js`) resolves that pointer from `connections` on every
 * request. The key therefore never sits in this browser, in the harness's settings file, or on the
 * harness volume — and rotating it in the vault reaches the next request with no restart.
 *
 * HOW IT KNOWS WHICH REFERENCE IS WHICH. The card's own reference is not in the seat's props, so the
 * table below names it per provider route — the same derivation the page uses
 * (`<ROUTE>_API_KEY`), written down once so a route we have no connection for shows nothing at all
 * rather than a button that would write to a reference nobody reads.
 *
 * THE BINDING IS READ BACK FROM THE HOST, not remembered here: `credentials.describe` returns
 * `source: "office-vault:<connection>"` for a bound reference (the field the harness's credential
 * API passes through unchanged), so the row is right after a reload, after another tab changed it,
 * and after the vault connection was emptied.
 */
window.__ModuleLoader__.load({
  id: "@bina/dsh-vault-key",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    const React = require("react");
    const { jsx, jsxs } = require("react/jsx-runtime");

    /** Dictionary namespace this plugin owns. */
    const NS = "vaultKey";

    /** Where each provider route's key reference lives, and which connections may back it. */
    const OFFERS = {
      deepseek: {
        ref: "DEEPSEEK_API_KEY",
        connections: [{ id: "deepseek-key", title: "DeepSeek API key" }],
      },
      openai: {
        ref: "OPENAI_API_KEY",
        connections: [{ id: "openai-key", title: "OpenAI API key" }],
      },
      anthropic: {
        ref: "ANTHROPIC_API_KEY",
        connections: [{ id: "anthropic-key", title: "Anthropic API key" }],
      },
    };

    /** The settings namespaces the Models page draws provider cards for. */
    const FAMILIES = ["llm-deepseek", "llm-pi-ai"];

    /** The connection a `describe().source` names, or `null` when the value is a literal key. */
    const BOUND = /^office-vault:([a-z0-9][a-z0-9-]*)$/;

    // ── the office vault, as this page uses it ───────────────────────────────────────────────────
    /**
     * The vault-facing surface the card talks to. Every call goes through the harness's own
     * credential API — no new route, no value crossing back into the browser.
     * @param ctx - browser plugin context (its `remote.credentials` is the credential API).
     * @returns the surface the component injects.
     */
    function vaultApi(ctx) {
      const listeners = new Set();
      const offer = (providerId) => (typeof providerId === "string" ? OFFERS[providerId] : undefined);

      /**
       * Read one reference: whether the host holds a value, and which connection is behind it.
       * @param ref - the credential reference.
       * @returns `{configured, connection, error}`; `error` only for a failed read.
       */
      async function describe(ref) {
        try {
          const response = await ctx.remote.credentials.describe([ref]);
          if (!response.ok) return { configured: false, connection: null, error: response.error?.message };
          const view = response.value?.[ref];
          const match = typeof view?.source === "string" ? BOUND.exec(view.source) : null;
          return {
            configured: view?.configured === true,
            connection: match === null ? null : match[1],
            error: undefined,
          };
        } catch (error) {
          return { configured: false, connection: null, error: error instanceof Error ? error.message : String(error) };
        }
      }

      /**
       * Point one reference at one of the office's vault connections.
       * @param ref - the credential reference.
       * @param connection - the vault connection id.
       */
      async function bind(ref, connection) {
        await ctx.remote.credentials.set(ref, `vault:${connection}`);
      }

      /**
       * Stop pointing a reference at the vault. The reference reads as unconfigured afterwards: a
       * vault binding is a pointer, so removing it leaves nothing behind to fall back to.
       * @param ref - the credential reference.
       */
      async function unbind(ref) {
        await ctx.remote.credentials.unset(ref);
      }

      return {
        offer,
        describe,
        bind,
        unbind,
        subscribe(listener) {
          listeners.add(listener);
          return () => listeners.delete(listener);
        },
        emit(ref) {
          for (const listener of listeners) listener(ref);
        },
      };
    }

    // ── the stylesheet ──────────────────────────────────────────────────────────────────────────
    const CSS = `
.bina-vk{display:flex;flex-direction:column;gap:6px;margin-top:10px;padding-top:10px;border-top:.5px solid var(--dsw-alias-border-l2)}
.bina-vk-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.bina-vk-label{color:var(--dsw-alias-label-secondary);font-size:12px;line-height:18px}
.bina-vk-value{color:var(--dsw-alias-label-primary);font-size:12px;line-height:18px;font-weight:500}
.bina-vk-id{font-family:var(--ds-font-family-code);color:var(--dsw-alias-label-tertiary);font-size:11px;line-height:16px;direction:ltr;unicode-bidi:isolate}
.bina-vk-action{margin-inline-start:auto;box-sizing:border-box;border:.5px solid var(--dsw-alias-border-l3);color:var(--dsw-alias-label-primary);background:0 0;border-radius:14px;height:26px;padding:0 10px;font:inherit;font-size:12px;line-height:18px;cursor:pointer;display:inline-flex;align-items:center;gap:4px}
.bina-vk-action:hover:not(:disabled){background:var(--dsw-alias-interactive-bg-hover)}
.bina-vk-action:disabled{opacity:.4;cursor:default}
.bina-vk-list{display:flex;flex-direction:column;gap:2px;margin:2px 0 0;padding:0;list-style:none}
.bina-vk-option{display:flex;align-items:center;gap:8px;width:100%;box-sizing:border-box;text-align:start;background:0 0;border:.5px solid transparent;border-radius:8px;padding:6px 8px;font:inherit;cursor:pointer;color:var(--dsw-alias-label-primary)}
.bina-vk-option:hover:not(:disabled){background:var(--dsw-alias-interactive-bg-hover)}
.bina-vk-option:disabled{opacity:.5;cursor:default}
.bina-vk-option[aria-current="true"]{border-color:var(--dsw-alias-brand-primary)}
.bina-vk-option-title{font-size:12px;line-height:18px}
.bina-vk-note{color:var(--dsw-alias-label-tertiary);margin:0;font-size:11px;line-height:16px}
.bina-vk-error{color:var(--dsw-alias-state-error-primary);margin:0;font-size:11px;line-height:16px}
`;

    /**
     * Append the stylesheet once per page.
     */
    function installCss() {
      if (typeof document === "undefined" || document.getElementById("bina-vault-key-css")) return;
      const tag = document.createElement("style");
      tag.id = "bina-vault-key-css";
      tag.textContent = CSS;
      document.head.appendChild(tag);
    }

    // ── the card's extension row ───────────────────────────────────────────────────────────────
    /**
     * One provider card's vault area: where the key comes from, and the one gesture that moves it.
     * @param props - the seat's owner props plus this plugin's injected surface.
     */
    function VaultRow({ provider, keyConfigured, t, vault }) {
      const offer = vault.offer(provider === undefined ? undefined : provider.provider);
      const ref = offer === undefined ? undefined : offer.ref;
      const [state, setState] = React.useState({ configured: false, connection: null, error: undefined });
      const [open, setOpen] = React.useState(false);
      const [busy, setBusy] = React.useState(false);
      const [failure, setFailure] = React.useState(null);

      const read = React.useCallback(async () => {
        if (ref === undefined) return;
        setState(await vault.describe(ref));
      }, [ref, vault]);

      React.useEffect(() => {
        if (ref === undefined) return undefined;
        void read();
        const off = vault.subscribe((changed) => {
          if (changed === ref) void read();
        });
        return off;
      }, [ref, read, vault]);

      // The page's own credential join is the cheapest re-read trigger after a write from anywhere.
      React.useEffect(() => {
        if (ref !== undefined) void read();
      }, [keyConfigured, ref, read]);

      if (ref === undefined) return null;

      const boundTitle = (connection) => {
        const found = offer.connections.find((candidate) => candidate.id === connection);
        return found === undefined ? connection : found.title;
      };

      const choose = async (connection) => {
        setBusy(true);
        setFailure(null);
        try {
          await vault.bind(ref, connection);
          await read();
          setOpen(false);
        } catch (error) {
          setFailure(error instanceof Error ? error.message : String(error));
        } finally {
          setBusy(false);
        }
      };

      const detach = async () => {
        setBusy(true);
        setFailure(null);
        try {
          await vault.unbind(ref);
          await read();
        } catch (error) {
          setFailure(error instanceof Error ? error.message : String(error));
        } finally {
          setBusy(false);
        }
      };

      const bound = state.connection;
      const value = bound !== null
        ? t("row.bound", { title: boundTitle(bound) })
        : state.configured
          ? t("row.pasted")
          : t("row.empty");

      return jsxs("div", {
        className: "bina-vk",
        dir: "rtl",
        children: [
          jsxs("div", {
            className: "bina-vk-row",
            children: [
              jsx("span", { className: "bina-vk-label", children: t("row.label") }),
              jsx("span", { className: "bina-vk-value", children: value }),
              bound === null ? null : jsx("span", { className: "bina-vk-id", children: bound }),
              jsx("button", {
                type: "button",
                className: "bina-vk-action",
                disabled: busy,
                onClick: () => setOpen((was) => !was),
                children: open ? t("row.close") : t("row.pick"),
              }),
              bound === null ? null : jsx("button", {
                type: "button",
                className: "bina-vk-action",
                disabled: busy,
                onClick: () => { void detach(); },
                children: t("row.detach"),
              }),
            ],
          }),
          open
            ? jsxs("ul", {
                className: "bina-vk-list",
                children: offer.connections.map((connection) =>
                  jsx("li", {
                    children: jsxs("button", {
                      type: "button",
                      className: "bina-vk-option",
                      "aria-current": connection.id === bound ? "true" : "false",
                      disabled: busy,
                      onClick: () => { void choose(connection.id); },
                      children: [
                        jsx("span", { className: "bina-vk-option-title", children: connection.title }),
                        jsx("span", { className: "bina-vk-id", children: connection.id }),
                      ],
                    }),
                  }, connection.id)),
              })
            : null,
          jsx("p", { className: "bina-vk-note", children: t("row.note") }),
          failure === null ? null : jsx("p", { className: "bina-vk-error", children: failure }),
          state.error === undefined ? null : jsx("p", { className: "bina-vk-error", children: state.error }),
        ],
      });
    }

    const he = {
      "row.label": "מקור המפתח",
      "row.bound": "מהסודות של הלשכה: {title}",
      "row.pasted": "מפתח שהוקלד כאן (נשמר אצל בינה)",
      "row.empty": "לא מוגדר",
      "row.pick": "בחר מהסודות",
      "row.close": "סגור",
      "row.detach": "נתק",
      "row.note": "המפתח נמשך מהסודות בכל בקשה — הוא לא נשמר בדף הזה.",
    };

    const en = {
      "row.label": "Key source",
      "row.bound": "From the office vault: {title}",
      "row.unknown": "From the office vault",
      "row.pasted": "Typed here (stored by Bina)",
      "row.empty": "Not configured",
      "row.pick": "Pick from secrets",
      "row.close": "Close",
      "row.detach": "Detach",
      "row.note": "The key is read from the vault on every request — it is not stored in this page.",
    };

    /** Required browser services (cordis fiber inject). */
    const inject = ["slots", "locale", "remote", "remote.credentials"];

    /**
     * Mount the provider-card row for every Models family this office ships.
     * @param ctx - browser plugin context.
     */
    function apply(ctx) {
      installCss();
      ctx.effect(() => ctx.locale.register(NS, "he", he), "vault-key: he dictionary");
      ctx.effect(() => ctx.locale.register(NS, "en", en), "vault-key: en dictionary");

      const vault = vaultApi(ctx);

      // A write that changes a bound reference anywhere (the vault, another tab, the Models page
      // itself) refreshes this row: the binding is a fact the HOST owns, so it is re-read, never
      // tracked locally.
      ctx.effect(
        () => ctx.remote.$on("credentials/reference-updated", (ref) => vault.emit(ref)),
        "vault-key: credential invalidations",
      );

      for (const family of FAMILIES) {
        ctx.slots.inject("settings.models.provider-card", () =>
          ctx.slots.register(
            {
              name: "settings.models.provider-card",
              key: family,
              order: 20,
              locale: NS,
              inject: () => ({ vault }),
            },
            VaultRow,
          ));
      }
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
