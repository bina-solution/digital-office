/**
 * Engine reasons → Hebrew. The ledger's `last_error` is written by n8n — HTTP-node messages, the
 * deliverers' own sentences, TAKE's `[unlisted]` / `[expired]` dead-letters — in English. The
 * operator reads Hebrew. Every known reason class gets one sentence a person can act on; the
 * original stays one hover away and in the items drawer. A reason nobody has translated falls
 * back to the original text, isolated LTR — never a guess dressed as a translation.
 *
 * `foldReason` mirrors the `sync_item_reasons` view: identifiers (an 18+ character token) and
 * line numbers are folded so the card groups "drive item <id> has no md5" once, and a chip's
 * click can find the rows behind it.
 */
export type ReasonKind = 'terminal' | 'review' | 'transient' | 'unknown';
export interface ReasonView { he: string; raw: string; kind: ReasonKind; translated: boolean }

const RULES: { re: RegExp; he: string; kind: ReasonKind }[] = [
  { re: /^\[legacy\] migrated/i, he: 'שורה מהמנוע הקודם — ללא רישום במקור', kind: 'review' },
  { re: /^\[unlisted\]/i, he: 'המקור כבר לא מציג את הפריט (הועבר או נמחק)', kind: 'review' },
  { re: /^\[expired\]/i, he: 'הפריט ישן מחלון הסנכרון', kind: 'review' },
  { re: /the mailbox no longer holds|could not be found|not (be )?found/i, he: 'ההודעה כבר לא בתיבה (נמחקה או ספאם)', kind: 'terminal' },
  { re: /has no md5 in its listing/i, he: 'לפריט בדרייב אין חתימת קובץ (md5) ברישום', kind: 'terminal' },
  { re: /no deliverable attachment/i, he: 'להודעה אין קובץ מצורף שניתן למסור', kind: 'terminal' },
  { re: /no-link-in-message|no link in the message/i, he: 'אין קישור למסמך בגוף ההודעה', kind: 'terminal' },
  { re: /unsupported[_ ]file[_ ]format|unsupported (file|type)/i, he: 'סוג קובץ שאינו נתמך', kind: 'terminal' },
  { re: /too (large|big)|exceeds the (size|limit)/i, he: 'הקובץ גדול מהמותר', kind: 'terminal' },
  { re: /no drive connection|no mailbox connection|no .*connection (for|on) this/i, he: 'למקור אין חיבור מוגדר', kind: 'terminal' },
  { re: /OVERQUOTA|quota|too many requests|\b429\b/i, he: 'המקור הגביל את הקצב — ייעשה ניסיון נוסף', kind: 'transient' },
  { re: /ENOTFOUND|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EAI_AGAIN|socket hang up|timed? ?out|\b50[234]\b/i, he: 'המקור לא נגיש (שגיאת רשת) — ייעשה ניסיון נוסף', kind: 'transient' },
  { re: /permission|forbidden|\b403\b|\b401\b|unauthori[sz]ed/i, he: 'אין הרשאה במקור (החיבור פג או הוסר)', kind: 'terminal' },
];

export function reasonView(raw: string | null | undefined): ReasonView | null {
  const r = String(raw ?? '').trim();
  if (!r) return null;
  for (const rule of RULES) {
    if (rule.re.test(r)) return { he: rule.he, raw: r, kind: rule.kind, translated: true };
  }
  return { he: r, raw: r, kind: /\[terminal\]/i.test(r) ? 'terminal' : 'unknown', translated: false };
}

/** the same fold the `sync_item_reasons` view applies, so a card chip matches its rows */
export function foldReason(raw: string | null | undefined): string {
  const r = String(raw ?? '').trim() || '(no reason recorded)';
  return r.replace(/[A-Za-z0-9_-]{18,}/g, '<id>').replace(/\[line \d+\]/g, '[line n]');
}
