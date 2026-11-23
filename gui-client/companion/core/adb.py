"""adb 封装：USB / 无线连接、端口转发、进程与 server 控制。

设计：本 GUI 不依赖 frida-python 内置的 adb 发现，而是自己用 adb 二进制
统一处理 **USB 与无线 adb** 两类设备（二者的区别只是 `adb connect` 是否先建立过
TCP 通道），然后对每个设备做 `adb forward` 到自定义控制端口，再交给 frida 层。
这样无论 frida-server 用的是官方 27042 还是本项目配套的 20442，都能稳定工作。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from . import config


class AdbError(RuntimeError):
    pass


@dataclass
class AdbDevice:
    """一行 `adb devices -l` 解析结果。"""
    serial: str            # 序列号，`adb -s <serial>` 用它
    state: str             # device / offline / unauthorized...
    transport: str = ""    # usb / tcpip / local...
    product: str = ""
    model: str = ""
    device: str = ""
    detail: str = ""
    is_wireless: bool = field(default=False)


def _find_adb() -> str:
    if config.ADB_PATH:
        return config.ADB_PATH
    on_path = shutil.which("adb")
    if on_path:
        return on_path
    # 常见 platform-tools 安装位置
    for cand in (
        os.path.expanduser("~/platform-tools/adb"),
        os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
        "/opt/android-sdk/platform-tools/adb",
        "/usr/local/platform-tools/adb",
    ):
        if os.path.isfile(cand):
            return cand
    raise AdbError(
        "未找到 adb。请安装 Android platform-tools，或用 --adb 参数指定 adb 路径；"
        "或用本界面「设置」里的路径输入框指定。"
    )


def adb_binary() -> str:
    return _find_adb()


def _run(adb_args: List[str], timeout: int = 30, check: bool = False) -> str:
    exe = _find_adb()
    cmd = [exe] + adb_args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise AdbError(f"无法执行 adb: {exe}")
    except subprocess.TimeoutExpired:
        raise AdbError("adb 命令超时")
    out = (proc.stdout or "") + (proc.stderr or "")
    out = out.strip()
    if check and proc.returncode != 0:
        raise AdbError(out or f"adb 命令失败: {' '.join(cmd)}")
    return out


def check_available() -> Optional[str]:
    """返回 None 表示可用，否则返回告警信息。"""
    try:
        _run(["version"])
        return None
    except Exception as e:  # noqa: BLE001
        return str(e)


def start_server() -> None:
    _run(["start-server"], check=True)


def kill_server() -> None:
    _run(["kill-server"])


def list_devices() -> List[AdbDevice]:
    """列出所有处于 device / offline / unauthorized 状态的设备。"""
    start_server()
    out = _run(["devices", "-l"], check=True)
    result: List[AdbDevice] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        meta = {}
        for tok in parts[2:]:
            if ":" in tok:
                k, _, v = tok.partition(":")
                meta[k] = v
        dev = AdbDevice(
            serial=serial,
            state=state,
            transport=meta.get("transport", ""),
            product=meta.get("product", ""),
            model=meta.get("model", ""),
            device=meta.get("device", ""),
            detail=line,
        )
        dev.is_wireless = (dev.transport == "tcpip" or ":" in serial)
        result.append(dev)
    return result


def connect_wireless(host: str, port: int) -> str:
    """`adb connect host:port`，返回输出。"""
    if ":" not in host:
        host = f"{host}:{port}"
    return _run(["connect", host], check=False)


def disconnect(serial: str) -> str:
    return _run(["disconnect", serial], check=False)


def forward(serial: str, local_port: int, remote_port: int) -> None:
    """`adb -s serial forward tcp:local tcp:remote`。"""
    _run(["-s", serial, "forward", f"tcp:{local_port}", f"tcp:{remote_port}"],
         check=True)


def remove_forward(serial: str, local_port: int) -> None:
    _run(["-s", serial, "forward", "--remove", f"tcp:{local_port}"], check=False)


def shell(serial: str, command: str, timeout: int = 30) -> str:
    """执行 `adb -s serial shell <command>`。"""
    out = _run(["-s", serial, "shell", command], timeout=timeout, check=False)
    return out


def push(serial: str, local: str, remote: str, timeout: int = 120) -> None:
    _run(["-s", serial, "push", local, remote], timeout=timeout, check=True)


def pull(serial: str, remote: str, local: str, timeout: int = 120) -> None:
    _run(["-s", serial, "pull", remote, local], timeout=timeout, check=True)


def list_forward(serial: str) -> List[str]:
    out = _run(["-s", serial, "forward", "--list"], check=False)
    return [x.strip() for x in out.splitlines() if x.strip()]


def is_process_running(serial: str, name: str) -> bool:
    cmds = [
        f"ps -A | grep -w {name}",
        f"pidof {name}",
    ]
    for c in cmds:
        try:
            out = shell(serial, c)
        except Exception:
            continue
        if out.strip():
            return True
    return False


def whoami(serial: str) -> str:
    return shell(serial, "id").strip()


def pick_free_forward_port(serial: str) -> int:
    """在配置的本地端口区间找一个未被占用的端口。"""
    used = set()
    try:
        for line in list_forward(serial):
            m = re.search(r"tcp:(\d+)", line)
            if m:
                used.add(int(m.group(1)))
    except Exception:
        pass
    for port in range(config.LOCAL_FORWARD_BASE, config.LOCAL_FORWARD_MAX):
        if port not in used:
            return port
    raise AdbError("本地转发端口空间已用完，请调整 LOCAL_FORWARD_BASE")


def install_and_start_server(serial: str, local_bin: str) -> str:
    """推送 frida-server 到设备并启动到自定义端口(或默认)。

    依赖设备 root(或已授权)。返回服务器输出摘要。
    """
    remote = f"/data/local/tmp/{config.SERVER_NAME}"
    push(serial, local_bin, remote)
    shell(serial, f"chmod 755 {remote}")
    # 若已运行先停掉
    shell(serial, f"pkill -f {config.SERVER_NAME} || true")
    start_cmd = f"nohup {remote} -l 0.0.0.0:{config.CONTROL_PORT} >/data/local/tmp/{config.SERVER_NAME}.log 2>&1 &"
    # 尝试以 root 运行，失败回退为普通方式
    su = shell(serial, f"su -c '{start_cmd}'")
    if "not found" in su or "denied" in su:
        shell(serial, f"sh -c '{start_cmd}'")
    return shell(serial, f"cat /data/local/tmp/{config.SERVER_NAME}.log 2>/dev/null || true")


def top_app_package(serial: str) -> Optional[str]:
    """尽力取前台应用包名（不保证兼容所有 ROM）。"""
    try:
        line = shell(serial, "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
        m = re.search(r"([/\w.]+)/[\w.]+\}", line)
        if m:
            return m.group(1)
    except Exception:
        return None
    return None