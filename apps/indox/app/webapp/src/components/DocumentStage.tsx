import {
  useCallback, useEffect, useMemo, useRef, useState, type CSSProperties,
} from 'react';
import { Ic } from './DataGrid';
import { IC } from '../icons';

/**
 * THE DOCUMENT STAGE — one component for looking at a document, anywhere it is put.
 *
 * It replaces DocumentViewer, which was correct only at the window size it was tuned on. Two
 * defects, both measured live on 2026-09-02 against doc_mtk56k1zbq1ws3, are why this is a
 * replacement and not a patch:
 *
 *   1. THE TOP OF THE DOCUMENT WAS UNREACHABLE. The pane centred its child with
 *      `align-items:center` while being a scroll container. A page taller than the pane
 *      overflows equally in both directions and `scrollTop` cannot go below zero, so the header
 *      of every portrait document was simply gone — 141px of it in a 1917x1078 window, 163px in
 *      a shorter one, worse the smaller the window, and `scrollHeight` reported the truncated
 *      height so nothing on the page admitted it. A scroll container must never centre with
 *      alignment; its child centres itself with `margin:auto`, which absorbs free space when
 *      there is some and invents none when there is not.
 *
 *   2. IT SIZED ITSELF FROM THE VIEWPORT. `max-height:76vh` inside the console iframe is 76% of
 *      the IFRAME, and excluded the tab strip, the caption and the card's own padding — so the
 *      card was taller than the region holding it and a shorter window clipped the caption too.
 *      Height is not a number a component may invent: it comes down the flex chain from the
 *      shell (`.app-shell` → `.wrap` → `.page-fill`). There is not one viewport unit in this
 *      file, and `scripts/ops/lint_viewport_units.py` fails the build if one appears.
 *
 * HOW IT FITS THE PAGE TO THE BOX — and the bug that decided this design. The first version
 * measured the stage in a layout effect and computed a scale from it. That is a feedback loop
 * with the layout it is measuring, and it hung the browser: dragging the split gutter froze the
 * renderer outright (reproduced with a real mouse drag, not a synthetic event, 2026-09-02).
 * Measurement now feeds NOTHING that affects layout — the fit is expressed in CSS, where the
 * browser resolves it in the same pass as everything else:
 *
 *     fit width   canvas `width:100%` + `aspect-ratio`
 *     fit page    the same, plus `max-height:100%`
 *     100% / n%   explicit pixel width and height, the only mode JS sizes at all
 *
 * JS reads the rendered size in exactly one place — `currentScale()`, called from a click or a
 * wheel to know what the browser's fit came out as before stepping away from it. A read inside
 * an event handler cannot loop with layout the way a read inside a render or an effect can.
 *
 * Deliberately still presentational: every url is passed in, and the caller (the document page,
 * the extraction tester) owns what those urls mean. P2 replaces the three baked-pixel overlays
 * with one page image plus vector layers; the source list below is already shaped for it.
 */

export interface DocumentStageProps {
  /** the original file — null when the caller has no working url for it (an honest absence) */
  fileUrl: string | null;
  /** apitools' drawn extraction overlay (anchor green, value blue) — omit if none exists yet */
  drawUrl?: string | null;
  /** the OCR token overlay: every word the engine read, boxed */
  tokensUrl?: string | null;
  /** the page preview — a lightweight fallback, clearly labelled, when a source fails */
  thumbnailUrl?: string | null;
  /** display name, used as the alt text */
  name?: string;
  /** bump to bust the <img> cache after a re-run cleared the server-side draw cache */
  cacheKey?: string | number;
  /** which source opens first. Defaults to the drawn overlay when there is one. */
  initialSource?: SourceKey;
  emptyDrawNote?: string;
  emptyTokensNote?: string;
  emptyDocNote?: string;
  /** the document at its source (e.g. Google Drive) — the escape hatch when nothing renders */
  externalLink?: string | null;
  externalLinkLabel?: string;
  /**
   * Whether `fileUrl` is an IMAGE. True for every production document — the BFF serves apitools'
   * rasterised page — and false in the extraction tester, whose dataset holds real PDFs. A PDF
   * goes in an `<iframe>` and brings its own zoom, so the stage's own zoom tools stand down for
   * that one source rather than pretending to drive something they cannot reach.
   */
  isImage?: boolean;
  /** the DOCUMENT this stage is showing. Zoom, rotation and scroll reset when this changes and
   *  survive a switch between the three sources, which is what makes them comparable. */
  docKey?: string | number;
  /** the page has given the document the whole width (the data column is hidden) */
  expanded?: boolean;
  /** offered only when the container can actually expand — omitted, the control is not drawn */
  onExpandToggle?: () => void;
  /**
   * `fill` (default) takes the height its container hands it — the shape every bounded page
   * uses. `block` is for a page that scrolls as a whole and therefore has no height to give:
   * the stage then takes a page-shaped slice of its own WIDTH (`aspect-ratio`), which is
   * container-relative and honest, where a viewport unit would not be.
   */
  mode?: 'fill' | 'block';
}

