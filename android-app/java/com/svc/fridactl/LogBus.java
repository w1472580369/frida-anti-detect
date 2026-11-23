package com.svc.fridactl;

import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.Date;
import java.util.Deque;
import java.util.Locale;

/**
 * 极简全局日志总线：保留最近若干行供 MCP 查询，同时维护一个待取队列供界面轮询。
 */
public final class LogBus {

    private static final int MAX_HISTORY = 3000;
    private static final int MAX_PENDING = 800;
    private static final Deque<String> HISTORY = new ArrayDeque<>();
    private static final Deque<String> PENDING = new ArrayDeque<>();
    private static final Object LOCK = new Object();

    private LogBus() {
    }

    public static void add(String message) {
        String line;
        synchronized (LOCK) {
            line = new SimpleDateFormat("HH:mm:ss", Locale.US).format(new Date()) + "  " + message;
            HISTORY.addLast(line);
            while (HISTORY.size() > MAX_HISTORY) {
                HISTORY.removeFirst();
            }
            PENDING.addLast(line);
            while (PENDING.size() > MAX_PENDING) {
                PENDING.removeFirst();
            }
        }
    }

    public static void add(String tag, String message) {
        add("[" + tag + "] " + message);
    }

    /** 取出并清空待显示日志；界面每 500ms 轮询一次。 */
    public static String drain() {
        synchronized (LOCK) {
            if (PENDING.isEmpty()) {
                return "";
            }
            StringBuilder sb = new StringBuilder();
            for (String line : PENDING) {
                sb.append(line).append('\n');
            }
            PENDING.clear();
            return sb.toString();
        }
    }

    public static String tail(int limit) {
        if (limit <= 0) {
            limit = 200;
        }
        synchronized (LOCK) {
            int skip = Math.max(0, HISTORY.size() - limit);
            StringBuilder sb = new StringBuilder();
            int i = 0;
            for (String line : HISTORY) {
                if (i++ >= skip) {
                    sb.append(line).append('\n');
                }
            }
            return sb.toString();
        }
    }

    public static void clear() {
        synchronized (LOCK) {
            HISTORY.clear();
            PENDING.clear();
        }
    }
}
