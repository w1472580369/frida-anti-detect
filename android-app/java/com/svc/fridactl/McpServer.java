package com.svc.fridactl;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * 极简 MCP Server（Streamable HTTP / JSON-RPC 2.0），不依赖任何第三方库。
 * 端点：POST /mcp   健康检查：GET /health
 * 鉴权：Authorization: Bearer &lt;token&gt; 或 ?token=&lt;token&gt;
 */
public class McpServer {

    private final AppCore core;
    private final int port;
    private final String token;
    private final String sessionId = UUID.randomUUID().toString();

    private ServerSocket serverSocket;
    private Thread acceptThread;
    private volatile boolean running;

    public McpServer(AppCore core, int port, String token) {
        this.core = core;
        this.port = port;
        this.token = token;
    }

    public boolean isRunning() {
        return running;
    }

    public synchronized void start() throws IOException {
        serverSocket = new ServerSocket();
        serverSocket.setReuseAddress(true);
        serverSocket.bind(new InetSocketAddress("0.0.0.0", port));
        running = true;
        acceptThread = new Thread(new Runnable() {
            @Override
            public void run() {
                acceptLoop();
            }
        }, "mcp-accept");
        acceptThread.setDaemon(true);
        acceptThread.start();
    }

    public synchronized void stop() {
        running = false;
        try {
            if (serverSocket != null) {
                serverSocket.close();
            }
        } catch (IOException ignored) {
        }
        serverSocket = null;
    }

    private void acceptLoop() {
        while (running) {
            try {
                final Socket socket = serverSocket.accept();
                Thread t = new Thread(new Runnable() {
                    @Override
                    public void run() {
                        handle(socket);
                    }
                }, "mcp-conn");
                t.setDaemon(true);
                t.start();
            } catch (IOException e) {
                if (running) {
                    LogBus.add("mcp", "accept 失败: " + e.getMessage());
                }
            }
        }
    }

    private void handle(Socket socket) {
        try (Socket s = socket) {
            s.setSoTimeout(60000);
            InputStream in = new BufferedInputStream(s.getInputStream());
            OutputStream out = new BufferedOutputStream(s.getOutputStream());

            String requestLine = readLine(in);
            if (requestLine == null || requestLine.trim().isEmpty()) {
                return;
            }
            String[] parts = requestLine.split(" ");
            if (parts.length < 2) {
                respond(out, 400, "application/json", "{\"error\":\"bad request\"}");
                return;
            }
            String method = parts[0].toUpperCase(Locale.US);
            String target = parts[1];
            String path = target;
            String query = "";
            int qi = target.indexOf('?');
            if (qi >= 0) {
                path = target.substring(0, qi);
                query = target.substring(qi + 1);
            }

            Map<String, String> headers = new LinkedHashMap<>();
            String line;
            while ((line = readLine(in)) != null && !line.isEmpty()) {
                int ci = line.indexOf(':');
                if (ci > 0) {
                    headers.put(line.substring(0, ci).trim().toLowerCase(Locale.US), line.substring(ci + 1).trim());
                }
            }

            int contentLength = 0;
            try {
                contentLength = Integer.parseInt(headers.containsKey("content-length")
                        ? headers.get("content-length") : "0");
            } catch (NumberFormatException ignored) {
            }
            if (contentLength > 8 * 1024 * 1024) {
                respond(out, 413, "application/json", "{\"error\":\"body too large\"}");
                return;
            }
            byte[] body = new byte[Math.max(0, contentLength)];
            int offset = 0;
            while (offset < body.length) {
                int n = in.read(body, offset, body.length - offset);
                if (n < 0) {
                    break;
                }
                offset += n;
            }

            if ("OPTIONS".equals(method)) {
                respond(out, 204, "text/plain", "");
                return;
            }

            if ("GET".equals(method)) {
                if ("/health".equals(path)) {
                    JSONObject o = new JSONObject();
                    try {
                        o.put("ok", true);
                        o.put("running", running);
                        o.put("server", "frida-phone-mcp");
                    } catch (Exception ignored) {
                    }
                    respond(out, 200, "application/json", o.toString());
                    return;
                }
                if ("/".equals(path)) {
                    JSONObject o = new JSONObject();
                    try {
                        o.put("name", "frida-phone-mcp");
                        o.put("endpoint", "/mcp");
                        o.put("transport", "streamable-http");
                    } catch (Exception ignored) {
                    }
                    respond(out, 200, "application/json", o.toString());
                    return;
                }
                if ("/mcp".equals(path)) {
                    respond(out, 405, "application/json", "{\"error\":\"method not allowed; use POST /mcp\"}");
                    return;
                }
                respond(out, 404, "application/json", "{\"error\":\"not found\"}");
                return;
            }

            if (!"POST".equals(method)) {
                respond(out, 405, "application/json", "{\"error\":\"method not allowed\"}");
                return;
            }
            if (!"/mcp".equals(path) && !"/".equals(path) && !"/messages".equals(path)) {
                respond(out, 404, "application/json", "{\"error\":\"not found\"}");
                return;
            }
            if (!authorized(headers, query)) {
                respond(out, 401, "application/json", "{\"error\":\"unauthorized\"}");
                return;
            }

            String payload = new String(body, StandardCharsets.UTF_8);
            String response = rpc(payload);
            if (response == null) {
                respond(out, 202, "application/json", "");
            } else {
                respond(out, 200, "application/json", response);
            }
        } catch (Exception e) {
            LogBus.add("mcp", "请求异常: " + e);
        }
    }

