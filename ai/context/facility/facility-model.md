# facility — managing a facility (a gym first): research and model map (v1)

DGO-1615 (bs106-t2). Written 2026-11-10 for the owner's pick, before any code. It is the sister of Exampleu's property
model ([../exampleu/assets-model.md](../exampleu/assets-model.md)): every entity the two share has the SAME name, fields
and rules there and here, so «one skeleton for Israeli businesses» stays one skeleton. The drivable mock and the
one-page migration note are on DGO-1615 (ci-artifacts/dgo1615/).

## 1. Sources, and how far each can be trusted

| Source | What it gave | Trust |
|---|---|---|
| bs106 (MEET-27, 2026-11-09), the machine transcript (ivrit.ai), 6:20–12:40 | the need, today's system, the price, the chips, the two offers | as heard; the other speaker worked at a gym that runs on the system heard as «פיזיקל» |
| [assets-model.md](../exampleu/assets-model.md) | the shared entities and principles | measured against Exampleu's own meeting (exu101) |
| Web, 2026-11-10 | the Fitness Centres regulations (health declaration), how check-in software decides at the door | each with its link (§ 7); the system «פיזיקל» was NOT found under that name |

## 2. What was asked, in the meeting's words

- «זה ניהול מתחם … אני יכול להוריד את זה לניהול מתחם» [6:36–6:46]; «הוא פעיל, הוא לא פעיל, הוא שילם, הוא לא שילם, מתי,
  באיזה תאריך נגמר לו … זה כמו ניהול נכסים, אותו דבר» [6:58–7:02]; «ואז יש לך צ׳יפ» [7:09].
- «אם יש לו כמה מתחמים … הוא מוסיף מתחם ואז יש לו מנויים … ויש לו ניקיון ויש לו הוצאות וחשמל, וכל מה שהולך ונהיה גנרי,
  נגיד ניהול חשבוניות או חשמל, אז זה כבר יכול להיות אפליקציה נפרדת» [8:24–8:42].
