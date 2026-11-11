package il.co.digitaloffice.app;

import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.TimeUnit;

/**
 * Which engine runs this phone's machine, and why (DGO-1328): the phone's own virtualization — the Android
 * Virtualization Framework, the hardware's speed — where the phone allows it to this app, else QEMU's
 * emulation (TCG), on any arm64 phone, many times slower. Four checks decide, each said on the status
 * screen with its reason, in the order a phone fails them:
 * <ol>
 * <li>the phone has AVF for a custom machine: Android 15+ and the virtualization_framework feature;</li>
 * <li>it runs a machine that is not protected — Snapdragon phones run only protected ones, which boot
 * nothing but a signed payload (the phone's own capabilities, or ro.boot.hypervisor.vm.supported);</li>
 * <li>this app holds both of AVF's permissions — development permissions, granted once through Wireless
 * debugging (Pairing), kept across reboots and updates;</li>
 * <li>the office's machine has booted under AVF here, or has not failed to: the result of the last boot,
 * kept, and this machine's AVF kernel present.</li>
 * </ol>
 */
final class Virt {

    static final String MANAGE = "android.permission.MANAGE_VIRTUAL_MACHINE";
    static final String CUSTOM = "android.permission.USE_CUSTOM_VIRTUAL_MACHINE";
    private static final String FEATURE = "android.software.virtualization_framework";
    private static final int NON_PROTECTED = 2;   // VirtualMachineManager.CAPABILITY_NON_PROTECTED_VM

    /** One check: green or not, and the line the status screen says. */
    static final class Check {
        final boolean ok;
        final String said;

        Check(boolean ok, String said) {
            this.ok = ok;
            this.said = said;
        }
    }

    /** The four checks, and what they decide. */
    static final class Choice {
        final Check avf, unprotected, granted, boots;
        final boolean unknown;    // the phone did not say whether it runs an unprotected machine (until the grant)
        final boolean hardware;   // AVF
        final String why;         // the first check that is not green, or why AVF

        Choice(Check avf, Check unprotected, boolean unknown, Check granted, Check boots) {
            this.avf = avf;
            this.unprotected = unprotected;
            this.unknown = unknown;
            this.granted = granted;
            this.boots = boots;
            Check first = !avf.ok ? avf : !unprotected.ok ? unprotected : !granted.ok ? granted : !boots.ok ? boots : null;
            hardware = first == null;
            why = first == null ? "הטלפון מריץ את מכונת הלשכה בווירטואליזציה של החומרה (AVF)" : first.said;
        }

        /**
         * The phone could run AVF once this app holds the permissions — or may, where it says nothing of an
         * unprotected machine before them: the pairing is worth offering.
         */
        boolean pairable() {
            return avf.ok && (unprotected.ok || unknown) && !granted.ok;
        }
    }

    private Virt() {
    }

    /** files/run/avf-boot: "ok <seconds>" once the machine booted under AVF, "failed <why>" after it did not. */
    static File bootResult(Context c) {
        return new File(new File(c.getFilesDir(), "run"), "avf-boot");
    }

    /** The machine's AVF kernel and initrd (Guest.fetch keeps them beside its disk). */
    static File kernel(Context c) {
        return new File(new File(c.getFilesDir(), "boot"), "kernel");
    }

    static File initrd(Context c) {
        return new File(new File(c.getFilesDir(), "boot"), "initrd");
    }

