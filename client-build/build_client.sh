#!/usr/bin/env bash
# 构建「与魔改 frida-server 协议配套」的 frida-python 客户端（同源重编）。
#
# 为什么需要它：
#   本项目把 D-Bus 接口名与对象路径从 re.frida.* / /re/frida/* 改成了
#   app.svc.* / /app/svc/*，同时把控制端口改成 20442。官方 PyPI 的 frida 包
#   仍然说 re.frida.*，连上会直接被服务端拒绝，所以 PC 端必须用同一份源码重编。
#
# 用法：
#   bash client-build/build_client.sh                  # 默认 linux-x86_64
#   bash client-build/build_client.sh linux-arm64
#   bash client-build/build_client.sh macos-arm64      # 需在 macOS + Xcode 上跑
#   bash client-build/build_client.sh windows-x86_64   # 需在 Windows + MSVC 上跑
#
# 可选环境变量：
#   FRIDA_CLIENT_WORK  构建工作目录，必须 ASCII 路径（默认 /opt/frida-client-build）
#   FRIDA_SRC          已打补丁的源码树（默认 <repo>/frida）
#   JOBS               ninja 并发数（默认 1，1 核小机器别调大）
#   SKIP_SERVER=1      不构建同架构 frida-server（少几分钟，但没法做端到端自测）
#
# 产物：
#   dist/frida-<ver>-cp37-abi3-<plat>.whl
#   dist/frida-server-<ver>-<host>（未 SKIP_SERVER 时，仅用于本机协议自测）
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${1:-linux-x86_64}"
WORK="${FRIDA_CLIENT_WORK:-/opt/frida-client-build}"
SRC="${FRIDA_SRC:-$REPO/frida}"
JOBS="${JOBS:-1}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

ascii_only() {
    # 有非 ASCII 字符时 grep 退出码为 0
    printf '%s' "$1" | LC_ALL=C grep -q '[^ -~]'
}

# ---------------------------------------------------------------- 0. 前置检查
[ -d "$SRC" ] || die "源码树不存在: $SRC"
grep -q 'app\.svc\.HostSession17' "$SRC/subprojects/frida-core/lib/base/session.vala" \
    || die "源码树还没打补丁，先执行: python3 tools/apply_patches.py"

if ascii_only "$WORK"; then
    die "工作目录含非 ASCII 字符（meson 子进程会 UnicodeDecodeError）: $WORK
    请设置 FRIDA_CLIENT_WORK 到一个纯 ASCII 路径，例如 /opt/frida-client-build"
fi

BUILD_SRC="$WORK/src"
DEPS="$WORK/deps"
NESTED="$WORK/nested"
mkdir -p "$WORK" "$DEPS" "$NESTED"

# ---------------------------------------------------------------- 1. 源码搬到 ASCII 路径
if [ ! -f "$BUILD_SRC/meson.build" ]; then
    step "复制源码到 ASCII 工作路径 $BUILD_SRC"
    mkdir -p "$BUILD_SRC"
    # FUSE 云盘上的 mtime 不稳定，tar 会报 "file changed as we read it" 并以 1 退出，
    # 在 set -o pipefail 下会直接中断构建；这些警告可以安全忽略。
    ( cd "$SRC" && tar -cf - --warning=no-file-changed --warning=no-timestamp \
        --exclude=.git --exclude=build --exclude='build-*' --exclude=deps . ) \
        | tar -xf - --warning=no-file-changed --warning=no-timestamp -C "$BUILD_SRC"