    private boolean authorized(Map<String, String> headers, String query) {
        if (token == null || token.isEmpty()) {
            return true;
        }
        String auth = headers.get("authorization");
        if (auth != null && auth.regionMatches(true, 0, "Bearer ", 0, 7)) {
            if (auth.substring(7).trim().equals(token)) {
                return true;
            }
        }
        if (query != null && !query.isEmpty()) {
            for (String pair : query.split("&")) {
                int eq = pair.indexOf('=');
                if (eq > 0 && "token".equals(pair.substring(0, eq))) {
                    try {
                        if (URLDecoder.decode(pair.substring(eq + 1), "UTF-8").equals(token)) {
                            return true;
                        }
                    } catch (Exception ignored) {
                    }
                }
            }
        }
        return false;
    }

    // ------------------------------------------------------------ JSON-RPC

    private String rpc(String payload) {
        if (payload == null || payload.trim().isEmpty()) {
            return errorResponse(null, -32700, "Parse error");
        }
        String text = payload.trim();
        try {
            if (text.startsWith("[")) {
                JSONArray batch = new JSONArray(text);
                JSONArray out = new JSONArray();
                for (int i = 0; i < batch.length(); i++) {
                    JSONObject req = batch.optJSONObject(i);
                    if (req == null) {
                        continue;
                    }
                    String one = rpcOne(req);
                    if (one != null) {
                        out.put(new JSONObject(one));
                    }
                }
                return out.length() == 0 ? null : out.toString();
            }
            return rpcOne(new JSONObject(text));
        } catch (Exception e) {
            return errorResponse(null, -32700, "Parse error: " + e.getMessage());
        }
    }

    private String rpcOne(JSONObject req) {
        Object id = req.has("id") ? req.opt("id") : null;
        String method = req.optString("method", "");
        JSONObject params = req.optJSONObject("params");
        if (params == null) {
            params = new JSONObject();
        }
        try {
            Object result;
            if ("initialize".equals(method)) {
                result = initialize(params);
            } else if ("notifications/initialized".equals(method)
                    || "notifications/cancelled".equals(method)) {
                return null;
            } else if ("ping".equals(method)) {
                result = new JSONObject();
            } else if ("tools/list".equals(method)) {
                result = toolsList();
            } else if ("tools/call".equals(method)) {
                result = toolsCall(params);
            } else if ("resources/list".equals(method)) {
                result = new JSONObject().put("resources", new JSONArray());
            } else if ("prompts/list".equals(method)) {
                result = new JSONObject().put("prompts", new JSONArray());
            } else {
                return errorResponse(id, -32601, "Method not found: " + method);
            }

            JSONObject resp = new JSONObject();
            resp.put("jsonrpc", "2.0");
            if (id != null && id != JSONObject.NULL) {
                resp.put("id", id);
            }
            resp.put("result", result);
            return resp.toString();
        } catch (Exception e) {
            return errorResponse(id, -32603, "Internal error: " + e.getMessage());
        }
    }

