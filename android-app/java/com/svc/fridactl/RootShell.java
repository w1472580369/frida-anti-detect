package com.svc.fridactl;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.concurrent.TimeUnit;

/**
 * root / shell 执行封装。所有需要 ptrace 的操作都必须走 su。
 */
public final class RootShell {

    public static final class Result {
        public final int code;
        public final String out;
        public final boolean ok;

        Result(int code, String out) {
            this.code = code;
            this.out = out == null ? "" : out.trim();
            this.ok = code == 0;
        }

        public boolean hasText() {
            return !out.isEmpty();
        }
    }

    private RootShell() {
    }

    public static boolean isRooted() {
        Result r = runRoot("id", 10000);
        return r.ok && r.out.contains("uid=0");
    }

    public static Result run(String command) {
        return exec(new String[]{"sh", "-c", command}, 20000);
    }

    public static Result runRoot(String command) {
        return runRoot(command, 40000);
    }

    public static Result runRoot(String command, int timeoutMs) {
        return exec(new String[]{"su", "-c", command}, timeoutMs);
    }

    /** 启动一个长驻 root 进程（frida-inject / frida-server）。 */
    public static Process startRoot(String command) throws IOException {
        return new ProcessBuilder("su", "-c", command)
                .redirectErrorStream(true)
                .start();
    }

    public static Result exec(String[] argv, int timeoutMs) {
        Process process = null;
        try {
            process = new ProcessBuilder(argv).redirectErrorStream(true).start();
            final StringBuilder output = new StringBuilder();
            final Process p = process;
            Thread reader = new Thread(new Runnable() {
                @Override
                public void run() {
                    try (BufferedReader br = new BufferedReader(new InputStreamReader(p.getInputStream()))) {
                        String line;
                        while ((line = br.readLine()) != null) {
                            output.append(line).append('\n');
                        }
                    } catch (IOException ignored) {
                    }
                }
            }, "shell-reader");
            reader.setDaemon(true);
            reader.start();

            boolean finished = process.waitFor(timeoutMs, TimeUnit.MILLISECONDS);
            if (!finished) {
                process.destroy();
                process.waitFor(2, TimeUnit.SECONDS);
                return new Result(-1, output + "\n(timeout)");
            }
            reader.join(1000);
            return new Result(process.exitValue(), output.toString());
        } catch (Exception e) {
            return new Result(-1, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (process != null) {
                process.destroy();
            }
        }
    }
}
