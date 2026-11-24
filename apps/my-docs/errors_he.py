"""The ledger's refusals, as the owner reads them (DGO-2169, the code audit A.7).

apitools answers in its own words — `str(e)`, English: «not_compliant: customer address missing (§9(a)(4))»,
«document doc_… is issued and immutable — issue a credit document to correct», «cannot pay a cancelled document».
The screen showed them as they came. Here each is one Hebrew sentence that says what is missing or why, the
regulation's section kept where the ledger named it; the ledger's own text stays beside it as `detail`, for the log.
An unknown message is never guessed at: it gets the general sentence of its status, and its text goes in `detail`.
"""
import re

#: what each compliance check names, by the start of the ledger's own words (doc_models/models.py validate_compliance)
_MISSING = [
    ('issuer name missing', 'שם העסק'),
    ('issuer registration number', 'מספר העוסק או ח.פ. של העסק'),
    ('issuer address missing', 'כתובת העסק'),
    ('document date missing', 'תאריך המסמך'),
    ("the credited invoice's number missing", 'מספר החשבונית שמזוכה'),
    ("the credited invoice's date missing", 'תאריך החשבונית שמזוכה'),
    ('the reason for the credit missing', 'סיבת הזיכוי'),
    ('invoice number missing', 'מספר החשבונית'),
    ('delivery-note ref missing', 'מספר תעודת המשלוח'),
    ('customer name missing', 'שם הלקוח'),
    ('customer address missing', 'כתובת הלקוח (רחוב או עיר)'),
    ('payer name missing', 'שם המשלם'),
    ('no lines', 'שורה אחת לפחות: מה נמכר או ניתן'),
    ('invoice total missing', 'סכום החשבונית'),
    ('amount received missing', 'הסכום שהתקבל'),
    ('nature of receipt', 'עבור מה התקבל התשלום'),
    ('recipient signature missing', 'חתימת מקבל התשלום'),
    ('cheque number/bank missing', 'מספר ההמחאה והבנק שלה'),
    ('SENDER signature missing', 'חתימת השולח'),
]
#: a line's check: «line 2: unit of measure missing (§9(a)(6))» — counted from 0 by the ledger, from 1 on the screen
_LINE = [
    ('description missing', 'תיאור'),
    ('goods description missing', 'תיאור הטובין'),
    ('unit of measure missing', 'יחידת מידה'),
    ('quantity missing', 'כמות'),
]

#: a document's state, as «המסמך כבר …» says it — and as «מסמך ש…» does
_STATUS = {'draft': 'טיוטה', 'issued': 'הופק', 'sent': 'נשלח', 'paid': 'שולם', 'cancelled': 'בוטל'}
_THAT = {'draft': 'שעדיין טיוטה', 'issued': 'שכבר הופק', 'sent': 'שכבר נשלח', 'paid': 'ששולם', 'cancelled': 'שבוטל'}
_ACT = {'pay': 'לסמן כשולם', 'send': 'לסמן כנשלח', 'issue': 'להפיק', 'cancel': 'לבטל'}

#: the general sentence of a status the ledger's words are not known for. A word the tables do not know is never
#: carried into a Hebrew sentence («המסמך כבר being», the reader): the whole message is then this one
_GENERAL = {400: 'הבקשה לא התקבלה — חסר בה פרט או שאחד הערכים אינו תקין',
            403: 'הפעולה אינה מותרת כאן',
            409: 'הפעולה לא בוצעה: המצב השתנה בינתיים או שאינו מאפשר אותה — רעננו ונסו שוב',
            422: 'המסמך לא הופק — חסרים בו פרטים שהחוק דורש'}
#: what was not found, by the path that asked for it
_NOT_FOUND = (('documents', 'המסמך לא נמצא'), ('customers', 'הלקוח לא נמצא'), ('items', 'הפריט לא נמצא'))


def _section(text):
    """The regulation's section the ledger named, «§9(a)(4)» — its brackets nest, and its English after it is dropped."""
    i = text.find('(§')
    depth = 0
    for j in range(max(i, 0), len(text)) if i >= 0 else ():
        depth += {'(': 1, ')': -1}.get(text[j], 0)
        if depth == 0:
            return ' (' + text[i + 1:j].split(';')[0].split(' — ')[0].strip() + ')'
    return ''


