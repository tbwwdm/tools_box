#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPv6 掩码计算器 — IPv6 Mask Calculator Pro
============================================
单文件 PySide6 桌面应用
功能：IPv6 地址计算 / 掩码分析 / 地址范围

Python 3.11+  |  PySide6
"""

import sys
import ipaddress
import math

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QTabWidget,
    QGroupBox, QFrame, QSizePolicy, QSpinBox, QScrollArea, QDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette, QColor


# ═══════════════════════════════════════════════════════════════════════
#  核心计算模块
# ═══════════════════════════════════════════════════════════════════════

class IPv6CalculatorCore:
    """IPv6 核心计算引擎"""

    @staticmethod
    def parse_address(text: str) -> ipaddress.IPv6Network | ipaddress.IPv6Address:
        """解析用户输入，返回 IPv6Network 或 IPv6Address"""
        text = text.strip()
        if "/" in text:
            return ipaddress.IPv6Network(text, strict=False)
        return ipaddress.IPv6Address(text)

    @staticmethod
    def expand_address(addr: ipaddress.IPv6Address) -> str:
        return addr.exploded

    @staticmethod
    def compress_address(addr: ipaddress.IPv6Address) -> str:
        return str(addr)

    @staticmethod
    def get_address_type(addr: ipaddress.IPv6Address) -> str:
        """识别 IPv6 地址类型"""
        if addr == ipaddress.IPv6Address("::"):
            return "Unspecified (::)  —  未指定地址"
        if addr == ipaddress.IPv6Address("::1"):
            return "Loopback (::1)  —  环回地址"
        if addr.ipv4_mapped:
            return "IPv4-Mapped IPv6 (::ffff:0:0/96)  —  IPv4映射地址"
        # 优先匹配特殊前缀（必须在 is_global 之前检查）
        for net, label, cn in [
            ("100::/64", "Discard", "丢弃前缀"),
            ("2001:20::/28", "ORCHIDv2", "ORCHIDv2"),
            ("2001:db8::/32", "Documentation", "文档地址"),
            ("2002::/16", "6to4", "6to4隧道"),
            ("3ffe::/16", "6bone (Deprecated)", "6bone(已弃用)"),
            ("5f00::/16", "ULAv2 (Deprecated)", "ULAv2(已弃用)"),
        ]:
            if addr in ipaddress.IPv6Network(net):
                return f"{label} ({net})  —  {cn}"
        # 通用类型匹配
        if addr.is_multicast:
            return "Multicast (ff00::/8)  —  组播地址"
        if addr.is_link_local:
            return "Link-Local (fe80::/10)  —  链路本地地址"
        if addr.is_site_local:
            return "Site-Local (fec0::/10)  —  站点本地地址(已弃用)"
        if addr.is_private:
            return "Unique Local (fc00::/7)  —  唯一本地地址"
        if addr.is_global:
            return "Global Unicast (2000::/3)  —  全局单播地址"
        return "Unknown / Reserved  —  未知/保留地址"

    @staticmethod
    def hex_mask(prefixlen: int) -> str:
        """根据 prefix length 生成 128 位掩码的十六进制表示"""
        mask = (1 << 128) - (1 << (128 - prefixlen))
        hex_str = f"{mask:032x}"
        groups = [hex_str[i:i+4] for i in range(0, 32, 4)]
        return ":".join(groups).upper()

    @staticmethod
    def calc_address_count(prefixlen: int) -> int:
        if prefixlen > 128:
            return 0
        return 1 << (128 - prefixlen)

    @staticmethod
    def format_address_count(count: int) -> str:
        if count == 1:
            return "1"
        if count >= 2**64:
            exponent = 128 - int(math.log2(count))
            return f"2^(128-{exponent}) = {count:,}"
        if count >= 2**32:
            return f"{count:,}"
        return f"{count:,d}"


    @staticmethod
    def build_expanded_html(addr: ipaddress.IPv6Address, prefixlen: int) -> str:
        """
        生成展开地址的 HTML，整组标记可变主机位。
        只在完整的 16-bit 组边界上染色，边界所在的组不染色。
        例如 /112 → 前7组固定、最后1组橙色；/113 → 前7组固定、第8组边界(不染色)。
        """
        groups = addr.exploded.split(":")
        full_network_groups = prefixlen // 16          # 完全固定的组数
        has_partial = prefixlen % 16 != 0              # 是否有边界组

        html_parts = []
        for i, g in enumerate(groups):
            if i > 0:
                html_parts.append("<span style='color:#585b70;'>:</span>")

            if i < full_network_groups:
                # 完全属于网络前缀 → 正常色
                html_parts.append(f"<span style='color:#cdd6f4;'>{g}</span>")
            elif i == full_network_groups and has_partial:
                # 边界组（部分网络＋部分主机）→ 不染色，正常显示
                html_parts.append(f"<span style='color:#a6adc8;'>{g}</span>")
            else:
                # 完全属于主机部分 → 橙色高亮
                html_parts.append(f"<span style='color:#fab387;font-weight:bold;'>{g}</span>")

        return "".join(html_parts)

    @staticmethod
    def calculate(text: str) -> dict:
        """一站式计算，返回结果字典"""
        result = {
            "input": text.strip(),
            "error": None,
            "is_network": False,
            "address": None,
            "network": None,
            "expanded": "",
            "expanded_html": "",
            "compressed": "",
            "address_type": "",
            "prefix_length": None,
            "subnet_mask": "",
            "first_address": "",
            "last_address": "",
            "total_count": 0,
            "total_count_str": "",
            "next_first": "",
            "next_last": "",
            "is_unspecified": False,
            "is_loopback": False,
            "is_multicast": False,
            "is_link_local": False,
            "is_global": False,
            "is_unique_local": False,
            "ipv4_mapped": None,
        }

        try:
            parsed = IPv6CalculatorCore.parse_address(text)
        except Exception as e:
            result["error"] = f"输入解析失败: {e}"
            return result

        if isinstance(parsed, ipaddress.IPv6Network):
            result["is_network"] = True
            result["network"] = parsed
            addr = parsed.network_address
            result["prefix_length"] = parsed.prefixlen
            result["first_address"] = parsed.network_address.exploded
            result["last_address"] = parsed.broadcast_address.exploded
            # 下一组子网
            step = IPv6CalculatorCore.calc_address_count(parsed.prefixlen)
            next_net = int(parsed.network_address) + step
            next_bcast = int(parsed.broadcast_address) + step
            result["next_first"] = ipaddress.IPv6Address(next_net).exploded
            result["next_last"] = ipaddress.IPv6Address(next_bcast).exploded
            result["total_count"] = IPv6CalculatorCore.calc_address_count(parsed.prefixlen)
            result["total_count_str"] = IPv6CalculatorCore.format_address_count(result["total_count"])
            result["subnet_mask"] = IPv6CalculatorCore.hex_mask(parsed.prefixlen)
        else:
            addr = parsed
            result["prefix_length"] = 128
            result["total_count"] = 1
            result["total_count_str"] = "1"
            result["subnet_mask"] = "FFFF:FFFF:FFFF:FFFF:FFFF:FFFF:FFFF:FFFF"
            result["first_address"] = str(addr)
            result["last_address"] = str(addr)

        result["address"] = addr
        result["expanded"] = IPv6CalculatorCore.expand_address(addr)
        result["compressed"] = IPv6CalculatorCore.compress_address(addr)
        result["address_type"] = IPv6CalculatorCore.get_address_type(addr)
        result["expanded_html"] = IPv6CalculatorCore.build_expanded_html(addr, result["prefix_length"])
        result["is_unspecified"] = addr == ipaddress.IPv6Address("::")
        result["is_loopback"] = addr == ipaddress.IPv6Address("::1")
        result["is_multicast"] = addr.is_multicast
        result["is_link_local"] = addr.is_link_local
        result["is_global"] = addr.is_global
        result["is_unique_local"] = addr.is_private
        if addr.ipv4_mapped:
            result["ipv4_mapped"] = str(addr.ipv4_mapped)

        return result


# ═══════════════════════════════════════════════════════════════════════
#  GUI 界面
# ═══════════════════════════════════════════════════════════════════════

class IPv6CalculatorApp(QMainWindow):
    """IPv6 Calculator Pro 主窗口"""

    APP_STYLE = """
    QMainWindow, QWidget {
        background-color: #1e1e2e;
        color: #cdd6f4;
        font-family: 'Microsoft YaHei', 'Consolas', 'Segoe UI', sans-serif;
    }
    QTabWidget::pane {
        border: 1px solid #313244;
        background-color: #1e1e2e;
    }
    QTabBar::tab {
        background-color: #181825;
        color: #a6adc8;
        padding: 8px 24px;
        margin-right: 2px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        font-size: 13px;
    }
    QTabBar::tab:selected {
        background-color: #313244;
        color: #cdd6f4;
        border-bottom: 2px solid #89b4fa;
    }
    QTabBar::tab:hover:!selected {
        background-color: #252536;
    }
    QGroupBox {
        font-size: 13px;
        font-weight: bold;
        color: #89b4fa;
        border: 1px solid #313244;
        border-radius: 8px;
        margin-top: 14px;
        padding-top: 14px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }
    QLineEdit {
        background-color: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
        border-radius: 6px;
        padding: 10px 14px;
        font-size: 15px;
        font-family: 'Consolas', 'Courier New', monospace;
    }
    QLineEdit:focus {
        border-color: #89b4fa;
    }
    QPushButton {
        background-color: #89b4fa;
        color: #1e1e2e;
        border: none;
        border-radius: 6px;
        padding: 10px 24px;
        font-size: 14px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #74c7ec;
    }
    QPushButton:pressed {
        background-color: #89dceb;
    }
    QPushButton:disabled {
        background-color: #45475a;
        color: #6c7086;
    }
    QTextEdit {
        background-color: #181825;
        color: #cdd6f4;
        border: 1px solid #313244;
        border-radius: 6px;
        padding: 8px;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 14px;
    }
    QLabel {
        color: #cdd6f4;
        font-size: 13px;
    }
    QLabel.section-title {
        color: #6c7086;
        font-size: 11px;
        font-weight: bold;
        letter-spacing: 1px;
    }
    QScrollBar:vertical {
        background-color: #181825;
        width: 10px;
        border: none;
    }
    QScrollBar::handle:vertical {
        background-color: #45475a;
        border-radius: 5px;
        min-height: 30px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPv6 Mask Calculator Pro")
        self.setMinimumSize(900, 780)
        self.resize(950, 860)
        self.setStyleSheet(self.APP_STYLE)
        self._setup_ui()
        self._apply_fonts()

    def _apply_fonts(self):
        font = QFont("Microsoft YaHei", 10)
        self.setFont(font)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Tab 面板 ──
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        main_layout.addWidget(self.tabs)

        self._build_tab_calculator()
        self._build_tab_info()

        # 状态栏
        self.statusBar().setStyleSheet(
            "background-color: #181825; color: #6c7086;"
            "border-top: 1px solid #313244; padding: 2px;"
        )
        self.statusBar().showMessage("就绪 — 输入 IPv6 地址开始计算")

    # ─────────────────────────────────────────────────────────────────
    #  Tab1: IPv6 计算器（唯一功能标签页）
    # ─────────────────────────────────────────────────────────────────

    def _build_tab_calculator(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        # 可滚动区域（防止内容超出窗口高度）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        layout.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        cl = QVBoxLayout(container)
        cl.setSpacing(12)
        cl.setContentsMargins(16, 12, 16, 12)

        # ── 输入区域 ──
        input_group = QGroupBox("IPv6 地址输入")
        ig = QVBoxLayout(input_group)
        ig.setSpacing(8)

        input_row = QHBoxLayout()
        self.addr_input = QLineEdit()
        self.addr_input.setPlaceholderText("例:  2001:db8::/32  |  fd00:aaaa:bbbb:cccc:172:16:0:0/112  |  fe80::1")
        self.addr_input.returnPressed.connect(self._do_calculate)
        input_row.addWidget(self.addr_input, 1)

        self.btn_calc = QPushButton("🔍  计算")
        self.btn_calc.clicked.connect(self._do_calculate)
        self.btn_calc.setFixedWidth(130)
        self.btn_calc.setFixedHeight(42)
        input_row.addWidget(self.btn_calc)
        ig.addLayout(input_row)

        cl.addWidget(input_group)

        # ── 掩码选择（1-128 全部按钮，分多行显示）──
        mask_group = QGroupBox("掩码长度选择  (点击任意 /N 按钮直接计算)")
        mg = QVBoxLayout(mask_group)
        mg.setSpacing(4)

        # 第一行：当前值 SpinBox
        top_row = QHBoxLayout()
        lbl_p = QLabel("当前掩码:  /")
        lbl_p.setStyleSheet("color: #a6adc8; font-size: 13px;")
        top_row.addWidget(lbl_p)

        self.mask_spin = QSpinBox()
        self.mask_spin.setRange(1, 128)
        self.mask_spin.setValue(64)
        self.mask_spin.setFixedWidth(80)
        self.mask_spin.setStyleSheet(
            "QSpinBox { background-color: #313244; color: #cdd6f4;"
            "border: 1px solid #45475a; border-radius: 6px;"
            "padding: 4px 8px; font-size: 15px; font-weight: bold;"
            "font-family: 'Consolas', monospace; }"
            "QSpinBox:focus { border-color: #89b4fa; }"
        )
        self.mask_spin.valueChanged.connect(self._on_mask_changed)
        top_row.addWidget(self.mask_spin)

        lbl_hint = QLabel("  （或点击下方按钮）")
        lbl_hint.setStyleSheet("color: #585b70; font-size: 11px;")
        top_row.addWidget(lbl_hint)
        top_row.addStretch()
        mg.addLayout(top_row)

        # 按钮网格：16 列 × 8 行
        btn_grid = QGridLayout()
        btn_grid.setSpacing(2)

        self.btn_default_style = (
            "QPushButton { background-color: #313244; color: #a6adc8;"
            "border: 1px solid #45475a; border-radius: 3px;"
            "font-size: 9px; font-family: 'Consolas', monospace;"
            "min-width: 32px; min-height: 18px; padding: 0px; }"
            "QPushButton:hover { background-color: #89b4fa; color: #1e1e2e; }"
        )
        self.btn_active_style = (
            "QPushButton { background-color: #89b4fa; color: #1e1e2e;"
            "border: 1px solid #89b4fa; border-radius: 3px;"
            "font-size: 9px; font-family: 'Consolas', monospace;"
            "font-weight: bold;"
            "min-width: 32px; min-height: 18px; padding: 0px; }"
            "QPushButton:hover { background-color: #74c7ec; color: #1e1e2e; }"
        )

        self.mask_buttons = []
        cols = 16
        for mask_val in range(1, 129):
            row = (mask_val - 1) // cols
            col = (mask_val - 1) % cols
            btn = QPushButton(f"/{mask_val}")
            btn.setStyleSheet(self.btn_default_style)
            btn.clicked.connect(lambda checked, m=mask_val: self._apply_prefix(m))
            btn_grid.addWidget(btn, row, col)
            self.mask_buttons.append(btn)

        mg.addLayout(btn_grid)

        cl.addWidget(mask_group)

        # 默认高亮 /64
        self._highlight_mask(64)

        # ── 结果显示区域（逐行展示）──
        core_group = QGroupBox("计算结果")
        cg = QVBoxLayout(core_group)
        cg.setSpacing(6)

        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)
        grid.setColumnStretch(1, 1)  # 值列自动拉伸

        def add_row(grid, row, label_text, attr_name, mono=True, is_expanded=False):
            """添加一行：标签 | 值 | 复制按钮"""
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #6c7086; font-size: 13px;")
            grid.addWidget(lbl, row, 0, Qt.AlignTop)

            if is_expanded:
                val = QLabel("—")
                val.setTextFormat(Qt.RichText)
            else:
                val = QLabel("—")
            val.setObjectName(attr_name)
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if mono:
                val.setStyleSheet(
                    "font-family: 'Consolas', 'Courier New', monospace;"
                    "color: #cdd6f4; font-size: 14px;"
                )
            else:
                val.setStyleSheet("color: #cdd6f4; font-size: 14px;")
            grid.addWidget(val, row, 1)

            copy_btn = QPushButton("📋")
            copy_btn.setFixedSize(26, 26)
            copy_btn.setToolTip("复制")
            copy_btn.setStyleSheet(
                "background-color: transparent; border: 1px solid #45475a;"
                "border-radius: 13px; font-size: 11px; padding: 0;"
            )
            if is_expanded:
                copy_btn.clicked.connect(lambda checked: self._copy_text(
                    self._result_cache.get("expanded", "") if self._result_cache else ""
                ))
            else:
                copy_btn.clicked.connect(lambda checked, v=val: self._copy_text(v.text()))
            grid.addWidget(copy_btn, row, 2)
            return val

        self._result_cache = {}
        self.res_expanded = add_row(grid, 0, "完整展开格式:", "res_expanded", mono=True, is_expanded=True)
        self.res_first = add_row(grid, 1, "起始地址 (Network):", "res_first", mono=True)
        self.res_last = add_row(grid, 2, "结束地址 (Broadcast):", "res_last", mono=True)

        # 下一组子网
        self.res_next_first = add_row(grid, 4, "下一组起始地址:", "res_next_first", mono=True)
        self.res_next_last = add_row(grid, 5, "下一组结束地址:", "res_next_last", mono=True)



        self.res_count = add_row(grid, 6, "地址数量:", "res_count", mono=False)
        self.res_count.setStyleSheet("color: #fab387; font-size: 14px; font-weight: bold;")

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #313244;")
        grid.addWidget(sep, 7, 0, 1, 3)

        self.res_compressed = add_row(grid, 8, "压缩格式:", "res_compressed", mono=True)
        self.res_type = add_row(grid, 9, "地址类型:", "res_type", mono=False)
        self.res_prefix = add_row(grid, 10, "Prefix Length:", "res_prefix")
        self.res_mask = add_row(grid, 11, "子网掩码:", "res_mask", mono=True)

        cg.addLayout(grid)
        cl.addWidget(core_group, 1)

        self.tabs.addTab(tab, "🧮 掩码计算器")

    # ─────────────────────────────────────────────────────────────────
    #  Tab2: 关于
    # ─────────────────────────────────────────────────────────────────

    def _build_tab_info(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 16, 24, 16)

        info = QTextEdit()
        info.setReadOnly(True)
        info.setStyleSheet("background-color: transparent; border: none; font-size: 13px;")
        info.setHtml("""
        <h2 style='color:#89b4fa;'>IPv6 Mask Calculator Pro</h2>
        <p style='color:#a6adc8;'>
        面向网络工程师的 IPv6 地址规划与计算工具。
        </p>
        <h3 style='color:#89b4fa;'>功能</h3>
        <ul style='color:#cdd6f4;'>
        <li>展开地址 — <b style='color:#fab387;'>橙色标记</b>可变主机位</li>
        <li>起始地址 · 结束地址 · 地址总数</li>
        <li>压缩格式 · Prefix Length · 子网掩码</li>
        <li>地址类型自动识别</li>
        </ul>
        <h3 style='color:#89b4fa;'>支持地址类型</h3>
        <p style='color:#cdd6f4;'>
        Global Unicast (2000::/3)  ·  Unique Local (fc00::/7)<br>
        Link-Local (fe80::/10)    ·  Multicast (ff00::/8)<br>
        Loopback (::1)            ·  Unspecified (::)<br>
        Documentation (2001:db8::/32) ·  IPv4-Mapped (::ffff:0:0/96)
        </p>
        <p style='color:#6c7086; margin-top:20px;'>
        Python 3 · PySide6 · ipaddress (stdlib)  |  v2.0
        </p>
        """)
        layout.addWidget(info, 1)

        self.tabs.addTab(tab, "ℹ️ 关于")

    # ═══════════════════════════════════════════════════════════════════
    #  事件处理
    # ═══════════════════════════════════════════════════════════════════

    def _highlight_mask(self, prefix_len: int):
        """高亮对应的掩码按钮，同步 SpinBox"""
        self.mask_spin.blockSignals(True)
        self.mask_spin.setValue(prefix_len)
        self.mask_spin.blockSignals(False)

        for i, btn in enumerate(self.mask_buttons):
            if i + 1 == prefix_len:
                btn.setStyleSheet(self.btn_active_style)
            else:
                btn.setStyleSheet(self.btn_default_style)

    def _fill_example(self, addr: str):
        self.addr_input.setText(addr)
        self._do_calculate()

    def _apply_prefix(self, prefix_len: int):
        """点击掩码按钮时：替换或追加 prefix 后计算"""
        text = self.addr_input.text().strip()
        if not text:
            # 输入为空，自动填入 ::/prefix
            text = f"::/{prefix_len}"
        elif "/" in text:
            # 替换已有 prefix
            base = text.rsplit("/", 1)[0]
            # 如果基础部分看起来像一个纯 IPv6 地址
            try:
                ipaddress.IPv6Address(base)
                text = f"{base}/{prefix_len}"
            except ValueError:
                text = f"{text}/{prefix_len}"  # 兜底追加（不太可能）
        else:
            # 没有 prefix 就追加
            text = f"{text}/{prefix_len}"

        self.addr_input.setText(text)
        self._do_calculate()

    def _on_mask_changed(self, value: int):
        """SpinBox 值改变时触发"""
        self._apply_prefix(value)

    def _do_calculate(self):
        text = self.addr_input.text().strip()
        if not text:
            self.statusBar().showMessage("⚠️ 请输入 IPv6 地址")
            return

        result = IPv6CalculatorCore.calculate(text)
        self._result_cache = result  # 供复制按钮用

        if result["error"]:
            self._set_result_error(result["error"])
            self.statusBar().showMessage(f"❌ {result['error']}")
            return

        # 同步掩码按钮高亮
        prefixlen = result["prefix_length"]
        self._highlight_mask(prefixlen)

        # 1) 展开地址（HTML 彩色标记）
        has_host_bits = prefixlen < 128
        hint = ""
        if has_host_bits:
            hint = "  <span style='color:#6c7086;font-size:12px;font-weight:normal;'>"
            hint += "(<span style='color:#fab387;'>橙色</span> = 主机位, <span style='color:#a6adc8;'>灰色</span> = 边界组)</span>"
        html = f"<span style='font-size:14px;font-family:Consolas,\"Courier New\",monospace;'>{result['expanded_html']}</span>{hint}"
        self.res_expanded.setText(html)

        # 2) 压缩格式
        self.res_compressed.setText(result["compressed"])

        # 3) 地址类型
        self.res_type.setText(result["address_type"])

        # 4) Prefix Length
        if result["is_network"]:
            self.res_prefix.setText(f"/{prefixlen}")
        else:
            self.res_prefix.setText("/128 (单个地址)")

        # 5) 子网掩码
        self.res_mask.setText(result["subnet_mask"])

        # 6) 起始地址
        self.res_first.setText(result["first_address"])

        # 7) 结束地址
        self.res_last.setText(result["last_address"])

        # 下一组子网
        if result["is_network"] and result["next_first"]:
            self.res_next_first.setText(result["next_first"])
            self.res_next_last.setText(result["next_last"])
        else:
            self.res_next_first.setText("—")
            self.res_next_last.setText("—")

        # 8) 地址数量
        count = result["total_count"]
        if count >= 1_000_000:
            self.res_count.setText(f"{result['total_count_str']}  ({count:,d})")
        elif count > 1:
            self.res_count.setText(f"{count:,d}")
        else:
            self.res_count.setText("1")



        if result["ipv4_mapped"]:
            self.res_type.setText(f"{result['address_type']}  →  {result['ipv4_mapped']}")

        self.statusBar().showMessage(
            f"✅ {result['compressed']}  —  /{prefixlen}  —  {result['total_count_str']} 地址"
        )

    def _set_result_error(self, error: str):
        self.res_expanded.setText(f"<span style='color:#f38ba8;'>{error}</span>")
        self.res_compressed.setText("—")
        self.res_type.setText(f"❌ {error}")
        self.res_prefix.setText("—")
        self.res_mask.setText("—")
        self.res_first.setText("—")
        self.res_last.setText("—")
        self.res_next_first.setText("—")
        self.res_next_last.setText("—")
        self.res_count.setText("—")

    def _show_plan_detail(self):
        """打开地址分组规划详情对话框"""
        if not self._plan_data:
            self.statusBar().showMessage("没有可用的规划数据")
            return
        dialog = PlanDialog(self._plan_network, self._plan_data, self)
        dialog.exec()

    def _copy_plan_text(self):
        """复制规划文本到剪贴板"""
        if not self._plan_data:
            self.statusBar().showMessage("没有可用的规划数据")
            return
        lines = [f"地址分组规划 - {self._plan_network}"]
        lines.append("=" * 50)
        for item in self._plan_data:
            lines.append(f"  /{item['prefix']:<4d}  ->  {item['count_str']} 个子网")
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("已复制规划文本到剪贴板", 2000)

    def _copy_text(self, text: str):
        if not text or text == "—":
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.statusBar().showMessage(f"📋 已复制", 2000)


# ═══════════════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 46))
    palette.setColor(QPalette.WindowText, QColor(205, 214, 244))
    palette.setColor(QPalette.Base, QColor(24, 24, 37))
    palette.setColor(QPalette.AlternateBase, QColor(49, 50, 68))
    palette.setColor(QPalette.ToolTipBase, QColor(205, 214, 244))
    palette.setColor(QPalette.ToolTipText, QColor(24, 24, 37))
    palette.setColor(QPalette.Text, QColor(205, 214, 244))
    palette.setColor(QPalette.Button, QColor(49, 50, 68))
    palette.setColor(QPalette.ButtonText, QColor(205, 214, 244))
    palette.setColor(QPalette.BrightText, QColor(243, 139, 168))
    palette.setColor(QPalette.Highlight, QColor(137, 180, 250))
    palette.setColor(QPalette.HighlightedText, QColor(24, 24, 37))
    app.setPalette(palette)

    window = IPv6CalculatorApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

