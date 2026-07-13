# -*- coding: utf-8 -*-
import sys, os, json, logging, time, threading, difflib, posixpath, re, subprocess, tarfile, tempfile
from datetime import datetime
from collections import defaultdict

import paramiko
from scp import SCPClient

from PySide6.QtWidgets import (QWidget, QApplication, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QTextEdit, QFileDialog,
    QMessageBox, QComboBox, QFormLayout, QFrame, QProgressBar, QGroupBox,
    QGridLayout, QDialog, QListWidget, QListWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMenu,
    QScrollArea, QSplitter, QTreeWidget, QTreeWidgetItem, QSizePolicy)
from PySide6.QtCore import QThread, Signal, Qt, QTimer, QEvent
from PySide6.QtGui import QFont, QAction

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
HOSTS_PATH = os.path.join(BASE_DIR, "config", "hosts.json")
NE_CONFIG_PATH = os.path.join(BASE_DIR, "config", "ims_ne_config.json")
LOG_NE_CONFIG_PATH = os.path.join(BASE_DIR, "config", "log_ne_config.json")

def _load_hosts():
    try:
        with open(HOSTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def _save_hosts(hosts):
    try:
        with open(HOSTS_PATH, "w", encoding="utf-8") as f:
            json.dump(hosts, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        QMessageBox.warning(None, "Save Failed", str(e))
        return False

# ═══════════════════════════════════════════════
#  Theme System
# ═══════════════════════════════════════════════

_T = {
    "primary": "#0984e3",
    "primary_hover": "#0873c4",
    "primary_light": "#e8f4fd",
    "accent": "#ff6900",
    "accent_light": "#fff3e6",
    "success": "#00b894",
    "success_hover": "#00a381",
    "danger": "#e74c3c",
    "danger_hover": "#c0392b",
    "warning": "#f39c12",
    "bg": "#f0f2f5",
    "surface": "#ffffff",
    "surface_alt": "#f8f9fa",
    "border": "#e0e0e0",
    "border_light": "#f0f0f0",
    "text": "#1a1a1a",
    "text_secondary": "#636e72",
    "text_hint": "#999999",
    "shadow": "rgba(0,0,0,0.06)",
    "card_radius": "10px",
    "btn_radius": "6px",
    "input_radius": "6px",
    "gap_xs": "2px",
    "gap_sm": "4px",
    "gap_md": "8px",
    "gap_lg": "12px",
    "gap_xl": "16px",
    "gap_2xl": "24px",
    "font_sm": "11px",
    "font_md": "12px",
    "font_lg": "13px",
    "font_xl": "14px",
    "font_title": "16px",
}

STYLE_XIAOMI = f"""
    QWidget {{ background:{_T['bg']}; }}
    QLabel {{ color:{_T['text']}; font-size:{_T['font_md']}; }}
    QLineEdit {{
        background:{_T['surface']}; border:1px solid {_T['border']};
        border-radius:{_T['input_radius']}; padding:6px 10px; font-size:{_T['font_lg']};
    }}
    QLineEdit:focus {{ border-color:{_T['primary']}; }}
    QLineEdit:disabled {{ background:{_T['surface_alt']}; color:{_T['text_hint']}; }}
    QComboBox {{
        background:{_T['surface']}; border:1px solid {_T['border']};
        border-radius:{_T['input_radius']}; padding:6px 10px; font-size:{_T['font_lg']}; min-height:16px;
    }}
    QComboBox:focus {{ border-color:{_T['primary']}; }}
    QComboBox::drop-down {{ border:none; width:22px; }}
    QComboBox QAbstractItemView {{
        background:{_T['surface']}; border:1px solid {_T['border']};
        border-radius:{_T['btn_radius']}; selection-background-color:{_T['primary_light']};
        selection-color:{_T['text']}; padding:4px;
    }}
    QCheckBox {{ color:{_T['text']}; font-size:{_T['font_md']}; spacing:6px; }}
    QCheckBox::indicator {{ width:16px; height:16px; border:1px solid {_T['border']}; border-radius:3px; background:{_T['surface']}; }}
    QCheckBox::indicator:checked {{ background:{_T['primary']}; border-color:{_T['primary']}; }}
    QGroupBox {{ font-weight:bold; border:1px solid {_T['border']}; border-radius:{_T['card_radius']};
        margin-top:12px; padding:14px 12px 12px; background:{_T['surface']}; font-size:{_T['font_lg']}; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:14px; padding:0 8px; color:{_T['text']}; }}
    QScrollBar:vertical {{ background:{_T['surface_alt']}; width:8px; border-radius:4px; }}
    QScrollBar::handle:vertical {{ background:{_T['border']}; border-radius:4px; min-height:24px; }}
    QScrollBar::handle:vertical:hover {{ background:{_T['text_hint']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:none; }}
    QProgressBar {{ border:none; border-radius:5px; background:{_T['border']}; height:4px; text-align:center; }}
    QProgressBar::chunk {{ background:{_T['accent']}; border-radius:5px; }}
"""

# ═══════════════════════════════════════════════
#  Shared Workers
# ═══════════════════════════════════════════════

class ConnectWorker(QThread):
    result = Signal(bool, str)
    def __init__(self, host, port, user, pwd):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd
    def run(self):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(self.host, self.port, self.user, self.pwd, timeout=1)
            c.close()
            self.result.emit(True, "")
        except Exception as e:
            self.result.emit(False, str(e))

# ═══════════════════════════════════════════════
#  ConfigDiffDialog (from IMS_NE_Upgrade)
# ═══════════════════════════════════════════════

class InterfaceScanWorker(QThread):
    result = Signal(list, str)
    def __init__(self, host, port, user, pwd):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd
    def run(self):
        c = None
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(self.host, self.port, self.user, self.pwd, timeout=8, banner_timeout=8, auth_timeout=8)
            cmd = (
                "for p in /sys/class/net/*; do "
                "n=${p##*/}; [ \"$n\" = lo ] && continue; "
                "state=$(cat \"$p/operstate\" 2>/dev/null || echo unknown); "
                "addr=$(ip -o -4 addr show dev \"$n\" 2>/dev/null | awk '{print $4}' | paste -sd, -); "
                "printf '%s|%s|%s\\n' \"$n\" \"$state\" \"$addr\"; "
                "done"
            )
            _, stdout, stderr = c.exec_command(cmd, timeout=15)
            raw = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            interfaces = []
            for line in raw.splitlines():
                parts = line.split("|", 2)
                if not parts or not parts[0].strip():
                    continue
                name = parts[0].strip().split("@", 1)[0]
                state = parts[1].strip() if len(parts) > 1 else ""
                addr = parts[2].strip() if len(parts) > 2 else ""
                if name:
                    interfaces.append({"name": name, "state": state, "addr": addr})
            self.result.emit(interfaces, err)
        except Exception as e:
            self.result.emit([], str(e))
        finally:
            try:
                if c: c.close()
            except:
                pass

class ConfigDiffDialog(QDialog):
    def __init__(self, diff_items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置文件对比 - 逐块确认差异")
        self.resize(1000, 700)
        self.diff_items = diff_items
        self.results = []
        self._file_index = 0; self._hunk_index = 0
        self._hunk_decisions = []
        self._file_merged = {}
        self._build_ui()
    def _tr(self, zh, en):
        """根据 self.lang 返回对应文本"""
        return en if self.lang == 'en' else zh


    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("font-size:13px;color:#2d3436;padding:4px 0;")
        layout.addWidget(self.progress_label)
        self.file_label = QLabel()
        self.file_label.setStyleSheet("font-size:11px;color:#636e72;padding:2px 0;")
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)
        self.diff_view = QTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(QFont("Consolas", 10))
        self.diff_view.setStyleSheet("background:#1e1e1e;color:#d4d4d4;border-radius:6px;padding:8px;")
        layout.addWidget(self.diff_view, 1)
        btn_row = QHBoxLayout()
        btn_accept = QPushButton("接受此修改"); btn_accept.setStyleSheet("QPushButton{background:#27ae60;color:white;font-weight:bold;padding:10px 32px;border:none;border-radius:6px;font-size:14px;}QPushButton:hover{background:#219a52;}")
        btn_reject = QPushButton("保留旧版"); btn_reject.setStyleSheet("QPushButton{background:#e67e22;color:white;font-weight:bold;padding:10px 32px;border:none;border-radius:6px;font-size:14px;}QPushButton:hover{background:#d35400;}")
        btn_all_acc = QPushButton("全部接受"); btn_all_acc.setStyleSheet("QPushButton{font-size:11px;padding:6px 16px;border:1px solid #0984e3;color:#0984e3;border-radius:4px;background:white;}QPushButton:hover{background:#0984e3;color:white;}")
        btn_all_rej = QPushButton("全部旧版"); btn_all_rej.setStyleSheet("QPushButton{font-size:11px;padding:6px 16px;border:1px solid #e74c3c;color:#e74c3c;border-radius:4px;background:white;}QPushButton:hover{background:#e74c3c;color:white;}")
        btn_accept.clicked.connect(self._on_accept)
        btn_reject.clicked.connect(self._on_reject)
        btn_all_acc.clicked.connect(self._on_accept_all)
        btn_all_rej.clicked.connect(self._on_reject_all)
        btn_row.addWidget(btn_accept); btn_row.addWidget(btn_reject); btn_row.addStretch()
        btn_row.addWidget(btn_all_acc); btn_row.addWidget(btn_all_rej)
        layout.addLayout(btn_row)
        self._show_current()

    def _show_current(self):
        if self._file_index >= len(self.diff_items):
            self._finish(); return
        item = self.diff_items[self._file_index]
        hunks = item.get("hunks", [])
        if not self._hunk_decisions or self._hunk_index == 0:
            self._hunk_decisions = [None] * len(hunks)
        self.progress_label.setText(f'<b>文件 {self._file_index+1}/{len(self.diff_items)}</b> — {"无差异" if not hunks else f"差异块 {self._hunk_index+1}/{len(hunks)}"}')
        self.file_label.setText(f'<span style="color:#636e72;">{item["path"]}</span>')
        if not hunks:
            self._hunk_decisions = []; self._apply_and_next(); return
        hunk = hunks[self._hunk_index]
        html = []
        for line in hunk["lines"]:
            escaped = line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            if line.startswith("+"): html.append(f'<span style="color:#27ae60;">{escaped}</span>')
            elif line.startswith("-"): html.append(f'<span style="color:#e74c3c;">{escaped}</span>')
            elif line.startswith("@@"): html.append(f'<span style="color:#0984e3;font-weight:bold;">@@ 区域: {hunk["section"]} @@</span>')
            else: html.append(escaped)
        self.diff_view.setHtml("<br>".join(html))

    def _on_accept(self): self._hunk_decisions[self._hunk_index] = True; self._hunk_index += 1; self._advance_or_next()
    def _on_reject(self): self._hunk_decisions[self._hunk_index] = False; self._hunk_index += 1; self._advance_or_next()
    def _on_accept_all(self):
        for i in range(len(self.diff_items[self._file_index].get("hunks",[]))): self._hunk_decisions[i] = True
        self._apply_and_next()
    def _on_reject_all(self):
        for i in range(len(self.diff_items[self._file_index].get("hunks",[]))): self._hunk_decisions[i] = False
        self._apply_and_next()
    def _advance_or_next(self):
        if self._hunk_index >= len(self.diff_items[self._file_index].get("hunks",[])): self._apply_and_next()
        else: self._show_current()
    def _apply_and_next(self):
        item = self.diff_items[self._file_index]
        hunks = item.get("hunks",[])
        if not hunks:
            merged = item["old_content"]
        else:
            old_lines = item["old_content"].splitlines(True)
            for i in reversed(range(len(hunks))):
                if self._hunk_decisions[i]:
                    h = hunks[i]; start = h["old_start"] - 1
                    end = min(start + len(h["old_lines"]), len(old_lines))
                    old_lines[start:end] = h["new_lines"]
            merged = "".join(old_lines)
        self._file_merged[item["path"]] = merged
        self._file_index += 1; self._hunk_index = 0; self._hunk_decisions = []
        self._show_current()
    def _finish(self):
        for item in self.diff_items:
            self.results.append({"path": item["path"], "merged_content": self._file_merged.get(item["path"], item["old_content"])})
        self.accept()

def _format_size(sz):
    sz = float(sz)
    for unit in ["B","KB","MB","GB"]:
        if sz < 1024:
            return f"{sz:.0f}{unit}" if sz == int(sz) else f"{sz:.1f}{unit}"
        sz /= 1024
    return f"{sz:.1f}TB"

def _shell_quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"

def _remote_tcpdump_match_cmd(remote_path):
    qpath = _shell_quote(f" -w {remote_path}")
    return (
        "for p in $(pgrep -x tcpdump 2>/dev/null); do "
        'ps -o pid=,args= -p "$p"; '
        f"done | grep -F -- {qpath} || true"
    )

def _remote_tcpdump_kill_cmd(remote_path):
    qpath = _shell_quote(f" -w {remote_path}")
    return (
        "for p in $(pgrep -x tcpdump 2>/dev/null); do "
        'line=$(ps -o args= -p "$p"); '
        f"case \"$line\" in *{qpath}*) kill \"$p\" 2>/dev/null || true;; esac; "
        "done"
    )

# ═══════════════════════════════════════════════
#  IMSTool - Combined Tool
# ═══════════════════════════════════════════════

class IMSTool(QWidget):
    def __init__(self, lang="zh"):
        super().__init__()
        self.lang = lang
        self._hosts = _load_hosts()
        self._capturing = False
        self._upgrading = False
        self._log_view_active = False
        self._timer_workers = []
        self._manual_workers = []
        self._stop_workers = []
        self._cleanup_workers = []
        self._up_worker = None
        self._ne_service_worker = None
        self._log_worker = None
        self._log_browse_worker = None
        self._log_tail_worker = None
        self._log_dl_worker = None
        self._log_download_active = False
        self._active_remote_paths = []
        self._init_ui()

    # ── UI Init ──

    def _btn_primary(self, text, color=None):
        c = color or _T['primary']
        h = _T['primary_hover'] if c == _T['primary'] else c
        return f"QPushButton{{background:{c};color:white;border:none;border-radius:{_T['btn_radius']};padding:7px 20px;font-size:{_T['font_lg']};font-weight:600;}}QPushButton:hover{{background:{h};}}QPushButton:disabled{{background:{_T['border']};color:{_T['text_hint']};}}"

    def _btn_secondary(self):
        return f"QPushButton{{background:{_T['surface']};color:{_T['text']};border:1px solid {_T['border']};border-radius:{_T['btn_radius']};padding:6px 14px;font-size:{_T['font_md']};}}QPushButton:hover{{background:{_T['surface_alt']};}}QPushButton:disabled{{background:{_T['surface']};color:{_T['text_hint']};}}"

    def _btn_danger(self):
        return f"QPushButton{{background:{_T['danger']};color:white;border:none;border-radius:{_T['btn_radius']};padding:6px 14px;font-size:{_T['font_md']};font-weight:600;}}QPushButton:hover{{background:{_T['danger_hover']};}}QPushButton:disabled{{background:#ffcdd2;color:white;}}"

    def _btn_success(self):
        return f"QPushButton{{background:{_T['success']};color:white;border:none;border-radius:{_T['btn_radius']};padding:6px 14px;font-size:{_T['font_md']};font-weight:600;}}QPushButton:hover{{background:{_T['success_hover']};}}QPushButton:disabled{{background:#b2dfdb;color:white;}}"

    def _btn_small(self, color=None):
        c = color or _T['surface_alt']
        return f"QPushButton{{background:{c};color:{_T['text_secondary']};border:1px solid {_T['border']};border-radius:4px;padding:4px 10px;font-size:{_T['font_sm']};}}QPushButton:hover{{background:{_T['border']};}}"

    def _init_ui(self):
        title = "IMS Tools" if self.lang == "en" else "IMS 工具"
        self.setWindowTitle(title)
        self.resize(1400, 900)
        self.setStyleSheet(STYLE_XIAOMI)

        # ── Pre-init host data (needed by tab init) ──
        self._host_rows = []
        self._host_container = QVBoxLayout()
        self._host_container.setSpacing(6)
        self._host_container.setContentsMargins(0, 0, 0, 0)

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Title Bar ──
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet(f"background:{_T['surface']};border-bottom:1px solid {_T['border']};")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(12, 0, 16, 0)
        tb_layout.setSpacing(0)

        title = QLabel("IMS 工具")
        title.setStyleSheet(f"font-size:{_T['font_title']};font-weight:bold;color:{_T['text']};")
        tb_layout.addWidget(title)
        tb_layout.addStretch()
        layout.addWidget(title_bar)

        # ── Content Area ──
        content = QWidget()
        content.setStyleSheet(f"background:{_T['bg']};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 8, 10, 0)
        content_layout.setSpacing(6)

        # ── Shared Host Bar ──
        self._add_host_row()

        host_btn_row = QHBoxLayout()
        host_btn_row.setContentsMargins(0, 0, 0, 0)
        self._add_host_btn = QPushButton("+ Add Host")
        self._add_host_btn.setFixedHeight(28)
        self._add_host_btn.setStyleSheet(
            f"QPushButton{{background:{_T['success']};color:white;border:none;border-radius:4px;"
            f"font-size:{_T['font_sm']};padding:4px 12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{_T['success_hover']};}}"
        )
        self._add_host_btn.clicked.connect(lambda: self._add_host_row())
        host_btn_row.addWidget(self._add_host_btn)
        host_btn_row.addStretch()
        self._host_container.addLayout(host_btn_row)
        content_layout.addLayout(self._host_container)

        # ── Main body: left=Log, right=Capture+Upgrade ──
        body_splitter = QSplitter(Qt.Horizontal)
        body_splitter.setStyleSheet(f"QSplitter{{background:transparent;}} QSplitter::handle{{background:{_T['border']};width:2px;}}")
        body_splitter.setHandleWidth(3)

        # Left panel: 日志 (Log)
        log_card = self._init_log_tab()
        log_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        body_splitter.addWidget(log_card)

        # Right panel: 抓包 + 升级 stacked vertically
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setStyleSheet(f"QSplitter{{background:transparent;}} QSplitter::handle{{background:{_T['border']};height:2px;}}")
        right_splitter.setHandleWidth(3)

        capture_card = self._init_capture_tab()
        capture_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        right_splitter.addWidget(capture_card)
        upgrade_card = self._init_upgrade_tab()
        upgrade_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        right_splitter.addWidget(upgrade_card)
        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 1)

        right_layout.addWidget(right_splitter)
        body_splitter.addWidget(right_panel)

        body_splitter.setStretchFactor(0, 3)
        body_splitter.setStretchFactor(1, 2)

        content_layout.addWidget(body_splitter, 0)

        # ── Log Console (bottom, fixed) ──
        bottom_panel = QWidget()
        bottom_panel.setFixedHeight(160)
        bl = QVBoxLayout(bottom_panel)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(4)
        bl.addWidget(self.progress_bar)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 10))
        self.log_box.setStyleSheet(
            f"QTextEdit{{background:{_T['surface']};border:1px solid {_T['border']};"
            f"border-radius:{_T['card_radius']};padding:8px;font-size:{_T['font_sm']};}}"
        )
        bl.addWidget(self.log_box)

        content_layout.addWidget(bottom_panel, 0)
        layout.addWidget(content, 1)

        # Initial host trigger
        if self._hosts and self._host_rows:
            QTimer.singleShot(100, lambda: self._host_rows[0]['cb'].setCurrentIndex(0))

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {msg}")

    def closeEvent(self, event):
        self._log_stop_tail()
        if self._up_worker and self._up_worker.isRunning():
            self._up_worker.stop()
        if self._ne_service_worker and self._ne_service_worker.isRunning():
            self._ne_service_worker.stop()
        self._emergency_cleanup()
        event.accept()

    def _emergency_cleanup(self):
        for w in getattr(self, '_timer_workers', []) or []:
            if isinstance(w, SBCMCaptureWorker): w.request_stop()
            elif w.isRunning(): w.terminate()
        for w in getattr(self, '_manual_workers', []) or []:
            if isinstance(w, SBCMCaptureWorker): w.request_stop()
            elif hasattr(w, 'request_stop'): w.request_stop()
            elif w.isRunning(): w.terminate()
        for w in getattr(self, '_stop_workers', []) or []:
            if w.isRunning(): w.terminate()
        for r in getattr(self, '_host_rows', []) or []:
            w = r.get('_iface_worker')
            if w and w.isRunning():
                w.terminate()
        if self._active_remote_paths:
            by_host = {}
            for key, rpath in self._active_remote_paths:
                by_host.setdefault(key, []).append(rpath)
            for (host, port, user, pwd), paths in by_host.items():
                names = [p.split("/")[-1] for p in paths]
                w = KillWorker(host, port, user, pwd, names)
                self._cleanup_workers.append(w)
                w.finished.connect(lambda worker=w: self._cleanup_workers.remove(worker) if worker in self._cleanup_workers else None)
                w.start()

    # ═══════════════════════════════════════════════
    #  Host Management
    # ═══════════════════════════════════════════════

    def _add_host_row(self, prefill_host_idx=None):
        idx = len(self._host_rows)
        row = {}
        frame = QFrame()
        frame.setStyleSheet("QFrame{background:white;border:1px solid #dfe6e9;border-radius:6px;padding:6px 12px;}")
        main_layout = QVBoxLayout(frame)
        main_layout.setContentsMargins(8, 4, 8, 4)
        host_bar = QHBoxLayout()
        host_bar.setSpacing(8)

        first = QWidget()
        first.setFixedSize(72, 28)
        fl = QHBoxLayout(first); fl.setContentsMargins(2,0,2,0)
        if idx == 0:
            lbl = QLabel("Host:"); lbl.setStyleSheet("font-size:12px;color:#1a1a1a;"); fl.addWidget(lbl)
        else:
            rm = QPushButton("✕"); rm.setFixedSize(24,24)
            rm.setStyleSheet("QPushButton{background:#e74c3c;color:white;border:none;border-radius:12px;font-size:12px;font-weight:bold;}QPushButton:hover{background:#c0392b;}")
            rm.clicked.connect(lambda: self._remove_host_row(frame))
            fl.addWidget(rm)
        host_bar.addWidget(first)

        cb = QComboBox()
        cb.setMinimumWidth(350)
        cb.setStyleSheet("QComboBox{border:1px solid #dfe6e9;border-radius:4px;padding:6px 8px;font-size:13px;background:#f8f9fa;}QComboBox:focus{border:1px solid #0984e3;background:white;}QComboBox QAbstractItemView{background:white;color:#1a1a1a;selection-background-color:#f5f5f5;selection-color:#1a1a1a;}QComboBox QAbstractItemView QScrollBar:vertical{background:transparent;width:6px;margin:2px 0;}QComboBox QAbstractItemView QScrollBar::handle:vertical{background:#c0c0c0;border-radius:3px;min-height:20px;}QComboBox QAbstractItemView QScrollBar::handle:vertical:hover{background:#a0a0a0;}QComboBox QAbstractItemView QScrollBar::add-line:vertical,QComboBox QAbstractItemView QScrollBar::sub-line:vertical{height:0;}")
        cb.setEditable(True)
        cb.setPlaceholderText("Select or type user@host:port")
        cb.setInsertPolicy(QComboBox.NoInsert)
        for h in self._hosts:
            display = f"{h.get('desc', h.get('name',''))} — {h['host']}:{h.get('port',22)} ({h['user']})"
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
        connect_btn.clicked.connect(lambda: self._test_connection(row))
        host_bar.addWidget(connect_btn)
        row['connect_btn'] = connect_btn

        host_bar.addStretch()
        conn_status = QLabel("● Disconnected")
        conn_status.setStyleSheet("color:#e74c3c;font-weight:bold;font-size:13px;")
        host_bar.addWidget(conn_status)
        row['conn_status'] = conn_status

        main_layout.addLayout(host_bar)

        # ── Per-host filter section (only visible on 抓包 tab) ──
        row['filters'] = []
        filter_section = QWidget()
        fs_layout = QVBoxLayout(filter_section)
        fs_layout.setContentsMargins(0, 0, 0, 0)
        fs_layout.setSpacing(4)
        row['_interfaces'] = []
        filter_container = QVBoxLayout()
        filter_container.setSpacing(4)
        row['filter_container'] = filter_container
        fs_layout.addLayout(filter_container)
        self._add_filter_row(row)

        add_f_btn = QPushButton("+ Add Filter")
        add_f_btn.setStyleSheet("QPushButton{background:#f0f3f5;color:#636e72;border:1px solid #dfe6e9;border-radius:4px;padding:3px 10px;font-size:11px;}QPushButton:hover{background:#e8e8e8;}")
        add_f_btn.clicked.connect(lambda: self._add_filter_row(row))
        fs_layout.addWidget(add_f_btn)

        row['filter_section'] = filter_section
        main_layout.addWidget(filter_section)

        row['frame'] = frame
        row['_conn_worker'] = None
        row['_iface_worker'] = None
        self._host_rows.append(row)
        host_layout = self._host_container
        host_layout.insertWidget(host_layout.count() - 1, frame)
        if prefill_host_idx is not None and 0 <= prefill_host_idx < len(self._hosts):
            cb.setCurrentIndex(prefill_host_idx)
        self._cap_update_preview()
        self._update_upgrade_button_state()
        return row

    def _remove_host_row(self, frame):
        for i, r in enumerate(self._host_rows):
            if r['frame'] is frame:
                self._host_rows.pop(i)
                frame.setVisible(False)
                self._host_container.removeWidget(frame)
                frame.deleteLater()
                break
        if not self._host_rows:
            self._add_host_row()
        self._cap_update_preview()
        self._update_upgrade_button_state()

    def _on_host_selected(self, frame):
        for r in self._host_rows:
            if r['frame'] is frame:
                self._set_conn_status(r, False)
                self._reset_interface_combo(r, "any")
                self._test_connection(r)
                break
        self._cap_update_preview()
        self._update_upgrade_button_state()

    def _test_connection(self, row):
        idx = row['cb'].currentIndex()
        if idx < 0 or idx >= len(self._hosts): return
        h = self._hosts[idx]
        row['connect_btn'].setEnabled(False)
        row['connect_btn'].setText("Connecting...")
        row['conn_status'].setText("● Testing...")
        row['conn_status'].setStyleSheet("color:#fdd835;font-weight:bold;font-size:13px;")
        w = ConnectWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""))
        row['_conn_worker'] = w
        w.result.connect(lambda ok, msg, r=row: self._on_conn_result(r, ok, msg))
        w.finished.connect(lambda r=row: self._on_conn_finished(r))
        w.start()

    def _on_conn_result(self, row, ok, msg):
        self._set_conn_status(row, ok)
        if ok:
            self._scan_interfaces(row)

    def _reset_interface_combo(self, row, current="any"):
        row['_interfaces'] = []
        for fw in row.get('filters', []):
            self._populate_interface_combo(fw.get('iface'), [], current)

    def _scan_interfaces(self, row):
        idx = row['cb'].currentIndex()
        if idx < 0 or idx >= len(self._hosts):
            return
        h = self._hosts[idx]
        for fw in row.get('filters', []):
            self._populate_interface_combo(fw.get('iface'), [], "any", scanning=True)
        w = InterfaceScanWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""))
        row['_iface_worker'] = w
        w.result.connect(lambda interfaces, msg, r=row: self._on_interface_scan_result(r, interfaces, msg))
        w.finished.connect(lambda r=row: self._on_interface_scan_finished(r))
        w.start()

    def _on_interface_scan_result(self, row, interfaces, msg):
        row['_interfaces'] = interfaces
        for fw in row.get('filters', []):
            cb = fw.get('iface')
            previous = cb.currentData() if cb else "any"
            self._populate_interface_combo(cb, interfaces, previous or "any")
        if interfaces:
            self._log(f"[iface] found {len(interfaces)} interfaces on {row['cb'].currentText()}")
        elif msg:
            self._log(f"[iface] scan failed: {msg}")
        self._cap_update_preview()

    def _populate_interface_combo(self, cb, interfaces, current="any", scanning=False):
        if not cb:
            return
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("any (scanning...)" if scanning else "any", "any")
        seen = set()
        for item in interfaces:
            name = item.get("name", "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            cb.addItem(name, name)
        target = cb.findData(current)
        cb.setCurrentIndex(target if target >= 0 else 0)
        cb.blockSignals(False)

    def _on_interface_scan_finished(self, row):
        row['_iface_worker'] = None

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
        dlg.resize(520, 520)
        dlg.setStyleSheet("""
            QDialog { background:#f5f5f5; }
            QTreeWidget { background:white; border:1px solid #e0e0e0; border-radius:8px; padding:4px; }
            QTreeWidget::item { padding:5px 8px; border-radius:4px; }
            QTreeWidget::item:selected { background:#f5f5f5; color:#1a1a1a; }
            QTreeWidget::branch { background:transparent; }
            QScrollBar:vertical { background:#f0f0f0; width:8px; border-radius:4px; }
            QScrollBar::handle:vertical { background:#c0c0c0; border-radius:4px; min-height:24px; }
            QScrollBar::handle:vertical:hover { background:#a0a0a0; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:none; }
            QLineEdit { background:white; border:1px solid #e0e0e0; border-radius:6px; padding:6px 10px; font-size:13px; }
            QLineEdit:focus { border-color:#0984e3; }
            QLabel { font-size:12px; color:#333; }
        """)
        layout = QVBoxLayout(dlg)
        search_box = QLineEdit()
        search_box.setPlaceholderText("🔍 Search by name or IP...")
        search_box.setClearButtonEnabled(True)
        layout.addWidget(search_box)
        layout.addWidget(QLabel("Saved Hosts:"))
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setIndentation(20)
        tree.setAnimated(True)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(tree, 1)
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

        def get_prefix(h):
            ip = h.get("host", "")
            parts = ip.strip().split(".")
            if len(parts) >= 3:
                return ".".join(parts[:3]) + ".x"
            return ip or "Other"

        def host_text(h):
            return f"{h.get('desc', h.get('name',''))} — {h['host']}:{h.get('port',22)} ({h['user']})"

        def rebuild_tree():
            search_box.clear()
            tree.clear()
            groups = {}
            for i, h in enumerate(self._hosts):
                prefix = get_prefix(h)
                groups.setdefault(prefix, []).append((i, h))
            for prefix in sorted(groups.keys()):
                group_item = QTreeWidgetItem([prefix])
                group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
                f = group_item.font(0); f.setBold(True); group_item.setFont(0, f)
                group_item.setForeground(0, Qt.gray)
                for idx, h in groups[prefix]:
                    child = QTreeWidgetItem([host_text(h)])
                    child.setData(0, Qt.UserRole, idx)
                    group_item.addChild(child)
                tree.addTopLevelItem(group_item)
                group_item.setExpanded(True)

        def on_select():
            item = tree.currentItem()
            if not item or not item.parent():
                ip_edit.clear(); port_edit.setText("22"); user_edit.setText("root")
                pwd_edit.clear(); desc_edit.clear()
                return
            idx = item.data(0, Qt.UserRole)
            if idx is not None and 0 <= idx < len(self._hosts):
                h = self._hosts[idx]
                ip_edit.setText(h["host"]); port_edit.setText(str(h.get("port",22)))
                user_edit.setText(h["user"]); pwd_edit.setText(h.get("pwd",""))
                desc_edit.setText(h.get("desc",""))

        tree.currentItemChanged.connect(on_select)
        rebuild_tree()

        def filter_tree(text):
            for i in range(tree.topLevelItemCount()):
                gp = tree.topLevelItem(i)
                visible = False
                if text:
                    for j in range(gp.childCount()):
                        ch = gp.child(j)
                        match = text.lower() in ch.text(0).lower()
                        ch.setHidden(not match)
                        if match: visible = True
                    gp.setHidden(not visible)
                else:
                    gp.setHidden(False)
                    for j in range(gp.childCount()):
                        gp.child(j).setHidden(False)
        search_box.textChanged.connect(filter_tree)

        def on_add():
            if not ip_edit.text().strip(): return
            self._hosts.append(dict(host=ip_edit.text().strip(), port=int(port_edit.text().strip() or "22"),
                user=user_edit.text().strip() or "root", pwd=pwd_edit.text(),
                name=desc_edit.text().strip() or ip_edit.text().strip(), desc=desc_edit.text().strip()))
            _save_hosts(self._hosts); rebuild_tree(); self._reload_hosts()
            ip_edit.clear(); pwd_edit.clear(); desc_edit.clear(); port_edit.setText("22"); user_edit.setText("root")
        add_btn.clicked.connect(on_add)

        def on_update():
            item = tree.currentItem()
            if not item or not item.parent() or not ip_edit.text().strip(): return
            idx = item.data(0, Qt.UserRole)
            if idx is None or idx >= len(self._hosts): return
            self._hosts[idx] = dict(host=ip_edit.text().strip(), port=int(port_edit.text().strip() or "22"),
                user=user_edit.text().strip() or "root", pwd=pwd_edit.text(),
                name=desc_edit.text().strip() or ip_edit.text().strip(), desc=desc_edit.text().strip())
            _save_hosts(self._hosts); rebuild_tree(); self._reload_hosts()
        update_btn.clicked.connect(on_update)

        def on_del():
            item = tree.currentItem()
            if not item or not item.parent(): return
            idx = item.data(0, Qt.UserRole)
            if idx is None or idx >= len(self._hosts): return
            if QMessageBox.question(dlg, "Confirm", f"Delete {self._hosts[idx]['host']}?") == QMessageBox.Yes:
                self._hosts.pop(idx); _save_hosts(self._hosts); rebuild_tree(); self._reload_hosts()
        del_btn.clicked.connect(on_del)

        def on_dlg_close():
            new_order = []
            for i in range(tree.topLevelItemCount()):
                gp = tree.topLevelItem(i)
                for j in range(gp.childCount()):
                    idx = gp.child(j).data(0, Qt.UserRole)
                    if idx is not None and idx < len(self._hosts):
                        new_order.append(self._hosts[idx])
            if new_order:
                self._hosts[:] = new_order
                _save_hosts(self._hosts)
            if on_close: on_close()

        dlg.finished.connect(on_dlg_close)
        dlg.exec()

    def _reload_hosts(self):
        for r in self._host_rows:
            cb = r['cb']
            cb.blockSignals(True)
            current = cb.currentData()
            cb.clear()
            for h in self._hosts:
                display = f"{h.get('desc', h.get('name',''))} — {h['host']}:{h.get('port',22)} ({h['user']})"
                cb.addItem(display, h)
            if current:
                for i in range(cb.count()):
                    if cb.itemData(i) == current:
                        cb.setCurrentIndex(i); break
            cb.blockSignals(False)
        self._update_upgrade_button_state()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            for r in self._host_rows:
                if obj == r['cb'].lineEdit():
                    r['cb'].showPopup(); return True
        if event.type() == QEvent.Type.KeyPress and hasattr(self, "log_table"):
            if obj in (self.log_table, self.log_table.viewport()) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._log_activate_current_row()
                return True
        return super().eventFilter(obj, event)

    def _selected_hosts(self):
        result = []
        for r in self._host_rows:
            idx = r['cb'].currentIndex()
            if 0 <= idx < len(self._hosts):
                result.append(self._hosts[idx])
        return result

    def _first_selected_host(self):
        hosts = self._selected_hosts()
        return hosts[0] if hosts else None

    def _forget_remote_capture(self, worker):
        if not worker:
            return
        remote_path = getattr(worker, "remote_path", None)
        if not remote_path:
            return
        key = (worker.host, worker.port, worker.user, worker.pwd)
        for item in list(self._active_remote_paths):
            item_key, item_path = item
            same_host = item_key[0] == key[0] and str(item_key[1]) == str(key[1])
            same_auth = item_key[2:] == key[2:]
            if same_host and same_auth and item_path == remote_path:
                self._active_remote_paths.remove(item)
                break

    # ═══════════════════════════════════════════════
    #  Tab 1: 抓包 (Packet Capture)
    # ═══════════════════════════════════════════════

    def _init_capture_tab(self):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{_T['surface']};border:1px solid {_T['border']};"
            f"border-radius:{_T['card_radius']};}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Section header
        header = QLabel("Packet Capture" if self.lang == "en" else "抓包 Capture")
        header.setStyleSheet(f"font-size:{_T['font_lg']};font-weight:bold;color:{_T['text']};padding-bottom:2px;")
        layout.addWidget(header)

        # Mode bar
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(6)
        self.cap_mode_cb = QComboBox()
        self.cap_mode_cb.addItems(["Manual", "Timed"])
        self.cap_mode_cb.setFixedWidth(90)
        self.cap_mode_cb.setStyleSheet(
            f"QComboBox{{border:1px solid {_T['border']};border-radius:4px;padding:3px 6px;"
            f"font-size:{_T['font_md']};background:{_T['surface_alt']};}}"
        )
        self.cap_mode_cb.currentIndexChanged.connect(self._on_cap_mode_changed)
        mode_bar.addWidget(self.cap_mode_cb)

        self.cap_dur_label = QLabel("Duration")
        self.cap_dur_label.setStyleSheet(f"font-size:{_T['font_md']};color:{_T['text_secondary']};")
        mode_bar.addWidget(self.cap_dur_label)
        self.cap_duration = QLineEdit("30")
        self.cap_duration.setFixedWidth(45)
        self.cap_duration.setAlignment(Qt.AlignCenter)
        self.cap_duration.setStyleSheet(
            f"QLineEdit{{border:1px solid {_T['border']};border-radius:4px;padding:3px 4px;font-size:{_T['font_md']};}}"
        )
        mode_bar.addWidget(self.cap_duration)
        self.cap_dur_unit = QComboBox()
        self.cap_dur_unit.addItems(["sec", "min"])
        self.cap_dur_unit.setFixedWidth(60)
        self.cap_dur_unit.setStyleSheet(
            f"QComboBox{{border:1px solid {_T['border']};border-radius:4px;padding:3px 4px;"
            f"font-size:{_T['font_md']};background:{_T['surface_alt']};}}"
        )
        mode_bar.addWidget(self.cap_dur_unit)
        mode_bar.addStretch()

        self.cap_start_btn = QPushButton("Start")
        self.cap_start_btn.setStyleSheet(
            f"QPushButton{{background:{_T['success']};color:white;border:none;border-radius:{_T['btn_radius']};"
            f"padding:5px 18px;font-size:{_T['font_md']};font-weight:600;}}"
            f"QPushButton:hover{{background:{_T['success_hover']};}}"
            f"QPushButton:disabled{{background:#a5d6a7;color:white;}}"
        )
        self.cap_start_btn.clicked.connect(self._do_cap_start)
        mode_bar.addWidget(self.cap_start_btn)
        self.cap_stop_btn = QPushButton("Stop")
        self.cap_stop_btn.setStyleSheet(
            f"QPushButton{{background:{_T['danger']};color:white;border:none;border-radius:{_T['btn_radius']};"
            f"padding:5px 18px;font-size:{_T['font_md']};font-weight:600;}}"
            f"QPushButton:hover{{background:{_T['danger_hover']};}}"
            f"QPushButton:disabled{{background:#ffcdd2;color:white;}}"
        )
        self.cap_stop_btn.clicked.connect(self._do_cap_manual_stop)
        self.cap_stop_btn.setEnabled(False)
        mode_bar.addWidget(self.cap_stop_btn)

        layout.addLayout(mode_bar)

        # Save path
        path_row = QHBoxLayout()
        self.cap_save_path = QLineEdit()
        self.cap_save_path.setPlaceholderText("Save Path")
        self.cap_save_path.setText(os.path.join(os.path.expanduser("~"), "Desktop"))
        path_row.addWidget(self.cap_save_path)
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet(self._btn_secondary())
        browse_btn.clicked.connect(lambda: self.cap_save_path.setText(QFileDialog.getExistingDirectory(self, "Select Save Directory") or self.cap_save_path.text()))
        path_row.addWidget(browse_btn)
        self.cap_compress_cb = QCheckBox("Compress")
        path_row.addWidget(self.cap_compress_cb)
        layout.addLayout(path_row)

        # Command preview
        self.cap_preview = QTextEdit()
        self.cap_preview.setReadOnly(True)
        self.cap_preview.setFixedHeight(120)
        self.cap_preview.setStyleSheet(
            f"QTextEdit{{background:{_T['surface_alt']};border:1px solid {_T['border']};"
            f"border-radius:{_T['card_radius']};padding:8px 12px;font-family:Consolas,monospace;"
            f"font-size:{_T['font_sm']};color:{_T['text']};}}"
        )
        layout.addWidget(self.cap_preview)

        self._on_cap_mode_changed(self.cap_mode_cb.currentIndex())
        self._cap_update_preview()
        return card

    def _on_cap_mode_changed(self, idx):
        if idx == 0:
            self.cap_dur_label.setVisible(False); self.cap_duration.setVisible(False); self.cap_dur_unit.setVisible(False)
            self.cap_start_btn.setText("Start")
        else:
            self.cap_dur_label.setVisible(True); self.cap_duration.setVisible(True); self.cap_dur_unit.setVisible(True)
            self.cap_start_btn.setText("Start & Download")

    def _cap_update_preview(self):
        if not hasattr(self, 'cap_preview'):
            return
        lines = []
        for r in self._host_rows:
            idx = r['cb'].currentIndex()
            if idx < 0 or idx >= len(self._hosts):
                continue
            h = self._hosts[idx]
            host_name = h.get('name', h['host'])
            filters = self._get_host_filters(r)
            if not filters:
                lines.append(f"  {host_name}: no filters")
                continue
            for f in filters:
                if f['proto'] == 'SBCM':
                    lines.append(f"  {host_name}: SBCM capture")
                else:
                    expr = self._build_filter_expr(f)
                    lines.append(f"  {host_name}: tcpdump -i {f['iface']} -w /opt/tar/... {expr}")
        if not lines:
            self.cap_preview.setPlainText("No captures configured")
        else:
            self.cap_preview.setPlainText("Captures:\n" + "\n".join(lines))

    def _add_filter_row(self, row, data=None):
        fw = {}
        frame = QFrame()
        frame.setStyleSheet("QFrame{background:#f8f9fa;border:1px solid #e8e8e8;border-radius:4px;padding:4px 8px;}")
        rl = QHBoxLayout(frame); rl.setContentsMargins(4,2,4,2); rl.setSpacing(4)

        fi = len(row['filters'])
        if fi > 0:
            rm_container = QWidget()
            rm_container.setFixedSize(28, 22)
            rml = QHBoxLayout(rm_container); rml.setContentsMargins(0,0,0,0)
            rm_btn = QPushButton("✕")
            rm_btn.setFixedSize(18,18)
            rm_btn.setStyleSheet("QPushButton{background:#e74c3c;color:white;border:none;border-radius:9px;font-size:9px;font-weight:bold;}QPushButton:hover{background:#c0392b;}")
            rm_btn.clicked.connect(lambda: self._remove_filter_row(row, frame))
            rml.addWidget(rm_btn)
            rl.addWidget(rm_container)
        else:
            spacer = QWidget()
            spacer.setFixedSize(28, 22)
            rl.addWidget(spacer)

        rl.addWidget(QLabel(f"F{fi+1}:"))
        iface = QComboBox()
        iface.setFixedWidth(90)
        self._populate_interface_combo(iface, row.get('_interfaces', []), data.get('iface', 'any') if data else 'any')
        fw['iface'] = iface; rl.addWidget(iface)

        proto = QComboBox()
        proto.addItems(["any", "tcp", "udp", "icmp", "arp", "SBCM"])
        proto.setFixedWidth(90)
        if data:
            idx = proto.findText(data['proto'])
            if idx >= 0: proto.setCurrentIndex(idx)
        fw['proto'] = proto; rl.addWidget(proto)

        src_ip = QLineEdit(); src_ip.setPlaceholderText("Src IP"); src_ip.setFixedWidth(120); fw['src_ip'] = src_ip; rl.addWidget(src_ip)
        rl.addWidget(QLabel("→"))
        dst_ip = QLineEdit(); dst_ip.setPlaceholderText("Dst IP"); dst_ip.setFixedWidth(120); fw['dst_ip'] = dst_ip; rl.addWidget(dst_ip)
        src_port = QLineEdit(); src_port.setPlaceholderText("Sport"); src_port.setFixedWidth(65); fw['src_port'] = src_port; rl.addWidget(src_port)
        rl.addWidget(QLabel("→"))
        dst_port = QLineEdit(); dst_port.setPlaceholderText("Dport"); dst_port.setFixedWidth(65); fw['dst_port'] = dst_port; rl.addWidget(dst_port)
        dir_cb = QCheckBox("Dir"); fw['directional'] = dir_cb; rl.addWidget(dir_cb)

        def on_proto(t):
            is_s = t == "SBCM"
            iface.setDisabled(is_s)
            src_ip.setDisabled(is_s); dst_ip.setDisabled(is_s)
            src_port.setDisabled(is_s); dst_port.setDisabled(is_s); dir_cb.setDisabled(is_s)
        proto.currentTextChanged.connect(on_proto)
        on_proto(proto.currentText())

        rl.addStretch()
        fw['frame'] = frame
        row['filters'].append(fw)
        row['filter_container'].addWidget(frame)
        for w in (iface, proto, src_ip, dst_ip, src_port, dst_port, dir_cb):
            if hasattr(w, 'textChanged'): w.textChanged.connect(self._cap_update_preview)
            elif hasattr(w, 'currentTextChanged'): w.currentTextChanged.connect(self._cap_update_preview)
            elif hasattr(w, 'toggled'): w.toggled.connect(self._cap_update_preview)
        self._cap_update_preview()
        return fw

    def _remove_filter_row(self, row, frame):
        for i, fw in enumerate(row['filters']):
            if fw['frame'] is frame:
                row['filters'].pop(i)
                frame.setParent(None); frame.deleteLater()
                break
        for i, fw in enumerate(row['filters']):
            lbl = fw['frame'].layout().itemAt(1).widget()
            if lbl: lbl.setText(f"F{i+1}:")
        self._cap_update_preview()

    def _get_host_filters(self, row):
        result = []
        for fw in row['filters']:
            result.append({
                'proto': fw['proto'].currentText(),
                'iface': fw['iface'].currentData() or "any",
                'src_ip': fw['src_ip'].text().strip(),
                'dst_ip': fw['dst_ip'].text().strip(),
                'src_port': fw['src_port'].text().strip(),
                'dst_port': fw['dst_port'].text().strip(),
                'directional': fw['directional'].isChecked(),
            })
        return result

    def _build_filter_expr(self, f):
        if f['proto'] == "SBCM": return "SBCM"
        parts = []
        if f['proto'] != "any": parts.append(f['proto'])
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

    def _do_cap_start(self):
        if self.cap_mode_cb.currentIndex() == 0:
            self._do_cap_manual_start()
        else:
            self._do_cap_timed_start()

    def _do_cap_timed_start(self):
        tasks = []
        for row in self._host_rows:
            idx = row['cb'].currentIndex()
            if idx < 0 or idx >= len(self._hosts): continue
            h = self._hosts[idx]
            filters = self._get_host_filters(row)
            ts = datetime.now().strftime('%Y%m%d_%H%M')
            is_sbcm = any(f['proto'] == 'SBCM' for f in filters)
            if is_sbcm:
                tasks.append(('sbcm', h, None, f"{h.get('name','capture')}_sbcm_{ts}"))
            else:
                for fi, f in enumerate(filters):
                    expr = self._build_filter_expr(f)
                    tasks.append(('tcpdump', h, expr, f"{h.get('name','capture')}_f{fi+1}_{f['proto']}_{ts}.pcap", f['iface']))
        if not tasks:
            QMessageBox.warning(self, "Warning", "No hosts selected"); return
        save_dir = self.cap_save_path.text().strip()
        if not save_dir:
            QMessageBox.warning(self, "Warning", "Select save directory"); return
        os.makedirs(save_dir, exist_ok=True)
        raw_dur = self.cap_duration.text().strip() or "30"
        try:
            duration_int = int(raw_dur) * 60 if self.cap_dur_unit.currentText() == "min" else int(raw_dur)
        except ValueError:
            QMessageBox.warning(self, "Warning", "Duration must be a positive integer"); return
        if duration_int <= 0:
            QMessageBox.warning(self, "Warning", "Duration must be greater than 0"); return
        duration = str(duration_int)
        if self._timer_workers:
            for w in self._timer_workers:
                if w.isRunning(): w.terminate()
            self._timer_workers = []
        self._capturing = True; self._capture_counts = len(tasks)
        self._capture_done = 0; self._capture_errors = 0; self._capture_results = []
        self._multi_completed = False
        self.cap_mode_cb.setEnabled(False); self.cap_start_btn.setEnabled(False)
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0)
        for ti, task in enumerate(tasks):
            ttype, h, expr, oname = task[:4]
            iface = task[4] if len(task) > 4 else "any"
            lp = os.path.join(save_dir, oname)
            if ttype == 'sbcm':
                self._log(f"[timed] SBCM {h['host']} → {oname}")
                w = SBCMCaptureWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), lp, duration=int(duration))
            else:
                rp = f"/opt/tar/{oname}"
                self._active_remote_paths.append(((h['host'],h.get('port',22),h['user'],h.get('pwd','')), rp))
                cmd = f"tcpdump -i {_shell_quote(iface)} -w {rp} {expr}"
                self._log(f"[timed] {h['host']} → {oname}")
                self._log(f"[command] {cmd}")
                w = CaptureWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), cmd, rp, lp, duration, self.cap_compress_cb.isChecked())
            w.log.connect(self._log)
            w.progress.connect(lambda v, ot=ti: self._on_multi_progress(ot, v))
            w.done.connect(self._on_multi_done)
            w.error.connect(self._on_multi_error)
            w.finished.connect(self._on_multi_finished)
            self._timer_workers.append(w); w.start()

    def _do_cap_manual_start(self):
        tasks = []
        for row in self._host_rows:
            idx = row['cb'].currentIndex()
            if idx < 0 or idx >= len(self._hosts): continue
            h = self._hosts[idx]
            filters = self._get_host_filters(row)
            ts = datetime.now().strftime('%Y%m%d_%H%M')
            is_sbcm = any(f['proto'] == 'SBCM' for f in filters)
            if is_sbcm:
                tasks.append(('sbcm', h, None, f"{h.get('name','capture')}_sbcm_{ts}"))
            else:
                for fi, f in enumerate(filters):
                    expr = self._build_filter_expr(f)
                    tasks.append(('tcpdump', h, expr, f"{h.get('name','capture')}_f{fi+1}_{f['proto']}_{ts}.pcap", f['iface']))
        if not tasks:
            QMessageBox.warning(self, "Warning", "No hosts selected"); return
        save_dir = self.cap_save_path.text().strip()
        if not save_dir:
            QMessageBox.warning(self, "Warning", "Select save directory"); return
        os.makedirs(save_dir, exist_ok=True)
        self._manual_workers = []; self._manual_errors = 0; self._manual_started_count = 0
        self._stop_workers = []; self._stop_done = 0; self._stop_errors = 0; self._stop_results = []
        self._manual_stopping = False; self._stop_completed = False
        self._capturing = True; self.cap_mode_cb.setEnabled(False); self.cap_start_btn.setEnabled(False); self.cap_stop_btn.setEnabled(False)
        for task in tasks:
            ttype, h, expr, oname = task[:4]
            iface = task[4] if len(task) > 4 else "any"
            lp = os.path.join(save_dir, oname)
            if ttype == 'sbcm':
                self._log(f"[manual] SBCM {h['host']} → {oname}")
                w = SBCMCaptureWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), lp, duration=None)
                w.log.connect(self._log); w.done.connect(self._on_manual_stopped); w.error.connect(self._on_manual_error)
                w.control_ready.connect(self._on_manual_control_ready)
            else:
                rp = f"/opt/tar/{oname}"
                self._active_remote_paths.append(((h['host'],h.get('port',22),h['user'],h.get('pwd','')), rp))
                cmd = f"tcpdump -i {_shell_quote(iface)} -w {rp} {expr}"
                self._log(f"[manual] Start {h['host']} → {oname}")
                self._log(f"[command] {cmd}")
                w = CaptureStartWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), cmd, rp)
                w._out_name = oname; w._remote_path = rp; w._local_path = lp; w._hostname = h['host']
                w.log.connect(self._log)
                w.started.connect(self._on_manual_started); w.control_ready.connect(self._on_manual_control_ready)
                w.error.connect(self._on_manual_error); w.finished.connect(lambda: None)
            self._manual_workers.append(w); w.start()

    def _do_cap_manual_stop(self):
        if not self._manual_workers: return
        self.cap_stop_btn.setEnabled(False); self.cap_start_btn.setEnabled(False)
        self._manual_stopping = True
        self._stop_workers = []; self._stop_done = 0; self._stop_errors = 0; self._stop_results = []
        self._stop_completed = False
        for w in self._manual_workers:
            if isinstance(w, SBCMCaptureWorker):
                self._log(f"[manual] Stopping SBCM capture")
                try:
                    w.error.disconnect(self._on_manual_error)
                except (TypeError, RuntimeError):
                    pass
                w.error.connect(self._on_manual_stop_error)
                w.finished.connect(self._on_stop_finished)
                w.request_stop(); self._stop_workers.append(w)
            else:
                h_name = getattr(w, '_hostname', '')
                self._log(f"[manual] Stop & download {h_name}")
                sw = CaptureStopWorker(w.host, w.port, w.user, w.pwd, w._remote_path, w._local_path, self.cap_compress_cb.isChecked())
                sw.log.connect(self._log); sw.done.connect(self._on_manual_stopped)
                sw.error.connect(self._on_manual_stop_error); sw.finished.connect(self._on_stop_finished)
                self._stop_workers.append(sw); sw.start()
                if hasattr(w, 'request_stop'):
                    w.request_stop()
        if not self._stop_workers:
            self._manual_stopping = False
            self._capturing = False
            self.cap_mode_cb.setEnabled(True); self.cap_start_btn.setEnabled(True); self.cap_stop_btn.setEnabled(False)

    def _on_manual_started(self): self._manual_started_count += 1
    def _on_manual_control_ready(self, ready):
        sender = self.sender()
        if sender:
            sender.setProperty("_control_ready", bool(ready))
        if not getattr(self, '_capturing', False) or getattr(self, '_manual_stopping', False):
            return
        any_ready = any(bool(w.property("_control_ready")) for w in getattr(self, '_manual_workers', []) or [])
        self.cap_stop_btn.setEnabled(any_ready)
    def _on_manual_error(self, msg):
        self._manual_errors += 1; self._log(f"[error] {msg}")
        if self._manual_errors >= len(self._manual_workers):
            self._capturing = False; self._manual_stopping = False
            self.cap_mode_cb.setEnabled(True); self.cap_start_btn.setEnabled(True); self.cap_stop_btn.setEnabled(False)
    def _on_manual_stopped(self, lp):
        self._stop_done += 1; self._stop_results.append(lp); self._log(f"[done] {lp}")
    def _on_manual_stop_error(self, msg):
        self._stop_errors += 1; self._log(f"[error] {msg}")
    def _on_stop_finished(self):
        self._forget_remote_capture(self.sender())
        if self._stop_done + self._stop_errors >= len(self._stop_workers) and not getattr(self, '_stop_completed', False):
            self._stop_completed = True
            self._capturing = False; self._manual_stopping = False
            self.cap_mode_cb.setEnabled(True); self.cap_start_btn.setEnabled(True); self.cap_stop_btn.setEnabled(False)
            if self._stop_results: self._show_cap_done(self._stop_results)
            self._manual_workers = []
            self._stop_workers = []
    def _on_multi_progress(self, idx, val):
        count = len(self._timer_workers) or 1
        total = sum((w.property("_prog") or 0) if w != self._timer_workers[idx] else val for i, w in enumerate(self._timer_workers))
        if self._timer_workers: self._timer_workers[idx].setProperty("_prog", val)
        self.progress_bar.setValue(int(total / count))
    def _on_multi_done(self, lp):
        self._capture_done += 1; self._capture_results.append(lp); self._log(f"[done] {lp}")
    def _on_multi_error(self, msg):
        self._capture_errors += 1; self._log(f"[error] {msg}")
    def _on_multi_finished(self):
        self._forget_remote_capture(self.sender())
        if self._capture_done + self._capture_errors >= self._capture_counts and not getattr(self, '_multi_completed', False):
            self._multi_completed = True
            self._capturing = False; self.cap_mode_cb.setEnabled(True); self.cap_start_btn.setEnabled(True); self.progress_bar.setVisible(False)
            if self._capture_results: self._show_cap_done(self._capture_results)
            self._timer_workers = []
    def _show_cap_done(self, paths):
        self.progress_bar.setValue(100)
        self._log(f"[done] All captures complete.")
        save_dir = self.cap_save_path.text().strip()
        if save_dir:
            subprocess.run(['explorer', os.path.normpath(save_dir)], creationflags=subprocess.CREATE_NO_WINDOW)

    # ═══════════════════════════════════════════════
    #  Tab 2: 升级 (IMS NE Upgrade)
    # ═══════════════════════════════════════════════

    def _init_upgrade_tab(self):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{_T['surface']};border:1px solid {_T['border']};"
            f"border-radius:{_T['card_radius']};}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self.ne_configs = self._load_ne_configs()

        # Section header
        header = QLabel("升级 Upgrade")
        header.setStyleSheet(f"font-size:{_T['font_lg']};font-weight:bold;color:{_T['text']};padding-bottom:2px;")
        layout.addWidget(header)

        # NE type config
        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(8)
        cfg_row.addWidget(QLabel("NE Type:"))
        self.up_ne_combo = QComboBox()
        self.up_ne_combo.setMinimumWidth(200)
        for ne_type, nc in self.ne_configs.items():
            self.up_ne_combo.addItem(f"{nc.get('description','?')} ({ne_type})", (ne_type, nc))
        self.up_ne_combo.currentIndexChanged.connect(lambda _: self._update_upgrade_button_state())
        cfg_row.addWidget(self.up_ne_combo)
        cfg_row.addWidget(QLabel("Description:"))
        self.up_desc_input = QLineEdit()
        self.up_desc_input.setPlaceholderText("Optional")
        self.up_desc_input.setMinimumWidth(120)
        cfg_row.addWidget(self.up_desc_input, 1)
        layout.addLayout(cfg_row)

        # Patch file
        patch_row = QHBoxLayout()
        patch_row.setSpacing(6)
        patch_row.addWidget(QLabel("Patch:"))
        self.up_patch_path = QLineEdit()
        self.up_patch_path.setPlaceholderText("Select patch file(s)")
        patch_row.addWidget(self.up_patch_path, 1)
        patch_btn = QPushButton("Browse")
        patch_btn.setStyleSheet(self._btn_secondary())
        def on_browse_patch():
            ne_type, ne_config = self.up_ne_combo.currentData()
            patch_cfg = ne_config.get("patch", {})
            default_dir = patch_cfg.get("default_dir") or ""
            keyword = self._patch_keyword(ne_type, ne_config)
            if patch_cfg.get("multiple"):
                fpaths, _ = QFileDialog.getOpenFileNames(self, "Select Patches", default_dir, "All Files (*)")
                if not fpaths:
                    return
                bad = [os.path.basename(fp) for fp in fpaths if keyword and keyword.lower() not in os.path.basename(fp).lower()]
                if bad:
                    QMessageBox.warning(self, "File Mismatch", f"Patch filename should contain \"{keyword}\": {bad[0]}")
                    return
                self._append_patch_paths(fpaths)
            else:
                fpath, _ = QFileDialog.getOpenFileName(self, "Select Patch", default_dir, "All Files (*);;tar.gz (*.tar.gz)")
                if not fpath:
                    return
                fname = os.path.basename(fpath)
                if keyword and keyword.lower() not in fname.lower():
                    QMessageBox.warning(self, "File Mismatch",
                        f"NE type {ne_type} requires filename containing {keyword}, but selected file is {fname}")
                    return
                self.up_patch_path.setText(fpath)
        patch_btn.clicked.connect(on_browse_patch)
        patch_row.addWidget(patch_btn)
        patch_dir_btn = QPushButton("Folder")
        patch_dir_btn.setStyleSheet(self._btn_secondary())
        def on_browse_patch_dir():
            ne_type, ne_config = self.up_ne_combo.currentData()
            patch_cfg = ne_config.get("patch", {})
            if not patch_cfg.get("allow_dirs"):
                QMessageBox.warning(self, "Warning", "Current NE type does not accept folder patches")
                return
            default_dir = patch_cfg.get("default_dir") or ""
            dpath = QFileDialog.getExistingDirectory(self, "Select Patch Folder", default_dir)
            if not dpath:
                return
            keyword = self._patch_keyword(ne_type, ne_config)
            dname = os.path.basename(os.path.normpath(dpath))
            if keyword and keyword.lower() not in dname.lower():
                QMessageBox.warning(self, "File Mismatch", f"Patch folder name should contain \"{keyword}\": {dname}")
                return
            self._append_patch_paths([dpath])
        patch_dir_btn.clicked.connect(on_browse_patch_dir)
        patch_row.addWidget(patch_dir_btn)
        layout.addLayout(patch_row)

        # NE service control + Steps in horizontal layout
        mid_row = QHBoxLayout()
        mid_row.setSpacing(8)

        # Service buttons (compact vertical stack)
        svc_col = QVBoxLayout()
        svc_col.setSpacing(4)
        self.ne_start_btn = QPushButton("▶ Start NE")
        self.ne_start_btn.setStyleSheet(
            f"QPushButton{{background:{_T['success']};color:white;border:none;border-radius:{_T['btn_radius']};"
            f"padding:6px 14px;font-size:{_T['font_md']};font-weight:600;}}"
            f"QPushButton:hover{{background:{_T['success_hover']};}}"
            f"QPushButton:disabled{{background:#a5d6a7;color:white;}}"
        )
        self.ne_start_btn.clicked.connect(self._do_ne_start)
        svc_col.addWidget(self.ne_start_btn)
        self.ne_stop_btn = QPushButton("⏹ Stop NE")
        self.ne_stop_btn.setStyleSheet(
            f"QPushButton{{background:{_T['warning']};color:white;border:none;border-radius:{_T['btn_radius']};"
            f"padding:6px 14px;font-size:{_T['font_md']};font-weight:600;}}"
            f"QPushButton:hover{{background:#e67e22;}}"
            f"QPushButton:disabled{{background:#f0c27a;color:white;}}"
        )
        self.ne_stop_btn.clicked.connect(self._do_ne_stop)
        svc_col.addWidget(self.ne_stop_btn)
        svc_col.addStretch()
        mid_row.addLayout(svc_col)

        # Steps pipeline
        steps_layout = QVBoxLayout()
        steps_layout.setSpacing(4)
        step_names = [
            ("1", "Stop"), ("2", "Backup"), ("3", "Upload"),
            ("4", "Extract"), ("5", "PostExt"), ("6", "CfgDiff"),
            ("7", "Chown"), ("8", "License"), ("9", "Start"),
        ]
        self.up_step_labels = {}
        for row_idx in range(3):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(0)
            for col_idx in range(3):
                idx = row_idx * 3 + col_idx
                if idx >= len(step_names):
                    break
                num, name = step_names[idx]
                step_widget = QWidget()
                step_widget.setFixedWidth(90)
                step_widget.setFixedHeight(26)
                sw_layout = QHBoxLayout(step_widget)
                sw_layout.setContentsMargins(4, 0, 4, 0)
                sw_layout.setSpacing(2)

                circle = QLabel(num)
                circle.setFixedSize(22, 22)
                circle.setAlignment(Qt.AlignCenter)
                circle.setStyleSheet(
                    f"background:{_T['surface_alt']};color:{_T['text_secondary']};"
                    f"border:2px solid {_T['border']};border-radius:11px;"
                    f"font-size:{_T['font_sm']};font-weight:bold;"
                )
                sw_layout.addWidget(circle)

                name_lbl = QLabel(name)
                name_lbl.setStyleSheet(
                    f"font-size:{_T['font_sm']};color:{_T['text_secondary']};"
                    f"padding:0 2px;font-weight:500;"
                )
                sw_layout.addWidget(name_lbl)

                self.up_step_labels[num] = {'circle': circle, 'label': name_lbl, 'widget': step_widget}
                row_layout.addWidget(step_widget)
                if col_idx < 2 and idx < len(step_names) - 1:
                    arrow = QLabel("→")
                    arrow.setStyleSheet(f"color:{_T['text_hint']};font-size:{_T['font_sm']};padding:0 2px;")
                    row_layout.addWidget(arrow)
            row_layout.addStretch()
            steps_layout.addLayout(row_layout)
        mid_row.addLayout(steps_layout, 1)
        layout.addLayout(mid_row)

        # Control buttons
        ctrl_row = QHBoxLayout()
        self.up_start_btn = QPushButton("Start Upgrade")
        self.up_start_btn.setStyleSheet(self._btn_primary("Start Upgrade", _T['primary']))
        self.up_start_btn.clicked.connect(self._do_upgrade)
        ctrl_row.addWidget(self.up_start_btn)
        self.up_stop_btn = QPushButton("Stop")
        self.up_stop_btn.setStyleSheet(
            f"QPushButton{{background:{_T['danger']};color:white;border:none;border-radius:{_T['btn_radius']};"
            f"padding:6px 14px;font-size:{_T['font_md']};font-weight:600;}}"
            f"QPushButton:hover{{background:{_T['danger_hover']};}}"
            f"QPushButton:disabled{{background:#ffcdd2;color:white;}}"
        )
        self.up_stop_btn.clicked.connect(self._stop_upgrade)
        self.up_stop_btn.setEnabled(False)
        ctrl_row.addWidget(self.up_stop_btn)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)
        return card

    def _load_ne_configs(self):
        try:
            with open(NE_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except: return {}

    def _host_display_name(self, host):
        if not host:
            return ""
        return " ".join(str(host.get(k, "")) for k in ("name", "desc", "host"))

    def _patch_keyword(self, ne_type, ne_config):
        patch_cfg = ne_config.get("patch", {}) if ne_config else {}
        if "keyword" in patch_cfg:
            return patch_cfg.get("keyword") or ""
        keyword_map = {"CCF": "PSC", "MGCF": "MGCF", "XCDR": "XCDR", "QUERY_data": "QUERY", "QUERY_opt": "QUERY", "cdrTools": "cdrTools"}
        return keyword_map.get(ne_type, ne_type)

    def _patch_paths(self):
        text = self.up_patch_path.text().strip()
        return [part.strip().strip('"') for part in text.split(";") if part.strip()]

    def _set_patch_paths(self, paths):
        unique = []
        seen = set()
        for path in paths:
            norm = os.path.normpath(path.strip().strip('"'))
            key = os.path.normcase(norm)
            if norm and key not in seen:
                unique.append(norm)
                seen.add(key)
        self.up_patch_path.setText(";".join(unique))

    def _append_patch_paths(self, paths):
        self._set_patch_paths(self._patch_paths() + paths)

    def _is_host_allowed_for_ne(self, ne_config, host):
        required = (ne_config or {}).get("host_name_required")
        if not required:
            return True, ""
        host_name = self._host_display_name(host)
        if required.lower() in host_name.lower():
            return True, ""
        return False, f"Selected NE requires host name containing {required}"

    def _update_upgrade_button_state(self):
        if not hasattr(self, "up_start_btn"):
            return
        if self._up_worker and self._up_worker.isRunning():
            return
        ne_data = self.up_ne_combo.currentData() if hasattr(self, "up_ne_combo") else None
        ne = ne_data[1] if ne_data else {}
        allowed, reason = self._is_host_allowed_for_ne(ne, self._first_selected_host())
        self.up_start_btn.setEnabled(allowed)
        self.up_start_btn.setToolTip("" if allowed else reason)

    def _do_upgrade(self):
        h = self._first_selected_host()
        if not h:
            QMessageBox.warning(self, "Warning", "Please select a host first"); return
        ne_data = self.up_ne_combo.currentData()
        if not ne_data:
            QMessageBox.warning(self, "Warning", "Select NE type"); return
        ne_type, ne = ne_data
        allowed, reason = self._is_host_allowed_for_ne(ne, h)
        if not allowed:
            QMessageBox.warning(self, "Warning", reason)
            self._update_upgrade_button_state()
            return
        patch_cfg = ne.get("patch", {})
        patch_paths = self._patch_paths()
        if not patch_paths:
            QMessageBox.warning(self, "Warning", "Select valid patch file(s)"); return
        if not patch_cfg.get("multiple") and len(patch_paths) != 1:
            QMessageBox.warning(self, "Warning", "Select only one patch file for this NE type"); return
        allow_dirs = bool(patch_cfg.get("allow_dirs"))
        missing = [p for p in patch_paths if not os.path.isfile(p) and not (allow_dirs and os.path.isdir(p))]
        if missing:
            QMessageBox.warning(self, "Warning", f"Patch path not found: {missing[0]}"); return
        keyword = self._patch_keyword(ne_type, ne)
        bad = [p for p in patch_paths if keyword and keyword.lower() not in os.path.basename(p).lower()]
        if bad:
            QMessageBox.warning(self, "File Mismatch", f"Patch filename should contain \"{keyword}\"")
            return

        self._upgrading = True
        self.up_start_btn.setEnabled(False); self.up_stop_btn.setEnabled(True)
        for info in self.up_step_labels.values():
            circle = info['circle']
            circle.setStyleSheet(
                f"background:{_T['surface_alt']};color:{_T['text_secondary']};"
                f"border:2px solid {_T['border']};border-radius:11px;"
                f"font-size:{_T['font_sm']};font-weight:bold;"
            )
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0)

        patch_arg = patch_paths if patch_cfg.get("multiple") else patch_paths[0]
        self._up_worker = SSHWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), ne, patch_arg)
        self._up_worker.log_signal.connect(self._log)
        self._up_worker.step_signal.connect(self._on_up_step)
        self._up_worker.finished_signal.connect(self._on_up_finished)
        self._up_worker.config_diff_signal.connect(self._on_up_config_diff)
        self._up_worker.kill_residual_signal.connect(self._on_up_kill_residual)
        self._up_worker.finished.connect(self._on_up_thread_finished)
        self._up_worker.start()

    def _stop_upgrade(self):
        if self._up_worker:
            self._up_worker.stop()
            self.up_stop_btn.setEnabled(False)
            self._log("[upgrade] Stop requested")

    def _do_ne_stop(self):
        self._do_ne_service("stop")

    def _do_ne_start(self):
        self._do_ne_service("start")

    def _do_ne_service(self, action):
        h = self._first_selected_host()
        if not h:
            QMessageBox.warning(self, "Warning", "Please select a host first"); return
        ne_data = self.up_ne_combo.currentData()
        if not ne_data:
            QMessageBox.warning(self, "Warning", "Select NE type"); return
        ne_type, ne = ne_data
        cfg = ne.get(action)
        if not cfg:
            QMessageBox.warning(self, "Warning", f"No {action} configuration for {ne_type}"); return
        user = cfg.get("user", "root")
        commands = cfg.get("commands", [])
        inputs = cfg.get("inputs", {}) if action == "stop" else {}
        method = cfg.get("method", "script") if action == "stop" else "script"
        process_names = cfg.get("process_names", []) if action == "stop" else []
        self._log(f"[{action}] {ne_type} on {h['host']} as {user}...")
        w = NEServiceWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), user, method, commands, inputs, process_names, ne_type, action)
        w.log.connect(self._log)
        w.service_finished.connect(lambda ok, msg: self._log(f"[{action}] {'Done' if ok else 'Error'}: {msg}"))
        self.ne_start_btn.setEnabled(False); self.ne_stop_btn.setEnabled(False)
        def on_finished():
            self.ne_start_btn.setEnabled(True); self.ne_stop_btn.setEnabled(True)
            self._ne_service_worker = None
        w.service_finished.connect(lambda *a: on_finished())
        self._ne_service_worker = w
        w.start()

    def _on_up_step(self, step_key):
        step_map = {"stop":"1","backup":"2","upload":"3","extract":"4","post_extract":"5","config_diff":"6","chown":"7","license":"8","start":"9"}
        num = step_map.get(step_key, "?")
        if num in self.up_step_labels:
            info = self.up_step_labels[num]
            circle = info['circle']
            circle.setStyleSheet(
                f"background:{_T['accent']};color:white;"
                f"border:2px solid {_T['accent']};border-radius:11px;"
                f"font-size:{_T['font_sm']};font-weight:bold;"
            )
        steps = {"1":15,"2":25,"3":40,"4":55,"5":65,"6":75,"7":85,"8":90,"9":100}
        self.progress_bar.setValue(steps.get(num, 0))

    def _on_up_finished(self, status):
        self._upgrading = False; self.up_start_btn.setEnabled(True); self.up_stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        if status == "success":
            for info in self.up_step_labels.values():
                circle = info['circle']
                circle.setStyleSheet(
                    f"background:{_T['success']};color:white;"
                    f"border:2px solid {_T['success']};border-radius:11px;"
                    f"font-size:{_T['font_sm']};font-weight:bold;"
                )
        self._log(f"[upgrade] Finished: {status}")
        self._update_upgrade_button_state()

    def _on_up_thread_finished(self):
        if self.sender() is self._up_worker:
            self._up_worker = None
            self._update_upgrade_button_state()

    def _on_up_config_diff(self, diff_items):
        dlg = ConfigDiffDialog(diff_items, self)
        if dlg.exec() == QDialog.Accepted:
            if self._up_worker:
                self._up_worker.set_config_diff_result(dlg.results)
        else:
            if self._up_worker:
                self._up_worker.set_config_diff_result([])

    def _on_up_kill_residual(self, remaining, pname):
        msg = f"Found {len(remaining)} residual processes matching '{pname}'. Continue upgrade?"
        ret = QMessageBox.question(self, "Residual Processes", msg, QMessageBox.Yes | QMessageBox.No)
        if self._up_worker:
            self._up_worker.set_kill_decision(ret == QMessageBox.Yes)

    # ═══════════════════════════════════════════════
    #  Tab 3: 日志 (Log Viewer)
    # ═══════════════════════════════════════════════

    def _init_log_tab(self):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{_T['surface']};border:1px solid {_T['border']};"
            f"border-radius:{_T['card_radius']};}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Section header
        header = QLabel("日志 Log")
        header.setStyleSheet(f"font-size:{_T['font_lg']};font-weight:bold;color:{_T['text']};padding-bottom:2px;")
        layout.addWidget(header)

        # Top bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)
        self.log_ne_combo = QComboBox()
        self.log_ne_configs = self._load_log_ne_configs()
        for log_ne_type, lc in self.log_ne_configs.items():
            self.log_ne_combo.addItem(log_ne_type, lc)
        top_bar.addWidget(QLabel("NE:"))
        top_bar.addWidget(self.log_ne_combo)

        self.log_connect_btn = QPushButton("Connect")
        self.log_connect_btn.setStyleSheet(
            f"QPushButton{{background:{_T['primary']};color:white;border:none;border-radius:{_T['btn_radius']};"
            f"padding:5px 14px;font-size:{_T['font_md']};font-weight:600;}}"
            f"QPushButton:hover{{background:{_T['primary_hover']};}}"
        )
        self.log_connect_btn.clicked.connect(self._do_log_connect)
        top_bar.addWidget(self.log_connect_btn)
        self.log_refresh_btn = QPushButton("Refresh")
        self.log_refresh_btn.setStyleSheet(self._btn_secondary())
        self.log_refresh_btn.clicked.connect(self._do_log_refresh)
        top_bar.addWidget(self.log_refresh_btn)
        top_bar.addStretch()
        self.log_status = QLabel("● Disconnected")
        self.log_status.setStyleSheet(f"color:{_T['danger']};font-weight:bold;font-size:{_T['font_md']};")
        top_bar.addWidget(self.log_status)
        layout.addLayout(top_bar)

        # Nav bar
        nav_bar = QHBoxLayout()
        self.log_up_btn = QPushButton("▲ Up")
        self.log_up_btn.setStyleSheet(self._btn_secondary())
        self.log_up_btn.clicked.connect(self._log_nav_up)
        nav_bar.addWidget(self.log_up_btn)
        self.log_path_label = QLabel("/")
        self.log_path_label.setStyleSheet(
            f"font-size:{_T['font_sm']};color:{_T['text_secondary']};"
            f"padding:3px 6px;background:{_T['surface']};border:1px solid {_T['border']};"
            f"border-radius:4px;"
        )
        nav_bar.addWidget(self.log_path_label, 1)
        layout.addLayout(nav_bar)

        # File table
        self.log_table = QTableWidget(0, 6)
        self.log_table.setHorizontalHeaderLabels(["", "Remote Path", "Description", "Filename", "Size", "Actions"])
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.log_table.setColumnWidth(0, 36)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.log_table.setColumnWidth(5, 160)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.verticalHeader().setDefaultSectionSize(32)
        self.log_table.verticalHeader().setMinimumSectionSize(32)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.cellDoubleClicked.connect(lambda row, column: self._log_activate_row(row))
        self.log_table.installEventFilter(self)
        self.log_table.viewport().installEventFilter(self)
        self.log_table.setStyleSheet(f"""
            QTableWidget {{
                background:{_T['surface']};
                alternate-background-color:{_T['surface_alt']};
                border:1px solid {_T['border']};
                border-radius:{_T['card_radius']};
                gridline-color:{_T['border_light']};
                selection-background-color:{_T['primary_light']};
                selection-color:{_T['text']};
            }}
            QTableWidget::item {{
                padding:4px 6px;
                border:none;
                color:{_T['text']};
            }}
            QTableWidget::item:hover {{
                background:{_T['surface_alt']};
                color:{_T['text']};
            }}
            QTableWidget::item:selected,
            QTableWidget::item:selected:active,
            QTableWidget::item:selected:!active {{
                background:{_T['primary_light']};
                color:{_T['text']};
            }}
            QHeaderView::section {{
                background:{_T['surface_alt']};
                color:{_T['text_secondary']};
                border:none;
                border-bottom:1px solid {_T['border']};
                padding:6px;
                font-weight:600;
                font-size:{_T['font_sm']};
            }}
        """)
        log_toolbar = QHBoxLayout()
        log_toolbar.setSpacing(6)
        self.log_select_all_cb = QCheckBox("Select All")
        self.log_select_all_cb.toggled.connect(self._log_select_all)
        log_toolbar.addWidget(self.log_select_all_cb)
        self.log_download_selected_btn = QPushButton("Download Selected")
        self.log_download_selected_btn.setStyleSheet(self._btn_success())
        self.log_download_selected_btn.clicked.connect(self._log_download)
        self.log_download_selected_btn.setEnabled(False)
        log_toolbar.addWidget(self.log_download_selected_btn)
        log_toolbar.addStretch()
        layout.addLayout(log_toolbar)
        layout.addWidget(self.log_table, 1)

        # Tail bar
        tail_bar = QHBoxLayout()
        tail_bar.addStretch()
        self.log_stop_tail_btn = QPushButton("⬛ Stop Tail")
        self.log_stop_tail_btn.setStyleSheet(
            f"QPushButton{{background:{_T['danger']};color:white;border:none;border-radius:4px;"
            f"padding:4px 14px;font-size:{_T['font_sm']};font-weight:600;}}"
            f"QPushButton:hover{{background:{_T['danger_hover']};}}"
        )
        self.log_stop_tail_btn.clicked.connect(self._log_stop_tail)
        self.log_stop_tail_btn.setVisible(False)
        tail_bar.addWidget(self.log_stop_tail_btn)
        layout.addLayout(tail_bar)

        # Tail view
        self.log_tail_view = QTextEdit()
        self.log_tail_view.setReadOnly(True)
        self.log_tail_view.setFont(QFont("Consolas", 10))
        self.log_tail_view.setMinimumHeight(60)
        self.log_tail_view.setMaximumHeight(150)
        self.log_tail_view.setStyleSheet(
            f"QTextEdit{{background:#1e1e1e;color:#d4d4d4;border:1px solid {_T['border']};"
            f"border-radius:{_T['card_radius']};padding:8px;font-size:{_T['font_sm']};}}"
        )
        self.log_tail_view.setVisible(False)
        layout.addWidget(self.log_tail_view)

        self._log_browse_path = ""
        self._log_root_paths = set()
        self._log_tail_path = ""
        return card

    def _load_log_ne_configs(self):
        try:
            with open(LOG_NE_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except: return {}

    def _current_log_host(self):
        return self._first_selected_host()

    def _log_ssh(self):
        h = self._current_log_host()
        if not h: raise RuntimeError("No host selected")
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(h["host"], int(h.get("port",22)), h["user"], h.get("pwd",""), timeout=5)
        return c

    def _log_select_all(self, checked):
        for row in range(self.log_table.rowCount()):
            cw = self.log_table.cellWidget(row, 0)
            if not cw:
                continue
            cb = cw.layout().itemAt(0).widget()
            if cb and cb.isEnabled():
                cb.setChecked(checked)

    def _do_log_connect(self):
        h = self._current_log_host()
        if not h:
            QMessageBox.warning(self, "Warning", "Select a host first"); return
        self.log_status.setText("● Connecting...")
        self.log_status.setStyleSheet("color:#fdd835;font-weight:bold;font-size:13px;")
        self._log_file_list = []
        self._log_current_path = ""
        self.log_table.setRowCount(0)
        if hasattr(self, 'log_select_all_cb'):
            self.log_select_all_cb.blockSignals(True); self.log_select_all_cb.setChecked(False); self.log_select_all_cb.blockSignals(False)
        if hasattr(self, 'log_download_selected_btn'):
            self.log_download_selected_btn.setEnabled(False)
        self._log_worker = LogListWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), self.log_ne_combo.currentData())
        self._log_worker.log.connect(self._log)
        self._log_worker.file_info.connect(self._on_log_file_info)
        self._log_worker.finished.connect(self._on_log_list_finished)
        self._log_worker.error.connect(lambda e: (self._log(f"[error] {e}"), self.log_status.setText("● Error")))
        self._log_worker.start()

    def _on_log_file_info(self, info):
        self._log_file_list.append(info)
        self._log_table_add_row(info)
        if hasattr(self, 'log_download_selected_btn'):
            self.log_download_selected_btn.setEnabled(True)

    def _log_table_add_row(self, info):
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)
        self.log_table.setRowHeight(row, 34)

        is_missing = info.get("missing", False)
        is_group = info.get("type") == "group"
        is_dir = info.get("type") == "directory"

        cb = QCheckBox()
        cw = QWidget(); cl = QHBoxLayout(cw); cl.setContentsMargins(0,0,0,0); cl.setAlignment(Qt.AlignCenter); cl.addWidget(cb)
        self.log_table.setCellWidget(row, 0, cw)

        name_item = QTableWidgetItem(info.get("name",""))
        if is_missing: name_item.setForeground(Qt.gray)
        if is_group: name_item.setForeground(Qt.darkBlue)
        if is_dir:
            name_item.setForeground(Qt.darkMagenta)
            name_item.setToolTip("Click to enter directory")
        self.log_table.setItem(row, 3, name_item)

        desc = info.get("desc","") or "无"
        desc_item = QTableWidgetItem(desc)
        if is_missing: desc_item.setForeground(Qt.gray)
        self.log_table.setItem(row, 2, desc_item)

        fpath = info.get("path","")
        group_files = info.get("group_files",[])
        if is_group and len(group_files) > 1:
            expand_btn = QPushButton(f"▾ {fpath}")
            expand_btn.setStyleSheet("QPushButton{background:transparent;border:none;text-align:left;font-size:12px;color:#0984e3;}")
            expand_btn.clicked.connect(lambda checked, gf=group_files, btn=expand_btn: self._log_open_group_menu(btn, gf))
            self.log_table.setCellWidget(row, 1, expand_btn)
        else:
            path_item = QTableWidgetItem(fpath)
            if is_missing: path_item.setForeground(Qt.gray)
            self.log_table.setItem(row, 1, path_item)

        if is_group:
            size_str = f"{info.get('size',0)} files"
        elif is_dir:
            size_str = "folder"
        else:
            size_str = _format_size(info.get("size",0)) if not is_missing else "N/A"
        size_item = QTableWidgetItem(size_str)
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.log_table.setItem(row, 4, size_item)

        actions_w = QWidget()
        actions_l = QHBoxLayout(actions_w); actions_l.setContentsMargins(0,0,0,0); actions_l.setSpacing(6); actions_l.setAlignment(Qt.AlignCenter)
        view_btn = QPushButton("View" if not is_dir else "Enter")
        view_btn.setFixedSize(62, 24)
        view_btn.setStyleSheet("QPushButton{background:#00b894;color:white;border:none;border-radius:4px;padding:0;font-size:11px;}QPushButton:hover{background:#00a381;}")
        dl_btn = QPushButton("Download")
        dl_btn.setFixedSize(86, 24)
        dl_btn.setStyleSheet("QPushButton{background:#0984e3;color:white;border:none;border-radius:4px;padding:0;font-size:11px;}QPushButton:hover{background:#0873c4;}")
        if is_missing:
            view_btn.setEnabled(False); dl_btn.setEnabled(False); cb.setEnabled(False)
        if is_group:
            is_single = len(group_files) == 1
            if is_single:
                single_path = group_files[0]
                view_btn.clicked.connect(lambda checked, p=single_path: self._log_view_file_at(p))
            else:
                view_btn.clicked.connect(lambda checked, gf=group_files, btn=view_btn: self._log_open_group_menu(btn, gf))
            dl_btn.clicked.connect(lambda checked, gf=group_files: self._log_download_group(gf))
        elif is_dir:
            view_btn.clicked.connect(lambda checked, p=fpath: self._browse_log_path(p))
            dl_btn.clicked.connect(lambda checked, p=fpath: self._log_download_path(p))
        else:
            view_btn.clicked.connect(lambda checked, p=fpath: self._log_view_file_at(p))
            dl_btn.clicked.connect(lambda checked, p=fpath, n=info.get("name","file"): self._log_download_path(p))
        actions_l.addWidget(view_btn); actions_l.addWidget(dl_btn)
        self.log_table.setCellWidget(row, 5, actions_w)

    def _on_log_list_finished(self):
        self.log_status.setText("● Connected")
        self.log_status.setStyleSheet("color:#27ae60;font-weight:bold;font-size:13px;")
        self._log_root_data = list(self._log_file_list)
        if hasattr(self, 'log_download_selected_btn'):
            self.log_download_selected_btn.setEnabled(bool(self._log_file_list))

    def _log_open_group_menu(self, btn, group_files):
        menu = QMenu()
        for fp in group_files:
            action = menu.addAction(fp)
            action.triggered.connect(lambda checked, p=fp: self._log_view_file_at(p))
        if btn is not None:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            menu.exec(self.log_table.mapToGlobal(self.log_table.rect().center()))

    def _do_log_refresh(self):
        self._do_log_connect()

    def _log_nav_up(self):
        if not hasattr(self, '_log_root_data') or not self._log_root_data: return
        self.log_table.setRowCount(0)
        self._log_file_list = []
        if hasattr(self, 'log_select_all_cb'):
            self.log_select_all_cb.blockSignals(True); self.log_select_all_cb.setChecked(False); self.log_select_all_cb.blockSignals(False)
        for info in self._log_root_data:
            self._log_file_list.append(info)
            self._log_table_add_row(info)
        self.log_path_label.setText("/")
        self._log_browse_path = ""

    def _browse_log_path(self, path):
        h = self._current_log_host()
        if not h: return
        self._log_browse_path = path
        self.log_path_label.setText(path)
        self.log_status.setText("● Browsing...")
        self.log_status.setStyleSheet("color:#fdd835;font-weight:bold;font-size:13px;")
        self._log_file_list = []
        self.log_table.setRowCount(0)
        if hasattr(self, 'log_select_all_cb'):
            self.log_select_all_cb.blockSignals(True); self.log_select_all_cb.setChecked(False); self.log_select_all_cb.blockSignals(False)
        self._log_browse_worker = LogBrowseWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), path)
        self._log_browse_worker.log.connect(self._log)
        self._log_browse_worker.file_info.connect(self._on_log_file_info)
        self._log_browse_worker.finished.connect(lambda: (self.log_status.setText("● Connected"), self.log_status.setStyleSheet("color:#27ae60")))
        self._log_browse_worker.error.connect(lambda e: (self._log(f"[error] {e}"), self.log_status.setText("● Error")))
        self._log_browse_worker.start()

    def _log_view_file(self):
        rows = self._get_log_selected_rows()
        if not rows: return
        self._log_open_info(self._log_file_list[rows[0]])

    def _log_activate_current_row(self):
        row = self.log_table.currentRow()
        if row < 0:
            selected = self.log_table.selectionModel().selectedRows()
            row = selected[0].row() if selected else -1
        self._log_activate_row(row)

    def _log_activate_row(self, row):
        if row < 0 or row >= len(getattr(self, "_log_file_list", [])):
            return
        self._log_open_info(self._log_file_list[row])

    def _log_open_info(self, info):
        if info.get("type") == "directory":
            self._browse_log_path(info["path"])
        elif info.get("type") == "group" and len(info.get("group_files",[])) == 1:
            self._log_view_file_at(info["group_files"][0])
        elif info.get("type") == "group":
            self._log_open_group_menu(None, info["group_files"])
        else:
            self._log_view_file_at(info.get("path",""))

    def _log_view_file_at(self, path):
        h = self._current_log_host()
        if not h: return
        self.log_tail_view.setVisible(True)
        self.log_tail_view.setPlainText("Loading...\n")
        self._log_tail_path = path
        if hasattr(self, '_log_tail_worker') and self._log_tail_worker:
            self._log_tail_worker.stop()
            self._log_tail_worker.wait(3000)
        self.log_stop_tail_btn.setVisible(True)
        w = LogViewerWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), path, tail=True)
        w.log.connect(lambda t: self.log_tail_view.append(t))
        w.done.connect(lambda: None)
        w.start()
        self._log_tail_worker = w

    def _log_stop_tail(self):
        if hasattr(self, '_log_tail_worker') and self._log_tail_worker:
            self._log_tail_worker.stop()
            self._log_tail_worker.wait(3000)
            self._log_tail_worker = None
        self.log_stop_tail_btn.setVisible(False)

    def _log_download(self):
        if getattr(self, '_log_download_active', False):
            self._log("[download] Another download is running")
            return
        rows = self._get_log_selected_rows()
        if not rows: return
        h = self._current_log_host()
        if not h: return
        save_dir = QFileDialog.getExistingDirectory(self, "Save to")
        if not save_dir: return
        files_to_dl = []
        for r in rows:
            info = self._log_file_list[r]
            if info.get("type") == "group":
                files_to_dl.extend(info.get("group_files",[]))
            elif info.get("type") == "directory":
                files_to_dl.append(info["path"])
            else:
                files_to_dl.append(info["path"])
        self._start_log_download(files_to_dl, save_dir)

    def _log_download_group(self, group_files):
        if getattr(self, '_log_download_active', False):
            self._log("[download] Another download is running")
            return
        h = self._current_log_host()
        if not h: return
        save_dir = QFileDialog.getExistingDirectory(self, "Save to")
        if not save_dir: return
        self._start_log_download(group_files, save_dir)

    def _log_download_path(self, path):
        if getattr(self, '_log_download_active', False):
            self._log("[download] Another download is running")
            return
        h = self._current_log_host()
        if not h: return
        save_dir = QFileDialog.getExistingDirectory(self, "Save to")
        if not save_dir: return
        self._start_log_download([{"remote_path": path, "filename": os.path.basename(path)}], save_dir)

    def _start_log_download(self, files_to_dl, save_dir):
        if not files_to_dl:
            return
        if getattr(self, '_log_download_active', False):
            self._log("[download] Another download is running")
            return
        h = self._current_log_host()
        if not h:
            return
        self._log_download_active = True
        self.log_status.setText("● Downloading...")
        self.log_status.setStyleSheet("color:#fdd835;font-weight:bold;font-size:13px;")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        if hasattr(self, 'log_download_selected_btn'):
            self.log_download_selected_btn.setEnabled(False)
        self.log_connect_btn.setEnabled(False)
        self.log_refresh_btn.setEnabled(False)
        self._log_dl_worker = LogDownloadWorker(h["host"], h.get("port",22), h["user"], h.get("pwd",""), files_to_dl, save_dir)
        self._log_dl_worker.log.connect(self._log)
        self._log_dl_worker.progress.connect(self.progress_bar.setValue)
        self._log_dl_worker.done.connect(self._on_log_download_done)
        self._log_dl_worker.error.connect(self._on_log_download_error)
        self._log_dl_worker.start()

    def _finish_log_download_ui(self, ok):
        self._log_download_active = False
        self.progress_bar.setVisible(False)
        self.log_connect_btn.setEnabled(True)
        self.log_refresh_btn.setEnabled(True)
        if hasattr(self, 'log_download_selected_btn'):
            self.log_download_selected_btn.setEnabled(bool(getattr(self, '_log_file_list', [])))
        self.log_status.setText("● Connected" if ok else "● Error")
        self.log_status.setStyleSheet("color:#27ae60;font-weight:bold;font-size:13px;" if ok else "color:#e74c3c;font-weight:bold;font-size:13px;")

    def _on_log_download_done(self, message):
        self._log(f"[download] {message}")
        self._finish_log_download_ui(True)

    def _on_log_download_error(self, message):
        self._log(f"[error] {message}")
        self._finish_log_download_ui(False)

    def _get_log_selected_rows(self):
        rows = set()
        for row in range(self.log_table.rowCount()):
            cw = self.log_table.cellWidget(row, 0)
            if cw:
                cb = cw.layout().itemAt(0).widget()
                if cb and cb.isChecked(): rows.add(row)
        return sorted(rows)

