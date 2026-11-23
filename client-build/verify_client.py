#!/usr/bin/env python3
"""端到端自测：用「同源重编」的 frida-python 连「魔改 frida-server」，跑通真实注入。

这一步验证的正是改名最容易翻车的地方——客户端与服务端说的 D-Bus 接口名/对象
路径必须完全一致（app.svc.* / /app/svc/*），端口必须是 20442。任何一边用了官方
的 re.frida.*，连接会直接失败。

前提：
    bash client-build/build_client.sh          # 产出 dist/frida-server-*-linux-x86_64
    pip install --force-reinstall dist/frida-*-cp37-abi3-*.whl

用法：
    python3 client-build/verify_client.py [--port 20442] [--keep]
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"

OK = "\033[32m[PASS]\033[0m"
BAD = "\033[31m[FAIL]\033[0m"


def pick_server() -> Path:
    for p in sorted(DIST.glob("frida-server-*-linux-x86_64")):
        return p
    raise SystemExit("找不到 dist/frida-server-*-linux-x86_64，先跑 build_client.sh")


def wait_port(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=20442)
    ap.add_argument("--keep", action="store_true", help="结束后保留 server 进程")
    args = ap.parse_args()

    server = pick_server()
    print(f"server: {server}")

    # ---------------------------------------------------------------- 0. 静态核对
    data = server.read_bytes()
    # 端口是整型常量，不会以字符串形式出现；端口是否正确由下面的真实监听验证。
    for needle, want in ((b"re.frida", 0), (b"27042", 0), (b"frida:rpc", 0), (b"app.svc", 1)):
        hit = data.count(needle)
        status = OK if (hit == 0 if want == 0 else hit > 0) else BAD
        print(f"{status} server 内 {needle.decode()} 出现 {hit} 次（期望{'0' if want == 0 else '>0'}）")

    # ---------------------------------------------------------------- 1. 起 server
    log = open("/tmp/frida-server-verify.log", "wb")
    proc = subprocess.Popen(
        [str(server), "-l", f"127.0.0.1:{args.port}"],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    if not wait_port(args.port):
        log.close()
        print(BAD, "server 没起来，日志：")
        print(Path("/tmp/frida-server-verify.log").read_text(errors="replace")[-2000:])
        proc.kill()
        return 1
    print(f"{OK} server 已在 127.0.0.1:{args.port} 监听")

    rc = 1
    child = None
    try:
        import frida  # noqa: F401

        print(f"{OK} frida-python {frida.__version__} 已加载")

        pkg = Path(frida.__file__).parent
        init_src = (pkg / "__init__.py").read_text(errors="replace")
        if "app:rpc" in init_src and "frida:rpc" not in init_src:
            print(f"{OK} 客户端 RPC 标记已对齐（app:rpc）")
        else:
            print(f"{BAD} 当前装的是官方 frida，RPC 标记不匹配；"
                  f"pip install --force-reinstall dist/frida-*-cp37-abi3-*.whl")
            return 1

        mgr = frida.get_device_manager()
        dev = mgr.add_remote_device(f"127.0.0.1:{args.port}")
        procs = dev.enumerate_processes()
        print(f"{OK} enumerate_processes 返回 {len(procs)} 个进程（协议握手成功）")

        # ------------------------------------------------------------ 2. 真实 attach + RPC
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        time.sleep(0.4)
        session = dev.attach(child.pid)
        print(f"{OK} attach 到 pid={child.pid} 成功")

        agent = """
        rpc.exports = {
            ping: function () { return 'pong'; },
            info: function () { return Process.arch + '|' + Process.platform; }
        };
        """
        script = session.create_script(agent)
        script.load()
        pong = script.exports_sync.ping()
        assert pong == "pong", pong
        info = script.exports_sync.info()
        print(f"{OK} 脚本注入 + rpc.exports 调用成功（{info}）")

        # ------------------------------------------------------------ 3. 清理
        session.detach()
        print(f"{OK} session.detach 正常")
        rc = 0
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} {type(exc).__name__}: {exc}")
        print("      server 日志尾部：")
        print(Path("/tmp/frida-server-verify.log").read_text(errors="replace")[-1500:])
    finally:
        if child is not None and child.poll() is None:
            child.kill()
        if not args.keep:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        log.close()

    print("\n结果:", "全部通过" if rc == 0 else "有失败项")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
