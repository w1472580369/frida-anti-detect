package com.svc.fridactl;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import java.util.Locale;

/**
 * 应用后端：同时服务于 WebView 界面（@JavascriptInterface）与 MCP Server。
 */
public class AppCore {

    private static final String PREFS = "frida_phone";
    private static final String KEY_TOKEN = "mcp_token";
    private static final String KEY_PORT = "mcp_port";

    private static AppCore instance;

    private final Context context;
    private final SharedPreferences prefs;
    private final Object lock = new Object();

    private volatile FridaInjector injector;
    private McpServer mcpServer;

    private volatile String mcpToken;
    private volatile int mcpPort;
    private volatile Boolean rootCache;

    private AppCore(Context context) {
        this.context = context.getApplicationContext();
        this.prefs = this.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        this.mcpToken = prefs.getString(KEY_TOKEN, null);
        if (this.mcpToken == null || this.mcpToken.isEmpty()) {
            this.mcpToken = randomToken();
            prefs.edit().putString(KEY_TOKEN, this.mcpToken).apply();
        }
        this.mcpPort = prefs.getInt(KEY_PORT, 8765);
    }

    public static synchronized AppCore get(Context context) {
        if (instance == null) {
            instance = new AppCore(context);
        }
        return instance;
    }

    public Context context() {
        return context;
    }

    // ---------------------------------------------------------------- MCP