# ═══════════════════════════════════════════════
#  Capture Workers
# ═══════════════════════════════════════════════

class KillWorker(QThread):
    def __init__(self, host, port, user, pwd, out_names):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd; self.out_names = out_names
    def run(self):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(self.host, self.port, self.user, self.pwd, timeout=5)
            for name in self.out_names:
                c.exec_command(f"pkill -f {_shell_quote('tcpdump .*' + name)} 2>/dev/null || true")
            c.exec_command("sleep 1")
            c.close()
        except: pass

class CaptureWorker(QThread):
    log = Signal(str); progress = Signal(int); done = Signal(str); error = Signal(str)
    def __init__(self, host, port, user, pwd, cmd, remote_path, local_path, duration, compress=True):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd
        self.cmd = cmd; self.remote_path = remote_path; self.local_path = local_path
        self.duration = int(duration); self.compress = compress
        self._last_monitor_ok = None
    def _ssh(self):
        c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(self.host, self.port, self.user, self.pwd, timeout=10, banner_timeout=10, auth_timeout=10)
        transport = c.get_transport()
        if transport:
            transport.set_keepalive(15)
        return c
    def _ssh_exec_retry(self, cmd, timeout=10, retries=12, delay=5):
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                return self._ssh_exec(cmd, timeout=timeout)
            except Exception as e:
                last_err = e
                if attempt < retries:
                    self.log.emit(f"[tcpdump] reconnect {attempt}/{retries}: {self._err_text(e)}")
                    time.sleep(delay)
        raise last_err
    def _ssh_fire_and_forget(self, cmd, timeout=5):
        c = self._ssh()
        try:
            chan = c.get_transport().open_session(); chan.settimeout(timeout)
            chan.exec_command(cmd)
            time.sleep(0.5)
            chan.close()
        finally:
            c.close()
    def _ssh_fire_retry(self, cmd, timeout=5, retries=12, delay=5):
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                self._ssh_fire_and_forget(cmd, timeout=timeout)
                return
            except Exception as e:
                last_err = e
                if attempt < retries:
                    self.log.emit(f"[tcpdump] reconnect before start {attempt}/{retries}: {self._err_text(e)}")
                    time.sleep(delay)
        raise last_err
    def _err_text(self, exc):
        text = str(exc).strip()
        return text or exc.__class__.__name__
    def _download_retry(self, remote_path, local_path, retries=12, delay=5):
        last_err = None
        for attempt in range(1, retries + 1):
            c = None
            try:
                c = self._ssh(); SCPClient(c.get_transport()).get(remote_path, local_path); c.close()
                return
            except Exception as e:
                last_err = e
                try:
                    if c: c.close()
                except: pass
                if attempt < retries:
                    self.log.emit(f"[tcpdump] reconnect for download {attempt}/{retries}: {self._err_text(e)}")
                    time.sleep(delay)
        raise last_err
    def _match_tcpdump(self):
        out, _ = self._ssh_exec(_remote_tcpdump_match_cmd(self.remote_path), timeout=5)
        return out
    def run(self):
        try:
            self.log.emit(f"[tcpdump] Execute: {self.cmd}")
            self._ssh_exec_retry("mkdir -p /opt/tar")
            self._ssh_fire_retry(f"nohup {self.cmd} </dev/null >/dev/null 2>&1 &")
            self.log.emit(f"[tcpdump] Capturing {self.duration}s ...")
            for i in range(self.duration):
                time.sleep(1); self.progress.emit(int((i+1)*100/self.duration))
                if i == 0 or (i + 1) % 5 == 0:
                    try:
                        procs = self._match_tcpdump()
                        if self._last_monitor_ok is not True:
                            self.log.emit("[tcpdump] control connection ready (root shell)")
                        if procs:
                            self.log.emit(f"[tcpdump] matched process: {procs.splitlines()[0]}")
                        else:
                            self.log.emit("[tcpdump] process not found; stop will still collect the pcap if it exists")
                        self._last_monitor_ok = True
                    except Exception as e:
                        if self._last_monitor_ok is not False:
                            self.log.emit(f"[tcpdump] control connection lost, reconnecting in background: {self._err_text(e)}")
                        self._last_monitor_ok = False
            self.log.emit("[tcpdump] Stopping capture")
            self._ssh_exec_retry(_remote_tcpdump_kill_cmd(self.remote_path) + "; sleep 2")
            out, _ = self._ssh_exec_retry(f"test -f {self.remote_path} && echo OK || echo MISSING")
            if out != "OK":
                raise RuntimeError(f"File not found: {self.remote_path}")
            dl_path, dl_local = self.remote_path, self.local_path
            if self.compress:
                self.log.emit(f"[compress] gzip {self.remote_path}")
                self._ssh_exec_retry(f"gzip -f {self.remote_path}", timeout=120)
                dl_path, dl_local = self.remote_path+".gz", self.local_path+".gz"
            self.log.emit(f"[download] {dl_path} -> {dl_local}")
            self._download_retry(dl_path, dl_local)
            self._ssh_exec_retry(f"rm -f {_shell_quote(dl_path)} {_shell_quote(self.remote_path + '.tcpdump.log')}")
            self.log.emit(f"[done] {dl_local}"); self.done.emit(dl_local)
        except Exception as e:
            try:
                self._ssh_exec_retry(f"rm -f {_shell_quote(self.remote_path + '.tcpdump.log')}", retries=1)
            except Exception:
                pass
            self.log.emit(f"[error] {str(e)}"); self.error.emit(str(e)); logger.exception("CaptureWorker error")
    def _ssh_exec(self, cmd, timeout=10):
        c = self._ssh(); chan = c.get_transport().open_session(); chan.settimeout(timeout)
        chan.exec_command(cmd); out = chan.makefile("rb",-1).read(); err = chan.makefile_stderr("rb",-1).read().decode("utf-8",errors="replace").strip()
        c.close()
        for enc in ("utf-8","gbk"):
            try: return out.decode(enc).strip(), err
            except: continue
        return out.decode("utf-8",errors="replace").strip(), err
    def _ssh_nohup(self, cmd):
        c = self._ssh(); chan = c.get_transport().open_session(); chan.exec_command(cmd); chan.close(); c.close()

