"""检查器：常用 Frida 操作 —— 枚举模块/导出、dlopen、hook 模板生成、调用函数。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ..core.session_mgr import TargetSession

PROBE_JS = r"""
const rpc = {};
rpc.modules = function () {
    const out = [];
    Process.enumerateModules().forEach(m => out.push({name: m.name, base: m.base.toString(), size: m.size}));
    return out;
};
rpc.exports = function (mod) {
    const out = [];
    const m = Process.findModuleByName(mod);
    if (!m) return out;
    m.enumerateExports().forEach(e => out.push({name: e.name, type: e.type, address: e.address.toString()}));
    return out;
};
rpc.dlopen = function (p) { return Module.load(p); };
rpc.findExport = function (mod, sym) {
    const a = Module.findExportByName(mod || null, sym);
    return a ? a.toString() : null;
};
rpc.exports = rpc.exports;
"""


class ExportDialog(QDialog):
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("模块导出")
        self.setMinimumSize(560, 420)
        lay = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        lines = "\n".join(f"{r['type']:>5} {r['address']}  {r['name']}" for r in rows)
        self.text.setPlainText(lines or "(无导出)")
        lay.addWidget(self.text)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        lay.addWidget(close)


class InspectorPanel(QWidget):
    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.mod_combo = QComboBox()
        self.mod_combo.setEditable(True)
        self.mod_combo.setMinimumWidth(280)
        self.btn_scan = QPushButton("扫描模块")
        self.btn_scan.clicked.connect(self.scan_modules)
        self.btn_dlopen = QPushButton("dlopen")
        self.btn_dlopen.clicked.connect(self.dlopen)
        self.btn_exports = QPushButton("导出")
        self.btn_exports.clicked.connect(self.show_exports)
        top.addWidget(QLabel("模块："))
        top.addWidget(self.mod_combo, 1)
        top.addWidget(self.btn_scan)
        top.addWidget(self.btn_dlopen)
        top.addWidget(self.btn_exports)
        lay.addLayout(top)

        form = QHBoxLayout()
        self.sym_edit = QLineEdit()
        self.sym_edit.setPlaceholderText("导出符号，如 Java_com_example_MainActivity_nativeFn")
        self.btn_gen = QPushButton("生成 Hook 模板")
        self.btn_gen.clicked.connect(self.gen_hook)
        form.addWidget(self.sym_edit, 1)
        form.addWidget(self.btn_gen)
        lay.addLayout(form)

        self.preview = QPlainTextEdit()
        self.preview.setPlaceholderText("生成的 Hook 模板会显示在这里，复制到脚本面板运行")
        self.preview.setMinimumHeight(180)
        lay.addWidget(self.preview, 1)
        self.status = QLabel("在脚本面板 attach/spawn 一个目标后，可在此加载模块与导出")
        self.status.setStyleSheet("color:#9db3c8;")
        lay.addWidget(self.status)

    def _session(self) -> Optional[TargetSession]:
        return self._host.current_session()

    def scan_modules(self):
        sess = self._session()
        if sess is None:
            self.status.setText("请先在「脚本面板」运行一个脚本以授权注入")
            return
        try:
            s = sess._session.create_script(PROBE_JS)
            s.load()
            mods = s.exports_sync.modules()
            s.unload()
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"扫描失败: {exc}")
            return
        self._mods = {m["name"]: m for m in mods}
        current = self.mod_combo.currentText()
        self.mod_combo.clear()
        self.mod_combo.addItem("")  # 全局
        for m in mods:
            self.mod_combo.addItem(f"{m['name']} (@{m['base']})", m)
        self.status.setText(f"共 {len(mods)} 个模块")

    def _run_probe_call(self, method, *args):
        sess = self._session()
        s = sess._session.create_script(PROBE_JS)
        s.load()
        try:
            return getattr(s.exports_sync, method)(*args)
        finally:
            s.unload()

    def dlopen(self):
        path = self.mod_combo.currentText().split(" ")[0]
        if not path:
            self.status.setText("请输入要 dlopen 的 so 路径")
            return
        try:
            r = self._run_probe_call("dlopen", path)
            self.status.setText(f"dlopen 成功: {r}")
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"dlopen 失败: {exc}")

    def show_exports(self):
        text = self.mod_combo.currentText()
        mod = text.split(" ")[0] if text else ""
        if not mod:
            self.status.setText("请选择模块")
            return
        try:
            rows = self._run_probe_call("exports", mod)
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"枚举导出失败: {exc}")
            return
        ExportDialog(rows, self).exec()

    def gen_hook(self):
        sym = self.sym_edit.text().strip()
        if not sym:
            self.status.setText("请输入导出符号")
            return
        text = self.mod_combo.currentText()
        mod = text.split(" ")[0] if text else ""
        tmpl = (
            f'// 一键生成的 Hook 模板 —— 复制到脚本面板运行\n'
            f'const target = Module.getExportByName("{mod or "libc.so"}", "{sym}");\n'
            f'send("[+] 地址 = " + target);\n\n'
            f'Interceptor.attach(target, {{\n'
            f'  onEnter(args) {{ send("[>] 进入 {sym}: " + args[0]); }},\n'
            f'  onLeave(retval) {{ send("[<] 返回: " + retval); }}\n'
            f'}});\n'
        )
        self.preview.setPlainText(tmpl)

    def add_widgets(self):  # 预留扩展位
        pass