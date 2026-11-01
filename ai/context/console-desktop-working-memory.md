# Console as a working-memory desktop — research and implementation prep

Source talk: **Scott Jenson, "Are we really going to use the same Desktop UX forever?"**, KDE Akademy
2026 (Day 1, Room 2), 40:55, published 2026-09-19.
Video: <https://youtu.be/V7AfAcQwLW0> · Recording + license:
<https://media.ccc.de/v/kde2026-7-are_we_really_going_to_use_the_same_desktop_ux_forever>
(CC BY-SA 4.0).

This doc turns the talk into:
1. a timestamped walkthrough (§2);
2. a numbered inventory of every idea and feature shown on stage (§3);
3. the sources behind them, including Jenson's own prototype code (§4);
4. a plan that maps the three prototypes onto the console (the window manager) and any-concurrency
   (the timeline) (§5–§9). Every later section cites
the IDs from §3 (`S*`, `A*`, `E*`, …).

> **No verbatim transcript is stored in the repo.** §2 is a paraphrase written for implementation
> work. For the exact wording, open the video → *…more* → *Show transcript*, or use the
> media.ccc.de page. The talk is CC BY-SA 4.0, so a copy kept for our own use needs attribution.

## 1. The thesis in five lines

1. The desktop stopped evolving about 20 years ago, and Linux waited for Apple and Microsoft to do the
   research. Those two have stopped taking risks, so someone else has to start.
2. The real problem is not pixels. It is the layer underneath, the conventions everyone accepts
   (Jenson calls it "stuff"). One example is overlapping windows, a leftover from the 512×342 Mac.
3. The AI lesson worth keeping is that tools improved when they took **context from the desktop**
   (Claude Code reading the file system), not when they generated more. So make the desktop hold
   more context.
4. Direct manipulation is fast, but it is **stateless**: nothing remembers what you did. The fix is
   to treat the desktop as **working memory**, built for people first and usable by AI later.
5. Three prototypes, one per kind of memory. **Spatial**: messy, organic window placement.
   **Associative**: clips and files kept with the document they belong to. **Episodic**: private
   attention signals turned into a story of what you did.

## 2. Timestamped walkthrough (paraphrase)

