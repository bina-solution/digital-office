package il.co.digitaloffice.app;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Why the office's core did not start, in the owner's words (DGO-1817). The status screen showed him
 * «java.io.IOException: forward-auth -first-run said null (exit 139)»: the phone APK (arm64 only) opened on
 * the x86_64 emulator, its Go programs run there under Android's arm64 translation and die by SIGSEGV. The
 * raw line stays in the log; this is the sentence his screen says. No Android class here, so it is tested
 * with plain Java (src/test, run by android-app.yml).
 */
final class CoreFailure {
    private CoreFailure() {
    }

    /** a program's end as NativeService words it: «(exit N)»; N is 0–255 */
    private static final Pattern EXIT = Pattern.compile("\\(exit (\\d{1,3})\\)");

    /** The library directory's last segment Android installs each ABI's libraries under. */
    static String libDirOf(String abi) {
        switch (abi == null ? "" : abi) {
            case "arm64-v8a": return "arm64";
            case "armeabi-v7a": case "armeabi": return "arm";
            default: return abi == null ? "" : abi;   // x86_64 and x86 keep their names
        }
    }

    /**
     * The sentence for a core that did not start.
     *
     * @param error     the exception's text (its message, as the log has it)
     * @param deviceAbi the device's first ABI (Build.SUPPORTED_ABIS[0])
     * @param libDir    the app's nativeLibraryDir: its last segment is the ABI its libraries were installed for
     */
    static String say(String error, String deviceAbi, String libDir) {
        Matcher m = EXIT.matcher(error == null ? "" : error);
        if (!m.find()) return "הבסיס לא עלה. הפרטים ב«הלוג המלא».";
        int code = Integer.parseInt(m.group(1));
        if (code <= 128 || code > 192) {
            return "תוכנה של הבסיס נעצרה עם קוד " + code + " כשעלתה. הפרטים ב«הלוג המלא».";
        }
        // a program killed by a signal: on a device that runs this APK's libraries in translation, that is the
        // reason (the arm64 APK on the x86_64 emulator, 2026-11-11); anywhere else, the signal is
        String installed = libDir == null ? "" : libDir.substring(libDir.lastIndexOf('/') + 1);
        String native_ = libDirOf(deviceAbi);
        if (!installed.isEmpty() && !native_.isEmpty() && !installed.equals(native_)) {
            return "הגרסה הזו של האפליקציה נבנתה למעבד " + installed + ", והמכשיר הזה הוא " + deviceAbi
                    + ": הליבה רצה בו בתרגום ונופלת. צריך את הגרסה שנבנתה ל-" + deviceAbi + ".";
        }
        int signal = code - 128;
        String what = signal == 11 ? "קרסה (SIGSEGV)" : signal == 9 ? "נהרגה (SIGKILL)" : signal == 6 ? "נעצרה (SIGABRT)"
                : "נעצרה באות " + signal;
        return "תוכנה של הבסיס " + what + " כשעלתה. הפרטים ב«הלוג המלא».";
    }
}
