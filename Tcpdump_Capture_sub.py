# -*- coding: utf-8 -*-
import sys, os, json, logging, time, subprocess, platform
from datetime import datetime

import paramiko
from scp import SCPClient

from PySide6.QtWidgets import (QWidget, QApplication, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QTextEdit, QFileDialog,
    QMessageBox, QGroupBox, QComboBox, QFormLayout, QFrame, QProgressBar,
    QInputDialog, QCompleter, QDialog, QListWidget)
from PySide6.QtCore import QThread, Signal, Qt, QTimer, QEvent
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

XIAOMI_SS = """
    TcpdumpCapture {
        background:#f5f5f5;
    }
    QLabel {
        color:#1a1a1a;
        font-size:12px;
    }
    QLineEdit {
        background:white;
        border:1px solid #e0e0e0;
        border-radius:8px;
        padding:7px 12px;
        font-size:13px;
        color:#1a1a1a;
    }
    QLineEdit:focus {
        border-color:#ff6900;
    }
    QLineEdit:disabled {
        background:#f5f5f5;
        color:#999;
    }
    QComboBox {
        background:white;
        border:1px solid #e0e0e0;
        border-radius:8px;
        padding:7px 12px;
        font-size:13px;
        color:#1a1a1a;
        min-height:16px;
    }
    QComboBox:focus {
        border-color:#ff6900;
    }
    QComboBox::drop-down {
        border:none;
        width:22px;
    }
    QComboBox QAbstractItemView {
        background:white;
        border:1px solid #e0e0e0;
        border-radius:8px;
        selection-background-color:#fff3e6;
        selection-color:#1a1a1a;
        padding:4px;
    }
    QCheckBox {
        font-size:12px;
        color:#1a1a1a;
        spacing:6px;
    }
    QCheckBox::indicator {
        width:18px;
        height:18px;
        border:1px solid #d0d0d0;
        border-radius:4px;
        background:white;
    }
    QCheckBox::indicator:checked {
        background:#ff6900;
        border-color:#ff6900;
    }
    QTextEdit {
        background:#fafafa;
        border:1px solid #e8e8e8;
        border-radius:8px;
        padding:8px;
        font-size:11px;
        color:#1a1a1a;
    }
    QProgressBar {
        border:none;
        border-radius:5px;
        background:#e8e8e8;
        height:5px;
        text-align:center;
        font-size:10px;
        color:#999;
    }
    QProgressBar::chunk {
        background:#ff6900;
        border-radius:5px;
    }
"""