def _items(text):
    """The ledger's list, split on its «; » — never on one inside a check's own brackets («(§5(a)(7); waived …)»)."""
    out, depth, cur = [], 0, ''
    for ch in text:
        depth += {'(': 1, ')': -1}.get(ch, 0)
        if ch == ';' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    return out + [cur]


def _one_missing(item):
    item = item.strip()
    m = re.match(r'line (\d+):\s*(.*)$', item)
    if m:
        n, rest = int(m.group(1)) + 1, m.group(2)
        for en, he in _LINE:
            if rest.startswith(en):
                return f'{he} בשורה {n}{_section(rest)}'
        return None
    for en, he in _MISSING:
        if item.startswith(en):
            return he + _section(item)
    return None


def _general(status, path=''):
    if status == 404:
        part = str(path or '').strip('/').split('/')
        what = part[1] if part and part[0] == 'api' and len(part) > 1 else (part[0] if part else '')
        return next((s for p, s in _NOT_FOUND if what == p), 'מה שנתבקש לא נמצא — ייתכן שנמחק או שהקישור שגוי')
    return _GENERAL.get(status) or ('מאגר המסמכים לא השלים את הפעולה' if status >= 500 else _GENERAL[400])


def he(message, status=400, path=''):
    """The Hebrew sentence for the ledger's `message` (None when there is none), its HTTP `status`, and the `path`
    that was asked (it names what a 404 did not find)."""
    msg = str(message or '').strip()
    if msg.startswith('not_compliant:'):
        items = [i for i in _items(msg[len('not_compliant:'):]) if i.strip()]
        said = [_one_missing(i) for i in items]
        if said and all(said):
            return 'המסמך לא הופק — חסר בו: ' + '; '.join(said)
        return _GENERAL[422]
    if msg.startswith('allocation_held:'):
        return 'רשות המסים לא נתנה מספר הקצאה לחשבונית, והיא לא הופקה — נסו שוב בעוד כמה דקות'
    m = re.match(r'document \S+ is (\w+) and immutable', msg)
    if m and m.group(1) in _STATUS:
        return f'המסמך כבר {_STATUS[m.group(1)]} ואינו נערך עוד — מתקנים אותו במסמך זיכוי או במסמך חדש'
    m = re.match(r'document \S+ (?:is )?already (\w+)', msg)
    if m and m.group(1) in _STATUS:
        return f'המסמך כבר {_STATUS[m.group(1)]}'
    m = re.match(r'cannot (\w+) a (\w+) document', msg)
    if m and m.group(1) in _ACT and m.group(2) in _THAT:
        return f'אי אפשר {_ACT[m.group(1)]} מסמך {_THAT[m.group(2)]}'
    if msg.startswith('a credit note is not cancelled'):
        return 'חשבונית זיכוי אינה מבוטלת — מפיקים חשבונית מס חדשה במקומה'
    if msg.startswith('the credit note would not reverse'):
        return 'חשבונית הזיכוי לא הייתה מבטלת את המסמך בדיוק, ולכן לא בוצע דבר'
    if re.match(r'document \S+ changed while it was being cancelled', msg):
        return 'המסמך השתנה בזמן הביטול ולא בוטל — פתחו אותו שוב'
    if msg.startswith('cannot convert'):
        return 'אי אפשר להמשיך מהמסמך הזה למסמך מהסוג הזה'
    if msg.startswith('an agreement is made from an issued'):
        return 'הסכם נעשה ממסמך שכבר הופק — הפיקו את המסמך קודם'
    if re.search(r'an \w+ business does not issue this document', msg):
        return 'סוג העסק שבהגדרות אינו מפיק מסמך מהסוג הזה'
    if msg.startswith('unknown doc_type'):
        return 'סוג המסמך אינו מוכר'
    if re.search(r'is not an amount', msg):
        return 'אחד הסכומים אינו מספר'
    if re.search('[א-ת]', msg) and not re.search('[A-Za-z]{4,}', msg):
        return msg                                   # the ledger said it in Hebrew already
    return _general(status, path)


def body(payload, status, path=''):
    """A ledger's JSON error body, its `message` in Hebrew and its own words kept as `said` — a key the ledger does not
    write, so nothing of its own is overwritten (the reader: `detail` was). The rest is kept."""
    if not isinstance(payload, dict) or status < 400:
        return payload
    out = dict(payload)
    own = out.get('message') or out.get('error') or ''
    out['message'] = he(own, status, path)
    if own and own != out['message']:
        out['said'] = str(own)
    return out
