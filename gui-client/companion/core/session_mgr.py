"""会话与脚本生命周期管理：attach / spawn / resume / load script / message 回调。"""
from __future__ import annotations

from typing import Callable, List, Optional

from . import frida_device as fd


class TargetSession:
    """绑定到某个目标进程(pid 或 app)的一次 frida 会话。"""

    def __init__(self, device: fd.ManagedDevice, session, detail: str):
        self.device = device
        self._session = session
        self.detail = detail
        self._script = None
        self._on_message: Optional[Callable[[str, object], None]] = None

    # ---------------- 会话 ----------------
    @classmethod
    def attach(cls, device: fd.ManagedDevice, pid: int) -> "TargetSession":
        sess = device.frida_device.attach(pid)
        return cls(device, sess, f"attach pid={pid}")

    @classmethod
    def spawn(cls, device: fd.ManagedDevice, package: str, entrypoint: str = "") -> "TargetSession":
        if entrypoint:
            sess = device.frida_device.spawn(package, main_module=entrypoint)
        else:
            sess = device.frida_device.spawn(package)
        return cls(device, sess, f"spawn {package}")

    @classmethod
    def attach_with_spawn(cls, device: fd.ManagedDevice, package: str,
                          entrypoint: str = "") -> "TargetSession":
        """spawn 后立刻 resume；常用于需要注入调试的注入点。"""
        raw = None
        if entrypoint:
            target = device.frida_device.spawn(package, main_module=entrypoint)
        else:
            target = device.frida_device.spawn(package)
        device.frida_device.resume(target.pid)
        raw = target
        return cls(device, raw, f"spawn+resume {package}")

    def resume(self) -> None:
        self._session.resume()

    def detach(self) -> None:
        try:
            self._session.detach()
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 脚本 ----------------
    def load_script(self, source: str,
                    on_message: Callable[[str, object], None]) -> None:
        self._on_message = on_message
        script = self._session.create_script(source)
        script.on("message", on_message)
        script.load()
        self._script = script

    def reload(self, source: str) -> None:
        if self._script is not None:
            self._script.unload()
        script = self._session.create_script(source)
        script.on("message", lambda msg, data: self._on_message(msg, data)
                  if self._on_message else None)
        script.load()
        self._script = script

    def unload(self) -> None:
        if self._script is not None:
            try:
                self._script.unload()
            except Exception:  # noqa: BLE001
                pass
            self._script = None

    # ---------------- RPC ----------------
    def call(self, name: str, *args):
        if self._script is None:
            raise RuntimeError("尚未加载脚本")
        fn = getattr(self._script.exports_sync, name, None)
        if fn is None:
            # 尝试通过 exports 句柄
            fn = self._script.exports_sync
            return fn[name](*args) if hasattr(fn, "__getitem__") else None
        return fn(*args)


class SessionManager:
    """维护 设备 -> 当前目标会话 的映射。"""

    def __init__(self):
        self._sessions: dict = {}  # serial -> Optional[TargetSession]

    def set(self, serial: str, session: Optional[TargetSession]) -> None:
        old = self._sessions.get(serial)
        if old:
            try:
                old.detach()
            except Exception:  # noqa: BLE001
                pass
        self._sessions[serial] = session

    def get(self, serial: str) -> Optional[TargetSession]:
        return self._sessions.get(serial)

    def active(self) -> Optional[TargetSession]:
        for s in list(self._sessions.values()):
            if s is not None:
                return s
        return None