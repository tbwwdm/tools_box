import pandas as pd
import paramiko
from concurrent.futures import ThreadPoolExecutor
import datetime
import os
import logging
import re
import threading
import sys
import customtkinter as ctk
from tkinter import filedialog
from datetime import datetime


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

base_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
print(base_dir)

log_dir = os.path.join(base_dir, "log")
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
output_dir = os.path.join(base_dir, "output")
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

log_filename = os.path.join(log_dir, f"安全基线检查_日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
excel_filename = os.path.join(output_dir, f"安全基线检查_记录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")

print(log_filename)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(log_filename)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)


def read_excel(file_path):
    logger.info(f"读取Excel文件: {file_path}")
    df = pd.read_excel(file_path)
    df['密码'] = df['密码'].astype(str)
    return df


def ssh_connect(hostname, ip, username, password):
    logger.info(f"尝试连接到 {hostname} ({ip})")
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=username, password=password)
        logger.info(f"成功连接到 {hostname} ({ip})")
        return client
    except Exception as e:
        logger.error(f"连接到 {hostname} ({ip}) 失败: {e}")
        return None


def check_os_type(ssh_client):
    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/os-release')
    output = stdout.read().decode().lower()
    
    if 'ubuntu' in output:
        return 'ubuntu'
    elif 'red hat' in output or 'centos' in output:
        return 'redhat'
    elif 'kylin' in output:
        return 'kylin'
    else:
        return 'other'


def perform_checks(ssh_client, os_type, ip):
    logger.info(f"{ip} - 开始检查操作系统类型: {os_type}")
    results = []
    
    if os_type == 'redhat':
        results.extend(check_redhat(ssh_client, ip))
    elif os_type == 'kylin':
        results.extend(check_redhat(ssh_client, ip))
    elif os_type == 'ubuntu':
        results.extend(check_ubuntu(ssh_client, ip))
    else:
        logger.warning(f"{ip} - 不支持的操作系统类型")
        results.append(('操作系统检查', '不支持的操作系统类型', '未通过', '请检查操作系统类型'))
    
    return results


