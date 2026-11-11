package il.co.digitaloffice.app;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * This phone's office as its status screen shows it (DGO-1723, the owner: «שקוף בדיוק מה קורה מה רץ»): read once,
 * off the main thread, into one {@link Now}. The core says what it runs in run/status.json (native/status.go);
 * «מכולות» — the office's machine, where every app that needs a container runs — is told from the app's own
 * state: whether the owner installed it, its fetch and unpack, its engine, its refusal. Hebrew on the screen; the
 * app's English stays in the log.
 *
 * <p>«מכולות» is installed by the owner's button and nothing else: a phone that only opened the app never fetches
 * the machine's ~2 GB by itself ({@link #chosen}). A machine already on the phone is installed.
 */
final class Office {

    private Office() {
    }

    /** The refusal NativeService writes while «מכולות» is not installed: serve.go and {@link #said} know its words. */
    static final String NOT_INSTALLED = "containers are not installed: the owner installs them from the status screen";

    /** The owner's choice to install «מכולות»: files/containers-chosen (removed: the install stops). */
    static File chosenFile(Context c) {
        return new File(c.getFilesDir(), "containers-chosen");
    }

    /** «מכולות» is installed here, or its install was asked for: the machine may be fetched and started. */
    static boolean chosen(Context c) {
        return chosenFile(c).isFile() || EngineService.guest(c).exists();
    }

    /** The owner's «התקנת מכולות»: remembered, and the core's ask answered anew (NativeService.wantNow). */
    static void install(Context c) throws IOException {
        File f = chosenFile(c);
        try (OutputStream o = new FileOutputStream(f)) {
            o.write((System.currentTimeMillis() / 1000 + "\n").getBytes(StandardCharsets.UTF_8));
        }
        NativeService.wantNow(c);
    }

    /**
     * The owner's «הפעלה» / «לנסות שוב» while no core runs: files/containers-ask, which the core's start answers
     * (NativeService.run) — an office whose apps run nowhere in the machine would otherwise start the base alone.
     */
    static File askFile(Context c) {
        return new File(c.getFilesDir(), "containers-ask");
    }

    /** «עצירת ההתקנה»: the fetch under way sees it is no more wanted and stops; what came down stays. */
    static void stopInstall(Context c) {
        chosenFile(c).delete();
    }

    // ── the snapshot ────────────────────────────────────────────────────────────────────────────────

    static final int OK = 0, RUN = 1, BAD = 2, OFF = 3;

    /** «מכולות»: not installed, installing (fetch/unpack), starting, running, stopped, or failed (a reason). */
    static final int C_NONE = 0, C_INSTALLING = 1, C_STARTING = 2, C_RUNNING = 3, C_STOPPED = 4, C_FAILED = 5;

    static final class Part {
        final String name;
        final int tone;

        Part(String name, int tone) {
            this.name = name;
            this.tone = tone;
        }
    }

    static final class AppRow {
        String id, name, said = "", state = "";
        int tone = OFF;
    }

    static final class Now {
        // the line at the top
        String head = "", say = "", pill = "";
        int tone = RUN;
        // the base: the core's own parts
        boolean core;
        List<Part> base = new ArrayList<>();
        String baseMeta = "";
        // «מכולות»
        int containers = C_NONE;
        String cMeta = "", cPill = "", problem = "", stepNow = "";
        int cTone = OFF, permille = -1;
        List<String[]> facts = new ArrayList<>();   // {what, value}
        String action = "";                          // the one action of a failure: "room", "again", "wifi"
        boolean pairable;                            // AVF possible here once the owner grants it: a speed-up
        // the apps the office runs on «מכולות»
        List<AppRow> apps = new ArrayList<>();
        String appsMeta = "", appsPill = "";
        int appsTone = OFF;
        // the newest lines, and the phone
        String log = "", device = "";
    }

    private static long lastDone = -1, lastAt;
    private static double speed;   // bytes a second, smoothed across reads

