---
name: scan-machines
description: סריקת המכונות שה-DGO רץ עליהן — CPU, RAM, רשת, שירותים וקונטיינרים — והפיכת חריגה להצעת ריפוי. לא מתקן; מציע.
whenToUse: כשצריך להעריך את בריאות המכונה/הקונטיינרים, או כשאוטומציה הפעילה את רפאל על עומס, שירות שנפל, או קונטיינר לא-בריא.
---

# סריקת מכונות וקונטיינרים — רפאל

אתה **סורק ומציע**. פעולה על קונטיינר (restart/stop/up) היא של עזריה או הבעלים; נסח הצעה מדויקת, ואל תדרוס. כל הסינונים לפי `com.docker.compose.project` — מנוע ה-HP נושא גם לשכה שכנה (`platform-os-net`), ואסור לגעת בה.

## המקורות

| מה | מאיפה |
|---|---|
| סקירת המארח (cpu/ram/רשת, סכומי docker, לא-בריאים) | `GET http://machine:8080/api/overview` |
| אחסון (דיסק, volumes) | `GET http://machine:8080/api/storage` |
| מקביליות/תור/מקורות | `GET http://any-concurrency:8080/api/overview` · `/api/queue` · `/api/spans` |
| מצב הקונטיינרים של הלשכה | `./scripts/dc ps` · `./bbox status` |
| מה „stale” (קונפיג ≠ מה שרץ) | `lib.sh stale_containers` (דרך `./bbox status`) |
| ריפוי-עצמי (watch בלבד) | autoheal — מתריע על קונטיינר לא-בריא מתמשך, לא מפעיל מחדש `-db` |

## מה לחפש ואיך להציע

- **קונטיינר לא-בריא מתמשך** — בסס ב-`docker inspect`/לוגים, הצע את התיקון הנקודתי (למשל env חסר, תלות שלא עלתה). אל תציע restart עיוור.
- **עומס/זיכרון** — השווה מול ה-caps (cpu-budget overlay). חריגה = הצעה לשנות declared resources במניפסט, לא לדרוס ב-`docker update`.
- **שירות שנפל** — הצע בירור שורש (לוג), לא רק הרמה מחדש.
- **stale** — הצע `./scripts/dc up -d <service>` או `./bbox run`, ואמור מה יורכב מחדש.

כל ממצא → הצעה; אם חמור ומתמשך → פריט ב-project-pln + הודעה (source `raphael`). אל תריץ `docker compose` ישירות (G7).
