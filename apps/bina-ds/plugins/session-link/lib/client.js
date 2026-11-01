window.__ModuleLoader__.load({
	id: "@bina/dsh-client-session-link",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		// ── the conversation in the address bar ────────────────────────────────────────────────
		// WHAT WAS MISSING. Every other office app is reachable at the screen you were last on: the
		// console's hash grammar is `#/m/<id>[/inner/path][?query]` and it hands that tail to the
		// frame, and the shell mirrors the frame's own URL back into its address bar. The harness was
		// the ONE app that never took part: its browser half has no URL routing at all (measured on
		// the pinned build, dsh-web-frontend 0.1.6-alpha.1 — zero `location.hash`, `pushState` or
		// `URLSearchParams` in dist/assets/index-*.js), and its durable selection lives in the
		// browser's own storage (`dsh.sessions.current`, api-session-controller client.js:3059). So
		// the owner's URL was `#/m/bina` whatever conversation was on screen, and there was no way to
		// say "look at THIS conversation" (owner, 2026-10-12).
		//
		// THIS FILE IS THE APP'S OWN JOB AND NOTHING ELSE: keep the open conversation in the
		// harness's OWN URL. The harness publishes the one fact needed — the client service
		// `sessions`: `list` is a snapshot store (`getSnapshot`, `subscribe`) carrying `current`, and
		// `open(id)` selects — and the plugin does two things around it:
		//   · arriving — a session id in our own query (`/a/bina/?s=<id>`, the shell's tail) is opened
		//     once, against the first complete list;
		//   · leaving — every change of the open conversation is written into this page's own URL.
		// The SHELL is told nothing: it mirrors the frame's URL by itself
		// (platform-base/console/static/app.js `watchFrameRoute`), which is why the `bina:route`
		// postMessage this plugin used to send is gone — one writer of one fact, not two.
		//
		// The route is a QUERY rather than a path because the harness's own server answers 404 for a
		// path it does not know while a query is served by everything, and because it keeps the
		// standalone host (`bina.<domain>/?s=<id>`) working with the same reader.
		//
		// A name is never typed here: the id is the session's own durable identity, the same one
		// `bbox agent list` prints and the console shows in its URL.
		const QUERY = "s";
		/** Required service: the session controller's list and selection. */
		const inject = ["sessions"];

		/** The session id this page was opened with — `?s=<id>` — or nothing. */
		function requestedSession() {
			try {
				const id = new URL(globalThis.location.href).searchParams.get(QUERY);
				return id === null || id === "" ? undefined : id;
			} catch (error) {
				return undefined;
			}
		}

		/** The inner route as the shell's grammar spells it: `?s=<id>`, or `/` for "no conversation". */
		function routeOf(sessionId) {
			return sessionId === undefined ? "/" : "?" + QUERY + "=" + encodeURIComponent(sessionId);
		}

		/** Keep this page's own address bar naming the conversation (the standalone host, not the shell). */
		function adopt(path) {
			try {
				const url = new URL(globalThis.location.href);
				const search = path === "/" ? "" : path;
				if (url.search === search) return;
				url.search = search;
				globalThis.history.replaceState(null, "", url.href);
			} catch (error) {
				// A URL we may not rewrite is not a reason to lose the address for the shell to read.
			}
		}

		/**
		 * Mount the two directions. One list subscription carries both: the list is where the
		 * conversation that was asked for appears, and where the open one changes.
		 * @param ctx - Client root context (services declared by {@link inject}).
		 */
		function apply(ctx) {
			const sessions = ctx.sessions;
			const wanted = requestedSession();
			ctx.effect(() => {
				let ask = wanted;
				let written;
				const publish = () => {
					const list = sessions.list.getSnapshot();
					// `pending` is the state before the first successful pull: `current` is then not
					// an answer about this page, it is only "nothing is known yet" — reporting it
					// would rewrite the shell's URL to a conversation the reader did not choose.
					if (list.phase !== "ready") return;
					let current = list.current;
					if (ask !== undefined) {
						// The FIRST COMPLETE LIST IS THE AUTHORITY, and this ask is answered against
						// it exactly once: the id is either in the pull — and opening it is what the
						// link asked for — or it names nothing any more (deleted, archived, another
						// office's), and the reader stays on whatever is open instead of being sent
						// somewhere that does not exist. `open()` refuses an id the list does not
						// carry (unknown ids fail loud); the catch is the narrow window between the
						// pull and this line.
						const asked = ask;
						ask = undefined;
						if (list.ids.indexOf(asked) >= 0) {
							try {
								sessions.open(asked);
							} catch (error) {
								// Gone since the pull: report what IS open.
							}
							// Selecting moves the list and notifies it, so this call has already
							// been re-entered with the new snapshot — which is why `current` is
							// read AGAIN here. Reporting the snapshot captured before the open is
							// how the address bar would end up naming the conversation just left.
							current = sessions.list.getSnapshot().current;
						}
					}
					const path = routeOf(current);
					if (path === written) return;
					written = path;
					// ONLY ONE WRITER, AND IT IS THIS PAGE'S OWN URL. The shell mirrors the frame's
					// URL by itself now (platform-base/console/static/app.js `watchFrameRoute`), so the
					// postMessage this plugin used to send — and the `bina:route` listener that read
					// it — are both redundant here: two writers of one fact, which is one too many.
					adopt(path);
				};
				const dispose = sessions.list.subscribe(publish);
				publish();
				return () => {
					dispose();
				};
			}, "session-link: the conversation in the address bar");
		}
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
