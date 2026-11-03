package il.co.digitaloffice.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.util.Base64;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.SecureRandom;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * This phone's office core, natively (DGO-1090; ai/context/research/android-path.md): no machine — two
 * processes from the app's native-library directory, run as a foreground service so Android keeps them:
 * forward-auth (identity, libforward-auth.so) and the core (`libdgo.so be-child native`: the edge on
 * 127.0.0.1:8080, which the WebView opens and which believes no caller, and behind it the console's server
 * and the control plane, each on a socket in files/run — the app's alone). The office root they read
 * (assets/office-root.zip: the core's state, its apps' manifests, the console's registry) is unpacked to
 * files/office, and again whenever the APK carries another commit's. The first start mints the code that
 * makes the owner (forward-auth -first-run) and keeps its link in files/auth, where the app opens it. The
 * machine ({@link EngineService}) is started only for an app that runs in a container.
 */
public class NativeService extends Service {

    static final String STOP = "stop";
    static final String CONSOLE = "http://console.localhost:8080";
    private static final String SIGNIN = "http://signin.localhost:8080";
    private static final String CHANNEL = "office";
    private static final Object LOCK = new Object();
    private static Process auth, core;   // the two processes; null while none runs
    private static boolean starting;     // between a start being asked and both running
    private static boolean stopping;     // a stop was asked: the start in progress launches nothing more

    static boolean running() {
        synchronized (LOCK) {
            return starting || (core != null && core.isAlive());
        }
    }

    private static long logFrom;   // the log's length as this start's core began: its own lines come after

    /**
     * The core of THIS start is up and holds the edge's port: alive, and its log, since it began, says its
     * edge listens — dgo writes that line only once every listener is bound. Before it, 127.0.0.1:8080 may be
     * any app's (loopback is every app's): what answers there is not ours to send the owner to.
     */
    static boolean serving(Context c) {
        long from;
        synchronized (LOCK) {
            if (starting || core == null || !core.isAlive()) return false;
            from = logFrom;
        }
        try (java.io.RandomAccessFile r = new java.io.RandomAccessFile(log(c), "r")) {
            long to = Math.min(r.length(), from + (256 << 10));
            if (to <= from) return false;
            byte[] b = new byte[(int) (to - from)];
            r.seek(from);
            r.readFully(b);
            return new String(b, StandardCharsets.UTF_8).contains("the office's core: the edge on 127.0.0.1:8080");
        } catch (IOException e) {
            return false;
        }
    }

    static File log(Context c) {
        return new File(c.getFilesDir(), "native.log");
    }

    /** The owner's one-time link, while there is no owner yet: what the app opens first. */
    static File firstRunLink(Context c) {
        return new File(new File(c.getFilesDir(), "auth"), "first-run-link");
    }

    static boolean installed(Context c) {
        File lib = new File(c.getApplicationInfo().nativeLibraryDir);
        return new File(lib, "libdgo.so").exists() && new File(lib, "libforward-auth.so").exists();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, getString(R.string.engine), NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, getPackageManager().getLaunchIntentForPackage(getPackageName()),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, NativeService.class).setAction(STOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification n = new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle(getString(R.string.engine_running)).setOngoing(true).setContentIntent(open)
                .addAction(new Notification.Action.Builder(null, getString(R.string.engine_stop), stop).build())
                .build();
        if (Build.VERSION.SDK_INT >= 34) startForeground(2, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(2, n);
        if (intent != null && STOP.equals(intent.getAction())) {
            synchronized (LOCK) {
                if (stopping) return START_NOT_STICKY;
                stopping = true;
            }
            new Thread(this::shutdown).start();
            return START_NOT_STICKY;
        }
        synchronized (LOCK) {
            if (starting || (core != null && core.isAlive())) return START_NOT_STICKY;   // one core
            starting = true;
            stopping = false;
        }
        new Thread(this::run).start();
        return START_NOT_STICKY;
    }

    /**
     * SIGTERM first — the core finishes the requests in flight and removes its sockets; forward-auth ends at
     * once, and the socket it leaves is replaced at its next start — then a kill.
     */
    private void shutdown() {
        Process c, a;
        synchronized (LOCK) {
            c = core;
            a = auth;
        }
        end(c);   // an unpack this core asked for stops with it (its wanted says no once stopping is set)
        end(a);
        boolean idle;
        synchronized (LOCK) {
            idle = !starting;
        }
        if (idle) {
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
        }
    }

    private static void end(Process p) {
        if (p == null || !p.isAlive()) return;
        p.destroy();
        try {
            if (!p.waitFor(35, TimeUnit.SECONDS)) p.destroyForcibly();   // the core's own grace is 30 s
        } catch (InterruptedException e) {
            p.destroyForcibly();
        }
    }

    private void run() {
        Process a = null, c = null;
        try {
            File files = getFilesDir();
            File log = log(this);
            if (log.length() > (1 << 20)) log.renameTo(new File(files, "native.log.1"));   // one MiB, and the one before it
            File office = unpackRoot(files);
            File run = own(new File(files, "run"));
            // what an earlier core left (an ask it made in its last second, a process killed mid-unpack):
            // this one asks anew, for itself
            new File(run, "machine-wanted").delete();
            if (!Guest.busy()) {
                new File(run, "machine-step").delete();
                new File(run, "machine-refused").delete();
            }
            synchronized (LOCK) {
                lastSaid = null;
                looped = false;   // a new core is a new start, whatever an old loop held
                refusalPlaced = false;
                quick = 0;
                lastStart = 0;
            }
            File authDir = own(new File(files, "auth"));
            String lib = getApplicationInfo().nativeLibraryDir;
            File users = new File(authDir, "users");

            ProcessBuilder fa = new ProcessBuilder(lib + "/libforward-auth.so").directory(files)
                    .redirectErrorStream(true).redirectOutput(ProcessBuilder.Redirect.appendTo(log(this)));
            Map<String, String> env = fa.environment();
            env.put("FORWARD_AUTH_LISTEN", "unix:" + new File(run, "forward-auth.sock"));
            env.put("FORWARD_AUTH_SECRET", secret(new File(authDir, "secret")));
            env.put("FORWARD_AUTH_EXTERNAL_URL", SIGNIN);
            env.put("FORWARD_AUTH_ALLOWED_HOSTS", ".localhost");
            env.put("FORWARD_AUTH_USERS_FILE", users.getAbsolutePath());
            env.put("FORWARD_AUTH_SETUP_FILE", new File(authDir, "setup").getAbsolutePath());
            env.put("TMPDIR", getCacheDir().getAbsolutePath());
            if (users.exists()) {
                firstRunLink(this).delete();   // the owner is made: the link is spent
            } else if (!firstRunLink(this).exists()) {
                firstRun(lib, env);
            }

            ProcessBuilder dgo = new ProcessBuilder(lib + "/libdgo.so", "be-child", "native",
                    "--listen", "127.0.0.1:8080", "--dir", run.getAbsolutePath(), "--domain", "localhost")
                    .directory(files).redirectErrorStream(true).redirectOutput(ProcessBuilder.Redirect.appendTo(log(this)));
            dgo.environment().put("DGO_OFFICE_ROOT", office.getAbsolutePath());
            dgo.environment().put("TMPDIR", getCacheDir().getAbsolutePath());
            synchronized (LOCK) {
                if (stopping) return;
                a = fa.start();
                auth = a;
                logFrom = log(this).length();
                c = dgo.start();
                core = c;
                starting = false;
            }
            // either one ending ends the other: a core without its identity service answers nobody — and the
            // control plane's ask for the machine (a container app chosen) is answered here, once a second
            File wanted = new File(run, "machine-wanted");
            while (!c.waitFor(1, TimeUnit.SECONDS)) {
                if (!a.isAlive()) break;
                if (wanted.exists() && wanted.delete()) wantMachine(run);
            }
        } catch (Exception e) {
            try (OutputStream o = new FileOutputStream(log(this), true)) {
                o.write(("\n[the app] the office's core did not start: " + e + "\n").getBytes(StandardCharsets.UTF_8));
            } catch (IOException ignored) {
                // nothing more to say than the log already shows
            }
        } finally {
            end(c);   // one of them ended (or never started): the other serves nothing alone
            end(a);
            boolean last;
            synchronized (LOCK) {
                if (c == null) starting = false;
                last = core == c && !starting;
                if (core == c) core = null;
                if (auth == a) auth = null;
                if (last) stopping = false;
            }
            if (last) {
                stopForeground(STOP_FOREGROUND_REMOVE);
                stopSelf();
            }
        }
    }

    /**
     * The machine, asked for by the core's control plane (android-path.md "the machine on demand"): started
     * behind it — unless it is already running, or not on this phone yet (its disk comes with the APK
     * today, unpacked here; fetched in pieces once the APK is thin, DGO-1089), which the log says.
     */
    private void wantMachine(File run) {
        synchronized (LOCK) {
            if (stopping) return;   // the core is in its last seconds: nothing is started behind it
        }
        String refused = null;
        if (EngineService.running() && EngineService.behindCore()) {
            say(run, null, "the machine is running already, behind the core");
            return;
        } else if (EngineService.running()) {
            refused = "the machine's own office is running on this phone: stop it from its notification first";
        } else if (!EngineService.installed(this)) {
            refused = "this app carries no machine (DGO-1089): a container app cannot start";
        } else if (!EngineService.guest(this).exists()) {
            if (!Guest.inApk(this) && !Guest.fetchable()) {
                refused = "the machine is not on this phone yet (DGO-1089): a container app cannot start";
            } else if (!Guest.busy()) {
                new Thread(() -> unpackThenStart(run)).start();
                return;
            } else {
                return;   // unpacking: its step is the wizard's
            }
        } else {
            refused = startMachine();
        }
        say(run, refused, refused != null ? refused : "the machine is starting, behind the core");
    }

    /**
     * The machine's disk out of the APK, or fetched in pieces where the APK names a published one (DGO-1089),
     * its progress the wizard's step (machine-step), then the machine started — behind a core, if one still
     * runs. The CPU is kept awake for it: the screen that waits for it may sleep, and a fetch or an unpack of
     * minutes would freeze with it.
     */
    private void unpackThenStart(File run) {
        File step = new File(run, "machine-step");
        int[] last = {-1};
        boolean[] mine = {true};   // a Busy one leaves the running unpack's step alone
        // a core runs (or is starting: the one that asked may have been restarted meanwhile), and no stop
        java.util.function.BooleanSupplier ours = () -> {
            synchronized (LOCK) {
                return (starting || (core != null && core.isAlive())) && !stopping;
            }
        };
        android.os.PowerManager.WakeLock awake = getSystemService(android.os.PowerManager.class)
                .newWakeLock(android.os.PowerManager.PARTIAL_WAKE_LOCK, "dgo:unpack");
        awake.setReferenceCounted(false);
        awake.acquire(6 * 60 * 60 * 1000L);   // a slow network's fetch and the slowest phone's unpack: never held for good
        // out of the APK when it carries the machine, else fetched in pieces (DGO-1089): 0–49 fetching
        boolean fetched = !Guest.inApk(this);
        java.util.function.IntConsumer progress = p -> {
            if (p == last[0]) return;
            last[0] = p;
            String said = !fetched ? "the office's machine is being unpacked: " + p + "%"
                    : p < 50 ? "the office's machine is being fetched: " + (p * 2) + "%"
                    : "the office's machine is being unpacked: " + ((p - 50) * 2) + "%";
            try {
                place(step, said, false);
            } catch (IOException ignored) {
                // a step the wizard does not see is a step, not a failure
            }
        };
        try {
            if (fetched) Guest.fetch(this, ours, progress);
            else Guest.unpack(this, true, ours, progress);
            step.delete();
            if (!ours.getAsBoolean()) {
                say(run, null, "the machine is unpacked; no core runs now, so it is not started");
                return;
            }
            String refused = startMachine();
            say(run, refused, refused != null ? refused : "the machine is unpacked and starting, behind the core");
        } catch (Guest.Busy e) {
            mine[0] = false;   // another unpack is under way: its end starts the machine, or says why not
        } catch (Guest.Cancelled e) {
            say(run, null, "the machine's unpack stopped with the core");
        } catch (Guest.Absent e) {
            say(run, "the machine is not on this phone yet (DGO-1089): a container app cannot start", null);
        } catch (Guest.Metered e) {
            say(run, "the machine is " + Math.max(1, (e.left + (1L << 29)) >> 30) + " GB to fetch and the phone's network is metered:"
                    + " on Wi-Fi it is fetched — open the app again there", null);
        } catch (Guest.NoRoom e) {
            say(run, "the phone has " + (e.free >> 30) + " GB free, and the machine needs " + ((e.need + (1L << 30) - 1) >> 30) + " GB", null);
        } catch (Exception e) {
            say(run, "the machine could not be " + (fetched ? "fetched or unpacked: " : "unpacked: ") + e, null);
        } finally {
            if (mine[0]) step.delete();
            awake.release();
        }
    }

    /** EngineService behind the core; null, or why Android did not let it start now. */
    private String startMachine() {
        // a machine that ends right after it starts, again and again (its disk, QEMU), is not started a fourth
        // time — every ask would boot it anew, and the waiting page asks every few seconds. A start is asked only
        // while no machine runs, so one asked within two minutes of the last is a machine that ended within them;
        // refused until the owner's return to the app tries again (inFront). The clock is the phone's uptime: a
        // wall clock set back would make an hour's run look like a crash.
        long now = android.os.SystemClock.elapsedRealtime();
        boolean soon;
        // the refusal gone while the loop was held is the owner asking again: an enable forgot it (serve's
        // down), as inFront does — the count starts over (only those and a core start remove it meanwhile).
        // Only a refusal known to be on the disk: one that could not be written (a full disk) is no ask
        File refusedFile = new File(new File(getFilesDir(), "run"), "machine-refused");
        synchronized (LOCK) {
            if (looped && refusalPlaced && !refusedFile.exists()) {
                looped = false;
                refusalPlaced = false;
                quick = 0;
                lastStart = 0;
            }
            // within 15 s of a start: that one is on its way (its service not up yet) — or it ended faster than
            // that, which the next ask after the 15 s counts
            if (lastStart > 0 && now - lastStart < 15_000L) return null;
            soon = lastStart > 0 && now - lastStart < 2 * 60 * 1000L;
            if (looped || soon && quick >= 2) {
                looped = true;
                return "the office's machine ended within two minutes of starting, three times running (stopped, "
                        + "or failed: its console log says why) — open the app again to try once more";
            }
        }
        try {
            startForegroundService(new Intent(this, EngineService.class).putExtra(EngineService.BEHIND_CORE, true));
            synchronized (LOCK) {   // counted only once it is started: a start Android refused is no crash
                quick = soon ? quick + 1 : 0;
                lastStart = now;
            }
            return null;
        } catch (RuntimeException e) {   // Android 12+ refuses a foreground start while the app is not in view
            return "Android did not let the machine start now (" + e.getClass().getSimpleName() + "): open the app and it starts";
        }
    }

    private static long lastStart;    // the uptime startMachine last started the machine at (0: not since the process began)
    private static int quick;         // how many starts in a row came within two minutes of the one before
    private static boolean looped;    // a crash loop was refused: until the owner asks again (inFront, an enable)
    private static boolean refusalPlaced;   // …and its refusal is on the disk (say), whose going is that ask

    /**
     * The app is in view (an activity resumed): whatever kept the machine from starting is asked again, once
     * — a start Android refused out of view, room made since, the machine's own office stopped since: the
     * owner coming back to the app is the retry the waiting page never makes on its own (it loads itself
     * every few seconds, and must not restart what fails over and over).
     */
    static void inFront(Context c) {
        if (!running()) return;
        File run = new File(c.getFilesDir(), "run");
        File refused = new File(run, "machine-refused");
        if (!refused.exists()) return;
        synchronized (LOCK) {   // first: an ask that lands meanwhile is not refused anew by the old count
            quick = 0;   // the owner's try once more, a crash loop's included
            lastStart = 0;
            looped = false;
            refusalPlaced = false;
        }
        if (!refused.delete()) return;
        try {
            place(new File(run, "machine-wanted"), "1\n", false);
        } catch (IOException ignored) {
            // the wizard's next enable asks again
        }
    }

    private static String lastSaid;   // the log's last line from here: the wizard's polls ask again and again

    /**
     * The refusal the control plane answers the wizard with (run/machine-refused, or none) — one short line,
     * as the core reads it — and the log's line, once while it says the same.
     */
    private void say(File run, String refused, String line) {
        if (refused != null) {
            refused = refused.replaceAll("\\s+", " ").trim();
            if (refused.length() > 300) refused = refused.substring(0, 300) + "…";
        }
        File refusedFile = new File(run, "machine-refused");
        try {
            if (refused != null) {
                place(refusedFile, refused, true);
                synchronized (LOCK) {
                    if (looped) refusalPlaced = true;   // a held loop's refusal, on the disk: its going is an ask again
                }
            } else {
                refusedFile.delete();
                synchronized (LOCK) {
                    refusalPlaced = false;   // the app's own removal is no ask: the next refusal is placed anew
                }
            }
        } catch (IOException ignored) {
            // the log below says it
        }
        String said = line != null ? line : refused;
        synchronized (LOCK) {
            if (said.equals(lastSaid)) return;
            lastSaid = said;
        }
        try (OutputStream o = new FileOutputStream(log(this), true)) {
            o.write(("[the app] " + said + "\n").getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
            // the control plane's job says it too
        }
    }

    /**
     * The owner's one-time code, minted here and given to forward-auth on stdin (`-first-run`, which keeps
     * only its sha256); the link that spends it is kept for the app to open — on this phone alone.
     */
    private void firstRun(String lib, Map<String, String> env) throws Exception {
        byte[] raw = new byte[33];
        new SecureRandom().nextBytes(raw);
        String code = Base64.encodeToString(raw, Base64.URL_SAFE | Base64.NO_PADDING | Base64.NO_WRAP);   // 44 characters
        // its reasons on the log (they never quote the code); its one word on stdout
        ProcessBuilder pb = new ProcessBuilder(lib + "/libforward-auth.so", "-first-run").directory(getFilesDir())
                .redirectError(ProcessBuilder.Redirect.appendTo(log(this)));
        pb.environment().putAll(env);
        Process p = pb.start();
        try (OutputStream in = p.getOutputStream()) {
            in.write((code + "\n").getBytes(StandardCharsets.UTF_8));
        }
        String said;
        try (BufferedReader out = new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
            said = out.readLine();
        }
        boolean ended = p.waitFor(30, TimeUnit.SECONDS);
        if (!ended) p.destroyForcibly();
        if ("owner-exists".equals(said)) return;
        if (!"pending".equals(said)) {
            throw new IOException("forward-auth -first-run said " + said + (ended ? " (exit " + p.exitValue() + ")" : " and did not end"));
        }
        place(firstRunLink(this), SIGNIN + "/setup?code=" + code + "&rd=" + CONSOLE + "/");
    }

    /** text at f, whole or not at all: a .part, synced, then renamed — a cut-short write is never f. */
    private static void place(File f, String text) throws IOException {
        place(f, text, true);
    }

    /**
     * …or, unsynced, a line only read while this process runs (a step's progress): a sync there would wait
     * behind the gigabytes an unpack has written and not yet synced.
     */
    private static void place(File f, String text, boolean sync) throws IOException {
        File part = new File(f.getPath() + ".part");
        try (FileOutputStream o = new FileOutputStream(part)) {
            o.write(text.getBytes(StandardCharsets.UTF_8));
            if (sync) o.getFD().sync();
        }
        if (!part.renameTo(f)) throw new IOException("could not place " + f);
    }

    /**
     * forward-auth's cookie key: made once, 32 random bytes as hex, kept in the app's own storage — and made
     * again when what is there is not one (a key cut short would keep forward-auth from starting at all;
     * the sessions signed with a lost key end, nothing more).
     */
    private static String secret(File f) throws IOException {
        if (f.exists()) {
            String had = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8).trim();
            if (had.matches("[0-9a-f]{64}")) return had;
        }
        byte[] raw = new byte[32];
        new SecureRandom().nextBytes(raw);
        StringBuilder hex = new StringBuilder();
        for (byte b : raw) hex.append(String.format("%02x", b));
        place(f, hex.toString());
        return hex.toString();
    }

    /** A directory of the app's own, opened by it alone (the core refuses one others may open). */
    private static File own(File d) throws IOException {
        if (!d.isDirectory() && !d.mkdirs()) throw new IOException("could not make " + d);
        boolean ok = d.setReadable(false, false) && d.setReadable(true, true)
                && d.setWritable(false, false) && d.setWritable(true, true)
                && d.setExecutable(false, false) && d.setExecutable(true, true);
        if (!ok) throw new IOException("could not make " + d + " the app's alone");
        return d;
    }

    /**
     * assets/office-root.zip into files/office — unless the root there is the one the APK carries (its
     * marker, which names the commit, is the same). Into office.new first, then in place of the old one,
     * so a cut-short unpack is never a root; no entry may land outside it.
     */
    private File unpackRoot(File files) throws IOException {
        File office = new File(files, "office");
        File old = new File(files, "office.old");
        File marker = new File(office, ".dgo-office-root");
        // a swap cut short (below): office is gone and the old root waits beside it — it is the office again
        if (!marker.isFile() && new File(old, ".dgo-office-root").isFile()) {
            delete(office);
            if (!old.renameTo(office)) throw new IOException("could not take back " + office);
        }
        delete(old);   // a swap that finished but for this
        byte[] want = entry(".dgo-office-root");
        if (want != null && marker.isFile() && java.util.Arrays.equals(want, Files.readAllBytes(marker.toPath()))) return office;
        File fresh = new File(files, "office.new");
        delete(fresh);
        own(fresh);
        String base = fresh.getCanonicalPath() + File.separator;
        try (ZipInputStream zip = new ZipInputStream(getAssets().open("office-root.zip"))) {
            for (ZipEntry e; (e = zip.getNextEntry()) != null; ) {
                File to = new File(fresh, name(e));
                if (!to.getCanonicalPath().startsWith(base)) throw new IOException("office-root.zip: " + e.getName() + " leaves the root");
                if (e.isDirectory()) {
                    own(to);
                    continue;
                }
                own(to.getParentFile());
                try (OutputStream o = new FileOutputStream(to)) {
                    copy(zip, o);
                }
            }
        }
        if (!new File(fresh, ".dgo-office-root").isFile()) throw new IOException("office-root.zip holds no .dgo-office-root");
        // the office's own choices — its record and its apps, which the control plane writes into the root's
        // state — are the office's, not the APK's: the new root takes the old one's state, as an office's
        // update never overwrites its platform.state.yaml. The APK's own is kept beside it as
        // platform.state.shipped.yaml, whose apps the core adds where the office's state lacks them (a core
        // app a later APK brings, native.go). A state of another schema is not carried — the new core could
        // not read it — but kept in files/office-state.schema-<n>.yaml, and the log says the office starts afresh.
        File had = new File(office, "platform.state.yaml");
        File shipped = new File(fresh, "platform.state.yaml");
        if (had.isFile() && shipped.isFile()) {
            String was = schema(had), is = schema(shipped);
            if (was.equals(is)) {
                copySynced(shipped, new File(fresh, "platform.state.shipped.yaml"));
                copySynced(had, shipped);
            } else {
                // kept, never dropped: the office's record and apps beside the roots (files/, which no update
                // swaps), named by its schema — a short name, whatever the line held
                String n = was.replaceAll("[^A-Za-z0-9.]", "_");
                if (n.length() > 40) n = n.substring(0, 40);
                File kept = new File(files, "office-state.schema-" + n + ".yaml");
                copySynced(had, kept);
                try (OutputStream o = new FileOutputStream(log(this), true)) {
                    o.write(("[the app] the office's state is of schema " + was + ", this core's " + is
                            + ": the office starts from the APK's state; its own is kept as " + kept.getName() + "\n")
                            .getBytes(StandardCharsets.UTF_8));
                }
            }
        }
        // swapped by renames, so a cut-short swap leaves a whole root to take back (above), never none
        if (office.exists() && !office.renameTo(old)) throw new IOException("could not move " + office + " aside");
        if (!fresh.renameTo(office)) {
            old.renameTo(office);   // the old root back at once: never a start with no office at all
            throw new IOException("could not place " + office);
        }
        delete(old);
        return office;
    }

    /** from copied to to, synced: on the phone's storage before the root it is in replaces the old one. */
    private static void copySynced(File from, File to) throws IOException {
        try (InputStream in = new FileInputStream(from); FileOutputStream out = new FileOutputStream(to)) {
            copy(in, out);
            out.getFD().sync();
        }
    }

    /**
     * A state file's schema_version, as it is written ("" for none) — its trailing comment off, as YAML reads
     * it, so `1  # …` is the schema `1` is.
     */
    private static String schema(File state) throws IOException {
        // decoded leniently: a byte that is not UTF-8 elsewhere in the file must not keep the core from starting
        for (String l : new String(Files.readAllBytes(state.toPath()), StandardCharsets.UTF_8).split("\n")) {
            if (l.startsWith("schema_version:")) {
                return l.substring("schema_version:".length()).replaceFirst("\\s+#.*$", "").trim();
            }
        }
        return "";
    }

    /** One file of assets/office-root.zip, or null. */
    private byte[] entry(String wanted) throws IOException {
        try (ZipInputStream zip = new ZipInputStream(getAssets().open("office-root.zip"))) {
            for (ZipEntry e; (e = zip.getNextEntry()) != null; ) {
                if (!e.isDirectory() && name(e).equals(wanted)) {
                    ByteArrayOutputStream b = new ByteArrayOutputStream();
                    copy(zip, b);
                    return b.toByteArray();
                }
            }
        }
        return null;
    }

    /** An entry's path inside the root: zip's own "./" prefix, when it wrote one, is not part of it. */
    private static String name(ZipEntry e) {
        String n = e.getName();
        while (n.startsWith("./")) n = n.substring(2);
        return n;
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[1 << 16];
        for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
    }

    private static void delete(File f) {
        File[] kids = f.isDirectory() ? f.listFiles() : null;
        if (kids != null) for (File k : kids) delete(k);
        f.delete();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