| Time | Section | What is said / shown |
|---|---|---|
| 00:09 | Who he is | UX at Symbian, Apple (Finder team) and Google (incl. Chrome). Now mentors designers and does UX for Mastodon and Home Assistant. Open source needs UX help, and the reason is understaffing, not "programmer culture". |
| 01:42 | Why this talk | A similar talk at the 2025 Ubuntu Summit went viral (~500k views), which shows real appetite for the topic. |
| 02:28 | Details matter | Finder truncates long names in the *middle* so the informative end survives (his change, still shipping). On the Mac, mouse-down selects and mouse-up raises the window, so you can drag out of a background window. That is data movement into apps, not file copying. A KDE developer implemented it after his earlier talk. |
| 03:59 | Stagnation | The desktop hasn't changed in ~20 years. The lineage runs Xerox Star → Mac → Windows → Linux and back. Linux let Apple and Microsoft do the research and make the mistakes (Clippy), but they no longer do. Alan Kay: perspective is worth 80 IQ points. He promises that half the talk will be prototypes. |
| 06:18 | Vendors stalled | Apple neglected the Mac from 2017 (keyboard, ports, Mac Pro, the "What's a computer?" iPad ad). Liquid Glass was partly walked back. New features deepen ecosystem lock-in rather than improve the desktop. Microsoft: OneDrive nagging, Recall, ads. His Windows-UX interview agenda was small optional experiments, and it wasn't a fit. |
| 09:23 | Three pushbacks | "Mobile won": it won consumption, not productivity, and desktops are quietly excellent. "It's a finished standard": so were CD-ROM and BlackBerry, and the laptop form is just an ergonomic standard. "Don't touch my setup": change gently and optionally, don't blow things up. |
| 11:42 | What UX is | Against the "UI/UX" label. The terms went human interface → user interface → user experience (Don Norman). UX has many disciplines, and managers reduce it to pixels. Layers: **style** (visuals), **structure** (navigation, flows, errors), **strategy** (who, what matters, what to say no to). |
| 14:48 | The "stuff" layer | From his book *The Simplicity Shift*: under strategy sit the technology and decades of accepted conventions ("historical cruft"). Fixing the desktop means questioning that layer. |
| 15:33 | Example: mobile text editing | Android study: 10 of 10 users failed to delete a double space, and one needed 5 tries. People avoid editing on phones (finish on desktop, or select-all and retype). Root cause: a desktop model copied without cursor, menu bar or shortcuts, so one tap carries too many meanings. A new long-press selection gesture fixed it but never shipped. |
| 17:51 | Desktop analog | The first Mac screen was 342 px high, so overlap was necessary. On today's huge screens, overlapping-window management is tiring, which is why tiling WMs exist. |
| 18:36 | Method | Know your present, remember your past, and make your questions clear before reaching for solutions. |
| 19:22 | Present: AI | AI enters the desktop either *above* the UX (Google's AI-pointer research and a shake-the-cursor assistant: an unchanged UX with AI sneaked in) or *below* it (a project hyped as an "AI OS" that is really OS scripting plus a chatbot; Apple on-screen awareness, Android AssistStructure and freedesktop.org efforts to read the screen for chat/voice). Nothing works *in the middle*. |
| 21:39 | The glimmer | AI was losing steam until Claude Code took context from the file system instead of the user. The same is happening with Obsidian and personal notes. He objects to frontier models on ethics and energy and prefers small, local, ethically trained models (Apertus). **The value is context, not generation.** |
| 23:56 | Building blocks | Windows, files/icons and the clipboard (plus mouse/keyboard) capture, move, edit and store data. That is direct manipulation, and it is **stateless**: come back tomorrow and nothing remembers what you did, and the clipboard silently overwrites. The dozens of WMs, shells, file managers and clipboard managers each patch one silo. Reframe it all as **working memory**, for people first and AI later. |
| 26:13 | Past | Lifestreams (documents on a timeline), WinFS (relational FS that records provenance: where from, who touched it), Nepomuk (KDE semantic desktop). They failed because hardware and systems weren't ready, not because the ideas were wrong. Remnants live on in Spotlight and Baloo. Revisit them, maybe simpler. |
| 27:44 | Questions | Design **only** for very large and ultra-wide monitors (the original Mac fits inside an iPad mini screen) and ignore laptops for the experiment. Fuse clipboard, files and windows into one concept. Capture user intent over time. Knuth caveat: the prototypes are rough on purpose. |
| 28:59 | **Prototype 1: spatial** | Widescreen simulation (see §3.S). |
| 32:20 | **Prototype 2: associative** | Document plus clip collection (see §3.A). |
| 33:55 | **Prototype 3: episodic** | Privacy-preserving attention history (see §3.E). |
| 36:08 | Wrap-up | The spatial / associative / episodic framing. He is pitching distros to build these as optional side experiments, Ink & Switch style (small team, fast prototype, open-sourced, as with *Upwelling*). Research in the open is open source's superpower, and someone has to start. |
| 39:10 | Q&A: privacy | Question: how is this not Windows Recall? Answer: a history store is a honeypot. Mitigate by collecting low-value signals (focus, not text), prototype first, then encrypt properly. Recall's real failure was weak protection. He treats it as solvable. |

## 3. Every idea and feature from the stage

IDs are stable. Later sections and issues cite them.

### 3.P Principles and critique

| ID | Time | Idea |
|---|---|---|
| P1 | 00:54 | Open source needs UX design help. Understaffing is the cause, not a lack of care. |
| P2 | 02:00 | Desktop UX is its own discipline, distinct from mobile/web UX. |
| P3 | 02:28 | Small details carry big value: middle-truncation of long names keeps the informative end visible. |
| P4 | 03:13 | Drag from a background window without raising it (select on down, raise on up). It is about moving data *into applications*. |
| P5 | 03:59 | Open source's superpower: "good idea" leads straight to "implemented" (KDE shipped P4 after his talk). |
| P6 | 03:59 | The desktop has not meaningfully changed in ~20 years, while what we do on computers has. |
| P7 | 04:46 | Linux copied Windows/Mac and drafted behind their research and mistakes. That strategy is over. |
| P8 | 05:31 | Perspective is worth 80 IQ points (Alan Kay): reframing beats raw effort. |
| P9 | 06:18 | Show prototypes, not just critique (lesson from the Ubuntu talk). |
| P10 | 06:18 | Apple optimizes for ecosystem lock-in, not for desktop improvement. |
| P11 | 07:50 | Microsoft degrades the desktop (upsell nags, Recall, ads). |
| P12 | 08:37 | Evolve via optional experiments beside the stable desktop, never a forced overhaul. |
| P13 | 09:23 | You cannot patch and bug-fix your way into the future. Someone must lead. |
| P14 | 09:23 | Mobile won consumption, not productivity. Desktops (keyboard + big screen) are quietly excellent. |
| P15 | 10:09 | "Standards" die (CD-ROM, BlackBerry). The laptop is only an ergonomic standard, and new hardware will arrive. |
| P16 | 10:55 | Respect users' tuned setups: grow into new tools gently and keep them optional. |
| P17 | 11:42 | Incremental change over radical change. |
| P18 | 12:30 | "UI/UX" is a harmful label. UX spans many disciplines and is not pixels. |
| P19 | 14:00 | UX layers: style, structure, strategy. |
| P20 | 14:00 | The quickest UX win is helping a team say no (hard in open source). |
| P21 | 14:48 | The fourth layer, "stuff": technology plus accepted conventions. Fixing the desktop starts there. |
| P22 | 15:33 | Mobile text editing is broken because a single tap is overloaded. A dedicated long-press selection gesture fixes it. |
| P23 | 16:19 | When a task is too hard, users stop doing it (they finish on desktop or retype). Watch for avoided tasks. |
| P24 | 17:05 | Much UX is copying without understanding why the original worked. |
| P25 | 17:51 | Overlapping windows are a leftover of tiny screens. On large screens they tire users, and tiling WMs are a symptom. |
| P26 | 18:36 | Method: present → past → clear questions. Rush to questions, not solutions. |
| P27 | 19:22 | AI is sucking the oxygen out of other desktop innovation. |
| P28 | 20:54 | AI arrives above the UX (pointer tricks) or below it (OS scripting, screen-reading), with nothing in the middle. The middle is the opportunity. |
| P29 | 21:39 | Tools got useful when they pulled context from the desktop (file system) instead of the user typing it. |
| P30 | 22:24 | Prefer small, local, ethically trained models: fewer environmental and privacy problems. |
| P31 | 23:10 | The value is context, not generation. Ask how the desktop can hold more context. |
| P32 | 23:56 | Building blocks: windows, files/icons, clipboard (+ mouse, keyboard). Their job is to capture, move, edit and store data. |
| P33 | 24:42 | The curse of direct manipulation: fast and powerful, but stateless. No memory across days, and the clipboard loses data. |
| P34 | 24:42 | Many alternative WMs, shells, file managers and clipboard managers show the pain, but each fixes its own silo. |
| P35 | 25:27 | Treat the desktop holistically as **working memory**. |
| P36 | 25:27 | Design for people first. AI benefits later as a side effect. |
| P37 | 26:59 | Failed visionary projects did not prove the ideas wrong. The hardware of the time let them down, so revisit them, possibly simpler. |
| P38 | 27:44 | Design question: what if we designed **only** for very large or ultra-wide monitors? |
| P39 | 27:44 | Design question: how do clipboard, files and windows become one holistic concept? |
| P40 | 27:44 | Design question: how do we capture user intent over time? |
| P41 | 28:29 | Premature optimization is the root of all evil (Knuth). Prototypes are allowed to be rough. |
| P42 | 36:08 | The three memories: **spatial, associative, episodic**. |
| P43 | 36:53 | Build these as optional experiments, pitched to distros. |
| P44 | 36:53 | Ink & Switch model: small team, fast prototype, open-source the result. Research in the open. |
| P45 | 37:39 | Working memory is one perspective; others are welcome. |

### 3.R References and prior art named on stage

| ID | Time | Reference | Why it was cited |
|---|---|---|---|
| R1 | 02:28 | Mac Finder middle-ellipsis truncation | Example of a small detail that lasts (P3) |
| R2 | 03:13 | Mac click-through drag from a background window, later implemented in KDE | P4, P5 |
| R3 | 04:46 | Xerox Star → Macintosh → Windows → Linux distros | Lineage (P7) |
| R4 | 05:31 | Clippy | The kind of mistake worth letting others make first |
| R5 | 05:31 | Alan Kay, "perspective is worth 80 IQ points" | P8 |
| R6 | 06:18 | Apple 2017 (Mac neglect, "What's a computer?" iPad ad), Liquid Glass | P10 |
| R7 | 07:50 | Microsoft OneDrive sign-up nags, Recall, ads | P11 |
| R8 | 12:30 | Don Norman coined "user experience"; Figma-era narrowing of UX | P18 |
| R9 | 14:48 | Scott Jenson, *The Simplicity Shift* (the "stuff" layer) | P21 |
| R10 | 15:33 | Android text-editing study and long-press selection (unshipped) | P22 |
| R11 | 17:51 | Original Macintosh 512×342 screen | P25 |
| R12 | 19:22 | Google "AI pointer" research; shake-the-cursor assistant on Google laptops | AI above the UX (P28) |
| R13 | 20:09 | A project marketed as an "AI OS" (his view: OS scripting plus a chatbot) | AI below the UX (P28) |
| R14 | 20:54 | Apple on-screen awareness, Android AssistStructure, freedesktop.org screen-context work | Screen-reading for chat/voice (P28) |
| R15 | 21:39 | Claude Code (context from the file system), Obsidian | P29, P31, and the model for A1 |
| R16 | 22:24 | Apertus (Swiss, ethically sourced data, large and small models) | P30 |
| R17 | 24:42 | Many Linux window managers, alternative shells, file managers, clipboard managers | P34 |
| R18 | 26:13 | Lifestreams (1990s): documents organized on a timeline | Episodic memory prior art |
| R19 | 26:13 | WinFS: relational file system recording provenance | Associative/episodic prior art |
| R20 | 26:13 | Nepomuk (KDE semantic desktop); remnants in Spotlight and Baloo | P37 |
| R21 | 28:29 | Donald Knuth, premature optimization | P41 |
| R22 | 29:15 | Mac Exposé | The baseline that S2 improves on |
| R23 | 30:47 | Virtual desktops | Power-user tool that consumers don't use (S9) |
| R24 | 31:32 | Responsive web design | Model for window → widget (S10) |
| R25 | 32:20 | Wayland | Judged able to do all of this today (S14) |
| R26 | 36:53 | Ink & Switch, *Upwelling* | P44 |
| R27 | 39:10 | Windows Recall's security failure | Q1–Q5 |

### 3.S Prototype 1: spatial memory (28:59–32:20)

| ID | Feature as shown |
|---|---|
| S1 | A **widescreen simulation**: design for an ultra-wide display first (P38). |
| S2 | **Exposé critique**: with double the windows it degrades into a plain grid sort, it is *modal*, and you can't work in the thumbnails, even though small windows are still useful. |
| S3 | **Center vs periphery**: the far sides of a wide screen suit peripheral vision, not work. |
| S4 | **Move the menu bar and corner icons inward**, toward the center. |
| S5 | A **central ~50% focus zone**, with a background that visually marks center vs periphery (a demo aid, not a shipping look). |
| S6 | **Drag toward the side and the window shrinks continuously** as it approaches the edge. It docks in the side area and can be pulled back out at full size. |
| S7 | A continuous morph/slide while dragging was tried and **rejected as illegible**, so it is a plain scale. |
| S8 | **Stashed windows stay live**: still real windows, selectable and interactive (not every window supports this). |
| S9 | **Organic, messy organization instead of virtual desktops**, which suit organized power users but not most people. |
| S10 | **Window → widget**: a stashed window *reflows* like responsive web. The music player collapses into a play/pause button. |
| S11 | The hybrid is **part window manager, part Exposé**: always-on, not a modal overview. |
| S12 | **Shake a window** and every *other* window flies to the sides automatically. |
| S13 | **It scales**: shake still works with 2× and more windows. |
| S14 | This is feasible on Wayland today. Next step: a real prototype to test the feel, and iterate if it's wrong. |

### 3.A Prototype 2: associative memory (32:20–33:55)

| ID | Feature as shown |
|---|---|
| A1 | A **document with an attached collection pane**, Obsidian-inspired. |
| A2 | **Park, don't process**: select text you don't want to handle now and drag it into the collection. |
| A3 | It is **not clipboard history but a clipboard *file*** that belongs to that document. |
| A4 | **Heterogeneous items**: text snippets, files dragged from the file manager, items dragged from the web browser. |
| A5 | **Persistence**: close the document, come back tomorrow, and the collection is still there. |
| A6 | **Local AI acts on the collection**: it notices several hotel items and offers to organize them. |
| A7 | **Select items → derive an artifact**: asking for a map of the selected hotels produces one, which you drag into the document. |
| A8 | **Split screen**: view *and edit* collected items beside the document. |
| A9 | Moving items back and forth adds up to a **lightweight virtual desktop scoped to the task**. |

### 3.E Prototype 3: episodic memory (33:55–36:08)

| ID | Feature as shown |
|---|---|
| E1 | **Privacy-preserving telemetry**, because rich capture makes people nervous. |
| E2 | Test set: **50 pages** browsed while shopping for an e-bike. Browsers show them as a linear list (or a weak tree). |
| E3 | Collect **attention signals, not content**: dwell time, scroll depth, whether a copy happened, whether a paste happened (never the text). |
| E4 | **Simple math, no AI**, condenses 50 nodes into **~7**: the search, the three pages that mattered, where you landed, the "keep" action. An opinionated view. |
| E5 | E4 is a *feasibility proof*, not a user-facing UI. |
| E6 | **Desktop-wide history as a story**: mail → opened a document → fetched an image → worked in the document. |
| E7 | **History mode on the collection (provenance)**: every clip shows where it came from (a part of a doc, a budget from a file window, a map from a web page). |
| E8 | **Annotate collected data with that story**, locally and privately, gathering as little as possible. |

### 3.Q Q&A: privacy (39:10–40:52)

| ID | Point |
|---|---|
| Q1 | A history store is a honeypot and will be attacked. |
| Q2 | Mitigate by collecting *uninteresting* data: focus and attention signals, never text. |
| Q3 | Prototype first to learn whether it helps, then design encryption and protection. |
| Q4 | People already keep bank details on their machines. This is a small step beyond that, so be very careful. |
| Q5 | Recall's biggest mistake was how weakly it protected its data. That is a solvable problem. |

## 4. Sources, code, and what the reference prototypes do

### 4.1 The talk
- **Recording:** <https://media.ccc.de/v/kde2026-7-are_we_really_going_to_use_the_same_desktop_ux_forever>. CC BY-SA 4.0; MP4/WebM/AV1/MP3/Opus downloads; **no subtitles, no slides**.
- **Mirror:** <https://youtu.be/V7AfAcQwLW0>. YouTube's auto-captions are the only transcript.
- **Abstract:** <https://conf.kde.org/event/11/contributions/332/>. Sat 2026-09-19 15:35, Room 2, no materials attached. The program is at <https://akademy.kde.org/2026/program/>.
- **Write-up:** LWN, "Ideas on modernizing the open-source desktop" (J. Brockmeier, 2026-09-23), <https://lwn.net/Articles/1095425/>.
- **Slides:** none published as of 2026-09-25.

### 4.2 Jenson's prototype code: readable, not reusable
All live at <https://github.com/scottjenson>. **Every repo has no license** (checked 2026-09-25 via the GitHub API), which means all rights are reserved. Read them for behavior and parameters, then write our own code; copy no code or assets. The summaries below are ours.

| Repo | Stage demo | Stack | What it shows (ideas and parameters only) |
|---|---|---|---|
| `Desktop5` | Prototype 1, spatial | three.js r185 + Chrome's experimental HTML-in-canvas (flag, Chrome 150+); a 3440×1440 ultra-wide stage, letterboxed | - A background "tension grid" is square in the center and compressed toward the edges. A window's scale follows the same power curve, and its scale is the derivative of the grid warp, so shrinking reads as space compressing.<br>- **Shake stashes every other window into two columns per side**: an inner column at about 0.62 scale holds the most recent windows, an outer one at about 0.22 takes the overflow, packed vertically without overlap.<br>- Shake is **stateless on purpose**: no restore-all. A session-based "park all" was built and then removed.<br>- Also: shift-drag edge snap, shift-click stash, Exposé and window-doubling demo keys.<br>- Morph experiments found text survives horizontal squeeze but not vertical shear. |
| `Desktop6` | Prototype 2, associative | Plain DOM + vanilla JS, no build | - A scrapbook panel attached to a document viewer slides out from its side without moving the document.<br>- **Drops land flat and messy**: document text becomes a *cut* snippet, browser text a *copy* snippet, a URL a web-page row, a file icon a file row.<br>- Items are later grouped into a **folder, which is the unit an AI action runs on**: folder → prompt → map item.<br>- A two-up split mode, and the document plus scrapbook minimize together to one desktop icon.<br>- **History toggle**: hovering an item reveals its source window and highlights the exact origin. A cut leaves a hidden anchor in the document so the origin survives.<br>- The clipboard and file plumbing is narrated rather than real; the drags are real. |
| `DesktopUX1` | Prototype 3, episodic | Vanilla JS/SVG, no build | - A 50-visit e-bike session. Per-visit signals: dwell, max scroll %, clipboard event (copy/paste), transition type (search, link, tab/app switch, new tab, form submit…), parent visit.<br>- **Revisits collapse into "places".** A multi-signal **anchor score** combines scroll-gated dwell, copies, pastes received, hub structure and a long-dwell fallback. Its weights were grid-searched to match a hand-labeled set.<br>- About 6 anchors result, with satellites orbiting them and edges drawn for copy → paste flow.<br>- Stated principles: multiple signals beat one, continuous encodings beat tiers, capture explicit events (the paste destination) rather than inferring them. |
| `Desktop4` | The activity-timeline idea | Vite + React Three Fiber | - **Swim lanes per activity category on a time axis.**<br>- Telemetry is split into *navigation edges* (from → to, switch vs spawn; revisits reuse one id, which marks hubs) and *per-visit summaries*: total duration, passive dwell, max scroll, and event verbs (typing, cut/copy/paste, **transmit** = send/save).<br>- The v2 score adds foreground *focus seconds*.<br>- Scores map to three block heights, and runs of consecutive low-score visits are fenced into a compact cluster. |
| `FocusStream`, `FocusStream2` | Attention capture | Chrome MV3 extension; Swift for macOS | - Counts interactions (scroll, typing, click, audio) only in the focused, visible tab, on a 10 s heartbeat.<br>- **Never stores keystrokes or clipboard contents.** Data stays local and is purged after 7 days.<br>- A Lifestreams-style ribbon: width is dwell, height/brightness is engagement, repeat visits chain together. |
| `Lineage` | Provenance of highlighted text | Python + Screenpipe + Gemini | Recovers where a piece of text came from by searching recorded screen text and screenshots. **This is the Recall-style approach we reject** (Q2). Our provenance is recorded structurally at capture time. |
| `DesktopUX0`, `DesktopUX3` | Earlier explorations | Web | A desktop with files and clipboard snippets side by side; a 3D window organizer for large screens. |

### 4.3 Related talks and writing
- **Ubuntu Summit 25.10**, "Are we stuck with the same Desktop UX forever?" (2025-10-24), the viral predecessor: <https://www.youtube.com/watch?v=1fZTOjd_bOQ>. Abstract: <https://discourse.ubuntu.com/t/are-we-stuck-with-the-same-desktop-ux-forever/67253>
- **Local-first conference talk:** <https://www.youtube.com/watch?v=-IOLRcFC6OY>
- **InfoQ podcast** (2026-08-31), which walks through all three prototypes: <https://www.infoq.com/podcasts/evolving-desktop-agentic-ux/>
- **jenson.org essays:** <https://jenson.org/files/>, <https://jenson.org/files2/>, <https://jenson.org/small/>, <https://jenson.org/ma/>, <https://jenson.org/talks/>
- ***The Simplicity Shift*** (2002), free PDF from the author: <https://jenson.org/The-Simplicity-Shift.pdf>
- **An independent implementation:** "Funnel", a COSMIC compositor fork where windows shrink toward the screen edges and dock into stacks. GPL-3.0, credits the Ubuntu talk: <https://github.com/mergedeyes/cosmic-comp>

### 4.4 References cited on stage (by R-ID)
| ID | Source |
|---|---|
| R1 | AppKit `byTruncatingMiddle`: <https://developer.apple.com/documentation/appkit/nslinebreakmode/bytruncatingmiddle> |
| R2 | KDE bug 489806 <https://bugs.kde.org/show_bug.cgi?id=489806>, fixed by Xaver Hugl in KWin commit `5f852805` <https://invent.kde.org/plasma/kwin/-/commit/5f85280563cc44988c083737acfd7fdc0d607721> (Plasma 6.3.0) |
| R3 | <https://en.wikipedia.org/wiki/Xerox_Star> |
| R5 | <https://quoteinvestigator.com/2018/05/29/pov/> |
| R8 | <https://www.nngroup.com/articles/definition-user-experience/> |
| R9 | <https://jenson.org/The-Simplicity-Shift.pdf> |
| R12 | Google DeepMind AI pointer <https://deepmind.google/blog/ai-pointer/>; the Googlebook "Magic Pointer" shake-to-summon <https://www.androidauthority.com/magic-pointer-gemini-in-google-chrome-3666405/> |
| R13 | *Inferred, unconfirmed:* DHH's Omarchy <https://omarchy.org/> (the auto-caption reads "DHS") |
| R14 | Apple on-screen awareness (WWDC24 10133) <https://developer.apple.com/videos/play/wwdc2024/10133/>; Android `AssistStructure` <https://developer.android.com/reference/android/app/assist/AssistStructure>. The freedesktop.org effort was **not found**; the closest is a local-AI portal discussion at <https://github.com/containers/ramalama/discussions/1098> |
| R16 | Apertus, ETH announcement <https://ethz.ch/en/news-and-events/eth-news/news/2025/09/press-release-apertus-a-fully-open-transparent-multilingual-language-model.html>; models incl. 0.5B/1.5B/4B at <https://huggingface.co/swiss-ai> |
| R18 | Lifestreams (Freeman & Gelernter, SIGMOD Record 25(1), 1996) <https://sigmodrecord.org/publications/sigmodRecord/9603/pdfs/381854.381893.pdf>; project page <http://cs-www.cs.yale.edu/homes/freeman/lifestreams.html> |
| R19 | <https://en.wikipedia.org/wiki/WinFS> |
| R20 | <https://en.wikipedia.org/wiki/NEPOMUK_(software)>; Baloo <https://invent.kde.org/frameworks/baloo> |
| R21 | Knuth, "Structured Programming with go to Statements" (1974), DOI 10.1145/356635.356640 |
| R22 | <https://en.wikipedia.org/wiki/Mission_Control_(macOS)> |
| R26 | <https://www.inkandswitch.com/upwelling/> |
| R27 | <https://en.wikipedia.org/wiki/Windows_Recall>; the extraction tool that exposed it <https://github.com/xaitax/TotalRecall> |

### 4.5 Open-source building blocks (reference designs; the platform rule is zero new dependencies)
- **Web window managers:**
  - WinBox.js (Apache-2.0, vanilla) <https://github.com/nextapps-de/winbox>
  - interact.js (MIT; drag, resize, snap) <https://github.com/taye/interact.js>
  - daedalOS (MIT, React) <https://github.com/DustinBrett/daedalOS>
  - OS.js (BSD-2, dormant) <https://github.com/os-js/OS.js>
  - Puter (AGPL; avoid) <https://github.com/HeyPuter/puter>
- **Shake:** KWin's shake-cursor plugin (GPL; read the method, don't copy) <https://invent.kde.org/plasma/kwin/-/tree/master/src/plugins/shakecursor>. Precedent: Windows Aero Shake.
- **Window → widget:** CSS container queries <https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_containment/Container_queries>
- **Collection file format:** JSON Canvas (MIT), Obsidian's open canvas format <https://jsoncanvas.org/>
- **Timelines:** vis-timeline <https://github.com/visjs/vis-timeline>; TimelineJS3 (MPL-2.0) <https://github.com/NUKnightLab/TimelineJS3>. any-concurrency's own lanes come first.
- **Attention capture without content:**
  - ActivityWatch + aw-watcher-web (MPL-2.0, local-only) <https://github.com/ActivityWatch/activitywatch>
  - the Intersection Observer and Page Visibility APIs
  - Plausible's scroll-depth model (AGPL; take the idea only)