    static Choice choose(Context c) {
        Check avf;
        boolean feature = c.getPackageManager().hasSystemFeature(FEATURE);
        if (Build.VERSION.SDK_INT < 35) {
            avf = new Check(false, "Android " + Build.VERSION.RELEASE + ": מכונה וירטואלית לאפליקציה דורשת Android 15 ומעלה");
        } else if (!feature) {
            avf = new Check(false, "הטלפון הזה (" + Build.MANUFACTURER + " " + Build.MODEL + ") לא כולל את מסגרת הווירטואליזציה של Android (AVF)");
        } else {
            avf = new Check(true, "Android " + Build.VERSION.RELEASE + " עם AVF");
        }

        Check unprotected;
        boolean unknown = false;
        if (!avf.ok) {
            unprotected = new Check(false, "לא נבדק: אין AVF");
        } else {
            int caps = capabilities(c);
            String prop = property("ro.boot.hypervisor.vm.supported");
            if (caps >= 0 ? (caps & NON_PROTECTED) != 0 : "1".equals(prop) || "true".equals(prop)) {
                unprotected = new Check(true, "הטלפון מריץ מכונה וירטואלית רגילה (לא מוגנת)");
            } else if (caps >= 0 || !prop.isEmpty()) {
                unprotected = new Check(false, "הטלפון מריץ רק מכונות מוגנות וחתומות (כך בטלפונים עם Snapdragon) — לא מכונה של לשכה");
            } else {
                unknown = true;
                unprotected = new Check(false, "הטלפון לא אומר אם הוא מריץ מכונה רגילה — ייבדק אחרי מתן ההרשאות");
            }
        }

        boolean manage = c.checkSelfPermission(MANAGE) == PackageManager.PERMISSION_GRANTED;
        boolean custom = c.checkSelfPermission(CUSTOM) == PackageManager.PERMISSION_GRANTED;
        Check granted = manage && custom ? new Check(true, "לאפליקציה יש את שתי הרשאות המכונה")
                : new Check(false, "לאפליקציה חסרות הרשאות המכונה — ניתנות פעם אחת, דרך «ניפוי באגים אלחוטי»");

        Check boots;
        String last = read(bootResult(c));
        String[] failed = last.startsWith("failed ") ? last.substring(7).split(" ", 2) : null;
        if (!kernel(c).isFile() || !initrd(c).isFile()) {
            boots = new Check(false, "למכונה שבטלפון עוד אין ליבה ל-AVF — היא תגיע עם המכונה הבאה");
        } else if (failed != null && failed.length == 2 && failed[0].equals(String.valueOf(BuildConfig.VERSION_CODE))) {
            // a failure holds for the APK that met it: a newer one tries AVF again (and «לנסות שוב» does, now)
            boots = new Check(false, "העלייה האחרונה ב-AVF נכשלה: " + failed[1]);
        } else if (failed != null) {
            boots = new Check(true, "העלייה ב-AVF נכשלה בגרסה קודמת — הגרסה הזו מנסה שוב");
        } else if (last.startsWith("retry")) {
            boots = new Check(true, "הטלפון אתחל את המכונה בעלייה — העלייה הבאה מבקשת ליבת מעבד אחת");
        } else if (last.startsWith("ok")) {
            boots = new Check(true, "המכונה עלתה ב-AVF בטלפון הזה (" + last.substring(2).trim() + ")");
        } else {
            boots = new Check(true, "המכונה עוד לא עלתה ב-AVF בטלפון הזה — העלייה הבאה תנסה");
        }
        return new Choice(avf, unprotected, unknown, granted, boots);
    }

    /** The last AVF boot failed for this very APK: the status screen offers to try once more. */
    static boolean failedHere(Context c) {
        String last = read(bootResult(c));
        return last.startsWith("failed " + BuildConfig.VERSION_CODE + " ");
    }

    /**
     * VirtualMachineManager.getCapabilities() (a system API — reflection may call it, and the hidden-API
     * exemption is asked first all the same), or -1 when it does not answer.
     */
    private static int capabilities(Context c) {
        Avf.bypass();
        try {
            Class<?> vmm = Class.forName("android.system.virtualmachine.VirtualMachineManager");
            Object m = c.getSystemService(vmm);
            if (m == null) return -1;
            Method caps = vmm.getMethod("getCapabilities");
            return (Integer) caps.invoke(m);
        } catch (Throwable e) {   // absent, refused (a permission), or any other way it does not answer
            return -1;
        }
    }

    /** A system property as getprop prints it, "" when it is not set or not readable by this app. */
    static String property(String name) {
        Process p = null;
        try {
            p = new ProcessBuilder("/system/bin/getprop", name).redirectErrorStream(true).start();
            String line;
            try (BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
                line = r.readLine();
            }
            if (!p.waitFor(3, TimeUnit.SECONDS)) p.destroyForcibly();
            return line == null ? "" : line.trim();
        } catch (Exception e) {
            if (p != null) p.destroyForcibly();
            return "";
        }
    }

    private static String read(File f) {
        try {
            return f.isFile() ? new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8).trim() : "";
        } catch (Exception e) {
            return "";
        }
    }
}
