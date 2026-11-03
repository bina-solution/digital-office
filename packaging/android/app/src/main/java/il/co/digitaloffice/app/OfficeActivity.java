package il.co.digitaloffice.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.ConsoleMessage;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

/**
 * One office, full screen: its console, signed in through the office's own sign-in (its cookies are
 * kept), every app it serves inside it — as the console is in a browser. Links that are not the web
 * (mail, phone, a store) go to the phone; uploads use the phone's picker; downloads go to Downloads
 * with the office's session.
 */
public class OfficeActivity extends Activity {

    static final String URL = "url";
    static final String NAME = "name";
    private static final int PICK = 1;

    private WebView web;
    private ValueCallback<Uri[]> picked;

    @SuppressLint("SetJavaScriptEnabled")   // the console is a JavaScript app
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);   // a meeting's audio and video
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                String scheme = u.getScheme();
                // Google refuses its sign-in inside a WebView (disallowed_useragent): the phone's browser
                // takes it. A connection made there completes there, not in this session — the
                // console's own sign-in does not go through Google.
                if ("accounts.google.com".equals(u.getHost()) || !("http".equals(scheme) || "https".equals(scheme))) {
                    open(u);
                    return true;
                }
                return false;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            // a page this WebView cannot even parse stays white: say why, once, whatever its version. Only a
            // script that does not parse, of the office's own host: a JSON that is a sign-in page, a bad
            // selector or an app's logged error are SyntaxErrors too, and say nothing about the WebView
            @Override
            public boolean onConsoleMessage(ConsoleMessage m) {
                String said = m.message() == null ? "" : m.message();
                String page = web.getUrl() == null ? null : Uri.parse(web.getUrl()).getHost();
                String from = m.sourceId() == null ? null : Uri.parse(m.sourceId()).getHost();
                if (m.messageLevel() == ConsoleMessage.MessageLevel.ERROR && said.startsWith("Uncaught SyntaxError:")
                        && !said.contains("JSON") && !said.contains("Failed to execute") && !said.contains("Unexpected token '<'")
                        && page != null && page.equals(from)) {
                    oldWebView(false);
                }
                return false;
            }

            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (picked != null) picked.onReceiveValue(null);
                picked = callback;
                // any file: an accept list of extensions (".pdf") is no MIME type, and would match no picker
                Intent pick = new Intent(Intent.ACTION_GET_CONTENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                try {
                    startActivityForResult(pick, PICK);
                } catch (ActivityNotFoundException e) {
                    picked = null;
                    return false;
                }
                return true;
            }
        });
        web.setDownloadListener((url, agent, disposition, mime, length) -> download(url, agent, disposition, mime));

        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(getColor(R.color.tile));
        frame.addView(web);
        Edges.pad(frame);
        setContentView(frame);
        if (saved == null || web.restoreState(saved) == null) web.loadUrl(getIntent().getStringExtra(URL));
        int major = webViewMajor(s);
        if (major > 0 && major < MIN_WEBVIEW) oldWebView(true);
    }

    /**
     * Below this major the office's sign-in does not load at all — measured on Android 11's own WebView,
     * 83.0.4103.106: "Uncaught SyntaxError: Unexpected token '='" (the logical assignments, ??= and ||=,
     * are Chrome 85's), a white page. A phone updates its WebView from the store; this one says to.
     */
    private static final int MIN_WEBVIEW = 85;
    private boolean warned;

    /**
     * The Chromium major this phone's WebView renders with, read from its own user agent ("Chrome/83.…"):
     * a maker's WebView package may number its builds its own way. 0 when it does not say.
     */
    private static int webViewMajor(WebSettings s) {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("Chrome/(\\d+)").matcher(String.valueOf(s.getUserAgentString()));
        try {
            return m.find() ? Integer.parseInt(m.group(1)) : 0;
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    /** Says the WebView is too old to show the office, with its version and a way to update it — once. */
    private void oldWebView(boolean before) {
        if (warned || isFinishing() || isDestroyed()) return;
        warned = true;
        android.content.pm.PackageInfo p = WebView.getCurrentWebViewPackage();
        String pkg = p == null ? "com.google.android.webview" : p.packageName;
        String version = p == null || p.versionName == null ? "?" : p.versionName;
        new AlertDialog.Builder(this)
                .setTitle(R.string.webview_old_title)
                .setMessage(getString(before ? R.string.webview_old : R.string.webview_failed, version))
                .setPositiveButton(R.string.webview_update, (d, w) -> {
                    if (!open(Uri.parse("market://details?id=" + pkg))
                            && !open(Uri.parse("https://play.google.com/store/apps/details?id=" + pkg))) {
                        Toast.makeText(this, R.string.webview_no_store, Toast.LENGTH_LONG).show();
                    }
                })
                .setNegativeButton(R.string.webview_continue, null)
                .show();
    }

    /** A file the office serves, into Downloads, asked for with the office's cookies (it sits behind the sign-in). */
    private void download(String url, String agent, String disposition, String mime) {
        Uri u = Uri.parse(url);
        String host = u.getHost() == null ? "" : u.getHost();
        boolean fetchable = "http".equals(u.getScheme()) || "https".equals(u.getScheme());
        // The system's download service resolves names with the platform's resolver, which knows `localhost`
        // but not `console.localhost` (the WebView resolves *.localhost itself): this phone's own office is
        // left to the browser, as are a file the page made itself (blob:, data: — nothing to fetch again)
        // and Android 8–9, where Downloads needs a storage permission this app does not ask for.
        if (!fetchable || host.endsWith(".localhost") || Build.VERSION.SDK_INT < 29) {
            if (!open(u)) Toast.makeText(this, R.string.no_download, Toast.LENGTH_LONG).show();
            return;
        }
        String name = URLUtil.guessFileName(url, disposition, mime);
        DownloadManager.Request r = new DownloadManager.Request(u)
                .setMimeType(mime)
                .setTitle(name)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
        String cookies = CookieManager.getInstance().getCookie(url);
        if (cookies != null) r.addRequestHeader("Cookie", cookies);
        r.addRequestHeader("User-Agent", agent);
        DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
        try {
            if (dm == null) throw new IllegalStateException("no download service");
            dm.enqueue(r);
            Toast.makeText(this, name, Toast.LENGTH_SHORT).show();
        } catch (RuntimeException e) {   // the system's Download Manager switched off: enqueue throws
            if (!open(u)) Toast.makeText(this, R.string.no_download, Toast.LENGTH_LONG).show();
        }
    }

    private boolean open(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
            return true;
        } catch (ActivityNotFoundException ignored) {
            return false;   // nothing on the phone opens it: the page stays where it is
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        if (request == PICK && picked != null) {
            Uri[] files = null;
            if (result == RESULT_OK && data != null) {
                ClipData many = data.getClipData();
                if (many != null) {
                    files = new Uri[many.getItemCount()];
                    for (int i = 0; i < files.length; i++) files[i] = many.getItemAt(i).getUri();
                } else if (data.getData() != null) {
                    files = new Uri[]{data.getData()};
                }
            }
            picked.onReceiveValue(files);
            picked = null;
            return;
        }
        super.onActivityResult(request, result, data);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    @SuppressWarnings("deprecation")   // the framework Activity's own back, kept for Android 8–12
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onResume() {
        super.onResume();
        NativeService.inFront(this);   // what kept the machine from starting, asked again once
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();   // a sign-in survives the app being closed
    }
}
