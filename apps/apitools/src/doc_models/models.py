"""INDOX document data models — the ground truth a generated document is built from.

Plain dataclasses (no new deps). Each doc model exposes:
  - to_dict() / from_dict(): full JSON round-trip (the /docGen request body)
  - extraction_truth(): the AI-extraction-contract JSON this document must yield
  - short_doc_id: the last-5-digits dedup key

See SPEC.md for how these were derived from the demo corpus.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, '') else 0))


def _agorot(v: Decimal) -> float:
    """Half up to the agora, in decimal — the arithmetic the printed page uses (src/doc_gen/house/view.py), so the
    books and the page agree (DGO-2029: float round() gave 222.25 VAT where the page printed 222.26)."""
    return float(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def _last5(doc_id: str) -> str:
    digits = re.sub(r'\D', '', doc_id or '')
    return digits[-5:] if digits else ''


@dataclass
class Party:
    name: str
    company_id: str = ''            # ח.פ / עוסק מורשה (9 digits)
    street: str = ''
    city: str = ''
    zip: str = ''
    phone: str = ''
    fax: str = ''
    email: str = ''
    vat_file_no: str = ''           # מס' תיק במע"מ (usually == company_id)
    deduction_file_no: str = ''     # מס. תיק ניכויים
    customer_no: str = ''           # מס' לקוח (on the customer side)
    tax_status: str = 'murshe'      # murshe (עוסק מורשה) | patur (עוסק פטור) | company (ח.פ)
    # how the document presents the party (DGO-2029, the house style): none of these is a field of the law
    name_en: str = ''               # the name in Latin letters, under the Hebrew one
    website: str = ''
    mark: str = ''                  # 'i0' — the office's own mark — when the business has no logo of its own
    logo: str = ''                  # an SVG text or a data: URI
    signatory: str = ''             # who signs for the business, and as what
    signatory_title: str = ''
    contact_person: str = ''        # on the customer side: «לידי …»
    contact_title: str = ''


@dataclass
class LineItem:
    sku: str = ''
    description: str = ''
    qty: float = 1
    unit: str = "יח'"
    unit_price: float = 0.0
    order_ref: str = ''             # SO/PO the line came from (הזמנה)
    customer_order_ref: str = ''    # הזמנתכם
    shipment_ref: str = ''          # תעודת משלוח the line was delivered on
    packages: int = 0               # מס. אריזות (shipment certs)
    detail: str = ''                # a second, smaller line under the description (DGO-2029)

    @property
    def total(self) -> float:
        return _agorot(_d(self.qty) * _d(self.unit_price))


@dataclass
class BankDetails:
    bank: str = 'בנק לאומי (10)'
    branch: str = ''
    account: str = ''


@dataclass
class _BaseDoc:
    supplier: Party = None
    customer: Party = None
    doc_id: str = ''
    doc_date: str = ''              # DD/MM/YYYY
    # what the house style prints around the lines (DGO-2029); empty = not printed
    subject: str = ''
    notes: str = ''
    terms: List[str] = field(default_factory=list)

    @property
    def short_doc_id(self) -> str:
        return _last5(self.doc_id)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['doc_type'] = self.DOC_TYPE
        return d


@dataclass
class Invoice(_BaseDoc):
    DOC_TYPE = 'INVOICE'
    centralized: bool = False       # חשבונית מס מרכזת
    details_note: str = ''          # פרטים: ...
    delivery_note_ref: str = ''     # §9(a)(3) מספר תעודת משלוח
    delivery_note_date: str = ''
    issued_at_shipping: bool = False   # waiver for §9(a)(3)
    retail_cash_sale: bool = False     # customer-details waiver (NOT if zero-rated)
    zero_rated_or_exempt: bool = False
    allocation_number: str = ''        # מספר הקצאה (חשבוניות ישראל)
    allocation_status: str = 'none'    # none | pending | granted | held
    lines: List[LineItem] = field(default_factory=list)
    discount_pct: float = 0.0
    vat_pct: float = 18.0
    payment_due: str = ''           # לתשלום עד DD/MM/YY
    payment_terms: str = 'ש+90'
    bank: Optional[BankDetails] = None
    agent: str = ''
    # ── visual style (two distinct corpus families — see SPEC.md) ──
    style: str = 'white'            # 'white' (zebra + barcode) | 'tan' (Priority beige)
    has_logo: bool = True
    has_seal: bool = False          # round 'מסמך ממוחשב' seal (tan family)
    has_barcode: bool = False       # barcode under the title (white family)
    refs_mode: str = 'block'        # 'per_line' (תעודה/הזמנה/הזמנתכם columns) | 'block'
    doc_order_ref: str = ''         # doc-level הזמנה (block mode)
    doc_shipment_ref: str = ''      # doc-level תעודה (block mode)
    doc_customer_order_ref: str = ''  # doc-level הזמנתכם (block mode)
    printed_note: str = ''          # e.g. 'חשבונית מפורטת לפי פריטים תמסר עפ"י דרישה'

    @property
    def subtotal(self) -> float:
        return _agorot(sum((_d(l.total) for l in self.lines), Decimal(0)))

    @property
    def discount(self) -> float:
        return _agorot(_d(self.subtotal) * _d(self.discount_pct) / 100)

    @property
    def after_discount(self) -> float:
        return _agorot(_d(self.subtotal) - _d(self.discount))

    @property
    def vat(self) -> float:
        return _agorot(_d(self.after_discount) * _d(self.vat_pct) / 100)

    @property
    def total_due(self) -> float:
        return _agorot(_d(self.after_discount) + _d(self.vat))

    def extraction_truth(self) -> dict:
        return {
            'AI_COMPANY_ID': self.supplier.company_id,
            'AI_DOC_ID': self.doc_id,
            'AI_DOC_DATE': self.doc_date,
            'AI_DOC_AMOUNT': f'{self.total_due:.2f}',
            'AI_SHIPMENT_IDS': sorted({l.shipment_ref for l in self.lines if l.shipment_ref}),
            'AI_ORDER_IDS': ','.join(sorted({l.order_ref for l in self.lines if l.order_ref})),
            'AI_TYPE': 'INVOICE',
        }


@dataclass
class InvoiceReceipt(Invoice):
    """חשבונית מס קבלה — a tax invoice AND a receipt in one (the most-issued Israeli
    document): the sale and its payment recorded together. Inherits all invoice
    computation; for VAT/allocation purposes it IS a tax invoice."""
    DOC_TYPE = 'INVOICE_RECEIPT'
    payment_method: str = 'מזומן'   # מזומן | המחאה | העברה בנקאית | כרטיס אשראי
    paid_amount: float = 0.0        # 0 => full total_due
    cheque_number: str = ''
    cheque_bank: str = ''
    cheque_due_date: str = ''

    @property
    def amount_paid(self) -> float:
        return _agorot(_d(self.paid_amount or self.total_due))

    def extraction_truth(self) -> dict:
        t = super().extraction_truth()
        t['AI_TYPE'] = 'INVOICE'      # a tax invoice for VAT/allocation
        return t


@dataclass
class CreditNote(Invoice):
    """חשבונית מס זיכוי — reverses a tax invoice, whole or in part. Its own type and series (CN), never a
    «חשבונית מס» with negative prices (DGO-2029: that printed as a tax invoice): §9(ה) asks the numbers and
    dates of the invoices it credits, and the reason. The lines keep the ledger's sign — negative prices —
    so its totals, and the VAT report built from them, are negative as a credit is."""
    DOC_TYPE = 'CREDIT_NOTE'
    original_invoice: str = ''          # the number of the tax invoice it credits
    original_date: str = ''             # that invoice's date
    reason: str = ''                    # why

    def extraction_truth(self) -> dict:
        t = super().extraction_truth()
        t['AI_TYPE'] = 'CREDIT_NOTE'
        return t


class HouseDoc:
    """A document of the house catalogue that has no dataclass of its own (DGO-2029): a proposal, an
    agreement, an NDA, a work order, a payment request, a letter, a statement. It IS its dict — the shape
    src/doc_gen/house reads — with the few attributes the ledger asks of every model (the parties, the
    number, the totals) computed from it by the house's own arithmetic, so the page and the books agree."""

    def __init__(self, doc_type, **kw):
        self.DOC_TYPE = doc_type
        self.data = dict(kw)
        self.data['doc_type'] = doc_type
        for pk in ('supplier', 'customer'):
            v = kw.get(pk)
            setattr(self, pk, v if isinstance(v, Party) or v is None else Party(**{
                k: val for k, val in v.items() if k in Party.__dataclass_fields__}))
        self.doc_id = kw.get('doc_id') or ''
        self.doc_date = kw.get('doc_date') or ''
        self._t = None

    def _totals(self):
        if self._t is None:
            from src.doc_gen.house import context
            groups = context(self.to_dict()).get('groups') or []
            one = next((g for g in groups if not g['period']), None)
            self._t = one['totals'] if one else None
        return self._t

    @property
    def subtotal(self):
        t = self._totals()
        return float(t['raw_after']) if t else None

    @property
    def vat(self):
        t = self._totals()
        return float(t['raw_vat']) if t else None

    @property
    def total_due(self):
        t = self._totals()
        return float(t['raw_total']) if t else None

    @property
    def short_doc_id(self) -> str:
        return _last5(self.doc_id)

    def to_dict(self) -> dict:
        d = dict(self.data)
        d['doc_id'] = self.doc_id
        return d

    def extraction_truth(self) -> dict:
        return {'AI_COMPANY_ID': self.supplier.company_id if self.supplier else '', 'AI_DOC_ID': self.doc_id,
                'AI_DOC_DATE': self.doc_date,
                'AI_DOC_AMOUNT': f'{self.total_due:.2f}' if self.total_due is not None else '',
                'AI_SHIPMENT_IDS': [], 'AI_ORDER_IDS': '', 'AI_TYPE': self.DOC_TYPE}


