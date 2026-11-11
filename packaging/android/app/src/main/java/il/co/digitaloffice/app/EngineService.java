package il.co.digitaloffice.app;

import android.app.ActivityManager;
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
import android.os.PowerManager;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * This phone's office (DGO-1071): the office's own engine — a Linux guest with Docker 28 and the office in
 * it, the MacBook engine's guest — run by QEMU from the app's native-library directory, as a foreground
 * service so Android keeps it. No app gets KVM on a stock phone, so QEMU emulates the CPU (TCG) unless the
 * phone opens /dev/kvm to it. The guest's edge (traefik, port 80) is forwarded to the phone's
 * 127.0.0.1:8080, where the console answers as http://console.localhost:8080 — the address the app opens,
 * as Lima forwards it on the Mac.
 */
public class EngineService extends Service {

    static final String STOP = "stop";
    /**
     * Started for the office's native core (DGO-1090, android-path.md "the machine on demand"): the guest's
     * edge forwarded to a loopback port chosen at this boot (not 8080, which the core's edge holds), the
     * core's token for this boot given to the guest outside its network (QEMU fw_cfg), and the machine
     * reported to the core in files/run/machine once its QEMU holds the port — removed when it ends. The core
     * sends it nothing until it has proved the token (native.go machineGate).
     */
    static final String BEHIND_CORE = "behind_core";
    private static final String CHANNEL = "engine";
    private static volatile boolean behindCore;   // this start's: the machine of the native core
    private static final Object LOCK = new Object();
    private static Process qemu;          // the one QEMU; null while none runs
    private static Avf avf;               // or the machine on the phone's own virtualization (DGO-1328)
    private static boolean starting;      // between a start being asked and the machine running
    private static boolean stopping;      // a stop was asked: the start in progress launches nothing

    static boolean running() {
        synchronized (LOCK) {
            return starting || (qemu != null && qemu.isAlive()) || (avf != null && avf.alive());
        }
    }

    /**
     * files/run/engine: which engine runs the machine and why — "avf", "kvm" or "tcg", or "none" (an APK with no
     * QEMU where AVF did not come up, DGO-1723) — the reason, then the four
     * checks, "1 <line>" or "0 <line>" each (Virt) — written at every start, read by the status screen.
     */
    static File engineFile(Context c) {
        return new File(new File(c.getFilesDir(), "run"), "engine");
    }

    /** files/run/times: what each stage of this start took, "<stage> <seconds>" a line (the status screen). */
    static File timesFile(Context c) {
        return new File(new File(c.getFilesDir(), "run"), "times");
    }

    /** The machine running (or starting) now was started behind the native core — not its own office. */
    static boolean behindCore() {
        return behindCore;
    }

    static File guest(Context c) {
        return new File(c.getFilesDir(), "guest.img");
    }

    static File console(Context c) {
        return new File(c.getFilesDir(), "console.log");
    }

    /** The APK carries QEMU (the arm64 ones do; an x86_64 APK carries none, DGO-1723). */
    static boolean hasQemu(Context c) {
        return new File(c.getApplicationInfo().nativeLibraryDir, "libqemu-system-aarch64.so").exists();
    }