def check_redhat(ssh_client, ip):
    results = []

    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/login.defs')
    login_defs_config = stdout.read().decode()
    pass_min_len_match = re.search(r'^\s*PASS_MIN_LEN\s+(\d+)', login_defs_config, re.IGNORECASE | re.MULTILINE)
    if pass_min_len_match:
        pass_min_len_value = int(pass_min_len_match.group(1))
        if pass_min_len_value >= 8:
            results.append(('密码策略', '检查密码最小长度配置', '通过', 'PASS_MIN_LEN 已设置为大于等于 8'))
            logger.info(f"{ip} - 检查密码最小长度配置，PASS_MIN_LEN 已设置为 {pass_min_len_value} -通过")
        else:
            results.append(('密码策略', '检查密码最小长度配置', '未通过', '/etc/login.defs 文件中 PASS_MIN_LEN 配置需要大于等于 8;'))
            logger.warning(f"{ip} - 检查密码最小长度配置，PASS_MIN_LEN 设置为 {pass_min_len_value}，应大于等于 8 - 未通过")
    else:
        results.append(('密码策略', '检查密码最小长度配置', '未通过', '/etc/login.defs 文件中 PASS_MIN_LEN 配置需要大于等于 8;'))
        logger.warning(f"{ip} - 检查密码最小长度配置，未找到 PASS_MIN_LEN 相关配置 - 未通过")

    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/pam.d/system-auth')
    pam_config = stdout.read().decode()
    cracklib_pattern = re.compile(r'^\s*password\s+requisite\s+pam_cracklib\.so\s+.*$', re.IGNORECASE | re.MULTILINE)
    if cracklib_pattern.search(pam_config):
        if all(param in pam_config for param in ['retry=3', 'minlen=8', 'minclass=3']):
            results.append(('密码策略', '检查密码创建要求是否配置', '通过', 'pam_cracklib 配置正确'))
            logger.info(f"{ip} - 检查密码创建要求是否配置 - 通过")
        else:
            results.append(('密码策略', '检查密码创建要求是否配置', '未通过', '/etc/pam.d/system-auth 文件中未找到 password requisite pam_cracklib.so retry=3 minlen=8 minclass=3;'))
            logger.warning(f"{ip} - 检查密码创建要求是否配置 - 未通过")
    else:
        results.append(('密码策略', '检查密码创建要求是否配置', '未通过', '/etc/pam.d/system-auth 文件中未找到 password requisite pam_cracklib.so retry=3 minlen=8 minclass=3;'))
        logger.warning(f"{ip} - 检查密码创建要求是否配置 - 未通过")

    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/login.defs')
    login_defs_config = stdout.read().decode()
    pass_max_days_match = re.search(r'^\s*PASS_MAX_DAYS\s+(\d+)', login_defs_config, re.IGNORECASE | re.MULTILINE)
    if pass_max_days_match:
        pass_max_days_value = int(pass_max_days_match.group(1))
        if pass_max_days_value <= 90:
            results.append(('密码策略', '检查密码过期时间', '通过', 'PASS_MAX_DAYS 已设置为小于 90'))
            logger.info(f"{ip} - 检查密码过期时间，PASS_MAX_DAYS 已设置为 {pass_max_days_value} - 通过")
        else:
            results.append(('密码策略', '检查密码过期时间', '未通过', '在/etc/login.defs文件中 PASS_MAX_DAYS 配置需要小于等于 90;'))
            logger.warning(f"{ip} - 检查密码过期时间，PASS_MAX_DAYS 设置为 {pass_max_days_value}，应小于 90 - 未通过")
    else:
        results.append(('密码策略', '检查密码过期时间', '未通过', '在/etc/login.defs文件中 PASS_MAX_DAYS 配置需要小于等于 90;'))
        logger.warning(f"{ip} - 检查密码过期时间，未找到 PASS_MAX_DAYS 配置，准备添加 PASS_MAX_DAYS 90 - 未通过")
        

    rsyslog_conf_path = '/etc/rsyslog.conf'
    stdin, stdout, stderr = ssh_client.exec_command(f'cat {rsyslog_conf_path}')
    rsyslog_conf = stdout.read().decode()
    ip_pattern = re.compile(r'\*\.\* @\d+\.\d+\.\d+\.\d+')
    if ip_pattern.search(rsyslog_conf):
        results.append(('日志配置', '检查是否配置日志 server 服务器', '通过', '已配置日志 server 服务器'))
        logger.info(f"{ip} - 检查是否配置日志 server 服务器 - 通过")
    else:
        results.append(('日志配置', '检查是否配置日志 server 服务器', '未通过', '在/etc/syslog.conf或/etc/rsyslog.conf文件中配置*.* @ip，ip为日志server的地址'))
        logger.warning(f"{ip} - 检查是否配置日志 server 服务器 - 未通过")
    
    rsyslog_conf_path = '/etc/rsyslog.conf'
    stdin, stdout, stderr = ssh_client.exec_command(f'cat {rsyslog_conf_path}')
    rsyslog_conf = stdout.read().decode()
    if 'cron.* /var/log/cron' in rsyslog_conf:
        results.append(('日志配置', '检查是否记录 cron 行为日志', '通过', '已记录cron行为日志'))
        logger.info(f"{ip} - 检查是否记录 cron 行为日志 - 通过")
    else:
        results.append(('日志配置', '检查是否记录 cron 行为日志', '未通过', '在/etc/syslog.conf或/etc/rsyslog.conf文件中配置cron.* /var/log/cron'))
        logger.warning(f"{ip} - 检查是否记录 cron 行为日志 - 未通过")
    
    rsyslog_conf_path = '/etc/rsyslog.conf'
    syslog_conf_path = '/etc/syslog.conf'
    stdin, stdout, stderr = ssh_client.exec_command(f'cat {rsyslog_conf_path}')
    rsyslog_conf = stdout.read().decode()
    if not rsyslog_conf:
        stdin, stdout, stderr = ssh_client.exec_command(f'cat {syslog_conf_path}')
        syslog_conf = stdout.read().decode()
    else:
        syslog_conf = rsyslog_conf
    if "authpriv.* /var/log/secure" in syslog_conf:
        results.append(('日志配置', '检查是否启用 Syslog 日志审计', '通过', '日志审计Syslog 配置-已启用'))
        logger.info(f"{ip} - 检查是否启用 Syslog 日志审计 - 通过")
    else:
        results.append(('日志配置', '检查是否启用 Syslog 日志审计', '未通过', '在/etc/syslog.conf或/etc/rsyslog.conf文件行尾加入authpriv.* /var/log/secure'))
        logger.warning(f"{ip} - 检查是否启用 Syslog 日志审计 - 未通过")
    
    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/profile')
    profile_config = stdout.read().decode()
    if "TMOUT=600" in profile_config:
        results.append(('登陆超时', '检查是否配置登陆超时时间设置', '通过', '用户已配置登录超时配置'))
        logger.info(f"{ip} - 检查是否配置登陆超时时间设置 - 通过")
    else:
        results.append(('登陆超时', '检查是否配置登陆超时时间设置', '未通过', '修改/etc/profile文件中TMOUT的值小于等于600，若没有TMOUT配置则在行尾加入TMOUT=600'))
        logger.warning(f"{ip} - 检查是否配置登陆超时时间设置 - 未通过")
    
    files_to_check = {
        '/etc/passwd': '644',
        '/etc/group': '644',
        '/etc/shadow': '600'
    }
    for file, expected_permission in files_to_check.items():
        stdin, stdout, stderr = ssh_client.exec_command(f'stat -c "%a" {file}')
        actual_permission = stdout.read().decode().strip()
        
        if actual_permission == expected_permission:
            results.append(('权限控制', f'检查 {file} 文件权限', '通过', f'{file} 权限已正确设置为 {expected_permission}'))
            logger.info(f"{ip} - 检查用户最小权限配置，{file} 权限已正确设置为 {expected_permission}")
        else:
            results.append(('权限控制', f'检查 {file} 文件权限', '未通过', f'{file} 权限应设置为 {expected_permission}'))
            logger.warning(f"{ip} - 检查用户最小权限配置，{file} 权限应设置为 {expected_permission}")

    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/login.defs')
    login_defs_config = stdout.read().decode()
    umask_pattern = re.compile(r'^\s*umask\s+027\s*$', re.IGNORECASE | re.MULTILINE)
    if umask_pattern.search(login_defs_config):
        results.append(('权限控制', '检查是否配置文件与目录缺省权限控制', '通过', 'umask 已正确设置为 027'))
        logger.info(f"{ip} - 检查是否配置文件与目录缺省权限控制 - 通过")
    else:
        results.append(('权限控制', '检查是否配置文件与目录缺省权限控制', '未通过', '在/etc/login.defs中设置umask为027'))
        logger.warning(f"{ip} - 检查是否配置文件与目录缺省权限控制 - 未通过")
    
    
    service_status = ssh_client.exec_command('systemctl is-active vsftpd')
    service_running = service_status[1].read().decode().strip()

    if service_running == "active":
        stdin, stdout, stderr = ssh_client.exec_command('cat /etc/vsftpd/ftpusers')
        ftpusers_config = stdout.read().decode()

        if "root" in ftpusers_config:
            results.append(('FTP设置', '检查是否禁止 root 用户登录 FTP', '通过', '已禁止 root 用户登录 FTP'))
            logger.info(f"{ip} - 检查是否禁止 root 用户登录 FTP - 通过")
        else:
            results.append(('FTP设置', '检查是否禁止 root 用户登录 FTP', '未通过', '在/etc/vsftpd/ftpusers中禁止root用户登录'))
            logger.warning(f"{ip} - 检查是否禁止 root 用户登录 FTP - 未通过")
    else:
        results.append(('FTP设置', '检查是否禁止 root 用户登录 FTP', '通过', 'VSFTPD服务未运行'))
        logger.info(f"{ip} - 检查是否禁止 root 用户登录 FTP，VSFTPD服务未运行 - 通过")

    service_status = ssh_client.exec_command('systemctl is-active vsftpd')
    service_running = service_status[1].read().decode().strip()
    if service_running == "active":
        stdin, stdout, stderr = ssh_client.exec_command('cat /etc/vsftpd/vsftpd.conf')
        ftpusers_config = stdout.read().decode()
        if re.search(r'anonymous_enable\s*=\s*no', ftpusers_config, re.IGNORECASE):
            results.append(('FTP设置', '检查是否禁止 ftp 匿名用户登陆', '通过', '已禁止FTP匿名用户登录'))
            logger.info(f"{ip} - 检查是否禁止 ftp 匿名用户登陆 - 通过")
        else:
            results.append(('FTP设置', '检查是否禁止 ftp 匿名用户登陆', '未通过', '修改配置文件/etc/vsftpd/vsftpd.conf, 设置 anonymous_enable=No;'))
            logger.warning(f"{ip} - 检查是否禁止 ftp 匿名用户登陆 - 未通过")
    else:
        results.append(('FTP设置', '检查是否禁止 ftp 匿名用户登陆', '通过', 'VSFTPD服务未运行'))
        logger.info(f"{ip} - 检查是否禁止 ftp 匿名用户登陆，VSFTPD服务未运行 - 通过")

    stdin, stdout, stderr = ssh_client.exec_command('systemctl is-active xinetd.service')
    telnet_status = stdout.read().decode().strip()
    print(telnet_status)
    if telnet_status == 'active':
        results.append(('服务检查', '检查是否禁用 Telnet 服务', '未通过', '建议关闭telnet服务，保障系统远程连接安全'))
        logger.warning(f"{ip} - 检查是否禁用 Telnet 服务 - 未通过")
    else:
        results.append(('服务检查', '检查是否禁用 Telnet 服务', '通过', '未启用或已关闭telnet服务'))
        logger.info(f"{ip} - 检查是否禁用 Telnet 服务，未启用或已关闭telnet服务 - 通过")
    
    return results


