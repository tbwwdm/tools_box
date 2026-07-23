# -*- coding: utf-8 -*-
"""
语言支持模块 - 为所有子工具提供语言切换能力
"""

from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QLineEdit, QComboBox
from PySide6.QtWidgets import QCheckBox, QRadioButton, QGroupBox, QTabWidget
from PySide6.QtWidgets import QTableWidgetItem, QListWidgetItem


class LanguageMixin:
    """
    语言支持混入类 - 为PySide6应用提供动态语言切换
    使用方法：
    1. 让子工具类继承这个类
    2. 在 __init__ 中调用 self.setup_language(lang)
    3. 为所有需要翻译的UI元素设置 objectName
    4. 创建语言字典 LANG_DICT
    """
    
    def setup_language(self, lang="zh"):
        """初始化语言设置"""
        self._current_lang = lang
        self._translatable_widgets = {}  # {objectName: widget}
        
    def set_language(self, lang):
        """切换语言"""
        self._current_lang = lang
        self._update_ui_text()
        
    def _update_ui_text(self):
        """更新所有UI文本 - 需要子类重写"""
        raise NotImplementedError("子类需要实现 _update_ui_text 方法")
    
    def _register_translatable(self, widget, name):
        """注册需要翻译的部件"""
        widget.setObjectName(name)
        self._translatable_widgets[name] = widget
        
    def _get_text(self, key, tool_class_name=None):
        """获取翻译后的文本"""
        if self._current_lang == "zh":
            return key  # 中文使用原文本
        
        if tool_class_name is None:
            tool_class_name = self.__class__.__name__
            
        # 从 lang.py 获取翻译
        try:
            from lang import LANGUAGES
            tool_dict = LANGUAGES.get("en", {}).get(tool_class_name, {})
            return tool_dict.get(key, key)
        except ImportError:
            return key


def translate_ui(widget, lang, translations):
    """
    翻译UI部件的文本
    :param widget: 部件对象
    :param lang: 语言 ("zh" 或 "en")
    :param translations: 翻译字典 {objectName: {zh: "...", en: "..."}}
    """
    if lang == "zh":
        return
        
    # 递归遍历所有子部件
    def translate_widget(w):
        if hasattr(w, 'objectName'):
            name = w.objectName()
            if name in translations:
                text = translations[name].get(lang, translations[name].get("zh", ""))
                if isinstance(w, QLabel):
                    w.setText(text)
                elif isinstance(w, QPushButton):
                    w.setText(text)
                elif isinstance(w, QLineEdit):
                    if 'placeholder' in translations[name]:
                        w.setPlaceholderText(translations[name]['placeholder'].get(lang, ""))
                elif isinstance(w, QComboBox):
                    # 对于ComboBox，需要重新设置选项
                    pass
                elif isinstance(w, QCheckBox):
                    w.setText(text)
                elif isinstance(w, QRadioButton):
                    w.setText(text)
                elif isinstance(w, QGroupBox):
                    w.setTitle(text)
                elif isinstance(w, QTableWidgetItem):
                    w.setText(text)
                elif isinstance(w, QListWidgetItem):
                    w.setText(text)
                    
        # 递归处理子部件
        if hasattr(w, 'children'):
            for child in w.children():
                translate_widget(child)
                
    translate_widget(widget)
