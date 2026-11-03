package il.co.digitaloffice.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;

/**
 * The app (DGO-1071, DGO-1084): this phone's DGO — the whole office, as `bbox run` brings it up on every
 * other OS. The first open unpacks the office's machine from the APK (assets/guest: the engine's guest,
 * made in CI with the office and its images in it) and starts the engine ({@link EngineService}); every
 * open shows how far the office has come — its own lines, from the machine's console — and opens the
 * console ({@link OfficeActivity}) once it is up. Nothing to choose: linking to other offices and the rest
 * is done from inside the office, as everywhere else. Built by hand, with no AndroidX.
 *
 * <p>An APK that carries the office's core natively (DGO-1090: dgo and forward-auth as the app's libraries,
 * the office root as an asset) starts that instead ({@link NativeService}) and opens the console as soon as
 * its edge answers — seconds, nothing unpacked, no machine booted; the owner's one-time link first, on a
 * fresh phone. Its install wizard can finish with the core alone; an app that runs in a container needs the
 * machine, which this path does not start yet.
 */
public class MainActivity extends Activity {

    static final String CONSOLE = "http://console.localhost:8080";

    private static volatile boolean unpacking;   // one unpack, whichever screen started it
    private static volatile int percent = -1;
    private static volatile String failed;
    private volatile boolean ready;

