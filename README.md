# Frida anti-detect 魔改项目

> **仓库**：https://github.com/w1472580369/frida-anti-detect（private）  
> **Release v1.2**：https://github.com/w1472580369/frida-anti-detect/releases/tag/v1.2  
> 含 `FridaPhone-1.2-apk.zip` 与 `frida-anti-detect-source-17.19.0.zip`。

目标：修改 Frida 源码，消除市场上主流 App 的本地检测特征，并**真实构建出可直接使用的 Android frida-server**。

项目提供两种 D-Bus 模式，按场景选择：

| 模式 | D-Bus 名 / 对象路径 | 官方 frida-tools | 适用场景 |
|---|---|---|---|
| **compat**（APK 默认） | `re.frida.*` / `/re/frida/*` | ✅ 直接连接 | 需要 PC 官方客户端；其余反检测改动全部保留 |
| **stealth** | `app.svc.*` / `/app/svc/*` | ❌ 需配套 wheel | 需要最大化改名；PC 必须装本项目同源重编的 `frida` |

两种模式共用同一套源码补丁；切换只改 `lib/base/session.vala`，用 `tools/dbus_mode.py` 完成。

**先说一句实话**：「绕过市面上所有 App 的检测」没有终局方案——这是军备竞赛。
native 函数完整性校验、内核态/eBPF 检测、服务端风控不在源码改名能解决的范围内。
本项目把**主流的本地检测点全部 patch 掉**，覆盖率做到尽量高，并附带完整可复现的构建链。

---

## 一、已覆盖的检测点（对应改动见 `patches/`）

| 类别 | 检测特征 | 改动后 |
|---|---|---|
| 线程名 | `gum-js-loop` / `gum-probe` | `main-loop` |
| 线程名 | `frida-agent-container` / `frida-agent-emulated` | `agent-worker` / `agent-emulated` |
| 线程名 | `frida-eternal-agent` | `svc-eternal` |
| 线程名 | `frida-generate-certificate` | `svc-gen-cert` |
| 线程名 | `frida-android-helper` | `android-svc` |
| 进程名 | `g_set_prgname("frida")` | `system` |
| 注入名 | `options.name = "frida"` | `svc` |
| 共享内存 | `gum-<pid>` | `shm-<pid>` |
| 控制端口 | 27042 / 27052 | **20442 / 20452** |
| RPC 通道 | `frida:rpc` | `app:rpc`（C/Vala、gumjs JS、barebone TS、frida-python 四层同步） |
| agent 库名 | `frida-agent-<arch>.so` | `libhelper-<arch>.so` |
| helper 名 | `frida-helper-32/64` | `svc-32/64` |
| socket 路径 | `/frida-<uuid>` | `/svc-<uuid>` |
| Android socket | `/frida-helper-<id>` | `/svc-<id>` |
| Android 路径 | `/data/local/tmp/frida-helper-*.dex` | `/data/local/tmp/.svc-*.dex` |
| Android 路径 | `/data/local/tmp/frida-gadget-*` | `/data/local/tmp/.gadget-*` |
| 临时目录 | `/data/local/tmp`（root 写法） | `/data/local/.svc`（可用 `FRIDA_TMPDIR` 覆盖） |
| Android 包名 | `re.frida.*` | `app.svc.*` |
| D-Bus/服务名 | `re.frida.*`（接口名 + 对象路径） | compat 保留；stealth 改为 `app.svc.*` |
| SELinux 类型 | `frida_memfd` / `frida_file` | `svc_memfd` / `svc_file` |
| zymbiote | abstract 名 `/frida-zymbiote-*` | `/svc-zymbiote-*`（C 源码 + 4 架构桩全部重编译） |
| HTTP 标识 | `Frida/<ver>` | `System/<ver>` |
| inspector | `Frida Agent` / `Frida/v` | `System` / `System/v` |
| 内存 VFS | `-isystem /frida`、`/frida/` 前缀 | `/sysinc`、`/sysinc/` |
| helper.dex | 预编译 dex 内 `re/frida/*`、`/frida-helper` | 已重编译为 `app/svc/*`、`/svc-` |

