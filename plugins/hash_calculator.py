# -*- coding: utf-8 -*-
"""
Hash计算器 — 支持拖拽文件，计算 MD5 / SHA-1 / SHA-256
"""
import sys, os, hashlib, base64

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFileDialog, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QDragEnterEvent, QDropEvent

# ═══════════════════════════════════════════════════════════
#  PluginBase 包装（必须放在 import 之后、class 之前）
# ═══════════════════════════════════════════════════════════

from framework.plugin_interface import PluginBase


class HashCalculatorPlugin(PluginBase):
    @property
    def plugin_name(self) -> str: return "Hash计算器"
    @property
    def plugin_name_en(self) -> str: return "Hash Calculator"
    @property
    def plugin_version(self) -> str: return "1.0.0"
    @property
    def plugin_icon(self) -> str: return "#️⃣"
    @property
    def plugin_description(self) -> str: return "拖拽文件计算 MD5 / SHA-1 / SHA-256"
    @property
    def plugin_description_en(self) -> str: return "Drag file to calculate MD5 / SHA-1 / SHA-256"
    @property
    def plugin_tags(self) -> list: return ["hash", "security"]

    def create_widget(self, parent=None):
        return HashCalculator()


# ═══════════════════════════════════════════════════════════
#  主界面
# ═══════════════════════════════════════════════════════════

cl_bg = "#f0f2f5"
cl_card = "#ffffff"
cl_border = "#e8eaed"
cl_text = "#2d3436"
cl_muted = "#868e96"
cl_primary = "#4361ee"


class DropArea(QFrame):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(100)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("dropArea")
        self.setStyleSheet(f"""
            QFrame#dropArea {{
                border: 2px dashed #d0d3d9;
                border-radius: 10px; background: {cl_card};
            }}
            QFrame#dropArea:hover, QFrame#dropArea[drag="true"] {{
                border: 2px dashed {cl_primary};
                background: #f0f2ff;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)
        self._icon = QLabel("📂")
        self._icon.setFont(QFont("Segoe UI Emoji", 30))
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setStyleSheet("background: transparent;")
        layout.addWidget(self._icon)
        self._text = QLabel("拖拽文件到此处，或点击选择")
        self._text.setAlignment(Qt.AlignCenter)
        self._text.setStyleSheet(f"color: {cl_muted}; font-size: 12px; background: transparent;")
        layout.addWidget(self._text)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("drag", True); self.style().unpolish(self); self.style().polish(self)
            self._icon.setText("📄"); self._text.setText("释放鼠标计算")

    def dragLeaveEvent(self, event):
        self.setProperty("drag", False); self.style().unpolish(self); self.style().polish(self)
        self._icon.setText("📂"); self._text.setText("拖拽文件到此处，或点击选择")

    def dropEvent(self, event: QDropEvent):
        self.setProperty("drag", False); self.style().unpolish(self); self.style().polish(self)
        self._icon.setText("✅"); self._text.setText("文件已就绪")
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.file_dropped.emit(path); return

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件")
            if path:
                self.file_dropped.emit(path)


class HashRow(QWidget):
    """单行：标签 | 哈希值 [复制]"""
    def __init__(self, label):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(12)

        self._lbl = QLabel(label)
        self._lbl.setFixedWidth(130)
        self._lbl.setStyleSheet(f"color: {cl_muted}; font-size: 12px; font-weight: 600;")
        layout.addWidget(self._lbl)

        self._val = QLabel("—")
        self._val.setFont(QFont("Consolas", 11))
        self._val.setStyleSheet(f"color: #adb5bd;")
        self._val.setWordWrap(True)
        self._val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._val, 1)

        self._cpy = QPushButton("复制")
        self._cpy.setFixedSize(50, 26)
        self._cpy.setCursor(Qt.PointingHandCursor)
        self._cpy.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid #e0e0e0;
                border-radius: 5px; font-size: 11px; color: #868e96;
            }}
            QPushButton:hover {{ border-color: {cl_primary}; color: {cl_primary}; background: #f0f2ff; }}
        """)
        self._cpy.clicked.connect(self._copy)
        layout.addWidget(self._cpy)

    def set(self, text, ok=True):
        self._val.setText(text)
        self._val.setStyleSheet(f"color: {cl_text if ok else '#adb5bd'};")

    def _copy(self):
        t = self._val.text()
        if t and t != "—":
            QApplication.clipboard().setText(t)


class HashWorker(QThread):
    """后台计算哈希值，不阻塞界面"""
    result_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self._path = file_path

    def run(self):
        try:
            with open(self._path, "rb") as f:
                data = f.read()
            md5 = hashlib.md5(data).hexdigest()
            sha1 = hashlib.sha1(data).hexdigest()
            sha256 = hashlib.sha256(data).hexdigest()
            sha256_b64 = base64.b64encode(hashlib.sha256(data).digest()).decode()
            self.result_ready.emit({
                "MD5": md5.upper(),
                "SHA-1": sha1.upper(),
                "SHA-256 (Hex)": sha256.upper(),
                "SHA-256 (Base64)": sha256_b64,
            })
        except Exception as e:
            self.error_occurred.emit(str(e))


