---
type: article
slug: the-triangle
lang: he
title: "המשולש: להריץ קוד פתוח איפה שרוצים ולהגיע אליו מכל מקום"
seo_title: "גישה מרחוק לשרת ביתי: הדרכים, העלות והמשולש של DGO"
meta_description: "איך מגיעים לשירות שרץ על מחשב בבית או במשרד: CGNAT, Tailscale, Cloudflare Tunnel, WireGuard והמשולש של DGO, עם מחירים בשקלים. נכון לאוקטובר 2026."
summary: "המשולש הוא שלוש לשכות של DGO, למשל לפטופ, מחשב נוסף ו-VPS, שכל אחת מקושרת לשתי האחרות במנהרת WireGuard מוצפנת, כך שאפליקציה שרצה באחת נפתחת כאריח בקונסול של אחרת. המאמר משווה אותו לפורט פתוח, ל-Cloudflare Tunnel ול-Tailscale, עם מחירים בשקלים נכון ל-19.10.2026. הגבול הכן: לשכה על לפטופ נעלמת כשהוא ישן."
category: networks
tags: [ המשולש, הרחבת הלשכה, WireGuard, Tailscale, Cloudflare Tunnel, CGNAT, IPv6, VPS, self-hosting, גישה מרחוק ]
keywords: { primary: "גישה מרחוק לשרת ביתי", secondary: [ "להריץ שרת בבית", "Tailscale לעסק", "Cloudflare Tunnel", "WireGuard בעברית", "CGNAT ישראל" ] }
plane: DGO-757
author: צוות בינה סולושנס
publisher: בינה סולושנס
published: 2026-10-19
updated: 2026-10-19
words: 0
reading_minutes: 0
faq:
  - q: "איך מגיעים למחשב בבית מבחוץ אם אין לי כתובת IP ציבורית?"
    a: "מחברים אותו החוצה ולא פנימה. Cloudflare Tunnel פותח חיבור יוצא ל-Cloudflare, רשת כמו Tailscale מנקבת את ה-NAT או מעבירה דרך ממסר, ומנהרת WireGuard אל VPS עם כתובת ציבורית יוצאת מהנתב בלי פורט נכנס. מאחורי CGNAT, בטווח 100.64.0.0/10, אי אפשר להעביר פורט, ושלוש הדרכים האלה עדיין עובדות."
  - q: "האם Tailscale בחינם לעסק?"
    a: "לא. תוכנית Personal בחינם עד 6 משתמשים, אבל Tailscale כותבת שהיא מתאימה לשימוש לא מסחרי בלבד, ו-tailnet עם שם מתחם משלכם נחשב עסקי ומתחיל בניסיון חינם. התוכנית Standard עולה 8 דולר למשתמש בחודש, כ-25 ₪ בשער 3.11 של 19.10.2026."
  - q: "איך בודקים אם אני מאחורי CGNAT?"
    a: "משווים את כתובת ה-WAN בנתב לכתובת שאתר «מה ה-IP שלי» מציג. אם הן שונות, יש NAT נוסף בדרך. אם כתובת ה-WAN בטווח 100.64.0.0/10, ש-RFC 6598 מייעד לספקים, זה CGNAT של הספק ואי אפשר להעביר פורט."
  - q: "האם IPv6 פותר את הבעיה בישראל?"
    a: "חלקית. לפי APNIC כ-64% מהמשתמשים בישראל מסוגלים IPv6 וכ-59% משתמשים בו בפועל (ממוצע 30 יום עד 11.10.2026), והוא מבטל את ה-NAT. אבל לפי RFC 6092 נתב ביתי לא מעביר פנימה תעבורה שלא התבקשה, ושני הצדדים צריכים IPv6."
  - q: "מה קורה כשהרשת חוסמת UDP?"
    a: "WireGuard עובד מעל UDP בלבד, ואתר הפרויקט אומר שאינו תומך בהעברה מעל TCP. ב-DGO, כשרשת חוסמת UDP (נמדד ב-Windows/Hyper-V), הזוג עובר לנתיב TCP."
  - q: "כמה עולה לקשר שלושה מחשבים?"
    a: "DGO חינמית. משלמים על החומרה, ואם רוצים לשכה שדולקת תמיד, על VPS קטן: KVM 2 של Hostinger (2 vCPU, 8GB, 100GB) עולה 8.79 דולר במבצע ו-14.99 בחידוש, כ-27 עד 47 ₪ בחודש. חשמל למחשב שדולק כל הזמן הוא כ-4.6 ₪ בחודש לכל 10 וואט."
  - q: "מה ההבדל בין המשולש של DGO ל-Tailscale?"
    a: "Tailscale מחברת מכשירים ברשת פרטית ויש לה אפליקציות לטלפונים. המשולש מחבר לשכות, ולכן אפליקציה שרצה בלשכה אחת נפתחת כאריח בקונסול של אחרת. Tailscale קלה יותר להקמה; לשכה היא סטאק שלם, עם בנייה ראשונה של 10 עד 15 דקות על מחשב קטן."
  - q: "מה קורה ללשכה שרצה על לפטופ כשהוא נרדם?"
    a: "היא לא זמינה עד שהלפטופ מתעורר, והלשכות האחרות ממשיכות לעבוד. מה שחייב לענות כל הזמן, כמו אתר ציבורי או קריאת webhook, שייך ללשכה שדולקת תמיד, למשל על VPS."
