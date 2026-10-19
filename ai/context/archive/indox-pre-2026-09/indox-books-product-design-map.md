# INDOX → "INDOX Books" — Product Design Map
### Turning a proven Israeli-compliance document engine into a morning.com-class accounting/AP SaaS

*Decision-ready. Opinionated. Every recommendation grounded in the parallel research and in what we have already proven live against Supabase Postgres.*

---

## 1. Vision & Positioning

**Thesis: INDOX is the only Israeli SMB accounting platform that closes the loop on *both* sides of the ledger — outbound issuance *and* inbound supplier-document capture — on top of a compliance core we have already built and proven, and that morning structurally cannot add without becoming a different product.**

The Israeli SMB market is defined by morning (Green Invoice): ~160k businesses, ~34% of professionals, acquired by TeamSystem for ~$150M in Dec 2024. It sets the feature bar. But morning — and every SMB peer (iCount ~60k, EZcount/Hyp, Sumit/OfficeGuy, Rivhit) — is **outbound-only**: it issues *your* documents and, at best, OCR-scans an expense receipt into a flat line item. **None of them reconcile inbound supplier documents against your own orders and deliveries.** That capability lives only in ERP territory (Priority, Hashavshevet) at ERP price and complexity.

We have inverted the usual startup risk profile. The hard, defensible, most-regulated layer is **already built and proven**:

- **doc_models** — typed Israeli doc types (INVOICE, tax-invoice, ORDER, SHIPMENT/תעודת משלוח, RECEIPT, BALANCE_SHEET/aging) + `validate_compliance()` implementing income-tax bookkeeping regs §5/§8/§9.
- **doc_gen** — realistic Hebrew RTL PDFs (logo, מסמך ממוחשב seal, barcode, מקור/העתק/טיוטה, Instruction-36 footer, per-line refs), 100% extraction-aligned.
- **doc_data** — Postgres/Supabase CRUD + lifecycle (draft→issue→sent→paid, cancel→credit-note), gapless per-type/series/tax-year numbering, immutability, מקור-once serving, SHA-256 tamper chain, audit trail, 7-year retention, consent registry.
- **LEGAL layer** — CMS/PKCS#7 digital signature (certifiable with a CA .p12), allocation-number/חשבוniות-ישראל (₪5k threshold live 1.6.2026 — landed *exactly* as we implemented it), PCN874, VAT 18%.

**The gap to a sellable morning-competitor is not compliance. It is the SaaS shell:** multi-tenancy, Customers/Items entities, payments/clearing, accountant export (מבנה-אחיד), dashboards, recurring billing, mobile, integrations.

**Positioning, stated three ways:**

- **To the freelancer/עוסק:** "Issue a compliant חשבונית מס קבלה in seconds — and never key in a supplier bill again."
- **To the importer/distributor/retailer (our beachhead):** "The only Israeli tool that matches your supplier invoices to your POs and delivery notes automatically."
- **To the accountant (רו״ח/מייצג):** "Your whole client book, with inbound reconciliation and a clean מבנה-אחיד export — the AP work morning makes you do by hand."

**Guardrail:** Do *not* re-fight outbound issuance head-on against a TeamSystem-funded 160k-business incumbent on features or price (EZcount/Sumit have genuine free tiers backed by Hyp/OfficeGuy rails — we cannot win a price war). Reach parity on the *visible demo surface*, then win on the **inbound wedge + compliance depth + accountant channel**.

---

## 2. Target Segments & Pricing

### Beachhead → expansion sequence

| Priority | Segment | Why | The hook |
|---|---|---|---|
| **1 (beachhead)** | Importers / distributors / retail with heavy supplier-invoice + delivery-note flow | Highest inbound-doc pain; where 3-way matching converts and morning/iCount are weakest. Our demo corpus already models invoice/order/shipment. | AP automation / 3-way match |
| **2 (channel multiplier)** | Accountants & bookkeeping firms (רו״ח/מייצג) | A firm drags its whole client book onto a platform. Our AP + PCN874 + audit trail is a stronger pitch to a CPA managing supplier reconciliation than to a solo freelancer. morning productized exactly this as "CPA". | Accountant portal + מבנה-אחיד + multi-client |
| **3 (volume)** | Freelancers / עוסק פטור / small עוסק מורשה | The mass market morning owns; we enter once table-stakes exist. | חשבונית מס קבלה in seconds |

### Pricing model — calibrated to morning's actual ladder