class CaptureStartWorker(QThread):
    started = Signal(); control_ready = Signal(bool); log = Signal(str); error = Signal(str)
    def __init__(self, host, port, user, pwd, cmd, remote_path=None):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd; self.cmd = cmd
        self.remote_path = remote_path
        self._remote_path = remote_path
        self._stop_requested = False
        self._last_ready = None
    def request_stop(self): self._stop_requested = True
    def _ssh(self):
        c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(self.host, self.port, self.user, self.pwd, timeout=10, banner_timeout=10, auth_timeout=10)
        transport = c.get_transport()
        if transport:
            transport.set_keepalive(15)
        return c
    def _ssh_exec(self, cmd, timeout=10):
        c = self._ssh()
        try:
            chan = c.get_transport().open_session(); chan.settimeout(timeout)
            chan.exec_command(cmd)
            out = chan.makefile("rb", -1).read().decode("utf-8", errors="replace").strip()
            err = chan.makefile_stderr("rb", -1).read().decode("utf-8", errors="replace").strip()
            return out, err
        finally:
            c.close()
    def _ssh_fire_and_forget(self, cmd, timeout=5):
        c = self._ssh()
        try:
            chan = c.get_transport().open_session(); chan.settimeout(timeout)
            chan.exec_command(cmd)
            time.sleep(0.5)
            chan.close()
        finally:
            c.close()
    def _err_text(self, exc):
        text = str(exc).strip()
        return text or exc.__class__.__name__
    def _set_ready(self, ready):
        self.setProperty("_control_ready", ready)
        if self._last_ready is not ready:
            self.control_ready.emit(ready)
            self._last_ready = ready
    def _match_tcpdump(self):
        remote_path = self.remote_path or getattr(self, "_remote_path", "")
        if not remote_path:
            out, _ = self._ssh_exec("for p in $(pgrep -x tcpdump 2>/dev/null); do ps -o pid=,args= -p \"$p\"; done", timeout=5)
            return out
        out, _ = self._ssh_exec(_remote_tcpdump_match_cmd(remote_path), timeout=5)
        return out
    def _start_or_attach(self):
        procs = self._match_tcpdump()
        if procs:
            return procs
        log_path = f"{self.remote_path}.tcpdump.log"
        out, err = self._ssh_exec(
            f"mkdir -p /opt/tar; rm -f {_shell_quote(log_path)}; "
            f"nohup {self.cmd} </dev/null > {_shell_quote(log_path)} 2>&1 & echo $!",
            timeout=8,
        )
        pid = (out or "").strip().splitlines()[-1:] or [""]
        if pid[0]:
            self.log.emit(f"[tcpdump] start pid: {pid[0]}")
        if err:
            self.log.emit(f"[tcpdump] start stderr: {err}")
        for _ in range(5):
            time.sleep(1)
            procs = self._match_tcpdump()
            if procs:
                return procs
        exists, _ = self._ssh_exec(f"test -f {_shell_quote(self.remote_path)} && echo OK || echo MISSING", timeout=5)
        log_out, _ = self._ssh_exec(f"test -f {_shell_quote(log_path)} && tail -80 {_shell_quote(log_path)} || true", timeout=5)
        detail = log_out.strip() or f"pcap={exists.strip() or 'UNKNOWN'}"
        raise RuntimeError(f"tcpdump did not start or exited early: {detail}")
    def run(self):
        started_emitted = False
        last_proc_log = 0
        last_state_log = None
        self.log.emit("[tcpdump] connecting root shell")
        try:
            while not self._stop_requested:
                try:
                    procs = self._start_or_attach() if not started_emitted else self._match_tcpdump()
                    self._set_ready(True)
                    if not started_emitted:
                        self.started.emit()
                        started_emitted = True
                        self.log.emit("[tcpdump] capture control ready")
                    now = time.time()
                    if now - last_proc_log >= 10:
                        if procs:
                            self.log.emit(f"[tcpdump] matched process: {procs.splitlines()[0]}")
                        else:
                            self.log.emit("[tcpdump] connected, but tcpdump process is not matched")
                        last_proc_log = now
                    last_state_log = "ready"
                    for _ in range(2):
                        if self._stop_requested:
                            break
                        time.sleep(1)
                except Exception as e:
                    self._set_ready(False)
                    msg = self._err_text(e)
                    if msg.startswith("tcpdump did not start"):
                        self.error.emit(msg)
                        return
                    if last_state_log != msg:
                        self.log.emit(f"[tcpdump] control connection lost, reconnecting: {msg}")
                        last_state_log = msg
                    for _ in range(2):
                        if self._stop_requested:
                            break
                        time.sleep(1)
        except Exception as e:
            self.error.emit(self._err_text(e))
        finally:
            self._set_ready(False)