#: the house types the ledger keeps as HouseDoc (their shape is the house's, see src/doc_gen/house/samples.py)
HOUSE_TYPES = ('PROPOSAL', 'SERVICE_AGREEMENT', 'NDA', 'WORK_ORDER', 'PAYMENT_REQUEST', 'LETTER', 'STATEMENT', 'REPORT')


@dataclass
class Order(_BaseDoc):
    DOC_TYPE = 'ORDER'
    lines: List[LineItem] = field(default_factory=list)
    # what the house page prints above the lines and in its chips (DGO-2029: the screen sent them and the save
    # failed — the dataclass had neither)
    intro: str = ''
    delivery_date: str = ''         # מועד אספקה
    vat_pct: float = 18.0           # the business's rate, which the house page prints its VAT at

    @property
    def total(self) -> float:
        return _agorot(sum((_d(l.total) for l in self.lines), Decimal(0)))

    def extraction_truth(self) -> dict:
        return {
            'AI_COMPANY_ID': self.supplier.company_id,
            'AI_DOC_ID': self.doc_id,
            'AI_DOC_DATE': self.doc_date,
            'AI_DOC_AMOUNT': f'{self.total:.2f}',
            'AI_SHIPMENT_IDS': [],
            'AI_ORDER_IDS': '',
            'AI_TYPE': 'ORDER',
        }


