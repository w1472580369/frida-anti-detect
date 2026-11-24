# Frida Phone（Android 客户端）

把本项目的能力装进手机：**不依赖 PC、不依赖 adb**，手机上直接完成进程查看、注入、脚本执行、RPC 调用，并内置一个 MCP 服务，让 AI 客户端（Claude Desktop、Cherry Studio、自研 Agent 等）通过 HTTP 调用本机能力。

- 包名：`com.svc.fridactl`
- 版本：1.1（versionCode 2）
- minSdk 26 / targetSdk 34
- 架构：arm64-v8a（仅 64 位设备/64 位进程；32 位应用无法注入）
- UI：WebView + 原生 Java 桥（`Android` 对象），无第三方前端依赖

---

## 一、安装

`dist/` 下有两种等价形态，任选其一：

| 文件 | 说明 |
|---|---|
| `FridaPhone-1.1-apk.zip` | 推荐。解压后得到 `FridaPhone-1.1.apk` + 安装说明，APK 未被云盘改写 |
| `FridaPhone-1.1.apk.bin` | APK 原始字节，下载后**改名为 `.apk`** 即可安装 |

```bash
# 方式一：adb
adb install -r FridaPhone-1.1.apk

# 方式二：手机浏览器/文件管理器直接点开安装
```

首次启动需要授予：

1. **Root 权限**（Magisk / KernelSU / APatch）：注入其他 App 必须 root，App 会调用 `su`，请在弹窗中允许并勾选“记住”。
2. **通知权限**（Android 13+）：前台服务通知，用于保持 MCP 服务存活。

> 没有 root 时，进程列表、模板、MCP 仍可使用，但注入与启动 frida-server 会失败并给出提示。

---

## 二、两种工作模式

### 模式 A：手机内直接注入（无需 PC）

这是本 APK 的主路径：

```
App → su → /data/local/tmp/.svc-helper (frida-inject)
        → 注入目标进程
        → 目标进程内运行 bridge.js，监听 127.0.0.1:<随机端口>
        → App 通过 TCP JSON 执行 eval / RPC
```

操作步骤：

1. 「进程」页搜索目标进程，点「附加」；
2. 首次会复制注入器到 `/data/local/tmp` 并申请 root，等待 2~5 秒；
3. 顶部出现会话状态（PID / 端口）后，到「脚本」页写代码，点「运行」；
4. 脚本里 `rpc.exports = { ... }` 定义的函数，会出现在「RPC」页，可直接填参数调用；
5. 目标进程里的 `send()` / `console.log()` 会实时出现在「脚本」页输出区和「日志」页。

「应用」页列出已安装的第三方应用，点「启动并附加」会自动 `monkey` 拉起应用、轮询 PID、再注入，适合冷启动场景。

### 模式 B：手机当 frida-server（给 PC 用）

「设置」页 → 「启动 server」，会把内置的**兼容版 frida-server**（`libfsrv.so`，端口 20442）释放到 `/data/local/tmp/.svc-server` 并后台运行。

```bash
# PC 与手机同一局域网
frida-ps -H 192.168.1.23:20442
frida -H 192.168.1.23:20442 -f com.example.app -l hook.js
```

这是 **compat 版** server：端口 20442，保留官方 `re.frida.*` D-Bus 协议名，官方 `frida-tools` 可直接连接；路径、端口、线程名等其余改动仍在。App 内 injector 继续使用 `app.svc.*`，两者互不影响。

> 模式 A 与模式 B 可以同时开：server 供 PC 使用，App 内注入走自己的 injector，互不冲突。

---

## 三、MCP 服务（给 AI 用）

App 启动后自动在 `0.0.0.0:8765` 起一个 MCP 服务（前台服务保活）。

- 端点：`http://<手机IP>:8765/mcp`
- 健康检查：`GET http://<手机IP>:8765/health`
- 鉴权：`Authorization: Bearer <token>`，也支持 `?token=<token>`
- 协议：JSON-RPC 2.0，MCP 协议版本 `2024-11-05`，Streamable HTTP（`POST`）
- Token / 端口：「设置」页可见，可一键复制、重置 token、改端口后重启

「设置」页的「复制 AI 配置」会生成如下片段，直接粘进支持 MCP 的客户端即可：

```json
{
  "mcpServers": {
    "frida-phone": {
      "url": "http://192.168.1.23:8765/mcp",
      "headers": { "Authorization": "Bearer <你的token>" }
    }
  }
}
```

### 工具列表（24 个）