- **Clip provenance:** Obsidian Web Clipper (MIT) <https://github.com/obsidianmd/obsidian-clipper>; the `SourceURL` field in the Windows HTML clipboard format <https://learn.microsoft.com/en-us/windows/win32/dataxchg/html-clipboard-format>
- **Screen-recording recall** (the approach we reject): OpenRecall (AGPL) and Screenpipe (now commercial).

## 5. Where the platform stands (verified 2026-09-25)

### Console (`platform-base/console`)
- **One app at a time.** There is a single `<iframe id="frame">` (`static/index.html:53-54`). The router is `parseModuleHash()` / `route()` (`static/app.js:319,336`). An app's inner route arrives as a `bina:route` postMessage and is mirrored with `replaceState`, accepted only from `#frame` (`app.js:368-385`). The layout is a `238px | 1fr` grid (`style.css:114`), with an icon rail on tablet and a bottom bar on phone (`style.css:385-411`).
- **No server-side state.** Only the rail state and theme, kept in browser storage (`app.js:212-240`). The console has no volume (`app.json:74-77`).
- **Palette searches modules only** (Cmd/Ctrl-K, `app.js:251-289`). There is no toast channel: native `confirm`/`alert`/`prompt` are used (a platform-ui-ux anti-pattern).
- **Every app is same-origin under `/a/<alias>/`** through the console's reverse proxy (`app.py:332-406`). The proxy injects `<base>`, rewrites URLs and can add per-app CSS (`app.py:292-300`). WebSockets bypass it through Traefik (`platform/manager/reconcile.py:777-829`).
  → The shell *can* read focus, scroll, selection and copy/paste events inside every frame without changing the apps.
