package il.co.digitaloffice.app;

import android.content.Context;
import android.os.Build;
import android.os.ParcelFileDescriptor;

import org.lsposed.hiddenapibypass.HiddenApiBypass;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

/**
 * The office's machine on the phone's own virtualization (DGO-1328): AVF's crosvm boots the machine's own
 * kernel and initrd (kept beside its disk, Virt.kernel) over the same disk QEMU boots, at the hardware's
 * speed. Its API for a custom machine is the platform's hidden one (android.system.virtualmachine, its
 * custom image config: @hide), reached by reflection once HiddenApiBypass lets this app see it; its two
 * permissions are development ones, granted once through Wireless debugging (Pairing).
 *
 * <p>What the guest needs from here, and how it gets it — the same office as under QEMU:
 * <ul>
 * <li>its console: AVF captures it (debug level FULL) and it is written to the same console.log;</li>
 * <li>the edge: AVF gives an app no port forward, only a connection to a port the GUEST listens on
 * (connectVsock) — so the phone's loopback port is served here, each connection carried to the guest's
 * vsock 5080, where systemd hands it to its edge on 80 (guest.sh, dgo-edge-vsock);</li>
 * <li>the core's token for this boot: on a disk of its own, read-only, /dev/vdb (QEMU gives it in fw_cfg);</li>
 * <li>the time: AVF wires no clock, so the kernel's command line carries it (dgo.epoch), until NTP;</li>
 * <li>its network: the phone's own, through AVF's tethering (Android 15's setNetworkSupported, 16's
 * useNetwork), where the phone's AVF has it;</li>
 * <li>a clean power-off: a connection to its vsock 5099 (dgo-poweroff), then a stop if it does not end.</li>
 * </ul>
 */
final class Avf {

    static final long EDGE_PORT = 5080, POWEROFF_PORT = 5099;
    private static final String NAME = "dgo-office";
    private static volatile boolean bypassed;

    private final Context c;
    private final File console;
    private Object vm;                 // android.system.virtualmachine.VirtualMachine
    private ServerSocket edge;
    private volatile boolean reached;  // a connection reached the guest's edge: the machine is up to systemd
    private volatile boolean stopped;
    private volatile String stoppedWhy = "";
    private final long started = System.currentTimeMillis();

    Avf(Context c, File console) {
        this.c = c;
        this.console = console;
    }

    /** Hidden APIs open to this app — AVF's custom machine is one (once a process: it holds for its life). */
    static void bypass() {
        if (bypassed || Build.VERSION.SDK_INT < 28) return;
        bypassed = HiddenApiBypass.addHiddenApiExemptions("L");
    }

