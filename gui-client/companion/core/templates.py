"""常用 Frida JS 脚本模板库。

每条模板: (分类, 名称, 一句话说明, JS 源码)
按分类展示在下拉框，插入编辑器后可直接运行。
"""
from __future__ import annotations

from typing import List, Tuple

Template = Tuple[str, str, str, str]

TEMPLATES: List[Template] = [
    # ---------------- 基础信息 ----------------
    ("基础信息", "进程与架构", "打印 PID、架构与加载模块数",
     r"""send("[*] PID = " + Process.id);
send("[*] arch = " + Process.arch);
send("[*] platform = " + Process.platform);
send("[*] 模块数 = " + Process.enumerateModules().length);
send("[*] 当前库基址 = " + Module.getBaseAddress(Process.enumerateModules()[0].name));"""),

    ("基础信息", "主模块导出(前80)", "列出主模块前 80 个导出符号",
     r"""var mod = Process.enumerateModules()[0];
mod.enumerateExports().slice(0, 80).forEach(function (e) {
    send(e.type + " " + e.name + " @ " + e.address);
});"""),

    # ---------------- Native Hook ----------------
    ("Native Hook", "按符号拦截函数", "通过导出符号定位并 Hook，打印参数/返回值",
     r"""var target = Module.getExportByName(null, "getprop") || Module.getExportByName("libc.so", "getprop");
if (!target) { send("[-] 找不到该符号"); } else {
    send("[+] 目标 = " + target);
    Interceptor.attach(target, {
        onEnter(args) { send("[>] 进入: " + args[0]); },
        onLeave(retval) { send("[<] 返回: " + retval); }
    });
}"""),

    ("Native Hook", "基址+偏移拦截", "按模块基址+偏移定位函数并 Hook",
     r"""var base = Module.getBaseAddress("libexample.so");
var target = base.add(0x12345);
send("[+] hook @ " + target);
Interceptor.attach(target, {
    onEnter(args) {
        this.a0 = args[0];
        send("[>] a0 = " + args[0].toInt32());
    },
    onLeave(retval) { send("[<] 返回 = " + retval.toInt32()); }
});"""),

    ("Native Hook", "参数 hexdump 追踪", "打印调用栈与参数内存 hexdump，适合逆向分析",
     r"""var dump = function (x, n) {
    try { return hexdump(x, {length: Math.min(n || 32, 64)}); }
    catch (e) { return "(读取失败)"; }
};
Interceptor.attach(Module.getExportByName(null, "strlen"), {
    onEnter(args) {
        send(Thread.backtrace(this.context, Backtracer.ACCURATE)
            .map(DebugSymbol.fromAddress).join("\n"));
        send("input:\n" + dump(args[0], 64));
    }
});"""),

    # ---------------- Java Hook ----------------
    ("Java Hook", "Hook Java 方法(含重载)", "按类名+方法名 Hook，自动处理重载",
     r"""if (Java.available) {
    Java.perform(function () {
        var target = Java.use("com.example.MainActivity");
        target.evilMethod.overloads.forEach(function (ov) {
            ov.implementation = function () {
                send("[>] " + ov.method_name + " 被调用, 参数: " + arguments[0]);
                return ov.apply(this, arguments);
            };
        });
        send("[*] Java Hook 已安装");
    });
} else { send("[-] 目标不是 Java 应用"); }"""),

    ("Java Hook", "动态创建 Java 对象并调用", "实例化类、改字段、调用方法",
     r"""if (Java.available) {
    Java.perform(function () {
        var Cls = Java.use("com.example.Settings");
        var inst = Cls.$new();
        inst.setPremium("true");       // 自定义方法示例
        Cls.token.value = "改后的值";   // 改静态字段
        send("[*] 完成: " + inst.toString());
    });
}"""),

    # ---------------- 内存 ----------------
    ("内存", "扫描内存字符串", "在指定模块内存中扫描 ASCII 字符串模式",
     r"""var bytes = "FLAG{hello}";
var hex = Array.from(bytes).map(function (c) { return c.charCodeAt(0).toString(16); }).join(" ");
var mod = Process.enumerateModules()[0];
send("[*] 扫描 " + bytes + " ...");
var hits = [];
Memory.scan(mod.base, mod.size, hex, {
    onMatch(addr, size) {
        hits.push(addr.toString());
        send("  found: " + addr);
        if (hits.length >= 20) return "stop";
    },
    onComplete() { send("[*] 共命中 " + hits.length + " 处"); }
});
"""),

    ("内存", "读取指定地址", "从绝对地址读取一段 bytes",
     r"""var addr = ptr("0x7000000000");
var n = 64;
try {
    var data = Memory.readByteArray(addr, n);
    send("bytes @ " + addr + ":\n" + hexdump(data, {header: true, ansi: false}));
} catch (e) { send("[-] 读取失败: " + e); }"""),

    # ---------------- 通用工具 ----------------
    ("通用工具", "快速只读 Trace(native)", "遍历主模块导出，打印被调用命中(粗粒度)",
     r"""var mod = Process.enumerateModulesWithoutTracing()[0] || Process.enumerateModules()[1] || Process.enumerateModules()[0];
var count = 0;
mod.enumerateExports().forEach(function (e) {
    if (e.type !== "function") return;
    Interceptor.attach(e.address, {
        onEnter() { if (count++ < 50) send("[trace] " + e.name); },
        onLeave() {}
    });
});
send("[*] 已对 " + mod.name + " 的导出函数标记 trace");"""),

    ("通用工具", "枚举某 so 的全部导出", "打印指定模块所有 export 类型与地址",
     r"""var m = Process.findModuleByName("libc.so");
if (!m) { send("[-] 模块不存在"); }
else {
    m.enumerateExports().forEach(function (e) {
        send(e.type + "\t" + e.name + "\t" + e.address);
    });
}"""),
]


def by_category() -> List[str]:
    seen: list = []
    for t in TEMPLATES:
        if t[0] not in seen:
            seen.append(t[0])
    return seen


def templates_of(category: str) -> list:
    return [t for t in TEMPLATES if t[0] == category]


def build_combo_items():
    """生成 (显示文本, js源码) 列表，显示文本形如 "分类 · 名称"。"""
    out = []
    for cat in by_category():
        for t in templates_of(cat):
            out.append((f"{cat} · {t[1]}", t[3]))
    return out