## 二、目录结构

```
frida-anti-detect/
├─ frida/                  # 已应用改动的源码树（frida + frida-gum + frida-core）
├─ tools/
│  ├─ apply_mods.py        # 幂等应用全部源码改动（断言出现次数）
│  ├─ apply_patches.py     # 按 patches/series 应用补丁到对应子模块（幂等）
│  ├─ gen_patches.py       # 从工作树差异生成 patches/*.patch
│  ├─ build_helper_dex.py  # 用 JDK + d8 重建中性包名 helper.dex
│  ├─ build_zymbiote.py    # 用 NDK 重建 4 架构 zymbiote 注入桩
│  ├─ dbus_mode.py         # 切换 compat / stealth 的 D-Bus 协议名
│  ├─ patch_embedded_dex.py# 只替换已有 server 的内嵌 helper dex
│  └─ patch_inject_binary.py# 魔改 frida-inject 二进制
├─ patches/                # 按文件拆分的 54 个补丁 + series
├─ dist/                   # 已构建的 frida-server 与 Android APK
├─ gui-client/             # PC 桌面客户端（PySide6 + frida-python + adb）
├─ client-build/           # 配套 frida-python 客户端构建（协议改名后必须同源重编）
├─ android-app/            # 手机端 APK 工程（WebView + Java + 内置 MCP）
├─ build.sh                # 一键拉源码 + 打补丁 + 构建
└─ .github/workflows/
   ├─ anti-detect-build.yml  # GitHub Actions：构建 frida-server
   └─ client-wheel.yml       # GitHub Actions：构建配套客户端 wheel
```

## 三、已构建产物

`dist/` 目录（本环境真实编译产出，Frida 17.19.0，NDK r29）：

| 文件 | 架构 | 大小 |
|---|---|---|
| `frida-server-17.19.0-android-arm64` | ARM64，**compat 版**（保留 `re.frida`） | ~56 MB |
| `frida-server-17.19.0-android-arm` | ARM32（老设备，stealth 版） | ~26 MB |
| `FridaPhone-1.2-apk.zip` | Android 客户端 APK + 安装说明 | ~50 MB |
| `FridaPhone-1.2.apk.bin` | 同一 APK 的原始字节（下载后改名 `.apk`） | ~50 MB |
| `frida-17.19.0-cp37-abi3-linux_x86_64.whl` | **stealth 模式配套 PC 客户端**（abi3，Python 3.7~3.13 通用） | ~37 MB |
| `frida-server-17.19.0-linux-x86_64` | Linux 版 server，仅用于本机协议自测 | ~41 MB |

APK 内 `libfinj.so` 已核对：`27042` / `re.frida` / `/re/frida/` / `frida:rpc` /
`frida-zymbiote` 均为 **0 命中**，helper dex 为源码重建的 `app/svc` 版本。
APK 内 `libfsrv.so` 为 **compat 版**：保留 `re.frida` / `/re/frida/` 协议名，因此官方客户端可直连；
`27042` / `app.svc` / `frida:rpc` 仍为 0 命中。stealth 版 server 的 `re.frida` 为 0 命中。

## 四、使用方法

```bash
# 推到设备（文件名随意，不影响）
adb push dist/frida-server-17.19.0-android-arm64 /data/local/tmp/svc
adb shell "su -c 'chmod 755 /data/local/tmp/svc'"

# 启动（注意新默认端口 20442，不再是 27042）
adb shell "su -c '/data/local/tmp/svc -l 0.0.0.0:20442 &'"

# PC 端连接（frida-tools 需显式指定端口/设备）
adb forward tcp:20442 tcp:20442
frida-ps -H 127.0.0.1:20442
```

> 端口/路径可通过环境变量 `FRIDA_TMPDIR` 等覆盖；连接若异常优先检查端口是否仍用旧的 27042。

