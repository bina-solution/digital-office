window.__ModuleLoader__.load({
	id: "@bina/dsh-client-ui-brand-bina",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		// The same two slots the shipped ui-brand-official fills, in the same registration shape
		// (packages/client/ui-brand-official/src/client/index.ts). The profile replaces that row
		// with this one, so the sidebar names the office agent instead of the harness vendor.
		const { jsx } = require("react/jsx-runtime");
		const inject = ["slots"];
		// The harness prints its own build state ("תצוגה מקדימה" / "Preview") as a pill next to the
		// hero headline — the vendor's word about the vendor's build, on the office's hero. The hero
		// owns its title row here, so the pill is hidden. Matched by the readable CSS-module suffix
		// (the same convention locale-he's RTL rules use) so a harness rebuild that rehashes the
		// prefix does not silently bring it back. Owner decision 2026-09-25.
		const HERO_CSS = '[class*="_previewBadge"]{display:none}';
		// ── the side menu, aligned with the office's own ────────────────────────────────────────
		// Every app in the office carries ONE side menu (platform-base/bina-ui/bina-nav.css), whose
		// metrics were taken from THIS harness's sidebar — 36px rows, 8px radius, a subtle tint for
		// the active row. What did not match was the material: the harness paints its menu from its
		// own palette (a neutral grey, light and dark) while the apps paint theirs from the office's
		// (--surface-2). Two greys, two products, visible the moment a bina panel and a mail panel
		// sit side by side — which is exactly what the owner photographed.
		//
		// So the harness's sidebar tokens are re-pointed at the office's values. NOTHING ELSE moves:
		// the geometry, the states and the behaviour stay the harness's, because those are the parts
		// we copied ON PURPOSE. Owner request 2026-09-29.
		//
		// These are the ONE place the office's colours are written outside its palette file, and G82
		// allows them by name: this page is another product's, it carries no token block, and its
		// dark ground is chosen by ITS switch (data-ds-dark-theme), which no block of ours follows.
		// The values are «Olive Grove»'s (platform-base/bina-ui/theme-tokens.css, DGO-450) —
		// --surface-2, and the side menu's hover and active rows (its ink at 6% and 10% over that
		// fill, as bina-nav.css mixes them) — for the light ground and for the dark one. When the
		// palette changes, these six change with it.
		const OFFICE_CSS = HERO_CSS + `
body{--dsw-specific-sidebar-fill:#f9fafb;--dsw-specific-sidebar-nav-item-hover:#eceeed;--dsw-specific-sidebar-nav-item-active:#e3e5e4}
body[data-ds-dark-theme]{--dsw-specific-sidebar-fill:#192213;--dsw-specific-sidebar-nav-item-hover:#262f21;--dsw-specific-sidebar-nav-item-active:#2f372a}
`;
		// The office's mark: its olive tile, and what is written on olive (the console's own logo tile).
		const MARK = { background: "#56693f", color: "#f3f5f7" };
		function installHeroStyles() {
			if (typeof document === "undefined" || document.getElementById("bina-hero-css")) return;
			const tag = document.createElement("style");
			tag.id = "bina-hero-css";
			tag.textContent = OFFICE_CSS;
			document.head.appendChild(tag);
		}
		function BinaBrandMark({ size }) {
			// A plain glyph at the host-requested size: no asset to load, legible in both themes.
			return jsx("span", {
				"aria-hidden": "true",
				style: { display: "inline-flex", alignItems: "center", justifyContent: "center", width: size, height: size, borderRadius: "22%", ...MARK, fontWeight: 700, fontSize: Math.round((size || 24) * 0.58) + "px", lineHeight: 1 },
				children: "ב",
			});
		}
		function BinaBrandName() {
			return jsx("span", { lang: "he", style: { fontWeight: 700, letterSpacing: "-0.01em" }, children: "בינה" });
		}
		function BinaHeroMark({ size, className }) {
			// The blank-session hero: same glyph, host-requested size and class (the host animates it).
			return jsx("span", {
				className,
				"aria-hidden": "true",
				style: { display: "inline-flex", alignItems: "center", justifyContent: "center", width: size, height: size, borderRadius: "22%", ...MARK, fontWeight: 700, fontSize: Math.round((size || 34) * 0.58) + "px", lineHeight: 1 },
				children: "ב",
			});
		}
		function apply(ctx) {
			installHeroStyles();
			ctx.slots.inject("sidebar.brand.mark", () => ctx.slots.inject("sidebar.brand.name", function* () {
				yield ctx.slots.register({ name: "sidebar.brand.mark" }, BinaBrandMark);
				yield ctx.slots.register({ name: "sidebar.brand.name" }, BinaBrandName);
			}));
			// ui-conversation declares the hero slot and keeps the whale as its own fallback; the
			// registration waits for the slot so a load-order change can never leave a blank hero.
			ctx.slots.inject("conversation.hero.brand.mark", () => ctx.slots.register({ name: "conversation.hero.brand.mark" }, BinaHeroMark));
		}
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