    /** Everything the screen shows, now. Off the main thread: it reads files and asks Android. */
    static Now read(Context c) {
        Now n = new Now();
        File run = new File(c.getFilesDir(), "run");
        JSONObject st = status(new File(run, "status.json"));
        n.core = NativeService.running() && st != null;

        // the base — the core's parts, as it says them
        Map<String, String> names = new HashMap<>();
        names.put("forward-auth", "כניסה");
        names.put("edge", "שער הלשכה");
        names.put("console", "המרכז");
        names.put("control", "ניהול אפליקציות");
        int up = 0, all = 0;
        if (st != null) {
            JSONArray base = st.optJSONArray("base");
            for (int i = 0; base != null && i < base.length(); i++) {
                JSONObject p = base.optJSONObject(i);
                if (p == null) continue;
                String id = p.optString("id");
                boolean ok = p.optBoolean("up");
                n.base.add(new Part(names.containsKey(id) ? names.get(id) : id, ok ? OK : RUN));
                all++;
                if (ok) up++;
            }
        } else {
            for (String id : new String[]{"forward-auth", "edge", "console", "control"}) n.base.add(new Part(names.get(id), NativeService.running() ? RUN : OFF));
            all = n.base.size();
        }
        n.baseMeta = n.core ? "רץ ישירות בטלפון" : NativeService.running() ? "עולה עכשיו" : "כבוי";

        // «מכולות»
        String refused = text(new File(run, "machine-refused"));
        String step = text(new File(run, "machine-step"));
        String cstate = st == null ? "" : st.optJSONObject("containers") == null ? "" : st.optJSONObject("containers").optString("state");
        String g = Guest.stage;
        boolean installed = EngineService.guest(c).exists();
        Virt.Choice v = Virt.choose(c);
        boolean hardware = v.hardware;
        n.pairable = v.pairable();
        String engine = hardware ? "חומרה · מהיר" : EngineService.hasQemu(c) ? "מדומה · איטי" : "אין מנוע בטלפון הזה";
        if (!g.isEmpty() && !"boot".equals(g)) {
            n.containers = C_INSTALLING;
            long done = Guest.done, total = Math.max(1, Guest.total), at = System.currentTimeMillis();
            if (lastDone >= 0 && at > lastAt && done >= lastDone) {
                double s = (done - lastDone) * 1000.0 / (at - lastAt);
                speed = speed <= 0 ? s : speed * 0.7 + s * 0.3;
            }
            lastDone = done;
            lastAt = at;
            int pct = (int) Math.min(100, done * 100 / total);
            n.permille = (int) Math.min(1000, done * 1000 / total);
            boolean fetch = "fetch".equals(g);
            n.cPill = (fetch ? "הורדה · " : "פריסה · ") + pct + "%";
            n.cMeta = "מותקנת עכשיו";
            n.stepNow = fetch ? "fetch" : "unpack";
            n.facts.add(new String[]{fetch ? "ירד" : "נפרס", size(done) + " / " + size(total)});
            n.facts.add(new String[]{"מהירות", speed > 0 ? size((long) speed) + "/s" : "—"});
            n.facts.add(new String[]{"נשאר", speed > 0 ? about((long) ((total - done) / speed)) : "—"});
        } else {
            lastDone = -1;
            speed = 0;
            if (!refused.isEmpty() && refused.startsWith("containers are not installed")) {
                n.containers = C_NONE;
            } else if (!refused.isEmpty()) {
                n.containers = C_FAILED;
                n.problem = said(refused);
                n.action = refused.contains("GB free") ? "room" : refused.contains("metered") ? "wifi" : "again";
            } else if ("up".equals(cstate)) {
                n.containers = C_RUNNING;
            } else if (EngineService.running() || "step".equals(cstate) || "wanted".equals(cstate) || !step.isEmpty()) {
                n.containers = installed || EngineService.running() ? C_STARTING : chosen(c) ? C_INSTALLING : C_NONE;
                if (n.containers == C_INSTALLING) n.stepNow = "fetch";
            } else {
                n.containers = installed ? C_STOPPED : chosen(c) ? C_INSTALLING : C_NONE;
                // chosen, nothing under way yet: the fetch reads its list and hashes what it kept before its first byte
                if (n.containers == C_INSTALLING) n.stepNow = "fetch";
            }
        }
        String console = MainActivity.tail(EngineService.console(c), 256 << 10);
        Map<String, String> report = report(console);
        boolean bboxUp = MainActivity.runEnded(console);
        // «NOT up:» ended the run too (DGO-995), but nothing of it may read as running: an app with no row of its
        // own is not «פועלת» after a fatal end
        boolean bboxFatal = MainActivity.runFatal(console);
        switch (n.containers) {
            case C_NONE:
                n.cTone = OFF;
                n.cPill = "לא מותקנת";
                n.cMeta = "מריצה את כל שאר האפליקציות";
                n.facts.add(new String[]{"הורדה", Guest.fetchable() || Guest.inApk(c) ? "כ-2 GB" : "לא בגרסה הזו"});
                n.facts.add(new String[]{"מקום", size(Guest.ROOM)});
                n.facts.add(new String[]{"מנוע בטלפון", engine});
                break;
            case C_INSTALLING:
                n.cTone = RUN;
                if (n.cPill.isEmpty()) n.cPill = "מתחילה";
                if (n.cMeta.isEmpty()) n.cMeta = "מותקנת עכשיו";
                break;
            case C_STARTING:
                n.cTone = RUN;
                n.cPill = "עולה";
                n.stepNow = "engine";
                // the stage it is at, or where it is stuck — never a boot log on the card (DGO-1818: the owner
                // read a cloud-init log for minutes while the machine sat in emergency mode)
                String[] stage = EngineService.running() ? bootStage(console) : null;
                if (stage != null && stage[0].equals("stuck")) {
                    n.cTone = BAD;
                    n.cPill = "תקועה";
                    n.cMeta = "המכונה תקועה: " + stage[1];
                    break;
                }
                n.cMeta = (hardware ? "מנוע חומרה" : "מנוע מדומה") + " · " + (stage == null ? "מתחילה"
                        : bboxFatal ? "האפליקציות עלו עם תקלה"
                        : "שלב " + stage[0] + " מתוך " + stage[1] + ": " + stage[2]);
                break;
            case C_RUNNING:
                n.cTone = OK;
                n.cPill = "פועלת";
                int count = report.size();
                n.cMeta = (hardware ? "מנוע חומרה" : "מנוע מדומה") + (count > 0 ? " · " + count(count, "מכולה אחת רצה", "מכולות רצות") : "");
                n.facts.add(new String[]{"מנוע", hardware ? "חומרה" : "מדומה"});
                n.facts.add(new String[]{"דיסק", size(used(EngineService.guest(c)))});
                n.facts.add(new String[]{"פנוי בטלפון", size(c.getFilesDir().getUsableSpace())});
                break;
            case C_STOPPED:
                n.cTone = OFF;
                n.cPill = "כבויה";
                n.cMeta = "מותקנת · עולה כשאפליקציה צריכה אותה";
                break;
            default:
                n.cTone = BAD;
                n.cPill = "נעצרה";
                n.cMeta = installed ? "המנוע לא עולה" : "ההתקנה נעצרה";
        }

        // the apps that run on «מכולות», each with what is known of it
        JSONArray apps = st == null ? null : st.optJSONArray("apps");
        int ok = 0, coming = 0, bad = 0;
        for (int i = 0; apps != null && i < apps.length(); i++) {
            JSONObject a = apps.optJSONObject(i);
            if (a == null) continue;
            AppRow r = new AppRow();
            r.id = a.optString("id");
            r.name = title(c, r.id);
            switch (n.containers) {
                case C_RUNNING:
                case C_STARTING:
                    appState(r, report, bboxUp && !bboxFatal, n.containers == C_RUNNING && console.lastIndexOf("dgo-office-report: clean") > console.lastIndexOf("dgo-office-report: the containers"));
                    break;
                case C_INSTALLING:
                    r.said = "תעלה מעצמה כשהמכולות מוכנות";
                    r.state = "מחכה";
                    r.tone = RUN;
                    break;
                case C_FAILED:
                    r.said = "מחכה למכולות";
                    r.state = "מחכה";
                    r.tone = OFF;
                    break;
                case C_STOPPED:
                    r.said = "עולה כשפותחים אותה";
                    r.state = "כבויה";
                    r.tone = OFF;
                    break;
                default:
                    r.said = "אחרי התקנת מכולות";
            }
            if (r.tone == OK) ok++;
            if (r.tone == RUN) coming++;
            if (r.tone == BAD) bad++;
            n.apps.add(r);
        }
        if (n.containers == C_RUNNING || n.containers == C_STARTING) {
            n.appsMeta = "לחיצה על שורה — הלוג שלה";
            n.appsPill = coming > 0 ? count(coming, "אחת עולה", "עולות") : n.apps.isEmpty() ? "" : ok + "/" + n.apps.size() + " פועלות";
            n.appsTone = bad > 0 ? BAD : coming > 0 || ok < n.apps.size() ? RUN : OK;
        } else {
            n.appsMeta = n.containers == C_INSTALLING ? "יעלו מעצמן כשהמכולות מוכנות" : n.containers == C_FAILED ? "מחכות למכולות" : "רצות על מכולות";
        }

        // the line at the top: the one thing that is true now
        if (!NativeService.running()) {
            n.head = "הלשכה כבויה";
            n.say = "פתיחת הלשכה מפעילה את הבסיס בתוך שניות.";
            n.tone = OFF;
            n.pill = "כבויה";
        } else if (!n.core || up < all) {
            n.head = "הבסיס עולה";
            n.say = "עוד רגע נפתחת הלשכה.";
            n.tone = RUN;
            n.pill = "עולה";
        } else if (n.containers == C_NONE) {
            n.head = "הלשכה פועלת";
            n.say = "הבסיס פועל בטלפון. כדי להריץ את שאר האפליקציות — מתקינים «מכולות».";
            n.tone = OK;
            n.pill = "פועלת";
        } else if (n.containers == C_INSTALLING) {
            n.head = "מתקין מכולות";
            n.say = "הבסיס פועל ואפשר להשתמש בלשכה. המכולות יורדות ברקע, גם כשהמסך כבוי.";
            n.tone = RUN;
            n.pill = "מתקינה";
        } else if (n.containers == C_STARTING) {
            n.head = "האפליקציות עולות";
            n.say = "הבסיס פועל. המכולות עולות, והאפליקציות נפתחות מעצמן כשהן מוכנות.";
            n.tone = RUN;
            n.pill = "עולה";
        } else if (n.containers == C_FAILED) {
            n.head = installed ? "המכולות לא עולות" : "ההתקנה נעצרה";
            n.say = "הבסיס פועל. " + n.problem;
            n.tone = BAD;
            n.pill = "דורשת פעולה";
        } else if (n.containers == C_STOPPED) {
            n.head = "הלשכה פועלת";
            n.say = "הבסיס פועל. המכולות כבויות, ועולות כשפותחים אפליקציה שצריכה אותן.";
            n.tone = OK;
            n.pill = "פועלת";
        } else {
            n.head = "הכל פועל";
            n.say = "הבסיס ו«מכולות» פועלים" + (n.apps.isEmpty() ? "." : ", ו" + count(n.apps.size(), "אפליקציה אחת", "אפליקציות") + " עליהן.");
            n.tone = OK;
            n.pill = "פועלת";
        }

        // the newest lines, each with where it came from
        StringBuilder log = new StringBuilder();
        for (String l : lastLines(MainActivity.tail(NativeService.log(c), 8 << 10), 6)) log.append("[בסיס] ").append(l).append('\n');
        if (!console.isEmpty()) for (String l : lastLines(console, 6)) log.append("[מכולות] ").append(l).append('\n');
        n.log = log.toString().trim();

        String net = "אין רשת";
        ConnectivityManager cm = c.getSystemService(ConnectivityManager.class);
        NetworkCapabilities caps = cm == null || cm.getActiveNetwork() == null ? null : cm.getNetworkCapabilities(cm.getActiveNetwork());
        if (caps != null) net = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ? "Wi-Fi" : caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ? "סלולרי" : "רשת";
        n.device = Build.MODEL + " · Android " + Build.VERSION.RELEASE + " · פנוי " + size(c.getFilesDir().getUsableSpace()) + " · " + net;
        return n;
    }

