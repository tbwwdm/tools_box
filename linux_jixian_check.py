# -*- coding: utf-8 -*-
"""
Linux 安全基线检查工具 (PySide6)
"""
import sys, os, re, threading, logging, queue
import pandas as pd
import paramiko
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from PySide6.QtWidgets import (QWidget, QApplication, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QMessageBox, QGroupBox)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor

logger = logging.getLogger(__name__)


def read_excel(file_path):
    logger.info(f"读取Excel文件: {file_path}")
    df = pd.read_excel(file_path)
    df['password'] = df['password'].astype(str)
    return df


def ssh_connect(host, ip, username, password):
    logger.info(f"尝试连接 {host} ({ip})")
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(ip, username=username, password=password, timeout=10)
        logger.info(f"成功连接 {host}")
        return c
    except Exception as e:
        logger.error(f"连接 {host} 失败: {e}")
        return None


def check_os_type(ssh):
    o = ssh.exec_command('cat /etc/os-release')[1].read().decode().lower()
    if 'ubuntu' in o: return 'ubuntu'
    if 'centos' in o or 'red hat' in o: return 'redhat'
    if 'kylin' in o: return 'kylin'
    return 'other'


def check_item(ssh, cmd, pattern, flag, ok_msg, fail_msg):
    o = ssh.exec_command(cmd)[1].read().decode()
    if re.search(pattern, o, re.I | re.M):
        return ('通过', ok_msg)
    return ('未通过', fail_msg)


def _add(r, ip, cat, item, ok, detail):
    r.append((cat, item, ok, detail))
    if ok == '通过':
        logger.info(f"{ip} - [{cat}] {item}: {ok} ({detail})")
    else:
        logger.warning(f"{ip} - [{cat}] {item}: {ok} ({detail})")


def check_redhat(ssh, ip):
    r = []
    lo = ssh.exec_command('cat /etc/login.defs')[1].read().decode()
    m = re.search(r'^\s*PASS_MIN_LEN\s+(\d+)', lo, re.M | re.I)
    _add(r, ip, '密码策略', '密码最小长度',
         '通过' if m and int(m.group(1)) >= 8 else '未通过',
         f'PASS_MIN_LEN={m.group(1)}' if m else '需设置PASS_MIN_LEN>=8')
    m = re.search(r'^\s*PASS_MAX_DAYS\s+(\d+)', lo, re.M | re.I)
    _add(r, ip, '密码策略', '密码过期时间',
         '通过' if m and int(m.group(1)) <= 90 else '未通过',
         f'PASS_MAX_DAYS={m.group(1)}' if m else '需设置PASS_MAX_DAYS<=90')
    pa = ssh.exec_command('cat /etc/pam.d/system-auth')[1].read().decode()
    ok = all(x in pa for x in ['retry=3', 'minlen=8', 'minclass=3'])
    _add(r, ip, '密码策略', '密码创建要求', '通过' if ok else '未通过',
         '配置正确' if ok else '需配置pam_cracklib')
    rs = ssh.exec_command('cat /etc/rsyslog.conf')[1].read().decode()
    _add(r, ip, '日志配置', '日志服务器', '通过' if re.search(r'\*\.\*\s+@\d+', rs) else '未通过',
         '已配置' if re.search(r'\*\.\*\s+@\d+', rs) else '需配置*.*@IP')
    _add(r, ip, '日志配置', 'cron日志', '通过' if 'cron.* /var/log/cron' in rs else '未通过',
         '已记录' if 'cron.* /var/log/cron' in rs else '需配置cron.* /var/log/cron')
    _add(r, ip, '日志配置', 'Syslog审计', '通过' if 'authpriv.* /var/log/secure' in rs else '未通过',
         '已启用' if 'authpriv.* /var/log/secure' in rs else '需配置authpriv.* /var/log/secure')
    pf = ssh.exec_command('cat /etc/profile')[1].read().decode()
    _add(r, ip, '登录超时', '超时设置', '通过' if 'TMOUT=600' in pf else '未通过',
         'TMOUT=600已配置' if 'TMOUT=600' in pf else '需在/etc/profile设置TMOUT=600')
    for f, p in [('/etc/passwd', '644'), ('/etc/group', '644'), ('/etc/shadow', '600')]:
        a = ssh.exec_command(f'stat -c "%a" {f}')[1].read().decode().strip()
        _add(r, ip, '权限控制', f'{f}权限', '通过' if a == p else '未通过',
             f'权限{a}' if a == p else f'需设置权限{p}')
    _add(r, ip, '权限控制', '缺省umask', '通过' if re.search(r'^\s*umask\s+027\s*$', lo, re.M) else '未通过',
         'umask=027' if re.search(r'^\s*umask\s+027\s*$', lo, re.M) else '需设置umask 027')
    v = ssh.exec_command('systemctl is-active vsftpd')[1].read().decode().strip()
    if v == 'active':
        ft = ssh.exec_command('cat /etc/vsftpd/ftpusers')[1].read().decode()
        _add(r, ip, 'FTP设置', '禁止root登录FTP', '通过' if 'root' in ft else '未通过',
             '已禁止' if 'root' in ft else '需在ftpusers中禁止root')
        cf = ssh.exec_command('cat /etc/vsftpd/vsftpd.conf')[1].read().decode()
        _add(r, ip, 'FTP设置', '禁止匿名FTP', '通过' if re.search(r'anonymous_enable\s*=\s*no', cf, re.I) else '未通过',
             '已禁止' if re.search(r'anonymous_enable\s*=\s*no', cf, re.I) else '需设置anonymous_enable=no')
    else:
        _add(r, ip, 'FTP设置', '禁止root登录FTP', '通过', 'VSFTPD未运行')
        _add(r, ip, 'FTP设置', '禁止匿名FTP', '通过', 'VSFTPD未运行')
    t = ssh.exec_command('systemctl is-active xinetd.service')[1].read().decode().strip()
    _add(r, ip, '服务检查', '禁用Telnet', '通过' if t != 'active' else '未通过',
         '未启用' if t != 'active' else '建议关闭telnet')
    return r


