package il.co.digitaloffice.app;

import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.io.SequenceInputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.BooleanSupplier;
import java.util.function.IntConsumer;
import java.util.function.LongConsumer;

/**
 * The office's machine into the app's own storage, once — out of the APK (assets/guest's .img.xz: the one
 * unpack the machine's own screen, {@link MainActivity}, and the native core, {@link NativeService}, both
 * run), or fetched in pieces where the APK names a published one (DGO-1089, the core's alone) — one at a
 * time, and never over a machine that is there: it holds the office's data. The APK's zstd does the reading
 * (Java's framework has no .xz reader); this feeds it and counts. Sparse: the disk is 24 GB raw and mostly
 * zeros, and zstd skips a zero block, so it takes what the machine holds (~7 GB). Through a .part and a
 * rename: a cut unpack is never the machine.
 */
final class Guest {

    static final String ASSET = "guest/dgo-guest-arm64.img.xz";
    /** What unpacks it: zstd, built with QEMU (it reads .xz too), from the native-library directory. */
    static final String UNPACKER = "libzstd-cli.so";
    /** Free room asked before the unpack: the machine holds ~7 GB, every image the office runs in it. */
    static final long ROOM = 10L << 30;
    /** What a machine to fetch is said to be before its list is read (the list itself is at most 1 MiB). */
    private static final long ABOUT = 2L << 30;

    private static final AtomicBoolean BUSY = new AtomicBoolean();

    /** The APK carries no machine (or carries it compressed, which is no machine this can read). */
    static final class Absent extends Exception {
    }

    /** Not room enough on the phone: what it has, and what the machine asks, in bytes. */
    static final class NoRoom extends Exception {
        final long free, need;

        NoRoom(long free) {
            this(free, ROOM);
        }

        NoRoom(long free, long need) {
            this.free = free;
            this.need = need;
        }
    }

    /** Another unpack is running: its caller says its progress. */
    static final class Busy extends Exception {
    }

    /** The phone's network is metered (a data plan): what is left to fetch, in bytes — fetched on Wi-Fi. */
    static final class Metered extends Exception {
        final long left;

        Metered(long left) {
            this.left = left;
        }
    }

    /** Whoever asked for this unpack wants it no more (the core that asked stopped), and it stopped. */
    static final class Cancelled extends Exception {
    }

    private Guest() {
    }

    static boolean inApk(Context c) {
        try (AssetFileDescriptor afd = c.getAssets().openFd(ASSET)) {
            return afd.getLength() > 0;
        } catch (IOException e) {
            return false;
        }
    }

    /** This APK names a published machine to fetch (BuildConfig, checked in build.gradle). */
    static boolean fetchable() {
        return !BuildConfig.MACHINE_MANIFEST.isEmpty() && BuildConfig.MACHINE_URL.startsWith("https://");
    }

    static boolean busy() {
        return BUSY.get();
    }

    /**
     * The machine's disk is the native core's (its unpack placed this beside it), not the machine's own
     * office's (DGO-1084): the app opens the core, which starts the machine behind it.
     */
    static File coreMarker(Context c) {
        return new File(c.getFilesDir(), "guest.core");
    }

    /**
     * The APK's machine unpacked, for the core's machine (core) or the machine's own office's; wanted is
     * asked at every block it feeds — once it says no, zstd is ended, the .part deleted, and Cancelled thrown
     * (no core is left: nobody waits for the disk). A disk unpacked whole is placed whatever wanted says by then.
     */
    static void unpack(Context c, boolean core, BooleanSupplier wanted, IntConsumer percent) throws Exception {
        if (!BUSY.compareAndSet(false, true)) throw new Busy();
        try {
            new File(EngineService.guest(c).getPath() + ".part").delete();   // a cut one's would count against the room
            AssetFileDescriptor opened;
            try {
                opened = c.getAssets().openFd(ASSET);
            } catch (IOException e) {   // absent, or packed compressed: either way not a machine this APK has
                throw new Absent();
            }
            try (AssetFileDescriptor afd = opened) {
                long free = c.getFilesDir().getUsableSpace();
                if (free < ROOM) throw new NoRoom(free);
                // the asset open before zstd starts: zstd waits on its input until that input is closed
                try (InputStream in = afd.createInputStream()) {
                    unzstd(c, core, wanted, percent, in, Math.max(1, afd.getLength()));
                }
            }
        } finally {
            BUSY.set(false);
        }
    }

