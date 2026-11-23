"""脚本面板：JS 编辑器 + 输出控制台，管理一次 target 会话(attach/spawn 后的脚本)。"""
from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from ..core.session_mgr import TargetSession
from ..core import templates as tpl


class ScriptPanel(QWidget):
    DEFAULT_JS = r"""// 示例脚本：直接在「运行」后输出目标进程基本信息。
// 可从上方「模板库」插入其它常用脚本。
send("[*] PID = " + Process.id);
send("[*] arch = " + Process.arch);
send("[*] platform = " + Process.platform);
send("[*] 模块数 = " + Process.enumerateModules().length);

// rpc 示例：删除本行下内容可在右侧 RPC 面板调用
rpc.exports.hello = function (name) { return "hello, " + name; };
rpc.exports.add = function (a, b) { return a + b; };
"""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host

        lay = QVBoxLayout(self)
        title_row = QHBoxLayout()
        self.session_info = QLabel("未连接目标")
        self.session_info.setStyleSheet("color:#e6b450;font-weight:600;")
        title_row.addWidget(self.session_info, 1)
        self.btn_run = QPushButton("运行 ▶")
        self.btn_run.setProperty("primary", True)
        self.btn_run.clicked.connect(self.run)
        self.btn_reload = QPushButton("重载")
        self.btn_reload.clicked.connect(self.reload)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_clear = QPushButton("清空控制台")
        self.btn_clear.clicked.connect(self.clear_console)
        title_row.addWidget(self.btn_run)
        title_row.addWidget(self.btn_reload)
        title_row.addWidget(self.btn_stop)
        title_row.addWidget(self.btn_clear)
        lay.addLayout(title_row)

        # 模板库 + 脚本文件
        tpl_row = QHBoxLayout()
        self.tpl_combo = QComboBox()
        self.tpl_combo.addItem("— 选择常用脚本模板 —", None)
        for label, js in tpl.build_combo_items():
            self.tpl_combo.addItem(label, js)
        btn_insert = QPushButton("插入模板")
        btn_insert.clicked.connect(self.insert_template)
        btn_open = QPushButton("打开")
        btn_open.clicked.connect(self.open_script)
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self.save_script)
        tpl_row.addWidget(QLabel("模板库："))
        tpl_row.addWidget(self.tpl_combo, 1)
        tpl_row.addWidget(btn_insert)
        tpl_row.addWidget(btn_open)
        tpl_row.addWidget(btn_save)
        lay.addLayout(tpl_row)

        split = QSplitter(Qt.Orientation.Vertical)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(self.DEFAULT_JS)
        self.editor.setMinimumHeight(220)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)
        split.addWidget(self.editor)
        split.addWidget(self.console)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

    # ---------------- 控制台输出 ----------------
    def log(self, text: str, color: str = "#d6e2ed"):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.console.appendHtml(
            f'<span style="color:#778899">{ts}</span> '
            f'<span style="color:{color}">{text}</span>')

    def clear_console(self):
        self.console.clear()

    # ---------------- 模板 / 脚本文件 ----------------
    def insert_template(self):
        js = self.tpl_combo.currentData()
        if not js:
            return
        self.editor.insertPlainText("\n// ========== 模板插入 ==========\n" + js + "\n")

    def open_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 JS 脚本", "", "JavaScript (*.js);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self.editor.setPlainText(f.read())
        except OSError as exc:
            self.log(f"[打开失败] {exc}", "#ff7b72")

    def save_script(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 JS 脚本", "script.js", "JavaScript (*.js);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            self.log(f"[*] 已保存到 {path}", "#7ee787")
        except OSError as exc:
            self.log(f"[保存失败] {exc}", "#ff7b72")

    # ---------------- 消息回调 ----------------
    def _on_message(self, message, data):
        if message.get("type") == "send":
            payload = message.get("payload", "")
            self.log(str(payload), "#7ee787")
        elif message.get("type") == "error":
            desc = message.get("description", message)
            self.log(f"[错误] {desc}", "#ff7b72")
            stack = message.get("stack")
            if stack:
                self.log(stack, "#ff7b72")
        else:
            self.log(json.dumps(message), "#e6b450")

    # ---------------- 会话操作 ----------------
    def _current(self) -> TargetSession:
        return self._host.current_session()

    def run(self):
        sess = self._current()
        if sess is None:
            self.log("请先在进程面板 attach / spawn 目标", "#e6b450")
            return
        src = self.editor.toPlainText()
        try:
            sess.load_script(src, self._on_message)
            self.log("[*] 脚本运行中")
        except Exception as exc:  # noqa: BLE001
            self.log(f"[注入失败] {exc}", "#ff7b72")

    def reload(self):
        sess = self._current()
        if sess is None:
            self.log("未连接目标", "#e6b450")
            return
        try:
            sess.reload(self.editor.toPlainText())
            self.log("[*] 脚本已重载")
        except Exception as exc:  # noqa: BLE001
            self.log(f"[重载失败] {exc}", "#ff7b72")

    def stop(self):
        sess = self._current()
        if sess is None:
            return
        sess.unload()
        self.log("[*] 脚本已卸载")

    def reflect_target(self, serial: str, detail: str):
        self.session_info.setText(f"目标@{serial}: {detail}")