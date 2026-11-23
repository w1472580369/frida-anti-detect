#!/usr/bin/env python3
"""把 meson 构建出来的 frida-python 模块装配成可 pip 安装的 wheel。

为什么需要这一步：frida-python 的 meson 构建只产出 `_frida.abi3.so` 和若干
生成的 .py，没有 wheel 目标。官方发版时用另一套脚本打包，这里做一个最小实现。

产物命名遵循 abi3 约定（扩展用 Py_LIMITED_API 3.7 编译），因此一个 wheel 可以
覆盖 Python 3.7+ 的所有小版本，文件名形如：

    frida-17.19.0-cp37-abi3-linux_x86_64.whl

用法：
    python3 make_wheel.py --build /opt/frida-client-build/src/build \
                          --out   ../dist \
                          [--plat linux_x86_64] [--version 17.19.0]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

PKG = "frida"
DIST_INFO_TMPL = "{name}-{version}.dist-info"


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[x] {msg}", file=sys.stderr)
    raise SystemExit(1)


def find_module_dir(build: Path) -> Path:
    """定位 meson 生成 frida 包的目录。"""
    candidates = sorted(build.glob("subprojects/frida-python/frida"))
    for d in candidates:
        if (d / "__init__.py").exists():
            return d
    # 兜底：全树搜索 _frida 扩展
    for ext in build.rglob("_frida*.so"):
        return ext.parent
    for ext in build.rglob("_frida*.pyd"):
        return ext.parent
    die(f"在 {build} 下找不到 frida-python 构建产物，先跑 build_client.sh")


def detect_version(mod_dir: Path) -> str:
    """版本号可能是字面量，也可能是 __version__ = _frida.__version__（动态）。"""
    text = (mod_dir / "__init__.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    if m:
        return m.group(1)
    # 动态版本：直接把构建产物 import 进来读
    sys.path.insert(0, str(mod_dir.parent))
    try:
        import importlib

        mod = importlib.import_module(mod_dir.name)
        return mod.__version__
    except Exception as exc:  # noqa: BLE001
        die(f"无法确定版本号（{exc}），请用 --version 指定")
    finally:
        sys.path.pop(0)


def detect_plat() -> str:
    if sys.platform.startswith("linux"):
        return "linux_" + _machine()
    if sys.platform == "darwin":
        return "macosx_11_0_" + _machine()
    if sys.platform in ("win32", "cygwin"):
        return "win_amd64" if _machine() == "x86_64" else "win_arm64"
    die(f"未知平台 {sys.platform}，请用 --plat 指定")


def _machine() -> str:
    import platform

    m = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "arm64", "aarch64": "aarch64"}.get(m, m)


def hash_b64(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True, help="meson build 目录")
    ap.add_argument("--out", required=True, help="wheel 输出目录")
    ap.add_argument("--plat", default=None, help="平台标签，如 linux_x86_64 / win_amd64")
    ap.add_argument("--version", default=None, help="覆盖版本号（默认读 __init__.py）")
    args = ap.parse_args()

    build = Path(args.build).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    mod_dir = find_module_dir(build)
    version = args.version or detect_version(mod_dir)
    plat = args.plat or detect_plat()

    exts = list(mod_dir.glob("_frida*.so")) + list(mod_dir.glob("_frida*.pyd"))
    if not exts:
        die(f"{mod_dir} 下没有 _frida 扩展")
    ext = exts[0]

    files: dict[str, Path] = {}
    for name in ("__init__.py", "aio.py", "_frida.pyi"):
        p = mod_dir / name
        if p.exists():
            files[f"{PKG}/{name}"] = p
    files[f"{PKG}/{ext.name}"] = ext

    # 打一个标记文件：GUI 客户端靠它区分「配套客户端」和「官方 PyPI 客户端」
    marker = Path(tempfile.mkdtemp()) / "ANTIDETECT"
    marker.write_text(
        "\n".join(
            [
                "protocol=anti-detect",
                f"version={version}",
                "dbus_prefix=app.svc.",
                "object_prefix=/app/svc/",
                "control_port=20442",
                "cluster_port=20452",
                "rpc_channel=app:rpc",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files[f"{PKG}/ANTIDETECT"] = marker

    # py.typed 来自源码树
    for parent in [mod_dir, *mod_dir.parents]:
        cand = parent / "frida" / "py.typed"
        if cand.exists():
            files[f"{PKG}/py.typed"] = cand
            break

    wheel_name = f"{PKG}-{version}-cp37-abi3-{plat}.whl"
    wheel_path = out / wheel_name

    dist_info = DIST_INFO_TMPL.format(name=PKG, version=version)
    metadata = "\n".join(
        [
            "Metadata-Version: 2.1",
            f"Name: {PKG}",
            f"Version: {version}",
            "Summary: Dynamic instrumentation toolkit for developers, reverse-engineers, and security researchers (anti-detect build)",
            "Home-page: https://frida.re",
            "License: wxWindows Library Licence, Version 3.1",
            "Requires-Python: >=3.7",
            "",
        ]
    )
    wheel_meta = "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: frida-antidetect-client-build",
            "Root-Is-Purelib: false",
            f"Tag: cp37-abi3-{plat}",
            "",
        ]
    )

    records: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / "stage"
        for arcname, src in files.items():
            dst = stage / arcname
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        (stage / dist_info).mkdir(parents=True, exist_ok=True)
        (stage / dist_info / "METADATA").write_text(metadata, encoding="utf-8")
        (stage / dist_info / "WHEEL").write_text(wheel_meta, encoding="utf-8")

        for path in sorted(stage.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(stage).as_posix()
            data = path.read_bytes()
            records.append(f"{rel},sha256={hash_b64(data)},{len(data)}")
        records.append(f"{dist_info}/RECORD,,")
        (stage / dist_info / "RECORD").write_text("\n".join(records) + "\n", encoding="utf-8")

        with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(stage).as_posix())

    size_mb = wheel_path.stat().st_size / (1024 * 1024)
    print(f"[ok] {wheel_path}  ({size_mb:.1f} MB)")
    print(f"     包内文件: {', '.join(sorted(files))}")
    print(f"     安装: pip install --force-reinstall {wheel_path.name}")


if __name__ == "__main__":
    main()