    /** An app's state from the machine's own report: the containers whose names carry its id. */
    private static void appState(AppRow r, Map<String, String> report, boolean bboxUp, boolean clean) {
        if (clean) {
            r.state = "פועלת";
            r.tone = OK;
            return;
        }
        String worst = null;
        for (Map.Entry<String, String> e : report.entrySet()) {
            if (!e.getKey().contains(r.id)) continue;
            String s = e.getValue();
            String w = s.startsWith("Up") && s.contains("unhealthy") ? "bad"
                    : s.startsWith("Up") && s.contains("health: starting") ? "run"
                    : s.startsWith("Up") ? "ok"
                    : s.startsWith("Exited (0)") ? "ok"
                    : s.startsWith("Restarting") || s.startsWith("Exited") || s.startsWith("Dead") ? "bad" : "run";
            if (worst == null || rank(w) > rank(worst)) worst = w;
        }
        if (worst == null) {
            r.state = bboxUp ? "פועלת" : "עולה";
            r.tone = bboxUp ? OK : RUN;
            r.said = bboxUp ? "" : "המכולות מפעילות אותה";
        } else if ("bad".equals(worst)) {
            r.state = "לא תקינה";
            r.tone = BAD;
            r.said = "הלוג שלה אומר למה";
        } else if ("run".equals(worst)) {
            r.state = "עולה";
            r.tone = RUN;
            r.said = "בודקת תקינות";
        } else {
            r.state = "פועלת";
            r.tone = OK;
        }
    }