    private JSONObject initialize(JSONObject params) throws Exception {
        String version = params.optString("protocolVersion", "2024-11-05");
        if (!"2024-11-05".equals(version) && !"2024-10-07".equals(version)) {
            version = "2024-11-05";
        }
        JSONObject result = new JSONObject();
        result.put("protocolVersion", version);
        result.put("capabilities", new JSONObject().put("tools", new JSONObject().put("listChanged", false)));
        result.put("serverInfo", new JSONObject().put("name", "frida-phone").put("version", "1.2.0"));
        result.put("instructions",
                "Android 端 Frida 控制服务（APK 内置 patched frida-inject 17.19.0，仅 arm64，已修 Android 12/MIUI systemMain 兼容）。"
                        + "注入需要 root：先调用 frida_attach(pid) 或 frida_launch_app(package)，"
                        + "再用 frida_eval 执行 JS，或用 frida_rpc_list / frida_rpc_call 调用脚本导出。"
                        + "frida_start_server 可启动随 APK 打包的兼容版 frida-server（端口 20442，保留 re.frida D-Bus 协议名，官方 frida-tools 可直接连接）。"
                        + "第一次使用建议先调用 frida_get_guide，获取端口、路径和 PC 命令。");
        return result;
    }

    private JSONObject toolsList() throws Exception {
        JSONArray tools = new JSONArray();

        tools.put(tool("frida_status",
                "查看设备 root 状态、当前附加会话、frida-server 与 MCP 服务状态；injector 字段为 patched-17.19.0-r4-miui-libcshim，server_mode 为 compat。",
                new JSONObject()));

        tools.put(tool("frida_get_guide",
                "获取 App 内说明：实际端口、兼容版 server 与 patched injector 的命名差异、文件路径、PC frida-tools 命令、MCP curl 示例。"
                        + "兼容版 server 保留 re.frida 协议名，官方客户端可直接连；injector 内部使用 app.svc。AI 第一次操作前应先调用本工具。",
                new JSONObject()));

        tools.put(tool("frida_device_info",
                "查看设备型号、Android 版本、ABI、root 状态和局域网 IP。",
                new JSONObject()));

        tools.put(tool("frida_list_apps",
                "列出已安装的第三方应用包名（pm list packages -3）。",
                new JSONObject()));

        tools.put(tool("frida_recheck_root",
                "重新检测 root 权限并返回最新状态（不会重启注入器）。",
                new JSONObject()));

        tools.put(tool("frida_server_log",
                "读取兼容版 frida-server 的日志（/data/local/tmp/.svc-server.log）。",
                props(p("lines", "integer", "可选，返回行数，默认 60，最大 2000"))));

        tools.put(tool("frida_clear_logs",
                "清空 App 的运行日志缓冲区（不影响 server 日志文件）。",
                new JSONObject()));

        tools.put(tool("frida_mcp_info",
                "查看 MCP 服务地址、端口、令牌和运行状态。",
                new JSONObject()));

        tools.put(tool("frida_run_template",
                "获取内置脚本模板并立即在已附加进程中执行（等价于 get_template + eval）。",
                props(p("name", "string", "模板名称"),
                        p("timeout_ms", "integer", "可选，超时毫秒，默认 30000")), "name"));

        tools.put(tool("frida_list_processes",
                "列出 Android 进程（PID 与进程名），可按关键字过滤。",
                props(p("filter", "string", "可选，进程名/包名关键字"))));

        tools.put(tool("frida_attach",
                "附加到指定 PID 的目标进程（需要 root）。成功后可用 frida_eval 执行 JS。",
                props(p("pid", "integer", "目标进程 PID")), "pid"));

        tools.put(tool("frida_detach",
                "断开当前附加会话。",
                new JSONObject()));

        tools.put(tool("frida_eval",
                "在已附加的目标进程中执行一段 Frida JavaScript，返回表达式结果；send()/console.log 输出会进入日志。",
                props(p("code", "string", "要执行的 JavaScript"),
                        p("timeout_ms", "integer", "可选，超时毫秒，默认 30000")), "code"));

        tools.put(tool("frida_rpc_list",
                "列出目标脚本通过 rpc.exports 暴露的方法名。",
                new JSONObject()));

        tools.put(tool("frida_rpc_call",
                "调用目标脚本的 rpc.exports 方法。",
                props(p("name", "string", "RPC 方法名"),
                        p("args", "array", "参数数组，默认 []"),
                        p("timeout_ms", "integer", "可选，超时毫秒，默认 30000")), "name"));

        tools.put(tool("frida_list_templates",
                "列出内置的常用 Frida 脚本模板（名称、分类、说明）。",
                new JSONObject()));

        tools.put(tool("frida_get_template",
                "按名称获取一个脚本模板的完整 JS 源码。",
                props(p("name", "string", "模板名称")), "name"));

        tools.put(tool("frida_start_server",
                "启动随 APK 打包的兼容版 frida-server（监听 0.0.0.0:20442，保留 re.frida D-Bus 协议名），官方 frida-tools 可直接连接。",
                new JSONObject()));

        tools.put(tool("frida_stop_server",
                "停止 frida-server。",
                new JSONObject()));

        tools.put(tool("frida_restart_mcp",
                "延迟重启 MCP 服务（可改端口/令牌）。会短暂断开当前连接；默认延迟 1500ms 先让本次响应返回。",
                props(p("port", "integer", "可选，新端口 1024-65535；省略保持当前端口"),
                        p("token", "string", "可选，新令牌；省略保持当前令牌"),
                        p("delay_ms", "integer", "可选，延迟毫秒，默认 1500"))));

        tools.put(tool("frida_regenerate_token",
                "生成新的 MCP 令牌并延迟重启服务。旧令牌立即失效，返回结果中包含新令牌，调用方需立即更新配置。",
                props(p("delay_ms", "integer", "可选，延迟毫秒，默认 1500"))));

        tools.put(tool("frida_launch_app",
                "按包名启动应用，等待进程出现后自动附加。",
                props(p("package", "string", "Android 包名，如 com.example.app")), "package"));

        tools.put(tool("frida_get_logs",
                "读取最近的运行日志（注入器输出、send()、console.log、MCP 事件）。",
                props(p("limit", "integer", "可选，返回行数，默认 200"))));

        tools.put(tool("frida_drain_logs",
                "取出并清空尚未读取的增量日志。",
                new JSONObject()));

        JSONObject result = new JSONObject();
        result.put("tools", tools);
        return result;
    }

