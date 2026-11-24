# 源码包说明

本仓库是 FridaPhone / frida-anti-detect 的完整源码包，基于 Frida 17.19.0。

## 目录

- `frida/`：已应用反检测补丁的 Frida 源码树（含 frida-gum / frida-core 子模块内容）
- `patches/`：按文件拆分的补丁与 `series`，可在干净 Frida 17.19.0 上重放
- `tools/`：应用补丁、重建 helper.dex / zymbiote、切换 D-Bus 模式、魔改二进制
- `android-app/`：手机端 APK 工程（Java + WebView + 内置 MCP），含已构建的 arm64 二进制
- `client-build/`：stealth 模式配套 frida-python 客户端构建
- `gui-client/`：PC 桌面客户端
- `.github/workflows/`：源码构建、客户端 wheel 构建

## 两种 D-Bus 模式

```bash
# compat：保留 re.frida.*，官方 frida-tools 可直接连 20442
python3 tools/dbus_mode.py --mode compat

# stealth：改成 app.svc.*，PC 必须装配套 frida wheel
python3 tools/dbus_mode.py --mode stealth
```

## 从干净源码构建（Linux x86_64）

```bash
git clone --recurse-submodules --branch 17.19.0 https://github.com/frida/frida.git frida
python3 tools/apply_patches.py
python3 tools/dbus_mode.py --mode compat   # 或 stealth
python3 tools/build_helper_dex.py --frida frida --android-jar /path/android.jar
python3 tools/build_zymbiote.py
cd frida && ./configure --host=android-arm64
ninja -C build subprojects/frida-core/server/frida-server
ninja -C build subprojects/frida-core/inject/frida-inject
```

也可以直接推送到 GitHub，手动触发 `source-build` 工作流，选择 compat / stealth。

## 构建 APK

`android-app/jniLibs/arm64-v8a/` 已带本轮构建的 `libfinj.so` / `libfsrv.so`：

```bash
bash android-app/build_apk.sh
```

产物在 `dist/FridaPhone-1.3-apk.zip`。

## 重要取舍

官方客户端兼容与 `app.svc.*` 完全改名在 D-Bus 协议层互斥：

- compat：`re.frida.*`，官方客户端可用，其余反检测改动保留；
- stealth：`app.svc.*`，官方客户端不可用，必须配套 wheel。

APK 默认使用 compat server + patched injector（injector 内部仍是 `app.svc.*`）。