    private static int rank(String w) {
        return "bad".equals(w) ? 2 : "run".equals(w) ? 1 : 0;
    }

    /**
     * Where the machine's boot is, from its console (DGO-1818): {"stage", "of", "what"} — «שלב 3 מתוך 5: המערכת עולה»
     * — or {"stuck", "why"} once the console says it cannot go on (an emergency shell, a kernel panic). Each stage is
     * done when the line that ends it is on the console; a later line implies the earlier stages.
     */
    static String[] bootStage(String console) {
        if (console.contains("You are in emergency mode") || console.contains("Reached target emergency.target"))
            return new String[]{"stuck", "מצב חירום — דיסק או שירות שהמכונה חיכתה לו לא הגיע (DGO-1818)"};
        if (console.contains("Kernel panic"))
            return new String[]{"stuck", "הליבה של המכונה קרסה בעלייה"};
        String[][] stages = {
                // {what is happening, the lines that say it is over — any one of them}. The card reads the console's
                // tail, so a stage that lasts (the apps') is also proven by lines its own unit keeps printing: once
                // bbox's output has pushed «Starting dgo-office.service» out of the tail, its [bbox] lines remain
                {"הקושחה וטעינת הליבה", "Linux version", "Booting Linux"},
                {"הליבה עולה", "Welcome to ", "systemd[1]:"},
                {"המערכת עולה", "Started docker.service"},
                {"Docker עולה", "Starting dgo-office.service", "[bbox]", "dgo-office-report:"},
                {"האפליקציות עולות"},                     // over when the run ended (MainActivity.runEnded)
        };
        int done = 0;
        for (int i = stages.length - 1; i >= 0 && done == 0; i--) {
            if (i == stages.length - 1) {
                if (MainActivity.runEnded(console)) done = i + 1;
                continue;
            }
            for (int k = 1; k < stages[i].length; k++) {
                if (console.contains(stages[i][k])) { done = i + 1; break; }
            }
        }
        int now = Math.min(done, stages.length - 1);
        return new String[]{String.valueOf(now + 1), String.valueOf(stages.length), stages[now][0]};
    }

