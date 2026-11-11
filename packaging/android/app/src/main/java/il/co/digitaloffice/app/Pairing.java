package il.co.digitaloffice.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.RemoteInput;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Build;
import android.os.Bundle;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

/**
 * The app grants itself AVF's two permissions, once, through the phone's own Wireless debugging (DGO-1328):
 * the phone advertises its pairing port and its debugging port over mDNS on the Wi-Fi (_adb-tls-pairing,
 * _adb-tls-connect), found here; the owner types the six digits Settings shows into this app's
 * notification — Settings stays in front, and its dialog with it (it closes when another app comes up);
 * libdgo.so pairs and runs `pm grant` (packaging/dgo/internal/adb). The phone keeps the grant across reboots
 * and updates. On Android 12–13 the same shell switches off the killer of an app's child processes, which
 * would end QEMU's emulated machine.
 */
final class Pairing {

    static final String CHANNEL = "pairing";
    static final String KEY_CODE = "code";
    static final int NOTE = 7;
    private static final String PAIR_SERVICE = "_adb-tls-pairing._tcp";
    private static final String CONNECT_SERVICE = "_adb-tls-connect._tcp";

    /** What the pairing is doing now, and what it said last — the pairing screen reads both. */
    static volatile String state = "", said = "";
    static volatile String pairAt = "", connectAt = "";   // host:port, as discovered
    private static NsdManager.DiscoveryListener pairing, connecting;

    private Pairing() {
    }

    /** Looks for the phone's pairing and debugging ports on the Wi-Fi, until stop(). */
    static synchronized void discover(Context c) {
        NsdManager nsd = c.getSystemService(NsdManager.class);
        if (nsd == null) {
            said = "הטלפון לא מחפש שירותים ברשת (NsdManager)";
            return;
        }
        if (pairing == null) pairing = listen(nsd, PAIR_SERVICE, true);
        if (connecting == null) connecting = listen(nsd, CONNECT_SERVICE, false);
    }

    static synchronized void stop(Context c) {
        NsdManager nsd = c.getSystemService(NsdManager.class);
        for (NsdManager.DiscoveryListener l : new NsdManager.DiscoveryListener[]{pairing, connecting}) {
            if (nsd != null && l != null) {
                try {
                    nsd.stopServiceDiscovery(l);
                } catch (RuntimeException ignored) {
                    // not discovering any more
                }
            }
        }
        pairing = null;
        connecting = null;
    }

    private static NsdManager.DiscoveryListener listen(NsdManager nsd, String type, boolean pair) {
        NsdManager.DiscoveryListener l = new NsdManager.DiscoveryListener() {
            @Override
            public void onServiceFound(NsdServiceInfo s) {
                resolve(nsd, s, pair);
            }

            @Override
            public void onServiceLost(NsdServiceInfo s) {
                if (pair) pairAt = "";
            }

            @Override
            public void onDiscoveryStarted(String t) {
            }

            @Override
            public void onDiscoveryStopped(String t) {
            }

            @Override
            public void onStartDiscoveryFailed(String t, int code) {
                said = "החיפוש של " + t + " לא התחיל (" + code + ")";
            }

            @Override
            public void onStopDiscoveryFailed(String t, int code) {
            }
        };
        nsd.discoverServices(type, NsdManager.PROTOCOL_DNS_SD, l);
        return l;
    }

    @SuppressWarnings("deprecation")   // resolveService: the one call from Android 8 on; 14's callback is newer only
    private static void resolve(NsdManager nsd, NsdServiceInfo s, boolean pair) {
        nsd.resolveService(s, new NsdManager.ResolveListener() {
            @Override
            public void onResolveFailed(NsdServiceInfo s, int code) {
            }

            @Override
            public void onServiceResolved(NsdServiceInfo s) {
                InetAddress host = s.getHost();
                // this phone's own adbd only: on an office's Wi-Fi another phone's Wireless debugging is found
                // too, and pm grant must never go to it
                if (host == null || !mine(host)) return;
                String at = (host instanceof java.net.Inet6Address ? "[" + host.getHostAddress() + "]" : host.getHostAddress()) + ":" + s.getPort();
                if (pair) pairAt = at;
                else connectAt = at;
            }
        });
    }

    /** One of this phone's own addresses. */
    private static boolean mine(InetAddress a) {
        try {
            for (java.net.NetworkInterface n : java.util.Collections.list(java.net.NetworkInterface.getNetworkInterfaces())) {
                for (InetAddress own : java.util.Collections.list(n.getInetAddresses())) {
                    if (own.equals(a)) return true;
                }
            }
        } catch (Exception ignored) {
            // the interfaces do not read: no address is known to be this phone's
        }
        return false;
    }

