#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NTP配置工具
使用PySide6创建图形界面，用于批量配置Linux服务器的NTP时间同步
"""


import sys
import os
import json
import logging
import paramiko
import pandas as pd
from datetime import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                            QHBoxLayout, QLabel, QLineEdit,
                            QPushButton, QTextEdit, QFileDialog, QMessageBox,
                            QSpinBox, QGroupBox, QProgressBar, QSplitter, QComboBox, QCompleter)
from PySide6.QtCore import QThread, Signal, Qt, QStringListModel
from PySide6.QtGui import QFont, QTextCursor

logger = logging.getLogger(__name__)


ALL_TIMEZONES = [
    "","Africa/Abidjan", "Africa/Accra", "Africa/Addis_Ababa", "Africa/Algiers",
    "Africa/Asmara", "Africa/Bamako", "Africa/Bangui", "Africa/Banjul",
    "Africa/Bissau", "Africa/Blantyre", "Africa/Brazzaville", "Africa/Bujumbura",
    "Africa/Cairo", "Africa/Casablanca", "Africa/Ceuta", "Africa/Conakry",
    "Africa/Dakar", "Africa/Dar_es_Salaam", "Africa/Djibouti", "Africa/Douala",
    "Africa/El_Aaiun", "Africa/Freetown", "Africa/Gaborone", "Africa/Harare",
    "Africa/Johannesburg", "Africa/Juba", "Africa/Kampala", "Africa/Khartoum",
    "Africa/Kigali", "Africa/Kinshasa", "Africa/Lagos", "Africa/Libreville",
    "Africa/Lome", "Africa/Luanda", "Africa/Lubumbashi", "Africa/Lusaka",
    "Africa/Malabo", "Africa/Maputo", "Africa/Maseru", "Africa/Mbabane",
    "Africa/Mogadishu", "Africa/Monrovia", "Africa/Nairobi", "Africa/Ndjamena",
    "Africa/Niamey", "Africa/Nouakchott", "Africa/Ouagadougou", "Africa/Porto-Novo",
    "Africa/Sao_Tome", "Africa/Tripoli", "Africa/Tunis", "Africa/Windhoek",
    "America/Adak", "America/Anchorage", "America/Anguilla", "America/Antigua",
    "America/Araguaina", "America/Argentina/Buenos_Aires", "America/Argentina/Catamarca",
    "America/Argentina/Cordoba", "America/Argentina/Jujuy", "America/Argentina/La_Rioja",
    "America/Argentina/Mendoza", "America/Argentina/Rio_Gallegos", "America/Argentina/Salta",
    "America/Argentina/San_Juan", "America/Argentina/San_Luis", "America/Argentina/Tucuman",
    "America/Argentina/Ushuaia", "America/Aruba", "America/Asuncion", "America/Atikokan",
    "America/Bahia", "America/Bahia_Banderas", "America/Barbados", "America/Belem",
    "America/Belize", "America/Blanc-Sablon", "America/Boa_Vista", "America/Bogota",
    "America/Boise", "America/Cambridge_Bay", "America/Campo_Grande", "America/Cancun",
    "America/Caracas", "America/Cayenne", "America/Cayman", "America/Chicago",
    "America/Chihuahua", "America/Costa_Rica", "America/Creston", "America/Cuiaba",
    "America/Curacao", "America/Danmarkshavn", "America/Dawson", "America/Dawson_Creek",
    "America/Denver", "America/Detroit", "America/Dominica", "America/Edmonton",
    "America/Eirunepe", "America/El_Salvador", "America/Fort_Nelson", "America/Fortaleza",
    "America/Glace_Bay", "America/Goose_Bay", "America/Grand_Turk", "America/Grenada",
    "America/Guadeloupe", "America/Guatemala", "America/Guayaquil", "America/Guyana",
    "America/Halifax", "America/Havana", "America/Hermosillo", "America/Indiana/Indianapolis",
    "America/Indiana/Knox", "America/Indiana/Marengo", "America/Indiana/Petersburg",
    "America/Indiana/Tell_City", "America/Indiana/Vevay", "America/Indiana/Vincennes",
    "America/Indiana/Winamac", "America/Inuvik", "America/Iqaluit", "America/Jamaica",
    "America/Juneau", "America/Kentucky/Louisville", "America/Kentucky/Monticello",
    "America/Kralendijk", "America/La_Paz", "America/Lima", "America/Los_Angeles",
    "America/Lower_Princes", "America/Maceio", "America/Managua", "America/Manaus",
    "America/Marigot", "America/Martinique", "America/Matamoros", "America/Mazatlan",
    "America/Menominee", "America/Merida", "America/Metlakatla", "America/Mexico_City",
    "America/Miquelon", "America/Moncton", "America/Monterrey", "America/Montevideo",
    "America/Montserrat", "America/Nassau", "America/New_York", "America/Nipigon",
    "America/Nome", "America/Noronha", "America/North_Dakota/Beulah", "America/North_Dakota/Center",
    "America/North_Dakota/New_Salem", "America/Nuuk", "America/Ojinaga", "America/Panama",
    "America/Pangnirtung", "America/Paramaribo", "America/Phoenix", "America/Port-au-Prince",
    "America/Port_of_Spain", "America/Porto_Velho", "America/Puerto_Rico", "America/Punta_Arenas",
    "America/Rainy_River", "America/Rankin_Inlet", "America/Recife", "America/Regina",
    "America/Resolute", "America/Rio_Branco", "America/Santarem", "America/Santiago",
    "America/Santo_Domingo", "America/Sao_Paulo", "America/Scoresbysund", "America/Sitka",
    "America/St_Barthelemy", "America/St_Johns", "America/St_Kitts", "America/St_Lucia",
    "America/St_Thomas", "America/St_Vincent", "America/Swift_Current", "America/Tegucigalpa",
    "America/Thule", "America/Thunder_Bay", "America/Tijuana", "America/Toronto",
    "America/Tortola", "America/Vancouver", "America/Whitehorse", "America/Winnipeg",
    "America/Yakutat", "America/Yellowknife", "Antarctica/Casey", "Antarctica/Davis",
    "Antarctica/DumontDUrville", "Antarctica/Macquarie", "Antarctica/Mawson",
    "Antarctica/McMurdo", "Antarctica/Palmer", "Antarctica/Rothera", "Antarctica/Syowa",
    "Antarctica/Troll", "Antarctica/Vostok", "Arctic/Longyearbyen", "Asia/Aden",
    "Asia/Almaty", "Asia/Amman", "Asia/Anadyr", "Asia/Aqtau", "Asia/Aqtobe",
    "Asia/Ashgabat", "Asia/Atyrau", "Asia/Baghdad", "Asia/Bahrain", "Asia/Baku",
    "Asia/Bangkok", "Asia/Barnaul", "Asia/Beirut", "Asia/Bishkek", "Asia/Brunei",
    "Asia/Chita", "Asia/Choibalsan", "Asia/Colombo", "Asia/Damascus", "Asia/Dhaka",
    "Asia/Dili", "Asia/Dubai", "Asia/Dushanbe", "Asia/Famagusta", "Asia/Gaza",
    "Asia/Hebron", "Asia/Ho_Chi_Minh", "Asia/Hong_Kong", "Asia/Hovd", "Asia/Irkutsk",
    "Asia/Jakarta", "Asia/Jayapura", "Asia/Jerusalem", "Asia/Kabul", "Asia/Kamchatka",
    "Asia/Karachi", "Asia/Kathmandu", "Asia/Khandyga", "Asia/Kolkata", "Asia/Krasnoyarsk",
    "Asia/Kuala_Lumpur", "Asia/Kuching", "Asia/Kuwait", "Asia/Macau", "Asia/Magadan",
    "Asia/Makassar", "Asia/Manila", "Asia/Muscat", "Asia/Nicosia", "Asia/Novokuznetsk",
    "Asia/Novosibirsk", "Asia/Omsk", "Asia/Oral", "Asia/Phnom_Penh", "Asia/Pontianak",
    "Asia/Pyongyang", "Asia/Qatar", "Asia/Qostanay", "Asia/Qyzylorda", "Asia/Riyadh",
    "Asia/Sakhalin", "Asia/Samarkand", "Asia/Seoul", "Asia/Shanghai", "Asia/Singapore",
    "Asia/Srednekolymsk", "Asia/Taipei", "Asia/Tashkent", "Asia/Tbilisi", "Asia/Tehran",
    "Asia/Thimphu", "Asia/Tokyo", "Asia/Tomsk", "Asia/Ulaanbaatar", "Asia/Urumqi",
    "Asia/Ust-Nera", "Asia/Vientiane", "Asia/Vladivostok", "Asia/Yakutsk", "Asia/Yangon",
    "Asia/Yekaterinburg", "Asia/Yerevan", "Atlantic/Azores", "Atlantic/Bermuda",
    "Atlantic/Canary", "Atlantic/Cape_Verde", "Atlantic/Faroe", "Atlantic/Madeira",
    "Atlantic/Reykjavik", "Atlantic/South_Georgia", "Atlantic/St_Helena", "Atlantic/Stanley",
    "Australia/Adelaide", "Australia/Brisbane", "Australia/Broken_Hill", "Australia/Darwin",
    "Australia/Eucla", "Australia/Hobart", "Australia/Lindeman", "Australia/Lord_Howe",
    "Australia/Melbourne", "Australia/Perth", "Australia/Sydney", "Europe/Amsterdam",
    "Europe/Andorra", "Europe/Astrakhan", "Europe/Athens", "Europe/Belgrade",
    "Europe/Berlin", "Europe/Bratislava", "Europe/Brussels", "Europe/Bucharest",
    "Europe/Budapest", "Europe/Busingen", "Europe/Chisinau", "Europe/Copenhagen",
    "Europe/Dublin", "Europe/Gibraltar", "Europe/Guernsey", "Europe/Helsinki",
    "Europe/Isle_of_Man", "Europe/Istanbul", "Europe/Jersey", "Europe/Kaliningrad",
    "Europe/Kiev", "Europe/Kirov", "Europe/Lisbon", "Europe/Ljubljana", "Europe/London",
    "Europe/Luxembourg", "Europe/Madrid", "Europe/Malta", "Europe/Mariehamn",
    "Europe/Minsk", "Europe/Monaco", "Europe/Moscow", "Europe/Oslo", "Europe/Paris",
    "Europe/Podgorica", "Europe/Prague", "Europe/Riga", "Europe/Rome", "Europe/Samara",
    "Europe/San_Marino", "Europe/Sarajevo", "Europe/Saratov", "Europe/Simferopol",
    "Europe/Skopje", "Europe/Sofia", "Europe/Stockholm", "Europe/Tallinn", "Europe/Tirane",
    "Europe/Ulyanovsk", "Europe/Uzhgorod", "Europe/Vaduz", "Europe/Vatican",
    "Europe/Vienna", "Europe/Vilnius", "Europe/Volgograd", "Europe/Warsaw",
    "Europe/Zagreb", "Europe/Zaporozhye", "Europe/Zurich", "Indian/Antananarivo",
    "Indian/Chagos", "Indian/Christmas", "Indian/Cocos", "Indian/Comoro",
    "Indian/Kerguelen", "Indian/Mahe", "Indian/Maldives", "Indian/Mauritius",
    "Indian/Mayotte", "Indian/Reunion", "Pacific/Apia", "Pacific/Auckland",
    "Pacific/Bougainville", "Pacific/Chatham", "Pacific/Chuuk", "Pacific/Easter",
    "Pacific/Efate", "Pacific/Enderbury", "Pacific/Fakaofo", "Pacific/Fiji",
    "Pacific/Funafuti", "Pacific/Galapagos", "Pacific/Gambier", "Pacific/Guadalcanal",
    "Pacific/Guam", "Pacific/Honolulu", "Pacific/Kiritimati", "Pacific/Kosrae",
    "Pacific/Kwajalein", "Pacific/Majuro", "Pacific/Marquesas", "Pacific/Midway",
    "Pacific/Nauru", "Pacific/Niue", "Pacific/Norfolk", "Pacific/Noumea",
    "Pacific/Pago_Pago", "Pacific/Palau", "Pacific/Pitcairn", "Pacific/Pohnpei",
    "Pacific/Port_Moresby", "Pacific/Rarotonga", "Pacific/Saipan", "Pacific/Tahiti",
    "Pacific/Tarawa", "Pacific/Tongatapu", "Pacific/Wake", "Pacific/Wallis", "UTC"
]

class SSHWorker(QThread):
    """SSH操作工作线程"""
    log_signal = Signal(str)
    progress_signal = Signal(int)
    finished_signal = Signal()
    
    def __init__(self, servers, ntp_config, operation):
        super().__init__()
        self.servers = servers
        self.ntp_config = ntp_config
        self.operation = operation
        self.is_running = True
        
    def run(self):
        """执行SSH操作"""
        total_servers = len(self.servers)
        
        for i, server in enumerate(self.servers):
            if not self.is_running:
                break
                
            try:
                # self.log_signal.emit(f"正在连接服务器: {server['host']}:{server['port']}")
                
                # 创建SSH连接
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # 连接服务器
                ssh.connect(
                    hostname=server['host'],
                    port=server['port'],
                    username=server['username'],
                    password=server['password'],
                    timeout=30
                )
                
                if self.operation == "configure":
                    self._configure_ntp(ssh, server)
                elif self.operation == "restore":
                    self._restore_ntp(ssh, server)
                elif self.operation == "status":
                    self._get_ntp_status(ssh, server)
                    
                ssh.close()
                # 仅在非"获取状态"操作时输出完成日志
                #if self.operation == "configure" :
                #    self.log_signal.emit(f"服务器 {server['host']} 配置操作完成")
            
            except Exception as e:
                self.log_signal.emit(f"服务器 {server['host']} 配置操作失败: {str(e)} 请检查!!!")
            
            # 更新进度
            progress = int((i + 1) / total_servers * 100)
            self.progress_signal.emit(progress)
            
        self.finished_signal.emit()

    def _configure_ntp(self, ssh, server):
        """配置NTP"""
        # 检测操作系统，Ubuntu 使用不同的 chrony 配置文件路径
        stdin, stdout, stderr = ssh.exec_command("grep '^ID=' /etc/os-release")
        os_id = stdout.read().decode().strip()
        is_ubuntu = 'ubuntu' in os_id.lower()
        chrony_conf = "/etc/chrony/chrony.conf" if is_ubuntu else "/etc/chrony.conf"

        # 备份原始配置
        backup_cmd = f"cp {chrony_conf} {chrony_conf}.backup.$(date +%Y%m%d_%H%M%S)"
        stdin, stdout, stderr = ssh.exec_command(backup_cmd)
        stdout.read()

        # 停止chrony服务
        ssh.exec_command("systemctl stop chronyd")

        # 修改配置文件（先清理旧行，再注释现有条目，最后添加新配置）
        # 1) 删除未注释/已注释的 server 与 makestep 行
        ssh.exec_command(f"sed -i '/^server.*6$/d' {chrony_conf}")
        ssh.exec_command(f"sed -i '/^makestep.*1$/d' {chrony_conf}")
        ssh.exec_command(f"sed -i '/^#server.*6$/d' {chrony_conf}")
        ssh.exec_command(f"sed -i '/^#makestep.*1$/d' {chrony_conf}")
        ssh.exec_command(f"sed -i '/^#.*#$/d' {chrony_conf}")

        # 2) 注释 pool/server/makestep 开头的现有行
        ssh.exec_command(f"sed -i '/^pool/s/^/#/' {chrony_conf}")
        ssh.exec_command(f"sed -i '/^server/s/^/#/' {chrony_conf}")
        ssh.exec_command(f"sed -i '/^makestep/s/^/#/' {chrony_conf}")

        # 3) 追加由界面参数生成的新配置
        server_addr = str(self.ntp_config['server']).strip()
        minpoll_val = int(self.ntp_config['minpoll'])
        maxpoll_val = int(self.ntp_config['maxpoll'])
        step_val = int(self.ntp_config['step'])
        timezone = str(self.ntp_config['timezone']).strip()

        ssh.exec_command(f"""echo "### ADD NTP Server Config ###" >> {chrony_conf}""")
        ssh.exec_command(
            f"""echo "server {server_addr} iburst minpoll {minpoll_val} maxpoll {maxpoll_val}" >> {chrony_conf}""")
        ssh.exec_command(f"""echo "makestep 1.0 {step_val}" >> {chrony_conf}""")
        if timezone != "":
            ssh.exec_command(f"timedatectl set-timezone {timezone}")

        # 启动chrony服务
        ssh.exec_command("systemctl start chronyd")
        ssh.exec_command("systemctl enable chronyd")

        # 检查服务状态和开机自启状态
        stdin, stdout, stderr = ssh.exec_command("systemctl is-active chronyd")
        service_status = stdout.read().decode().strip()

        stdin, stdout, stderr = ssh.exec_command("systemctl is-enabled chronyd")
        enabled_status = stdout.read().decode().strip()

        stdin, stdout, stderr = ssh.exec_command("timedatectl")
        timedatectl_status = stdout.read().decode().strip()
        # 提取本地时间
        local_time = timedatectl_status.split("Local time: ")[1].split("\n")[0].strip()
        # 提取时区
        time_zone = timedatectl_status.split("Time zone: ")[1].split("\n")[0].strip()

        # 输出配置完成信息（等宽对齐）
        host_col = f"服务器 {server['host']:<15}"
        config_col = f"NTP配置完成"
        service_col = f"NTP服务状态:{service_status:<2}"
        enabled_col = f"开机自启:{enabled_status:<2}"
        timezone_col = f"时区:{time_zone:<2}"
        local_time_col = f"系统时间:{local_time:<2}"
        self.log_signal.emit(
            f"{host_col}   {config_col}   {service_col}   {enabled_col}   {timezone_col}   {local_time_col}")


    def _restore_ntp(self, ssh, server):
        """还原NTP配置"""
        #self.log_signal.emit(f"正在还原 {server['host']} 的NTP配置...")
        
        # 查找最新的备份文件    
        find_cmd = "ls -t /etc/chrony.conf.backup.* 2>/dev/null | head -1"
        stdin, stdout, stderr = ssh.exec_command(find_cmd)
        backup_file = stdout.read().decode().strip()
        
        if backup_file:
            # 还原配置
            restore_cmd = f"cp {backup_file} /etc/chrony.conf"
            ssh.exec_command(restore_cmd)
            ssh.exec_command("systemctl restart chronyd")
            self.log_signal.emit(f"服务器 {server['host']} 使用备份文件还原NTP配置已成功")
        else:
            self.log_signal.emit(f"服务器 {server['host']} 未找到备份文件")
    
    def _get_ntp_status(self, ssh, server):
        """获取NTP状态"""
        #self.log_signal.emit(f"正在获取 {server['host']} 的NTP状态...")

        # 1) NTP服务状态
        stdin, stdout, stderr = ssh.exec_command("systemctl is-active chronyd")
        is_active = stdout.read().decode().strip()
        service_ok = (is_active == "active")

        # # 2) NTP同步状态（chronyc）
        # stdin, stdout, stderr = ssh.exec_command("chronyc sources -v || chronyc sources")
        # sources_output = stdout.read().decode(errors='ignore')
        # synced = False
        # for line in sources_output.splitlines():
        #     s = line.lstrip()
        #     if s.startswith('^*') or s.startswith('*'):
        #         synced = True
        #         break

        # 2) NTP同步状态（chronyc）
        stdin, stdout, stderr = ssh.exec_command("chronyc sources -v || chronyc sources")
        sources_output = stdout.read().decode(errors='ignore')
        synced = False
        ntp_server_ip = "Not_Server_IP"  # 改为默认值而不是 None

        for line in sources_output.splitlines():
            s = line.lstrip()
            if s.startswith('^*') or s.startswith('*'):
                synced = True
                # 提取IP：去掉 * 或 ^* 前缀，取第一个字段
                parts = s.lstrip('^*').split()
                if parts:
                    ntp_server_ip = parts[0]
                break

        # 3) 当前时间
        stdin, stdout, stderr = ssh.exec_command("date '+%F %T'")
        current_time = stdout.read().decode().strip()

        stdin, stdout, stderr = ssh.exec_command("timedatectl")
        timedatectl_status = stdout.read().decode().strip()
        # 提取本地时间
        local_time = timedatectl_status.split("Local time: ")[1].split("\n")[0].strip()
        # 提取时区
        time_zone = timedatectl_status.split("Time zone: ")[1].split("\n")[0].strip()

        # 中文字符宽度处理函数
        def fix_width(text, width):
            display_width = sum(2 if '\u4e00' <= c <= '\u9fff' else 1 for c in text)
            return text + ' ' * (width - display_width)

        service_text = "正常" if service_ok else "异常!!!"
        sync_text = "正常" if synced else "异常!!!"

        # 输出一行综合信息（等宽对齐各列）
        host_col = f"客户端服务器 {server['host']:<15}"
        service_col = f"NTP服务:{fix_width(service_text, 7)}"
        sync_col = f"NTP同步状态:{fix_width(sync_text, 7)}"
        server_ip_col = f"NTP服务器:{fix_width(ntp_server_ip, 14)}"
        timezone_col = f"时区:{fix_width(time_zone, 20)}"  # 时区较长，给20宽度
        time_col = f"当前系统时间:{local_time}"

        self.log_signal.emit(f"{host_col}   {service_col}   {sync_col}  {server_ip_col} {timezone_col}  {time_col}")


    
    def stop(self):
        """停止操作"""
        self.is_running = False


class NTPConfigTool(QMainWindow):
    """NTP配置工具主窗口"""
    
    def __init__(self):
        super().__init__()
        self.servers = []
        self.ssh_worker = None
        self._init_logging()
        self.init_ui()

    def _init_logging(self):
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(log_dir, f"NTP配置_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
            encoding="utf-8")
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)
        
    def init_ui(self):
        self.setWindowTitle("NTP配置工具")
        self.setGeometry(200, 130, 1450, 700)

        central = QWidget()
        central.setObjectName("ntp_central")
        central.setStyleSheet("""
            QWidget#ntp_central { background:#f5f6fa; }
            QLineEdit { border:none; border-bottom:1px solid #dfe6e9; padding:6px 4px; background:transparent; font-size:13px; }
            QLineEdit:focus { border-bottom:2px solid #0984e3; }
            QSpinBox { border:none; border-bottom:1px solid #dfe6e9; padding:4px 2px; background:transparent; }
            QSpinBox:focus { border-bottom:2px solid #0984e3; }
            QComboBox { border:none; border-bottom:1px solid #dfe6e9; padding:6px 4px; background:transparent; font-size:13px; }
            QComboBox:focus { border-bottom:2px solid #0984e3; }
            QTextEdit { border:1px solid #dfe6e9; border-radius:4px; background:white; font-size:13px; }
            QProgressBar { border:none; border-radius:4px; text-align:center; height:6px; background:#dfe6e9; }
            QProgressBar::chunk { background:#0984e3; border-radius:3px; }
        """)
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(28, 24, 28, 24)

        # 文件
        l1 = QHBoxLayout()
        l1.addWidget(QLabel("配置文件"))
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("选择包含SSH登录信息的配置文件")
        self.file_path_edit.setReadOnly(True)
        l1.addWidget(self.file_path_edit)
        self.select_file_btn = QPushButton("选择文件")
        self.select_file_btn.setStyleSheet("QPushButton{background:#0984e3;color:white;padding:7px 20px;border:none;border-radius:4px;font-size:13px;}QPushButton:hover{background:#0873c4;}")
        self.select_file_btn.clicked.connect(self.select_file)
        l1.addWidget(self.select_file_btn)
        layout.addLayout(l1)

        layout.addSpacing(12)

        # NTP配置
        l2 = QHBoxLayout()
        l2.addWidget(QLabel("NTP服务器"))
        self.ntp_server_edit = QLineEdit()
        self.ntp_server_edit.setPlaceholderText("ntp.aliyun.com")
        self.ntp_server_edit.setText("ntp.aliyun.com")
        l2.addWidget(self.ntp_server_edit)
        l2.addSpacing(20)
        l2.addWidget(QLabel("MinPoll"))
        self.minpoll_spin = QSpinBox()
        self.minpoll_spin.setRange(3, 17); self.minpoll_spin.setValue(3)
        l2.addWidget(self.minpoll_spin)
        l2.addWidget(QLabel("MaxPoll"))
        self.maxpoll_spin = QSpinBox()
        self.maxpoll_spin.setRange(3, 17); self.maxpoll_spin.setValue(6)
        l2.addWidget(self.maxpoll_spin)
        l2.addWidget(QLabel("Step"))
        self.step_spin = QSpinBox()
        self.step_spin.setRange(-1, 1); self.step_spin.setValue(-1)
        l2.addWidget(self.step_spin)
        l2.addWidget(QLabel("时区"))
        self.timezone_combo = QComboBox()
        self.timezone_combo.setEditable(True)
        self.timezone_combo.setInsertPolicy(QComboBox.NoInsert)
        for tz in ALL_TIMEZONES:
            self.timezone_combo.addItem(tz)
        cmpl = QCompleter()
        cmpl.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        cmpl.setFilterMode(Qt.MatchFlag.MatchContains)
        cmpl.setModel(QStringListModel(ALL_TIMEZONES))
        self.timezone_combo.setCompleter(cmpl)
        self.timezone_combo.setCurrentText("Asia/Shanghai")
        l2.addWidget(self.timezone_combo)
        l2.addStretch()
        layout.addLayout(l2)

        layout.addSpacing(16)

        # 按钮
        btn_row = QHBoxLayout()
        self.configure_btn = QPushButton("执行配置"); self.configure_btn.clicked.connect(self.configure_ntp)
        self.configure_btn.setStyleSheet("QPushButton{background:#27ae60;color:white;font-weight:bold;padding:8px 24px;border:none;border-radius:4px;font-size:13px;}QPushButton:hover{background:#219a52;}QPushButton:disabled{background:#b2bec3;}")
        btn_row.addWidget(self.configure_btn)
        self.restore_btn = QPushButton("还原配置"); self.restore_btn.clicked.connect(self.restore_ntp)
        self.restore_btn.setStyleSheet("QPushButton{background:#e67e22;color:white;font-weight:bold;padding:8px 24px;border:none;border-radius:4px;font-size:13px;}QPushButton:hover{background:#d35400;}QPushButton:disabled{background:#b2bec3;}")
        btn_row.addWidget(self.restore_btn)
        self.status_btn = QPushButton("获取状态"); self.status_btn.clicked.connect(self.get_status)
        self.status_btn.setStyleSheet("QPushButton{background:#0984e3;color:white;font-weight:bold;padding:8px 24px;border:none;border-radius:4px;font-size:13px;}QPushButton:hover{background:#0873c4;}QPushButton:disabled{background:#b2bec3;}")
        btn_row.addWidget(self.status_btn)
        self.clear_btn = QPushButton("清空日志"); self.clear_btn.clicked.connect(self.clear_log)
        self.clear_btn.setStyleSheet("QPushButton{background:#e74c3c;color:white;font-weight:bold;padding:8px 24px;border:none;border-radius:4px;font-size:13px;}QPushButton:hover{background:#c0392b;}QPushButton:disabled{background:#b2bec3;}")
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addSpacing(8)

        # 日志
        self.log_text = QTextEdit()
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.log_message("NTP配置工具已启动")
        
    def select_file(self):
        """选择服务器配置文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择服务器配置文件", 
            "", 
            "Excel文件 (*.xlsx *.xls);;JSON文件 (*.json);;文本文件 (*.txt);;所有文件 (*)"
        )
        
        if file_path:
            self.file_path_edit.setText(file_path)
            self.load_servers(file_path)
    
    def load_servers(self, file_path):
        """加载服务器配置"""
        try:
            if file_path.endswith(('.xlsx', '.xls')):
                # 处理Excel文件格式
                df = pd.read_excel(file_path)
                
                # 检查必需的列 - 支持两种格式
                if all(col in df.columns for col in ['host', 'port', 'username', 'password']):
                    # 使用新格式: host, port, username, password
                    df = df.dropna(subset=['host', 'username', 'password'])
                    self.servers = []
                    for _, row in df.iterrows():
                        server = {
                            'host': str(row['host']).strip(),
                            'port': int(row['port']) if pd.notna(row['port']) else 22,
                            'username': str(row['username']).strip(),
                            'password': str(row['password']).strip()
                        }
                        self.servers.append(server)
                elif all(col in df.columns for col in ['IP', '用户名', '密码']):
                    # 使用旧格式: IP, 用户名, 密码
                    df = df.dropna(subset=['IP', '用户名', '密码'])
                    self.servers = []
                    for _, row in df.iterrows():
                        server = {
                            'host': str(row['IP']).strip(),
                            'port': 22,  # 默认SSH端口
                            'username': str(row['用户名']).strip(),
                            'password': str(row['密码']).strip()
                        }
                        self.servers.append(server)
                else:
                    raise ValueError("Excel文件格式不正确，需要包含以下列之一：\n格式1: host, port, username, password\n格式2: IP, 用户名, 密码")
                    
            elif file_path.endswith('.json'):
                # 处理JSON文件格式
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.servers = json.load(f)
            else:
                # 处理文本文件格式
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    self.servers = []
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            parts = line.split(',')
                            if len(parts) >= 4:
                                server = {
                                    'host': parts[0].strip(),
                                    'port': int(parts[1].strip()) if len(parts) > 1 else 22,
                                    'username': parts[2].strip(),
                                    'password': parts[3].strip()
                                }
                                self.servers.append(server)
            
            self.log_message(f"成功加载 {len(self.servers)} 个服务器配置")
            
            # 显示服务器列表
            for i, server in enumerate(self.servers, 1):
                self.log_message(f"服务器 {i}: {server['username']}@{server['host']}:{server['port']}")

        except Exception as e:
            self.log_message(f"加载服务器配置失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"加载服务器配置失败:\n{str(e)}")
    
    def configure_ntp(self):
        """执行NTP配置"""
        if not self.servers:
            QMessageBox.warning(self, "警告", "请先选择服务器配置文件")
            return
        
        ntp_config = {
            'server': self.ntp_server_edit.text().strip(),
            'minpoll': self.minpoll_spin.value(),
            'maxpoll': self.maxpoll_spin.value(),
            'step': self.step_spin.value(),
            'timezone': self.timezone_combo.currentText().strip()
        }
        
        if not ntp_config['server']:
            QMessageBox.warning(self, "警告", "请输入NTP服务器地址")
            return
        
        self.log_message("********************************************************")
        self.log_message("开始执行NTP配置...")
        self._start_operation("configure", ntp_config)
    
    def restore_ntp(self):
        """还原NTP配置"""
        if not self.servers:
            QMessageBox.warning(self, "警告", "请先选择服务器配置文件")
            return
        
        reply = QMessageBox.question(self, "确认", "确定要还原所有服务器的NTP配置吗？")
        if reply == QMessageBox.Yes:
            self.log_message("********************************************************")
            self.log_message("开始还原NTP配置...")
            self._start_operation("restore", None)
    
    def get_status(self):
        """获取NTP状态"""
        if not self.servers:
            QMessageBox.warning(self, "警告", "请先选择服务器配置文件")
            return
        
        self.log_message("********************************************************")
        self.log_message("开始获取NTP状态...")
        self._start_operation("status", None)
    
    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
        self.log_message("日志已清空")
    
    def _start_operation(self, operation, ntp_config):
        """开始执行操作"""
        # 禁用按钮
        self.configure_btn.setEnabled(False)
        self.restore_btn.setEnabled(False)
        self.status_btn.setEnabled(False)
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # 创建工作线程
        self.ssh_worker = SSHWorker(self.servers, ntp_config, operation)
        self.ssh_worker.log_signal.connect(self.log_message)
        self.ssh_worker.progress_signal.connect(self.progress_bar.setValue)
        self.ssh_worker.finished_signal.connect(self._operation_finished)
        self.ssh_worker.start()
    
    def _operation_finished(self):
        """操作完成"""
        # 启用按钮
        self.configure_btn.setEnabled(True)
        self.restore_btn.setEnabled(True)
        self.status_btn.setEnabled(True)
        
        # 隐藏进度条
        self.progress_bar.setVisible(False)
        
        self.log_message("所有操作已完成")
    
    def log_message(self, message):
        logger.info(message)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)
    
    def closeEvent(self, event):
        """关闭事件"""
        if self.ssh_worker and self.ssh_worker.isRunning():
            reply = QMessageBox.question(self, "确认", "操作正在进行中，确定要退出吗？")
            if reply == QMessageBox.Yes:
                self.ssh_worker.stop()
                self.ssh_worker.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def create_sample_config():
    """创建示例配置文件"""
    sample_servers = [
        {
            "host": "192.168.1.100",
            "port": 22,
            "username": "root",
            "password": "password123"
        },
        {
            "host": "192.168.1.101",
            "port": 22,
            "username": "root",
            "password": "password123"
        }
    ]
    
    config_file = "servers_config.json"
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(sample_servers, f, indent=4, ensure_ascii=False)
    
    print(f"示例配置文件已创建: {config_file}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle('Fusion')
    
    # 创建主窗口
    window = NTPConfigTool()
    window.show()
    
    # 创建示例配置文件
    # create_sample_config()
    
    sys.exit(app.exec())