- **Capacity.** 1 gunicorn worker × 16 threads (`gunicorn.conf.py`), capped at 0.5 CPU / 256M (`docker-compose.yml:42`). An SSE stream holds a thread with no read timeout (`app.py:353-358`). Every live window adds proxied load, so **windows need a budget.**
- **Per-user identity** exists only at the console, as `X-authentik-*` headers (`app.py:25,71-76`).

### any-concurrency (`platform-base/any-concurrency`)
- **Stack.** FastAPI (`app.py`, ~2.8k lines) plus a one-page UI (`static/index.html`).
- **Span model.** `{id,src,svc,svcid,label,status,s,e,d,meta}` (`_IngestSpan`, `app.py:2667`), kept in per-source **in-memory** `RingStore` deques (`app.py:660`). There is no DB and no user field.
- **Sources:**
  - n8n executions and event log
  - Traefik access log and Docker events
  - `CUSTOM_SOURCE_*` lanes (drive, mail, apitools)
  - `SPAN_SOURCE_INDOX`
  - webhook ingest: `POST /ingest/span(s)` and `/ingest/span/{id}/close` behind `ENABLE_WEBHOOK`
- **Read APIs.** `/api/spans` (up to 14 days), `/ws`, `/api/span/{id}`, `/api/sources`.
- **UI.** Lanes grouped system → process → stacked lanes, 15-minute to 7-day windows, zoom/pan, a detail drawer. It polls every 3.5s. It has no URL state and no `bina:route`.
  - `inspiration/` holds 12 DAW/NLE screenshots: track headers, collapsible lanes, clips on one shared time ruler.
