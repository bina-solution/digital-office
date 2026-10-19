/**
 * THE TIME WINDOW — one control, one list, one persisted value, for every view that has one.
 *
 * Same control, same labels, same interaction as the mail inbox's window
 * (apps/mail/mailview/static/app.js) — one platform, one idiom. `all` is the default and
 * reproduces the pre-window behaviour exactly.
 *
 * The window is SERVER-SIDE wherever it is used, and that is the entire point: `/dashboard/stats`
 * pushes it into a `created_at >= …` WHERE clause and `/dashboard/actions` cuts on the action's own
 * parsed epoch, so a narrow window means the server never reads the rest of an 8,500+-row (and
 * growing) table.
 *
 * RTL needs no special casing: the segmented control is inline-flex inside a dir="rtl" document, so
 * הכל → 15 דק׳ → 30 דק׳ → שעה → היום → החודש lays out right-to-left on its own.
 *
 * The list widens monotonically after `all`, so the control reads as one scale rather than a bag of
 * options — a new span is inserted at its place in that order, never appended. `15m` is the
 * narrowest the pipeline can be usefully watched at: the main state machine polls every 30s and the
 * sync scanners run on a 15-minute cadence, so a quarter of an hour is one full scanner cycle —
 * below that the board mostly shows the gaps between cycles.
 *
 * It lives in its own file because there are now TWO views under this window (the dashboard and
 * יומן פעולות). Two copies of a segmented control drift in the small ways that matter most — one
 * gains `15 דק׳`, the other does not; one remembers your choice, the other resets — and a user
 * moving between the two tabs reads that as the product being unsure what "the last hour" means.
 */

/** The windows the SERVER understands (`_DASH_WINDOWS`, api/__init__.py). */
export const WINDOWS = [
  { id: 'all', he: 'הכל' },
  { id: '15m', he: '15 דק׳' },
  { id: '30m', he: '30 דק׳' },
  { id: '1h', he: 'שעה' },
  { id: 'today', he: 'היום' },
  { id: 'month', he: 'החודש' },
];

/** Windows narrower than a calendar day. They are meaningless on a BUSINESS-DATE basis
 *  (`granularity: 'day'`), because such a column stores a date with no time of day: the server
 *  floors them to the start of the day and says so in `win_effective`. The UI's job is to make that
 *  visible BEFORE the click rather than after — these buttons go disabled, with the reason in their
 *  tooltip, exactly the way an unavailable BASIS renders disabled with its reason. The alternative
 *  (leave them live and quietly relabel) would put a day's numbers under a "15 דק׳" heading, which
 *  is the one thing this whole control exists to prevent.
 *
 *  This list MUST mirror the server's `_DASH_WINDOW_SECONDS` keys (api/__init__.py). It is the one
 *  duplicated fact in the window control: everything else the server derives, but the disabled
 *  state has to be decided here, before any request is made. */
export const SUBDAY_WINDOWS = ['15m', '30m', '1h'];
export const SUBDAY_BLOCKED_HE =
  'טווח קצר מיום אינו ישים לתאריך עסקי — לתאריך המסמך אין שעה';

/** localStorage, matching drive's/mail's bare-key convention. SHARED between the views on
 *  purpose: "which time range am I looking at" is one question, so moving from לוח בקרה to
 *  יומן פעולות keeps the range you were already reading instead of silently resetting to הכל. */
export const WIN_KEY = 'win';

export function isWindow(v: unknown): boolean {
  return WINDOWS.some((w) => w.id === v);
}

export function loadWin(): string {
  try {
    const v = localStorage.getItem(WIN_KEY);
    return isWindow(v) ? (v as string) : 'all';
  } catch {
    return 'all'; // private mode / storage disabled — never fatal
  }
}

export function saveWin(id: string): void {
  try {
    localStorage.setItem(WIN_KEY, id);
  } catch {
    /* storage disabled — the window still works for this session */
  }
}

/** The window's Hebrew name, for prose ("מציג את הפעולות ב<שעה האחרונה>"). */
export function winLabel(id: string): string {
  return WINDOWS.find((w) => w.id === id)?.he ?? id;
}

/**
 * radiogroup, not a row of buttons: exactly one is active and a screen reader announces
 * arrow-navigation for this role — the exact control mailview ships, so the platform reads as one
 * product. Dimmed while a switch is in flight so a second click is visibly not being taken.
 */
export default function WindowPicker({
  value,
  onChange,
  busy = false,
  blockSubday = false,
  ariaLabel = 'טווח זמן',
}: {
  value: string;
  onChange: (id: string) => void;
  /** a switch is in flight — dim and swallow clicks */
  busy?: boolean;
  /** disable the sub-day windows, with the measured reason in their tooltip (a
   *  day-granularity date basis cannot express them) */
  blockSubday?: boolean;
  ariaLabel?: string;
}) {
  return (
    <span className={`winseg${busy ? ' busy' : ''}`} role="radiogroup" aria-label={ariaLabel}>
      {WINDOWS.map((w) => {
        /* A sub-day window on a day-granularity basis is not a narrower question, it is an
           unanswerable one — same treatment an unavailable BASIS gets: disabled, with the reason
           in the tooltip, never silently reinterpreted. */
        const blocked = blockSubday && SUBDAY_WINDOWS.includes(w.id);
        return (
          <button
            key={w.id}
            role="radio"
            aria-checked={w.id === value}
            disabled={blocked}
            title={blocked ? SUBDAY_BLOCKED_HE : ''}
            className={w.id === value ? 'on' : ''}
            onClick={() => onChange(w.id)}
          >
            {w.he}
          </button>
        );
      })}
    </span>
  );
}