    private JSONObject toolsCall(JSONObject params) throws Exception {
        String name = params.optString("name", "");
        JSONObject args = params.optJSONObject("arguments");
        if (args == null) {
            args = new JSONObject();
        }

        String text;
        boolean isError = false;
        try {
            if ("frida_status".equals(name)) {
                JSONObject o = core.statusJson();
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_get_guide".equals(name)) {
                JSONObject o = new JSONObject(core.guide());
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_device_info".equals(name)) {
                JSONObject o = new JSONObject(core.deviceInfo());
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_list_apps".equals(name)) {
                JSONObject o = new JSONObject(core.listApps());
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_recheck_root".equals(name)) {
                JSONObject o = new JSONObject(core.recheckRoot());
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_server_log".equals(name)) {
                int lines = Math.min(2000, args.optInt("lines", 60));
                JSONObject o = new JSONObject(core.serverLog(lines));
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_clear_logs".equals(name)) {
                core.clearLogs();
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("message", "App 日志缓冲区已清空");
                text = o.toString(2);
            } else if ("frida_mcp_info".equals(name)) {
                JSONObject o = new JSONObject(core.mcpInfo());
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_run_template".equals(name)) {
                String templateName = args.optString("name", "");
                JSONObject t = core.templateJson(templateName);
                if (!t.optBoolean("ok", true)) {
                    text = t.toString(2);
                    isError = true;
                } else {
                    JSONObject tpl = t.optJSONObject("template");
                    String code = tpl == null ? "" : tpl.optString("code", "");
                    if (code.isEmpty()) {
                        text = "{\"ok\":false,\"error\":\"模板没有 code 字段\"}";
                        isError = true;
                    } else {
                        int timeout = Math.min(120000, args.optInt("timeout_ms", 30000));
                        JSONObject o = core.evalJson(code, timeout);
                        o.put("template", templateName);
                        text = o.toString(2);
                        isError = !o.optBoolean("ok", true);
                    }
                }
            } else if ("frida_restart_mcp".equals(name)) {
                int newPort = args.optInt("port", -1);
                if (newPort > 0 && (newPort < 1024 || newPort > 65535)) {
                    text = "{\"ok\":false,\"error\":\"端口需在 1024-65535 之间\"}";
                    isError = true;
                } else {
                    int delay = Math.max(300, Math.min(30000, args.optInt("delay_ms", 1500)));
                    String newToken = args.optString("token", "");
                    core.scheduleRestartMcp(newPort, newToken, delay);
                    JSONObject o = new JSONObject();
                    o.put("ok", true);
                    o.put("scheduled", true);
                    o.put("port", newPort > 0 ? newPort : core.mcpPort());
                    o.put("token_changed", newToken != null && !newToken.isEmpty());
                    if (newToken != null && !newToken.isEmpty()) {
                        o.put("token", newToken);
                    }
                    o.put("delay_ms", delay);
                    o.put("note", "MCP 将在延迟后重启；当前连接可能断开，请按新端口/令牌重连。");
                    text = o.toString(2);
                }
            } else if ("frida_regenerate_token".equals(name)) {
                int delay = Math.max(300, Math.min(30000, args.optInt("delay_ms", 1500)));
                JSONObject o = core.scheduleRegenerateToken(delay);
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_list_processes".equals(name)) {
                JSONArray arr = core.processesJson(args.optString("filter", ""));
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("count", arr.length());
                o.put("processes", arr);
                text = o.toString(2);
            } else if ("frida_attach".equals(name)) {
                int pid = args.optInt("pid", -1);
                if (pid <= 0) {
                    text = "{\"ok\":false,\"error\":\"pid 必须为正整数\"}";
                    isError = true;
                } else {
                    JSONObject o = core.attachJson(pid);
                    text = o.toString(2);
                    isError = !o.optBoolean("ok", true);
                }
            } else if ("frida_detach".equals(name)) {
                JSONObject o = core.detachJson();
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_eval".equals(name)) {
                String code = args.optString("code", "");
                if (code.isEmpty()) {
                    text = "{\"ok\":false,\"error\":\"code 不能为空\"}";
                    isError = true;
                } else {
                    int timeout = Math.min(120000, args.optInt("timeout_ms", 30000));
                    JSONObject o = core.evalJson(code, timeout);
                    text = o.toString(2);
                    isError = !o.optBoolean("ok", true);
                }
            } else if ("frida_rpc_list".equals(name)) {
                JSONObject o = core.rpcListJson();
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_rpc_call".equals(name)) {
                String rpcName = args.optString("name", "");
                JSONArray rpcArgs = args.optJSONArray("args");
                int timeout = Math.min(120000, args.optInt("timeout_ms", 30000));
                JSONObject o = core.rpcCallJson(rpcName, rpcArgs, timeout);
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_list_templates".equals(name)) {
                JSONObject o = core.templatesJson();
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_get_template".equals(name)) {
                JSONObject o = core.templateJson(args.optString("name", ""));
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_start_server".equals(name)) {
                JSONObject o = core.startServerJson();
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_stop_server".equals(name)) {
                JSONObject o = core.stopServerJson();
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_launch_app".equals(name)) {
                JSONObject o = core.launchJson(args.optString("package", ""));
                text = o.toString(2);
                isError = !o.optBoolean("ok", true);
            } else if ("frida_get_logs".equals(name)) {
                int limit = Math.min(2000, args.optInt("limit", 200));
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("logs", core.logs(limit));
                text = o.toString(2);
            } else if ("frida_drain_logs".equals(name)) {
                String drained = core.drainLogs();
                JSONObject o = new JSONObject();
                o.put("ok", true);
                o.put("logs", drained.isEmpty() ? "(无新日志)" : drained);
                text = o.toString(2);
            } else {
                text = "{\"ok\":false,\"error\":\"未知工具: " + name + "\"}";
                isError = true;
            }
        } catch (Exception e) {
            text = "{\"ok\":false,\"error\":\"" + escape(String.valueOf(e.getMessage())) + "\"}";
            isError = true;
        }

        JSONObject result = new JSONObject();
        JSONArray content = new JSONArray();
        content.put(new JSONObject().put("type", "text").put("text", text));
        result.put("content", content);
        result.put("isError", isError);
        return result;
    }