morning's tier gating tells us the true value ladder: core docs + CRM are table-stakes at the bottom (Basic ₪29/mo); **EXPENSES + PAYMENTS + API are the paid upsell** (Best ₪45/mo); higher tiers mostly raise caps (Extra ₪74, Prime ₪129). iCount is à-la-carte (~₪19.90 base + add-ons). We mirror the ladder but **make the inbound wedge the headline of the upper tiers, not a hidden add-on.**

| Tier | Price target | Included | Rationale |
|---|---|---|---|
| **Starter** | ~₪29/mo | Outbound docs (all types incl. חשבונית מס קבלה, quote, receipt), Customers, Items, allocation-number, PCN874/VAT, accountant online-sync (read + scheduled report), email send, 20 docs/mo | Undercut nobody; match morning Basic feature-for-feature so a switcher sees parity in the first 5 minutes. |
| **Pro** | ~₪49/mo | + Payments (payment links, card/Bit/wallets), auto-receipt, recurring/standing orders, expense capture, WhatsApp send, dashboards + tax-forecast, public API/webhooks | The revenue tier. Payments + expenses + API = where SMBs actually pay, per morning's own gating. |
| **AP / Business** | ~₪129–199/mo | + **Inbound supplier-document capture + PO↔delivery↔invoice 3-way matching**, suppliers entity, reconciliation exceptions, multi-currency/English docs, bulk actions | Our differentiator, priced as a premium capability morning cannot offer. This is where inbound-doc-heavy businesses land. |
| **Accountant / Firm** | Per-seat / per-client | Multi-client console, per-client roles, bulk מבנה-אחיד/חשבשבת/Rivhit export, cross-client dashboards | Distribution channel. Sold to the firm, not the owner. |

**Free/trial:** 30-day full trial (match EZcount/Sumit expectation) but **no permanent free tier** — we sell on AP capability premium, not on being a cheaper invoice generator.

---

## 3. Product Lifecycle — Document Graph, States & Tenant Lifecycle

### 3a. The Israeli sales-document graph

```
                    ┌──────────────────────────────────────────────┐
   OUTBOUND         │  הצעת מחיר (Quote)                            │
   (we issue)       │        │  accept                              │
                    │        ▼                                      │
                    │  הזמנה / הזמנת עבודה (Order)                  │
                    │        │                                      │
                    │        ▼                                      │
                    │  תעודת משלוח (Delivery note) ──┐              │
                    │        │                        │ N→1         │
                    │        ▼                        ▼             │
                    │  חשבון עסקה (Proforma) ─► חשבונית מס (Tax invoice)
                    │  דרישת תשלום (Payment req)     │              │
                    │                                ▼              │
                    │                            קבלה (Receipt)     │
                    │   ── OR single-shot ──►  חשבונית מס קבלה      │
                    │   corrections: חשבונית זיכוי (Credit, full/partial)
                    └──────────────────────────────────────────────┘
                                        ▲
                                        │ RECONCILE (our wedge)
   INBOUND          ┌──────────────────────────────────────────────┐
   (we capture)     │  Supplier invoice ⇄ our PO ⇄ supplier delivery │
                    │      3-way match → expense → PCN874 posting    │
                    └──────────────────────────────────────────────┘
```