else
    # 副本是复用的：源码树里改了补丁（比如 JS/TS 里的协议标记）必须同步过去，
    # 否则会拿旧副本构建，产物看起来"没生效"。
    step "同步源码改动到 $BUILD_SRC"
    for _sp in frida-core frida-gum; do
        # FUSE 上 tar 常以 1 退出（"file changed as we read it"），pipefail 下会误杀构建，
        # 这里降级成告警；真正的完整性由下面那行断言兜底。
        tar -C "$SRC/subprojects/$_sp" -cf - --warning=no-file-changed --warning=no-timestamp \
            --exclude=.git --exclude=build . \
            | tar -xf - --warning=no-file-changed --warning=no-timestamp \
                -C "$BUILD_SRC/subprojects/$_sp" \
            || echo "[warn] 同步 $_sp 时有告警（不影响构建）"
    done
    grep -q '"app:rpc"' "$BUILD_SRC/subprojects/frida-core/src/barebone/script-runtime/message-dispatcher.ts" \
        || die "同步后 barebone 运行时仍是旧标记，检查源码树是否已打补丁"
fi

# 源码树里的版本号来自 git describe；ASCII 副本没有 .git 会退化成 0.0.0，
# 这里给副本打一个最小快照仓库并打上 tag，让 meson 拿到真实版本。
FRIDA_VER="$(git -C "$SRC" describe --tags --always 2>/dev/null || echo 0.0.0)"
if [ ! -d "$BUILD_SRC/.git" ]; then
    step "给构建副本建立版本快照（$FRIDA_VER）"
    printf 'build/\ndeps/\n' > "$BUILD_SRC/.gitignore"
    git -C "$BUILD_SRC" init -q
    git -C "$BUILD_SRC" -c user.email=build@local -c user.name=build add -A
    git -C "$BUILD_SRC" -c user.email=build@local -c user.name=build commit -qm "build snapshot"
    git -C "$BUILD_SRC" tag -f "$FRIDA_VER" >/dev/null
fi

# ---------------------------------------------------------------- 2. releng 的两个子模块
# releng 用 git submodule 指针锁定 meson / tomlkit 的精确版本；必须按指针取，
# 直接 clone 默认分支会拿到新版 meson（UserArrayOption 已从 coredata 迁走），
# configure 会直接 ImportError。
pin_of() {
    git -C "$SRC/releng" ls-tree HEAD "$1" 2>/dev/null | awk '{print $3}'
}

fetch_at() { # <url> <dst> <commit>
    local url="$1" dst="$2" commit="$3"
    rm -rf "$dst"
    git init -q "$dst"
    git -C "$dst" remote add origin "$url"
    if [ -n "$commit" ]; then
        git -C "$dst" fetch -q --depth 1 origin "$commit"
        git -C "$dst" checkout -q FETCH_HEAD
    else
        git -C "$dst" fetch -q --depth 1 origin HEAD
        git -C "$dst" checkout -q FETCH_HEAD
    fi
}

MESON_PIN="$(pin_of meson)"
TOMLKIT_PIN="$(pin_of tomlkit)"

if [ ! -f "$NESTED/meson/mesonbuild/coredata.py" ] \
    || { [ -n "$MESON_PIN" ] && [ "$(git -C "$NESTED/meson" rev-parse HEAD 2>/dev/null)" != "$MESON_PIN" ]; }; then
    step "拉取 releng 锁定的 meson（${MESON_PIN:-default}）"
    fetch_at https://github.com/frida/meson.git "$NESTED/meson" "$MESON_PIN"
fi
rm -rf "$BUILD_SRC/releng/meson"
ln -sfn "$NESTED/meson" "$BUILD_SRC/releng/meson"

if [ ! -f "$NESTED/tomlkit/tomlkit/toml_file.py" ] \
    || { [ -n "$TOMLKIT_PIN" ] && [ "$(git -C "$NESTED/tomlkit" rev-parse HEAD 2>/dev/null)" != "$TOMLKIT_PIN" ]; }; then
    step "拉取 releng 锁定的 tomlkit（${TOMLKIT_PIN:-default}）"
    fetch_at https://github.com/python-poetry/tomlkit.git "$NESTED/tomlkit" "$TOMLKIT_PIN"
fi
rm -rf "$BUILD_SRC/releng/tomlkit"
ln -sfn "$NESTED/tomlkit" "$BUILD_SRC/releng/tomlkit"