- **Every ingested span is broadcast to every viewer**, so nothing personal may ever be ingested.
- **Known cost.** `issues/any-concurrency-resource-intensive.yaml`: the top CPU consumer; 8 concurrent `/api/spans` calls slow from 0.86s to 4.56s.

### Rules any design here must obey
- **platform-ui-ux skill** (`.claude/skills/platform-ui-ux/SKILL.md`):
  - Hebrew-only UI text, existing tokens and components, no emoji, one toast channel.
  - Every screen is a URL with empty/loading/failure states.
  - A written design plan before the first edit (this doc).
  - Proof by screenshots in the owner's Chrome plus flow-qa.
- **Navigation design** (`ai/context/platform-navigation-design.md`): zero new dependencies or build steps, one delegated listener, collapsing never reloads the iframe, no abstraction before the third use.
- **URL state** (`ai/context/console-url-state.md`): the URL is the state, and storage is only a backup.
- **Gates:**
  - G9 layering: the console may not name layer-3 apps, so per-app widgets must be declared in each app's `app.json` and compiled by reconcile.
  - G27: theme tokens byte-identical.
  - G30: memory budget for any console limit change.
- **Harness contract: exactly one `#frame`.** It is assumed by:
  - `digital-office/sim/build.mjs:288-300`
  - `sim/overlay/responsive.js:64`
  - `flow-qa.py` (`frame_locator('iframe')`)
  - `scripts/ui-coverage/{capture,live-ui-map,sim-live-parity}.py`
- **This Mac** has no Docker, node or playwright, so offline sim/flow-qa proofs must run elsewhere until those are installed.

## 6. Target design: "Desktop mode" (שולחן עבודה)

Desktop mode is an **optional mode beside the current shell** (P12, P16, P43) and ships incrementally (P17). It is built for people first (P36), treats context as the point rather than generation (P31), and is designed for ultra-wide screens first (P38).

### 6.1 Modes
| Mode | Width | Behavior |
|---|---|---|
| `classic` | any | Today's single-frame shell, **unchanged and the default**. Every harness contract stays valid. |
| `desktop` | ≥ 1280 px | Opt-in per user from the account chip. Below 1280 px it falls back to classic plus a "windows" sheet, so phone and tablet stay as they are. |

### 6.2 Windows (spatial core)
- **Anatomy.** A window is a frame, a title bar and a body. The title bar carries the app icon, a **middle-truncated** title (P3) and actions: stash, maximize, close. The body is an iframe on `/a/<alias>/<inner>` or a native console view.
- **Interaction.**
  - Move, 8-handle resize, focus and raise, all with native Pointer Events and no library.
  - On console-native content, raise on **pointer-up**, so dragging out of a background window works (P4).
  - Optional snap-to-halves inside the focus zone, for tiling users (P25).
- **Keyboard.** Cmd/Ctrl-K lists open windows plus modules; Alt+\` cycles windows.
- **URL.**
  - `#/m/<id>/<inner>` keeps its meaning: open or focus that app's window at that route. The focused window's route is mirrored to the URL.
  - `bina:route` is accepted from every window's frame, keyed by `event.source`.
  - The whole layout is a server-saved workspace named in the URL (decision D3).

### 6.3 Focus zone and periphery (S1–S5)
- **Zone width.** 50% of the screen at ≥ 2560 px (S5), about 64% at 1920 px, about 76% at 1440 px. The remaining width is the left and right periphery.
- **Top bar.** Title, palette and account chip span **only the focus zone** (S4). The module rail becomes a launcher inside the zone.
- **Zone marker.** A token-based background marking zone vs periphery, as a dev toggle only (S5).

### 6.4 Stash rails (S6–S9, S11, S13)
- **Continuous shrink.** Dragging toward an edge scales the window uniformly by a power curve of its depth into the periphery (S6). The zone-marker background (S5) is warped by the same curve, so the shrink reads as space compressing, which is how `Desktop5` ties them (§4.2).
  - There is no content morph (S7). The prototype found text survives horizontal squeeze but not vertical shear.
  - `scale = 1 − (1 − s_min)·t^k`, with `t = clamp(depth / peripheryWidth, 0, 1)`, `s_min ≈ 0.22` and `k` tuned by eye.
  - Every rail position must sit **on** the curve, so re-grabbing a stashed window never jumps in size.
- **Dock and pull back.** A drop with `t > 0.5` docks into the rail. Pulling a stashed window back restores its last full rect.
- **Stashed windows stay live** (S8): `transform: scale()` keeps the iframe interactive with correct hit-testing.
- **Two columns per side** (S13), matching the reference prototype: an inner column at about 0.62 scale holds the most recent windows, and an outer column at about 0.22 takes the overflow. Both are packed top-to-bottom without overlap.
  - Only at extreme counts do the oldest windows collapse into clickable title chips.
- **No modal overview.** The rails are an always-on overview that replaces Exposé (S2, S11), and there are no virtual desktops by default (S9).

### 6.5 Window → widget (S10)
- **Real reflow, not just scaling.** A stashed window gets a **real narrow viewport** (for example 280×180), so the app's own responsive CSS reflows it. This mirrors responsive web (R24).
- **Opt-in declaration.** Apps opt in through `app.json`: `routing[].module.widget = {path?, min:[w,h], pref:[w,h]}`. Reconcile compiles it into `console.modules.yaml`, which is G9-safe.
  - Without a declaration, the window stays a scaled live preview (S8).
  - Simple cases can use the proxy's existing per-app CSS injection.