    public synchronized void startMcp() {
        if (mcpServer != null && mcpServer.isRunning()) {
            return;
        }
        final McpServer server = new McpServer(this, mcpPort, mcpToken);
        mcpServer = server;
        /* ServerSocket.bind 不能在主线程做，否则可能触发 NetworkOnMainThreadException */
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    server.start();
                    LogBus.add("mcp", "已启动 http://" + localIp() + ":" + mcpPort + "/mcp");
                } catch (Exception e) {
                    LogBus.add("mcp", "启动失败: " + e);
                    synchronized (AppCore.this) {
                        if (mcpServer == server) {
                            mcpServer = null;
                        }
                    }
                }
            }
        }, "mcp-start");
        t.setDaemon(true);
        t.start();
    }

    public synchronized void stopMcp() {
        if (mcpServer != null) {
            mcpServer.stop();
            mcpServer = null;
            LogBus.add("mcp", "已停止");
        }
    }

    public synchronized void restartMcp(int port, String token) {
        stopMcp();
        if (port > 0) {
            mcpPort = port;
            prefs.edit().putInt(KEY_PORT, port).apply();
        }
        if (token != null && !token.isEmpty()) {
            mcpToken = token;
            prefs.edit().putString(KEY_TOKEN, token).apply();
        }
        startMcp();
    }

    /**
     * 延迟重启 MCP：先让当前请求把响应写回客户端，再关闭监听端口。
     * 用于 MCP 工具 frida_restart_mcp / frida_regenerate_token。
     */
    public synchronized void scheduleRestartMcp(final int port, final String token, long delayMs) {
        final int newPort = port > 0 ? port : mcpPort;
        final String newToken = (token == null || token.isEmpty()) ? mcpToken : token;
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    Thread.sleep(Math.max(200, delayMs));
                } catch (InterruptedException ignored) {
                }
                restartMcp(newPort, newToken);
            }
        }, "mcp-restart");
        t.setDaemon(true);
        t.start();
    }

    public synchronized JSONObject scheduleRegenerateToken(long delayMs) {
        String token = randomToken();
        scheduleRestartMcp(mcpPort, token, delayMs);
        JSONObject o = new JSONObject();
        try {
            o.put("ok", true);
            o.put("scheduled", true);
            o.put("token", token);
            o.put("port", mcpPort);
            o.put("delay_ms", Math.max(200, delayMs));
            o.put("note", "新令牌已生效；请立即用新令牌重连 MCP，旧连接会在重启时断开。");
        } catch (Exception e) {
            return error(e.getMessage());
        }
        return o;
    }

    public synchronized boolean isMcpRunning() {
        return mcpServer != null && mcpServer.isRunning();
    }

    public String mcpToken() {
        return mcpToken;
    }

    public int mcpPort() {
        return mcpPort;
    }

    // ---------------------------------------------------------------- 状态

    public boolean isRooted() {
        if (rootCache == null) {
            rootCache = RootShell.isRooted();
        }
        return rootCache;
    }

    public boolean refreshRoot() {
        rootCache = RootShell.isRooted();
        return rootCache;
    }

    JSONObject statusJson() {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", true);
            o.put("root", isRooted());
            o.put("device", Build.MANUFACTURER + " " + Build.MODEL);
            o.put("android", Build.VERSION.RELEASE);
            o.put("abi", Build.SUPPORTED_ABIS.length > 0 ? Build.SUPPORTED_ABIS[0] : "?");
            o.put("ip", localIp());

            FridaInjector inj = injector;
            if (inj == null) {
                o.put("session", JSONObject.NULL);
            } else {
                JSONObject s = new JSONObject();
                s.put("pid", inj.targetPid);
                s.put("port", inj.port);
                s.put("alive", inj.isAlive());
                o.put("session", s);
            }

            o.put("server", ServerManager.isRunning());

            JSONObject m = new JSONObject();
            m.put("running", isMcpRunning());
            m.put("port", mcpPort);
            m.put("token", mcpToken);
            m.put("url", "http://" + localIp() + ":" + mcpPort + "/mcp");
            o.put("mcp", m);
            o.put("injector", "patched-17.19.0-r5-miui-nullguard");
            o.put("server_mode", "compat");
        } catch (Exception e) {
            o = error("状态读取失败: " + e.getMessage());
        }
        return o;
    }

    JSONArray processesJson(String filter) {
        String f = filter == null ? "" : filter.trim().toLowerCase(Locale.US);
        JSONArray arr = new JSONArray();
        for (ProcessScanner.Proc p : ProcessScanner.list()) {
            if (!f.isEmpty() && !p.name.toLowerCase(Locale.US).contains(f)
                    && !String.valueOf(p.pid).equals(f)) {
                continue;
            }
            JSONObject o = new JSONObject();
            try {
                o.put("pid", p.pid);
                o.put("name", p.name);
                arr.put(o);
            } catch (Exception ignored) {
            }
            if (arr.length() >= 500) {
                break;
            }
        }
        return arr;
    }

    JSONObject attachJson(int pid) {
        synchronized (lock) {
            try {
                if (!isRooted()) {
                    return error("未获取 root，无法注入进程");
                }
                if (injector != null) {
                    injector.detach();
                    injector = null;
                }
                injector = FridaInjector.attach(context, pid);
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("pid", pid);
                o.put("port", injector.port);
                return o;
            } catch (Exception e) {
                injector = null;
                return error("附加失败: " + e.getMessage());
            }
        }
    }

    JSONObject detachJson() {
        synchronized (lock) {
            if (injector != null) {
                injector.detach();
                injector = null;
            }
            JSONObject o = new JSONObject();
            try {
                o.put("ok", true);
            } catch (Exception ignored) {
            }
            return o;
        }
    }

    JSONObject evalJson(String code, int timeoutMs) {
        FridaInjector inj = injector;
        if (inj == null || !inj.isAlive()) {
            return error("尚未附加进程，请先在“进程”页附加一个应用");
        }
        try {
            String result = inj.client.eval(code, Math.max(1000, timeoutMs));
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("result", result);
            return o;
        } catch (Exception e) {
            return error("执行失败: " + e.getMessage());
        }
    }

    JSONObject rpcListJson() {
        FridaInjector inj = injector;
        if (inj == null || !inj.isAlive()) {
            return error("尚未附加进程");
        }
        try {
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("exports", inj.client.rpcList());
            return o;
        } catch (Exception e) {
            return error("读取 RPC 失败: " + e.getMessage());
        }
    }

    JSONObject rpcCallJson(String name, JSONArray args, int timeoutMs) {
        FridaInjector inj = injector;
        if (inj == null || !inj.isAlive()) {
            return error("尚未附加进程");
        }
        try {
            String result = inj.client.rpcCall(name, args, Math.max(1000, timeoutMs));
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("result", result);
            return o;
        } catch (Exception e) {
            return error("RPC 调用失败: " + e.getMessage());
        }
    }

    JSONObject launchJson(String pkg) {
        if (pkg == null || !pkg.matches("[A-Za-z0-9._]+")) {
            return error("包名不合法");
        }
        if (!isRooted()) {
            return error("未获取 root");
        }
        try {
            RootShell.runRoot("monkey -p " + pkg + " -c android.intent.category.LAUNCHER 1");
            int pid = -1;
            long deadline = System.currentTimeMillis() + 10000;
            while (System.currentTimeMillis() < deadline) {
                pid = ProcessScanner.pidOf(pkg);
                if (pid > 0) {
                    break;
                }
                Thread.sleep(400);
            }
            if (pid <= 0) {
                RootShell.Result r = RootShell.runRoot("cmd package resolve-activity --brief " + pkg + " | tail -n 1");
                String component = r.out.trim();
                if (component.contains("/")) {
                    RootShell.runRoot("am start -n " + component);
                    deadline = System.currentTimeMillis() + 8000;
                    while (System.currentTimeMillis() < deadline) {
                        pid = ProcessScanner.pidOf(pkg);
                        if (pid > 0) {
                            break;
                        }
                        Thread.sleep(400);
                    }
                }
            }
            if (pid <= 0) {
                return error("应用已启动，但未找到进程；请手动刷新进程列表后附加");
            }
            return attachJson(pid);
        } catch (Exception e) {
            return error("启动失败: " + e.getMessage());
        }
    }

    JSONObject startServerJson() {
        try {
            String log = ServerManager.start(context);
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("port", ServerManager.PORT);
            o.put("log", log);
            return o;
        } catch (Exception e) {
            return error("启动 server 失败: " + e.getMessage());
        }
    }

    JSONObject stopServerJson() {
        ServerManager.stop();
        try {
            JSONObject o = new JSONObject();
            o.put("ok", true);
            return o;
        } catch (Exception e) {
            return error(e.getMessage());
        }
    }

    JSONObject templatesJson() {
        try {
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("templates", Templates.all(context));
            return o;
        } catch (Exception e) {
            return error(e.getMessage());
        }
    }

    JSONObject templateJson(String name) {
        JSONObject t = Templates.find(context, name);
        if (t == null) {
            return error("模板不存在: " + name);
        }
        try {
            JSONObject o = new JSONObject();
            o.put("ok", true);
            o.put("template", t);
            return o;
        } catch (Exception e) {
            return error(e.getMessage());
        }
    }

    JSONObject guideJson() {
        JSONObject o = new JSONObject();
        try {
            String ip = localIp();
            String mcpUrl = "http://" + ip + ":" + mcpPort + "/mcp";
            o.put("ok", true);
            o.put("title", "Frida Phone 说明（兼容版）");
            o.put("version", "17.19.0-compat");
            o.put("injector", "patched-17.19.0-r5-miui-nullguard");
            o.put("server_mode", "compat");
            o.put("ip", ip);
            o.put("server_port", ServerManager.PORT);
            o.put("mcp_url", mcpUrl);
            o.put("mcp_token", mcpToken);

            JSONArray blocks = new JSONArray();

            JSONObject b1 = block("端口与入口");
            b1.put("lines", arr(
                    "frida-server 监听 0.0.0.0:" + ServerManager.PORT + "（改端口，避开 27042 特征）",
                    "兼容版 server 保留官方 D-Bus 协议名 re.frida.*，官方 frida-tools 可直接连接",
                    "MCP 监听 0.0.0.0:" + mcpPort + "，端点 /mcp",
                    "App 内注入不监听固定端口：注入器在目标进程里开随机本地端口，再由 App 用一次性令牌连接",
                    "PC 连的是 frida-server（20442），不是 App 内注入器"
            ));
            blocks.put(b1);

            JSONObject b2 = block("兼容版 server（PC 用）");
            b2.put("lines", arr(
                    "D-Bus 服务名：re.frida.*（官方协议，未改名）",
                    "D-Bus 对象路径：/re/frida/*（官方协议，未改名）",
                    "二进制：/data/local/tmp/.svc-server",
                    "日志：/data/local/tmp/.svc-server.log",
                    "helper dex：已由源码重建，内含 Android 12 / MIUI systemMain 回退",
                    "说明：兼容版优先保证官方客户端可用；线程名、路径、端口仍是改过的"
            ));
            blocks.put(b2);

            JSONObject b2b = block("patched injector（App 内用）");
            b2b.put("lines", arr(
                    "D-Bus 服务名：app.svc.*（原 re.frida.*）",
                    "D-Bus 对象路径：/app/svc/*（原 /re/frida/*）",
                    "线程名：svc-eternal / main-loop（原 frida-eternal-agent / gum-js-loop）",
                    "注入器：/data/local/tmp/.svc-helper",
                    "bridge 脚本：/data/local/tmp/.svc-bridge-<port>.js",
                    "helper dex：/data/local/tmp/.svc-<id>.dex",
                    "注入器只在手机内部使用，不对外提供 RPC，所以 app.svc 改名不影响 PC 官方客户端"
            ));
            blocks.put(b2b);

            JSONObject b3 = block("PC 连接命令（官方 frida-tools）");
            JSONArray cmds = new JSONArray();
            cmds.put(cmd("列出进程", "frida-ps -H " + ip + ":" + ServerManager.PORT, "手机与 PC 在同一局域网"));
            cmds.put(cmd("按包名启动并注入", "frida -H " + ip + ":" + ServerManager.PORT + " -f com.example.app -l hook.js", "spawn 模式"));
            cmds.put(cmd("按进程名附加", "frida -H " + ip + ":" + ServerManager.PORT + " -n com.example.app -l hook.js", "attach 模式"));
            cmds.put(cmd("按 PID 附加", "frida -H " + ip + ":" + ServerManager.PORT + " -p 12345 -l hook.js", "PID 用 frida-ps 查"));
            cmds.put(cmd("USB + adb 转发", "adb forward tcp:" + ServerManager.PORT + " tcp:" + ServerManager.PORT + " && frida-ps -H 127.0.0.1:" + ServerManager.PORT, "没有局域网时使用"));
            cmds.put(cmd("手动启动 server", "su -c '/data/local/tmp/.svc-server -l 0.0.0.0:" + ServerManager.PORT + "'", "App 的“启动”按钮会自动做这一步"));
            b3.put("commands", cmds);
            b3.put("lines", arr(
                    "官方客户端直接用 pip 安装即可：pip install frida-tools",
                    "客户端版本建议与 server 对齐：pip install frida==17.19.0 frida-tools",
                    "注意：frida-inject 没有 -H 参数，不能直接连 server；PC 侧请用 frida / frida-ps。",
                    "PC 命令请使用 20442；不要使用官方默认端口。"
            ));
            blocks.put(b3);

            JSONObject b4 = block("App 内操作");
            b4.put("lines", arr(
                    "进程页选择目标 → 附加；应用页可按包名启动并自动附加。",
                    "附加成功后到脚本页运行 JS，RPC 页调用 rpc.exports。",
                    "注入器已处理 Android 12 / MIUI 的 systemMain 兼容问题，可注入系统设置等系统应用。",
                    "注入器为 patched 17.19.0：控制端口、服务名、对象路径、线程名、helper dex 均已处理。",
                    "仅支持 arm64 设备；注入其他应用需要 root。"
            ));
            blocks.put(b4);

            JSONObject b5 = block("MCP / AI 调用");
            JSONArray mcpLines = arr(
                    "端点：" + mcpUrl,
                    "请求头：Authorization: Bearer " + mcpToken,
                    "协议：JSON-RPC 2.0，支持 initialize / tools/list / tools/call / ping",
                    "工具覆盖：状态、进程、应用、附加/断开、eval、RPC、模板、server 启停、日志、说明、MCP 信息。",
                    "AI 第一次调用建议先执行 frida_get_guide，按返回的命令和路径操作。"
            );
            b5.put("lines", mcpLines);
            JSONArray mcpCmds = new JSONArray();
            mcpCmds.put(cmd("列出 MCP 工具",
                    "curl -s -H 'Authorization: Bearer " + mcpToken + "' -H 'Content-Type: application/json' "
                            + "-d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}' " + mcpUrl,
                    "返回全部工具及参数 schema"));
            mcpCmds.put(cmd("调用工具",
                    "curl -s -H 'Authorization: Bearer " + mcpToken + "' -H 'Content-Type: application/json' "
                            + "-d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"frida_status\",\"arguments\":{}}}' "
                            + mcpUrl,
                    "把 name 换成任意工具名"));
            b5.put("commands", mcpCmds);
            blocks.put(b5);

            o.put("blocks", blocks);
            o.put("note", "本 APK 采用“兼容版 server + patched injector”：server 保留 re.frida 协议名以兼容官方 frida-tools，注入器继续使用 app.svc 内部命名。两者互不影响。源码树与 GitHub Actions 支持 compat / stealth 两种构建；stealth 版 server 使用 app.svc，必须搭配项目构建的 patched frida wheel。");
        } catch (Exception e) {
            return error("说明读取失败: " + e.getMessage());
        }
        return o;
    }

    private static JSONObject block(String title) throws Exception {
        JSONObject o = new JSONObject();
        o.put("title", title);
        return o;
    }

    private static JSONObject cmd(String label, String command, String note) throws Exception {
        JSONObject o = new JSONObject();
        o.put("label", label);
        o.put("cmd", command);
        o.put("note", note);
        return o;
    }

    private static JSONArray arr(String... values) {
        JSONArray a = new JSONArray();
        for (String v : values) {
            a.put(v);
        }
        return a;
    }

    String localIp() {
        try {
            List<NetworkInterface> ifaces = Collections.list(NetworkInterface.getNetworkInterfaces());
            String fallback = null;
            for (NetworkInterface nif : ifaces) {
                if (!nif.isUp() || nif.isLoopback()) {
                    continue;
                }
                for (InetAddress addr : Collections.list(nif.getInetAddresses())) {
                    if (!(addr instanceof Inet4Address) || addr.isLoopbackAddress()) {
                        continue;
                    }
                    String ip = addr.getHostAddress();
                    if (nif.getName().startsWith("wlan")) {
                        return ip;
                    }
                    if (fallback == null) {
                        fallback = ip;
                    }
                }
            }
            return fallback == null ? "127.0.0.1" : fallback;
        } catch (Exception e) {
            return "127.0.0.1";
        }
    }

    static JSONObject error(String message) {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", false);
            o.put("error", message == null ? "unknown" : message);
        } catch (Exception ignored) {
        }
        return o;
    }

    private static String randomToken() {
        SecureRandom r = new SecureRandom();
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 20; i++) {
            sb.append(String.format(Locale.US, "%x", r.nextInt(16)));
        }
        return sb.toString();
    }

    // ---------------------------------------------------------------- JS 接口

    @android.webkit.JavascriptInterface
    public String status() {
        return statusJson().toString();
    }

    @android.webkit.JavascriptInterface
    public String guide() {
        return guideJson().toString();
    }

    @android.webkit.JavascriptInterface
    public String recheckRoot() {
        rootCache = RootShell.isRooted();
        return statusJson().toString();
    }

    @android.webkit.JavascriptInterface
    public String listProcesses() {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", true);
            o.put("processes", processesJson(""));
        } catch (Exception e) {
            return error(e.getMessage()).toString();
        }
        return o.toString();
    }

    @android.webkit.JavascriptInterface
    public String attach(int pid) {
        return attachJson(pid).toString();
    }

    @android.webkit.JavascriptInterface
    public String detach() {
        return detachJson().toString();
    }

    @android.webkit.JavascriptInterface
    public String eval(String code) {
        return evalJson(code, 30000).toString();
    }

    @android.webkit.JavascriptInterface
    public String rpcList() {
        return rpcListJson().toString();
    }

    @android.webkit.JavascriptInterface
    public String rpcCall(String name, String argsJson) {
        try {
            JSONArray args = new JSONArray(argsJson == null || argsJson.trim().isEmpty() ? "[]" : argsJson);
            return rpcCallJson(name, args, 30000).toString();
        } catch (Exception e) {
            return error("参数必须是 JSON 数组: " + e.getMessage()).toString();
        }
    }

    @android.webkit.JavascriptInterface
    public String listApps() {
        JSONObject o = new JSONObject();
        try {
            RootShell.Result r = RootShell.runRoot("pm list packages -3");
            if (!r.ok || !r.hasText()) {
                r = RootShell.run("pm list packages -3");
            }
            JSONArray arr = new JSONArray();
            for (String line : r.out.split("\n")) {
                line = line.trim();
                if (line.startsWith("package:")) {
                    String pkg = line.substring("package:".length()).trim();
                    if (!pkg.isEmpty()) {
                        JSONObject a = new JSONObject();
                        a.put("package", pkg);
                        arr.put(a);
                    }
                }
            }
            o.put("ok", true);
            o.put("apps", arr);
        } catch (Exception e) {
            return error(e.getMessage()).toString();
        }
        return o.toString();
    }

    @android.webkit.JavascriptInterface
    public String launchApp(String pkg) {
        return launchJson(pkg).toString();
    }

    @android.webkit.JavascriptInterface
    public String startServer() {
        return startServerJson().toString();
    }

    @android.webkit.JavascriptInterface
    public String stopServer() {
        return stopServerJson().toString();
    }

    @android.webkit.JavascriptInterface
    public String serverLog() {
        return serverLog(60);
    }

    public String serverLog(int lines) {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", true);
            o.put("log", ServerManager.tailLog(Math.min(2000, Math.max(1, lines))));
        } catch (Exception e) {
            return error(e.getMessage()).toString();
        }
        return o.toString();
    }

    @android.webkit.JavascriptInterface
    public String templates() {
        return templatesJson().toString();
    }

    @android.webkit.JavascriptInterface
    public String mcpInfo() {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", true);
            o.put("running", isMcpRunning());
            o.put("port", mcpPort);
            o.put("token", mcpToken);
            o.put("ip", localIp());
            o.put("url", "http://" + localIp() + ":" + mcpPort + "/mcp");
        } catch (Exception e) {
            return error(e.getMessage()).toString();
        }
        return o.toString();
    }

    @android.webkit.JavascriptInterface
    public String restartMcp(String portText, String token) {
        try {
            int port = Integer.parseInt(portText.trim());
            if (port < 1024 || port > 65535) {
                return error("端口需在 1024-65535 之间").toString();
            }
            restartMcp(port, token == null ? "" : token.trim());
            return mcpInfo();
        } catch (Exception e) {
            return error("端口不合法: " + e.getMessage()).toString();
        }
    }

    @android.webkit.JavascriptInterface
    public String regenerateToken() {
        String token = randomToken();
        restartMcp(mcpPort, token);
        return mcpInfo();
    }

    @android.webkit.JavascriptInterface
    public String drainLogs() {
        return LogBus.drain();
    }

    @android.webkit.JavascriptInterface
    public String logs(int limit) {
        return LogBus.tail(limit);
    }

    @android.webkit.JavascriptInterface
    public void clearLogs() {
        LogBus.clear();
    }

    @android.webkit.JavascriptInterface
    public void copy(String text) {
        final String value = text == null ? "" : text;
        new Handler(Looper.getMainLooper()).post(new Runnable() {
            @Override
            public void run() {
                ClipboardManager cm = (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
                if (cm != null) {
                    cm.setPrimaryClip(ClipData.newPlainText("frida", value));
                }
            }
        });
    }

    @android.webkit.JavascriptInterface
    public String deviceInfo() {
        JSONObject o = new JSONObject();
        try {
            o.put("ok", true);
            o.put("device", Build.MANUFACTURER + " " + Build.MODEL);
            o.put("android", Build.VERSION.RELEASE + " (API " + Build.VERSION.SDK_INT + ")");
            o.put("abi", Build.SUPPORTED_ABIS.length > 0 ? Build.SUPPORTED_ABIS[0] : "?");
            o.put("root", isRooted());
            o.put("ip", localIp());
        } catch (Exception e) {
            return error(e.getMessage()).toString();
        }
        return o.toString();
    }

    public void shutdown() {
        synchronized (lock) {
            if (injector != null) {
                injector.detach();
                injector = null;
            }
        }
        stopMcp();
    }
}