@dataclass
class Quote(Order):
    """הצעת מחיר — a price quote. Not a tax document (no allocation/legal-original
    requirement); converts into a sales document."""
    DOC_TYPE = 'QUOTE'
    valid_until: str = ''

    def extraction_truth(self) -> dict:
        t = super().extraction_truth()
        t['AI_TYPE'] = 'QUOTE'
        return t


@dataclass
class ShipmentCert(_BaseDoc):
    DOC_TYPE = 'SHIPMENT'
    copy_marker: bool = True        # "- העתק"
    print_time: str = '08:30'
    delivery_address: str = ''
    warehouse: str = 'Main, מחסן ראשי'
    route: str = ''
    lines: List[LineItem] = field(default_factory=list)
    payment_terms: str = 'ש+60'
    agent: str = ''
    gross_weight: float = 0.0
    legal_terms: bool = True
    signature_block: bool = True        # recipient block (trade custom)
    sender_signature: str = ''          # §8 mandates the SENDER's signature
    unsold_goods_move: bool = False     # §8: unsold-goods transport -> SEPARATE series
    print_date: str = ''                # תאריך הדפסה (distinct from ship date)
    customer_line: str = ''             # לקוח:: A  (route/customer code line)
    has_barcode: bool = True            # delivery notes carry a barcode
    delivery_date: str = ''             # מועד אספקה, as the house page prints it (DGO-2029)

    def extraction_truth(self) -> dict:
        return {
            'AI_COMPANY_ID': self.supplier.company_id,
            'AI_DOC_ID': self.doc_id,
            'AI_DOC_DATE': self.doc_date,
            'AI_DOC_AMOUNT': '',
            'AI_SHIPMENT_IDS': [],
            'AI_ORDER_IDS': ','.join(sorted({l.order_ref for l in self.lines if l.order_ref})),
            'AI_TYPE': 'SHIPMENT',
        }


