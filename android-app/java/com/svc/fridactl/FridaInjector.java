package com.svc.fridactl;

import android.content.Context;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Locale;

/**
 * 负责把 frida-inject 与 bridge.js 送进目标进程，并建立 TCP 控制通道。
 *
 * 说明：注入其他应用必须 root；frida-inject 以 root 身份运行，目标进程内由
 * bridge.js 监听 127.0.0.1 的一个随机端口，App 通过该端口下发 JS / RPC。
 */
public class FridaInjector {

    private static final String REMOTE_DIR = "/data/local/tmp";
    private static final String REMOTE_BIN = REMOTE_DIR + "/.svc-helper";
    // 升级标记：stock 与 patched 的 libfinj.so 尺寸相同，不能只比 size。
    private static final String INJECTOR_TAG = "patched-17.19.0-r3-miui";
    private static final String PREFS = "frida_phone";

    public final int targetPid;
    public final int port;
    public final String token;
    public final BridgeClient client;

    private final Process process;

    private FridaInjector(int targetPid, int port, String token, BridgeClient client, Process process) {
        this.targetPid = targetPid;
        this.port = port;
        this.token = token;
        this.client = client;
        this.process = process;
    }

    public static FridaInjector attach(Context context, int pid) throws Exception {
        if (pid <= 0) {
            throw new IOException("无效的 PID");
        }
        if (!RootShell.isRooted()) {
            throw new IOException("未获取 root，无法注入其他进程");
        }

        int port = 27100 + new SecureRandom().nextInt(500);
        String token = randomToken();

        String template = readAsset(context, "bridge.js");
        String script = template
                .replace("__PORT__", String.valueOf(port))
                .replace("__TOKEN__", token);

        File localScript = new File(context.getCacheDir(), "bridge_" + port + ".js");
        writeFile(localScript, script);

        String remoteScript = REMOTE_DIR + "/.svc-bridge-" + port + ".js";
        RootShell.Result pushed = RootShell.runRoot(
                "cp '" + localScript.getAbsolutePath() + "' " + remoteScript + " && chmod 600 " + remoteScript);
        if (!pushed.ok) {
            throw new IOException("下发 bridge.js 失败: " + pushed.out);
        }

        String bin = ensureBinary(context);
        String cmd = bin + " -p " + pid + " -s " + remoteScript;
        LogBus.add("inject", "执行: " + cmd);

        Process process = RootShell.startRoot(cmd);
        pump(process, "inject");

        BridgeClient client;
        try {
            client = BridgeClient.connect(port, token, 20000);
        } catch (Exception e) {
            try {
                process.destroy();
            } catch (Exception ignored) {
            }
            RootShell.runRoot("pkill -f '.svc-helper -p " + pid + "'");
            throw e;
        }
        LogBus.add("inject", "已附加 PID " + pid + "，控制端口 " + port);
        return new FridaInjector(pid, port, token, client, process);
    }

    private static String ensureBinary(Context context) throws Exception {
        File src = new File(context.getApplicationInfo().nativeLibraryDir, "libfinj.so");
        if (!src.exists()) {
            throw new IOException("APK 中缺少 libfinj.so");
        }
        String want = String.valueOf(src.length());
        String installedTag = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString("injector_tag", "");
        RootShell.Result stat = RootShell.runRoot("stat -c %s " + REMOTE_BIN + " 2>/dev/null");
        if (stat.ok && want.equals(stat.out.trim()) && INJECTOR_TAG.equals(installedTag)) {
            return REMOTE_BIN;
        }
        RootShell.Result cp = RootShell.runRoot(
                "cp '" + src.getAbsolutePath() + "' " + REMOTE_BIN + " && chmod 755 " + REMOTE_BIN);
        if (!cp.ok) {
            throw new IOException("释放注入器失败: " + cp.out);
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("injector_tag", INJECTOR_TAG).apply();
        return REMOTE_BIN;
    }

    private static void pump(final Process process, final String tag) {
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                try (BufferedReader br = new BufferedReader(
                        new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = br.readLine()) != null) {
                        line = line.replaceAll("\u001B\\[[0-9;]*m", "").replace('\r', ' ').trim();
                        if (!line.isEmpty()) {
                            LogBus.add(tag, line);
                        }
                    }
                } catch (IOException ignored) {
                }
                try {
                    int code = process.waitFor();
                    LogBus.add(tag, "进程结束，退出码 " + code);
                } catch (InterruptedException ignored) {
                }
            }
        }, "inject-pump");
        t.setDaemon(true);
        t.start();
    }

    public boolean isAlive() {
        return client.isAlive();
    }

    public void detach() {
        try {
            client.close();
        } catch (Exception ignored) {
        }
        RootShell.runRoot("pkill -f '.svc-helper -p " + targetPid + "'");
        try {
            process.destroy();
        } catch (Exception ignored) {
        }
        LogBus.add("inject", "已断开 PID " + targetPid);
    }

    private static String randomToken() {
        SecureRandom r = new SecureRandom();
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 16; i++) {
            sb.append(String.format(Locale.US, "%x", r.nextInt(16)));
        }
        return sb.toString();
    }

    private static String readAsset(Context context, String name) throws IOException {
        try (InputStream is = context.getAssets().open(name)) {
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = is.read(buf)) > 0) {
                bos.write(buf, 0, n);
            }
            return new String(bos.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static void writeFile(File file, String content) throws IOException {
        try (OutputStream os = new FileOutputStream(file)) {
            os.write(content.getBytes(StandardCharsets.UTF_8));
        }
    }
}