class CaptureStopWorker(QThread):
    log = Signal(str); done = Signal(str); error = Signal(str)
    def __init__(self, host, port, user, pwd, remote_path, local_path, compress=True):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd
        self.remote_path = remote_path; self.local_path = local_path; self.compress = compress
    def _ssh(self):
        c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(self.host, self.port, self.user, self.pwd, timeout=10, banner_timeout=10, auth_timeout=10)
        transport = c.get_transport()
        if transport:
            transport.set_keepalive(15)
        return c
    def _exec_retry(self, cmd, timeout=10, retries=12, delay=5):
        last_err = None
        for attempt in range(1, retries + 1):
            c = None
            try:
                c = self._ssh(); chan = c.get_transport().open_session(); chan.settimeout(timeout)
                chan.exec_command(cmd)
                out = chan.makefile("rb",-1).read().decode("utf-8",errors="replace").strip()
                err = chan.makefile_stderr("rb",-1).read().decode("utf-8",errors="replace").strip()
                chan.close(); c.close()
                return out, err
            except Exception as e:
                last_err = e
                try:
                    if c: c.close()
                except: pass
                if attempt < retries:
                    self.log.emit(f"[tcpdump] reconnect before stop {attempt}/{retries}: {e}")
                    time.sleep(delay)
        raise last_err
    def _download_retry(self, remote_path, local_path, retries=12, delay=5):
        last_err = None
        for attempt in range(1, retries + 1):
            c = None
            try:
                c = self._ssh(); SCPClient(c.get_transport()).get(remote_path, local_path); c.close()
                return
            except Exception as e:
                last_err = e
                try:
                    if c: c.close()
                except: pass
                if attempt < retries:
                    self.log.emit(f"[tcpdump] reconnect for download {attempt}/{retries}: {e}")
                    time.sleep(delay)
        raise last_err
    def run(self):
        try:
            self.log.emit("[tcpdump] Stopping capture")
            procs, _ = self._exec_retry(_remote_tcpdump_match_cmd(self.remote_path))
            if procs:
                self.log.emit(f"[tcpdump] matched process before stop: {procs.splitlines()[0]}")
            self._exec_retry(_remote_tcpdump_kill_cmd(self.remote_path) + "; sleep 2")
            out, _ = self._exec_retry(f"test -f {self.remote_path} && echo OK || echo MISSING")
            if out != "OK": raise RuntimeError(f"File not found: {self.remote_path}")
            dl_path, dl_local = self.remote_path, self.local_path
            if self.compress:
                self.log.emit(f"[compress] gzip {self.remote_path}")
                self._exec_retry(f"gzip -f {self.remote_path}", timeout=120)
                dl_path, dl_local = self.remote_path+".gz", self.local_path+".gz"
            self.log.emit(f"[download] {dl_path} -> {dl_local}")
            self._download_retry(dl_path, dl_local)
            self._exec_retry(f"rm -f {_shell_quote(dl_path)} {_shell_quote(self.remote_path + '.tcpdump.log')}")
            self.log.emit(f"[done] {dl_local}"); self.done.emit(dl_local)
        except Exception as e:
            try:
                self._exec_retry(f"rm -f {_shell_quote(self.remote_path + '.tcpdump.log')}", retries=1)
            except Exception:
                pass
            self.log.emit(f"[error] {str(e)}"); self.error.emit(str(e))