- **Protocol.** The shell posts `bina:display {mode:"full"|"widget", w, h}` to the frame.
- **First widgets to prove the contract:**
  - INDOX: documents-waiting count plus the last 3
  - mail: unread count plus the top 3 threads
  - notifications: the last 5
  - chat: last message plus quick reply
  - any-concurrency: a "running now" mini-lane

### 6.6 Shake (S12–S13)
- **Detection.** During a title-bar drag: ≥ 4 horizontal direction reversals of ≥ 24 px within 600 ms, with net displacement under 200 px. Cooldown 800 ms.
- **Effect.** Every other unpinned window flies to the rail on its own side (by center x), keeping recency order, while the shaken window stays under the pointer.
- **Stateless by default**, like the reference prototype: stashed windows stay where they land and come back one at a time by dragging. Jenson built a restore-all session and removed it on purpose.
  - A shake-again-to-restore toggle (Aero Shake style) is a later A/B experiment, not the default.
- **Reduced motion.** With `prefers-reduced-motion`, windows move with no animation.

### 6.7 Live-window budget
- **Budget.** At most `N` live iframes (default 6, env-tunable).
- **Sleeping windows.** Beyond the budget, the least-recently-focused windows **sleep**: the iframe goes to `about:blank`, and the title, icon and last inner route are kept. Waking reloads the deep link, and sleeping frees their SSE threads.
- **Before raising `N` or the console's threads or memory (G30):** add a read timeout to proxied SSE (`app.py:353-358`).

### 6.8 Collections: associative memory (A1–A9)
- **Scope.** A collection belongs to the **object** a window shows (`my-docs:doc/<id>`, `indox:document/<id>`, `mail:thread/<id>`, a client company). This is the per-document "clipboard file" (A3).
- **Views.**
  - A pane docked to its window's side, toggled from the title bar (A1).
  - It can pop out as a window beside the document for split-screen editing (A8), which gives a task-scoped desktop (A9).
- **Item kinds** (A4): text, file reference, link, image, app object.
- **Provenance on every item** (E7): `{app, window_title, deeplink, captured_at, how: drag|paste|share|derived, parents[]}`.
- **Capture paths:**
  - drag or paste from any same-origin frame
  - OS file drop, handed to the app that owns files, so the console never names drive (G9)
  - a `bina:clip` postMessage from apps offering "add to collection"
- **Drops land flat and messy.** Organizing comes later: the user groups items into **folders**, and a folder is the unit an AI action runs on (A6–A7), as in `Desktop6`.
- **Cut vs copy.** Text dragged out of an app document is a *cut* snippet, and text from anywhere else is a *copy*.
  - Opt-in and app-side: a cut leaves a hidden anchor in the source document so provenance can point back to the exact spot (E7).
- **One unit.** A document and its collection move, stash and minimize together.
- **Persistence.** Stored server-side per user, so it survives restarts (A5). Export as a JSON Canvas file (§4.5) lets it leave the platform as a real file (A3).
- **AI actions** (A6–A7, last phase, opt-in): organize, table, summarize, draft a reply, map. Each produces a **derived item** whose `parents[]` keep the provenance and which can be dragged into the document.
  - Accounting-office examples: a table of these invoices, a comparison of these quotes, a reply drafted from these facts.

### 6.9 Episodic memory, with any-concurrency as the timeline (E1–E8, Q1–Q5)
- **Signals** (E3) are emitted by the shell only and carry no content. The schema follows `Desktop4`/`DesktopUX1`:
  - **A place** is an app object (`indox:document/<id>`, `mail:thread/<id>`, `drive:file/<id>`, `my-docs:doc/<id>`, a console view). A revisit reuses the same id, which is how hubs show up.
  - **Navigation edges:** `{ts, from_place, to_place, transition}`, where `transition` is one of palette, deep link from another app, notification, drag, new window, or switch to an existing one.
  - **Visit summaries:** `{place, arrived, left, total_s, focus_s, passive_s, max_scroll_pct, events:{typing_n, cut_n, copy_n, paste_n, transmit_n, clip_n}}`. *Transmit* means the visit finalized something: sent a mail, approved an INDOX document, saved a doc.
  - **Also recorded:** stash, unstash, shake and mode switches.
  - **Never** text, keystrokes, clipboard contents or screenshots. `typing_n` is a count. That is the line Recall crossed (R27, Q2) and that `Lineage` and Screenpipe cross (§4.2).
