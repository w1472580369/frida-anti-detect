package com.svc.fridactl;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.Closeable;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 与目标进程内 bridge.js 的 TCP 控制通道。
 * 协议：一行一个 JSON，请求带 id/token/cmd，响应带同一个 id。
 */
public class BridgeClient implements Closeable {

    private final Socket socket;
    private final BufferedReader reader;
    private final BufferedWriter writer;
    private final String token;
    private final AtomicInteger seq = new AtomicInteger(1);
    private final Map<Integer, CompletableFuture<JSONObject>> pending = new ConcurrentHashMap<>();
    private final List<String> events = Collections.synchronizedList(new ArrayList<String>());
    private volatile boolean closed;

    private BridgeClient(Socket socket, String token) throws IOException {
        this.socket = socket;
        this.token = token;
        this.reader = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
        this.writer = new BufferedWriter(new OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8));
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                readLoop();
            }
        }, "bridge-reader");
        t.setDaemon(true);
        t.start();
    }

    public static BridgeClient connect(int port, String token, long timeoutMs) throws IOException {
        long deadline = System.currentTimeMillis() + timeoutMs;
        IOException last = null;
        while (System.currentTimeMillis() < deadline) {
            Socket s = new Socket();
            try {
                s.connect(new InetSocketAddress("127.0.0.1", port), 900);
                s.setTcpNoDelay(true);
                return new BridgeClient(s, token);
            } catch (IOException e) {
                last = e;
                try {
                    s.close();
                } catch (IOException ignored) {
                }
                try {
                    Thread.sleep(250);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }
        throw last != null ? last : new IOException("连接 bridge 超时");
    }

    private void readLoop() {
        try {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.trim().isEmpty()) {
                    continue;
                }
                JSONObject obj;
                try {
                    obj = new JSONObject(line);
                } catch (Exception e) {
                    LogBus.add("bridge", line);
                    continue;
                }
                if (obj.has("id")) {
                    CompletableFuture<JSONObject> f = pending.remove(obj.optInt("id"));
                    if (f != null) {
                        f.complete(obj);
                    }
                    continue;
                }
                if (obj.has("event")) {
                    events.add(line);
                    if (events.size() > 200) {
                        events.remove(0);
                    }
                    String event = obj.optString("event");
                    if ("log".equals(event)) {
                        Object payload = obj.opt("payload");
                        LogBus.add("target", payload == null || payload == JSONObject.NULL ? "" : String.valueOf(payload));
                    } else if ("ready".equals(event)) {
                        LogBus.add("bridge", "控制通道就绪，端口 " + obj.optInt("port"));
                    }
                }
            }
        } catch (IOException ignored) {
        } finally {
            closed = true;
            IOException err = new IOException("bridge 连接已断开");
            for (Integer id : pending.keySet()) {
                CompletableFuture<JSONObject> f = pending.remove(id);
                if (f != null) {
                    f.completeExceptionally(err);
                }
            }
        }
    }

    public boolean isAlive() {
        return !closed && socket.isConnected() && !socket.isClosed();
    }

    public JSONObject call(String cmd, JSONObject args, int timeoutMs) throws Exception {
        if (closed) {
            throw new IOException("bridge 连接已断开");
        }
        int id = seq.getAndIncrement();
        JSONObject req = new JSONObject();
        req.put("id", id);
        req.put("token", token);
        req.put("cmd", cmd);
        if (args != null) {
            Iterator<String> keys = args.keys();
            while (keys.hasNext()) {
                String k = keys.next();
                req.put(k, args.get(k));
            }
        }
        CompletableFuture<JSONObject> future = new CompletableFuture<>();
        pending.put(id, future);
        try {
            synchronized (writer) {
                writer.write(req.toString());
                writer.write("\n");
                writer.flush();
            }
            JSONObject resp = future.get(timeoutMs, TimeUnit.MILLISECONDS);
            if (!resp.optBoolean("ok", false)) {
                throw new IOException(resp.optString("error", "执行失败"));
            }
            return resp;
        } catch (Exception e) {
            pending.remove(id);
            throw e;
        }
    }

    public String eval(String code, int timeoutMs) throws Exception {
        JSONObject args = new JSONObject();
        args.put("code", code);
        JSONObject resp = call("eval", args, timeoutMs);
        Object result = resp.opt("result");
        if (result == null || result == JSONObject.NULL) {
            return "";
        }
        return String.valueOf(result);
    }

    public JSONArray rpcList() throws Exception {
        JSONObject resp = call("rpc_list", null, 10000);
        JSONArray arr = resp.optJSONArray("result");
        return arr == null ? new JSONArray() : arr;
    }

    public String rpcCall(String name, JSONArray args, int timeoutMs) throws Exception {
        JSONObject req = new JSONObject();
        req.put("name", name);
        req.put("args", args == null ? new JSONArray() : args);
        JSONObject resp = call("rpc_call", req, timeoutMs);
        Object result = resp.opt("result");
        if (result == null || result == JSONObject.NULL) {
            return "";
        }
        return String.valueOf(result);
    }

    public String drainEvents() {
        synchronized (events) {
            if (events.isEmpty()) {
                return "";
            }
            StringBuilder sb = new StringBuilder();
            for (String e : events) {
                sb.append(e).append('\n');
            }
            events.clear();
            return sb.toString();
        }
    }

    @Override
    public void close() {
        closed = true;
        try {
            socket.close();
        } catch (IOException ignored) {
        }
    }
}