    /**
     * Boots the machine: the edge served on loopback port (its connections carried to the guest), its token on
     * a disk of its own, memory and CPUs as given (oneCpu: the phone reset a guest that matched its CPUs).
     */
    void start(int port, String token, long memoryBytes, boolean oneCpu) throws Exception {
        bypass();
        File run = new File(c.getFilesDir(), "run");
        File tokenDisk = new File(run, "edge-token.img");
        // its first 64 bytes are the token, as the guest reads them (guest.sh: head -c 64 /dev/vdb, under AVF only)
        try (RandomAccessFile f = new RandomAccessFile(tokenDisk, "rw")) {
            f.setLength(0);
            f.write((token + "\n").getBytes(StandardCharsets.UTF_8));
            f.setLength(4096);   // a disk is whole sectors
            f.getFD().sync();
        }
        Class<?> vmmClass = Class.forName("android.system.virtualmachine.VirtualMachineManager");
        Class<?> cfgClass = Class.forName("android.system.virtualmachine.VirtualMachineConfig");
        Class<?> builder = Class.forName("android.system.virtualmachine.VirtualMachineConfig$Builder");
        Class<?> custom = Class.forName("android.system.virtualmachine.VirtualMachineCustomImageConfig");
        Class<?> customBuilder = Class.forName("android.system.virtualmachine.VirtualMachineCustomImageConfig$Builder");
        Class<?> disk = Class.forName("android.system.virtualmachine.VirtualMachineCustomImageConfig$Disk");

        Object img = customBuilder.getConstructor().newInstance();
        call(img, "setName", NAME);
        call(img, "setKernelPath", Virt.kernel(c).getAbsolutePath());
        call(img, "setInitrdPath", Virt.initrd(c).getAbsolutePath());
        for (String p : new String[]{"root=LABEL=cloudimg-rootfs", "ro", "console=hvc0", "dgo.engine=avf",
                "dgo.epoch=" + (System.currentTimeMillis() / 1000)}) {
            customBuilder.getMethod("addParam", String.class).invoke(img, p);
        }
        customBuilder.getMethod("addDisk", disk).invoke(img, disk.getMethod("RWDisk", String.class).invoke(null, EngineService.guest(c).getAbsolutePath()));
        customBuilder.getMethod("addDisk", disk).invoke(img, disk.getMethod("RODisk", String.class).invoke(null, tokenDisk.getAbsolutePath()));
        if (Build.VERSION.SDK_INT >= 36) {
            // each where this Android has it: a vendor's build without one boots the machine all the same
            for (String switched : new String[]{"useNetwork", "useAutoMemoryBalloon"}) {
                try {
                    customBuilder.getMethod(switched, boolean.class).invoke(img, true);
                } catch (NoSuchMethodException e) {
                    say("[the app] AVF on this Android has no " + switched + ": the machine boots without it");
                }
            }
            gpu(customBuilder, img);
        }
        Object image = customBuilder.getMethod("build").invoke(img);

        Object b = builder.getConstructor(Context.class).newInstance(c);
        builder.getMethod("setProtectedVm", boolean.class).invoke(b, false);
        builder.getMethod("setDebugLevel", int.class).invoke(b, 1);            // DEBUG_LEVEL_FULL: its console is captured
        builder.getMethod("setVmOutputCaptured", boolean.class).invoke(b, true);
        builder.getMethod("setMemoryBytes", long.class).invoke(b, memoryBytes);
        builder.getMethod("setCpuTopology", int.class).invoke(b, oneCpu ? 0 : 1);   // ONE_CPU / MATCH_HOST
        builder.getMethod("setCustomImageConfig", custom).invoke(b, image);
        if (Build.VERSION.SDK_INT == 35) {
            try {
                builder.getMethod("setNetworkSupported", boolean.class).invoke(b, true);
            } catch (NoSuchMethodException e) {
                say("[the app] AVF on this Android has no network switch for a machine: it boots without the phone's network");
            }
        }
        Object config = builder.getMethod("build").invoke(b);

        Object vmm = c.getSystemService(vmmClass);
        if (vmm == null) throw new IOException("the phone answers no VirtualMachineManager");
        try {   // a fresh config every boot: what the last one said (its memory, its kernel) is not this one
            vmmClass.getMethod("delete", String.class).invoke(vmm, NAME);
        } catch (Exception ignored) {
            // none there yet
        }
        vm = vmmClass.getMethod("create", String.class, cfgClass).invoke(vmm, NAME, config);
        listen();
        new FileOutputStream(console).close();   // this boot's console, from its first line — as QEMU's redirect starts it
        vm.getClass().getMethod("run").invoke(vm);
        pump((InputStream) vm.getClass().getMethod("getConsoleOutput").invoke(vm), "console");
        pump((InputStream) vm.getClass().getMethod("getLogOutput").invoke(vm), "log");
        serveEdge(port);
        say("[the app] the machine boots under AVF: " + (memoryBytes >> 20) + " MiB, " + (oneCpu ? "one CPU" : "the phone's CPUs")
                + ", the edge on 127.0.0.1:" + port + " through vsock " + EDGE_PORT);
    }

