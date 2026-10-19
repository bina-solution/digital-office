# INDOX Companies Coverage Report

**Scope:** all `public.incoming_documents` rows with `STATUS` in (`UNKNOWN_COMPANY`, `MISSING_COMPANY_ID`), plus any row whose `COMPANY_ID` is non-empty but matches no `public.companies` row on `"מזהה 1"` / `"מזהה 2"` / `"שם ספק מפריוריטי"`. Read-only analysis — no table, workflow, or file was modified. Generated 2026-08-17.

---

## Summary

| Metric | Value |
|---|---|
| Target population (docs) | **1853** |
| — from STATUS ∈ {UNKNOWN_COMPANY, MISSING_COMPANY_ID} | 1663 |
| — from orphan COMPANY_ID on other statuses (OLD/MAX_ITERATIONS/COMPLETED/GARBAGE) | 190 |
| companies rows currently on file (instance=incoming-documents-main) | 1183 |
| **Group A — ADD** (new company candidates) | **353** candidates / **586** docs (270 named, 83 ID-only) |
| **Group B — UPDATE** (existing row, formatting/alias gap) | **1** row(s) / **6** docs |
| **Group C — UNRESOLVABLE** (this pass) | **1105** docs |
| Informational: self-identifier leakage (extraction defect, not a data gap) | 143 docs |
| Informational: extraction-miss (existing company, both OCR legs missed it) | 13 docs / 8 companies |
| **Coverage BEFORE** | 0 / 1853 (0.0%) — population is defined as currently-unresolved |
| **Coverage AFTER applying Group A (named) + Group B** | **493 / 1853 (26.6%)** |
| … + filename-matcher bonus on remaining no-ID docs | +0 docs (see note below) |
| … + if the 83 ID-only Group A candidates are manually named | +99 more docs become resolvable |

