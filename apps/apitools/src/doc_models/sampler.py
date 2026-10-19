"""Seeded realistic document sampling — 'the average of the demo corpus'.

sample(doc_type, seed) returns a fully-populated model whose field distributions
mirror the real corpus (see SPEC.md presence rates). Deterministic per seed.
"""
from __future__ import annotations

import random

from .models import (Party, LineItem, BankDetails, BSLine, Invoice, InvoiceReceipt,
                     Order, Quote, ShipmentCert, BalanceSheet, Receipt)

SUPPLIERS = [
    ('אגן מפעלי הנדסה (1988) בע"מ', '511301129', 'היוזמה 33', 'אשדוד'),
    ('דיאור יבוא ושיווק בע"מ', '513105494', 'התעשייה 51', 'נשר'),
    ('כהן פור ש.א. בע"מ', '511022493', 'האורגים 12', 'חולון'),
    ('מפעל מתכת כפר מנחם בע"מ', '570043745', 'קיבוץ כפר מנחם', 'כפר מנחם'),
    ('אלקטרה מוצרי בנייה בע"מ', '511234567', 'הרכבת 5', 'ראש העין'),
    ('דלתות תייר בע"מ', '511634388', 'המלאכה 8', 'נתניה'),
    ('בניאס סחר בע"מ', '510605959', 'הברזל 3', 'תל אביב'),
    ('פולירון תעשיות בע"מ', '513498345', 'הפלדה 7', 'עכו'),
]
CUSTOMER = Party(name='מ.ש. הכהנים חומרי בניין בע"מ', company_id='515561520',
                 street='שבות רחל', city='אזה"ת שילה', zip='4483200',
                 phone='02-6507801', fax='15326507801', customer_no='1946')

PRODUCTS = [
    ('7280000075', 'מלט אפור 50 ק"ג', 'שק', 32.50),
    ('7200630020', 'ברזל זיון 12 מ"מ', "יח'", 145.00),
    ('1024400010', 'פנל לבן גג קלקר ע.100 ממ', 'מטר', 62.00),
    ('2200110034', 'בלוק פומיס 20', "יח'", 8.40),
    ('3306600021', 'טיח פנים 25 ק"ג', 'שק', 21.90),
    ('4409900112', 'צינור PVC קוטר 110', 'מטר', 18.75),
    ('5501230077', 'רשת ברזל מרותכת 6 ממ', "יח'", 96.00),
    ('6620045003', 'דבק אריחים גמיש', 'שק', 44.20),
    ('7731200019', 'איטום ביטומני 18 ל', 'פח', 189.00),
    ('8842100266', 'קרש בניה 4 מטר', "יח'", 27.60),
]
BS_NOTES = ['הנחת מזומן', 'חשבונית מס', 'זיכוי', 'תשלום שוטף', 'העברה בנקאית', '']


def _party(rng) -> Party:
    name, cid, street, city = rng.choice(SUPPLIERS)
    return Party(name=name, company_id=cid, street=street, city=city,
                 phone=f'0{rng.randint(2, 9)}-{rng.randint(6000000, 8999999)}',
                 fax=f'0{rng.randint(2, 9)}-{rng.randint(6000000, 8999999)}',
                 email='office@' + 'supplier%d.co.il' % rng.randint(1, 99),
                 vat_file_no=cid, deduction_file_no=str(rng.randint(900000000, 989999999)))


def _date(rng, year=None) -> str:
    y = year or rng.choice([2025, 2026])
    return f'{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{y}'


def _lines(rng, n, with_refs=False):
    out = []
    for _ in range(n):
        sku, desc, unit, price = rng.choice(PRODUCTS)
        li = LineItem(sku=sku, description=desc, unit=unit,
                      qty=rng.choice([1, 2, 5, 10, 20, 40, 50, 104]),
                      unit_price=round(price * rng.uniform(0.9, 1.15), 2))
        if with_refs:
            li.order_ref = f'SO{rng.choice([25, 26])}{rng.randint(0, 999999):06d}'
            if rng.random() < 0.7:
                li.shipment_ref = f'SH{rng.choice([25, 26])}{rng.randint(0, 999999):06d}'
            if rng.random() < 0.6:
                li.customer_order_ref = f'PO{rng.choice([25, 26])}{rng.randint(0, 999999):06d}'
        out.append(li)
    return out


