# 全局默认配置（亦可被 CLI 参数覆盖）

# 设备端 frida-server 的控制端口。
# 官方默认 27042；本项目反检测魔改版将端口改为 20442。
CONTROL_PORT = 20442

# 需要转发的本地端口范围下限（避免与系统端口冲突）。
LOCAL_FORWARD_BASE = 27550
LOCAL_FORWARD_MAX  = 29550

# adb 可执行文件：可手动指定，否则自动探测。
ADB_PATH = None

# 设备上已推送的 frida-server 二进制名（用于“自动启动”按钮）。
SERVER_NAME = "frida-server"

# 无线 adb 默认端口。
ADB_WIRELESS_PORT = 5555

# 自动刷新进程列表间隔(秒)；<=0 表示关闭自动刷新。
AUTO_REFRESH_SECS = 3.0

# 主题配色（暗色）。
THEME = {
    "bg":          "#1e2227",
    "bg_alt":      "#262b31",
    "panel":       "#23272e",
    "fg":          "#d7dbe0",
    "fg_dim":      "#8a919c",
    "accent":      "#4f8cff",
    "accent_soft": "#2b3d5e",
    "ok":          "#3fb96f",
    "warn":        "#e0a23c",
    "err":         "#e05555",
    "border":      "#353b44",
}

# GUI 里预设的常用 quick action 模板（会渲染进脚本面板下拉）。
QUICK_TEMPLATES = [
    ("附着一个目标进程的示例脚本",
     "setTimeout(function () {\n"
     "    console.log('attached to: ' + Process.id + ' / ' + Process.arch);\n"
     "    console.log('modules: ' + Process.enumerateModules().length);\n"
     "}, 0);"),
    ("枚举主模块导出并 Hook printf/logger",
     "var mod = Process.enumerateModules()[0];\n"
     "console.log('main module: ' + mod.name);\n"
     "mod.enumerateExports().slice(0, 80).forEach(function (e) {\n"
     "    console.log(e.type + ' ' + e.name + ' @ ' + e.address);\n"
     "});"),
    ("扫描内存字符串",
     "var pattern = 'FridaIsHere'.split('').map(function (c){return c.charCodeAt(0).toString(16)}).join(' ');\n"
     "console.log('scan for: ' + pattern);\n"
     "Memory.scan(Process.enumerateModules()[0].base, "
     "Process.enumerateModules()[0].size, pattern, {\n"
     "  onMatch: function (addr, size){ console.log('found: ' + addr); },\n"
     "  onComplete: function(){ console.log('scan done'); }\n"
     "});"),
    ("拦截 native 函数(示例: free)",
     "Interceptor.attach(Module.getExportByName(null, 'free'), {\n"
     "  onEnter: function (args){ console.log('free(' + args[0] + ')'); },\n"
     "  onLeave: function (retval){ }\n"
     "});"),
]