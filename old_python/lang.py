# -*- coding: utf-8 -*-
"""
语言配置文件 - 所有子工具的英文翻译
只包含主要界面元素的翻译
"""

# 英文翻译字典
EN_TEXTS = {
    # ========== Linux_Tools_sub.py ==========
    "LinuxToolsGUI": {
        "window_title": "Linux Tools Suite",
        "user_manage": "User Management",
        "ssh_config": "SSH Configuration",
        "login_test": "Login Test",
        "user_list": "User List",
        "security_check": "Security Check",
    },
    
    # ========== Tool_Passwd_Creat_sub.py ==========
    "PasswdTool": {
        "window_title": "Password Generator",
        "generate": "Generate Password",
        "batch_generate": "Batch Generate",
        "process_excel": "Process Excel",
        "length": "Length:",
        "count": "Count:",
    },
    
    # ========== PDF_Tool_sub.py ==========
    "PDFToolBox": {
        "window_title": "PDF Tools",
        "merge": "Merge PDFs",
        "split": "Split PDF",
        "a4_layout": "A4 Layout",
        "select_file": "Select File",
        "select_files": "Select Files",
    },
    
    # ========== Ping_Scanner_sub.py ==========
    "PingScanner": {
        "window_title": "Ping Scanner",
        "start_scan": "Start Scan",
        "stop_scan": "Stop Scan",
        "export": "Export Results",
        "ip_range": "IP Range:",
        "threads": "Threads:",
    },
    
    # ========== IMS_Tool_sub.py ==========
    "IMSTool": {
        "window_title": "IMS Tools",
        "capture": "Packet Capture",
        "upgrade": "Upgrade NE",
        "logs": "View Logs",
        "sbc_config": "SBC Config",
    },
    
    # ========== Linux_Docker_Tool_sub.py ==========
    "DockerManager": {
        "window_title": "Docker Manager",
        "connect": "Connect",
        "create_container": "Create Container",
        "start_container": "Start Container",
        "stop_container": "Stop Container",
        "image_manage": "Image Management",
    },
    
    # ========== Linux_yum_sub.py ==========
    "MainWindow": {
        "window_title": "YUM Repository Manager",
        "create_local": "Create Local Repo",
        "create_web": "Create Web Repo",
        "manage": "Manage Repos",
        "check_client": "Check Client",
    },
}


def get_text(tool_class, key, default="", lang="zh"):
    """
    根据语言获取翻译文本
    :param tool_class: 工具类名
    :param key: 翻译键
    :param default: 默认文本（中文）
    :param lang: 语言 ("zh" 或 "en")
    :return: 翻译后的文本
    """
    if lang == "zh":
        return default  # 中文模式，返回默认值
    
    # 英文模式
    tool_dict = EN_TEXTS.get(tool_class, {})
    return tool_dict.get(key, default)  # 如果找不到翻译，返回默认值