class SBCMCaptureWorker(QThread):
    log = Signal(str); progress = Signal(int); done = Signal(str); control_ready = Signal(bool); error = Signal(str)
    def __init__(self, host, port, user, pwd, local_path, duration=None):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd
        self.local_path = local_path; self.duration = int(duration) if duration is not None else None
        self._stop_requested = False; self._chan = None; self._ssh = None
        self._last_ready = None
    def request_stop(self): self._stop_requested = True
    def _set_ready(self, ready):
        self.setProperty("_control_ready", ready)
        if self._last_ready is not ready:
            self.control_ready.emit(ready)
            self._last_ready = ready
    def _recv_all(self, chan):
        data = b""
        while chan.recv_ready():
            chunk = chan.recv(4096)
            if not chunk: break
            data += chunk
        if data: self.log.emit(f"[SBCM] [recv] {data.decode('utf-8',errors='replace')[-500:]}")
        return data
    def _expect(self, chan, expected, timeout=30):
        data = b""; start = time.time()
        while time.time()-start < timeout:
            if chan.recv_ready():
                chunk = chan.recv(4096)
                if not chunk: break
                data += chunk
                txt = data.decode("utf-8",errors="replace")
                if expected in txt:
                    self.log.emit(f"[SBCM] [expect] '{expected}' matched")
                    return txt
            elif chan.exit_status_ready(): break
            else: time.sleep(0.1)
        txt = data.decode("utf-8",errors="replace")
        self.log.emit(f"[SBCM] [expect] '{expected}' timeout, recv={txt[-300:]}")
        raise TimeoutError(f"Expected '{expected}' not found. Got: {txt[-300:]}")
    def _expect_any(self, chan, expected_list, timeout=30):
        data = b""; start = time.time()
        while time.time()-start < timeout:
            if chan.recv_ready():
                chunk = chan.recv(4096)
                if not chunk: break
                data += chunk
                txt = data.decode("utf-8",errors="replace")
                for expected in expected_list:
                    if expected in txt:
                        self.log.emit(f"[SBCM] [expect] '{expected}' matched")
                        return expected, txt
            elif chan.exit_status_ready(): break
            else: time.sleep(0.1)
        txt = data.decode("utf-8",errors="replace")
        labels = ", ".join(repr(x) for x in expected_list)
        self.log.emit(f"[SBCM] [expect] any({labels}) timeout, recv={txt[-300:]}")
        raise TimeoutError(f"Expected one of {labels} not found. Got: {txt[-300:]}")
    def _send_cmd(self, chan, text, label=None):
        label = label or text.rstrip("\n")
        self.log.emit(f"[SBCM] [send] {label}"); chan.send(text)
    def _telnet_and_diagnose(self, chan):
        self._recv_all(chan)
        self._send_cmd(chan, "telnet 127.0.0.1\n")
        for _ in range(3):
            self._expect(chan, "[USERNAME]:")
            self._send_cmd(chan, "admin\n", "admin (username)")
            self._expect(chan, "[PASSWORD]:")
            self._send_cmd(chan, "admin\n", "admin (password)")
            for _ in range(4):
                matched, _ = self._expect_any(
                    chan,
                    ["NuBiz>>", "Kick it out", "Y/N", "[USERNAME]:"],
                    timeout=30,
                )
                if matched == "NuBiz>>":
                    self._send_cmd(chan, "cm diagnose\n")
                    self._expect(chan, "NuBiz$$")
                    return
                if matched in ("Kick it out", "Y/N"):
                    self._send_cmd(chan, "Y\n", "kick existing admin session Y")
                    continue
                if matched == "[USERNAME]:":
                    self._send_cmd(chan, "admin\n", "admin (username)")
                    self._expect(chan, "[PASSWORD]:")
                    self._send_cmd(chan, "admin\n", "admin (password)")
                    continue
        raise TimeoutError("SBCM telnet login failed: NuBiz>> not reached")
    def _stop_capture(self, chan):
        self._send_cmd(chan, "debug dp 0x912\n")
        self._expect(chan, "<para1>"); self._send_cmd(chan, "\n","enter para1")
        self._expect(chan, "<para2>"); self._send_cmd(chan, "\n","enter para2")
        self._expect(chan, "<para3>"); self._send_cmd(chan, "\n","enter para3")
        self._expect(chan, "<para4>"); self._send_cmd(chan, "\n","enter para4")
        self._expect(chan, "End of Packet Capture", timeout=120)
    def _close_control(self):
        if self._chan:
            try: self._chan.close()
            except: pass
        if self._ssh:
            try: self._ssh.close()
            except: pass
        self._chan = None; self._ssh = None
        self._set_ready(False)
    def _connect_control(self, retries=12, delay=5):
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                self._close_control()
                self.log.emit(f"[SBCM] Connecting {self.host}:{self.port}")
                c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(self.host, self.port, self.user, self.pwd, timeout=10, banner_timeout=10, auth_timeout=10)
                transport = c.get_transport()
                if transport:
                    transport.set_keepalive(15)
                chan = c.invoke_shell(); chan.settimeout(30)
                self._ssh = c; self._chan = chan
                time.sleep(1); self._recv_all(chan)
                self._telnet_and_diagnose(chan)
                self._set_ready(True)
                self.log.emit("[SBCM] NuBiz$$ control view ready")
                return chan
            except Exception as e:
                last_err = e
                self._close_control()
                if attempt < retries:
                    self.log.emit(f"[SBCM] reconnect {attempt}/{retries}: {e}")
                    time.sleep(delay)
        raise last_err
    def _ensure_control(self):
        chan = self._chan
        if not chan or not chan.active or chan.exit_status_ready():
            self.log.emit("[SBCM] control session lost, reconnecting")
            return self._connect_control()
        try:
            if chan.recv_ready():
                chan.recv(4096)
            chan.send("\n")
            return chan
        except Exception as e:
            self.log.emit(f"[SBCM] keepalive failed, reconnecting: {e}")
            return self._connect_control()
    def _ssh_exec_retry(self, cmd, timeout=10, retries=12, delay=5):
        last_err = None
        for attempt in range(1, retries + 1):
            c = None
            try:
                c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(self.host, self.port, self.user, self.pwd, timeout=10, banner_timeout=10, auth_timeout=10)
                transport = c.get_transport()
                if transport:
                    transport.set_keepalive(15)
                chan = transport.open_session(); chan.settimeout(timeout)
                chan.exec_command(cmd)
                out = chan.makefile("rb",-1).read().decode("utf-8",errors="replace").strip()
                err = chan.makefile_stderr("rb",-1).read().decode("utf-8",errors="replace").strip()
                chan.close(); c.close()
                return out, err
            except Exception as e:
                last_err = e
                try:
                    if c: c.close()
                except: pass
                if attempt < retries:
                    self.log.emit(f"[SBCM] reconnect for file operation {attempt}/{retries}: {e}")
                    time.sleep(delay)
        raise last_err
    def _download_retry(self, remote_path, local_path, retries=12, delay=5):
        last_err = None
        for attempt in range(1, retries + 1):
            c = None
            try:
                c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(self.host, self.port, self.user, self.pwd, timeout=10, banner_timeout=10, auth_timeout=10)
                SCPClient(c.get_transport()).get(remote_path, local_path); c.close()
                return
            except Exception as e:
                last_err = e
                try:
                    if c: c.close()
                except: pass
                if attempt < retries:
                    self.log.emit(f"[SBCM] reconnect for download {attempt}/{retries}: {e}")
                    time.sleep(delay)
        raise last_err
    def run(self):
        try:
            chan = self._connect_control()
            self._send_cmd(chan, "debug dp 0x911\n")
            self._expect(chan, "<para1>"); self._send_cmd(chan, "\n","enter para1")
            self._expect(chan, "<para2>"); self._send_cmd(chan, "\n","enter para2")
            self._expect(chan, "<para3>"); self._send_cmd(chan, "\n","enter para3")
            self._expect(chan, "<para4>"); self._send_cmd(chan, "\n","enter para4")
            self.log.emit("[SBCM] Capture started")
            self._capture_start = time.time(); last_keepalive = time.time()
            while True:
                if self.duration is not None:
                    elapsed = int(time.time()-self._capture_start)
                    if elapsed >= self.duration: break
                    self.progress.emit(int(elapsed*100/self.duration))
                else:
                    self.progress.emit(50)
                    if self._stop_requested: break
                if time.time()-last_keepalive >= 30:
                    chan = self._ensure_control(); last_keepalive = time.time()
                    self.log.emit("[SBCM] keepalive sent")
                time.sleep(1)
            for attempt in range(1, 13):
                try:
                    chan = self._ensure_control()
                    self._stop_capture(chan); break
                except Exception as e:
                    self._set_ready(False)
                    if attempt >= 12:
                        raise
                    self.log.emit(f"[SBCM] stop command failed, reconnecting {attempt}/12: {e}")
                    chan = self._connect_control()
            self.log.emit("[SBCM] Capture stopped, waiting for flush..."); time.sleep(3)
            try:
                self._send_cmd(chan, "exit\n"); self._expect(chan, "Y/N")
                self._send_cmd(chan, "Y\n", "exit confirm Y"); time.sleep(2)
                self._recv_all(chan)
            except Exception as e:
                self.log.emit(f"[SBCM] exit diagnose skipped: {e}")
            self._close_control()
            self.log.emit("[SBCM] Locating pdump folder")
            remote_folder = ""
            for retry in range(10):
                out, _ = self._ssh_exec_retry("ls -td /mnt/hfs1/PROGRAM/pdump/pdump* 2>/dev/null | head -1")
                remote_folder = out.strip()
                if remote_folder:
                    oc, _ = self._ssh_exec_retry(f"ls -A {remote_folder} 2>/dev/null | head -5")
                    if oc: break
                time.sleep(2)
            if not remote_folder: raise RuntimeError("SBCM: pdump folder not found!")
            folder_name = remote_folder.rstrip("/").split("/")[-1]
            remote_tar = f"/opt/tar/{folder_name}.tar.gz"
            self.log.emit(f"[SBCM] Packing {remote_folder}")
            o2, _ = self._ssh_exec_retry(f"tar czf {remote_tar} -C /mnt/hfs1/PROGRAM/pdump {folder_name} && stat --format=%s {remote_tar}", timeout=120)
            if not o2 or o2=="0": raise RuntimeError(f"SBCM: packed file empty! ({remote_tar})")
            self.log.emit(f"[SBCM] Packed size: {o2} bytes")
            lp = self.local_path+".tar.gz"
            self.log.emit(f"[SBCM] Downloading {remote_tar} -> {lp}")
            self._download_retry(remote_tar, lp)
            self._ssh_exec_retry(f"rm -f {remote_tar}")
            self.progress.emit(100); self.log.emit(f"[done] {lp}"); self.done.emit(lp)
        except Exception as e:
            emsg = str(e); self.log.emit(f"[error] {emsg}"); self.error.emit(emsg); logger.exception("SBCMCaptureWorker error")
        finally:
            self._close_control()

