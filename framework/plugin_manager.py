# -*- coding: utf-8 -*-
"""
Plugin Manager: 加载 plugins/ 目录下的 .pyd / .py 插件，
维护已加载插件的缓存，并提供按名称获取插件类的接口。
"""
import sys
import os
import importlib
import importlib.util
import logging
from typing import Optional

from framework.plugin_interface import PluginBase

logger = logging.getLogger("toolbox")


class PluginManager:
    """插件管理器 —— 负责扫描、加载、缓存插件。"""

    def __init__(self, plugins_dir: str = None):
        self._plugins_dir = plugins_dir or self._default_plugins_dir()
        self._loaded_modules: dict[str, object] = {}   # module_name -> module
        self._loaded_classes: dict[str, type[PluginBase]] = {}  # name -> class

        # 确保 plugins 目录在搜索路径中
        if self._plugins_dir and self._plugins_dir not in sys.path:
            sys.path.insert(0, self._plugins_dir)

        logger.info("Plugin manager initialized, plugins dir: %s", self._plugins_dir)

    # ── 路径解析 ──────────────────────────────────────────────

    @staticmethod
    def _default_plugins_dir() -> str:
        """自动定位 plugins 目录（支持开发环境和打包后）。"""
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "plugins")

    # ── 扫描与加载 ────────────────────────────────────────────

    def scan_plugins(self) -> list[dict]:
        """扫描 plugins 目录，返回可用插件的元信息列表。

        Returns:
            [{module_name, file_path, is_pyd, ...}, ...]
        """
        results = []
        if not os.path.isdir(self._plugins_dir):
            logger.warning("Plugins directory not found: %s", self._plugins_dir)
            return results

        for fname in os.listdir(self._plugins_dir):
            file_path = os.path.join(self._plugins_dir, fname)
            if not os.path.isfile(file_path):
                continue

            # 支持 .pyd (编译后) 和 .py (开发调试)
            if fname.endswith(".pyd"):
                module_name = fname[:-4]
                results.append({
                    "module_name": module_name,
                    "file_path": file_path,
                    "is_pyd": True,
                })
            elif fname.endswith(".py") and fname != "__init__.py":
                module_name = fname[:-3]
                results.append({
                    "module_name": module_name,
                    "file_path": file_path,
                    "is_pyd": False,
                })

        logger.info("Scanned %d plugins", len(results))
        return results

    def load_plugin_module(self, module_name: str):
        """加载指定模块（优先从缓存返回）。

        Args:
            module_name: 模块名称（不含 .py/.pyd 后缀）

        Returns:
            加载的 module object
        """
        if module_name in self._loaded_modules:
            return self._loaded_modules[module_name]

        try:
            module = importlib.import_module(module_name)
            self._loaded_modules[module_name] = module
            logger.info("Loaded plugin module: %s", module_name)
            return module
        except ImportError as exc:
            logger.error("Failed to load plugin module '%s': %s", module_name, exc)
            raise

    def get_plugin_class(self, module_name: str, class_name: str = None) -> type[PluginBase]:
        """获取指定插件中的 PluginBase 子类。

        Args:
            module_name: 模块名称
            class_name:  类名（None 则自动查找 PluginBase 子类）

        Returns:
            插件类（继承 PluginBase）
        """
        cache_key = f"{module_name}.{class_name or '*'}"
        if cache_key in self._loaded_classes:
            return self._loaded_classes[cache_key]

        module = self.load_plugin_module(module_name)

        if class_name:
            cls = getattr(module, class_name, None)
            if cls is None:
                raise AttributeError(
                    f"Plugin '{module_name}' has no class '{class_name}'"
                )
        else:
            # 自动发现模块内第一个 PluginBase 子类
            cls = self._find_plugin_class(module)
            if cls is None:
                raise TypeError(
                    f"No PluginBase subclass found in module '{module_name}'"
                )

        self._loaded_classes[cache_key] = cls
        return cls

    @staticmethod
    def _find_plugin_class(module) -> Optional[type[PluginBase]]:
        """在模块中查找第一个继承 PluginBase 的类。"""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, PluginBase)
                    and attr is not PluginBase):
                return attr
        return None

    def instantiate_plugin(self, module_name: str, class_name: str = None,
                           parent=None) -> PluginBase:
        """快捷方法：加载并实例化一个插件。

        Args:
            module_name: 模块名称
            class_name:  类名（None=自动查找）
            parent:      父控件

        Returns:
            插件实例（PluginBase 子类实例）
        """
        cls = self.get_plugin_class(module_name, class_name)
        instance = cls()
        return instance

    def reload_plugin(self, module_name: str):
        """重新加载指定插件（用于热更新）。"""
        if module_name in self._loaded_modules:
            del self._loaded_modules[module_name]
        # 清除类缓存
        keys_to_delete = [k for k in self._loaded_classes if k.startswith(module_name)]
        for k in keys_to_delete:
            del self._loaded_classes[k]
        # 从 importlib 缓存中移除
        if module_name in sys.modules:
            del sys.modules[module_name]
        return self.load_plugin_module(module_name)

    def get_plugin_metadata(self, module_name: str) -> dict:
        """获取插件元信息（名称、版本、图标等）。"""
        try:
            cls = self.get_plugin_class(module_name)
            # 创建临时实例获取元信息
            inst = cls()
            return {
                "name": inst.plugin_name,
                "name_en": inst.plugin_name_en,
                "version": inst.plugin_version,
                "icon": inst.plugin_icon,
                "description": inst.plugin_description,
                "description_en": inst.plugin_description_en,
                "tags": inst.plugin_tags,
                "module": module_name,
                "class": cls.__name__,
            }
        except Exception as exc:
            logger.error("Failed to get metadata for '%s': %s", module_name, exc)
            return {
                "name": module_name,
                "version": "0.0.0",
                "icon": "❓",
                "error": str(exc),
            }
