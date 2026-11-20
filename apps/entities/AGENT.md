# Operating «ישויות» (`entities`)

**Everyone the business works with, in one place** (DGO-2101): people and organizations, and the roles each holds —
customer («לקוח»), supplier («ספק»), company («חברה»: the legal record), salesperson («איש מכירות»), contact
(«איש קשר»). The business itself is not here: that is «זהות» (`GET /api/brand` of digital-assets). Documents name
their parties by an entity's id and print `party(id)`. No other app keeps a list of customers or suppliers; a
question about one is answered from here, and a change is made here.

The model (`ai/context/business-domains.md`): an entity is `person` or `organization`; its own fields are phone,
mobile, email, street, city, zip, website, notes; each role adds its pattern's fields (`./bbox entities patterns`). One
organization can be a customer and a supplier. A person `works_at` an organization (with a title); a salesperson
`handles` a customer.

## What you can do from here

```bash
./bbox entities list customer                  # one line each: id | kind | name | roles | key (ח״פ / email / phone)
./bbox entities list --q "אורן"                # search names, numbers, phones, emails, every field
./bbox entities show ent_…                     # its fields, each role's fields, its relations
./bbox entities party ent_…                    # the block a document prints (name, number, address, contact)
./bbox entities add organization "קבוצת אורן בע״מ" --role customer phone=03-0000002 \
    company.business_number=516123457 company.entity_type="חברה בע״מ" customer.billing_email=billing@oren.example
./bbox entities add person "דנה לוי" --role contact email=dana@oren.example contact.title="סמנכ״לית תפעול"
./bbox entities relate ent_<person> works_at ent_<organization> "סמנכ״לית תפעול"
./bbox entities set ent_… phone=03-0000022 customer.payment_terms="שוטף + 30"   # an empty value removes a field
./bbox entities set ent_… kind=organization     # correct a kind (the ledger makes a customer with no number a person);
                                               # refused while a role or a «works at» would no longer fit
./bbox entities role ent_… supplier bank_name="לאומי" bank_branch=800 bank_account=12345
./bbox entities history ent_…                  # who changed what, when, from what to what (a removed role's fields too)
```

From another app (a service): `GET http://entities:8999/api/entities?role=customer&q=…`, `GET
/api/entities/{id}`, `GET /api/entities/{id}/party`, `GET /api/parties?role=customer` (each as a document prints
it), `POST /api/entities`, `PUT /api/entities/{id}/roles/{role}`, with `Authorization: Bearer $ENTITIES_API_TOKEN`
and a JSON body for a change.

The documents' customers are these: the ledger's `/customers` answers from here once «ישויות» runs, and its own
old list moved here by itself the first time (each entity keeps its `ledger:cus_…` source). A customer added
from a document form is added here.

## Traps

- **Add a person or an organization only when the owner, a document or a message shows they exist.** Never invent
  a business number, a bank account or an email: an empty field is better than a guessed one (`missing`, not wrong).
- **Search before you add**: `list --q` by name, number and phone. Two records of one customer is the bug this app
  ends.
- **A document already issued is not changed by a change here** — it keeps its parties as they were. A change here
  reaches the next documents.
- **Nothing is deleted**: an entity is archived (out of every list, still answering by id, because a document may
  name it). Say «הועבר לארכיון», never «נמחק».
- **A client's own customers are not ours.** This office's «ישויות» holds this business's people and organizations;
  a client's suppliers live in the client's office (or its INDOX instance).
- The kinds of business (`company.entity_type`) are a closed list: עוסק פטור · עוסק מורשה · חברה בע״מ · שותפות ·
  עמותה. The documents read it to know whether VAT is charged.
