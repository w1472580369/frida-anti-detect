"""Frida 设备层：把 adb 转发的 TCP 端点注册为 frida remote device。

说明：官方 frida 通过 `frida.get_usb_device()` 走它内置的 adb 并固定转发 27042。
本项目反检测版把控制端口改成了 20442，直接走内置 adb 会失配。因此这里统一使用
`adb forward` 到配置端口，再用 `add_remote_device()` 建立连接——**官方(27042)与
反检测(20442)两种 server 都能用**，同时 USB 与无线 adb 走同一套逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import adb, config


@dataclass
class ManagedDevice:
    """一个已通过 frida 连接成功的设备。"""
    serial: str
    model: str
    is_wireless: bool
    local_port: int          # 本机转发端口
    frida_device: object = field(repr=False)  # frida.core.Device
    _session: object = field(default=None, repr=False)  # frida session(attach/spawn 后)

    @property
    def name(self) -> str:
        tag = "无线" if self.is_wireless else "USB"
        return f"{self.model or self.serial} [{tag}] {self.serial}"


def ensure_frida() -> None:
    try:
        import frida  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "未安装 frida-python，请在 PC 上执行: pip install -r requirements.txt"
        ) from exc


def connect_serial(serial: str, is_wireless: bool, model: str = "") -> ManagedDevice:
    """对指定 adb serial 建立 frida 连接（内部自动做端口转发）。"""
    import frida  # 延迟导入，仅在使用时要求安装
    ensure_frida()

    local_port = adb.pick_free_forward_port(serial)
    device_port = config.CONTROL_PORT
    adb.forward(serial, local_port, device_port)
    try:
        mgr = frida.get_device_manager()
        dev = mgr.add_remote_device(f"127.0.0.1:{local_port}")
        # 触一发查询，验证连接真实可用
        dev.enumerate_processes()
    except Exception:
        adb.remove_forward(serial, local_port)
        raise
    return ManagedDevice(
        serial=serial,
        model=model,
        is_wireless=is_wireless,
        local_port=local_port,
        frida_device=dev,
    )


def connect_all(adb_devices: List[adb.AdbDevice]) -> List[ManagedDevice]:
    result: List[ManagedDevice] = []
    errors: List[tuple] = []
    for d in adb_devices:
        if d.state != "device":
            continue
        try:
            result.append(connect_serial(d.serial, d.is_wireless, d.model))
        except Exception as exc:  # noqa: BLE001
            errors.append((d.serial, str(exc)))
    return result, errors


# ---------------------------------------------------------------- 常用枚举
def list_processes(dev: ManagedDevice) -> List[dict]:
    procs = dev.frida_device.enumerate_processes()
    out = []
    for p in procs:
        name = p.name if hasattr(p, "name") else getattr(p, "parameters", "")
        out.append({"pid": p.pid, "name": name})
    return out


def frontmost_app(dev: ManagedDevice) -> Optional[str]:
    try:
        app = dev.frida_device.get_frontmost_application()
        if app and getattr(app, "identifier", None):
            return app.identifier
    except Exception:  # noqa: BLE001
        return None
    return None


def frontmost_pid(dev: ManagedDevice) -> Optional[int]:
    """前台应用的 PID（仅当属于已运行的应用时存在）。"""
    try:
        app = dev.frida_device.get_frontmost_application()
        if app:
            pid = getattr(app, "pid", None)
            if pid:
                return int(pid)
    except Exception:  # noqa: BLE001
        return None
    return None


def enumerate_apps(dev: ManagedDevice) -> List[dict]:
    try:
        apps = dev.frida_device.enumerate_applications()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for a in apps:
        out.append({
            "id": a.identifier,
            "name": a.name if hasattr(a, "name") else a.identifier,
            "pid": a.pid if hasattr(a, "pid") else None,
        })
    return out