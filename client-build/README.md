# 配套客户端构建（frida-python）

## 为什么需要这个目录

本项目把 frida 的 D-Bus 接口名和对象路径从 `re.frida.*` / `/re/frida/*` 改成了
`app.svc.*` / `/app/svc/*`，控制端口也从 `27042` 改成 `20442`。

服务端改名之后，**官方 PyPI 的 `frida` 包连不上**：它的 libfrida-core 仍然按
`re.frida.HostSession17` 去调方法，而魔改 server 上注册的是
`app.svc.HostSession17`，握手阶段就会被拒。

所以 PC 端必须用**同一份源码**重编一个 `frida` 客户端。这个目录就是干这个的：
一次 configure 同时产出「配套 wheel」和「同架构 frida-server（用于本机自测）」。

## 快速开始（Linux x86_64）

```bash
# 1. 构建（首次会下载约 300MB 依赖，1 核机器约 6~10 分钟）
bash client-build/build_client.sh linux-x86_64

# 2. 安装配套客户端
pip install --force-reinstall dist/frida-17.19.0-cp37-abi3-linux_x86_64.whl

# 3. 端到端自测（起本机 server → 握手 → attach → 注入 → RPC）
python3 client-build/verify_client.py
```

`verify_client.py` 会依次验证：

| 步骤 | 说明 |
|---|---|
| 静态核对 | server 二进制里 `re.frida` / `27042` / `frida:rpc` 出现 0 次，`app.svc` 出现 >0 次 |
| 客户端核对 | 已装的 `frida` 包内 RPC 标记是 `app:rpc`（不是官方包） |
| 起 server | 用构建出的 Linux 版 frida-server 监听 `127.0.0.1:20442` |
| 握手 | `add_remote_device()` + `enumerate_processes()` —— 这一步就是 D-Bus 改名是否一致的试金石 |
| 注入 | attach 一个 python 子进程，`create_script` + `script.load()` |
| RPC | 调 `rpc.exports.ping()`，验证 `app:rpc` 三端同步没漏 |
| 清理 | `session.detach()` 不崩 |

## 支持的目标

`build_client.sh` 的第一个参数是 frida 的 `--host`：

| 参数 | 说明 |
|---|---|
| `linux-x86_64` | **本目录已验证**，产出 `linux_x86_64` wheel |
| `linux-arm64` | 同上流程，交叉/原生均可 |
| `macos-arm64` / `macos-x86_64` | 需在 macOS + Xcode Command Line Tools 上跑 |
| `windows-x86_64` | 需在 Windows + MSVC（Developer Command Prompt）上跑，脚本用 Git Bash 执行 |

Windows / macOS 没有本机环境时，最省事的办法是把仓库推到 GitHub，用
`.github/workflows/client-wheel.yml` 出 Linux / macOS wheel（Windows 需 MSVC，建议本机跑）。

> 脚本复用 `/opt/frida-client-build/src` 这份 ASCII 副本；每次运行会先把
> `subprojects/frida-core`、`subprojects/frida-gum` 的改动同步过去，所以改了补丁
> （比如协议标记）后直接重跑即可，不用手动删目录。

## 产物

```
dist/
├─ frida-17.19.0-cp37-abi3-linux_x86_64.whl   # 配套客户端（36.8 MB，abi3，Python 3.7+ 通用）
└─ frida-server-17.19.0-linux-x86_64          # 同架构 server，仅用于本机自测
```

wheel 是 `abi3`（`Py_LIMITED_API 3.7`）的，一个包覆盖 Python 3.7~3.13，不用按小版本分别编。

## 和 frida-tools / GUI 客户端配合

`frida-tools`（`frida-ps` / `frida` / `frida-trace`）是纯 Python，依赖 `frida` 包：

```bash
pip install frida-tools        # 它只会检查 frida>=17，不会覆盖已装好的配套版
frida-ps -H 127.0.0.1:20442
```

实测：`frida-tools 14.8.2` + 本 wheel，`frida-ps -H 127.0.0.1:20442` 能正常列出进程。

GUI 客户端（`gui-client/`）同理，装好这个 wheel 后 `python run.py` 就能连上魔改 server。

> 注意：`pip install -U frida` 会把配套版覆盖回官方版，届时连接会失效。锁版本：
> `pip install "frida==17.19.0" --no-index --find-links dist`。

## 构建期踩过的坑（脚本里已处理）

1. **路径必须是 ASCII**。meson 调用 pkg-config 时用严格 utf-8 解码输出，中文路径会
   `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe8`。脚本会把源码复制到
   `$FRIDA_CLIENT_WORK/src`（默认 `/opt/frida-client-build`）。
2. **releng 的 meson / tomlkit 必须按 submodule 指针取**。直接 clone 默认分支会拿到新版
   meson（`UserArrayOption` 已从 `mesonbuild.coredata` 迁到 `mesonbuild.options`），
   `configure` 直接 ImportError。脚本从 `git ls-tree` 读指针再 `fetch --depth 1 <sha>`。
3. **版本号来自 `git describe`**。复制出来的源码树没有 `.git` 会退化成 `0.0.0`，
   脚本会给副本建一个最小快照仓库并打 tag。
4. **`frida-python` 的 meson.build 会执行 `python3 setup.py -V`**，缺 `setuptools` 会失败。
5. **`--disable-frida-tools`**：否则 configure 会去初始化 `frida-tools` 子模块并构建它，
   而 PyPI 的 frida-tools 已经够用。
6. **1 核 / 2G 的机器用 `-j1`**。默认就是 1；内存大的机器可以 `JOBS=4`。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `FRIDA_CLIENT_WORK` | `/opt/frida-client-build` | 构建工作目录，必须 ASCII |
| `FRIDA_SRC` | `<repo>/frida` | 已打补丁的源码树 |
| `JOBS` | `1` | ninja 并发 |
| `SKIP_SERVER` | `0` | 设 1 则不构建同架构 server（省几分钟，但没法自测） |
