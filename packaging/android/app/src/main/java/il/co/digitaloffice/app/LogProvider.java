package il.co.digitaloffice.app;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * The status screen's «שיתוף לוג» (DGO-1328): the log it wrote to the app's cache, read by the app the owner
 * shares it with (Telegram, mail) through a one-time grant on its content address — and nothing else: only
 * a file the screen named dgo-log-<digits>.txt in cache/share, read-only. Not exported.
 */
public class LogProvider extends ContentProvider {

    static final String AUTHORITY = "il.co.digitaloffice.app.logs";

    static Uri uri(File f) {
        return Uri.parse("content://" + AUTHORITY + "/" + f.getName());
    }

    static File dir(android.content.Context c) {
        return new File(c.getCacheDir(), "share");
    }

    private File file(Uri uri) throws FileNotFoundException {
        String name = uri.getLastPathSegment();
        if (name == null || !name.matches("dgo-log-[0-9]+\\.txt")) throw new FileNotFoundException(String.valueOf(uri));
        File f = new File(dir(getContext()), name);
        if (!f.isFile()) throw new FileNotFoundException(String.valueOf(uri));
        return f;
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("read-only");
        return ParcelFileDescriptor.open(file(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public String getType(Uri uri) {
        return "text/plain";
    }

    /** Its name and size, which the app it is shared with shows (and some ask before they read). */
    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder) {
        File f;
        try {
            f = file(uri);
        } catch (FileNotFoundException e) {
            return null;
        }
        MatrixCursor c = new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE});
        c.addRow(new Object[]{f.getName(), f.length()});
        return c;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException();
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException();
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        throw new UnsupportedOperationException();
    }
}
