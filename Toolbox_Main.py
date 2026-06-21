# -*- coding: utf-8 -*-
"""
工具箱主程序 (PySide6)
"""
import sys, os, json, importlib, logging, shutil, traceback
from datetime import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QListWidget,
    QListWidgetItem, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QDialog, QMessageBox)
from PySide6.QtCore import QSize, Qt

APP_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = getattr(sys, '_MEIPASS', APP_DIR)
CONFIG_DIR = os.path.join(APP_DIR, "config")


def _bundled_config_path(filename):
    return os.path.join(RESOURCE_DIR, "config", filename)


def _config_path(filename, required=False):
    paths = [
        os.path.join(CONFIG_DIR, filename),
        _bundled_config_path(filename),
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    if required:
        raise FileNotFoundError(
            f"Missing config/{filename}. Put the config folder next to the exe, "
            f"or include it when packaging."
        )
    return paths[0]


def _ensure_runtime_config():
    bundled_dir = os.path.join(RESOURCE_DIR, "config")
    if not getattr(sys, 'frozen', False) or not os.path.isdir(bundled_dir):
        return
    os.makedirs(CONFIG_DIR, exist_ok=True)
    for name in os.listdir(bundled_dir):
        src = os.path.join(bundled_dir, name)
        dst = os.path.join(CONFIG_DIR, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)


_ensure_runtime_config()
PATH = APP_DIR
TOOLS_CFG = _config_path("tools.json")
TOOL_ICONS = ["🕐", "👤", "🔐", "🛠", "⚙", "📊", "🔧", "💻", "🌐", "📁"]
VIS_CFG = os.path.join(CONFIG_DIR, "tool_visibility.json")
ORDER_CFG = os.path.join(CONFIG_DIR, "tool_order.json")
tools = []
tool_windows = []


def import_cls(mod_name, cls_name):
    try:
        return getattr(importlib.import_module(mod_name), cls_name)
    except Exception:
        logging.getLogger("toolbox").error(
            "工具类加载失败: %s.%s\n%s",
            mod_name,
            cls_name,
            traceback.format_exc(),
        )
        return None


def rebuild_tool_list(tl, tools, visible_map):
    tl.clear()
    for i, t in enumerate(tools):
        if not visible_map.get(t["name"], True):
            continue
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 54))
        item.setData(Qt.UserRole, i)
        tl.addItem(item)
        iw = QWidget()
        iw.setStyleSheet("background:transparent;")
        iwl = QHBoxLayout(iw)
        iwl.setContentsMargins(20, 0, 20, 0)
        iwl.setSpacing(14)
        ilbl = QLabel(t.get("icon", "🔧"))
        ilbl.setStyleSheet("font-size:22px;color:#dfe6e9;")
        iwl.addWidget(ilbl)
        nlbl = QLabel(t["name"])
        nlbl.setStyleSheet("font-size:14px;color:#dfe6e9;")
        iwl.addWidget(nlbl)
        iwl.addStretch()
        tl.setItemWidget(item, iw)


def _rebuild_item_widgets(tl, tools):
    for i in range(tl.count()):
        item = tl.item(i)
        idx = item.data(Qt.UserRole)
        t = tools[idx]
        iw = QWidget()
        iw.setStyleSheet("background:transparent;")
        iwl = QHBoxLayout(iw)
        iwl.setContentsMargins(20, 0, 20, 0)
        iwl.setSpacing(14)
        ilbl = QLabel(t.get("icon", "🔧"))
        ilbl.setStyleSheet("font-size:22px;color:#dfe6e9;")
        iwl.addWidget(ilbl)
        nlbl = QLabel(t["name"])
        nlbl.setStyleSheet("font-size:14px;color:#dfe6e9;")
        iwl.addWidget(nlbl)
        iwl.addStretch()
        tl.setItemWidget(item, iw)


def _save_order(tools):
    os.makedirs(os.path.dirname(ORDER_CFG), exist_ok=True)
    json.dump(
        [t["name"] for t in tools],
        open(ORDER_CFG, "w", encoding="utf-8"),
        ensure_ascii=False, indent=2
    )