@dataclass
class BSLine:
    ref_id: str = ''                # אסמכתא
    ref2: str = ''                  # אסמכתא-2
    doc_date: str = ''              # ת.אסמ  (DD/MM/YY)
    value_date: str = ''            # ת.ערך
    details: str = ''               # פרטים
    debit: float = 0.0              # חובה
    credit: float = 0.0             # זכות

    @property
    def amount(self) -> float:
        return _agorot(_d(self.debit) - _d(self.credit))


@dataclass
class BalanceSheet(_BaseDoc):
    DOC_TYPE = 'BALANCE_SHEET'
    print_time: str = '09:47'
    range_from: str = '01/01/80'
    range_to: str = '31/12/29'
    account_no: str = ''
    contact_line: str = ''
    lines: List[BSLine] = field(default_factory=list)
    weighted_payment_date: str = ''

    @property
    def document_total(self) -> float:
        return _agorot(sum((_d(l.amount) for l in self.lines), Decimal(0)))

    def extraction_truth(self) -> dict:
        def iso(d):
            m = re.match(r'(\d{2})/(\d{2})/(\d{2,4})', d or '')
            if not m: return d
            dd, mm, yy = m.groups()
            yy = ('20' + yy) if len(yy) == 2 else yy
            return f'{yy}-{mm}-{dd}'
        return {
            'documentDate': iso(self.doc_date),
            'lines': [{'id': l.ref_id, 'date': iso(l.doc_date), 'amount': l.amount,
                       'balanceAmount': 0, 'notes': l.details} for l in self.lines],
            'summary': {
                'totalLines': len(self.lines),
                'documentTotal': self.document_total,
                'calculatedAmountSum': self.document_total,
                'calculatedBalanceSum': 0,
                'totalsMatch': True, 'matchType': 'amount',
                'difference': 0, 'amountDifference': 0,
                'balanceDifference': -self.document_total,
            },
        }


@dataclass
class Receipt(_BaseDoc):
    """קבלה per §5 of the Bookkeeping Regulations."""
    DOC_TYPE = 'RECEIPT'
    amount: float = 0.0
    nature: str = ''                # מהות התקבול / החשבון שיזוכה
    payment_method: str = 'מזומן'   # מזומן | המחאה | העברה בנקאית | כרטיס אשראי
    cheque_number: str = ''         # §5(b) when paid by cheque/bill
    cheque_bank: str = ''
    cheque_branch: str = ''
    cheque_due_date: str = ''
    retail_cash_sale: bool = False
    computerized: bool = True       # מסמך ממוחשב -> recipient signature waived (§5(a)(7))
    recipient_signature: str = ''

    def extraction_truth(self) -> dict:
        return {
            'AI_COMPANY_ID': self.supplier.company_id,
            'AI_DOC_ID': self.doc_id,
            'AI_DOC_DATE': self.doc_date,
            'AI_DOC_AMOUNT': f'{self.amount:.2f}',
            'AI_SHIPMENT_IDS': [], 'AI_ORDER_IDS': '',
            'AI_TYPE': 'RECEIPT',
        }


