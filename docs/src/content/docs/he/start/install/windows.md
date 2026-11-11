---
title: התקנה על Windows
description: להעלות לשכה על Windows — WSL, git clone, bbox.cmd install windows ו-bbox.cmd run. הלשכה רצה בתוך WSL עם Docker משלה, לא עם Docker Desktop.
---

## למה

המנוע של Docker רץ רק על לינוקס. ב-Windows, WSL2 הוא הלינוקס.
הלשכה מתקינה בתוך WSL את Docker CE משלה, מגרסה 28.
Docker Desktop לא בשימוש, בין אם הוא מותקן ובין אם לא.
זו הדרך היחידה להריץ את הלשכה על Windows.

## לפני שמתחילים

- ‏Windows עם WSL2 וההפצה `Ubuntu`. פעם אחת במחשב: פתחו PowerShell כמנהל והריצו את הפקודה הבאה, הפעילו את המחשב מחדש, ופתחו את Ubuntu פעם אחת.

  ```
  wsl --install -d Ubuntu
  ```

- `git` ב-Windows.
- שורת פקודה רגילה: `CMD` או PowerShell.

## השלבים

1. שכפלו את המאגר לתיקייה כלשהי בכונן `C:` ועברו אליה:

   ```
   git clone https://github.com/bina-solution/digital-office C:\path\you\like\digital-office
   cd C:\path\you\like\digital-office
   ```

2. הכינו את WSL בשביל הלשכה:

   ```
   bbox.cmd install windows
   ```

   הפקודה מכינה את WSL ומתקינה בתוכו `git` ו-Docker. היא יכולה לבקש `wsl --shutdown` והרצה שנייה שלה.

3. קובץ ההגדרות `.env` הוא שלכם, כמו על לינוקס: ראו [התקנה על לינוקס](/he/start/install/linux), שלב 3.

4. העלו את הלשכה:

   ```
   bbox.cmd run
   ```

   `bbox.cmd` מעביר את הפקודה ל-`bbox` שבתוך ההפצה `Ubuntu` של WSL, על אותה תיקייה בדיוק. אין עותק שני לסנכרן.
   ב-`run` הוא גם רושם ב-Windows משימה מתוזמנת (Task Scheduler) שמשאירה את WSL ער, כדי שהלשכה תחזור לבד אחרי הפעלה מחדש.

## איך בודקים שזה עבד

```
bbox.cmd status
```

‏WSL2 מעביר את `localhost`, כך שהקצה שבתוך WSL עונה לדפדפן של Windows ישירות. אם הכתובות ב-`.env` הן `*.localhost`, פתחו את `console.localhost`.

> TODO-product: הכתובת של לשכת Windows. התבנית `.env.ex` גוזרת `console.<slug>.digital-office.co.il`, לא `*.localhost`, ואין מקור שאומר איך לשכת Windows בלי דומיין נפתחת בדפדפן.

![חלון CMD עם bbox.cmd run באמצע הריצה](TODO-shot: חלון CMD ב-Windows, bbox.cmd run באמצע הריצה; ערכה בהירה)

## אם משהו לא עובד

- **`Error code: Wsl/Service/0x8007274c`:** ‏Windows לא קיבל תשובה מהמכונה של WSL בזמן, בדרך כלל בעבודה כבדה. זו לא תקלה בלשכה. נסו שוב.
- **Windows נשאר בלי זיכרון אחרי עבודה כבדה:** ‏WSL לא מחזיר זיכרון לבד. `wsl --shutdown` מחזיר אותו מיד, אבל עוצר את כל מה שרץ ב-WSL, כולל הלשכה. עשו את זה רק בין עבודות.

## לשכה שלשכה אחרת מתקשרת אליה

במצב הרשת הרגיל של WSL ‏(NAT) שום דבר ברשת לא מגיע ללשכה. היא יכולה רק להתקשר החוצה.
כדי שלשכה אחרת תתקשר אליה, צריך את מצב הרשת `mirrored`, ב-Windows 11 22H2 ומעלה:

```
bbox.cmd dialable -Check
bbox.cmd dialable
bbox.cmd dialable -Undo
```

הראשונה רק קוראת. השנייה מסבירה מה תעשה ומבקשת `YES` מוקלד. השלישית מחזירה את המצב הקודם. המעבר מפעיל מחדש את WSL.

## מה הלאה

- [אחרי ההתקנה](/he/start/after-install)
- [השעה הראשונה](/he/start/first-hour)