def _allocation(rng, total):
    """מספר הקצאה — required (2026) for tax invoices with total >= 5,000 pre-VAT.
    Realistic form: a long internal ref + the 9-digit ITA allocation number."""
    if total >= 5000 and rng.random() < 0.85:
        return f'{rng.randint(10**16, 10**17 - 1)} {rng.randint(100000000, 999999999)}'
    return ''


def sample_invoice(seed: int) -> Invoice:
    rng = random.Random(('inv', seed).__repr__())
    sup = _party(rng)
    # the corpus has two families: centralized invoices carry per-line refs (tan/Priority
    # look); plain invoices carry a doc-level ref block (white/zebra look with barcode)
    centralized = rng.random() < 0.5
    style = 'tan' if centralized else 'white'
    refs_mode = 'per_line' if centralized else 'block'
    inv = Invoice(
        supplier=sup, customer=CUSTOMER,
        doc_id=(f'SI{rng.choice([25, 26])}6{rng.randint(0, 999999):06d}'
                if rng.random() < 0.7 else str(rng.randint(100000, 99999999999))),
        doc_date=_date(rng), centralized=centralized,
        details_note=('חש. מרכזת ' + rng.choice(['אפר', 'מאי', 'יונ', 'יול']) + "-25"
                      if centralized else ''),
        lines=_lines(rng, rng.randint(3, 10), with_refs=(refs_mode == 'per_line')),
        discount_pct=rng.choice([0, 0, 5, 10, 12]) if rng.random() < 0.73 else 0,
        payment_due=_date(rng, 2026), payment_terms=rng.choice(['שוטף+90', 'שוטף+60', '120', 'מזומן']),
        bank=(BankDetails(branch=f'{rng.randint(100, 999)} - עסקים',
                          account=str(rng.randint(10000000, 99999999)))
              if rng.random() < 0.51 else None),
        agent=rng.choice(['מתן אל', 'דורון אטיאס', 'נועם', '']),
        style=style, has_logo=True, has_seal=(style == 'tan'),
        has_barcode=(style == 'white'), refs_mode=refs_mode,
        printed_note=('חשבונית מפורטת לפי פריטים תמסר עפ"י דרישה' if style == 'white' and rng.random() < 0.5 else ''),
    )
    inv.delivery_note_ref = f'SH{rng.choice([25, 26])}{rng.randint(0, 999999):06d}'
    inv.delivery_note_date = _date(rng)
    if refs_mode == 'block':
        inv.doc_shipment_ref = inv.delivery_note_ref
        inv.doc_order_ref = f'SO{rng.choice([25, 26])}{rng.randint(0, 999999):06d}'
        inv.doc_customer_order_ref = f'PO{rng.choice([25, 26])}{rng.randint(0, 999999):06d}'
    inv.allocation_number = _allocation(rng, inv.total_due)
    inv.allocation_status = 'granted' if inv.allocation_number else 'none'
    return inv


def sample_order(seed: int) -> Order:
    rng = random.Random(('ord', seed).__repr__())
    return Order(
        supplier=_party(rng), customer=CUSTOMER,
        doc_id=f'PO{rng.choice([25, 26])}{rng.randint(0, 999999):06d}',
        doc_date=_date(rng),
        lines=_lines(rng, rng.randint(2, 5)),
    )


def sample_shipment(seed: int) -> ShipmentCert:
    rng = random.Random(('shp', seed).__repr__())
    fmt = rng.choice(['SH{y}{n:06d}', '02TSH{y}0{n:05d}', 'SHM{y}0{n:04d}', 'S01{y}00{n:04d}'])
    return ShipmentCert(
        supplier=_party(rng), customer=CUSTOMER,
        doc_id=fmt.format(y=rng.choice([25, 26]), n=rng.randint(0, 99999) % 100000),
        doc_date=_date(rng), print_time=f'{rng.randint(6, 17):02d}:{rng.randint(0, 59):02d}',
        delivery_address='שבות רחל - שילה',
        route=rng.choice(['רמלה לוד', 'ירושלים + דרום', 'שרון', '']),
        lines=_lines(rng, rng.randint(1, 4), with_refs=True),
        agent=rng.choice(['בן- ירושלים + דרום', 'דורון אטיאס', '']),
        gross_weight=round(rng.uniform(50, 12000), 2),
        sender_signature=rng.choice(['אירנה', 'יוסי מ.', 'מחסן ראשי']),
        print_date=_date(rng), customer_line='A', has_barcode=True,
    )