def validate_compliance(m) -> list:
    """Return the list of Bookkeeping-Regulations violations for a document model.
    Empty list = compliant field-wise (see COMPLIANCE.md for the source mapping)."""
    v = []
    def need(cond, msg):
        if not cond: v.append(msg)
    sup = m.supplier
    need(sup and sup.name, 'issuer name missing')
    need(sup and sup.company_id, 'issuer registration number (ח.פ/עוסק מורשה) missing')
    need(m.doc_date, 'document date missing')
    if m.DOC_TYPE == 'CREDIT_NOTE':
        need(m.original_invoice, 'the credited invoice\'s number missing (§9(ה))')
        need(m.original_date, 'the credited invoice\'s date missing (§9(ה))')
        need(m.reason, 'the reason for the credit missing (§9(ה))')
    if m.DOC_TYPE in ('INVOICE', 'INVOICE_RECEIPT', 'CREDIT_NOTE'):
        need(sup and (sup.street or sup.city), 'issuer address missing (§9(a)(1))')
        need(m.doc_id, 'invoice number missing')
        if not m.issued_at_shipping:
            need(m.delivery_note_ref, 'delivery-note ref missing (§9(a)(3); set issued_at_shipping=True if issued at shipping stage)')
        cust_waived = m.retail_cash_sale and not m.zero_rated_or_exempt
        if not cust_waived:
            need(m.customer and m.customer.name, 'customer name missing (§9(a)(4))')
            need(m.customer and (m.customer.street or m.customer.city), 'customer address missing (§9(a)(4))')
        need(m.lines, 'no lines (§9(a)(5) goods/service description)')
        for i, l in enumerate(m.lines):
            need(l.description, f'line {i}: description missing (§9(a)(5))')
            need(l.unit, f'line {i}: unit of measure missing (§9(a)(6))')
            need(l.qty, f'line {i}: quantity missing (§9(a)(7))')
        need(m.total_due is not None, 'invoice total missing (§9(a)(9))')
    elif m.DOC_TYPE == 'RECEIPT':
        need(m.amount, 'amount received missing (§5(a)(5))')
        need(m.nature, 'nature of receipt / credited account missing (§5(a)(6))')
        if not m.retail_cash_sale:
            need(m.customer and m.customer.name, 'payer name missing (§5(a)(4))')
        if not m.computerized:
            need(m.recipient_signature, 'recipient signature missing (§5(a)(7); waived only for מסמך ממוחשב)')
        if m.payment_method == 'המחאה':
            need(m.cheque_number and m.cheque_bank, 'cheque number/bank missing (§5(b))')
    elif m.DOC_TYPE == 'SHIPMENT':
        need(m.customer and m.customer.name or getattr(m, 'retail_cash_sale', False),
             'customer name missing (§8)')
        for i, l in enumerate(m.lines):
            need(l.description, f'line {i}: goods description missing (§8)')
            need(l.qty, f'line {i}: quantity missing (§8)')
        need(m.sender_signature, "SENDER signature missing (§8 — the business/agent signs, not the customer)")
    return v


DOC_TYPES = {c.DOC_TYPE: c for c in (Invoice, InvoiceReceipt, Order, Quote, ShipmentCert, BalanceSheet, Receipt)}
#: what the ledger can hold: the corpus types above, a credit note, and the house's own types
LEDGER_TYPES = dict(DOC_TYPES, CREDIT_NOTE=CreditNote)
