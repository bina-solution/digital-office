/* test_bina_ask.mjs — the shared question and notice, executed against a DOM just big enough.
 *
 *   node platform-base/bina-ui/test_bina_ask.mjs
 *
 * `bina-ask.js` replaces the browser's confirm / alert / prompt. What it must keep is what those
 * guaranteed and what they could not do: a question that is ANSWERED (never left open, never
 * answered twice), a cancel that is a cancel on every path (Esc, the button, a click outside), the
 * focus given back, a destructive question that Enter does not confirm by reflex, a text that must
 * be typed before deleting for good, and the facts shown before the question is asked.
 * Pixels are not its business; the flow suites look at the screens.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'bina-ask.js'), 'utf8');

/* ── a DOM, just enough of one ──────────────────────────────────────────────────────────────── */
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.on = {}; this.className = ''; this.textContent = ''; this.value = ''; this.disabled = false; this.parent = null; this.id = ''; }
  appendChild(n) { this.children.push(n); n.parent = this; return n; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(t, f) { (this.on[t] = this.on[t] || []).push(f); }
  focus() { doc.activeElement = this; }
  fire(t, e = {}) { (this.on[t] || []).forEach((f) => f(Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, e))); }
  all() { return [this, ...this.children.flatMap((c) => c.all())]; }
  find(cls) { return this.all().filter((n) => n.className.split(' ').includes(cls)); }
  text() { return this.all().map((n) => n.textContent).join(' '); }
}
const keys = [];
const doc = {
  head: new El('head'), body: new El('body'), activeElement: null,
  createElement: (t) => new El(t),
  getElementById: (id) => [...doc.head.all(), ...doc.body.all()].find((n) => n.id === id) || null,
  addEventListener: (t, f) => { if (t === 'keydown') keys.push(f); },
  removeEventListener: (t, f) => { const i = keys.indexOf(f); if (i >= 0) keys.splice(i, 1); },
};
const press = (key, extra = {}) => [...keys].forEach((f) => f(Object.assign({ key, preventDefault() {}, stopPropagation() {} }, extra)));
const timers = [];
const box = { document: doc, setTimeout: (f, ms) => { timers.push([f, ms]); return timers.length; }, Promise };
vm.createContext(box);
vm.runInContext(src, box);
vm.runInContext(src, box);                               // two screens on one page may both carry it
const { binaAsk, binaTell } = box;

let passed = 0;
function ok(cond, what) {
  if (!cond) { console.error('FAIL  ' + what); process.exit(1); }
  passed += 1;
}
const open = () => doc.body.find('bask');
const card = () => open()[0].find('bask-card')[0];
const btn = (cls) => card().find('bask-btn').find((b) => b.className.includes(cls));
const settle = async (p) => Promise.race([p, new Promise((r) => setImmediate(() => r('still open')))]);

/* ── a plain question ───────────────────────────────────────────────────────────────────────── */
const opener = new El('button'); doc.activeElement = opener;
let p = binaAsk({ title: 'לפרוס את האתר מחדש?', body: 'שורה ראשונה\n\nשורה שנייה', ok: 'פריסה' });
ok(open().length === 1 && card().attrs.role === 'alertdialog' && card().attrs['aria-modal'] === 'true' && card().attrs.dir === 'rtl',
   'the question is one modal dialog, right to left');
ok(card().find('bask-read')[0].children.filter((c) => c.tag === 'p').length === 2, 'each line of the body is a paragraph (no markup is read from it)');
ok(doc.activeElement === btn('primary') && btn('primary').textContent === 'פריסה', 'a plain question opens on its action, named by the caller');
ok(await settle(p) === 'still open', 'nothing answers for the person');
btn('primary').fire('click');
ok(await p === true && open().length === 0 && doc.activeElement === opener, 'agreeing answers true, closes, and gives the focus back');
ok(keys.length === 0, 'the keyboard is released when the question closes');
ok(doc.head.all().filter((n) => n.id === 'bina-ask-css').length === 1, 'the style is added once, however many questions are asked');

/* ── every way of cancelling is a cancel ────────────────────────────────────────────────────── */
p = binaAsk({ title: 'x' }); press('Escape'); ok(await p === false && open().length === 0, 'Esc cancels');
p = binaAsk({ title: 'x' }); card().find('bask-btn')[0].fire('click'); ok(await p === false, 'the cancel button cancels — and comes first');
p = binaAsk({ title: 'x' }); open()[0].fire('mousedown'); ok(await p === false, 'a click outside the card cancels');
p = binaAsk({ title: 'x' }); card().fire('mousedown', { target: card() }); ok(await settle(p) === 'still open', '…a click inside it does not');
press('Escape'); await p;

