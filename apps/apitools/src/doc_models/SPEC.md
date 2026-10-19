# INDOX document data models — derived from the demo corpus (2026-07-08)

Source of truth for what a "realistic" document of each type contains. Derived by
surveying the full demo corpus (90 invoices, 5 orders, 15 shipment certs, 60 balance
sheets — OCR texts of 105 docs + visual reads), the KW query anchors (settings `q_*`),
and the AI extraction contract (`ai_extraction_cache` value shapes).

## The extraction contract every generated doc must satisfy

**invoice-kind AI output** (INVOICE / ORDER / SHIPMENT docs):
```json
{"AI_COMPANY_ID": "<supplier ח.פ>", "AI_DOC_ID": "<doc number>", "AI_DOC_DATE": "DD/MM/YYYY",
 "AI_DOC_AMOUNT": "1234.00", "AI_SHIPMENT_IDS": ["..."], "AI_ORDER_IDS": "...", "AI_TYPE": "INVOICE|ORDER|SHIPMENT"}
```
**bs-kind AI output** (balance sheets / גיול חובות):
```json
{"documentDate": "YYYY-MM-DD",
 "lines": [{"id": "<ref>", "date": "YYYY-MM-DD", "amount": -3533, "balanceAmount": 0, "notes": "..."}],
 "summary": {"totalLines": n, "documentTotal": n, "calculatedAmountSum": n,
             "calculatedBalanceSum": n, "totalsMatch": true, "matchType": "amount", ...}}
```
`SHORT_DOC_ID` (dedup key) = last 5 digits of the doc number.

**KW anchors the layout must place the values next to** (canonical subset of `q_*`):
- doc number: invoice → `חשבונית מס [מרכזת] <ID>` (title line); shipment → `תעודת משלוח מספר <ID>`;
  order → `הזמנת רכש` + `הזמנה מספר: <ID>` / `מס' הזמנה`.
- date: `תאריך חשבונית: <DD/MM/YY>` / `תאריך התעודה:` / `תאריך:` (validation: len 8–10, has digits).
- total: `סה"כ לתשלום` / `סך הכל כולל מע"מ` / `סה"כ מחיר` followed/preceded by the amount.
- order refs on invoices/shipments: `הזמנתכם <n>` / `הזמנה` column.
- BS detector: the phrase family `חובות שטרם שולמו` / גיול header marks BALANCE_SHEET.

## Corpus statistics (presence rates → generation probabilities)

| section | invoice (n=74) | order (n=5) | shipment (n=5) | balance (n=21) |
|---|---|---|---|---|
| doc number | 89% | 100% | 100% | 14% (account no. instead) |
| date | 97% | 100% | 100% | 95% |
| supplier ח.פ block | 81% | 100% | 80% | 10% |
| customer block (לכבוד) | 85% | 100% | 100% | 10% (חשבון line) |
| lines table (מק"ט/תיאור/כמות/מחיר) | 89% | 100% | 40% | — |
| totals + מע"מ | 84–91% | 100% | 80% | — |
| discount (הנחה) | 73% | 0% | — | — |
| bank details | 51% | 0% | — | 71% (refs) |
| order refs (הזמנתכם/הזמנה) | 49% | — | 20% | — |
| signature block | 14% | — | 100% | — |
| balance columns (חובה/זכות/יתרה) | — | — | — | 100% |

## Per-type models (see models.py)

1. **Invoice (חשבונית מס)** — supplier Party (name, ח.פ/עוסק מורשה, address, phone/fax,
   email, tax-file numbers), customer Party (לכבוד + customer company id), title
   `חשבונית מס [מרכזת] <ID> - מקור (מסמך ממוחשב)`, `תאריך חשבונית`, lines
   (sku, description, qty, unit, unit_price, line_total, order_ref?, shipment_ref?),
   totals (subtotal → הנחה % → מחיר אחרי הנחה → מע"מ 18% → סה"כ לתשלום), payment terms
   (לתשלום עד, תנאי תשלום), optional bank block, optional agent. Doc-number formats seen:
   `SI<YY>6<6d>`, plain 6–11 digits.
2. **Order / הזמנת רכש** — title `הזמנת רכש`, band `הזמנה מספר: PO<YY><6d> | תאריך: DD/MM/YYYY`,
   supplier (ספק) block + מזמין block (both with ח.פ), lines table, `סה"כ מחיר` total.
   Clean digital layout (the PO*.png family).
3. **ShipmentCert / תעודת משלוח** — supplier header, לכבוד + delivery address block,
   `תאריך התעודה` + print date/time, warehouse/route lines, title
   `תעודת משלוח מספר <ID> [- העתק]`, barcode line `*<ID>*`, lines (הזמנה SO/PO refs,
   הזמנתכם, מק"ט, תיאור, כמות, אריזות), payment terms, agent, customer numbers,
   legal paragraph (numbered), signature block (שם המקבל/חתימת המקבל), gross weight.
   Number formats: `SH<YY><6d>`, `02TSH<8d>`, `SHM<7d>`, `S<10d>`.
4. **BalanceSheet / גיול חובות פתוחים** — title + print time/date, filter ranges line
   (תאריך אסמכתא מ/עד, תאריך ערך מ/עד), account line `חשבון: <n> <customer name>`,
   contact sub-line, table (אסמ. / אסמ-2 / ת.אסמ. / ת.ערך / פרטים / חובה / זכות /
   יתרת החוב) with running balance, `תאריך תשלום משוקלל`, page footer `עמוד X מתוך Y`.

Every model exposes `extraction_truth()` returning the exact AI-contract JSON — the
model IS the ground truth, which is what makes a synthetic suite provable to 100%.
