"""暗色主题 QSS。"""
from ..core import config

C = config.THEME


def qss() -> str:
    return f"""
    * {{ font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
         font-size: 13px; color: {C['fg']}; }}
    QMainWindow, QDialog {{ background: {C['bg']}; }}
    QWidget {{ background: transparent; }}

    QDockWidget::title {{
        background: {C['panel']}; padding: 6px 10px; font-weight: 600;
        border: 1px solid {C['border']}; border-left: 3px solid {C['accent']};
    }}
    QDockWidget {{ titlebar-close-icon: none; titlebar-normal-icon: none; }}

    QTabWidget::pane {{ border: 1px solid {C['border']}; top: -1px; }}
    QTabBar::tab {{
        background: {C['panel']}; padding: 6px 16px; border: 1px solid {C['border']};
        border-bottom: none; margin-right: 2px;
    }}
    QTabBar::tab:selected {{ background: {C['accent_soft']}; color: #fff; }}

    QTableView, QTreeView, QListWidget {{
        background: {C['bg_alt']}; alternate-background-color: {C['panel']};
        border: 1px solid {C['border']}; gridline-color: {C['border']};
        selection-background-color: {C['accent_soft']}; selection-color: #fff;
    }}
    QHeaderView::section {{
        background: {C['panel']}; padding: 4px 8px; border: none;
        border-right: 1px solid {C['border']}; border-bottom: 1px solid {C['border']};
        font-weight: 600;
    }}

    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
        background: {C['bg_alt']}; border: 1px solid {C['border']};
        border-radius: 4px; padding: 4px 6px; selection-background-color: {C['accent']};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {C['accent']}; }}

    QPushButton {{
        background: {C['accent_soft']}; border: 1px solid {C['border']};
        border-radius: 4px; padding: 5px 12px;
    }}
    QPushButton:hover {{ border-color: {C['accent']}; }}
    QPushButton:disabled {{ color: {C['fg_dim']}; background: {C['panel']}; }}
    QPushButton[primary="true"] {{ background: {C['accent']}; color: #fff; font-weight: 600; }}

    QStatusBar {{ background: {C['panel']}; border-top: 1px solid {C['border']}; }}
    QToolBar {{ background: {C['panel']}; border-bottom: 1px solid {C['border']}; spacing: 4px; }}

    QScrollBar:vertical {{ background: {C['bg']}; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 5px; min-height: 24px; }}

    QLabel[subtitle="true"] {{ color: {C['fg_dim']}; }}

    QSplitter::handle {{ background: {C['border']}; }}
    """