    // ------------------------------------------------------------ helpers

    private static JSONObject tool(String name, String description, JSONObject properties, String... required)
            throws Exception {
        JSONObject schema = new JSONObject();
        schema.put("type", "object");
        schema.put("properties", properties);
        if (required.length > 0) {
            JSONArray req = new JSONArray();
            for (String r : required) {
                if (properties.has(r)) {
                    req.put(r);
                }
            }
            if (req.length() > 0) {
                schema.put("required", req);
            }
        }
        JSONObject tool = new JSONObject();
        tool.put("name", name);
        tool.put("description", description);
        tool.put("inputSchema", schema);
        return tool;
    }

    private static JSONObject props(JSONObject... items) {
        JSONObject o = new JSONObject();
        for (JSONObject item : items) {
            try {
                String name = item.getString("__name");
                item.remove("__name");
                o.put(name, item);
            } catch (Exception ignored) {
            }
        }
        return o;
    }

    private static JSONObject p(String name, String type, String description) {
        JSONObject o = new JSONObject();
        try {
            o.put("__name", name);
            o.put("type", type);
            o.put("description", description);
        } catch (Exception ignored) {
        }
        return o;
    }

    private static String errorResponse(Object id, int code, String message) {
        JSONObject resp = new JSONObject();
        try {
            resp.put("jsonrpc", "2.0");
            resp.put("id", id == null ? JSONObject.NULL : id);
            resp.put("error", new JSONObject().put("code", code).put("message", message));
        } catch (Exception ignored) {
        }
        return resp.toString();
    }