def sample_balance_sheet(seed: int) -> BalanceSheet:
    rng = random.Random(('bs', seed).__repr__())
    sup = _party(rng)
    lines, bal = [], 0.0
    for _ in range(rng.randint(2, 8)):
        debit = round(rng.uniform(100, 9000), 2) if rng.random() < 0.8 else 0.0
        credit = 0.0 if debit else round(rng.uniform(100, 4000), 2)
        lines.append(BSLine(ref_id=str(rng.randint(100000, 119999)),
                            ref2=str(rng.randint(1000, 9999)) if rng.random() < 0.5 else '',
                            doc_date=_date(rng)[:6] + _date(rng)[8:],  # DD/MM/YY
                            value_date=_date(rng)[:6] + _date(rng)[8:],
                            details=rng.choice(BS_NOTES), debit=debit, credit=credit))
    return BalanceSheet(
        supplier=sup, customer=CUSTOMER, doc_id='', doc_date=_date(rng),
        account_no=CUSTOMER.customer_no, lines=lines,
        contact_line=f'הנהש{CUSTOMER.phone}, טל: {CUSTOMER.fax}',
        weighted_payment_date=_date(rng, 2026),
    )


def sample_receipt(seed: int) -> Receipt:
    rng = random.Random(('rcp', seed).__repr__())
    method = rng.choice(['מזומן', 'המחאה', 'העברה בנקאית'])
    r = Receipt(
        supplier=_party(rng), customer=CUSTOMER,
        doc_id='', doc_date=_date(rng),
        amount=round(rng.uniform(200, 20000), 2),
        nature=rng.choice(['תשלום ע"ח חשבונית', 'מקדמה', 'תשלום שוטף']),
        payment_method=method,
    )
    if method == 'המחאה':
        r.cheque_number = str(rng.randint(1000000, 9999999))
        r.cheque_bank = 'לאומי (10)'
        r.cheque_branch = str(rng.randint(100, 999))
        r.cheque_due_date = _date(rng, 2026)
    return r


def sample_invoice_receipt(seed: int) -> InvoiceReceipt:
    """חשבונית מס קבלה — a tax invoice paid on the spot (invoice + payment block)."""
    rng = random.Random(('ir', seed).__repr__())
    method = rng.choice(['מזומן', 'כרטיס אשראי', 'העברה בנקאית', 'המחאה'])
    ir = InvoiceReceipt(
        supplier=_party(rng), customer=CUSTOMER,
        doc_id=f'IR{rng.choice([25, 26])}{rng.randint(0, 999999):06d}',
        doc_date=_date(rng),
        lines=_lines(rng, rng.randint(2, 6)),
        discount_pct=rng.choice([0, 0, 5, 10]) if rng.random() < 0.5 else 0,
        payment_due=_date(rng, 2026),
        style='white', has_logo=True, has_barcode=True, refs_mode='block',
        issued_at_shipping=True, payment_method=method,
    )
    if method == 'המחאה':
        ir.cheque_number = str(rng.randint(1000000, 9999999))
        ir.cheque_bank = 'לאומי (10)'
        ir.cheque_due_date = _date(rng, 2026)
    ir.allocation_number = _allocation(rng, ir.total_due)
    ir.allocation_status = 'granted' if ir.allocation_number else 'none'
    return ir


def sample_quote(seed: int) -> Quote:
    """הצעת מחיר — a price quote (order-shaped, valid-until + intro)."""
    rng = random.Random(('qt', seed).__repr__())
    return Quote(
        supplier=_party(rng), customer=CUSTOMER,
        doc_id=f'QT{rng.choice([25, 26])}{rng.randint(0, 999999):06d}',
        doc_date=_date(rng),
        lines=_lines(rng, rng.randint(2, 6)),
        valid_until=_date(rng, 2026),
        intro=rng.choice(['בהמשך לפנייתכם, להלן הצעת המחיר שלנו:',
                          'הצעת מחיר לאספקת חומרי בניין', 'הצעת מחיר — בתוקף ל־30 יום', '']),
    )


SAMPLERS = {'INVOICE': sample_invoice, 'INVOICE_RECEIPT': sample_invoice_receipt,
            'ORDER': sample_order, 'QUOTE': sample_quote,
            'SHIPMENT': sample_shipment, 'BALANCE_SHEET': sample_balance_sheet,
            'RECEIPT': sample_receipt}


def sample(doc_type: str, seed: int):
    return SAMPLERS[doc_type.upper()](seed)