sources:
  - { title: "Tailscale blog: How NAT traversal works (David Anderson, 21.8.2020)", url: "https://tailscale.com/blog/how-nat-traversal-works", accessed: 2026-10-19 }
  - { title: "IETF RFC 6598: IANA-Reserved IPv4 Prefix for Shared Address Space", url: "https://www.rfc-editor.org/rfc/rfc6598", accessed: 2026-10-19 }
  - { title: "IETF RFC 6092: Recommended Simple Security Capabilities in CPE for Residential IPv6", url: "https://www.rfc-editor.org/rfc/rfc6092", accessed: 2026-10-19 }
  - { title: "APNIC Labs: Use of IPv6 for Israel (IL)", url: "https://stats.labs.apnic.net/ipv6/IL", accessed: 2026-10-19 }
  - { title: "APNIC Labs: IPv6 time series for Israel (JSON)", url: "https://data1.labs.apnic.net/v6stats/v6economy/IL.json", accessed: 2026-10-19 }
  - { title: "GitHub Advisory GHSA-v4pr-fm98-w9pg (CVE-2026-21858): n8n unauthenticated file access", url: "https://github.com/advisories/GHSA-v4pr-fm98-w9pg", accessed: 2026-10-19 }
  - { title: "Tailscale: public DERP map", url: "https://login.tailscale.com/derpmap/default", accessed: 2026-10-19 }
  - { title: "Tailscale docs: DERP servers", url: "https://tailscale.com/kb/1232/derp-servers", accessed: 2026-10-19 }
  - { title: "WonderNetwork: ping times from Tel Aviv", url: "https://wondernetwork.com/pings/Tel%20Aviv", accessed: 2026-10-19 }
  - { title: "Bank of Israel: representative exchange rates (public API)", url: "https://boi.org.il/PublicApi/GetExchangeRates?asXml=false", accessed: 2026-10-19 }
  - { title: "Kamaze: Gilat Telecom, fiber on Bezeq infrastructure, fixed IP add-on", url: "https://www.kamaze.co.il/Deals/40369/gilat-telecom/1000mb-250mb", accessed: 2026-10-19 }
  - { title: "Cloudflare docs: Cloudflare Tunnel", url: "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/", accessed: 2026-10-19 }
  - { title: "Cloudflare docs: Create a remotely-managed tunnel", url: "https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/", accessed: 2026-10-19 }
  - { title: "Cloudflare: Zero Trust plans", url: "https://www.cloudflare.com/plans/sase-zero-trust.md", accessed: 2026-10-19 }
  - { title: "Cloudflare docs: Error 413 and maximum upload size", url: "https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/", accessed: 2026-10-19 }
  - { title: "Tailscale: Pricing", url: "https://tailscale.com/pricing", accessed: 2026-10-19 }
  - { title: "Tailscale: Pricing FAQ", url: "https://tailscale.com/kb/1251/pricing-faq", accessed: 2026-10-19 }
  - { title: "Tailscale: Download (supported platforms)", url: "https://tailscale.com/download", accessed: 2026-10-19 }
  - { title: "Tailscale: Open source", url: "https://tailscale.com/opensource", accessed: 2026-10-19 }
  - { title: "GitHub: juanfont/headscale", url: "https://github.com/juanfont/headscale", accessed: 2026-10-19 }
  - { title: "GitHub: netbirdio/netbird", url: "https://github.com/netbirdio/netbird", accessed: 2026-10-19 }
  - { title: "NetBird: Pricing", url: "https://netbird.io/pricing", accessed: 2026-10-19 }
  - { title: "ZeroTier: Pricing", url: "https://www.zerotier.com/pricing/", accessed: 2026-10-19 }
  - { title: "WireGuard: home page", url: "https://www.wireguard.com/", accessed: 2026-10-19 }
  - { title: "WireGuard: quick start", url: "https://www.wireguard.com/quickstart/", accessed: 2026-10-19 }
  - { title: "WireGuard: known limitations", url: "https://www.wireguard.com/known-limitations/", accessed: 2026-10-19 }
  - { title: "WireGuard: presentations", url: "https://www.wireguard.com/presentations/", accessed: 2026-10-19 }
  - { title: "Linux Plumbers Conference 2018 on YouTube: WireGuard, Next-Generation Secure Kernel Network Tunnel", url: "https://www.youtube.com/watch?v=CejbCQ5wS7Q", accessed: 2026-10-19 }
  - { title: "KernelNewbies: Linux 5.6", url: "https://kernelnewbies.org/Linux_5.6", accessed: 2026-10-19 }
  - { title: "Hostinger: VPS hosting", url: "https://www.hostinger.com/vps-hosting", accessed: 2026-10-19 }
  - { title: "TheMarker SuperMarker: תעריף החשמל 2026 (לפי ספר לוחות התעריפים של רשות החשמל)", url: "https://www.supermarker.themarker.com/bills/guides/electricity-tariff-2026", accessed: 2026-10-19 }
  - { title: "Apple Support: Mac mini power consumption and thermal output", url: "https://support.apple.com/103253", accessed: 2026-10-19 }
  - { title: "Microsoft Learn: Advanced settings configuration in WSL", url: "https://learn.microsoft.com/en-us/windows/wsl/wsl-config", accessed: 2026-10-19 }
  - { title: "Meta for Developers: WhatsApp Cloud API webhooks", url: "https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks/", accessed: 2026-10-19 }