    /** The notification the owner types the code into, Settings' dialog still open in front of it. */
    static void ask(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "התאמת ניפוי באגים", NotificationManager.IMPORTANCE_HIGH));
        RemoteInput in = new RemoteInput.Builder(KEY_CODE).setLabel("קוד ההתאמה (6 ספרות)").build();
        int mutable = Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0;
        PendingIntent reply = PendingIntent.getBroadcast(c, 3, new Intent(c, Code.class).setPackage(c.getPackageName()),
                PendingIntent.FLAG_UPDATE_CURRENT | mutable);
        Notification.Action act = new Notification.Action.Builder(null, "הזנת הקוד", reply).addRemoteInput(in).build();
        Notification n = new Notification.Builder(c, CHANNEL).setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle("הקוד שבחלון «התאמה עם קוד»")
                .setContentText("הקלד כאן את 6 הספרות, בלי לסגור את החלון בהגדרות")
                .setOngoing(true).addAction(act).build();
        nm.notify(NOTE, n);
    }

    static void tell(Context c, String title, String text) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "התאמת ניפוי באגים", NotificationManager.IMPORTANCE_HIGH));
        PendingIntent open = PendingIntent.getActivity(c, 4, new Intent(c, PairingActivity.class), PendingIntent.FLAG_IMMUTABLE);
        nm.notify(NOTE, new Notification.Builder(c, CHANNEL).setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle(title).setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(open).setAutoCancel(true).build());
    }

    /** The code typed into the notification. */
    public static final class Code extends BroadcastReceiver {
        @Override
        public void onReceive(Context c, Intent i) {
            Bundle in = RemoteInput.getResultsFromIntent(i);
            CharSequence code = in == null ? null : in.getCharSequence(KEY_CODE);
            if (code == null) return;
            // the pairing and the grant take up to two minutes, past a broadcast's own time: the work runs in a
            // thread of the app's process — kept by the office's foreground service — and its end is told in
            // the notification (Pairing.tell)
            Context app = c.getApplicationContext();
            new Thread(() -> run(app, code.toString().replaceAll("[^0-9]", "")), "pairing").start();
        }
    }

    /** Pairs with the code, then grants the permissions and checks them: what it said, in a line. */
    static synchronized void run(Context c, String code) {
        try {
            if (code.length() != 6) throw new Exception("הקוד הוא 6 ספרות — הוקלד «" + code + "»");
            String at = pairAt;
            if (at.isEmpty()) throw new Exception("פורט ההתאמה לא נמצא ברשת: חלון «התאמה עם קוד» צריך להיות פתוח, והטלפון ב-Wi-Fi");
            state = "מתאים…";
            tell(c, "מתאים…", "עם " + at);
            String out = dgo(c, 40, "pair", at, code);
            state = "מותאם — נותן הרשאות…";
            String conn = connectAt;
            for (int i = 0; i < 20 && conn.isEmpty(); i++) {
                Thread.sleep(500);
                conn = connectAt;
            }
            if (conn.isEmpty()) throw new Exception("הותאם (" + out.trim() + "), אבל פורט ניפוי הבאגים לא נמצא ברשת");
            String pkg = c.getPackageName();
            StringBuilder cmd = new StringBuilder("pm grant " + pkg + " " + Virt.MANAGE + " && pm grant " + pkg + " " + Virt.CUSTOM);
            // the killer of an app's child processes, which ends QEMU's machine under load: off, where adb may
            // (12L–16: the global setting; 12: device_config), each a no-op elsewhere
            cmd.append("; settings put global settings_enable_monitor_phantom_procs false");
            if (Build.VERSION.SDK_INT == 31) {
                cmd.append("; device_config set_sync_disabled_for_tests persistent; device_config put activity_manager max_phantom_processes 2147483647");
            }
            cmd.append("; echo dgo-granted");
            String shell = dgo(c, 60, "shell", conn, cmd.toString());
            boolean ok = c.checkSelfPermission(Virt.MANAGE) == android.content.pm.PackageManager.PERMISSION_GRANTED
                    && c.checkSelfPermission(Virt.CUSTOM) == android.content.pm.PackageManager.PERMISSION_GRANTED;
            if (!ok) throw new Exception("הפקודה רצה אבל ההרשאות לא ניתנו: " + shell.trim());
            state = "";
            said = "✓ ההרשאות ניתנו. בהפעלה הבאה המכונה עולה ב-AVF.";
            tell(c, "האצת החומרה מוכנה", said);
        } catch (Exception e) {
            state = "";
            said = "✗ " + e.getMessage();
            tell(c, "ההתאמה לא הצליחה", e.getMessage());
        }
    }

    /** `libdgo.so be-child adb <args>`, its key in the app's own files: what it printed, or its reason. */
    private static String dgo(Context c, int seconds, String... args) throws Exception {
        File dir = new File(c.getFilesDir(), "adb");
        if (!dir.isDirectory() && !dir.mkdirs()) throw new Exception("אין מקום למפתח");
        String lib = c.getApplicationInfo().nativeLibraryDir;
        String[] cmd = new String[3 + args.length];
        cmd[0] = lib + "/libdgo.so";
        cmd[1] = "be-child";
        cmd[2] = "adb";
        System.arraycopy(args, 0, cmd, 3, args.length);
        ProcessBuilder pb = new ProcessBuilder(cmd).redirectErrorStream(true).directory(dir);
        pb.environment().put("DGO_ADB_KEY", new File(dir, "adbkey").getAbsolutePath());
        pb.environment().put("TMPDIR", c.getCacheDir().getAbsolutePath());
        Process p = pb.start();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (InputStream in = p.getInputStream()) {
            byte[] buf = new byte[8192];
            for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
        }
        if (!p.waitFor(seconds, TimeUnit.SECONDS)) {
            p.destroyForcibly();
            throw new Exception("לא הסתיים תוך " + seconds + " שניות");
        }
        String said = out.toString(StandardCharsets.UTF_8.name());
        if (p.exitValue() != 0) throw new Exception(said.replace("dgo adb: ", "").trim());
        return said;
    }
}
