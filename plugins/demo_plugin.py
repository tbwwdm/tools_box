# -*- coding: utf-8 -*-
"""
Demo Plugin — 示例插件，用于测试框架加载流程。
编译：python build/build_plugin.py demo_plugin
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from framework.plugin_interface import PluginBase


class DemoPlugin(PluginBase):
    """示例插件 — 测试框架加载和更新流程。"""

    @property
    def plugin_name(self) -> str:
        return "示例工具"

    @property
    def plugin_name_en(self) -> str:
        return "Demo Tool"

    @property
    def plugin_version(self) -> str:
        return "1.0.0"

    @property
    def plugin_icon(self) -> str:
        return "🧪"

    @property
    def plugin_description(self) -> str:
        return "框架加载测试示例工具"

    @property
    def plugin_description_en(self) -> str:
        return "Framework loading test demo tool"

    @property
    def plugin_tags(self) -> list:
        return ["demo", "test"]

    def create_widget(self, parent: QWidget = None) -> QWidget:
        widget = QWidget(parent)
        widget.setStyleSheet("background: #ffffff;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(16)

        # 标题
        title = QLabel("🧪 示例工具 — 加载成功！")
        title.setFont(QFont("Microsoft YaHei", 22, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a2e;")
        layout.addWidget(title)

        # 说明
        desc = QLabel(
            "这个页面证明插件框架已经正常工作。\n\n"
            "插件从 .pyd 动态加载 → PluginBase.create_widget()\n"
            "→ 框架自动嵌入右侧内容区 → 完成。\n\n"
            "后续你可以把真正的功能界面写在这里。"
        )
        desc.setWordWrap(True)
        desc.setFont(QFont("Microsoft YaHei", 12))
        desc.setStyleSheet("color: #636e72; line-height: 1.8;")
        layout.addWidget(desc)

        # 版本信息
        ver = QLabel(f"版本: {self.plugin_version}")
        ver.setFont(QFont("Microsoft YaHei", 10))
        ver.setStyleSheet("color: #b2bec3;")
        layout.addWidget(ver)

        layout.addStretch()

        # 返回提示
        hint = QLabel("💡 点击左上角「← 返回功能列表」回到主界面")
        hint.setFont(QFont("Microsoft YaHei", 10))
        hint.setStyleSheet("color: #b2bec3; padding: 8px; "
                          "background: #f8f9fa; border-radius: 6px;")
        layout.addWidget(hint)

        return widget