    /**
     * The machine fetched in pieces, for the core (DGO-1089): the list named by the SHA-256 this APK carries
     * (kept beside the pieces once it checks out), then every piece it names by its own SHA-256 — each kept in
     * files/machine-pieces once it checks out, so a cut fetch (or the next one) fetches only what it lacks,
     * from where it was cut — then unpacked from them in the list's order, and the pieces deleted once the
     * machine is whole. Its percent: 0–49 fetching, 50–99 unpacking. Nothing it fetches is trusted that does
     * not hash back to this APK, and nothing is fetched but on the unmetered network it began on (network).
     */
    static void fetch(Context c, BooleanSupplier wanted, IntConsumer percent) throws Exception {
        if (!fetchable()) throw new Absent();
        if (!BUSY.compareAndSet(false, true)) throw new Busy();
        try {
            new File(EngineService.guest(c).getPath() + ".part").delete();
            File dir = new File(c.getFilesDir(), "machine-pieces");
            if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("could not make " + dir);
            File kept = new File(dir, "list-" + BuildConfig.MACHINE_MANIFEST);
            Manifest cached = cached(kept);
            Network net = null;
            if (cached == null) {
                long first = c.getFilesDir().getUsableSpace();   // no room is said before "Wi-Fi only", the first time too
                if (first < ABOUT + ROOM) throw new NoRoom(first, ABOUT + ROOM);
                net = network(c, ABOUT);
                cached = list(net, kept, wanted);
            }
            final Manifest list = cached;   // once: the progress below reads it
            sweep(dir, list, kept);
            // the network first where a piece is missing by its length alone: on a data plan the fetch is refused
            // before it reads anything back
            long missing = 0;
            for (Piece p : list.pieces) if (p.file(dir).length() != p.size) missing += p.size;
            long room = c.getFilesDir().getUsableSpace();   // no room is said before "Wi-Fi only": it holds there too
            if (room < missing + ROOM) throw new NoRoom(room, missing + ROOM);
            if (missing > 0 && net == null) net = network(c, missing);
            // a kept piece is hashed again: a byte gone bad on the phone's storage would fail every unpack after
            long need = 0, done = 0;
            for (Piece p : list.pieces) {
                if (!wanted.getAsBoolean()) throw new Cancelled();
                File f = p.file(dir);
                if (f.length() == p.size && p.sha.equals(sha(f))) {
                    done += p.size;
                } else {
                    f.delete();
                    need += p.size;
                }
            }
            long free = c.getFilesDir().getUsableSpace();
            if (free < need + ROOM) throw new NoRoom(free, need + ROOM);
            if (need > 0 && net == null) net = network(c, need);
            for (Piece p : list.pieces) {
                if (p.file(dir).isFile()) continue;
                long from = done;
                piece(net, p, p.file(dir), wanted, got -> percent.accept((int) Math.min(49, (from + got) * 50 / list.total)));
                done += p.size;
            }
            try (InputStream in = new SequenceInputStream(new Pieces(list.pieces, dir))) {
                unzstd(c, true, wanted, q -> percent.accept(50 + q / 2), in, list.total);
            }
            File[] all = dir.listFiles();   // the machine is whole: its pieces and its list are not needed
            if (all != null) for (File f : all) f.delete();
            dir.delete();
        } finally {
            BUSY.set(false);
        }
    }

    // ── the network ──────────────────────────────────────────────────────────────────────────────────

