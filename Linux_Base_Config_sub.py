# -*- coding: utf-8 -*-
"""
远程多主机系统初始化配置工具 v3.2.7
支持: Kylin / RedHat / CentOS
功能: 批量导入服务器列表，一键远程执行安全加固与服务初始化
"""

import sys, os, subprocess, re, socket, json, base64
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QFrame, QMessageBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFileDialog, QAbstractItemView, QDialog, QMenu,
    QStyle, QStyleOptionButton,
)
from PySide6.QtCore import Qt, QThread, Signal, QRect
from PySide6.QtGui import QColor, QPainter, QFont

STYLE_BTN_PRIMARY = """
    QPushButton { background: #0984e3; color: white; border: none; padding: 10px 24px; border-radius: 4px; font-size: 13px; }
    QPushButton:hover { background: #0873c4; }
    QPushButton:disabled { background: #b2bec3; }
"""
STYLE_BTN_SECONDARY = """
    QPushButton { background: #f0f3f5; color: #5b7a9a; border: 1px solid #c8d0d8; padding: 8px 16px; border-radius: 4px; font-size: 12px; }
    QPushButton:hover { background: #e4e8ec; }
"""
STYLE_BTN_DANGER = """
    QPushButton { background: #d63031; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-size: 12px; }
    QPushButton:hover { background: #b3292a; }
    QPushButton:disabled { background: #b2bec3; color: #dfe6e9; }
"""

TASK_META = {
    "firewall": "🛡防火墙",
    "selinux":  "🛡SELinux",
    "sshd_dns": "🚀SSHD",
    "rc_local": "⚙rc.local",
    "ntp_off":  "⏱旧NTP",
    "chrony":   "⏱Chrony",
    "ftp":      "📦FTP",
    "telnet":   "📦Telnet",
    "python2":  "🐍Python2",
    "gdb":      "🔧GDB",
}

# 需要 YUM 的任务代码集合（始终选中，左侧不显示复选框）
YUM_TASKS_SET = {"chrony", "ftp", "telnet", "python2", "gdb"}
YUM_TASKS = ["chrony", "ftp", "telnet", "python2", "gdb"]

