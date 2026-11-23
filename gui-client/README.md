# Frida 反检测 PC 客户端 GUI（配套）

为上一阶段完成的**反检测 Frida** 配套的桌面客户端，支持通过 **有线 USB** 与 **无线 adb** 两种方式连接 Android 手机，并提供 Frida 常用操作的可视化界面。

## 特性

- **两种手机连接方式**
  - 有线 USB：`adb devices` 自动识别（需开启 USB 调试）。
  - 无线 adb：输入 `IP[:端口]`，自动 `adb connect`（手机需 `adb tcpip` 开启无线调试）。
- **与反检测 server 配套**：默认控制端口 **20442**（与魔改 frida-server 一致）；也可用 `--port 27042` 连官方 server。
- **自动部署 frida-server**：填入本机编译好的 server 二进制，一键 push 到设备并启动到对应端口。
- **常用 Frida 功能**
  - 进程 / 应用枚举、前台应用识别、过滤搜索。
  - `attach` 附加进程、`spawn` 冷启动应用（可指定入口模块）、“attach 前台应用”一键附加。
  - **内置脚本模板库**：基础信息 / Native Hook / Java Hook / 内存 / 通用工具 五大类 11 个可运行示例，一键插入编辑器。
  - **RPC 调用面板**：自动列出当前脚本 `rpc.exports` 的函数，以 JSON 传参并调用、查看返回。
  - 脚本编辑器 + 实时输出控制台：运行 / 重载 / 停止 / 打开 / 保存 / 清空；进程支持**自动刷新**（可开关）。
  - 检查器：枚举模块、枚举导出、`dlopen`、按符号一键生成 Hook 模板。
  - 暗色主题、日志控制台（颜色区分 `send` / 错误 / 日志）。

## 运行环境（在 PC 上）

| 依赖 | 说明 |
| --- | --- |
| Python 3.9+ | 运行时 |
| `PySide6`、`frida` | `pip install -r requirements.txt` |
| adb | Android `platform-tools`，加入 PATH 或界面里指定路径 |

## 启动

```bash
cd gui-client
pip install -r requirements.txt

# （推荐）连的是反检测版 server，端口 20442
python run.py

# 选项
python run.py --port 27042            # 连官方默认 frida-server
python run.py --adb ~/platform-tools/adb   # 指定 adb 路径
python run.py --server-name my_server      # 设备上的 server 二进制名(默认 frida-server)
```

## 使用步骤

1. 手机开启 **USB 调试**（有线）或 `adb tcpip 5555`（无线）。
2. PC 上点「**刷新设备**」→ 下拉框选目标设备。
3. 若设备上还没有 server：填本机编译好的 server 二进制路径 →「**自动启动 frida-server**」。
4. 「进程 / 应用」页 → 刷新 → 选中目标进程点「**附加**」，或点「**spawn 启动**」填包名。
5. 「脚本」页 → 编辑 JS →「**运行**」，在控制台看输出。
6. 「**RPC 调用**」页 → 运行脚本后点「刷新导出」，选中函数填 JSON 参数 →「调用」。

### 脚本模板库 & RPC 快速上手

- 在「脚本」页顶部的**模板库下拉框**选一个模板 →「插入模板」，脚本会插入标注段，改好目标即可运行。
- 想在右侧 RPC 面板调用某个函数，只需在 JS 里写：
  ```js
  rpc.exports.hello = function (name) { return "hello, " + name; };
  ```
  运行后到「RPC 调用」页点「刷新导出」，填 `"World"` →「调用」。

## 目录结构

```
gui-client/
├── run.py                      # 启动入口
├── requirements.txt
└── companion/
    ├── core/
    │   ├── config.py           # 端口/端口范围/主题/快速模板 等配置
    │   ├── adb.py              # adb 封装：USB/无线、转发、push、启动 server
    │   ├── frida_device.py     # frida 设备连接(经 adb 转发)与进程/应用枚举
    │   ├── session_mgr.py      # attach/spawn/脚本生命周期/RPC
    │   └── templates.py        # 常用脚本模板库(11 个示例)
    └── ui/
        ├── theme.py            # 暗色主题 QSS
        ├── device_panel.py     # 设备连接区
        ├── process_panel.py    # 进程/应用 + attach/spawn + 自动刷新
        ├── script_panel.py     # JS 编辑器 + 控制台 + 模板库 + 打开/保存
        ├── rpc_panel.py        # RPC 导出列表与调用
        ├── inspector_panel.py  # 模块/导出/dlopen/hook 模板
        └── main_window.py      # 主窗口与装配
```

## 关于自定义端口的一点说明

官方 `frida.get_usb_device()` 会走 frida 内置 adb 并**固定转发 27042**。本项目反检测版端口改为 20442，因此本客户端**不用**内置 usb device，而是自己 `adb forward` 到 `config.CONTROL_PORT` 后 `add_remote_device` 连接。这样官方与反检测 server 都能用同一套代码连接，USB / 无线逻辑统一。

> 注意：反检测版 frida 还改动了 D-Bus / 线程 / 路径等标识，请使用与本客户端**同批编译**的 `frida-server`，避免与协议层面的配套不一致。