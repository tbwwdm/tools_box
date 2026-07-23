import sys, os, logging
import subprocess
import platform
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QGridLayout,
    QFrame, QSizePolicy, QTextEdit
)
from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QFont, QLinearGradient, QPen, QBrush
from datetime import datetime
import time

# v1.3 — 起始/结束输入框加高至26px; 按钮同步统一高度



class PingWorker(QThread):
    result_ready = Signal(int, int)

    def __init__(self, base_ip, ip_start, ip_end, max_workers=10):
        super().__init__()
        self.base_ip = base_ip
        self.ip_start = ip_start
        self.ip_end = ip_end
        self.max_workers = max_workers
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        param = "-n" if platform.system().lower() == "windows" else "-c"

        r1_pool = ThreadPoolExecutor(max_workers=self.max_workers)
        r2_pool = ThreadPoolExecutor(max_workers=self.max_workers)

        r1_futures = {}
        for i in range(self.ip_start, self.ip_end + 1):
            if self._stopped:
                break
            r1_futures[r1_pool.submit(self._ping_one, i, param)] = i

        r2_futures = {}

        while (r1_futures or r2_futures) and not self._stopped:
            for f in list(r1_futures.keys()):
                if f.done():
                    idx = r1_futures.pop(f)
                    _, alive = f.result()
                    if alive:
                        self.result_ready.emit(idx, 2)
                    else:
                        self.result_ready.emit(idx, 1)
                        r2_futures[r2_pool.submit(self._ping_one, idx, param)] = idx

            for f in list(r2_futures.keys()):
                if f.done():
                    idx = r2_futures.pop(f)
                    _, alive = f.result()
                    self.result_ready.emit(idx, 2 if alive else 0)

            if r1_futures or r2_futures:
                time.sleep(0.01)

        r1_pool.shutdown(wait=False)
        r2_pool.shutdown(wait=False)

    def _ping_one(self, ip_index, param):
        ip = f"{self.base_ip}.{ip_index}"
        try:
            kwargs = {"capture_output": True, "timeout": 3}
            if platform.system().lower() == "windows":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            ret = subprocess.run(["ping", param, "1", "-w", "1000", ip], **kwargs)
            alive = ret.returncode == 0
        except Exception:
            alive = False
        return ip_index, alive


COLOR_MAP = {
    2: QColor(76, 175, 80),
    1: QColor(255, 238, 180),
    0: QColor(255, 235, 59),
}
LABEL_MAP = {2: "通", 1: "待重试", 0: "不通"}


class IpCell(QFrame):
    def __init__(self, ip_index, parent=None):
        super().__init__(parent)
        self.ip_index = ip_index
        self.setFixedSize(26, 26)
        self._level = -1
        self._color = QColor(255, 255, 255)
        self.setToolTip(f"{ip_index} - 未扫描")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -2, -2)

        gradient = QLinearGradient(0, 0, 0, rect.height())
        base = self._color
        gradient.setColorAt(0, base.lighter(130))
        gradient.setColorAt(1, base)

        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(QColor(180, 180, 180), 1))
        painter.drawRoundedRect(rect, 3, 3)

        painter.setPen(Qt.black)
        font = QFont("Arial", 8)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, str(self.ip_index))

    def set_level(self, level):
        self._level = level
        self._color = COLOR_MAP.get(level, QColor(255, 255, 255))
        self.setToolTip(f"{self.ip_index} - {LABEL_MAP.get(level, '未扫描')}")
        self.update()