    private static String escape(String s) {
        if (s == null) {
            return "";
        }
        return s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n");
    }

    private static String readLine(InputStream in) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        int b;
        boolean any = false;
        while ((b = in.read()) != -1) {
            any = true;
            if (b == '\n') {
                break;
            }
            if (b != '\r') {
                bos.write(b);
            }
        }
        if (!any && bos.size() == 0) {
            return null;
        }
        return new String(bos.toByteArray(), StandardCharsets.UTF_8);
    }

    private void respond(OutputStream out, int code, String contentType, String body) throws IOException {
        byte[] bytes = body == null ? new byte[0] : body.getBytes(StandardCharsets.UTF_8);
        StringBuilder h = new StringBuilder();
        h.append("HTTP/1.1 ").append(code).append(' ').append(reason(code)).append("\r\n");
        if (bytes.length > 0) {
            h.append("Content-Type: ").append(contentType).append("\r\n");
        }
        h.append("Content-Length: ").append(bytes.length).append("\r\n");
        h.append("Connection: close\r\n");
        h.append("Access-Control-Allow-Origin: *\r\n");
        h.append("Access-Control-Allow-Headers: content-type, authorization, mcp-session-id\r\n");
        h.append("Access-Control-Allow-Methods: POST, GET, OPTIONS\r\n");
        h.append("Access-Control-Expose-Headers: Mcp-Session-Id\r\n");
        h.append("Mcp-Session-Id: ").append(sessionId).append("\r\n");
        if (code == 401) {
            h.append("WWW-Authenticate: Bearer\r\n");
        }
        if (code == 405) {
            h.append("Allow: POST, OPTIONS\r\n");
        }
        h.append("\r\n");
        out.write(h.toString().getBytes(StandardCharsets.US_ASCII));
        out.write(bytes);
        out.flush();
    }

    private static String reason(int code) {
        switch (code) {
            case 200:
                return "OK";
            case 202:
                return "Accepted";
            case 204:
                return "No Content";
            case 400:
                return "Bad Request";
            case 401:
                return "Unauthorized";
            case 404:
                return "Not Found";
            case 405:
                return "Method Not Allowed";
            case 413:
                return "Payload Too Large";
            default:
                return "OK";
        }
    }
}
