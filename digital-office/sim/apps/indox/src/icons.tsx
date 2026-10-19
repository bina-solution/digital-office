/* The marks this fork draws itself — the live app's vocabulary (`apps/indox/app/webapp/src/icons.ts`) and its
   one primitive (`Ic`, in its DataGrid.tsx), the paths taken as they are there. A character of a font stood in
   each of these places (✕ ✓ ✗ ★ ↻ ☰ ▦ ▶ ⬆ ✎ ↗ ＋ ‹ ›): it took that font's metrics, sat off the baseline of
   the Hebrew beside it, and its size was a font-size somebody had to guess per button. */
export const IC = {
  x: 'M18 6L6 18M6 6l12 12',
  check: 'M20 6L9 17l-5-5',
  plus: 'M12 5v14M5 12h14',
  play: 'M5 3l14 9-14 9V3z',
  upload: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
  refresh: 'M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15',
  external: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3',
  arrowLeft: 'M19 12H5M12 19l-7-7 7-7',
  arrowRight: 'M5 12h14M12 5l7 7-7 7',
  edit: 'M17 3a2.828 2.828 0 1 1 4 4L7.5 21.5 2 23l1.5-5.5L17 3z',
  trash: 'M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
  star: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z',
  // the pager's, as the live grid draws them: on this right-to-left page "first/previous" travel right
  first: 'M13 17l5-5-5-5M6 17l5-5-5-5',
  prev: 'M9 18l6-6-6-6',
  next: 'M15 18l-6-6 6-6',
  last: 'M11 17l-5-5 5-5M18 17l-5-5 5-5',
};

export function Ic({ p, title }: { p: string; title?: string }) {
  return (
    <svg className="dg-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {title ? <title>{title}</title> : null}
      <path d={p} />
    </svg>
  );
}

/* the close / clear cross — the live app's `<Ic p={IC.x} />` */
export function XIcon() {
  return <Ic p={IC.x} />;
}