# ═══════════════════════════════════════════════
#  Upgrade Workers (from IMS_NE_Upgrade)
# ═══════════════════════════════════════════════

class SSHWorker(QThread):
    log_signal = Signal(str); step_signal = Signal(str); finished_signal = Signal(str)
    config_diff_signal = Signal(list); kill_residual_signal = Signal(list, str)

    def __init__(self, host, port, username, password, ne_config, patch_local, parent=None):
        super().__init__(parent)
        self.host = host; self.port = port; self.username = username; self.password = password
        self.ne = ne_config; self.patch_local = patch_local
        self.sftp = None; self.ssh = None; self._stopped = False; self._kill_continue = None

    def stop(self): self._stopped = True
    def _log(self, msg): self.log_signal.emit(msg)
    def _step(self, msg): self.step_signal.emit(msg)
    def set_config_diff_result(self, r): self._config_diff_result = r
    def set_kill_decision(self, d): self._kill_continue = d
    def _patch_files(self):
        if isinstance(self.patch_local, (list, tuple)):
            return list(self.patch_local)
        return [self.patch_local]

    def _ensure_remote_dir(self, remote_dir):
        self._exec(f"mkdir -p {_shell_quote(remote_dir)}")

    def _upload_file(self, local_path, remote_path):
        self._ensure_remote_dir(posixpath.dirname(remote_path))
        remote_name = os.path.basename(local_path)
        self._log(f"Uploading {remote_name} -> {remote_path} ...")
        start = time.time()
        last_pct = [0]
        def progress(transferred, total):
            if self._stopped:
                raise Exception("stopped")
            if total:
                pct = int(transferred / total * 100)
                if pct >= last_pct[0] + 10 or pct == 100:
                    elapsed = max(time.time() - start, 0.001)
                    speed = transferred / elapsed / 1024
                    self._log(f"  [{pct:3d}%] {self._fmt_size(transferred)}/{self._fmt_size(total)} {speed:.0f}KB/s")
                    last_pct[0] = pct
        self.sftp.put(local_path, remote_path, callback=progress)
        self._check_remote_path(remote_path, "uploaded patch")
        self._log(f"Upload done ({time.time() - start:.1f}s)")

    def _upload_dir(self, local_dir, remote_dir):
        folder_name = os.path.basename(os.path.normpath(local_dir))
        remote_parent = posixpath.dirname(remote_dir.rstrip("/"))
        archive_name = f".{folder_name}_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        remote_archive = posixpath.join(remote_parent, archive_name)
        local_archive = None
        self._log(f"Packing folder {folder_name} locally ...")
        try:
            with tempfile.NamedTemporaryFile(prefix=f"{folder_name}_", suffix=".tar.gz", delete=False) as tmp:
                local_archive = tmp.name
            with tarfile.open(local_archive, "w:gz") as tar:
                tar.add(local_dir, arcname=folder_name)
            self._log(f"Packed {folder_name}: {self._fmt_size(os.path.getsize(local_archive))}")
            self._upload_file(local_archive, remote_archive)
            if self._stopped:
                return
            self._log(f"Extracting {remote_archive} -> {remote_parent} ...")
            rc, _, _ = self._exec(
                f"rm -rf {_shell_quote(remote_dir)} && tar -xzf {_shell_quote(remote_archive)} -C {_shell_quote(remote_parent)} && rm -f {_shell_quote(remote_archive)}",
                timeout=300,
                user=self.ne["patch"].get("extract_user", "root")
            )
            if rc != 0:
                raise RuntimeError(f"remote folder extract failed rc={rc}")
            self._check_remote_path(remote_dir, "uploaded patch folder")
            self._log(f"Folder upload done: {remote_dir}")
        finally:
            if local_archive and os.path.exists(local_archive):
                try:
                    os.remove(local_archive)
                except Exception as e:
                    self._log(f"  [warn] failed removing local temp archive: {e}")

    def _exec(self, cmd, timeout=60, user=None, input_str=None):
        full_cmd = cmd
        if user and user != self.username:
            escaped = cmd.replace("'","'\"'\"'")
            full_cmd = f"su - {user} -c '{escaped}'"
        self._log(f"> {full_cmd}")
        stdin, stdout, stderr = self.ssh.exec_command(full_cmd, timeout=timeout)
        if input_str:
            self._log(f"  <<< send input: {input_str.strip()}")
            stdin.write(input_str); stdin.flush(); stdin.channel.shutdown_write()
        return self._read_result(stdin, stdout, stderr, timeout)

    def _exec_bg(self, cmd, user=None):
        full_cmd = cmd
        if user and user != self.username:
            escaped = cmd.replace("'","'\"'\"'")
            full_cmd = f"su - {user} -c '{escaped}'"
        self._log(f"> {full_cmd}")
        stdin, stdout, stderr = self.ssh.exec_command(full_cmd, timeout=5)
        stdin.close(); time.sleep(1)
        try: stdout.channel.close()
        except: pass
        try: stderr.channel.close()
        except: pass
        return 0, "", ""

    def _read_result(self, stdin, stdout, stderr, timeout):
        try: out = stdout.read().decode("utf-8",errors="replace").strip()
        except: out = ""
        try: err = stderr.read().decode("utf-8",errors="replace").strip()
        except: err = ""
        try: rc = stdout.channel.recv_exit_status()
        except: rc = -1
        if out:
            for l in out.split("\n"): self._log(f"  {l}")
        if err:
            for l in err.split("\n"): self._log(f"  ! {l}")
        return rc, out, err

    def _exec_script_user(self, user, commands, inputs=None):
        self._log(f"> [{user}] exec {len(commands)} commands")
        cwd = None
        for i, cmd in enumerate(commands):
            if self._stopped: return
            if cmd.startswith("WAIT"):
                sec = int(cmd.split()[1])
                for s in range(sec,0,-1):
                    if self._stopped: return
                    time.sleep(1)
                continue
            if cmd.startswith("cd "):
                cwd = cmd[3:].strip().strip('"').strip("'"); continue
            actual_cmd = cmd
            if cwd: actual_cmd = f"cd {cwd} && {cmd}"
            inp = inputs.get(str(i)) if inputs else None
            if actual_cmd.strip().endswith("&"):
                bg = actual_cmd.rstrip()[:-1].rstrip()+" </dev/null >>nohup.out 2>&1 &"
                rc, out, err = self._exec_bg(bg, user=user)
            else:
                rc, out, err = self._exec(actual_cmd, user=user, input_str=inp)
            if rc != 0: self._log(f"  ⚠ rc={rc}")
            else: self._log(f"  ✓ rc={rc}")

    def _check_remote_path(self, path, path_type="path"):
        qpath = _shell_quote(path)
        rc, out, _ = self._exec(f"ls -d {qpath} 2>/dev/null && echo EXISTS || echo NOTEXISTS")
        if out.strip().splitlines()[-1:] == ["EXISTS"]:
            self._exec(f"stat --format='%F size:%s bytes modified:%y' {qpath} 2>/dev/null || file {qpath}")
            return True
        self._log(f"  [warn] {path_type} not found: {path}")
        return False

    def _fmt_size(self, b):
        for u in ("B","KB","MB","GB"):
            if b<1024: return f"{b:.1f}{u}"
            b/=1024
        return f"{b:.1f}TB"

    def run(self):
        try:
            self._log("═"*50); self._log(f"IMS NE Upgrade Start"); self._log(f"Target: {self.host}:{self.port}")
            self._log(f"NE: {self.ne.get('description','?')}")
            for patch_file in self._patch_files():
                self._log(f"Patch: {os.path.basename(patch_file)} ({self._fmt_size(os.path.getsize(patch_file))})")
            self._log("═"*50)
            self._log(f"Connecting {self.host}:{self.port} ...")
            self.ssh = paramiko.SSHClient(); self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(self.host, port=self.port, username=self.username, password=self.password, timeout=15)
            self._log("✓ SSH connected"); self.sftp = self.ssh.open_sftp(); self._log("✓ SFTP opened")
            steps = [("stop",self._do_stop),("backup",self._do_backup),("upload",self._do_upload),
                     ("extract",self._do_extract),("post_extract",self._do_post_extract),
                     ("config_diff",self._do_config_diff),("chown",self._do_chown),
                     ("license",self._do_license),("start",self._do_start),
                     ("cleanup",self._do_cleanup_uploads)]
            for sk, sf in steps:
                if self._stopped: break
                self._step(sk); sf(); self._log("")
            if not self._stopped:
                self._log("═"*50); self._log("✓ All steps completed"); self._log("═"*50)
                self.finished_signal.emit("success")
            else: self.finished_signal.emit("stopped")
        except paramiko.AuthenticationException:
            self._log("✗ Auth failed"); self.finished_signal.emit("error")
        except Exception as e:
            self._log(f"✗ {e}"); import traceback; self._log(traceback.format_exc()); self.finished_signal.emit("error")
        finally:
            if self.sftp:
                try: self.sftp.close()
                except Exception as e: self._log(f"[warn] SFTP close failed: {e}")
            if self.ssh:
                try: self.ssh.close()
                except Exception as e: self._log(f"[warn] SSH close failed: {e}")

    def _do_stop(self):
        cfg = self.ne["stop"]; self._log("━━━ Step 1/9: Stop ━━━")
        if not cfg.get("commands") and not cfg.get("process_names"): return
        if cfg["method"]=="script":
            self._exec_script_user(cfg["user"], cfg["commands"], inputs=cfg.get("inputs"))
        elif cfg["method"]=="kill":
            for pname in cfg.get("process_names",[]):
                if self._stopped: return
                rc, out, _ = self._exec(f"ps -ef | grep '{pname}' | grep -v grep")
                lines = [l.strip() for l in out.split("\n") if l.strip()]
                if not lines: continue
                pids = []
                for l in lines:
                    parts = l.split(); pid = parts[1] if len(parts)>=2 else "?"
                    if pid!="?": pids.append(pid)
                if pids:
                    self._exec(f"kill -9 {' '.join(pids)}"); time.sleep(2)
                    rc2, out2, _ = self._exec(f"ps -ef | grep '{pname}' | grep -v grep")
                    remaining = [l.strip() for l in out2.split("\n") if l.strip()]
                    if remaining:
                        self.kill_residual_signal.emit(remaining, pname)
                        self._kill_continue = None
                        while self._kill_continue is None and not self._stopped: time.sleep(0.1)
                        if self._stopped or not self._kill_continue: return
        self._log("✓ Step 1 done")

    def _do_backup(self):
        cfg = self.ne["backup"]; self._log("━━━ Step 2/9: Backup ━━━")
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S"); self._backup_map = {}
        for item in cfg["items"]:
            if self._stopped: return
            src = posixpath.join(cfg["base_dir"], item["source"])
            backup_name = item["source"]+item["backup_suffix"].replace("{date}",date_str)
            dst = posixpath.join(cfg["base_dir"], backup_name)
            bu = item.get("user") or cfg["user"]
            self._log(f"  backup {src} -> {dst} as {bu}")
            if not self._check_remote_path(src, "backup source"):
                continue
            rc, _, _ = self._exec(f"cp -r {_shell_quote(src)} {_shell_quote(dst)}", timeout=120, user=bu)
            if rc==0 and item.get("remove_source",False):
                self._exec(f"rm -rf {_shell_quote(src)}", timeout=60, user="root")
            if rc == 0:
                self._check_remote_path(dst, "backup target")
            self._backup_map[item["source"]] = {"src":src,"dst":dst}
        self._log("✓ Step 2 done")

    def _do_upload(self):
        self._log("Step 3/9: Upload")
        tar_path = self.ne["patch"].get("tar_path", "/opt/tar")
        self._exec(f"mkdir -p {_shell_quote(tar_path)}")
        self._uploaded_paths = []
        for patch_file in self._patch_files():
            if self._stopped:
                return
            remote_name = os.path.basename(patch_file)
            remote_path = posixpath.join(tar_path, remote_name)
            if os.path.isdir(patch_file):
                self._upload_dir(patch_file, remote_path)
            else:
                self._upload_file(patch_file, remote_path)
            self._uploaded_paths.append(remote_path)
        self._uploaded_path = self._uploaded_paths[0] if self._uploaded_paths else ""
        post_upload = self.ne["patch"].get("post_upload")
        if post_upload and not self._stopped:
            self._log("Post upload commands...")
            self._exec_script_user(post_upload.get("user", "root"), post_upload.get("commands", []))
        self._log("Step 3 done")

    def _do_extract(self):
        self._log("Step 4/9: Extract")
        if self.ne["patch"].get("extract") is False:
            self._log("  skip extract by patch config")
            return
        user = self.ne["patch"]["extract_user"]
        self._check_remote_path(self._uploaded_path, "uploaded patch")
        rc, _, _ = self._exec(f"cd /opt/tar && tar -xzf {_shell_quote(self._uploaded_path)} -C /", timeout=180, user=user)
        if rc != 0:
            raise RuntimeError(f"tar extract failed rc={rc}")
        self._log("Step 4 done")

    def _do_post_extract(self):
        cfg = self.ne.get("post_extract"); self._log("━━━ Step 5/9: Post Extract ━━━")
        if not cfg: self._log("  skip"); return
        self._exec_script_user(cfg["user"], cfg["commands"]); self._log("✓ Step 5 done")

    def _do_config_diff(self):
        self._log("━━━ Step 6/9: Config Diff ━━━")
        config_files = self.ne.get("config_files",[])
        if not config_files: return
        base_dir = self.ne["backup"]["base_dir"]; file_items = []
        for cf in config_files:
            if self._stopped: return
            old_path = ""
            for sk, info in self._backup_map.items():
                sp = posixpath.join(base_dir, sk)
                if cf==sp or cf.startswith(sp+"/"): old_path = cf.replace(sp, info["dst"], 1); break
            if not old_path: continue
            old_found = True; new_found = True
            try:
                with self.sftp.open(old_path,"r") as f: old_c = f.read().decode("utf-8",errors="replace")
            except:
                old_c = ""; old_found = False
            try:
                with self.sftp.open(cf,"r") as f: new_c = f.read().decode("utf-8",errors="replace")
            except:
                new_c = ""; new_found = False
            if not new_found:
                self._log(f"  [warn] new config not found, skip: {cf}")
                continue
            if not old_found:
                self._log(f"  [warn] backup config not found, keep new config: {old_path}")
                file_items.append({"path":cf,"old_content":"","new_content":new_c,"hunks":[],"skip_diff":True})
                continue
            ol = old_c.splitlines(True); nl = new_c.splitlines(True)
            diff = list(difflib.unified_diff(ol, nl, fromfile="old", tofile="new", lineterm=""))
            hunks = self._parse_hunks(diff)
            file_items.append({"path":cf,"old_content":old_c,"new_content":new_c,"hunks":hunks})
        if not file_items: return
        skip_items = [it for it in file_items if it.get("skip_diff")]
        diff_items = [it for it in file_items if not it.get("skip_diff")]
        results = [{"path": it["path"], "merged_content": it["new_content"]} for it in skip_items]
        if diff_items:
            self.config_diff_signal.emit(diff_items)
            self._config_diff_result = None
            while self._config_diff_result is None and not self._stopped: time.sleep(0.1)
            if self._config_diff_result:
                results.extend(self._config_diff_result)
        if self._stopped: return
        for r in results:
            try:
                with self.sftp.open(r["path"],"w") as f: f.write(r["merged_content"])
                self._log(f"  wrote merged config: {r['path']}")
            except Exception as e:
                self._log(f"  [warn] failed writing {r['path']}: {e}")
        self._log("✓ Step 6 done")

    def _parse_hunks(self, diff_lines):
        hunks = []; cur = None
        for line in diff_lines:
            if line.startswith("@@"):
                if cur: hunks.append(cur)
                m = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@(.*)', line)
                cur = {"old_start":int(m.group(1)) if m else 0,"new_start":int(m.group(3)) if m else 0,
                       "section":m.group(5).strip() if m and m.group(5) else "","old_lines":[],"new_lines":[],"lines":[]}
            elif line.startswith("---") or line.startswith("+++"): continue
            elif cur:
                cur["lines"].append(line)
                if line.startswith("-"): cur["old_lines"].append(line[1:])
                elif line.startswith("+"): cur["new_lines"].append(line[1:])
                else: cur["old_lines"].append(line[1:]); cur["new_lines"].append(line[1:])
        if cur: hunks.append(cur)
        return hunks

    def _do_chown(self):
        cfg = self.ne.get("chown"); self._log("━━━ Step 7/9: Chown ━━━")
        if not cfg: return
        for p in cfg["paths"]:
            if self._stopped: return
            rc, _, _ = self._exec(f"chown {cfg['user']}:{cfg['group']} {_shell_quote(p)}", user="root")
            if rc == 0:
                self._exec(f"ls -l {_shell_quote(p)} | awk '{{print $3\":\"$4}}'")
        self._log("✓ Step 7 done")

    def _do_license(self):
        cfg = self.ne.get("license",{}); self._log("━━━ Step 8/9: License ━━━")
        if not cfg.get("has_license"): return
        lp = cfg["file_path"]; base_dir = self.ne["backup"]["base_dir"]; old_lp = ""
        for sk, info in self._backup_map.items():
            sp = posixpath.join(base_dir, sk)
            if lp.startswith(sp+"/") or lp==sp: old_lp = lp.replace(sp, info["dst"], 1); break
        self._check_remote_path(lp, "license")
        if old_lp and self._check_remote_path(old_lp, "backup license"):
            self._exec(f"cp {_shell_quote(old_lp)} {_shell_quote(lp)}", user=cfg.get("user","root"))
            self._check_remote_path(lp, "restored license")
        elif not old_lp:
            self._log("  [warn] no matching license path found in backup map")
        self._log("✓ Step 8 done")

    def _do_start(self):
        cfg = self.ne["start"]; self._log("━━━ Step 9/9: Start ━━━")
        self._exec_script_user(cfg["user"], cfg["commands"])
        ck = cfg.get("check")
        if ck:
            time.sleep(ck.get("wait",0))
            rc, out, _ = self._exec(ck["command"], user=cfg["user"])
            if rc==0 and ck.get("expected","") in out: self._log("✓ Start OK")
            else: self._log("⚠ Start check failed")
        self._log("✓ Step 9 done")

    def _do_cleanup_uploads(self):
        patch_cfg = self.ne.get("patch", {})
        if not patch_cfg.get("cleanup_uploaded"):
            return
        paths = getattr(self, "_uploaded_paths", [])
        if not paths:
            self._log("Cleanup uploaded patches: no uploaded paths")
            return
        self._log("Cleanup uploaded patches")
        cleanup_user = patch_cfg.get("cleanup_user", "root")
        for remote_path in paths:
            if self._stopped:
                return
            rc, _, _ = self._exec(f"rm -f {_shell_quote(remote_path)}", user=cleanup_user)
            if rc == 0:
                self._log(f"  removed {remote_path}")
            else:
                self._log(f"  [warn] failed removing {remote_path} rc={rc}")


