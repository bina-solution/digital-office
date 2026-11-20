---
title: Entities
description: "Everyone the business works with — people and organizations — in one place, each with its roles: customer, supplier, company, salesperson, contact. Documents and the whole office take them from here."
---

## What it is

Entities (`entities`) is the one place an office defines everyone the business works with. Each entity is a
**person** or an **organization**, and holds **roles**, several at once: an organization can be our customer and our
supplier.

The business itself is not here: it is defined in [Identity](/en/apps/digital-assets/).

| Role | For | Its fields |
|---|---|---|
| Company | the legal record a document prints | legal name, business number, the kind of business (a closed list), VAT file |
| Customer | whoever we sell to | customer number, billing email, payment terms, price list, credit limit, our salesperson |
| Supplier | whoever we buy from | supplier number, bank, branch, account, deduction file, withholding and its certificate's validity, payment terms |
| Salesperson | a person who sells, ours or theirs | commission, region |
| Contact | a person at an organization | title, what they receive |

Every entity also has its own fields: phone, mobile, email, street, city, zip, website and notes. A relation links a
person to an organization ("works at", with a title) and a salesperson to a customer ("handles").

## The whole office takes it from here

- **Documents**: the ledger's customers are the customers in Entities. The first time Entities answers in an office,
  the ledger hands over its own old customers, once. A customer added from a document form is added here. An issued
  document keeps its parties as they were on the day it was issued.
- **The block a document prints** (`party`): the name, business number, tax status, address, phone, billing email
  and contact person.

## Nothing is deleted

An entity is **archived**: it leaves every list and still answers by its id, because a document may name it. Every
change is kept: who made it, when, and each field's value before and after. A role that was taken off keeps its
fields in that history.

## Who opens it

Entities is open to the office's admins. An admin changes records from the app's own screen only. A service (the
ledger, a flow) reads and writes with the app's token.

```bash
./bbox apps enable entities
./bbox run
./bbox entities list customer
./bbox entities show ent_…
./bbox entities party ent_…
```

## Where it is written

- The division of domains (identity · entities · documents): `ai/context/business-domains.md`
- The agents' brief: `apps/entities/AGENT.md`
