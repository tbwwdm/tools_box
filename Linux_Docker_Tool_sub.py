# -*- coding: utf-8 -*-
"""
Docker 远程管理工具  v2.6.0
通过SSH连接远程服务器，管理Docker容器、网络等
"""

import sys, os, logging, threading, time, json
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QSpinBox, QFrame, QTextEdit, QGroupBox,
    QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QFormLayout, QMessageBox, QComboBox, QScrollArea,
    QSizePolicy, QSplitter, QCheckBox, QMenu, QStyleFactory,
    QStyledItemDelegate, QStyleOptionViewItem, QRadioButton, QButtonGroup,
    QPlainTextEdit, QFileDialog, QProgressBar, QAbstractItemView, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPoint, QEvent, QRect
from PySide6.QtGui import QFont, QColor, QPainter, QPixmap, QPolygon, QPalette, QPen
from PySide6.QtWidgets import QStyle
import paramiko

logger = logging.getLogger(__name__)

STYLE_CONNECTED = "color: #27ae60; font-weight: bold"
STYLE_DISCONNECTED = "color: #e74c3c; font-weight: bold"
STYLE_CARD = """
    QFrame {
        background: white; border: 1px solid #e0e0e0;
        border-radius: 8px; padding: 12px;
    }
"""
STYLE_CARD_TITLE = "font-size: 13px; color: #666; margin-bottom: 4px;"
STYLE_CARD_VALUE = "font-size: 15px; font-weight: bold; color: #2d3436;"
STYLE_INPUT = """
    QLineEdit, QSpinBox, QComboBox {
        border: none; border-bottom: 2px solid #dfe6e9;
        padding: 6px 4px; font-size: 13px; background: #f8f9fa;
    }
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
        border-bottom: 2px solid #0984e3;
    }
"""
STYLE_INPUT_FLAT = """
    QLineEdit, QSpinBox, QComboBox {
        border: 1px solid #dfe6e9; border-radius: 4px;
        padding: 6px 8px; font-size: 13px; background: #f8f9fa;
    }
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
        border: 1px solid #0984e3; background: white;
    }
"""
STYLE_BTN_PRIMARY = """
    QPushButton {
        background: #5b7a9a; color: white; border: none;
        padding: 8px 24px; border-radius: 4px; font-weight: bold; font-size: 13px;
    }
    QPushButton:hover { background: #4e6b89; }
    QPushButton:disabled { background: #c8d0d8; }
"""
STYLE_BTN_DANGER = """
    QPushButton {
        background: #b85450; color: white; border: none;
        padding: 8px 24px; border-radius: 4px; font-weight: bold; font-size: 13px;
    }
    QPushButton:hover { background: #a34945; }
    QPushButton:disabled { background: #c8d0d8; }
"""
STYLE_BTN_SUCCESS = """
    QPushButton {
        background: #5d8a6a; color: white; border: none;
        padding: 8px 24px; border-radius: 4px; font-weight: bold; font-size: 13px;
    }
    QPushButton:hover { background: #4f7a5d; }
    QPushButton:disabled { background: #c8d0d8; }
"""
STYLE_BTN_CTRL = """
    QPushButton {
        border: none; border-radius: 3px;
        padding: 5px 14px; font-size: 12px; font-weight: bold; color: white;
    }
    QPushButton:disabled { background: #c8d0d8; color: #e8ecf0; }
"""
STYLE_BTN_CANCEL = """
    QPushButton {
        background: white; color: #6b7a7f;
        border: 1px solid #c8d0d8; border-radius: 4px;
        padding: 8px 20px; font-size: 13px;
    }
    QPushButton:hover { background: #f0f3f5; }
"""
STYLE_CARD_TITLE = "font-size: 12px; color: #636e72; font-weight: normal;"


class DockerSSHWorker(QThread):
    output_ready = Signal(str)
    data_ready = Signal(dict)

    def __init__(self, host, port, username, password, commands=None, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.commands = commands or []
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        client = None
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.host, port=self.port, username=self.username,
                           password=self.password, timeout=15)
            self.output_ready.emit(f"✅ SSH连接成功 {self.host}")

            if self.commands:
                results = []
                for cmd in self.commands:
                    if self._stopped:
                        break
                    self.output_ready.emit(f"▶ 执行: {cmd}")
                    stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
                    out = stdout.read().decode("utf-8", errors="replace").strip()
                    err = stderr.read().decode("utf-8", errors="replace").strip()
                    results.append({"cmd": cmd, "stdout": out, "stderr": err})
                    if out:
                        for line in out.split("\n")[:5]:
                            self.output_ready.emit(f"  {line}")
                    if err:
                        self.output_ready.emit(f"  ⚠ {err[:200]}")
                self.data_ready.emit({"type": "command_results", "results": results})
            else:
                data = self._fetch_all_docker_info(client)
                self.data_ready.emit({"type": "docker_info", "data": data})
                self.output_ready.emit("✅ Docker信息加载完成")

        except paramiko.AuthenticationException:
            self.output_ready.emit("❌ SSH认证失败，请检查用户名和密码")
        except paramiko.SSHException as e:
            self.output_ready.emit(f"❌ SSH连接失败: {e}")
        except Exception as e:
            self.output_ready.emit(f"❌ 错误: {e}")
        finally:
            if client:
                client.close()

    def _fetch_all_docker_info(self, client):
        data = {
            "service_status": "未知", "service_enabled": "未知",
            "version": "未知", "uptime_counts": {"run": "0", "paused": "0", "stopped": "0"},
            "containers": [], "images": [], "networks": [], "interfaces": []
        }
        try:
            stdin, stdout, stderr = client.exec_command(
                "systemctl is-active docker 2>/dev/null", timeout=10)
            lines = [l.strip() for l in stdout.read().decode().split("\n") if l.strip()]
            data["service_status"] = lines[0] if lines else "未知"
        except:
            pass
        try:
            stdin, stdout, stderr = client.exec_command(
                "systemctl is-enabled docker 2>/dev/null", timeout=10)
            lines = [l.strip() for l in stdout.read().decode().split("\n") if l.strip()]
            data["service_enabled"] = lines[0] if lines else "未知"
        except:
            pass
        try:
            stdin, stdout, stderr = client.exec_command(
                "docker --version 2>/dev/null || echo '未安装'", timeout=10)
            lines = [l.strip() for l in stdout.read().decode().split("\n") if l.strip()]
            v = lines[0] if lines else "未知"
            if v and " " in v:
                v = v.split()[2].rstrip(",")
            data["version"] = v
        except:
            pass
        try:
            stdin, stdout, stderr = client.exec_command(
                "docker info --format '{{.ContainersRunning}}|{{.ContainersPaused}}|{{.ContainersStopped}}' 2>/dev/null || echo '---'",
                timeout=10)
            parts = stdout.read().decode().strip().split("|")
            if len(parts) >= 3 and parts[0].strip().isdigit():
                data["uptime_counts"] = {"run": parts[0], "paused": parts[1], "stopped": parts[2]}
        except:
            pass
        try:
            stdin, stdout, stderr = client.exec_command(
                "docker ps -a --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.CreatedAt}}' 2>/dev/null",
                timeout=10)
            for line in stdout.read().decode().strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if len(parts) >= 4:
                        data["containers"].append({
                            "id": parts[0][:12], "name": parts[1], "image": parts[2],
                            "status": parts[3], "ports": parts[4] if len(parts) > 4 else "",
                            "created": parts[5] if len(parts) > 5 else ""
                        })
        except:
            pass
        try:
            stdin, stdout, stderr = client.exec_command(
                "docker images --format '{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}' 2>/dev/null",
                timeout=10)
            for line in stdout.read().decode().strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if len(parts) >= 4:
                        data["images"].append({
                            "repo": parts[0], "tag": parts[1],
                            "id": parts[2][:12], "size": parts[3],
                            "created": parts[4] if len(parts) > 4 else ""
                        })
        except:
            pass
        try:
            stdin, stdout, stderr = client.exec_command(
                "docker network ls -q 2>/dev/null | xargs docker network inspect "
                "--format '{{.Name}}\t{{.Driver}}\t{{.Scope}}\t"
                "{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null",
                timeout=10)
            for line in stdout.read().decode().strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        subnet = parts[3].strip() if len(parts) > 3 else ""
                        data["networks"].append({
                            "name": parts[0], "driver": parts[1],
                            "scope": parts[2] if len(parts) > 2 else "",
                            "subnet": subnet
                        })
        except:
            pass
        try:
            stdin, stdout, stderr = client.exec_command(
                "ls /sys/class/net 2>/dev/null", timeout=5)
            data["interfaces"] = [l.strip() for l in stdout.read().decode().split()
                                  if l.strip() and l.strip() not in ("lo", "docker0")]
        except:
            pass
        try:
            stdin, stdout, stderr = client.exec_command(
                "docker ps -q 2>/dev/null | xargs docker inspect "
                "--format '{{.Name}}\t{{range $k,$v:=.NetworkSettings.Networks}}{{$v.IPAddress}} {{end}}' "
                "2>/dev/null", timeout=30)
            ip_map = {}
            for line in stdout.read().decode().strip().split("\n"):
                line = line.strip()
                if line:
                    parts = line.split("\t", 1)
                    name = parts[0].lstrip("/") if len(parts) > 0 else ""
                    ips = parts[1].strip().split() if len(parts) > 1 else []
                    if name:
                        ip_map[name] = ips
            data["container_ips"] = ip_map
        except:
            data["container_ips"] = {}
        return data


class _ComboDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        if opt.state & QStyle.State_MouseOver:
            opt.palette.setColor(QPalette.HighlightedText, QColor("#333"))
            opt.palette.setColor(QPalette.Highlight, QColor("#dfe6e9"))
        super().paint(painter, opt, index)