    private SharedPreferences prefs;
    private TextView state, log;
    private ProgressBar bar;
    private final Handler tick = new Handler(Looper.getMainLooper());
    private ScrollView scroll;
    private volatile Thread watch;
    private long asked;              // when this screen started the engine, or last saw it run (0: neither)
    private volatile Boolean nativeCore;   // the APK carries the native core (natively()); null until asked
    private boolean askedPermission; // the notifications' permission is asked once a screen

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences("office", MODE_PRIVATE);
        // the first start runs for long under emulation: a phone that dozes meanwhile stops its network
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(20);
        root.setPadding(pad, pad, pad, pad);
        TextView title = new TextView(this);
        title.setText(R.string.app_name);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 26);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        root.addView(title);
        state = new TextView(this);
        state.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        state.setPadding(0, dp(16), 0, dp(12));
        root.addView(state);
        bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(100);
        root.addView(bar);
        log = new TextView(this);
        log.setTypeface(Typeface.MONOSPACE);
        log.setTextSize(TypedValue.COMPLEX_UNIT_SP, 10);
        log.setTextIsSelectable(true);
        log.setPadding(0, dp(16), 0, 0);
        root.addView(log);

        scroll = new ScrollView(this);
        scroll.setBackgroundColor(getColor(android.R.color.white));
        scroll.addView(root);
        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(getColor(R.color.tile));
        frame.addView(scroll);
        Edges.pad(frame);
        setContentView(frame);
    }

    /** Come back to: the office is wanted again — a stopped engine is started, what failed is tried again. */
    @Override
    protected void onRestart() {
        super.onRestart();
        asked = 0;
        if (!unpacking) failed = null;
    }

    @Override
    protected void onResume() {
        super.onResume();
        ready = false;
        // its notification again, if it was swiped away (Android 14+ lets an ongoing one go): the start of a
        // running engine only posts it — both, while the machine runs behind the core
        // (as it runs: behind the core or not, should it have ended between the check and the start)
        if (EngineService.running()) {
            startForegroundService(new Intent(this, EngineService.class).putExtra(EngineService.BEHIND_CORE, EngineService.behindCore()));
        }
        if (NativeService.running()) startForegroundService(new Intent(this, NativeService.class));
        NativeService.inFront(this);   // what kept the machine from starting, asked again once
        tick.post(refresh);
        watch = new Thread(this::watchOffice);
        watch.start();
    }

    @Override
    protected void onPause() {
        super.onPause();
        tick.removeCallbacks(refresh);
        Thread w = watch;
        watch = null;
        if (w != null) w.interrupt();
    }

    // ── what the screen says, every 2 s ──────────────────────────────────────────────────────────

    private final Runnable refresh = new Runnable() {
        @Override
        public void run() {
            if (natively()) {
                core();
                return;
            }
            if (ready) {
                prefs.edit().putBoolean("was_up", true).apply();
                // A fresh office's first screen is the one that makes its owner (DGO-1090): forward-auth's
                // prepare hook prints a one-time link on the console. Once the owner exists the same link
                // leads on to the console, so an old line costs one redirect and nothing else.
                String setup = firstRunLink(tail(EngineService.console(MainActivity.this), 4 << 20));
                startActivity(new Intent(MainActivity.this, OfficeActivity.class)
                        .putExtra(OfficeActivity.URL, setup != null ? setup : CONSOLE)
                        .putExtra(OfficeActivity.NAME, getString(R.string.app_name)));
                finish();   // the app is the office: back from it leaves the app, the engine keeps running
                return;
            }
            String s;
            boolean spin = false;   // the bar turns only while something is under way
            if (failed != null) {
                s = failed;
            } else if (!EngineService.installed(MainActivity.this)) {
                s = getString(R.string.setup_no_engine);
            } else if (unpacking || !EngineService.guest(MainActivity.this).exists()) {
                if (!unpacking) unpack();
                s = getString(R.string.setup_unpacking, Math.max(0, percent));
            } else if (!EngineService.running() && asked == 0) {
                start();
                s = getString(R.string.setup_starting);
                spin = true;
            } else if (!EngineService.running() && System.currentTimeMillis() - asked > 10_000) {
                // started (or seen running) from here and ended — a Stop, or a failure: said, not started again
                // in a loop; the console says why, and coming back to the app starts it again (onRestart)
                s = getString(R.string.setup_engine_stopped);
            } else if (!EngineService.running()) {
                s = getString(R.string.setup_starting);
                spin = true;
            } else {
                asked = System.currentTimeMillis();
                s = getString(prefs.getBoolean("was_up", false) ? R.string.setup_coming_up : R.string.setup_first_up);
                spin = true;
            }
            state.setText(s);
            bar.setIndeterminate(spin);
            if (!spin && !unpacking) bar.setProgress(0);
            if (unpacking) bar.setProgress(Math.max(0, percent));
            // the newest lines in view: they are the progress the text above points to
            log.setText(tail(EngineService.console(MainActivity.this), 2500));
            scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
            tick.postDelayed(this, 2000);
        }
    };

    // ── the office's core, natively (DGO-1090) ───────────────────────────────────────────────────

    /**
     * The office's core runs natively when the APK carries it — dgo and forward-auth as the app's own
     * libraries, and the office root (assets/office-root.zip): the console in seconds, nothing to unpack,
     * no machine to boot (NativeService). An APK without them is the machine's, as before.
     */
    private boolean natively() {
        if (nativeCore == null) {
            // …and only where the office is not the machine's already: a phone that ran the machine's office
            // (DGO-1084) keeps its office, its owner and its data there — the core does not start beside it.
            // A disk the core unpacked for its own machine is marked so (Guest.coreMarker): its office is the core's.
            boolean has = NativeService.installed(this)
                    && (!EngineService.guest(this).exists() || Guest.coreMarker(this).exists());
            if (has) {
                try (InputStream in = getAssets().open("office-root.zip")) {
                    has = in != null;
                } catch (IOException e) {
                    has = false;
                }
            }
            nativeCore = has;
        }
        return nativeCore;
    }

    /** One tick of the native core's screen: started once, then its log until its edge answers. */
    private void core() {
        if (ready) {
            startActivity(new Intent(this, OfficeActivity.class).putExtra(OfficeActivity.URL, coreLink())
                    .putExtra(OfficeActivity.NAME, getString(R.string.app_name)));
            finish();   // the app is the office: back from it leaves the app, the core keeps running
            return;
        }
        String s;
        boolean stopped = false;
        if (!NativeService.running() && asked == 0) {
            asked = System.currentTimeMillis();
            if (!askedPermission && Build.VERSION.SDK_INT >= 33
                    && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                askedPermission = true;
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 2);
            }
            startForegroundService(new Intent(this, NativeService.class));
            s = getString(R.string.setup_starting);
        } else if (!NativeService.running() && System.currentTimeMillis() - asked > 10_000) {
            s = getString(R.string.setup_engine_stopped);   // it ended: its log says why; coming back starts it again
            stopped = true;
        } else {
            // seen running: a Stop (or an end) from now on is said, not undone by the next tick
            if (NativeService.running()) asked = System.currentTimeMillis();
            s = getString(R.string.setup_starting);
        }
        state.setText(s);
        bar.setIndeterminate(!stopped);
        if (stopped) bar.setProgress(0);
        log.setText(tail(NativeService.log(this), 2500));
        scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
        tick.postDelayed(refresh, 1000);
    }

    /**
     * Where the core opens: the owner's one-time link while there is no owner (NativeService minted it,
     * on this phone alone), else the console. Only the office's own sign-in host's setup page is taken.
     */
    private String coreLink() {
        File f = NativeService.firstRunLink(this);
        try {
            String link = f.exists() ? new String(java.nio.file.Files.readAllBytes(f.toPath()), java.nio.charset.StandardCharsets.UTF_8).trim() : "";
            if (link.startsWith("http://signin.localhost:8080/setup?")) return link;
        } catch (IOException ignored) {
            // no link to read: the console, whose sign-in leads on
        }
        return CONSOLE;
    }

    private void start() {
        asked = System.currentTimeMillis();
        if (!askedPermission && Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            askedPermission = true;
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 2);
        }
        startForegroundService(new Intent(this, EngineService.class));
    }

    // ── is the office up? ─────────────────────────────────────────────────────────────────────────

    /**
     * Up = the office's edge answers AND, on a machine that writes bbox's lines to its console, bbox run said
     * "up" (the edge alone cannot tell: the sign-in answers for every host before the console behind it is
     * ready). That a machine writes them is remembered: on a later boot the containers are back before
     * bbox's first line, and the edge would answer early. Only a machine never seen to write one is judged
     * by its edge alone.
     */
    private void watchOffice() {
        // its own loop only: okhttp may swallow an interrupt mid-request, so the thread checks it is current
        while (watch == Thread.currentThread() && !isFinishing()) {
            // the native core is up when its edge answers the console's host: a 302 to the sign-in is
            // forward-auth answering through it (a 502 is the edge alone, forward-auth not yet there)
            if (natively()) {
                if (NativeService.serving(this) && signInAnswers()) {
                    ready = true;
                    return;
                }
            } else if (EngineService.running()) {
                String said = tail(EngineService.console(this), 1 << 16);
                if (said.contains("[bbox]") && !prefs.getBoolean("bbox_lines", false)) {
                    prefs.edit().putBoolean("bbox_lines", true).apply();
                }
                boolean bbox = prefs.getBoolean("bbox_lines", false);
                boolean up = said.contains("up. check health") || said.contains("up, with problems");
                if ((up || !bbox) && edgeAnswers()) {
                    ready = true;
                    return;
                }
            }
            try {
                Thread.sleep(natively() ? 500 : 5000);   // the core is up in a second or two; the machine in minutes
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    /**
     * The native core's edge, through forward-auth: an anonymous request for the console is sent to sign in
     * — a 302 to the office's own sign-in host. A 200 is never ours (forward-auth answers 2xx only to a
     * session); a 502 is the edge with forward-auth not answering yet.
     */
    private static boolean signInAnswers() {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL("http://127.0.0.1:8080/").openConnection(Proxy.NO_PROXY);
            c.setRequestProperty("Host", "console.localhost:8080");
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(3000);
            c.setReadTimeout(5000);
            String to = c.getHeaderField("Location");
            return c.getResponseCode() == 302 && to != null && to.startsWith("http://signin.localhost:8080/login?rd=");
        } catch (IOException e) {
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static boolean edgeAnswers() {
        HttpURLConnection c = null;
        try {
            // the phone's resolver knows localhost, not console.localhost: the address, and the office's host
            // NO_PROXY: a Wi-Fi proxy would take 127.0.0.1 elsewhere
            c = (HttpURLConnection) new URL("http://127.0.0.1:8080/").openConnection(Proxy.NO_PROXY);
            c.setRequestProperty("Host", "console.localhost:8080");
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(3000);
            c.setReadTimeout(5000);
            int code = c.getResponseCode();
            return code == 200 || (code >= 301 && code <= 308);
        } catch (IOException e) {
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    // ── the office's machine, out of the APK ─────────────────────────────────────────────────────

    /** assets/guest's machine into the app's own storage, once ({@link Guest}), its progress on this screen. */
    private void unpack() {
        unpacking = true;
        percent = 0;
        failed = null;
        new Thread(() -> {
            try {
                Guest.unpack(this, false, () -> true, p -> percent = p);
            } catch (Guest.Busy e) {
                // another unpack is under way: the screen asks again on its next tick
            } catch (Guest.Absent e) {
                failed = getString(R.string.setup_no_guest);
            } catch (Guest.NoRoom e) {
                failed = getString(R.string.setup_no_room, Guest.ROOM >> 30, e.free >> 30);
            } catch (Exception e) {
                failed = getString(R.string.setup_failed) + " " + e;
            } finally {
                unpacking = false;
                percent = -1;
            }
        }).start();
    }

    /**
     * The newest first-run link on the console, or null. Only the office's own sign-in host's setup page
     * is taken: the console carries whatever the machine prints, and the WebView must not be sent
     * anywhere else from it.
     */
    static final java.util.regex.Pattern FIRST_RUN = java.util.regex.Pattern.compile(
            "\\[forward-auth\\] first run: open (http://signin\\.localhost:8080/setup\\?[A-Za-z0-9=&%:/._-]+)");

    static String firstRunLink(String console) {
        java.util.regex.Matcher m = FIRST_RUN.matcher(console);
        String last = null;
        while (m.find()) last = m.group(1);
        return last;
    }

    // ── small things ──────────────────────────────────────────────────────────────────────────────

    /**
     * The console's terminal codes (ECMA-48), after one ESC or a run of them: a CSI — ESC [, parameter
     * bytes 0x30–0x3F, intermediates 0x20–0x2F, a final 0x40–0x7E: the kernel's colours, and the firmware's
     * ESC[2J, ESC[01;01H, ESC[=3h; a string (ESC ] P X ^ _: a title, a link) to BEL or ST, never past its
     * line, so a cut one keeps the next line's "[bbox]"; or a short escape, ESC, intermediates, a final
     * 0x30–0x7E (ESC(B, ESC c).
     */
    static final java.util.regex.Pattern CODES = java.util.regex.Pattern.compile(
            "\u001b+(\\[[0-?]*[ -/]*[@-~]|[\\]PX^_][^\u0007\u001b\n]*(\u0007|\u001b\\\\)?|[ -/]*[0-~])");

    /** The console's last bytes, without its terminal codes. */
    static String tail(File f, int max) {
        if (!f.exists()) return "";
        try (RandomAccessFile r = new RandomAccessFile(f, "r")) {
            long from = Math.max(0, r.length() - max);
            byte[] b = new byte[(int) (r.length() - from)];
            r.seek(from);
            r.readFully(b);
            return CODES.matcher(new String(b, java.nio.charset.StandardCharsets.UTF_8)).replaceAll("");
        } catch (Exception e) {
            return e.toString();
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