def check_ubuntu(ssh_client, ip):
    results = []

    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/login.defs')
    login_defs_config = stdout.read().decode()
    pass_min_len_match = re.search(r'^\s*PASS_MIN_LEN\s+(\d+)', login_defs_config, re.IGNORECASE | re.MULTILINE)
    if pass_min_len_match:
        pass_min_len_value = int(pass_min_len_match.group(1))
        if pass_min_len_value >= 8:
            results.append(('密码策略', '检查密码最小长度配置', '通过', 'PASS_MIN_LEN 已设置为大于等于 8'))
            logger.info(f"{ip} - 检查密码最小长度配置，PASS_MIN_LEN 已设置为 {pass_min_len_value} -通过")
        else:
            results.append(('密码策略', '检查密码最小长度配置', '未通过', '/etc/login.defs 文件中 PASS_MIN_LEN 配置需要大于等于 8;'))
            logger.warning(f"{ip} - 检查密码最小长度配置，PASS_MIN_LEN 设置为 {pass_min_len_value}，应大于等于 8 - 未通过")
    else:
        results.append(('密码策略', '检查密码最小长度配置', '未通过', '/etc/login.defs 文件中 PASS_MIN_LEN 配置需要大于等于 8;'))
        logger.warning(f"{ip} - 检查密码最小长度配置，未找到 PASS_MIN_LEN 相关配置 - 未通过")

    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/pam.d/common-password')
    pam_config = stdout.read().decode()
    cracklib_pattern = re.compile(r'^\s*password\s+requisite\s+pam_cracklib\.so\s+.*$', re.IGNORECASE | re.MULTILINE)
    if cracklib_pattern.search(pam_config):
        if all(param in pam_config for param in ['retry=3', 'minlen=8', 'minclass=3']):
            results.append(('密码策略', '检查密码创建要求是否配置', '通过', 'pam_cracklib 配置正确'))
            logger.info(f"{ip} - 检查密码创建要求是否配置 - 通过")
        else:
            results.append(('密码策略检查', '检查密码创建要求是否配置', '未通过', '/etc/pam.d/system-auth 文件中未找到 password requisite pam_cracklib.so retry=3 minlen=8 minclass=3;'))
            logger.warning(f"{ip} - 检查密码创建要求是否配置 - 未通过")
    else:
        results.append(('密码策略', '检查密码创建要求是否配置', '未通过', '/etc/pam.d/system-auth 文件中未找到 password requisite pam_cracklib.so retry=3 minlen=8 minclass=3;'))
        logger.warning(f"{ip} - 检查密码创建要求是否配置 - 未通过")

    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/login.defs')
    login_defs_config = stdout.read().decode()
    pass_max_days_match = re.search(r'^\s*PASS_MAX_DAYS\s+(\d+)', login_defs_config, re.IGNORECASE | re.MULTILINE)
    if pass_max_days_match:
        pass_max_days_value = int(pass_max_days_match.group(1))
        if pass_max_days_value < 90:
            results.append(('密码策略', '检查密码过期时间', '通过', 'PASS_MAX_DAYS 已设置为小于 90'))
            logger.info(f"{ip} - 检查密码过期时间，PASS_MAX_DAYS 已设置为 {pass_max_days_value} - 通过")
        else:
            results.append(('密码策略', '检查密码过期时间', '未通过', 'PASS_MAX_DAYS 应设置为小于 90'))
            logger.warning(f"{ip} - 检查密码过期时间，PASS_MAX_DAYS 设置为 {pass_max_days_value}，应小于 90 - 未通过")
    else:
        results.append(('密码策略', '检查密码过期时间', '未通过', '未找到 PASS_MAX_DAYS 配置，准备添加'))
        logger.warning(f"{ip} - 检查密码过期时间，未找到 PASS_MAX_DAYS 配置，准备添加 PASS_MAX_DAYS 90 - 未通过")
        

    rsyslog_conf_path = '/etc/rsyslog.conf'
    stdin, stdout, stderr = ssh_client.exec_command(f'cat {rsyslog_conf_path}')
    rsyslog_conf = stdout.read().decode()
    ip_pattern = re.compile(r'\*\.\* @\d+\.\d+\.\d+\.\d+')
    if ip_pattern.search(rsyslog_conf):
        results.append(('日志配置', '检查是否配置日志 server 服务器', '通过', '已配置日志 server 服务器'))
        logger.info(f"{ip} - 检查是否配置日志 server 服务器 - 通过")
    else:
        results.append(('日志配置', '检查是否配置日志 server 服务器', '未通过', '在/etc/syslog.conf或/etc/rsyslog.conf文件中配置*.* @ip，ip为日志server的地址'))
        logger.warning(f"{ip} - 检查是否配置日志 server 服务器 - 未通过")
    
    rsyslog_conf_path = '/etc/rsyslog.conf'
    stdin, stdout, stderr = ssh_client.exec_command(f'cat {rsyslog_conf_path}')
    rsyslog_conf = stdout.read().decode()
    if 'cron.* /var/log/cron' in rsyslog_conf:
        results.append(('日志配置', '检查是否记录 cron 行为日志', '通过', '已记录cron行为日志'))
        logger.info(f"{ip} - 检查是否记录 cron 行为日志 - 通过")
    else:
        results.append(('日志配置', '检查是否记录 cron 行为日志', '未通过', '在/etc/syslog.conf或/etc/rsyslog.conf文件中配置cron.* /var/log/cron'))
        logger.warning(f"{ip} - 检查是否记录 cron 行为日志 - 未通过")
    
    rsyslog_conf_path = '/etc/rsyslog.conf'
    syslog_conf_path = '/etc/syslog.conf'
    stdin, stdout, stderr = ssh_client.exec_command(f'cat {rsyslog_conf_path}')
    rsyslog_conf = stdout.read().decode()
    if not rsyslog_conf:
        stdin, stdout, stderr = ssh_client.exec_command(f'cat {syslog_conf_path}')
        syslog_conf = stdout.read().decode()
    else:
        syslog_conf = rsyslog_conf
    if "authpriv.* /var/log/secure" in syslog_conf:
        results.append(('日志配置', '检查是否启用 Syslog 日志审计', '通过', '日志审计Syslog 配置-已启用'))
        logger.info(f"{ip} - 检查是否启用 Syslog 日志审计 - 通过")
    else:
        results.append(('日志配置', '检查是否启用 Syslog 日志审计', '未通过', '在/etc/syslog.conf或/etc/rsyslog.conf文件行尾加入authpriv.* /var/log/secure'))
        logger.warning(f"{ip} - 检查是否启用 Syslog 日志审计 - 未通过")
    
    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/profile')
    profile_config = stdout.read().decode()
    if "TMOUT=600" in profile_config:
        results.append(('登陆超时', '检查是否配置登陆超时时间设置', '通过', '用户已配置登录超时配置'))
        logger.info(f"{ip} - 检查是否配置登陆超时时间设置 - 通过")
    else:
        results.append(('登陆超时', '检查是否配置登陆超时时间设置', '未通过', '修改/etc/profile文件中TMOUT的值小于等于600，若没有TMOUT配置则在行尾加入TMOUT=600'))
        logger.warning(f"{ip} - 检查是否配置登陆超时时间设置 - 未通过")
    
    files_to_check = {
        '/etc/passwd': '644',
        '/etc/group': '644',
        '/etc/shadow': '600'
    }
    for file, expected_permission in files_to_check.items():
        stdin, stdout, stderr = ssh_client.exec_command(f'stat -c "%a" {file}')
        actual_permission = stdout.read().decode().strip()
        
        if actual_permission == expected_permission:
            results.append(('权限控制', f'检查 {file} 文件权限', '通过', f'{file} 权限已正确设置为 {expected_permission}'))
            logger.info(f"{ip} - 检查用户最小权限配置，{file} 权限已正确设置为 {expected_permission} - 通过")
        else:
            results.append(('权限控制', f'检查 {file} 文件权限', '未通过', f'{file} 权限应设置为 {expected_permission}'))
            logger.warning(f"{ip} - 检查用户最小权限配置，{file} 权限应设置为 {expected_permission} - 未通过")

    stdin, stdout, stderr = ssh_client.exec_command('cat /etc/login.defs')
    login_defs_config = stdout.read().decode()
    umask_pattern = re.compile(r'^\s*umask\s+027\s*$', re.IGNORECASE | re.MULTILINE)
    if umask_pattern.search(login_defs_config):
        results.append(('权限控制', '检查是否配置文件与目录缺省权限控制', '通过', 'umask 已正确设置为 027'))
        logger.info(f"{ip} - 检查是否配置文件与目录缺省权限控制 - 通过")
    else:
        results.append(('权限控制', '检查是否配置文件与目录缺省权限控制', '未通过', '在/etc/login.defs中设置umask为027'))
        logger.warning(f"{ip} - 检查是否配置文件与目录缺省权限控制 - 未通过")
    
    
    service_status = ssh_client.exec_command('systemctl is-active vsftpd')
    service_running = service_status[1].read().decode().strip()

    if service_running == "active":
        stdin, stdout, stderr = ssh_client.exec_command('cat /etc/vsftpd/ftpusers')
        ftpusers_config = stdout.read().decode()

        if "root" in ftpusers_config:
            results.append(('FTP设置', '检查是否禁止 root 用户登录 FTP', '通过', '已禁止 root 用户登录 FTP'))
            logger.info(f"{ip} - 检查是否禁止 root 用户登录 FTP - 通过")
        else:
            results.append(('FTP设置', '检查是否禁止 root 用户登录 FTP', '未通过', '在/etc/vsftpd/ftpusers中禁止root用户登录'))
            logger.warning(f"{ip} - 检查是否禁止 root 用户登录 FTP - 未通过")
    else:
        results.append(('FTP设置', '检查是否禁止 root 用户登录 FTP', '通过', 'VSFTPD服务未运行'))
        logger.info(f"{ip} - 检查是否禁止 root 用户登录 FTP，VSFTPD服务未运行 - 通过")
    
    service_status = ssh_client.exec_command('systemctl is-active vsftpd')
    service_running = service_status[1].read().decode().strip()
    if service_running == "active":
        stdin, stdout, stderr = ssh_client.exec_command('cat /etc/vsftpd/vsftpd.conf')
        ftpusers_config = stdout.read().decode()
        if re.search(r'anonymous_enable\s*=\s*no', ftpusers_config, re.IGNORECASE):
            results.append(('FTP设置', '检查是否禁止 ftp 匿名用户登陆', '通过', '已禁止FTP匿名用户登录'))
            logger.info(f"{ip} - 检查是否禁止 ftp 匿名用户登陆 - 通过")
        else:
            results.append(('FTP设置', '检查是否禁止 ftp 匿名用户登陆', '未通过', '修改配置文件/etc/vsftpd/vsftpd.conf, 设置 anonymous_enable=No;'))
            logger.warning(f"{ip} - 检查是否禁止 ftp 匿名用户登陆 - 未通过")
    else:
        results.append(('FTP设置', '检查是否禁止 ftp 匿名用户登陆', '通过', 'VSFTPD服务未运行'))
        logger.info(f"{ip} - 检查是否禁止 ftp 匿名用户登陆，VSFTPD服务未运行 - 通过")
        
    stdin, stdout, stderr = ssh_client.exec_command('systemctl is-active xinetd.service')
    telnet_status = stdout.read().decode().strip()
    print(telnet_status)
    if telnet_status == 'active':
        results.append(('服务检查', '检查是否禁用 Telnet 服务', '未通过', '建议关闭telnet服务，保障系统远程连接安全'))
        logger.warning(f"{ip} - 检查是否禁用 Telnet 服务 - 未通过")
    else:
        results.append(('服务检查', '检查是否禁用 Telnet 服务', '通过', '未启用或已关闭telnet服务'))
        logger.info(f"{ip} - 检查是否禁用 Telnet 服务 - 通过")
    
    return results


