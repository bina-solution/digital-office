#!/usr/bin/env python3
"""«מסמכים» in a real browser (DGO-2169): the page as served (static/ with a <base>, as app.py's _page writes it), its
API a stand-in on this machine that answers SLOWLY on purpose (a document takes 1.5 s), driven over the DevTools
protocol with the standard library alone. What it holds, in the owner's words: «אני לוחץ על פריט ולא ברור מה קורה».

    python3 -I apps/my-docs/screen_check.py <chrome binary> apps/my-docs/static            # the checks
    python3 -I apps/my-docs/screen_check.py <chrome binary> apps/my-docs/static --shots DIR   # the pictures

Chrome for Testing on the Mac: ~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for
Testing.app/Contents/MacOS/Google Chrome for Testing. Not a test_* file on purpose: the line's runner has no Chrome.
On the stage-3 code: 61 of 61 (rebuilt here after a reboot wiped the session's copy); the first 31 of them on the code
before stage 1: 12 (the reds were the bugs). The pictures use the simulation's invented records — no real customer.
"""
import base64, http.server, json, os, random, re, signal, socket, subprocess, sys, tempfile, threading, time
import urllib.parse, urllib.request

BIN, STATIC = sys.argv[1], os.path.abspath(sys.argv[2])
SHOTS = sys.argv[sys.argv.index('--shots') + 1] if '--shots' in sys.argv else None
PORT, DBG = 8700 + random.randint(0, 200), 9500 + random.randint(0, 300)
NAME = 'קבוצת אורן בע"מ <b>x</b>'
DOCS = {
    'doc_a': {'id': 'doc_a', 'doc_type': 'QUOTE', 'status': 'issued', 'doc_number': 'A-1', 'customer_name': NAME,
              'total': 100, 'model': {'customer': {'name': NAME, 'phone': '050-123-4567', 'email': 'a@example.com'}}},
    'doc_b': {'id': 'doc_b', 'doc_type': 'QUOTE', 'status': 'draft', 'doc_number': None, 'customer_name': 'סטודיו גפן',
              'total': 50, 'model': {'customer': {'name': 'סטודיו גפן', 'phone': '050-1234567', 'zip': '6100000'},
                                     'lines': [{'description': 'סדנה', 'qty': 1, 'unit_price': 50, 'unit': 'יום',
                                                'order_ref': 'PO-7'}]}},
}
SLOW = {'doc_a': 1.5}
SHIFT = [0]
CALLS = []
FILL, SIGN, LINKS = {}, {}, {}       # per document: «מילוי וחתימה» events, one-signer envelopes, links (set by a check)
# «חתימות» (step 4): every link, as the BFF's /api/signatures gives it
SIGROWS = [
    {'id': 'fev1', 'kind': 'fill', 'ref': 'doc_a', 'doc': 'הצעת מחיר A-1 — קבוצת אורן', 'name': 'x.pdf', 'who': 'דנה',
     'state': 'opened', 'signed': 1, 'parties': 2, 'created_at': '2026-11-21T09:00:00Z'},
    {'id': 'env_f1', 'kind': 'sign', 'ref': None, 'doc': None, 'name': 'חוזה שכירות.pdf', 'who': 'משפחת לוי',
     'state': 'sent', 'created_at': '2026-11-20T09:00:00Z', 'expires_at': '2026-12-04T09:00:00Z'},
    {'id': 'env_v1', 'kind': 'view', 'ref': 'doc_b', 'doc': 'הצעת מחיר — סטודיו גפן', 'name': 'v.pdf', 'who': 'סטודיו גפן',
     'state': 'opened', 'created_at': '2026-11-19T09:00:00Z'},
    {'id': 'env_s9', 'kind': 'sign', 'ref': None, 'doc': None, 'name': 'טופס הצטרפות.pdf', 'who': 'משה',
     'state': 'signed', 'created_at': '2026-11-10T09:00:00Z', 'signed_at': '2026-11-11T09:00:00Z'},
    # a document's «מילוי וחתימה» the ledger did not name (older than its newest 500): still the DOCUMENT's — by its ref
    {'id': 'fev9', 'kind': 'fill', 'ref': 'doc_b', 'doc': None, 'name': 'הצעה ישנה.pdf', 'who': 'אבי', 'state': 'signing',
     'signed': 1, 'parties': 1, 'created_at': '2026-11-08T09:00:00Z'},
]


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ct='application/json'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def api(self, method, path, body, q=None):
        CALLS.append((method, path, body))
        p = path[len('/api'):]
        m = re.match(r'^/documents/([^/]+)(?:/(\w+))?$', p)
        if m:
            d = DOCS.get(m.group(1))
            time.sleep(SLOW.get(m.group(1), 0))
            if not d:
                return 404, {'error': 'not_found', 'message': 'המסמך לא נמצא'}
            if m.group(2) == 'preview':
                return 200, '<html><body dir="rtl"><h1 id="pv">%s</h1></body></html>' % d['id'], 'text/html'
            if m.group(2) == 'events':
                return 200, [{'ts': '2026-11-21T22:30:00+00:00', 'action': 'issue', 'detail': ''},
                             {'ts': '2026-11-21 23:45:00', 'action': 'send', 'detail': '<i>דנה</i>'}]
            if method == 'PATCH':
                d['model'] = json.loads(body or b'{}')
            return 200, d
        if p.startswith('/documents'):                # the ledger's pages, as apitools gives them (limit, offset)
            off, lim = int((q or {}).get('offset', ['0'])[0]), int((q or {}).get('limit', ['500'])[0])
            off = max(0, off - SHIFT[0]) if off else 0    # documents written between two reads: rows come again
            return 200, list(DOCS.values())[off:off + lim]
        if p == '/business':
            return 200, {'name': 'בינה', 'business_type': 'murshe', 'onboarded': True, 'vat_pct': 18}
        if p == '/me':
            return 200, {'name': 'דנה'}
        if p == '/signatures':
            return 200, {'ok': True, 'links': SIGROWS}
        if p == '/signatures/file' and method == 'POST':
            return 200, {'ok': True, 'link': 'https://sign.test/s/tok-file-1',
                         'envelope': {'id': 'env_f2', 'expires_at': '2026-12-06T10:00:00Z'}}
        if p.endswith('/prepare'):                    # «מילוי וחתימה» preparing: slow, then refused
            time.sleep(2.0)
            return 200, {'ok': False, 'message': 'המסמך לא הוכן לחתימה'}
        if p.startswith('/fill/'):
            return 200, {'ok': True, 'events': FILL.get(p[len('/fill/'):], [])}
        if p.startswith('/sign/'):
            return 200, {'ok': True, 'envelopes': SIGN.get(p[len('/sign/'):], [])}
        if p.startswith('/share/') and method == 'POST':
            return 200, {'ok': True, 'link': 'https://sign.test/s/tok-view-1',
                         'envelope': {'id': 'env_v9', 'expires_at': '2026-12-22T10:00:00Z'}}
        if p.startswith('/links/'):
            did = p[len('/links/'):]
            if did in LINKS:
                return 200, {'ok': True, 'links': LINKS[did]}
            if did == 'doc_a':
                return 200, {'ok': True, 'links': [{'id': 'env_a1', 'kind': 'view', 'state': 'sent', 'signer_name': 'דנה',
                                                    'created_at': '2026-11-21T10:00:00Z', 'expires_at': '2099-01-01T00:00:00Z'}]}
            return 200, {'ok': True, 'links': []}
        if p == '/customers':
            return 200, [{'id': 'c1', 'name': 'קבוצת אורן בע"מ', 'phone': '052-7654321'}]
        if p == '/items':
            return 200, []
        if p.startswith('/docGen/house/types'):
            return 200, {'types': [{'code': 'QUOTE', 'he': 'הצעת מחיר', 'summary': 'הצעה'}]}
        if p.startswith('/docGen/house/template'):
            time.sleep(SLOW.get('template', 0))
            return 200, {'ok': True, 'document': {}}
        if p == '/archive':                           # one of the office's own documents, and a file in «קבצים»
            return 200, {'data': {'status': [], 'rows': [
                {'provider': 'local', 'id': 'local:doc_a', 'ref': {'id': 'doc_a'}, 'type': 'QUOTE', 'number': 'A-1',
                 'party': NAME, 'date': '2026-11-20'},
                {'provider': 'drive', 'id': 'drive:1', 'ref': {'path': '/לקוחות/חוזה.pdf'}, 'type_name': 'קובץ',
                 'number': 'חוזה.pdf', 'date': '2026-11-19'}]}}
        if p.startswith('/docGen/house'):
            return 200, '<html><body>preview</body></html>', 'text/html'
        return 200, {}

    def go(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else b''
        if u.path.startswith('/api/'):
            r = self.api(self.command, u.path, body, urllib.parse.parse_qs(u.query))
            return self.send(r[0], r[1], r[2] if len(r) > 2 else 'application/json')
        f = os.path.normpath(os.path.join(STATIC, u.path.lstrip('/')))
        if f.startswith(STATIC) and os.path.isfile(f) and not f.endswith('index.html'):
            ct = {'.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml'}.get(os.path.splitext(f)[1],
                                                                                            'application/octet-stream')
            return self.send(200, open(f, 'rb').read(), ct)
        page = open(os.path.join(STATIC, 'index.html'), encoding='utf-8').read()
        page = re.sub(r'(<head(?:\s[^>]*)?>)', r'\1<base href="/">', page, count=1)   # as app.py's _page does
        return self.send(200, page, 'text/html; charset=utf-8')
    do_GET = do_POST = do_PATCH = do_PUT = go


class WS:
    """The least of a WebSocket client that speaks to Chrome's DevTools."""

    def __init__(self, url):
        host, rest = url.split('//', 1)[1].split('/', 1)
        h, p = host.split(':')
        self.s = socket.create_connection((h, int(p)), timeout=30)
        k = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(('GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                        'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n' % (rest, host, k)).encode())
        b = b''
        while b'\r\n\r\n' not in b:
            b += self.s.recv(4096)
        self.x = b.split(b'\r\n\r\n', 1)[1]
        self.n = 0

    def _r(self, k):
        while len(self.x) < k:
            self.x += self.s.recv(65536)
        o, self.x = self.x[:k], self.x[k:]
        return o

    def call(self, m, **p):
        self.n += 1
        my = self.n
        d = json.dumps({'id': my, 'method': m, 'params': p}).encode()
        ln = len(d)
        h = bytes([0x81]) + (bytes([0x80 | ln]) if ln < 126 else bytes([0x80 | 126]) + ln.to_bytes(2, 'big')
                             if ln < 65536 else bytes([0x80 | 127]) + ln.to_bytes(8, 'big'))
        mk = os.urandom(4)
        self.s.sendall(h + mk + bytes(c ^ mk[i % 4] for i, c in enumerate(d)))
        while True:
            b1, b2 = self._r(2)
            ll = b2 & 0x7F
            ll = int.from_bytes(self._r(2), 'big') if ll == 126 else int.from_bytes(self._r(8), 'big') if ll == 127 else ll
            f = self._r(ll)
            if b1 & 0x0F != 1:
                continue
            j = json.loads(f)
            if j.get('id') == my:
                return j.get('result', {})


results, errors = [], []


def check(name, ok, seen=None):
    results.append((bool(ok), name, seen))


def run_checks(ws, ev, wait):
    def go_home():
        for _ in range(3):                    # a cold Chrome may drop the first navigation: the page, or again
            ws.call('Page.navigate', url='http://127.0.0.1:%d/dash' % PORT)
            if wait("location.port === '%d' && document.readyState === 'complete'" % PORT, 15):
                return
    go_home()
    errors.clear()
    check('the dashboard lists the documents', wait("document.querySelectorAll('#recent tr[data-id]').length === 2", 15),
          ev('location.href'))
    cell = ev("document.querySelector('#recent tr[data-id=\"doc_a\"] td:nth-child(3)').textContent")
    check("a customer's name is text, never markup (A.4)", cell == NAME and not ev("!!document.querySelector('#recent td b')"), cell)
    check('a row takes the keyboard (tabindex)', ev("document.querySelector('#recent tr[data-id]').tabIndex") == 0)

    # 1. the drawer opens AT ONCE, while the slow document is still on its way
    ev("document.querySelector('#recent tr[data-id=\"doc_a\"]').click()")
    time.sleep(0.15)
    check('the drawer is open 150 ms after the click, the document still loading (A.2)',
          ev("!document.querySelector('#drawer').classList.contains('hidden') && document.querySelector('#dNum').textContent === '…'"),
          ev("[document.querySelector('#dNum').textContent, location.pathname]"))
    check('the address names the document at once', ev('location.pathname') == '/doc/doc_a')
    wait("document.querySelector('#dNum').textContent === 'A-1'", 4)
    check('then the document draws: its number', ev("document.querySelector('#dNum').textContent") == 'A-1')
    evs = ev("document.querySelector('#dEvents').textContent") or ''
    check("the log is Israel's clock, whatever the device's (A.13)", '22/11/2026 00:30' in evs and '22/11/2026 01:45' in evs, evs)
    check("an event's detail is text, never markup", not ev("!!document.querySelector('#dEvents i')"))

    # 2. ✕ goes BACK to the list's own entry; Forward reopens the document
    ev("document.querySelector('#closeDrawer').click()")
    wait("location.pathname === '/dash'", 3)
    check('✕ closes the drawer and the address is the list again',
          ev("document.querySelector('#drawer').classList.contains('hidden') && location.pathname === '/dash'"))
    ev('history.forward()')
    check('Forward reopens it: ✕ went back, it left no second «dash» (A.10)',
          wait("location.pathname === '/doc/doc_a' && !document.querySelector('#drawer').classList.contains('hidden')", 4))
    wait("document.querySelector('#dNum').textContent === 'A-1'", 4)

    # 3. Back closes the drawer
    ev('history.back()')
    check('Back closes the drawer (A.10)',
          wait("location.pathname === '/dash' && document.querySelector('#drawer').classList.contains('hidden')", 3))

    # 4. only the LATEST open draws: A is slow, B is fast
    ev("openDoc('doc_a'); openDoc('doc_b')")
    time.sleep(2.2)
    num = ev("document.querySelector('#dNum').textContent")
    acts = ev("[...document.querySelectorAll('#drawer [data-act]')].map(b => b.textContent.trim()).join(' | ')") or ''
    cust = ev("document.querySelector('#dCust') && document.querySelector('#dCust').textContent")
    check("two opens, the slow one first: the drawer is B's alone (A.3)", num == '' and cust == 'סטודיו גפן', [num, cust, acts[:40]])
    check("B's buttons (a draft: «עריכה»), never A's", 'עריכה' in acts and 'ביטול' not in acts, acts)
    nxt = ev("document.querySelector('#dNext').textContent") or ''
    check('a draft says where it stands and its next step is the main button',
          'טיוטה' in nxt and ev("document.querySelector('#dNext .primary') && document.querySelector('#dNext .primary').dataset.act") == 'issuefill', nxt)
    check('«עוד פעולות» holds the rest, without the next step\'s own', ev(
          "!document.querySelector('#dActions [data-act=\"issuefill\"]') && !document.querySelector('#dActions [data-act=\"edit\"]')"
          " && !!document.querySelector('#dActions [data-act=\"editlink\"]') && !document.querySelector('#dActions .primary')"))
    check("B's page in the preview", 'doc_b' in (ev("document.querySelector('#dPdf').srcdoc") or ''))
    check("the address is B's", ev('location.pathname') == '/doc/doc_b')
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)

    # 4a. an issued quote: «הופקה», its next step is to send it to sign; the timeline holds the link's own time
    ev("openDoc('doc_a')")
    wait("document.querySelector('#dNum').textContent === 'A-1' && document.querySelector('#dEvents').textContent.includes('קישור לצפייה')", 5)
    nxt = ev("document.querySelector('#dNext').textContent") or ''
    check('an issued quote: «הצעת מחיר הופקה. השלב הבא: לשלוח … לחתימה»', 'הצעת מחיר הופקה' in nxt and 'לחתימה' in nxt
          and ev("document.querySelector('#dNext .primary').dataset.act") == 'fill', nxt)
    tl = ev("document.querySelector('#dEvents').textContent") or ''
    # (the stand-in's link was made at 10:00Z on the 21st, before the issue at 22:30Z: time decides the order)
    check("the timeline: the ledger's trail and the link's «נשלח קישור לצפייה», in time order",
          'הופק' in tl and 'נשלח קישור לצפייה' in tl and tl.index('נשלח קישור לצפייה') < tl.index('הופק') < tl.index('נשלח ·'), tl)
    check('the head says what, for whom, how much', ev("document.querySelector('#dCust').textContent") == NAME
          and '₪' in (ev("document.querySelector('#dHead').textContent") or ''), ev("document.querySelector('#dHead').textContent"))

    # 4a'. «קישור לצפייה»: the short form, then the SEND SHEET — WhatsApp first, to the customer's own number
    ev("document.querySelector('#dNext [data-act=\"share\"]').click()")
    wait("!!document.querySelector('form.lcard input[name=to]')", 4)
    ev("document.querySelector('form.lcard').requestSubmit()")
    check('the link is sent from a sheet, WhatsApp first', wait("!!document.querySelector('.ss .ss-opt')", 5)
          and ev("document.querySelector('.ss .ss-opt').dataset.s") == 'wa',
          ev("document.querySelector('.ss') && [...document.querySelectorAll('.ss .ss-opt')].map(o => o.dataset.s).join()"))
    wa = ev("document.querySelector('.ss-wa') && document.querySelector('.ss-wa').getAttribute('href')") or ''
    check("WhatsApp opens on the customer's own number, the link in the words",
          wa.startswith('https://wa.me/972501234567?text=') and 'tok-view-1' in urllib.parse.unquote(wa), wa[:90])
    check("the sheet says the link's own date", '22/12/2026' in (ev("document.querySelector('.ss').textContent") or ''))
    ws.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    time.sleep(0.4)
    check('Escape closes the sheet and leaves the document open',
          not ev("!!document.querySelector('.ss')") and ev("!document.querySelector('#drawer').classList.contains('hidden')"))
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)

    # 4b. while B loads, A's links are gone from the drawer (the reader of stage 1, #1)
    SLOW.pop('doc_a', None)
    SLOW['doc_b'] = 1.5
    ev("openDoc('doc_a')")
    wait("!!document.querySelector('#dLinks [data-revoke]')", 4)
    had = ev("!!document.querySelector('#dLinks [data-revoke]')")
    ev("openDoc('doc_b')")
    time.sleep(0.2)
    check("A's «סגירת הקישור» is gone the moment B opens, while B loads",
          had and not ev("!!document.querySelector('#dLinks [data-revoke]')") and ev("document.querySelector('#dLinks').dataset.doc") == 'doc_b',
          [had, ev("document.querySelector('#dLinks').innerHTML.slice(0,60)")])
    time.sleep(1.6)
    SLOW.pop('doc_b', None)
    SLOW['doc_a'] = 1.5
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)

    # 4c. an issued document's edit address takes its own place: Back is not stuck on it (the reader, #3)
    wait("location.pathname === '/dash'", 2)
    ev("showRoute('doc/doc_a/edit')")
    L2 = ev('history.length')
    ev("editDoc('doc_a')")
    wait("location.pathname === '/doc/doc_a'", 4)
    check("an issued document's edit address is replaced by its drawer, not pushed over",
          ev('history.length') == L2 and ev('location.pathname') == '/doc/doc_a', [L2, ev('history.length'), ev('location.pathname')])
    ev('history.back()')
    check('…so Back leaves it', wait("location.pathname === '/dash' && document.querySelector('#drawer').classList.contains('hidden')", 4),
          ev('location.pathname'))

    # 5. Escape closes a drawer
    ev("openDoc('doc_b')")
    wait("!document.querySelector('#drawer').classList.contains('hidden')", 2)
    ws.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    time.sleep(0.5)
    check('Escape closes the drawer', ev("document.querySelector('#drawer').classList.contains('hidden')"))

    # 6. the editor is ONE entry, and Back asks before it drops what was typed
    wait("location.pathname === '/dash'", 2)
    ev("document.querySelector('#newBtn').click()")
    wait("location.pathname === '/new' && !!document.querySelector('.tcard[data-type=\"QUOTE\"]')", 4)
    ev("document.querySelector('.tcard[data-type=\"QUOTE\"]').click()")
    wait("location.pathname === '/new/QUOTE'", 4)
    # (history.length counts forward entries too: the claim is that the entry behind the form is the list itself)
    check('the gallery and the form are one history entry: behind the form is the list',
          ev('history.state && history.state.from') == 'dash', ev('history.state'))
    ev("const c = document.querySelector('#cName'); c.value = 'לקוח חדש'; c.dispatchEvent(new Event('input', {bubbles: true}))")
    ev('history.back()')
    check('Back with something typed asks first (A.11)', wait("!!document.querySelector('.bask')", 3),
          ev("document.querySelector('.bask h2') && document.querySelector('.bask h2').textContent"))
    ev('history.back()')                                   # a second Back while the question is up
    time.sleep(0.4)
    check('a second Back while asked asks nothing more', ev("document.querySelectorAll('.bask').length") == 1,
          ev("document.querySelectorAll('.bask').length"))
    ev("document.querySelectorAll('.bask .bask-btn')[0].click()")      # «חזרה לעריכה»
    time.sleep(0.4)
    check('«חזרה לעריכה»: the editor stays, typed text and its address with it',
          ev("!document.querySelector('#editor').classList.contains('hidden') && document.querySelector('#cName').value === 'לקוח חדש' && location.pathname === '/new/QUOTE'"),
          ev("[location.pathname, document.querySelector('#cName').value]"))
    ev('history.back()')
    wait("!!document.querySelector('.bask')", 3)
    ev("document.querySelectorAll('.bask .bask-btn')[1].click()")      # «יציאה»
    # (two Backs were pressed above: the address went two entries back, and the screen follows the address)
    check('«יציאה»: the editor closes, and the screen is what the address says',
          wait("document.querySelector('#editor').classList.contains('hidden') && "
               "(location.pathname.startsWith('/doc/') ? !document.querySelector('#drawer').classList.contains('hidden') "
               ": document.querySelector('#drawer').classList.contains('hidden'))", 4), ev('location.pathname'))
    ev("if (!document.querySelector('#drawer').classList.contains('hidden')) document.querySelector('#closeDrawer').click()")
    time.sleep(0.5)
    ev("document.querySelector('#newBtn').click()")
    wait("!!document.querySelector('.tcard[data-type=\"QUOTE\"]')", 4)
    ev("document.querySelector('.tcard[data-type=\"QUOTE\"]').click()")
    wait("location.pathname === '/new/QUOTE'", 4)
    ev("const c2 = document.querySelector('#cName'); c2.value = 'אחר'; c2.dispatchEvent(new Event('input', {bubbles: true}))")
    ev("document.querySelector('#overlay').click()")
    check('a tap outside the editor asks before it drops the form', wait("!!document.querySelector('.bask')", 3))
    ev("document.querySelectorAll('.bask .bask-btn')[1].click()")
    time.sleep(0.5)
    check('…and «יציאה» closes it', ev("document.querySelector('#editor').classList.contains('hidden')"))

    # 7. a draft's save keeps what its form does not show (the second reader of DGO-2047, #2)
    ev("editDoc('doc_b')")
    wait("location.pathname === '/doc/doc_b/edit' && document.querySelector('#cName').value === 'סטודיו גפן'", 5)
    m = json.loads(ev('JSON.stringify(buildModel())') or '{}')
    check('the same customer keeps its phone and zip',
          m.get('customer', {}).get('phone') == '050-1234567' and m.get('customer', {}).get('zip') == '6100000', m.get('customer'))
    ln = (m.get('lines') or [{}])[0]
    check('a line keeps its unit and its order ref', ln.get('unit') == 'יום' and ln.get('order_ref') == 'PO-7', ln)
    ev("const c3 = document.querySelector('#cName'); c3.value = 'לקוח אחר'; c3.dispatchEvent(new Event('input', {bubbles: true}))")
    m2 = json.loads(ev('JSON.stringify(buildModel())') or '{}')
    check('another customer is only what the form says', 'phone' not in m2.get('customer', {}), m2.get('customer'))
    ev("document.querySelector('#cName').value = 'סטודיו גפן'")
    ws.call('Input.dispatchKeyEvent', type='keyDown', key='ס', code='KeyX', windowsVirtualKeyCode=88, modifiers=4)
    time.sleep(0.3)
    check('⌘X on the Hebrew layout saves nothing', not [c for c in CALLS if c[0] == 'PATCH'])
    ws.call('Input.dispatchKeyEvent', type='keyDown', key='ד', code='KeyS', windowsVirtualKeyCode=83, modifiers=4)
    time.sleep(0.8)
    check('⌘S (the S key, «ד») saves the draft where it is', [c for c in CALLS if c[0] == 'PATCH'])

    # 7b. the list (doc-list.js) — chips with counts, search, a real click on a row, the same row again, a phone's card
    ev("closeEditor(true); show('docs')")
    check('the list: a row per document, each a link to its address',
          wait("document.querySelectorAll('#docsTable a.lst-row').length === 2", 6) and
          ev("document.querySelector('#docsTable a.lst-row').getAttribute('href').startsWith('doc/')"),
          ev("document.querySelectorAll('#docsTable a.lst-row').length"))
    chips = (ev("[...document.querySelectorAll('.lst-chip')].map(c => c.textContent).join(' | ')") or '').replace(' ', '')
    check('chips say how many each holds', 'הכל2' in chips and 'טיוטות1' in chips, chips)
    ev("document.querySelector('.lst-chip[data-f=\"draft\"]').click()")
    check('a chip filters', ev("document.querySelectorAll('#docsTable a.lst-row').length") == 1)
    ev("document.querySelector('.lst-chip[data-f=\"all\"]').click()")
    ev("const q = document.querySelector('.lst-search input'); q.value = 'אורן'; q.dispatchEvent(new Event('input'))")
    time.sleep(0.4)
    found = ev("[...document.querySelectorAll('#docsTable a.lst-row')].map(a => a.dataset.id).join()")
    check('one search finds the customer', found == 'doc_a', found)
    ev("const q2 = document.querySelector('.lst-search input'); q2.value = ''; q2.dispatchEvent(new Event('input'))")
    time.sleep(0.4)

    def click_row(rid):
        x, y = ev("(()=>{const b=document.querySelector('#docsTable a.lst-row[data-id=\"%s\"]').getBoundingClientRect();"
                  " return [b.x+b.width/2, b.y+b.height/2];})()" % rid)
        for t in ('mousePressed', 'mouseReleased'):
            ws.call('Input.dispatchMouseEvent', type=t, x=x, y=y, button='left', clickCount=1)
    click_row('doc_b')
    time.sleep(0.2)
    check('a real click on a row opens the drawer at once, the row marked',
          ev("!document.querySelector('#drawer').classList.contains('hidden') && location.pathname === '/doc/doc_b'")
          and ev("document.querySelector('a.lst-row[data-id=\"doc_b\"]').getAttribute('aria-current')") == 'true')
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.5)
    click_row('doc_b')
    time.sleep(0.2)
    check('the same row again opens it again', ev("!document.querySelector('#drawer').classList.contains('hidden')"))
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.5)
    ws.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
    time.sleep(0.6)
    areas = ev("getComputedStyle(document.querySelector('#docsTable a.lst-row')).gridTemplateAreas")
    check('a phone: each row is a card of two lines, nothing off the side',
          '"t amt" "cust st"' in (areas or '') and ev('document.documentElement.scrollWidth <= 390'),
          [areas, ev('document.documentElement.scrollWidth')])
    ws.call('Emulation.clearDeviceMetricsOverride')
    time.sleep(0.4)

    # 7b'. a wide screen: the document BESIDE the list — no overlay, the list keeps its clicks, one history entry
    ev("show('docs')")
    wait("document.querySelectorAll('#docsTable a.lst-row').length === 2", 5)
    click_row('doc_a')
    wait("document.querySelector('#dNum').textContent === 'A-1'", 5)
    check('a wide screen: the document opens beside the list, with no overlay',
          ev("document.body.classList.contains('split') && getComputedStyle(document.querySelector('#overlay')).display === 'none'"))
    check('the other rows stay where they were, and take a click',
          ev("(()=>{const r=document.querySelector('#docsTable a.lst-row[data-id=\"doc_b\"]').getBoundingClientRect();"
             " const e=document.elementFromPoint(r.x+r.width*0.8, r.y+r.height/2); return !!(e && e.closest('a.lst-row[data-id=\"doc_b\"]'));})()"))
    click_row('doc_b')
    wait("location.pathname === '/doc/doc_b' && document.querySelector('#dCust') && document.querySelector('#dCust').textContent === 'סטודיו גפן'", 5)
    check('another row takes the open one\'s place: one history entry, the list behind it',
          ev("location.pathname") == '/doc/doc_b' and ev('history.state && history.state.from') == 'docs',
          [ev('location.pathname'), ev('history.state')])
    # «מסמך חדש» beside an open document: the editor is modal — the document steps aside, and comes back after it
    ev("document.querySelector('#newBtn').click()")
    wait("!!document.querySelector('.tcard[data-type=\"QUOTE\"]')", 4)
    check('«מסמך חדש» from the split: the editor on top, the open document out of its way',
          ev("getComputedStyle(document.querySelector('#editor')).display !== 'none' && getComputedStyle(document.querySelector('#drawer')).display === 'none'"))
    ev("document.querySelector('#closeEditor').click()")
    check('…and closing the editor brings the document back, at its own address',
          wait("document.querySelector('#editor').classList.contains('hidden') && getComputedStyle(document.querySelector('#drawer')).display !== 'none' && location.pathname === '/doc/doc_b'", 4),
          ev('location.pathname'))
    ev("document.querySelector('#closeDrawer').click()")
    check('✕ goes back to the list, and the page takes its whole width again',
          wait("location.pathname === '/docs' && !document.body.classList.contains('split')", 4), ev('location.pathname'))
    # a scrolled list: the drawer still starts under the bar, inside the screen (it was measured against the window)
    ws.call('Emulation.setDeviceMetricsOverride', width=1366, height=380, deviceScaleFactor=1, mobile=False)
    time.sleep(0.4)
    ev('window.scrollTo(0, 200)')
    time.sleep(0.3)
    ev("document.querySelector('#docsTable a.lst-row[data-id=\"doc_a\"]').click()")
    wait("document.body.classList.contains('split')", 4)
    top = ev("document.querySelector('#drawer').getBoundingClientRect().top")
    check('a scrolled list: the drawer starts under the bar, inside the screen', top is not None and 0 < top < 150 and
          ev("(()=>{const b=document.querySelector('#closeDrawer').getBoundingClientRect(); const e=document.elementFromPoint(b.x+b.width/2, b.y+b.height/2); return !!(e && e.closest('#closeDrawer'));})()"),
          top)
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)
    ws.call('Emulation.clearDeviceMetricsOverride')
    time.sleep(0.4)
    # the dashboard's rows beside an open document: one history entry too
    ev("show('dash')")
    wait("document.querySelectorAll('#recent tr[data-id]').length === 2", 4)
    ev("document.querySelector('#recent tr[data-id=\"doc_a\"]').click()")
    wait("location.pathname === '/doc/doc_a'", 4)
    ev("document.querySelector('#recent tr[data-id=\"doc_b\"]').click()")
    wait("location.pathname === '/doc/doc_b'", 4)
    check("the dashboard's rows beside an open document take its place: one entry, the dashboard behind it",
          ev('history.state && history.state.from') == 'dash', ev('history.state'))
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)
    ev("show('docs')")
    wait("document.querySelectorAll('#docsTable a.lst-row').length === 2", 4)
    ws.call('Emulation.setDeviceMetricsOverride', width=1100, height=900, deviceScaleFactor=1, mobile=False)
    time.sleep(0.5)
    click_row('doc_a')
    wait("!document.querySelector('#drawer').classList.contains('hidden')", 4)
    check('a narrower screen keeps the document over the page, with its overlay',
          ev("!document.body.classList.contains('split') && getComputedStyle(document.querySelector('#overlay')).display !== 'none'"))
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.5)
    ws.call('Emulation.clearDeviceMetricsOverride')
    time.sleep(0.4)

    # 7c. «הצעד הבא» reads every way a document went out (the reader of stage 3)
    def opened(did, t=6):
        ev("openDoc('%s')" % did)
        return wait("!!document.querySelector('#dCust') && location.pathname === '/doc/%s' && "
                    "!document.querySelector('#dEvents p.muted')" % did, t)

    def nxt_text():
        return ev("document.querySelector('#dNext').textContent") or ''

    def primary():
        return ev("(document.querySelector('#dNext .primary') || {dataset: {}}).dataset.act || ''")
    DOCS['doc_fc'] = {'id': 'doc_fc', 'doc_type': 'QUOTE', 'status': 'sent', 'doc_number': 'Q-9', 'customer_name': 'קבוצת אורן',
                      'total': 10, 'model': {}}
    FILL['doc_fc'] = [{'id': 'ev1', 'status': 'complete', 'final_state': 'ok',
                       'parties': [{'label': 'הלקוח', 'state': 'signed', 'signed_at': '2026-11-21T12:00:00Z'},
                                   {'label': 'הספק', 'state': 'signed', 'signed_at': '2026-11-21T13:00:00Z'}]}]
    opened('doc_fc')
    time.sleep(0.4)
    check('every side signed by «מילוי וחתימה»: the step is the invoice, never «שליחה לחתימה»',
          'כל הצדדים חתמו' in nxt_text() and primary() == 'convert:INVOICE' and 'המשך' in nxt_text(), [nxt_text(), primary()])
    FILL['doc_fc'] = [{'id': 'ev2', 'status': 'open', 'parties': [{'label': 'הלקוח', 'state': 'waiting'},
                                                                   {'label': 'הספק', 'state': 'signed'}]}]
    ev('closeDrawer(true)')
    opened('doc_fc')
    time.sleep(0.4)
    check('an open «מילוי וחתימה»: how many signed, and no second send offered',
          'חתמו 1 מתוך 2' in nxt_text() and primary() == '', [nxt_text(), primary()])
    DOCS['doc_n'] = {'id': 'doc_n', 'doc_type': 'NDA', 'status': 'sent', 'doc_number': 'N-1', 'customer_name': 'ACME',
                     'total': None, 'model': {}}
    SIGN['doc_n'] = [{'id': 'env_n', 'status': 'signed', 'signer_name': 'ACME', 'signed_at': '2026-11-20T09:00:00Z'}]
    ev('closeDrawer(true)')
    opened('doc_n')
    time.sleep(0.4)
    check('a signed NDA bills nothing (CONVERSIONS has none): its signed copy is the step; «מ־ACME»',
          primary() == 'signed:env_n' and 'מ־ACME' in nxt_text() and 'convert:' not in (ev("document.querySelector('#drawer').innerHTML") or 'x'),
          [nxt_text(), primary()])
    DOCS['doc_i'] = {'id': 'doc_i', 'doc_type': 'INVOICE', 'status': 'issued', 'doc_number': 'I-5', 'customer_name': '',
                     'total': 50, 'model': {}}
    ev('closeDrawer(true)')
    opened('doc_i')
    time.sleep(0.4)
    check('no customer name: «ללקוח», never «להלקוח»', 'ללקוח' in nxt_text() and 'להלקוח' not in nxt_text(), nxt_text())
    LINKS['doc_i'] = [{'id': 'env_vi', 'kind': 'view', 'state': 'sent', 'signer_name': 'דנה', 'created_at': '2026-11-22T08:00:00Z',
                       'expires_at': '2099-01-01T00:00:00Z'}]
    ev('closeDrawer(true)')
    opened('doc_i')
    wait("document.querySelector('#dNext').textContent.includes('קישור לצפייה')", 4)
    check('an invoice sent by a view link: the step is the payment', primary() == 'pay' and 'נשלח קישור לצפייה' in nxt_text(),
          [nxt_text(), primary()])
    DOCS['doc_cn'] = {'id': 'doc_cn', 'doc_type': 'INVOICE', 'series': 'CN', 'status': 'issued', 'doc_number': 'CN-1',
                      'customer_name': 'קבוצת אורן', 'total': -50, 'model': {}}
    ev('closeDrawer(true)')
    opened('doc_cn')
    time.sleep(0.4)
    check('an old credit (an INVOICE in series CN, negative) is never offered «סימון כשולם»',
          not ev("!!document.querySelector('#drawer [data-act=\"pay\"]')"), nxt_text())
    DOCS['doc_d'] = {'id': 'doc_d', 'doc_type': 'INVOICE', 'status': 'draft', 'doc_number': None, 'customer_name': 'קבוצת אורן',
                     'total': 5, 'model': {}}
    ev('closeDrawer(true)')
    opened('doc_d')
    time.sleep(0.3)
    issued = lambda: len([c for c in CALLS if c[0] == 'POST' and c[1].endswith('/issue')])
    before = issued()
    ev("document.querySelector('#dNext [data-act=\"issue\"]').click()")
    time.sleep(0.4)
    check('«הפקה» asks before it issues', ev("!!document.querySelector('.bask')") and issued() == before)
    ev("document.querySelectorAll('.bask .bask-btn')[0].click()")
    time.sleep(0.3)
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)
    check('closing marks no row in the list', not ev("!!document.querySelector('a.lst-row[aria-current=\"true\"]')"))

    # 7d. the phone for WhatsApp is read from «לקוחות» when sending — never written into the document
    DOCS['doc_k'] = {'id': 'doc_k', 'doc_type': 'LETTER', 'status': 'issued', 'doc_number': 'L-1', 'customer_id': 'c1',
                     'customer_name': 'קבוצת אורן בע"מ', 'total': None, 'model': {'customer': {'name': 'קבוצת אורן בע"מ'}}}
    opened('doc_k')
    time.sleep(0.3)
    ev("document.querySelector('#dNext [data-act=\"share\"]').click()")
    wait("!!document.querySelector('form.lcard')", 4)
    ev("document.querySelector('form.lcard').requestSubmit()")
    wait("!!document.querySelector('.ss-wa')", 5)
    wa2 = ev("document.querySelector('.ss-wa').getAttribute('href')") or ''
    check("WhatsApp to the catalog's number when the document holds none", wa2.startswith('https://wa.me/972527654321?'), wa2[:60])
    ev("document.querySelector('.ss-wa').addEventListener('click', e => e.preventDefault(), {once: true}); document.querySelector('.ss-wa').click()")
    time.sleep(0.6)
    check('the sheet stays after WhatsApp (the link is not lost when the app does not open)', ev("!!document.querySelector('.ss')"))
    ev("document.querySelector('.ss [data-s=close]').click()")
    time.sleep(0.3)
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)
    ev("document.querySelector('#newBtn').click()")
    wait("!!document.querySelector('.tcard[data-type=\"QUOTE\"]')", 4)
    ev("document.querySelector('.tcard[data-type=\"QUOTE\"]').click()")
    wait("location.pathname === '/new/QUOTE'", 4)
    time.sleep(0.4)
    ev("const cn = document.querySelector('#cName'); cn.value = 'קבוצת אורן בע\"מ'; cn.dispatchEvent(new Event('input', {bubbles: true}))")
    check('a customer picked in the editor brings no phone into the document (it would be printed)',
          'phone' not in json.loads(ev('JSON.stringify(buildModel().customer)') or '{}'), ev('JSON.stringify(buildModel().customer)'))
    ev('closeEditor()')
    time.sleep(0.3)

    # 7e. «חתימות» inside «מסמכים» (step 4): every link in one place, a document's opens the document, a file's its card
    check('«חתימות» is in the app\'s own nav, a real link', ev("(document.querySelector('.side nav a[data-view=\"signatures\"]') || {}).getAttribute && "
                                                             "document.querySelector('.side nav a[data-view=\"signatures\"]').getAttribute('href')") == 'signatures')
    ev("show('signatures')")
    check('the view lists every link', wait("document.querySelectorAll('#sigTable a.lst-row').length === 5", 6),
          ev("document.querySelectorAll('#sigTable a.lst-row').length"))
    chips = (ev("[...document.querySelectorAll('#sigTable .lst-chip')].map(c => c.textContent).join(' | ')") or '').replace(' ', '')
    check('chips: how many wait for a signature (one being signed now too), how many were signed',
          'ממתיניםלחתימה3' in chips and 'נחתמו1' in chips, chips)
    ev("const sq = document.querySelector('#sigTable .lst-search input'); sq.value = 'לוי'; sq.dispatchEvent(new Event('input'))")
    time.sleep(0.4)
    check('one search finds the signer', ev("document.querySelectorAll('#sigTable a.lst-row').length") == 1)
    ev("const sq2 = document.querySelector('#sigTable .lst-search input'); sq2.value = ''; sq2.dispatchEvent(new Event('input'))")
    time.sleep(0.4)
    ev("document.querySelector('#sigTable a.lst-row[data-i=\"0\"]').click()")
    check("a document's link opens the document itself", wait("location.pathname === '/doc/doc_a' && !document.querySelector('#drawer').classList.contains('hidden')", 5),
          ev('location.pathname'))
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.5)
    ev("document.querySelector('#sigTable a.lst-row[data-i=\"1\"]').click()")
    check("a file's link opens its card: a new link, close it", wait("!!document.querySelector('.lcard [data-a=\"again\"]')", 4)
          and ev("!!document.querySelector('.lcard [data-a=\"revoke\"]')"))
    ws.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    time.sleep(0.4)
    check('Escape closes the card and asks nothing (it is not «סגירת הקישור»)',
          not ev("!!document.querySelector('.lcard')") and not ev("!!document.querySelector('.bask')"))
    ev("document.querySelector('#sigTable a.lst-row[data-i=\"4\"]').click()")
    check("a document's link the ledger did not name still opens the document (by its ref), never a file's card",
          wait("location.pathname === '/doc/doc_b' && !document.querySelector('#drawer').classList.contains('hidden')", 5)
          and not ev("!!document.querySelector('.lcard')"), ev('location.pathname'))
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.5)
    # «חתימה על קובץ»: a real PDF into the file field, then the link, sent WhatsApp first
    ev("document.querySelector('#sigTable .sig-new').click()")
    wait("!!document.querySelector('form.lcard input[type=file]')", 4)
    ev("document.querySelector('form.lcard').requestSubmit()")
    time.sleep(0.3)
    check('no file: said in the form, nothing sent', ev("!document.querySelector('form.lcard .lc-warn').hidden")
          and not [c for c in CALLS if c[1] == '/api/signatures/file'])
    pdf = os.path.join(tempfile.mkdtemp(), 'חוזה.pdf')
    open(pdf, 'wb').write(b'%PDF-1.7 a lease\n')
    root = ws.call('DOM.getDocument', depth=-1)['root']['nodeId']
    node = ws.call('DOM.querySelector', nodeId=root, selector='form.lcard input[type=file]')['nodeId']
    ws.call('DOM.setFileInputFiles', files=[pdf], nodeId=node)
    ev("const fm = document.querySelector('form.lcard'); fm.signer.value = 'משפחת לוי'; fm.phone.value = '054-1112233'; fm.requestSubmit()")
    check('a file goes out to be signed, and its link is sent WhatsApp first to the number typed',
          wait("!!document.querySelector('.ss-wa')", 6) and
          (ev("document.querySelector('.ss-wa').getAttribute('href')") or '').startswith('https://wa.me/972541112233?'),
          ev("document.querySelector('.ss-wa') && document.querySelector('.ss-wa').getAttribute('href')"))
    sent = [c for c in CALLS if c[1] == '/api/signatures/file']
    check('the PDF itself went to the BFF, with its signer', sent and b'%PDF-1.7 a lease' in sent[-1][2]
          and 'משפחת לוי'.encode() in sent[-1][2])
    ev("document.querySelector('.ss [data-s=close]').click()")
    time.sleep(0.3)

    # 7f. the editor on a phone: the form OR the document, the total always in sight, no drawing out of sight
    ws.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
    time.sleep(0.5)
    ev("document.querySelector('#newBtn').click()")
    wait("!!document.querySelector('.tcard[data-type=\"QUOTE\"]')", 4)
    ev("document.querySelector('.tcard[data-type=\"QUOTE\"]').click()")
    wait("location.pathname === '/new/QUOTE' && !document.querySelector('#stage').classList.contains('hidden')", 5)
    time.sleep(0.6)
    vis = lambda sel: ev("(()=>{const e=document.querySelector('%s'); return !!e && getComputedStyle(e).display !== 'none';})()" % sel)
    check('a phone: the switch «טופס | המסמך», the form shown, the document not', vis('.ed-seg') and vis('#docForm') and not vis('#stagePreview'))
    drawn = lambda: len([c for c in CALLS if c[0] == 'POST' and c[1] == '/api/docGen/house'])
    before = drawn()
    ev("const pr = document.querySelector('#lines input[data-k=\"unit_price\"]'); pr.value = '100'; pr.dispatchEvent(new Event('input', {bubbles: true}))")
    time.sleep(0.9)
    tot = ev("document.querySelector('#edTotal').textContent") or ''
    check('the total in the buttons\' row follows the typing (VAT in)', '118.00' in tot, tot)
    check('while the form is shown the document is not drawn on every pause', drawn() == before, [before, drawn()])
    ev("document.querySelector('.ed-seg [data-t=\"doc\"]').click()")
    time.sleep(0.8)
    check('«המסמך»: the document is shown, and drawn now', vis('#stagePreview') and not vis('#docForm') and drawn() > before, [drawn(), before])
    ev("document.querySelector('.ed-seg [data-t=\"form\"]').click()")
    time.sleep(0.3)
    ws.call('Emulation.clearDeviceMetricsOverride')
    time.sleep(0.6)
    check('a wide desk: the form and the document side by side, no switch', not vis('.ed-seg') and vis('#docForm') and vis('#stagePreview'))
    ev('closeEditor()')
    time.sleep(0.3)

    # 7g. the audit's last findings: each mark only while it says something (A.9); the preparing card can be left
    # (A.12); «ייצוא» writes the list as filtered, a formula-like name as text; every page of the ledger is read
    DOCS['doc_paid'] = {'id': 'doc_paid', 'doc_type': 'INVOICE', 'status': 'paid', 'doc_number': 'I-9', 'customer_name': 'סטודיו גפן',
                        'total': 30, 'model': {}}
    opened('doc_paid')
    time.sleep(0.4)
    check('a paid invoice offers neither «סימון כשולם» nor «סימון כנשלח» (A.9)',
          not ev("!!document.querySelector('#drawer [data-act=\"pay\"], #drawer [data-act=\"send\"]')"),
          ev("[...document.querySelectorAll('#drawer [data-act]')].map(b => b.dataset.act).join()"))
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)
    ev("FillEditor.open({id: 'doc_a', doc_type: 'QUOTE', status: 'issued'})")
    check('«מילוי וחתימה» while it prepares: a way out (A.12)', wait("!!document.querySelector('.fe-load [data-fe=\"close\"]')", 3))
    ws.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    time.sleep(0.3)
    gone = not ev("!!document.querySelector('.fe-scrim')")
    time.sleep(2.3)                                       # the refusal arrives after it was closed
    check('Escape closes it, and its late answer draws nothing', gone and not ev("!!document.querySelector('.fe-scrim')"))
    DOCS['doc_x2'] = {'id': 'doc_x2', 'doc_type': 'QUOTE', 'status': 'issued', 'doc_number': 'Q-77',
                      'customer_name': '=HYPERLINK("http://x")', 'total': -12.5, 'model': {}}
    ev("show('docs')")
    wait("document.querySelectorAll('#docsTable a.lst-row').length > 2", 5)
    # (the file's own bytes: Blob.text() decodes and drops the byte-order mark, as the Encoding standard says)
    ev("window.__csv = null; window.__bom = null; const _o = URL.createObjectURL; URL.createObjectURL = b => {"
       " b.arrayBuffer().then(a => { window.__bom = [...new Uint8Array(a.slice(0, 3))]; window.__csv = new TextDecoder('utf-8').decode(a); });"
       " return _o.call(URL, b); }")
    ev("document.querySelector('#docsTable .lst-export').click()")
    wait('window.__csv !== null', 4)
    csv, bom = ev('window.__csv') or '', ev('window.__bom')
    check('«ייצוא»: the list as a file Excel opens in Hebrew (UTF-8 with its mark), every row',
          bom == [0xEF, 0xBB, 0xBF] and csv.startswith('"סוג"') and '"Q-77"' in csv
          and csv.count('\r\n') == ev("document.querySelectorAll('#docsTable a.lst-row').length"), [bom, csv[:60]])
    check('…a name that begins like a formula is written as text, a negative sum stays a number',
          '"\'=HYPERLINK(""http://x"")"' in csv and '"-12.50"' in csv, [l for l in csv.split('\r\n') if 'Q-77' in l])
    DOCS.pop('doc_x2', None)
    for i in range(505):                                  # past one page of the ledger (500)
        DOCS['bulk%03d' % i] = {'id': 'bulk%03d' % i, 'doc_type': 'RECEIPT', 'status': 'issued', 'doc_number': str(9000 + i),
                                'customer_name': 'לקוח %d' % i, 'total': 1, 'model': {}}
    ev("show('dash'); show('docs')")
    total = len(DOCS)
    check('every page of the ledger is read: the count holds documents past the first 500',
          wait("(document.querySelector('.lst-chip[data-f=\"all\"] .lst-c') || {}).textContent === '%d'" % total, 8),
          [total, ev("(document.querySelector('.lst-chip[data-f=\"all\"] .lst-c') || {}).textContent")])
    # one fewer (the count then says the new reading), and a document written between two pages: a row comes again
    DOCS.pop('bulk000', None)
    SHIFT[0] = 1
    ev("show('dash'); show('docs')")
    check('…a row that comes on two pages is counted once (the reader)',
          wait("(document.querySelector('.lst-chip[data-f=\"all\"] .lst-c') || {}).textContent === '%d'" % (total - 1), 8),
          [total - 1, ev("(document.querySelector('.lst-chip[data-f=\"all\"] .lst-c') || {}).textContent")])
    SHIFT[0] = 0
    ev("DOCS_CAP = 500; show('dash'); show('docs')")
    check('…and more documents than the screen reads is said',
          wait("[...document.querySelectorAll('#bina-tell .btell')].some(t => t.textContent.includes('האחרונים בלבד'))", 8))
    ev('DOCS_CAP = 20000')
    for i in range(505):
        DOCS.pop('bulk%03d' % i, None)

    # 7h. the template on its way: the form waits for it, and one that answers after ✕ opens nothing (A.14); the
    # archive's rows take the keyboard
    SLOW['template'] = 1.2
    ev("document.querySelector('#newBtn').click()")
    wait("!!document.querySelector('.tcard[data-type=\"QUOTE\"]')", 4)
    ev("document.querySelector('.tcard[data-type=\"QUOTE\"]').click()")
    time.sleep(0.3)
    check('while the template is on its way the form takes no typing (A.14), nor its buttons a click (the reader)',
          ev("document.querySelector('#docForm').inert === true && document.querySelector('#editorFoot').inert === true"))
    posts = lambda: len([c for c in CALLS if c[0] == 'POST' and c[1] == '/api/documents'])
    n_posts = posts()
    # a form that would pass — a customer and a line — so only the wait can stop it
    ev("document.querySelector('#cName').value = 'לקוח בדיקה'; lines[0].description = 'סדנה'; lines[0].unit_price = 100")
    ev('save(true)')                                      # «הפק מסמך» by another way in: nothing is issued
    check('…and nothing is issued under a waiting form', posts() == n_posts, [n_posts, posts()])
    ev("document.querySelector('#closeEditor').click()")
    wait("!location.pathname.startsWith('/new')", 3)     # ✕ goes back through the history: async
    was = ev('location.pathname') or ''
    time.sleep(2.0)                                       # the template arrives after ✕
    check('…a template that answers after ✕ opens nothing, nor writes the address',
          ev("document.querySelector('#editor').classList.contains('hidden')") and not was.startswith('/new')
          and ev('location.pathname') == was, [was, ev('location.pathname')])
    ev("document.querySelector('#newBtn').click()")
    wait("!!document.querySelector('.tcard[data-type=\"QUOTE\"]')", 4)
    ev("document.querySelector('.tcard[data-type=\"QUOTE\"]').click()")
    check('…and once it arrived, the form is the user\'s again',
          wait("location.pathname === '/new/QUOTE' && document.querySelector('#docForm').inert === false", 4))
    SLOW.pop('template', None)
    ev('closeEditor()')
    wait("!location.pathname.startsWith('/new')", 3)     # (its Back lands later: a view shown before it would be undone)
    time.sleep(0.3)
    ev("show('archive')")
    wait("document.querySelectorAll('#archTable tr[data-i]').length === 2", 5)
    check('an archive row is reached by Tab', ev("document.querySelector('#archTable tr[data-i]').tabIndex") == 0)
    ev("document.querySelector('#archTable tr[data-i]').focus()")
    for t in ('keyDown', 'keyUp'):
        ws.call('Input.dispatchKeyEvent', type=t, key='Enter', code='Enter', windowsVirtualKeyCode=13)
    check('…and Enter opens it, as a click does', wait("location.pathname === '/doc/doc_a'", 5), ev('location.pathname'))
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)
    # a link closed in a drawer opened over «חתימות», and «מילוי וחתימה» sent: the list on screen is read again
    reads = lambda path: len([c for c in CALLS if c[0] == 'GET' and c[1] == path])
    ev("show('signatures')")
    wait("document.querySelectorAll('#sigTable a.lst-row').length > 0", 6)
    before = reads('/api/signatures')
    opened('doc_a')
    wait("!!document.querySelector('#dLinks [data-revoke]')", 6)
    ev("document.querySelector('#dLinks [data-revoke]').click()")
    wait("!!document.querySelector('.bask')", 3)
    ev("document.querySelectorAll('.bask .bask-btn')[1].click()")        # «סגירה»
    time.sleep(1.0)
    check('a link closed in a drawer over «חתימות»: the list is read again (the reader)',
          reads('/api/signatures') > before, [before, reads('/api/signatures')])
    before, doc_before = reads('/api/signatures'), reads('/api/documents/doc_a')
    ev("window.FillEditorSent({id: 'doc_a', doc_type: 'QUOTE', status: 'issued'})")
    time.sleep(2.0)
    check('«מילוי וחתימה» sent: its drawer and «חתימות» are read again (the reader)',
          reads('/api/signatures') > before and reads('/api/documents/doc_a') > doc_before,
          [before, reads('/api/signatures'), doc_before, reads('/api/documents/doc_a')])
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)
    # 7i. the dashboard's figures stay inside their cards — an eight-figure total, a six-figure average — at full width,
    # beside an open document (its average was cut to «l,542.37» there: the round's own pictures) and on a phone
    for i in range(20):
        DOCS['big%d' % i] = {'id': 'big%d' % i, 'doc_type': 'INVOICE', 'status': 'issued', 'doc_number': str(6100 + i),
                             'customer_name': 'לקוח %d' % i, 'total': 12000000 if i == 0 else 1000, 'vat': 0,
                             'doc_date': '01/11/2026', 'model': {}}
    figures = "[...document.querySelectorAll('#stats .kv, #stats .hc-amount')]"
    fits = figures + ".every(e => e.scrollWidth <= e.clientWidth)"
    seen = figures + ".map(e => e.textContent + ' ' + e.scrollWidth + '/' + e.clientWidth).join(' · ')"
    # (it measures THESE figures, never the small ones an earlier drawing left: the reader)
    drawn = "((document.querySelector('#stats .hc-amount') || {}).textContent || '').startsWith('₪12,0')"
    ev("show('dash')")
    full = wait(drawn, 8), ev(fits), ev(seen)
    opened('doc_a')
    time.sleep(0.4)
    beside = ev("document.body.classList.contains('split')"), ev(fits), ev(seen)
    ev("document.querySelector('#closeDrawer').click()")
    time.sleep(0.4)
    ws.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
    ev("show('docs'); show('dash')")
    time.sleep(0.6)
    phone = wait(drawn, 8), ev(fits), ev(seen), ev('document.documentElement.scrollWidth')
    ws.call('Emulation.clearDeviceMetricsOverride')
    check('the dashboard\'s figures fit their cards — at full width, beside an open document, on a phone',
          all(full[:2]) and all(beside[:2]) and all(phone[:2]) and phone[3] <= 390, [full, beside, phone])
    for i in range(20):
        DOCS.pop('big%d' % i, None)

    # 8. form fields keep a quote (A.4); Israel's day
    ev("closeEditor(true); editEntity('customers', {id: 'c1', name: 'קבוצת אורן בע\"מ'})")
    val = ev("document.querySelector('#editor input[name=name]').value")
    check('a name with «"» is whole in its field', val == 'קבוצת אורן בע"מ', val)
    check("Israel's day for a new document, whatever the device's", ev("whenFullHe('2026-11-21T23:30:00Z')") == '22/11/2026 01:30',
          ev("whenFullHe('2026-11-21T23:30:00Z')"))
    check('no script error on the page', not errors, errors)


