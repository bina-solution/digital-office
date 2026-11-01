# console-url-state — הקישור הוא התצוגה (חוזה הפלטפורמה)

**עיקרון (2026-08-24, הוראת בעלים):** מצב-תצוגה חי ב-URL. קישור שהועתק משחזר בדיוק את מה
שהיה על המסך; מצב-פעולה (בחירת שורות, מודאלים, טיוטות) לעולם לא.

## מה כבר קיים (המקורות שנחקרו)
| רכיב | דפוס | קובץ |
|---|---|---|
| ActionLogPage | הקנוני: "THE WINDOW LIVES IN THE URL" — `win`/`cls`/`dup` ב-URL, כתיבה `replace:true`, ‏localStorage כגיבוי חוצה-דפים, ‏URL גובר כשקיים, דגל `winSubstituted` כשהוחלף | `pages/ActionLogPage.tsx:341-406` |
| DocumentBrowserPage | drill-down כניסה: `status/type/company/source` + `empty/notempty/f_<COL>` — נקרא פעם אחת ("היכן שהגעת"); מ-2026-08-24 גם `q/sort/page/size/view` דו-כיווני + מחיקת פרמטר עם הסרת צ'יפ + כפתור 🔗 העתק קישור | `pages/DocumentBrowserPage.tsx` |
| DataGrid | `initialSearch/initialSorting/initialPageIndex/initialPageSize` — זריעה חד-פעמית, המצב החי נשאר של הגריד | `components/DataGrid.tsx` |
| Console shell | ניתוב hash ‏`#/m/<id>`; ה-embed של אפליקציה יושב תחת `/a/<id>/…` עם `<base>` — נתיב האפליקציה וה-query שלה שקופים לקונסול | `platform-base/console/static/app.js` |

## הכללים
1. **קריאה פעם אחת, כתיבה חד-כיוונית.** ‏URL→state רק במאונט (או popstate); ‏state→URL בכל
   שינוי, ‏`replace:true` + ‏debounce ‏350ms — היסטוריה נשארת כניסה אחת; Back עוזב את הדף,
   לא את ההקשות.
2. **ברירת מחדל = היעדר.** פרמטר שערכו כברירת המחדל נמחק (`page=1`, ‏`size=50`, ‏`view=table`,
   ‏`q=`) — קישורים נקיים.
3. **צ'יפ שהוסר = פרמטר שנמחק.** קישור מועתק לעולם לא טוען סינון שכבר בוטל.
4. **סלקציה אינה URL.** בחירת שורות היא מצב-פעולה; מה שכן משותף הוא הסינון שמגדיר אותה
   (`בחר את כל התואמים` נגזר מהפילטר, לא מרשימת ids).
5. **אוצר מילים אחיד:** `q` חיפוש · `sort=<COL>:<asc|desc>` · `page` (1-based) · `size` ·
   `view=table|cards` · `win` חלונות-זמן · שוויון מתויג: `status/type/company/source` ·
   שלילה: `ne_<COL>=<val>` · **פילטרי-גריד (דו-כיווני, בבעלות הגריד):** `f_<COL>` שוויון ·
   `has_<COL>` מכיל · `in_<COL>=v1,v2` ‏enum · `m_<COL>=YYYY-MM|__no_date__` חודש ·
   `empty=<COL,..>` / `notempty=<COL,..>` היעדר/קיום.
6. **localStorage הוא גיבוי חוצה-דפים בלבד** (כמו `WIN_KEY`) — לעולם לא תחליף ל-URL, ותמיד
   מפסיד לו.
7. **ה-URL הוא הסלקטור (2026-08-24, הוראת בעלים).** אותו סלקטור משמש ניווט, תצוגה
   ופעולות: פרמטרי-הגריד נזרעים ל-`initialFilters` (קריאה-פעם-אחת), נערכים בפופאוברים,
   ונכתבים חזרה כסט שלם (wipe-then-write — אין רוחות של פילטרים שהוסרו); ה-drill המתויג
   (`status/…/ne_`) *נגזר* מה-params על מפתח יציב, לא מועתק ל-state; ו-`selPayload` של
   הסלקטור-היחיד שולח את אותו `combinedFilter` לכל bulk/dispatch/drain/export. מומש
   ב-`DocumentBrowserPage` + ‏`DataGrid.initialFilters` (build 9, 2026-08-24).

## אנטי-דפוסים שנצפו ונאסרו
- כתיבת URL ב-push (זיהום היסטוריה) — תמיד replace למצב-תצוגה.
- קריאת params בכל רנדר וכפייתם על ה-state — מוחק את הקליק הבא של המפעיל (התיעוד ב-drill-down).
- ‏state ששרד רק ב-React — רענון/שיתוף מאבדים את התצוגה (זה מה שתוקן היום).
