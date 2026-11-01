/**
 * voice — the browser half: **the composer's send button becomes the microphone when there is
 * nothing to send**, exactly like WhatsApp, and the default is to send the RECORDING to the agent.
 *
 * The owner's model (2026-10-07), which this file now implements:
 *   • empty composer → the primary action is a microphone; press it and you are recording;
 *   • press it again → the recording is sent to the conversation, as audio, immediately. The agent
 *     transcribes it itself (it has the `transcription` skill);
 *   • want the text instead? While recording, press "תמלול": the recording is transcribed and the
 *     words land in the composer, editable, to be sent as text — the audio is not sent.
 *
 * The send button is not ours to re-render (it belongs to the harness's InputBar), so this plugin
 * does the least invasive thing that produces exactly that behaviour: it hides the harness's send
 * button while the draft is empty and renders its own primary button **in the same DOM parent**, via
 * a portal into the composer card (`[data-composer-card]`). Position, size and theme are therefore
 * the harness's; only the glyph and the action are ours.
 *
 *
 * The browser cuts the segments (`SEGMENT_MS`): MediaRecorder is restarted per segment, because the
 * spec is explicit that individual `timeslice` chunks need not be playable, so they cannot be posted
 * piecemeal. 30 s is not a UI preference either — Whisper pads every window to 30 s of mel frames, so
 * a 10 s segment costs nearly the same as a 30 s one (measured: ~0.5× real time against ~1.4×).
 */