    /**
     * A headless 2-D, surfaceless GPU: on a Pixel a machine with no GPU runs the minimal crosvm, which has no
     * network, and a GPU puts it on the full one (measured by others; no screen is drawn).
     */
    private static void gpu(Class<?> customBuilder, Object img) {
        try {
            Class<?> gpu = Class.forName("android.system.virtualmachine.VirtualMachineCustomImageConfig$GpuConfig");
            Class<?> gb = Class.forName("android.system.virtualmachine.VirtualMachineCustomImageConfig$GpuConfig$Builder");
            Object g = gb.getConstructor().newInstance();
            gb.getMethod("setBackend", String.class).invoke(g, "2d");
            gb.getMethod("setRendererUseSurfaceless", Boolean.class).invoke(g, Boolean.TRUE);
            customBuilder.getMethod("setGpuConfig", gpu).invoke(img, gb.getMethod("build").invoke(g));
        } catch (Throwable ignored) {
            // no GPU config on this Android: the machine is asked for its network all the same
        }
    }

    /** The machine's end, as AVF tells it: kept with its reason (onStopped's, onError's). */
    private void listen() throws Exception {
        Class<?> cb = Class.forName("android.system.virtualmachine.VirtualMachineCallback");
        Object callback = Proxy.newProxyInstance(cb.getClassLoader(), new Class<?>[]{cb}, (proxy, method, args) -> {
            String m = method.getName();
            if (method.getDeclaringClass() == Object.class) {   // the platform may keep it in a set
                switch (m) {
                    case "equals": return proxy == args[0];
                    case "hashCode": return System.identityHashCode(proxy);
                    default: return "dgo-office's callback";
                }
            }
            if ("onStopped".equals(m)) {
                stoppedWhy = "stopped (" + stopReason(args != null && args.length > 1 ? (Integer) args[1] : -1) + ")";
                stopped = true;
            } else if ("onError".equals(m)) {
                stoppedWhy = "error " + (args != null && args.length > 2 ? args[1] + ": " + args[2] : "");
                say("[the app] AVF: " + stoppedWhy);
            }
            return null;
        });
        vm.getClass().getMethod("setCallback", java.util.concurrent.Executor.class, cb)
                .invoke(vm, Executors.newSingleThreadExecutor(), callback);
    }

    /** VirtualMachineCallback's STOP_REASON_*, in words (AOSP libs/framework-virtualization). */
    static String stopReason(int r) {
        switch (r) {
            case -1: return "the virtualization service died";
            case 0: return "an infrastructure error";
            case 1: return "killed";
            case 3: return "the machine powered off";
            case 4: return "the machine did not start";
            case 5: return "the machine rebooted";
            case 6: return "the machine crashed";
            case 16: return "the machine hung up";
            default: return "reason " + r;
        }
    }

    /** The machine ended by rebooting within its first two minutes: the phone reset a guest of its CPUs' count. */
    boolean resetEarly() {
        return stoppedWhy.contains(stopReason(5)) && System.currentTimeMillis() - started < 120_000;
    }

    boolean alive() {
        if (stopped || vm == null) return false;
        try {
            return (Integer) vm.getClass().getMethod("getStatus").invoke(vm) == 1;   // STATUS_RUNNING
        } catch (Exception e) {
            return false;
        }
    }

    String why() {
        return stoppedWhy;
    }

    /** A connection has reached the guest's edge: the machine booted to its systemd. */
    boolean reached() {
        return reached;
    }

    long since() {
        return started;
    }

    /** The guest powers itself off (its journal and its databases closed); stopped if it has not within wait. */
    void powerDown(long waitMillis) {
        try {
            ParcelFileDescriptor p = (ParcelFileDescriptor) vm.getClass().getMethod("connectVsock", long.class).invoke(vm, POWEROFF_PORT);
            p.close();
        } catch (Exception e) {
            say("[the app] the machine did not take the power-off (" + e + "): it is stopped");
        }
        long until = System.currentTimeMillis() + waitMillis;
        while (alive() && System.currentTimeMillis() < until) {
            try {
                Thread.sleep(1000);
            } catch (InterruptedException e) {
                break;
            }
        }
        kill();
    }