class HashCalculator(QWidget):
    def __init__(self):
        super().__init__()
        self._current_file = ""
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Hash计算器")
        self.setStyleSheet(f"HashCalculator, QWidget {{ background: {cl_bg}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        # ── 顶栏 ──
        top = QHBoxLayout()
        title = QLabel("Hash 计算器")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        title.setStyleSheet(f"color: {cl_text}; background: transparent;")
        top.addWidget(title)
        top.addStretch()

        self._copy_all_btn = QPushButton("复制全部")
        self._copy_all_btn.setFixedHeight(32)
        self._copy_all_btn.setCursor(Qt.PointingHandCursor)
        self._copy_all_btn.setEnabled(False)
        self._copy_all_btn.setStyleSheet(f"""
            QPushButton {{
                background: {cl_primary}; color: white; font-weight: bold;
                border: none; border-radius: 6px; padding: 0 20px; font-size: 12px;
            }}
            QPushButton:hover {{ background: #3a56d4; }}
            QPushButton:disabled {{ background: #ced4da; color: #868e96; }}
        """)
        self._copy_all_btn.clicked.connect(self._copy_all)
        top.addWidget(self._copy_all_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setFixedHeight(32)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: white; color: #636e72;
                border: 1px solid #e0e0e0; border-radius: 6px;
                padding: 0 16px; font-size: 12px;
            }}
            QPushButton:hover {{ background: #f5f5f5; border-color: #d0d0d0; }}
        """)
        clear_btn.clicked.connect(self._clear)
        top.addWidget(clear_btn)
        layout.addLayout(top)

        # ── 提示 ──
        tip = QLabel("支持 MD5 / SHA-1 / SHA-256，拖拽或点击选择文件自动计算")
        tip.setStyleSheet(f"color: {cl_muted}; font-size: 12px; background: transparent;")
        layout.addWidget(tip)

        # ── 拖拽区 ──
        self._drop = DropArea()
        self._drop.file_dropped.connect(self._on_file)
        layout.addWidget(self._drop)

        # ── 文件信息 ──
        self._file_info = QLabel("")
        self._file_info.setStyleSheet(f"color: {cl_muted}; font-size: 11px; background: transparent;")
        layout.addWidget(self._file_info)

        # ── 结果区 ──
        result_area = QWidget()
        result_area.setStyleSheet("background: transparent;")
        rl = QVBoxLayout(result_area)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        # 表头
        hdr = QHBoxLayout()
        hdr_l = QLabel("算法")
        hdr_l.setFixedWidth(130)
        hdr_l.setStyleSheet(f"color: {cl_muted}; font-size: 11px; font-weight: bold;")
        hdr.addWidget(hdr_l)
        hdr_v = QLabel("哈希值")
        hdr_v.setStyleSheet(f"color: {cl_muted}; font-size: 11px; font-weight: bold;")
        hdr.addWidget(hdr_v, 1)
        hdr_c = QLabel("操作")
        hdr_c.setFixedWidth(60)
        hdr_c.setStyleSheet(f"color: {cl_muted}; font-size: 11px; font-weight: bold;")
        hdr_c.setAlignment(Qt.AlignCenter)
        hdr.addWidget(hdr_c)
        rl.addLayout(hdr)

        # 分隔线
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {cl_border}; border: none; margin: 6px 0;")
        rl.addWidget(sep)

        self._rows = {
            "MD5": HashRow("MD5"),
            "SHA-1": HashRow("SHA-1"),
            "SHA-256 (Hex)": HashRow("SHA-256"),
            "SHA-256 (Base64)": HashRow("SHA-256 (Base64)"),
        }
        for r in self._rows.values():
            rl.addWidget(r)

        layout.addWidget(result_area, 1)

    def _on_file(self, path):
        self._current_file = path
        name = os.path.basename(path)
        size = os.path.getsize(path)
        s = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.2f} MB"
        self._file_info.setText(f"📎 {name}  ·  {s}")
        # 计算中状态
        self._drop._icon.setText("⏳")
        self._drop._text.setText("正在计算...")
        for r in self._rows.values():
            r.set("—", False)
        self._copy_all_btn.setEnabled(False)
        # 启动后台线程
        self._worker = HashWorker(path)
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _on_result(self, results):
        self._rows["MD5"].set(results["MD5"])
        self._rows["SHA-1"].set(results["SHA-1"])
        self._rows["SHA-256 (Hex)"].set(results["SHA-256 (Hex)"])
        self._rows["SHA-256 (Base64)"].set(results["SHA-256 (Base64)"])
        self._copy_all_btn.setEnabled(True)
        self._drop._icon.setText("✅")
        self._drop._text.setText("计算完成")
        self._worker = None

    def _on_error(self, msg):
        QMessageBox.warning(self, "计算失败", msg)
        self._clear()
        self._worker = None

    def _copy_all(self):
        lines = [f"{k}: {r._val.text()}" for k, r in self._rows.items()
                 if r._val.text() and r._val.text() != "—"]
        if lines:
            QApplication.clipboard().setText("\n".join(lines))

    def _clear(self):
        for r in self._rows.values():
            r.set("—", False)
        self._file_info.setText("")
        self._current_file = ""
        self._copy_all_btn.setEnabled(False)
        self._drop._icon.setText("📂")
        self._drop._text.setText("拖拽文件到此处，或点击选择")


# ═══════════════════════════════════════════════════════════
#  独立调试入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = HashCalculator()
    w.resize(760, 560)
    w.show()
    sys.exit(app.exec())