def check_ubuntu(ssh, ip):
    r = []
    lo = ssh.exec_command('cat /etc/login.defs')[1].read().decode()
    m = re.search(r'^\s*PASS_MIN_LEN\s+(\d+)', lo, re.M | re.I)
    _add(r, ip, '密码策略', '密码最小长度',
         '通过' if m and int(m.group(1)) >= 8 else '未通过',
         f'PASS_MIN_LEN={m.group(1)}' if m else '需设置PASS_MIN_LEN>=8')
    m = re.search(r'^\s*PASS_MAX_DAYS\s+(\d+)', lo, re.M | re.I)
    _add(r, ip, '密码策略', '密码过期时间',
         '通过' if m and int(m.group(1)) <= 90 else '未通过',
         f'PASS_MAX_DAYS={m.group(1)}' if m else '需设置PASS_MAX_DAYS<=90')
    pa = ssh.exec_command('cat /etc/pam.d/common-password')[1].read().decode()
    ok = all(x in pa for x in ['retry=3', 'minlen=8', 'minclass=3'])
    _add(r, ip, '密码策略', '密码创建要求', '通过' if ok else '未通过',
         '配置正确' if ok else '需配置pam_cracklib')
    rs = ssh.exec_command('cat /etc/rsyslog.conf')[1].read().decode()
    _add(r, ip, '日志配置', '日志服务器', '通过' if re.search(r'\*\.\*\s+@\d+', rs) else '未通过',
         '已配置' if re.search(r'\*\.\*\s+@\d+', rs) else '需配置*.*@IP')
    _add(r, ip, '日志配置', 'cron日志', '通过' if 'cron.* /var/log/cron' in rs else '未通过',
         '已记录' if 'cron.* /var/log/cron' in rs else '需配置cron.* /var/log/cron')
    _add(r, ip, '日志配置', 'Syslog审计', '通过' if 'authpriv.* /var/log/secure' in rs else '未通过',
         '已启用' if 'authpriv.* /var/log/secure' in rs else '需配置authpriv.* /var/log/secure')
    pf = ssh.exec_command('cat /etc/profile')[1].read().decode()
    _add(r, ip, '登录超时', '超时设置', '通过' if 'TMOUT=600' in pf else '未通过',
         'TMOUT=600已配置' if 'TMOUT=600' in pf else '需在/etc/profile设置TMOUT=600')
    for f, p in [('/etc/passwd', '644'), ('/etc/group', '644'), ('/etc/shadow', '600')]:
        a = ssh.exec_command(f'stat -c "%a" {f}')[1].read().decode().strip()
        _add(r, ip, '权限控制', f'{f}权限', '通过' if a == p else '未通过',
             f'权限{a}' if a == p else f'需设置权限{p}')
    _add(r, ip, '权限控制', '缺省umask', '通过' if re.search(r'^\s*umask\s+027\s*$', lo, re.M) else '未通过',
         'umask=027' if re.search(r'^\s*umask\s+027\s*$', lo, re.M) else '需设置umask 027')
    v = ssh.exec_command('systemctl is-active vsftpd')[1].read().decode().strip()
    if v == 'active':
        ft = ssh.exec_command('cat /etc/vsftpd/ftpusers')[1].read().decode()
        _add(r, ip, 'FTP设置', '禁止root登录FTP', '通过' if 'root' in ft else '未通过',
             '已禁止' if 'root' in ft else '需在ftpusers中禁止root')
        cf = ssh.exec_command('cat /etc/vsftpd/vsftpd.conf')[1].read().decode()
        _add(r, ip, 'FTP设置', '禁止匿名FTP', '通过' if re.search(r'anonymous_enable\s*=\s*no', cf, re.I) else '未通过',
             '已禁止' if re.search(r'anonymous_enable\s*=\s*no', cf, re.I) else '需设置anonymous_enable=no')
    else:
        _add(r, ip, 'FTP设置', '禁止root登录FTP', '通过', 'VSFTPD未运行')
        _add(r, ip, 'FTP设置', '禁止匿名FTP', '通过', 'VSFTPD未运行')
    t = ssh.exec_command('systemctl is-active xinetd.service')[1].read().decode().strip()
    _add(r, ip, '服务检查', '禁用Telnet', '通过' if t != 'active' else '未通过',
         '未启用' if t != 'active' else '建议关闭telnet')
    return r