export type SourceKey = 'draw' | 'tokens' | 'doc';
type Stage = 'primary' | 'fallback' | 'empty';
type Zoom = { mode: 'fit-width' } | { mode: 'fit-page' } | { mode: 'abs'; scale: number };

const MIN_SCALE = 0.08;
const MAX_SCALE = 8;

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

interface Source {
  key: SourceKey;
  /** the full label, shown whenever the toolbar has room */
  label: string;
  /** the label the toolbar falls back to before it would wrap (container query, 860px) */
  short: string;
  title: string;
  url: string | null;
  emptyNote: string;
  emptyIcon: string;
  /** the status line: one clause, always true of what is on screen right now */
  shortNote: string;
  /** the status line when a SUBSTITUTE is showing instead of this source */
  fallbackNote: string;
  /** the full sentence, as the status line's tooltip */
  note: (stage: Stage) => string;
}

export default function DocumentStage({
  fileUrl,
  drawUrl = null,
  tokensUrl = null,
  thumbnailUrl = null,
  name = '',
  cacheKey = 0,
  initialSource,
  emptyDrawNote = 'הרץ חילוץ כדי לראות את הסימון על המסמך',
  emptyTokensNote = 'אין עדיין זיהוי תווים למסמך הזה',
  emptyDocNote = 'המסמך המקורי אינו זמין כרגע',
  externalLink = null,
  externalLinkLabel = 'פתח מקור',
  isImage = true,
  mode = 'fill',
  docKey,
  expanded = false,
  onExpandToggle,
}: DocumentStageProps) {
  const sources = useMemo<Source[]>(() => [
    {
      key: 'draw',
      label: 'חילוץ מסומן',
      short: 'סימון',
      title: 'מה שהמנוע סימן על המסמך — עוגן ירוק, ערך כחול',
      url: drawUrl,
      emptyNote: emptyDrawNote,
      emptyIcon: IC.image,
      shortNote: 'הסימון שהמנוע צייר על המסמך.',
      fallbackNote: 'לא הופק סימון חילוץ למסמך זה — זו תצוגה מקדימה של הקובץ בלבד.',
      note: (s) => (s === 'fallback'
        ? 'לא הופק סימון חילוץ (documentDraw) למסמך זה — זו תצוגה מקדימה של הקובץ בלבד, ללא עוגן/ערך מסומנים.'
        : 'הסימון מצויר על ידי apitools עצמו (/documentDraw): עוגן ירוק, ערך כחול — לכל שדה השאילתה שלו, קריאה אחת לערך.'),
    },
    {
      key: 'tokens',
      label: 'זיהוי תווים',
      short: 'תווים',
      title: 'כל מילה שמנוע ה-OCR קרא, ממוסגרת',
      url: tokensUrl,
      emptyNote: emptyTokensNote,
      emptyIcon: IC.type,
      shortNote: 'כל מילה שזוהתה בקריאת התווים. מה שלא מסומן כאן, החילוץ לא יכול למצוא.',
      fallbackNote: 'אין זיהוי תווים למסמך זה — זו תצוגה מקדימה של הקובץ בלבד.',
      note: () =>
        'זיהוי תווים (/documentOcrDraw): כל מילה שמנוע ה-OCR קרא, ממוסגרת עם הטקסט שזוהה — לפני שכל שאילתה רצה. מה שלא מסומן כאן, החילוץ לא יכול למצוא.',
    },
    {
      key: 'doc',
      label: 'מסמך מקורי',
      short: 'מקור',
      title: 'המסמך כפי שהתקבל מהמקור',
      url: fileUrl,
      emptyNote: emptyDocNote,
      emptyIcon: IC.file,
      shortNote: 'המסמך כפי שהתקבל מהמקור.',
      fallbackNote: 'תצוגה מקדימה שהופקה בזמן הסנכרון — לא קובץ המקור המלא.',
      note: (s) => (s === 'fallback'
        ? 'תצוגה מקדימה של המסמך (התמונה שהופקה בזמן הסנכרון) — לא קובץ המקור המלא.'
        : 'המסמך כפי שהתקבל מהמקור.'),
    },
  ], [drawUrl, tokensUrl, fileUrl, emptyDrawNote, emptyTokensNote, emptyDocNote]);

  const [key, setKey] = useState<SourceKey>(initialSource ?? (drawUrl ? 'draw' : 'doc'));
  const src = sources.find((s) => s.key === key) ?? sources[2];

  /* the source ladder: the real thing → the preview (labelled as one) → an explained absence.
     Never the browser's broken-image glyph, and never a raw JSON error body painted into the
     frame, which is what an <iframe> did with a 404 before the panes became images. */
  const [stage, setStage] = useState<Stage>(() => (src.url ? 'primary' : thumbnailUrl ? 'fallback' : 'empty'));
  useEffect(() => {
    setStage(src.url ? 'primary' : thumbnailUrl ? 'fallback' : 'empty');
  }, [src.url, thumbnailUrl]);

  const shownUrl = stage === 'primary' ? src.url : stage === 'fallback' ? thumbnailUrl : null;

  // ── geometry ───────────────────────────────────────────────────────────────────────────────
  const stageRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [rot, setRot] = useState(0);
  const [zoom, setZoom] = useState<Zoom>({ mode: 'fit-width' });
  const [loading, setLoading] = useState(true);

  /* ── THE VIEW SURVIVES A SOURCE SWITCH ─────────────────────────────────────────────────────
     The three sources are three renders of the SAME page, so switching between them is how you
     compare: is the amount the engine boxed the amount on the paper, and did the OCR even read
     it? That only works if the view holds still. It used to reset to fit-width, unrotated, at
     the top on every switch, which meant finding your place again three times to answer one
     question.

     So zoom and rotation persist across sources and reset only when the DOCUMENT changes, and
     the scroll position is carried as a FRACTION of the scrollable extent rather than in pixels:
     the overlay renders are the same page but not always the same pixel size, and a fraction
     lands on the same part of the document where a pixel offset would drift. */
  const viewRef = useRef<{ fx: number; fy: number } | null>(null);
  const rememberScroll = useCallback(() => {
    const el = stageRef.current;
    if (!el) return;
    const mx = el.scrollWidth - el.clientWidth;
    const my = el.scrollHeight - el.clientHeight;
    viewRef.current = { fx: mx > 0 ? el.scrollLeft / mx : 0, fy: my > 0 ? el.scrollTop / my : 0 };
  }, []);
  const restoreScroll = useCallback(() => {
    const el = stageRef.current;
    const v = viewRef.current;
    if (!el || !v) return;
    const mx = el.scrollWidth - el.clientWidth;
    const my = el.scrollHeight - el.clientHeight;
    el.scrollLeft = mx > 0 ? v.fx * mx : 0;
    el.scrollTop = my > 0 ? v.fy * my : 0;
  }, []);

  const switchSource = useCallback((next: SourceKey) => {
    if (next === key) return;
    rememberScroll();
    setKey(next);
  }, [key, rememberScroll]);

  // a new DOCUMENT starts fresh; a new source does not
  useEffect(() => {
    viewRef.current = null;
    setZoom({ mode: 'fit-width' });
    setRot(0);
  }, [docKey]);

  // the image itself always restarts: a new src has no size until it loads
  useEffect(() => {
    setNat(null);
    setLoading(Boolean(shownUrl));
  }, [shownUrl]);

  /* A CACHED IMAGE NEVER FIRES `load`. The page's whole geometry comes from the natural size,
     which `onLoad` reports — and on a reload the browser can finish the image before React has
     attached that handler, so the event never arrives and the canvas stays at its 1x1
     placeholder: a document that simply does not appear. Caught on the second reload of the
     same document, 2026-09-02, with the endpoint answering a perfectly good 200.

     So ask the element as well as waiting to be told. Runs after the reset above (source order
     is effect order), so it re-reads the size the reset just cleared. */
  useEffect(() => {
    const im = imgRef.current;
    if (im && im.complete && im.naturalWidth) {
      setNat({ w: im.naturalWidth, h: im.naturalHeight });
      setLoading(false);
      requestAnimationFrame(restoreScroll);
    }
  }, [shownUrl, key, stage, cacheKey, restoreScroll]);

  /** the page's on-screen size after rotation, before scaling */
  const disp = useMemo(() => {
    if (!nat) return null;
    return rot % 180 === 0 ? { w: nat.w, h: nat.h } : { w: nat.h, h: nat.w };
  }, [nat, rot]);

  /**
   * The scale RIGHT NOW — the exact number in absolute mode, and a one-off read of the rendered
   * canvas in a fit mode, because only the browser knows what "fit" came out as.
   *
   * Called from event handlers only, never from a render or an effect. That distinction is the
   * whole lesson of this component: the first version kept this number in state, refreshed it
   * whenever the box changed, and sized the canvas from it — a measurement feeding the layout it
   * measures. Dragging the split gutter froze the renderer outright. Read at the instant of a
   * click, the same number is perfectly safe, because nothing is laid out from it.
   */
  const currentScale = useCallback((): number => {
    if (zoom.mode === 'abs') return zoom.scale;
    const c = canvasRef.current;
    if (!c || !disp) return 1;
    const s = c.getBoundingClientRect().width / disp.w;
    return Number.isFinite(s) && s > 0 ? s : 1;
  }, [zoom, disp]);

  /* Zoom anchored on a point, so +/- and ctrl+wheel keep what you are looking at where it is.
     Without this, zooming a tall document always drifts back to the top-left corner. */
  const zoomTo = useCallback((next: number, anchor?: { x: number; y: number }) => {
    const el = stageRef.current;
    const target = clamp(next, MIN_SCALE, MAX_SCALE);
    const from = currentScale();
    setZoom({ mode: 'abs', scale: target });
    if (!el || !from) return;
    const ax = anchor?.x ?? el.clientWidth / 2;
    const ay = anchor?.y ?? el.clientHeight / 2;
    const cx = (el.scrollLeft + ax) / from;
    const cy = (el.scrollTop + ay) / from;
    requestAnimationFrame(() => {
      const s = stageRef.current;
      if (!s) return;
      s.scrollLeft = cx * target - ax;
      s.scrollTop = cy * target - ay;
    });
  }, [currentScale]);

  const onWheel = useCallback((e: React.WheelEvent) => {
    // ctrl+wheel is also what a trackpad pinch reports — the browser's own zoom gesture
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const el = stageRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    zoomTo(currentScale() * (e.deltaY < 0 ? 1.12 : 1 / 1.12),
      { x: e.clientX - r.left, y: e.clientY - r.top });
  }, [currentScale, zoomTo]);

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.target !== e.currentTarget) return; // never steal keys from a control inside
    const k = e.key;
    if (k === '+' || k === '=') { e.preventDefault(); zoomTo(currentScale() * 1.2); }
    else if (k === '-' || k === '_') { e.preventDefault(); zoomTo(currentScale() / 1.2); }
    else if (k === '0') { e.preventDefault(); setZoom({ mode: 'fit-page' }); }
    else if (k === '1') { e.preventDefault(); setZoom({ mode: 'abs', scale: 1 }); }
    else if (k === 'w' || k === 'W') { e.preventDefault(); setZoom({ mode: 'fit-width' }); }
    else if (k === 'r' || k === 'R') { e.preventDefault(); setRot((v) => (v + 90) % 360); }
    else if ((k === 'f' || k === 'F') && onExpandToggle) { e.preventDefault(); onExpandToggle(); }
    else if (k === 'Escape' && expanded && onExpandToggle) { e.preventDefault(); onExpandToggle(); }
  }, [currentScale, zoomTo, onExpandToggle, expanded]);

  /* ── THE OTHER TWO SOURCES ARE FETCHED BEFORE YOU ASK FOR THEM ────────────────────────────
     Comparing means switching back and forth, and a cold overlay costs seconds. Warming the
     other renders once this one is on screen makes the switch instant. Deliberately AFTER the
     visible image has loaded, so the comparison never competes with the thing being looked at. */
  useEffect(() => {
    if (loading || !nat) return;
    const others = sources.map((s) => s.url).filter((u): u is string => Boolean(u) && u !== shownUrl);
    const imgs = others.map((u) => {
      const im = new Image();
      im.src = u;
      return im;
    });
    return () => imgs.forEach((im) => { im.src = ''; });
  }, [loading, nat, sources, shownUrl]);

  /* ── DRAG TO PAN ──────────────────────────────────────────────────────────────────────────
     Scrollbars alone are not how anyone reads a zoomed document; every viewer lets you take
     hold of the page. Pointer events, so a trackpad, a mouse and a touchscreen all work, and
     `setPointerCapture` so a drag that leaves the stage still ends correctly. */
  const panRef = useRef<{ x: number; y: number; l: number; t: number } | null>(null);
  const [panning, setPanning] = useState(false);
  const canPan = () => {
    const el = stageRef.current;
    return Boolean(el && (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1));
  };
  const onPointerDown = useCallback((e: React.PointerEvent) => {
    // never steal the gesture from a control, a link, or a text selection inside the stage
    if (e.button !== 0 || (e.target as HTMLElement).closest('a,button')) return;
    const el = stageRef.current;
    if (!el || !canPan()) return;
    panRef.current = { x: e.clientX, y: e.clientY, l: el.scrollLeft, t: el.scrollTop };
    setPanning(true);
    el.setPointerCapture(e.pointerId);
  }, []);
  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const el = stageRef.current;
    const p = panRef.current;
    if (!el || !p) return;
    el.scrollLeft = p.l - (e.clientX - p.x);
    el.scrollTop = p.t - (e.clientY - p.y);
  }, []);
  const endPan = useCallback((e: React.PointerEvent) => {
    const el = stageRef.current;
    if (el && el.hasPointerCapture?.(e.pointerId)) el.releasePointerCapture(e.pointerId);
    panRef.current = null;
    setPanning(false);
  }, []);

  /* A COLD OVERLAY TAKES SECONDS, and a shimmer that never ends looks like a hang. After a
     couple of seconds the stage says what it is waiting for, in the words of the thing that is
     slow (apitools draws the overlay on demand; measured 4.8-9.8s healthy, 67s under load). */
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    setSlow(false);
    if (!loading || !shownUrl) return;
    const t = window.setTimeout(() => setSlow(true), 2500);
    return () => window.clearTimeout(t);
  }, [loading, shownUrl]);

  /* THE FIT, IN CSS. The browser resolves these in the same layout pass as everything else, so
     the page re-fits on a gutter drag, a window resize or a stacked-mode switch with no
     measurement, no observer, and nothing that can loop. */
  const canvasStyle: CSSProperties = !disp
    ? { width: 1, height: 1, opacity: 0 }
    : zoom.mode === 'abs'
      ? { width: Math.round(disp.w * zoom.scale), height: Math.round(disp.h * zoom.scale) }
      : zoom.mode === 'fit-page'
        ? { width: '100%', aspectRatio: `${disp.w} / ${disp.h}`, maxHeight: '100%' }
        : { width: '100%', aspectRatio: `${disp.w} / ${disp.h}` };

  /* In a fit mode there is no percentage to state without measuring, so the control says what it
     DOES (`1:1`, go to actual size) instead of a number that would have to be kept in sync. In
     absolute mode it states the zoom it is holding. Nothing here is ever stale. */
  const zoomLabel = zoom.mode === 'abs' ? `${Math.round(zoom.scale * 100)}%` : '1:1';
  const openHref = shownUrl || externalLink;
  const fitActive = zoom.mode === 'fit-width' ? 'w' : zoom.mode === 'fit-page' ? 'p' : '';
  /* the one source this stage does not draw itself: a real PDF in the extraction dataset. The
     embedded viewer owns zoom and paging for it, so ours steps aside instead of competing. */
  const framed = key === 'doc' && !isImage && stage === 'primary' && Boolean(shownUrl);

  return (
    <div className={`card doc-stage${mode === 'block' ? ' is-block' : ''}`}>
      {/* ── THE TOOLBAR. One control family, one row, never wrapping.
             It used to be four: 35px tabs borrowed from the settings sub-nav, 26px outline
             pills, 28px icon buttons and a 29px text link, which wrapped to two lines and read
             as unfinished. Everything here is now the app's own `.winseg` segmented control —
             the same one the time-window switch uses elsewhere — plus `.icbtn`, so this screen
             looks like the rest of the product instead of like a viewer someone bolted on. ── */}
      <div className="stage-bar">
        <div className="winseg stage-sources" role="tablist" aria-label="תצוגת המסמך">
          {sources.map((s) => (
            <button
              key={s.key}
              role="tab"
              aria-selected={key === s.key}
              className={key === s.key ? 'on' : ''}
              title={s.title}
              onClick={() => switchSource(s.key)}
            >
              {/* the label shortens before the row would wrap — see the container query */}
              <span className="stage-src-long">{s.label}</span>
              <span className="stage-src-short">{s.short}</span>
            </button>
          ))}
        </div>

        <div className="stage-tools">
          {!framed && (
            <>
              <div className="winseg" role="group" aria-label="התאמת גודל">
                <button
                  className={fitActive === 'w' ? 'on' : ''}
                  onClick={() => setZoom({ mode: 'fit-width' })}
                  title="התאם לרוחב (W)"
                >
                  רוחב
                </button>
                <button
                  className={fitActive === 'p' ? 'on' : ''}
                  onClick={() => setZoom({ mode: 'fit-page' })}
                  title="התאם לעמוד (0)"
                >
                  עמוד
                </button>
              </div>

              {/* one control, three parts: out, the current zoom, in */}
              <div className="winseg stage-zoom" role="group" aria-label="מרחק מבט">
                <button onClick={() => zoomTo(currentScale() / 1.2)} title="התרחק (-)" aria-label="התרחק">
                  <Ic p={IC.minus} />
                </button>
                <button
                  className="val"
                  onClick={() => setZoom({ mode: 'abs', scale: 1 })}
                  title="גודל מלא — 100% (1)"
                  aria-label={zoom.mode === 'abs'
                    ? `מרחק מבט ${Math.round(zoom.scale * 100)} אחוז — לחיצה מחזירה לגודל מלא`
                    : 'הצג בגודל מלא'}
                >
                  {zoomLabel}
                </button>
                <button onClick={() => zoomTo(currentScale() * 1.2)} title="התקרב (+)" aria-label="התקרב">
                  <Ic p={IC.plus} />
                </button>
              </div>

              <button
                className="icbtn"
                onClick={() => setRot((v) => (v + 90) % 360)}
                title="סובב 90° (R)"
                aria-label="סובב"
              >
                <Ic p={IC.refresh} />
              </button>
              <span className="stage-sep" aria-hidden="true" />
            </>
          )}
          {onExpandToggle && (
            <button
              className="icbtn"
              onClick={onExpandToggle}
              title={expanded ? 'החזר את פרטי המסמך (F)' : 'הגדל את המסמך על כל הרוחב (F)'}
              aria-label={expanded ? 'צא ממסך מלא' : 'מסך מלא'}
              aria-pressed={expanded}
            >
              <Ic p={expanded ? IC.minimize : IC.maximize} />
            </button>
          )}
          {openHref ? (
            <a
              className="icbtn"
              href={openHref}
              target="_blank"
              rel="noreferrer"
              title="פתיחת התצוגה הנוכחית בלשונית חדשה"
              aria-label="פתח בחלון"
            >
              <Ic p={IC.external} />
            </a>
          ) : (
            <span className="icbtn" aria-disabled="true" title="אין קובץ לפתוח בתצוגה הזו"
                  style={{ opacity: 0.4 }}>
              <Ic p={IC.external} />
            </span>
          )}
        </div>
      </div>

      {/* ── the scroller. Centres nothing (the canvas does that with margin:auto), bounds
             nothing (the container does that), and is LTR because it holds an image, not
             text: RTL scroll origins differ between engines and every scrollLeft here
             would be wrong. ───────────────────────────────────────────────────────────── */}
      <div
        className={`stage${panning ? ' is-panning' : ''}`}
        ref={stageRef}
        tabIndex={0}
        role="group"
        aria-label={`תצוגת המסמך — ${src.label}`}
        onWheel={onWheel}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPan}
        onPointerCancel={endPan}
      >
        {framed ? (
          <iframe className="stage-frame" src={shownUrl!} title={name} />
        ) : shownUrl ? (
          <div ref={canvasRef} className={`stage-canvas rot${rot}`} style={canvasStyle}>
            <img
              ref={imgRef}
              key={`${key}-${stage}-${cacheKey}`}
              src={shownUrl}
              alt={stage === 'fallback' ? `${name} — תצוגה מקדימה` : name}
              draggable={false}
              style={{ transform: `translate(-50%, -50%) rotate(${rot}deg)` }}
              onLoad={(e) => {
                const im = e.currentTarget;
                setNat({ w: im.naturalWidth || 1, h: im.naturalHeight || 1 });
                setLoading(false);
                // the canvas is sized on the next frame; put the reader back where they were
                requestAnimationFrame(restoreScroll);
              }}
              onError={() => {
                setLoading(false);
                setStage((s) => (s === 'primary' && thumbnailUrl ? 'fallback' : 'empty'));
              }}
            />
          </div>
        ) : (
          <EmptyStage
            icon={src.emptyIcon}
            note={src.emptyNote}
            actionHref={key === 'doc' ? externalLink : null}
            actionLabel={externalLinkLabel}
          />
        )}
        {loading && shownUrl && !framed && <div className="stage-skeleton" aria-hidden="true" />}
        {slow && loading && shownUrl && !framed && (
          <div className="stage-slow" role="status">
            <span className="spinner" aria-hidden="true" />
            {key === 'draw' ? 'מפיק את הסימון על המסמך… בפעם הראשונה זה כמה שניות.'
              : 'טוען את המסמך…'}
          </div>
        )}
      </div>

      {/* THE STATUS LINE — one line, always, saying what you are looking at and (when it is a
          substitute) that it is one. The full sentence used to hang under the frame across two
          lines of dense Hebrew, which reads as debug output rather than as part of the product;
          it is the tooltip now, and a warning icon replaces the quiet grey dot when what you are
          seeing is NOT what the label promises. */}
      <div className="stage-note" title={src.note(stage)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d={stage === 'fallback' ? IC.alert : IC.info} />
        </svg>
        <span className="t">{stage === 'fallback' ? src.fallbackNote : src.shortNote}</span>
        {/* the legend belongs where the colours are, not in a sentence about them */}
        {key === 'draw' && stage === 'primary' && (
          <span className="stage-legend" aria-hidden="true">
            <span className="k"><i className="sw anchor" />עוגן</span>
            <span className="k"><i className="sw value" />ערך</span>
          </span>
        )}
      </div>
    </div>
  );
}

/** an absence, explained, with the one action that resolves it where such an action exists */
function EmptyStage({
  icon, note, actionHref, actionLabel,
}: {
  icon: string;
  note: string;
  actionHref?: string | null;
  actionLabel?: string;
}) {
  return (
    <div className="stage-empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
           strokeLinecap="round" strokeLinejoin="round" width="36" height="36" aria-hidden="true">
        <path d={icon} />
      </svg>
      <div className="stage-empty-note">{note}</div>
      {actionHref && (
        <a className="btn sm" href={actionHref} target="_blank" rel="noreferrer" title="פתיחת המקור בלשונית חדשה">
          {actionLabel ?? 'פתח מקור'} <Ic p={IC.external} />
        </a>
      )}
    </div>
  );
}