related: [ "dgo://article/wireguard", "dgo://article/one-small-vps", "dgo://tutorial/dgo-on-a-small-vps", "dgo://article/hardware-for-an-office", "dgo://tutorial/install-dgo-with-claude", "dgo://article/plane" ]
---

# המשולש: להריץ קוד פתוח איפה שרוצים ולהגיע אליו מכל מקום

המשולש הוא שלוש לשכות של הלשכה הדיגיטלית (DGO), שכל אחת מהן מקושרת לשתי האחרות: אצלנו אלה ה-MacBook, מחשב HP עם Windows ו-VPS קטן (שרת וירטואלי להשכרה). לשכה היא `./bbox run` אחד על מחשב אחד, והקישורים ביניהן הם מנהרות WireGuard מוצפנות, כך שאפליקציה שרצה באחת נפתחת כאריח בקונסול של לשכה אחרת. המאמר מיועד לבעל עסק, לפרילנסר או לאיש IT שיש לו מחשבים בבית ובמשרד ורוצה להריץ עליהם קוד פתוח ולהגיע אליו מכל מקום.

השורה התחתונה: את המנהרה עצמה אפשר להשיג בכמה דרכים, ו-Tailscale עושה זאת בקלות רבה יותר. המשולש משתלם כשבכל קצה כבר יש לכם סטאק של אפליקציות ואתם רוצים לפתוח את כולן מקונסול אחד. המחיר: שלושה מחשבים לתחזק, ולפטופ שהולך לישון הוא לשכה שנעלמת עד שיתעורר.

[[diagram: שלוש לשכות (MacBook, מחשב HP ו-VPS) עם קו מוצפן בין כל זוג, ואריח של Plane מה-HP שנפתח בקונסול של ה-MacBook | alt: תרשים משולש של שלוש לשכות מקושרות, שבו אפליקציה שרצה במחשב אחד נפתחת כאריח בקונסול של מחשב אחר]]

## למה קשה להגיע למחשב שלכם מבחוץ?