# ── SSH 工作线程 ─────────────────────────────────────────────
class SSHWorker(QThread):
    log = Signal(str)                    # 日志
    task_status = Signal(int, int, str)  # (row, task_idx, icon)
    os_detected = Signal(int, str)       # (row, os_version)
    yum_status = Signal(int, str)        # (row, status_text)  ✅正常 ❌不可用
    worker_done = Signal(int, bool)      # (row, all_success)

    def __init__(self, host, port, user, pwd, tasks, row, has_yum, yum_ok=None):
        super().__init__()
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd
        self.tasks = tasks       # [(cmd, desc, tidx, tcode), ...]
        self.row = row
        self.has_yum = has_yum
        self._yum_ok = yum_ok if yum_ok is not None else True
        self._prechecked = yum_ok is not None
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        import paramiko
        client = None
        all_ok = True
        try:
            self.log.emit(f"🔌 [{self.host}] 正在连接 SSH...")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.host, port=self.port, username=self.user,
                           password=self.pwd, timeout=15)
            self.log.emit(f"✅ [{self.host}] SSH 连接成功")

            # OS 检测
            stdin, stdout, stderr = client.exec_command(
                "grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null || echo Unknown", timeout=10)
            os_line = stdout.read().decode().strip()
            os_name = os_line.replace('PRETTY_NAME=', '').strip('"')
            self.os_detected.emit(self.row, os_name)

            # ── YUM 源预检 ──
            if self.has_yum and not self._prechecked:
                self.log.emit(f"🗄 [{self.host}] 正在检测 YUM 源可用性...")
                self.yum_status.emit(self.row, "🔄")
                cmd = "timeout 20 yum repolist enabled 2>&1"
                stdin, stdout, stderr = client.exec_command(cmd, timeout=25)
                out = stdout.read().decode()
                rc = stdout.channel.recv_exit_status() if hasattr(stdout, 'channel') else -1

                if "repolist: 0" in out:
                    self.log.emit(f"❌ [{self.host}] 无可用 YUM 仓库")
                    self.yum_status.emit(self.row, "❌")
                    self._yum_ok = False
                elif any(x in out for x in ["Failed","Cannot find","Could not resolve","Errno"]):
                    self.log.emit(f"⚠️ [{self.host}] YUM 源异常")
                    self.yum_status.emit(self.row, "⚠️")
                    self._yum_ok = False
                elif rc == 0:
                    self.log.emit(f"✅ [{self.host}] YUM 源正常")
                    self.yum_status.emit(self.row, "✅")
                    self._yum_ok = True
                else:
                    self.log.emit(f"❌ [{self.host}] YUM 源异常 (timeout / rc={rc})")
                    self.yum_status.emit(self.row, "❌")
                    self._yum_ok = False
            elif self.has_yum and self._prechecked:
                self.log.emit(f"🗄 [{self.host}] YUM 预检已完成 ({'✅' if self._yum_ok else '❌'})")

            # ── 逐项执行任务 ──
            # 统计唯一任务数
            unique_tcodes = []
            for _, _, _, tc in self.tasks:
                if tc not in unique_tcodes:
                    unique_tcodes.append(tc)
            total_unique = len(unique_tcodes)
            prev_tcode = None
            task_counter = 0
            for cmd, desc, tidx, tcode in self.tasks:
                if self._stopped:
                    self.log.emit(f"⏹ [{self.host}] 已停止")
                    self.task_status.emit(self.row, tidx, "⏹")
                    all_ok = False
                    break

                # YUM 不可用时跳过需要 YUM 的任务
                if tcode in YUM_TASKS_SET and not self._yum_ok:
                    if tcode != prev_tcode:
                        task_counter += 1
                        task_name = TASK_META.get(tcode, tcode)
                        self.log.emit(f"\n━━━ 任务 {task_counter}/{total_unique}: {task_name} ━━━")
                        prev_tcode = tcode
                    self.log.emit(f"⏹ [{self.host}] 跳过 {desc} (YUM 不可用)")
                    self.task_status.emit(self.row, tidx, "⏹")
                    continue

                # 新任务组分隔
                if tcode != prev_tcode:
                    task_counter += 1
                    task_name = TASK_META.get(tcode, tcode)
                    self.log.emit(f"\n━━━ 任务 {task_counter}/{total_unique}: {task_name} ━━━")
                    prev_tcode = tcode

                self.task_status.emit(self.row, tidx, "🔄")
                self.log.emit(f"▶ [{self.host}] {desc}")

                if callable(cmd):
                    try:
                        cmd(self.log, self.host)
                        self.task_status.emit(self.row, tidx, "✅")
                    except Exception as e:
                        self.log.emit(f"  ✖ {e}")
                        self.task_status.emit(self.row, tidx, "❌")
                        all_ok = False
                else:
                    self.log.emit(f"  $ {cmd}")
                    stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
                    out_text = stdout.read().decode()
                    for line in out_text.splitlines():
                        if line.strip():
                            self.log.emit(f"  {line.strip()}")
                    err_text = stderr.read().decode().strip()
                    if err_text:
                        self.log.emit(f"  ⚠ {err_text[:200]}")
                    rc2 = stdout.channel.recv_exit_status() if hasattr(stdout, 'channel') else 0
                    if rc2 == 0:
                        self.task_status.emit(self.row, tidx, "✅")
                    else:
                        self.log.emit(f"  ⚠ 退出码 {rc2}")
                        self.task_status.emit(self.row, tidx, "❌")
                        all_ok = False

            client.close()
            self.log.emit(f"✅ [{self.host}] 全部任务执行完毕")
            self.worker_done.emit(self.row, all_ok)

        except paramiko.AuthenticationException:
            self.log.emit(f"❌ [{self.host}] 认证失败")
            all_ok = False
        except paramiko.SSHException as e:
            self.log.emit(f"❌ [{self.host}] SSH 异常: {e}")
            all_ok = False
        except Exception as e:
            self.log.emit(f"❌ [{self.host}] 连接失败: {e}")
            all_ok = False
        finally:
            if client:
                client.close()
            self.worker_done.emit(self.row, all_ok)

# ── YUM 预检工作线程 ─────────────────────────────────────────
class YumPrecheckWorker(QThread):
    log = Signal(str)
    yum_status = Signal(int, str)   # (row, icon)
    worker_done = Signal(int, bool)  # (row, yum_ok)

    def __init__(self, host, port, user, pwd, row):
        super().__init__()
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd
        self.row = row
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        import paramiko
        client = None
        ok = True
        try:
            self.log.emit(f"🗄 [{self.host}] YUM 预检: 正在连接...")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.host, port=self.port, username=self.user,
                           password=self.pwd, timeout=15)
            self.log.emit(f"✅ [{self.host}] YUM 预检: 连接成功")

            self.yum_status.emit(self.row, "🔄")
            cmd = "timeout 20 yum repolist enabled 2>&1"
            stdin, stdout, stderr = client.exec_command(cmd, timeout=25)
            out = stdout.read().decode()
            rc = stdout.channel.recv_exit_status() if hasattr(stdout, 'channel') else -1

            if "repolist: 0" in out:
                self.log.emit(f"❌ [{self.host}] 无可用 YUM 仓库")
                self.yum_status.emit(self.row, "❌")
                ok = False
            elif any(x in out for x in ["Failed","Cannot find","Could not resolve","Errno"]):
                self.log.emit(f"⚠️ [{self.host}] YUM 源异常")
                self.yum_status.emit(self.row, "⚠️")
                ok = False
            elif rc == 0:
                self.log.emit(f"✅ [{self.host}] YUM 源正常")
                self.yum_status.emit(self.row, "✅")
                ok = True
            else:
                self.log.emit(f"❌ [{self.host}] YUM 源异常 (timeout / rc={rc})")
                self.yum_status.emit(self.row, "❌")
                ok = False

            client.close()
        except paramiko.AuthenticationException:
            self.log.emit(f"❌ [{self.host}] YUM 预检: 认证失败")
            ok = False
        except Exception as e:
            self.log.emit(f"❌ [{self.host}] YUM 预检错误: {e}")
            ok = False
        finally:
            if client:
                client.close()
            self.worker_done.emit(self.row, ok)