    void kill() {
        try {
            if (edge != null) edge.close();
        } catch (IOException ignored) {
            // closed
        }
        try {
            if (vm != null && alive()) vm.getClass().getMethod("stop").invoke(vm);
        } catch (Exception ignored) {
            // it ended meanwhile
        }
        try {
            if (vm != null) vm.getClass().getMethod("close").invoke(vm);
        } catch (Exception ignored) {
            // closed
        }
        stopped = true;
    }

    /** The guest's console (and its log) into console.log, read for as long as it writes: a full pipe stops the guest. */
    private void pump(InputStream in, String what) {
        Thread t = new Thread(() -> {
            byte[] buf = new byte[1 << 14];
            try (InputStream from = in; OutputStream to = new FileOutputStream(console, true)) {
                for (int n; (n = from.read(buf)) > 0; ) {
                    to.write(buf, 0, n);
                    to.flush();
                }
            } catch (IOException e) {
                if (!stopped) say("[the app] the machine's " + what + " ended: " + e.getMessage());
            }
        }, "avf-" + what);
        t.setDaemon(true);
        t.start();
    }

    /**
     * The phone's 127.0.0.1:port, each connection carried to the guest's vsock EDGE_PORT. One that the guest
     * does not take yet (its systemd not up) is closed at once — the core's proof asks again.
     */
    private void serveEdge(int port) throws IOException {
        edge = new ServerSocket(port, 64, InetAddress.getByName("127.0.0.1"));
        Thread t = new Thread(() -> {
            while (!edge.isClosed()) {
                Socket s;
                try {
                    s = edge.accept();
                } catch (IOException e) {
                    return;   // closed: the machine is gone
                }
                new Thread(() -> carry(s), "avf-edge").start();
            }
        }, "avf-edge-accept");
        t.setDaemon(true);
        t.start();
    }

    private void carry(Socket s) {
        ParcelFileDescriptor p;
        try {
            p = (ParcelFileDescriptor) vm.getClass().getMethod("connectVsock", long.class).invoke(vm, EDGE_PORT);
        } catch (Exception e) {
            try {
                s.close();
            } catch (IOException ignored) {
                // closed
            }
            return;
        }
        reached = true;
        try {
            InputStream fromGuest = new FileInputStream(p.getFileDescriptor());
            OutputStream toGuest = new FileOutputStream(p.getFileDescriptor());
            Thread up = new Thread(() -> copy(stream(s, true), toGuest, s, p), "avf-edge-up");
            up.start();
            copy(fromGuest, stream(s, false), s, p);
            up.join();
        } catch (Exception ignored) {
            // either side ended
        } finally {
            close(s, p);
        }
    }

    private static Object stream(Socket s, boolean in) {
        try {
            return in ? s.getInputStream() : s.getOutputStream();
        } catch (IOException e) {
            return null;
        }
    }

    private static void copy(Object from, Object to, Socket s, ParcelFileDescriptor p) {
        if (!(from instanceof InputStream) || !(to instanceof OutputStream)) {
            close(s, p);
            return;
        }
        byte[] buf = new byte[1 << 16];
        try {
            for (int n; (n = ((InputStream) from).read(buf)) > 0; ) {
                ((OutputStream) to).write(buf, 0, n);
                ((OutputStream) to).flush();
            }
        } catch (IOException ignored) {
            // the other side closed
        }
        close(s, p);   // one direction's end is the connection's: the other is unblocked by it
    }

    private static void close(Socket s, ParcelFileDescriptor p) {
        try {
            s.close();
        } catch (IOException ignored) {
            // closed
        }
        try {
            p.close();
        } catch (IOException ignored) {
            // closed
        }
    }

    private static Object call(Object on, String method, String arg) throws Exception {
        Method m = on.getClass().getMethod(method, String.class);
        return m.invoke(on, arg);
    }

    private void say(String line) {
        try (OutputStream o = new FileOutputStream(console, true)) {
            o.write(("\n" + line + "\n").getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
            // the console is the only place to say it
        }
    }
}