### 4.1 PC 客户端怎么选

**compat 版 server（APK 默认）**：D-Bus 名仍是 `re.frida.*`，官方客户端直接可用：

```bash
pip install frida-tools
frida-ps -H 127.0.0.1:20442
```

建议版本对齐：`pip install frida==17.19.0 frida-tools`。官方 `frida-tools` 16.x / 17.x
都使用 `re.frida.*`，可以连接；不要用改过协议名的 wheel 去连 compat 版。

**stealth 版 server**：D-Bus 名改成 `app.svc.*`，官方 PyPI 的 `frida` 包连不上，
必须装本项目同源重编的客户端：

```bash
pip install --force-reinstall dist/frida-17.19.0-cp37-abi3-linux_x86_64.whl
pip install frida-tools
frida-ps -H 127.0.0.1:20442
```

wheel 是 abi3（Python 3.7~3.13 通用）。macOS / Windows 没有现成包，可本地跑
`bash client-build/build_client.sh macos-arm64`（Windows 需 MSVC），或用
[`.github/workflows/client-wheel.yml`](.github/workflows/client-wheel.yml) 出包。

> 别执行 `pip install -U frida`，会把配套版覆盖回官方版。

## 五、如何重新构建

方式 A：一键脚本（需 Linux x86_64，建议 >=4 核 / 8GB）
```bash
bash build.sh arm64    # 或 arm
```

方式 B：GitHub Actions
把本项目推到 GitHub，手动触发 `source-build`，选择 `compat` 或 `stealth`，
产物自动打包上传（server + injector）。工作流默认固定 Frida `17.19.0`，避免上游漂移。

方式 C：对干净源码手打补丁
```bash
git clone --recurse-submodules https://github.com/frida/frida.git
( cd frida && python3 ../tools/apply_patches.py )
# 然后重建 helper.dex / zymbiote（见 build.sh 第 4、5 步）
```

方式 D：只魔改官方 `frida-inject` 二进制（APK 内置注入器当前采用）
```bash
# 先用 d8 重建 app/svc 版 helper dex，再原地替换字符串与 dex
python3 tools/patch_inject_binary.py \
  toolchain/frida-inject \
  android-app/jniLibs/arm64-v8a/libfinj.so \
  --dex tools/helper-patched.dex
bash android-app/build_apk.sh
```
详见 `android-app/README.md` 第七节。

## 六、构建验证状态

- ✅ 54 个补丁全部从真实 `git diff` 生成，`apply_patches.py` 可在干净源码树上幂等应用。
- ✅ `helper.dex` 用 Temurin JDK 17 + d8（R8 8.13）重新编译，内部 `app/svc/*`、`/svc-` 生效。
- ✅ zymbiote 4 架构（arm64/arm/x86_64/x86）用 NDK r29 clang 重新编译为 static-pie，导出符号与 socket 名对齐。
- ✅ helper dex 已加入 Android 12 / MIUI `ActivityThread.systemMain()` 回退：捕获 `InvocationTargetException`，
  反射安装普通 `Resources` 到 `Resources.sSystem` 后重试，修复 MIUI `theme_compatibility.xml` 缺失导致的 1-2 秒失败。
- ✅ compat 版 server 保留 `re.frida.*`，官方 `frida-tools` 可直接连 20442；stealth 版继续使用 `app.svc.*`。
- ✅ APK 内置 `frida-inject` 已做二进制级魔改：端口/服务名/对象路径/线程名/路径字符串 + 内嵌 helper dex 原地替换；同版本 x86_64 样本已做真实注入与 bridge `ping/eval/rpc` 验证。
- ✅ **配套 frida-python 客户端已同源重编，并完成端到端实测**：起 Linux 版 server → `add_remote_device` 握手 →
  `enumerate_processes` → `attach` → `create_script`/`load` → `rpc.exports.ping()` 返回 `pong` → `detach`，
  全部通过（`client-build/verify_client.py`，11/11 PASS）。这同时证明了 `app.svc.*` 接口名、`/app/svc/*` 对象路径、
  `app:rpc` 标记在客户端/服务端/agent 三侧完全对齐。
