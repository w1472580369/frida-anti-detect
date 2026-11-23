#!/usr/bin/env python3
"""把 frida-python 的 Python 层 RPC 标记从 frida:rpc 改成 app:rpc。

背景：RPC 标记在三层都要一致，缺一层就「调用挂住、没有报错」——

  1. C/Vala 层  lib/base/rpc.vala            （libfrida-core，已由 tools/apply_mods.py 改）
  2. agent 层   gumjs runtime/*.js           （已由 tools/apply_mods.py 改）
  3. Python 层  frida_bindgen/assets/facade_rpc_*.py  ← 本脚本负责

第 3 层是 frida-bindgen 的代码模板，构建时才从 frida-python 子模块里取，所以
主仓的 apply_mods.py 覆盖不到。症状很有迷惑性：`script.post()` 双向通、
手工按协议发一条也能收到 agent 的正常回应，唯独 `script.exports_sync.xxx()`
永远阻塞——因为 Python 层在等 payload[0] == "frida:rpc" 的回包。

用法：
    python3 client-build/patch_client.py <frida-python 源码目录>
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGETS = [
    "frida/frida_bindgen/assets/facade_rpc_members.py",
    "frida/frida_bindgen/assets/facade_rpc_members_aio.py",
]
OLD = "frida:rpc"
NEW = "app:rpc"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"[x] 目录不存在: {root}")
        return 1

    changed = 0
    for rel in TARGETS:
        path = root / rel
        if not path.exists():
            print(f"[x] 缺少文件: {path}")
            return 1
        text = path.read_text(encoding="utf-8")
        n = text.count(OLD)
        if n == 0:
            if NEW in text:
                print(f"[=] {rel} 已改过")
                continue
            print(f"[x] {rel} 里既没有 {OLD} 也没有 {NEW}，版本可能变了")
            return 1
        path.write_text(text.replace(OLD, NEW), encoding="utf-8")
        changed += 1
        print(f"[+] {rel}: {OLD} → {NEW} × {n}")

    print(f"完成，改动 {changed} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