    /**
     * The network the fetch is bound to: the phone's network now, on the internet and not metered — never
     * the owner's data plan. Every connection of the fetch is opened on it, so a Wi-Fi gone mid-way fails the
     * fetch (the next return to the app asks again) instead of carrying it on over the data plan.
     */
    private static Network network(Context c, long left) throws Exception {
        ConnectivityManager cm = c.getSystemService(ConnectivityManager.class);
        Network net = cm == null ? null : cm.getActiveNetwork();
        NetworkCapabilities caps = net == null ? null : cm.getNetworkCapabilities(net);
        if (caps == null || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) {
            throw new IOException("the phone is on no network now");
        }
        if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) throw new Metered(left);
        return net;
    }

    /** A plain GET on net, its redirects followed only to https (a release asset's own host): never cleartext. */
    private static HttpURLConnection open(Network net, String url) throws IOException {
        URL u = new URL(url);
        if (!"https".equals(u.getProtocol())) throw new IOException("not https: " + url);
        HttpURLConnection h = (HttpURLConnection) net.openConnection(u);
        h.setConnectTimeout(20_000);
        h.setReadTimeout(60_000);
        h.setInstanceFollowRedirects(true);   // https → http is never followed by HttpURLConnection
        h.setRequestProperty("Accept-Encoding", "identity");   // the bytes as named, never a re-encoding of them
        return h;
    }

    // ── the list and its pieces ──────────────────────────────────────────────────────────────────────

    /** One piece of the machine's .xz: its SHA-256, which is its name, and its size. */
    private static final class Piece {
        final String sha;
        final long size;

        Piece(String sha, long size) {
            this.sha = sha;
            this.size = size;
        }

        /** Where it is kept: there only once it checked out (a .part, verified, renamed). */
        File file(File dir) {
            return new File(dir, sha);
        }
    }

    /** The machine's list: its pieces in order, and their total. */
    private static final class Manifest {
        final List<Piece> pieces;
        final long total;

        Manifest(List<Piece> pieces, long total) {
            this.pieces = pieces;
            this.total = total;
        }
    }

    /** The list kept from an earlier fetch, if it is there and still hashes to the one this APK names. */
    private static Manifest cached(File kept) {
        try {
            byte[] raw = Files.readAllBytes(kept.toPath());
            if (!hex(MessageDigest.getInstance("SHA-256").digest(raw)).equals(BuildConfig.MACHINE_MANIFEST)) return null;
            return parse(raw);
        } catch (Exception e) {
            return null;
        }
    }

    /** The list fetched on net, held to the SHA-256 the APK carries, and kept; tried four times, a pause between. */
    private static Manifest list(Network net, File kept, BooleanSupplier wanted) throws Exception {
        Exception last = null;
        for (int attempt = 0; attempt < 4; attempt++) {
            if (attempt > 0) pause(attempt, wanted);
            try {
                byte[] raw = get(net, BuildConfig.MACHINE_URL + "/" + BuildConfig.MACHINE_MANIFEST, 1 << 20, wanted);
                if (!hex(MessageDigest.getInstance("SHA-256").digest(raw)).equals(BuildConfig.MACHINE_MANIFEST)) {
                    throw new IOException("the machine's list does not match the one this app names");
                }
                Manifest list = parse(raw);
                File part = new File(kept.getPath() + ".part");
                try (FileOutputStream o = new FileOutputStream(part)) {
                    o.write(raw);
                    o.getFD().sync();
                }
                if (!part.renameTo(kept)) throw new IOException("could not keep " + kept);
                return list;
            } catch (IOException e) {
                last = e;
            }
        }
        throw new IOException("the machine's list could not be fetched: " + last, last);
    }

    /**
     * {"version": 1, "total": <bytes>, "pieces": [{"sha256": "<hex>", "size": <bytes>}, …]} — every piece
     * named by 64 hex characters, its size above 0 and at most 1 GiB, the sizes adding up to the total.
     */
    private static Manifest parse(byte[] raw) throws IOException {
        try {
            JSONObject o = new JSONObject(new String(raw, java.nio.charset.StandardCharsets.UTF_8));
            if (o.getInt("version") != 1) throw new IOException("the machine's list is of version " + o.get("version"));
            JSONArray a = o.getJSONArray("pieces");
            if (a.length() == 0 || a.length() > 4096) throw new IOException("the machine's list names " + a.length() + " pieces");
            List<Piece> pieces = new ArrayList<>();
            long sum = 0;
            for (int i = 0; i < a.length(); i++) {
                JSONObject p = a.getJSONObject(i);
                String sha = p.getString("sha256");
                long size = p.getLong("size");
                if (!sha.matches("[0-9a-f]{64}") || size <= 0 || size > (1L << 30)) {
                    throw new IOException("the machine's list holds a piece that is no piece: " + i);
                }
                pieces.add(new Piece(sha, size));
                sum += size;
            }
            if (sum != o.getLong("total")) throw new IOException("the machine's pieces do not add up to its total");
            return new Manifest(pieces, sum);
        } catch (JSONException e) {
            throw new IOException("the machine's list does not read: " + e.getMessage(), e);
        }
    }

    /** What an earlier list left that this one does not name (an update's new machine): not kept. */
    private static void sweep(File dir, Manifest list, File kept) {
        Set<String> keep = new HashSet<>();
        keep.add(kept.getName());
        for (Piece p : list.pieces) {
            keep.add(p.sha);
            keep.add(p.sha + ".part");
        }
        File[] all = dir.listFiles();
        if (all != null) for (File f : all) if (!keep.contains(f.getName())) f.delete();
    }

    /**
     * One piece into f: fetched on net into f.part — from where a cut fetch left it — hashed as it comes, and
     * named f only once it is all there and its SHA-256 is its name. Tried four times, a pause between.
     */
    private static void piece(Network net, Piece p, File f, BooleanSupplier wanted, LongConsumer got) throws Exception {
        File part = new File(f.getPath() + ".part");
        Exception last = null;
        for (int attempt = 0; attempt < 4; attempt++) {
            if (attempt > 0) pause(attempt, wanted);
            try {
                into(net, p, part, wanted, got);
                if (!part.renameTo(f)) throw new IOException("could not place " + f);
                return;
            } catch (IOException e) {
                last = e;
            }
        }
        throw new IOException("the machine's piece " + p.sha.substring(0, 12) + " could not be fetched: " + last, last);
    }

    /** A retry's pause: 5 s a try, asked at every second whether the fetch is still wanted. */
    private static void pause(int attempt, BooleanSupplier wanted) throws Exception {
        for (int s = 0; s < 5 * attempt; s++) {
            if (!wanted.getAsBoolean()) throw new Cancelled();
            Thread.sleep(1000);
        }
        if (!wanted.getAsBoolean()) throw new Cancelled();
    }

    private static void into(Network net, Piece p, File part, BooleanSupplier wanted, LongConsumer got) throws Exception {
        long have = part.length();
        if (have > p.size) {   // longer than the piece: from the start
            part.delete();
            have = 0;
        }
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        if (have > 0) {
            try (InputStream in = new FileInputStream(part)) {
                byte[] buf = new byte[1 << 20];
                for (int n; (n = in.read(buf)) > 0; ) md.update(buf, 0, n);
            }
        }
        if (have == p.size) {   // all there, cut before its rename: checked, not fetched again
            if (hex(md.digest()).equals(p.sha)) return;
            part.delete();
            have = 0;
            md.reset();
        }
        HttpURLConnection h = open(net, BuildConfig.MACHINE_URL + "/" + p.sha);
        try {
            if (have > 0) h.setRequestProperty("Range", "bytes=" + have + "-");
            int code = h.getResponseCode();
            if (code == HttpURLConnection.HTTP_OK && have > 0) {   // the range not taken: all of it again
                have = 0;
                md.reset();
            } else if (code == HttpURLConnection.HTTP_PARTIAL) {
                String range = h.getHeaderField("Content-Range");
                if (range == null || !range.startsWith("bytes " + have + "-")) {
                    part.delete();   // a resume this server will not answer: the next try takes it whole
                    throw new IOException("answered another range: " + range);
                }
            } else if (code != HttpURLConnection.HTTP_OK) {
                throw new IOException("HTTP " + code);
            }
            try (InputStream in = h.getInputStream(); FileOutputStream out = new FileOutputStream(part, have > 0)) {
                byte[] buf = new byte[1 << 20];
                for (int n; (n = in.read(buf)) > 0; ) {
                    if (!wanted.getAsBoolean()) throw new Cancelled();
                    if (have + n > p.size) {
                        out.close();
                        part.delete();
                        throw new IOException("longer than its list says");
                    }
                    out.write(buf, 0, n);
                    md.update(buf, 0, n);
                    have += n;
                    got.accept(have);
                }
                out.getFD().sync();
            }
        } finally {
            h.disconnect();
        }
        if (have != p.size) throw new IOException("cut short at " + have + " of " + p.size + " bytes");
        if (!hex(md.digest()).equals(p.sha)) {
            part.delete();
            throw new IOException("does not match its name");
        }
    }

    /** A small answer on net, whole: the list. */
    private static byte[] get(Network net, String url, int max, BooleanSupplier wanted) throws Exception {
        HttpURLConnection h = open(net, url);
        try {
            int code = h.getResponseCode();
            if (code != HttpURLConnection.HTTP_OK) throw new IOException("the machine's list: HTTP " + code);
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            try (InputStream in = h.getInputStream()) {
                byte[] buf = new byte[1 << 16];
                for (int n; (n = in.read(buf)) > 0; ) {
                    if (!wanted.getAsBoolean()) throw new Cancelled();
                    if (b.size() + n > max) throw new IOException("the machine's list is larger than a list");
                    b.write(buf, 0, n);
                }
            }
            return b.toByteArray();
        } finally {
            h.disconnect();
        }
    }

    /** A file's SHA-256 in hex, or "" if it cannot be read. */
    private static String sha(File f) {
        try (InputStream in = new FileInputStream(f)) {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] buf = new byte[1 << 20];
            for (int n; (n = in.read(buf)) > 0; ) md.update(buf, 0, n);
            return hex(md.digest());
        } catch (Exception e) {
            return "";
        }
    }

    /** The pieces, opened one after another as SequenceInputStream reaches each. */
    private static final class Pieces implements Enumeration<InputStream> {
        private final List<Piece> pieces;
        private final File dir;
        private int next;

        Pieces(List<Piece> pieces, File dir) {
            this.pieces = pieces;
            this.dir = dir;
        }

        @Override
        public boolean hasMoreElements() {
            return next < pieces.size();
        }

        @Override
        public InputStream nextElement() {
            if (next >= pieces.size()) throw new NoSuchElementException();
            File f = pieces.get(next++).file(dir);
            try {
                return new FileInputStream(f);
            } catch (IOException e) {
                throw new IllegalStateException("the machine's piece " + f.getName() + " is gone", e);
            }
        }
    }

    private static String hex(byte[] b) {
        StringBuilder s = new StringBuilder(b.length * 2);
        for (byte x : b) s.append(String.format("%02x", x));
        return s.toString();
    }

    // ── the unpack ───────────────────────────────────────────────────────────────────────────────────

    /** in (total bytes of .xz) through zstd into the machine's .part, then named the machine, marked whose. */
    private static void unzstd(Context c, boolean core, BooleanSupplier wanted, IntConsumer percent, InputStream in, long total) throws Exception {
        File dst = EngineService.guest(c);
        File part = new File(dst.getPath() + ".part");
        part.delete();
        try {
            String lib = c.getApplicationInfo().nativeLibraryDir;
            File log = new File(c.getCacheDir(), "unpack.log");
            ProcessBuilder pb = new ProcessBuilder(new File(lib, UNPACKER).getPath(),
                    "-d", "-q", "-f", "--sparse", "-o", part.getPath(), "-")
                    .redirectErrorStream(true).redirectOutput(log);
            pb.environment().put("LD_LIBRARY_PATH", lib);
            Process z = pb.start();
            try (OutputStream to = z.getOutputStream()) {
                byte[] buf = new byte[1 << 20];
                long read = 0;
                for (int n; (n = in.read(buf)) > 0; ) {
                    if (!wanted.getAsBoolean()) {
                        z.destroyForcibly();
                        throw new Cancelled();
                    }
                    to.write(buf, 0, n);
                    read += n;
                    percent.accept((int) Math.min(99, read * 100 / total));
                }
            } catch (IOException e) {   // its input could not be read, or it stopped reading: both are said
                z.destroyForcibly();
                z.waitFor();
                throw new IOException("the unpack stopped (" + e.getMessage() + "); " + UNPACKER + " said: "
                        + MainActivity.tail(log, 300).trim(), e);
            } catch (Cancelled | RuntimeException e) {   // a piece gone mid-way is a RuntimeException of Pieces
                z.destroyForcibly();
                z.waitFor();   // ended: its output is the .part deleted below
                throw e;
            }
            int st = z.waitFor();
            if (st != 0) throw new IOException(UNPACKER + " " + st + ": " + MainActivity.tail(log, 300).trim());
            try (RandomAccessFile out = new RandomAccessFile(part, "rw")) {
                out.getFD().sync();   // on the phone's storage before it is named the machine
            }
            // whole and synced: placed even if nobody wants it now — the next ask starts the machine at once;
            // whose disk it is, before it is the machine: the core's marked, the machine's own office's not
            File marker = coreMarker(c);
            if (core) {
                try (FileOutputStream m = new FileOutputStream(marker)) {
                    m.getFD().sync();
                }
            } else if (marker.exists() && !marker.delete()) {
                throw new IOException("could not remove " + marker);
            }
            if (!part.renameTo(dst)) throw new IOException("could not place " + dst);
        } catch (Exception e) {
            part.delete();
            throw e;
        }
    }
}