/* ── a destructive question, with its facts ─────────────────────────────────────────────────── */
p = binaAsk({ title: 'להסיר את המחשב?', ok: 'הסרה', danger: true, facts: [['מחשב', 'שרת פיתוח'], ['כתובת', '203.0.113.82']] });
ok(doc.activeElement === card().find('bask-btn')[0] && doc.activeElement.textContent === 'ביטול', 'a destructive question opens on «ביטול»: Enter never destroys by reflex');
ok(btn('danger') && btn('danger').textContent === 'הסרה', 'its action is marked as destructive');
const facts = card().find('bask-facts')[0];
ok(facts && facts.children.map((c) => c.tag + ':' + c.textContent).join('|') === 'dt:מחשב|dd:שרת פיתוח|dt:כתובת|dd:203.0.113.82', 'the facts are shown as key and value, before the question is answered');
press('Tab'); ok(doc.activeElement === btn('danger'), 'Tab moves inside the question');
press('Tab'); ok(doc.activeElement.textContent === 'ביטול', '…and wraps there: the page behind is not reachable');
press('Tab', { shiftKey: true }); ok(doc.activeElement === btn('danger'), 'Shift+Tab goes the other way');
press('Escape'); ok(await p === false, 'and it can still be cancelled');

/* ── a question that takes text ─────────────────────────────────────────────────────────────── */
p = binaAsk({ title: 'שם לתצוגה', ok: 'שמירה', input: { label: 'שם', value: 'ישן', dir: 'auto' } });
let field = card().all().find((n) => n.tag === 'input');
ok(doc.activeElement === field && field.value === 'ישן' && field.attrs.dir === 'auto', 'a question with a field opens in the field, holding what was there');
field.value = 'חדש'; press('Enter'); ok(await p === 'חדש', 'Enter in the field answers with the text');
p = binaAsk({ title: 'שם', input: {} }); press('Escape'); ok(await p === null, 'cancelling a text question is null — not an empty answer');
p = binaAsk({ title: 'שם', input: {} }); btn('primary').fire('click'); ok(await p === '', '…and an empty answer is an answer');

/* ── a text that must be typed before deleting for good ─────────────────────────────────────── */
p = binaAsk({ title: 'למחוק את תיקיית האתר?', ok: 'מחיקה', danger: true, input: { label: 'הקלד את מזהה האתר', must: 'my-site' } });
field = card().all().find((n) => n.tag === 'input');
ok(btn('danger').disabled === true, 'the action is not offered until the text is typed');
press('Enter'); btn('danger').fire('click'); ok(await settle(p) === 'still open', '…by Enter or by a click');
field.value = 'my-sit'; field.fire('input'); ok(btn('danger').disabled === true, 'a near miss is not it');
press('Tab'); press('Tab'); ok(doc.activeElement !== btn('danger'), 'Tab does not land on an action that is not offered');
field.value = ' my-site '; field.fire('input'); ok(btn('danger').disabled === false, 'the exact text (spaces around it aside) offers it');
btn('danger').fire('click'); ok((await p).trim() === 'my-site', 'and the answer is what was typed');

/* ── what is READ is the one part that scrolls; the title, the field, a refusal and the buttons are not in it ── */
p = binaAsk({ title: 'למחוק לצמיתות?', body: 'הפעולה אינה הפיכה', ok: 'מחיקה', danger: true, facts: [['קבצים', '128']], input: { label: 'הקלידו', must: 'x' } });
const read = card().find('bask-read')[0];
ok(card().children.map((c) => (c.tag === 'h2' ? 'title' : c.className.split(' ')[0])).join(' ') === 'title bask-read bask-field bask-said bask-acts',
   'the card is its title, what is read, the field, the refusal and the buttons, in that order');
ok(read.children.map((c) => c.tag).join() === 'p,dl' && read.all().every((n) => n.tag !== 'button' && n.tag !== 'input'),
   'what is read is the body and the facts — nothing a person presses or types in');
Object.assign(read, { scrollHeight: 300, clientHeight: 100, scrollTop: 0 });
press('ArrowDown'); ok(read.scrollTop === 0, 'in the field the arrows are the caret\'s');
press('Tab'); press('ArrowDown'); press('PageDown'); press('ArrowUp');
ok(doc.activeElement.textContent === 'ביטול' && read.scrollTop === 100, 'from a button the arrows and the page keys scroll what is read');
read.scrollHeight = 100; press('ArrowDown'); ok(read.scrollTop === 100, '…and are left alone when all of it is in sight');
press('Escape'); ok(await p === null, 'and it is cancelled like any other');

/* ── a question that does the action itself: busy while it runs, and a refusal is said in it ── */
const runs = [];
let flight;
const act = (v) => new Promise((res, rej) => { runs.push(v); flight = { res, rej }; });
const said = () => card().find('bask-said')[0];
p = binaAsk({ title: 'לבטל את הצימוד?', ok: 'ביטול הצימוד', danger: true, run: act });
ok(said().textContent === '' && said().attrs.role === 'alert', 'the place a refusal is said in is there, and empty, before anything is refused');
btn('danger').fire('click');
ok(await settle(p) === 'still open' && runs.length === 1 && runs[0] === true, 'with `run`, agreeing runs the action and the question stays up');
ok(btn('danger').disabled && btn('danger').textContent === 'מבצע…' && card().find('bask-btn')[0].disabled && doc.activeElement === card(),
   'while it runs the action says it is working, neither button can be pressed, and the focus stays in the question');