- ✅ 官方 `frida-tools`（14.8.2，纯 Python）可直接驱动这套魔改：`frida-ps -H 127.0.0.1:20442`
  正常列出目标进程，说明 `frida-tools → 配套 frida-python → 魔改 server → agent` 整条链路可用。
- ⚠️ 当前沙箱无 Android 设备，未做 MIUI 真机 attach 实测；APK 已内置修复，需在 Android 12 / MIUI 设备上复验。

## 七、剩余 / 已知限制

- 无法根除：native 函数完整性校验（inline hook 必改 prologue）、内核态/eBPF、服务端风控。
- 内嵌的 frida-agent blob 内仍有少量自身符号名（如 `frida_agent_main`），
  这类字符串不落盘、仅在内存中；二进制级替换无法安全重命名全部符号，需源码级构建才能彻底处理。
- APK 内注入器的 Android helper dex 已整体替换为 `app/svc` 版本；agent blob 的 soname/符号仍可能被强扫描识别。
- 二进制内仍保留版本/soname、调试断言里的源码路径（`/home/oleavr/...`），属功能/排错信息，未做激进混淆。
- **compat 与 stealth 的 D-Bus 名互斥**：compat 保留 `re.frida.*`，官方客户端可用；stealth 改成
  `app.svc.*`，必须装配套 `frida` wheel。不能既完全改名又让官方客户端直连。
- stealth 模式下 `frida-node` / `frida-swift` 等其它语言绑定同样需要同源重编。
- 各 App 具体检测逻辑仍建议配合 Magisk hide / Shamiko / LSPosed 等逐 app 实测。

> 仅供安全研究、学习与合法授权的逆向工程用途使用。

## 八、Android 客户端（Frida Phone）

把本项目装进手机：不依赖 PC/adb，手机内完成进程查看、注入、脚本执行、RPC 调用，并内置 MCP 服务供 AI 客户端调用。

- 包名 `com.svc.fridactl`，arm64-v8a，minSdk 26 / targetSdk 34，约 50 MB。
- 内置两份二进制：
  - `libfsrv.so`：**compat 版** frida-server，端口 20442，保留 `re.frida.*`，官方 `frida-tools` 可直接连；
  - `libfinj.so`：patched frida-inject 17.19.0，内部服务名 `app.svc`、线程 `svc-eternal`/`main-loop`，
    helper dex 由源码重建并含 Android 12 / MIUI `systemMain` 回退。
- server 与 injector 的 D-Bus 名不同是刻意设计：PC 只连 server，注入器只在手机内部用，互不影响。
- 两种模式：
  - **手机内注入**：App 释放 `.svc-helper` 到 `/data/local/tmp`，注入 `bridge.js`，通过 `127.0.0.1` 随机端口执行 eval/RPC。
  - **手机当 server**：设置页一键启动 compat 版 server，PC 用 `frida-ps -H <手机IP>:20442` 直连。
- App 内新增「说明」页：端口、服务名、文件路径、PC `frida-tools` 命令、MCP curl 示例，命令可一键复制。
- MCP：`http://<手机IP>:8765/mcp`，Bearer token，24 个工具（状态 / 说明 / 设备 / 应用 / 进程 / 附加 / eval / RPC / 模板 / server / MCP / 日志）。
- 前提：**root**（Magisk/KernelSU）。无 root 只能看进程与模板。

安装、MCP 工具表、curl 示例、构建方法与限制详见 [`android-app/README.md`](android-app/README.md)。

> 说明：APK 内的 server 为 compat 版，注入器为 patched 17.19.0。项目源码与 GitHub Actions 可从 Frida 17.19.0 源码重建 server / injector（compat 或 stealth），用于完全源码级替换。
