# -*- coding: utf-8 -*-
"""
密码生成工具 (PySide6)
"""
import sys, os, logging, secrets, string
from datetime import datetime

import pandas as pd

from PySide6.QtWidgets import (QWidget, QApplication, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QMessageBox,
    QTabWidget, QGroupBox)


logger = logging.getLogger(__name__)


def rand_pass(length=12):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(chars) for _ in range(length))


def save_log(data, prefix="密码"):
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    with open(path, 'w', encoding='utf-8') as f:
        if isinstance(data, list):
            for line in data:
                f.write(str(line) + '\n')
        else:
            f.write(str(data))
    return path


class PasswdTool(QWidget):
    def __init__(self, lang="zh"):
        super().__init__()
        self.lang = lang
        self._init_logging()

        title = "Password Generator" if self.lang == "en" else self._tr("密码生成器", "Password Generator")
        self.setWindowTitle(title)
        self.resize(820, 620)
        self.setStyleSheet("""
            PasswdTool { background:#f5f6fa; }
            QGroupBox { font-weight:bold; color:#2d3436; border:none; margin-top:16px; padding:14px 0 4px 0; }
            QGroupBox::title { padding:0 0 6px 0; border-bottom:2px solid #0984e3; }
            QLineEdit { border:none; border-bottom:1px solid #dfe6e9; padding:6px 4px; background:transparent; font-size:13px; }
            QLineEdit:focus { border-bottom:2px solid #0984e3; }
            QTextEdit { border:1px solid #dfe6e9; border-radius:4px; background:white; font-size:13px; }
            QTabWidget::pane { border:1px solid #dfe6e9; border-radius:4px; background:white; }
            QTabBar::tab { padding:8px 20px; font-size:13px; border:none; }
            QTabBar::tab:selected { border-bottom:2px solid #0984e3; color:#0984e3; font-weight:bold; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("密码生成工具")
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#2d3436;")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_single_tab()
        self._build_batch_tab()
        self._build_excel_tab()

    def _tr(self, zh: str, en: str) -> str:
        """根据当前语言返回对应文本"""
        return en if self.lang == "en" else zh


    def _init_logging(self):
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(log_dir, f"密码生成_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
            encoding="utf-8")
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)

    def _btn(self, text, color="#0984e3", hover=None):
        if hover is None:
            hover = {"#0984e3":"#0873c4", "#27ae60":"#219a52", "#636e72":"#535c69"}.get(color, color)
        return (f"QPushButton{{background:{color};color:white;padding:7px 22px;"
                f"border:none;border-radius:4px;font-size:13px;}}"
                f"QPushButton:hover{{background:{hover};}}")

    def _build_single_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        g = QGroupBox("密码设置")
        hl = QHBoxLayout(g)
        hl.addWidget(QLabel("密码长度"))
        self.s_len = QLineEdit("12")
        self.s_len.setFixedWidth(60)
        hl.addWidget(self.s_len)
        hl.addStretch()
        layout.addWidget(g)

        btn = QPushButton("Generate Password" if self.lang == "en" else self._tr("生成密码", "Generate Password"))
        btn.setStyleSheet(self._btn("#0984e3"))
        btn.clicked.connect(self._gen_single)
        layout.addWidget(btn)

        self.s_out = QTextEdit()
        self.s_out.setReadOnly(True)
        self.s_out.setPlaceholderText("Generated passwords will be displayed here" if self.lang == "en" else "生成的密码将显示在这里")
        layout.addWidget(self.s_out)
        self.tabs.addTab(tab, "Single Generate" if self.lang == "en" else "单个生成")

    def _build_batch_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        g = QGroupBox("密码设置")
        hl = QHBoxLayout(g)
        hl.addWidget(QLabel("密码长度"))
        self.b_len = QLineEdit("12")
        self.b_len.setFixedWidth(60)
        hl.addWidget(self.b_len)
        hl.addStretch()
        layout.addWidget(g)

        g2 = QGroupBox("IP 地址列表（每行一个）")
        vl = QVBoxLayout(g2)
        self.b_ips = QTextEdit()
        self.b_ips.setPlaceholderText("192.168.1.1\n192.168.1.2")
        self.b_ips.setFixedHeight(120)
        vl.addWidget(self.b_ips)
        layout.addWidget(g2)

        btn = QPushButton("Generate Password" if self.lang == "en" else self._tr("生成密码", "Generate Password"))
        btn.setStyleSheet(self._btn("#0984e3"))
        btn.clicked.connect(self._gen_batch)
        layout.addWidget(btn)

        self.b_out = QTextEdit()
        self.b_out.setReadOnly(True)
        self.b_out.setPlaceholderText("Generated passwords will be displayed here" if self.lang == "en" else "生成的密码将显示在这里")
        layout.addWidget(self.b_out)
        self.tabs.addTab(tab, "Batch Generate" if self.lang == "en" else "批量生成")

    def _build_excel_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        g = QGroupBox("密码设置")
        hl = QHBoxLayout(g)
        hl.addWidget(QLabel("密码长度"))
        self.e_len = QLineEdit("12")
        self.e_len.setFixedWidth(60)
        hl.addWidget(self.e_len)
        hl.addStretch()
        layout.addWidget(g)

        g2 = QGroupBox("Excel 文件")
        hl2 = QHBoxLayout(g2)
        self.e_path = QLineEdit()
        placeholder = "Select Excel file with IP column" if self.lang == "en" else "选择包含 IP 列的 Excel 文件"
        self.e_path.setPlaceholderText(placeholder)
        hl2.addWidget(self.e_path)
        btn = QPushButton("Browse" if self.lang == "en" else "浏览")
        btn.setStyleSheet(self._btn("#636e72"))
        dialog_title = "Select Excel" if self.lang == "en" else "选择Excel"
        btn.clicked.connect(lambda: self.e_path.setText(
            QFileDialog.getOpenFileName(self, dialog_title, "", "Excel (*.xlsx)")[0]))
        hl2.addWidget(btn)
        layout.addWidget(g2)

        btn2 = QPushButton("Process Excel" if self.lang == "en" else "处理 Excel")
        btn2.setStyleSheet(self._btn("#27ae60"))
        btn2.clicked.connect(self._gen_excel)
        layout.addWidget(btn2)

        self.e_out = QTextEdit()
        self.e_out.setReadOnly(True)
        placeholder2 = "Processing results will be displayed here" if self.lang == "en" else "处理结果将显示在这里"
        self.e_out.setPlaceholderText(placeholder2)
        layout.addWidget(self.e_out)
        tab_name = "Process Excel" if self.lang == "en" else "Excel处理"
        self.tabs.addTab(tab, tab_name)

    def _gen_single(self):
        try:
            n = max(1, int(self.s_len.text()))
            pwd = rand_pass(n)
            path = save_log(pwd, "单个密码")
            logger.info(f"生成单个密码")
            self.s_out.setText(f"密码: {pwd}\n\n已保存: {path}")
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))

    def _gen_batch(self):
        try:
            n = max(1, int(self.b_len.text()))
            ips = [l.strip() for l in self.b_ips.toPlainText().strip().split('\n') if l.strip()]
            if not ips:
                QMessageBox.warning(self, "提示", "请输入IP地址")
                return
            lines = []
            for ip in ips:
                pwd = rand_pass(n)
                lines.append(f"{ip}  {pwd}")
            log_data = '\n'.join(lines)
            path = save_log(log_data, "批量密码")
            logger.info(f"批量生成 {len(ips)} 个密码")
            self.b_out.setText('\n'.join(lines) + f"\n\n已保存: {path}")
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))

    def _gen_excel(self):
        try:
            fp = self.e_path.text()
            if not fp:
                QMessageBox.warning(self, "提示", "请选择Excel文件")
                return
            n = max(1, int(self.e_len.text()))
            df = pd.read_excel(fp)
            if 'IP' not in df.columns:
                QMessageBox.critical(self, "错误", "Excel 文件需要包含 'IP' 列")
                return
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            df['密码'] = [rand_pass(n) for _ in range(len(df))]
            df['生成时间'] = ts
            out = os.path.join(os.path.dirname(fp), f"密码生成_{os.path.basename(fp)}")
            df.to_excel(out, index=False)
            logger.info(f"Excel处理完成: {len(df)} 条记录")
            msg = '\n'.join(f"{r['IP']}  {r['密码']}" for _, r in df.iterrows())
            self.e_out.setText(f"处理完成！共 {len(df)} 条\n{'-'*30}\n{msg}\n\n已保存: {out}")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    w = PasswdTool()
    w.show()
    sys.exit(app.exec())