def check_ubuntu(ssh, ip):
    r = []
    lo = ssh.exec_command('cat /etc/login.defs')[1].read().decode()
    m = re.search(r'^\s*PASS_MIN_LEN\s+(\d+)', lo, re.M | re.I)
    r.append(('密码策略','密码最小长度', '通过' if m and int(m.group(1))>=8 else '未通过',
              f'PASS_MIN_LEN={m.group(1)}' if m else '需设置PASS_MIN_LEN>=8'))
    m = re.search(r'^\s*PASS_MAX_DAYS\s+(\d+)', lo, re.M | re.I)
    r.append(('密码策略','密码过期时间', '通过' if m and int(m.group(1))<=90 else '未通过',
              f'PASS_MAX_DAYS={m.group(1)}' if m else '需设置PASS_MAX_DAYS<=90'))
    pa = ssh.exec_command('cat /etc/pam.d/common-password')[1].read().decode()
    ok = all(x in pa for x in ['retry=3','minlen=8','minclass=3'])
    r.append(('密码策略','密码创建要求','通过' if ok else '未通过','配置正确' if ok else '需配置pam_cracklib'))
    rs = ssh.exec_command('cat /etc/rsyslog.conf')[1].read().decode()
    r.append(('日志配置','日志服务器','通过' if re.search(r'\*\.\*\s+@\d+',rs) else '未通过',
              '已配置' if re.search(r'\*\.\*\s+@\d+',rs) else '需配置*.*@IP'))
    r.append(('日志配置','cron日志','通过' if 'cron.* /var/log/cron' in rs else '未通过',
              '已记录' if 'cron.* /var/log/cron' in rs else '需配置cron.* /var/log/cron'))
    r.append(('日志配置','Syslog审计','通过' if 'authpriv.* /var/log/secure' in rs else '未通过',
              '已启用' if 'authpriv.* /var/log/secure' in rs else '需配置authpriv.* /var/log/secure'))
    pf = ssh.exec_command('cat /etc/profile')[1].read().decode()
    r.append(('登录超时','超时设置','通过' if 'TMOUT=600' in pf else '未通过',
              'TMOUT=600已配置' if 'TMOUT=600' in pf else '需在/etc/profile设置TMOUT=600'))
    for f, p in [('/etc/passwd','644'),('/etc/group','644'),('/etc/shadow','600')]:
        a = ssh.exec_command(f'stat -c "%a" {f}')[1].read().decode().strip()
        r.append(('权限控制',f'{f}权限','通过' if a==p else '未通过',f'权限{a}' if a==p else f'需设置权限{p}'))
    r.append(('权限控制','缺省umask','通过' if re.search(r'^\s*umask\s+027\s*$',lo,re.M) else '未通过',
              'umask=027' if re.search(r'^\s*umask\s+027\s*$',lo,re.M) else '需设置umask 027'))
    v = ssh.exec_command('systemctl is-active vsftpd')[1].read().decode().strip()
    if v=='active':
        ft = ssh.exec_command('cat /etc/vsftpd/ftpusers')[1].read().decode()
        r.append(('FTP设置','禁止root登录FTP','通过' if 'root' in ft else '未通过',
                  '已禁止' if 'root' in ft else '需在ftpusers中禁止root'))
        cf = ssh.exec_command('cat /etc/vsftpd/vsftpd.conf')[1].read().decode()
        r.append(('FTP设置','禁止匿名FTP','通过' if re.search(r'anonymous_enable\s*=\s*no',cf,re.I) else '未通过',
                  '已禁止' if re.search(r'anonymous_enable\s*=\s*no',cf,re.I) else '需设置anonymous_enable=no'))
    else:
        r.append(('FTP设置','禁止root登录FTP','通过','VSFTPD未运行'))
        r.append(('FTP设置','禁止匿名FTP','通过','VSFTPD未运行'))
    t = ssh.exec_command('systemctl is-active xinetd.service')[1].read().decode().strip()
    r.append(('服务检查','禁用Telnet','通过' if t!='active' else '未通过',
              '未启用' if t!='active' else '建议关闭telnet'))
    return r