# ═══════════════════════════════════════════════
#  Log Viewer Workers (from LogViewer)
# ═══════════════════════════════════════════════

class LogListWorker(QThread):
    log = Signal(str); file_info = Signal(dict); finished = Signal(); error = Signal(str)
    def __init__(self, host, port, user, pwd, ne_config):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd; self.ne = ne_config

    @staticmethod
    def _group_files(file_list):
        groups = defaultdict(list)
        for fp in file_list:
            clean_fp = fp.rstrip("/")
            bn = posixpath.basename(clean_fp)
            dn = posixpath.dirname(clean_fp)
            if '.' in bn:
                name, ext = bn.rsplit('.', 1); ext = '.' + ext
            else:
                name = bn; ext = ''
            stem = re.sub(r'\d+$', '', name)
            if not stem: stem = name
            groups[(dn, stem, ext)].append(fp)
        return groups

    def _exec(self, c, cmd):
        stdin, stdout, stderr = c.exec_command(cmd, timeout=15)
        return stdout.read().decode("utf-8",errors="replace"), stderr.read().decode("utf-8",errors="replace")

    def run(self):
        try:
            c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(self.host, self.port, self.user, self.pwd, timeout=10)
            def _resolve_entry(entry):
                if isinstance(entry, dict): return entry["path"], entry.get("desc","")
                return str(entry), ""

            for entry in self.ne.get("files", []):
                fpath, desc = _resolve_entry(entry)
                if '*' in fpath or '?' in fpath:
                    out, _ = self._exec(c, f"ls -1 {fpath} 2>/dev/null || echo MISSING")
                    if out and out.strip() != "MISSING":
                        matches = [l.strip() for l in out.split("\n") if l.strip()]
                        groups = self._group_files(matches)
                        for (gdir, stem, ext), files in sorted(groups.items()):
                            first_name = posixpath.basename(files[0].rstrip("/"))
                            pattern = f"{stem}*{ext}" if stem != first_name else first_name
                            self.file_info.emit({
                                "path": gdir, "name": pattern, "size": len(files),
                                "type": "group", "group_files": sorted(files),
                                "pattern_path": f"{gdir}/{pattern}", "desc": desc
                            })
                    else:
                        name = posixpath.basename(fpath.rstrip("/")) or fpath
                        self.file_info.emit({"path": fpath, "name": name, "size": 0, "type": "file", "missing": True, "desc": desc})
                else:
                    qpath = _shell_quote(fpath)
                    name = posixpath.basename(fpath.rstrip("/")) or fpath
                    out, _ = self._exec(c, f"stat --format='%s' {qpath} 2>/dev/null || echo MISSING")
                    if out and out.strip() != "MISSING":
                        try: sz = int(out.strip().split("\n")[0])
                        except: sz = 0
                        self.file_info.emit({"path": fpath, "name": name, "size": sz, "type": "file", "desc": desc})
                    else:
                        self.file_info.emit({"path": fpath, "name": name, "size": 0, "type": "file", "missing": True, "desc": desc})

            for entry in self.ne.get("directories", []):
                dpath, desc = _resolve_entry(entry)
                qpath = _shell_quote(dpath.rstrip("/") or "/")
                name = posixpath.basename(dpath.rstrip("/")) or dpath.rstrip("/") or "/"
                out, _ = self._exec(c, f"test -d {qpath} && echo OK || echo MISSING")
                if out and out.strip() == "OK":
                    self.file_info.emit({"path": dpath, "name": name + "/", "size": 0, "type": "directory", "desc": desc})
                else:
                    self.file_info.emit({"path": dpath, "name": name + "/", "size": 0, "type": "directory", "missing": True, "desc": desc})

            c.close()
            self.finished.emit()
        except Exception as e: self.error.emit(str(e))

