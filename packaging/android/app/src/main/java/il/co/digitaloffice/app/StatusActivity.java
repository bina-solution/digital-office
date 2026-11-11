package il.co.digitaloffice.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * «מצב הלשכה» — the one screen of this phone's office (DGO-1723; the owner: «שקוף בדיוק מה קורה מה רץ», and the
 * mock ci-artifacts/dgo1723/mock as drawn). What is true now in one line, then the base (what runs natively in the
 * app), «מכולות» (the app that runs every other app: not installed, installing, coming up, running, or stopped with
 * its reason and the one action that helps), the apps that run on it with each one's state and log, the newest
 * lines, and «פתיחת הלשכה». No sign-in here and no ✗ list: what the engine checked, the measured stages and the
 * hardware speed-up are under «פרטים טכניים», folded.
 *
 * <p>Read every second off the main thread ({@link Office#read}); drawn again only when what it shows changed.
 * Opened from the first screen with {@link #OPEN} it opens the office by itself once its sign-in answers.
 */
public class StatusActivity extends Activity {

    /** Opened by the first screen: the office opens from here once the base answers (MainActivity.core). */
    static final String OPEN = "open-when-ready";

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService reader = Executors.newSingleThreadExecutor();
    private LinearLayout content;
    private boolean live, open, askedPermission, baseOpen;
    private volatile boolean reading, opening, techOpen;
    private String drawn = "";
    private Office.Now last;   // what was drawn last: a tap on «פירוט» redraws it at once
    private Tech lastTech;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        open = getIntent().getBooleanExtra(OPEN, false);

        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        content.setPadding(dp(16), dp(14), dp(16), dp(16));
        ScrollView scroll = new ScrollView(this);
        scroll.addView(content);

        LinearLayout dock = new LinearLayout(this);
        dock.setPadding(dp(16), dp(10), dp(16), dp(12));
        dock.setBackgroundColor(getColor(R.color.surface));
        dock.addView(button("פתיחת הלשכה", PRIMARY, v -> openOffice()), new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(48)));

        LinearLayout outer = new LinearLayout(this);
        outer.setOrientation(LinearLayout.VERTICAL);
        outer.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        View rule = new View(this);
        rule.setBackgroundColor(getColor(R.color.line));
        outer.addView(rule, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1));
        outer.addView(dock);

        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(getColor(R.color.bg));
        frame.addView(outer);
        Edges.pad(frame);
        setContentView(frame);
    }

    @Override
    protected void onResume() {
        super.onResume();
        live = true;
        if (open && !askedPermission && Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            askedPermission = true;   // the office's notification says what runs: asked once, from the first open
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 2);
        }
        // no NativeService.inFront here: it asks again and clears the refusal this screen is opened to read
        // (MainActivity and OfficeActivity ask it); «לנסות שוב» is the owner's own ask
        ui.post(tick);
    }

    @Override
    protected void onPause() {
        super.onPause();
        live = false;
        ui.removeCallbacks(tick);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        reader.shutdownNow();
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!live || reading) return;
            reading = true;
            Runnable self = this;
            reader.execute(() -> {
                Office.Now n = null;
                Tech t = null;
                boolean ready = false;
                try {
                    n = Office.read(StatusActivity.this);
                    t = techOpen ? tech() : null;
                    // opened by the first screen: the office, as soon as its sign-in answers through the edge
                    ready = open && NativeService.serving(StatusActivity.this) && MainActivity.signInAnswers();
                } catch (RuntimeException e) {
                    // one read that failed is a second without news, never a screen that stops reading
                }
                Office.Now got = n;
                Tech gotTech = t;
                boolean up = ready;
                ui.post(() -> {
                    reading = false;
                    if (!live) return;
                    if (up && !opening) {
                        openOffice();
                        return;
                    }
                    if (got != null) show(got, gotTech);
                    ui.postDelayed(self, 1000);
                });
            });
        }
    };

    // ── what is drawn ────────────────────────────────────────────────────────────────────────────────

    private void show(Office.Now n, Tech t) {
        last = n;
        lastTech = t;
        String key = key(n) + "|" + baseOpen + techOpen + (t == null ? "" : t.key());
        if (key.equals(drawn)) return;
        drawn = key;
        content.removeAllViews();

        // the head: the mark, the office's name, this phone, and the one word of where it stands
        LinearLayout head = row();
        TextView mark = text("i0", 17, true, R.color.accent_ink);
        mark.setGravity(Gravity.CENTER);
        mark.setBackground(round(R.color.accent, 0, 10));
        head.addView(mark, new LinearLayout.LayoutParams(dp(40), dp(40)));
        LinearLayout names = column();
        names.setPadding(dp(10), 0, dp(10), 0);
        names.addView(text(getString(R.string.app_name), 18, true, R.color.text));
        names.addView(text("בטלפון הזה · גרסה " + BuildConfig.VERSION_NAME, 12, false, R.color.muted));
        head.addView(names, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        head.addView(pill(n.pill, n.tone));
        content.addView(head, spaced(12));

        // what is true now, in one line and one sentence
        LinearLayout truth = card();
        truth.addView(text(n.head, 20, true, R.color.text));
        truth.addView(text(n.say, 14, false, R.color.muted));
        content.addView(truth, spaced(12));

        content.addView(baseCard(n), spaced(12));
        content.addView(containersCard(n), spaced(12));
        content.addView(appsCard(n), spaced(12));
        content.addView(logCard(n), spaced(12));
        content.addView(techCard(t), spaced(12));

        TextView dev = text(n.device, 11, false, R.color.muted);
        dev.setGravity(Gravity.CENTER);
        content.addView(dev);
    }

    private String key(Office.Now n) {
        StringBuilder b = new StringBuilder().append(n.head).append(n.say).append(n.pill).append(n.tone).append(n.baseMeta)
                .append(n.containers).append(n.cPill).append(n.cMeta).append(n.problem).append(n.permille).append(n.stepNow)
                .append(n.pairable).append(n.appsMeta).append(n.appsPill).append(n.log).append(n.device);
        for (Office.Part p : n.base) b.append(p.name).append(p.tone);
        for (String[] f : n.facts) b.append(f[0]).append(f[1]);
        for (Office.AppRow r : n.apps) b.append(r.id).append(r.state).append(r.said).append(r.tone);
        return b.toString();
    }

    private View baseCard(Office.Now n) {
        LinearLayout c = card();
        int ok = 0;
        for (Office.Part p : n.base) if (p.tone == Office.OK) ok++;
        boolean all = ok == n.base.size() && !n.base.isEmpty();
        c.addView(cardHead("הבסיס", n.baseMeta, all ? ok + "/" + n.base.size() + " פועלים" : n.core ? "עולה · " + ok + "/" + n.base.size() : "כבוי",
                all ? Office.OK : n.core ? Office.RUN : Office.OFF));
        if (all && !baseOpen) {
            // all well: folded to the names, a tap opens it
            LinearLayout r = row();
            r.setPadding(0, dp(10), 0, 0);
            StringBuilder s = new StringBuilder();
            for (Office.Part p : n.base) s.append(s.length() == 0 ? "" : " · ").append(p.name);
            r.addView(text(s.toString(), 12, false, R.color.muted), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            r.addView(text("פירוט", 12, true, R.color.ok));
            r.setOnClickListener(v -> {
                baseOpen = true;
                redraw();
            });
            c.addView(r);
            return c;
        }
        LinearLayout grid = column();
        grid.setPadding(0, dp(8), 0, 0);
        for (int i = 0; i < n.base.size(); i += 2) {
            LinearLayout line = row();
            for (int k = i; k < i + 2; k++) {
                LinearLayout cell = row();
                cell.setPadding(0, dp(6), 0, dp(6));
                if (k < n.base.size()) {
                    Office.Part p = n.base.get(k);
                    cell.addView(dot(p.tone));
                    TextView name = text(p.name, 13, false, R.color.text);
                    name.setPadding(dp(8), 0, dp(6), 0);
                    cell.addView(name);
                    if (p.tone != Office.OK) cell.addView(text(p.tone == Office.RUN ? "עולה" : "כבוי", 11, true, fg(p.tone)));
                }
                line.addView(cell, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            }
            grid.addView(line);
        }
        if (all) grid.setOnClickListener(v -> {
            baseOpen = false;
            redraw();
        });
        c.addView(grid);
        return c;
    }

    private View containersCard(Office.Now n) {
        LinearLayout c = card();
        c.addView(cardHead("מכולות", n.cMeta, n.cPill, n.cTone));
        LinearLayout b = column();
        b.setPadding(0, dp(10), 0, 0);
        switch (n.containers) {
            case Office.C_NONE: {
                b.addView(text(appsSentence(n), 13, false, R.color.text), spaced(8));
                b.addView(facts(n.facts), spaced(10));
                boolean can = Guest.fetchable() || Guest.inApk(this);
                TextView install = button("התקנת מכולות", OUTLINE, v -> install());
                install.setEnabled(can);
                install.setAlpha(can ? 1f : 0.5f);
                b.addView(install, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
                TextView note = text(can ? "ב-Wi-Fi בלבד · ממשיכה גם כשהמסך כבוי" : "בגרסה הזו של האפליקציה אין מכולות להתקנה", 11, false, R.color.muted);
                note.setGravity(Gravity.CENTER);
                note.setPadding(0, dp(6), 0, 0);
                b.addView(note);
                break;
            }
            case Office.C_INSTALLING:
                b.addView(bar(n.permille), spaced(10));
                if (!n.facts.isEmpty()) b.addView(facts(n.facts), spaced(10));
                b.addView(steps(n.stepNow), spaced(8));
                b.addView(buttons(button("עצירת ההתקנה", GHOST, v -> stopInstall())));
                break;
            case Office.C_STARTING:
                b.addView(bar(-1), spaced(10));
                b.addView(steps("engine"), spaced(8));
                b.addView(buttons(button("הלוג של המנוע", GHOST, v -> engineLog())));
                break;
            case Office.C_RUNNING:
                b.addView(facts(n.facts), spaced(10));
                b.addView(buttons(button("עצירה", GHOST, v -> stopContainers()), button("הלוג של המנוע", GHOST, v -> engineLog())));
                break;
            case Office.C_STOPPED:
                b.addView(buttons(button("הפעלה", OUTLINE, v -> again()), button("הלוג של המנוע", GHOST, v -> engineLog())));
                break;
            default: {
                TextView call = text(n.problem, 13, false, R.color.text);
                call.setBackground(round(R.color.danger_soft, R.color.danger, 10));
                call.setPadding(dp(12), dp(10), dp(12), dp(10));
                b.addView(call, spaced(10));
                TextView act = "room".equals(n.action) ? button("פינוי מקום", PRIMARY, v -> settings(Settings.ACTION_INTERNAL_STORAGE_SETTINGS))
                        : "wifi".equals(n.action) ? button("הגדרות Wi-Fi", PRIMARY, v -> settings(Settings.ACTION_WIFI_SETTINGS))
                        : button("לנסות שוב", PRIMARY, v -> again());
                b.addView(buttons(act, button("הלוג של המנוע", GHOST, v -> engineLog())));
            }
        }
        if (n.pairable && n.containers != Office.C_NONE) {
            // a speed-up the owner may take, never a requirement: AVF runs the containers about twelve times faster
            LinearLayout r = row();
            r.setPadding(0, dp(12), 0, 0);
            r.addView(text("הטלפון יכול להריץ את המכולות מהר יותר, בהאצת חומרה — הפעלה חד-פעמית.", 12, false, R.color.muted),
                    new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            r.addView(button("הפעלה", GHOST, v -> startActivity(new Intent(this, PairingActivity.class))));
            b.addView(r);
        }
        c.addView(b);
        return c;
    }

    /** «אוטומציות, קבצים, מייל ועוד 31 אפליקציות רצות על מכולות. מתקינים פעם אחת.» from the office's own apps. */
    private static String appsSentence(Office.Now n) {
        if (n.apps.isEmpty()) return "כל אפליקציה שצריכה מכולה רצה עליהן. מתקינים פעם אחת.";
        StringBuilder s = new StringBuilder();
        int shown = Math.min(3, n.apps.size());
        for (int i = 0; i < shown; i++) s.append(i == 0 ? "" : i == shown - 1 && n.apps.size() == shown ? " ו" : ", ").append(n.apps.get(i).name);
        int more = n.apps.size() - shown;
        if (more > 0) s.append(" ועוד ").append(Office.count(more, "אפליקציה אחת", "אפליקציות"));
        return s + (n.apps.size() == 1 ? " רצה" : " רצות") + " על מכולות. מתקינים פעם אחת.";
    }

    private View steps(String now) {
        LinearLayout l = column();
        String[][] all = {{"fetch", "הורדה"}, {"unpack", "פריסה בטלפון"}, {"engine", "הפעלת המנוע"}};
        boolean past = true;
        for (int i = 0; i < all.length; i++) {
            boolean here = all[i][0].equals(now);
            if (here) past = false;
            LinearLayout r = row();
            r.setPadding(0, dp(3), 0, dp(3));
            TextView num = text(past && !here ? "✓" : String.valueOf(i + 1), 11, true, here ? R.color.info : R.color.muted);
            num.setGravity(Gravity.CENTER);
            num.setBackground(round(here ? R.color.info_soft : R.color.surface_2, here ? R.color.info : R.color.line, 99));
            r.addView(num, new LinearLayout.LayoutParams(dp(20), dp(20)));
            TextView t = text(all[i][1], 13, here, here ? R.color.text : R.color.muted);
            t.setPadding(dp(8), 0, 0, 0);
            r.addView(t);
            l.addView(r);
        }
        return l;
    }

    private View appsCard(Office.Now n) {
        LinearLayout c = card();
        c.addView(cardHead("אפליקציות הלשכה", n.appsMeta, n.appsPill, n.appsTone));
        if (n.apps.isEmpty()) {
            TextView none = text("אין בלשכה עדיין אפליקציה שרצה על מכולות. מתקינים אפליקציות מתוך הלשכה, כמו בכל מחשב.", 12, false, R.color.muted);
            none.setPadding(0, dp(8), 0, 0);
            c.addView(none);
            return c;
        }
        for (Office.AppRow a : n.apps) {
            View rule = new View(this);
            rule.setBackgroundColor(getColor(R.color.line));
            c.addView(rule, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1));
            LinearLayout r = row();
            r.setPadding(0, dp(9), 0, dp(9));
            LinearLayout tx = column();
            tx.addView(text(a.name, 14, true, R.color.text));
            if (!a.said.isEmpty()) tx.addView(text(a.said, 11, false, R.color.muted));
            r.addView(tx, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            TextView where = text("מכולות", 10, false, R.color.muted);
            where.setBackground(round(R.color.surface_2, R.color.line, 99));
            where.setPadding(dp(7), dp(1), dp(7), dp(1));
            r.addView(where);
            if (!a.state.isEmpty()) {
                TextView st = text(a.state, 12, true, fg(a.tone));
                st.setPadding(dp(10), 0, 0, 0);
                r.addView(st);
            }
            if (n.containers == Office.C_RUNNING || n.containers == Office.C_STARTING) r.setOnClickListener(v -> appLog(a));
            c.addView(r);
        }
        return c;
    }

    private View logCard(Office.Now n) {
        LinearLayout c = card();
        c.addView(cardHead("מה קורה עכשיו", "השורות האחרונות מכל הלשכה", "", Office.OFF));
        TextView log = mono(n.log.isEmpty() ? "—" : n.log);
        log.setBackground(round(R.color.surface_2, R.color.line, 10));
        log.setPadding(dp(10), dp(8), dp(10), dp(8));
        c.addView(log, spacedTop(8));
        c.addView(buttons(button("הלוג המלא", GHOST, v -> fullLog()), button("שיתוף", GHOST, v -> share())));
        return c;
    }

    // ── «פרטים טכניים»: what the engine checked, what each stage took — folded ─────────────────────────

    private static final class Tech {
        String engine = "", why = "", checks = "", times = "";
        boolean retry, childToggle;

        String key() {
            return engine + why + checks + times + retry + childToggle;
        }
    }

    private static final Map<String, String> STAGES = new LinkedHashMap<>();

    static {
        STAGES.put("fetch", "הורדה");
        STAGES.put("unpack", "פריסה");
        STAGES.put("boot-files", "הורדת ליבת ה-AVF");
        STAGES.put("avf-edge", "עליית המנוע ב-AVF");
        STAGES.put("qemu-edge", "עליית המנוע המדומה");
        STAGES.put("office-up", "עליית האפליקציות");
        STAGES.put("office-not-up", "האפליקציות עלו עם תקלה");
    }

    /** Off the main thread: Virt asks Android (a binder call, a getprop). */
    private Tech tech() {
        Tech t = new Tech();
        Virt.Choice now = Virt.choose(this);
        String[] engine = Office.text(EngineService.engineFile(this)).split("\n");
        StringBuilder ch = new StringBuilder();
        if (engine.length >= 2) {
            t.engine = engine[0];
            t.why = engine[1];
            for (int i = 2; i < engine.length; i++) ch.append(engine[i].startsWith("1 ") ? "✓ " : "· ").append(engine[i].length() > 2 ? engine[i].substring(2) : engine[i]).append('\n');
        } else {
            t.engine = now.hardware ? "avf" : EngineService.hasQemu(this) ? "tcg" : "none";
            t.why = now.why;
            for (Virt.Check k : new Virt.Check[]{now.avf, now.unprotected, now.granted, now.boots}) ch.append(k.ok ? "✓ " : "· ").append(k.said).append('\n');
        }
        t.checks = ch.toString().trim();
        t.retry = Virt.failedHere(this);
        t.childToggle = !"avf".equals(t.engine) && !"none".equals(t.engine) && Build.VERSION.SDK_INT >= 34 && EngineService.running();
        StringBuilder tm = new StringBuilder();
        for (String l : Office.text(EngineService.timesFile(this)).split("\n")) {
            String[] p = l.split(" ");
            if (p.length == 2 && p[1].matches("[0-9]{1,9}")) {
                tm.append(STAGES.containsKey(p[0]) ? STAGES.get(p[0]) : p[0]).append(": ").append(Office.duration(Long.parseLong(p[1]))).append('\n');
            }
        }
        t.times = tm.toString().trim();
        return t;
    }

    private View techCard(Tech t) {
        LinearLayout c = card();
        LinearLayout h = row();
        h.addView(text("פרטים טכניים", 14, true, R.color.text), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        h.addView(text(techOpen ? "סגירה" : "פירוט", 12, true, R.color.ok));
        h.setOnClickListener(v -> {
            techOpen = !techOpen;
            redraw();   // its details come with the next read, within a second
        });
        c.addView(h);
        if (!techOpen || t == null) return c;
        String engine = "avf".equals(t.engine) ? "AVF (חומרה)" : "kvm".equals(t.engine) ? "KVM (חומרה)" : "none".equals(t.engine) ? "אין" : "מדומה (TCG)";
        c.addView(text("מנוע המכולות: " + engine, 13, true, R.color.text), spacedTop(8));
        c.addView(text(t.why, 12, false, R.color.muted));
        if (!t.checks.isEmpty()) c.addView(mono(t.checks), spacedTop(6));
        c.addView(text(t.times.isEmpty() ? "עוד לא נמדד שלב בהפעלה הזו" : "נמדד בטלפון הזה:\n" + t.times, 12, false, R.color.muted), spacedTop(8));
        LinearLayout more = column();
        more.addView(buttons(button("העתקת הכל", GHOST, v -> copy())));
        if (t.retry) more.addView(buttons(button("לנסות שוב ב-AVF בהפעלה הבאה", GHOST, v -> {
            reader.execute(() -> Virt.bootResult(this).delete());
            Toast.makeText(this, "בהפעלה הבאה AVF ינסה שוב", Toast.LENGTH_SHORT).show();
        })));
        if (t.childToggle) more.addView(buttons(button("שהמכולות לא ייעצרו ברקע — אפשרויות המפתח", GHOST, v -> childProcesses())));
        c.addView(more);
        return c;
    }

    // ── the buttons ──────────────────────────────────────────────────────────────────────────────────

    /**
     * The office — or, while no core runs, the first screen that starts it. Opened as the first screen (OPEN)
     * this one is done once the office opens: back from the office leaves the app, as before, and never lands
     * here to open the office a second time; nor does a stopped core's first screen stack on this one.
     */
    private void openOffice() {
        if (NativeService.running()) {
            String link = NativeService.firstRunUrl(this);   // while there is no owner: the one sign-in there is
            startActivity(new Intent(this, OfficeActivity.class).putExtra(OfficeActivity.URL, link != null ? link : MainActivity.CONSOLE)
                    .putExtra(OfficeActivity.NAME, getString(R.string.app_name)));
            if (open) {
                opening = true;
                finish();
            }
        } else {
            startActivity(new Intent(this, MainActivity.class));
            finish();
        }
    }

    private void redraw() {
        drawn = "";
        if (last != null) show(last, lastTech);
    }

    /** The core, started when none runs: what the owner's button asked for is then asked by its start (run). */
    private void startCore() {
        if (!NativeService.running()) startForegroundService(new Intent(this, NativeService.class));
    }

    private void install() {
        reader.execute(() -> {
            String err = null;
            try {
                Office.install(this);
            } catch (Exception e) {
                err = e.getMessage();
            }
            String said = err;
            ui.post(() -> {
                if (isFinishing() || isDestroyed()) return;
                if (said != null) Toast.makeText(this, "ההתקנה לא התחילה: " + said, Toast.LENGTH_LONG).show();
                else startCore();
            });
        });
    }

    private void stopInstall() {
        dialog().setMessage("לעצור את התקנת המכולות? מה שכבר ירד נשמר, ואפשר להמשיך אחר כך.")
                .setPositiveButton("עצירה", (d, w) -> reader.execute(() -> Office.stopInstall(this)))
                .setNegativeButton("ביטול", null).show();
    }

    private void stopContainers() {
        dialog().setMessage("לעצור את המכולות? האפליקציות שרצות עליהן ייעצרו, והבסיס ממשיך לפעול.")
                .setPositiveButton("עצירה", (d, w) -> startService(new Intent(this, EngineService.class).setAction(EngineService.STOP)))
                .setNegativeButton("ביטול", null).show();
    }

    /** «לנסות שוב», «הפעלה»: asked now — or by the core's own start, when none runs. */
    private void again() {
        if (NativeService.running()) {
            reader.execute(() -> NativeService.wantNow(this));
            return;
        }
        reader.execute(() -> {
            try {
                Office.askFile(this).createNewFile();   // there already: the same ask
            } catch (java.io.IOException e) {
                // the core still starts: an office with container apps asks for the machine by itself
            }
            ui.post(() -> {
                if (!isFinishing() && !isDestroyed()) startCore();
            });
        });
    }

    /**
     * A dialog in the phone's own light or dark: the app's theme is a light one, and the sheet's text takes the
     * palette's colours of the hour, so a dark phone's sheet must be dark too.
     */
    private AlertDialog.Builder dialog() {
        boolean night = (getResources().getConfiguration().uiMode & android.content.res.Configuration.UI_MODE_NIGHT_MASK)
                == android.content.res.Configuration.UI_MODE_NIGHT_YES;
        return new AlertDialog.Builder(this, night ? android.R.style.Theme_Material_Dialog_Alert : android.R.style.Theme_Material_Light_Dialog_Alert);
    }

    private void settings(String action) {
        try {
            startActivity(new Intent(action));
        } catch (Exception e) {
            startActivity(new Intent(Settings.ACTION_SETTINGS));
        }
    }

    /** Android 14+'s own switch: «Disable child process restrictions», in Developer options. */
    private void childProcesses() {
        Toast.makeText(this, "באפשרויות המפתח: «השבתת ההגבלות על תהליכי צאצא» — כדי ש-Android לא יעצור את המכולות", Toast.LENGTH_LONG).show();
        try {
            startActivity(new Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS));
        } catch (Exception e) {
            Toast.makeText(this, "אפשרויות המפתח כבויות: הגדרות ← מידע על הטלפון ← שבע הקשות על «מספר גרסה»", Toast.LENGTH_LONG).show();
        }
    }

    private void engineLog() {
        reader.execute(() -> {
            String t = MainActivity.tail(EngineService.console(this), 64 << 10);
            ui.post(() -> sheet("הלוג של המנוע", "המכולות", Office.lastLines(t, 200)));
        });
    }

    /** An app's own lines: the machine's console lines that name it. */
    private void appLog(Office.AppRow a) {
        reader.execute(() -> {
            String t = MainActivity.tail(EngineService.console(this), 256 << 10);
            StringBuilder b = new StringBuilder();
            for (String l : t.split("\n")) if (l.contains(a.id)) b.append(l).append('\n');
            String said = a.state + (a.said.isEmpty() ? "" : " · " + a.said);
            ui.post(() -> sheet(a.name, "רצה במכולות · " + said, Office.lastLines(b.toString(), 120)));
        });
    }

    private void fullLog() {
        reader.execute(() -> {
            String nat = MainActivity.tail(NativeService.log(this), 32 << 10);
            String con = MainActivity.tail(EngineService.console(this), 32 << 10);
            List<String> lines = Office.lastLines(nat, 80);
            lines.add("— מכולות —");
            lines.addAll(Office.lastLines(con, 120));
            ui.post(() -> sheet("הלוג המלא", "הבסיס, ואחריו המכולות", lines));
        });
    }

    /** A log in a sheet — unless the screen went meanwhile (the office opened over it, a back press). */
    private void sheet(String title, String meta, List<String> lines) {
        if (isFinishing() || isDestroyed()) return;
        LinearLayout b = column();
        b.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        b.setPadding(dp(16), dp(12), dp(16), dp(4));
        b.addView(text(meta, 12, false, R.color.muted));
        TextView log = mono(lines.isEmpty() ? "אין עדיין שורות" : TextUtils.join("\n", lines));
        log.setTextIsSelectable(true);
        ScrollView s = new ScrollView(this);
        s.addView(log);
        b.addView(s, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(320)));
        s.post(() -> s.fullScroll(View.FOCUS_DOWN));
        dialog().setTitle(title).setView(b).setPositiveButton("סגירה", null)
                .setNeutralButton("שיתוף", (d, w) -> share()).show();
    }

    private void copy() {
        reader.execute(() -> {
            String all = report(256 << 10);
            ui.post(() -> {
                ClipboardManager cb = getSystemService(ClipboardManager.class);
                if (cb != null) cb.setPrimaryClip(ClipData.newPlainText("dgo", all));
                Toast.makeText(this, "הועתק", Toast.LENGTH_SHORT).show();
            });
        });
    }

    private void share() {
        reader.execute(() -> {
            try {
                File dir = LogProvider.dir(this);
                if (!dir.isDirectory() && !dir.mkdirs()) throw new java.io.IOException("no room for the log");
                File[] old = dir.listFiles();
                if (old != null) for (File f : old) f.delete();
                File f = new File(dir, "dgo-log-" + System.currentTimeMillis() + ".txt");
                try (OutputStream o = new FileOutputStream(f)) {
                    o.write(report(4 << 20).getBytes(StandardCharsets.UTF_8));
                }
                Intent send = new Intent(Intent.ACTION_SEND).setType("text/plain")
                        .putExtra(Intent.EXTRA_STREAM, LogProvider.uri(f))
                        .putExtra(Intent.EXTRA_SUBJECT, "הלשכה בטלפון — לוג " + BuildConfig.VERSION_NAME)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                ui.post(() -> startActivity(Intent.createChooser(send, "שיתוף הלוג")));
            } catch (Exception e) {
                ui.post(() -> Toast.makeText(this, "הלוג לא נכתב: " + e.getMessage(), Toast.LENGTH_LONG).show());
            }
        });
    }

    /** Everything this screen shows, the phone's facts, and the logs' last bytes (each at most max). */
    private String report(int max) {
        Office.Now n = Office.read(this);
        Tech t = tech();
        StringBuilder b = new StringBuilder();
        b.append("DGO Android ").append(BuildConfig.VERSION_NAME).append(" (").append(BuildConfig.VERSION_CODE).append(")\n");
        b.append(Build.MANUFACTURER).append(' ').append(Build.MODEL).append(" · Android ").append(Build.VERSION.RELEASE)
                .append(" (API ").append(Build.VERSION.SDK_INT).append(')');
        if (Build.VERSION.SDK_INT >= 31) b.append(" · SoC ").append(Build.SOC_MANUFACTURER).append(' ').append(Build.SOC_MODEL);
        b.append('\n');
        b.append("ro.boot.hypervisor.vm.supported=").append(Virt.property("ro.boot.hypervisor.vm.supported"))
                .append(" protected_vm.supported=").append(Virt.property("ro.boot.hypervisor.protected_vm.supported"))
                .append(" virtualization_framework=").append(getPackageManager().hasSystemFeature("android.software.virtualization_framework"))
                .append('\n');
        b.append("now: ").append(n.head).append(" — ").append(n.say).append('\n');
        b.append("base: ").append(n.baseMeta);
        for (Office.Part p : n.base) b.append(" · ").append(p.name).append(p.tone == Office.OK ? " up" : " not up");
        b.append('\n').append("containers: ").append(n.containers).append(' ').append(n.cPill).append(" — ").append(n.cMeta).append(' ').append(n.problem).append('\n');
        for (Office.AppRow a : n.apps) b.append("  ").append(a.id).append(": ").append(a.state).append(' ').append(a.said).append('\n');
        b.append("engine: ").append(t.engine).append(" — ").append(t.why).append('\n').append(t.checks).append('\n').append(t.times).append("\n\n");
        b.append("===== the machine's console (console.log) =====\n").append(MainActivity.tail(EngineService.console(this), max)).append("\n\n");
        b.append("===== the core (native.log) =====\n").append(MainActivity.tail(NativeService.log(this), max / 4)).append('\n');
        return b.toString();
    }

    // ── small things ─────────────────────────────────────────────────────────────────────────────────

    private static final int PRIMARY = 0, OUTLINE = 1, GHOST = 2;

    private int fg(int tone) {
        return tone == Office.OK ? R.color.ok : tone == Office.RUN ? R.color.info : tone == Office.BAD ? R.color.danger : R.color.muted;
    }

    private int soft(int tone) {
        return tone == Office.OK ? R.color.ok_soft : tone == Office.RUN ? R.color.info_soft : tone == Office.BAD ? R.color.danger_soft : R.color.surface_2;
    }

    private GradientDrawable round(int fill, int stroke, int radiusDp) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(getColor(fill));
        if (stroke != 0) d.setStroke(Math.max(1, dp(1)), getColor(stroke));
        d.setCornerRadius(dp(radiusDp));
        return d;
    }

    private LinearLayout card() {
        LinearLayout c = column();
        c.setBackground(round(R.color.surface, R.color.line, 14));
        c.setPadding(dp(14), dp(12), dp(14), dp(12));
        return c;
    }

    private LinearLayout cardHead(String title, String meta, String pill, int tone) {
        LinearLayout h = row();
        LinearLayout t = column();
        t.addView(text(title, 15, true, R.color.text));
        if (meta != null && !meta.isEmpty()) t.addView(text(meta, 12, false, R.color.muted));
        h.addView(t, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        if (pill != null && !pill.isEmpty()) h.addView(pill(pill, tone));
        return h;
    }

    private TextView pill(String s, int tone) {
        TextView p = text(s, 11, true, fg(tone));
        p.setBackground(round(soft(tone), tone == Office.OFF ? R.color.line : 0, 99));
        p.setPadding(dp(9), dp(3), dp(9), dp(3));
        return p;
    }

    private View dot(int tone) {
        View d = new View(this);
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        g.setColor(getColor(fg(tone)));
        d.setBackground(g);
        d.setLayoutParams(new LinearLayout.LayoutParams(dp(8), dp(8)));
        return d;
    }

    private View facts(List<String[]> fs) {
        LinearLayout r = row();
        r.setBackground(round(R.color.surface_2, R.color.line, 10));
        r.setPadding(dp(4), dp(8), dp(4), dp(8));
        for (String[] f : fs) {
            LinearLayout col = column();
            col.setGravity(Gravity.CENTER_HORIZONTAL);
            TextView k = text(f[0], 11, false, R.color.muted);
            TextView v = text(f[1], 13, true, R.color.text);
            k.setGravity(Gravity.CENTER);
            v.setGravity(Gravity.CENTER);
            col.addView(k);
            col.addView(v);
            r.addView(col, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        }
        return r;
    }

    private View bar(int permille) {
        ProgressBar b = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        b.setMax(1000);
        b.setIndeterminate(permille < 0);
        if (permille >= 0) b.setProgress(permille);
        b.setProgressTintList(ColorStateList.valueOf(getColor(R.color.info)));
        b.setIndeterminateTintList(ColorStateList.valueOf(getColor(R.color.info)));
        b.setProgressBackgroundTintList(ColorStateList.valueOf(getColor(R.color.line)));
        return b;
    }

    private LinearLayout buttons(TextView... bs) {
        LinearLayout r = row();
        r.setPadding(0, dp(8), 0, 0);
        for (int i = 0; i < bs.length; i++) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(36));
            if (i > 0) lp.setMarginStart(dp(8));
            r.addView(bs[i], lp);
        }
        return r;
    }

    private TextView button(String s, int kind, View.OnClickListener l) {
        TextView b = text(s, 14, true, kind == PRIMARY ? R.color.accent_ink : kind == OUTLINE ? R.color.accent : R.color.text);
        b.setGravity(Gravity.CENTER);
        b.setPadding(dp(14), 0, dp(14), 0);
        b.setBackground(kind == PRIMARY ? round(R.color.accent, 0, 10) : kind == OUTLINE ? round(R.color.surface, R.color.accent, 10)
                : round(R.color.surface_2, R.color.line, 10));
        b.setClickable(true);
        b.setFocusable(true);
        b.setOnClickListener(l);
        return b;
    }

    private TextView text(String s, int sp, boolean bold, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(getColor(color));
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG_RTL);
        return t;
    }

    private TextView mono(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTypeface(Typeface.MONOSPACE);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 10);
        t.setTextColor(getColor(R.color.text));
        t.setTextDirection(View.TEXT_DIRECTION_LTR);
        t.setGravity(Gravity.START);
        return t;
    }

    private LinearLayout row() {
        LinearLayout r = new LinearLayout(this);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(Gravity.CENTER_VERTICAL);
        return r;
    }

    private LinearLayout column() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        return c;
    }

    private LinearLayout.LayoutParams spaced(int bottomDp) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dp(bottomDp);
        return lp;
    }

    private LinearLayout.LayoutParams spacedTop(int topDp) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(topDp);
        return lp;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