    /** The containers the machine last listed (dgo-office-report): name → Docker's status. */
    static Map<String, String> report(String console) {
        Map<String, String> m = new java.util.LinkedHashMap<>();
        int at = console.lastIndexOf("dgo-office-report: the containers");
        if (at < 0) return m;
        for (String l : console.substring(at).split("\n")) {
            if (l.startsWith("dgo-office-report:")) {
                if (!m.isEmpty()) break;
                continue;
            }
            int colon = l.indexOf(": ");
            if (colon > 0) m.put(l.substring(0, colon).trim(), l.substring(colon + 2).trim());
        }
        return m;
    }

    private static final Map<String, String> TITLES = new java.util.concurrent.ConcurrentHashMap<>();

    /**
     * An app's Hebrew title from the office root's manifest (files/office/…/<id>/app.json), else its id — read once
     * per process: the office root changes only with an APK, which starts a new one.
     */
    static String title(Context c, String id) {
        String had = TITLES.get(id);
        if (had != null) return had;
        String t = readTitle(c, id);
        TITLES.put(id, t);
        return t;
    }

    private static String readTitle(Context c, String id) {
        File office = new File(c.getFilesDir(), "office");
        for (String layer : new String[]{"apps", "platform-base"}) {
            File f = new File(office, layer + "/" + id + "/app.json");
            if (!f.isFile()) continue;
            try {
                JSONObject t = new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8)).optJSONObject("title");
                String he = t == null ? "" : t.optString("he");
                if (!he.isEmpty()) return he;
            } catch (Exception ignored) {
                // its id says it
            }
        }
        return id;
    }

    /**
     * The app's refusal (NativeService's say) in Hebrew — the sentence the owner reads, and what to do; the same
     * refusals serve.go's waiting page tells (absentSays). A refusal not known here is told as one.
     */
    static String said(String why) {
        java.util.regex.Matcher m;
        if ((m = java.util.regex.Pattern.compile("phone has (\\d+) GB free, and the machine needs (\\d+) GB").matcher(why)).find()) {
            return "אין מספיק מקום בטלפון: פנויים " + m.group(1) + " GB, והמכולות צריכות " + m.group(2) + " GB. מה שכבר ירד נשמר.";
        }
        if ((m = java.util.regex.Pattern.compile("(\\d+) GB to fetch and the phone's network is metered").matcher(why)).find()) {
            return "הטלפון על חבילת גלישה, והמכולות (" + m.group(1) + " GB) יורדות רק ב-Wi-Fi. מתחברים ל-Wi-Fi וזה ממשיך.";
        }
        if (why.contains("not on this phone yet") || why.contains("carries no machine")) {
            return "בגרסה הזו של האפליקציה אין מכולות להתקנה. צריך גרסה חדשה של האפליקציה.";
        }
        if (why.contains("own office is running on this phone")) {
            return "הלשכה הישנה של הטלפון עוד רצה. עוצרים אותה מההתראה שלה, ואז מנסים שוב.";
        }
        if (why.contains("three times running")) {
            return "המכולות נעצרו מיד אחרי שעלו, שלוש פעמים ברצף. הלוג של המנוע אומר למה.";
        }
        if (why.contains("on no network")) {
            return "הטלפון לא מחובר לרשת. כשיתחבר ל-Wi-Fi ההתקנה ממשיכה.";
        }
        if (why.contains("could not be fetched") || why.contains("could not be unpacked")) {
            return "ההורדה או הפריסה נכשלה. מה שכבר ירד נשמר, ואפשר לנסות שוב.";
        }
        if (why.contains("AVF cannot run")) {
            return "בטלפון הזה אין מנוע שיכול להריץ את המכולות עדיין.";
        }
        if (why.contains("Android did not let")) {
            return "Android לא נתן למכולות לעלות כשהאפליקציה ברקע. פותחים את האפליקציה והן עולות.";
        }
        return "המכולות לא עולות. הלוג של המנוע אומר למה.";
    }

    /**
     * The notification's one line (the mock's «הלשכה פועלת · … · מכולות: …»): cheap — files only, no Android
     * service asked — so the core's service says it every few seconds.
     */
    static String line(Context c) {
        File run = new File(c.getFilesDir(), "run");
        JSONObject st = status(new File(run, "status.json"));
        if (st == null) return "הבסיס עולה";
        JSONArray apps = st.optJSONArray("apps");
        int n = apps == null ? 0 : apps.length();
        JSONObject ct = st.optJSONObject("containers");
        String state = ct == null ? "" : ct.optString("state");
        String refused = text(new File(run, "machine-refused"));
        String g = Guest.stage;
        String containers;
        if (!g.isEmpty() && !"boot".equals(g)) {
            containers = ("fetch".equals(g) ? "הורדה " : "פריסה ") + Math.min(100, Guest.done * 100 / Math.max(1, Guest.total)) + "%";
        } else if (refused.startsWith("containers are not installed")) {
            containers = "לא מותקנות";
        } else if (!refused.isEmpty()) {
            containers = "דורשות פעולה";
        } else if ("up".equals(state)) {
            containers = "פועלות";
        } else if (EngineService.running() || "step".equals(state) || "wanted".equals(state)) {
            containers = "עולות";
        } else {
            containers = EngineService.guest(c).exists() ? "כבויות" : "לא מותקנות";
        }
        return "הבסיס פועל · " + (n == 0 ? "" : count(n, "אפליקציה אחת", "אפליקציות") + " · ") + "מכולות: " + containers;
    }

    // ── small things ─────────────────────────────────────────────────────────────────────────────────

    private static JSONObject status(File f) {
        // older than a few of the core's beats: a core that is not running (status.go's StatusEvery is 2 s)
        if (!f.isFile() || System.currentTimeMillis() - f.lastModified() > 10_000) return null;
        try {
            return new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
        } catch (Exception e) {
            return null;
        }
    }

    static String text(File f) {
        try {
            return f.isFile() ? new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8).trim() : "";
        } catch (IOException e) {
            return "";
        }
    }

    static List<String> lastLines(String text, int n) {
        List<String> out = new ArrayList<>();
        String[] ls = text.trim().split("\n");
        for (int i = Math.max(0, ls.length - n); i < ls.length; i++) if (!ls[i].trim().isEmpty()) out.add(ls[i].trim());
        return out;
    }

    /** The bytes a sparse file holds on the phone (its blocks), not its apparent size. */
    static long used(File f) {
        if (!f.isFile()) return 0;
        try {
            Object blocks = Files.getAttribute(f.toPath(), "unix:blocks");
            return blocks instanceof Long ? (Long) blocks * 512 : f.length();
        } catch (Exception e) {
            return f.length();
        }
    }

    static String size(long b) {
        if (b >= (1L << 30)) return String.format(Locale.ROOT, "%.1f GB", b / (double) (1L << 30));
        return String.format(Locale.ROOT, "%.0f MB", b / (double) (1L << 20));
    }

    /** About how long, said as a person says it (one is said as one: «כשעה», never «כ-1 שעות»). */
    static String about(long s) {
        if (s < 60) return "פחות מדקה";
        if (s < 120) return "כדקה";
        if (s < 3600) return "כ-" + (s / 60) + " דקות";
        if (s < 7200) return "כשעה";
        return "כ-" + (s / 3600) + " שעות";
    }

    /** How long, exactly (G89: one second, minute or hour is its own word). */
    static String duration(long s) {
        if (s < 60) return count((int) s, "שנייה אחת", "שניות");
        if (s < 3600) return count((int) (s / 60), "דקה אחת", "דקות") + (s % 60 > 0 ? and(count((int) (s % 60), "שנייה אחת", "שניות")) : "");
        return count((int) (s / 3600), "שעה אחת", "שעות") + ((s % 3600) / 60 > 0 ? and(count((int) ((s % 3600) / 60), "דקה אחת", "דקות")) : "");
    }

    /** « ו-5 דקות» before a number, « ודקה אחת» before a word. */
    private static String and(String s) {
        return !s.isEmpty() && Character.isDigit(s.charAt(0)) ? " ו-" + s : " ו" + s;
    }

    /** A count of one is its own sentence (G89): one says {@code one}, more say the number and {@code many}. */
    static String count(int n, String one, String many) {
        return n == 1 ? one : n + " " + many;
    }
}
