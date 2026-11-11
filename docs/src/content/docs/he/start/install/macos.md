---
title: התקנה על macOS
description: להעלות לשכה על Mac — git clone ו-./bbox run. הלשכה מקימה מכונה וירטואלית משלה עם Docker 28, בלי הרשאות מנהל ובלי Docker Desktop.
---

## למה

ב-Mac אין ליבת לינוקס, ו-Docker צריך אחת.
לכן `bbox` מקים מנוע משלו: מכונה וירטואלית של Ubuntu (Lima על Virtualization.framework של Apple) עם Docker CE 28.5.2 נעול על הגרסה.
הכול נוצר בתיקייה `~/.bbox/macos`, בלי הרשאות מנהל, בלי Docker Desktop ובלי Homebrew.

## לפני שמתחילים

- ‏macOS 13 ומעלה.
- שכפלו את המאגר לתיקייה כלשהי מתחת לתיקיית הבית. המנוע רואה את התיקייה באותו נתיב.
- דפדפן: Chrome או Firefox. Safari לפני macOS 26 לא מוצא כתובות `*.localhost`.
- אימג'ים שנבנו רק ל-amd64 צריכים Rosetta. Apple מתקינה אותו:

  ```bash
  softwareupdate --install-rosetta
  ```

- [הדרישות](/he/start/requirements): על Mac עם 8 GB המכונה מקבלת 5 GiB ו-4 מעבדים.

## השלבים

1. שכפלו את המאגר ועברו לתיקייה שלו:

   ```bash
   git clone https://github.com/bina-solution/digital-office
   cd digital-office
   ```

2. העלו את הלשכה:

   ```bash
   ./bbox run
   ```

   בהרצה הראשונה `bbox` מוריד גרסה נעולה ובדוקה של Lima, מקים את המכונה, ומעביר אליה את הפקודה.
   `./bbox install macos` ו-`./bbox engine start` מקימים רק את המנוע. `./bbox run` מקים את המנוע ומעלה את הלשכה.

3. אין קובץ `.env`? ההרצה הראשונה יוצרת אחד: סודות אקראיים, `DEPLOYMENT_NAME=local`, והקצה על פורט 8080.
   אחר כך כתבו בו את שם העסק, `BUSINESS_NAME`.

הכתובות של הלשכה הן `http://<app>.localhost:8080`. ב-macOS תהליך בלי הרשאות לא יכול לפתוח את פורט 80.

**אם כתבתם `.env` ביד:** כל כתובת שהדפדפן פותח (`*_BASE_URL`, `AUTH_EXTERNAL_URL`) חייבת לכלול `:8080`. בלי זה כל אפליקציה שמאחורי הכניסה תחזיר 404, ו-`bbox status` עדיין יראה הכול ירוק.

## איך בודקים שזה עבד

```bash
./bbox engine status
./bbox status
```

נמדד על Mac עם 8 GB: ההרצה הראשונה החמה לקחה כחמש דקות, ו-33 מתוך 33 שירותים היו תקינים.

![הפלט של ./bbox engine status במסוף של Mac](/shots/macos-engine-status.light.he.png)

## המנוע

| פקודה | מה היא עושה |
|---|---|
| `./bbox engine start` | מפעיל את המנוע |
| `./bbox engine stop` | עוצר את המנוע |
| `./bbox engine status` | מצב המנוע |
| `./bbox engine shell` | מסוף בתוך המכונה |
| `./bbox engine doctor` | בדיקת המנוע |

שימו לב: `./bbox engine shell` מפעיל מנוע שעצור. בדקו קודם `./bbox engine status`.

## שינה ומכסה

Mac שנרדם מקפיא את המכונה ואת כל מה שבה.
בהגדרות המסוף («הגדרות מסוף…») יש כרטיס «חשמל ושינה»: לכל מצב (מסך נעול, מכסה סגור) ולכל מקור חשמל, «להמשיך לעבוד» או «לישון».
עם מכסה סגור, Mac נרדם בכל מקרה, אלא אם בעל המחשב מתקין את הכלל הצר שהכרטיס מראה. בלי הצעד הזה: חשמל ומסך חיצוני משאירים Mac סגור עובד.

## מה הלאה

- [אחרי ההתקנה](/he/start/after-install)
- [השעה הראשונה](/he/start/first-hour)