# ---------------------------------------------------------------- 3. frida-python 子模块
if [ ! -f "$BUILD_SRC/subprojects/frida-python/meson.build" ]; then
    step "拉取 frida-python"
    rm -rf "$BUILD_SRC/subprojects/frida-python"
    git clone --depth 1 https://github.com/frida/frida-python.git \
        "$BUILD_SRC/subprojects/frida-python"
fi

if [ ! -f "$BUILD_SRC/subprojects/frida-python/frida-bindgen/frida_bindgen_core/__init__.py" ]; then
    step "拉取 frida-bindgen（frida-python 的子模块）"
    rm -rf "$BUILD_SRC/subprojects/frida-python/frida-bindgen"
    git clone --depth 1 https://github.com/frida/frida-bindgen.git \
        "$BUILD_SRC/subprojects/frida-python/frida-bindgen"
fi

# frida-python 的 Python 层 RPC 客户端硬编码了 "frida:rpc"，必须同步改名，
# 否则 script.exports_sync.xxx() 会永远阻塞（握手和 post 都正常，极易误判）
step "同步 Python 层 RPC 标记"
python3 "$REPO/client-build/patch_client.py" "$BUILD_SRC/subprojects/frida-python"

# ---------------------------------------------------------------- 4. deps
rm -rf "$BUILD_SRC/deps"
ln -sfn "$DEPS" "$BUILD_SRC/deps"

# ---------------------------------------------------------------- 5. 环境
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONUTF8=1 PYTHONIOENCODING=utf-8

# frida-python 的 meson.build 会用 `python3 setup.py -V` 取版本号，需要 setuptools
if ! python3 -c "import setuptools" >/dev/null 2>&1; then
    step "安装 setuptools（frida-python 构建需要）"
    python3 -m pip install -q setuptools wheel
fi
case "$HOST" in
    android-*)
        NDK="${ANDROID_NDK_ROOT:-/opt/android-sdk/android-ndk-r29}"
        [ -d "$NDK" ] || die "android 目标需要 NDK r29，未找到 $NDK"
        export ANDROID_NDK_ROOT="$NDK" ANDROID_NDK_HOME="$NDK"
        ;;
esac

# ---------------------------------------------------------------- 6. configure
step "configure --host=$HOST"
cd "$BUILD_SRC"
rm -rf build
./configure --host="$HOST" --enable-server --enable-frida-python --disable-frida-tools

# ---------------------------------------------------------------- 7. build
NINJA="$(ls -d "$DEPS"/toolchain-*/bin/ninja 2>/dev/null | head -1)"
[ -n "$NINJA" ] || NINJA="$(command -v ninja || true)"
[ -n "$NINJA" ] || die "找不到 ninja"

if [ "${SKIP_SERVER:-0}" = "1" ]; then
    TARGETS=(subprojects/frida-python/frida/_frida)
    step "构建 frida-python（跳过 server）"
else
    TARGETS=()
    step "构建全部目标（含同架构 frida-server，用于端到端自测）"
fi

"$NINJA" -C build -j"$JOBS" "${TARGETS[@]}"

# ---------------------------------------------------------------- 8. 打包 wheel
step "装配 wheel"
python3 "$REPO/client-build/make_wheel.py" --build "$BUILD_SRC/build" --out "$REPO/dist" --version "$FRIDA_VER"

# ---------------------------------------------------------------- 9. 顺手产出本机 server
if [ "${SKIP_SERVER:-0}" != "1" ] && [ -x "$BUILD_SRC/build/subprojects/frida-core/server/frida-server" ]; then
    OUT="$REPO/dist/frida-server-$FRIDA_VER-$HOST"
    cp "$BUILD_SRC/build/subprojects/frida-core/server/frida-server" "$OUT"
    chmod 755 "$OUT"
    echo "[ok] $OUT"
fi

step "完成"
echo "客户端安装:  pip install --force-reinstall dist/frida-*-cp37-abi3-*.whl"
echo "端到端自测:  python3 client-build/verify_client.py"