def run_shots(ws, ev, wait):
    """The list, a quote, a draft, an invoice and its send sheet — desktop and phone — with invented records."""
    DOCS.clear()
    SLOW.clear()

    def doc(i, t, st, no, cust, total, date):
        DOCS[i] = {'id': i, 'doc_type': t, 'status': st, 'doc_number': no, 'customer_name': cust, 'total': total,
                   'doc_date': date, 'model': {'customer': {'name': cust}}}
    doc('d1', 'QUOTE', 'issued', '10001', 'לקוח לדוגמה — אולפני הקלטה', 12000, '19/11/2026')
    doc('d2', 'QUOTE', 'draft', None, 'נגריית אור השרון', 4800, '21/11/2026')
    doc('d3', 'PAYMENT_REQUEST', 'paid', '40012', 'סטודיו לב לבן', 8000, '13/11/2026')
    doc('d4', 'INVOICE', 'issued', '60031', 'מעדניית הגליל', 9360, '17/11/2026')
    doc('d5', 'RECEIPT', 'issued', '80016', 'סטודיו לב לבן', 8000, '13/11/2026')
    doc('d6', 'QUOTE', 'sent', '10000', 'שיפוצי א.ד.', 23500, '06/11/2026')
    doc('d7', 'RECEIPT', 'cancelled', '80009', 'קפה בוקר טוב', 3920, '27/10/2026')
    os.makedirs(SHOTS, exist_ok=True)
    ws.call('Emulation.setTimezoneOverride', timezoneId='Asia/Jerusalem')

    def shot(name):
        time.sleep(0.5)
        open(os.path.join(SHOTS, name), 'wb').write(base64.b64decode(ws.call('Page.captureScreenshot', format='png')['data']))
        print('shot', name)
    for w, h, mob, tag in ((1366, 900, False, 'desk'), (390, 844, True, 'phone')):
        ws.call('Emulation.setDeviceMetricsOverride', width=w, height=h, deviceScaleFactor=2 if mob else 1, mobile=mob)
        for _ in range(3):
            ws.call('Page.navigate', url='http://127.0.0.1:%d/docs' % PORT)
            if wait("document.querySelectorAll('#docsTable a.lst-row').length === 7", 15):
                break
        shot(tag + '-list.png')
        for did, name in (('d1', 'doc-quote'), ('d2', 'doc-draft'), ('d4', 'doc-invoice')):
            ev("document.querySelector('a.lst-row[data-id=\"%s\"]').click()" % did)
            wait("!!document.querySelector('#dNext .primary')", 8)
            shot('%s-%s.png' % (tag, name))
            if did != 'd4':
                ev("document.querySelector('#closeDrawer').click()")
                time.sleep(0.4)
        ev("document.querySelector('#dNext [data-act=\"share\"]').click()")
        wait("!!document.querySelector('form.lcard')", 5)
        ev("document.querySelector('form.lcard').requestSubmit()")
        wait("!!document.querySelector('.ss-scrim.on')", 5)
        shot(tag + '-send-sheet.png')
        ev("document.querySelector('.ss [data-s=close]').click()")
        time.sleep(0.3)
        ev("document.querySelector('#closeDrawer').click()")
        time.sleep(0.4)


