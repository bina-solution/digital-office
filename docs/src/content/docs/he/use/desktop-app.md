---
title: האפליקציה למחשב
description: מורידים את אפליקציית הלשכה הדיגיטלית ל-Windows, ל-macOS או ל-Linux. היא פותחת את הלשכות שלכם בחלון משלה, בלי דפדפן.
---

## למה

האפליקציה מכניסה את הלשכה לרשימת האפליקציות של המחשב: תפריט התחל, Applications, רשימת האפליקציות של Linux. היא פותחת את הלשכה בחלון משלה, ולא צריך דפדפן.

- חלון אחד מחזיק את כל הלשכות שאתם עובדים בהן. כל לשכה מחוברת בנפרד, וסרגל בצד עובר ביניהן.
- סגירת החלון משאירה את האפליקציה במגש (במק, בשורת התפריטים), וההתראות של הלשכה ממשיכות להגיע.

## הורדה

| מחשב | הקובץ |
|---|---|
| Windows 10 או 11, ‏64 ביט | [dgo-desktop-win-x64.exe](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-win-x64.exe) |
| macOS 13 ומעלה, Apple silicon או Intel | [dgo-desktop-mac-universal.dmg](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-mac-universal.dmg) |
| Debian או Ubuntu | [dgo-desktop-linux-amd64.deb](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-linux-amd64.deb) |
| Fedora או RHEL | [dgo-desktop-linux-x86_64.rpm](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-linux-x86_64.rpm) |
| כל Linux אחר | [dgo-desktop-linux-x86_64.AppImage](https://github.com/bina-solution/digital-office/releases/latest/download/dgo-desktop-linux-x86_64.AppImage) |

כל קישור נותן את הגרסה החדשה ביותר. כל הגרסאות נמצאות ב[דף הגרסאות](https://github.com/bina-solution/digital-office/releases).

## התקנה

האפליקציה עוד לא חתומה, ולכן כל מערכת מזהירה פעם אחת, בפעם הראשונה. אחר כך היא נפתחת כמו כל אפליקציה אחרת.

### Windows

1. פתחו את `dgo-desktop-win-x64.exe`.
2. ‏Windows אומר «Windows protected your PC» («‏Windows הגן על המחשב שלך»). לחצו «More info» («מידע נוסף»), ואחר כך «Run anyway» («הפעל בכל זאת»).
3. האפליקציה מותקנת רק בשבילכם, בלי סיסמת מנהל, ונפתחת.

«הלשכה הדיגיטלית» נמצאת עכשיו בתפריט התחל ועל שולחן העבודה.

### macOS

1. פתחו את `dgo-desktop-mac-universal.dmg` וגררו את «Digital Office» אל Applications.
2. פתחו אותה מ-Applications. ‏macOS אומר שאינו יכול לבדוק או לאמת את האפליקציה. סגרו את ההודעה: «Done» («סיום»),
   או «Cancel» («ביטול») ב-macOS 13 ו-14. אל תעבירו אותה לפח.
3. פתחו את System Settings ← Privacy & Security («הגדרות המערכת ← פרטיות ואבטחה»). תחת Security, ליד «Digital Office», לחצו «Open Anyway» («פתח בכל זאת») ואשרו בסיסמה.

מעכשיו היא נפתחת מ-Applications, מ-Launchpad ומה-Dock.

### Linux

- **‏Debian או Ubuntu:**‏ `sudo apt install ./dgo-desktop-linux-amd64.deb`. ‏apt מתקין את מה שהאפליקציה צריכה.
- **‏Fedora או RHEL:**‏ `sudo dnf install ./dgo-desktop-linux-x86_64.rpm`.
- **‏AppImage:** הפכו את הקובץ להרצה (`chmod +x dgo-desktop-linux-x86_64.AppImage`) ופתחו אותו.

החבילה מכניסה את «הלשכה הדיגיטלית» לרשימת האפליקציות. ב-Linux אין אזהרה.

## בפעם הראשונה שהיא נפתחת

האפליקציה שואלת איזו לשכה לפתוח:

- **התחברות ללשכה:** הקלידו את הכתובת שלה. מספיק הדומיין: עבור `example.co.il` האפליקציה מנסה קודם את `console.example.co.il`. אחר כך נכנסים, כמו בדפדפן.
- **הלשכה במחשב הזה:** כשהלשכה פועלת במחשב הזה, האפליקציה פותחת אותה. כשהיא מותקנת אבל לא פועלת, האפליקציה מפעילה אותה.

כדי להוסיף לשכה נוספת אחר כך: `Ctrl Shift N` (במק `Cmd Shift N`). ‏`Ctrl 1` עד `Ctrl 9` עוברים ביניהן.

## איך בודקים שזה עבד

- האפליקציה ברשימת האפליקציות: תפריט התחל ב-Windows, ‏Applications במק, רשימת האפליקציות ב-Linux.
- היא פותחת את הלשכה בחלון משלה, בלי דפדפן מסביב.

## הסרה

- **‏Windows:**‏ Settings ← Apps ← «Digital Office» ← Uninstall («הגדרות ← אפליקציות ← הסר התקנה»).
- **‏macOS:** גררו את «Digital Office» מ-Applications לפח.
- **‏Linux:**‏ `sudo apt remove dgo-desktop`, או `sudo dnf remove dgo-desktop`. ‏AppImage נמחק כמו כל קובץ.

## ראו גם

- [הכרות עם המרכז](/he/use/console)
- [כניסה ומשתמשים](/he/use/sign-in)
