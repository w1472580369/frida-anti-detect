"""主窗口：设备面板 + 进程 / 脚本 / 检查器 三个标签页。"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox, QTabWidget, QVBoxLayout,
    QWidget,
)

from ..core import config
from ..core import frida_device as fd
from ..core.session_mgr import SessionManager, TargetSession
from .device_panel import DevicePanel
from .inspector_panel import InspectorPanel
from .process_panel import ProcessPanel
from .rpc_panel import RpcPanel
from .script_panel import ScriptPanel
from . import theme


def run_app() -> int:
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("Frida Companion")
    app.setStyleSheet(theme.qss())
    win = MainWindow()
    win.show()
    return app.exec()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Frida 反检测配套 GUI — PC 客户端")
        self.resize(1180, 760)
        self._devices: List[fd.ManagedDevice] = []
        self._manager = SessionManager()
        self._build()

    # ---------------- 构建 ----------------
    def _build(self):
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(6, 6, 6, 6)

        self.device_panel = DevicePanel(self._toast, self._on_devices_changed)
        lay.addWidget(self.device_panel)

        self.tabs = QTabWidget()
        self.process_panel = ProcessPanel(self)
        self.script_panel = ScriptPanel(self)
        self.inspector_panel = InspectorPanel(self)
        self.rpc_panel = RpcPanel(self)
        self.tabs.addTab(self.process_panel, "进程 / 应用")
        self.tabs.addTab(self.script_panel, "脚本")
        self.tabs.addTab(self.rpc_panel, "RPC 调用")
        self.tabs.addTab(self.inspector_panel, "检查器")
        lay.addWidget(self.tabs, 1)

        self.setCentralWidget(central)
        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label, 1)
        self.hint = QLabel(f"默认 frida 控制端口 {config.CONTROL_PORT}（反检测版）")
        self.statusBar().addPermanentWidget(self.hint)

    # ---------------- 回调 / 公共接口 ----------------
    def _toast(self, level: str, text: str):
        colors = {"info": "#7ee787", "warn": "#e6b450", "error": "#ff7b72"}
        self.status_label.setStyleSheet("color:" + colors.get(level, "#d6e2ed"))
        self.status_label.setText(text)
        if level == "error":
            QMessageBox.warning(self, "提示", text)

    def _on_devices_changed(self, devices: List[fd.ManagedDevice]):
        self._devices = devices
        lhs = self._manager.active()
        if lhs:
            self.script_panel.reflect_target(lhs.device.serial, lhs.detail)

    def current_device(self) -> Optional[fd.ManagedDevice]:
        return self.device_panel.current_device()

    def current_session(self) -> Optional[TargetSession]:
        dev = self.current_device()
        return self._manager.get(dev.serial) if dev else None

    def attach_to(self, pid: int, name: str):
        dev = self.current_device()
        if dev is None:
            self._toast("warn", "未选择设备")
            return
        try:
            sess = TargetSession.attach(dev, pid)
            self._manager.set(dev.serial, sess)
            self.script_panel.reflect_target(dev.serial, f"attach {name}(pid={pid})")
            self._toast("info", f"已附加 {name} (pid={pid})")
            self.tabs.setCurrentWidget(self.script_panel)
        except Exception as exc:  # noqa: BLE001
            self._toast("error", f"附加失败: {exc}")

    def spawn_app(self, pkg: str, entry: str):
        dev = self.current_device()
        if dev is None:
            self._toast("warn", "未选择设备")
            return
        try:
            sess = TargetSession.spawn(dev, pkg, entry)
            self._manager.set(dev.serial, sess)
            self.script_panel.reflect_target(dev.serial, f"spawn {pkg}")
            self._toast("info", f"已 spawn {pkg}")
            self.tabs.setCurrentWidget(self.script_panel)
        except Exception as exc:  # noqa: BLE001
            self._toast("error", f"spawn 失败: {exc}")

    def closeEvent(self, event):
        for sess in [self._manager.active()]:
            if sess:
                try:
                    sess.detach()
                except Exception:  # noqa: BLE001
                    pass
        event.accept()