רשת ביתית או משרדית היא מגדל שמירה: הכול יוצא, וחזרה נכנס רק מה שיצא קודם. כך [Tailscale מתארת](https://tailscale.com/blog/how-nat-traversal-works) חומת אש עם מצב, ולכן מחשב שמאחורי נתב מגיע לכל מקום ואף אחד לא מגיע אליו.

הפתרון הקלאסי הוא פורט פתוח בנתב עם כתובת קבועה או DDNS (שם שמתעדכן עם כתובת הבית), והוא עובד רק כשיש לכם כתובת ציבורית אמיתית. ספק שמחבר לקוחות מאחורי CGNAT (תרגום כתובות ברמת הספק) נותן כתובת מהטווח 100.64.0.0/10, ששמור לזה ב-[RFC 6598](https://www.rfc-editor.org/rfc/rfc6598), ושם אין פורט להעביר.

:::tip
בדיקה של דקה: משווים את כתובת ה-WAN בנתב לכתובת שאתר «מה ה-IP שלי» מציג. אם הן שונות, יש NAT נוסף בדרך. אם ה-WAN בטווח 100.64.0.0/10, זה CGNAT של הספק.
:::

בישראל לא נמצא פרסום של ספק שמצהיר אם הוא משתמש ב-CGNAT, ולכן אי אפשר לומר כאן מי כן. מה שכן נמדד הוא IPv6: לפי [APNIC](https://stats.labs.apnic.net/ipv6/IL) כ-64% מהמשתמשים בישראל מסוגלים אליו וכ-59% משתמשים בו בפועל (ממוצע 30 יום עד 11.10.2026). IPv6 מבטל את ה-NAT אבל לא את חומת האש: [RFC 6092](https://www.rfc-editor.org/rfc/rfc6092) קובע שנתב ביתי לא מעביר פנימה תעבורה שלא התבקשה, ושני הצדדים צריכים IPv6.

וכשהכתובת קיימת, מה שחשוף ייבדק. ב-7.1.2026 פורסמה [פרצה קריטית](https://github.com/advisories/GHSA-v4pr-fm98-w9pg) ב-n8n (CVE-2026-21858, ציון 10.0, בלי אימות, גרסאות 1.65.0 עד 1.121.0) שאפשרה גישה לקבצים בשרת דרך תהליך עם טופס. לא כל אפליקציה שאתם מריצים צריכה לעמוד מול כל האינטרנט.

הדרכים שלא פותחות פורט נשענות על כך שהמחשב שלכם יוצא החוצה: או לשירות באמצע, או לניקוב NAT בו-זמנית של שני מכשירים, ואם זה נכשל, לממסר. הניקוב לרוב נכשל כששני הצדדים מאחורי NAT «קשה», ואין לו סיכוי ברשת שחוסמת UDP יוצא. הממסר של Tailscale (DERP) [עובד מעל HTTP](https://tailscale.com/blog/how-nat-traversal-works) בגלל זה. ב[רשימה הציבורית שלה](https://login.tailscale.com/derpmap/default) 28 אזורי ממסר ואף אחד לא בישראל: הקרוב במזרח התיכון הוא דובאי, ובאירופה פרנקפורט, 48 אלפיות שנייה מתל אביב לפי [WonderNetwork](https://wondernetwork.com/pings/Tel%20Aviv) (19.10.2026). שני מכשירים ישראליים שנפלו לממסר מדברים דרך אירופה או דובאי.

[[diagram: מסלול חבילה מלפטופ שמאחורי נתב ו-CGNAT אל VPS עם כתובת ציבורית: יציאה, ניקוב, וממסר כשהניקוב נכשל | alt: תרשים של שני מכשירים מאחורי NAT שמנסים להתחבר ישירות ונופלים לממסר]]

## חמש דרכים להגיע לשירות ביתי: מה כל אחת עולה ואיפה היא נשברת

המחירים נכון ל-19.10.2026, בשער בנק ישראל: 3.11 ₪ לדולר ו-3.4919 ₪ לאירו ([API](https://boi.org.il/PublicApi/GetExchangeRates?asXml=false)).

| הדרך | מה היא נותנת | עלות | הגבול |
|---|---|---|---|
| פורט פתוח בנתב | גישה ישירה, בלי צד שלישי | DDNS בחינם; כתובת קבועה כ-15 ₪ לחודש ([Kamaze](https://www.kamaze.co.il/Deals/40369/gilat-telecom/1000mb-250mb), ספק אחד על תשתית בזק, בלי תאריך עדכון) | דורש כתובת ציבורית אמיתית; כל פרצה חשופה לכולם |
| [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) | פרסום אתר בחיבור יוצא בלבד | [Zero Trust](https://www.cloudflare.com/plans/sase-zero-trust.md) בחינם עד 50 משתמשים, ואז 7$ למשתמש (כ-22 ₪) | חובה [להוסיף שם מתחם ל-Cloudflare](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/); [העלאה עד 100MB](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/) בחבילה החינמית |
| [Tailscale](https://tailscale.com/pricing) | רשת פרטית בין מכשירים, עם ניקוב NAT וממסר | Personal בחינם; לעסק 8$ למשתמש בחודש (כ-25 ₪) | ממסר רחוק מישראל; החינמית לשימוש לא מסחרי |
| [Headscale](dgo://project/headscale), [NetBird](dgo://project/netbird), [ZeroTier](dgo://project/zerotier) | אותו רעיון, בקוד פתוח או בתמחור אחר | Headscale בחינם; NetBird בחינם עד 5 משתמשים ואז 6€ (כ-21 ₪); ZeroTier בחינם ל-10 מכשירים, ואז 18$ לחודש (כ-56 ₪) | ב-Headscale שרת התיאום עליכם; ב-NetBird ו-ZeroTier חינם רק במסגרת מוגבלת |
| המשולש של DGO | לשכה בכל קצה: האפליקציה נפתחת כאריח | DGO בחינם; VPS אופציונלי כ-27 עד 47 ₪ | לפטופ שנרדם הוא לשכה שנעלמת |

:::warning
Tailscale Personal בחינם עד 6 משתמשים, אבל [לפי Tailscale](https://tailscale.com/kb/1251/pricing-faq) היא לשימוש לא מסחרי בלבד, ו-tailnet עם שם מתחם משלכם נחשב עסקי. גם ZeroTier Personal, עם [10 מכשירים בחינם](https://www.zerotier.com/pricing/), מיועדת לשימוש לא מסחרי.
:::

איפה כל אחד מנצח: Tailscale כשצריך להגיע מטלפון או ממחשב של לקוח, כי יש לה [אפליקציות ל-iOS ול-Android](https://tailscale.com/download) והיא מוכנה בדקות. Cloudflare Tunnel כשצריך לפרסם אתר לציבור בלי כתובת ציבורית. פורט פתוח כשיש כתובת אמיתית ורוצים אפס צד שלישי. הלקוח של Tailscale פתוח, אבל [שרת התיאום של השירות המתארח סגור](https://tailscale.com/opensource); [Headscale](https://github.com/juanfont/headscale) הוא שרת תיאום בקוד פתוח (BSD-3) לרשת אחת, לשימוש אישי או לארגון קטן, ו-[NetBird](https://github.com/netbirdio/netbird) פתוחה ברובה, עם רכיבי השרת תחת AGPLv3. מחירי [NetBird](https://netbird.io/pricing) הם באירו, לחודש למשתמש.

המשולש מנצח בדבר אחד: בשני הקצוות יש לשכה, ולכן מה שנפתח בקונסול הוא האפליקציה עצמה ולא כתובת ברשת. ואם צריך רק גישה לשירות אחד, זה יותר מדי: לשכה היא סטאק שלם, עם בנייה ראשונה של 10 עד 15 דקות על מחשב קטן. אם הממשקים של הכלים האחרים זמינים בעברית, לא נבדק; הקונסול של DGO בעברית ומימין לשמאל.

## מה WireGuard נותן ומה הוא לא נותן?

מתחת לקישור יושב [WireGuard](https://www.wireguard.com/): מנהרה שמעבירה חבילות IP מעל UDP, עם הצפנה מבוססת Noise (Curve25519, ChaCha20, Poly1305). רכיבי הליבה שלו תחת GPLv2, והוא חלק מ[ליבת לינוקס מגרסה 5.6](https://kernelnewbies.org/Linux_5.6), מ-29.3.2020. שני מאפיינים חשובים ללפטופ שנודד. הוא מעדכן את כתובת הצד המתחבר מכל חבילה מאומתת, כך שמעבר מ-Wi-Fi לנקודה חמה לא מפיל את הקישור. וצד שמאחורי NAT שולח [חבילת שמירה כל 25 שניות](https://www.wireguard.com/quickstart/) כדי שהנתב לא ישכח אותו; ברירת המחדל כבויה.

מה הוא לא עושה: TCP. [אתר הפרויקט](https://www.wireguard.com/known-limitations/) מצהיר שהוא לא תומך בהעברה מעל TCP, בגלל בעיות הביצועים של TCP בתוך TCP, ומשאיר זאת לשכבה חיצונית כמו udptunnel או udp2raw. ב-DGO, כשרשת חוסמת UDP (נמדד ב-Windows/Hyper-V), הזוג עובר לנתיב TCP. הביצועים שלו: [[fact: תפוקה והשהיה מדודות של זוג לשכות על נתיב TCP לעומת UDP]].

[[video: youtube | ההרצאה על WireGuard בכנס Linux Plumbers 2018, כפי שהיא מופיעה בעמוד ההרצאות הרשמי של הפרויקט | url: https://www.youtube.com/watch?v=CejbCQ5wS7Q]]

## למה שלוש לשכות ולא שתיים או כוכב?

קישור בין שתי מכונות הוא קו אחד. כוכב, עם ה-VPS באמצע, חוסך קו, אבל כשה-VPS נופל שני הלפטופים כבר לא מדברים. במשולש כל זוג מקושר ישירות, ולכן נפילה של לשכה אחת משאירה את האחרות מדברות. החשבון: רשת מלאה של n לשכות היא n(n-1)/2 קישורים, כלומר 3 לשלוש לשכות, 6 לארבע ו-10 לחמש. אצלנו כל לשכה מקושרת לשתי האחרות, וזו הנקודה שבה העלות עוד נמוכה והעמידות כבר מורגשת.

[[diagram: כוכב מול משולש: מה נשאר מחובר כשה-VPS נופל וכשלפטופ נרדם | alt: שני תרשימים זה לצד זה: בכוכב נפילת ה-VPS מנתקת את הלפטופים זה מזה, ובמשולש נשאר קישור ישיר ביניהם]]

## איך מקשרים לשכות, ומה רואים בפועל?

יש שלוש דרכים לקשר לשכות:

- **זיווג מהמסכים:** קוד QR, המצלמה או הצעה שמודבקת כטקסט, ושני המסכים מציגים אותן שש ספרות.
- **הצהרה על מכונה:** לשכה אחת מתקינה את השנייה דרך SSH. כך הוקמה לשכת ה-VPS שלנו.
- **הצטרפות בהצהרה (`DGO_JOIN`):** ללשכה שאין מי שיושב מול המסך שלה.

אפליקציה שרצה בלשכה אחת נפתחת כאריח בקונסול של אחרת. אצלנו [Plane](dgo://article/plane) רץ על מחשב ה-HP ונפתח מהקונסול של ה-MacBook, בכתובת `plane.hp-laptop.console.localhost`.

[[screenshot: מסך הזיווג ב«הרחבת הלשכה»: קוד QR, אפשרות המצלמה ושש הספרות שמוצגות בשני הצדדים | alt: מסך זיווג בין שתי לשכות עם קוד QR ושש ספרות להשוואה]]

[[screenshot: הקונסול של ה-MacBook עם אריח Plane שרץ במחשב ה-HP, בכתובת plane.hp-laptop.console.localhost | alt: קונסול בעברית שבו חלון Plane נפתח מלשכה אחרת]]

שלוש שאלות מעשיות:

- **מה צריך כדי שהקישור יעלה:** [[fact: האם צד אחד בכל זוג חייב פורט UDP פתוח, והאם שני צדדים שמאחורי NAT יכולים להתחבר]].
- **מאיפה פותחים כשלא בבית:** [[fact: הכתובת הציבורית של הקונסול בלשכת ה-VPS והכניסה אליה מטלפון, והאם אריחים של אפליקציות שרצות על ה-MacBook מופיעים בה]].
- **הכניסה לאפליקציה המרוחקת:** [[fact: האם הכניסה האחת (authentik) תקפה גם באריח של לשכה מקושרת]].

:::dgo
המשולש הוא היכולת של «הרחבת הלשכה», אפליקציה של בינה שמקשרת לשכות. מזווגים מהמסכים, מצהירים על מכונה שהלשכה מתקינה דרך SSH, או מצטרפים בהצהרה כשאין מי שיושב מול המסך. הקישור הוא מנהרת WireGuard מוצפנת, עם נתיב TCP כשהרשת חוסמת UDP, ואפליקציה שרצה בלשכה אחת נפתחת כאריח בקונסול של אחרת. ההסתייגות: לשכה על לפטופ מנותקת כשהוא ישן או כבוי, והאחרות ממשיכות לעבוד. DGO חינמית, ובינה סולושנס פיתחה אותה ושחררה אותה ב-19.10.2026 ברישיון AGPL v3.
:::

## איפה מריצים מה, וכמה זה עולה?

מי שצריך לענות כל הזמן, או לקבל בקשות מהאינטרנט, שייך ללשכה שדולקת: ה-VPS. דוגמה: כשכתובת ה-webhook של וואטסאפ של Meta לא עונה, Meta [מנסה שוב](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks/) עד 7 ימים בתדירות יורדת, ועלולות להגיע הודעות כפולות. מי שכבד או פרטי שייך למחשב החזק שבבית או במשרד. מי שיכול לחכות נשאר בלפטופ שנודד.

מה נמדד אצלנו: `vps1` הוא [Hostinger KVM 2](https://www.hostinger.com/vps-hosting) (2 vCPU, 8GB, 100GB, Debian 12, פריז) ומריץ לשכה מלאה ואת האתרים הציבוריים של החברה. לשכת ה-MacBook רצה בתוך מכונה וירטואלית של 4 מעבדים ו-5 GiB. פריז רחוקה מתל אביב 64 אלפיות שנייה ופרנקפורט 48 (WonderNetwork, 19.10.2026).

| פריט | עלות, נכון ל-19.10.2026 |
|---|---|
| DGO | 0 ₪ |
| VPS: KVM 2 | 8.79$ במבצע ו-14.99$ בחידוש: כ-27 עד 47 ₪ לחודש |
| חשמל למחשב שדולק כל הזמן | כל 10 וואט רצופים: כ-4.6 ₪ לחודש, לפי [תעריף של 63.52 אגורות לקוט״ש](https://www.supermarker.themarker.com/bills/guides/electricity-tariff-2026) כולל מע״מ מ-1.7.2026. Mac mini M4 בסיסי, [4 וואט בסרק](https://support.apple.com/103253): כ-1.8 ₪ |
| ענן מנוהל של DGO | אין עדיין |

## מה המשולש לא פותר?

- **לפטופ שנרדם.** לשכה על לפטופ לא זמינה כשהוא ישן או כבוי. ב-Windows יש שכבה נוספת: ברירות המחדל של [WSL](https://learn.microsoft.com/en-us/windows/wsl/wsl-config) הן 15 שניות עד שהפצה לא פעילה נסגרת (`instanceIdleTimeout`) ו-60 שניות למכונה וירטואלית לא פעילה (`vmIdleTimeout`, Windows 11 בלבד); הערך `-1` מבטל את הסגירה. [[fact: האם bbox.cmd מגדירה זאת בעצמה]].
- **תחזוקה פי שלושה.** כל לשכה היא מחשב לעדכן. ב-Linux וב-VPS צריך Docker 28.x: ב-Docker 29 הנתב Traefik 3.3 עולה ולא מוצא נתיבים, והוא עדיין לא נתמך.
- **גיבוי.** גיבוי ושחזור מלאים של נתוני הלשכה נעשים ב«ניהול נתונים», ולפטופ בלי גיבוי הוא פשוט לפטופ אחד שנופל.

## מה עושים עכשיו?

- לשכה ראשונה, על המחשב שדולק הכי הרבה: [התקנת DGO עם Claude](dgo://tutorial/install-dgo-with-claude), או [DGO על VPS זול](dgo://tutorial/dgo-on-a-small-vps) ו[VPS קטן אחד](dgo://article/one-small-vps).
- המנהרה עצמה לעומק: [WireGuard](dgo://article/wireguard).
- איזה מחשב להקצות ללשכה: [חומרה ללשכה](dgo://article/hardware-for-an-office).
