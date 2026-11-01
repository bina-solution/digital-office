/* The office's own question (platform-base/bina-ui/bina-ask.js). The simulation's build gives that block to
   every page it embeds, so this fork asks through it and keeps no dialog of its own — and never the browser's
   `confirm()`: one line of text, outside the page, English buttons left to right, and nothing about what is
   about to be removed. Resolves true on the action, false on «ביטול», Escape or a click outside. */
export interface Ask {
  title: string;
  body?: string;
  /** what decides the answer, as [what it is, its value] — the thing named, the count */
  facts?: [string, string][];
  ok?: string;
  /** destructive: the action is red and the focus opens on «ביטול» */
  danger?: boolean;
}

export const ask = (q: Ask): Promise<boolean> =>
  (window as unknown as { binaAsk: (q: Ask) => Promise<boolean> }).binaAsk(q);

/* …and its own notice, from the same block: what was done or what failed and — with `undo` — one way
   back. The table and the sync board each kept a toast of their own beside it. */
export const tell = (kind: 'ok' | 'bad', text: string, undo?: () => void): void => {
  (window as unknown as { binaTell: (t: string, k: string, o?: object) => unknown })
    .binaTell(text, kind, undo && { ms: 6000, act: ['בטל', undo] });
};
