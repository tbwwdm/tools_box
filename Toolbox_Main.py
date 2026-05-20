# -*- coding: utf-8 -*-
"""
工具箱主程序 (PySide6)
"""
import sys, os, json, importlib, logging
from datetime import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QListWidget,
    QListWidgetItem, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame)
from PySide6.QtCore import QSize

PATH = os.path.dirname(__file__)
TOOLS_CFG = os.path.join(PATH, "config", "tools.json")
TOOL_ICONS = ["🕐", "👤", "🔐", "🛠", "⚙", "📊", "🔧", "💻", "🌐", "📁"]
tools = []
tool_windows = []


def import_cls(mod_name, cls_name):
    try:
        return getattr(importlib.import_module(mod_name), cls_name)
    except:
        return None


if __name__ == "__main__":
    cfgs = json.load(open(TOOLS_CFG, encoding="utf-8"))["tools"]

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

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

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

    for i, c in enumerate(cfgs):
        icon = c.get("icon", TOOL_ICONS[i % len(TOOL_ICONS)])
        tools.append({**c, "icon": icon})
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 54))
        tl.addItem(item)
        iw = QWidget()
        iw.setStyleSheet("background:transparent;")
        iwl = QHBoxLayout(iw)
        iwl.setContentsMargins(20, 0, 20, 0)
        iwl.setSpacing(14)
        ilbl = QLabel(icon)
        ilbl.setStyleSheet("font-size:22px;color:#dfe6e9;")
        iwl.addWidget(ilbl)
        nlbl = QLabel(c["name"])
        nlbl.setStyleSheet("font-size:14px;color:#dfe6e9;")
        iwl.addWidget(nlbl)
        iwl.addStretch()
        tl.setItemWidget(item, iw)

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
        row = tl.row(cur)
        if row < 0 or row >= len(tools):
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
        t = tools[tl.currentRow()]
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

    tl.currentItemChanged.connect(on_sel)
    tl.itemDoubleClicked.connect(do_launch)
    lb.clicked.connect(do_launch)

    w.show()
    sys.exit(app.exec())
