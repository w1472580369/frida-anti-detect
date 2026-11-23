"""进程/应用面板：列出进程与前台应用，支持 附加(attach) 与 启动(spawn)。"""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QSortFilterProxyModel, QAbstractTableModel, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from ..core import config
from ..core import frida_device as fd


class ProcModel(QAbstractTableModel):
    _headers = ["PID", "名称"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[list] = []

    def set_rows(self, rows: List[list]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._rows)

    def columnCount(self, parent=None):
        return len(self._headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        val = self._rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return str(val)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._headers[section]
        return None


class SpawnDialog(QDialog):
    """spawn 参数：应用 ID(包名)，可选入口模块。"""

    def __init__(self, apps: List[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("spawn 启动应用")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.pkg_edit = QLineEdit()
        self.pkg_edit.setPlaceholderText("如 com.example.app")
        self.entry_edit = QLineEdit()
        self.entry_edit.setPlaceholderText("可选：入口模块 so(留空自动)")
        form.addRow("应用包名：", self.pkg_edit)
        form.addRow("入口模块：", self.entry_edit)
        if apps:
            hint = "， ".join(a["id"] for a in apps[:12])
            form.addRow(QLabel("可用应用(参考)："),
                        QLabel("…" + hint))
        btn = QPushButton("spawn")
        btn.setProperty("primary", True)
        btn.clicked.connect(self.accept)
        form.addRow(btn)

    def values(self):
        return self.pkg_edit.text().strip(), self.entry_edit.text().strip()


class ProcessPanel(QWidget):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host           # MainWindow
        self._model = ProcModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterKeyColumn(1)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("按名称过滤…")
        self.filter.textChanged.connect(self._proxy.setFilterFixedString)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_attach = QPushButton("附加(attach)")
        self.btn_attach.setProperty("primary", True)
        self.btn_attach.clicked.connect(self.attach_selected)
        self.btn_spawn = QPushButton("spawn 启动")
        self.btn_spawn.clicked.connect(self.spawn_dialog)
        self.show_apps = QCheckBox("显示应用")
        top.addWidget(self.filter, 1)
        top.addWidget(self.btn_refresh)
        top.addWidget(self.btn_attach)
        top.addWidget(self.btn_spawn)
        top.addWidget(self.show_apps)
        self.btn_front = QPushButton("attach 前台应用")
        self.btn_front.clicked.connect(self.attach_frontmost)
        self.auto_refresh = QCheckBox("自动刷新")
        self.auto_refresh.toggled.connect(self._on_auto_toggle)
        top.addWidget(self.btn_front)
        top.addWidget(self.auto_refresh)
        lay.addLayout(top)

        self.table = QTableView()
        self.table.setModel(self._proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.attach_selected)
        lay.addWidget(self.table, 1)
        self.status = QLabel("点击「刷新」加载进程")
        self.status.setStyleSheet("color:" + "#9db3c8")
        lay.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    def _on_auto_toggle(self, on: bool):
        if on:
            secs = config.AUTO_REFRESH_SECS
            if secs > 0:
                self._timer.start(int(secs * 1000))
        else:
            self._timer.stop()

    def attach_frontmost(self):
        dev = self._host.current_device()
        if dev is None:
            self.status.setText("请先连接设备")
            return
        pid = fd.frontmost_pid(dev)
        if pid is None:
            # 前台应用可能是冷启动或未暴露 pid，尝试用包名 spawn
            pkg = fd.frontmost_app(dev)
            if pkg:
                self._host.spawn_app(pkg, "")
                return
            self.status.setText("无法获取前台应用")
            return
        # 前台 pid 可能不在当前列表，直接 attach
        self._host.attach_to(pid, f"前台应用(pid={pid})")

    def refresh(self):
        dev = self._host.current_device()
        if dev is None:
            self.status.setText("请先在顶部连接设备")
            return
        try:
            rows = []
            if self.show_apps.isChecked():
                for a in fd.enumerate_apps(dev):
                    rows.append([a["pid"] or "-", f"{a['name']} ({a['id']})"])
            else:
                for p in fd.list_processes(dev):
                    rows.append([p["pid"], p["name"]])
            self._model.set_rows(rows)
            front = fd.frontmost_app(dev)
            self.status.setText(f"共 {len(rows)} 条  前台应用: {front}")
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"加载失败: {exc}")

    def _selected_row(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return None
        idx = sel[0]
        return self._proxy.mapToSource(idx).row()

    def attach_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.status.setText("请先在列表中选中目标")
            return
        src = self._proxy.mapToSource(rows[0]).row()
        pid, name = self._model._rows[src][0], self._model._rows[src][1]
        try:
            pidnum = int(pid)
        except ValueError:
            self.status.setText("该行为应用(无 PID)，请用 spawn 或再刷新后选择进程")
            return
        self._host.attach_to(pidnum, name)

    def spawn_dialog(self):
        dev = self._host.current_device()
        if dev is None:
            self.status.setText("请先连接设备")
            return
        dlg = SpawnDialog(fd.enumerate_apps(dev), self)
        if dlg.exec():
            pkg, entry = dlg.values()
            if not pkg:
                self.status.setText("请输入应用包名")
                return
            self._host.spawn_app(pkg, entry)