package com.svc.fridactl;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

/**
 * 通过 root shell 枚举进程。优先使用 toybox 的 ps -A -o PID,NAME，失败时退回 ps -A 解析。
 */
public final class ProcessScanner {

    public static final class Proc {
        public final int pid;
        public final String name;

        Proc(int pid, String name) {
            this.pid = pid;
            this.name = name;
        }
    }

    private ProcessScanner() {
    }

    public static List<Proc> list() {
        RootShell.Result r = RootShell.runRoot("ps -A -o PID,NAME");
        if (!r.ok || r.out.isEmpty()) {
            r = RootShell.run("ps -A -o PID,NAME");
        }
        List<Proc> out = parseColumns(r.out);
        if (out.isEmpty()) {
            r = RootShell.runRoot("ps -A");
            if (!r.ok || r.out.isEmpty()) {
                r = RootShell.run("ps -A");
            }
            out = parseLegacy(r.out);
        }
        Collections.sort(out, new Comparator<Proc>() {
            @Override
            public int compare(Proc a, Proc b) {
                return a.name.compareToIgnoreCase(b.name);
            }
        });
        return out;
    }

    private static List<Proc> parseColumns(String text) {
        List<Proc> out = new ArrayList<>();
        if (text == null) {
            return out;
        }
        String[] lines = text.split("\n");
        for (String line : lines) {
            line = line.trim();
            if (line.isEmpty()) {
                continue;
            }
            String[] parts = line.split("\\s+");
            if (parts.length < 2) {
                continue;
            }
            if ("PID".equalsIgnoreCase(parts[0])) {
                continue;
            }
            try {
                int pid = Integer.parseInt(parts[0]);
                if (pid <= 0) {
                    continue;
                }
                String name = parts[1];
                if (name.startsWith("[") || "NAME".equalsIgnoreCase(name)) {
                    continue;
                }
                out.add(new Proc(pid, name));
            } catch (NumberFormatException ignored) {
            }
        }
        return out;
    }

    private static List<Proc> parseLegacy(String text) {
        List<Proc> out = new ArrayList<>();
        if (text == null) {
            return out;
        }
        for (String line : text.split("\n")) {
            line = line.trim();
            if (line.isEmpty() || line.startsWith("USER")) {
                continue;
            }
            String[] parts = line.split("\\s+");
            if (parts.length < 9) {
                continue;
            }
            try {
                int pid = Integer.parseInt(parts[1]);
                String name = parts[parts.length - 1];
                if (pid <= 0 || name.startsWith("[")) {
                    continue;
                }
                out.add(new Proc(pid, name));
            } catch (NumberFormatException ignored) {
            }
        }
        return out;
    }

    public static int pidOf(String processName) {
        if (processName == null || processName.isEmpty()) {
            return -1;
        }
        RootShell.Result r = RootShell.runRoot("pidof " + processName);
        if (r.ok && r.hasText()) {
            for (String token : r.out.split("\\s+")) {
                try {
                    int pid = Integer.parseInt(token.trim());
                    if (pid > 0) {
                        return pid;
                    }
                } catch (NumberFormatException ignored) {
                }
            }
        }
        for (Proc p : list()) {
            if (p.name.equals(processName)) {
                return p.pid;
            }
        }
        return -1;
    }
}
