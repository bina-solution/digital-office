/* Business data spine — the single "running business" seed shared by every embedded app.
   Injected (by build.mjs) before each mock, so a mock reads window.__biz instead of inventing its
   own entities. This is what makes the 10 apps tell ONE coherent story: an invoice that arrives in
   mail is the same document INDOX processes, my-docs lists, and notifications alerts about.

   Sim-only: real backends have their own data; this seeds the offline demo. Mocks project app-specific
   shapes from these canonical entities — the spine holds data, not response formats.

   Status vocabulary for an incoming document: to_handle | processing | done | failed. */
(function () {
  if (window.__biz) return;                       // idempotent (injected once per app iframe)

  var business = {
    name: 'בינה פתרונות בע״מ', tax_id: '514789234', type: 'עוסק מורשה',
    email: 'person127@example.com', domain: 'bina-solutions.co.il',
  };

  // Incoming supplier documents — the mail → INDOX → notifications spine. Values match what each app
  // already showed, now single-sourced. `date` is an ISO string; `kind` picks the INDOX/label bucket.
  var incoming = [
    {
      key: 'karton_20458', supplier: 'ישראל קרטון בע״מ', supplier_id: '513765432',
      email: 'person128@example.com', kind: 'invoice', number: '20458',
      amount: 3450.00, currency: 'ILS', date: '2026-07-21T09:42:00', status: 'to_handle', unread: true,
      subject: 'חשבונית מס 20458 - אספקת קרטונים לחודש יולי',
      file: 'חשבונית_20458.pdf', size: 184320,
      snippet: 'מצורפת חשבונית מס 20458 בגין אספקת קרטונים לחודש יולי 2026, סך 3,450.00 ₪.',
      body_html: '<div dir="rtl" style="font-family:Arial,sans-serif">מצ"ב חשבונית מס <b>20458</b> בגין אספקת קרטונים לחודש יולי 2026.<br>סכום לתשלום: <b>3,450.00 ₪</b> (כולל מע"מ).<br>תנאי תשלום: שוטף+30.<br><br>בברכה,<br>מחלקת הנהלת חשבונות<br>ישראל קרטון בע"מ</div>',
    },
    {
      key: 'cloud_88213', supplier: 'ספק הענן בע״מ', supplier_id: '514771290',
      email: 'person129@example.com', kind: 'receipt', number: '88213',
      amount: 412.00, currency: 'ILS', date: '2026-07-20T11:20:00', status: 'done', unread: false,
      subject: 'קבלה #88213 עבור מנוי ענן - יולי 2026',
      file: 'קבלה_88213.pdf', size: 92160,
      snippet: 'קבלה על תשלום חודשי עבור שירותי אחסון ענן — 412.00 ₪.',
      body_html: '<div dir="rtl" style="font-family:Arial,sans-serif">תודה על התשלום! מצ"ב קבלה מס\' 88213 עבור מנוי הענן החודשי (יולי 2026), סך <b>412.00 ₪</b>.<br><br>ספק הענן בע"מ</div>',
    },
    {
      key: 'iec_44521', supplier: 'חברת חשמל לישראל', supplier_id: '500010111',
      email: 'person130@example.com', kind: 'invoice', number: '44521',
      amount: 1205.60, currency: 'ILS', date: '2026-07-19T16:48:00', status: 'failed', unread: true,
      fail_reason: 'מספר עוסק מורשה לא תואם לרשומה הקיימת במערכת',
      subject: 'חשבון חשמל - מספר לקוח 44521 - תקופה 6',
      file: 'חשבון_חשמל_44521.pdf', size: 65536,
      snippet: 'חשבון חשמל עבור תקופה 6/2026, סך 1,205.60 ₪.',
      body_html: '<div dir="rtl" style="font-family:Arial,sans-serif">חשבון החשמל שלך עבור מספר לקוח 44521, תקופה 6/2026, מצורף.<br>סכום לתשלום: <b>1,205.60 ₪</b>.<br><br>חברת חשמל לישראל בע"מ</div>',
    },
    {
      key: 'bezeq_jul', supplier: 'בזק בינלאומי', supplier_id: '520044771',
      email: 'person131@example.com', kind: 'invoice', number: 'BZ-07-26',
      amount: 289.90, currency: 'ILS', date: '2026-07-19T10:03:00', status: 'processing', unread: true,
      subject: 'חשבונית אינטרנט וטלפוניה - יולי 2026',
      file: 'חשבונית_בזק_יולי.pdf', size: 71200,
      snippet: 'חשבונית עבור שירותי אינטרנט וטלפוניה לחודש יולי 2026 — 289.90 ₪.',
      body_text: 'לקוח יקר,\n\nמצורפת חשבונית עבור שירותי אינטרנט וטלפוניה לחודש 07/2026.\nסכום לתשלום: 289.90 ₪.\n\nבזק בינלאומי',
    },
  ];

  // ── projections / helpers ──────────────────────────────────────────────────
  var KIND_HE = { invoice: 'חשבוניות', receipt: 'קבלות', bank: 'דוחות בנק' };       // plural (label bucket)
  var KIND_HE_ONE = { invoice: 'חשבונית', receipt: 'קבלה', bank: 'דוח בנק' };       // singular (a document)
  // (INDOX's own types: it has no «BANK_REPORT» — a bank's statement is a document it does not recognise)
  var KIND_INDOX = { invoice: 'INVOICE', receipt: 'RECEIPT', bank: 'UNKNOWN' };
  var STATUS_HE = { to_handle: 'לטיפול', processing: 'באמצע עיבוד', done: 'טופל', failed: 'נכשל' };
  // INDOX document STATUS enum (matches incoming.js DOCS): to_handle→NEEDS_REVIEW,
  // processing→IN_PROGRESS, done→COMPLETED, failed→EXTRACTION_FAILED.
  var STATUS_INDOX = { to_handle: 'NEEDS_REVIEW', processing: 'IN_PROGRESS', done: 'COMPLETED', failed: 'EXTRACTION_FAILED' };

  // ── connections + what lives inside them ───────────────────────────────────
  // THE canonical account catalog. Drive, Mail and INDOX all read it, so INDOX's sync editor offers
  // exactly the accounts and exactly the folders/labels the Drive and Mail UIs show — previously
  // INDOX invented its own list and the three could drift apart silently.
  //   id/label/identity/color/status match the drive & mail mocks 1:1 (localdrive.js ACCOUNTS,
  //   mailview.js MAIL_ACCOUNTS); `locations` are that account's real folders (drive) or labels (mail).
  var DRIVE_CONNS = [
    { id: 'drive-local', source: 'drive', provider: 'local', label: 'אחסון מקומי',
      identity: 'מקומי · מובנה', color: 'var(--olive)', status: 'ok', builtin: true,
      locations: ['נכנס', 'נכנס/חשבוניות', 'נכנס/קבלות', 'ארכיון', 'סרוקים'] },
    { id: 'acc_office', source: 'drive', provider: 'gdrive', label: 'Google Drive · בינה',
      identity: 'person127@example.com', color: '#1a73e8', status: 'ok',
      locations: ['לקוחות', 'חשבוניות ומסמכים', 'כספים 2026', 'חוזים', 'מצגות',
                  'נכנס/חשבוניות', 'נכנס/קבלות', 'נכנס/תעודות משלוח', 'ארכיון/חשבוניות', 'ארכיון/קבלות'] },
    { id: 'acc_personal', source: 'drive', provider: 'gdrive', label: 'Google Drive · אישי',
      identity: 'person132@example.com', color: '#e8710a', status: 'warning',
      reason: 'מכסת האחסון כמעט מלאה (92% מתוך 15GB)',
      locations: ['תמונות', 'מסמכים אישיים', 'סרוקים 2026'] },
    { id: 'acc_dropbox', source: 'drive', provider: 'dropbox', label: 'Dropbox',
      identity: 'Dropbox · office@bina', color: '#0061ff', status: 'error',
      reason: 'החיבור נותק — נדרש אימות מחדש (שגיאת הרשאה 401)',
      locations: ['Shared', 'פרויקטים', 'Archive/2025', 'Archive/2026', 'Inbox'] },
  ];
  var MAIL_CONNS = [
    { id: 'local', source: 'gmail', provider: 'local', label: 'דואר מקומי',
      identity: 'מקומי · מובנה', color: 'var(--olive)', status: 'ok', builtin: true,
      locations: ['INBOX', 'ספקים', 'כספים'] },
    { id: 'gmail_office', source: 'gmail', provider: 'gmail', label: 'Gmail',
      identity: 'person127@example.com', color: '#ea4335', status: 'ok',
      locations: ['INBOX', 'לקוחות', 'ספקים', 'דחוף', 'מעקב', 'כספים',
                  'אינדוקס - חשבוניות - לטיפול', 'אינדוקס - חשבוניות - טופל',
                  'אינדוקס - קבלות - לטיפול', 'אינדוקס - קבלות - טופל',
                  'אינדוקס - דוחות בנק - לטיפול', 'אינדוקס - נכשל'] },
    { id: 'outlook_admin', source: 'gmail', provider: 'outlook', label: 'Outlook',
      identity: 'person133@example.com', color: '#0078d4', status: 'warning',
      reason: 'אימות Microsoft יפוג בעוד 3 ימים — מומלץ לחדש את החיבור',
      locations: ['INBOX', 'ספקים', 'הנהלת חשבונות', 'דוחות גיול'] },
  ];
  var CONNECTIONS = DRIVE_CONNS.concat(MAIL_CONNS);

  window.__biz = {
    business: business,
    incoming: incoming,
    connections: CONNECTIONS,
    driveConnections: DRIVE_CONNS,
    mailConnections: MAIL_CONNS,
    connection: function (id) { return CONNECTIONS.filter(function (c) { return c.id === id; })[0] || null; },
    /** The folders (drive) or labels (mail) that actually exist inside a connection. */
    locations: function (id) {
      var c = this.connection(id);
      return c ? { kind: c.source === 'gmail' ? 'labels' : 'folders', items: c.locations.slice() } : { kind: 'folders', items: [] };
    },
    addLocation: function (id, path) {
      var c = this.connection(id);
      if (!c || !path) return false;
      if (c.locations.indexOf(path) === -1) c.locations.push(path);
      return true;
    },
    // the Gmail/INDOX label a supplier doc carries, e.g. "אינדוקס - חשבוניות - לטיפול"
    mailLabel: function (doc) { return 'אינדוקס - ' + (KIND_HE[doc.kind] || KIND_HE.invoice) + ' - ' + (STATUS_HE[doc.status] || ''); },
    statusHe: function (s) { return STATUS_HE[s] || s; },
    kindHe: function (k) { return KIND_HE[k] || k; },
    kindHeOne: function (k) { return KIND_HE_ONE[k] || k; },
    kindIndox: function (k) { return KIND_INDOX[k] || 'INVOICE'; },
    statusIndox: function (s) { return STATUS_INDOX[s] || 'NEEDS_REVIEW'; },
    byKey: function (k) { return incoming.filter(function (d) { return d.key === k; })[0] || null; },
    byStatus: function (s) { return incoming.filter(function (d) { return d.status === s; }); },
  };
})();