def main():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    prof = tempfile.mkdtemp()
    pr = subprocess.Popen([BIN, '--headless=new', '--remote-debugging-port=%d' % DBG, '--user-data-dir=' + prof,
                           '--no-first-run', '--window-size=1280,900', 'about:blank'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        pg = None
        for _ in range(150):                  # a loaded Mac: Chrome took 9 s to listen
            try:
                targets = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json' % DBG))
                pg = next((t for t in targets if t['type'] == 'page'), None)
            except OSError:
                pg = None
            if pg:
                break
            time.sleep(0.3)
        if not pg:
            sys.exit('screen_check: Chrome did not answer on its DevTools port')
        ws = WS(pg['webSocketDebuggerUrl'])
        ws.call('Page.enable')
        ws.call('Runtime.enable')
        ws.call('Emulation.setTimezoneOverride', timezoneId='America/New_York')   # the device's clock is not Israel's

        def ev(e):
            r = ws.call('Runtime.evaluate', expression=e, returnByValue=True, awaitPromise=True)
            if r.get('exceptionDetails'):
                d = r['exceptionDetails']
                errors.append((e[:80], d.get('exception', {}).get('description', d.get('text'))))
            return r.get('result', {}).get('value')

        def wait(cond, t=6):                  # a condition that returns a DOM node reads as {}: write `!!…`
            end = time.time() + t
            while time.time() < end:
                if ev(cond):
                    return True
                time.sleep(0.1)
            return False
        (run_shots if SHOTS else run_checks)(ws, ev, wait)
    finally:
        try:
            os.killpg(pr.pid, signal.SIGTERM)
            pr.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            os.killpg(pr.pid, signal.SIGKILL)
        srv.shutdown()
    if not SHOTS:
        for ok, name, seen in results:
            print(('ok   ' if ok else 'FAIL ') + name + ('' if ok or seen is None else '   — saw: %r' % (seen,)))
        good = sum(1 for r in results if r[0])
        print('%d of %d' % (good, len(results)))
        sys.exit(0 if good == len(results) else 1)


if __name__ == '__main__':
    main()