btn('danger').fire('click'); press('Escape'); open()[0].fire('mousedown'); card().find('bask-btn')[0].fire('click'); press('Tab');
ok(runs.length === 1 && await settle(p) === 'still open', '…it does not run twice, and nothing cancels what is already in flight');
flight.rej(new Error('הלשכה השנייה לא ענתה'));
ok(await settle(p) === 'still open' && said().textContent === 'הלשכה השנייה לא ענתה', 'a refusal is said in the question, in the error\'s own words');
ok(!btn('danger').disabled && btn('danger').textContent === 'ביטול הצימוד' && doc.activeElement.textContent === 'ביטול',
   'the action is offered again under its own name — and a destructive one waits on «ביטול» again');
btn('danger').fire('click'); ok(await settle(p) === 'still open' && runs.length === 2 && said().textContent === '', 'trying again runs it again, and the old refusal is taken down');
flight.res();
ok(await p === true && open().length === 0 && doc.activeElement === opener, 'once the action succeeded the question answers true, closes, and gives the focus back');
p = binaAsk({ title: 'שם הלשכה', ok: 'שמירה', input: { label: 'שם', value: 'ישן' }, run: act });
field = card().all().find((n) => n.tag === 'input');
field.value = 'חדש'; press('Enter');
ok(await settle(p) === 'still open' && runs.length === 3 && runs[2] === 'חדש', 'the action is handed the answer — here, what was typed');
flight.rej({});
ok(await settle(p) === 'still open' && said().textContent === 'הפעולה נכשלה' && doc.activeElement === field, 'a refusal with no words of its own is still said, and the focus is back in the field');
press('Escape'); ok(await p === null, 'after a refusal the question can be cancelled like any other');
p = binaAsk({ title: 'x', run: () => { throw new Error('נזרק מיד'); } }); btn('primary').fire('click');
ok(await settle(p) === 'still open' && said().textContent === 'נזרק מיד', 'an action that throws at once is a refusal too');
press('Escape'); await p;

/* ── a notice ───────────────────────────────────────────────────────────────────────────────── */
const a = binaTell('המחיקה נכשלה', 'bad'), b = binaTell('הועתק');
const tell = doc.getElementById('bina-tell');
ok(tell && tell.children.length === 2 && doc.body.children.filter((c) => c.id === 'bina-tell').length === 1, 'notices stack in one place');
ok(a.attrs.role === 'alert' && b.attrs.role === 'status' && a.className.includes('bad') && b.className.includes('ok'), 'a failure interrupts a screen reader; a success does not');
ok(a.textContent === 'המחיקה נכשלה', 'a notice is text: nothing in it is read as markup');
const [, msBad] = timers[timers.length - 2], [, msOk] = timers[timers.length - 1];
ok(msBad > msOk, 'a failure stays longer than a success');
a.fire('click'); ok(tell.children.length === 1, 'a click dismisses a notice');
timers[timers.length - 1][0](); ok(tell.children.length === 0, '…and it leaves by itself');

/* ── what a notice can carry: a way on, the service's own sentence, no clock ────────────────── */
let went = 0;
const clocks = timers.length;
const u = binaTell('הקובץ עבר לאשפה', 'ok', { ms: 8000, act: ['ביטול', () => { went += 1; }] });
ok(timers.length === clocks + 1 && timers[timers.length - 1][1] === 8000, 'the time a notice stays can be named beside what it carries');
const way = u.children.find((c) => c.tag === 'button');
ok(way && way.textContent === 'ביטול' && way.attrs.type === 'button', 'a way on is a button in the notice, named by the caller');
way.fire('click'); ok(went === 1 && tell.children.length === 0, 'pressing it runs the way on once and takes the notice down');
const before = timers.length;
const s = binaTell('השליחה נכשלה', 'bad', { more: 'upstream said: 502', stay: true });
ok(s.children.filter((c) => c.tag === 'small').map((c) => c.textContent).join() === 'upstream said: 502' && s.textContent === 'השליחה נכשלה',
   'the service\'s own sentence is a line of its own, as text, under the notice\'s words');
ok(timers.length === before && tell.children.length === 1, 'a notice that stays has no clock');
s.fire('click'); ok(tell.children.length === 0, '…and leaves when it is pressed');
binaTell('נשמר', 'ok', 3000); ok(timers[timers.length - 1][1] === 3000, 'a bare number is still the time it stays');
tell.children.slice().forEach((n) => n.remove());

console.log(`bina-ask: ${passed} checks passed`);
