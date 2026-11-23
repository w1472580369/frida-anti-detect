"""设备连接面板：USB / 无线 adb 两种连接，以及 frida-server 管理。"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ..core import adb, config
from ..core import frida_device as fd


class DevicePanel(QWidget):
    """顶部设备连接区。

    通过回调把 "就绪的 ManagedDevice 列表" 上报给主窗口，GUI 各处据此切换当前设备。
    """

    def __init__(self, on_status: Callable[[str, str], None],
                 on_devices_changed: Callable[[list], None], parent=None):
        super().__init__(parent)
        self._on_status = on_status
        self._on_devices_changed = on_devices_changed
        self._managed: Dict[str, fd.ManagedDevice] = {}

        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        # --- 设备下拉与操作 ---
        row_main = QHBoxLayout()
        self.status = QLabel("adab 未检测")
        self.status.setStyleSheet("color:" + config.THEME["warn"])
        self.device_box = QComboBox()
        self.device_box.setMinimumWidth(320)
        self.btn_refresh = QPushButton("刷新设备")
        self.btn_con_usb = QPushButton("连接 USB")
        self.btn_con_usb.clicked.connect(self.connect_usb)
        self.btn_refresh.clicked.connect(self.refresh)
        row_main.addWidget(QLabel("设备："))
        row_main.addWidget(self.device_box, 1)
        row_main.addWidget(self.btn_refresh)
        row_main.addWidget(self.btn_con_usb)
        lay.addLayout(row_main)

        # --- 无线 / server 行 ---
        row2 = QHBoxLayout()
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("无线 adb 地址 IP[:端口]")
        self.btn_con_wireless = QPushButton("无线连接")
        self.btn_con_wireless.clicked.connect(self.connect_wireless)
        self.btn_start_srv = QPushButton("自动启动 frida-server")
        self.btn_start_srv.clicked.connect(self.start_server)
        row2.addWidget(self.ip_edit, 1)
        row2.addWidget(self.btn_con_wireless)
        row2.addWidget(self.btn_start_srv)
        lay.addLayout(row2)

        # 设置小行
        row3 = QHBoxLayout()
        self.adb_edit = QLineEdit()
        self.adb_edit.setPlaceholderText("adb 路径(可留空自动探测)")
        self.port_edit = QLineEdit(str(config.CONTROL_PORT))
        self.port_edit.setMaximumWidth(70)
        self.srvname_edit = QLineEdit(config.SERVER_NAME)
        self.srvname_edit.setMaximumWidth(140)
        self.server_bin_edit = QLineEdit()
        self.server_bin_edit.setPlaceholderText("本机 frida-server 二进制路径(启动时用)")
        self.btn_apply = QPushButton("应用设置")
        self.btn_apply.clicked.connect(self.apply_settings)
        row3.addWidget(QLabel("adb:"))
        row3.addWidget(self.adb_edit, 1)
        row3.addWidget(QLabel("端口:"))
        row3.addWidget(self.port_edit)
        row3.addWidget(QLabel("server名:"))
        row3.addWidget(self.srvname_edit)
        row3.addWidget(self.btn_apply)
        lay.addLayout(row3)

    # ---------------- 配置 ----------------
    def apply_settings(self):
        if self.adb_edit.text().strip():
            config.ADB_PATH = self.adb_edit.text().strip()
        try:
            config.CONTROL_PORT = int(self.port_edit.text().strip())
        except ValueError:
            self._on_status("warn", "端口必须为数字")
            return
        if self.srvname_edit.text().strip():
            config.SERVER_NAME = self.srvname_edit.text().strip()
        self._on_status("info", "设置已应用")
        self.refresh()

    # ---------------- 连接 ----------------
    def refresh(self):
        self._managed = {}
        try:
            err = adb.check_available()
            if err:
                self._on_status("error", err)
                self.status.setText("adb 不可用")
                return
            devs = adb.list_devices()
        except Exception as exc:  # noqa: BLE001
            self._on_status("error", f"adb 错误: {exc}")
            return
        ok_devs = [d for d in devs if d.state == "device"]
        if not ok_devs:
            self._on_status("warn", "未发现已连接的 adb 设备")
            self.reload_box([])
            self.status.setText("无设备")
            return
        managed, errors = fd.connect_all(ok_devs)
        for e_serial, emsg in errors:
            self._on_status("warn", f"转发失败 {e_serial}: {emsg}")
        if managed:
            self._on_status("info", f"已连接 {len(managed)} 个设备(frida端口 {config.CONTROL_PORT})")
        self._managed = {m.serial: m for m in managed}
        self.reload_box(managed)
        self.status.setText(f"{len(managed)} 台已就绪" if managed else "连接失败")

    def connect_usb(self):
        # 先杀掉可能残留的转发，然后统一走 refresh 的重连逻辑
        adb.kill_server()
        self.refresh()

    def connect_wireless(self):
        text = self.ip_edit.text().strip()
        if not text:
            self._on_status("warn", "请填写无线 adb 地址")
            return
        try:
            adb.connect_wireless(text, config.ADB_WIRELESS_PORT)
        except Exception as exc:  # noqa: BLE001
            self._on_status("error", f"无线连接失败: {exc}")
            return
        self._on_status("info", f"无线 adb: {text}")
        self.refresh()

    def start_server(self):
        dev = self.current_device()
        if dev is None:
            self._on_status("warn", "请先连接设备")
            return
        if not self.server_bin_edit.text().strip():
            self._on_status("warn", "请填写本机 frida-server 二进制路径")
            return
        try:
            summary = adb.install_and_start_server(dev.serial, self.server_bin_edit.text().strip())
            self._on_status("info", f"frida-server 已在 {dev.serial} 启动(端口 {config.CONTROL_PORT})")
            if summary:
                self._on_status("info", "server 日志: " + summary[-200:])
        except Exception as exc:  # noqa: BLE001
            self._on_status("error", f"启动失败: {exc}")
        # 启动后重连到新端口
        self.refresh()

    # ---------------- 对外接口 ----------------
    def reload_box(self, managed: list):
        self.device_box.clear()
        for m in managed:
            self.device_box.addItem(m.name, m.serial)
        self._on_devices_changed(managed)

    def current_device(self) -> Optional[fd.ManagedDevice]:
        idx = self.device_box.currentIndex()
        if idx < 0:
            return None
        serial = self.device_box.itemData(idx)
        return self._managed.get(serial)