def log_results(hostname, ip, results, start_time, end_time):
    logger.info(f"生成的Excel文件: {excel_filename}")
    
    df = pd.DataFrame([{
        '主机名称': hostname,
        '公网IP/内网IP': ip,
        '检查大类': result[0],
        '检查项': result[1],
        '检查结果': result[2],
        '加固建议': result[3],
        '开始时间': start_time,
        '结束时间': end_time
    } for result in results])
    
    if not os.path.exists(excel_filename):
        df.to_excel(excel_filename, index=False)
    else:
        existing_df = pd.read_excel(excel_filename)
        new_df = pd.concat([existing_df, df], ignore_index=True)
        new_df.to_excel(excel_filename, index=False)


def process_host(row):
    hostname, ip, username, password = row
    start_time = datetime.now()
    ssh_client = ssh_connect(hostname, ip, username, password)
    if ssh_client:
        os_type = check_os_type(ssh_client)
        results = perform_checks(ssh_client, os_type, ip)
        end_time = datetime.now()
        log_results(hostname, ip, results, start_time, end_time)
        ssh_client.close()
    else:
        logger.warning(f"跳过 {hostname} ({ip}) 的检查")
        end_time = datetime.now()
        log_results(hostname, ip, [('SSH连接', 'SSH连接失败', '未通过')], start_time, end_time)


