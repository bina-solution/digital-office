# Israeli business-document compliance — verified checklist → implemented features

Source: deep research 2026-07-08, every claim 3-vote verified against primary sources —
הוראות מס הכנסה (ניהול פנקסי חשבונות) תשל"ג-1973 (consolidated text, Wikisource/Nevo),
ITA circular 4/01, Instruction 36 / Annex E, and the ITA "Israel Invoice Model API
Description" v2.0 (7/2024, gov.il). Confidence high on all items below.

| # | Requirement (source) | Where implemented |
|---|---|---|
| 1 | Invoice §9(a): 9 mandatory fields — issuer name/address/ID (בדפוס), date, delivery-note no.+date (waived if issued at shipping), customer name+address (waivable retail-cash but NOT zero-rated/exempt), goods description, unit of measure, quantity, unit price, total | `Invoice` fields + `validate_compliance()` |
| 2 | קבלה §5: sequential no., issuer+ID, date, payer name/address (waivers), amount, nature/credited account, recipient signature — waived for מסמך ממוחשב; cheque: number/bank/branch/due date; one copy to payer | `Receipt` model + validator |
| 3 | תעודת משלוח §8: issuer+ID, ship date, customer (waivers), goods description (+manufacturer/serial for Appendix C goods), unit, quantity, SENDER signature; unsold-goods moves = SEPARATE number series | `ShipmentCert.sender_signature`, series support in registry |
| 4 | מסמך ממוחשב §1+§18ב: certified/secured e-signature (E-Signature Law 5761-2001) + label 'מסמך ממוחשב' conspicuous + generated from the permanent file + assessing-officer notification + prior recipient consent (recorded, retained) | render label; `doc_data.consents`; signing hook (`sign.py` — certified CA cert must be supplied; stub signature marked NON-CERTIFIED) |
| 5 | §18(a/b) numbering: strictly sequential, gapless, non-repeating within a tax year; cancelled docs marked מבוטל, never deleted | registry sequences keyed (type, series, tax_year); `cancel()` keeps row+artifact |
| 6 | Permanent file (קובץ קבוע, §1 + circular 4/01): append-only; consecutive RECORD number distinct from doc number; drafts are not 'recorded'; software must self-check numbering continuity (Instruction 36 / Annex E(5)) | registry `pk` = record no.; `verify_sequence()` + `verify_chain()`; drafts never registered |
| 7 | Output marking: מקור printed exactly ONCE (software must prevent a second מקור), all other copies העתק; temp-file output marked טיוטה and never issued; every output carries taxpayer name, output type, production date, page serial, end-of-output marker | registry `serve()` once-semantics → render label; `render(..., label=)`; Instruction-36 footer on every doc |
| 8 | Retention §25(c): keep 7y from tax-year end or 6y from filing (later); e-signed מסמך ממוחשב stored WITH its signature as part of the books; scanned-original destruction only per Appendix ו׳/ז׳ | registry never deletes; signature stored alongside artifact |
| 9 | חשבוניות ישראל (Economic Efficiency Law 2023): allocation number = precondition for customer input-VAT deduction above threshold. Thresholds pre-VAT: 25k (2024 pilot) → 20k (2025) → 10k (1.1.2026) → 5k (1.6.2026, in force) | `allocation.py`: `needs_allocation(total, date)`; Invoice.allocation_number |
| 10 | ITA API spec v2.0: save allocation number on the invoice record; PRINT it with the 9 right-most digits highlighted under 'מספר הקצאה:'; report 9-digit form in PCN874; Invoice_ID mandatory before requesting; held-invoice (substantive denial) → 4-alternative user flow | registry column + render line; `allocation_status` field (granted/held/pending/none) |

NOT covered by verified findings (flagged, not silently assumed): current VAT *rounding*
rules and the de-facto field validations of GreenInvoice/iCount. VAT rate is configured
per-document (`vat_pct`, default 18% — the rate in force since 1.1.2025); confirm before
relying on it for live billing.