class LogBrowseWorker(QThread):
    log = Signal(str); file_info = Signal(dict); finished = Signal(); error = Signal(str)
    def __init__(self, host, port, user, pwd, path):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd; self.path = path
    def run(self):
        try:
            c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(self.host, self.port, self.user, self.pwd, timeout=5)
            qpath = _shell_quote(self.path.rstrip("/"))
            stdin, stdout, stderr = c.exec_command(f"find {qpath} -maxdepth 1 -mindepth 1 -type d -print 2>/dev/null | sort | head -200")
            dirs = [line.strip() for line in stdout.read().decode("utf-8",errors="replace").split("\n") if line.strip()]
            for d in dirs:
                name = posixpath.basename(d.rstrip("/")) or d.rstrip("/") or "/"
                self.file_info.emit({"path": d, "name": name + "/", "size": 0, "type": "directory", "desc": ""})
            stdin, stdout, stderr = c.exec_command(f"find {qpath} -maxdepth 1 -mindepth 1 -type f -print 2>/dev/null | sort | head -500")
            files = [line.strip() for line in stdout.read().decode("utf-8",errors="replace").split("\n") if line.strip()]
            groups = LogListWorker._group_files(files)
            for (gdir, stem, ext), group_files in sorted(groups.items()):
                first_name = posixpath.basename(group_files[0].rstrip("/"))
                pattern = f"{stem}*{ext}" if stem != first_name else first_name
                self.file_info.emit({
                    "path": gdir, "name": pattern, "size": len(group_files),
                    "type": "group", "group_files": sorted(group_files),
                    "pattern_path": f"{gdir}/{pattern}", "desc": ""
                })
            c.close()
            self.finished.emit()
        except Exception as e: self.error.emit(str(e))

class LogViewerWorker(QThread):
    log = Signal(str); done = Signal()
    def __init__(self, host, port, user, pwd, remote_path, tail=False):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd
        self.remote_path = remote_path; self.tail = tail; self._stop = False
        self._ssh = None; self._chan = None
    def stop(self):
        self._stop = True
        try:
            if self._chan: self._chan.close()
        except: pass
        try:
            if self._ssh: self._ssh.close()
        except: pass
    def run(self):
        try:
            c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(self.host, self.port, self.user, self.pwd, timeout=5); self._ssh = c
            qpath = _shell_quote(self.remote_path)
            if self.tail:
                chan = c.get_transport().open_session()
                self._chan = chan
                chan.exec_command(f"tail -n 500 -f {qpath} 2>/dev/null")
                while not self._stop:
                    if chan.recv_ready():
                        data = chan.recv(4096).decode("utf-8",errors="replace")
                        for line in data.split("\n"):
                            if line.strip(): self.log.emit(line)
                    else: time.sleep(0.1)
                chan.close()
            else:
                stdin, stdout, stderr = c.exec_command(f"tail -200 {qpath} 2>/dev/null")
                out = stdout.read().decode("utf-8",errors="replace")
                for line in out.split("\n"):
                    if line.strip(): self.log.emit(line)
            c.close()
            self.done.emit()
        except Exception as e: self.log.emit(f"Error: {e}"); self.done.emit()

class LogDownloadWorker(QThread):
    log = Signal(str); progress = Signal(int); done = Signal(str); error = Signal(str)
    def __init__(self, host, port, user, pwd, files, save_dir):
        super().__init__()
        self.host = host; self.port = int(port); self.user = user; self.pwd = pwd
        self.files = files; self.save_dir = save_dir

    def _exec(self, c, cmd, timeout=None):
        _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err

    def _items(self):
        items = []
        used = {}
        for item in self.files:
            if isinstance(item, dict):
                rp = item.get("remote_path") or item.get("path") or ""
                name = item.get("filename") or os.path.basename(rp.rstrip("/"))
            else:
                rp = str(item)
                name = os.path.basename(rp.rstrip("/"))
            rp = rp.strip()
            name = (name or "download").strip().replace("/", "_").replace("\\", "_")
            if not rp:
                continue
            base, ext = os.path.splitext(name)
            idx = used.get(name, 0)
            used[name] = idx + 1
            if idx:
                name = f"{base}_{idx + 1}{ext}"
            items.append((rp, name))
        return items

    def _remote_is_dir(self, c, remote_path):
        rc, out, _ = self._exec(c, f"test -d {_shell_quote(remote_path)} && echo DIR || echo FILE", timeout=10)
        return rc == 0 and out.strip() == "DIR"

    def _safe_extract(self, archive_path):
        target = os.path.abspath(self.save_dir)
        with tarfile.open(archive_path, "r:gz") as tf:
            for member in tf.getmembers():
                member_path = os.path.abspath(os.path.join(target, member.name))
                if member_path != target and not member_path.startswith(target + os.sep):
                    raise RuntimeError(f"Unsafe archive member: {member.name}")
            tf.extractall(target)

    def _download_archive(self, c, items):
        batch_id = f"ims_log_dl_{int(time.time())}_{threading.get_ident()}"
        remote_dir = f"/tmp/{batch_id}"
        remote_archive = f"/tmp/{batch_id}.tar.gz"
        local_archive = None
        try:
            rc, _, err = self._exec(c, f"rm -rf {_shell_quote(remote_dir)} {_shell_quote(remote_archive)}; mkdir -p {_shell_quote(remote_dir)}", timeout=20)
            if rc != 0:
                raise RuntimeError(err.strip() or "Create remote temp directory failed")
            total = len(items)
            for idx, (rp, name) in enumerate(items, 1):
                link_path = posixpath.join(remote_dir, name)
                rc, _, err = self._exec(c, f"ln -s {_shell_quote(rp)} {_shell_quote(link_path)}", timeout=20)
                if rc != 0:
                    raise RuntimeError(err.strip() or f"Prepare remote file failed: {rp}")
                self.progress.emit(5 + int(idx / max(total, 1) * 20))
            self.log.emit(f"[download] packaging {total} item(s) on remote host")
            rc, _, err = self._exec(c, f"tar -C {_shell_quote(remote_dir)} -czhf {_shell_quote(remote_archive)} .", timeout=600)
            if rc != 0:
                raise RuntimeError(err.strip() or "Remote archive failed")
            self.progress.emit(45)
            fd, local_archive = tempfile.mkstemp(prefix="ims_logs_", suffix=".tar.gz", dir=self.save_dir)
            os.close(fd)
            self.log.emit(f"[download] {remote_archive} -> {local_archive}")
            sftp = c.open_sftp()
            try:
                sftp.get(remote_archive, local_archive)
            finally:
                sftp.close()
            self.progress.emit(80)
            self.log.emit(f"[download] extracting to {self.save_dir}")
            self._safe_extract(local_archive)
            self.progress.emit(95)
        finally:
            try:
                self._exec(c, f"rm -rf {_shell_quote(remote_dir)} {_shell_quote(remote_archive)}", timeout=20)
            except Exception:
                pass
            if local_archive and os.path.exists(local_archive):
                try: os.remove(local_archive)
                except Exception: pass

    def _download_single(self, c, remote_path, local_name):
        lp = os.path.join(self.save_dir, local_name)
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        self.log.emit(f"[download] {remote_path} -> {lp}")
        sftp = c.open_sftp()
        try:
            sftp.get(remote_path, lp)
        finally:
            sftp.close()
        self.progress.emit(100)

    def run(self):
        c = None
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            items = self._items()
            if not items:
                self.done.emit("No files to download")
                return
            c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(self.host, self.port, self.user, self.pwd, timeout=10)
            self.progress.emit(3)
            if len(items) == 1 and not self._remote_is_dir(c, items[0][0]):
                self._download_single(c, items[0][0], items[0][1])
            else:
                self._download_archive(c, items)
                self.progress.emit(100)
            self.done.emit(f"Done ({len(items)} item{'s' if len(items) != 1 else ''})")
        except Exception as e: self.error.emit(str(e))
        finally:
            try:
                if c: c.close()
            except Exception:
                pass

class NEServiceWorker(QThread):
    log = Signal(str); service_finished = Signal(bool, str)
    def __init__(self, host, port, ssh_user, ssh_pwd, exec_user, method, commands, inputs, process_names, ne_type, action):
        super().__init__()
        self.host = host; self.port = int(port); self.ssh_user = ssh_user; self.ssh_pwd = ssh_pwd
        self.exec_user = exec_user; self.method = method; self.commands = commands; self.inputs = inputs
        self.process_names = process_names; self.ne_type = ne_type; self.action = action
        self._stop = False
    def stop(self): self._stop = True
    def run(self):
        try:
            c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(self.host, self.port, self.ssh_user, self.ssh_pwd, timeout=10)
            if self.method == "kill":
                for pn in self.process_names:
                    out = self._exec(c, f"ps -ef | grep '{pn}' | grep -v grep")
                    pids = []
                    for l in out.split("\n"):
                        parts = l.strip().split()
                        if len(parts) >= 2:
                            pids.append(parts[1])
                    if pids:
                        self._exec(c, f"kill -9 {' '.join(pids)}")
                        time.sleep(1)
                        self._exec(c, f"ps -ef | grep '{pn}' | grep -v grep | awk '{{print $2}}' | xargs -r kill -9 2>/dev/null; echo done")
            else:
                cwd = None
                for i, cmd in enumerate(self.commands):
                    if self._stop: break
                    if cmd.startswith("WAIT "):
                        sec = int(cmd.split()[1])
                        self.log.emit(f"  (wait {sec}s)")
                        time.sleep(sec)
                        continue
                    if cmd.startswith("cd "):
                        cwd = cmd[3:].strip()
                        self.log.emit(f"  (cd {cwd})")
                        continue
                    inp = self.inputs.get(str(i+1)) if self.inputs else None
                    actual = f"cd {cwd} && {cmd}" if cwd else cmd
                    if actual.strip().endswith("&"):
                        bg = actual.rstrip()[:-1].rstrip() + " </dev/null >>nohup.out 2>&1 &"
                        if self.exec_user and self.exec_user != self.ssh_user:
                            escaped = bg.replace("'","'\"'\"'")
                            bg = f"su - {self.exec_user} -c '{escaped}'"
                        self.log.emit(f"> {bg}")
                        c.exec_command(bg)
                    else:
                        self._exec(c, actual, inp)
            c.close()
            self.service_finished.emit(True, f"{self.ne_type} {self.action} completed")
        except Exception as e:
            self.service_finished.emit(False, str(e))
    def _exec(self, c, cmd, input_str=None):
        full_cmd = cmd
        if self.exec_user and self.exec_user != self.ssh_user:
            escaped = cmd.replace("'","'\"'\"'")
            full_cmd = f"su - {self.exec_user} -c '{escaped}'"
        self.log.emit(f"> {full_cmd}")
        stdin, stdout, stderr = c.exec_command(full_cmd, timeout=60)
        if input_str:
            stdin.write(input_str); stdin.flush(); stdin.channel.shutdown_write()
        try:
            out = stdout.read().decode("utf-8",errors="replace").strip()
            err = stderr.read().decode("utf-8",errors="replace").strip()
        except: out = ""; err = ""
        for l in out.split("\n"):
            if l.strip(): self.log.emit(f"  {l.strip()}")
        for l in err.split("\n"):
            if l.strip(): self.log.emit(f"  ! {l.strip()}")
        return out

# ═══════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    w = IMSTool()
    w.show()
    sys.exit(app.exec())