def main(app_instance, file_path, concurrent_count=1):
    logger.info("程序开始执行")
    logger.info(f"生成的日志文件: {log_filename}")
    data = read_excel(file_path)
    with ThreadPoolExecutor(max_workers=concurrent_count) as executor:
        executor.map(process_host, data.values)
    app_instance.stop_scan()
    logger.info("########################程序执行完毕########################")


class SecurityCheckApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Genew Linux基线安全扫描工具 v3.0")
        self.root.geometry("1100x700")

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(3, weight=1)

        title_label = ctk.CTkLabel(root, text="Genew Linux基线安全扫描工具 v3.0", font=ctk.CTkFont(size=24, weight="bold"))
        title_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        file_frame = ctk.CTkFrame(root)
        file_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        file_frame.grid_columnconfigure(1, weight=1)

        file_label = ctk.CTkLabel(file_frame, text="选择扫描表格:", font=ctk.CTkFont(size=14))
        file_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")

        self.file_entry = ctk.CTkEntry(file_frame, placeholder_text="请选择Excel文件...")
        self.file_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        self.browse_button = ctk.CTkButton(file_frame, text="浏览", command=self.browse_file, width=100)
        self.browse_button.grid(row=0, column=2, padx=10, pady=10)

        settings_frame = ctk.CTkFrame(root)
        settings_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        settings_frame.grid_columnconfigure(1, weight=1)

        concurrent_label = ctk.CTkLabel(settings_frame, text="并发数量 (1-5):", font=ctk.CTkFont(size=14))
        concurrent_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")

        self.concurrent_entry = ctk.CTkEntry(settings_frame, width=80)
        self.concurrent_entry.grid(row=0, column=1, padx=10, pady=10, sticky="w")
        self.concurrent_entry.insert(0, "1")

        button_frame = ctk.CTkFrame(root)
        button_frame.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")
        button_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.start_button = ctk.CTkButton(button_frame, text="开始扫描", command=self.start_scan, 
                                           font=ctk.CTkFont(size=14, weight="bold"), height=40,
                                           fg_color="#2fa848", hover_color="#258039")
        self.start_button.grid(row=0, column=0, padx=10, pady=10)

        self.stop_button = ctk.CTkButton(button_frame, text="停止扫描", command=self.stop_scan, 
                                          font=ctk.CTkFont(size=14), height=40,
                                          fg_color="#e74856", hover_color="#c42d3b")
        self.stop_button.grid(row=0, column=1, padx=10, pady=10)

        self.clear_button = ctk.CTkButton(button_frame, text="清除日志", command=self.clear_log, 
                                           font=ctk.CTkFont(size=14), height=40)
        self.clear_button.grid(row=0, column=2, padx=10, pady=10)

        log_frame = ctk.CTkFrame(root)
        log_frame.grid(row=4, column=0, padx=20, pady=(0, 20), sticky="nsew")
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        self.log_text = ctk.CTkTextbox(log_frame, font=ctk.CTkFont(size=12))
        self.log_text.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.log_handler = TextHandler(self.log_text)
        logger.addHandler(self.log_handler)

        self.scan_thread = None
        self.scanning = False

    def browse_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx")])
        if file_path:
            self.file_entry.delete(0, ctk.END)
            self.file_entry.insert(0, file_path)

    def start_scan(self):
        if not self.scanning:
            self.scanning = True
            file_path = self.file_entry.get()
            concurrent_count = self.concurrent_entry.get()
            if file_path:
                try:
                    concurrent_count = int(concurrent_count)
                    if concurrent_count < 1 or concurrent_count > 5:
                        raise ValueError("并发数量必须在1到5之间")
                except ValueError as e:
                    logger.warning(f"无效的并发数量: {e}")
                    self.scanning = False
                    return

                self.scan_thread = threading.Thread(target=main, args=(self, file_path, concurrent_count))
                self.scan_thread.start()
            else:
                logger.warning("请先选择一个Excel文件")
                self.scanning = False

    def stop_scan(self):
        if self.scanning:
            self.scanning = False
            logger.info("扫描已停止")

    def clear_log(self):
        self.log_text.delete("1.0", ctk.END)


class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        logging.Handler.__init__(self)
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)-8s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        self.text_widget = text_widget
        self.text_widget.tag_config('INFO', foreground='black')
        self.text_widget.tag_config('WARNING', foreground='#e74856')
        self.text_widget.tag_config('ERROR', foreground='#e74856')
        self.text_widget.tag_config('CRITICAL', foreground='white', background='#e74856')

    def emit(self, record):
        msg = self.format(record)
        def append():
            tag = record.levelname
            self.text_widget.insert(ctk.END, msg + '\n', tag)
            self.text_widget.see(ctk.END)
        self.text_widget.after(0, append)


if __name__ == "__main__":
    root = ctk.CTk()
    app = SecurityCheckApp(root)
    root.mainloop()