def check_host(ssh, os_type, ip):
    logger.info(f"{ip} - 系统: {os_type}")
    if os_type in ('redhat','kylin'):
        return check_redhat(ssh, ip)
    elif os_type == 'ubuntu':
        return check_ubuntu(ssh, ip)
    logger.warning(f"{ip} - 不支持的系统")
    return [('系统检查','操作系统类型','未通过','不支持')]


def save_results(excel_path, host, ip, results, st, et):
    df = pd.DataFrame([{
        '主机名称':host,'IP':ip,'检查大类':r[0],'检查项':r[1],
        '检查结果':r[2],'加固建议':r[3],'开始时间':st,'结束时间':et
    } for r in results])
    if os.path.exists(excel_path):
        df = pd.concat([pd.read_excel(excel_path), df], ignore_index=True)
    df.to_excel(excel_path, index=False)


def scan_one(row, excel_path):
    host = str(row[0])
    port = int(row[1]) if len(row)>1 and pd.notna(row[1]) else 22
    user = str(row[2]) if len(row)>2 else ''
    pwd = str(row[3]) if len(row)>3 else ''
    st = datetime.now()
    logger.info(f"=== 开始 {host} ===")
    ssh = ssh_connect(host, host, user, pwd)
    if ssh:
        ot = check_os_type(ssh)
        res = check_host(ssh, ot, host)
        save_results(excel_path, host, host, res, st, datetime.now())
        ssh.close()
        logger.info(f"=== {host} 完成 ===")
    else:
        logger.warning(f"=== {host} SSH失败 ===")


class LogQueue(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)-8s - %(message)s'))

    def emit(self, record):
        self.q.put(self.format(record))