- Today: memberships in «פיזיקל», invoices in «חשבונית ירוקה» (Morning's former name; heard «החלטות ירוקה»), «וככה מפוצל
  למיליון דברים» [8:53–8:59]; «הם משלמים … 1,700 שקל בחודש» [9:35]; hostages to the system, Google, their site, their
  developer and Morning [10:04]; «פיזיקל מביאים את הצ׳יפים» [11:17]; «אתה לא יכול להגיד להם מה אתה רוצה» [12:03].
- The aim: «הכי מותאם לעסק שאפשר … ועדיין לצבור איזושהי מהות … גנרית לעסקים ישראלים … שלד שאפשר להתחיל איתה, כל חדר
  כושר» [9:04–9:18].

## 3. Principles (the property model's, unchanged, plus two)

1. **Fixed slots, derived totals.** «Active», «paid», «ends on», «inside now» are computed, never typed.
2. **Nothing is overwritten.** A freeze, a price change, a lost chip: each is a dated record.
3. **The place and the contract are separate.** A zone is the physical room or door; a membership covers one or more
   facilities and zones over dated periods (the property model's unit ↔ lease).
4. **A company holds one or more facilities**, and a facility belongs to one company.
5. **Tax documents stay in the licensed invoicing software** (Morning for this gym): the office computes the charge,
   Morning issues the invoice-receipt, and its number comes back.
6. **Every change is audited.**
7. **The door asks the record, once, at the moment of entry** (new): one rule decides (§ 5), every decision is logged
   with its reason, and the staff see the reason, not a red light.
8. **What is generic is someone else's app** (new, the owner [8:33–8:42]): invoices (Morning / my-docs), expenses and
   electricity (the shared Expense), documents (drive), tasks (Plane). The facility app keeps only what is a gym's.

## 4. The model

Types as in the property model: `money` = integer agorot, `date` ISO, `ref→X` a key.

### 4.1 Shared with the property model — the same entities (read their fields there)

| Here | In assets-model.md | Note |
|---|---|---|
| `Company`, `Holding`, `BankAccount`, `Person` | the same | the gym's company; trainers and staff are `Person` |
| `Facility` | `Property` | kind `gym` · `studio` · `pool` · `mixed`; address, local_authority, opening hours |
| `Zone` | `Unit` | the floor, a studio, the pool, the lockers; `access_controlled` when a door reads chips |
| `Member` | `Tenant` (kind `person`) | plus birth date (a minor's rule, § 4.2) and an emergency contact |
| `Membership` | `Lease` | the member's contract, over one or more facilities (`MembershipFacility` = `LeaseUnit`) |
| `MembershipChange` | `LeaseAmendment` | a freeze, a plan change, a transfer between facilities |
| `MembershipCharge` | `LeaseCharge` | kind `membership` · `registration` · `locker` · `personal_training` · `other`; basis `fixed` per period |
| `Discount` | `Discount` | a family, a soldier, a company deal |
| `Demand`, `DemandLine`, `Payment`, `DirectDebit`, `DebitRun`, `BankTxn` | the same | «הוא שילם, הוא לא שילם» is a derived arrears state, never a field |
| `Expense`, `Supplier` | the same | cleaning, electricity, rent, equipment, maintenance — per facility |
| `Document`, `Note`, `Email`, `Task`, `Alert`, `AuditEntry` | the same | |

`IndexValue` / `Indexation` are not needed (gym prices are not CPI-linked in what was said) and stay in the shared
core for the businesses that are.

### 4.2 The gym's own

- `Plan` (מסלול): id, name («חודשי», «שנתי», «כרטיסייה 10»), kind (`period` | `punch_card` | `trial` | `class_pack`),
  period_months or entries, price money, zones allowed, hours allowed (e.g. mornings only), entries_per_week (none = open),
  freeze_allowed_days. A plan is the template; a `Membership` copies its terms on the day it is signed (a later price
  change does not touch signed members).
- `Freeze` (הקפאה): membership, from, to, reason, document — the membership's end moves by the frozen days.
- `Credential` (צ׳יפ / כרטיס): id, member, kind (`rfid_tag` | `card` | `qr` | `phone`), uid (as the reader reads it),
  issued_on, deposit money, status (`active` | `lost` | `returned` | `blocked`). A member may hold several; a lost chip
  is `lost`, never deleted, so its later use is seen.
- `Reader` (קורא בדלת): facility, zone, device_id, kind (`rfid` | `qr`), direction (`in` | `in_out`).
- `AccessEvent` (כניסה): credential, reader, at, decision (`allowed` | `denied` | `override`), reason (§ 5), by
  (a staff `Person` for an override). Append-only.
- `HealthDeclaration` (הצהרת בריאות): member, kind (`declaration` | `medical_certificate`), signed_on, valid_until
  (declaration: signed_on + 2 years; certificate: accepted only if issued ≤ 3 months before), all_answers_no bool,
  minor_documents (when under 18), document. The regulations of 2015 (§ 7); the gym keeps them two years.
- `ClassSession` (שיעור), optional, for studios: zone, trainer ref→Person, starts_at, capacity; `Booking`: member,
  session, status. Not in the first build unless the gym asks.

### 4.3 What is derived, never stored

- Membership state: `trial` · `active` · `frozen` · `notice` · `expired` · `cancelled` — from its dates, its freezes
  and its changes. «מתי נגמר לו» = the end after freezes.
- Arrears: the open demands by age; «שילם / לא שילם» = no demand overdue.
- Inside now (when readers count exits) or entries today, per facility and zone.
- Per facility: active members, new and leaving this month, revenue billed and collected, expenses, and the result.

## 5. The door's rule (one function, every decision logged)

```
credential unknown or not active        → denied  «צ׳יפ לא מוכר / חסום»
membership not active on this day       → denied  «המנוי הסתיים ב־<date>» · «המנוי מוקפא עד <date>»
zone or hour not in the plan            → denied  «המסלול לא כולל <zone/hour>»
entries this week ≥ the plan's          → denied  «נוצלו <n> כניסות השבוע»
punch card with 0 entries left           → denied  «הכרטיסייה נגמרה»
health declaration missing or expired   → allowed, with an alert to the desk (the gym's choice: deny)
arrears older than the gym's grace days → allowed, with an alert (the gym's choice: deny)
otherwise                               → allowed
```

The reasons are the staff's words, in Hebrew, on the desk screen and in the member's card. An override needs a staff
member and is logged as such. Check-in systems on the market decide the same way at the door (§ 7, Zenoti).

## 6. Moving a gym off its current system (the note on the item says it to the gym)

1. What moves: members, plans, memberships with their end dates, freezes, open balances, the chips' uids, the health
   declarations, and the entry history if the current system exports it. **To ask first: what it exports, and in
   what form** (unknown for «פיזיקל»).
2. Chips: the existing chips stay when the new reader reads them (their uid is the `Credential.uid`); otherwise new
   chips (the owner: ordered abroad) and a day of handing them out.
3. Invoices stay in Morning; the office computes and sends the charge, Morning issues the document.
4. A month in parallel, then the old system is cancelled at the end of its commitment.

## 7. Outside sources (2026-11-10)

- תקנות מכוני כושר (רישוי ופיקוח) (הצהרת בריאות ותעודה רפואית), התשע״ו-2015 —
  https://melonaim.org/wp-content/uploads/2023/03/תקנות-מכוני-כושר-רישוי-ופיקוח-הצהרת-בריאות-ותעודה-רפואית-תשע-ו-2015.pdf ;
  the 2015 amendment's bill (no doctor's certificate required; the declaration instead) —
  https://fs.knesset.gov.il/13/law/13_lsr_210975.pdf . No later change was found; check before building.
- Check-in software records each entry and checks membership state and unpaid balance at the door —
  https://www.zenoti.com/thecheckin/gym-check-in-software-guide ; the five check-in forms (app, RFID, biometric,
  kiosk, desk) — https://www.glofox.com/blog/gym-check-in-system/ .
- «פיזיקל»: no Israeli gym product under that name came up in a search (only Arbox, with conflicting public prices),
  so nothing here is said about its features or exports.

## 8. Open, for the owner

- Which gym, and its own answers: plans and prices, how many facilities, readers in use, grace days, whether the door
  denies on a missing declaration or arrears.
- Pricing to the gym: the two forms said in bs106 — hours plus the AI cost of the build, «וזה שלהם» [9:42–9:57], or a
  monthly fee like today's for a year [10:58–11:09]. The owner's decision.