| 工具 | 参数 | 作用 |
|---|---|---|
| `frida_status` | — | root、设备、当前会话、server、MCP 状态；`injector` 为 `patched-17.19.0-r3-miui`，`server_mode` 为 `compat` |
| `frida_get_guide` | — | App 内说明：兼容版 server 与 patched injector 的命名差异、端口、路径、PC 命令、MCP 示例。**AI 第一次调用应先读它** |
| `frida_device_info` | — | 设备型号、Android 版本、ABI、root、局域网 IP |
| `frida_list_apps` | — | 已安装第三方应用包名 |
| `frida_recheck_root` | — | 重新检测 root 并返回最新状态 |
| `frida_server_log` | `lines`（可选） | 读 `/data/local/tmp/.svc-server.log` |
| `frida_clear_logs` | — | 清空 App 日志缓冲区 |
| `frida_mcp_info` | — | MCP 地址、端口、令牌、运行状态 |
| `frida_run_template` | `name`（必填）、`timeout_ms` | 取模板并立即在已附加进程执行 |
| `frida_list_processes` | `filter`（可选） | 进程列表，最多 500 条 |
| `frida_attach` | `pid`（必填） | 用内置 patched 注入器注入指定 PID，建立 bridge 会话 |
| `frida_detach` | — | 断开当前会话并清理注入器 |
| `frida_eval` | `code`（必填）、`timeout_ms` | 在目标进程执行 JS，返回结果字符串 |
| `frida_rpc_list` | — | 列出脚本导出的 RPC 方法 |
| `frida_rpc_call` | `name`（必填）、`args`（数组）、`timeout_ms` | 调用 RPC 方法 |
| `frida_list_templates` | — | 模板列表（名称/分类/描述） |
| `frida_get_template` | `name`（必填） | 取模板完整代码 |
| `frida_start_server` | — | 启动内置兼容版 frida-server（20442，官方客户端可连） |
| `frida_stop_server` | — | 停止 frida-server |
| `frida_restart_mcp` | `port`、`token`、`delay_ms`（均可选） | 延迟重启 MCP；会短暂断开当前连接 |
| `frida_regenerate_token` | `delay_ms`（可选） | 生成新令牌并延迟重启；返回新令牌，旧令牌失效 |
| `frida_launch_app` | `package`（必填） | 拉起应用、等待 PID、自动附加 |
| `frida_get_logs` | `limit`（可选） | 读最近日志（不消费） |
| `frida_drain_logs` | — | 取走并清空待读日志 |

返回值统一为 MCP `content: [{type:"text", text:"<JSON>"}]`，业务失败时 `isError: true`。

> `frida_restart_mcp` / `frida_regenerate_token` 会改变当前 MCP 连接参数，属于破坏性操作；默认延迟 1500ms，让本次响应先返回。AI 调用后必须立即用新地址/令牌重连。

### curl 示例

```bash
TOKEN=你的token
BASE=http://192.168.1.23:8765

# 健康检查（不需要 token）
curl -s $BASE/health

# 初始化
curl -s $BASE/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'

# 列工具
curl -s $BASE/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 看进程
curl -s $BASE/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"frida_list_processes","arguments":{"filter":"chrome"}}}'

# 附加并执行
curl -s $BASE/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"frida_attach","arguments":{"pid":12345}}}'

curl -s $BASE/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"frida_eval","arguments":{"code":"Process.arch + \" \" + Process.mainModule.name"}}}'
```

> 手机与 AI 客户端需在同一网络；MCP 走明文 HTTP，**不要暴露到公网**。用完可在设置页重置 token 或停止服务。

---

## 四、功能页签

| 页签 | 内容 |
|---|---|
| 进程 | 搜索/刷新进程，一键附加，显示会话状态 |
| 应用 | 第三方应用列表，一键「启动并附加」 |
| 脚本 | 模板插入、JS 编辑、运行、清空输出、实时日志 |
| RPC | 刷新 RPC 方法、填 JSON 参数、调用并看返回值 |
| 模板 | 13 个常用脚本模板（Hook Java/native、SSL pinning、Root 检测、加解密等） |
| 说明 | 兼容版 server / patched injector 的命名差异、端口、路径、PC `frida-tools` 命令、MCP curl 示例；命令可一键复制 |
| 设置 | 设备信息、root 重检、MCP 地址/令牌/端口/复制配置、frida-server 启停与日志、按包名启动 |
| 日志 | 全局日志（注入器输出、bridge 事件、错误），可刷新/清空 |

脚本输出每 700ms 增量拉取；状态每 4 秒刷新。

> 输出说明：`console.log()` 会被 bridge 广播，实时进入输出区；`send()` 在 Frida 17 中是**只读全局**，脚本侧无法改写，其输出由 `frida-inject` 的 stdout 带回日志（显示为原始 JSON 行）。写脚本时优先用 `console.log()`。

---

## 五、构建

### 依赖

- Linux x86_64
- JDK 17（`javac` / `keytool`）
- Android build-tools：`aapt2`、`d8`、`zipalign`、`apksigner`
- `android.jar`（platform 35）
- Python 3