**Conversion is line-level, not doc-level.** Two named primitives define the category (morning's help center):
- **הפקת מסמך מתוך מסמך** (1→1, e.g. quote→invoice, with skip-steps allowed).
- **הפקת מסמך המשך מתוך מספר מסמכים** (N→1, e.g. a month of delivery notes → one monthly tax invoice / ריכוז חודשי) — the high-value retainer/goods pattern.

Source lines carry **provenance refs** (we already render per-line refs in doc_gen). Partial conversion (convert some quantities, leave the rest open) and a **`converted/linked`** source state are required.

**The single most-issued document in Israel is חשבונית מס קבלה** (tax-invoice-receipt, cash-basis, one-shot). It must be the *default one-click* path, not a secondary tile.

### 3b. Document state machine (extend our proven spine minimally but correctly)

Our current `draft → issue → sent → paid` + `cancel → credit-note` is a correct spine. Add:

- **Quote:** `sent → accepted / rejected / expired → converted`
- **Invoice collection:** `partially-paid`, `overdue` (driven by receipts + due date)
- **Manual:** `מטופל / handled` flag with reopen
- **Linkage:** `converted/linked` (source consumed by a follow-on)
- **Credit:** **partial** credit note (זיכוי חלקי) from *both* חשבונית מס and קבלה — distinct from full cancellation

**Invariants preserved:** gapless per-type/series/tax-year numbering, immutability, SHA-256 tamper chain. Conversions and N→1 consolidation must be **atomic, idempotent, with source-line locking** to avoid gaps or double-consumption.

### 3c. Customer / tenant lifecycle

`onboard (business profile + עוסק type + certs) → issue → collect (payment link → auto-receipt) → reconcile (inbound match) → report (dashboards, PCN874) → accountant handoff (מבנה-אחיד + scheduled report) → renew (recurring / retention)`

---

## 4. Feature Map — Epics, Priority, Effort, Dependencies

Legend: **HAVE** = already built/proven · **SURFACE** = exists in engine, needs UI · **BUILD** = net-new. Priority M/S/C = must/should/could.

### EPIC A — Foundation & Multi-Tenancy *(nothing ships without this)*
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| Multi-tenant issuer/business entity (de-hardcode issuer; tenant-scope docs, series, signatures, retention) | must | L | BUILD | — |
| Per-tenant gapless numbering series + tax-year reset | must | M | BUILD (retrofit doc_data) | multi-tenant |
| Users, roles & permissions per tenant (owner/staff/accountant) | must | M | BUILD | multi-tenant; map to Authentik groups |
| Self-serve onboarding & business profile (עוסק type, tax ID, VAT status, logo, bank, certs) | must | M | BUILD | multi-tenant; reuses incoming-documents onboarding runbook |

### EPIC B — Foundation Entities (Customers & Items)
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| Customer entity (לקוחות: tax-id/עוסק, VAT status, contacts, default terms) | must | M/L | BUILD | multi-tenant |
| Item/product catalog (פריטים: SKU, desc, unit price, VAT class) | must | M | BUILD | multi-tenant |
| Customer import (CSV / from morning) | must | S | BUILD | Customers |
| Customer autofill by tax ID | should | S | BUILD | Customers |
| Suppliers entity (mirror of Customers, for expenses/AP) | should | S | BUILD | Customers pattern |

### EPIC C — Document Creation & Conversions
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| חשבונית מס קבלה combined doc (default one-click) | must | S | BUILD (new doc_model over engine) | Customers/Items |
| Line-level conversion engine (הפקת מסמך מתוך מסמך, skip-steps, partial, provenance, `linked` state) | must | L | BUILD | Customers/Items; lifecycle |
| Price quote (הצעת מחיר) + accept + open-tracking | must | M | BUILD | conversions |
| Credit note from issued invoice (full) | must | S | **HAVE** (surface cancel→credit) | — |
| Partial credit note (זיכוי חלקי from invoice & receipt) | should | M | BUILD | credit-note |
| N→1 consolidation (ריכוז חודשי) | should | M | BUILD | conversions; Delivery note |
| Proforma (חשבון עסקה) + payment demand (דרישת תשלום) | should | S | BUILD | — |
| Delivery note (תעודת משלוח) + Order doc types (outbound) | should | M | Partial HAVE (SHIPMENT model) | Items |
| Duplicate / copy-from-existing | should | S | BUILD | — |

### EPIC D — Payments & Collection
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| Provider-agnostic PSP abstraction + one Israeli clearer (Meshulam/Grow or Cardcom or Tranzila) | must | L | BUILD | multi-tenant |
| Payment links (branded, WhatsApp/email) | must | L | BUILD | PSP |
| Auto-receipt on payment + reconciliation | should | M | BUILD (receipt doc_gen HAVE) | PSP webhooks |
| Recurring / standing order (הוראת קבע, tokenized card, auto-issue) | should | L | BUILD | PSP tokenization |
| Auto dunning + AR aging dashboard | should | M | SURFACE (BALANCE_SHEET/aging HAVE) | Customers; delivery channels |
| Bank sync / open-banking read-side reconciliation | could | L | BUILD | last; open-banking access gates |

### EPIC E — Dashboards & Reports
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| VAT / PCN874 report in UI | must | S | **SURFACE** (PCN874 HAVE) | — |
| Business dashboard (income vs expense, open invoices, revenue goal) | should | M | BUILD | Customers + payments data |
| Receivables aging report | should | S | SURFACE (aging HAVE) | Customers balances |
| P&L / income report | should | M | BUILD | expenses |
| Tax-forecast widget (VAT + income tax + Bituach Leumi) | could | M | BUILD (differentiator) | turnover + עוסק type |
| Cashflow view | could | M | BUILD | recurring + expenses |

### EPIC F — Expenses & Inbound *(the wedge)*
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| Expense/inbound receipt capture + OCR extraction | should | M | **HAVE** (extraction pipeline) — productize | Suppliers |
| Supplier-document capture + PO↔delivery↔invoice 3-way matching UI (review/approve, discrepancy flags) | could→**flagship** | L | **HAVE in main workflow** — productize, don't rebuild | Suppliers; conversions |
| Supplier-invoice → expense → PCN874 posting | should | M | BUILD | 3-way match; PCN874 |

### EPIC G — Accountant Export & Integration
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| מבנה-אחיד / openformat export (BKMVDATA.TXT + INI.TXT) | must | M | BUILD (validate vs real חשבשבת/Rivhit import) | doc store |
| Accountant portal + scheduled auto-export/send (income+expense) | must | M | BUILD | roles; reports |
| Bookkeeping-format export (חשבשבת, Rivhit) | should | M | BUILD | מבנה-אחיד |

### EPIC H — Notifications & Delivery
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| Email delivery with open-tracking | must | S | BUILD | — |
| WhatsApp document/pay-link delivery | must | M | BUILD (leverage existing chat service) | payment links |
| Payment reminders & dunning | should | S | BUILD | balances; channels |

### EPIC I — Templates, Branding, Search, Bulk
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| Global search & filters (doc/customer/supplier/amount/date) | must | M | BUILD (Postgres FTS) | entities |
| Per-tenant templates & branding (logo/colors/footer) | should | M | SURFACE (doc_gen renders these) | multi-tenant |
| Bulk actions (multi-send/export/issue) | should | S | BUILD | list views |
| Custom fields & greeting/notes | could | S | BUILD | renderer |

### EPIC J — Multi-currency & Language
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| Multi-currency documents + FX rate frozen at issue | should | M | BUILD | Items |
| English document (Hebrew **original of record** + English **copy**) | should | M | BUILD (compliance-shaped, not naive i18n) | doc_gen |

### EPIC K — Mobile & Ecosystem
| Feature | Pri | Eff | Status | Deps |
|---|---|---|---|---|
| Responsive PWA: issue-on-the-go + camera expense scan | should | L | BUILD (camera reuses OCR) | core app |
| Public API + Webhooks (tenant-safe) | could | M | Partial HAVE (indoxApiRouter internal) | multi-tenant |
| E-commerce connectors (WooCommerce/Shopify) + Zapier/Make | could | M | BUILD | public API |
| Native iOS/Android | could | L | BUILD | PWA validated |

---

## 5. Multi-Tenant SaaS Architecture

**Decision: single shared-schema, RLS-enforced multitenancy with `tenant_id` on every business-owned row. NOT schema-per-tenant.** Postgres catalog bloat degrades past ~1–2k schemas; migrations run linearly per schema (45min+ deploys reported); `search_path` pinning breaks PgBouncer transaction pooling. All three are fatal for a many-small-business accounting SaaS.

### 5a. Tenant identity — the Authentik/BFF twist

We run a **trusted Flask BFF behind Authentik SSO**, *not* Supabase Auth issuing JWTs. So the canonical `auth.jwt() ->> 'tenant_id'` RLS pattern does **not** apply. Instead:

1. BFF authenticates the user via Authentik (existing SSO).
2. BFF resolves Authentik identity → tenant membership (Authentik group ↔ tenant).
3. BFF opens a DB transaction and sets a **transaction-scoped GUC**:
   `SELECT set_config('app.current_tenant', :tenant_id, true);`
4. RLS policies read `current_setting('app.current_tenant')`.
5. **RLS is defense-in-depth, not the only gate** — tenant identity is verified at the API boundary and propagated into every n8n/background job and every cache key (Redis keys namespaced by tenant).

### 5b. Table & policy sketch

```sql
create table tenant (
  id uuid primary key default gen_random_uuid(),
  legal_name text not null,
  tax_id text not null,                      -- ח.פ / עוסק
  osek_type text not null,                   -- morshe | patur | company
  vat_status text not null,
  authentik_group text unique not null,      -- SSO ↔ tenant binding
  created_at timestamptz default now()
);

-- every business-owned table carries tenant_id
create table document (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id),
  doc_type text not null,
  series text not null,
  tax_year int not null,
  seq bigint not null,                        -- gapless per (tenant,doc_type,series,tax_year)
  state text not null,
  sha256_prev text, sha256 text not null,     -- tamper chain, per tenant
  created_at timestamptz default now(),
  unique (tenant_id, doc_type, series, tax_year, seq)
);

alter table document enable row level security;
create policy tenant_isolation on document
  using (tenant_id = current_setting('app.current_tenant')::uuid)
  with check (tenant_id = current_setting('app.current_tenant')::uuid);
```

**Force RLS even for the table owner** (`alter table document force row level security;`) so a bug in the BFF cannot leak cross-tenant. Repeat the `tenant_id + RLS` pattern on `customer`, `item`, `supplier`, `payment`, `subscription`, `audit_log`, `ai_cache`, etc.

### 5c. Numbering series (correctness landmine)

Gapless numbering was designed single-tenant. Make the allocation atomic and tenant-scoped:

```sql
-- serialize allocation per (tenant, doc_type, series, tax_year)
create table doc_counter (
  tenant_id uuid, doc_type text, series text, tax_year int,
  next_seq bigint not null default 1,
  primary key (tenant_id, doc_type, series, tax_year)
);
-- allocate inside the issuing transaction with row lock:
--   SELECT next_seq FROM doc_counter WHERE ... FOR UPDATE;  UPDATE ... next_seq+1;
```

Conversions/consolidation allocate through the same locked counter to keep the sequence gapless and the tamper chain intact.

### 5d. Israeli-specific: certs & allocation authorization are **per legal entity, non-shareable**

- Each tenant needs its **own encrypted .p12 signing cert** (per-business tax-invoice signing). Store encrypted (envelope encryption; keys in a KMS/secret store, **never** the app DB in plaintext).
- **ITA allocation-number authorization is per-legal-entity**: each עוסק/חברה owner must personally delegate digital authorization on gov.il (ת.ז + password, after תאגיד registration). This is exactly the "accountant manages many clients" (מייצג/CPA) shape morning productized. The onboarding flow must walk each owner through the gov.il delegation and store per-tenant ITA credentials/tokens encrypted.

### 5e. Roles

| Role | Can |
|---|---|
| owner | everything for the tenant |
| staff | issue docs, view, no billing/roles |
| accountant | read + reports + exports; no issuing (or scoped) |
| firm-admin (Accountant tier) | switch across their client tenants |

Map roles to Authentik groups; the BFF derives capability from group membership, not a bespoke auth stack.

### 5f. Tenant billing, retention, backups

- **Tenant billing:** own subscription table (plan, seats, doc-cap, PSP customer token) — dogfood our own recurring engine once it exists.
- **Retention:** 7-year retention + immutability + consent registry already built — now enforced **per tenant** (retention clock per document, not global).
- **Backups:** Supabase PITR + logical per-tenant export (the מבנה-אחיד export doubles as a tenant data-portability artifact). Test cross-tenant isolation on every restore.

---

## 6. Payments & Collection Design

**Strategy: integrate a licensed Israeli clearing partner — do NOT pursue morning's ISA 2nd-tier open-banking-initiation license.** Get the feature and the monetization without the regulatory burden. Open-banking *payment initiation* is out of scope; open-banking *read-only aggregation* for reconciliation is a later "could".

### 6a. Provider-agnostic abstraction

```
PaymentProvider (interface)
  ├─ create_payment_link(doc, amount, methods[]) -> url
  ├─ tokenize_card(secure_session) -> token         # for הוראת קבע
  ├─ charge(token, amount) -> result
  ├─ refund(charge_id, amount)
  └─ webhook_verify(payload, sig) -> event

Adapters: Meshulam/Grow · Cardcom · Tranzila · (PayPlus/Z-Credit later) · Bit · Apple/Google Pay
```

First adapter: **Meshulam/Grow or Cardcom** (the pragmatic SMB-SaaS choices). Effort **L**, not S — Israeli clearing has its own tokenization/PCI/settlement quirks; scope it strictly to a partner integration.

### 6b. PCI & data invariants

- **Card data stays with the PSP.** We store only a **token**. Never card PAN in Postgres — otherwise the whole tamper/retention/audit story is undermined.
- Recurring (הוראת קבע) charges via the stored token; PCI scope stays with the PSP.

### 6c. Receipt-on-payment loop

```
Invoice/Payment-request → payment link (WhatsApp/email)
   → customer pays (card/Bit/wallet)
   → PSP webhook (verified)
   → auto-issue compliant קבלה via existing doc_gen  ✅ (we already render receipts)
   → mark invoice paid / partially-paid
   → post to AR ledger + dashboard
```

This closes the `issue → collect → paid` arc automatically and is the prerequisite for recurring's card flavor and cashflow projection. **Sequence: payments → recurring → cashflow** (hard dependency chain).

### 6d. Allocation-number interaction (do not skip)

Scheduled/recurring invoices above the ₪5k threshold need a **live allocation number at issue time**. The scheduler must use the **held-invoice / deferred-number path** and retry on ITA API failure rather than issuing an invalid document.

---

## 7. Integrations & Ecosystem

### 7a. Accountant uniform-file export (legally mandated — the system-of-record gate)
- Emit **BKMVDATA.TXT + INI.TXT** per the current ITA openformat/מבנה-אחיד spec. **Pin to the current spec version and validate against a real חשבשבת/Rivhit import** before claiming support — a stale field layout produces an export accountants reject, which is worse than none.
- Add חשבשבת and Rivhit movement/import formats.
- Scheduled monthly accountant report auto-send ("set a date, reports go to the רו״ח").

### 7b. INDOX inbound differentiator (productize, don't rebuild)
Our main n8n workflow already **captures + extracts inbound supplier documents and links PO↔delivery↔invoice**. Productize into the app:
- Review/approve UI with discrepancy flags (price, qty, missing delivery).
- 3-way match → expense → PCN874 posting.
- Market as the named **"Reconcile"** lifecycle stage — inbound + outbound in one graph — which morning/iCount structurally cannot offer.

### 7c. API & webhooks
apitools is API-native (indoxApiRouter internal). Expose a **tenant-safe** documented public API + webhooks (parity with morning Apiary / iCount / EZcount). Defer to after multi-tenancy is solid.

### 7d. E-commerce / POS
WooCommerce/Shopify/Wix connectors as **thin clients over the public API** — auto-invoice per order. Build after the API. Zapier/Make apps last.

### 7e. WhatsApp
Leverage the existing **chat** service in the deployment for document + pay-link delivery — morning's most-used channel in Israel.

---

## 8. UX — Screens, the "Issue in Seconds" Loop, Journeys

**Reality check:** many "musts" (Customers profile, dashboard, search, bulk) are as much front-end as backend. Our strength is backend; the thin Flask BFF + minimal SPA is a schedule risk and a conversion risk — Israeli SMB buyers expect the morning RTL look-and-feel. Budget real UI effort.

### 8a. Screen inventory (RTL Hebrew)
- **Dashboard** — income vs expense graph, open invoices/receivables, revenue-goal bar, tax-forecast widget.
- **Quick Issue** — the money screen (below).
- **Documents** — list + global search/filters + bulk actions.
- **Customers** — registry, per-customer ledger (כרטסת), statement, balance.
- **Items** — catalog.
- **Suppliers / Expenses / Reconcile** — inbound capture, 3-way match review.
- **Payments** — links, standing orders, dunning.
- **Reports** — PCN874/VAT, P&L, aging, cashflow, accountant export.
- **Settings** — business profile, branding/templates, certs, ITA delegation, users/roles, plan/billing.

### 8b. The "issue an invoice in seconds" core loop (benchmark: morning's "חשבונית תוך שניות")
```
[+ חשבונית מס קבלה]  ← default one-click tile
   → pick customer (autofill by tax-id) or quick-add
   → add items from catalog (1 click/row) or free line
   → amount, VAT auto, payment method
   → [הפק]  → sign (CMS) + allocation-number (if ≥₪5k) + render RTL PDF
   → send (email / WhatsApp) + optional pay-link
```
Optimize this to seconds. Everything else is secondary navigation.

### 8c. Key journeys
- **Switcher demo (first 5 min):** import customers → issue חשבונית מס קבלה → quote with open-tracking → convert quote→invoice → send WhatsApp pay-link → auto-receipt. This is exactly what a prospect judges against morning; compliance depth is invisible until this shell exists.
- **AP journey (our wedge):** supplier bill lands → auto-extracted → matched to PO + delivery → exceptions flagged → approve → posted to expenses/PCN874.
- **Accountant journey:** firm logs into multi-client console → per-client reports → scheduled מבנה-אחיד export → month-end close.
- **English/multi-currency:** original stays Hebrew (record-of-language), English **copy** generated for the overseas customer, FX rate frozen at issue, export invoice VAT-zero. Naive translation of the מקור would be a **compliance defect**.

---

## 9. QA Strategy — Parallel Cycles per Epic

**Principle: QA runs as a set of standing lanes, each shadowing a dev epic, feeding one shared release gate. Nothing merges to the release branch without its lane green.** We already have the assets to make this real: the synthetic-doc generator (`scripts/gen-unique-corpus.py`, `unique-corpus-map.json`), authoritative ground truth per doc, and CI e2e (the indox-e2e / observability publish pipeline).

### 9a. Per-epic QA lanes (run in parallel with each dev epic)
| Dev epic | Parallel QA lane | Focus |
|---|---|---|
| A Foundation/Multi-tenant | **RLS-isolation lane** | cross-tenant leak fuzzing, forced-RLS, GUC propagation into n8n jobs & Redis keys |
| B Entities | Entity-contract lane | Customer/Item CRUD, import correctness, autofill |
| C Docs/Conversions | **Numbering-invariant lane** | gapless per-tenant seq, atomic/idempotent conversions, N→1 no double-consume, tamper-chain continuity |
| D Payments | Payments lane | PSP sandbox, webhook verify, auto-receipt correctness, tokenization (no PAN in DB), refund/partial |
| E/F Reports & Inbound | Extraction-quality lane | 3-way match accuracy vs ground truth, PCN874 posting |
| G Accountant export | **מבנה-אחיד conformance lane** | validate BKMVDATA/INI against real חשבשבת/Rivhit import; spec-version pin |
| H/I/J UX/Notifications | a11y + RTL lane | RTL correctness, keyboard/a11y, WhatsApp/email delivery, open-tracking |

### 9b. Nightly compliance battery (the crown jewel)
Runs every night in CI, fully automated:
1. **Generate** a fresh synthetic corpus per doc type/source with our generator (deterministic seed → known ground truth).
2. **Issue** each through the full pipeline (sign + allocation-number stub + render).
3. **Assert** against authoritative ground truth: field-level extraction alignment, `validate_compliance()` §5/§8/§9 pass, gapless numbering, tamper-chain intact, מקור-once, PCN874 totals.
4. **Round-trip** the מבנה-אחיד export and re-import to confirm parity.
5. Publish a scorecard (reuse the existing observability publish-run pattern) with pass/fail per type/source; the bar is our existing spec: **100+/type/source COMPLETED in 10 min**.

### 9c. Security / RLS-isolation testing
- Automated **cross-tenant probe**: with tenant A's GUC set, attempt to read/write tenant B rows through every API path and every background job → must fail closed.
- Secret handling: certs/ITA creds/PSP tokens never in plaintext; static scan for PAN-in-DB.
- Authentik-group ↔ tenant binding tests (revoked membership → immediate loss of access).

### 9d. Contract tests vs the ITA API
- Run against **ITA stub in CI** on every PR; **live ITA nightly** (scoped test entity). Assert held-invoice/deferred-number path, 9-digit print, retry on failure, threshold logic (₪5k since 1.6.2026). Treat SHAAM spec drift as a monitored contract — alert on schema change.

### 9e. Load, a11y, release gating
- **Load:** replay the Sheets-rate-limit / doc-flood scenarios (per prod memory) against the multi-tenant DB; confirm numbering-counter lock contention and PSP webhook throughput hold under 100+/type/source.
- **a11y:** RTL + screen-reader + keyboard on the core loop.
- **Release gate:** a merge to the release branch requires: nightly compliance battery green + the touched epic's lane green + RLS probe green + ITA contract (stub) green. **No ✅ from a partial check** (standing memory: verify end-to-end, mark blocked steps OPEN).

---

## 10. Phased Roadmap

### Phase 0 — MVP: "Second Tenant" *(prove it's a real SaaS)*
- **Goal:** two real tenants can each issue compliant outbound docs end-to-end, isolated.
- **Epics:** A (multi-tenant + numbering + roles + onboarding), B (Customers/Items + import), C (חשבונית מס קבלה default, quote, conversions, surface credit-note), H-email, I-search, VAT/PCN874 surfaced.
- **Parallel QA:** RLS-isolation lane + Numbering-invariant lane + nightly compliance battery live from day one.
- **Exit criteria:** two tenants fully isolated (RLS probe green); issue-in-seconds loop works; per-tenant gapless numbering + tamper chain intact under the battery; customer import works; morning-parity demo (import→issue→quote→convert→send) passes.

### Phase 1 — GA: "Get Paid & Hand Off" *(revenue + switch-ability)*
- **Goal:** businesses collect payment in-app and switch off morning with their accountant's blessing.
- **Epics:** D (PSP abstraction + one clearer + payment links + auto-receipt + recurring), G (מבנה-אחיד export + accountant portal + scheduled report), E (dashboard + aging + PCN874 UI), H-WhatsApp + dunning, J (English/multi-currency).
- **Parallel QA:** Payments lane + מבנה-אחיד conformance lane + a11y/RTL lane; battery extended with round-trip export.
- **Exit criteria:** live payment → auto-receipt → paid state, PAN never in DB; recurring auto-issues with allocation-number held-path; מבנה-אחיד validated against real חשבשבת/Rivhit import; accountant can self-serve reports; ITA live contract nightly green.

### Phase 2 — Scale: "The Inbound Wedge" *(differentiate + distribute)*
- **Goal:** ship the capability morning cannot — inbound AP 3-way matching — and open the accountant/ecosystem channel.
- **Epics:** F (inbound capture + 3-way match UI + supplier→expense→PCN874 — productize existing workflow), Accountant/Firm multi-client console, K (public API + webhooks, PWA + camera scan, e-commerce connectors), E tax-forecast + cashflow, D open-banking read-side reconciliation.
- **Parallel QA:** Extraction-quality lane at scale + load lane + API contract tests; battery adds inbound-match accuracy vs ground truth.
- **Exit criteria:** 3-way match accuracy meets ground-truth bar at 100+/type/source in 10 min; firm console isolates clients (RLS); PWA issue+scan works; public API tenant-safe; tax-forecast within tolerance.

---

## 11. Top Risks & Mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Head-on outbound competition unwinnable** vs 160k-business, TeamSystem-funded morning; free floors (EZcount/Sumit) compress price. | Compete on the **inbound/AP wedge + compliance depth + accountant channel**, not price or outbound features. Guard the roadmap against morning-parity feature-race scope creep. |
| 2 | **Per-tenant numbering is a correctness landmine** — gapless per-type/series/tax-year + tamper chain designed single-tenant. | Get the schema right in the Foundation epic *before data accrues*; atomic locked counter; Numbering-invariant QA lane from day one. |
| 3 | **Payments/clearing is the largest unbuilt surface** and gates recurring/auto-receipt/cashflow; effort-L not S; PCI. | Strict PSP-partner scope (no ISA license); token-only, PAN never in DB; sequence payments→recurring→cashflow; Payments QA lane in sandbox. |
| 4 | **מבנה-אחיד / ITA spec drift** — stale layout → accountant-rejected export; SHAAM/allocation specs evolve. | Pin spec version; validate vs real חשבשבת/Rivhit import; conformance QA lane + ITA contract tests (stub PR, live nightly); treat allocation integration as ongoing maintenance. |
| 5 | **Multi-tenant retrofit / RLS leak** — issuer hardcoded; BFF-set GUC pattern is non-standard (not Supabase-Auth JWT). | Introduce tenant scoping before real data; force RLS + defense-in-depth at API boundary; propagate tenant into every n8n job & cache key; automated cross-tenant probe. |
| 6 | **Per-entity certs & ITA authorization non-shareable** — each owner must delegate on gov.il; each tenant needs its own .p12. | Onboarding walks each owner through gov.il delegation; per-tenant encrypted cert/creds in KMS; never share across tenants. |
| 7 | **Recurring × allocation-number** — scheduled ≥₪5k invoices need live allocation at issue time. | Scheduler uses held-invoice/deferred-number path + retry on ITA failure; never issue an invalid doc. |
| 8 | **Thin UI vs polished incumbents** — Israeli buyers expect morning look-and-feel; many musts are front-end-heavy. | Budget real UI effort; a11y/RTL QA lane; prioritize the issue-in-seconds loop and switcher demo polish. |
| 9 | **Conversion engine races** — N→1 consolidation / partial conversion can gap or double-consume. | Atomic, idempotent conversions with source-line locking through the shared counter; QA in Numbering-invariant lane. |
| 10 | **English/multi-currency compliance** — naive i18n corrupts the מקור. | Original stays Hebrew (record-of-language) invariant explicit; English is a generated copy; FX frozen at issue; export VAT-zero. |

---

### Bottom line
Freeze compliance scope (it's won). Ship the **Foundation → parity-demo → payments/accountant → inbound-wedge** sequence, with a **standing parallel QA battery** built on our synthetic-doc generator and CI e2e that we already have. Lead every conversation with the one sentence morning can't say: **"We do inbound too."**
---

## ADDENDUM — Deployment model correction (2026-07-08)

**This is NOT a multi-tenant SaaS.** The whole deployment is a SINGLE-BUSINESS install:
either an easy laptop Docker setup with native `app.localhost` access, or a Claude-managed
VPS where the apps run on a public domain behind Authentik. **One deployment = one business.**

Consequences that OVERRIDE §5 (Multi-Tenant Architecture) above:
- No RLS/tenancy, no per-tenant isolation, no tenant billing. The "issuer" is a SINGLETON
  `business_settings` row = THE business for this deployment.
- "Onboarding" = first-run BUSINESS SETUP (name, ח.פ/עוסק type, address, logo, VAT, signing
  cert, ITA creds, numbering start), not tenant provisioning.
- Numbering series, signing cert, and allocation authorization are simply this business's —
  the "non-shareable per legal entity" concern disappears (there's exactly one entity).
- Auth stays as-is: Authentik gates the deployment's users (owner + staff), not tenants.

**Focus now:** a complete, self-contained local morning-like business product — onboarding,
customers, items, documents, payments, reports — WITHOUT mixing in the INDOX inbound pipeline.
The inbound wedge (§7b, EPIC F) is a later, separate concern for this single-business app.
Roadmap collapses to: Onboarding+Entities → Documents/parity → Payments+Reports → (later) inbound.
