package il.co.digitaloffice.app;

/**
 * CoreFailure.say (DGO-1817), with plain Java and no Android classes:
 *   javac -d out src/main/java/il/co/digitaloffice/app/CoreFailure.java src/test/java/il/co/digitaloffice/app/CoreFailureTest.java
 *   java -cp out il.co.digitaloffice.app.CoreFailureTest
 */
public final class CoreFailureTest {
    private static int failed;

    private static void expect(String name, String got, String... parts) {
        for (String p : parts) {
            if (!got.contains(p)) {
                failed++;
                System.out.println("FAIL " + name + ": «" + got + "» lacks «" + p + "»");
                return;
            }
        }
        System.out.println("ok   " + name);
    }

    public static void main(String[] args) {
        String arm64Lib = "/data/app/~~x==/il.co.digitaloffice.app-y==/lib/arm64";
        String x86Lib = "/data/app/~~x==/il.co.digitaloffice.app-y==/lib/x86_64";
        String raw = "forward-auth -first-run said null (exit 139)";
        // the emulator measured 2026-11-11: an arm64-only APK on an x86_64 device — the processor is the reason
        expect("arm64 APK on x86_64", CoreFailure.say(raw, "x86_64", arm64Lib), "arm64", "x86_64", "בתרגום");
        // the right libraries, and a program that crashed: the signal, named
        expect("SIGSEGV", CoreFailure.say(raw, "x86_64", x86Lib), "קרסה (SIGSEGV)", "«הלוג המלא»");
        expect("SIGSEGV on a phone", CoreFailure.say(raw, "arm64-v8a", arm64Lib), "קרסה (SIGSEGV)");
        expect("SIGKILL", CoreFailure.say("x said null (exit 137)", "arm64-v8a", arm64Lib), "SIGKILL");
        expect("SIGABRT", CoreFailure.say("x said null (exit 134)", "arm64-v8a", arm64Lib), "SIGABRT");
        expect("exit 255 is a code, not a signal", CoreFailure.say("x said null (exit 255)", "arm64-v8a", arm64Lib), "עם קוד 255");
        // translated, but the failure is not a program's death: never blamed on the processor
        expect("translated, a full disk", CoreFailure.say("could not place files/office", "x86_64", arm64Lib), "הבסיס לא עלה");
        expect("translated, an exit code", CoreFailure.say("x said nope (exit 2)", "x86_64", arm64Lib), "עם קוד 2");
        expect("an oversized number", CoreFailure.say("x (exit 99999999999999)", "arm64-v8a", arm64Lib), "הבסיס לא עלה");
        expect("another signal", CoreFailure.say("x said null (exit 143)", "arm64-v8a", arm64Lib), "באות 15");
        expect("an exit code", CoreFailure.say("x said nope (exit 2)", "arm64-v8a", arm64Lib), "עם קוד 2");
        expect("no code", CoreFailure.say("x said null and did not end", "arm64-v8a", arm64Lib), "הבסיס לא עלה");
        expect("no message", CoreFailure.say(null, "arm64-v8a", arm64Lib), "הבסיס לא עלה");
        // nothing known about the libraries or the device: never a processor guess
        expect("unknown lib dir", CoreFailure.say(raw, "x86_64", null), "SIGSEGV");
        expect("unknown device", CoreFailure.say(raw, "", arm64Lib), "SIGSEGV");
        expect("armeabi-v7a maps to arm", CoreFailure.say(raw, "armeabi-v7a", "/data/app/a/lib/arm"), "SIGSEGV");
        if (CoreFailure.say(raw, "x86_64", arm64Lib).contains("Exception")) {
            failed++;
            System.out.println("FAIL the sentence quotes the exception");
        }
        System.out.println(failed == 0 ? "PASS" : "FAILED " + failed);
        System.exit(failed == 0 ? 0 : 1);
    }
}
