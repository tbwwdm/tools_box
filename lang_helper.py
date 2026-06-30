# -*- coding: utf-8 -*-
"""
语言辅助工具 - 提供简单的翻译功能
"""

# 英文翻译字典 - 按类名和中文文本映射
TRANSLATIONS = {
    "LinuxToolsGUI": {
        "Linux工具集": "Linux Tools Suite",
        "用户管理": "User Management",
        "SSH配置": "SSH Config",
        "登录测试": "Login Test",
        "用户列表": "User List",
        "安全检查": "Security Check",
    },
    
    "PasswdTool": {
        "密码生成器": "Password Generator",
        "生成密码": "Generate Password",
        "批量生成": "Batch Generate",
        "处理Excel": "Process Excel",
        "密码长度": "Password Length",
        "数量": "Count",
    },
    
    "PDFToolBox": {
        "PDF工具集": "PDF Tools",
        "合并PDF": "Merge PDFs",
        "拆分PDF": "Split PDF",
        "A4拼版": "A4 Layout",
        "选择文件": "Select File",
        "选择文件们": "Select Files",
    },
    
    "PingScanner": {
        "网段Ping扫描器": "Ping Scanner",
        "开始扫描": "Start Scan",
        "停止扫描": "Stop Scan",
        "导出结果": "Export Results",
        "IP网段": "IP Range",
        "线程数": "Threads",
    },
    
    "IMSTool": {
        "IMS工具": "IMS Tools",
        "抓包": "Packet Capture",
        "升级": "Upgrade",
        "日志": "Logs",
        "SBC配置": "SBC Config",
    },
    
    "DockerManager": {
        "Docker自动化": "Docker Manager",
        "连接": "Connect",
        "创建容器": "Create Container",
        "启动容器": "Start Container",
        "停止容器": "Stop Container",
        "镜像管理": "Image Management",
    },
    
    "MainWindow": {
        "YUM源管理器": "YUM Repository Manager",
        "创建本地源": "Create Local Repo",
        "创建Web源": "Create Web Repo",
        "管理源": "Manage Repos",
        "检查客户端": "Check Client",
    },
}


def tr(tool_class, text, lang="zh"):
    """
    翻译文本
    :param tool_class: 工具类名
    :param text: 中文文本
    :param lang: 语言 ("zh" 或 "en")
    :return: 翻译后的文本
    """
    if lang == "zh":
        return text
    
    # 英文模式
    tool_dict = TRANSLATIONS.get(tool_class, {})
    return tool_dict.get(text, text)  # 如果找不到翻译，返回原文


def apply_lang_to_button(button, tool_class, lang="zh"):
    """为按钮应用翻译"""
    if lang == "en":
        text = tr(tool_class, button.text(), lang)
        if text != button.text():
            button.setText(text)


def apply_lang_to_label(label, tool_class, lang="zh"):
    """为标签应用翻译"""
    if lang == "en":
        text = tr(tool_class, label.text(), lang)
        if text != label.text():
            label.setText(text)
