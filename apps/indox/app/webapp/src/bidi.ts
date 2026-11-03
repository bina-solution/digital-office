/** A LATIN TOKEN THAT STAYS ONE PIECE INSIDE A HEBREW SENTENCE (DGO-534).
 *
 *  Hebrew runs right to left; a Latin token inside it runs left to right, and everything at the
 *  SEAM — a `*`, a `/`, a parenthesis — is direction-neutral, so it takes the direction of the
 *  sentence around it instead of the token. Measured on the four sentences the owner's scan found
 *  («q_v3_*» rendered as «*q_v3_», «(/documentDraw)» with its mark on the wrong side): the reader
 *  sees a token that is not the token.
 *
 *  U+2066 (LEFT-TO-RIGHT ISOLATE) … U+2069 (POP DIRECTIONAL ISOLATE) say "everything between us is
 *  one left-to-right run", so the seam belongs to the token. Written as a function rather than pasted
 *  into the sentences because a mark nobody can see is not left lying in the source — the same rule
 *  the mail screen's `ltr()` carries (apps/mail/mailview/static/app.js).
 */
export const ltr = (s: string): string => `\u2066${s}\u2069`;
