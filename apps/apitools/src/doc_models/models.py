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
from typing import List, Optional


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

    @property
    def total(self) -> float:
        return round(self.qty * self.unit_price, 2)


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
        return round(sum(l.total for l in self.lines), 2)

    @property
    def discount(self) -> float:
        return round(self.subtotal * self.discount_pct / 100.0, 2)

    @property
    def after_discount(self) -> float:
        return round(self.subtotal - self.discount, 2)

    @property
    def vat(self) -> float:
        return round(self.after_discount * self.vat_pct / 100.0, 2)

    @property
    def total_due(self) -> float:
        return round(self.after_discount + self.vat, 2)

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
        return round(self.paid_amount or self.total_due, 2)

    def extraction_truth(self) -> dict:
        t = super().extraction_truth()
        t['AI_TYPE'] = 'INVOICE'      # a tax invoice for VAT/allocation
        return t


@dataclass
class Order(_BaseDoc):
    DOC_TYPE = 'ORDER'
    lines: List[LineItem] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(l.total for l in self.lines), 2)

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
    intro: str = ''

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
        return round(self.debit - self.credit, 2)


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
        return round(sum(l.amount for l in self.lines), 2)

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
    if m.DOC_TYPE in ('INVOICE', 'INVOICE_RECEIPT'):
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