window.__ModuleLoader__.load({
	id: "@bina/dsh-plugin-voice",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

		const React = require("react");
		const { jsx, jsxs } = require("react/jsx-runtime");
		const { createPortal } = require("react-dom");

		const inject = ["slots"];

		// The first segment is short ON PURPOSE: on this box a 30 s segment takes 30-45 s to come back,
		// so a person pressing the microphone and seeing nothing for a minute concludes it is broken
		// (that is exactly what happened on 2026-10-07). 12 s gets the first words back in ~20 s; every
		// later segment stays at 30 s because Whisper pads a window to 30 s anyway, so shorter ones cost
		// nearly the same and buy nothing.
		const FIRST_SEGMENT_MS = 12000;
		const SEGMENT_MS = 30000;
		const POLL_MS = 2500;

		const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

		// Two classes, and every value is a harness token with a neutral fallback, so the strip stays
		// legible even if a future build renames one.
		const CSS = `
.bina-voice-btn{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:8px;border:0;background:transparent;color:var(--dsw-alias-label-primary,#1f2328);cursor:pointer;padding:0}
.bina-voice-primary{border-radius:50%;background:var(--dsw-alias-button-primary-fill,var(--dsw-alias-brand-primary,#2563eb));color:var(--dsw-alias-label-primary-foreground,#fff)}
.bina-voice-primary:hover{background:var(--dsw-alias-button-primary-hover,var(--dsw-alias-brand-primary,#1d4ed8))}
.bina-voice-primary[data-recording="true"]{background:var(--dsw-alias-state-error-primary,#c62828)}
.bina-voice-btn:hover{background:var(--dsw-alias-button-tool-bar-hover,rgba(127,127,127,.14))}
.bina-voice-btn[data-recording="true"]{color:var(--dsw-alias-state-error-primary,#c62828);background:var(--dsw-alias-interactive-bg-hover-danger,rgba(198,40,40,.12))}
.bina-voice-strip{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:4px 8px 6px;font-size:12px;line-height:1.6;color:var(--dsw-alias-label-caption,#5b6470)}
.bina-voice-strip b{font-weight:600;color:var(--dsw-alias-label-primary,#1f2328)}
.bina-voice-dot{width:7px;height:7px;border-radius:50%;background:var(--dsw-alias-state-error-primary,#c62828);animation:bina-voice-pulse 1.3s ease-in-out infinite}
@keyframes bina-voice-pulse{0%,100%{opacity:1}50%{opacity:.2}}
.bina-voice-act{border:0;background:transparent;color:var(--dsw-alias-label-primary,#1f2328);font:inherit;cursor:pointer;padding:2px 6px;border-radius:6px;text-decoration:underline;text-underline-offset:2px}
.bina-voice-act:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.12))}
.bina-voice-err{color:var(--dsw-alias-state-error-primary,#c62828)}
`;
		function installCss() {
			if (typeof document === "undefined" || document.getElementById("bina-voice-css")) return;
			const tag = document.createElement("style");
			tag.id = "bina-voice-css";
			tag.textContent = CSS;
			document.head.appendChild(tag);
		}

		// ── one recorder for the whole client (a microphone is a single-mic activity) ──────────
		const controller = {
			state: {
				recording: false,
				elapsed: 0,
				segments: 0,
				pending: 0,
				queue: 0,
				sessionId: null,
				asrId: null,
				note: "",
				error: "",
				uploading: false,
				finalReady: false,
				detached: false,
				mode: "send",          // "send" = deliver the audio; "text" = transcribe into the composer
				transcribing: false,
			},
			listeners: new Set(),
			ctx: null,
			stream: null,
			index: 0,
			running: false,
			lastMirror: "",
			startedAt: 0,
			pollTimer: null,
			tickTimer: null,
			clearTimer: null,
			set(patch) {
				Object.assign(this.state, patch);
				for (const listener of this.listeners) listener();
			},
			subscribe(listener) {
				this.listeners.add(listener);
				return () => this.listeners.delete(listener);
			},
		};

		function useVoice() {
			const [, bump] = React.useState(0);
			React.useEffect(() => controller.subscribe(() => bump((n) => n + 1)), []);
			return controller.state;
		}

		function sessionFromUrl() {
			try {
				const url = new URL(window.location.href);
				const query = url.searchParams.get("session") || url.searchParams.get("sessionId");
				if (query) return query;
				const match = url.pathname.match(/\/(?:session|sessions|chat)\/([A-Za-z0-9_-]{6,})/);
				return match ? match[1] : null;
			} catch {
				return null;
			}
		}

		function shellFor(sessionId) {
			try {
				const ctx = controller.ctx;
				const conversation = (ctx && (ctx.get ? ctx.get("conversation") : ctx.conversation)) || null;
				if (!conversation || !conversation.input || !sessionId) return null;
				return conversation.input.shell(sessionId);
			} catch {
				return null;
			}
		}

		function draftText(sessionId) {
			try {
				const shell = shellFor(sessionId);
				const projection = shell && shell.projection;
				return (projection && (projection.clipboardText ?? projection.detectText)) || "";
			} catch {
				return "";
			}
		}

		/** Write the transcript into the composer — but never over words the owner typed. */
		function mirror(text, sessionId) {
			const shell = shellFor(sessionId);
			if (!shell || typeof shell.setDraft !== "function") return;
			const current = draftText(sessionId).trim();
			if (current !== "" && current !== controller.lastMirror.trim()) {
				controller.set({ detached: true });
				return;
			}
			try {
				shell.setDraft(text);
				controller.lastMirror = text;
				controller.set({ detached: false });
			} catch {
				/* the composer may be re-mounting; the next poll tries again */
			}
		}

		/** True when the composer holds nothing the harness could send. */
		function draftEmpty(sessionId) {
			return draftText(sessionId).trim() === "";
		}

		function pickMime() {
			for (const type of ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"]) {
				try {
					if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(type)) return type;
				} catch {
					/* deprecated API, still the only synchronous answer */
				}
			}
			return "";
		}

		function joined(segments) {
			return Object.keys(segments)
				.map(Number)
				.sort((a, b) => a - b)
				.map((index) => (segments[index] || "").trim())
				.filter(Boolean)
				.join(" ");
		}

		function stopTracks() {
			try {
				controller.stream?.getTracks().forEach((track) => track.stop());
			} catch {
				/* nothing to stop */
			}
			controller.stream = null;
		}

		async function openLiveSession() {
			const response = await fetch("/api/voice/session", { method: "POST" });
			const body = await response.json().catch(() => ({}));
			if (!response.ok || !body.id) throw new Error(body.detail || body.error || `HTTP ${response.status}`);
			controller.index = 0;
			controller.set({ asrId: body.id, segments: 0, pending: 0, finalReady: false });
			return body.id;
		}

		function poll() {
			if (controller.pollTimer) clearTimeout(controller.pollTimer);
			const tick = async () => {
				const asrId = controller.state.asrId;
				if (!asrId) return;
				try {
					const response = await fetch(`/api/voice/status?session=${encodeURIComponent(asrId)}`);
					if (response.ok) {
						const view = await response.json();
						const texts = {};
						let pending = 0;
						for (const segment of view.segments || []) {
							texts[segment.index] = segment.text || "";
							if (segment.status === "queued" || segment.status === "processing") pending += 1;
						}
						const wasPending = controller.state.pending;
						controller.set({
							pending,
							queue: view.queue?.queue_depth ?? 0,
							segments: (view.segments || []).length,
							finalReady: Boolean(view.final && view.final.status === "completed"),
						});
						// the status line is chrome, not history: once the queue drains it takes itself
						// away, so the composer goes back to being just a composer.
						if (wasPending > 0 && pending === 0) {
							controller.set({ note: "" });
							if (controller.clearTimer) clearTimeout(controller.clearTimer);
							controller.clearTimer = setTimeout(() => controller.set({ note: "", queue: 0 }), 4000);
						}
						const text = joined(texts);
						if (text && controller.state.mode === "text") {
							mirror(text, controller.state.sessionId);
							if (pending === 0 && !controller.state.recording) {
								controller.set({ transcribing: false, note: "התמלול בתיבה — אפשר לערוך ולשלוח." });
							}
						}
					}
				} catch {
					/* a missed poll is not something the owner needs to know */
				}
				controller.pollTimer = setTimeout(tick, controller.state.recording ? POLL_MS : POLL_MS * 2);
			};
			tick();
		}

		async function recordSegment(stream, milliseconds) {
			const mime = pickMime();
			const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
			const chunks = [];
			recorder.ondataavailable = (event) => { if (event.data && event.data.size) chunks.push(event.data); };
			const stopped = new Promise((resolve) => {
				recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType || mime || "audio/webm" }));
			});
			recorder.start();
			const until = Date.now() + milliseconds;
			while (Date.now() < until && controller.running) await sleep(250);
			if (recorder.state !== "inactive") recorder.stop();
			return stopped;
		}

		async function upload(blob, index) {
			controller.set({ uploading: true });
			try {
				const response = await fetch(
					`/api/voice/segment?session=${encodeURIComponent(controller.state.asrId)}&index=${index}`,
					{ method: "POST", headers: { "content-type": blob.type || "audio/webm" }, body: blob },
				);
				if (!response.ok) {
					const body = await response.json().catch(() => ({}));
					throw new Error(body.detail || body.error || `HTTP ${response.status}`);
				}
				controller.set({ segments: controller.state.segments + 1 });
			} catch (error) {
				controller.set({ error: `מקטע לא עלה: ${String(error?.message || error)}` });
			} finally {
				controller.set({ uploading: false });
			}
		}

		async function start() {
			controller.set({ error: "", note: "", detached: false, finalReady: false, mode: "send" });
			try {
				let sessionId = controller.state.sessionId;
				if (!sessionId) {
					const fromUrl = sessionFromUrl();
					let newest = { id: null };
					try {
						newest = await (await fetch("/api/voice/current")).json();
					} catch {
						/* the newest-session lookup is a convenience, not a requirement */
					}
					sessionId = fromUrl || newest.id || null;
					if (!sessionId) {
						// recording from the blank hero: the relay creates the conversation
						const ensured = await (await fetch("/api/voice/ensure-session", { method: "POST" })).json();
						sessionId = ensured.id || null;
					}
				}
				controller.lastMirror = "";
				controller.set({ sessionId });
				await openLiveSession();
				const stream = await navigator.mediaDevices.getUserMedia({
					audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
				});
				controller.stream = stream;
				controller.running = true;
				controller.startedAt = Date.now();
				controller.set({ recording: true, elapsed: 0 });
				if (controller.tickTimer) clearInterval(controller.tickTimer);
				controller.tickTimer = setInterval(() => {
					controller.set({ elapsed: Math.round((Date.now() - controller.startedAt) / 1000) });
				}, 1000);
				poll();
				(async () => {
					let first = true;
					// UPLOAD FIRST, then decide whether to continue. The previous order (`break` when the
					// owner stopped) threw away the final partial segment — so a recording shorter than one
					// segment produced no audio at all and "nothing happened", which is the bug the owner
					// hit on his phone (2026-10-07): four live sessions opened, not one segment uploaded.
					while (true) {
						const blob = await recordSegment(stream, first ? FIRST_SEGMENT_MS : SEGMENT_MS);
						first = false;
						if (blob && blob.size) await upload(blob, controller.index++);
						if (!controller.running) break;
					}
				})();
			} catch (error) {
				controller.running = false;
				stopTracks();
				controller.set({ recording: false, error: `ההקלטה לא התחילה: ${String(error?.message || error)}` });
			}
		}

		function stop() {
			controller.running = false;
			if (controller.tickTimer) clearInterval(controller.tickTimer);
			stopTracks();
			controller.set({ recording: false, note: controller.state.pending ? "מתמלל את ההמשך…" : "" });
		}

		/** "תמלול": stop, keep the audio, and put the words in the composer to be sent as text. */
		async function transcribeInstead() {
			controller.set({ mode: "text", transcribing: true, note: "מתמלל…" });
			stop();
			// the segment loop keeps uploading whatever it already has; poll() mirrors the text in
			controller.set({ transcribing: true });
		}

		/** The default action when the recording stops: send the audio itself, at once. */
		async function sendNow() {
			const asrId = controller.state.asrId;
			if (!asrId) return;
			controller.set({ note: "שולח את ההקלטה…" });
			try {
				// wait a moment for the last partial segment to land, so the joined file is whole
				for (let i = 0; i < 20 && controller.state.pending > 0; i += 1) await sleep(500);
				const query = new URLSearchParams({
					session: controller.state.sessionId || "",
					asr: asrId,
					text: controller.state.mode === "text" ? draftText(controller.state.sessionId) : "",
				});
				const response = await fetch(`/api/voice/send-recording?${query}`, { method: "POST" });
				const body = await response.json().catch(() => ({}));
				if (!response.ok || body.error) throw new Error(body.error || `HTTP ${response.status}`);
				if (body.session) controller.set({ sessionId: body.session });
				controller.set({ note: "ההקלטה נשלחה לסוכן.", finalReady: false });
				if (controller.clearTimer) clearTimeout(controller.clearTimer);
				controller.clearTimer = setTimeout(() => controller.set({ note: "" }), 8000);
			} catch (error) {
				controller.set({ note: `שליחת ההקלטה נכשלה: ${String(error?.message || error)}` });
			}
		}

		async function accurate() {
			controller.set({ note: "מתמלל שוב את ההקלטה כולה…" });
			try {
				const response = await fetch(`/api/voice/finish?session=${encodeURIComponent(controller.state.asrId)}`, { method: "POST" });
				const body = await response.json().catch(() => ({}));
				if (!response.ok) throw new Error(body.detail || body.error || `HTTP ${response.status}`);
				controller.set({ finalReady: false, note: "התמלול המדויק בתור." });
				poll();
			} catch (error) {
				controller.set({ note: `התמלול המדויק לא נכנס לתור: ${String(error?.message || error)}` });
			}
		}

		async function cancelRecording() {
			controller.set({ mode: "cancel" });
			stop();
			const asrId = controller.state.asrId;
			if (asrId) {
				try {
					await fetch(`/api/voice/cancel?session=${encodeURIComponent(asrId)}`, { method: "POST" });
				} catch {
					/* nothing to undo on the client side: the audio was never sent */
				}
			}
			controller.set({ note: "", pending: 0, transcribing: false, finalReady: false });
		}

		function appendToDraft() {
			const shell = shellFor(controller.state.sessionId);
			if (!shell || typeof shell.setDraft !== "function") return;
			const current = draftText(controller.state.sessionId).trim();
			const text = (controller.lastMirror || "").trim();
			if (!text) return;
			const next = current ? `${current} ${text}` : text;
			try {
				shell.setDraft(next);
				controller.lastMirror = next;
				controller.set({ detached: false });
			} catch {
				/* the text is still recoverable from the strip's own state */
			}
		}

		function clock(seconds) {
			return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
		}

		function MicGlyph({ recording }) {
			return jsx("svg", {
				width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
				strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true",
				children: recording
					? jsx("rect", { x: 7, y: 7, width: 10, height: 10, rx: 2.5, fill: "currentColor", stroke: "none" })
					: jsxs(React.Fragment, { children: [
						jsx("rect", { x: 9, y: 3, width: 6, height: 11, rx: 3 }),
						jsx("path", { d: "M5.5 11.5a6.5 6.5 0 0 0 13 0" }),
						jsx("path", { d: "M12 18v3" }),
					] }),
			});
		}

		/**
		 * The primary action: a microphone that REPLACES the send button while there is nothing to
		 * send, and a stop-and-send while recording. Rendered by portal into the send button's own
		 * parent inside the composer card, so it lands exactly where the send button is — same size,
		 * same theme, no layout of our own. The harness's button is hidden only while it has nothing
		 * to do (empty draft, not recording), and restored the moment it does.
		 */
		function PrimaryButton() {
			const state = useVoice();
			const anchorNode = React.useRef(null);
			const [target, setTarget] = React.useState(null);

			React.useEffect(() => {
				const node = anchorNode.current;
				const card = node && node.closest("[data-composer-card]");
				if (!card) return;
				const buttons = [...card.querySelectorAll("button")].filter((b) => !b.classList.contains("bina-voice-btn"));
				const send = buttons[buttons.length - 1] || null;
				if (send && send.parentElement) setTarget({ parent: send.parentElement, send });
			}, []);

			React.useEffect(() => {
				if (!target) return undefined;
				const sync = () => {
					const idle = !controller.state.recording && draftEmpty(controller.state.sessionId);
					target.send.style.display = idle ? "none" : "";
				};
				sync();
				const timer = setInterval(sync, 400);
				return () => {
					clearInterval(timer);
					target.send.style.display = "";
				};
			}, [target, state.recording, state.sessionId]);

			const label = state.recording ? "שלח הקלטה" : "הקלטה";
			const button = jsx("button", {
				type: "button",
				className: "bina-voice-btn bina-voice-primary",
				title: label,
				"aria-label": label,
				"data-recording": String(state.recording),
				onClick: () => (state.recording ? stopAndSend() : start()),
				children: jsx(MicGlyph, { recording: state.recording }),
			});
			return jsxs(React.Fragment, {
				children: [
					jsx("span", { ref: anchorNode, style: { display: "none" }, "aria-hidden": "true" }),
					target ? createPortal(button, target.parent) : button,
				],
			});
		}

		/** Stopping by pressing the primary button means "send it" — the default the owner asked for. */
		async function stopAndSend() {
			stop();
			await sendNow();
		}

		/** The one line of chrome while something is happening, inside the composer card. */
		function VoiceStrip() {
			const state = useVoice();
			const busy = state.recording || state.pending > 0 || state.uploading || Boolean(state.note);
			if (!busy) return null;
			const parts = [];
			if (state.recording) {
				parts.push(jsx("span", { className: "bina-voice-dot", key: "dot" }));
				parts.push(jsx("b", { key: "rec", children: `${clock(state.elapsed)} · הקלטה לסוכן` }));
				parts.push(jsx("button", { key: "astext", className: "bina-voice-act", onClick: transcribeInstead, children: "תמלול במקום" }));
				parts.push(jsx("button", { key: "cancel", className: "bina-voice-act", onClick: cancelRecording, children: "בטל" }));
			} else if (state.transcribing) {
				parts.push(jsx("b", { key: "t", children: "מתמלל…" }));
			} else if (state.uploading || state.pending > 0) {
				parts.push(jsx("b", { key: "up", children: "מעלה את ההקלטה…" }));
			}
			if (state.note) parts.push(jsx("span", { key: "note", children: state.note }));
			if (state.error) parts.push(jsx("span", { className: "bina-voice-err", key: "err", children: state.error }));
			return jsx("div", { className: "bina-voice-strip", children: parts });
		}

		function apply(ctx) {
			// CONTAINMENT: this plugin is an addition to someone else's shell, so a failure here must
			// cost the microphone button and nothing else — a throw during boot shows the office
			// "Failed to load plugins" instead of the agent.
			try {
				installCss();
				controller.ctx = ctx;
				ctx.slots.inject("conversation.input.right", () =>
					ctx.slots.register({ id: "voice", name: "conversation.input.right" }, PrimaryButton));
				// `conversation.input.overlay` — NOT `conversation.composer.dock`: the dock only
				// renders in the composer variant, so on the blank-session hero (which is where a person
				// presses the microphone for the first time) the status line silently never appeared.
				// The overlay anchor is inside the composer card in both variants.
				ctx.slots.inject("conversation.input.overlay", () =>
					ctx.slots.register({ id: "voice-status", name: "conversation.input.overlay" }, VoiceStrip));
			} catch (error) {
				try {
					ctx.logger?.error?.("voice plugin disabled: %s", error);
				} catch {
					/* the logger belongs to the harness */
				}
			}
		}

		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	},
});