本仓库默认从 `toolchain/bt/android-15/` 和 `toolchain/android-sdk/platforms/android-35/android.jar` 取；也可用环境变量覆盖：

```bash
export AAPT2=/path/to/aapt2
export D8=/path/to/d8
export ZIPALIGN=/path/to/zipalign
export APKSIGNER=/path/to/apksigner
export ANDROID_JAR=/path/to/android.jar
```

### 一键构建

```bash
bash android-app/build_apk.sh
```

脚本流程（全部中间产物在 `/tmp/frida-phone-build`，避免云盘 FUSE 对 mmap 写入返回全零）：

1. 复制 `res/` `assets/` `java/` `jniLibs/` `AndroidManifest.xml`
2. `aapt2 compile` + `aapt2 link`（生成 `R.java` 与含 assets 的 base APK）
3. `javac`（`-bootclasspath android.jar`）
4. `d8 --min-api 26`
5. Python 合并 `classes.dex` + `lib/arm64-v8a/libfinj.so` + `libfsrv.so`
6. `zipalign -p 4`
7. `apksigner` 签名（`keystore/debug.keystore`，不存在会自动生成）
8. 回传 `dist/FridaPhone-1.1.apk.bin` 与 `dist/FridaPhone-1.1-apk.zip`，并校验 md5

### 目录

```
android-app/
├─ AndroidManifest.xml
├─ res/                     # 字符串、主题、矢量图标
├─ assets/
│  ├─ index.html            # 全部 UI（单文件，内联 CSS/JS）
│  ├─ bridge.js             # 注入到目标进程的 bridge，__PORT__/__TOKEN__ 由 Java 替换
│  └─ templates.json        # 13 个脚本模板
├─ java/com/svc/fridactl/
│  ├─ MainActivity.java     # WebView 容器
│  ├─ AppCore.java          # JS 桥 + 业务编排
│  ├─ McpService.java       # 前台服务保活
│  ├─ McpServer.java        # 纯 Java MCP HTTP 服务
│  ├─ FridaInjector.java    # 释放并执行 frida-inject，建立 bridge
│  ├─ BridgeClient.java     # TCP JSON 客户端
│  ├─ ServerManager.java    # 内置 frida-server 启停
│  ├─ ProcessScanner.java   # ps 解析
│  ├─ RootShell.java        # su/sh 执行封装
│  ├─ Templates.java        # 模板读取
│  └─ LogBus.java           # 环形日志缓冲
├─ jniLibs/arm64-v8a/
│  ├─ libfinj.so            # patched frida-inject 17.19.0（20442 / app.svc / MIUI helper dex）
│  └─ libfsrv.so            # compat 版 frida-server 17.19.0（re.frida，官方客户端可连）
├─ keystore/debug.keystore.b64
└─ build_apk.sh
```

---

## 六、已知限制（重要）

1. **模式 A 的注入器为 patched 17.19.0**。当前 `libfinj.so` 已处理：
   - 控制端口 `27042/27052 → 20442/20452`；
   - 服务名 `re.frida.* → app.svc.*`、对象路径 `/re/frida/* → /app/svc/*`；
   - 线程名 `frida-eternal-agent → svc-eternal`、`gum-js-loop → main-loop`；
   - 注入器路径 `/data/local/tmp/.svc-helper`、bridge `.svc-bridge-<port>.js`、helper dex `.svc-<id>.dex`；
   - 内嵌 Android helper dex 由源码重建为 `app/svc` 包名，并加入 Android 12 / MIUI `systemMain()` 回退。
   仍会保留少量 `frida_*` 符号名（例如 `frida_agent_main`），对只扫描高信号字符串的检测已明显改善，但不等同于源码级全量去特征。需要完全覆盖时使用下一节的 CI 源码构建。
2. **必须 root**。非 root 设备只能看进程/模板/MCP，不能注入。
3. **SELinux**：部分 ROM 即使 root 也限制 `ptrace` 或 `exec` `/data/local/tmp`，表现为注入器启动即退出。可尝试 Magisk 的 `su -c setenforce 0`（不推荐长期）或换用模式 B + PC。
4. **16KB page**：Android 15 部分设备要求 16KB 对齐的 native 库。当前 `.so` 为 4KB 对齐，如安装报 `INSTALL_FAILED_INVALID_APK` 或运行崩溃，需用 16KB 对齐的工具链重编。
5. **MCP 无 TLS**：仅限可信局域网；token 明文传输，泄露后可在设置页一键重置。
6. **APK 约 48MB**：两个 57MB 的 ELF 压缩后体积仍较大，属正常。
7. **仅支持 64 位**：APK 只打包了 arm64 的注入器与 server。64 位系统上的 32 位应用（如部分老游戏/工具）无法注入；32 位设备无法安装。需要时可为 `armeabi-v7a` 单独构建 `libfinj.so` / `libfsrv.so` 并出 split APK。
8. **后台保活**：部分 OEM（小米/华为/OPPO/vivo）会清理前台服务，建议在系统设置中允许自启动、关闭电池优化，否则 MCP 可能在息屏后被断开。
9. **未做真机自动化测试**：本环境无 Android 设备，签名/清单/dex/资源/依赖均已静态校验，实际注入效果请在设备上验证。
10. **bridge 协议已做真实运行时验证**：用 Frida 17.15.3 在本机 Linux 进程上真实注入 `bridge.js`，覆盖 ping、eval、大段中文（跨 TCP 分片）、请求拆包/粘包、20 路并发、RPC 列表/调用、`console.log` 广播，全部通过；并修复了 Frida `SocketConnection.output` 不允许并发写的 `stream has outstanding operation` 问题（所有写入已串行化）。