**Which live resolver consumes each fix** (per the 2026-08-17 two-point-rule base-extraction design, `BaseDocEx01`):
- Group A / Group B rows that land in **`"מזהה 1"`/`"מזהה 2"`/`"שם ספק מפריוריטי"`** are picked up by the **id-map leg** — `LOCAL_COMPANY_ID`/`AI_COMPANY_ID` → `pick()` — the next time each doc's COMPANY_ID is (re)compared, and by `NameCompanyMatchOffline`'s registry build immediately (`q_v3_company`'s `@registry_ids`).
- Group A rows also populate the **filename matcher**'s pool (`NAME Company Match (Offline)`, anchored prefix ≥5 chars off `"שם חברה"`) — this is the *only* leg that can rescue a doc that still has **no COMPANY_ID at all** (pure `MISSING_COMPANY_ID`), since the OCR/AI legs already ran once and found nothing on those. In this dataset that bonus measured **0** docs (see Methodology §6) — the no-ID remainder's filenames are almost all generic (`unknown-NNNNN.*`) or internal reports, not vendor-labelled.
- Docs already carrying a usable `COMPANY_ID`/`AI_COMPANY_ID` (the 383-doc orphan population) resolve **immediately** on the next comparison once the matching companies row exists — no re-extraction needed.
- Docs with **no candidate ID at all** (1470 `MISSING_COMPANY_ID` docs) need either a successful filename match (rare here) or a **re-run of base extraction** after Group A/B land, so a fresh AI/local OCR pass can pick up the newly-registered id — this report does not re-run extraction (read-only).

---

## Group A — ADD (proposed new `public.companies` rows)

270 candidates have a usable proposed name; 83 more have a confirmed ID but no readable name (listed separately below). Sorted by confidence, then document count. Confidence: **high** = name agrees across ≥2 independently-sourced docs (or cross-validated by both the AI leg and independent raw-OCR mining); **medium** = a single clean OCR header read, or a bare-number hit repeated across ≥2 docs; **low** = single weak OCR read or filename-only.

| # | Proposed שם חברה | מזהה 1 | Docs | Sample doc IDs | Evidence | Confidence |
|---|---|---|---|---|---|---|
| 1 | דאמוני תאורה ומסחר בע"מ | 515998094 | 24 | doc_msnpj8yjfvzz75, doc_mslztbvusurjwx, doc_msmai1du5b7vb8 | OCR header text on 1 sampled doc (of 22 docs carrying this ID) AND independently corroborated by raw OCR mining on 2 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 2 | קומנדו הנעלה והלבשה בעיימ | 517142121 | 17 | doc_msmb3btcu0yrlq, doc_msmahuw6i7hvdy, doc_msmc7ajzk4bvrt | OCR header text on 1 sampled doc (of 10 docs carrying this ID) AND independently corroborated by raw OCR mining on 7 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 3 | מעש תעשיות פלדה 2001 בע"מ | 513372060 | 13 | doc_mss7s0px50nm2b, doc_mss7dz15q3bwmp, doc_msoabafaa7onvp | OCR header text agrees across 2 sampled docs | high |
| 4 | עוסק מורשה מאוחד | 557640380 | 12 | doc_msm9dynn1092kt, doc_msm6a8ouas9sqx, doc_msmc2mitb4lau5 | OCR header text on 1 sampled doc (of 10 docs carrying this ID) AND independently corroborated by raw OCR mining on 2 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 5 | 505703609 :חשבונית מס | 512022930 | 10 | doc_msnpgj9u2h5lty, doc_msns4vevytssqm, doc_msoaw3rhkrvokg | OCR header text on 1 sampled doc (of 8 docs carrying this ID) AND independently corroborated by raw OCR mining on 2 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 6 | e-mail: person106@example.com | 513324616 | 8 | doc_msm555db48borl, doc_msm555k7v6b09j, doc_mspyfneifejhw0 | OCR header text agrees across 2 sampled docs AND independently corroborated by raw OCR mining on 2 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 7 | א . מ.ס.י 33 מנעולנות בע"מ | 517270229 | 7 | doc_msm5tkcw6pm27l, doc_msm33csowvqtk2, doc_msm33cisyxkq67 | OCR header text on 1 sampled doc (of 5 docs carrying this ID) AND independently corroborated by raw OCR mining on 2 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 8 | קפרו תעשיות בע"מ | 511414666 | 6 | doc_msm5u652qxb4yt, doc_msmoivb3t5dylx, doc_msmdq9q4x53ehd | OCR header text on 1 sampled doc (of 5 docs carrying this ID) AND independently corroborated by raw OCR mining on 1 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 9 | e-mail: bmayltdֲ@gmail.com | 514254663 | 6 | doc_mslw4fgeilvaae, doc_msoa2c5r2zu4pd, doc_mslvhdled47hk7 | OCR header text on 1 sampled doc (of 5 docs carrying this ID) AND independently corroborated by raw OCR mining on 1 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 10 | הוט מובייל בע"מ | 512615964 | 6 | doc_msqsqccsbhmf9n, doc_msm9dbq1r2euh7, doc_msng453kp0aga2 | OCR header text agrees across 2 sampled docs AND independently corroborated by raw OCR mining on 2 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 11 | מ"בע חברה | 516252475 | 5 | doc_msr480api2ymf9, doc_msnuag3zdb49sz, doc_msnalob85g10z4 | OCR header text agrees across 2 sampled docs | high |
| 12 | 30 :  תנאי תשלום- שירות לחודש יולי | 517199550 | 5 | doc_msoauaxa6el2so, doc_msr7z3n0kzctk9, doc_msiz4s8riromit | OCR header text on 1 sampled doc (of 2 docs carrying this ID) AND independently corroborated by raw OCR mining on 3 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 13 | PRISSMACER CERAMICA S L U NIF/VAT ESB | ESB12816021 | 4 | doc_msm9gx7qrw7q3s, doc_mslybck7wn324r, doc_msm561ssqino4g | OCR header text agrees across 2 sampled docs | high |
| 14 | e-mail: person107@example.com | 515181022 | 4 | doc_msnpgbogfm5aw9, doc_msnpqw09whx39w, doc_msnpfjxrfmtqlw | OCR header text agrees across 2 sampled docs | high |
| 15 | לאונאיי בע"מ | 516916954 | 4 | doc_msn7aamcy4zkgr, doc_msok4jbvbsko16, doc_msq0kwffec29q0 | OCR header text agrees across 2 sampled docs | high |
| 16 | Ner online | 318336773 | 4 | doc_msni63mwspbka3, doc_msmw0x8rla054f, doc_msoaimyk9okm5q | OCR header text agrees across 2 sampled docs AND independently corroborated by raw OCR mining on 1 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 17 | א.ש. פלסט | 511926990 | 4 | doc_msm9dn785edba6, doc_msmdum5rr6c2ig, doc_msmimu2dvfni11 | OCR header text on 1 sampled doc (of 3 docs carrying this ID) AND independently corroborated by raw OCR mining on 1 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 18 | עמותה רשומה | 580656460 | 3 | doc_msm41f6ztmkjk1, doc_msm41f87riinn2, doc_msm41f7t65pj6f | OCR header text agrees across 2 sampled docs | high |
| 19 | עוסק מורשה / / תא' הפקה / / תא' סיום | 036696003 | 2 | doc_msm4du4aqrmwni, doc_msm42muadlgm55 | OCR header text agrees across 2 sampled docs | high |
| 20 | גרניט שיווק מותגים בע"מ | 516544640 | 2 | doc_msmgdqhclgdhwu, doc_msmgdqcysc80bh | OCR header text agrees across 2 sampled docs | high |
| 21 | אבן טין בע"מ \| Tin Stone LTD | 517119533 | 2 | doc_msos62uddnguic, doc_mso1ycqv5htp07 | OCR header text agrees across 2 sampled docs | high |
| 22 | Part IVA IT N Mecc MO | IT00330200361 | 2 | doc_msm0w5s6f86cox, doc_msm0w5yf6drk15 | OCR header text agrees across 2 sampled docs | high |
| 23 | איון אנרגיה ישראל בע"מ | 516658705 | 2 | doc_msmcoc8ln2rb16, doc_msmcomweyitc5b | OCR header text agrees across 2 sampled docs | high |
| 24 | www.cloudways.com | EU528002224 | 2 | doc_msme8p1fogrxo6, doc_msm32g7ybj9q85 | OCR header text agrees across 2 sampled docs | high |
| 25 | ח.פ. - מ"בע דרך ושרותי מוסכים רשת שלמה | 512304056 | 2 | doc_msmgebikew76nl, doc_mssnthec0h24gr | OCR header text agrees across 2 sampled docs | high |
| 26 | web site: www.mds.co.il | 511509762 | 2 | doc_msmfzbnkcn8ozk, doc_msmfyr7zf8lxj5 | OCR header text agrees across 2 sampled docs | high |
| 27 | תרושקת תוכרעמ טראמס השרומ דודשא קסוע דיינsmartsys @gmail com ליימיאsmartsystemss co il רתא | 313145153 | 2 | doc_msok4hwpapetir, doc_msj1f8l7b0q9am | OCR header text on the only doc carrying this ID AND independently corroborated by raw OCR mining on 1 additional doc(s) originally at MISSING_COMPANY_ID | high |
| 28 | טלפון | 046055506 | 2 | doc_msmi16u2n81n8w, doc_msmqnblkxrvjot | raw OCR mining: 2 label-anchored + 0 bare-number hit(s) across 2 doc(s) | high |
| 29 | worker | 558019410 | 10 | doc_mslyntrwy65k7m, doc_msm3h31600yolq, doc_mso9tpd6ge94ke | OCR header text on 1 sampled doc (of 10 docs carrying this ID) | medium |
| 30 | Pasadena, CA | 911894477 | 10 | doc_msiz7trf5bztpe, doc_msmyp829zv4nid, doc_msmypr32dtjmmp | raw OCR mining: 0 label-anchored + 10 bare-number hit(s) across 10 doc(s) | medium |
| 31 | מן הישראלי | 51-201207-1 | 7 | doc_msmb3cstve9rst, doc_msm5u555tq1k8h, doc_msmai32fi916kj | OCR header text on 1 sampled doc (of 7 docs carrying this ID) | medium |
| 32 | ctrl | 515453389 | 5 | doc_msm6u7714vbptg, doc_msm336cfvzx3so, doc_msm6u5v7rwzvs0 | OCR header text on 1 sampled doc (of 5 docs carrying this ID) | medium |
| 33 | מרכז | 513354977 | 4 | doc_msmc2mz62bzqcr, doc_msmc2mjjlhjo9e, doc_msmc2me2grhjd6 | OCR header text on 1 sampled doc (of 4 docs carrying this ID) | medium |
| 34 | העתק תעודת עוסק מורשה | 517236683 | 4 | doc_msq0znhibgonw8, doc_msq0l3f2fzrnqe, doc_msq0z10v2kpjzj | OCR header text on 1 sampled doc (of 4 docs carrying this ID) | medium |
| 35 | גבאי | 514714237 | 4 | doc_msm7uic2p6cl2i, doc_msm9wr016e83zp, doc_mslzq2xjsea7jp | OCR header text on 1 sampled doc (of 4 docs carrying this ID) | medium |
| 36 | V A T ESB | ESB12004198 | 3 | doc_msmal4tl5uutsf, doc_mslybc5pg54t1s, doc_msm561llr5oh7n | OCR header text on 1 sampled doc (of 3 docs carrying this ID) | medium |
| 37 | וסק מורשה | 511441388 | 3 | doc_msqrs9ooqs442p, doc_mss6vp8j1fyct4, doc_msqry2vdr56wvd | OCR header text on 1 sampled doc (of 3 docs carrying this ID) | medium |
| 38 | web site: www.ysteel.co.il | 520039256 | 3 | doc_mso6c1ysufwzvq, doc_msm6flafb3kxe5, doc_msm1d0a1vg5yq5 | OCR header text on 1 sampled doc (of 3 docs carrying this ID) | medium |
| 39 | אגש"ח בע"מ | 557656139 | 3 | doc_mspytg2oyz0ijp, doc_msob2acywbyimj, doc_msq0nw8qflmsbe | OCR header text on 1 sampled doc (of 3 docs carrying this ID) | medium |
| 40 | הדפסת תעודת משלוח - מקובץ | 557684834 | 3 | doc_msmc3ig7nx0did, doc_msm9hdh0qj6wdu, doc_msm69e7jec4csv | OCR header text on 1 sampled doc (of 3 docs carrying this ID) | medium |
| 41 | F ביצענו התאמה לפריטים הבאים עם מסמך מספר | 110000017 | 3 | doc_msmuxpgxgy4xmo, doc_msmuxtd9z5ijvi, doc_msptyteiv87238 | raw OCR mining: 0 label-anchored + 3 bare-number hit(s) across 3 doc(s) | medium |
| 42 | שיכר SHEICHIAR | 513676106 | 2 | doc_msmalkbjqby24x, doc_msm5ur161swvtu | OCR header text on 1 sampled doc (of 2 docs carrying this ID) | medium |
| 43 | סניף מנפיק : שפלה | 514583558 | 2 | doc_msmfdxnqoy53ws, doc_msoax5c9zv4pf4 | OCR header text on 1 sampled doc (of 2 docs carrying this ID) | medium |
| 44 | טלפון פקס | 514971464 | 2 | doc_msm28kua8vcyme, doc_msly5kaveq03s6 | OCR header text on 1 sampled doc (of 2 docs carrying this ID) | medium |
| 45 | C F E N DI SCRIZIONE REG, IMPR DI MO | 00611410374 | 2 | doc_msm9gxxn1niwlt, doc_msm564txp5zg43 | OCR header text on 1 sampled doc (of 2 docs carrying this ID) | medium |
| 46 | (דף מספר )( ) עוסק מורשה | 511851248 | 2 | doc_msmc2s60pbpfby, doc_msmc2s6tzy5u8c | OCR header text on 1 sampled doc (of 2 docs carrying this ID) | medium |
| 47 | עוסק מורשה מכן | 513942185 | 2 | doc_msojz0udtjmbh0, doc_msm7uu7qj4ywku | OCR header text on 1 sampled doc (of 2 docs carrying this ID) | medium |
| 48 | 1  מתוך1   \|  עמוד50197   \|  חשבונית מס11:11 26/04/2026 הופק ב | 516285996 | 2 | doc_msmcolyfzxuf31, doc_msqww0f6q5bzrb | OCR header text on 1 sampled doc (of 2 docs carrying this ID) | medium |
| 49 | קבוצת נגב בע"מ | 557288644 | 2 | doc_msobd2v7s3zx60, doc_msofba0v48ebnq | OCR header text on 1 sampled doc (of 2 docs carrying this ID) | medium |
| 50 | pupaqou | 15672863 | 2 | 1779972261941fm31oh, doc_msmi19iadjj5e7 | OCR header text on 1 sampled doc (of 2 docs carrying this ID) | medium |
| 51 | ()עותק | 202626640 | 2 | doc_msovr1dwrehijy, doc_msovr3tktuy0aa | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | medium |
| 52 |  ʺʥʫʩʠʺʸʷʡʺʷʬʧʮʬʺʥʰʴʬʯʺʩʰʭʩʸʥʸʩʡʬ | 036533615 | 2 | doc_msmdu41zpzgved, doc_msmex0km8130eu | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | medium |
| 53 | חשבוניות פתוחות- סטאטוס מצב לקוח | 320001072 | 2 | doc_msmqlvco8l6dlj, doc_msnsb6mzktxjvo | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | medium |
| 54 | תאריך חשבונית | 261009546 | 2 | doc_msmkgsy5dsmjp0, doc_msq0fhmjuadxpj | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | medium |
| 55 | * הודפס על ידי רמות סוכנויות ביטוח בע"מ | 510999154 | 2 | doc_msmog820eckpai, doc_msmoga8935rb1w | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | medium |
| 56 | F ביצענו התאמה לפריטים הבאים עם מסמך מספר | 110000016 | 2 | doc_msmj2bdy8fdbbq, doc_msmj2k5lvdh5kj | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | medium |
| 57 | e mail shmulik s @ b e zeqint net | 039300641 | 2 | doc_msmypxks3td0bq, doc_msmys1lm3c22td | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | medium |
| 58 | Plassim Infrastructures Ltd. | 106132113 | 2 | doc_msmco7z1lr9ahq, doc_msmxmrexajgz05 | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | medium |
| 59 | F ביצענו התאמה לפריטים הבאים עם מסמך מספר | 110000018 | 2 | doc_msm9wsb295vr51, doc_msnhyd0dvnj2am | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | medium |
| 60 | 1  מתוך1   \|  עמוד50071   \|  חשבונית מס18:16 12/08/2026 הופק ב | 516737780 | 1 | doc_msq97fs9vq9qgo | OCR header text on the only doc carrying this ID | medium |
| 61 | 2 מתוך 1   \|  עמוד1046   \|  חשבונית מס / קבלה19:04 25/01/2026 הופק ב | 061271557 | 1 | doc_msmdox9sz3h1ym | OCR header text on the only doc carrying this ID | medium |
| 62 | מע"מ+ סה"כ | 514153584 | 1 | doc_msowgr8oly35an | OCR header text on the only doc carrying this ID | medium |
| 63 | דואר נע גרנות 3881100 • עוסק מורשה מס' 570047142 | 570047142 | 1 | doc_msmbnjg0fj8ygq | OCR header text on the only doc carrying this ID | medium |
| 64 | ארגנטולס בע"מ | 510528714 | 1 | doc_msmj8j5uzujg5u | OCR header text on the only doc carrying this ID | medium |
| 65 | מ"בע דפוס פתרונות ראש | 515210144 | 1 | doc_msmco8u473dkck | OCR header text on the only doc carrying this ID | medium |
| 66 | גרבלי זוהר חפציבה | 203172754 | 1 | doc_msm32fdxojl1y3 | OCR header text on the only doc carrying this ID | medium |
| 67 | ארד אמיליו בע"מ | 515078574 | 1 | doc_msqdzil68b3ci5 | OCR header text on the only doc carrying this ID | medium |
| 68 | CODICE IDENTIFICATIVO IT | IT01024300368 | 1 | doc_msm9gxspgm2wck | OCR header text on the only doc carrying this ID | medium |
| 69 | מוסך המרכבה (2004) בע"מ | 513560797 | 1 | doc_msmnjmts8acelz | OCR header text on the only doc carrying this ID | medium |
| 70 | לכבוד: | 022612691 | 1 | doc_msq3c9q52trplh | OCR header text on the only doc carrying this ID | medium |
| 71 | HALLON CERAMICAS, S.L.U. inscrita en el Reg. Mercantil de Castellon, de recha 27-06-2019, al lomo 1U33, Libro 597, Follo 4, Hoja CS 2609 - Inscripcion 5b - CI.F. B-12008272 | B-12008272 | 1 | doc_msm6tvrlcny6qe | OCR header text on the only doc carrying this ID | medium |
| 72 | בסייד | 308944198 | 1 | doc_msmcom6t5lnek1 | OCR header text on the only doc carrying this ID | medium |
| 73 | תעודת משלות | 570038168 | 1 | doc_msm7vdazhzexix | OCR header text on the only doc carrying this ID | medium |
| 74 | חשבונית זו מהווה אחריות שנה על המוצר אותו רכשת בחברתנו ע"י תקנון היבואן א. אברהמי | 205651987 | 1 | doc_msr0dkv062qwp2 | OCR header text on the only doc carrying this ID | medium |
| 75 | a ונם ו וו בדורנם | 562197129 | 1 | doc_mshfiyxbt5qckt | OCR header text on the only doc carrying this ID | medium |
| 76 | פז שמנים וכימיקלים (שיווק ומסחר) בע"מ \| מספר חברה \| עוסק מורשה | 511892085 | 1 | doc_msmj8gesgf18sv | OCR header text on the only doc carrying this ID | medium |
| 77 | אמוץ יבוא ושיווק בע''מ | 515757565 | 1 | doc_mss1emowhrul2o | OCR header text on the only doc carrying this ID | medium |
| 78 | ח פ מרכז שרות | 511171852 | 1 | doc_mslynvy2vs3she | OCR header text on the only doc carrying this ID | medium |
| 79 | פרץ הבית לקבלן ביתר עלית בעמ | 516406113 | 1 | doc_msmcob0lp9hw2u | OCR header text on the only doc carrying this ID | medium |
| 80 | מסמך זה הופק בתוכנה "בקלות כפולה" | 513448407 | 1 | doc_msqwob4cm8z08a | OCR header text on the only doc carrying this ID | medium |
| 81 | web site: https://www.sri.org.il/he/Home | 580072965 | 1 | doc_msmedujppvz6wf | OCR header text on the only doc carrying this ID | medium |
| 82 | תאריך תעודה! | 513293746 | 1 | doc_msme8jv2oacf2u | OCR header text on the only doc carrying this ID | medium |
| 83 | מפגש התאומים | 300202264 | 1 | doc_msm5pttuxoq369 | OCR header text on the only doc carrying this ID | medium |
| 84 | C I F ES A | A-03108669 | 1 | doc_msm33yygtirjro | OCR header text on the only doc carrying this ID | medium |
| 85 | التاريخ | 562191833 | 1 | doc_msojz0vcpq005w | OCR header text on the only doc carrying this ID | medium |
| 86 | קבוצת זיקה בע"מ | 557871696 | 1 | doc_msojzesgxszevu | OCR header text on the only doc carrying this ID | medium |
| 87 | פנים עיצוב -דוד בן טלי | 038012456 | 1 | doc_msmx2a664xzssd | OCR header text on the only doc carrying this ID | medium |
| 88 | לכבוד: | 558327417 | 1 | doc_msm95868cwabn3 | OCR header text on the only doc carrying this ID | medium |
| 89 | N I F A | A12315917 | 1 | doc_msm9gxdutb7tvi | OCR header text on the only doc carrying this ID | medium |
| 90 | C I F ES A | ES A-03108669 | 1 | doc_msm565upbp5xvb | OCR header text on the only doc carrying this ID | medium |
| 91 | in una p | 557653847 | 1 | doc_msm5qjrq127le1 | OCR header text on the only doc carrying this ID | medium |
| 92 | מ"בע 1997 ובניו פילו | 512426685 | 1 | doc_msmcoofpjexif9 | OCR header text on the only doc carrying this ID | medium |
| 93 | ( בע"מ ) סלם יעקב ובניו ע מ | 512090119 | 1 | doc_msmdos6l7ktqc4 | OCR header text on the only doc carrying this ID | medium |
| 94 | י \| תיק דיווח מע"מ | 558187274 | 1 | doc_msqq64aphms3bs | OCR header text on the only doc carrying this ID | medium |
| 95 | הופק ע"י חשבשבת ERP מסמך ממוחשב | 086655789 | 1 | doc_msmk96f3ctsd5c | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 96 | טלפון פקס | 026792037 | 1 | doc_msi40x47gjn29a | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 97 | מס לקוח | 768132105 | 1 | doc_msm6ub3zwxfmm8 | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 98 | אומנות השולחן | 058105677 | 1 | doc_mslmdww7f4hdqt | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 99 | 554354  , מס' חשבון028 ( , סניף31) פרטי חשבון: בנק הבינלאומי | 515899623 | 1 | doc_msfzc418zeeykj | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 100 | מ.מוריס בע"מ | 516695954 | 1 | doc_mslmdazevhzq62 | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 101 | טורנדו מוצרי צריכה בע"מ | 039011500 | 1 | doc_msofnnkuah1zok | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 102 | web site: | 089255414 | 1 | doc_msok5rtq85j69v | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 103 | יציל פיננסים בע"מ | 558180592 | 1 | doc_msoa2blwif79gb | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 104 | טלפון , פקס | 088566506 | 1 | doc_msmml28fs1r7fl | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 105 | "ס אגש"ח בע"מ | 046007001 | 1 | doc_msmorok9bvhbws | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 106 | דרך השלום , תד , נשר \| טלפון \| פקס | 048211429 | 1 | doc_msmik98o3ldu6v | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) | medium |
| 107 | ם נרספ po ניתן לפנות | 098925666 | 6 | doc_mshq045is4ymr6, doc_mshwn56oh2ivb6, doc_mshxw6gvecpc02 | raw OCR mining: 0 label-anchored + 6 bare-number hit(s) across 6 doc(s) | low |
| 108 | lea@nogaeinat co il | 820132172 | 3 | doc_msmed8p0rru3h5, doc_msmogjeu56tlzw, doc_msns3fa888dl3s | raw OCR mining: 0 label-anchored + 3 bare-number hit(s) across 3 doc(s) | low |
| 109 | PACKING LIST | 225248094 | 3 | doc_msmymlbg6sbmrp, doc_msmyn2hpftb3x2, doc_msmyoe26gyiwse | raw OCR mining: 0 label-anchored + 3 bare-number hit(s) across 3 doc(s) | low |
| 110 | בי גי-07780 | 514291416 | 2 | doc_msm5u20krneyye, doc_msrfmt12tvnb3f | filename fallback only (OCR header unreadable/unavailable) | low |
| 111 | לסה ויז'ן-02139 | 516664950 | 2 | 1776405937624m68s8, 17738429303612vjwrf | filename fallback only (OCR header unreadable/unavailable) | low |
| 112 | מס תיק ניכויים | 943288662 | 2 | doc_mshvagh3lym4pc, doc_mshxw6ms9zge7f | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | low |
| 113 | OR \| \| קבל — ge ה ₪ קנה קבל מתנה / Design Your Choice ספןס"מ \| \| \| | 039629353 | 2 | doc_mshtlra6anslz7, doc_msmuxkelwtgnvj | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | low |
| 114 | ח.נ משקאות בע מ | 168060266 | 2 | doc_mshr7pfpfdl5nt, doc_mshvb1dveuwxj3 | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | low |
| 115 | רשיון נהיגה DRIVING LICENCE | 214253072 | 2 | doc_msmdttnq99oa6f, doc_msmi5frf6itjrj | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | low |
| 116 | רשיון נהיגה DRIVING LICENCE | 328181672 | 2 | doc_msmyplmgpkim4d, doc_msmyrczzq33ywl | raw OCR mining: 0 label-anchored + 2 bare-number hit(s) across 2 doc(s) | low |
| 117 | מיכאל הום דיזיין-05316 | 514616923 | 1 | doc_msmgiswtxd35jp | filename fallback only (OCR header unreadable/unavailable) | low |
| 118 | uz9l3e95vuf | 510942007 | 1 | doc_mss1duovhdmwip | filename fallback only (OCR header unreadable/unavailable) | low |
| 119 | טרנדי טויס-05088 | 515142464 | 1 | doc_msmflmmik8r1ne | filename fallback only (OCR header unreadable/unavailable) | low |
| 120 | nv2rc18mhpi | 510339575 | 1 | doc_msm79z1p5xc46z | filename fallback only (OCR header unreadable/unavailable) | low |
| 121 | אלרם-unknown | 512705482 | 1 | doc_msm34ty32sx6yf | filename fallback only (OCR header unreadable/unavailable) | low |
| 122 | vt22i2lp031 | 510931534 | 1 | doc_mspxy6xowhzmp2 | filename fallback only (OCR header unreadable/unavailable) | low |
| 123 | אשדוד סחר-78100 | 511061560 | 1 | doc_msoabpp4mgbih6 | filename fallback only (OCR header unreadable/unavailable) | low |
| 124 | אבני סלע 28216 | 515744453 | 1 | doc_msqejwi2e19hbr | filename fallback only (OCR header unreadable/unavailable) | low |
| 125 | jn9nm14get2 | 510425585 | 1 | doc_mspxywb0b3t73d | filename fallback only (OCR header unreadable/unavailable) | low |
| 126 | General Ledger_20260701_101442 | 514071646 | 1 | doc_msoaug1ng7zq7x | filename fallback only (OCR header unreadable/unavailable) | low |
| 127 | גולן פלסטיק-unknown | 513029875 | 1 | doc_msm2zogpnzwlin | filename fallback only (OCR header unreadable/unavailable) | low |
| 128 | yzxtkd6dy9b | 515233158 | 1 | doc_msnam9av02lz3k | filename fallback only (OCR header unreadable/unavailable) | low |
| 129 | Invoice-8D22EF5E-0002 | 61-1797223 | 1 | doc_msmzqr9u2dgxrs | filename fallback only (OCR header unreadable/unavailable) | low |
| 130 | קיסנר-00861 | 512711252 | 1 | doc_msmff5nl0ti2zx | filename fallback only (OCR header unreadable/unavailable) | low |
| 131 | ep2y70pxz5p | 570046129 | 1 | doc_msnubx3oeu3u7i | filename fallback only (OCR header unreadable/unavailable) | low |
| 132 | חשבונית_מס_קבלה_121 | 308475789 | 1 | doc_mspzcbnoousqdl | filename fallback only (OCR header unreadable/unavailable) | low |
| 133 | icibp4prhnl | 510229975 | 1 | doc_mso9sna7u7ggiw | filename fallback only (OCR header unreadable/unavailable) | low |
| 134 | tiny.txt | 513134988 | 1 | doc_mshr02nwcs5lnj | filename fallback only (OCR header unreadable/unavailable) | low |
| 135 | איטונג-93581 | 557586161 | 1 | doc_msmgduu1fytsz5 | filename fallback only (OCR header unreadable/unavailable) | low |
| 136 | אשדוד סחר-78149 | 511851566 | 1 | doc_mspg5btp1b5lq3 | filename fallback only (OCR header unreadable/unavailable) | low |
| 137 | תסקיר בדיקת : אביזרי ע"פ | 145627170 | 1 | doc_msovquhjn83fb9 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 138 | כתובת: | 792930480 | 1 | doc_msm9hcu9pd8oz9 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 139 | מפרט )דף רשימה( לפוליסה לביטוח ציוד מכני הנדסי | 700000000 | 1 | doc_msmw1gv09svv2n | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 140 | Your F | 626333165 | 1 | doc_msm6u5g7dhx9ot | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 141 | ז שמבוטל עם בטעות חן | 714768799 | 1 | doc_msoauns6qcw2hx | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 142 | מ ר פסמ | 201069721 | 1 | doc_mspxs525p47q2l | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 143 | לתאום התקנה (תיאום התקנות מתבצע בימי חמישי בלבד) | 035544720 | 1 | doc_msrxovz56zq67t | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 144 | מספר / | 185664887 | 1 | doc_msn9j5kw62cxnd | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 145 | עמוד1 | 112000019 | 1 | doc_msmuvo9142o5uh | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 146 | מספר תעודה CR | 267000323 | 1 | 4285570545qmmoo | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 147 | משרד \| מכירות | 086408517 | 1 | doc_mshwvrw2uklj33 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 148 | Argentools Ltd. | 269000232 | 1 | doc_msj1df2pmy5o0k | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 149 | איתור לפני שידור איתור איתור עסקאות טוקנים / / תשלום / / *** *** | 202611249 | 1 | doc_msj059kn5lzct4 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 150 | ד נ מזרח בנימין | 029700603 | 1 | doc_msm91ipvxw56cx | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 151 | לקוח | 911019555 | 1 | doc_msj1fe7ativtuz | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 152 | ה FD אשראי מספרכם \|\| אזור מרכז \| גדולה ana מסמך מקורו FD בשלמותה TERT ות אפוקסי ל שבר במקלחונים במראות ובכיזרים os mo \|\| המקלחון ביתי בלבד opr ליציאת ארונות ע"י מתקין re kd Bouny ו TUR | 260084451 | 1 | doc_msi417dzqhdlq6 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 153 | ₪ Viele x | 028018833 | 1 | doc_msj20brlw0w8kv | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 154 | מ"בע מים מערכות ת.ל.י.ש | 515919819 | 1 | doc_msllydrfn00mjv | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 155 | רשת אקססוריז ויצירה בע"א | 515459774 | 1 | doc_msmco834rk1yx0 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 156 | הדפסת תעודת כזו. | 080656151 | 1 | doc_msptzm26y8m0xy | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 157 | RWH/ משלוח ‘vn | 122606813 | 1 | doc_mshrk1gfonoob1 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 158 | חשבונית מס IN מקור | 260005400 | 1 | doc_msm6fmg2vejwfi | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 159 | :מספר תסקיר134571/155589הרמה-תסקיר בדיקה וניסוי מכונות | 468991281 | 1 | doc_msiz7uu1xwjv6w | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 160 | מנעול אופניים מספרים ס"מ | 590522152 | 1 | doc_mslzpq5qmr015d | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 161 | תאריך לידה של הנהג מספר רשיון נהיגה של הנהג | 198119302 | 1 | doc_msj16htoj7pvi5 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 162 | KOL TIMBER LTD. | 269000193 | 1 | doc_msmqlejw3eakan | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 163 | מוע"ימ מס" TIS מורשיה Dow | 010846061 | 1 | doc_mslmcrxlxdizh1 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 164 | איש קשר | 206008790 | 1 | doc_msm1oav5up3c1u | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 165 | AE2083WH | 122313456 | 1 | doc_msmeebq10zrc5y | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 166 | תוא גישהל רשפאנו לכל שאלהטנרטניאה רתאב ןופלטב תואבה םיכרדב הרהבהו | 057771630 | 1 | doc_mspg45gz8k3s1d | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 167 | 347667067   מספר חשבון חוזה | 347667067 | 1 | doc_msmi5ge3g16l78 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 168 | 'דוח שירות מס313323 | 202618713 | 1 | doc_msmohurq33ikz0 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 169 | מאייד | 020000012 | 1 | doc_mshq048jxuz6xm | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 170 | לפתיחת תביעה שלא בהסדר ולמשלוח מסמכים נוספים _t prat@menora co il yn או יקס שמספרד | 035663969 | 1 | doc_msj1fewe2jyg2k | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 171 | רשומון יבוא | 430646703 | 1 | doc_msmfb96qie3r6s | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 172 | סוכן <person108@example.com> | 330330170 | 1 | doc_msoff5nuokqipr | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 173 | לינוי לורבר | 039116060 | 1 | doc_msiz79hnm4ripi | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 174 | SUNDECK | 000021602 | 1 | doc_msm481bdi1lonb | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 175 | / / הודפס ע'י בבית נכסים** ** שולם | 165703261 | 1 | doc_msmdpsp3j6q4wi | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 176 | Gelem Metal & Plastic 2000 Ltd. | 256016463 | 1 | doc_msqwo7n5x368ud | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 177 | PIU INOUL | 052786602 | 1 | doc_msovvmmrgxip7w | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 178 | מסר מעלקח | 615501620 | 1 | doc_msmb0eckp7338y | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 179 | / מועד עליה לכבישZCFC C R | 557864022 | 1 | doc_msnqj8scwxlqmr | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 180 | מ"ל אקווהפלסט לעץ (טיק) בשפופרת | 611001916 | 1 | doc_msr4gq5myzru06 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 181 | מרכז שורות ארצי | 089575612 | 1 | doc_msi33hw060i4oh | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 182 | ILS , RV | 604122025 | 1 | doc_msmwaejrqe9tpm | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 183 | טסדפון \| | 039230331 | 1 | doc_mshxuu79p6p0ki | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 184 | רישיון נהיגה1912524 | 191252402 | 1 | doc_msnngvg6145dq5 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 185 | service@nyga co il מייל | 036157701 | 1 | doc_msi5gzbyx4trfz | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 186 | 348265792   מספר חשבון חוזה | 348265792 | 1 | doc_msmi5g2n1c231p | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 187 | inbal aviram designs and construction ltd. | 266000013 | 1 | doc_msmwaz3ma9uycn | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 188 | לבירורים לגבי החשבונית/תשלום באשראי/דיווחי תנועה | 039081111 | 1 | doc_msmpsn99rnp6d8 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 189 | דף מתוך | 557658060 | 1 | doc_msm3p6a6b9tioe | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 190 | דוחות של אימון בעולם כדי העמדה מס' ספק משהב"ט | 832747716 | 1 | doc_msm3jjfb3eurbv | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 191 | MESH SPACiNG * | 204954330 | 1 | doc_msoa2gwygmcru2 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 192 | Traditional Blue | 182569128 | 1 | doc_msm3j6w3swhu8m | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 193 | 505673122 :חשבונית מס | 505673122 | 1 | doc_msmxuxu3s3ot0c | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 194 | עמוד: | 127032012 | 1 | doc_msnrp20iltm68a | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 195 | TERMOKIR INDUSTRIES (1980) LTD | 442001030 | 1 | doc_msn3p4ce07kdnl | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 196 | 505637313 :חשבונית מס | 505637313 | 1 | doc_msmjtgivbsocja | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 197 | / / הודפס ע'י בבית נכסים** ** שולם | 105417264 | 1 | doc_msmk8hr2zqr7uu | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 198 | / מועד עליה לכבישZCFC C P | 554511962 | 1 | doc_msnhwznuvmmgjh | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 199 | IL Local שחר מדפי פיוזד סט | 415040004 | 1 | doc_msojlkedogcafd | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 200 | web site: http://www.saltech.co.il | 035566474 | 1 | doc_msm3j57mev8j9j | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 201 | ehud | 304255192 | 1 | doc_msofe3iew4kt48 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 202 | בקרו באתר שלנו | 717272313 | 1 | doc_msi312bxohz5j9 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 203 | / " לצביעה כללית אורך שיער | 613153866 | 1 | doc_msq0fc7lvthzhu | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 204 | mo וסט qual au, \| tel Tr, fQ ן te LIGA WIV LHO ucthL re ui א ma תס VTL, [AS vou TALL אל נוי אספאוא Ty TORT ERIE CTALIU © סש סש LCE UTN LU ם, וו שש ₪ LL NLU ag’ % ₪ יי unulL NoGdu // / שו TAN uty הווקס AL הווא וסוט , TG TU wm SR d NL, ich ₪ a, , ude ו ווח TALI ₪ LGRL TA, aL" \| גוסו Nu eu! aad \| וס Sy inh \| \| טש , SE / ed > האר jd | 025195516 | 1 | doc_msi1ytlznqboaa | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 205 | on ror ומוס on סא | 610710080 | 1 | doc_msj2udwwk5mrnc | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 206 | / / הודפס ע'י בבית נכסים** ** שולם | 109656266 | 1 | doc_msm9ddakiboloe | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 207 | טמבור בע"מ | 224052026 | 1 | doc_msm0txs4lbf4aj | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 208 | לידי: | 301615367 | 1 | doc_msm3o2cidaa19o | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 209 | Navn מס IN מקור | 264007437 | 1 | doc_mshcugl4jhful0 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 210 | ליטר קולורנט חום | 512306153 | 1 | doc_msmagdf8h7w23i | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 211 | 555245  חשבונית מס | 631242020 | 1 | doc_msn7e0seu6vl0l | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 212 | J % (Q) Lielyauticoil Nf \| uTiemm ISUZU SUNUIN | 039160600 | 1 | doc_msj2fq5q0j1mii | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 213 | עמוד1 | 200015185 | 1 | doc_msmfjuqbg7rzth | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 214 | משרד החינוך | 335932265 | 1 | doc_msmfu0twt327y6 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 215 | / / הודפס ע'י בבית נכסים** ** שולם | 051702264 | 1 | doc_msoaiul38vic8v | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 216 | תסקיר ניסוי ובדיקת מכונות הרמה | 010001700 | 1 | doc_msnsa0oy8cw0fv | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 217 | magen pirzul ltd | 269000026 | 1 | doc_msnst7w8e04cow | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 218 | שראל | 091220244 | 1 | doc_msm8ccg5r1cfnt | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 219 | F ביצענו התאמה לפריטים הבאים עם מסמך מספר | 110000020 | 1 | doc_msoa171n90r7qq | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 220 | israel | 720040100 | 1 | doc_msmw130gh1rnrj | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 221 | ASSEMBLY INSTRUCTION | 181942231 | 1 | doc_msmeeaqnc0lx2b | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 222 | Amir A | 122570801 | 1 | doc_msofeyeslmzuqv | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 223 | 346666231   מספר חשבון חוזה | 346666231 | 1 | doc_msmi5gi39b1fjt | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 224 | 'rt n,I-r ,n"yr rrt | 169000001 | 1 | doc_msmjtgk2ru7ule | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 225 | un , can ran rir Santino / FO | 261100174 | 1 | doc_msmorptw9jlx77 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 226 | קרקבב"מ 76885 | 105545630 | 1 | doc_msmqnraxtusz2g | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 227 | 'דוח שירות מס313734 | 202619743 | 1 | doc_msms14du8q4bvq | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 228 | ɧɭɪɗ ɥɖɮɛɰɟɖ ɢɯ ɰɛɝɛɭɢɚ ɰɛɮɟɯ ɜɡɮɤɢ ɣɛɰɝɛ ɖɢɤ ɚɜ ɝɧɛɦ ɛɮɟɜɝɚ ɖɦɖ | 035571789 | 1 | doc_msmw9yfm6cs9st | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 229 | רשיון נהיגה DRIVING LICENCE | 040720174 | 1 | doc_msmi6ho9brnnxi | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 230 | משקל | 249624966 | 1 | doc_msm3074hlvvzh9 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 231 | TERMOKIR INDUSTRIES (1980) LTD | 266001631 | 1 | doc_msn3pxbu3ytcxr | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 232 | ליטר קליפת אגוז | 351981388 | 1 | doc_msrq7sn70bms0u | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 233 | ILS , RV | 619032026 | 1 | doc_msn3qz1kkzote0 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 234 | שייח יח' | 113009600 | 1 | doc_msm0t50mhg6ion | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 235 | DRY NLS | 225647389 | 1 | doc_msm242fa5437hh | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 236 | ממספר כרטיס | 202657812 | 1 | doc_msoa2h4zqqiqbx | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 237 | אגן מפעלי הנדסה (1988) בע"מ, שרה מויאל | 266000954 | 1 | doc_msofns6ot2us6l | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 238 | / / הודפס ע'י בבית נכסים** ** שולם | 211875265 | 1 | doc_msr0ft5pdpjol8 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 239 | 'דוח שירות מס311354 | 202618667 | 1 | doc_msmeqz2yb1k3s1 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 240 | יעקב יעקבי ובניו בע"מ | 009408700 | 1 | doc_msmx1vziubxsxg | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 241 | TASSA | 431099654 | 1 | doc_msm3oyz5v1gwze | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 242 | 'דוח שירות מס311502 | 202618697 | 1 | doc_msmfih0wn0wapc | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 243 | לכבוד: | 197551020 | 1 | doc_mslzppqr65b3ho | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 244 | כולל מעיימ | 505054348 | 1 | doc_msm1o5o0dsr2kq | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 245 | תסקיר ניסוי ובדיקת מכונות הרמה | 115003000 | 1 | doc_msnsacvdfunwxy | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 246 | עמוד1 | 200015585 | 1 | doc_msm9glgo1kgyvs | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 247 | 109110001  `מס  אישור קבלה | 870506075 | 1 | doc_msm90zpw4gz9ij | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 248 | ILS RV | 606112025 | 1 | doc_msmco7zdn7aus5 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 249 | )'ואף במישור הנורמטיבי אין לקבלה" (וראו גם עת"מ (חי | 617090117 | 1 | doc_msmcpho3gmb07t | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 250 | 348686637   מספר חשבון חוזה | 348686637 | 1 | doc_msmi5grtjmagx6 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 251 | קנה קבל מתנה | 131391552 | 1 | doc_msm682iaki2o1t | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 252 | רטוק | 102507138 | 1 | doc_msmi7rsiorzhvn | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 253 | TS \| נהג מתאים | 125014070 | 1 | doc_msmj3ao1nebk9q | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 254 | www.cloudways.com | 528002224 | 1 | doc_msmjsn2dbycrg8 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 255 | כחול מסWORK ארקלית/אחסונית | 823871608 | 1 | doc_msm5npjya1p4k5 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 256 | / / הודפס ע'י בבית נכסים** ** שולם | 150089267 | 1 | doc_msmk8icwt2rb4o | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 257 | CIMENT I.S. LTD | 269008511 | 1 | doc_msmlcxmin048q0 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 258 | / / הודפס ע'י בבית נכסים** ** שולם | 122867264 | 1 | doc_msmmew07edvx4j | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 259 | אוהב ציון בע"מ, איריס נעים | 264000982 | 1 | doc_msmwazeytv6qgb | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 260 | א.ר. אסקו יבוא ושיווק בע"מ | 250135675 | 1 | doc_msmx072w0ocrrr | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 261 | ד"סב      502063415  מורשה עוסק     השרון משמר קיבוץ קרגל מתחם בע"מ אימפורט גלקסי            חשבונות | 502063415 | 1 | doc_msmx150ip36e1m | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 262 | 't, n,ln ,n"!,f l]lt | 925002992 | 1 | doc_msm7u6n90zqdw5 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 263 | ", או פקס שמספרו 03-7602085 | 155615234 | 1 | doc_msn9pvfzr5nfko | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 264 | , חוזה שרות / / חלמSI | 266000784 | 1 | doc_mso2bdtw3hvoj8 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 265 | Sher IMPORT & MARKETING OF AUTOMOBILE ACCESSORIE | 257001857 | 1 | doc_msmcp09qm2oklo | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 266 | MHGS04 | 246666661 | 1 | doc_msmeebwaj5u0po | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 267 | IN on mak | 254004418 | 1 | doc_msm3jkdjhhiahq | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 268 | E FETAYA | 264002266 | 1 | doc_msoajhqs064wgp | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 269 | / / הודפס ע'י בבית נכסים** ** שולם | 207581268 | 1 | doc_msw6r4d6y0hzme | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |
| 270 | קבוצת | 353114912 | 1 | doc_mso1stxkbpar0d | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) | low |

### Group A — ID confirmed, name still unresolved (83 candidates, 99 docs)

These all carry a trustworthy ח.פ (from the AI extraction leg, or independently corroborated via raw OCR), but neither the OCR header nor the filename yielded readable Hebrew/Latin text worth proposing as `"שם חברה"`. Recommend a manual lookup (e.g. the Israeli Registrar of Companies / רשם החברות) before inserting.

| # | מזהה 1 | Docs | Sample doc IDs | Evidence |
|---|---|---|---|---|
| 1 | 200516896 | 6 | doc_msm94s4zcbvzo2, doc_msmgeos7eggtka, doc_msmpsd1l9v9ms1 | raw OCR mining: 0 label-anchored + 6 bare-number hit(s) across 6 doc(s) |
| 2 | 557972627 | 4 | doc_msm9daugusye5e, doc_msmgj3rbluar2s, doc_msrxoavhiovf9e | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 3 | 513115949 | 4 | 17800741870467myqc3, doc_msm5bv7cpwtkui, doc_msmcoelnqjuo5o | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 4 | 515128676 | 3 | 17801367928683whsz1, doc_msm7f4iwm4d0ak, doc_msm7f5uh71mlc3 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 5 | 127818337 | 3 | doc_msmym3ewh9kz8b, doc_msmym3x3cnnbq9, doc_msmyoe2oe7mgep | raw OCR mining: 0 label-anchored + 3 bare-number hit(s) across 3 doc(s) |
| 6 | 515672883 | 2 | doc_msmalkpzhdbugt, doc_msm6xuzi1ro1iu | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 7 | 515367340 | 1 | doc_msr0qjy7ht9uwk | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 8 | 513029978 | 1 | doc_msm6afe2uainkf | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 9 | 511850935 | 1 | doc_msm1f955mu152n | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 10 | 513786038 | 1 | doc_msm6znzo5sju1u | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 11 | 515320150 | 1 | doc_msofox1uc0h10h | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 12 | 513414031 | 1 | doc_msqeea6atfzlsi | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 13 | 514598042 | 1 | doc_msme8kjhidr163 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 14 | 570049310 | 1 | doc_msm6a4n8h6x810 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 15 | 511890935 | 1 | doc_msm0wxic3hnpvr | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 16 | 514300767 | 1 | doc_msm6a8u14kvhp8 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 17 | A-12415917 | 1 | doc_msmbnfzczq503n | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 18 | 570045318 | 1 | doc_msm6a2vws3276p | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 19 | 511981084 | 1 | doc_msmx292j6ii3lv | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 20 | 513825905 | 1 | doc_msnam28mg3weq6 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 21 | 513028975 | 1 | doc_msm79ycgbo7k4n | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 22 | 513534389 | 1 | doc_msm7bg8ujqrnn9 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 23 | 514748888 | 1 | doc_msm5uuhq8dyw54 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 24 | 511429666 | 1 | doc_msmedhtw3klmbb | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 25 | 511032453 | 1 | doc_msmfvi5b2fw1sc | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 26 | 022083294 | 1 | doc_msm7ebanxumf3s | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 27 | 514262803 | 1 | doc_msm5uuk453mxhz | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 28 | 513698069 | 1 | doc_msm6a47m6k91tt | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 29 | B-12008772 | 1 | doc_msmbnfuhznp38c | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 30 | 570030150 | 1 | doc_msm7bg01gyeycz | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 31 | 515008877 | 1 | doc_msm30i3lg2mlji | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 32 | 513687995 | 1 | doc_mss1dud2z02e9b | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 33 | 513629875 | 1 | doc_msmhzo87f4tfnv | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 34 | 510255014 | 1 | doc_msoforve6h4fbc | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 35 | 511019054 | 1 | doc_msnamzo4d602vv | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 36 | 511943904 | 1 | doc_msnuaggwkqny0x | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 37 | 514667076 | 1 | doc_msm30kyb3vwerv | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 38 | 026858688 | 1 | doc_msmdot34wpw2yo | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 39 | 511371502 | 1 | doc_msmlcwwyaz9ftv | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 40 | 321568586 | 1 | doc_msmco7p0dvigmg | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 41 | 513028878 | 1 | doc_msm34slhcraor3 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 42 | 515675635 | 1 | doc_mss1et7y314kfd | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 43 | 303183939 | 1 | doc_msm7aiy1atel7q | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 44 | 512803824 | 1 | doc_msnamy3uv4mmqc | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 45 | 514300305 | 1 | doc_msnamwrwx60l3r | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 46 | 515672853 | 1 | doc_mspzcgjycn36rq | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 47 | 516451454 | 1 | doc_msojn9btxi5v5l | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 48 | 511027930 | 1 | doc_msmalo98q1sfrr | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 49 | 512012071 | 1 | doc_msm6a35t864zi9 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 50 | 514500945 | 1 | doc_msm30kfq2yqzkf | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 51 | 570085310 | 1 | doc_msm5q2onh7nm9o | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 52 | 520038842 | 1 | doc_msm6tqvbuvpjm6 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 53 | 570048310 | 1 | doc_msm1fnxf0l6ueg | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 54 | 558564852 | 1 | doc_msoa2cdf3zpaoc | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 55 | 511662926 | 1 | doc_msm340soz8yewm | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 56 | 510664693 | 1 | doc_msm34ap0c26rsa | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 57 | 513894389 | 1 | doc_msm7bgkvcem12c | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 58 | 514651520 | 1 | doc_mss1dthzzew6u7 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 59 | 557269655 | 1 | doc_msobfy7upnr4qc | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 60 | 511591084 | 1 | doc_msmbk3kmbj9id9 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 61 | 029681707 | 1 | doc_msmazkhibr9ru8 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 62 | 511475149 | 1 | doc_msm8cem831bpk1 | ID confirmed via AI extraction leg; no readable name (OCR + filename both uninformative) |
| 63 | 001107346 | 1 | doc_msmqmh8b4tsnng | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 64 | 202920230 | 1 | doc_mshy54q5murj15 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 65 | 586062010 | 1 | doc_mshnmurjff4zmc | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 66 | 208617423 | 1 | doc_mslmdwtkpgck1s | raw OCR mining: 1 label-anchored + 0 bare-number hit(s) across 1 doc(s) |
| 67 | 514528099 | 1 | doc_mshwngtu7qc2b4 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 68 | 325156347 | 1 | doc_msllshrlt4fs0t | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 69 | 701265015 | 1 | doc_mshr0jjlwjok3m | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 70 | 005356755 | 1 | doc_mslzpp7935z47w | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 71 | 536839497 | 1 | doc_mshvduvagirbhe | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 72 | 008906412 | 1 | doc_msmk8fhb8yd9fw | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 73 | 200402040 | 1 | doc_mshxw7uul1o235 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 74 | 511976001 | 1 | doc_mso1y361h6wo8g | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 75 | 620025500 | 1 | doc_msm28n29ojdt81 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 76 | 126020578 | 1 | doc_msofdvk3z13yrj | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 77 | 071956693 | 1 | doc_msmoru2hcdfi0l | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 78 | 220420190 | 1 | doc_msofnma25nj8x5 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 79 | 028332156 | 1 | doc_msmj3k6oynkieg | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 80 | 565187595 | 1 | doc_msowgwkqpyb7oc | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 81 | 952545705 | 1 | doc_msmeebaz62g0hd | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 82 | 380280250 | 1 | doc_msofdm4ircsa6l | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |
| 83 | 010100120 | 1 | doc_msojf0apioeuv5 | raw OCR mining: 0 label-anchored + 1 bare-number hit(s) across 1 doc(s) |

---

## Group B — UPDATE (existing `public.companies` rows)

| # | Company row | Existing מזהה 1 | Field to update | Proposed value | Docs affected | Evidence |
|---|---|---|---|---|---|---|
| 1 | id=680 מוניטולס | 511960619 | "מזהה 2" (add dashed alias) | `51-196-061-9` | 6 | AI extraction reads the ID with dashes (`51-196-061-9`); the stored `"מזהה 1"` (`511960619`) is the same number without punctuation. Exact-string matching (`NameCompanyMatchOffline`/`q_v3_company`) needs both spellings on file to catch either. |

*(No blank-identifier or `פריוריטי`-sentinel companies rows turned out to be genuine Group B targets — see Methodology §5: both blank rows are the tenant's own placeholder entries, and the one sentinel-looking row is a real company, already fully identified.)*

### Informational — extraction miss, not a companies-table gap

13 `MISSING_COMPANY_ID` docs across **8 already-known companies**: raw OCR mining found that company's *exact*, already-registered ID sitting in the document text, but neither the LOCAL leg (registry `find option`) nor the AI leg extracted it at the time — a base-extraction miss, not missing company data. No companies-table change is proposed; re-running base extraction on these doc IDs should resolve them directly.

| Company | מזהה 1 | Docs | Sample doc IDs |
|---|---|---|---|
| id=1177 מבנה דרום חדש | 516431434 | 6 | 178005141106521jukh, 1780051486422bpfnes, 1780051740358al4zhr |
| id=1029 פנל אור | 515021780 | 1 | 177721240668634utrz |
| id=710 בודי | 512341470 | 1 | doc_msoajqpg3mwb77 |
| id=1127 עלי סלאמה | 515943017 | 1 | doc_msm5tqcy05kt5b |
| id=655 פורום | 511640229 | 1 | doc_msmgifgl7p1qk5 |
| id=733 מילסטון | 512643859 | 1 | doc_msoa2h046khula |
| id=593 אשדוד סחר | 511061566 | 1 | doc_msm43ar0lnu771 |
| id=152 רכיבה בשבילי | 021956693 | 1 | doc_msmoprumhcx7ya |

---

## Group C — Unresolvable (this pass)

| Reason | Docs | Notes |
|---|---|---|
| No OCR at all (`API_TOOLS_ID` empty) | 388 | Never uploaded to apitools, or upload failed before OCR ran. Needs the ingest/upload lane, not a companies fix. |
| OCR cache miss (`API_TOOLS_ID` set, apitools returns `file_not_found`) | 155 | The row references a hash the shared OCR cache no longer has (eviction, or it was never actually completed). Needs a re-OCR, not a companies fix. |
| OCR present, no identifiable ID in the text | 497 | Genuinely no ≥9-digit run found in the pre-"לכבוד" header zone — garbage/low-quality scans, non-invoice documents (spreadsheets, personal certificates, WhatsApp exports), or the id sits in a layout our simple header-zone heuristic doesn't reach. |
| Candidate found but only in phone-number context | 65 | A 9-digit run existed near a תקn/פקס/נייד label and nowhere near an id label — treated as noise, not proposed. |

Total Group C (this pass): **1105 docs**. None of these are proposed for the companies table — they need a different fix (re-upload, re-OCR, or are simply not vendor-identifiable documents).

### Informational — tenant self-identifier leakage (AI extraction defect, not a companies gap)

**143 docs** where the extracted/mined "company" identity is actually the tenant's own record (**מ.ש הכהנים חומרי בניין בע"מ**, ח.פ `515561520` — deliberately stored in `public.companies` with **blank** identifier columns, ids 1262/1093, so the id-map can never self-match). `q_v3_company`'s own live query already carries `"exclude_near": ["הכהנים", "מ.ש הכהנים"]` for exactly this failure mode; this report mirrors that safeguard plus a fuzzy check (`כהנ`/`שילה` — the tenant's own delivery address, א.ת שילה) for garbled OCR variants of the same self-reference. Breakdown:

- Exact `COMPANY_ID = '515561520'` (AI leg): **34 docs**
- Garbled digit-variants of the same self-id, caught via the fuzzy name check, orphan-sourced: **10 docs** across 7 distinct AI-misread ID strings (511031551, 513594473, 513997370, 510815859, 513483693, 029524337, 318990611)
- Self-reference text found via raw OCR mining on candidate-less docs: **94 docs**

**Not proposed as companies-table changes** — this is an extraction-lane defect (AI/OCR occasionally reads the *recipient's* letterhead instead of the vendor's). Recommend a follow-up on `BaseDocEx01`/the AI extraction prompt, mirroring `q_v3_company`'s `exclude_near`. **Caveat:** the fuzzy `כהנ` check is a 3-letter Hebrew fragment and can false-positive on the common surname כהן/Cohen unrelated to the tenant (one such case was observed live: `כהן אלדד`, a personal name) — this bucket should be spot-checked, not treated as certain, before any downstream action.

---

## Methodology

### 1. Population query

```sql
-- Group A of the population: STATUS-based
select * from public.incoming_documents
where "STATUS" in ('UNKNOWN_COMPANY','MISSING_COMPANY_ID');

-- Group B of the population: orphan COMPANY_ID on ANY status
select d.* from public.incoming_documents d
where d."COMPANY_ID" is not null and btrim(d."COMPANY_ID") <> ''
  and not exists (
    select 1 from public.companies c
    where c.instance='incoming-documents-main'
      and (
        btrim(c."מזהה 1") = btrim(d."COMPANY_ID")
        or btrim(c."מזהה 2") = btrim(d."COMPANY_ID")
        or btrim(c."שם ספק מפריוריטי") = btrim(d."COMPANY_ID")
      )
  );
```

Result: 1663 (STATUS-based) + 190 (orphan COMPANY_ID on OLD/MAX_ITERATIONS/COMPLETED/GARBAGE) = **1853 total** (1461 have `API_TOOLS_ID` set, 392 do not).

### 2. Reused the live base-extraction signal instead of re-deriving it

Per `BaseDocEx01.workflow.ts` (`Select Base` node, two-point-rule 2026-08-17), `COMPANY_ID` is already `pick(LOCAL_COMPANY_ID, AI_COMPANY_ID)` falling back to a filename match. Checking the target population showed:

- **100% of the 383-doc orphan-COMPANY_ID population** got its id from the **AI leg alone** (`AI_COMPANY_ID`; `LOCAL_COMPANY_ID` was 0/383 — expected, since the LOCAL leg only ever matches an id already in the registry, so it can't produce an *unmatched* id by construction).
- The 1470 `MISSING_COMPANY_ID` docs have **both legs null** (1082 with `API_TOOLS_ID`/cached OCR, 388 without).

So for the 383 orphan docs, the ID itself was **trusted as-is from `AI_COMPANY_ID`** (no re-derivation) — OCR was only used to mine a **name** for it, anchored on the already-known number. For the 1470 candidate-less docs, both the ID and the name had to be mined fresh from OCR text, since neither engine had extracted anything at all.

### 3. apitools endpoint used

`POST http://apitools:8080/documentJsonQuery` (from inside the `n8n-shlomo-laptop` container), batched form:

```json
{"file_id": "<API_TOOLS_ID hash>", "ocr_json_queries": [{"field": "P", "ocr_json_query": {
  "action": "find regex", "action_value": "ZQPROBE_NEVER_MATCHES_9f3x7Q_ZQPROBE", "value_validations": []
}}]}
```

This deliberately-unmatchable probe always falls into the engine's error branch, which — per `ocr_json_query.py`'s `_run_single()` — unconditionally attaches the document's full raw OCR text as `results[0].result.error.full_text`. That is a more reliable way to obtain the whole page text than any single `find after`/`find option` query: those only return a single matched token, and — checked directly against `ocr_json_query.py` — their full-text FALLBACK path (`_fulltext_find_after`) does **not** honour `region`/`exclude_near` at all (only the annotation-alignment path does), which is exactly why a naive `find after` re-implementation mis-fired on a live test document (matched the recipient's own id after a stray `ע.מ.` token below `"לכבוד"`). Fetching the raw text once and applying the *same* safeguards `q_v3_company` uses (region + exclude_near) locally, in full control, proved both simpler and more correct than delegating to `find after`.

Cached-OCR full-text fetch measured **~45ms/doc** server-side (`elapsed_ms` in the response); the full 1300-call mining pass (see §4) completed in **59s** at concurrency 4 — well inside the ≤4-concurrent / small-host bound.

### 4. Extraction heuristic (mirrors `q_v3_company`'s own safeguards)

1. **Header zone** = text before the first `"לכבוד"` occurrence (or first 1500 chars if absent) — same rationale as `q_v3_company`'s fallback `region: {y_max: 0.55, exclude_below: "לכבוד"}`: text below `"לכבוד"` addresses the *customer* (the tenant), not the vendor.
2. **Candidate numbers**: all bare 9-digit runs, plus dash/dot-separated groups that normalize to 9 digits (covers ID formats like `51-201207-1`), found inside the header zone.
3. **Self-exclusion**: any candidate within ~45 chars of the literal strings `"הכהנים"`/`"מ.ש הכהנים"` is excluded outright (identical strings to `q_v3_company`'s live `exclude_near`), plus the confirmed self-id number `515561520` is excluded by value regardless of context. A weaker fuzzy check (`כהנ`/`שילה` within ~60 chars) *flags* rather than excludes, to catch OCR-garbled variants without silently dropping a real vendor id.
4. **Confidence scoring per candidate**: label-adjacent (within ~25 chars of `עוסק מורשה`/`ח.פ`/`ע.מ`/`מספר חברה`/etc.) scores highest; a bare number with no label scores lower; a number near a phone/fax label and no id label is treated as noise, not a candidate.
5. **Name candidate**: the text on the same line as the chosen number (digits/punctuation stripped), falling back to the previous non-empty line, plus the header zone's first non-empty line as an alternate candidate — the better of the two (favouring one containing a legal-entity suffix: בע"מ/חברה/שותפות/etc.) is proposed. Generic label-only fragments (e.g. a bare "עוסק מורשה") are rejected rather than proposed as a name.
6. Same-normalized-name agreement across ≥2 independently sourced documents (or cross-validation between the AI-leg-known id and an independent raw-OCR find) raises confidence to **high**.

### 5. Companies cross-reference

Every mined candidate id was checked against `public.companies` (instance=`incoming-documents-main`) **twice**: an exact `btrim` match (should already be excluded by the population query, and was, except for ids discovered fresh by OCR mining on the *candidate-less* `MISSING_COMPANY_ID` docs — the population query obviously couldn't check an id it didn't have yet) and a **digit-normalized** match (strips all punctuation, catches formatting-only mismatches). Also checked: companies rows with **all three identifier columns blank** (found only 2 — both are the tenant's own placeholder rows, ids 1262/1093, deliberately left blank so the id-map can never self-match) and rows whose identifier contains the substring `"פריוריטי"` (found only 1 — a real company, **Priority Software Ltd**, whose actual trade name contains that word; not a sentinel, no action needed).

### 6. Filename-matcher bonus check

For every Group C doc with **no** candidate id at all, checked whether its filename (`NAME`) would anchored-prefix-match (`position(cname in NAME)=1`, len≥5 — `NameCompanyMatchOffline`'s exact semantics) any of the 270 newly-proposed Group A names. Result: **0 docs**. Inspecting the filenames explains why: the no-OCR/no-candidate population's filenames are overwhelmingly generic (`unknown-NNNNN.pdf`, `IMG-*`, bare numbers) or internal reports (`פירוט עסקאות דלק CSV.csv`, `כרטסת.xlsx`, `Book1.xlsx`) rather than vendor-labelled uploads, so this leg has little to work with in this dataset.

### 7. Known limitations

- The name-mining heuristic is a simple line/proximity heuristic, not a layout-aware parser — it can pick a wrong nearby line on multi-column or table-heavy documents (observed on delivery-note-style scans).
- The `כהנ`/`שילה` fuzzy self-reference check can false-positive on the unrelated surname כהן (Cohen) — see the Group C self-reference note above.
- OCR-quality-dependent throughout: `pdf_textlayer`/local-engine documents with genuinely garbled text (observed live, e.g. a document reading `"Pr a ... TSR ... אוו"`) will not yield a usable candidate no matter how the text is mined — this is a real OCR-quality floor, not a gap in the heuristic.
- Sampling: for the 383 orphan-id docs, only ≤2 sample documents per distinct id were OCR'd (not all — up to 34 docs share one id); doc counts in Group A reflect the FULL count from the database for orphan-sourced rows, but the proposed name itself rests on only 1–2 of those documents.

---

## Proposed SQL (NOT executed — read-only report)

```sql
-- ============================================================
-- GROUP A: ADD -- 270 new companies rows (named candidates only;
-- the 83 ID-only candidates are listed above but intentionally have
-- no INSERT here -- fill in "שם חברה" after a manual lookup, then insert).
-- ============================================================
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'דאמוני תאורה ומסחר בע"מ', '515998094'); -- high, 24 doc(s), sample: doc_msnpj8yjfvzz75
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'קומנדו הנעלה והלבשה בעיימ', '517142121'); -- high, 17 doc(s), sample: doc_msmb3btcu0yrlq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מעש תעשיות פלדה 2001 בע"מ', '513372060'); -- high, 13 doc(s), sample: doc_mss7s0px50nm2b
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'עוסק מורשה מאוחד', '557640380'); -- high, 12 doc(s), sample: doc_msm9dynn1092kt
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '505703609 :חשבונית מס', '512022930'); -- high, 10 doc(s), sample: doc_msnpgj9u2h5lty
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'e-mail: person106@example.com', '513324616'); -- high, 8 doc(s), sample: doc_msm555db48borl
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'א . מ.ס.י 33 מנעולנות בע"מ', '517270229'); -- high, 7 doc(s), sample: doc_msm5tkcw6pm27l
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'קפרו תעשיות בע"מ', '511414666'); -- high, 6 doc(s), sample: doc_msm5u652qxb4yt
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'e-mail: bmayltdֲ@gmail.com', '514254663'); -- high, 6 doc(s), sample: doc_mslw4fgeilvaae
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'הוט מובייל בע"מ', '512615964'); -- high, 6 doc(s), sample: doc_msqsqccsbhmf9n
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מ"בע חברה', '516252475'); -- high, 5 doc(s), sample: doc_msr480api2ymf9
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '30 :  תנאי תשלום- שירות לחודש יולי', '517199550'); -- high, 5 doc(s), sample: doc_msoauaxa6el2so
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'PRISSMACER CERAMICA S L U NIF/VAT ESB', 'ESB12816021'); -- high, 4 doc(s), sample: doc_msm9gx7qrw7q3s
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'e-mail: person107@example.com', '515181022'); -- high, 4 doc(s), sample: doc_msnpgbogfm5aw9
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לאונאיי בע"מ', '516916954'); -- high, 4 doc(s), sample: doc_msn7aamcy4zkgr
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Ner online', '318336773'); -- high, 4 doc(s), sample: doc_msni63mwspbka3
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'א.ש. פלסט', '511926990'); -- high, 4 doc(s), sample: doc_msm9dn785edba6
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'עמותה רשומה', '580656460'); -- high, 3 doc(s), sample: doc_msm41f6ztmkjk1
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'עוסק מורשה / / תא'' הפקה / / תא'' סיום', '036696003'); -- high, 2 doc(s), sample: doc_msm4du4aqrmwni
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'גרניט שיווק מותגים בע"מ', '516544640'); -- high, 2 doc(s), sample: doc_msmgdqhclgdhwu
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אבן טין בע"מ | Tin Stone LTD', '517119533'); -- high, 2 doc(s), sample: doc_msos62uddnguic
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Part IVA IT N Mecc MO', 'IT00330200361'); -- high, 2 doc(s), sample: doc_msm0w5s6f86cox
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'איון אנרגיה ישראל בע"מ', '516658705'); -- high, 2 doc(s), sample: doc_msmcoc8ln2rb16
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'www.cloudways.com', 'EU528002224'); -- high, 2 doc(s), sample: doc_msme8p1fogrxo6
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ח.פ. - מ"בע דרך ושרותי מוסכים רשת שלמה', '512304056'); -- high, 2 doc(s), sample: doc_msmgebikew76nl
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'web site: www.mds.co.il', '511509762'); -- high, 2 doc(s), sample: doc_msmfzbnkcn8ozk
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'תרושקת תוכרעמ טראמס השרומ דודשא קסוע דיינsmartsys @gmail com ליימיאsmartsystemss co il רתא', '313145153'); -- high, 2 doc(s), sample: doc_msok4hwpapetir
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'טלפון', '046055506'); -- high, 2 doc(s), sample: doc_msmi16u2n81n8w
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'worker', '558019410'); -- medium, 10 doc(s), sample: doc_mslyntrwy65k7m
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Pasadena, CA', '911894477'); -- medium, 10 doc(s), sample: doc_msiz7trf5bztpe
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מן הישראלי', '51-201207-1'); -- medium, 7 doc(s), sample: doc_msmb3cstve9rst
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ctrl', '515453389'); -- medium, 5 doc(s), sample: doc_msm6u7714vbptg
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מרכז', '513354977'); -- medium, 4 doc(s), sample: doc_msmc2mz62bzqcr
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'העתק תעודת עוסק מורשה', '517236683'); -- medium, 4 doc(s), sample: doc_msq0znhibgonw8
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'גבאי', '514714237'); -- medium, 4 doc(s), sample: doc_msm7uic2p6cl2i
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'V A T ESB', 'ESB12004198'); -- medium, 3 doc(s), sample: doc_msmal4tl5uutsf
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'וסק מורשה', '511441388'); -- medium, 3 doc(s), sample: doc_msqrs9ooqs442p
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'web site: www.ysteel.co.il', '520039256'); -- medium, 3 doc(s), sample: doc_mso6c1ysufwzvq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אגש"ח בע"מ', '557656139'); -- medium, 3 doc(s), sample: doc_mspytg2oyz0ijp
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'הדפסת תעודת משלוח - מקובץ', '557684834'); -- medium, 3 doc(s), sample: doc_msmc3ig7nx0did
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'F ביצענו התאמה לפריטים הבאים עם מסמך מספר', '110000017'); -- medium, 3 doc(s), sample: doc_msmuxpgxgy4xmo
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'שיכר SHEICHIAR', '513676106'); -- medium, 2 doc(s), sample: doc_msmalkbjqby24x
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'סניף מנפיק : שפלה', '514583558'); -- medium, 2 doc(s), sample: doc_msmfdxnqoy53ws
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'טלפון פקס', '514971464'); -- medium, 2 doc(s), sample: doc_msm28kua8vcyme
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'C F E N DI SCRIZIONE REG, IMPR DI MO', '00611410374'); -- medium, 2 doc(s), sample: doc_msm9gxxn1niwlt
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '(דף מספר )( ) עוסק מורשה', '511851248'); -- medium, 2 doc(s), sample: doc_msmc2s60pbpfby
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'עוסק מורשה מכן', '513942185'); -- medium, 2 doc(s), sample: doc_msojz0udtjmbh0
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '1  מתוך1   |  עמוד50197   |  חשבונית מס11:11 26/04/2026 הופק ב', '516285996'); -- medium, 2 doc(s), sample: doc_msmcolyfzxuf31
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'קבוצת נגב בע"מ', '557288644'); -- medium, 2 doc(s), sample: doc_msobd2v7s3zx60
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'pupaqou', '15672863'); -- medium, 2 doc(s), sample: 1779972261941fm31oh
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '()עותק', '202626640'); -- medium, 2 doc(s), sample: doc_msovr1dwrehijy
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', ' ʺʥʫʩʠʺʸʷʡʺʷʬʧʮʬʺʥʰʴʬʯʺʩʰʭʩʸʥʸʩʡʬ', '036533615'); -- medium, 2 doc(s), sample: doc_msmdu41zpzgved
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'חשבוניות פתוחות- סטאטוס מצב לקוח', '320001072'); -- medium, 2 doc(s), sample: doc_msmqlvco8l6dlj
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'תאריך חשבונית', '261009546'); -- medium, 2 doc(s), sample: doc_msmkgsy5dsmjp0
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '* הודפס על ידי רמות סוכנויות ביטוח בע"מ', '510999154'); -- medium, 2 doc(s), sample: doc_msmog820eckpai
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'F ביצענו התאמה לפריטים הבאים עם מסמך מספר', '110000016'); -- medium, 2 doc(s), sample: doc_msmj2bdy8fdbbq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'e mail shmulik s @ b e zeqint net', '039300641'); -- medium, 2 doc(s), sample: doc_msmypxks3td0bq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Plassim Infrastructures Ltd.', '106132113'); -- medium, 2 doc(s), sample: doc_msmco7z1lr9ahq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'F ביצענו התאמה לפריטים הבאים עם מסמך מספר', '110000018'); -- medium, 2 doc(s), sample: doc_msm9wsb295vr51
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '1  מתוך1   |  עמוד50071   |  חשבונית מס18:16 12/08/2026 הופק ב', '516737780'); -- medium, 1 doc(s), sample: doc_msq97fs9vq9qgo
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '2 מתוך 1   |  עמוד1046   |  חשבונית מס / קבלה19:04 25/01/2026 הופק ב', '061271557'); -- medium, 1 doc(s), sample: doc_msmdox9sz3h1ym
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מע"מ+ סה"כ', '514153584'); -- medium, 1 doc(s), sample: doc_msowgr8oly35an
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'דואר נע גרנות 3881100 • עוסק מורשה מס'' 570047142', '570047142'); -- medium, 1 doc(s), sample: doc_msmbnjg0fj8ygq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ארגנטולס בע"מ', '510528714'); -- medium, 1 doc(s), sample: doc_msmj8j5uzujg5u
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מ"בע דפוס פתרונות ראש', '515210144'); -- medium, 1 doc(s), sample: doc_msmco8u473dkck
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'גרבלי זוהר חפציבה', '203172754'); -- medium, 1 doc(s), sample: doc_msm32fdxojl1y3
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ארד אמיליו בע"מ', '515078574'); -- medium, 1 doc(s), sample: doc_msqdzil68b3ci5
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'CODICE IDENTIFICATIVO IT', 'IT01024300368'); -- medium, 1 doc(s), sample: doc_msm9gxspgm2wck
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מוסך המרכבה (2004) בע"מ', '513560797'); -- medium, 1 doc(s), sample: doc_msmnjmts8acelz
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לכבוד:', '022612691'); -- medium, 1 doc(s), sample: doc_msq3c9q52trplh
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'HALLON CERAMICAS, S.L.U. inscrita en el Reg. Mercantil de Castellon, de recha 27-06-2019, al lomo 1U33, Libro 597, Follo 4, Hoja CS 2609 - Inscripcion 5b - CI.F. B-12008272', 'B-12008272'); -- medium, 1 doc(s), sample: doc_msm6tvrlcny6qe
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'בסייד', '308944198'); -- medium, 1 doc(s), sample: doc_msmcom6t5lnek1
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'תעודת משלות', '570038168'); -- medium, 1 doc(s), sample: doc_msm7vdazhzexix
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'חשבונית זו מהווה אחריות שנה על המוצר אותו רכשת בחברתנו ע"י תקנון היבואן א. אברהמי', '205651987'); -- medium, 1 doc(s), sample: doc_msr0dkv062qwp2
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'a ונם ו וו בדורנם', '562197129'); -- medium, 1 doc(s), sample: doc_mshfiyxbt5qckt
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'פז שמנים וכימיקלים (שיווק ומסחר) בע"מ | מספר חברה | עוסק מורשה', '511892085'); -- medium, 1 doc(s), sample: doc_msmj8gesgf18sv
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אמוץ יבוא ושיווק בע''''מ', '515757565'); -- medium, 1 doc(s), sample: doc_mss1emowhrul2o
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ח פ מרכז שרות', '511171852'); -- medium, 1 doc(s), sample: doc_mslynvy2vs3she
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'פרץ הבית לקבלן ביתר עלית בעמ', '516406113'); -- medium, 1 doc(s), sample: doc_msmcob0lp9hw2u
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מסמך זה הופק בתוכנה "בקלות כפולה"', '513448407'); -- medium, 1 doc(s), sample: doc_msqwob4cm8z08a
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'web site: https://www.sri.org.il/he/Home', '580072965'); -- medium, 1 doc(s), sample: doc_msmedujppvz6wf
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'תאריך תעודה!', '513293746'); -- medium, 1 doc(s), sample: doc_msme8jv2oacf2u
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מפגש התאומים', '300202264'); -- medium, 1 doc(s), sample: doc_msm5pttuxoq369
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'C I F ES A', 'A-03108669'); -- medium, 1 doc(s), sample: doc_msm33yygtirjro
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'التاريخ', '562191833'); -- medium, 1 doc(s), sample: doc_msojz0vcpq005w
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'קבוצת זיקה בע"מ', '557871696'); -- medium, 1 doc(s), sample: doc_msojzesgxszevu
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'פנים עיצוב -דוד בן טלי', '038012456'); -- medium, 1 doc(s), sample: doc_msmx2a664xzssd
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לכבוד:', '558327417'); -- medium, 1 doc(s), sample: doc_msm95868cwabn3
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'N I F A', 'A12315917'); -- medium, 1 doc(s), sample: doc_msm9gxdutb7tvi
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'C I F ES A', 'ES A-03108669'); -- medium, 1 doc(s), sample: doc_msm565upbp5xvb
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'in una p', '557653847'); -- medium, 1 doc(s), sample: doc_msm5qjrq127le1
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מ"בע 1997 ובניו פילו', '512426685'); -- medium, 1 doc(s), sample: doc_msmcoofpjexif9
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '( בע"מ ) סלם יעקב ובניו ע מ', '512090119'); -- medium, 1 doc(s), sample: doc_msmdos6l7ktqc4
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'י | תיק דיווח מע"מ', '558187274'); -- medium, 1 doc(s), sample: doc_msqq64aphms3bs
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'הופק ע"י חשבשבת ERP מסמך ממוחשב', '086655789'); -- medium, 1 doc(s), sample: doc_msmk96f3ctsd5c
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'טלפון פקס', '026792037'); -- medium, 1 doc(s), sample: doc_msi40x47gjn29a
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מס לקוח', '768132105'); -- medium, 1 doc(s), sample: doc_msm6ub3zwxfmm8
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אומנות השולחן', '058105677'); -- medium, 1 doc(s), sample: doc_mslmdww7f4hdqt
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '554354  , מס'' חשבון028 ( , סניף31) פרטי חשבון: בנק הבינלאומי', '515899623'); -- medium, 1 doc(s), sample: doc_msfzc418zeeykj
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מ.מוריס בע"מ', '516695954'); -- medium, 1 doc(s), sample: doc_mslmdazevhzq62
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'טורנדו מוצרי צריכה בע"מ', '039011500'); -- medium, 1 doc(s), sample: doc_msofnnkuah1zok
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'web site:', '089255414'); -- medium, 1 doc(s), sample: doc_msok5rtq85j69v
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'יציל פיננסים בע"מ', '558180592'); -- medium, 1 doc(s), sample: doc_msoa2blwif79gb
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'טלפון , פקס', '088566506'); -- medium, 1 doc(s), sample: doc_msmml28fs1r7fl
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '"ס אגש"ח בע"מ', '046007001'); -- medium, 1 doc(s), sample: doc_msmorok9bvhbws
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'דרך השלום , תד , נשר | טלפון | פקס', '048211429'); -- medium, 1 doc(s), sample: doc_msmik98o3ldu6v
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ם נרספ po ניתן לפנות', '098925666'); -- low, 6 doc(s), sample: doc_mshq045is4ymr6
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'lea@nogaeinat co il', '820132172'); -- low, 3 doc(s), sample: doc_msmed8p0rru3h5
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'PACKING LIST', '225248094'); -- low, 3 doc(s), sample: doc_msmymlbg6sbmrp
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'בי גי-07780', '514291416'); -- low, 2 doc(s), sample: doc_msm5u20krneyye
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לסה ויז''ן-02139', '516664950'); -- low, 2 doc(s), sample: 1776405937624m68s8
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מס תיק ניכויים', '943288662'); -- low, 2 doc(s), sample: doc_mshvagh3lym4pc
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'OR | | קבל — ge ה ₪ קנה קבל מתנה / Design Your Choice ספןס"מ | | |', '039629353'); -- low, 2 doc(s), sample: doc_mshtlra6anslz7
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ח.נ משקאות בע מ', '168060266'); -- low, 2 doc(s), sample: doc_mshr7pfpfdl5nt
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'רשיון נהיגה DRIVING LICENCE', '214253072'); -- low, 2 doc(s), sample: doc_msmdttnq99oa6f
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'רשיון נהיגה DRIVING LICENCE', '328181672'); -- low, 2 doc(s), sample: doc_msmyplmgpkim4d
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מיכאל הום דיזיין-05316', '514616923'); -- low, 1 doc(s), sample: doc_msmgiswtxd35jp
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'uz9l3e95vuf', '510942007'); -- low, 1 doc(s), sample: doc_mss1duovhdmwip
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'טרנדי טויס-05088', '515142464'); -- low, 1 doc(s), sample: doc_msmflmmik8r1ne
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'nv2rc18mhpi', '510339575'); -- low, 1 doc(s), sample: doc_msm79z1p5xc46z
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אלרם-unknown', '512705482'); -- low, 1 doc(s), sample: doc_msm34ty32sx6yf
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'vt22i2lp031', '510931534'); -- low, 1 doc(s), sample: doc_mspxy6xowhzmp2
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אשדוד סחר-78100', '511061560'); -- low, 1 doc(s), sample: doc_msoabpp4mgbih6
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אבני סלע 28216', '515744453'); -- low, 1 doc(s), sample: doc_msqejwi2e19hbr
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'jn9nm14get2', '510425585'); -- low, 1 doc(s), sample: doc_mspxywb0b3t73d
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'General Ledger_20260701_101442', '514071646'); -- low, 1 doc(s), sample: doc_msoaug1ng7zq7x
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'גולן פלסטיק-unknown', '513029875'); -- low, 1 doc(s), sample: doc_msm2zogpnzwlin
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'yzxtkd6dy9b', '515233158'); -- low, 1 doc(s), sample: doc_msnam9av02lz3k
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Invoice-8D22EF5E-0002', '61-1797223'); -- low, 1 doc(s), sample: doc_msmzqr9u2dgxrs
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'קיסנר-00861', '512711252'); -- low, 1 doc(s), sample: doc_msmff5nl0ti2zx
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ep2y70pxz5p', '570046129'); -- low, 1 doc(s), sample: doc_msnubx3oeu3u7i
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'חשבונית_מס_קבלה_121', '308475789'); -- low, 1 doc(s), sample: doc_mspzcbnoousqdl
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'icibp4prhnl', '510229975'); -- low, 1 doc(s), sample: doc_mso9sna7u7ggiw
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'tiny.txt', '513134988'); -- low, 1 doc(s), sample: doc_mshr02nwcs5lnj
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'איטונג-93581', '557586161'); -- low, 1 doc(s), sample: doc_msmgduu1fytsz5
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אשדוד סחר-78149', '511851566'); -- low, 1 doc(s), sample: doc_mspg5btp1b5lq3
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'תסקיר בדיקת : אביזרי ע"פ', '145627170'); -- low, 1 doc(s), sample: doc_msovquhjn83fb9
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'כתובת:', '792930480'); -- low, 1 doc(s), sample: doc_msm9hcu9pd8oz9
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מפרט )דף רשימה( לפוליסה לביטוח ציוד מכני הנדסי', '700000000'); -- low, 1 doc(s), sample: doc_msmw1gv09svv2n
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Your F', '626333165'); -- low, 1 doc(s), sample: doc_msm6u5g7dhx9ot
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ז שמבוטל עם בטעות חן', '714768799'); -- low, 1 doc(s), sample: doc_msoauns6qcw2hx
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מ ר פסמ', '201069721'); -- low, 1 doc(s), sample: doc_mspxs525p47q2l
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לתאום התקנה (תיאום התקנות מתבצע בימי חמישי בלבד)', '035544720'); -- low, 1 doc(s), sample: doc_msrxovz56zq67t
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מספר /', '185664887'); -- low, 1 doc(s), sample: doc_msn9j5kw62cxnd
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'עמוד1', '112000019'); -- low, 1 doc(s), sample: doc_msmuvo9142o5uh
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מספר תעודה CR', '267000323'); -- low, 1 doc(s), sample: 4285570545qmmoo
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'משרד | מכירות', '086408517'); -- low, 1 doc(s), sample: doc_mshwvrw2uklj33
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Argentools Ltd.', '269000232'); -- low, 1 doc(s), sample: doc_msj1df2pmy5o0k
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'איתור לפני שידור איתור איתור עסקאות טוקנים / / תשלום / / *** ***', '202611249'); -- low, 1 doc(s), sample: doc_msj059kn5lzct4
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ד נ מזרח בנימין', '029700603'); -- low, 1 doc(s), sample: doc_msm91ipvxw56cx
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לקוח', '911019555'); -- low, 1 doc(s), sample: doc_msj1fe7ativtuz
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ה FD אשראי מספרכם || אזור מרכז | גדולה ana מסמך מקורו FD בשלמותה TERT ות אפוקסי ל שבר במקלחונים במראות ובכיזרים os mo || המקלחון ביתי בלבד opr ליציאת ארונות ע"י מתקין re kd Bouny ו TUR', '260084451'); -- low, 1 doc(s), sample: doc_msi417dzqhdlq6
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '₪ Viele x', '028018833'); -- low, 1 doc(s), sample: doc_msj20brlw0w8kv
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מ"בע מים מערכות ת.ל.י.ש', '515919819'); -- low, 1 doc(s), sample: doc_msllydrfn00mjv
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'רשת אקססוריז ויצירה בע"א', '515459774'); -- low, 1 doc(s), sample: doc_msmco834rk1yx0
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'הדפסת תעודת כזו.', '080656151'); -- low, 1 doc(s), sample: doc_msptzm26y8m0xy
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'RWH/ משלוח ‘vn', '122606813'); -- low, 1 doc(s), sample: doc_mshrk1gfonoob1
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'חשבונית מס IN מקור', '260005400'); -- low, 1 doc(s), sample: doc_msm6fmg2vejwfi
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', ':מספר תסקיר134571/155589הרמה-תסקיר בדיקה וניסוי מכונות', '468991281'); -- low, 1 doc(s), sample: doc_msiz7uu1xwjv6w
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מנעול אופניים מספרים ס"מ', '590522152'); -- low, 1 doc(s), sample: doc_mslzpq5qmr015d
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'תאריך לידה של הנהג מספר רשיון נהיגה של הנהג', '198119302'); -- low, 1 doc(s), sample: doc_msj16htoj7pvi5
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'KOL TIMBER LTD.', '269000193'); -- low, 1 doc(s), sample: doc_msmqlejw3eakan
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מוע"ימ מס" TIS מורשיה Dow', '010846061'); -- low, 1 doc(s), sample: doc_mslmcrxlxdizh1
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'איש קשר', '206008790'); -- low, 1 doc(s), sample: doc_msm1oav5up3c1u
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'AE2083WH', '122313456'); -- low, 1 doc(s), sample: doc_msmeebq10zrc5y
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'תוא גישהל רשפאנו לכל שאלהטנרטניאה רתאב ןופלטב תואבה םיכרדב הרהבהו', '057771630'); -- low, 1 doc(s), sample: doc_mspg45gz8k3s1d
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '347667067   מספר חשבון חוזה', '347667067'); -- low, 1 doc(s), sample: doc_msmi5ge3g16l78
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '''דוח שירות מס313323', '202618713'); -- low, 1 doc(s), sample: doc_msmohurq33ikz0
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מאייד', '020000012'); -- low, 1 doc(s), sample: doc_mshq048jxuz6xm
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לפתיחת תביעה שלא בהסדר ולמשלוח מסמכים נוספים _t prat@menora co il yn או יקס שמספרד', '035663969'); -- low, 1 doc(s), sample: doc_msj1fewe2jyg2k
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'רשומון יבוא', '430646703'); -- low, 1 doc(s), sample: doc_msmfb96qie3r6s
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'סוכן <person108@example.com>', '330330170'); -- low, 1 doc(s), sample: doc_msoff5nuokqipr
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לינוי לורבר', '039116060'); -- low, 1 doc(s), sample: doc_msiz79hnm4ripi
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'SUNDECK', '000021602'); -- low, 1 doc(s), sample: doc_msm481bdi1lonb
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ / הודפס ע''י בבית נכסים** ** שולם', '165703261'); -- low, 1 doc(s), sample: doc_msmdpsp3j6q4wi
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Gelem Metal & Plastic 2000 Ltd.', '256016463'); -- low, 1 doc(s), sample: doc_msqwo7n5x368ud
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'PIU INOUL', '052786602'); -- low, 1 doc(s), sample: doc_msovvmmrgxip7w
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מסר מעלקח', '615501620'); -- low, 1 doc(s), sample: doc_msmb0eckp7338y
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ מועד עליה לכבישZCFC C R', '557864022'); -- low, 1 doc(s), sample: doc_msnqj8scwxlqmr
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מ"ל אקווהפלסט לעץ (טיק) בשפופרת', '611001916'); -- low, 1 doc(s), sample: doc_msr4gq5myzru06
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'מרכז שורות ארצי', '089575612'); -- low, 1 doc(s), sample: doc_msi33hw060i4oh
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ILS , RV', '604122025'); -- low, 1 doc(s), sample: doc_msmwaejrqe9tpm
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'טסדפון |', '039230331'); -- low, 1 doc(s), sample: doc_mshxuu79p6p0ki
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'רישיון נהיגה1912524', '191252402'); -- low, 1 doc(s), sample: doc_msnngvg6145dq5
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'service@nyga co il מייל', '036157701'); -- low, 1 doc(s), sample: doc_msi5gzbyx4trfz
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '348265792   מספר חשבון חוזה', '348265792'); -- low, 1 doc(s), sample: doc_msmi5g2n1c231p
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'inbal aviram designs and construction ltd.', '266000013'); -- low, 1 doc(s), sample: doc_msmwaz3ma9uycn
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לבירורים לגבי החשבונית/תשלום באשראי/דיווחי תנועה', '039081111'); -- low, 1 doc(s), sample: doc_msmpsn99rnp6d8
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'דף מתוך', '557658060'); -- low, 1 doc(s), sample: doc_msm3p6a6b9tioe
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'דוחות של אימון בעולם כדי העמדה מס'' ספק משהב"ט', '832747716'); -- low, 1 doc(s), sample: doc_msm3jjfb3eurbv
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'MESH SPACiNG *', '204954330'); -- low, 1 doc(s), sample: doc_msoa2gwygmcru2
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Traditional Blue', '182569128'); -- low, 1 doc(s), sample: doc_msm3j6w3swhu8m
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '505673122 :חשבונית מס', '505673122'); -- low, 1 doc(s), sample: doc_msmxuxu3s3ot0c
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'עמוד:', '127032012'); -- low, 1 doc(s), sample: doc_msnrp20iltm68a
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'TERMOKIR INDUSTRIES (1980) LTD', '442001030'); -- low, 1 doc(s), sample: doc_msn3p4ce07kdnl
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '505637313 :חשבונית מס', '505637313'); -- low, 1 doc(s), sample: doc_msmjtgivbsocja
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ / הודפס ע''י בבית נכסים** ** שולם', '105417264'); -- low, 1 doc(s), sample: doc_msmk8hr2zqr7uu
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ מועד עליה לכבישZCFC C P', '554511962'); -- low, 1 doc(s), sample: doc_msnhwznuvmmgjh
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'IL Local שחר מדפי פיוזד סט', '415040004'); -- low, 1 doc(s), sample: doc_msojlkedogcafd
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'web site: http://www.saltech.co.il', '035566474'); -- low, 1 doc(s), sample: doc_msm3j57mev8j9j
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ehud', '304255192'); -- low, 1 doc(s), sample: doc_msofe3iew4kt48
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'בקרו באתר שלנו', '717272313'); -- low, 1 doc(s), sample: doc_msi312bxohz5j9
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ " לצביעה כללית אורך שיער', '613153866'); -- low, 1 doc(s), sample: doc_msq0fc7lvthzhu
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'mo וסט qual au, | tel Tr, fQ ן te LIGA WIV LHO ucthL re ui א ma תס VTL, [AS vou TALL אל נוי אספאוא Ty TORT ERIE CTALIU © סש סש LCE UTN LU ם, וו שש ₪ LL NLU ag’ % ₪ יי unulL NoGdu // / שו TAN uty הווקס AL הווא וסוט , TG TU wm SR d NL, ich ₪ a, , ude ו ווח TALI ₪ LGRL TA, aL" | גוסו Nu eu! aad | וס Sy inh | | טש , SE / ed > האר jd', '025195516'); -- low, 1 doc(s), sample: doc_msi1ytlznqboaa
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'on ror ומוס on סא', '610710080'); -- low, 1 doc(s), sample: doc_msj2udwwk5mrnc
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ / הודפס ע''י בבית נכסים** ** שולם', '109656266'); -- low, 1 doc(s), sample: doc_msm9ddakiboloe
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'טמבור בע"מ', '224052026'); -- low, 1 doc(s), sample: doc_msm0txs4lbf4aj
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לידי:', '301615367'); -- low, 1 doc(s), sample: doc_msm3o2cidaa19o
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Navn מס IN מקור', '264007437'); -- low, 1 doc(s), sample: doc_mshcugl4jhful0
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ליטר קולורנט חום', '512306153'); -- low, 1 doc(s), sample: doc_msmagdf8h7w23i
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '555245  חשבונית מס', '631242020'); -- low, 1 doc(s), sample: doc_msn7e0seu6vl0l
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'J % (Q) Lielyauticoil Nf | uTiemm ISUZU SUNUIN', '039160600'); -- low, 1 doc(s), sample: doc_msj2fq5q0j1mii
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'עמוד1', '200015185'); -- low, 1 doc(s), sample: doc_msmfjuqbg7rzth
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'משרד החינוך', '335932265'); -- low, 1 doc(s), sample: doc_msmfu0twt327y6
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ / הודפס ע''י בבית נכסים** ** שולם', '051702264'); -- low, 1 doc(s), sample: doc_msoaiul38vic8v
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'תסקיר ניסוי ובדיקת מכונות הרמה', '010001700'); -- low, 1 doc(s), sample: doc_msnsa0oy8cw0fv
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'magen pirzul ltd', '269000026'); -- low, 1 doc(s), sample: doc_msnst7w8e04cow
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'שראל', '091220244'); -- low, 1 doc(s), sample: doc_msm8ccg5r1cfnt
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'F ביצענו התאמה לפריטים הבאים עם מסמך מספר', '110000020'); -- low, 1 doc(s), sample: doc_msoa171n90r7qq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'israel', '720040100'); -- low, 1 doc(s), sample: doc_msmw130gh1rnrj
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ASSEMBLY INSTRUCTION', '181942231'); -- low, 1 doc(s), sample: doc_msmeeaqnc0lx2b
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Amir A', '122570801'); -- low, 1 doc(s), sample: doc_msofeyeslmzuqv
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '346666231   מספר חשבון חוזה', '346666231'); -- low, 1 doc(s), sample: doc_msmi5gi39b1fjt
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '''rt n,I-r ,n"yr rrt', '169000001'); -- low, 1 doc(s), sample: doc_msmjtgk2ru7ule
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'un , can ran rir Santino / FO', '261100174'); -- low, 1 doc(s), sample: doc_msmorptw9jlx77
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'קרקבב"מ 76885', '105545630'); -- low, 1 doc(s), sample: doc_msmqnraxtusz2g
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '''דוח שירות מס313734', '202619743'); -- low, 1 doc(s), sample: doc_msms14du8q4bvq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ɧɭɪɗ ɥɖɮɛɰɟɖ ɢɯ ɰɛɝɛɭɢɚ ɰɛɮɟɯ ɜɡɮɤɢ ɣɛɰɝɛ ɖɢɤ ɚɜ ɝɧɛɦ ɛɮɟɜɝɚ ɖɦɖ', '035571789'); -- low, 1 doc(s), sample: doc_msmw9yfm6cs9st
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'רשיון נהיגה DRIVING LICENCE', '040720174'); -- low, 1 doc(s), sample: doc_msmi6ho9brnnxi
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'משקל', '249624966'); -- low, 1 doc(s), sample: doc_msm3074hlvvzh9
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'TERMOKIR INDUSTRIES (1980) LTD', '266001631'); -- low, 1 doc(s), sample: doc_msn3pxbu3ytcxr
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ליטר קליפת אגוז', '351981388'); -- low, 1 doc(s), sample: doc_msrq7sn70bms0u
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ILS , RV', '619032026'); -- low, 1 doc(s), sample: doc_msn3qz1kkzote0
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'שייח יח''', '113009600'); -- low, 1 doc(s), sample: doc_msm0t50mhg6ion
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'DRY NLS', '225647389'); -- low, 1 doc(s), sample: doc_msm242fa5437hh
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ממספר כרטיס', '202657812'); -- low, 1 doc(s), sample: doc_msoa2h4zqqiqbx
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אגן מפעלי הנדסה (1988) בע"מ, שרה מויאל', '266000954'); -- low, 1 doc(s), sample: doc_msofns6ot2us6l
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ / הודפס ע''י בבית נכסים** ** שולם', '211875265'); -- low, 1 doc(s), sample: doc_msr0ft5pdpjol8
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '''דוח שירות מס311354', '202618667'); -- low, 1 doc(s), sample: doc_msmeqz2yb1k3s1
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'יעקב יעקבי ובניו בע"מ', '009408700'); -- low, 1 doc(s), sample: doc_msmx1vziubxsxg
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'TASSA', '431099654'); -- low, 1 doc(s), sample: doc_msm3oyz5v1gwze
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '''דוח שירות מס311502', '202618697'); -- low, 1 doc(s), sample: doc_msmfih0wn0wapc
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'לכבוד:', '197551020'); -- low, 1 doc(s), sample: doc_mslzppqr65b3ho
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'כולל מעיימ', '505054348'); -- low, 1 doc(s), sample: doc_msm1o5o0dsr2kq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'תסקיר ניסוי ובדיקת מכונות הרמה', '115003000'); -- low, 1 doc(s), sample: doc_msnsacvdfunwxy
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'עמוד1', '200015585'); -- low, 1 doc(s), sample: doc_msm9glgo1kgyvs
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '109110001  `מס  אישור קבלה', '870506075'); -- low, 1 doc(s), sample: doc_msm90zpw4gz9ij
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ILS RV', '606112025'); -- low, 1 doc(s), sample: doc_msmco7zdn7aus5
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', ')''ואף במישור הנורמטיבי אין לקבלה" (וראו גם עת"מ (חי', '617090117'); -- low, 1 doc(s), sample: doc_msmcpho3gmb07t
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '348686637   מספר חשבון חוזה', '348686637'); -- low, 1 doc(s), sample: doc_msmi5grtjmagx6
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'קנה קבל מתנה', '131391552'); -- low, 1 doc(s), sample: doc_msm682iaki2o1t
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'רטוק', '102507138'); -- low, 1 doc(s), sample: doc_msmi7rsiorzhvn
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'TS | נהג מתאים', '125014070'); -- low, 1 doc(s), sample: doc_msmj3ao1nebk9q
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'www.cloudways.com', '528002224'); -- low, 1 doc(s), sample: doc_msmjsn2dbycrg8
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'כחול מסWORK ארקלית/אחסונית', '823871608'); -- low, 1 doc(s), sample: doc_msm5npjya1p4k5
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ / הודפס ע''י בבית נכסים** ** שולם', '150089267'); -- low, 1 doc(s), sample: doc_msmk8icwt2rb4o
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'CIMENT I.S. LTD', '269008511'); -- low, 1 doc(s), sample: doc_msmlcxmin048q0
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ / הודפס ע''י בבית נכסים** ** שולם', '122867264'); -- low, 1 doc(s), sample: doc_msmmew07edvx4j
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'אוהב ציון בע"מ, איריס נעים', '264000982'); -- low, 1 doc(s), sample: doc_msmwazeytv6qgb
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'א.ר. אסקו יבוא ושיווק בע"מ', '250135675'); -- low, 1 doc(s), sample: doc_msmx072w0ocrrr
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'ד"סב      502063415  מורשה עוסק     השרון משמר קיבוץ קרגל מתחם בע"מ אימפורט גלקסי            חשבונות', '502063415'); -- low, 1 doc(s), sample: doc_msmx150ip36e1m
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '''t, n,ln ,n"!,f l]lt', '925002992'); -- low, 1 doc(s), sample: doc_msm7u6n90zqdw5
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '", או פקס שמספרו 03-7602085', '155615234'); -- low, 1 doc(s), sample: doc_msn9pvfzr5nfko
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', ', חוזה שרות / / חלמSI', '266000784'); -- low, 1 doc(s), sample: doc_mso2bdtw3hvoj8
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'Sher IMPORT & MARKETING OF AUTOMOBILE ACCESSORIE', '257001857'); -- low, 1 doc(s), sample: doc_msmcp09qm2oklo
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'MHGS04', '246666661'); -- low, 1 doc(s), sample: doc_msmeebwaj5u0po
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'IN on mak', '254004418'); -- low, 1 doc(s), sample: doc_msm3jkdjhhiahq
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'E FETAYA', '264002266'); -- low, 1 doc(s), sample: doc_msoajhqs064wgp
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', '/ / הודפס ע''י בבית נכסים** ** שולם', '207581268'); -- low, 1 doc(s), sample: doc_msw6r4d6y0hzme
INSERT INTO public.companies (instance, "שם חברה", "מזהה 1") VALUES ('incoming-documents-main', 'קבוצת', '353114912'); -- low, 1 doc(s), sample: doc_mso1stxkbpar0d

-- ============================================================
-- GROUP B: UPDATE -- existing rows, add the dashed alias so exact-string
-- matching (NameCompanyMatchOffline / q_v3_company) catches both spellings.
-- ============================================================
UPDATE public.companies SET "מזהה 2" = '51-196-061-9' WHERE id = 680; -- מוניטולס, 6 doc(s) affected
```

