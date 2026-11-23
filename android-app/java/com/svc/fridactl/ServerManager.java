package com.svc.fridactl;

import android.content.Context;

import java.io.File;
import java.io.IOException;

/**
 * 管理随 APK 打包的魔改 frida-server（端口 20442），供 PC 客户端或其它工具连接。
 * 手机端自身注入不依赖它，走 frida-inject。
 */
public final class ServerManager {

    public static final int PORT = 20442;
    private static final String REMOTE_BIN = "/data/local/tmp/.svc-server";
    private static final String REMOTE_LOG = "/data/local/tmp/.svc-server.log";
    private static final String PREFS = "frida_phone";
    private static final String SERVER_TAG = "compat-17.19.0-miui-r2";

    private ServerManager() {
    }

    /** 直接探测端口，避免每次刷新状态都执行 su/pgrep。 */
    public static boolean isRunning() {
        try (java.net.Socket s = new java.net.Socket()) {
            s.connect(new java.net.InetSocketAddress("127.0.0.1", PORT), 300);
            return true;
        } catch (IOException e) {
            return false;
        }
    }

    public static String start(Context context) throws Exception {
        if (!RootShell.isRooted()) {
            throw new IOException("未获取 root");
        }
        ensureBinary(context);
        RootShell.runRoot("pkill -f '.svc-server'");
        RootShell.runRoot("rm -f " + REMOTE_LOG);

        String cmd = "setsid nohup " + REMOTE_BIN + " -l 0.0.0.0:" + PORT
                + " >" + REMOTE_LOG + " 2>&1 </dev/null &";
        RootShell.Result r = RootShell.runRoot(cmd);
        if (!r.ok) {
            // 部分老设备没有 setsid，退回普通后台启动
            String fallback = "nohup " + REMOTE_BIN + " -l 0.0.0.0:" + PORT
                    + " >" + REMOTE_LOG + " 2>&1 </dev/null &";
            r = RootShell.runRoot(fallback);
            if (!r.ok) {
                throw new IOException("启动 frida-server 失败: " + r.out);
            }
        }
        for (int i = 0; i < 12; i++) {
            Thread.sleep(250);
            if (isRunning()) {
                LogBus.add("server", "frida-server 已启动，端口 " + PORT);
                return tailLog(20);
            }
        }
        throw new IOException("frida-server 未能在预期时间内启动\n" + tailLog(30));
    }

    public static void stop() {
        RootShell.runRoot("pkill -f '.svc-server'");
        LogBus.add("server", "frida-server 已停止");
    }

    public static String tailLog(int lines) {
        RootShell.Result r = RootShell.runRoot("tail -n " + Math.max(1, lines) + " " + REMOTE_LOG + " 2>/dev/null");
        return r.out;
    }

    private static void ensureBinary(Context context) throws Exception {
        File src = new File(context.getApplicationInfo().nativeLibraryDir, "libfsrv.so");
        if (!src.exists()) {
            throw new IOException("APK 中缺少 libfsrv.so");
        }
        String want = String.valueOf(src.length());
        String installedTag = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString("server_tag", "");
        RootShell.Result stat = RootShell.runRoot("stat -c %s " + REMOTE_BIN + " 2>/dev/null");
        if (stat.ok && want.equals(stat.out.trim()) && SERVER_TAG.equals(installedTag)) {
            return;
        }
        RootShell.Result cp = RootShell.runRoot(
                "cp '" + src.getAbsolutePath() + "' " + REMOTE_BIN + " && chmod 755 " + REMOTE_BIN);
        if (!cp.ok) {
            throw new IOException("释放 frida-server 失败: " + cp.out);
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("server_tag", SERVER_TAG).apply();
    }
}