# ── 日志查看弹窗 ────────────────────────────────────────────
class LogDialog(QDialog):
    def __init__(self, host, logs, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"📋 {host} 执行日志")
        self.setMinimumSize(680, 400)
        vl = QVBoxLayout(self)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setStyleSheet("background: #2d3436; color: #dfe6e9; font-family: Consolas; font-size: 12px; padding: 10px; border-radius: 4px;")
        te.setPlainText("\n".join(logs))
        vl.addWidget(te)
        btn = QPushButton("关闭")
        btn.setStyleSheet(STYLE_BTN_SECONDARY)
        btn.clicked.connect(self.accept)
        vl.addWidget(btn, 0, Qt.AlignRight)

# ── 表头全选复选框 ───────────────────────────────────────────
class CheckboxHeader(QHeaderView):
    checked = Signal(bool)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._checked = True
        self.setSectionsClickable(True)

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()
        if logicalIndex == 0:
            opt = QStyleOptionButton()
            sz = 18
            x = rect.x() + (rect.width() - sz) // 2
            y = rect.y() + (rect.height() - sz) // 2
            opt.rect = QRect(x, y, sz, sz)
            opt.state = QStyle.State_Enabled | (QStyle.State_On if self._checked else QStyle.State_Off)
            self.style().drawControl(QStyle.CE_CheckBox, opt, painter, self)

    def mousePressEvent(self, event):
        idx = self.logicalIndexAt(event.position().toPoint())
        if idx == 0:
            self._checked = not self._checked
            self.checked.emit(self._checked)
            self.updateSection(0)
        else:
            super().mousePressEvent(event)