---

## 七、注入器二进制魔改（已内置）

APK 内的 `libfinj.so` 来自官方 `frida-inject 17.19.0`，已用 `tools/patch_inject_binary.py` 做原地魔改，不需要在手机上重编。

### 7.1 处理内容

| 类别 | 原版 | 魔改后 |
|---|---|---|
| 控制端口 | 27042 / 27052 | 20442 / 20452 |
| D-Bus 服务名 | `re.frida.*` | `app.svc.*` |
| D-Bus 对象路径 | `/re/frida/*` | `/app/svc/*` |
| 主线程名 | `frida-eternal-agent` | `svc-eternal` |
| JS 线程名 | `gum-js-loop` | `main-loop` |
| Android helper 类 | `re/frida/Helper` | `app/svc/Helper` |
| 注入器路径 | `/data/local/tmp/frida-helper-*` | `/data/local/tmp/.svc-helper` |
| helper dex | stock `re/frida` | 源码重建的 `app/svc` dex（27036 字节，原地替换并零填充） |
| RPC/管道标记 | `frida:rpc` / `frida:stdout` / `frida:stderr` | `app:rpc01` / `app:stdout` / `app:stderr` |

### 7.2 重新生成

```bash
# 1) 用 patched helper 源码重建 dex（27,608 字节）
cd frida
../toolchain/jdk-17.0.13+11/bin/javac -source 8 -target 8 -nowarn \
  -bootclasspath ../toolchain/android-35/android.jar \
  -cp ../toolchain/android-35/android.jar \
  -d /tmp/hdex/classes subprojects/frida-core/src/android-helper/app/svc/*.java
../toolchain/jdk-17.0.13+11/bin/java -cp ../toolchain/r8.jar com.android.tools.r8.D8 \
  --release --min-api 19 --classpath ../toolchain/android-35/android.jar \
  --output /tmp/hdex/out $(find /tmp/hdex/classes -name '*.class')

# 2) 对 stock frida-inject 做二进制魔改
#    仓库已带预编译 tools/helper-patched.dex（27608 字节），可直接使用；
#    上面的 d8 步骤用于从源码重新生成它。
cd ..
python3 tools/patch_inject_binary.py \
  toolchain/frida-inject \
  android-app/jniLibs/arm64-v8a/libfinj.so \
  --dex tools/helper-patched.dex

# 3) 静态验证
strings -a android-app/jniLibs/arm64-v8a/libfinj.so | \
  grep -E 'frida:rpc|re\.frida|/re/frida/|frida-eternal-agent|gum-js-loop|frida-zymbiote|27042' || echo "no high-signal strings"
readelf -h android-app/jniLibs/arm64-v8a/libfinj.so | head

# 4) 重签 APK
bash android-app/build_apk.sh
```

### 7.3 验证边界

- 已在 x86_64 Linux 上用同版本 stock `frida-inject` 做过真实注入验证：替换后 `bridge.js` 的 `ping` / `eval` / `rpc_list` / `rpc_call` 全部通过，说明同长度 token 替换和 helper dex 替换不会破坏 Frida 内部协议。
- ARM64 产物已做 ELF 解析、字符串扫描、dex 尺寸/校验和检查；本环境没有 Android 真机/模拟器，未做 ARM64 真机注入验证。
- 仍保留部分 `frida_*` 符号名与源码路径字符串；需要彻底覆盖时用 GitHub Actions `source-build` 从源码构建 `frida-inject` 后替换 `libfinj.so`。

> 需要完全源码级覆盖时：用 `.github/workflows/anti-detect-build.yml` 的 arm64 矩阵构建 `frida-inject`（工作流已加 `make frida-inject` 与上传步骤），再替换 `libfinj.so`。`frida-inject` 与 `frida-server` 应来自同一份源码/同一版本。

---

## 八、安全与合规

本工具仅用于**自有应用**的安全测试、逆向工程学习与**已获授权**的评估场景。注入他人应用、绕过其安全机制可能违反当地法律与服务条款，使用者自行承担全部责任。