class PingScanner(QWidget):
    def __init__(self, lang="zh"):
        super().__init__()
        self.lang = lang
        title = "Ping Scanner" if self.lang == "en" else "网段 Ping 扫描器"
        self.setWindowTitle(title)
        self.setMinimumSize(680, 520)
        self.cells = []
        self.worker = None
        self._alive_count = 0
        self._dead_count = 0
        self._result_queue = []
        self._result_timer = QTimer()
        self._result_timer.setInterval(30)
        self._result_timer.timeout.connect(self._process_next_result)

        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(log_dir, f"PingScanner_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
            encoding="utf-8")
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger = logging.getLogger(f"{__name__}.PingScanner")
        self.logger.addHandler(fh)
        self.logger.setLevel(logging.INFO)
        self.logger.info("PingScanner initialized")

        self._setup_ui()

    def _tr(self, zh: str, en: str) -> str:
        """根据当前语言返回对应文本"""
        return en if self.lang == "en" else zh

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        top_panel = QFrame()
        top_panel.setFrameShape(QFrame.StyledPanel)
        top_panel.setStyleSheet("QFrame { background: #f5f5f5; }")
        top_layout = QVBoxLayout(top_panel)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(6)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(QLabel("起始地址:"))
        self.start_ip = QLineEdit()
        self.start_ip.setPlaceholderText("如 192.168.1.10")
        self.start_ip.setFixedWidth(150)
        self.start_ip.setFixedHeight(26)
        self.start_ip.textChanged.connect(self._update_preview)
        self.start_ip.textChanged.connect(self._validate_inputs)
        input_row.addWidget(self.start_ip)

        input_row.addWidget(QLabel("结束:"))
        self.end_ip = QSpinBox()
        self.end_ip.setRange(1, 254)
        self.end_ip.setValue(254)
        self.end_ip.setFixedWidth(65)
        self.end_ip.setFixedHeight(26)
        self.end_ip.valueChanged.connect(self._validate_inputs)
        input_row.addWidget(self.end_ip)

        self.end_preview = QLabel("")
        self.end_preview.setStyleSheet("color: #999;")
        input_row.addWidget(self.end_preview)

        input_row.addStretch()

        self.start_btn = QPushButton("Start Scan" if self.lang == "en" else self._tr("开始扫描", "Start Scan"))
        self.start_btn.setFixedWidth(100)
        self.start_btn.setFixedHeight(26)
        self.start_btn.setStyleSheet("QPushButton { background: #1976d2; color: white; border: none; padding: 4px 12px; border-radius: 3px; font-weight: bold; } QPushButton:disabled { background: #bbb; } QPushButton:hover { background: #1565c0; }")
        self.start_btn.clicked.connect(self.start_scan)
        input_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop" if self.lang == "en" else self._tr("停止", "Stop"))
        self.stop_btn.setFixedWidth(80)
        self.stop_btn.setFixedHeight(26)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("QPushButton { background: #d32f2f; color: white; border: none; padding: 4px 12px; border-radius: 3px; font-weight: bold; } QPushButton:disabled { background: #bbb; } QPushButton:hover { background: #c62828; }")
        self.stop_btn.clicked.connect(self.stop_scan)
        input_row.addWidget(self.stop_btn)

        top_layout.addLayout(input_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        status_row.addWidget(self.status_label)

        status_row.addStretch()

        legend_items = [
            (QColor(255, 255, 255), "未扫描"),
            (QColor(76, 175, 80), "通"),
            (QColor(255, 235, 59), "不通"),
        ]
        for clr, text in legend_items:
            f = QFrame()
            f.setFixedSize(14, 14)
            f.setStyleSheet(f"background: {clr.name()}; border: 1px solid #999;")
            status_row.addWidget(f)
            status_row.addWidget(QLabel(text))

        top_layout.addLayout(status_row)

        main_layout.addWidget(top_panel)

        grid_outer = QWidget()
        grid_outer.setStyleSheet("background: #fafafa; border: 1px solid #e0e0e0;")
        grid_outer_layout = QVBoxLayout(grid_outer)
        grid_outer_layout.setAlignment(Qt.AlignCenter)

        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(1)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)

        per_row = 20
        self.cells = [None]
        for i in range(1, 255):
            cell = IpCell(i)
            row = (i - 1) // per_row
            col = (i - 1) % per_row
            self.grid_layout.addWidget(cell, row, col)
            self.cells.append(cell)

        hbox = QHBoxLayout()
        hbox.setAlignment(Qt.AlignCenter)
        hbox.addLayout(self.grid_layout)
        grid_outer_layout.addLayout(hbox)
        main_layout.addWidget(grid_outer, 1)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(120)
        self.log_box.setStyleSheet("QTextEdit { background: #ffffff; color: #333; font-family: Consolas; font-size: 11px; border: 1px solid #ddd; }")
        main_layout.addWidget(self.log_box)

        self._log("就绪，等待扫描...")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {msg}")

    def _update_preview(self):
        text = self.start_ip.text().strip()
        parts = text.split(".")
        if len(parts) == 3 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            base = text
            end_val = self.end_ip.value()
            self.end_preview.setText(f"→ {base}.{end_val}")
        else:
            self.end_preview.setText("")

    def _validate_inputs(self):
        text = self.start_ip.text().strip()

        if not text:
            self.start_ip.setStyleSheet("border: 1px solid #d32f2f; background: #fff5f5;")
            self.start_ip.setToolTip("起始地址不能为空")
            return False

        parts = text.split(".")
        if len(parts) != 4:
            self.start_ip.setStyleSheet("border: 1px solid #d32f2f; background: #fff5f5;")
            self.start_ip.setToolTip("需要完整的 IPv4 地址，如 192.168.1.10")
            return False

        for p in parts:
            if p == "" or not p.isdigit():
                self.start_ip.setStyleSheet("border: 1px solid #d32f2f; background: #fff5f5;")
                self.start_ip.setToolTip("包含无效字符")
                return False
            val = int(p)
            if val < 0 or val > 255:
                self.start_ip.setStyleSheet("border: 1px solid #d32f2f; background: #fff5f5;")
                self.start_ip.setToolTip(f"每段 0-255，当前: {val}")
                return False
            if len(p) > 1 and p[0] == "0":
                self.start_ip.setStyleSheet("border: 1px solid #d32f2f; background: #fff5f5;")
                self.start_ip.setToolTip(f"不允许前导零: {p}")
                return False

        start_octet = int(parts[3])
        end_val = self.end_ip.value()
        if end_val < start_octet:
            self.start_ip.setStyleSheet("border: 1px solid #d32f2f; background: #fff5f5;")
            self.start_ip.setToolTip(f"结束地址 {end_val} 不能小于起始 {start_octet}")
            return False

        total = end_val - start_octet + 1
        if total > 254:
            self.start_ip.setStyleSheet("border: 1px solid #d32f2f; background: #fff5f5;")
            self.start_ip.setToolTip(f"扫描地址不能超过 254 个（当前 {total} 个）")
            return False

        self.start_ip.setStyleSheet("")
        self.start_ip.setToolTip("")
        return True

    def start_scan(self):
        text = self.start_ip.text().strip()

        if not self._validate_inputs():
            self.status_label.setText("请检查起始地址")
            return

        parts = text.split(".")
        base = ".".join(parts[:3])
        ip_start = int(parts[3])
        ip_end = self.end_ip.value()

        for i in range(1, 255):
            self.cells[i].set_level(-1)

        self._alive_count = 0
        self._dead_count = 0
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"正在扫描 {base}.{ip_start} - {base}.{ip_end} ...")
        self._log(f"开始扫描 {base}.{ip_start} - {base}.{ip_end} ({ip_end - ip_start + 1}个) 10线程 两轮并发")
        self.logger.info(f"开始扫描 {base}.{ip_start} - {base}.{ip_end} ({ip_end - ip_start + 1}个)")

        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()

        self.worker = PingWorker(base, ip_start, ip_end, 10)
        self.worker.result_ready.connect(self._on_result)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def stop_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
            self._log("用户手动停止扫描")
            self.logger.info("用户手动停止扫描")
            self._on_finished()

    def _on_result(self, idx, level):
        if 1 <= idx <= 254:
            self._result_queue.append((idx, level))
            if not self._result_timer.isActive():
                self._result_timer.start()

    def _process_next_result(self):
        if not self._result_queue:
            self._result_timer.stop()
            return
        idx, level = self._result_queue.pop(0)
        self.cells[idx].set_level(level)
        if level == 2:
            self._alive_count += 1
        elif level == 0:
            self._dead_count += 1

    def _on_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        total = self._alive_count + self._dead_count
        self.status_label.setText(f"扫描完成: {self._alive_count} 通, {self._dead_count} 不通 / 共 {total}")
        self._log(f"扫描完成: {self._alive_count} 通, {self._dead_count} 不通")
        self.logger.info(f"扫描完成: {self._alive_count} 通, {self._dead_count} 不通")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = PingScanner()
    w.show()
    sys.exit(app.exec())