- **Store.** Private per user and tenant-local, with 30-day retention by default, pause, forget-this-range and export (Q1, Q3, Q5).
- **Condensation** (E4), plain math with no AI, following the structure of `DesktopUX1`/`Desktop4` with our own weights:
  1. Split sessions at idle gaps over 20 min.
  2. Collapse visits into places.
  3. Score each place: scroll-gated dwell (`total_s × max_scroll/100`, or `focus_s` for places that don't scroll) + a modest focus credit + weighted copy/paste/transmit/typing/clip counts + a hub bonus for places many edges leave from.
  4. **Calibrate the weights** with a grid search against a few hand-labeled sessions from real use, as the prototype did. Never ship its numbers unexamined.
  5. Map scores to three tiers (high/medium/low) that drive block height in the lanes, and fence runs of consecutive lows into a collapsible cluster.
  6. Target about 6–9 anchors per session. Satellites attach to their anchor, and copy → paste edges show where value moved.
- **Story view** (E6): "mail → invoice in INDOX → file from drive → worked in my-docs", with times.
- **History mode on a collection** (E7): each item shows its source chip, and clicking it opens the source window at the deep link.
- **The timeline window**, which combines the talk with any-concurrency:
  - It uses any-concurrency's lane UI pattern (DAW-style ruler).
  - The top lanes are **"You"**: your episodes, drawn from your private store.
  - Below them are **system lanes** from any-concurrency `/api/spans` for the same range: n8n executions, INDOX processing, mail/drive/apitools lanes.
  - **The join happens in the viewer's browser.** Personal data never enters any-concurrency, whose store broadcasts to all viewers.
- **Correlation** (E8, P40). When a span's `meta` names an object the user touched, draw the link: you uploaded → INDOX processed → n8n executed.
- **Episodic → spatial restore.** Pick a moment on the timeline and choose *restore this workspace*: that episode's windows reopen in their layout.

### 6.10 Owners (one owner per fact)
| Fact | Owner | Why |
|---|---|---|
| Window manager, modes, signals emitter, timeline view | `platform-base/console` — new `static/desktop.js` + `desktop.css`, loaded only in desktop mode | The shell owns the viewport (PORT-PLAN C16) |
| Layouts, collections, items, episodes | **new `platform-base` service (working name `memory`)** — per-user from authentik headers, SQLite or platform Postgres, with backup coverage | The console has no volume, 256M and 16 proxy threads. any-concurrency is in-memory, broadcasts to everyone, and is already the top CPU consumer |
| System spans | `platform-base/any-concurrency`, unchanged at first. Later: bounded range queries, URL state + `bina:route`, object ids in `meta` | It already ingests every system source |
| Widget declaration, `bina:clip`, `bina:display` | each app's `app.json` / frontend, opt-in | G9 layering |

## 7. Phases (each ships behind the desktop-mode toggle; one perfect example → review → scale)

| Phase | Scope (IDs) | Acceptance |
|---|---|---|
| 0. Prerequisites | Generalize the sim's `#frame` patch to every `/a/` iframe (`build.mjs:288-300`) and fix the stale `overlay/responsive.js:64` and `switcher.js:29`. Add a `desktop` flow-qa suite and target windows by app id instead of `frame_locator('iframe')`. Add an **ultrawide** profile (3440×1440) to `view-profiles.yaml` (S1, P38). Install node + playwright or run proofs on the VPS. Owner decisions D1–D7. | Classic mode unchanged; every existing suite still green. |
| 1. Windows | 6.2 with 3 apps first (INDOX, mail, drive), then all tiles. Toast channel replaces native dialogs on touched paths. | 8 windows open at 1440×900 and 3440×1440 with 0 JS errors; `#/m/mail/…` focuses mail; reload restores the layout; switching modes keeps the focused frame loaded. |
| 2. Zone + stash + shake | 6.3, 6.4, 6.6, 6.7 (S1–S9, S11–S13) | Drag to the edge → stashed at scale < 0.5 and still clickable. Pull back → original rect ±2 px. Shake with 12 windows → all others land in the two rail columns and the shaken window stays under the pointer. Re-grabbing a stashed window shows no size jump. Live iframes ≤ N. |
| 3. Widgets | 6.5 (S10): schema in `platform/schema/app.schema.json`, reconcile compile, `bina:display`, first 3 widgets | Stashed INDOX reflows at 280 px with no horizontal scroll; clicking opens the full window at the right deep link. |
| 4. Collections | 6.8 (A1–A5, A8–A9) + provenance data (E7) + the `memory` service | Drag text from mail, a drive file and a link into a my-docs document's collection. Restart the services → all still there. Every chip opens its source. |
| 5. Episodes + timeline | 6.9 (E1–E8, Q1–Q5) | A synthetic 50-page session condenses to 5–9 nodes. A test rejects any free-text field in the signal schema. The day view shows "You" lanes above system lanes on one ruler. *Restore* reopens the windows. |
| 6. AI on working memory | A6–A7, opt-in | Derived items carry `parents[]`. Nothing leaves the tenant unless D6 says so. |

## 8. Decisions for the owner

| # | Question | Recommendation |
|---|---|---|
| D1 | Desktop mode beside classic, or replacing it? | Beside it, opt-in (P12, P16) |
| D2 | Where working memory lives | A new `platform-base/memory` service |
| D3 | Layout in the URL | `#/m/<focused>` + `&ws=<workspace id>` (server-saved) |
| D4 | Live-window budget and console limits | N = 6; add an SSE read timeout before raising threads or memory (G30) |
| D5 | History retention and visibility | 30 days, owner-only, admins never |
| D6 | Model for A6–A7 | Start with the existing chat/bina-ds plumbing; move to a local small model when feasible (P30) |
| D7 | Theme | The UI skill says light-only while the console ships dark tokens; pick one for desktop mode |

## 9. Risks

| Risk | Mitigation |
|---|---|
| 16 proxy threads exhausted by many windows / SSE | Live budget, sleeping windows, SSE read timeout |
| Every UI harness assumes one `#frame` | Phase 0; classic stays default, so existing gates keep their meaning |
| History becomes a honeypot (Recall) | Content-free schema enforced by a test, private per-user store, pause/forget/retention, no admin access |
| any-concurrency load | Bounded range queries, refresh only while the timeline is visible, no new polling loops |
| Scope creep | 3 apps → review → all tiles; one phase at a time |
| Demo stills not captured (the browser pane was hidden during research) | Capture frames at 29:15, 30:02, 30:47, 31:32, 32:20, 33:05, 33:50, 34:35, 35:22. Or run `Desktop6`/`DesktopUX1` locally (plain static servers); `Desktop5` needs Chrome 150+ with the HTML-in-canvas flag |
| Copying unlicensed prototype code | Clean-room only: take behavior and parameters from §4.2, never files or snippets |

## 10. Implementation status: desktop mode v1 (2026-09-25)

**Where it lives.**
- `platform-base/console/static/desktop.js` + `desktop.css`: clean-room, vanilla JS, no dependencies, no build step.
- Hooks in the shell:
  - `app.js`: `openModule()` hands every module to the desktop when it is on; `boot()` mounts it before the first `route()`; `refreshModules()` rebuilds the dock.
  - `index.html`: loads `desktop.css` and `desktop.js`.
  - `modules.yaml`: new console-own view **"הגדרות מסוף"** (`#/m/settings`).

**How to turn it on.** Open *הגדרות → הגדרות מסוף → מצב שולחן עבודה*. It works on screens ≥ 1024 px; narrower screens stay classic.
- State is kept in the browser: `do-desktop`, `do-desktop-prefs`, `do-desktop-layout`. That settles D2 for v1 by deferring it; there is no per-user server state yet.
- A console-own view opens inside a window as the shell itself in bare mode (`/?bare=1#/m/<id>`).

**Local preview without Docker:** `python3 digital-office/sim/console-dev-server.py` → <http://localhost:8765>, also available as `.claude/launch.json` → `console-desktop-dev`.

| Demo feature | Status in v1 |
|---|---|
| S1 widescreen first | Zone + flanks sized from the screen: each flank is 25% at ≥ 2560 px, down to 18% at 1440 px |
| S2 Exposé for contrast | Kept and modal: key **E** or the dock's last icon; pick a window to leave |
| S3, S5 focus zone and periphery | Canvas "tension grid": square in the zone; in the flanks, rows pinch toward the middle by the **same curve** that scales windows. Wallpaper alternative on **G** |
| S4 menu bar pulled in | Starts full width and animates into a pill over the zone (**1** toggles). Menus: logo, app, חלון, תצוגה, עזרה; plus search (Ctrl K) and a clock |
| S6 drag → shrink | Scale is a function of x. The curve's steepness is fitted per screen so a typical window fits its flank halfway out; on ultra-wide it lands near the prototype's gentle curve. Rails light up under the dragged window. A window released in a flank docks into that side's column |
| S7 morph | Behind a switch (**0**), off by default, as the talk decided |
| S8 stashed windows stay live | The iframe stays loaded and clickable. Below 0.8 scale the page gets a narrower viewport, drawn back up, so the app's own responsive layout takes over and stays readable |
| S9 no virtual desktops | Yes |
| S10 window → widget | Protocol: the app posts `bina:widget {label, action:{id,label,icon}}`; the shell draws the control far out and posts `bina:widget-action` back. Any other window becomes an icon at the far edge. Proven with the dev server's player (play/pause runs inside the widget) |
| S11 always-on overview | The flanks |
| S12 shake | ≥ 4 horizontal reversals of ≥ 24 px within 650 ms; stateless. Also on **S**, and from the חלון menu |
| S13 scales with many windows | Two columns per flank where both fit (ultra-wide). On a narrow flank: one column of live windows plus a shelf of icons at the foot of the flank. **D** doubles the windows to test it |
| S14 build it for real | Web instead of Wayland: DOM + CSS transforms, in any browser, no flags (the prototype needs Chrome's experimental HTML-in-canvas) |
| P3 middle truncation | Window titles keep both ends |
| P4 drag from a background window | A click inside a page raises its window on release, so a drag out of it doesn't raise it |
| P25 tiling as an option | Shift-drag snaps to the zone's halves or to maximise; double-click maximises within the zone |
| Capacity | At most N live pages (default 10, set in settings); older windows sleep and wake on touch. Protects the console proxy's 16 threads |
| URL and persistence | The address bar is the focused window's deep link (`replaceState`). The layout, including the dock state, survives reloads |

**Verified 2026-09-25** on the dev server, in the Browser pane at 1920×1080:
- Drag scale 1 → 0.77 → 0.26, and docking on release fully on screen.
- Widget play/pause through `bina:widget-action`.
- Shake with 11 windows leaves no window off screen.
- Exposé in and out.
- Pull-back to scale 1 with the reflow reset.
- Corner resize.
- Doubling 11 → 22 with 10 live.
- Reload restores 16 windows at the same positions.
- Off from the settings window returns to classic; on from classic settings mounts it.
- < 1024 px stays classic.

**Gates run here:**
- G27 theme tokens: exit 0.
- charset-first: 0 failing.
- G12 compile: PASS.
- G9 layering: not runnable here (no PyYAML). `desktop.js` names no layer-3 app.

**Not in v1 yet:**
- A1–A9 collections
- E1–E8 episodic history and the any-concurrency timeline
- Real app widgets (INDOX, mail, notifications via `bina:widget`)
- The sim's multi-frame patch (`digital-office/sim/build.mjs` only serves `#frame`, so desktop mode inside `platform-sim.html` shows empty windows)
- A flow-qa `desktop` suite
- The live proof on the stack (platform-ui-ux protocol)

## 11. Desktop mode v2: real apps, collections, memory (2026-09-25, later)

**Real apps.** This Mac runs the real stack in the project engine (`./bbox engine status` → Running; `./bbox status` → 41/42 up). `./bbox run console` rebuilds the console with desktop mode. At <http://console.localhost:8080>, *הגדרות מסוף → מצב שולחן עבודה* opens every real app in a window. INDOX, drive and the בינה ודעת app were verified live; stashed INDOX reflows to its narrow layout at a 522 px viewport.

**Shell integration.**
- **Account chip.** The focused window's account chip (for apps with a `service`: drive, mail, git, sites, domains, computers) moves into the menu bar and follows focus.
- **Account switches.** `reloadEmbeddedApp()` hands a switch to `BinaDesktop.reloadService()`, which asks every window of that service to re-read (`platform:connection-changed`) and reloads it if it doesn't answer.

**Associative: `desktop-memory.js`, A1–A9 and E7.**
- **The panel.** Every app window has a collection button in its title bar (with a count). The panel sits on the window's side facing the screen middle and moves and scales with the window.
- **Getting things in:**
  - drag a selection, link or image out of any window's page;
  - drop files from the computer;
  - paste (Ctrl V);
  - take the selection from the window's own page (+).
- **Storage.** Items are stored in IndexedDB (`bina-desktop`: `items`, `blobs`) per place (module + route).
- **Provenance.** Every item records its source: app, route, window title, and the passage. With **מקור** on, hovering an item outlines the source window in red and marks the passage in it with the CSS Custom Highlight API, scrolled into view. The source name reopens it.
- **Actions (local, no model):** folder, table from the items, summary, organize by source, copy as text, open links, delete. Derived items keep their `parents`. Double-click opens an item beside the list (text is editable).

**Episodic: `desktop-memory.js`, E1–E8 and Q1–Q5.**
- **What is recorded.** Per place: time in front, max scroll %, and counts of keystrokes, copies, cuts, pastes, submits and items collected. Never content.
- **Where and how long.** In this browser only (`visits`, `snaps`), purged after 30 days.
- **Idle and pause.** A visit ends after 5 minutes without activity. Recording can be paused (settings, or the records tab); the records tab also exports and wipes.
- **The memory window** (dock icon, key **M**, or the חלון menu) has four views:
  - *סיפור*: sessions split at 20-minute gaps, each a chain of the places that held attention, plus "material carried from X to Y".
  - *עוגנים*: places condensed into 3–9 anchors by a local score (focus × read depth, copies, pastes, submits, collected items, hubs), with satellites; dashed lines where material moved.
  - *ציר זמן*: lanes per app for "you", above any-concurrency's real system lanes (`/a/any-concurrency/api/spans?hours=`, binned, errors in red) on one ruler. Click a block to open the place; pick a moment and **restore the windows from that moment** (window snapshots).
  - *רשומות*: exactly what is stored.

**App widgets (S10 for real apps).** mailview (`apps/mail/mailview/static/app.js`, `reportWidget`) and notifications (`platform-base/notifications/static/index.html`) post `bina:widget` with their unread count. Far out in a flank, their windows become a labelled button. These take effect after `./bbox run mailview notifications`.

**Sim.** `digital-office/sim/build.mjs` patches `src` on the `HTMLIFrameElement` prototype instead of `#frame` only, so desktop windows are served from the registry. Not built here (no node); console-own views in bare windows are not served in the sim.

## 12. Agents in the open, external apps, and staying up (2026-09-25, evening)

**Chat with Bina while watching browser42: no new feature, just the desktop.** Open בינה ודעת (it takes the zone; double-click fills it) and דפדפן הלשכה, then drag the browser into a flank. There it stays a live, reflowed view of the agent's Chromium (noVNC at `/a/browser42/`).
- Verified on the local stack: Bina maximized in the zone, browser42 live at 0.54 in the right flank showing its own Chromium tab.
- The budget never puts a flank window to sleep (see below).
- Every step the agent takes is visible in the chat: context injection, skill, each shell command with its exit code and stderr.

The first run exposed two problems outside the desktop:
1. **Bina's agent `cd`s to the checkout without the folder's trailing space.** Bina's own store (`/data/dsh/storages/workspace.json` in the `bina_ds_home` volume) has the path right, trailing space included, and the container mounts it correctly plus the `/workspace/office` symlink. The *model* drops the space when it writes the command.
   Robust fix: point the Bina workspace at `/workspace/office` (no trailing space to lose), or drop the space from the folder name.
2. **This 8 GB Mac cannot hold the full stack and browser42's Chromium together.** Measured: engine load average 146, engine swap 1947/2047 MB, Mac swap 4.8/6 GB. Docker could not start health checks ("timed out starting health check"), so Traefik dropped the console and Bina as unhealthy. browser42-browser was stopped again, as it had been since 2026-09-18. Running it needs a trimmed stack, more RAM, or the VPS.

**External apps (n8n and anything else with `embed: false`).**
- In desktop mode, app-management's *פתח* calls `BinaDesktop.openExternal({id,name,url,icon})`: a window on the app's own host, with a title-bar button that opens it in a tab and a passing hint in case the app refuses framing. Classic mode and standalone use still open a tab.
- n8n answers `X-Frame-Options: SAMEORIGIN`. `platform-base/n8n/docker-compose.yml` adds the `n8n-embed` Traefik middleware on its three UI routers: it removes that header and sets `Content-Security-Policy: frame-ancestors 'self' http(s)://${CONSOLE_BASE_URL}`, so only the console may frame the editor.
- Cookie caveat: on `*.localhost` the console and n8n are different sites, so n8n's SameSite=Lax session may not ride into the frame. Under one registrable domain (production) it does.

**The console stays up with many windows.**
- **Measured cause.** One gunicorn worker with 16 threads, and every proxied event stream held a thread for as long as it was open. With several apps on screen, `/healthz` went unanswered for ~7 minutes.
- **Streams bounded.** `app.py` `_bounded_stream` ends a proxied `text/event-stream` after `CONSOLE_STREAM_MAX_S` (55 s), or `CONSOLE_STREAM_IDLE_S` (45 s) with no bytes. The only consumers (domains, chat) use EventSource, which reconnects by itself.
- **More threads.** `gunicorn.conf.py` default threads: 16 → 48.

**Desktop behaviour fixes.**
- **Watched windows stay live.** The live budget never sleeps a window in a flank or a widget, only back windows in the zone and the icon shelf.
- **Compact mode.** A desktop that is already up and gets narrower than 1024 px (a side pane dragged in) no longer tears every window down, which reloaded every page including a running agent chat. It goes compact: the focused window fills the screen above the dock and the rest wait behind it, still loaded; widening restores the layout. A screen that is narrow from the start still gets the classic shell.