    /**
     * Does this app have an engine for its machine? QEMU, where the APK carries it. An x86_64 Android (the
     * emulator, DGO-1723) has no QEMU in its APK, and its engine is the phone's own virtualization: the app has one
     * there when the phone has AVF for a machine that is not protected (or does not say, until the grant). The
     * grant and the machine's kernel come later, each with its own line on the status screen; a phone with no
     * AVF says so here, as an arm64 APK without QEMU did.
     */
    static boolean installed(Context c) {
        if (hasQemu(c)) return true;
        if (!"amd64".equals(Guest.ARCH)) return false;
        Virt.Choice v = Virt.choose(c);
        return v.avf.ok && (v.unprotected.ok || v.unknown);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, getString(R.string.engine), NotificationManager.IMPORTANCE_LOW));
        // a tap opens the office; Stop powers its machine off (the only way to stop it: the app is the office)
        // the launcher's own intent: it brings the app's task to the front as it is (the console, or the
        // screen before it), where a new MainActivity would stack a second console on the first
        PendingIntent open = PendingIntent.getActivity(this, 0, getPackageManager().getLaunchIntentForPackage(getPackageName()),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, EngineService.class).setAction(STOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification n = new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle(getString(R.string.engine_running)).setOngoing(true).setContentIntent(open)
                .addAction(new Notification.Action.Builder(null, getString(R.string.status), status(this)).build())
                .addAction(new Notification.Action.Builder(null, getString(R.string.engine_stop), stop).build())
                .build();
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(1, n);
        if (intent != null && STOP.equals(intent.getAction())) {
            synchronized (LOCK) {
                if (stopping) return START_NOT_STICKY;   // one power-off: a second Ctrl-A c would leave the monitor
                stopping = true;
            }
            new Thread(this::shutdown).start();
            return START_NOT_STICKY;
        }
        synchronized (LOCK) {
            // one engine: a second start while either machine runs would boot QEMU over the disk AVF holds
            if (starting || (qemu != null && qemu.isAlive()) || (avf != null && avf.alive())) return START_NOT_STICKY;
            starting = true;
            stopping = false;
            behindCore = intent != null && intent.getBooleanExtra(BEHIND_CORE, false);
        }
        new Thread(this::run).start();
        // not sticky: after the system kills the app, the guest is not booted again unattended
        return START_NOT_STICKY;
    }

    /** The guest powers itself off (its journal and its databases closed), then QEMU is ended if it has not. */
    private void shutdown() {
        Process p;
        Avf a;
        synchronized (LOCK) {
            p = qemu;
            a = avf;
        }
        if (a != null && a.alive()) a.powerDown(180_000);
        if (p != null && p.isAlive()) {
            try {
                OutputStream mon = p.getOutputStream();   // -nographic: the monitor is on stdio after Ctrl-A c
                mon.write(new byte[]{0x01, 'c'});
                mon.write("system_powerdown\n".getBytes());
                mon.flush();
                // Docker and Postgres stop slowly under emulation (systemd alone allows 90 s a unit)
                if (!p.waitFor(180, TimeUnit.SECONDS)) p.destroy();
            } catch (Exception e) {
                p.destroy();
            }
        }
        // a start still preparing sees `stopping` before it launches, and ends its own service
        boolean idle;
        synchronized (LOCK) {
            idle = !starting;
        }
        if (idle) {
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
        }
    }

    private void run() {
        Process mine = null;
        Avf myAvf = null;
        // the CPU stays on while the office runs: with the screen off a phone sleeps its CPU, and the office
        // (its first start most of all) would stand still. Released when QEMU ends.
        PowerManager.WakeLock awake = getSystemService(PowerManager.class)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "dgo:office");
        awake.setReferenceCounted(false);
        try {
            awake.acquire();
            File usr = new File(getFilesDir(), "usr");
            File share = new File(usr, "share/qemu");
            copyAssets("qemu", share);
            File resolv = new File(usr, "etc/resolv.conf");
            if (!resolv.exists()) {   // slirp answers the guest's DNS from the prefix the build baked in
                resolv.getParentFile().mkdirs();
                try (OutputStream o = new FileOutputStream(resolv)) {
                    o.write("nameserver 8.8.8.8\nnameserver 1.1.1.1\n".getBytes());
                }
            }
            File vars = new File(getFilesDir(), "efi-vars.fd");
            if (!vars.exists()) try (RandomAccessFile f = new RandomAccessFile(vars, "rw")) {
                f.setLength(64L << 20);
            }
            String lib = getApplicationInfo().nativeLibraryDir;
            boolean behind = behindCore;
            File run = new File(getFilesDir(), "run");   // the core's own directory (NativeService)
            File tokenFile = new File(run, "edge-token"), reported = new File(run, "machine");
            int port = 8080;
            String token = "";
            if (behind) {
                reported.delete();
                byte[] raw = new byte[32];
                new java.security.SecureRandom().nextBytes(raw);
                StringBuilder hex = new StringBuilder();
                for (byte b : raw) hex.append(String.format("%02x", b));
                token = hex.toString();
                try (FileOutputStream o = new FileOutputStream(tokenFile)) {
                    o.write(token.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                    o.getFD().sync();
                }
                // a free loopback port now; QEMU binds it — and the core proves who holds it before it trusts it
                try (java.net.ServerSocket probe = new java.net.ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))) {
                    port = probe.getLocalPort();
                }
            }
            boolean kvm = new File("/dev/kvm").canRead() && new File("/dev/kvm").canWrite();
            ActivityManager.MemoryInfo mem = new ActivityManager.MemoryInfo();
            getSystemService(ActivityManager.class).getMemoryInfo(mem);
            long mb = Math.max(2048, Math.min(6144, mem.totalMem / 2 / (1 << 20)));   // half the phone, 2–6 GiB
            int cpus = Math.max(2, Math.min(4, Runtime.getRuntime().availableProcessors() / 2));
            long began = System.currentTimeMillis();

            // THE ENGINE (DGO-1328): the phone's own virtualization where its four checks pass (Virt) — behind
            // the core, whose token for this boot has a disk of its own there — else QEMU's emulation; which,
            // and why, kept for the status screen. AVF that does not boot the machine says why and hands this
            // very start to QEMU: the office comes up either way.
            Virt.Choice choice = Virt.choose(this);
            // an APK with no QEMU (x86_64, DGO-1723) has AVF alone: /dev/kvm is no reason to pass it by there
            boolean qemuHere = hasQemu(this);
            boolean hardware = behind && choice.hardware && (!kvm || !qemuHere);
            engine(hardware ? "avf" : kvm ? "kvm" : "tcg", hardware ? choice.why
                    : kvm ? "הטלפון פותח /dev/kvm לאפליקציה: QEMU רץ בהאצת חומרה"
                    : behind ? choice.why : "המשרד של המכונה עצמה (לא מאחורי הליבה) רץ ב-QEMU", choice);
            Avf a = null;
            if (hardware) {
                a = new Avf(this, console(this));
                synchronized (LOCK) {
                    if (stopping) return;   // stopped while preparing: nothing is launched (finally ends the service)
                    myAvf = a;
                    avf = a;
                }
                String failed = null;
                try {
                    a.start(port, token, mb << 20, new File(run, "avf-cpu").exists());
                    boolean stop;
                    synchronized (LOCK) {
                        starting = false;
                        stop = stopping;   // a Stop asked while AVF was starting: shutdown() found no machine yet
                    }
                    if (stop) {
                        a.powerDown(180_000);
                        return;
                    }
                    Avf on = a;
                    if (behind) report(on::alive, port, token, reported);
                    watchOffice(on::alive, began);
                    boolean booted = false;
                    while (a.alive()) {
                        if (!booted && a.reached()) {
                            booted = true;
                            long s = (System.currentTimeMillis() - began) / 1000;
                            times("avf-edge", s);
                            place(Virt.bootResult(this), "ok " + s + " s");
                        }
                        Thread.sleep(1000);
                    }
                    if (booted || stopping) return;   // it ran, and ended (a Stop, a power-off): the office's end
                    if (a.resetEarly()) {
                        // the phone reset a guest that matched its CPUs (Tensor G3/G4, measured by others): one CPU
                        // next, and AVF tried again — not a failure that shuts it out
                        place(new File(run, "avf-cpu"), "one");
                        place(Virt.bootResult(this), "retry " + Avf.stopReason(5) + " at boot — the next start asks for one CPU");
                        failed = Avf.stopReason(5) + " at boot";
                    } else {
                        failed = a.why().isEmpty() ? "it ended before its edge answered" : a.why();
                        place(Virt.bootResult(this), "failed " + BuildConfig.VERSION_CODE + " " + failed);
                    }
                } catch (Exception e) {
                    Throwable root = e instanceof java.lang.reflect.InvocationTargetException && e.getCause() != null ? e.getCause() : e;
                    failed = root.getClass().getSimpleName() + ": " + root.getMessage();
                    place(Virt.bootResult(this), "failed " + BuildConfig.VERSION_CODE + " " + root);
                }
                // AVF did not bring the machine up: QEMU does, in this same start — the office comes up either way
                a.kill();
                synchronized (LOCK) {
                    if (avf == a) avf = null;
                    myAvf = null;
                    starting = true;   // QEMU is this start's machine now
                }
                if (qemuHere) {
                    engine("tcg", "AVF לא העלה את המכונה (" + failed + ") — QEMU מעלה אותה", choice);
                    say(this, "[the app] AVF did not bring the machine up: " + failed + " — QEMU boots it");
                } else {
                    engine("none", "AVF לא העלה את המכונה (" + failed + "), ובאפליקציה הזו אין QEMU", choice);
                    say(this, "[the app] AVF did not bring the machine up: " + failed + " — and this APK carries no QEMU");
                    return;   // nothing launched: finally ends this start
                }
            }
            if (!qemuHere) {
                // no QEMU in this APK, and AVF was not this start's engine: behind the core, the first check that is
                // not green says why; the machine's own office (no core in front of it) runs under QEMU alone
                String why = behind ? "באפליקציה הזו אין QEMU, ו-AVF עוד לא יכול להריץ את המכונה: " + choice.why
                        : "באפליקציה הזו אין QEMU, והמשרד של המכונה עצמה (לא מאחורי הליבה) רץ רק ב-QEMU";
                engine("none", why, choice);
                say(this, "[the app] this APK carries no QEMU and AVF is not this start's engine: " + why);
                return;
            }
            List<String> cmd = new ArrayList<>(Arrays.asList(lib + "/libqemu-system-aarch64.so",
                    // QEMU is relocatable: it looks for its ROMs beside its own binary unless told where
                    "-L", share.getAbsolutePath(),
                    "-machine", "virt", "-accel", kvm ? "kvm" : "tcg,thread=multi",
                    // pointer authentication costs TCG up to 40 % of its time (Linaro)
                    "-cpu", kvm ? "host" : "max,pauth=off", "-smp", String.valueOf(cpus), "-m", mb + "M",
                    "-nographic",
                    "-drive", "if=pflash,format=raw,readonly=on,file=" + new File(share, "edk2-aarch64-code.fd"),
                    "-drive", "if=pflash,format=raw,file=" + vars,
                    // discard: blocks the guest frees (the images' tar once loaded) are freed on the phone too
                    "-drive", "if=virtio,format=raw,cache=writeback,discard=unmap,file=" + guest(this),
                    // the guest's edge listens on 80 (traefik); the phone's side is the office's 8080 — or,
                    // behind the native core, this boot's own port
                    "-netdev", "user,id=n0,hostfwd=tcp:127.0.0.1:" + port + "-:80",
                    "-device", "virtio-net-pci,netdev=n0"));
            if (behind) cmd.addAll(Arrays.asList("-fw_cfg", "name=opt/dgo/edge-token,file=" + tokenFile));
            ProcessBuilder pb = new ProcessBuilder(cmd).directory(getFilesDir()).redirectErrorStream(true)
                    .redirectOutput(console(this));
            pb.environment().put("LD_LIBRARY_PATH", lib);
            pb.environment().put("TMPDIR", getCacheDir().getAbsolutePath());
            synchronized (LOCK) {
                if (stopping) return;   // stopped while preparing: nothing is launched (finally ends the service)
                mine = pb.start();
                qemu = mine;
                starting = false;
            }
            Process q = mine;
            if (behind) report(q::isAlive, port, token, reported);
            watchOffice(q::isAlive, began);
            mine.waitFor();
        } catch (Exception e) {
            try (OutputStream o = new FileOutputStream(console(this), true)) {
                o.write(("\n[the app] the engine did not start: " + e + "\n").getBytes());
            } catch (Exception ignored) {
                // nothing more to say than the console already shows
            }
        } finally {
            awake.release();
            boolean last;
            synchronized (LOCK) {
                if (mine == null && myAvf == null) starting = false;   // this run never launched: its own start is over
                // a newer start (even one still preparing) keeps its service
                last = qemu == mine && avf == myAvf && !starting;
                if (qemu == mine) qemu = null;
                if (avf == myAvf) avf = null;
                if (last) stopping = false;
            }
            if (last) {
                // the machine is gone, and no newer start has made its own: the core is told at once (and its
                // token goes with it) — a newer start's files are its own, never this one's to remove
                new File(new File(getFilesDir(), "run"), "machine").delete();
                new File(new File(getFilesDir(), "run"), "edge-token").delete();
                stopForeground(STOP_FOREGROUND_REMOVE);
                stopSelf();
            }
        }
    }

    /** The engine and why (engineFile), with the four checks, written whole. */
    private void engine(String which, String why, Virt.Choice c) {
        StringBuilder s = new StringBuilder(which).append('\n').append(why.replace('\n', ' ')).append('\n');
        for (Virt.Check k : new Virt.Check[]{c.avf, c.unprotected, c.granted, c.boots}) {
            s.append(k.ok ? "1 " : "0 ").append(k.said.replace('\n', ' ')).append('\n');
        }
        try {
            place(engineFile(this), s.toString());
        } catch (Exception ignored) {
            // the status screen says what it can without it
        }
    }

    /**
     * The office in the machine up — bbox run's "up." on its console — measured from the machine's start
     * (timesFile's office-up), once, while the machine runs.
     */
    private void watchOffice(java.util.function.BooleanSupplier alive, long began) {
        Thread t = new Thread(() -> {
            while (alive.getAsBoolean()) {
                String said = MainActivity.tail(console(this), 1 << 16);
                if (MainActivity.runEnded(said)) {
                    times(MainActivity.runFatal(said) ? "office-not-up" : "office-up",
                            (System.currentTimeMillis() - began) / 1000);
                    return;
                }
                try {
                    Thread.sleep(5000);
                } catch (InterruptedException e) {
                    return;
                }
            }
        }, "office-up");
        t.setDaemon(true);
        t.start();
    }

    /** The status screen, as a notification's action opens it (DGO-1328). */
    static PendingIntent status(Context c) {
        return PendingIntent.getActivity(c, 5, new Intent(c, StatusActivity.class),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    /** A line of the app's own on the machine's console, where the status screen and the log show it. */
    static void say(Context c, String line) {
        try (OutputStream o = new FileOutputStream(console(c), true)) {
            o.write(("\n" + line + "\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
        } catch (Exception ignored) {
            // the console is the only place to say it
        }
    }

    /** One stage's time, appended to timesFile (NativeService empties it as the office starts). */
    static void times(Context c, String stage, long seconds) {
        try (OutputStream o = new FileOutputStream(timesFile(c), true)) {
            o.write((stage + " " + seconds + "\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
        } catch (Exception ignored) {
            // a time not kept is a time not shown
        }
    }

    private void times(String stage, long seconds) {
        times(this, stage, seconds);
    }

    /** text at f, whole: a .part, synced, renamed. */
    private static void place(File f, String text) throws java.io.IOException {
        File part = new File(f.getPath() + ".part");
        try (FileOutputStream o = new FileOutputStream(part)) {
            o.write(text.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            o.getFD().sync();
        }
        if (!part.renameTo(f)) throw new java.io.IOException("could not place " + f);
    }

    /**
     * Once the machine answers on its port, it is reported to the core — "<port> <token>", written whole
     * (a .part, synced, renamed) — from a thread of its own while the machine runs.
     */
    private static void report(java.util.function.BooleanSupplier alive, int port, String token, File to) {
        new Thread(() -> {
            while (alive.getAsBoolean()) {
                try (java.net.Socket s = new java.net.Socket()) {
                    s.connect(new java.net.InetSocketAddress("127.0.0.1", port), 500);
                    File part = new File(to.getPath() + ".part");
                    try (FileOutputStream o = new FileOutputStream(part)) {
                        o.write((port + " " + token + "\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
                        o.getFD().sync();
                    }
                    if (alive.getAsBoolean()) part.renameTo(to);
                    else part.delete();
                    return;
                } catch (java.io.IOException e) {
                    try {
                        Thread.sleep(500);
                    } catch (InterruptedException ie) {
                        return;
                    }
                }
            }
        }).start();
    }

    /**
     * The APK's assets/<from>/ into <to>/: QEMU's firmware, where -L points. Each file through a .part and a
     * rename, so a copy cut short is made again; all of them again when the app was updated.
     */
    private void copyAssets(String from, File to) throws Exception {
        String[] names = getAssets().list(from);
        if (names == null) return;
        to.mkdirs();
        // the install's own time, not the version code: hand-built APKs all carry code 1
        long version = getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime;
        File stamp = new File(to, ".from-version");
        String had = stamp.exists() ? new String(java.nio.file.Files.readAllBytes(stamp.toPath())).trim() : "";
        boolean fresh = !had.equals(String.valueOf(version));
        for (String name : names) {
            File dst = new File(to, name);
            if (dst.exists() && !fresh) continue;
            File part = new File(to, name + ".part");
            try (InputStream in = getAssets().open(from + "/" + name); OutputStream out = new FileOutputStream(part)) {
                byte[] buf = new byte[1 << 16];
                for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
            }
            if (!part.renameTo(dst)) throw new java.io.IOException("could not place " + dst);
        }
        try (OutputStream o = new FileOutputStream(stamp)) {
            o.write(String.valueOf(version).getBytes());
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
