"""RPC 调用面板：列出当前脚本暴露的 rpc.exports 函数，并以 JSON 传参调用。"""
from __future__ import annotations

import json
from typing import List, Optional

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from ..core.session_mgr import TargetSession


class RpcPanel(QWidget):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.fn_combo = QComboBox()
        self.fn_combo.setEditable(True)
        self.fn_combo.setPlaceholderText("rpc.exports 的函数名")
        self.btn_list = QPushButton("刷新导出")
        self.btn_list.clicked.connect(self.refresh_exports)
        self.btn_call = QPushButton("调用 ▶")
        self.btn_call.setProperty("primary", True)
        self.btn_call.clicked.connect(self.call)
        top.addWidget(QLabel("函数："))
        top.addWidget(self.fn_combo, 1)
        top.addWidget(self.btn_list)
        top.addWidget(self.btn_call)
        lay.addLayout(top)

        self.args_edit = QPlainTextEdit()
        self.args_edit.setPlaceholderText(
            "调用参数，每行一个 JSON 值(逗号分隔也可)。\n"
            "示例:\n  123\n  \"hello\"\n  {\"a\":1}\n\n留空表示无参数。")
        self.args_edit.setMaximumHeight(120)
        lay.addWidget(QLabel("参数(JSON)："))
        lay.addWidget(self.args_edit)

        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("RPC 返回结果 / 日志")
        lay.addWidget(QLabel("结果："))
        lay.addWidget(self.result, 1)

    # ---------------- 逻辑 ----------------
    def _session(self) -> Optional[TargetSession]:
        return self._host.current_session()

    def refresh_exports(self):
        sess = self._session()
        if sess is None or sess._script is None:
            self.result.appendPlainText("[-] 当前没有运行中的脚本，先在「脚本」页运行")
            return
        try:
            names = self._list_exports(sess)
        except Exception as exc:  # noqa: BLE001
            self.result.appendPlainText(f"[-] 读取导出失败: {exc}")
            return
        self.fn_combo.clear()
        for n in names:
            self.fn_combo.addItem(n)
        self.result.appendPlainText(f"[*] 识别到 {len(names)} 个 rpc 导出: {', '.join(names)}")

    def _list_exports(self, sess: TargetSession) -> List[str]:
        # frida-python 的 exports_sync 支持 dir() 列出键
        exp = sess._script.exports_sync
        try:
            names = [k for k in dir(exp) if not k.startswith("_")]
        except Exception:  # noqa: BLE001
            names = []
        return names

    def call(self):
        sess = self._session()
        if sess is None or sess._script is None:
            self.result.appendPlainText("[-] 没有运行中的脚本")
            return
        name = self.fn_combo.currentText().strip()
        if not name:
            self.result.appendPlainText("[-] 请输入 RPC 函数名")
            return

        args = self._parse_args()
        if args is None:
            self.result.appendPlainText("[-] 参数 JSON 解析失败，请检查格式")
            return

        exp = sess._script.exports_sync
        try:
            fn = getattr(exp, name)
        except Exception as exc:  # noqa: BLE001
            self.result.appendPlainText(f"[-] 没有该导出函数 {name}: {exc}")
            return
        try:
            r = fn(*args)
            self.result.appendPlainText(f"[>] 调用 {name}{tuple(args) if args else ''}")
            self.result.appendPlainText("[+] 返回: " + self._fmt(r))
        except Exception as exc:  # noqa: BLE001
            self.result.appendPlainText(f"[-] 调用异常: {exc}")

    def _parse_args(self):
        text = self.args_edit.toPlainText().strip()
        if not text:
            return []
        # 兼容逗号分隔与换行分隔
        text = text.replace(",", "\n")
        parts = [p for p in text.split("\n") if p.strip()]
        out = []
        for p in parts:
            p = p.strip()
            try:
                out.append(json.loads(p))
            except Exception:  # noqa: BLE001
                return None
        return out

    def _fmt(self, v) -> str:
        try:
            return json.dumps(v, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            return str(v)