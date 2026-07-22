# -*- coding: utf-8 -*-
"""
Plugin interface: 所有插件必须继承 PluginBase 并实现其抽象方法。
"""
from abc import ABC, abstractmethod
from PySide6.QtWidgets import QWidget


class PluginBase(ABC):
    """插件基类 —— 所有 .pyd 插件必须实现此接口。"""

    # ── 元信息（属性） ──────────────────────────────────────────
    @property
    @abstractmethod
    def plugin_name(self) -> str:
        """插件中文名称，例如 'Linux工具集'"""
        ...

    @property
    @abstractmethod
    def plugin_name_en(self) -> str:
        """插件英文名称，例如 'Linux Tools'"""
        ...

    @property
    @abstractmethod
    def plugin_version(self) -> str:
        """插件版本号，例如 '1.0.0'"""
        ...

    @property
    @abstractmethod
    def plugin_icon(self) -> str:
        """插件图标（Emoji 或文字，显示在网格卡片上），例如 '💻'"""
        ...

    @property
    @abstractmethod
    def plugin_description(self) -> str:
        """插件中文描述"""
        ...

    @property
    @abstractmethod
    def plugin_description_en(self) -> str:
        """插件英文描述"""
        ...

    @property
    @abstractmethod
    def plugin_tags(self) -> list:
        """插件标签列表，例如 ['linux', 'system', 'admin']"""
        ...

    # ── 生命周期 ────────────────────────────────────────────────

    @abstractmethod
    def create_widget(self, parent: QWidget = None) -> QWidget:
        """创建并返回插件的主界面控件。

        Args:
            parent: 父控件（由主框架传入）

        Returns:
            插件的主 QWidget，主框架会将其放入右侧内容区。
        """
        ...

    def on_activated(self):
        """插件被激活时调用（可选重写）。"""
        pass

    def on_deactivated(self):
        """插件被切换走时调用（可选重写）。"""
        pass

    def on_language_changed(self, lang: str):
        """语言切换回调（可选重写）。"""
        pass
