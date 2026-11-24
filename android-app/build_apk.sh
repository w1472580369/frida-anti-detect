#!/usr/bin/env bash
# 手工构建 Frida Phone APK（无需 Gradle / Android Studio）
#
# 注意：本项目所在的云盘挂载有两个限制：
#   1) aapt2 的 mmap 写入会得到全零文件 -> 所有中间产物在 /tmp 本地盘生成；
#   2) 扩展名为 .apk 的文件会被写成全零 -> 成品落盘为 .apk.bin，并额外打一个 zip。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BT="$ROOT/toolchain/bt/android-15"
JAR="$ROOT/toolchain/android-35/android.jar"
JDK="$ROOT/toolchain/jdk-17.0.13+11"
WORK="${FP_WORK:-/tmp/frida-phone-build}"
KS="$WORK/debug.keystore"
NAME="FridaPhone-1.1"

export PATH="$JDK/bin:$PATH"

echo "[0/8] 准备本地构建目录 $WORK"
rm -rf "$WORK"
mkdir -p "$WORK/compiled" "$WORK/classes" "$WORK/dex" "$WORK/gen"
cp -r "$HERE/res" "$HERE/assets" "$HERE/java" "$HERE/jniLibs" "$HERE/AndroidManifest.xml" "$WORK/"

if [ -f "$HERE/keystore/debug.keystore.b64" ]; then
  base64 -d "$HERE/keystore/debug.keystore.b64" > "$KS"
else
  "$JDK/bin/keytool" -genkeypair -keystore "$KS" -storepass android -keypass android \
    -alias androiddebugkey -dname "CN=Android Debug,O=Android,C=US" \
    -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
  mkdir -p "$HERE/keystore"
  base64 -w0 "$KS" > "$HERE/keystore/debug.keystore.b64"
fi

echo "[1/8] aapt2 compile"
"$BT/aapt2" compile --dir "$WORK/res" -o "$WORK/compiled/res.zip"

echo "[2/8] aapt2 link"
"$BT/aapt2" link \
  -o "$WORK/base.apk" \
  -I "$JAR" \
  --manifest "$WORK/AndroidManifest.xml" \
  -A "$WORK/assets" \
  --java "$WORK/gen" \
  --auto-add-overlay \
  --min-sdk-version 26 \
  --target-sdk-version 34 \
  --version-code 2 \
  --version-name 1.1 \
  "$WORK/compiled/res.zip"

echo "[3/8] javac"
find "$WORK/java" "$WORK/gen" -name '*.java' > "$WORK/sources.txt"
"$JDK/bin/javac" -source 8 -target 8 -encoding UTF-8 \
  -bootclasspath "$JAR" -classpath "$JAR" \
  -d "$WORK/classes" @"$WORK/sources.txt"

echo "[4/8] d8"
find "$WORK/classes" -name '*.class' > "$WORK/classes.txt"
"$BT/d8" --release --min-api 26 --lib "$JAR" --output "$WORK/dex" @"$WORK/classes.txt"

echo "[5/8] 组装"
python3 - "$WORK" <<'PYEOF'
import os, shutil, sys, zipfile
work = sys.argv[1]
base = os.path.join(work, "base.apk")
unaligned = os.path.join(work, "unaligned.apk")
shutil.copyfile(base, unaligned)
with zipfile.ZipFile(unaligned, "a", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    z.write(os.path.join(work, "dex", "classes.dex"), "classes.dex")
    libdir = os.path.join(work, "jniLibs", "arm64-v8a")
    for name in sorted(os.listdir(libdir)):
        if name.endswith(".so"):
            z.write(os.path.join(libdir, name), "lib/arm64-v8a/" + name,
                    compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
print("assembled", os.path.getsize(unaligned), "bytes")
PYEOF

echo "[6/8] 对齐"
"$BT/zipalign" -f -p 4 "$WORK/unaligned.apk" "$WORK/aligned.apk"

echo "[7/8] 签名"
"$BT/apksigner" sign \
  --ks "$KS" --ks-key-alias androiddebugkey \
  --ks-pass pass:android --key-pass pass:android \
  --out "$WORK/$NAME.apk" "$WORK/aligned.apk"

echo "[8/8] 回传 + 校验"
mkdir -p "$ROOT/dist"
python3 - "$WORK" "$ROOT" <<'PYEOF'
import hashlib, os, sys, zipfile
work, root = sys.argv[1], sys.argv[2]
src = os.path.join(work, "FridaPhone-1.0.apk")
raw = os.path.join(root, "dist", "FridaPhone-1.0.apk.bin")
zpath = os.path.join(root, "dist", "FridaPhone-1.0-apk.zip")

def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def copy(src, dst):
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            b = fi.read(1024 * 1024)
            if not b:
                break
            fo.write(b)
        fo.flush()
        os.fsync(fo.fileno())

copy(src, raw)
if md5(src) != md5(raw):
    raise SystemExit("回传校验失败: " + md5(src) + " != " + md5(raw))

readme = """Frida Phone 1.0 安装说明

1. 将 FridaPhone-1.0.apk 安装到 arm64 Android 手机（Android 8.0+）。
2. 手机需要 root（Magisk / KernelSU 均可），首次启动授予通知权限。
3. 打开 App，在“进程”页选择目标应用 -> 附加；在“脚本”页运行 JS。
4. “设置”页可查看 MCP 端点与令牌，AI 客户端通过
   http://手机IP:8765/mcp 调用（Authorization: Bearer 令牌）。
5. “设置”页可启动随包内置的兼容版 frida-server（端口 20442），官方 frida-tools 可直接连接。
6. “说明”页列出端口、兼容版 server 与 patched injector 的命名差异、文件路径、PC frida-tools 命令和 MCP 示例，可直接复制。

注意：兼容版 server 保留官方 re.frida.* D-Bus 协议名，路径、端口、线程名仍已处理；
App 内注入器为 patched frida-inject 17.19.0，内部使用 app.svc.*、svc-eternal/main-loop，
helper dex 由源码重建并含 Android 12 / MIUI systemMain 回退。
源码树与 GitHub Actions 支持 compat / stealth 两种构建；stealth 版 server 使用 app.svc，
必须搭配项目构建的 patched frida wheel。
"""

with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
    z.write(src, "FridaPhone-1.0.apk")
    zi = zipfile.ZipInfo("安装说明.txt")
    zi.date_time = (2026, 11, 18, 22, 0, 0)
    z.writestr(zi, readme)

with zipfile.ZipFile(zpath) as z:
    inner = z.read("FridaPhone-1.0.apk")
    if hashlib.md5(inner).hexdigest() != md5(src):
        raise SystemExit("zip 内 APK 校验失败")
print("apk md5:", md5(src))
print("zip:", zpath, os.path.getsize(zpath), "bytes")
PYEOF

echo
echo "完成: $ROOT/dist/FridaPhone-1.0-apk.zip"
ls -lh "$ROOT/dist/FridaPhone-1.0-apk.zip" "$ROOT/dist/FridaPhone-1.0.apk.bin"
"$BT/apksigner" verify --print-certs "$WORK/$NAME.apk" | head -6