class CreateNetworkDialog(QDialog):
    def __init__(self, parent, interfaces, existing_networks, existing_subnets):
        super().__init__(parent)
        self.setWindowTitle("🌐 创建网络")
        self.setMinimumWidth(520)
        self.interfaces = interfaces
        self.existing_networks = set(n["name"] for n in existing_networks)
        self.existing_subnets = set(existing_subnets)
        self._command = None
        self._build_ui()
        self._populate_combos()

    def _build_ui(self):
        fl = QFormLayout(self)
        fl.setSpacing(6)
        fl.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        fl.setContentsMargins(20, 16, 20, 16)
        input_max = 300

        def _lbl(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 13px;")
            return lbl

        def _req(text):
            lbl = QLabel(f'<span style="color:red">*</span>{text}')
            lbl.setStyleSheet("font-size: 13px;")
            return lbl

        self.net_name = QLineEdit()
        self.net_name.setPlaceholderText("例如: macvlan_ipv6_23")
        self.net_name.setStyleSheet(STYLE_INPUT)
        self.net_name.setFixedWidth(input_max)
        self.net_name.textChanged.connect(self._validate_net_name)
        self.net_name_warn = QLabel("")
        self.net_name_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        name_row = QHBoxLayout()
        name_row.setSpacing(0)
        name_row.addWidget(self.net_name)
        name_row.addWidget(self.net_name_warn)
        name_row.addStretch()
        fl.addRow(_req("网络名称"), name_row)

        self.net_driver = QComboBox()
        self.net_driver.addItems(["macvlan", "bridge", "overlay", "ipvlan"])
        self.net_driver.setFixedWidth(input_max)
        fl.addRow(_req("驱动类型"), self.net_driver)

        self.net_nic = QComboBox()
        self.net_nic.setFixedWidth(input_max)
        self.net_nic.currentTextChanged.connect(self._check_ready)
        fl.addRow(_req("物理网卡"), self.net_nic)

        self._style_combos()

        self.net_macvlan_mode = QLineEdit("bridge")
        self.net_macvlan_mode.setReadOnly(True)
        self.net_macvlan_mode.setFixedWidth(input_max)
        self.net_macvlan_mode.setStyleSheet("""
            QLineEdit {
                border: none; border-bottom: 2px solid #dfe6e9;
                background: transparent; color: #636e72;
                font-size: 13px; padding: 6px 4px;
            }
        """)
        fl.addRow(_lbl("网卡模式"), self.net_macvlan_mode)

        self.net_subnet_v4 = QLineEdit()
        self.net_subnet_v4.setPlaceholderText("例如: 10.14.23.0/24")
        self.net_subnet_v4.setStyleSheet(STYLE_INPUT)
        self.net_subnet_v4.setFixedWidth(input_max)
        self.net_subnet_v4.textChanged.connect(self._validate_subnet)
        self.net_subnet_warn = QLabel("")
        self.net_subnet_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        subnet_row = QHBoxLayout()
        subnet_row.setSpacing(0)
        subnet_row.addWidget(self.net_subnet_v4)
        subnet_row.addWidget(self.net_subnet_warn)
        subnet_row.addStretch()
        fl.addRow(_req("子网 (IPv4)"), subnet_row)

        self.net_gateway_v4 = QLineEdit()
        self.net_gateway_v4.setPlaceholderText("例如: 10.14.23.1")
        self.net_gateway_v4.setStyleSheet(STYLE_INPUT)
        self.net_gateway_v4.setFixedWidth(input_max)
        self.net_gateway_v4.textChanged.connect(self._validate_gateway)
        self.net_gateway_warn = QLabel("")
        self.net_gateway_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        gw_row = QHBoxLayout()
        gw_row.setSpacing(0)
        gw_row.addWidget(self.net_gateway_v4)
        gw_row.addWidget(self.net_gateway_warn)
        gw_row.addStretch()
        fl.addRow(_req("网关 (IPv4)"), gw_row)

        self.net_ipv6_cb = QCheckBox("启用 IPv6")
        self.net_ipv6_cb.setStyleSheet("QCheckBox { padding: 4px 8px; }")
        self.net_ipv6_cb.toggled.connect(self._toggle_ipv6)

        self._lbl_subnet_v6 = _lbl("子网 (IPv6)")
        self.net_subnet_v6 = QLineEdit()
        self.net_subnet_v6.setPlaceholderText("例如: 2001:14:23::1/64")
        self.net_subnet_v6.setStyleSheet(STYLE_INPUT)
        self.net_subnet_v6.setFixedWidth(input_max)
        sub6_row = QHBoxLayout()
        sub6_row.setSpacing(0)
        sub6_row.addWidget(self.net_subnet_v6)
        sub6_row.addWidget(self.net_ipv6_cb)
        sub6_row.addStretch()
        fl.addRow(self._lbl_subnet_v6, sub6_row)

        self._lbl_gateway_v6 = _lbl("网关 (IPv6)")
        self.net_gateway_v6 = QLineEdit()
        self.net_gateway_v6.setPlaceholderText("例如: 2001:14:23::1")
        self.net_gateway_v6.setStyleSheet(STYLE_INPUT)
        self.net_gateway_v6.setFixedWidth(input_max)
        fl.addRow(self._lbl_gateway_v6, self.net_gateway_v6)
        self._set_ipv6_enabled(False)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.create_btn = QPushButton("🌐 创建网络")
        self.create_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self.create_btn.clicked.connect(self._do_create)
        self.create_btn.setEnabled(False)
        btn_row.addWidget(self.create_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(STYLE_BTN_CANCEL)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        fl.addRow(btn_row)

    def _style_combos(self):
        arrow_path = os.path.join(os.path.dirname(__file__), "arrow_down.png")
        if not os.path.exists(arrow_path):
            pix = QPixmap(12, 8)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QColor("#636e72"))
            p.setBrush(QColor("#636e72"))
            p.drawPolygon(QPolygon([QPoint(1, 1), QPoint(6, 7), QPoint(11, 1)]))
            p.end()
            pix.save(arrow_path)
        cs = f"""
            QComboBox {{
                border: none; border-bottom: 2px solid #dfe6e9;
                padding: 6px 4px; font-size: 13px; background: #f8f9fa;
            }}
            QComboBox:focus {{ border-bottom: 2px solid #0984e3; }}
            QComboBox::drop-down {{ border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: top right; }}
            QComboBox::down-arrow {{ image: url("{arrow_path.replace(chr(92), '/')}"); width: 12px; height: 8px; }}
        """
        for cb in (self.net_driver, self.net_nic):
            cb.setStyleSheet(cs)
            cb.setItemDelegate(_ComboDelegate(cb))
            v = cb.view()
            if v:
                v.setStyleSheet("""
                    QAbstractItemView {
                        background: white; color: #333; outline: none;
                        border: 1px solid #dfe6e9;
                    }
                    QAbstractItemView::item {
                        min-height: 24px; padding: 2px 8px;
                    }
                    QAbstractItemView::item:selected {
                        background: #0984e3; color: white;
                    }
                """)

    def _populate_combos(self):
        self.net_nic.clear()
        sorted_ifaces = sorted(self.interfaces,
                               key=lambda n: n in ("bridge", "host", "none"))
        for iface in sorted_ifaces:
            self.net_nic.addItem(iface)
        self.net_nic.setCurrentIndex(-1)

    def _validate_net_name(self):
        name = self.net_name.text().strip()
        if name in self.existing_networks:
            self.net_name_warn.setText("⚠ 该网络名已存在")
        else:
            self.net_name_warn.setText("")
        self._check_ready()

    def _validate_subnet(self):
        import re as _re
        sub = self.net_subnet_v4.text().strip()
        if sub:
            m = _re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/(\d{1,2})$", sub)
            if not m:
                self.net_subnet_warn.setText("⚠ 格式错误，示例: 10.14.23.0/24")
                self._update_btn(False)
                return
            octets = [int(m.group(i)) for i in range(1, 5)]
            mask = int(m.group(5))
            if any(o > 255 for o in octets) or mask > 32:
                self.net_subnet_warn.setText("⚠ IP或掩码超出范围")
                self._update_btn(False)
                return
        if sub in self.existing_subnets:
            self.net_subnet_warn.setText("⚠ 该网段已被占用")
            self._update_btn(False)
            return
        self.net_subnet_warn.setText("")
        self._check_ready()

    def _validate_gateway(self):
        import re as _re
        gw = self.net_gateway_v4.text().strip()
        if gw:
            m = _re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", gw)
            if not m:
                self.net_gateway_warn.setText("⚠ 格式错误，示例: 10.14.23.1")
                self._update_btn(False)
                return
            if any(int(m.group(i)) > 255 for i in range(1, 5)):
                self.net_gateway_warn.setText("⚠ IP超出范围")
                self._update_btn(False)
                return
        self.net_gateway_warn.setText("")
        self._check_ready()

    def _update_btn(self, enabled):
        self.create_btn.setEnabled(enabled)

    def _check_ready(self):
        name_ok = bool(self.net_name.text().strip()) and not self.net_name_warn.text()
        sub_ok = bool(self.net_subnet_v4.text().strip()) and not self.net_subnet_warn.text()
        gw_ok = bool(self.net_gateway_v4.text().strip()) and not self.net_gateway_warn.text()
        nic_ok = bool(self.net_nic.currentText().strip())
        self.create_btn.setEnabled(name_ok and sub_ok and gw_ok and nic_ok)

    def _set_ipv6_enabled(self, enabled):
        gray = """
            QLineEdit {
                border: none; border-bottom: 2px solid #dfe6e9;
                background: transparent; color: #b2bec3;
                font-size: 13px; padding: 6px 4px;
            }
        """
        style = STYLE_INPUT if enabled else gray
        self.net_subnet_v6.setStyleSheet(style)
        self.net_gateway_v6.setStyleSheet(style)
        self.net_subnet_v6.setEnabled(enabled)
        self.net_gateway_v6.setEnabled(enabled)
        if enabled:
            self._lbl_subnet_v6.setText('<span style="color:red">*</span>子网 (IPv6)')
            self._lbl_gateway_v6.setText('<span style="color:red">*</span>网关 (IPv6)')
        else:
            self._lbl_subnet_v6.setText("子网 (IPv6)")
            self._lbl_gateway_v6.setText("网关 (IPv6)")

    def _toggle_ipv6(self, checked):
        self._set_ipv6_enabled(checked)
        self._check_ready()

    def _do_create(self):
        name = self.net_name.text().strip()
        driver = self.net_driver.currentText().strip()
        nic = self.net_nic.currentText().strip()
        subnet = self.net_subnet_v4.text().strip()
        gateway = self.net_gateway_v4.text().strip()
        cmd = f"docker network create -d {driver}"
        if subnet:
            cmd += f" --subnet={subnet}"
        if gateway:
            cmd += f" --gateway={gateway}"
        if nic:
            cmd += f" -o parent={nic}"
        if self.net_ipv6_cb.isChecked():
            sub6 = self.net_subnet_v6.text().strip()
            gw6 = self.net_gateway_v6.text().strip()
            if sub6:
                cmd += f" --ipv6 --subnet={sub6}"
            if gw6:
                cmd += f" --gateway={gw6}"
        cmd += f" {name}"
        self._command = cmd
        self.accept()

    def get_command(self):
        return self._command

    def get_net_name(self):
        return self.net_name.text().strip()

class CreateContainerDialog(QDialog):
    def __init__(self, parent, images, networks):
        super().__init__(parent)
        self.setWindowTitle("创建容器")
        self.setMinimumWidth(520)
        self._command = None
        self._name_manually_edited = False
        self._last_hostname = ""
        _bottom = {"bridge", "host", "none"}
        networks = [n for n in networks if n.get("name", "") not in _bottom] + \
                   [n for n in networks if n.get("name", "") in _bottom]
        fl = QFormLayout(self)
        self._fl = fl
        fl.setSpacing(6)
        fl.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        fl.setContentsMargins(20, 16, 20, 16)
        input_max = 300

        def _lbl(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 13px;")
            return lbl

        def _req(text):
            lbl = QLabel(f'<span style="color:red">*</span>{text}')
            lbl.setStyleSheet("font-size: 13px;")
            return lbl

        # ── 容器类型 ──
        self.type_group = QGroupBox()
        self.type_group.setStyleSheet("QGroupBox { border: none; }")
        type_row = QHBoxLayout(self.type_group)
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(16)
        self.cont_type = QButtonGroup(self)
        for label, val in [("普通(无限制)", 1), ("普通(限制)", 2), ("DB", 3)]:
            rb = QRadioButton(label)
            rb.setStyleSheet("font-size: 13px;")
            type_row.addWidget(rb)
            self.cont_type.addButton(rb, val)
        self.cont_type.button(1).setChecked(True)
        self.cont_type.idClicked.connect(self._type_changed)
        fl.addRow("容器类型:", self.type_group)

        # ── 主机名称 ──
        self.cont_hostname = QLineEdit()
        self.cont_hostname.setPlaceholderText("例如: BJHYDX_SLR01")
        self.cont_hostname.setStyleSheet(STYLE_INPUT)
        self.cont_hostname.setFixedWidth(input_max)
        self.cont_hostname.textChanged.connect(self._on_hostname_changed)
        fl.addRow(_req("主机名称"), self.cont_hostname)

        # ── 容器名称 ──
        self.cont_name = QLineEdit()
        self.cont_name.setPlaceholderText("默认与主机名相同")
        self.cont_name.setStyleSheet(STYLE_INPUT)
        self.cont_name.setFixedWidth(input_max)
        self.cont_name.textChanged.connect(self._on_name_edited)
        self.cont_name.textChanged.connect(self._validate_name)
        self.cont_name_warn = QLabel("")
        self.cont_name_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        name_row = QHBoxLayout()
        name_row.setSpacing(0)
        name_row.addWidget(self.cont_name)
        name_row.addWidget(self.cont_name_warn)
        name_row.addStretch()
        fl.addRow(_req("容器名称"), name_row)

        # ── 网络 ──
        self.cont_net = QComboBox()
        self.cont_net.setEditable(True)
        self.cont_net.setFixedWidth(input_max)
        for n in networks:
            self.cont_net.addItem(n.get("name", ""))
        self.cont_net.setCurrentIndex(-1)
        self.cont_net.currentTextChanged.connect(self._check_ready)
        fl.addRow(_req("网络"), self.cont_net)

        # ── IPv4 ──
        self.cont_ip = QLineEdit()
        self.cont_ip.setPlaceholderText("例如: 10.9.15.130")
        self.cont_ip.setStyleSheet(STYLE_INPUT)
        self.cont_ip.setFixedWidth(input_max)
        self.cont_ip.textChanged.connect(self._validate_ipv4)
        self.cont_ip_warn = QLabel("")
        self.cont_ip_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        ip_row = QHBoxLayout()
        ip_row.setSpacing(0)
        ip_row.addWidget(self.cont_ip)
        ip_row.addWidget(self.cont_ip_warn)
        ip_row.addStretch()
        fl.addRow(_req("指定IPv4"), ip_row)

        # ── IPv6 ──
        self.cont_ip6_cb = QCheckBox("指定IPv6")
        self.cont_ip6_cb.setStyleSheet("QCheckBox { padding: 4px 8px; }")
        self.cont_ip6_cb.toggled.connect(self._toggle_ipv6)
        self._lbl_ip6 = _lbl("IPv6地址")
        self.cont_ip6 = QLineEdit()
        self.cont_ip6.setPlaceholderText("例如: 2001:14:23::24")
        self.cont_ip6.setStyleSheet(STYLE_INPUT)
        self.cont_ip6.setFixedWidth(input_max)
        self.cont_ip6.textChanged.connect(self._validate_ipv6)
        self.cont_ip6_warn = QLabel("")
        self.cont_ip6_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        ip6_row = QHBoxLayout()
        ip6_row.setSpacing(0)
        ip6_row.addWidget(self.cont_ip6)
        ip6_row.addWidget(self.cont_ip6_warn)
        ip6_row.addWidget(self.cont_ip6_cb)
        ip6_row.addStretch()
        fl.addRow(self._lbl_ip6, ip6_row)
        self._set_ipv6_enabled(False)

        # ── 镜像 ──
        self.cont_image = QComboBox()
        self.cont_image.setEditable(True)
        self.cont_image.setPlaceholderText("选择或输入镜像名")
        self.cont_image.setFixedWidth(input_max)
        for img in images:
            tag = img.get("tag", "latest")
            self.cont_image.addItem(f"{img.get('repo', '')}:{tag}")
        self.cont_image.currentTextChanged.connect(self._check_ready)
        fl.addRow(_req("镜像"), self.cont_image)

        # ── CPU ──
        self.cont_cpu = QLineEdit()
        self.cont_cpu.setPlaceholderText("正整数，例如: 4")
        self.cont_cpu.setStyleSheet(STYLE_INPUT)
        self.cont_cpu.setFixedWidth(input_max)
        self.cont_cpu.textChanged.connect(self._validate_cpu)
        self.cont_cpu_warn = QLabel("")
        self.cont_cpu_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        cpu_row = QHBoxLayout()
        cpu_row.setSpacing(0)
        cpu_row.addWidget(self.cont_cpu)
        cpu_row.addWidget(self.cont_cpu_warn)
        cpu_row.addStretch()
        self._lbl_cpu = _lbl("CPU数量")
        fl.addRow(self._lbl_cpu, cpu_row)
        self._cpu_row = cpu_row

        # ── 内存 ──
        self.cont_mem = QLineEdit()
        self.cont_mem.setPlaceholderText("正整数(GB)，例如: 8")
        self.cont_mem.setStyleSheet(STYLE_INPUT)
        self.cont_mem.setFixedWidth(input_max)
        self.cont_mem.textChanged.connect(self._validate_mem)
        self.cont_mem_warn = QLabel("")
        self.cont_mem_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        mem_row = QHBoxLayout()
        mem_row.setSpacing(0)
        mem_row.addWidget(self.cont_mem)
        mem_row.addWidget(self.cont_mem_warn)
        mem_row.addStretch()
        self._lbl_mem = _lbl("内存(GB)")
        fl.addRow(self._lbl_mem, mem_row)
        self._mem_row = mem_row

        # ── 共享内存 ──
        self.cont_shm = QLineEdit()
        self.cont_shm.setText("8G")
        self.cont_shm.setReadOnly(True)
        self.cont_shm.setFixedWidth(input_max)
        self.cont_shm.setStyleSheet(STYLE_INPUT)
        self._lbl_shm = _lbl("共享内存")
        fl.addRow(self._lbl_shm, self.cont_shm)

        # ── 卷挂载 ──
        self.cont_volumes = QLineEdit()
        self.cont_volumes.setPlaceholderText("多个以逗号分隔")
        self.cont_volumes.setStyleSheet(STYLE_INPUT)
        self.cont_volumes.setFixedWidth(input_max)
        self.cont_volumes.setText("/opt/tar/:/opt/tar/,/sys/fs/cgroup:/sys/fs/cgroup:ro")
        fl.addRow(_lbl("卷挂载"), self.cont_volumes)

        # ── 重启策略 ──
        self.cont_restart = QComboBox()
        self.cont_restart.addItems(["always", "no", "on-failure", "unless-stopped"])
        self.cont_restart.setCurrentText("always")
        self.cont_restart.setFixedWidth(input_max)
        fl.addRow(_lbl("重启策略"), self.cont_restart)

        # ── 第二网卡 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #dfe6e9; max-height: 1px; margin: 2px 0;")
        fl.addRow(sep)

        self.nic2_cb = QCheckBox("添加第二网卡")
        self.nic2_cb.setStyleSheet("QCheckBox { padding: 4px 0; font-size: 13px; }")
        self.nic2_cb.toggled.connect(self._toggle_nic2)
        fl.addRow("", self.nic2_cb)

        self.nic2_group = QWidget()
        self.nic2_group.setVisible(False)
        n2l = QFormLayout(self.nic2_group)
        n2l.setSpacing(6)
        n2l.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        n2l.setContentsMargins(0, 0, 0, 0)

        self.nic2_net = QComboBox()
        self.nic2_net.setFixedWidth(input_max)
        for n in networks:
            self.nic2_net.addItem(n.get("name", ""))
        self.nic2_net.setCurrentIndex(-1)
        self.nic2_net.currentTextChanged.connect(self._check_ready)
        n2l.addRow(_req("网络(网卡#2)"), self.nic2_net)

        self.nic2_ip = QLineEdit()
        self.nic2_ip.setPlaceholderText("例如: 10.9.15.131")
        self.nic2_ip.setStyleSheet(STYLE_INPUT)
        self.nic2_ip.setFixedWidth(input_max)
        self.nic2_ip.textChanged.connect(self._validate_nic2_ipv4)
        self.nic2_ip_warn = QLabel("")
        self.nic2_ip_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        n2_ip_row = QHBoxLayout()
        n2_ip_row.setSpacing(0)
        n2_ip_row.addWidget(self.nic2_ip)
        n2_ip_row.addWidget(self.nic2_ip_warn)
        n2_ip_row.addStretch()
        n2l.addRow(_req("指定IPv4"), n2_ip_row)

        self.nic2_ip6_cb = QCheckBox("指定IPv6")
        self.nic2_ip6_cb.setStyleSheet("QCheckBox { padding: 4px 8px; }")
        self.nic2_ip6_cb.toggled.connect(self._toggle_nic2_ipv6)

        self._lbl_nic2_ip6 = _lbl("IPv6地址")
        self.nic2_ip6 = QLineEdit()
        self.nic2_ip6.setPlaceholderText("例如: 2001:14:23::25")
        self.nic2_ip6.setStyleSheet(STYLE_INPUT)
        self.nic2_ip6.setFixedWidth(input_max)
        self.nic2_ip6.textChanged.connect(self._validate_nic2_ipv6)
        self.nic2_ip6_warn = QLabel("")
        self.nic2_ip6_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        n2_ip6_row = QHBoxLayout()
        n2_ip6_row.setSpacing(0)
        n2_ip6_row.addWidget(self.nic2_ip6)
        n2_ip6_row.addWidget(self.nic2_ip6_warn)
        n2_ip6_row.addWidget(self.nic2_ip6_cb)
        n2_ip6_row.addStretch()
        n2l.addRow(self._lbl_nic2_ip6, n2_ip6_row)
        self._set_nic2_ipv6_enabled(False)

        fl.addRow(self.nic2_group)

        self._style_combos()

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.create_btn = QPushButton("创建")
        self.create_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self.create_btn.clicked.connect(self._do_create)
        self.create_btn.setEnabled(False)
        btn_row.addWidget(self.create_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(STYLE_BTN_CANCEL)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        fl.addRow(btn_row)

        self._cpu_mem_visible = False
        self._shm_visible = False
        self._check_ready()
        self._fl.setRowVisible(self._cpu_row, False)
        self._fl.setRowVisible(self._mem_row, False)
        self._fl.setRowVisible(self.cont_shm, False)

    # ── 第二网卡 ──
    def _toggle_nic2(self, checked):
        self.nic2_group.setVisible(checked)
        if not checked:
            self.nic2_net.setCurrentIndex(-1)
            self.nic2_ip.clear()
            self.nic2_ip_warn.setText("")
            self.nic2_ip6_cb.setChecked(False)
            self.nic2_ip6.clear()
            self.nic2_ip6_warn.setText("")
        self._check_ready()

    def _set_nic2_ipv6_enabled(self, enabled):
        gray = """
            QLineEdit {
                border: none; border-bottom: 2px solid #dfe6e9;
                background: transparent; color: #b2bec3;
                font-size: 13px; padding: 6px 4px;
            }
        """
        self.nic2_ip6.setStyleSheet(STYLE_INPUT if enabled else gray)
        self.nic2_ip6.setEnabled(enabled)
        if enabled:
            self._lbl_nic2_ip6.setText('<span style="color:red">*</span>IPv6地址')
        else:
            self._lbl_nic2_ip6.setText("IPv6地址")
        if not enabled:
            self.nic2_ip6.clear()
            self.nic2_ip6_warn.setText("")

    def _toggle_nic2_ipv6(self, checked):
        self._set_nic2_ipv6_enabled(checked)
        self._check_ready()

    def _validate_nic2_ipv4(self):
        import re as _re
        text = self.nic2_ip.text().strip()
        if not text:
            self.nic2_ip_warn.setText("")
            self._check_ready()
            return
        m = _re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", text)
        if not m or any(int(m.group(i)) > 255 for i in range(1, 5)):
            self.nic2_ip_warn.setText("⚠ IPv4 格式错误")
        else:
            self.nic2_ip_warn.setText("")
        self._check_ready()

    def _validate_nic2_ipv6(self):
        import re as _re
        text = self.nic2_ip6.text().strip()
        if not text or not self.nic2_ip6.isEnabled():
            self.nic2_ip6_warn.setText("")
            self._check_ready()
            return
        m = _re.match(r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$", text)
        if not m:
            self.nic2_ip6_warn.setText("⚠ IPv6 格式错误")
        else:
            self.nic2_ip6_warn.setText("")
        self._check_ready()

    # ── 风格 ──
    def _set_ipv6_enabled(self, enabled):
        gray = """
            QLineEdit {
                border: none; border-bottom: 2px solid #dfe6e9;
                background: transparent; color: #b2bec3;
                font-size: 13px; padding: 6px 4px;
            }
        """
        style = STYLE_INPUT if enabled else gray
        self.cont_ip6.setStyleSheet(style)
        self.cont_ip6.setEnabled(enabled)
        if enabled:
            self._lbl_ip6.setText('<span style="color:red">*</span>IPv6地址')
        else:
            self._lbl_ip6.setText("IPv6地址")

    def _style_combos(self):
        arrow_path = os.path.join(os.path.dirname(__file__), "arrow_down.png")
        if not os.path.exists(arrow_path):
            pix = QPixmap(12, 8)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QColor("#636e72"))
            p.setBrush(QColor("#636e72"))
            p.drawPolygon(QPolygon([QPoint(1, 1), QPoint(6, 7), QPoint(11, 1)]))
            p.end()
            pix.save(arrow_path)
        cs = f"""
            QComboBox {{
                border: none; border-bottom: 2px solid #dfe6e9;
                padding: 6px 4px; font-size: 13px; background: #f8f9fa;
            }}
            QComboBox:focus {{ border-bottom: 2px solid #0984e3; }}
            QComboBox::drop-down {{ border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: top right; }}
            QComboBox::down-arrow {{ image: url("{arrow_path.replace(chr(92), '/')}"); width: 12px; height: 8px; }}
        """
        for cb in (self.cont_image, self.cont_net, self.cont_restart, self.nic2_net):
            cb.setStyleSheet(cs)
            cb.setItemDelegate(_ComboDelegate(cb))
            v = cb.view()
            if v:
                v.setStyleSheet("""
                    QAbstractItemView {
                        background: white; color: #333; outline: none;
                        border: 1px solid #dfe6e9;
                    }
                    QAbstractItemView::item {
                        min-height: 24px; padding: 2px 8px;
                    }
                    QAbstractItemView::item:selected {
                        background: #0984e3; color: white;
                    }
                """)

    # ── 交互 ──
    def _on_hostname_changed(self, text):
        self._last_hostname = text
        if not self._name_manually_edited:
            self.cont_name.setText(text)
        self._check_ready()

    def _on_name_edited(self, text):
        if text != self._last_hostname:
            self._name_manually_edited = True

    def _type_changed(self, type_id):
        show_cpu_mem = type_id in (2, 3)
        show_shm = type_id == 3
        self._cpu_mem_visible = show_cpu_mem
        self._shm_visible = show_shm
        self._fl.setRowVisible(self._cpu_row, show_cpu_mem)
        self._fl.setRowVisible(self._mem_row, show_cpu_mem)
        self._fl.setRowVisible(self.cont_shm, show_shm)
        if show_cpu_mem:
            self._lbl_cpu.setText('<span style="color:red">*</span>CPU数量')
            self._lbl_mem.setText('<span style="color:red">*</span>内存(GB)')
        else:
            self._lbl_cpu.setText("CPU数量")
            self._lbl_mem.setText("内存(GB)")
            self.cont_cpu.clear()
            self.cont_mem.clear()
            self.cont_cpu_warn.setText("")
            self.cont_mem_warn.setText("")
        if show_shm:
            self._lbl_shm.setText('<span style="color:red">*</span>共享内存')
        else:
            self._lbl_shm.setText("共享内存")
        self._check_ready()

    def _toggle_ipv6(self, checked):
        self._set_ipv6_enabled(checked)
        self._check_ready()

    # ── 校验 ──
    def _validate_name(self):
        text = self.cont_name.text()
        if " " in text:
            self.cont_name_warn.setText("⚠ 容器名不能包含空格")
        else:
            self.cont_name_warn.setText("")
        self._check_ready()

    def _validate_ipv4(self):
        import re as _re
        text = self.cont_ip.text().strip()
        if not text:
            self.cont_ip_warn.setText("")
            self._check_ready()
            return
        m = _re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", text)
        if not m or any(int(m.group(i)) > 255 for i in range(1, 5)):
            self.cont_ip_warn.setText("⚠ IPv4 格式错误")
        else:
            self.cont_ip_warn.setText("")
        self._check_ready()

    def _validate_ipv6(self):
        import re as _re
        text = self.cont_ip6.text().strip()
        if not text or not self.cont_ip6.isEnabled():
            self.cont_ip6_warn.setText("")
            self._check_ready()
            return
        m = _re.match(r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$", text)
        if not m:
            self.cont_ip6_warn.setText("⚠ IPv6 格式错误")
        else:
            self.cont_ip6_warn.setText("")
        self._check_ready()

    def _validate_cpu(self):
        text = self.cont_cpu.text().strip()
        if not text or not self._cpu_mem_visible:
            self.cont_cpu_warn.setText("")
            self._check_ready()
            return
        if not text.isdigit() or int(text) < 1:
            self.cont_cpu_warn.setText("⚠ 必须是正整数")
        else:
            self.cont_cpu_warn.setText("")
        self._check_ready()

    def _validate_mem(self):
        text = self.cont_mem.text().strip()
        if not text or not self._cpu_mem_visible:
            self.cont_mem_warn.setText("")
            self._check_ready()
            return
        if not text.isdigit() or int(text) < 1:
            self.cont_mem_warn.setText("⚠ 必须是正整数")
        else:
            self.cont_mem_warn.setText("")
        self._check_ready()

    def _check_ready(self):
        ok = True
        if not self.cont_hostname.text().strip():
            ok = False
        if not self.cont_name.text().strip() or self.cont_name_warn.text():
            ok = False
        if not self.cont_net.currentText().strip():
            ok = False
        if not self.cont_image.currentText().strip():
            ok = False
        if self.cont_ip.text().strip() and self.cont_ip_warn.text():
            ok = False
        if self.cont_ip6.isEnabled() and (not self.cont_ip6.text().strip() or self.cont_ip6_warn.text()):
            ok = False
        if self._cpu_mem_visible:
            if not self.cont_cpu.text().strip() or self.cont_cpu_warn.text():
                ok = False
            if not self.cont_mem.text().strip() or self.cont_mem_warn.text():
                ok = False
        if self._shm_visible and not self.cont_shm.text().strip():
            ok = False
        if self.nic2_cb.isChecked():
            if not self.nic2_net.currentText().strip():
                ok = False
            if self.nic2_ip.text().strip() and self.nic2_ip_warn.text():
                ok = False
            if self.nic2_ip6.isEnabled() and (not self.nic2_ip6.text().strip() or self.nic2_ip6_warn.text()):
                ok = False
        self.create_btn.setEnabled(ok)

    def _do_create(self):
        cmd = "docker run -d"
        name = self.cont_name.text().strip() or self.cont_hostname.text().strip()
        cmd += f" --name {name}"
        cmd += f" --hostname {self.cont_hostname.text().strip()}"
        cmd += f" --restart {self.cont_restart.currentText().strip()}"
        net = self.cont_net.currentText().strip()
        cmd += f" --network {net}"
        ip = self.cont_ip.text().strip()
        if ip:
            cmd += f" --ip {ip}"
        if self.cont_ip6.isEnabled():
            ip6 = self.cont_ip6.text().strip()
            if ip6:
                cmd += f" --ip6 {ip6}"
        typ = self.cont_type.checkedId()
        if typ in (2, 3):
            cpu = self.cont_cpu.text().strip()
            mem = self.cont_mem.text().strip()
            if cpu:
                cmd += f" --cpus {cpu}"
            if mem:
                cmd += f" --memory {mem}g"
        if typ == 3:
            cmd += " --shm-size 8g"
        vols = self.cont_volumes.text().strip()
        if vols:
            for v in vols.split(","):
                v = v.strip()
                if v:
                    cmd += f" -v {v}"
        image = self.cont_image.currentText().strip()
        cmd += f" {image}"
        if self.nic2_cb.isChecked():
            n2_net = self.nic2_net.currentText().strip()
            if n2_net:
                n2_cmd = f"docker network connect {n2_net} {name}"
                n2_ip = self.nic2_ip.text().strip()
                if n2_ip:
                    n2_cmd += f" --ip {n2_ip}"
                if self.nic2_ip6.isEnabled():
                    n2_ip6 = self.nic2_ip6.text().strip()
                    if n2_ip6:
                        n2_cmd += f" --ip6 {n2_ip6}"
                cmd += f" && {n2_cmd}"
        self._command = cmd
        self.accept()

    def get_command(self):
        return self._command


class AddNicDialog(QDialog):
    def __init__(self, parent, containers, networks, selected_container=None):
        super().__init__(parent)
        self.setWindowTitle("添加网卡")
        self.setMinimumWidth(520)
        self._command = None
        _bottom = {"bridge", "host", "none"}
        containers = [c for c in containers if c.get("name", "") not in _bottom] + \
                     [c for c in containers if c.get("name", "") in _bottom]
        networks = [n for n in networks if n.get("name", "") not in _bottom] + \
                   [n for n in networks if n.get("name", "") in _bottom]
        input_max = 300

        fl = QFormLayout(self)
        fl.setSpacing(6)
        fl.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        fl.setContentsMargins(20, 16, 20, 16)

        def _lbl(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 13px;")
            return lbl

        def _req(text):
            lbl = QLabel(f'<span style="color:red">*</span>{text}')
            lbl.setStyleSheet("font-size: 13px;")
            return lbl

        # ── 容器 ──
        self.nic_container = QComboBox()
        self.nic_container.setFixedWidth(input_max)
        for c in containers:
            self.nic_container.addItem(c.get("name", ""))
        if selected_container:
            idx = self.nic_container.findText(selected_container)
            if idx >= 0:
                self.nic_container.setCurrentIndex(idx)
        else:
            self.nic_container.setCurrentIndex(-1)
        self.nic_container.currentTextChanged.connect(self._check_ready)
        fl.addRow(_req("容器"), self.nic_container)

        # ── 网络 ──
        self.nic_network = QComboBox()
        self.nic_network.setFixedWidth(input_max)
        for n in networks:
            self.nic_network.addItem(n.get("name", ""))
        self.nic_network.setCurrentIndex(-1)
        self.nic_network.currentTextChanged.connect(self._check_ready)
        fl.addRow(_req("网络"), self.nic_network)

        # ── IPv4 ──
        self.nic_ip = QLineEdit()
        self.nic_ip.setPlaceholderText("例如: 10.9.15.131")
        self.nic_ip.setStyleSheet(STYLE_INPUT)
        self.nic_ip.setFixedWidth(input_max)
        self.nic_ip.textChanged.connect(self._validate_nic_ipv4)
        self.nic_ip_warn = QLabel("")
        self.nic_ip_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        ip_row = QHBoxLayout()
        ip_row.setSpacing(0)
        ip_row.addWidget(self.nic_ip)
        ip_row.addWidget(self.nic_ip_warn)
        ip_row.addStretch()
        fl.addRow(_lbl("指定IPv4"), ip_row)

        # ── IPv6 ──
        self.nic_ip6_cb = QCheckBox("指定IPv6")
        self.nic_ip6_cb.setStyleSheet("QCheckBox { padding: 4px 8px; }")
        self.nic_ip6_cb.toggled.connect(self._toggle_nic_ipv6)
        self._lbl_nic_ip6 = _lbl("IPv6地址")
        self.nic_ip6 = QLineEdit()
        self.nic_ip6.setPlaceholderText("例如: 2001:14:23::25")
        self.nic_ip6.setStyleSheet(STYLE_INPUT)
        self.nic_ip6.setFixedWidth(input_max)
        self.nic_ip6.textChanged.connect(self._validate_nic_ipv6)
        self.nic_ip6_warn = QLabel("")
        self.nic_ip6_warn.setStyleSheet("color: #d63031; font-size: 10px; padding-left: 8px;")
        ip6_row = QHBoxLayout()
        ip6_row.setSpacing(0)
        ip6_row.addWidget(self.nic_ip6)
        ip6_row.addWidget(self.nic_ip6_warn)
        ip6_row.addWidget(self.nic_ip6_cb)
        ip6_row.addStretch()
        fl.addRow(self._lbl_nic_ip6, ip6_row)
        self._set_nic_ipv6_enabled(False)

        self._style_combos()

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.ok_btn = QPushButton("连接")
        self.ok_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self.ok_btn.clicked.connect(self._do_add)
        self.ok_btn.setEnabled(False)
        btn_row.addWidget(self.ok_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(STYLE_BTN_CANCEL)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        fl.addRow(btn_row)

        self._check_ready()

    # ── 风格 ──
    def _style_combos(self):
        arrow_path = os.path.join(os.path.dirname(__file__), "arrow_down.png")
        if not os.path.exists(arrow_path):
            pix = QPixmap(12, 8)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QColor("#636e72"))
            p.setBrush(QColor("#636e72"))
            p.drawPolygon(QPolygon([QPoint(1, 1), QPoint(6, 7), QPoint(11, 1)]))
            p.end()
            pix.save(arrow_path)
        cs = f"""
            QComboBox {{
                border: none; border-bottom: 2px solid #dfe6e9;
                padding: 6px 4px; font-size: 13px; background: #f8f9fa;
            }}
            QComboBox:focus {{ border-bottom: 2px solid #0984e3; }}
            QComboBox::drop-down {{ border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: top right; }}
            QComboBox::down-arrow {{ image: url("{arrow_path.replace(chr(92), '/')}"); width: 12px; height: 8px; }}
        """
        for cb in (self.nic_container, self.nic_network):
            cb.setStyleSheet(cs)
            cb.setItemDelegate(_ComboDelegate(cb))
            v = cb.view()
            if v:
                v.setStyleSheet("""
                    QAbstractItemView {
                        background: white; color: #333; outline: none;
                        border: 1px solid #dfe6e9;
                    }
                    QAbstractItemView::item {
                        min-height: 24px; padding: 2px 8px;
                    }
                    QAbstractItemView::item:selected {
                        background: #0984e3; color: white;
                    }
                """)

    # ── IPv6 ──
    def _set_nic_ipv6_enabled(self, enabled):
        gray = """
            QLineEdit {
                border: none; border-bottom: 2px solid #dfe6e9;
                background: transparent; color: #b2bec3;
                font-size: 13px; padding: 6px 4px;
            }
        """
        self.nic_ip6.setStyleSheet(STYLE_INPUT if enabled else gray)
        self.nic_ip6.setEnabled(enabled)
        if enabled:
            self._lbl_nic_ip6.setText('<span style="color:red">*</span>IPv6地址')
        else:
            self._lbl_nic_ip6.setText("IPv6地址")
        if not enabled:
            self.nic_ip6.clear()
            self.nic_ip6_warn.setText("")

    def _toggle_nic_ipv6(self, checked):
        self._set_nic_ipv6_enabled(checked)
        self._check_ready()

    # ── 校验 ──
    def _validate_nic_ipv4(self):
        import re as _re
        text = self.nic_ip.text().strip()
        if not text:
            self.nic_ip_warn.setText("")
            self._check_ready()
            return
        m = _re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", text)
        if not m or any(int(m.group(i)) > 255 for i in range(1, 5)):
            self.nic_ip_warn.setText("⚠ IPv4 格式错误")
        else:
            self.nic_ip_warn.setText("")
        self._check_ready()

    def _validate_nic_ipv6(self):
        import re as _re
        text = self.nic_ip6.text().strip()
        if not text or not self.nic_ip6.isEnabled():
            self.nic_ip6_warn.setText("")
            self._check_ready()
            return
        m = _re.match(r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$", text)
        if not m:
            self.nic_ip6_warn.setText("⚠ IPv6 格式错误")
        else:
            self.nic_ip6_warn.setText("")
        self._check_ready()

    def _check_ready(self):
        ok = True
        if not self.nic_container.currentText().strip():
            ok = False
        if not self.nic_network.currentText().strip():
            ok = False
        if self.nic_ip.text().strip() and self.nic_ip_warn.text():
            ok = False
        if self.nic_ip6.isEnabled() and (not self.nic_ip6.text().strip() or self.nic_ip6_warn.text()):
            ok = False
        self.ok_btn.setEnabled(ok)

    def _do_add(self):
        container = self.nic_container.currentText().strip()
        network = self.nic_network.currentText().strip()
        if not container or not network:
            QMessageBox.warning(self, "提示", "请选择容器和网络")
            return
        cmd = f"docker network connect {network} {container}"
        ip = self.nic_ip.text().strip()
        if ip:
            cmd += f" --ip {ip}"
        ip6 = self.nic_ip6.text().strip()
        if ip6:
            cmd += f" --ip6 {ip6}"
        self._command = cmd
        self.accept()

    def get_command(self):
        return self._command


class ContainerDetailDialog(QDialog):
    def __init__(self, parent, cid, name, image, status, created, ssh_params):
        super().__init__(parent)
        self.setWindowTitle(f"📦 容器详情 — {name}")
        self.setMinimumWidth(580)
        self._cid = cid
        self._container_name = name
        self._ssh_params = ssh_params
        self._net_data = []
        self._inspect_worker = None

        vl = QVBoxLayout(self)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(12)

        # ── Info section ──
        info_group = QGroupBox("基本信息")
        info_group.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 13px; border: 1px solid #e0e0e0;
                        border-radius: 6px; margin-top: 12px; padding: 16px 12px 8px 12px; background: white; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;
                               padding: 0 8px; color: #2d3436; }
        """)
        fl = QFormLayout(info_group)
        fl.setSpacing(8)
        fl.setContentsMargins(12, 6, 12, 6)
        fl.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        def _info_row(label, value):
            lbl = QLabel(value)
            lbl.setStyleSheet("font-size: 14px;")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            key = QLabel(label + ":")
            key.setStyleSheet("font-size: 14px; font-weight: bold;")
            fl.addRow(key, lbl)

        _info_row("容器ID", cid[:16] + "…" if len(cid) > 16 else cid)
        _info_row("容器名称", name)
        status_lbl = QLabel(status)
        status_lbl.setStyleSheet("font-size: 14px;")
        status_key = QLabel("容器状态:")
        status_key.setStyleSheet("font-size: 14px; font-weight: bold;")
        fl.addRow(status_key, status_lbl)
        _info_row("创建时间", created[:16] if len(created) > 16 else created)
        _info_row("关联镜像", image)
        vl.addWidget(info_group)

        # ── Network section ──
        self._net_group = QGroupBox("网卡管理")
        self._net_group.setStyleSheet(info_group.styleSheet())
        self._net_vl = QVBoxLayout(self._net_group)
        self._net_vl.setSpacing(6)
        self._net_vl.setContentsMargins(12, 6, 12, 6)
        self._net_placeholder = QLabel("加载中…")
        self._net_placeholder.setStyleSheet("color: #b2bec3; font-size: 12px;")
        self._net_vl.addWidget(self._net_placeholder)
        add_nic_btn = QPushButton("🔗 添加网卡")
        add_nic_btn.setStyleSheet("background: #0984e3; color: white; border: none; border-radius: 4px; padding: 6px 14px; font-size: 12px;")
        add_nic_btn.clicked.connect(self._add_nic)
        self._net_vl.addWidget(add_nic_btn)
        vl.addWidget(self._net_group, 1)

        # ── Close button ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(STYLE_BTN_CANCEL)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        vl.addLayout(btn_row)

        self._fetch_networks()

    def _fetch_networks(self):
        host, port, user, pwd = self._ssh_params
        cmd = f"docker inspect {self._cid} --format '{{{{json .NetworkSettings.Networks}}}}'"
        self._inspect_worker = DockerSSHWorker(host, port, user, pwd, commands=[cmd], parent=self)
        self._inspect_worker.output_ready.connect(self._log)
        self._inspect_worker.data_ready.connect(self._on_inspect_result)
        self._inspect_worker.start()

    def _on_inspect_result(self, data):
        import json as _json
        if data["type"] == "command_results":
            results = data.get("results", [])
            out = results[0].get("stdout", "").strip() if results else ""
            new_net = []
            if out:
                try:
                    nets = _json.loads(out)
                    for net_name, info in nets.items():
                        ip = info.get("IPAddress", "")
                        new_net.append((net_name, ip))
                except _json.JSONDecodeError:
                    pass
            self._net_data = new_net
            self._rebuild_network_list()
            self._inspect_worker = None

    def _rebuild_network_list(self):
        while self._net_vl.count() > 1:
            item = self._net_vl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._net_data:
            lbl = QLabel("暂无网卡")
            lbl.setStyleSheet("color: #b2bec3; font-size: 12px;")
            self._net_vl.insertWidget(0, lbl)
            return
        for net_name, ip in self._net_data:
            row = QHBoxLayout()
            row.setSpacing(10)
            n_lbl = QLabel(net_name)
            n_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
            row.addWidget(n_lbl)
            ip_lbl = QLabel(ip if ip else "—")
            ip_lbl.setStyleSheet("font-size: 13px; color: #636e72;")
            row.addWidget(ip_lbl)
            row.addStretch()
            del_btn = QPushButton("删除")
            del_btn.setStyleSheet("background: transparent; color: #d63031; border: 1px solid #d63031; border-radius: 3px; padding: 4px 12px; font-size: 12px;")
            del_btn.clicked.connect(lambda checked, n=net_name: self._disconnect_nic(n))
            row.addWidget(del_btn)
            container = QWidget()
            container.setLayout(row)
            self._net_vl.insertWidget(self._net_vl.count() - 1, container)

    def _disconnect_nic(self, net_name):
        reply = QMessageBox.question(self, "确认断开",
                                     f"确定要从容器 {self._container_name} 断开网卡 {net_name} 吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        parent = self.parent()
        if hasattr(parent, '_execute_command'):
            parent._execute_command(f"docker network disconnect {net_name} {self._container_name}", f"disconnect_{net_name}")
        QTimer.singleShot(1000, self._fetch_networks)

    def _add_nic(self):
        parent = self.parent()
        if not hasattr(parent, 'docker_data'):
            return
        containers = parent.docker_data.get("containers", [])
        networks = parent.docker_data.get("networks", [])
        dlg = AddNicDialog(parent, containers, networks, selected_container=self._container_name)
        if dlg.exec() == QDialog.Accepted:
            cmd = dlg.get_command()
            if cmd:
                parent._execute_command(cmd, "add_nic")
            QTimer.singleShot(1000, self._fetch_networks)

    def _log(self, msg):
        pass

    def closeEvent(self, event):
        if self._inspect_worker and self._inspect_worker.isRunning():
            self._inspect_worker.stop()
            self._inspect_worker.wait(2000)
        super().closeEvent(event)


class BatchImportDialog(QDialog):
    _HEADERS = [
        "hostname", "container_name", "container_type",
        "network1_name", "ipv4_1", "ipv6_1",
        "image_ID", "cpu", "mem_gb", "shm_size", "restart",
        "network2_name", "ipv4_2", "ipv6_2",
        "network3_name", "ipv4_3", "ipv6_3",
    ]
    _IPV6_TABLE_COLS = [i + 1 for i, h in enumerate(_HEADERS) if h.startswith("ipv6")]  # +1 for checkbox col

    def __init__(self, parent=None, existing_names=None, existing_ips=None, config_path=None):
        super().__init__(parent)
        self.setWindowTitle("📋 批量导入容器")
        self.setMinimumSize(1200, 680)
        self._commands = []
        self._parsed = []
        self._existing_names = set(existing_names or [])
        self._existing_ips = set(existing_ips or [])
        self._config_path = config_path or os.path.join(
            os.path.dirname(__file__), "config", "docker_batch_config.json")
        self._updating_table = False
        self._clipboard = None

        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 16, 20, 16)
        vl.setSpacing(8)

        # Toolbar
        tool_row = QHBoxLayout()
        tool_row.setSpacing(6)
        add_row_btn = QPushButton("+ 添加行")
        add_row_btn.setStyleSheet(
            "QPushButton{background:#5b7a9a;color:white;border:none;"
            "border-radius:4px;padding:6px 14px;font-size:12px;}"
            "QPushButton:hover{background:#4e6b89;}")
        add_row_btn.clicked.connect(self._add_row)
        tool_row.addWidget(add_row_btn)

        del_row_btn = QPushButton("✕ 删除行")
        del_row_btn.setStyleSheet(
            "QPushButton{background:#b85450;color:white;border:none;"
            "border-radius:4px;padding:6px 14px;font-size:12px;}"
            "QPushButton:hover{background:#a34945;}")
        del_row_btn.clicked.connect(self._delete_row)
        tool_row.addWidget(del_row_btn)

        detail_btn = QPushButton("📋 详情")
        detail_btn.setStyleSheet(
            "QPushButton{background:#f0f3f5;color:#5b7a9a;border:1px solid #c8d0d8;"
            "border-radius:4px;padding:6px 14px;font-size:12px;}"
            "QPushButton:hover{background:#e4e8ec;}")
        detail_btn.clicked.connect(self._show_selected_detail)
        tool_row.addWidget(detail_btn)

        copy_btn = QPushButton("📋 复制行")
        copy_btn.setStyleSheet(
            "QPushButton{background:#f0f3f5;color:#5b7a9a;border:1px solid #c8d0d8;"
            "border-radius:4px;padding:6px 14px;font-size:12px;}"
            "QPushButton:hover{background:#e4e8ec;}")
        copy_btn.clicked.connect(self._copy_row)
        tool_row.addWidget(copy_btn)

        paste_btn = QPushButton("📌 粘贴行")
        paste_btn.setStyleSheet(
            "QPushButton{background:#f0f3f5;color:#5b7a9a;border:1px solid #c8d0d8;"
            "border-radius:4px;padding:6px 14px;font-size:12px;}"
            "QPushButton:hover{background:#e4e8ec;}")
        paste_btn.clicked.connect(self._paste_row)
        tool_row.addWidget(paste_btn)

        self.ipv6_cb = QCheckBox("IPv6")
        self.ipv6_cb.setChecked(True)
        self.ipv6_cb.toggled.connect(self._toggle_ipv6)
        self.ipv6_cb.setStyleSheet("font-size:12px; color:#5b7a9a; spacing:4px;")
        tool_row.addWidget(self.ipv6_cb)

        tool_row.addStretch()

        load_btn = QPushButton("📂 加载配置")
        load_btn.setStyleSheet(
            "QPushButton{background:#f0f3f5;color:#5b7a9a;border:1px solid #c8d0d8;"
            "border-radius:4px;padding:6px 14px;font-size:12px;}"
            "QPushButton:hover{background:#e4e8ec;}")
        load_btn.clicked.connect(self._load_config)
        tool_row.addWidget(load_btn)

        save_btn = QPushButton("💾 保存配置")
        save_btn.setStyleSheet(
            "QPushButton{background:#f0f3f5;color:#5b7a9a;border:1px solid #c8d0d8;"
            "border-radius:4px;padding:6px 14px;font-size:12px;}"
            "QPushButton:hover{background:#e4e8ec;}")
        save_btn.clicked.connect(self._save_config)
        tool_row.addWidget(save_btn)

        vl.addLayout(tool_row)

        # Volume
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("卷挂载路径:"))
        self.volume_input = QLineEdit()
        self.volume_input.setPlaceholderText("多个以逗号分隔")
        self.volume_input.setText("/opt/tar/:/opt/tar/,/sys/fs/cgroup:/sys/fs/cgroup:ro")
        self.volume_input.setStyleSheet(STYLE_INPUT)
        vol_row.addWidget(self.volume_input, 1)
        vl.addLayout(vol_row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #dfe6e9; max-height: 1px;")
        vl.addWidget(sep)

        # Editable table: checkbox + 17 data columns + status column
        self.preview = QTableWidget()
        all_headers = ["导入"] + list(self._HEADERS) + ["状态"]
        self.preview.setColumnCount(len(all_headers))
        self.preview.setHorizontalHeaderLabels(all_headers)
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.preview.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.preview.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.preview.cellChanged.connect(self._on_cell_changed)
        vl.addWidget(self.preview, 1)

        # Progress
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        vl.addWidget(self.progress)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.import_btn = QPushButton("🚀 开始导入")
        self.import_btn.setStyleSheet("""
            QPushButton { background: #5b7a9a; color: white; border: none;
            border-radius: 4px; padding: 8px 20px; font-size: 14px; }
            QPushButton:disabled { background: #c8d0d8; color: #e8ecf0; }
        """)
        self.import_btn.clicked.connect(self._do_import)
        self.import_btn.setEnabled(False)
        btn_row.addWidget(self.import_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(STYLE_BTN_CANCEL)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        vl.addLayout(btn_row)

        # Auto-load config
        self._load_config(silent=True)

    # ── Row management ──

    def _add_row(self):
        empty = {h: "" for h in self._HEADERS}
        empty["_row"] = len(self._parsed) + 1
        empty["_errors"] = []
        self._parsed.append(empty)
        self._update_preview()
        self._update_import_btn()

    def _delete_row(self):
        rows = sorted(set(
            r.row() for r in self.preview.selectedIndexes()
        ), reverse=True)
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择要删除的行")
            return
        for r in rows:
            if r < len(self._parsed):
                self._parsed.pop(r)
        self._update_preview()
        self._update_import_btn()

    def _show_selected_detail(self):
        rows = sorted(set(r.row() for r in self.preview.selectedIndexes()))
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        self._show_row_detail(rows[0], 0)

    def _copy_row(self):
        rows = sorted(set(r.row() for r in self.preview.selectedIndexes()))
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        d = self._parsed[rows[0]]
        self._clipboard = {h: d.get(h, "") for h in self._HEADERS}
        QMessageBox.information(self, "提示", f"已复制第 {rows[0]+1} 行")

    def _paste_row(self):
        if not self._clipboard:
            QMessageBox.warning(self, "提示", "请先复制一行")
            return
        rows = sorted(set(r.row() for r in self.preview.selectedIndexes()))
        insert_after = rows[-1] if rows else len(self._parsed) - 1
        new = {h: self._clipboard.get(h, "") for h in self._HEADERS}
        new["_row"] = len(self._parsed) + 1
        new["_errors"] = []
        self._parsed.insert(insert_after + 1, new)
        self._update_preview()
        self._update_import_btn()

    def _toggle_ipv6(self, visible):
        for col in self._IPV6_TABLE_COLS:
            self.preview.setColumnHidden(col, not visible)

    # ── Config persistence ──

    def _load_config(self, silent=False):
        path = self._config_path
        if not os.path.exists(path):
            if not silent:
                QMessageBox.information(self, "提示", "配置文件不存在，将使用空模板")
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self._parsed = []
            for i, item in enumerate(data):
                d = {h: str(item.get(h, "")) for h in self._HEADERS}
                d["_row"] = i + 1
                d["_errors"] = []
                self._parsed.append(d)
            self._validate_all()
            self._update_preview()
            self._toggle_ipv6(self.ipv6_cb.isChecked())
            self._update_import_btn()
            if not silent:
                QMessageBox.information(self, "完成", f"已加载 {len(self._parsed)} 条配置")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载配置文件失败:\n{e}")

    def _save_config(self):
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        data = []
        for d in self._parsed:
            entry = {h: d.get(h, "") for h in self._HEADERS}
            data.append(entry)
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "完成", f"已保存 {len(data)} 条配置到:\n{self._config_path}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败:\n{e}")

    # ── Table sync ──

    def _on_cell_changed(self, row, col):
        if self._updating_table:
            return
        if col == 0:
            return
        data_col = col - 1
        if row >= len(self._parsed) or data_col >= len(self._HEADERS):
            return
        item = self.preview.item(row, col)
        val = item.text().strip() if item else ""
        self._parsed[row][self._HEADERS[data_col]] = val
        self._validate_row(self._parsed[row])
        self._update_status_cell(row, self._parsed[row])
        self._update_import_btn()

    # ── Validation ──

    def _validate_all(self):
        import re as _re
        names_seen = set()
        ips_seen = set()
        for d in self._parsed:
            self._validate_row(d, names_seen, ips_seen)
            names_seen.add(d.get("container_name", ""))
            for k in ("ipv4_1", "ipv4_2", "ipv4_3"):
                v = d.get(k, "").strip()
                if v:
                    ips_seen.add(v)

    def _validate_row(self, d, names_seen=None, ips_seen=None):
        import re as _re
        errs = []
        if names_seen is None:
            names_seen = set()
        if ips_seen is None:
            ips_seen = set()

        for field in ("hostname", "container_name", "container_type", "network1_name", "ipv4_1", "image_ID"):
            if not d.get(field):
                errs.append(f"{field} 为空")

        ctype = d.get("container_type", "")
        if ctype and ctype not in ("1", "2", "3"):
            errs.append("container_type 无效")

        v4 = d.get("ipv4_1", "")
        if v4:
            m = _re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", v4)
            if not m or any(int(m.group(i)) > 255 for i in range(1, 5)):
                errs.append("ipv4_1 格式错误")

        v6 = d.get("ipv6_1", "").strip()
        if v6:
            if not _re.match(r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$", v6):
                errs.append("ipv6_1 格式错误")

        cname = d.get("container_name", "")
        if " " in cname:
            errs.append("container_name 不能有空格")
        if cname and cname in names_seen:
            errs.append("container_name 重复")
        if cname and cname in self._existing_names:
            errs.append(f"名称 \"{cname}\" 已存在")

        all_ips = set()
        for ip_key in ("ipv4_1", "ipv4_2", "ipv4_3"):
            ip_val = d.get(ip_key, "").strip()
            if ip_val:
                all_ips.add(ip_val)
                if ip_val in ips_seen:
                    errs.append(f"{ip_key} \"{ip_val}\" 重复")
                if ip_val in self._existing_ips:
                    errs.append(f"{ip_key} \"{ip_val}\" 已被使用")

        if ctype in ("2", "3"):
            cpu = d.get("cpu", "")
            mem = d.get("mem_gb", "")
            if not cpu or not cpu.isdigit() or int(cpu) < 1:
                errs.append("cpu 无效")
            if not mem or not mem.isdigit() or int(mem) < 1:
                errs.append("mem_gb 无效")

        if ctype == "3":
            shm = d.get("shm_size", "")
            if not shm:
                errs.append("shm_size 为空")

        for suffix in ("2", "3"):
            n = d.get(f"network{suffix}_name", "")
            if n:
                v4x = d.get(f"ipv4_{suffix}", "")
                if not v4x:
                    errs.append(f"ipv4_{suffix} 为空")
                else:
                    m = _re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", v4x)
                    if not m or any(int(m.group(i)) > 255 for i in range(1, 5)):
                        errs.append(f"ipv4_{suffix} 格式错误")
                v6x = d.get(f"ipv6_{suffix}", "").strip()
                if v6x and not _re.match(r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$", v6x):
                    errs.append(f"ipv6_{suffix} 格式错误")

        d["_errors"] = errs
        return errs

    # ── UI sync ──

    def _update_preview(self):
        self._updating_table = True
        self.preview.setRowCount(len(self._parsed))
        for i, d in enumerate(self._parsed):
            # Checkbox column
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked)
            self.preview.setItem(i, 0, chk)
            # Data columns
            for j, h in enumerate(self._HEADERS):
                val = d.get(h, "")
                item = QTableWidgetItem(val)
                item.setToolTip(val)
                self.preview.setItem(i, j + 1, item)
            self._update_status_cell(i, d)
        self._updating_table = False

    def _update_status_cell(self, row, d):
        errs = d.get("_errors", [])
        status_col = len(self._HEADERS) + 1
        if errs:
            item = QTableWidgetItem("❌ " + "; ".join(errs[:3]))
            item.setToolTip("\n".join(errs))
            item.setBackground(QColor("#fce4e4"))
        else:
            item = QTableWidgetItem("✅ 有效")
            item.setBackground(QColor("#e8f5e9"))
        self.preview.setItem(row, status_col, item)

    def _update_import_btn(self):
        has_any = False
        for i, d in enumerate(self._parsed):
            item = self.preview.item(i, 0)
            if item and item.checkState() == Qt.Checked and not d.get("_errors", []):
                has_any = True
                break
        self.import_btn.setEnabled(has_any)

    def _show_row_detail(self, row, col):
        if row < 0 or row >= len(self._parsed):
            return
        d = self._parsed[row]
        errs = d.get("_errors", [])
        lines = [f"第 {row+1} 行:"]
        for h in self._HEADERS:
            lines.append(f"  {h}: {d.get(h, '')}")
        if errs:
            lines.append("")
            lines.append("错误:")
            for e in errs:
                lines.append(f"  ❌ {e}")
        QMessageBox.information(self, "行详情", "\n".join(lines))

    # ── Command generation & import ──

    def _gen_command(self, d, volume):
        name = d["container_name"]
        hostname = d["hostname"]
        net = d["network1_name"]
        ip = d["ipv4_1"]
        ip6 = d["ipv6_1"].strip()
        image = d["image_ID"]
        ctype = d["container_type"]
        restart = d.get("restart") or "always"

        cmd = "docker run -tid"
        cmd += " -e \"container=docker\""
        cmd += f" --name {name} --hostname {hostname}"
        cmd += " --privileged"
        cmd += f" --restart {restart}"
        cmd += f" --network={net}"
        if ip:
            cmd += f" --ip={ip}"
        if ip6:
            cmd += f" --ip6={ip6}"

        if ctype in ("2", "3"):
            cpu = d.get("cpu", "")
            mem = d.get("mem_gb", "")
            if cpu:
                cmd += f" --cpus={cpu}"
            if mem:
                cmd += f" --memory={mem}g"
        if ctype == "3":
            shm = d.get("shm_size", "") or "8"
            shm = shm.rstrip().rstrip("gG")
            cmd += f" --shm-size {shm}g"

        if volume:
            for v in volume.replace("，", ",").split(","):
                v = v.strip()
                if v:
                    cmd += f" -v {v}"

        cmd += f" {image} /usr/sbin/init"

        parts = [cmd]
        for suffix in ("2", "3"):
            n = d.get(f"network{suffix}_name", "")
            if n:
                v4 = d.get(f"ipv4_{suffix}", "")
                v6 = d.get(f"ipv6_{suffix}", "").strip()
                nc = f"docker network connect {n} {name}"
                if v4:
                    nc += f" --ip {v4}"
                if v6:
                    nc += f" --ip6 {v6}"
                parts.append(nc)

        return " && ".join(parts)

    def _do_import(self):
        if not self._parsed:
            return
        valid = []
        for i, d in enumerate(self._parsed):
            item = self.preview.item(i, 0)
            if item and item.checkState() == Qt.Checked and not d.get("_errors", []):
                valid.append(d)
        if not valid:
            QMessageBox.warning(self, "提示", "没有勾选的有效数据可导入")
            return
        vol = self.volume_input.text().strip()
        commands = []
        for d in valid:
            cmd = self._gen_command(d, vol)
            commands.append(cmd)
        self._commands = commands
        self.accept()

    def get_commands(self):
        return self._commands


class SFTPUploadWorker(QThread):
    progress = Signal(str)
    file_progress = Signal(object, object)
    finished = Signal(bool, str)

    def __init__(self, host, port, username, password, local_path, remote_dir, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.local_path = local_path
        self.remote_dir = remote_dir
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(self.host, port=self.port, username=self.username,
                           password=self.password, timeout=15)
            self.progress.emit(f"\u2705 SSH\u8fde\u63a5\u6210\u529f {self.host}")

            filename = os.path.basename(self.local_path)
            remote_path = self.remote_dir.rstrip("/") + "/" + filename
            file_size = os.path.getsize(self.local_path)

            sftp = client.open_sftp()
            sftp.put(self.local_path, remote_path, callback=lambda x, y: self.file_progress.emit(x, y))
            sftp.close()
            client.close()

            self.progress.emit(f"\u2705 \u4e0a\u4f20\u5b8c\u6210: {filename}")
            self.finished.emit(True, filename)
        except Exception as e:
            self.progress.emit(f"\u274c \u4e0a\u4f20\u5931\u8d25: {e}")
            self.finished.emit(False, str(e))


class StripedProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._s_offset = 0
        self._s_active = False

    def set_offset(self, offset):
        self._s_offset = offset
        self._s_active = offset >= 0
        self.update()

    def stop_stripe(self):
        self._s_active = False
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._s_active:
            return
        crect = self._chunk_rect()
        if crect.isEmpty():
            return
        painter = QPainter(self)
        painter.setClipRect(crect)
        painter.setClipping(True)
        pen = QPen(QColor(255, 255, 255, 50), 2)
        painter.setPen(pen)
        sp = 14
        h = self.height()
        off = self._s_offset
        start_x = crect.left()
        end_x = crect.right()
        for x in range(start_x - sp, end_x + sp + sp, sp):
            xo = x + off
            painter.drawLine(xo, 0, xo - h, h)
        painter.end()

    def _chunk_rect(self):
        r = self.rect()
        rng = self.maximum() - self.minimum()
        if rng <= 0:
            return QRect()
        ratio = (self.value() - self.minimum()) / rng
        return QRect(r.left(), r.top(), int(r.width() * ratio), r.height())


class LoadImageDialog(QDialog):
    def __init__(self, parent, files):
        super().__init__(parent)
        self.setWindowTitle("\U0001f4e5 \u52a0\u8f7d\u955c\u50cf")
        self.resize(420, 360)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 12, 16, 12)
        vl.setSpacing(8)
        header_row = QHBoxLayout()
        hd = QLabel("\u9009\u62e9 /opt/tar/ \u4e2d\u7684\u955c\u50cf\u6587\u4ef6:")
        hd.setStyleSheet("font-size: 13px; font-weight: bold;")
        header_row.addWidget(hd)
        header_row.addStretch()
        self.cb_all = QCheckBox("\u5168\u9009")
        self.cb_all.setStyleSheet("font-size: 13px;")
        self.cb_all.toggled.connect(self._toggle_all)
        header_row.addWidget(self.cb_all)
        vl.addLayout(header_row)
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        for f in files:
            item = QListWidgetItem(f)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        vl.addWidget(self.list_widget)
        br = QHBoxLayout()
        br.addStretch()
        cb = QPushButton("\u53d6\u6d88")
        cb.setStyleSheet(STYLE_BTN_CANCEL)
        cb.clicked.connect(self.reject)
        br.addWidget(cb)
        ok = QPushButton("\u5f00\u59cb\u52a0\u8f7d")
        ok.setStyleSheet(STYLE_BTN_PRIMARY)
        ok.clicked.connect(self.accept)
        br.addWidget(ok)
        vl.addLayout(br)

    def _toggle_all(self, checked):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def selected_files(self):
        files = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                files.append(item.text().strip())
        return files


class SpaceCheckWorker(QThread):
    finished = Signal(object, object)

    def __init__(self, host, port, username, password):
        super().__init__()
        self._host = host
        self._port = port
        self._user = username
        self._pwd = password

    def run(self):
        avail_space = 0
        existing_tars = set()
        try:
            import paramiko as _pm
            client = _pm.SSHClient()
            client.set_missing_host_key_policy(_pm.AutoAddPolicy())
            client.connect(self._host, port=self._port, username=self._user,
                           password=self._pwd, timeout=15)
            try:
                _, stdout, _ = client.exec_command(
                    "df -B1 /opt/tar/ 2>/dev/null | awk 'NR==2{print $4}'", timeout=10)
                raw = stdout.read().decode().strip()
                avail_space = int(raw) if raw.isdigit() else 0
            except:
                pass
            try:
                _, stdout, _ = client.exec_command(
                    "ls /opt/tar/*.tar 2>/dev/null", timeout=10)
                existing_tars = {l.strip() for l in stdout.read().decode().split("\n") if l.strip()}
            except:
                pass
            client.close()
        except:
            pass
        self.finished.emit(avail_space, existing_tars)


class ExportImagesDialog(QDialog):
    def __init__(self, parent, ssh_params, containers):
        super().__init__(parent)
        self.setWindowTitle("\U0001f4e6 \u6279\u91cf\u5bfc\u51fa\u955c\u50cf")
        self.resize(700, 420)
        self.setMinimumSize(660, 380)
        self._ssh_params = ssh_params
        self._containers = containers
        self._host, self._port, self._user, self._pwd = ssh_params
        self._avail_space = 0
        self._existing_tars = set()
        self._export_cmds = []
        self._export_names = []
        self._selected_indices = set()

        self._build_ui()
        self._populate_table()
        QTimer.singleShot(0, self._start_space_check)

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 16, 20, 16)
        vl.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        tl = QLabel("\U0001f4c1 \u5b58\u50a8\u8def\u5f84: /opt/tar/")
        tl.setStyleSheet("font-size: 13px; font-weight: bold; color: #2d3436;")
        top_row.addWidget(tl)
        top_row.addStretch()
        self.lbl_space = QLabel("\u23f3 \u67e5\u8be2\u53ef\u7528\u7a7a\u95f4\u4e2d...")
        self.lbl_space.setStyleSheet("font-size: 13px; color: #636e72;")
        top_row.addWidget(self.lbl_space)
        vl.addLayout(top_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #dfe6e9; max-height: 1px;")
        vl.addWidget(sep)

        header_row = QHBoxLayout()
        self.cb_all = QCheckBox("\u5168\u9009")
        self.cb_all.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.cb_all.toggled.connect(self._toggle_all)
        header_row.addWidget(self.cb_all)
        header_row.addStretch()
        vl.addLayout(header_row)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["", "\u5bb9\u5668\u540d", "\u955c\u50cf\u540d", "\u6807\u7b7e"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 36)
        for col in range(1, 4):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, 180)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setStyleSheet("""
            QTableWidget { border: 1px solid #e0e0e0; font-size: 12px; }
            QTableWidget::item { padding: 4px 6px; }
            QHeaderView::section { background: #f0f2f5; border: none; padding: 6px; font-weight: bold; }
        """)
        vl.addWidget(self.table, 1)

        stat_row = QHBoxLayout()
        self.lbl_selected = QLabel("\u23f3 \u52a0\u8f7d\u6570\u636e\u4e2d...")
        self.lbl_selected.setStyleSheet("font-size: 13px; color: #2d3436;")
        stat_row.addWidget(self.lbl_selected)
        stat_row.addStretch()
        vl.addLayout(stat_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.export_btn = QPushButton("\U0001f4e6 \u5f00\u59cb\u5bfc\u51fa")
        self.export_btn.setStyleSheet("""
            QPushButton { background: #0984e3; color: white; border: none; border-radius: 4px; padding: 8px 20px; font-size: 14px; }
            QPushButton:disabled { background: #b2bec3; color: #dfe6e9; }
            QPushButton:hover { background: #0873c4; }
        """)
        self.export_btn.clicked.connect(self._do_export)
        self.export_btn.setEnabled(False)
        btn_row.addWidget(self.export_btn)
        self.cancel_btn = QPushButton("\u53d6\u6d88")
        self.cancel_btn.setStyleSheet("""
            QPushButton { background: #0984e3; color: white; border: none; border-radius: 4px; padding: 8px 20px; font-size: 14px; }
            QPushButton:disabled { background: #b2bec3; color: #dfe6e9; }
            QPushButton:hover { background: #0873c4; }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        vl.addLayout(btn_row)

    def _start_space_check(self):
        self.lbl_space.setText("\u23f3 \u67e5\u8be2\u53ef\u7528\u7a7a\u95f4\u4e2d...")
        self._space_worker = SpaceCheckWorker(self._host, self._port, self._user, self._pwd)
        self._space_worker.finished.connect(self._on_space_check_done)
        self._space_worker.start()

    def _on_space_check_done(self, avail_space, existing_tars):
        self._avail_space = avail_space
        self._existing_tars = existing_tars
        self._update_stats()

    def _populate_table(self):
        today = datetime.now().strftime("%Y%m%d")
        self.table.setRowCount(0)
        for i, c in enumerate(self._containers):
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = c.get("name", "")

            cb = QWidget()
            cb_layout = QHBoxLayout(cb)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignCenter)
            check = QCheckBox()
            check.setChecked(False)
            check.toggled.connect(lambda checked, idx=i: self._on_check_changed(idx, checked))
            cb_layout.addWidget(check)
            self.table.setCellWidget(row, 0, cb)

            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.item(row, 1).setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            img_edit = QLineEdit(name)
            img_edit.setStyleSheet("border: none; background: transparent; font-size: 12px;")
            self.table.setCellWidget(row, 2, img_edit)

            tag_edit = QLineEdit(today)
            tag_edit.setStyleSheet("border: none; background: transparent; font-size: 12px;")
            self.table.setCellWidget(row, 3, tag_edit)

        self._update_stats()

    def _fmt_size(self, bytes_val):
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}" if bytes_val >= 10 else f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.2f} PB"

    def _on_check_changed(self, idx, checked):
        if checked:
            self._selected_indices.add(idx)
        else:
            self._selected_indices.discard(idx)
        self._update_stats()

    def _toggle_all(self, checked):
        for row in range(self.table.rowCount()):
            w = self.table.cellWidget(row, 0)
            if w:
                cb = w.findChild(QCheckBox)
                if cb:
                    cb.blockSignals(True)
                    cb.setChecked(checked)
                    cb.blockSignals(False)
        if checked:
            self._selected_indices = set(range(self.table.rowCount()))
        else:
            self._selected_indices.clear()
        self._update_stats()

    def _update_stats(self):
        count = len(self._selected_indices)

        self.lbl_selected.setText(f"\u2714 \u5df2\u9009: {count} \u4e2a")
        avail_str = self._fmt_size(self._avail_space) if self._avail_space > 0 else "\u67e5\u8be2\u4e2d..."
        self.lbl_space.setText(f"\U0001f4be \u53ef\u7528: {avail_str}")

        self.export_btn.setEnabled(count > 0)

    def _do_export(self):
        if not self._selected_indices:
            return
        reply = QMessageBox.question(self, "\u786e\u8ba4\u5bfc\u51fa",
            "\u5bfc\u51fa\u955c\u50cf\u4f1a\u5173\u95ed\u52fe\u9009\u7684\u5bb9\u5668\uff0c\u5bfc\u51fa\u5b8c\u6bd5\u540e\u8bf7\u624b\u52a8\u542f\u52a8\u5bb9\u5668\u3002\n\n\u662f\u5426\u7ee7\u7eed\uff1f",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        sorted_idx = sorted(self._selected_indices)
        cmds = []
        names = []
        for idx in sorted_idx:
            c = self._containers[idx]
            cid = c.get("id", "")
            name = c.get("name", "")
            w_img = self.table.cellWidget(idx, 2)
            w_tag = self.table.cellWidget(idx, 3)
            img_name = w_img.text().strip() if w_img else name
            tag = w_tag.text().strip() if w_tag else datetime.now().strftime("%Y%m%d")

            base = f"/opt/tar/{img_name}_{tag}.tar"
            if base in self._existing_tars:
                suffix = datetime.now().strftime("_%H%M%S")
                base = f"/opt/tar/{img_name}_{tag}{suffix}.tar"

            cmds.append(f"docker stop {cid}")
            cmds.append(f"docker commit {cid} {img_name}:{tag}")
            cmds.append(f"docker save -o {base} {img_name}:{tag}")
            names.append(name)

        self._export_cmds = cmds
        self._export_names = names
        self.accept()

    def get_export_info(self):
        return self._export_cmds, self._export_names


class ExportProgressDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("\U0001f4e6 \u6279\u91cf\u5bfc\u51fa\u8fdb\u5ea6")
        self.resize(600, 380)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 12, 16, 12)
        vl.setSpacing(8)

        self.lbl_info = QLabel("\U0001f4e6 \u5bfc\u51fa\u4e2d...")
        self.lbl_info.setStyleSheet("font-size: 14px; font-weight: bold; color: #2d3436;")
        vl.addWidget(self.lbl_info)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("""
            QTextEdit {
                background: white; color: #333;
                font-family: Consolas, monospace; font-size: 11px;
                border: 1px solid #ddd; padding: 6px;
            }
        """)
        vl.addWidget(self.log_box, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("\u5173\u95ed")
        close_btn.setStyleSheet(STYLE_BTN_CANCEL)
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)
        vl.addLayout(btn_row)

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def update_info(self, idx, total, name):
        self.lbl_info.setText(f"\U0001f4e6 \u5bfc\u51fa\u5bb9\u5668: {name}  [{idx}/{total}]")

    def append_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {msg}")

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class LoadProgressDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("\U0001f4e5 \u52a0\u8f7d\u955c\u50cf\u8fdb\u5ea6")
        self.resize(600, 380)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 12, 16, 12)
        vl.setSpacing(8)

        self.lbl_info = QLabel("\U0001f4e5 \u52a0\u8f7d\u4e2d...")
        self.lbl_info.setStyleSheet("font-size: 14px; font-weight: bold; color: #2d3436;")
        vl.addWidget(self.lbl_info)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("""
            QTextEdit {
                background: white; color: #333;
                font-family: Consolas, monospace; font-size: 11px;
                border: 1px solid #ddd; padding: 6px;
            }
        """)
        vl.addWidget(self.log_box, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("\u5173\u95ed")
        close_btn.setStyleSheet(STYLE_BTN_CANCEL)
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)
        vl.addLayout(btn_row)

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def set_info(self, text):
        self.lbl_info.setText(text)

    def append_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {msg}")

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class DockerManager(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Docker 远程管理")
        self.resize(1500, 950)
        self.setMinimumSize(800, 600)

        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(log_dir, f"Docker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
            encoding="utf-8")
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger = logging.getLogger(f"{__name__}.DockerManager")
        self.logger.addHandler(fh)
        self.logger.setLevel(logging.INFO)
        self.logger.info("DockerManager initialized")

        self.ssh_params = None
        self.connected = False
        self.docker_data = {}
        self.worker = None
        self._exporting = False
        self._export_cmds = []
        self._export_names = []
        self._export_idx = 0
        self._export_progress_dlg = None
        self._load_progress_dlg = None

        self._hosts_file = os.path.join(os.path.dirname(__file__), "config", "docker_hosts.json")
        self._hosts = self._load_hosts()

        self.setStyleSheet("QWidget { font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; }")
        self._setup_ui()
        self._action_buttons = [
            self.refresh_btn,
            self.cont_create_btn, self.cont_batch_btn, self.cont_export_btn,
            self.cont_del_btn, self.net_addnic_btn,
            self.net_create_btn, self.net_del_btn,
            self.img_upload_btn, self.img_load_btn, self.img_del_btn,
        ] + self.service_buttons
        self._update_button_states(False)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._build_connection_bar(main_layout)
        self._build_separator(main_layout)

        self.home_page = self._build_home_page()
        main_layout.addWidget(self.home_page, 1)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(150)
        self.log_box.setStyleSheet("""
            QTextEdit {
                background: white; color: #333;
                font-family: Consolas, monospace; font-size: 11px;
                border: 1px solid #ddd; padding: 6px;
            }
        """)
        main_layout.addWidget(self.log_box)

        self._log("就绪，请连接SSH服务器")

    def _build_separator(self, parent):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #dfe6e9; max-height: 1px;")
        parent.addWidget(sep)

    def _build_connection_bar(self, parent):
        bar = QFrame()
        bar.setStyleSheet("QFrame { background: white; border-bottom: 1px solid #dfe6e9; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        layout.addWidget(QLabel("🔗"))
        layout.addWidget(QLabel("主机:"))

        self.host_combo = QComboBox()
        self.host_combo.setMinimumWidth(280)
        self.host_combo.setStyleSheet(
            STYLE_INPUT_FLAT + "\n"
            "QComboBox QAbstractItemView {"
            "  background: white; color: #1a1a1a; selection-background-color: #e8f0fe; selection-color: #1a1a1a;"
            "}")
        self._refresh_host_combo()
        layout.addWidget(self.host_combo)

        manage_btn = QPushButton("管理")
        manage_btn.setStyleSheet(
            "QPushButton{background:#f8f9fa;color:#636e72;border:1px solid #dfe6e9;"
            "border-radius:4px;padding:6px 12px;font-size:12px;}"
            "QPushButton:hover{background:#e8e8e8;}")
        manage_btn.clicked.connect(self._manage_hosts)
        layout.addWidget(manage_btn)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self.connect_btn.clicked.connect(self._toggle_connection)
        layout.addWidget(self.connect_btn)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setStyleSheet(STYLE_BTN_SUCCESS)
        self.refresh_btn.clicked.connect(self._refresh_data)
        self.refresh_btn.setEnabled(False)
        layout.addWidget(self.refresh_btn)

        layout.addStretch()

        self.status_indicator = QLabel("● 未连接")
        self.status_indicator.setStyleSheet(f"{STYLE_DISCONNECTED}; font-size: 13px;")
        layout.addWidget(self.status_indicator)

        parent.addWidget(bar)

    def _load_hosts(self):
        try:
            if os.path.exists(self._hosts_file):
                with open(self._hosts_file, encoding="utf-8") as f:
                    return json.load(f)
            return []
        except:
            return []

    def _save_hosts(self):
        os.makedirs(os.path.dirname(self._hosts_file), exist_ok=True)
        with open(self._hosts_file, "w", encoding="utf-8") as f:
            json.dump(self._hosts, f, ensure_ascii=False, indent=2)

    def _refresh_host_combo(self):
        self.host_combo.clear()
        for h in self._hosts:
            label = f"{h.get('desc','?')} — {h['host']}:{h.get('port',22)} ({h['user']})"
            self.host_combo.addItem(label)

    def _manage_hosts(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("管理主机")
        dlg.resize(520, 380)
        layout = QVBoxLayout(dlg)

        # List
        self._host_list = QListWidget()
        self._refresh_host_list()
        layout.addWidget(QLabel("已保存的主机:"))
        layout.addWidget(self._host_list)

        # Form
        form = QFormLayout()
        form.setSpacing(6)
        ip_edit = QLineEdit(); ip_edit.setPlaceholderText("192.168.1.100")
        port_edit = QLineEdit("22"); port_edit.setFixedWidth(80)
        user_edit = QLineEdit("root")
        pwd_edit = QLineEdit(); pwd_edit.setEchoMode(QLineEdit.Password)
        desc_edit = QLineEdit(); desc_edit.setPlaceholderText("例如: 北京-核心-01")
        form.addRow("IP:", ip_edit)
        p_row = QHBoxLayout(); p_row.addWidget(port_edit); p_row.addStretch()
        form.addRow("端口:", p_row)
        form.addRow("用户:", user_edit)
        form.addRow("密码:", pwd_edit)
        form.addRow("描述:", desc_edit)
        layout.addLayout(form)

        # Buttons
        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加")
        add_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        update_btn = QPushButton("更新")
        update_btn.setStyleSheet(
            "QPushButton{background:#f0f3f5;color:#5b7a9a;border:1px solid #c8d0d8;"
            "border-radius:4px;padding:6px 16px;}")
        del_btn = QPushButton("删除")
        del_btn.setStyleSheet(STYLE_BTN_DANGER)

        btn_row.addWidget(add_btn)
        btn_row.addWidget(update_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Load selected into form
        def on_select():
            row = self._host_list.currentRow()
            if 0 <= row < len(self._hosts):
                h = self._hosts[row]
                ip_edit.setText(h["host"])
                port_edit.setText(str(h.get("port", 22)))
                user_edit.setText(h["user"])
                pwd_edit.setText(h.get("pwd", ""))
                desc_edit.setText(h.get("desc", ""))
        self._host_list.currentRowChanged.connect(on_select)

        def on_add():
            if not ip_edit.text().strip():
                QMessageBox.warning(dlg, "提示", "请输入IP")
                return
            self._hosts.append(dict(
                host=ip_edit.text().strip(),
                port=int(port_edit.text().strip() or "22"),
                user=user_edit.text().strip() or "root",
                pwd=pwd_edit.text(),
                desc=desc_edit.text().strip(),
            ))
            self._save_hosts()
            self._refresh_host_list()
            self._refresh_host_combo()
            ip_edit.clear(); pwd_edit.clear(); desc_edit.clear()
            port_edit.setText("22"); user_edit.setText("root")
        add_btn.clicked.connect(on_add)

        def on_update():
            row = self._host_list.currentRow()
            if row < 0:
                QMessageBox.warning(dlg, "提示", "请先选择要更新的主机")
                return
            if not ip_edit.text().strip():
                QMessageBox.warning(dlg, "提示", "请输入IP")
                return
            self._hosts[row] = dict(
                host=ip_edit.text().strip(),
                port=int(port_edit.text().strip() or "22"),
                user=user_edit.text().strip() or "root",
                pwd=pwd_edit.text(),
                desc=desc_edit.text().strip(),
            )
            self._save_hosts()
            self._refresh_host_list()
            self._refresh_host_combo()
        update_btn.clicked.connect(on_update)

        def on_del():
            row = self._host_list.currentRow()
            if row < 0:
                QMessageBox.warning(dlg, "提示", "请先选择要删除的主机")
                return
            if QMessageBox.question(dlg, "确认", f"删除 {self._hosts[row]['host']}?") == QMessageBox.Yes:
                self._hosts.pop(row)
                self._save_hosts()
                self._refresh_host_list()
                self._refresh_host_combo()
        del_btn.clicked.connect(on_del)

        dlg.exec()

    def _refresh_host_list(self):
        if hasattr(self, '_host_list'):
            self._host_list.clear()
            for h in self._hosts:
                self._host_list.addItem(f"{h.get('desc','?')} — {h['host']}:{h.get('port',22)} ({h['user']})")

    def _build_home_page(self):
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setStyleSheet("QScrollArea { border: none; background: #f5f6fa; }")
        container = QWidget()
        container.setStyleSheet("background: #f5f6fa;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        status_row = QHBoxLayout()
        status_row.setSpacing(0)
        self.status_cards = {}

        def _make_card(title, key, default):
            card = QWidget()
            card.setStyleSheet("background: transparent;")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(0, 2, 0, 2)
            cl.setSpacing(6)
            tl = QLabel(title)
            tl.setStyleSheet("font-size: 12px; color: #636e72;")
            cl.addWidget(tl)
            val = QLabel(default)
            val.setStyleSheet("font-size: 13px; font-weight: bold; color: #2d3436;")
            cl.addWidget(val)
            self.status_cards[key] = val
            return card

        status_row.addWidget(_make_card("服务状态", "service_status", "● 未知"))
        status_row.addStretch(1)
        status_row.addWidget(_make_card("开机自启", "service_enabled", "未知"))
        status_row.addStretch(1)

        # Docker版本 badge
        ver_card = QWidget()
        ver_card.setStyleSheet("background: transparent;")
        ver_cl = QHBoxLayout(ver_card)
        ver_cl.setContentsMargins(0, 2, 0, 2)
        ver_cl.setSpacing(6)
        ver_tl = QLabel("Docker版本")
        ver_tl.setStyleSheet("font-size: 12px; color: #636e72;")
        ver_cl.addWidget(ver_tl)
        self.badge_version = QLabel("🐳 未知")
        self.badge_version.setStyleSheet("background: #0984e3; color: white; border-radius: 3px; padding: 2px 8px; font-size: 12px; font-weight: bold;")
        ver_cl.addWidget(self.badge_version)
        self.status_cards["version"] = self.badge_version
        status_row.addWidget(ver_card)

        status_row.addStretch(1)

        # 运行概览 3个色块badge
        upt_card = QWidget()
        upt_card.setStyleSheet("background: transparent;")
        upt_cl = QHBoxLayout(upt_card)
        upt_cl.setContentsMargins(0, 2, 0, 2)
        upt_cl.setSpacing(6)
        upt_tl = QLabel("运行概览")
        upt_tl.setStyleSheet("font-size: 12px; color: #636e72;")
        upt_cl.addWidget(upt_tl)
        for icon, badge_key, bg in [("▶", "uptime_run", "#27ae60"), ("⏸", "uptime_paused", "#f39c12"), ("⏹", "uptime_stopped", "#d63031")]:
            lbl = QLabel(f"{icon} 0")
            lbl.setStyleSheet(f"background: {bg}; color: white; border-radius: 3px; padding: 2px 8px; font-size: 12px; font-weight: bold;")
            upt_cl.addWidget(lbl)
            self.status_cards[badge_key] = lbl
        status_row.addWidget(upt_card)
        layout.addLayout(status_row)

        control_row = QHBoxLayout()
        control_row.setSpacing(10)

        svc_frame = QFrame()
        svc_frame.setStyleSheet("QFrame { background: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 4px 10px; }")
        svc_ly = QHBoxLayout(svc_frame)
        svc_ly.setContentsMargins(10, 4, 10, 4)
        svc_ly.setSpacing(4)
        svc_ly.addWidget(QLabel("⚙ Docker服务:"))
        self.service_buttons = []
        for text, bg, hover, action in [("▶ 启动","#5d8a6a","#4f7a5d","start"),("⏹ 停止","#b85450","#a34945","stop"),("🔄 重启","#c8913a","#b07d33","restart")]:
            btn = QPushButton(text)
            btn.setStyleSheet(f"{STYLE_BTN_CTRL} QPushButton {{ background: {bg}; }} QPushButton:hover {{ background: {hover}; }}")
            btn.clicked.connect(lambda checked, a=action: self._service_action(a))
            btn.setEnabled(False)
            svc_ly.addWidget(btn)
            self.service_buttons.append(btn)
        svc_ly.addStretch()

        boot_frame = QFrame()
        boot_frame.setStyleSheet("QFrame { background: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 4px 10px; }")
        boot_ly = QHBoxLayout(boot_frame)
        boot_ly.setContentsMargins(10, 4, 10, 4)
        boot_ly.setSpacing(4)
        boot_ly.addWidget(QLabel("🔄 Docker服务开机自启:"))
        for text, bg, hover, action in [("✓ 启用","#5b7a9a","#4e6b89","enable"),("✕ 禁用","#6b7a7f","#556168","disable")]:
            btn = QPushButton(text)
            btn.setStyleSheet(f"{STYLE_BTN_CTRL} QPushButton {{ background: {bg}; }} QPushButton:hover {{ background: {hover}; }}")
            btn.clicked.connect(lambda checked, a=action: self._service_action(a))
            btn.setEnabled(False)
            boot_ly.addWidget(btn)
            self.service_buttons.append(btn)
        boot_ly.addStretch()

        control_row.addWidget(svc_frame, 3)
        control_row.addWidget(boot_frame, 2)
        layout.addLayout(control_row)

        tables_section = QHBoxLayout()
        tables_section.setSpacing(16)

        left_panel = QVBoxLayout()
        left_panel.setSpacing(12)

        self.cont_group = QGroupBox("容器列表")
        self.cont_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 14px; border: 1px solid #e0e0e0;
                border-radius: 8px; margin-top: 12px; padding: 16px 8px 8px 8px;
                background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 4px 12px; color: #2d3436;
            }
        """)
        cl = QVBoxLayout(self.cont_group)
        cl.setSpacing(4)
        ADD_STYLE = """
            QPushButton {
                background: #5b7a9a; color: white;
                border: none; border-radius: 3px;
                padding: 3px 12px; font-size: 11px;
            }
            QPushButton:hover { background: #4e6b89; }
            QPushButton:disabled { background: #c8d0d8; }
        """
        DEL_STYLE = """
            QPushButton {
                background: transparent; color: #b85450;
                border: 1px solid #b85450; border-radius: 3px;
                padding: 2px 10px; font-size: 11px;
            }
            QPushButton:hover { background: #b85450; color: white; }
            QPushButton:disabled { color: #c8d0d8; border-color: #c8d0d8; }
        """
        self.cont_create_btn = QPushButton("+ 创建容器")
        self.cont_create_btn.setFixedHeight(24)
        self.cont_create_btn.setStyleSheet(ADD_STYLE)
        self.cont_create_btn.clicked.connect(self._show_create_container_dialog)
        self.cont_batch_btn = QPushButton("+ 批量导入")
        self.cont_batch_btn.setFixedHeight(24)
        self.cont_batch_btn.setStyleSheet(ADD_STYLE)
        self.cont_batch_btn.clicked.connect(self._show_batch_import_dialog)
        self.net_addnic_btn = QPushButton("+ 添加网卡")
        self.net_addnic_btn.setFixedHeight(24)
        self.net_addnic_btn.setStyleSheet(ADD_STYLE)
        self.net_addnic_btn.clicked.connect(self._show_add_nic_dialog)
        self.cont_export_btn = QPushButton("\U0001f4e6 批量导出")
        self.cont_export_btn.setFixedHeight(24)
        self.cont_export_btn.setStyleSheet(ADD_STYLE)
        self.cont_export_btn.clicked.connect(self._show_export_dialog)
        self.cont_del_btn = QPushButton("✕ 删除")
        self.cont_del_btn.setFixedHeight(24)
        self.cont_del_btn.setStyleSheet(DEL_STYLE)
        self.cont_del_btn.clicked.connect(self._delete_container)
        cont_btn_row = QHBoxLayout()
        cont_btn_row.addWidget(self.cont_create_btn)
        cont_btn_row.addWidget(self.cont_batch_btn)
        cont_btn_row.addWidget(self.net_addnic_btn)
        cont_btn_row.addWidget(self.cont_export_btn)
        cont_btn_row.addStretch()
        cont_btn_row.addWidget(self.cont_del_btn)
        cl.addLayout(cont_btn_row)

        self.cont_table = QTableWidget()
        self.cont_table.setColumnCount(5)
        self.cont_table.setHorizontalHeaderLabels(["容器ID", "容器名称", "镜像ID", "状态", "创建时间"])
        self.cont_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cont_table.setAlternatingRowColors(True)
        self.cont_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cont_table.setSelectionMode(QTableWidget.SingleSelection)
        self.cont_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cont_table.customContextMenuRequested.connect(lambda pos: self._table_context_menu(pos, self.cont_table))
        self.cont_table.cellDoubleClicked.connect(self._show_container_detail_dialog)
        self.cont_table.setStyleSheet("""
            QTableWidget { border: none; font-size: 12px; background: white; }
            QTableWidget::item { padding: 4px 8px; }
            QHeaderView::section { background: #f0f2f5; border: none; padding: 6px; font-weight: bold; }
        """)
        cl.addWidget(self.cont_table)
        left_panel.addWidget(self.cont_group, 4)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(12)

        self.net_group = QGroupBox("网络列表")
        self.net_group.setStyleSheet(self.cont_group.styleSheet())
        nl = QVBoxLayout(self.net_group)
        nl.setSpacing(4)
        self.net_create_btn = QPushButton("+ 创建网络")
        self.net_create_btn.setFixedHeight(24)
        self.net_create_btn.setStyleSheet(ADD_STYLE)
        self.net_create_btn.clicked.connect(self._show_create_network_dialog)
        self.net_del_btn = QPushButton("✕ 删除")
        self.net_del_btn.setFixedHeight(24)
        self.net_del_btn.setStyleSheet(DEL_STYLE)
        self.net_del_btn.clicked.connect(self._delete_network)
        net_btn_row = QHBoxLayout()
        net_btn_row.addWidget(self.net_create_btn)
        net_btn_row.addStretch()
        net_btn_row.addWidget(self.net_del_btn)
        nl.addLayout(net_btn_row)

        self.net_table = QTableWidget()
        self.net_table.setColumnCount(3)
        self.net_table.setHorizontalHeaderLabels(["名称", "驱动", "网段"])
        self.net_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.net_table.setAlternatingRowColors(True)
        self.net_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.net_table.setSelectionMode(QTableWidget.SingleSelection)
        self.net_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.net_table.customContextMenuRequested.connect(lambda pos: self._table_context_menu(pos, self.net_table))
        self.net_table.setStyleSheet(self.cont_table.styleSheet())
        nl.addWidget(self.net_table)
        right_panel.addWidget(self.net_group, 1)

        self.img_group = QGroupBox("镜像列表")
        self.img_group.setStyleSheet(self.cont_group.styleSheet())
        il = QVBoxLayout(self.img_group)
        il.setSpacing(4)
        self.img_del_btn = QPushButton("✕ 删除")
        self.img_del_btn.setFixedHeight(24)
        self.img_del_btn.setStyleSheet(DEL_STYLE)
        self.img_del_btn.clicked.connect(self._delete_image)
        img_btn_row = QHBoxLayout()
        self.img_upload_btn = QPushButton("\U0001f4e4 上传镜像")
        self.img_upload_btn.setFixedHeight(24)
        self.img_upload_btn.setStyleSheet(ADD_STYLE)
        self.img_upload_btn.clicked.connect(self._upload_image)
        img_btn_row.addWidget(self.img_upload_btn)
        self.img_load_btn = QPushButton("\U0001f4e5 加载镜像")
        self.img_load_btn.setFixedHeight(24)
        self.img_load_btn.setStyleSheet(ADD_STYLE)
        self.img_load_btn.clicked.connect(self._load_image)
        img_btn_row.addWidget(self.img_load_btn)
        img_btn_row.addStretch()
        img_btn_row.addWidget(self.img_del_btn)
        il.addLayout(img_btn_row)

        self.img_table = QTableWidget()
        self.img_table.setColumnCount(5)
        self.img_table.setHorizontalHeaderLabels(["仓库", "标签", "镜像ID", "大小", "创建时间"])
        self.img_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.img_table.setAlternatingRowColors(True)
        self.img_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.img_table.setSelectionMode(QTableWidget.SingleSelection)
        self.img_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.img_table.customContextMenuRequested.connect(lambda pos: self._table_context_menu(pos, self.img_table))
        self.img_table.setStyleSheet(self.cont_table.styleSheet())
        il.addWidget(self.img_table)
        right_panel.addWidget(self.img_group, 1)

        tables_section.addLayout(left_panel, 3)
        tables_section.addLayout(right_panel, 2)
        layout.addLayout(tables_section)

        page.setWidget(container)
        return page



    def _toggle_connection(self):
        if self.connected:
            self._do_disconnect()
        else:
            self._do_connect()

    def _do_connect(self):
        idx = self.host_combo.currentIndex()
        if idx < 0 or idx >= len(self._hosts):
            QMessageBox.warning(self, "提示", "请先在主机列表中添加目标主机")
            return
        h = self._hosts[idx]
        host = h["host"]
        port = int(h.get("port", 22))
        user = h.get("user", "root")
        pwd = h.get("pwd", "")

        self.ssh_params = (host, port, user, pwd)
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("连接中...")
        self._log(f"正在连接 {user}@{host}:{port} ...")

        self.worker = DockerSSHWorker(host, port, user, pwd, parent=self)
        self.worker.output_ready.connect(self._on_worker_output)
        self.worker.data_ready.connect(self._on_data_ready)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _do_disconnect(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        if getattr(self, '_export_worker', None) and self._export_worker.isRunning():
            self._export_worker.stop()
            self._export_worker.wait()
        self._exporting = False
        self.connected = False
        self.connect_btn.setText("连接")
        self.connect_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self.connect_btn.setEnabled(True)
        self._update_button_states(False)
        self.status_indicator.setText("● 未连接")
        self.status_indicator.setStyleSheet(f"{STYLE_DISCONNECTED}; font-size: 13px;")
        self._log("已断开连接")
        self.logger.info("Disconnected")

    def _on_worker_output(self, msg):
        self._log(msg)

    def _on_data_ready(self, data):
        if data["type"] == "docker_info":
            self.docker_data = data["data"]
            self._populate_home(data["data"])
            self.connected = True
            self.connect_btn.setText("断开")
            self.connect_btn.setStyleSheet(STYLE_BTN_DANGER)
            self._update_button_states(True)
            self.status_indicator.setText("● 已连接")
            self.status_indicator.setStyleSheet(f"{STYLE_CONNECTED}; font-size: 13px;")
            self._refresh_combos()
        elif data["type"] == "command_results":
            for r in data["results"]:
                if r["stderr"] and "Error" in r["stderr"]:
                    self._log(f"❌ 命令失败: {r['stderr']}")
                else:
                    self._log(f"✅ {r['cmd'][:60]}... 成功")

    def _on_worker_finished(self):
        self.connect_btn.setEnabled(True)

    def _populate_home(self, data):
        self.existing_network_names = {n["name"] for n in data.get("networks", [])}
        self.existing_subnets = {n.get("subnet", "") for n in data.get("networks", []) if n.get("subnet")}
        colors = {
            "active": "#27ae60", "inactive": "#e74c3c", "activating": "#f39c12",
            "deactivating": "#e67e22", "failed": "#d63031", "unknown": "#636e72"
        }
        status = data.get("service_status", "未知").lower()
        c = colors.get(status, "#636e72")
        self.status_cards["service_status"].setText(f"● {data.get('service_status', '未知')}")
        self.status_cards["service_status"].setStyleSheet(f"{STYLE_CARD_VALUE}; color: {c};")

        enabled = data.get("service_enabled", "未知")
        ec = "#27ae60" if enabled == "enabled" else "#e74c3c" if enabled == "disabled" else "#636e72"
        display_map = {"enabled": "● 已启用", "disabled": "● 已禁用", "unknown": "● 未知"}
        self.status_cards["service_enabled"].setText(display_map.get(enabled, enabled))
        self.status_cards["service_enabled"].setStyleSheet(f"{STYLE_CARD_VALUE}; color: {ec};")

        self.badge_version.setText(f"🐳 {data.get('version', '未知')}")

        counts = data.get("uptime_counts", {"run": 0, "paused": 0, "stopped": 0})
        self.status_cards["uptime_run"].setText(f"▶ {counts.get('run', 0)}")
        self.status_cards["uptime_paused"].setText(f"⏸ {counts.get('paused', 0)}")
        self.status_cards["uptime_stopped"].setText(f"⏹ {counts.get('stopped', 0)}")

        self._update_service_btn_states(data)

        self.cont_table.setRowCount(0)
        for c in data.get("containers", []):
            row = self.cont_table.rowCount()
            self.cont_table.insertRow(row)
            self.cont_table.setItem(row, 0, QTableWidgetItem(c.get("id", "")))
            self.cont_table.setItem(row, 1, QTableWidgetItem(c.get("name", "")))
            self.cont_table.setItem(row, 2, QTableWidgetItem(c.get("image", "")))
            item = QTableWidgetItem(c.get("status", ""))
            if "Up" in c.get("status", ""):
                item.setForeground(QColor("#27ae60"))
            elif "Exited" in c.get("status", ""):
                item.setForeground(QColor("#e74c3c"))
            self.cont_table.setItem(row, 3, item)
            created = c.get("created", "")
            self.cont_table.setItem(row, 4, QTableWidgetItem(created[:16] if len(created) > 16 else created))

        self.img_table.setRowCount(0)
        for img in data.get("images", []):
            row = self.img_table.rowCount()
            self.img_table.insertRow(row)
            self.img_table.setItem(row, 0, QTableWidgetItem(img.get("repo", "")))
            self.img_table.setItem(row, 1, QTableWidgetItem(img.get("tag", "")))
            self.img_table.setItem(row, 2, QTableWidgetItem(img.get("id", "")))
            self.img_table.setItem(row, 3, QTableWidgetItem(img.get("size", "")))
            created = img.get("created", "")
            self.img_table.setItem(row, 4, QTableWidgetItem(created[:16] if len(created) > 16 else created))

        self.net_table.setRowCount(0)
        nets = sorted(data.get("networks", []),
                      key=lambda n: n.get("name", "") in ("bridge", "host", "none"))
        for net in nets:
            row = self.net_table.rowCount()
            self.net_table.insertRow(row)
            self.net_table.setItem(row, 0, QTableWidgetItem(net.get("name", "")))
            self.net_table.setItem(row, 1, QTableWidgetItem(net.get("driver", "")))
            self.net_table.setItem(row, 2, QTableWidgetItem(net.get("subnet", "")))

        self.logger.info(
            f"首页更新: {len(data.get('containers', []))}容器 "
            f"{len(data.get('images', []))}镜像 "
            f"{len(data.get('networks', []))}网络"
        )

    def _update_service_btn_states(self, data):
        if len(self.service_buttons) < 5:
            return
        status = data.get("service_status", "").lower()
        enabled = data.get("service_enabled", "").lower()
        btn_start, btn_stop, btn_restart = self.service_buttons[0:3]
        btn_enable, btn_disable = self.service_buttons[3:5]

        btn_start.setEnabled(status != "active")
        btn_stop.setEnabled(status == "active")
        btn_restart.setEnabled(status == "active")

        btn_enable.setEnabled(enabled != "enabled")
        btn_disable.setEnabled(enabled == "enabled")

    def _update_button_states(self, connected):
        for btn in self._action_buttons:
            btn.setEnabled(connected)
        if connected:
            self._update_service_btn_states(self.docker_data)

    def _refresh_combos(self):
        pass

    def _refresh_data(self):
        if not self.ssh_params:
            return
        self._log("正在刷新Docker信息...")
        host, port, user, pwd = self.ssh_params
        self.worker = DockerSSHWorker(host, port, user, pwd, parent=self)
        self.worker.output_ready.connect(self._on_worker_output)
        self.worker.data_ready.connect(self._on_data_ready)
        self.worker.start()

    def _service_action(self, action):
        for btn in self.service_buttons:
            btn.setEnabled(False)
        cmd = f"systemctl {action} docker"
        self.logger.info(f"服务操作: {cmd}")
        self._execute_command(cmd, f"service_{action}")

    def _show_create_network_dialog(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "提示", "请先连接SSH")
            return
        dlg = CreateNetworkDialog(self,
            interfaces=self.docker_data.get("interfaces", []),
            existing_networks=self.docker_data.get("networks", []),
            existing_subnets={n.get("subnet", "") for n in self.docker_data.get("networks", []) if n.get("subnet")},
        )
        if dlg.exec() == QDialog.Accepted:
            cmd = dlg.get_command()
            self._log(f"提交创建网络: {dlg.get_net_name()}")
            self._execute_command(cmd, "create_network")

    def _show_create_container_dialog(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "提示", "请先连接SSH")
            return
        dlg = CreateContainerDialog(self,
            images=self.docker_data.get("images", []),
            networks=self.docker_data.get("networks", []),
        )
        if dlg.exec() == QDialog.Accepted:
            cmd = dlg.get_command()
            self._execute_command(cmd, "create_container")

    def _show_add_nic_dialog(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "提示", "请先连接SSH")
            return
        dlg = AddNicDialog(self,
            containers=self.docker_data.get("containers", []),
            networks=self.docker_data.get("networks", []),
        )
        if dlg.exec() == QDialog.Accepted:
            cmd = dlg.get_command()
            self._execute_command(cmd, "add_nic")

    def _show_container_detail_dialog(self, row, col):
        if not self.ssh_params:
            return
        if row < 0:
            return
        cid = self.cont_table.item(row, 0).text()
        name = self.cont_table.item(row, 1).text()
        image = self.cont_table.item(row, 2).text()
        status = self.cont_table.item(row, 3).text()
        created = self.cont_table.item(row, 4).text() if self.cont_table.item(row, 4) else ""
        dlg = ContainerDetailDialog(self, cid, name, image, status, created, self.ssh_params)
        dlg.exec()
        QTimer.singleShot(500, self._refresh_data)

    def _show_batch_import_dialog(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "提示", "请先连接SSH")
            return
        existing_names = [c.get("name", "") for c in self.docker_data.get("containers", [])]
        ip_map = self.docker_data.get("container_ips", {})
        existing_ips = set()
        for ips in ip_map.values():
            existing_ips.update(ips)
        dlg = BatchImportDialog(self,
            existing_names=existing_names,
            existing_ips=list(existing_ips),
            config_path=self._hosts_file.replace("docker_hosts.json", "docker_batch_config.json"),
        )
        if dlg.exec() == QDialog.Accepted:
            cmds = dlg.get_commands()
            if cmds:
                self._execute_batch_commands(cmds)

    def _show_export_dialog(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "提示", "请先连接SSH")
            return
        if self._exporting:
            if self._export_progress_dlg:
                self._export_progress_dlg.show()
                self._export_progress_dlg.raise_()
            return
        data = self.docker_data.get("containers", [])
        dlg = ExportImagesDialog(self, self.ssh_params, data)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cmds, names = dlg.get_export_info()
        if not cmds:
            return
        self._export_cmds = cmds
        self._export_names = names
        self._export_idx = 0
        self._exporting = True
        self.cont_export_btn.setText(f"\U0001f4e6 \u6279\u91cf\u5bfc\u51fa [0/{len(names)}]")
        self._start_export_worker()

    def _start_export_worker(self):
        cmds = self._export_cmds
        names = self._export_names
        total = len(names)
        self._log(f"\U0001f4e6 \u5f00\u59cb\u6279\u91cf\u5bfc\u51fa {total} \u4e2a\u5bb9\u5668")
        cmds_per_container = 3
        progress_cmds = []
        for i in range(len(names)):
            offset = i * cmds_per_container
            for j in range(cmds_per_container):
                progress_cmds.append(cmds[offset + j])
            progress_cmds.append(f"echo ===EXPORT_{i}_DONE===")
        host, port, username, password = self.ssh_params
        w = DockerSSHWorker(host, port, username, password, progress_cmds)
        w.output_ready.connect(self._on_export_output)
        w.finished.connect(self._on_export_done)
        self._export_worker = w
        self._export_worker.start()
        if not self._export_progress_dlg:
            self._export_progress_dlg = ExportProgressDialog(self)
        self._export_progress_dlg.update_info(0, len(names), "")

    def _on_export_output(self, line):
        import re
        m = re.search(r'===EXPORT_(\d+)_DONE===', line)
        if m:
            done_idx = int(m.group(1))
            self._export_idx = done_idx + 1
            total = len(self._export_names)
            cur = self._export_idx
            name = self._export_names[done_idx] if done_idx < len(self._export_names) else ""
            self._export_progress_dlg.update_info(cur, total, name)
            text = f"{cur}/{total}"
            self.cont_export_btn.setText(text)
            self._export_progress_dlg.append_log(f"\u2705 \u5df2\u5b8c\u6210: {name}")
            self._log(f"\u2705 \u5bfc\u51fa\u5b8c\u6210: {name} [{cur}/{total}]")
        else:
            self._export_progress_dlg.append_log(line.strip())
            self._log(line.strip())

    def _on_export_done(self):
        self._exporting = False
        total = len(self._export_names)
        self._export_progress_dlg.append_log("\u2705 \u5168\u90e8\u5bfc\u51fa\u5b8c\u6210")
        self._log("\u2705 \u5168\u90e8\u5bfc\u51fa\u5b8c\u6210")
        self._export_progress_dlg.show()
        self.cont_export_btn.setText(f"{total}/{total} \u2705")
        QTimer.singleShot(3000, lambda: self.cont_export_btn.setText("\U0001f4e6 \u6279\u91cf\u5bfc\u51fa"))
        self._export_cmds.clear()
        self._export_names.clear()
        self._export_idx = 0
        self._refresh_data()

    def _table_context_menu(self, pos, table):
        if table.currentRow() < 0:
            return
        menu = QMenu(self)
        if table is self.cont_table:
            a1 = menu.addAction("启动")
            a1.triggered.connect(self._start_container)
            a2 = menu.addAction("重启")
            a2.triggered.connect(self._restart_container)
            a3 = menu.addAction("停止")
            a3.triggered.connect(self._stop_container)
            menu.addSeparator()
            a_nic = menu.addAction("网卡管理")
            a_nic.triggered.connect(self._context_show_container_detail)
            menu.addSeparator()
            a4 = menu.addAction("删除容器")
            a4.triggered.connect(self._delete_container)
        elif table is self.img_table:
            a = menu.addAction("删除")
            a.triggered.connect(self._delete_image)
        else:
            a = menu.addAction("删除")
            a.triggered.connect(self._delete_network)
        menu.exec(table.viewport().mapToGlobal(pos))

    def _context_show_container_detail(self):
        row = self.cont_table.currentRow()
        self._show_container_detail_dialog(row, 0)

    def _container_action(self, action_name, cmd_label):
        row = self.cont_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择容器")
            return
        cid = self.cont_table.item(row, 0).text()
        self._execute_command(f"docker {action_name} {cid}", f"{action_name}_{cid[:12]}")

    def _start_container(self):
        self._container_action("start", "▶ 启动")

    def _restart_container(self):
        self._container_action("restart", "🔄 重启")

    def _stop_container(self):
        self._container_action("stop", "⏹ 停止")

    def _delete_container(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "提示", "请先连接SSH")
            return
        row = self.cont_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择要删除的容器")
            return
        cid = self.cont_table.item(row, 0).text()
        name = self.cont_table.item(row, 1).text()
        reply = QMessageBox.question(self, "确认删除",
                                     f"确定要删除容器 {name} ({cid[:12]}) 吗？\n\n操作: docker stop + docker rm",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._execute_command(f"docker stop {cid} && docker rm {cid}", f"del_container_{cid[:12]}")

    def _delete_image(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "提示", "请先连接SSH")
            return
        row = self.img_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择要删除的镜像")
            return
        repo = self.img_table.item(row, 0).text()
        tag = self.img_table.item(row, 1).text()
        iid = self.img_table.item(row, 2).text()
        reply = QMessageBox.question(self, "确认删除",
                                     f"确定要删除镜像 {repo}:{tag} ({iid[:12]}) 吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._execute_command(f"docker rmi {iid}", f"del_image_{iid[:12]}")

    def _upload_image(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "\u63d0\u793a", "\u8bf7\u5148\u8fde\u63a5SSH")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "\u9009\u62e9\u955c\u50cf\u6587\u4ef6",
                                                "", "Tar files (*.tar *.tar.gz);;All files (*)")
        if not paths:
            return
        if getattr(self, '_upload_queue', None) is not None and self._upload_queue_idx < len(self._upload_queue):
            self._upload_queue.extend(paths)
            self._log(f"\U0001f4ce \u8ffd\u52a0 {len(paths)} \u4e2a\u6587\u4ef6 (\u961f\u5217\u5171 {len(self._upload_queue)} \u4e2a)")
        else:
            self._upload_queue = paths
            self._upload_queue_idx = 0
            self._start_next_upload()

    def _start_next_upload(self):
        if self._upload_queue_idx >= len(self._upload_queue):
            self.img_upload_btn.setText("\U0001f4e4 上传镜像")
            self._log("\u2705 \u5168\u90e8\u4e0a\u4f20\u5b8c\u6210")
            return
        if hasattr(self, '_upload_worker') and self._upload_worker:
            try:
                self._upload_worker.progress.disconnect()
                self._upload_worker.file_progress.disconnect()
                self._upload_worker.finished.disconnect()
            except:
                pass
        path = self._upload_queue[self._upload_queue_idx]
        filename = os.path.basename(path)
        total = len(self._upload_queue)
        self._log(f"\u25b6 \u5f00\u59cb\u4e0a\u4f20 [{self._upload_queue_idx + 1}/{total}]: {filename}")
        host, port, user, pwd = self.ssh_params
        self._upload_start = time.time()
        self._upload_worker = SFTPUploadWorker(host, port, user, pwd, path, "/opt/tar/", parent=self)
        self._upload_worker.progress.connect(self._on_worker_output)
        self._upload_worker.file_progress.connect(self._on_upload_progress)
        self._upload_worker.finished.connect(self._on_upload_finished)
        self._upload_worker.start()

    def _on_upload_progress(self, current, total):
        pct = min(current * 100 // total, 100) if total else 0
        now = time.time()
        elapsed = now - self._upload_start
        speed_bps = current / elapsed if elapsed > 0 else 0
        speed_text = f"{speed_bps / 1024 / 1024:.1f} MB/s" if speed_bps >= 1024 * 1024 else f"{speed_bps / 1024:.0f} KB/s"
        prefix = f"[{self._upload_queue_idx + 1}/{len(self._upload_queue)}] " if len(self._upload_queue) > 1 else ""
        self.img_upload_btn.setText(f"\U0001f4e4 \u4e0a\u4f20\u4e2d {prefix}{pct}% ({speed_text})")

    def _on_upload_finished(self, success, message):
        total = len(self._upload_queue)
        idx = self._upload_queue_idx + 1
        if success:
            self._log(f"\u2705 \u4e0a\u4f20\u5b8c\u6210 [{idx}/{total}]: {message}")
        else:
            self._log(f"\u274c \u4e0a\u4f20\u5931\u8d25 [{idx}/{total}]: {message}")
        self._upload_queue_idx += 1
        self._start_next_upload()

    def _load_image(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "\u63d0\u793a", "\u8bf7\u5148\u8fde\u63a5SSH")
            return
        if getattr(self, '_loading', False):
            if self._load_progress_dlg:
                self._load_progress_dlg.show()
                self._load_progress_dlg.raise_()
            return
        self._log("\u25b6 \u67e5\u8be2 /opt/tar/ \u4e2d\u7684\u955c\u50cf\u6587\u4ef6...")
        host, port, user, pwd = self.ssh_params
        worker = DockerSSHWorker(host, port, user, pwd,
                                 commands=["ls -1 /opt/tar/*.tar /opt/tar/*.tar.gz 2>/dev/null || echo '\u7a7a'"],
                                 parent=self)
        worker.output_ready.connect(self._on_worker_output)
        worker.data_ready.connect(self._on_tar_list_result)
        worker.start()

    def _on_tar_list_result(self, data):
        if data["type"] != "command_results":
            return
        lines = []
        for r in data.get("results", []):
            out = r.get("stdout", "").strip()
            if out and out != "\u7a7a":
                lines.extend([l.strip() for l in out.split("\n") if l.strip()])
        if not lines:
            QMessageBox.information(self, "\u63d0\u793a", "/opt/tar/ \u4e0b\u6ca1\u6709\u627e\u5230\u955c\u50cf\u6587\u4ef6")
            return
        dlg = LoadImageDialog(self, lines)
        if dlg.exec() != QDialog.Accepted:
            return
        selected = dlg.selected_files()
        if not selected:
            return
        self._loading = True
        self._load_queue = selected
        self._load_queue_idx = 0
        self._start_next_load()

    def _start_next_load(self):
        if self._load_queue_idx >= len(self._load_queue):
            self._loading = False
            total = len(self._load_queue)
            self.img_load_btn.setText(f"{total}/{total} \u2705")
            self._log("\u2705 \u5168\u90e8\u52a0\u8f7d\u5b8c\u6210")
            if self._load_progress_dlg:
                self._load_progress_dlg.append_log("\u2705 \u5168\u90e8\u52a0\u8f7d\u5b8c\u6210")
                self._load_progress_dlg.show()
            QTimer.singleShot(3000, lambda: self.img_load_btn.setText("\U0001f4e5 \u52a0\u8f7d\u955c\u50cf"))
            return
        f = self._load_queue[self._load_queue_idx]
        total = len(self._load_queue)
        cur = self._load_queue_idx + 1
        self.img_load_btn.setText(f"\U0001f4e5 \u52a0\u8f7d\u4e2d [{cur}/{total}]")
        self._log(f"\u25b6 \u5f00\u59cb\u52a0\u8f7d [{cur}/{total}]: {f}")
        if not self._load_progress_dlg:
            self._load_progress_dlg = LoadProgressDialog(self)
        self._load_progress_dlg.set_info(f"\U0001f4e5 \u52a0\u8f7d\u4e2d [{cur}/{total}]")
        self._load_progress_dlg.append_log(f"\u25b6 \u5f00\u59cb\u52a0\u8f7d [{cur}/{total}]: {f}")
        host, port, user, pwd = self.ssh_params
        cmd = f"docker load -i {f}"
        worker = DockerSSHWorker(host, port, user, pwd,
                                 commands=[cmd, f"echo '===LOAD_{self._load_queue_idx}_DONE==='"],
                                 parent=self)
        worker.output_ready.connect(self._on_worker_output)
        if self._load_progress_dlg:
            worker.output_ready.connect(self._load_progress_dlg.append_log)
        worker.data_ready.connect(self._on_load_result)
        worker.start()

    def _on_load_result(self, data):
        if data["type"] != "command_results":
            return
        f = self._load_queue[self._load_queue_idx]
        total = len(self._load_queue)
        idx = self._load_queue_idx + 1
        results = data.get("results", [])
        success = any(f"===LOAD_{self._load_queue_idx}_DONE===" in r.get("stdout", "") for r in results)
        if success:
            msg = f"\u2705 \u52a0\u8f7d\u5b8c\u6210 [{idx}/{total}]: {f}"
            self._log(msg)
        else:
            err = results[0].get("stderr", "\u672a\u77e5\u9519\u8bef") if results else "\u672a\u77e5\u9519\u8bef"
            msg = f"\u274c \u52a0\u8f7d\u5931\u8d25 [{idx}/{total}]: {err[:200]}"
            self._log(msg)
        if self._load_progress_dlg:
            self._load_progress_dlg.append_log(msg)
        self._load_queue_idx += 1
        self._start_next_load()

    def _delete_network(self):
        if not self.ssh_params:
            QMessageBox.warning(self, "提示", "请先连接SSH")
            return
        row = self.net_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择要删除的网络")
            return
        name = self.net_table.item(row, 0).text()
        reply = QMessageBox.question(self, "确认删除",
                                     f"确定要删除网络 {name} 吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._execute_command(f"docker network rm {name}", f"del_network_{name}")

    def _execute_command(self, cmd, action):
        if not self.ssh_params:
            QMessageBox.warning(self, "提示", "请先连接SSH")
            return
        host, port, user, pwd = self.ssh_params
        self._log(f"▶ 执行: {cmd}")
        worker = DockerSSHWorker(host, port, user, pwd,
                                 commands=[cmd, "echo OK"], parent=self)
        worker.output_ready.connect(self._on_worker_output)
        worker.data_ready.connect(lambda d: self._on_action_result(d, action))
        worker.start()

    def _execute_batch_commands(self, commands):
        if not self.ssh_params:
            return
        host, port, user, pwd = self.ssh_params
        self._log(f"▶ 批量导入: {len(commands)} 个容器")
        final_commands = []
        for i, c in enumerate(commands):
            final_commands.append(c)
            final_commands.append(f"echo '===CONTAINER_{i}_DONE==='")
        final_commands.append("echo 'BATCH_IMPORT_DONE'")
        worker = DockerSSHWorker(host, port, user, pwd,
                                 commands=final_commands, parent=self)
        worker.output_ready.connect(self._on_worker_output)
        worker.data_ready.connect(self._on_batch_result)
        worker.start()

    def _on_action_result(self, data, action):
        if data["type"] == "command_results":
            results = data["results"]
            success = any("OK" in r.get("stdout", "") for r in results)
            if success:
                self._log(f"\u2705 {action} \u64cd\u4f5c\u6210\u529f!")
            else:
                err = results[0].get("stderr", "\u672a\u77e5\u9519\u8bef") if results else "\u672a\u77e5\u9519\u8bef"
                self._log(f"\u274c {action} \u64cd\u4f5c\u5931\u8d25: {err[:200]}")
            if action.startswith("service_"):
                self._update_service_btn_states(self.docker_data)
            QTimer.singleShot(500, self._refresh_data)

    def _on_batch_result(self, data):
        if data["type"] == "command_results":
            results = data["results"]
            success = any("BATCH_IMPORT_DONE" in r.get("stdout", "") for r in results)
            count = 0
            for r in results:
                out = r.get("stdout", "")
                if "CONTAINER_" in out and "_DONE" in out:
                    count += 1
            self._log(f"✅ 批量导入完成: {count}/{len(results)//2} 个容器")
            if not success:
                self._log("⚠ 部分容器可能导入失败，请检查日志")
            QTimer.singleShot(500, self._refresh_data)

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {msg}")
        self.logger.info(msg)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = DockerManager()
    w.show()
    sys.exit(app.exec())
