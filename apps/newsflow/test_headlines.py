"""What is a headline — the filter that keeps the office's news feed from becoming a page's own furniture.

Run: python3 apps/newsflow/test_headlines.py
The cases are not invented: every DROP below was measured in the store on 2026-11-05, led the Israel feed in
the owner's own screenshot (#180), and is kept here so the next change cannot quietly bring it back.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("newsflow_main", os.path.join(HERE, "main.py"))
nf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nf)

#: (title, url) — furniture: a job card, a promo, a paywall's pitch, a section label.
DROP = [
    ("Fresh Graduate Management Training Program (Onsite) Deliveree On-Demand Logistics",
     "https://www.techinasia.com/jobs/2016e69e-1b2e-4b73-a651-47df2f83dbc5?ref=tiahome"),
    ("Product Owner Daya Wira Performa IDR 6M – 11M", "https://www.techinasia.com/jobs/5a3f2364-d05a"),
    ("Digital Marketing Specialist Boleh Dicoba Digital", "https://www.techinasia.com/jobs/df12c354"),
    ("עקוב אחר כל השווקים ב-TradingView", "https://www.calcalist.co.il/calcalistech/article/x"),
    ("Support Tol and remove all ads", "https://www.timesofisrael.com/"),
    ("COMMUNITY (MEMBERS ONLY)", "https://www.timesofisrael.com/"),
    ("View our media library", "https://www.kan.org.il/"),
    ("{ גיוסי הון ואקזיטים }", "https://www.geektime.co.il/"),
    ("Contact us", "https://www.globes.co.il/"),
    ("הצצה יוקרתית מה הקשר בין מותג וויסקי לפורמולה 1? בשיתוף GWS", "https://www.mako.co.il/x"),
    ("whatsapp מעבר לאתר חיצוני", "https://innovationisrael.org.il/"),   # a link interstitial led the front page
]

#: (title, url) — real news, and the sentence the reader must see after the card's clock is peeled off.
KEEP = [
    ("ילדה בת 6 נפצעה באורח בינוני לאחר שככל הנראה נעקצה על ידי עקרב צהוב בבאר שבע",
     "https://www.mako.co.il/news-x", "ילדה בת 6 נפצעה באורח בינוני"),
    ("לפני 54 דקות גנב קונסולת פלייסטיישן ואוזניות: תושב קרית עקרון בן 46 נאשם",
     "https://www.mako.co.il/news-y", "גנב קונסולת פלייסטיישן"),
    ("05:06 ילדה בת 6 נפצעה באורח בינוני לאחר שנעקצה על ידי עקרב צהוב בבאר שבע",
     "https://www.mako.co.il/news-z", "ילדה בת 6 נפצעה"),
    ("FEATURED PREMIUM Is it a neocloud? A hyperscaler? Sea’s AI move puzzles investors",
     "https://www.techinasia.com/neocloud-hyperscaler", "Is it a neocloud?"),
    ("בלעדי | פעילות ההשכרה של ביי אנד דרייב תיסגר, עשרות רכבים יוצעו למכירה",
     "https://www.calcalist.co.il/local_news/a", "פעילות ההשכרה של ביי אנד דרייב"),
    ("1h ago SG AI startup Featherless to add MiniMax M3.1 Flash for coding",
     "https://www.techinasia.com/posts/x", "SG AI startup Featherless"),
    ("Containers & Kubernetes Powering open infrastructure for autonomous agents By Drew Bradstock • 11-minute read",
     "https://cloudblog.withgoogle.com/x", "Containers & Kubernetes Powering"),
    ("חסימות ענק בנתיבי איילון בסוף השבוע: הכביש ייסגר בשני הכיוונים",
     "https://www.calcalist.co.il/local_news/b", "חסימות ענק בנתיבי איילון"),
    # the clock and the reporter's name glued to the END of the sentence are the card's furniture too
    ("הכוכבת חושפת \"הייתי בת 11, הציעו לי קוקאין במסיבות סיום הצילומים\" 09:26 מיכל דאב",
     "https://www.mako.co.il/x", "הכוכבת חושפת"),
    # cyber news that names an external link is news, not an interstitial (DGO-2030, the second reader)
    ("הונאה חדשה: לחיצה על קישור חיצוני בוואטסאפ מרוקנת את חשבון הבנק",
     "https://www.ynet.co.il/digital/technews/article/x", "הונאה חדשה: לחיצה על קישור חיצוני"),
]


#: «ראשי» — a business news app does not lead with restaurants because they happened to be newest.
#: (Each row is (id, category) in the newest-first order SQL returned.)
FRONT_CASES = [
    ([("a", "content"), ("b", "tech"), ("c", "marketing"), ("d", "market-il")],
     ["b", "d", "a", "c"]),
    ([("a", "creative"), ("b", "ai"), ("c", "brand")], ["b", "a", "c"]),
    ([("a", "israel"), ("b", "law"), ("c", "video-ai"), ("d", "vc")], ["a", "b", "d", "c"]),
]


def main() -> int:
    bad = 0
    for title, url in DROP:
        if nf.is_headline(title, url):
            bad += 1
            print("FAIL kept furniture:", title[:70], url[:50])
    for title, url, want in KEEP:
        got = nf.clean_title(title)
        if not nf.is_headline(title, url):
            bad += 1
            print("FAIL dropped news:", title[:70])
        elif want not in got:
            bad += 1
            print("FAIL prefix not peeled:", title[:50], "->", got[:60])
    for rows, want in FRONT_CASES:
        got = [r["id"] for r in nf.order_front([{"id": i, "category": c} for i, c in rows])]
        if got != want:
            bad += 1
            print("FAIL front order:", got, "!=", want)
    print(f"{len(DROP) + len(KEEP) + len(FRONT_CASES)} cases, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
