"""The catalogue — every document the office issues, as data (DGO-2029).

One row per type. A row says what the document IS (its Hebrew name, its family), what it may
carry (prices, VAT, payments, a cover, clauses, signatures), who may issue it (an עוסק פטור
issues no tax invoice), its numbering series, and which template draws it. The templates read
these flags; nothing in a template asks "which type am I" by name.

Families:
  commercial  a quote, an order, a work order, a payment request — prices, no tax effect
  tax         a tax invoice, an invoice-receipt, a credit note — the VAT documents of the books
  book        a receipt, a delivery note — documents of the books that carry no VAT of their own
  report      a customer statement
  legal       a service agreement, an NDA — clauses and two signatures
  narrative   a proposal (a cover, sections, the price, the acceptance), a letter
  sign        the certificate that closes an e-signature
"""

PATUR, MURSHE, COMPANY = 'patur', 'murshe', 'company'
ALL = (PATUR, MURSHE, COMPANY)
VAT_ISSUERS = (MURSHE, COMPANY)

#: every type, in the order the screen offers them
TYPES = {
    'PROPOSAL': dict(
        he='הצעה עסקית', short='הצעה', en='Proposal', family='narrative', template='proposal',
        series='PR', issuers=ALL, prices=True, vat=True, cover=True, acceptance=True,
        total_label='סה״כ להצעה', note='הצעה זו אינה מהווה מסמך חשבונאי.',
        summary='שער, הבנת הצורך, היקף, לוח זמנים, מחיר ואישור — המסמך שסוגר עסקה'),
    'QUOTE': dict(
        he='הצעת מחיר', en='Quote', family='commercial', template='ledger',
        series='QT', issuers=ALL, prices=True, vat=True, acceptance=True,
        total_label='סה״כ להצעה', note='הצעת מחיר זו אינה מהווה מסמך חשבונאי.',
        summary='שורות, מחיר ותוקף, באישור הלקוח בחתימה'),
    'SERVICE_AGREEMENT': dict(
        he='הסכם שירות', en='Service agreement', family='legal', template='agreement',
        series='AG', issuers=ALL, cover=True, signatures=True,
        summary='הצדדים, ההגדרות, הסעיפים והחתימות — נחתם אלקטרונית'),
    'NDA': dict(
        he='הסכם סודיות', en='Non-disclosure agreement', family='legal', template='agreement',
        series='ND', issuers=ALL, signatures=True,
        summary='שמירת סודיות הדדית לפני שמתחילים לדבר'),
    'WORK_ORDER': dict(
        he='הזמנת עבודה', en='Work order', family='commercial', template='ledger',
        series='WO', issuers=ALL, prices=True, vat=True, acceptance=True, hours=True,
        total_label='סה״כ להזמנה', note='הזמנת עבודה זו אינה מהווה מסמך חשבונאי.',
        summary='מה ייעשה, מי ומתי, בכמה שעות — ואישור הלקוח'),
    'ORDER': dict(
        he='הזמנה', en='Order', family='commercial', template='ledger',
        series='OR', issuers=ALL, prices=True, vat=True, acceptance=True,
        total_label='סה״כ להזמנה', note='הזמנה זו אינה מהווה מסמך חשבונאי.',
        summary='אישור הזמנה עם מועד אספקה'),
    'SHIPMENT': dict(
        he='תעודת משלוח', en='Delivery note', family='book', template='ledger',
        series='DN', issuers=ALL, prices=False, receiver=True,
        summary='מה נמסר, כמה ולמי — בחתימת השולח והמקבל'),
    'PAYMENT_REQUEST': dict(
        he='חשבון עסקה', en='Payment request', family='commercial', template='ledger',
        series='PQ', issuers=ALL, prices=True, vat=True, bank=True, due=True,
        total_label='סה״כ לתשלום', note='חשבון עסקה אינו חשבונית מס. קבלה תופק עם התשלום.',
        summary='דרישת תשלום לפני חשבונית — למורשה; ולעוסק פטור, החשבון שלו'),
    'INVOICE': dict(
        he='חשבונית מס', en='Tax invoice', family='tax', template='ledger',
        series='INV', issuers=VAT_ISSUERS, prices=True, vat=True, bank=True, due=True,
        allocation=True, total_label='סה״כ לתשלום',
        summary='חשבונית מס כחוק, עם מספר הקצאה כשנדרש'),
    'INVOICE_RECEIPT': dict(
        he='חשבונית מס קבלה', en='Tax invoice-receipt', family='tax', template='ledger',
        series='IR', issuers=VAT_ISSUERS, prices=True, vat=True, payments=True,
        allocation=True, total_label='סה״כ',
        summary='המכירה והתשלום במסמך אחד'),
    'RECEIPT': dict(
        he='קבלה', en='Receipt', family='book', template='receipt',
        series='RC', issuers=ALL, payments=True,
        summary='הכסף שהתקבל, באיזה אמצעי ועבור מה'),
    'CREDIT_NOTE': dict(
        he='חשבונית מס זיכוי', short='חשבונית זיכוי', en='Credit note', family='tax', template='ledger',
        series='CN', issuers=VAT_ISSUERS, prices=True, vat=True, credit=True,
        total_label='סה״כ זיכוי',
        summary='מבטלת חשבונית או חלק ממנה — עם הפניה אליה'),
    'STATEMENT': dict(
        he='כרטסת לקוח', en='Customer statement', family='report', template='statement',
        series='ST', issuers=ALL,
        summary='חיובים, תשלומים ויתרה — ומה פתוח לפי גיל'),
    'REPORT': dict(
        he='דוח ללקוח', en='Report', family='narrative', template='proposal',
        series='RP', issuers=ALL, cover=True,
        summary='סיכום הבנת העסק, דוח ניתוח, ממצאים והמלצות — עם שער'),
    'LETTER': dict(
        he='מכתב', en='Letter', family='narrative', template='letter',
        series='LT', issuers=ALL,
        summary='נייר המכתבים של העסק'),
    'SIGN_CERTIFICATE': dict(
        he='תעודת חתימה אלקטרונית', en='Signing certificate', family='sign', template='certificate',
        series='', issuers=ALL,
        summary='מי חתם, מתי, איך אומת, וטביעת האצבע של המסמך'),
}

#: the ledger's older names for the same documents (they stay readable)
ALIASES = {'DELIVERY_NOTE': 'SHIPMENT', 'CREDIT_INVOICE': 'CREDIT_NOTE', 'BALANCE_SHEET': 'STATEMENT'}


#: what a row says when it says nothing: no prices, no VAT, no cover … (a flag is True only where a row sets it)
FLAGS = ('prices', 'vat', 'cover', 'acceptance', 'signatures', 'bank', 'due', 'allocation', 'payments',
         'receiver', 'hours', 'credit')


def kind(doc_type):
    """The catalogue row of a type (an alias resolves), every flag present; KeyError for an unknown type."""
    code = (doc_type or '').upper()
    code = ALIASES.get(code, code)
    row = {f: False for f in FLAGS}
    row.update({'short': '', 'note': '', 'total_label': 'סה״כ'})
    row.update(TYPES[code])
    row['code'] = code
    return row


def may_issue(doc_type, tax_status):
    """Can a business of this tax status issue this type? (an עוסק פטור issues no VAT document)."""
    return (tax_status or MURSHE) in kind(doc_type)['issuers']


def offered(tax_status):
    """The types the screen offers a business of this status, in catalogue order."""
    return [code for code in TYPES if may_issue(code, tax_status)]
