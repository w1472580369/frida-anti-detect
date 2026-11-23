'use strict';

/*
 * Frida Phone bridge
 * 由 App 在注入前替换 __PORT__ / __TOKEN__。
 * 在目标进程内监听 127.0.0.1:PORT，按行收发 JSON：
 *   {id, token, cmd:"eval"|"rpc_list"|"rpc_call"|"ping", ...}
 * 同时把 send() / console.log 广播给所有已连接客户端。
 */

const PORT = __PORT__;
const TOKEN = "__TOKEN__";
const clients = [];

function utf8Encode(str) {
    const out = [];
    for (let i = 0; i < str.length; i++) {
        let c = str.charCodeAt(i);
        if (c < 0x80) {
            out.push(c);
        } else if (c < 0x800) {
            out.push(0xC0 | (c >> 6), 0x80 | (c & 0x3F));
        } else if (c >= 0xD800 && c <= 0xDBFF) {
            const c2 = str.charCodeAt(++i);
            const cp = 0x10000 + ((c - 0xD800) << 10) + (c2 - 0xDC00);
            out.push(0xF0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3F),
                0x80 | ((cp >> 6) & 0x3F), 0x80 | (cp & 0x3F));
        } else {
            out.push(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 0x3F), 0x80 | (c & 0x3F));
        }
    }
    return new Uint8Array(out);
}

function utf8Decode(bytes) {
    let s = "";
    for (let i = 0; i < bytes.length;) {
        const b = bytes[i++];
        if (b < 0x80) {
            s += String.fromCharCode(b);
        } else if (b < 0xE0) {
            s += String.fromCharCode(((b & 0x1F) << 6) | (bytes[i++] & 0x3F));
        } else if (b < 0xF0) {
            s += String.fromCharCode(((b & 0x0F) << 12) | ((bytes[i++] & 0x3F) << 6) | (bytes[i++] & 0x3F));
        } else {
            const cp = ((b & 0x07) << 18) | ((bytes[i++] & 0x3F) << 12)
                | ((bytes[i++] & 0x3F) << 6) | (bytes[i++] & 0x3F);
            const v = cp - 0x10000;
            s += String.fromCharCode(0xD800 + (v >> 10), 0xDC00 + (v & 0x3FF));
        }
    }
    return s;
}

/* Frida 的 SocketConnection.output 同一时刻只允许一个写操作，
   所有写入串行化，避免 "stream has outstanding operation"。 */
function queueWrite(conn, bytes) {
    const prev = conn.__writeQueue || Promise.resolve();
    conn.__writeQueue = prev.then(function () {
        return conn.output.writeAll(bytes);
    }).catch(function () {
    });
    return conn.__writeQueue;
}

function broadcast(obj) {
    let line;
    try {
        line = JSON.stringify(obj) + "\n";
    } catch (e) {
        line = JSON.stringify({ event: "log", payload: String(obj) }) + "\n";
    }
    const bytes = utf8Encode(line).buffer;
    for (let i = clients.length - 1; i >= 0; i--) {
        try {
            queueWrite(clients[i], bytes);
        } catch (e) {
            clients.splice(i, 1);
        }
    }
}

/* Frida 17 的 send 是只读全局，无法在脚本里改写；send() 的输出会由注入器 stdout 带回 App 日志。
   console.log 可以改写，这里额外广播一份给已连接的客户端。 */

try {
    const origLog = console.log;
    console.log = function () {
        const args = Array.prototype.slice.call(arguments);
        const text = args.map(function (a) {
            if (typeof a === "string") return a;
            try { return JSON.stringify(a); } catch (e) { return String(a); }
        }).join(" ");
        broadcast({ event: "log", payload: text });
        try { origLog.apply(console, args); } catch (e) { }
    };
} catch (e) {
}

async function handle(conn) {
    clients.push(conn);
    broadcast({ event: "clients", count: clients.length });
    let pending = new Uint8Array(0);
    try {
        while (true) {
            const chunk = await conn.input.read(4096);
            if (!chunk || chunk.byteLength === 0) {
                break;
            }
            /* 按字节缓冲，避免多字节 UTF-8 字符被 TCP 分片截断 */
            const next = new Uint8Array(chunk);
            const merged = new Uint8Array(pending.length + next.length);
            merged.set(pending, 0);
            merged.set(next, pending.length);
            pending = merged;
            let idx;
            while ((idx = pending.indexOf(10)) >= 0) {
                const line = utf8Decode(pending.slice(0, idx));
                pending = pending.slice(idx + 1);
                if (!line.trim()) continue;

                let req;
                try {
                    req = JSON.parse(line);
                } catch (e) {
                    continue;
                }
                if (req.token !== TOKEN) {
                    const denied = JSON.stringify({ id: req.id, ok: false, error: "token 不匹配" }) + "\n";
                    await queueWrite(conn, utf8Encode(denied).buffer);
                    continue;
                }

                const resp = { id: req.id, ok: true };
                try {
                    if (req.cmd === "ping") {
                        resp.result = "pong";
                    } else if (req.cmd === "eval") {
                        let r = (0, eval)(req.code);
                        if (r && typeof r.then === "function") r = await r;
                        resp.result = (r === undefined) ? null : String(r);
                    } else if (req.cmd === "rpc_list") {
                        resp.result = Object.keys(rpc.exports || {});
                    } else if (req.cmd === "rpc_call") {
                        const fn = (rpc.exports || {})[req.name];
                        if (typeof fn !== "function") {
                            throw new Error("没有该 RPC 导出: " + req.name);
                        }
                        let r = fn.apply(null, req.args || []);
                        if (r && typeof r.then === "function") r = await r;
                        if (r === undefined || r === null) {
                            resp.result = null;
                        } else if (typeof r === "object") {
                            try { resp.result = JSON.stringify(r); } catch (e) { resp.result = String(r); }
                        } else {
                            resp.result = String(r);
                        }
                    } else {
                        throw new Error("未知命令: " + req.cmd);
                    }
                } catch (e) {
                    resp.ok = false;
                    resp.error = String((e && e.stack) || e);
                }
                await queueWrite(conn, utf8Encode(JSON.stringify(resp) + "\n").buffer);
            }
        }
    } catch (e) {
        /* 连接断开 */
    }
    const i = clients.indexOf(conn);
    if (i >= 0) clients.splice(i, 1);
}

(async function () {
    const listener = await Socket.listen({ family: "ipv4", host: "127.0.0.1", port: PORT });
    broadcast({ event: "ready", port: PORT });
    while (true) {
        try {
            const conn = await listener.accept();
            handle(conn);
        } catch (e) {
            await new Promise(function (resolve) { setTimeout(resolve, 300); });
        }
    }
})();