def _load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _load_config_json(filename, default=None, required=False):
    return _load_json(_config_path(filename, required=required), default)


class ToolSettingsDialog(QDialog):
    def __init__(self, all_tools, visible_map, parent=None):
        super().__init__(parent)
        self.setWindowTitle("栏位设置")
        self.setFixedSize(380, 460)
        self.setStyleSheet("QDialog{background:#f0f2f5;}")
        self._all_tools = all_tools
        self._visible_map = visible_map
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet("background:#2d3436;")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 12, 16, 12)
        hdr_label = QLabel("选择显示的工具")
        hdr_label.setStyleSheet("color:white;font-size:15px;font-weight:bold;")
        hdr_layout.addWidget(hdr_label)
        hdr_layout.addStretch()
        layout.addWidget(hdr)

        btn_row = QWidget()
        btn_row.setStyleSheet("background:#f0f2f5;")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(16, 10, 16, 10)
        select_all = QPushButton("全选")
        deselect_all = QPushButton("取消全选")
        for b in (select_all, deselect_all):
            b.setStyleSheet(
                "QPushButton{background:white;color:#2d3436;font-size:13px;"
                "padding:6px 18px;border:1px solid #d0d0d0;border-radius:4px;}"
                "QPushButton:hover{background:#e8e8e8;}"
            )
        btn_layout.addWidget(select_all)
        btn_layout.addWidget(deselect_all)
        btn_layout.addStretch()
        layout.addWidget(btn_row)

        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.InternalMove)
        self._list.setDefaultDropAction(Qt.MoveAction)
        self._list.setStyleSheet(
            "QListWidget{background:white;border:none;font-size:14px;}"
            "QListWidget::item{color:#2d3436;padding:6px 16px;}"
            "QListWidget::item:hover{background:#f0f2f5;color:#0984e3;}"
            "QListWidget::item:selected{background:#e8f0fe;}"
            "QScrollBar:vertical{width:8px;}"
            "QScrollBar::handle:vertical{background:#b0b0b0;border-radius:4px;}"
        )

        for t in self._all_tools:
            text = f'{t.get("icon", "🔧")}  {t["name"]}'
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if self._visible_map.get(t["name"], True) else Qt.Unchecked)
            self._list.addItem(item)

        layout.addWidget(self._list, 1)

        bottom = QWidget()
        bottom.setStyleSheet("background:#f0f2f5;")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 12, 16, 12)
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.setStyleSheet(
            "QPushButton{background:#0984e3;color:white;font-size:14px;font-weight:bold;"
            "padding:8px 32px;border:none;border-radius:6px;}"
            "QPushButton:hover{background:#0873c4;}"
        )
        cancel_btn.setStyleSheet(
            "QPushButton{background:white;color:#2d3436;font-size:14px;"
            "padding:8px 24px;border:1px solid #d0d0d0;border-radius:6px;}"
            "QPushButton:hover{background:#f5f5f5;}"
        )
        bottom_layout.addStretch()
        bottom_layout.addWidget(ok_btn)
        bottom_layout.addSpacing(10)
        bottom_layout.addWidget(cancel_btn)
        layout.addWidget(bottom)

        def set_all(checked):
            for i in range(self._list.count()):
                self._list.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)

        select_all.clicked.connect(lambda: set_all(True))
        deselect_all.clicked.connect(lambda: set_all(False))
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

    def get_visible_map(self):
        result = {}
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = item.text().split("  ", 1)[1]
            result[name] = item.checkState() == Qt.Checked
        return result

    def get_tool_order(self):
        order = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = item.text().split("  ", 1)[1]
            order.append(name)
        return order


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if not os.path.exists(TOOLS_CFG):
        QMessageBox.critical(
            None,
            "Config Missing",
            f"Cannot find config/tools.json.\n\nChecked:\n{CONFIG_DIR}\n{os.path.join(RESOURCE_DIR, 'config')}\n\n"
            "Please copy the config folder next to the exe, or package it with --add-data config;config."
        )
        sys.exit(1)

    cfgs = _load_json(TOOLS_CFG, {"tools": []})["tools"]
    visible_map = _load_config_json("tool_visibility.json", default={}) or {}

    logger = logging.getLogger("toolbox")
    log_dir = os.path.join(PATH, "logs")
    os.makedirs(log_dir, exist_ok=True)
    fh = logging.FileHandler(
        os.path.join(log_dir, f"工具箱_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        encoding="utf-8")
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)
    logger.info("工具箱启动")

    w = QMainWindow()
    w.setWindowTitle("工具箱")
    w.setGeometry(150, 80, 1500, 800)
    w.setMinimumSize(800, 500)

    cw = QWidget()
    w.setCentralWidget(cw)
    ml = QVBoxLayout(cw)
    ml.setContentsMargins(0, 0, 0, 0)
    ml.setSpacing(0)

    # 顶栏
    tb = QWidget()
    tb.setStyleSheet("background: #2d3436;")
    tll = QHBoxLayout(tb)
    tll.setContentsMargins(20, 14, 20, 14)
    ti = QLabel("🧰")
    ti.setStyleSheet("font-size:24px;")
    tll.addWidget(ti)
    tll.addSpacing(10)
    tt = QLabel("工具箱")
    tt.setStyleSheet("color:white;font-size:18px;font-weight:bold;")
    tll.addWidget(tt)
    tll.addStretch()
    settings_btn = QPushButton("⚙")
    settings_btn.setFixedSize(36, 36)
    settings_btn.setStyleSheet(
        "QPushButton{background:#3d4447;color:white;font-size:18px;"
        "border:none;border-radius:18px;}"
        "QPushButton:hover{background:#50575a;}"
    )
    tll.addWidget(settings_btn)
    ml.addWidget(tb)

    # 主体
    body = QWidget()
    body.setStyleSheet("background:#f0f2f5;")
    bl = QHBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(0)

    # 左侧列表
    tl = QListWidget()
    tl.setMinimumWidth(260)
    tl.setMaximumWidth(360)
    tl.setStyleSheet(
        "QListWidget{background:#2d3436;border:none;padding:4px 0;}"
        "QListWidget::item{color:#dfe6e9;padding:14px 20px;border-left:3px solid transparent;font-size:13px;}"
        "QListWidget::item:hover{background:#353b3e;border-left:3px solid #74b9ff;}"
        "QListWidget::item:selected{background:#3d4447;border-left:3px solid #0984e3;color:white;}"
    )
    tl.setDragDropMode(QListWidget.InternalMove)
    tl.setDefaultDropAction(Qt.MoveAction)

    for i, c in enumerate(cfgs):
        icon = c.get("icon", TOOL_ICONS[i % len(TOOL_ICONS)])
        tools.append({**c, "icon": icon})
    order_list = _load_config_json("tool_order.json", default=None)
    if order_list:
        name_to_tool = {t["name"]: t for t in tools}
        reordered = [name_to_tool[n] for n in order_list if n in name_to_tool]
        existing = {t["name"] for t in reordered}
        for t in tools:
            if t["name"] not in existing:
                reordered.append(t)
        tools[:] = reordered
    rebuild_tool_list(tl, tools, visible_map)

    tl.setCurrentRow(-1)
    bl.addWidget(tl)

    # 右侧详情
    right = QWidget()
    right.setStyleSheet("background:#f0f2f5;")
    rl = QVBoxLayout(right)
    rl.setContentsMargins(30, 30, 30, 30)

    card = QFrame()
    card.setStyleSheet("QFrame{background:white;border-radius:12px;}")
    cl = QVBoxLayout(card)
    cl.setContentsMargins(40, 40, 40, 40)

    di = QLabel("🔧")
    di.setStyleSheet("font-size:52px;color:#2d3436;")
    cl.addWidget(di)

    dn = QLabel("选择一个工具")
    dn.setStyleSheet("font-size:24px;font-weight:bold;color:#2d3436;")
    cl.addWidget(dn)

    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet("background:#ecf0f1;max-height:1px;margin:10px 0 20px 0;")
    cl.addWidget(sep)

    dd = QLabel("请从左侧列表选择一个工具，查看详情并启动")
    dd.setStyleSheet("font-size:14px;color:#4a4a4a;")
    dd.setWordWrap(True)
    cl.addWidget(dd)
    cl.addStretch()

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    lb = QPushButton("🚀  启动工具")
    lb.setEnabled(False)
    lb.setStyleSheet(
        "QPushButton{background:#0984e3;color:white;font-size:15px;font-weight:bold;"
        "padding:14px 44px;border:none;border-radius:8px;min-width:200px;}"
        "QPushButton:hover{background:#0873c4;}"
        "QPushButton:disabled{background:#dfe6e9;color:#b2bec3;}"
    )
    btn_row.addWidget(lb)
    btn_row.addStretch()
    cl.addLayout(btn_row)
    rl.addWidget(card)
    bl.addWidget(right, 1)
    ml.addWidget(body)

    # 信号
    def on_sel(cur, prev):
        if cur is None:
            di.setText("🔧")
            dn.setText("选择一个工具")
            dd.setText("请从左侧列表选择一个工具，查看详情并启动")
            lb.setEnabled(False)
            return
        row = cur.data(Qt.UserRole)
        if row is None or row < 0 or row >= len(tools):
            return
        t = tools[row]
        di.setText(t["icon"])
        dn.setText(t["name"])
        dd.setText(t.get("description", ""))
        lb.setEnabled(True)

    def do_launch():
        item = tl.currentItem()
        if item is None:
            return
        row = item.data(Qt.UserRole)
        if row is None or row < 0 or row >= len(tools):
            return
        t = tools[row]
        if not t.get("module") or not t.get("class"):
            logger.warning(f"工具配置不完整: {t['name']}")
            return
        logger.info(f"启动工具: {t['name']}")
        cls = import_cls(t["module"], t["class"])
        if cls is None:
            logger.error(f"工具类加载失败: {t['module']}.{t['class']}")
            return
        try:
            tw = cls()
            tw.setWindowTitle(f'{t["icon"]} {t["name"]}')
            tw.show()
            tool_windows.append(tw)
            logger.info(f"工具启动成功: {t['name']}")
        except Exception as e:
            logger.error(f"工具启动失败: {e}")

    def open_settings():
        dlg = ToolSettingsDialog(tools, visible_map, w)
        if dlg.exec():
            new_map = dlg.get_visible_map()
            new_order = dlg.get_tool_order()
            visible_map.clear()
            visible_map.update(new_map)
            name_to_tool = {t["name"]: t for t in tools}
            tools[:] = [name_to_tool[n] for n in new_order if n in name_to_tool]
            os.makedirs(os.path.dirname(VIS_CFG), exist_ok=True)
            json.dump(visible_map, open(VIS_CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            _save_order(tools)
            rebuild_tool_list(tl, tools, visible_map)

    def on_tools_reordered():
        new_visible = []
        for i in range(tl.count()):
            idx = tl.item(i).data(Qt.UserRole)
            new_visible.append(tools[idx])
        hidden = [t for t in tools if not visible_map.get(t["name"], True)]
        tools[:] = new_visible + hidden
        for i in range(tl.count()):
            tl.item(i).setData(Qt.UserRole, i)
        _rebuild_item_widgets(tl, tools)
        _save_order(tools)

    settings_btn.clicked.connect(open_settings)
    tl.model().rowsMoved.connect(lambda *a: on_tools_reordered())
    tl.model().rowsInserted.connect(
        lambda *a: on_tools_reordered(),
        Qt.QueuedConnection
    )
    tl.currentItemChanged.connect(on_sel)
    tl.itemDoubleClicked.connect(do_launch)
    lb.clicked.connect(do_launch)

    w.show()
    sys.exit(app.exec())