# ── 主窗口 ─────────────────────────────────────────────────
class LinuxBaseConfig(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🛡 远程多主机系统初始化配置工具 v3.2.7")
        self.setMinimumSize(1100, 680)
        self.resize(1350, 750)

        # 全局字体
        self.setFont(QFont("Microsoft YaHei UI", 9))

        self.servers = []          # [{host, port, user, pwd}, ...]
        self.workers = []
        self.logs_map = {}
        self._fixed_cols = 5       # □ + IP + port + user + YUM状态
        self._task_col_offset = 5
        self._op_col = 0
        self._current_codes = []   # 当前选中的任务代码列表

        # YUM 预检状态
        self._precheck_workers = []
        self._precheck_results = {}   # {row: True/False}
        self._precheck_pending = 0    # 剩余待完成的预检数
        self._zombie_workers = []     # 防止正在运行的 worker 被 GC
        self._yum_check_enabled = True



        self._build_ui()

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(12, 12, 12, 12)
        vl.setSpacing(8)

        # ── 顶部工具栏 ──
        tool_row = QHBoxLayout()
        import_btn = QPushButton("📂 导入服务器列表 (Excel)")
        import_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        import_btn.clicked.connect(self._import_excel)
        tool_row.addWidget(import_btn)

        self.path_lbl = QLabel("未导入文件")
        self.path_lbl.setStyleSheet("color: #636e72;")
        tool_row.addWidget(self.path_lbl, 1)

        add_btn = QPushButton("➕ 手动添加")
        add_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        add_btn.clicked.connect(self._add_manual)
        tool_row.addWidget(add_btn)

        del_btn = QPushButton("✕ 删除选中")
        del_btn.setStyleSheet(STYLE_BTN_DANGER)
        del_btn.clicked.connect(self._delete_selected)
        tool_row.addWidget(del_btn)

        vl.addLayout(tool_row)

        # ── 中间区域: 左配置 + 右列表 ──
        splitter = QSplitter(Qt.Horizontal)

        # 左侧: 配置项 + 全选/清空 + yum状态摘要
        left_w = QFrame()
        left_w.setStyleSheet("QFrame { background: white; border: 1px solid #dfe6e9; border-radius: 8px; padding: 12px; }")
        left_ly = QVBoxLayout(left_w)
        left_ly.setContentsMargins(10, 10, 10, 10)

        title = QLabel("⚙ 选择要应用的初始化配置")
        title_font = QFont("Microsoft YaHei UI")
        title_font.setPixelSize(13)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #2d3436;")
        left_ly.addWidget(title)

        # 全选三态复选框
        self._select_all_cb = QCheckBox("全选")
        self._select_all_cb.setTristate(True)
        self._select_all_cb.setChecked(False)
        cb_font = QFont("Microsoft YaHei UI")
        cb_font.setPixelSize(12)
        self._select_all_cb.setFont(cb_font)
        self._select_all_cb.setStyleSheet("padding: 3px; color: #0984e3;")
        self._select_all_cb.toggled.connect(self._on_select_all_toggled)
        left_ly.addWidget(self._select_all_cb)

        self.chks = []
        self._updating_checkboxes = False
        items = [
            ("firewall",  "🛡 关闭防火墙 (firewalld / iptables)"),
            ("selinux",   "🛡 关闭 SELinux 安全防护"),
            ("sshd_dns",  "🚀 加速 SSHD (禁用 DNS 反向解析)"),
            ("rc_local",  "⚙  启动 rc.local 开机服务"),
            ("ntp_off",   "⏱ 禁用旧版 NTP / NTPD 服务"),
            ("chrony",    "⏱ 安装并启用 Chronyd 时间同步"),
            ("ftp",       "📦 安装 vsftpd (FTP)"),
            ("telnet",    "📦 安装 Telnet 应急服务"),
            ("python2",   "🐍 安装 Python2 + 软链接"),
            ("gdb",       "🔧 安装 GDB 调试器"),
        ]
        for code, label in items:
            chk = QCheckBox(label)
            chk.setChecked(False)
            chk.setProperty("code", code)
            chk_font = QFont("Microsoft YaHei UI")
            chk_font.setPixelSize(12)
            chk.setFont(chk_font)
            chk.setStyleSheet("padding: 3px; color: #2d3436;")
            chk.toggled.connect(self._on_checkbox_toggled)
            self.chks.append(chk)
            left_ly.addWidget(chk)

        left_ly.addStretch()
        splitter.addWidget(left_w)

        # ── 右侧: 服务器表格 ──
        right_w = QWidget()
        right_ly = QVBoxLayout(right_w)
        right_ly.setContentsMargins(0, 0, 0, 0)

        # YUM 检测开关（仅控制是否执行 yum check-update，不影响 yum 任务的勾选）
        self._yum_check_cb = QCheckBox("YUM 源检测（启动前自动验证 YUM 可用性）")
        self._yum_check_cb.setChecked(True)
        self._yum_check_cb.toggled.connect(self._on_yum_check_toggled)
        right_ly.addWidget(self._yum_check_cb)

        self.table = QTableWidget()
        chk_header = CheckboxHeader(Qt.Horizontal)
        chk_header.checked.connect(self._on_header_checkbox_toggled)
        self.table.setHorizontalHeader(chk_header)
        self._rebuild_table_columns(self._get_active_codes())  # 初始列

        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        right_ly.addWidget(self.table)
        splitter.addWidget(right_w)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([210, 900])
        vl.addWidget(splitter, 1)

        # ── 底部按钮栏 ──
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.stop_all_btn = QPushButton("⏹ 停止全部")
        self.stop_all_btn.setStyleSheet(STYLE_BTN_DANGER)
        self.stop_all_btn.setEnabled(False)
        self.stop_all_btn.clicked.connect(self._stop_all)
        bottom.addWidget(self.stop_all_btn)

        self.run_btn = QPushButton("🚀 一键批量初始化")
        self.run_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self.run_btn.clicked.connect(self._run_all)
        bottom.addWidget(self.run_btn)
        vl.addLayout(bottom)

    # ── 工具方法 ──
    def _set_all(self, v):
        self._updating_checkboxes = True
        for c in self.chks:
            c.setChecked(v)
        self._updating_checkboxes = False
        self._update_select_all_state()
        self._on_checkboxes_changed()

    def _get_selected_codes(self):
        return [c.property("code") for c in self.chks if c.isChecked()]

    def _get_active_codes(self):
        return self._get_selected_codes()

    def _update_select_all_state(self):
        self._select_all_cb.blockSignals(True)
        checked = sum(1 for c in self.chks if c.isChecked())
        total = len(self.chks)
        if checked == 0:
            self._select_all_cb.setCheckState(Qt.Unchecked)
        elif checked == total:
            self._select_all_cb.setCheckState(Qt.Checked)
        else:
            self._select_all_cb.setCheckState(Qt.PartiallyChecked)
        self._select_all_cb.blockSignals(False)

    def _on_select_all_toggled(self, checked):
        self._set_all(checked)

    def _on_checkbox_toggled(self):
        self._update_select_all_state()
        if not self._updating_checkboxes:
            self._on_checkboxes_changed()

    def _on_checkboxes_changed(self):
        """勾选/取消勾选任务后：仅重建列，不触发 YUM 预检"""
        self._rebuild_table_columns(self._get_active_codes())

    # ── 动态重建表格列 ──
    def _rebuild_table_columns(self, codes):
        """固定列: □ + IP + port + user + YUM状态 | N个任务列 | 操作"""
        # 保存 YUM 状态（每次 clear 后会被重置）
        saved_yum = {}
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 4)
            if item:
                saved_yum[i] = (item.text(), item.background() if item.background() else None)
        self.table.clear()  # 清除所有 item + cell widget，防止旧 widget 残留
        self._current_codes = codes
        n_tasks = len(codes)
        total = self._fixed_cols + n_tasks + 1
        self._op_col = total - 1

        headers = ["", "IP地址", "端口", "用户名", "YUM源状态"]
        for c in codes:
            headers.append(TASK_META.get(c, c))
        headers.append("操作")

        self.table.setColumnCount(total)
        self.table.setHorizontalHeaderLabels(headers)

        # 先按内容计算自然宽度
        self.table.resizeColumnsToContents()

        # 复选框列固定
        header = self.table.horizontalHeader()
        self.table.setColumnWidth(0, 28)
        header.setSectionResizeMode(0, QHeaderView.Fixed)

        # 信息列(IP/端口/用户名/YUM)可拖动，宽度不低于 60px
        for c in range(1, min(self._fixed_cols, total)):
            if self.table.columnWidth(c) < 60:
                self.table.setColumnWidth(c, 60)
            header.setSectionResizeMode(c, QHeaderView.Interactive)

        # 任务列+操作自动拉伸填满，宽度不低于 50px
        for c in range(self._fixed_cols, total):
            if self.table.columnWidth(c) < 50:
                self.table.setColumnWidth(c, 50)
            header.setSectionResizeMode(c, QHeaderView.Stretch)

        # 填充已有数据
        self._restore_table_data(codes)
        # 恢复 YUM 状态
        for row, (text, bg) in saved_yum.items():
            if row < self.table.rowCount():
                item = self.table.item(row, 4)
                if item:
                    item.setText(text)
                    if bg:
                        item.setBackground(bg)
        self._update_run_btn()

    def _restore_table_data(self, codes):
        """填充或恢复服务器行数据"""
        n_tasks = len(codes)
        self.table.setRowCount(len(self.servers))
        for i, s in enumerate(self.servers):
            # □ 复选框 — 用 cell widget 居中
            cw = QWidget()
            hly = QHBoxLayout(cw)
            hly.setContentsMargins(0, 0, 0, 0)
            hly.setAlignment(Qt.AlignCenter)
            cb = QCheckBox()
            cb.setChecked(True)
            hly.addWidget(cb)
            self.table.setCellWidget(i, 0, cw)

            # IP
            ip_item = QTableWidgetItem(s["host"])
            self.table.setItem(i, 1, ip_item)

            # 端口 — 居中
            port_item = QTableWidgetItem(str(s["port"]))
            port_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 2, port_item)

            # 用户名 — 居中
            user_item = QTableWidgetItem(s["user"])
            user_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 3, user_item)

            # YUM源状态 — ⚪ 待检
            yum_item = QTableWidgetItem("⚪")
            yum_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 4, yum_item)

            # 任务列 — ⚪ 待执行
            for t in range(n_tasks):
                item = QTableWidgetItem("⚪")
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, self._fixed_cols + t, item)

            # 操作按钮
            self._set_op_btn(i, s["host"])

    def _set_op_btn(self, row, host):
        btn = QPushButton("📋")
        btn.setToolTip(f"查看 {host} 执行日志")
        btn.setStyleSheet("QPushButton{background:transparent;color:#0984e3;border:1px solid #0984e3;"
                          "border-radius:3px;padding:2px 6px;font-size:12px;}"
                          "QPushButton:hover{background:#e8f0fe;}")
        btn.clicked.connect(lambda checked, h=host: self._show_log(h))
        self.table.setCellWidget(row, self._op_col, btn)

    # ── YUM 预检 ──
    def _start_yum_precheck(self):
        """导入/添加/删除服务器后自动启动 YUM 源预检"""
        if not self._yum_check_enabled:
            self._update_run_btn()
            return

        self._zombie_workers = [w for w in self._zombie_workers if w.isRunning()]
        for w in self._precheck_workers:
            w.stop()
            self._zombie_workers.append(w)
        self._precheck_workers = []
        self._precheck_results.clear()
        self._precheck_pending = 0

        if not self.servers:
            self._update_run_btn()
            return

        self.run_btn.setEnabled(False)
        self.stop_all_btn.setEnabled(True)
        self._precheck_pending = len(self.servers)

        for i, s in enumerate(self.servers):
            yum_item = self.table.item(i, 4)
            if yum_item:
                yum_item.setText("🔄")
            w = YumPrecheckWorker(s["host"], s["port"], s["user"], s["pwd"], i)
            w.log.connect(lambda txt, h=s["host"]: self._on_log(h, txt))
            w.yum_status.connect(self._on_yum_status)
            w.worker_done.connect(self._on_precheck_done)
            w.finished.connect(lambda w=w: self._cleanup_zombie(w))
            self._precheck_workers.append(w)
            w.start()

    def _cleanup_zombie(self, worker):
        if worker in self._zombie_workers:
            self._zombie_workers.remove(worker)

    def _on_precheck_done(self, row, ok):
        if self._precheck_pending <= 0:
            return  # 已停止/已完成的残留信号
        self._precheck_pending -= 1
        self._precheck_results[row] = ok
        if self._precheck_pending <= 0:
            self.stop_all_btn.setEnabled(False)
            self._update_run_btn()

    def _on_yum_check_toggled(self, enabled):
        if self.workers:
            self._yum_check_cb.blockSignals(True)
            self._yum_check_cb.setChecked(not enabled)
            self._yum_check_cb.blockSignals(False)
            return
        self._yum_check_enabled = enabled
        if enabled:
            self._start_yum_precheck()
        else:
            for w in self._precheck_workers:
                w.stop()
                self._zombie_workers.append(w)
            self._precheck_workers = []
            self._precheck_results.clear()
            self._precheck_pending = 0
            for i in range(self.table.rowCount()):
                item = self.table.item(i, 4)
                if item:
                    item.setText("⏹")
            self._update_run_btn()

    # ── 防呆：更新运行按钮状态 ──
    def _update_run_btn(self):
        has_codes = bool(self._get_active_codes())
        if not hasattr(self, 'run_btn'):
            return

        # 基础条件
        can_run = len(self.servers) > 0 and has_codes

        # 预检中
        if self._precheck_pending > 0:
            can_run = False

        # YUM 检测开启且预检全部完成 → 有任一失败则锁定
        if self._yum_check_enabled and self._precheck_pending == 0 and self._precheck_results:
            if not all(self._precheck_results.values()):
                can_run = False

        self.run_btn.setEnabled(can_run)

    # ── Excel 导入 ──
    def _import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择服务器列表", "", "Excel (*.xlsx *.xls)")
        if not path:
            return
        self.path_lbl.setText(os.path.basename(path))
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path)
            ws = wb.active
            rows = list(ws.iter_rows(min_row=2, values_only=True))
            self.servers.clear()
            for r in rows:
                if r[0] and str(r[0]).strip():
                    self.servers.append({
                        "host": str(r[0]).strip(),
                        "port": int(r[1]) if r[1] else 22,
                        "user": str(r[2]).strip() if r[2] else "root",
                        "pwd": str(r[3]).strip() if r[3] else "",
                    })
            self._rebuild_table_columns(self._get_active_codes())
            self._set_all(True)
            QMessageBox.information(self, "导入成功", f"成功导入 {len(self.servers)} 台服务器")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"{e}")
        self._start_yum_precheck()

    # ── 手动添加 ──
    def _add_manual(self):
        from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("手动添加服务器")
        dlg.setFixedSize(380, 200)
        fl = QFormLayout(dlg)
        host_ed = QLineEdit(); host_ed.setPlaceholderText("192.168.1.10")
        port_ed = QLineEdit("22"); port_ed.setPlaceholderText("22")
        user_ed = QLineEdit("root"); user_ed.setPlaceholderText("root")
        pwd_ed = QLineEdit(); pwd_ed.setEchoMode(QLineEdit.Password); pwd_ed.setPlaceholderText("输入密码")
        fl.addRow("主机:", host_ed)
        fl.addRow("端口:", port_ed)
        fl.addRow("用户名:", user_ed)
        fl.addRow("密码:", pwd_ed)
        btn_ly = QHBoxLayout()
        ok = QPushButton("确认"); ok.setStyleSheet(STYLE_BTN_PRIMARY)
        cancel = QPushButton("取消"); cancel.setStyleSheet(STYLE_BTN_SECONDARY)
        btn_ly.addStretch(); btn_ly.addWidget(ok); btn_ly.addWidget(cancel)
        fl.addRow(btn_ly)
        ok.clicked.connect(dlg.accept)
        cancel.clicked.connect(dlg.reject)
        if dlg.exec() == QDialog.Accepted and host_ed.text().strip():
            self.servers.append({
                "host": host_ed.text().strip(),
                "port": int(port_ed.text()) if port_ed.text().isdigit() else 22,
                "user": user_ed.text().strip() or "root",
                "pwd": pwd_ed.text(),
            })
            self._rebuild_table_columns(self._get_active_codes())
            self._set_all(True)
            self._start_yum_precheck()

    # ── 删除选中 ──
    def _delete_selected(self):
        rows = sorted(set(r.row() for r in self.table.selectedIndexes()), reverse=True)
        for r in rows:
            if r < len(self.servers):
                self.servers.pop(r)
        self._rebuild_table_columns(self._get_active_codes())
        self._set_all(True)
        self._start_yum_precheck()

    # ── 右键菜单 ──
    def _on_table_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self.servers):
            return
        menu = QMenu(self)
        del_action = menu.addAction("✕ 删除此行")
        run_action = menu.addAction("🚀 仅执行此行")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == del_action:
            self._delete_row(row)
        elif action == run_action:
            self._run_single_row(row)

    def _delete_row(self, row):
        if self.workers or self._precheck_workers:
            self._stop_all()
        if row < len(self.servers):
            self.servers.pop(row)
        self._rebuild_table_columns(self._get_active_codes())
        self._set_all(True)
        self._start_yum_precheck()

    def _run_single_row(self, row):
        codes = self._get_active_codes()
        if not codes:
            QMessageBox.warning(self, "提示", "请至少勾选一项配置")
            return
        s = self.servers[row]
        reply = QMessageBox.question(self, "确认执行",
            f"即将对 {s['host']} 仅执行 {len(codes)} 项配置，\n"
            f"其中 {sum(1 for c in codes if c in YUM_TASKS_SET)} 项需要 YUM 源。\n确定继续？",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._stop_all()
        self.logs_map.clear()
        self._rebuild_table_columns(codes)
        tasks = self._build_tasks(codes)
        self.run_btn.setEnabled(False)
        self.stop_all_btn.setEnabled(True)
        for t in range(len(codes)):
            item = self.table.item(row, self._fixed_cols + t)
            if item:
                item.setText("🔄")
        yum_ok = self._precheck_results.get(row) if self._yum_check_enabled else True
        w = SSHWorker(s["host"], s["port"], s["user"], s["pwd"], tasks, row, True, yum_ok)
        w.log.connect(lambda txt, h=s["host"]: self._on_log(h, txt))
        w.task_status.connect(self._on_task_status)
        w.yum_status.connect(self._on_yum_status)
        w.os_detected.connect(self._on_os_detected)
        w.worker_done.connect(self._on_worker_done)
        w.finished.connect(lambda w=w: self._cleanup_zombie(w))
        self.workers.append(w)
        w.start()

    def _on_header_checkbox_toggled(self, checked):
        for i in range(self.table.rowCount()):
            cw = self.table.cellWidget(i, 0)
            if cw:
                cb = cw.findChild(QCheckBox)
                if cb:
                    cb.setChecked(checked)

    # ── 查看日志 ──
    def _show_log(self, host):
        logs = self.logs_map.get(host, ["暂无日志"])
        dlg = LogDialog(host, logs, self)
        dlg.exec()

    # ── 构建任务列表 ──
    def _build_tasks(self, codes):
        """返回 [(cmd_or_fn, desc, task_idx, task_code), ...]"""
        tasks = []
        for tidx, code in enumerate(codes):
            if code == "firewall":
                tasks += [("systemctl stop firewalld && systemctl is-active firewalld | grep -q inactive",
                           f"🛡 停止 firewalld", tidx, code),
                          ("systemctl disable firewalld && systemctl is-enabled firewalld | grep -q disabled",
                           f"🛡 禁用 firewalld", tidx, code),
                          ("if systemctl is-enabled iptables 2>/dev/null | grep -q enabled; then systemctl stop iptables 2>/dev/null; systemctl is-active iptables 2>&1 | grep -q inactive; else true; fi",
                           f"🛡 停止 iptables", tidx, code),
                          ("if systemctl is-enabled iptables 2>/dev/null | grep -q enabled; then systemctl disable iptables 2>/dev/null; ! systemctl is-enabled iptables 2>/dev/null | grep -q enabled; else true; fi",
                           f"🛡 禁用 iptables", tidx, code)]
            elif code == "selinux":
                tasks += [("setenforce 0 && getenforce | grep -q Permissive",
                           f"🛡 临时关闭 SELinux", tidx, code),
                          (r"sed -i 's/^SELINUX=enforcing/SELINUX=disabled/' /etc/selinux/config && grep -q '^SELINUX=disabled' /etc/selinux/config",
                           f"🛡 永久禁用 SELinux", tidx, code)]
            elif code == "sshd_dns":
                tasks += [(r"sed -i 's/^#UseDNS no/UseDNS no/' /etc/ssh/sshd_config && grep -q '^UseDNS no' /etc/ssh/sshd_config",
                           f"🚀 配置 SSHD 禁用 DNS", tidx, code),
                          ("systemctl restart sshd && systemctl is-active sshd | grep -q active",
                           f"🚀 重启 SSHD", tidx, code)]
            elif code == "rc_local":
                tasks += [("chmod +x /etc/rc.d/rc.local && test -x /etc/rc.d/rc.local",
                           f"⚙ 赋予执行权限", tidx, code),
                          ("systemctl enable rc-local && systemctl is-enabled rc-local | grep -q enabled",
                           f"⚙ 启用 rc-local", tidx, code),
                          ("systemctl start rc-local && systemctl is-active rc-local | grep -q active",
                           f"⚙ 启动 rc-local", tidx, code)]
            elif code == "ntp_off":
                tasks += [("if systemctl is-enabled ntp 2>/dev/null | grep -q enabled; then systemctl stop ntp 2>/dev/null; systemctl is-active ntp 2>&1 | grep -q inactive; else true; fi",
                           f"⏱ 停止 ntp", tidx, code),
                          ("if systemctl is-enabled ntp 2>/dev/null | grep -q enabled; then systemctl disable ntp 2>/dev/null; ! systemctl is-enabled ntp 2>/dev/null | grep -q enabled; else true; fi",
                           f"⏱ 禁用 ntp", tidx, code),
                          ("if systemctl is-enabled ntpd 2>/dev/null | grep -q enabled; then systemctl stop ntpd 2>/dev/null; systemctl is-active ntpd 2>&1 | grep -q inactive; else true; fi",
                           f"⏱ 停止 ntpd", tidx, code),
                          ("if systemctl is-enabled ntpd 2>/dev/null | grep -q enabled; then systemctl disable ntpd 2>/dev/null; ! systemctl is-enabled ntpd 2>/dev/null | grep -q enabled; else true; fi",
                           f"⏱ 禁用 ntpd", tidx, code)]
            elif code == "chrony":
                tasks += [("yum -y install chrony", f"⏱ 安装 chrony", tidx, code),
                          ("systemctl start chronyd && systemctl is-active chronyd | grep -q active",
                           f"⏱ 启动 chronyd", tidx, code),
                          ("systemctl enable chronyd && systemctl is-enabled chronyd | grep -q enabled",
                           f"⏱ 启用 chronyd", tidx, code)]
            elif code == "ftp":
                tasks += [("yum -y install vsftpd ftp", f"📦 安装 vsftpd", tidx, code),
                          ("systemctl start vsftpd && systemctl is-active vsftpd | grep -q active",
                           f"📦 启动 vsftpd", tidx, code),
                          ("systemctl enable vsftpd && systemctl is-enabled vsftpd | grep -q enabled",
                           f"📦 启用 vsftpd", tidx, code)]
            elif code == "telnet":
                _tc = """service telnet
{
        disable        = no
        flags          = REUSE
        socket_type    = stream
        wait           = no
        user           = root
        server         = /usr/sbin/in.telnetd
        log_on_failure += USERID
}
"""
                _b = base64.b64encode(_tc.encode()).decode()
                tasks += [("yum -y install telnet telnet-server xinetd", f"📦 安装 telnet", tidx, code),
                          (f"echo '{_b}' | base64 -d > /etc/xinetd.d/telnet", f"📦 写入配置", tidx, code),
                          ("systemctl restart xinetd && systemctl is-active xinetd | grep -q active",
                           f"📦 重启 xinetd", tidx, code),
                          ("systemctl enable xinetd && systemctl is-enabled xinetd | grep -q enabled",
                           f"📦 启用 xinetd", tidx, code)]
            elif code == "python2":
                tasks += [("yum -y install python2", f"🐍 安装 python2", tidx, code),
                          ("ln -sf /usr/bin/python2 /usr/bin/python && test -L /usr/bin/python",
                           f"🐍 建立软链接", tidx, code)]
            elif code == "gdb":
                tasks += [("yum -y install gdb", f"🔧 安装 gdb", tidx, code)]
        return tasks

    # ── 开始批量执行 ──
    def _run_all(self):
        codes = self._get_active_codes()
        if not codes:
            QMessageBox.warning(self, "提示", "请至少勾选一项配置")
            return

        # 找出勾选的行 (从 cell widget 读取)
        checked_rows = []
        for i in range(self.table.rowCount()):
            cw = self.table.cellWidget(i, 0)
            if cw:
                cb = cw.findChild(QCheckBox)
                if cb and cb.isChecked():
                    checked_rows.append(i)

        if not checked_rows:
            QMessageBox.warning(self, "提示", "请至少勾选一台需要执行的服务器")
            return

        self._stop_all()
        self.logs_map.clear()
        self._rebuild_table_columns(codes)

        has_yum = True  # YUM 任务始终选中
        tasks = self._build_tasks(codes)
        self.run_btn.setEnabled(False)
        self.stop_all_btn.setEnabled(True)

        for i in checked_rows:
            s = self.servers[i]
            host = s["host"]
            # 重置状态
            for t in range(len(codes)):
                item = self.table.item(i, self._fixed_cols + t)
                if item:
                    item.setText("🔄")
            # 预检结果（关闭检测时视为正常）
            yum_ok = self._precheck_results.get(i) if self._yum_check_enabled else True
            w = SSHWorker(s["host"], s["port"], s["user"], s["pwd"], tasks, i, has_yum, yum_ok)
            w.log.connect(lambda txt, h=host: self._on_log(h, txt))
            w.task_status.connect(self._on_task_status)
            w.yum_status.connect(self._on_yum_status)
            w.os_detected.connect(self._on_os_detected)
            w.worker_done.connect(self._on_worker_done)
            w.finished.connect(lambda w=w: self._cleanup_zombie(w))
            self.workers.append(w)
            w.start()

    def _on_log(self, host, text):
        if host not in self.logs_map:
            self.logs_map[host] = []
        self.logs_map[host].append(text)

    def _on_task_status(self, row, tidx, icon):
        if row < self.table.rowCount():
            col = self._fixed_cols + tidx
            if col < self.table.columnCount():
                item = self.table.item(row, col)
                if item:
                    item.setText(icon)
                    if icon == "✅":
                        item.setBackground(QColor("#e8f5e9"))
                    elif icon == "❌":
                        item.setBackground(QColor("#fce4e4"))
                    elif icon == "🔄":
                        item.setBackground(QColor("#fff3cd"))
                    elif icon == "⏹":
                        item.setBackground(QColor("#dfe6e9"))

    def _on_yum_status(self, row, icon):
        if row < self.table.rowCount():
            item = self.table.item(row, 4)
            if item:
                item.setText(icon)
                if icon == "✅":
                    item.setBackground(QColor("#e8f5e9"))
                elif icon == "❌":
                    item.setBackground(QColor("#fce4e4"))
                elif icon == "⚠️":
                    item.setBackground(QColor("#fff3cd"))
                elif icon == "🔄":
                    item.setBackground(QColor("#fff3cd"))

    def _on_os_detected(self, row, os_name):
        pass  # 已无系统版本列，不需要处理

    def _on_worker_done(self, row, success):
        # 所有 worker 都完成后重新启用按钮
        all_done = all(not w.isRunning() for w in self.workers)
        if all_done:
            self.run_btn.setEnabled(True)
            self.stop_all_btn.setEnabled(False)

    def _stop_all(self):
        self._zombie_workers = [w for w in self._zombie_workers if w.isRunning()]
        for w in self.workers:
            w.stop()
            self._zombie_workers.append(w)
        self.workers = []
        for w in self._precheck_workers:
            w.stop()
            self._zombie_workers.append(w)
        self._precheck_workers = []
        self._precheck_pending = 0
        self.stop_all_btn.setEnabled(False)
        self._update_run_btn()


    def closeEvent(self, event):
        self._stop_all()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = LinuxBaseConfig()
    w.show()
    sys.exit(app.exec())
