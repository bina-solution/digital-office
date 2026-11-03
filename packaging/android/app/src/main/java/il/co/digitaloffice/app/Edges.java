package il.co.digitaloffice.app;

import android.graphics.Insets;
import android.os.Build;
import android.view.View;
import android.view.WindowInsets;

/**
 * Android 15 draws an app that targets it edge to edge: under the status bar, the gesture or button
 * bar and the keyboard. Each screen's frame is padded by them, in the tile's colour, so the console's
 * top bar, its bottom row and a chat's composer stay where a finger and the eye can reach them.
 * Before 15 the system keeps its bars to itself (and resizes for the keyboard), so nothing is padded.
 */
final class Edges {

    private Edges() {
    }

    static void pad(View frame) {
        if (Build.VERSION.SDK_INT < 35) return;
        frame.setOnApplyWindowInsetsListener((v, in) -> {
            Insets i = in.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout()
                    | WindowInsets.Type.ime());
            v.setPadding(i.left, i.top, i.right, i.bottom);
            // used here, so the WebView inside does not pad the page by them again (env(safe-area-inset-*))
            return WindowInsets.CONSUMED;
        });
    }
}