def _load_hosts():
    cfg = os.path.join(BASE_DIR, "config", "hosts.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


class CaptureWorker(QThread):
    log = Signal(str)
    progress = Signal(int)
    done = Signal(str)
    error = Signal(str)

    def __init__(self, host, port, user, pwd, cmd, remote_path, local_path, duration, compress=True):
        super().__init__()
        self.host = host
        self.port = int(port)
        self.user = user
        self.pwd = pwd
        self.cmd = cmd
        self.remote_path = remote_path
        self.local_path = local_path
        self.duration = int(duration)
        self.compress = compress

    def _ssh(self):
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(self.host, self.port, self.user, self.pwd, timeout=10)
        return c

    def _ssh_exec(self, cmd, timeout=10):
        c = self._ssh()
        chan = c.get_transport().open_session()
        chan.settimeout(timeout)
        chan.exec_command(cmd)
        out = chan.makefile("rb", -1).read()
        err = chan.makefile_stderr("rb", -1).read().decode("utf-8", errors="replace").strip()
        c.close()
        for enc in ("utf-8", "gbk"):
            try:
                return out.decode(enc).strip(), err
            except UnicodeDecodeError:
                continue
        return out.decode("utf-8", errors="replace").strip(), err

    def _ssh_nohup(self, cmd):
        c = self._ssh()
        chan = c.get_transport().open_session()
        chan.exec_command(cmd)
        chan.close()
        c.close()

    def run(self):
        try:
            self.log.emit(f"[tcpdump] Execute: {self.cmd}")
            self._ssh_exec("mkdir -p /opt/tar")
            self._ssh_nohup(f"nohup {self.cmd} > /dev/null 2>&1 &")
            self.log.emit(f"[tcpdump] Capturing {self.duration}s ...")
            for i in range(self.duration):
                time.sleep(1)
                self.progress.emit(int((i + 1) * 100 / self.duration))
            self.log.emit(f"[tcpdump] Stopping capture")
            self._ssh_exec("killall tcpdump 2>/dev/null; pkill tcpdump 2>/dev/null; pgrep tcpdump | xargs -r kill 2>/dev/null; sleep 2")
            self.log.emit(f"[tcpdump] Capture done: {self.remote_path}")

            out, err = self._ssh_exec(f"test -f {self.remote_path} && echo OK || echo MISSING")
            if out != "OK":
                out2, _ = self._ssh_exec("which tcpdump")
                out3, _ = self._ssh_exec("ls -la /opt/tar/ 2>&1; tcpdump --version 2>&1")
                raise RuntimeError(f"File not found!\nCheck tcpdump: {out2}\n/opt/tar/: {out3}")

            dl_path = self.remote_path
            dl_local = self.local_path
            if self.compress:
                gz_path = self.remote_path + ".gz"
                self.log.emit(f"[compress] gzip {self.remote_path}")
                self._ssh_exec(f"gzip -f {self.remote_path}", timeout=120)
                self.log.emit(f"[compress] Done: {gz_path}")
                dl_path = gz_path
                dl_local = self.local_path + ".gz"

            self.log.emit(f"[download] Transfer: {dl_path} -> {dl_local}")
            c = self._ssh()
            SCPClient(c.get_transport()).get(dl_path, dl_local)
            c.close()
            self._ssh_nohup(f"rm -f {dl_path}")
            self.log.emit(f"[done] Saved: {dl_local}")
            self.done.emit(dl_local)
        except Exception as e:
            emsg = str(e)
            self.log.emit(f"[error] {emsg}")
            self.error.emit(emsg)
            logger.exception("CaptureWorker error")


class ConnectWorker(QThread):
    result = Signal(bool, str)

    def __init__(self, host, port, user, pwd, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = int(port)
        self.user = user
        self.pwd = pwd

    def run(self):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(self.host, self.port, self.user, self.pwd, timeout=1)
            c.close()
            self.result.emit(True, "")
        except Exception as e:
            self.result.emit(False, str(e))


class CaptureStartWorker(QThread):
    started = Signal()
    error = Signal(str)

    def __init__(self, host, port, user, pwd, cmd):
        super().__init__()
        self.host = host
        self.port = int(port)
        self.user = user
        self.pwd = pwd
        self.cmd = cmd

    def _ssh(self):
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(self.host, self.port, self.user, self.pwd, timeout=10)
        return c

    def run(self):
        try:
            c = self._ssh()
            chan = c.get_transport().open_session()
            chan.exec_command(f"mkdir -p /opt/tar && nohup {self.cmd} > /dev/null 2>&1 &")
            chan.close()
            c.close()
            self.started.emit()
        except Exception as e:
            self.error.emit(str(e))


class CaptureStopWorker(QThread):
    log = Signal(str)
    done = Signal(str)
    error = Signal(str)

    def __init__(self, host, port, user, pwd, remote_path, local_path, compress=True):
        super().__init__()
        self.host = host
        self.port = int(port)
        self.user = user
        self.pwd = pwd
        self.remote_path = remote_path
        self.local_path = local_path
        self.compress = compress

    def _ssh(self):
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(self.host, self.port, self.user, self.pwd, timeout=10)
        return c

    def run(self):
        try:
            self.log.emit("[tcpdump] Stopping capture")
            c = self._ssh()
            chan = c.get_transport().open_session()
            chan.exec_command("killall tcpdump 2>/dev/null; pkill tcpdump 2>/dev/null; pgrep tcpdump | xargs -r kill 2>/dev/null; sleep 2")
            chan.close()
            c.close()

            c = self._ssh()
            chan = c.get_transport().open_session()
            chan.exec_command(f"test -f {self.remote_path} && echo OK || echo MISSING")
            out = chan.makefile("rb", -1).read().decode().strip()
            chan.close()
            c.close()
            if out != "OK":
                raise RuntimeError(f"File not found: {self.remote_path}")

            dl_path = self.remote_path
            dl_local = self.local_path
            if self.compress:
                gz_path = self.remote_path + ".gz"
                self.log.emit(f"[compress] gzip {self.remote_path}")
                c = self._ssh()
                chan = c.get_transport().open_session()
                chan.exec_command(f"gzip -f {self.remote_path}")
                chan.close()
                c.close()
                dl_path = gz_path
                dl_local = self.local_path + ".gz"

            self.log.emit(f"[download] {dl_path} -> {dl_local}")
            c = self._ssh()
            SCPClient(c.get_transport()).get(dl_path, dl_local)
            c.close()

            c = self._ssh()
            chan = c.get_transport().open_session()
            chan.exec_command(f"rm -f {dl_path}")
            chan.close()
            c.close()

            self.log.emit(f"[done] {dl_local}")
            self.done.emit(dl_local)
        except Exception as e:
            self.error.emit(str(e))


class TcpdumpCapture(QWidget):
    def __init__(self):
        super().__init__()
        self._hosts = _load_hosts()
        self._capturing = False
        self._timer_workers = []
        self._init_ui()

    def _card(self, title, content_widget):
        wrapper = QFrame()
        wrapper.setStyleSheet(
            "QFrame#card{border:none; border-radius:12px; background:white;}")
        wrapper.setObjectName("card")
        v = QVBoxLayout(wrapper)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(10)
        if title:
            lbl = QLabel(title)
            lbl.setStyleSheet("font-size:14px; font-weight:600; color:#1a1a1a; padding-bottom:2px;")
            v.addWidget(lbl)
        v.addWidget(content_widget)
        return wrapper

    def _secondary_btn(self, text):
        btn = QPushButton(text)
        btn.setStyleSheet(
            "QPushButton{background:#f5f5f5;color:#1a1a1a;border:1px solid #e0e0e0;"
            "border-radius:8px;padding:7px 16px;font-size:12px;}"
            "QPushButton:hover{background:#eee;}"
            "QPushButton:disabled{background:#fafafa;color:#ccc;}")
        return btn

    def _init_ui(self):
        self.setWindowTitle("Remote Packet Capture")
        self.resize(780, 700)
        self.setStyleSheet(XIAOMI_SS)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── Multi-Host Container ──
        self._host_rows = []
        self._host_container = QVBoxLayout()
        self._host_container.setSpacing(6)
        self._add_host_row()
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(36)
        add_btn.setStyleSheet("QPushButton{background:#00b894;color:white;border:none;border-radius:4px;font-size:18px;font-weight:bold;}QPushButton:hover{background:#00a381;}")
        add_btn.clicked.connect(lambda: self._add_host_row())
        self._host_container.addWidget(add_btn)
        layout.addLayout(self._host_container)

        # ── Summary Preview ──
        self.cmd_preview = QLineEdit()
        self.cmd_preview.setReadOnly(True)
        self.cmd_preview.setStyleSheet(
            "QLineEdit{background:#fafafa;border:1px solid #e0e0e0;border-radius:8px;"
            "padding:8px 12px;font-family:Menlo,'Consolas',monospace;font-size:11px;color:#1a1a1a;}")
        layout.addWidget(self.cmd_preview)

        # ── Save Path Row ──

        # ── Save Path Row ──
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self.save_path = QLineEdit()
        self.save_path.setPlaceholderText("Save Path")
        self.save_path.setText(r"F:\BaiduNetdiskDownload\Bangladesh\ICX_BTCL\ANS")
        path_row.addWidget(self.save_path)
        browse_btn = self._secondary_btn("Browse")
        browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(browse_btn)
        self.compress_cb = QCheckBox("Compress")
        self.compress_cb.setChecked(False)
        path_row.addWidget(self.compress_cb)
        layout.addLayout(path_row)

        # ── Action Row ──
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        mode_label = QLabel("Mode")
        mode_label.setStyleSheet("font-size:12px;color:#1a1a1a;")
        action_row.addWidget(mode_label)
        self.mode_cb = QComboBox()
        self.mode_cb.addItems(["Manual", "Timed"])
        self.mode_cb.setFixedWidth(100)
        self.mode_cb.currentIndexChanged.connect(self._on_mode_changed)
        action_row.addWidget(self.mode_cb)

        self.dur_label = QLabel("Duration")
        self.dur_label.setStyleSheet("font-size:12px;color:#1a1a1a;")
        action_row.addWidget(self.dur_label)
        self.duration_input = QLineEdit("30")
        self.duration_input.setFixedWidth(50)
        self.duration_input.setAlignment(Qt.AlignCenter)
        self.duration_input.textChanged.connect(self._update_preview)
        action_row.addWidget(self.duration_input)
        self.duration_unit = QComboBox()
        self.duration_unit.addItems(["sec", "min"])
        self.duration_unit.setFixedWidth(70)
        self.duration_unit.currentTextChanged.connect(self._update_preview)
        action_row.addWidget(self.duration_unit)

        action_row.addStretch()

        self.start_btn = QPushButton("Start")
        self.start_btn.setStyleSheet(
            "QPushButton{background:#4caf50;color:white;border:none;"
            "border-radius:8px;padding:8px 24px;font-size:13px;font-weight:600;}"
            "QPushButton:hover{background:#388e3c;}"
            "QPushButton:disabled{background:#c8e6c9;color:white;}")
        self.start_btn.clicked.connect(self._do_start)
        action_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet(
            "QPushButton{background:#f44336;color:white;border:none;"
            "border-radius:8px;padding:8px 24px;font-size:13px;font-weight:600;}"
            "QPushButton:hover{background:#d32f2f;}"
            "QPushButton:disabled{background:#ffcdd2;color:white;}")
        self.stop_btn.clicked.connect(self._do_manual_stop)
        self.stop_btn.setEnabled(False)
        action_row.addWidget(self.stop_btn)

        layout.addLayout(action_row)

        # ── Progress ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(6)
        layout.addWidget(self.progress_bar)

        # ── Log ──
        layout.addWidget(QLabel("Log"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Menlo", 10) if "Menlo" in QFont().families() else QFont("Consolas", 10))
        self.log_box.setFixedHeight(150)
        self.log_box.setStyleSheet(
            "QTextEdit{background:#fafafa;border:1px solid #e0e0e0;border-radius:8px;"
            "padding:8px;font-size:11px;color:#1a1a1a;}")

        log_container = QFrame()
        log_container.setObjectName("card")
        log_container.setStyleSheet("QFrame#card{border:none; border-radius:12px; background:white;}")
        log_v = QVBoxLayout(log_container)
        log_v.setContentsMargins(12, 10, 12, 12)
        log_v.addWidget(self.log_box)
        layout.addWidget(log_container)

        self._on_mode_changed(self.mode_cb.currentIndex())
        self._update_preview()
        if self._hosts and self._host_rows:
            QTimer.singleShot(100, lambda: self._host_rows[0]['cb'].setCurrentIndex(0))

    def _gen_cmd(self):
        self._update_preview()

    def _on_browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if d:
            self.save_path.setText(d)

    def _do_start(self):
        if self.mode_cb.currentIndex() == 0:
            self._do_manual_start()
        else:
            self._do_timer_start()

    def _do_timer_start(self):
        tasks = []
        for row in self._host_rows:
            idx = row['cb'].currentIndex()
            if idx < 0 or idx >= len(self._hosts):
                continue
            h = self._hosts[idx]
            filters = self._get_host_filters(row)
            ts = datetime.now().strftime('%Y%m%d_%H%M')
            for fi, f in enumerate(filters):
                filter_expr = self._build_filter_expr(f)
                out_name = f"{h.get('name','capture')}_f{fi+1}_{f['proto']}_{ts}.pcap"
                tasks.append((h, filter_expr, out_name))
        if not tasks:
            QMessageBox.warning(self, "Warning", "No host selected")
            return
        save_dir = self.save_path.text().strip()
        if not save_dir:
            QMessageBox.warning(self, "Warning", "Please select a local save directory")
            return
        raw_dur = self.duration_input.text().strip() or "30"
        unit = self.duration_unit.currentText()
        duration = str(int(raw_dur) * 60) if unit == "min" else raw_dur

        if self._timer_workers:
            for w in self._timer_workers:
                if w.isRunning():
                    w.terminate()
            self._timer_workers = []

        self._capturing = True
        self._capture_counts = len(tasks)
        self._capture_done = 0
        self._capture_errors = 0
        self._capture_results = []
        self.mode_cb.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        for ti, (h, filter_expr, out_name) in enumerate(tasks):
            remote_path = f"/opt/tar/{out_name}"
            local_path = os.path.join(save_dir, out_name)
            cmd = f"tcpdump -i any -w {remote_path} {filter_expr}"
            self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [timed] {h['host']}:{h.get('port',22)} → {out_name}")
            self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [command] {cmd}")

            w = CaptureWorker(h["host"], h.get("port", 22), h["user"], h.get("pwd", ""),
                              cmd, remote_path, local_path, duration, self.compress_cb.isChecked())
            w.log.connect(self._on_log)
            w.progress.connect(lambda v, orig=ti: self._on_multi_progress(orig, v))
            w.done.connect(self._on_multi_done)
            w.error.connect(self._on_multi_error)
            w.finished.connect(self._on_multi_finished)
            w.start()
            self._timer_workers.append(w)

    def _on_multi_progress(self, idx, val):
        count = len(self._timer_workers) if self._timer_workers else 1
        total = sum(
            (w.property("_prog") or 0) if w != self._timer_workers[idx] else val
            for i, w in enumerate(self._timer_workers)
        )
        if self._timer_workers:
            self._timer_workers[idx].setProperty("_prog", val)
        self.progress_bar.setValue(int(total / count))

    def _on_multi_done(self, local_path):
        self._capture_done += 1
        self._capture_results.append(local_path)
        self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [done] {local_path}")

    def _on_multi_error(self, msg):
        self._capture_errors += 1
        self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [error] {msg}")

    def _on_multi_finished(self):
        if self._capture_done + self._capture_errors >= self._capture_counts:
            self._capturing = False
            self.mode_cb.setEnabled(True)
            self.progress_bar.setVisible(False)
            self._on_mode_changed(self.mode_cb.currentIndex())
            if self._capture_results:
                self._show_done_dialog(self._capture_results)
            self._timer_workers = []

    def _on_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {msg}")

    def _show_done_dialog(self, _paths):
        self.progress_bar.setValue(100)
        self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [done] All captures complete.")
        save_dir = self.save_path.text().strip()
        if save_dir:
            subprocess.run(['explorer', os.path.normpath(save_dir)], creationflags=subprocess.CREATE_NO_WINDOW)

    def _on_worker_finished(self):
        pass

    # ── Manual Mode ──

    def _on_mode_changed(self, idx):
        if idx == 0:
            self.dur_label.setVisible(False)
            self.duration_input.setVisible(False)
            self.duration_unit.setVisible(False)
            self.start_btn.setText("Start")
            self.start_btn.setStyleSheet(
                "QPushButton{background:#4caf50;color:white;border:none;"
                "border-radius:8px;padding:8px 24px;font-size:13px;font-weight:600;}"
                "QPushButton:hover{background:#388e3c;}"
                "QPushButton:disabled{background:#c8e6c9;color:white;}")
            self.start_btn.setEnabled(True)
            self.start_btn.setVisible(True)
            self.stop_btn.setEnabled(False)
            self.stop_btn.setVisible(True)
        else:
            self.dur_label.setVisible(True)
            self.duration_input.setVisible(True)
            self.duration_unit.setVisible(True)
            self.start_btn.setText("Start & Download")
            self.start_btn.setStyleSheet(
                "QPushButton{background:#ff6900;color:white;border:none;"
                "border-radius:8px;padding:8px 24px;font-size:13px;font-weight:600;}"
                "QPushButton:hover{background:#e55e00;}"
                "QPushButton:disabled{background:#f5d5c0;color:white;}")
            self.start_btn.setEnabled(True)
            self.start_btn.setVisible(True)
            self.stop_btn.setEnabled(False)
            self.stop_btn.setVisible(False)
        if not self._capturing:
            pass

    def _do_manual_start(self):
        tasks = []
        for row in self._host_rows:
            idx = row['cb'].currentIndex()
            if idx < 0 or idx >= len(self._hosts):
                continue
            h = self._hosts[idx]
            filters = self._get_host_filters(row)
            ts = datetime.now().strftime('%Y%m%d_%H%M')
            for fi, f in enumerate(filters):
                filter_expr = self._build_filter_expr(f)
                out_name = f"{h.get('name','capture')}_f{fi+1}_{f['proto']}_{ts}.pcap"
                tasks.append((h, filter_expr, out_name))
        if not tasks:
            QMessageBox.warning(self, "Warning", "No host selected")
            return
        save_dir = self.save_path.text().strip()
        if not save_dir:
            QMessageBox.warning(self, "Warning", "Please select a local save directory")
            return

        self._manual_workers = []
        self._manual_errors = 0
        self._manual_started_count = 0
        self._capturing = True
        self.mode_cb.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        for h, filter_expr, out_name in tasks:
            remote_path = f"/opt/tar/{out_name}"
            local_path = os.path.join(save_dir, out_name)
            cmd = f"tcpdump -i any -w {remote_path} {filter_expr}"
            self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [manual] Start {h['host']}:{h.get('port',22)} → {out_name}")
            self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [command] {cmd}")

            w = CaptureStartWorker(h["host"], h.get("port", 22), h["user"], h.get("pwd", ""), cmd)
            w._out_name = out_name
            w._remote_path = remote_path
            w._local_path = local_path
            w._hostname = h['host']
            w.started.connect(self._on_manual_started)
            w.error.connect(self._on_manual_error)
            w.finished.connect(lambda: None)
            w.start()
            self._manual_workers.append(w)

    def _on_manual_started(self):
        self._manual_started_count += 1

    def _on_manual_error(self, msg):
        self._manual_errors += 1
        self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [error] {msg}")
        if self._manual_errors >= len(self._manual_workers):
            self._capturing = False
            self.mode_cb.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def _do_manual_stop(self):
        if not self._manual_workers:
            return
        self.stop_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self._stop_workers = []
        self._stop_done = 0
        self._stop_errors = 0
        self._stop_results = []

        for w in self._manual_workers:
            h_name = getattr(w, '_hostname', '')
            self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [manual] Stop & download {h_name}")

            sw = CaptureStopWorker(
                w.host, w.port, w.user, w.pwd,
                w._remote_path, w._local_path, self.compress_cb.isChecked())
            sw.log.connect(self._on_log)
            sw.done.connect(self._on_manual_stopped)
            sw.error.connect(self._on_manual_stop_error)
            sw.finished.connect(self._on_stop_finished)
            sw.start()
            self._stop_workers.append(sw)

    def _on_manual_stopped(self, local_path):
        self._stop_done += 1
        self._stop_results.append(local_path)
        self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [done] {local_path}")

    def _on_manual_stop_error(self, msg):
        self._stop_errors += 1
        self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] [error] {msg}")

    def _on_stop_finished(self):
        if self._stop_done + self._stop_errors >= len(self._stop_workers):
            self._capturing = False
            self.mode_cb.setEnabled(True)
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._on_mode_changed(self.mode_cb.currentIndex())
            if self._stop_results:
                self._show_done_dialog(self._stop_results)

    # ── Multi-Host Management ──

    def _add_host_row(self, prefill_host_idx=None):
        idx = len(self._host_rows)
        row = {}
        frame = QFrame()
        frame.setStyleSheet("QFrame{background:white;border:1px solid #dfe6e9;border-radius:6px;padding:8px 12px;}")
        main_layout = QVBoxLayout(frame)
        main_layout.setContentsMargins(8, 4, 8, 4)
        main_layout.setSpacing(6)

        # ── Host bar ──
        host_bar = QHBoxLayout()
        host_bar.setSpacing(8)

        first = QWidget()
        first.setFixedSize(72, 28)
        fl = QHBoxLayout(first)
        fl.setContentsMargins(2, 0, 2, 0)
        if idx == 0:
            lbl = QLabel("🔗 Host:")
            lbl.setStyleSheet("font-size:12px;color:#1a1a1a;")
            fl.addWidget(lbl)
        else:
            rm = QPushButton("✕")
            rm.setFixedSize(24, 24)
            rm.setStyleSheet("QPushButton{background:#e74c3c;color:white;border:none;border-radius:12px;font-size:12px;font-weight:bold;}QPushButton:hover{background:#c0392b;}")
            rm.clicked.connect(lambda: self._remove_host_row(frame))
            fl.addWidget(rm)
        host_bar.addWidget(first)

        cb = QComboBox()
        cb.setMinimumWidth(400)
        cb.setStyleSheet("""
            QComboBox { border: 1px solid #dfe6e9; border-radius: 4px; padding: 6px 8px; font-size: 13px; background: #f8f9fa; }
            QComboBox:focus { border: 1px solid #0984e3; background: white; }
            QComboBox QAbstractItemView { background: white; color: #1a1a1a; selection-background-color: #e8f0fe; selection-color: #1a1a1a; }
        """)
        cb.setEditable(True)
        cb.setPlaceholderText("Select or type user@host:port")
        cb.setInsertPolicy(QComboBox.NoInsert)
        for h in self._hosts:
            display = f"{h.get('desc', h['name'])} — {h['host']}:{h.get('port', 22)} ({h['user']})"
            cb.addItem(display, h)
        cb.lineEdit().installEventFilter(self)
        cb.currentIndexChanged.connect(lambda: self._on_host_selected(frame))
        host_bar.addWidget(cb)
        row['cb'] = cb

        manage_btn = QPushButton("Manage")
        manage_btn.setStyleSheet("QPushButton{background:#f8f9fa;color:#636e72;border:1px solid #dfe6e9;border-radius:4px;padding:6px 12px;font-size:12px;}QPushButton:hover{background:#e8e8e8;}")
        manage_btn.clicked.connect(lambda: self._manage_hosts(lambda: self._reload_hosts()))
        host_bar.addWidget(manage_btn)

        connect_btn = QPushButton("Connect")
        connect_btn.setStyleSheet("QPushButton{background:#0984e3;color:white;border:none;border-radius:4px;padding:6px 18px;font-size:13px;font-weight:bold;}QPushButton:hover{background:#0873c4;}")
        connect_btn.clicked.connect(lambda: self._test_connection(frame))
        host_bar.addWidget(connect_btn)
        row['connect_btn'] = connect_btn

        host_bar.addStretch()
        conn_status = QLabel("● Disconnected")
        conn_status.setStyleSheet("color:#e74c3c;font-weight:bold;font-size:13px;")
        host_bar.addWidget(conn_status)
        row['conn_status'] = conn_status

        main_layout.addLayout(host_bar)

        # ── Filter section ──
        row['filters'] = []
        filter_container = QVBoxLayout()
        filter_container.setSpacing(4)
        row['filter_container'] = filter_container
        main_layout.addLayout(filter_container)
        self._add_filter_row(row)

        add_f_btn = QPushButton("+ Add Filter")
        add_f_btn.setStyleSheet("QPushButton{background:#f0f3f5;color:#636e72;border:1px solid #dfe6e9;border-radius:4px;padding:3px 10px;font-size:11px;}QPushButton:hover{background:#e8e8e8;}")
        add_f_btn.clicked.connect(lambda: self._add_filter_row(row))
        main_layout.addWidget(add_f_btn)

        row['frame'] = frame
        row['_conn_worker'] = None
        self._host_rows.append(row)

        host_layout = self._host_container
        host_layout.insertWidget(host_layout.count() - 1, frame)

        if prefill_host_idx is not None and 0 <= prefill_host_idx < len(self._hosts):
            cb.setCurrentIndex(prefill_host_idx)

        return row

    def _add_filter_row(self, row, data=None):
        fw = {}
        frame = QFrame()
        frame.setStyleSheet("QFrame{background:#f8f9fa;border:1px solid #e8e8e8;border-radius:4px;padding:4px 8px;}")
        rl = QHBoxLayout(frame)
        rl.setContentsMargins(4, 2, 4, 2)
        rl.setSpacing(4)

        fi = len(row['filters'])

        if fi > 0:
            rm_container = QWidget()
            rm_container.setFixedSize(28, 22)
            rml = QHBoxLayout(rm_container)
            rml.setContentsMargins(0, 0, 0, 0)
            rm_btn = QPushButton("✕")
            rm_btn.setFixedSize(18, 18)
            rm_btn.setStyleSheet("QPushButton{background:#e74c3c;color:white;border:none;border-radius:9px;font-size:9px;font-weight:bold;}QPushButton:hover{background:#c0392b;}")
            rm_btn.clicked.connect(lambda: self._remove_filter_row(row, frame))
            rml.addWidget(rm_btn)
            rl.addWidget(rm_container)
        else:
            spacer = QWidget()
            spacer.setFixedSize(28, 22)
            rl.addWidget(spacer)

        rl.addWidget(QLabel(f"F{fi+1}:"))

        proto = QComboBox()
        proto.addItems(["any", "tcp", "udp", "icmp", "arp", "sip"])
        proto.setFixedWidth(70)
        if data:
            idx = proto.findText(data['proto'])
            if idx >= 0: proto.setCurrentIndex(idx)
        fw['proto'] = proto
        rl.addWidget(proto)

        src_ip = QLineEdit()
        src_ip.setPlaceholderText("Src IP")
        src_ip.setFixedWidth(120)
        if data: src_ip.setText(data['src_ip'])
        fw['src_ip'] = src_ip
        rl.addWidget(src_ip)

        rl.addWidget(QLabel("→"))

        dst_ip = QLineEdit()
        dst_ip.setPlaceholderText("Dst IP")
        dst_ip.setFixedWidth(120)
        if data: dst_ip.setText(data['dst_ip'])
        fw['dst_ip'] = dst_ip
        rl.addWidget(dst_ip)

        src_port = QLineEdit()
        src_port.setPlaceholderText("Sport")
        src_port.setFixedWidth(65)
        if data: src_port.setText(data['src_port'])
        fw['src_port'] = src_port
        rl.addWidget(src_port)

        rl.addWidget(QLabel("→"))

        dst_port = QLineEdit()
        dst_port.setPlaceholderText("Dport")
        dst_port.setFixedWidth(65)
        if data: dst_port.setText(data['dst_port'])
        fw['dst_port'] = dst_port
        rl.addWidget(dst_port)

        dir_cb = QCheckBox("Dir")
        dir_cb.setChecked(data['directional'] if data else False)
        fw['directional'] = dir_cb
        rl.addWidget(dir_cb)

        rl.addStretch()
        fw['frame'] = frame
        row['filters'].append(fw)
        row['filter_container'].addWidget(frame)

        proto.currentTextChanged.connect(self._update_preview)
        src_ip.textChanged.connect(self._update_preview)
        dst_ip.textChanged.connect(self._update_preview)
        src_port.textChanged.connect(self._update_preview)
        dst_port.textChanged.connect(self._update_preview)
        dir_cb.toggled.connect(self._update_preview)

        self._update_preview()
        return fw

    def _remove_filter_row(self, row, frame):
        for i, fw in enumerate(row['filters']):
            if fw['frame'] is frame:
                row['filters'].pop(i)
                frame.setParent(None)
                frame.deleteLater()
                break
        for i, fw in enumerate(row['filters']):
            lbl = fw['frame'].layout().itemAt(1).widget()
            if lbl:
                lbl.setText(f"F{i+1}:")
        self._update_preview()

    def _get_host_filters(self, row):
        result = []
        for fw in row['filters']:
            result.append({
                'proto': fw['proto'].currentText(),
                'src_ip': fw['src_ip'].text().strip(),
                'dst_ip': fw['dst_ip'].text().strip(),
                'src_port': fw['src_port'].text().strip(),
                'dst_port': fw['dst_port'].text().strip(),
                'directional': fw['directional'].isChecked(),
            })
        return result

    def _build_filter_expr(self, f):
        parts = []
        if f['proto'] != "any":
            parts.append(f['proto'])
        if f['directional']:
            if f['src_ip']: parts.append(f"src {f['src_ip']}")
            if f['dst_ip']: parts.append(f"dst {f['dst_ip']}")
            if f['src_port']: parts.append(f"src port {f['src_port']}")
            if f['dst_port']: parts.append(f"dst port {f['dst_port']}")
        else:
            if f['src_ip']: parts.append(f"host {f['src_ip']}")
            if f['dst_ip']: parts.append(f"host {f['dst_ip']}")
            if f['src_port']: parts.append(f"port {f['src_port']}")
            if f['dst_port']: parts.append(f"port {f['dst_port']}")
        return " and ".join(parts) if parts else ""

    def _update_preview(self):
        if not hasattr(self, 'cmd_preview'):
            return
        total = 0
        host_count = 0
        for r in self._host_rows:
            if r['cb'].currentIndex() >= 0 and r['cb'].currentIndex() < len(self._hosts):
                host_count += 1
                total += len(r['filters'])
        if total == 0:
            self.cmd_preview.setText("No captures configured")
        elif total == 1:
            self.cmd_preview.setText("1 capture on 1 host")
        else:
            self.cmd_preview.setText(f"{total} captures on {host_count} host(s)")

    def _remove_host_row(self, frame):
        for i, r in enumerate(self._host_rows):
            if r['frame'] is frame:
                self._host_rows.pop(i)
                frame.setParent(None)
                frame.deleteLater()
                break
        # ensure at least one row
        if not self._host_rows:
            self._add_host_row()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            for r in self._host_rows:
                if obj == r['cb'].lineEdit():
                    r['cb'].showPopup()
                    return True
        return super().eventFilter(obj, event)

    def _on_host_selected(self, frame):
        for r in self._host_rows:
            if r['frame'] is frame:
                self._set_conn_status(r, False)
                self._test_connection(r)
                break

    def _test_connection(self, row):
        idx = row['cb'].currentIndex()
        if idx < 0 or idx >= len(self._hosts):
            return
        h = self._hosts[idx]
        row['connect_btn'].setEnabled(False)
        row['connect_btn'].setText("Connecting...")
        row['conn_status'].setText("● Testing...")
        row['conn_status'].setStyleSheet("color:#fdd835;font-weight:bold;font-size:13px;")
        w = ConnectWorker(h["host"], h.get("port", 22), h["user"], h.get("pwd", ""))
        row['_conn_worker'] = w
        w.result.connect(lambda ok, msg, r=row: self._on_conn_result(r, ok, msg))
        w.finished.connect(lambda r=row: self._on_conn_finished(r))
        w.start()

    def _on_conn_result(self, row, ok, msg):
        self._set_conn_status(row, ok)

    def _on_conn_finished(self, row):
        row['connect_btn'].setEnabled(True)
        row['connect_btn'].setText("Test" if row['conn_status'].text().startswith("● Connected") else "Connect")
        row['_conn_worker'] = None

    def _set_conn_status(self, row, ok):
        if ok:
            row['conn_status'].setText("● Connected")
            row['conn_status'].setStyleSheet("color:#27ae60;font-weight:bold;font-size:13px;")
        else:
            row['conn_status'].setText("● Disconnected")
            row['conn_status'].setStyleSheet("color:#e74c3c;font-weight:bold;font-size:13px;")

    def _manage_hosts(self, on_close=None):
        dlg = QDialog(self)
        dlg.setWindowTitle("Manage Hosts")
        dlg.resize(520, 380)
        layout = QVBoxLayout(dlg)
        host_list = QListWidget()
        layout.addWidget(QLabel("Saved Hosts:"))
        layout.addWidget(host_list)
        form = QFormLayout()
        form.setSpacing(6)
        ip_edit = QLineEdit(); ip_edit.setPlaceholderText("192.168.1.100")
        port_edit = QLineEdit("22"); port_edit.setFixedWidth(80)
        user_edit = QLineEdit("root")
        pwd_edit = QLineEdit(); pwd_edit.setEchoMode(QLineEdit.Password)
        desc_edit = QLineEdit(); desc_edit.setPlaceholderText("e.g. Beijing-Core-MGCF")
        form.addRow("IP:", ip_edit)
        p_row = QHBoxLayout(); p_row.addWidget(port_edit); p_row.addStretch()
        form.addRow("Port:", p_row)
        form.addRow("User:", user_edit)
        form.addRow("Password:", pwd_edit)
        form.addRow("Desc:", desc_edit)
        layout.addLayout(form)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add"); add_btn.setStyleSheet("QPushButton{background:#0984e3;color:white;padding:6px 16px;border:none;border-radius:4px;}")
        update_btn = QPushButton("Update"); update_btn.setStyleSheet("QPushButton{background:#f0f3f5;color:#333;border:1px solid #ccc;padding:6px 16px;border-radius:4px;}")
        del_btn = QPushButton("Delete"); del_btn.setStyleSheet("QPushButton{background:#e74c3c;color:white;padding:6px 16px;border:none;border-radius:4px;}")
        btn_row.addWidget(add_btn); btn_row.addWidget(update_btn); btn_row.addWidget(del_btn); btn_row.addStretch()
        layout.addLayout(btn_row)

        def refresh_list():
            host_list.clear()
            for h in self._hosts:
                host_list.addItem(f"{h.get('desc', h['name'])} — {h['host']}:{h.get('port',22)} ({h['user']})")

        def on_select():
            row_idx = host_list.currentRow()
            if 0 <= row_idx < len(self._hosts):
                h = self._hosts[row_idx]
                ip_edit.setText(h["host"]); port_edit.setText(str(h.get("port",22)))
                user_edit.setText(h["user"]); pwd_edit.setText(h.get("pwd",""))
                desc_edit.setText(h.get("desc",""))

        host_list.currentRowChanged.connect(on_select)
        refresh_list()

        def on_add():
            if not ip_edit.text().strip(): return
            self._hosts.append(dict(host=ip_edit.text().strip(), port=int(port_edit.text().strip() or "22"),
                user=user_edit.text().strip() or "root", pwd=pwd_edit.text(), name=desc_edit.text().strip() or ip_edit.text().strip(), desc=desc_edit.text().strip()))
            self._save_hosts()
            refresh_list(); self._reload_hosts()
            ip_edit.clear(); pwd_edit.clear(); desc_edit.clear(); port_edit.setText("22"); user_edit.setText("root")

        add_btn.clicked.connect(on_add)

        def on_update():
            row_idx = host_list.currentRow()
            if row_idx < 0 or not ip_edit.text().strip(): return
            self._hosts[row_idx] = dict(host=ip_edit.text().strip(), port=int(port_edit.text().strip() or "22"),
                user=user_edit.text().strip() or "root", pwd=pwd_edit.text(), name=desc_edit.text().strip() or ip_edit.text().strip(), desc=desc_edit.text().strip())
            self._save_hosts()
            refresh_list(); self._reload_hosts()

        update_btn.clicked.connect(on_update)

        def on_del():
            row_idx = host_list.currentRow()
            if row_idx < 0: return
            if QMessageBox.question(dlg, "Confirm", f"Delete {self._hosts[row_idx]['host']}?") == QMessageBox.Yes:
                self._hosts.pop(row_idx); self._save_hosts(); refresh_list(); self._reload_hosts()

        del_btn.clicked.connect(on_del)
        dlg.finished.connect(lambda: on_close() if on_close else None)
        dlg.exec()

    def _save_hosts(self):
        cfg = os.path.join(BASE_DIR, "config", "hosts.json")
        try:
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump(self._hosts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Save Failed", str(e))

    def _reload_hosts(self):
        for r in self._host_rows:
            cb = r['cb']
            cb.blockSignals(True)
            current = cb.currentData()
            cb.clear()
            for h in self._hosts:
                display = f"{h.get('desc', h['name'])} — {h['host']}:{h.get('port', 22)} ({h['user']})"
                cb.addItem(display, h)
            # restore selection
            if current:
                for i in range(cb.count()):
                    if cb.itemData(i) == current:
                        cb.setCurrentIndex(i)
                        break
            cb.blockSignals(False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    w = TcpdumpCapture()
    w.show()
    sys.exit(app.exec())
