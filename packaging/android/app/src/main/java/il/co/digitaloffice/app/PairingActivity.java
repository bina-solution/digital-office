package il.co.digitaloffice.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.util.TypedValue;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * «האצת חומרה — פעם אחת» (DGO-1328): the steps that give this app AVF's two permissions through the phone's
 * own Wireless debugging (Pairing), each with its state, live: Developer options on, Wi-Fi, Wireless
 * debugging's «pair with a code» open — the code then typed into this app's notification, or here in split
 * screen — then the grant, checked. Nothing here is needed again: the phone keeps the grant.
 */
public class PairingActivity extends Activity {

    private final Handler ui = new Handler(Looper.getMainLooper());
    private TextView steps, result;
    private EditText code;
    private boolean live;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        int pad = dp(16);
        root.setPadding(pad, pad, pad, pad);
        TextView title = text(22, true);
        title.setText("האצת חומרה — פעם אחת");
        root.addView(title);
        TextView why = text(14, false);
        why.setText("הטלפון יכול להריץ את המכונה של הלשכה בווירטואליזציה של החומרה (AVF) — מהר פי כמה מההדמיה. "
                + "Android נותן את זה לאפליקציה רק עם שתי הרשאות, שהיא נותנת לעצמה דרך «ניפוי באגים אלחוטי» של הטלפון — בלי מחשב. "
                + "הטלפון שומר אותן: זה נעשה פעם אחת.");
        root.addView(why);
        steps = text(15, false);
        steps.setPadding(0, dp(12), 0, dp(12));
        root.addView(steps);
        root.addView(button("1 · פתיחת אפשרויות המפתח ← «ניפוי באגים אלחוטי»", v -> openDeveloper()));
        TextView how = text(13, false);
        how.setText("שם: מפעילים «ניפוי באגים אלחוטי», נכנסים אליו, ובוחרים «התאמת מכשיר באמצעות קוד התאמה». "
                + "החלון עם הקוד נשאר פתוח — ובהתראה של הלשכה מקלידים את 6 הספרות.");
        root.addView(how);
        root.addView(button("2 · הצגת ההתראה להקלדת הקוד", v -> {
            if (askNotifications()) Pairing.ask(this);   // else once the owner allows notifications
        }));
        TextView or = text(13, false);
        or.setText("או, במסך מפוצל, כאן:");
        root.addView(or);
        code = new EditText(this);
        code.setInputType(InputType.TYPE_CLASS_NUMBER);
        code.setHint("קוד ההתאמה");
        root.addView(code);
        root.addView(button("התאמה", v -> {
            String c = code.getText().toString().replaceAll("[^0-9]", "");
            new Thread(() -> Pairing.run(getApplicationContext(), c), "pairing").start();
        }));
        result = text(15, true);
        result.setPadding(0, dp(12), 0, 0);
        root.addView(result);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(getColor(android.R.color.white));
        scroll.addView(root);
        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(getColor(R.color.tile));
        frame.addView(scroll);
        Edges.pad(frame);
        setContentView(frame);
    }

    @Override
    protected void onResume() {
        super.onResume();
        live = true;
        Pairing.discover(this);
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
        // the search goes on while Settings is in front (the code comes through the notification); it ends
        // with this screen
        Pairing.stop(this);
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!live) return;
            boolean dev = Settings.Global.getInt(getContentResolver(), Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) == 1;
            ConnectivityManager cm = getSystemService(ConnectivityManager.class);
            NetworkCapabilities caps = cm == null || cm.getActiveNetwork() == null ? null : cm.getNetworkCapabilities(cm.getActiveNetwork());
            boolean wifi = caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI);
            boolean granted = checkSelfPermission(Virt.MANAGE) == PackageManager.PERMISSION_GRANTED
                    && checkSelfPermission(Virt.CUSTOM) == PackageManager.PERMISSION_GRANTED;
            String s = (dev ? "✓" : "✗") + " אפשרויות המפתח פעילות" + (dev ? "" : " (הגדרות ← מידע על הטלפון ← 7 הקשות על «מספר גרסה»)") + "\n"
                    + (wifi ? "✓" : "✗") + " הטלפון מחובר ל-Wi-Fi" + (wifi ? "" : " — ניפוי באגים אלחוטי עובד רק ב-Wi-Fi") + "\n"
                    + (!Pairing.pairAt.isEmpty() ? "✓ חלון «התאמה עם קוד» פתוח (" + Pairing.pairAt + ")" : "… מחכה לחלון «התאמה עם קוד»") + "\n"
                    + (!Pairing.connectAt.isEmpty() ? "✓ ניפוי באגים אלחוטי פעיל (" + Pairing.connectAt + ")" : "… מחכה ש«ניפוי באגים אלחוטי» יופעל") + "\n"
                    + (granted ? "✓ לאפליקציה יש את שתי הרשאות המכונה" : "✗ ההרשאות עוד לא ניתנו");
            steps.setText(s);
            String st = Pairing.state;
            result.setText(!st.isEmpty() ? st : Pairing.said);
            ui.postDelayed(this, 1000);
        }
    };

    private void openDeveloper() {
        try {
            startActivity(new Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS));
        } catch (Exception e) {
            startActivity(new Intent(Settings.ACTION_DEVICE_INFO_SETTINGS));
        }
    }

    /** Notifications may be posted now; or the owner is asked, and the notification follows his answer. */
    private boolean askNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 5);
            return false;
        }
        return true;
    }

    @Override
    public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == 5 && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) Pairing.ask(this);
        else if (request == 5) Pairing.said = "✗ בלי התראות אין איפה להקליד את הקוד — אפשר להקליד אותו כאן, במסך מפוצל";
    }

    private TextView text(int sp, boolean bold) {
        TextView t = new TextView(this);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setTextDirection(View.TEXT_DIRECTION_RTL);
        return t;
    }

    private Button button(String s, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setOnClickListener(l);
        return b;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
