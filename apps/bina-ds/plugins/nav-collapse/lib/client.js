window.__ModuleLoader__.load({
	id: "@bina/dsh-client-ui-nav-collapse",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		// ── the agent's own navigation, folded away completely ─────────────────────────────────
		// THE PROBLEM (owner, 2026-10-12, from a phone): «כרגע זה משתמש במסך יקר בלי אפשרות לקפל».
		// On a narrow frame the harness auto-collapses its sidebar to a 56px rail
		// (`SIDEBAR_COLLAPSED`, ui-layout/columns) and there is no state below that: the rail IS the
		// control that reopens the menu, so the harness cannot remove it and stay reachable. On a
		// 390px phone that rail is 15% of the width, on every screen, forever.
		//
		// WHAT THIS ADDS: one state — `html[data-bina-compact]` — in which the two side columns are
		// not drawn at all, and a way back that is drawn INSTEAD of them. Nothing about the harness's
		// own geometry is written: the columns keep their widths in the layout store, so leaving the
		// state puts everything back exactly as it was (a close that forgot the user's width — which
		// is what `ctx.layout.toggleSidebar()` does — would be a worse answer than not closing).
		//
		// WHO WRITES WHAT, one writer each:
		//   · the app writes its own state here (the toggle, this page's storage);
		//   · the console writes ITS state on this same document (`data-shell-focus`), exactly as it
		//     already writes `data-theme` on the frame's document — because on a phone the shell's
		//     chrome and the app's navigation are the same decision, made by one gesture.
		//   · the button that folds it lives in the conversation header, beside the app's own (see
		//     `placeTwin`), and while the shell is in full screen it is not drawn at all: the shell's
		//     chip is the way back, and two doors side by side is one door too many.
		const COLLAPSE_ATTR = "data-bina-compact";   // ours
		const SHELL_ATTR = "data-shell-focus";       // the console's, read-only here
		const OVER_ATTR = "data-bina-menu-over";     // ours: the narrow frame's sheet (see below)
		const STORE_KEY = "dsh.navCollapsed";        // the remembered choice
		// The harness's own narrow breakpoint (`SIDEBAR_AUTO_COLLAPSE`, ui-layout): below it the frame
		// answers a request for the sidebar with arithmetic instead of an overlay — `computeColumns()`
		// keeps the sidebar's preferred width (264–420px) and hands the centre the remainder.
		const NARROW_PX = 1024;

		// A COLUMN IS HIDDEN BY ITS TRACK, NOT BY `display:none` — measured on a real instance, and
		// it is the one trap here: `display:none` removes the element from the grid, the centre
		// becomes the first item and is auto-placed into the ZERO-width track, and the conversation
		// ends up 0px wide inside a frame that reports the right columns. The columns therefore stay
		// placed (visibility + the 0 track + their own overflow:hidden) and only their pixels go.
		//
		// The harness's own class names, matched by the readable CSS-module SUFFIX — the same
		// convention `brand-bina` uses for `_previewBadge` and locale-he for its RTL rules, so a
		// harness rebuild that rehashes the prefix does not silently bring the columns back. Read off
		// the pinned build's AppFrame.module.css: `_frame` is the grid, `_sidebarCol`/`_rightbarCol`
		// are the two columns, `_handle` the drag handles that would otherwise stay draggable.
		const FRAME = '[class*="_frame"]';
		const COLS = '[class*="_sidebarCol"],[class*="_rightbarCol"]';
		const SIDEBAR_COL = '[class*="_sidebarCol"]';
		const HANDLES = '[class*="_handle"]';
		// What a tap INSIDE the menu means (DGO-552, below). Read off the live menu on 2026-10-14 —
		// tags, roles and classes of the app's own rows — never assumed: a session is
		// `[class*="_sessionRow"]`, the app's two doors to a new conversation are `_newSession` and the
		// brand button beside it, and the cluster they must NOT be confused with is `_rowActions` (the
		// «פעולות לשיחה …» button that sits one tap away from the row itself).
		const SESSION_ROW = '[class*="_sessionRow"]';
		const ROW_ACTIONS = '[class*="_rowActions"]';
		const NEW_DOORS = ['[class*="_newSession"]', '[class*="_brand"]'];
		const NEW_SESSION_RE = /שיחה חדשה|new (chat|conversation)/i;
		// The sheet's width is the width the HARNESS itself computed for the sidebar (its default, or
		// the reader's own drag) — read from the frame's own inline track and parked on the root as a
		// custom property, so the sheet keeps the reader's width instead of inventing one.
		const MENU_W_VAR = "--bina-menu-w";
		// The office's palette, by value: this page is another product's and carries no token block
		// (the same allowance brand-bina documents for the sidebar fills — olive and its ink).
		const CSS = `
html[${COLLAPSE_ATTR}] ${FRAME}{grid-template-columns:0 minmax(0,1fr) 0!important}
html[${COLLAPSE_ATTR}] ${COLS}{visibility:hidden!important;overflow:hidden!important}
html[${COLLAPSE_ATTR}] ${HANDLES}{display:none!important}
/* ── a NARROW frame draws the menu OVER the conversation, never beside it ────────────────────────
   The owner, 2026-10-13, from his phone: «תפריט בתצוגת מובייל מקווץ את החלק הראשי מקום להיות מעליו»
   — with the sessions menu open on a 390px frame the harness gives it its full 280px and the
   conversation the remaining 110, so the hero wraps one word per line. Measured live (console, phone
   profile, ci-artifacts/mobile-nav-squeeze/): sidebar 280 / centre 110 before, sidebar 281
   (absolute) / centre 390 after. One column while the menu is open, and the menu is a sheet above it.
   THE TRAP, paid for twice: an out-of-flow column leaves the grid, the centre becomes the FIRST item
   and is auto-placed into the ZERO track — the conversation is then 0px wide in a frame that reports
   the right columns (measured: centre=0 on the first attempt). The centre is therefore pinned to the
   middle track and the side panel to the third. */
html[${OVER_ATTR}] ${FRAME}{grid-template-columns:0 minmax(0,1fr) 0!important}
html[${OVER_ATTR}] [class*="_centerCol"]{grid-column:2!important;grid-row:1!important;z-index:1}
html[${OVER_ATTR}] [class*="_rightbarCol"]{grid-column:3!important;grid-row:1!important}
html[${OVER_ATTR}] ${SIDEBAR_COL}{
position:absolute!important;inset-block:0;inset-inline-start:0;
width:var(${MENU_W_VAR},300px);z-index:31;visibility:visible!important}
html[${OVER_ATTR}] ${HANDLES}{display:none!important}
.bina-menu-scrim{position:absolute;inset:0;z-index:30;background:rgb(0 0 0 / .34)}
/* Nothing of our own is drawn: the button is a TWIN of the one the app already puts in its
   conversation header — same classes, same size, same hover, same focus ring — with its glyph
   flipped on the X axis, because it acts on the other edge. One rule only: the glyph's mirror. */
.bina-nav-fold svg{transform:scaleX(-1)!important}
html[${SHELL_ATTR}] .bina-nav-fold{display:none!important}
`;

		/** Install the stylesheet once, whatever the load order. */
		function installStyles(doc) {
			if (!doc || doc.getElementById("bina-nav-collapse-css")) return;
			const tag = doc.createElement("style");
			tag.id = "bina-nav-collapse-css";
			tag.textContent = CSS;
			doc.head.appendChild(tag);
		}

		/** The remembered choice, or false. Storage can refuse (private mode): then it is simply off. */
		function stored() {
			try {
				return globalThis.localStorage.getItem(STORE_KEY) === "1";
			} catch (error) {
				return false;
			}
		}

		/**
		 * Mount the state, the panel control this app lacks, and the key.
		 * @param ctx - Client root context (no services are required; this is presentation only).
		 */
		function apply(ctx) {
			// A presentation plugin must never be the reason the agent's own page fails to load: every
			// step is inside the try, and the only thing a failure costs is the feature.
			try {
				const doc = globalThis.document;
				const root = doc && doc.documentElement;
				if (!root) return;
				installStyles(doc);

				const shellFocused = () => root.hasAttribute(SHELL_ATTR);
				const compact = () => root.hasAttribute(COLLAPSE_ATTR);

				// ── the narrow frame: the menu is a SHEET, not a column ────────────────────────────
				// Which frame is narrow is asked the way the harness asks it (`viewportWidth` is
				// `window.innerWidth`, compared with SIDEBAR_AUTO_COLLAPSE) — the app is embedded in a
				// frame that is the phone's width, so this is that same number.
				const narrowFrame = () => {
					const vw = Number(globalThis.innerWidth);
					if (Number.isFinite(vw) && vw > 0) return vw < NARROW_PX;
					const frame = doc.querySelector(FRAME);
					return Boolean(frame && frame.clientWidth && frame.clientWidth < NARROW_PX);
				};
				/** The state: a NARROW frame whose sessions menu is OPEN and nothing folded away. */
				const menuOver = () => {
					if (compact()) return false;                       // folded: nothing is drawn at all
					const frame = doc.querySelector(FRAME);
					if (!frame || frame.hasAttribute("data-sidebar-collapsed")) return false;  // the rail
					return narrowFrame();
				};
				/** The width the harness computed for the sidebar — the sheet keeps the reader's own. */
				const trackWidth = (frame) => {
					const track = String((frame && frame.style && frame.style.gridTemplateColumns) || "")
						.trim().split(/\s+/)[0];
					return /^\d+(\.\d+)?px$/.test(track) ? track : "";
				};
				let scrim = null;
				/** Draw (or drop) the sheet, its width and the way out that a tap outside is. */
				const applyOver = () => {
					const want = menuOver();
					if (want !== root.hasAttribute(OVER_ATTR)) root.toggleAttribute(OVER_ATTR, want);
					if (!want) {
						if (scrim) { scrim.remove(); scrim = null; }
						return;
					}
					const frame = doc.querySelector(FRAME);
					if (!frame) return;
					const width = trackWidth(frame);
					if (width) root.style.setProperty(MENU_W_VAR, width);
					if (!scrim || scrim.parentNode !== frame) {
						if (scrim) scrim.remove();
						scrim = doc.createElement("div");
						scrim.className = "bina-menu-scrim";
						// ONE gesture, and it is the layout's own: tapping outside the menu is the same
						// gesture the app's controls make (`toggleSidebar`), so the frame's state stays
						// the single owner of whether the panel is open.
						scrim.addEventListener("click", (ev) => {
							ev.preventDefault();
							ev.stopPropagation();
							try {
								if (ctx && ctx.layout && typeof ctx.layout.toggleSidebar === "function") {
									ctx.layout.toggleSidebar();
								}
							} catch (error) {
								// The scrim is a convenience: the twin and Shift+Cmd+B still close it.
							}
						});
						frame.appendChild(scrim);
					}
				};

				/** Recompute from the two inputs: the shell's state, and this page's own choice. */
				const refresh = () => {
					const on = shellFocused() || stored();
					if (on !== compact()) root.toggleAttribute(COLLAPSE_ATTR, on);
					if (twin) { twin.title = on ? "פתיחת הניווט" : "קיפול הניווט"; }
					applyOver();
				};

				/** A deliberate change by the person reading this page. Ignored while the shell decides. */
				const setByUser = (on) => {
					if (on && !shellFocused()) {
						// This is the same gesture the shell's own button makes, so a page that is not
						// embedded behaves identically to one that is.
					}
					try {
						globalThis.localStorage.setItem(STORE_KEY, on ? "1" : "0");
					} catch (error) {
						// Not remembered, still applied for this page.
					}
					root.toggleAttribute(COLLAPSE_ATTR, on || shellFocused());
				};

				// WHERE THE BUTTON GOES, and why: the app already answers "how do I reach a side that
				// is not drawn" with one button in the conversation header (ui-sidebar-right's
				// ExpandButton, whose own glyph is the sidebar's collapse icon mirrored). The office's
				// fold is the same question on the other edge, so it is the same affordance, in the
				// same row — and NOT a floating circle over the transcript (the owner, 2026-10-13:
				// «שיהיה אותו סמל רק הפוך … במקום הכפתור הצף שעשית»).
				// A REGEX, not a list of strings — and this is a lesson paid for: the day the office renamed
				// these very labels (2026-10-13, «פתיחת סרגל שמאל»), a list of the old sentences stopped
				// matching and the twin silently disappeared. Anything that names a panel is the app's own
				// control, in either language.
				const ANCHOR_RE = /(סרגל|sidebar)/i;
				const columnOf = (b) => (typeof b.closest === "function"
					? b.closest('[class*="_sidebarCol"],[class*="_rightbarCol"]') : null);
				// TWO PLACES, in this order, and both are the app's own language:
				//   1. the conversation header's control for a hidden side (ui-sidebar-right's
				//      ExpandButton) — the twin stands beside it and is hidden with it;
				//   2. if that button is not drawn (the panel is SHOWN, so it renders nothing, which is
				//      the default while the guide is docked) — the rail's own first row, beside the
				//      same affordance there. Without this the fold would vanish exactly in the state
				//      the owner photographed.
				function anchorButton() {
					const all = doc.querySelectorAll("button");
					let rail = null;
					for (let i = 0; i < all.length; i++) {
						const b = all[i];
						const aria = b.getAttribute("aria-label") || "";
						if (!ANCHOR_RE.test(aria)) continue;
						if (columnOf(b)) { if (!rail) rail = b; continue; }   // inside a column: the rail's
						return b;                                             // the header's: preferred
					}
					return rail;
				}
				// WHERE THE TWIN STANDS (owner, 2026-10-13: «לפני איפה שכתוב תיאור הסשן בקו תפריט עליון»):
				// immediately BEFORE the conversation header's title cluster (`_titleCluster`, ui-conversation)
				// — the leading edge of that row in RTL. The seat itself (`_headerCorner`, where the app puts
				// its own way-in button) is the FALLBACK, because that button is not drawn while the panel is
				// shown: measured on the live app, with the panel open there is no anchor in the row at all
				// and the first version of this plugin silently put the twin in the rail instead.
				function homeFor() {
					// SCOPED TO THE CONVERSATION'S OWN COLUMN (`_centerCol`). Unscoped, the first
					// `_titleCluster` in the document is one inside the RAIL, and the twin landed at
					// x=349 of a 390px frame — inside the sidebar, exactly where the owner was NOT
					// looking (measured on the live app, 2026-10-13).
					const centre = doc.querySelector('[class*="_centerCol"]') || doc;
					const title = centre.querySelector('[class*="_titleCluster"]');
					if (title && title.parentNode) return { parent: title.parentNode, before: title };
					const seat = centre.querySelector('[class*="_headerCorner"]');
					if (seat && seat.parentNode) return { parent: seat.parentNode, before: seat };
					const anchor = anchorButton();
					if (anchor && anchor.parentNode) return { parent: anchor.parentNode, before: anchor };
					return null;
				}
				let twin = null;
				// WHAT THE TWIN DOES (owner, 2026-10-13): «add another one at the other side, just before
				// session sum». The header already carries the way into the LEFT panel (ui-sidebar-right
				// renders on the left in RTL). What no screen carries is the same control for the RIGHT
				// one — the sessions sidebar — so this is it: the layout's own `toggleSidebar` (the API
				// the rail's control calls), labelled by its side, at the leading edge of the header row.
				// The panel's own state is published where the frame already says it: `data-sidebar-collapsed`
				// on the frame root (ui-layout). Reading it — rather than keeping a second copy of the
				// state here — is what lets the label say which way the button goes.
				const sidebarOpen = () => {
					const frame = doc.querySelector('[class*="_frame"]');
					return frame ? !frame.hasAttribute("data-sidebar-collapsed") : false;
				};
				const label = () => {
					if (!twin) return;
					const open = sidebarOpen();
					twin.title = open ? "כיווץ סרגל ימין" : "פתיחת סרגל ימין";
					twin.setAttribute("aria-label", twin.title);
					twin.setAttribute("aria-expanded", String(open));
				};
				function placeTwin() {
					const home = homeFor();
					if (!home) { if (twin) { twin.remove(); twin = null; } return; }
					if (twin && twin.parentNode === home.parent) return;
					if (twin) twin.remove();
					// the classes to wear: the header's own button if it is drawn, else the rail's
					const centreCol = doc.querySelector('[class*="_centerCol"]') || doc;
					const seat = centreCol.querySelector('[class*="_headerCorner"]');
					const seatBtn = seat ? seat.querySelector("button") : null;
					const style_ = (seatBtn || anchorButton());
					twin = doc.createElement("button");
					twin.type = "button";
					twin.className = (style_ && style_.className ? style_.className : "icon-btn") + " bina-nav-fold";
					twin.innerHTML = style_ ? style_.innerHTML : "";
					twin.addEventListener("click", (ev) => {
						ev.preventDefault();
						// THE ONE THING THE OWNER ASKED FOR (2026-10-13): «לפתוח את הנתיב צד ולסגור אותו
						// חזרה בבינה ודעת כדי שאוכל גם לנווט וגם להשתמש בכל רוחב המסך». Two states, one
						// control:
						//   · the panel is OPEN (he is navigating) → close it AND hide the rail, so the
						//     conversation gets the whole width;
						//   · it is not (he is working)             → bring the rail back AND open the
						//     panel over the page, so the sessions are one press away.
						// The frame's own action is what moves the panel (`toggleSidebar`, the call the
						// rail's control makes); hiding the rail entirely is this plugin's own state.
						const panelOpen = sidebarOpen();
						try {
							if (ctx && ctx.layout && typeof ctx.layout.toggleSidebar === "function") {
								ctx.layout.toggleSidebar();
								setByUser(panelOpen);        // navigating → full width; working → rail back
							} else {
								setByUser(!compact());
							}
						} catch (e) { setByUser(!compact()); }
						label();
					});
					if (home.before) home.parent.insertBefore(twin, home.before);
					else home.parent.appendChild(twin);
					label();
				}

				// ── A CHOICE INSIDE THE MENU ENDS THE MENU ─────────────────────────────────────────
				// The owner, 2026-10-13 (DGO-552): «במובייל בחירה בתפריט השיחות — «שיחה חדשה» או שיחה
				// קיימת — לא סוגרת את התפריט». The scrim closes the sheet from OUTSIDE it; this is the
				// inside half. On a phone the sheet covers the conversation, so a tap that means "show me
				// THAT" has to take the sheet with it or the choice is invisible.
				const spoken = (el) => (el && typeof el.getAttribute === "function"
					? String(el.getAttribute("aria-label") || el.textContent || "") : "");
				/** Does this tap mean "show me that" — a session, or a new one? */
				const choiceAt = (target) => {
					if (!target || typeof target.closest !== "function") return false;
					for (const sel of NEW_DOORS) if (target.closest(sel)) return true;
					// Inside a row's own control cluster only its "a new conversation HERE" door is a
					// choice (the app labels it «שיחה חדשה ב-…»); the rest of that cluster manages the
					// list — a tap there must leave the sheet where it is.
					if (target.closest(ROW_ACTIONS)) return NEW_SESSION_RE.test(spoken(target));
					return Boolean(target.closest(SESSION_ROW));
				};
				// CAPTURE phase, because some rows stop the event on the way up — and the app's own
				// action stays the one that moves the panel (`toggleSidebar`, the call the scrim makes).
				// It ASKS AFTERWARDS rather than toggling blind: the harness folds the sidebar by itself
				// on some navigations (measured), and a blind toggle would reopen a panel it had just
				// folded.
				const onChoice = (event) => {
					try {
						if (!menuOver() || !choiceAt(event.target)) return;
						const close = () => {
							if (!menuOver()) return;
							try {
								if (ctx && ctx.layout && typeof ctx.layout.toggleSidebar === "function") {
									ctx.layout.toggleSidebar();
								}
							} catch (error) {
								// The twin and Shift+Cmd+B are still two ways out.
							}
						};
						if (typeof globalThis.setTimeout === "function") globalThis.setTimeout(close, 0);
						else close();
					} catch (error) {
						// A navigation gesture never throws.
					}
				};
				doc.addEventListener("click", onChoice, true);

				const onKey = (event) => {
					// Shift+Cmd/Ctrl+B, the shortcut every editor uses for this. Deliberately inert
					// while the shell is in full screen: there the way back is the shell's chip, and a
					// key that half-leaves that state would be a second, disagreeing door.
					if (!(event.shiftKey && (event.metaKey || event.ctrlKey))) return;
					if (String(event.key).toLowerCase() !== "b") return;
					if (shellFocused()) return;
					event.preventDefault();
					setByUser(!compact());
				};
				doc.addEventListener("keydown", onKey);

				// The shell's flag can appear, change and disappear (its full screen, and its exit).
				const observer = new globalThis.MutationObserver(refresh);
				observer.observe(root, { attributes: true, attributeFilter: [SHELL_ATTR] });

				// …and the frame's own is what says whether the sessions menu is open (`ui-layout`
				// publishes `data-sidebar-collapsed` there), which is half of the sheet's state.
				const frameWatch = new globalThis.MutationObserver(applyOver);
				let watched = null;
				const watchFrame = () => {
					const frame = doc.querySelector(FRAME);
					if (!frame || frame === watched) return;
					frameWatch.disconnect();
					frameWatch.observe(frame, { attributes: true,
						attributeFilter: ["data-sidebar-collapsed", "style"] });
					watched = frame;
				};
				// A phone also turns, and a tablet is resized: the width is a live input.
				const onResize = () => { watchFrame(); applyOver(); };
				if (typeof globalThis.addEventListener === "function") {
					globalThis.addEventListener("resize", onResize);
				}

				watchFrame();
				refresh();
				placeTwin();
				// the app re-renders its header as sessions come and go: the twin is re-placed, never
				// duplicated (one writer per button, and it is this plugin)
				const headerWatch = new globalThis.MutationObserver(() => { placeTwin(); watchFrame(); applyOver(); label(); });
				if (doc.body) headerWatch.observe(doc.body, { childList: true, subtree: true });
				if (ctx && typeof ctx.effect === "function") {
					ctx.effect(() => () => {
						observer.disconnect();
						frameWatch.disconnect();
						headerWatch.disconnect();
						doc.removeEventListener("keydown", onKey);
						doc.removeEventListener("click", onChoice, true);
						if (typeof globalThis.removeEventListener === "function") {
							globalThis.removeEventListener("resize", onResize);
						}
						if (twin) twin.remove();
						if (scrim) { scrim.remove(); scrim = null; }
						root.removeAttribute(OVER_ATTR);
					}, "nav-collapse: the agent's own navigation, folded away");
				}
				exports._setByUser = setByUser;   // the test's seam; nothing in the app reads it
				exports._refresh = refresh;
			} catch (error) {
				// Loud in the console, invisible to the reader: the app keeps working without it.
				if (globalThis.console) globalThis.console.warn("[nav-collapse]", error);
			}
		}
		exports.apply = apply;
		// `layout` MUST be declared: the client runtime refuses to hand a service to a plugin that did
		// not ask for it ("cannot get property \"layout\" without inject" — measured on the live app,
		// 2026-10-13, and it is what the click was throwing).
		exports.inject = ["layout"];
		return module.exports;
	}
});