class SecurityCheckApp(QWidget):
    def __init__(self):
        super().__init__()
        self.scanning = False
        self.q = queue.Queue()
        self._init_logging()
        self._init_ui()
        self._setup_logging()

    def _init_logging(self):
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(log_dir, f"基线检查_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
            encoding="utf-8")
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)

    def _init_ui(self):
        self.setWindowTitle("安全基线检查")
        self.resize(1100, 700)
        self.setStyleSheet("""
            SecurityCheckApp { background:#f5f6fa; }
            QLineEdit { border:none; border-bottom:1px solid #dfe6e9; padding:6px 4px; background:transparent; font-size:13px; }
            QLineEdit:focus { border-bottom:2px solid #0984e3; }
            QTextEdit { border:1px solid #dfe6e9; border-radius:4px; background:white; font-size:13px; }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(28, 24, 28, 24)

        # 配置
        l1 = QHBoxLayout()
        l1.addWidget(QLabel("Excel 文件"))
        self.fe = QLineEdit()
        self.fe.setPlaceholderText("选择服务器信息Excel文件")
        l1.addWidget(self.fe)
        b = QPushButton("浏览")
        b.setStyleSheet("QPushButton{background:#0984e3;color:white;padding:7px 20px;border:none;border-radius:4px;font-size:13px;}QPushButton:hover{background:#0873c4;}")
        b.clicked.connect(lambda: self.fe.setText(
            QFileDialog.getOpenFileName(self, "选择","","Excel (*.xlsx)")[0]))
        l1.addWidget(b)
        l1.addSpacing(16)
        l1.addWidget(QLabel("并发数"))
        self.ce = QLineEdit("1")
        self.ce.setFixedWidth(50)
        l1.addWidget(self.ce)
        l1.addStretch()
        layout.addLayout(l1)

        layout.addSpacing(12)

        # 按钮
        btn_row = QHBoxLayout()
        self.sb = QPushButton("开始扫描")
        self.sb.setStyleSheet("QPushButton{background:#27ae60;color:white;font-weight:bold;padding:10px 36px;border:none;border-radius:4px;font-size:14px;}QPushButton:hover{background:#219a52;}QPushButton:disabled{background:#b2bec3;}")
        self.sb.clicked.connect(self._start)
        btn_row.addWidget(self.sb)
        self.sp = QPushButton("停止")
        self.sp.setEnabled(False)
        self.sp.setStyleSheet("QPushButton{background:#e74c3c;color:white;font-weight:bold;padding:10px 36px;border:none;border-radius:4px;font-size:14px;}QPushButton:hover{background:#c0392b;}QPushButton:disabled{background:#b2bec3;}")
        self.sp.clicked.connect(self._stop)
        btn_row.addWidget(self.sp)
        cl = QPushButton("清空")
        cl.setStyleSheet("QPushButton{padding:8px 20px;border:1px solid #dfe6e9;border-radius:4px;font-size:13px;}QPushButton:hover{background:#f0f2f5;}")
        cl.clicked.connect(lambda: self.log.clear())
        btn_row.addWidget(cl)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addSpacing(8)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        layout.addWidget(self.log)

    def _setup_logging(self):
        logger.setLevel(logging.INFO)
        logger.addHandler(LogQueue(self.q))
        self._timer = QTimer()
        self._timer.timeout.connect(self._flush_log)
        self._timer.start(200)

    def _flush_log(self):
        while not self.q.empty():
            self.log.append(self.q.get_nowait())
            self.log.ensureCursorVisible()

    def _start(self):
        if self.scanning: return
        fp = self.fe.text()
        if not fp:
            QMessageBox.warning(self, "提示", "请选择Excel文件"); return
        try:
            n = int(self.ce.text())
            if n < 1 or n > 10: raise ValueError
        except:
            QMessageBox.warning(self, "提示", "并发数1-10"); return
        self.scanning = True
        self.sb.setEnabled(False)
        self.sp.setEnabled(True)
        out = os.path.join(os.path.dirname(__file__), "output")
        os.makedirs(out, exist_ok=True)
        xl = os.path.join(out, f"安全基线检查_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        data = read_excel(fp)
        self._th = threading.Thread(target=self._run, args=(data, n, xl), daemon=True)
        self._th.start()

    def _run(self, data, n, xl):
        logger.info(f"开始扫描 {len(data)} 台服务器, 并发 {n}")
        try:
            with ThreadPoolExecutor(max_workers=n) as ex:
                fs = [ex.submit(scan_one, row, xl) for row in data.values]
                for f in as_completed(fs):
                    if not self.scanning:
                        ex.shutdown(wait=False, cancel_futures=True)
                        break
            logger.info("扫描完成" if self.scanning else "用户中断")
        finally:
            QTimer.singleShot(0, self._done)

    def _done(self):
        self.scanning = False
        self.sb.setEnabled(True)
        self.sp.setEnabled(False)

    def _stop(self):
        self.scanning = False


if __name__ == "__main__":
    log_dir = os.path.join(os.path.dirname(__file__), "log")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir,
                f"安全基线检查_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
                encoding="utf-8"),
            logging.StreamHandler()
        ])
    app = QApplication(sys.argv)
    w = SecurityCheckApp()
    w.show()
    sys.exit(app.exec())
