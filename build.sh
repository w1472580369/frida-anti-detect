#!/usr/bin/env bash
# Anti-detection Frida 一键构建脚本
#
# 在算力充足的 Linux x86_64 机器（建议 >=4 核 / 8GB）上执行：
#   bash build.sh [arm64|arm]
#
# 脚本会：
#   1. 拉取 frida 源码及全部子模块
#   2. 下载并解压 Android NDK r29
#   3. 应用 tools/ 下的全部 anti-detection 补丁（幂等）
#   4. 重建中性包名的 helper.dex
#   5. 重建内嵌的 zymbiote 注入桩
#   6. 配置并编译 frida-server，产物复制到 dist/
#
# 可通过环境变量覆盖：ANDROID_NDK_ROOT（已存在的 NDK）、JOBS（并行度）。

set -euo pipefail

ARCH="${1:-arm64}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

case "$ARCH" in
  arm64) HOST="android-arm64"; BUILD_DIR="build" ;;
  arm)   HOST="android-arm";   BUILD_DIR="build-arm" ;;
  *) echo "unsupported arch: $ARCH (use arm64 or arm)"; exit 1 ;;
esac

JOBS="${JOBS:-$(nproc)}"
NDK_VERSION="r29"

# ------------------------------------------------------------ 1. 源码
echo "[1/6] 准备 Frida 源码..."
if [ ! -d frida/.git ]; then
  git clone --recurse-submodules https://github.com/frida/frida.git frida
else
  git -C frida submodule update --init --recursive
fi

# ------------------------------------------------------------ 2. NDK
if [ -z "${ANDROID_NDK_ROOT:-}" ] || [ ! -f "${ANDROID_NDK_ROOT:-/nonexistent}/source.properties" ]; then
  echo "[2/6] 下载 Android NDK $NDK_VERSION..."
  mkdir -p toolchain
  if [ ! -f "toolchain/ndk-$NDK_VERSION.zip" ]; then
    curl -fL -o "toolchain/ndk-$NDK_VERSION.zip" \
      "https://dl.google.com/android/repository/android-ndk-$NDK_VERSION-linux.zip"
  fi
  mkdir -p "$SCRIPT_DIR/toolchain/ndk"
  (cd "$SCRIPT_DIR/toolchain/ndk" && unzip -q -o "../ndk-$NDK_VERSION.zip")
  export ANDROID_NDK_ROOT="$SCRIPT_DIR/toolchain/ndk/android-ndk-$NDK_VERSION"
else
  echo "[2/6] 使用已有 NDK: $ANDROID_NDK_ROOT"
fi
export ANDROID_NDK_HOME="$ANDROID_NDK_ROOT"

# ------------------------------------------------------------ 3. 补丁
echo "[3/6] 应用 anti-detection 补丁..."
( cd frida && python3 ../tools/apply_patches.py )

# ------------------------------------------------------------ 4. helper.dex
echo "[4/6] 重建 helper.dex（中性包名 app.svc）..."
if [ ! -f toolchain/android-35/android.jar ]; then
  mkdir -p toolchain/platformdl
  curl -fL -o toolchain/platformdl/platform-35.zip \
    "https://dl.google.com/android/repository/platform-35_r02.zip"
  (cd toolchain && unzip -q -o platformdl/platform-35.zip)
fi
python3 tools/build_helper_dex.py --frida frida \
  --android-jar "$SCRIPT_DIR/toolchain/android-35/android.jar"

# ------------------------------------------------------------ 5. zymbiote
echo "[5/6] 重建内嵌 zymbiote 注入桩..."
python3 tools/build_zymbiote.py

# ------------------------------------------------------------ 6. 构建
echo "[6/6] 配置并编译 frida-server ($HOST)..."
cd frida
EXTRA_ENV=()
[ "$ARCH" != "arm64" ] && EXTRA_ENV=(MESON_BUILD_ROOT="$PWD/$BUILD_DIR")
env "${EXTRA_ENV[@]}" ./configure --host="$HOST"
"$SCRIPT_DIR/frida/deps/toolchain-linux-x86_64/bin/ninja" -C "$BUILD_DIR" \
  -j"$JOBS" subprojects/frida-core/server/frida-server
cd "$SCRIPT_DIR"

mkdir -p dist
OUT="dist/frida-server-17.19.0-android-$ARCH"
cp "frida/$BUILD_DIR/subprojects/frida-core/server/frida-server" "$OUT"

echo
file "$OUT"
for bad in "27042" "gum-js-loop" "re/frida" "frida:rpc" "frida-zymbiote"; do
  if strings "$OUT" | grep -q "$bad"; then
    echo "WARNING: legacy indicator still present: $bad"
  fi
done
echo
echo "完成 -> $OUT"
