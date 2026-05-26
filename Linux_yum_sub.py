# -*- coding: utf-8 -*-
"""
Linux YUM 源管理器
功能:
  1. 本地 yum 源 - 挂载 ISO → 复制文件 → 生成 .repo
  2. Web yum 源 - 本地源 + httpd + 防火墙/SELinux + 多ISO客户端 .repo
"""

import os
import re
import sys
import glob
import shutil
import zipfile
import datetime
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QGroupBox, QStackedWidget, QProgressBar, QFileDialog,
    QCheckBox, QComboBox, QMessageBox, QSplitter, QFrame,
    QSizePolicy, QStatusBar, QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QHeaderView, QLineEdit, QGridLayout,
    QButtonGroup, QDialog, QRadioButton, QScrollArea, QStyle, QStyleOptionButton,
    QStyleOptionHeader,
)
from PySide6.QtCore import Qt, QThread, QObject, Signal, QMutex, QMutexLocker, QTimer
from PySide6.QtGui import QFont, QColor


# ============================================================
#  配置常量
# ============================================================
HTTP_DIR = "/var/www/html"
MOUNT_BASE = "/root/tmp/mnt/iso"
YUM_REPOS_DIR = "/etc/yum.repos.d"
YUM_REPO_DIR = "/opt/tar/yum.repo"
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"yum_manager_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")



# ============================================================
#  系统检测器
# ============================================================
class SystemDetector:
    def detect_distro(self) -> dict:
        info = {
            'pretty_name': 'Unknown',
            'distro': 'unknown',
            'version': '',
            'version_id': '',
            'arch': os.uname().machine if hasattr(os, 'uname') else 'unknown',
            'needs_appstream': False,
            'is_rhel': False,
            'is_kylin': False,
            'is_centos': False,
        }
        os_release = "/etc/os-release"
        if os.path.exists(os_release):
            with open(os_release, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('PRETTY_NAME='):
                        info['pretty_name'] = line.split('=', 1)[1].strip('"\'')
                    elif line.startswith('VERSION_ID='):
                        info['version_id'] = line.split('=', 1)[1].strip('"\'')
                    elif line.startswith('ID='):
                        distro_id = line.split('=', 1)[1].strip('"\'')
                        info['distro'] = distro_id

        name = info['pretty_name'].lower()
        if 'red hat' in name or 'rhel' in name:
            info['is_rhel'] = True
        elif 'centos' in name:
            info['is_centos'] = True
        elif 'rocky' in name or 'alma' in name or 'oracle' in name:
            info['is_rhel'] = True
        elif 'kylin' in name:
            info['is_kylin'] = True

        nums = re.findall(r'(\d+)', info['version_id'])
        major = nums[0] if nums else ''
        info['version'] = info['version_id']

        if info['is_rhel'] and major in ('8', '9', '10'):
            info['needs_appstream'] = True
        if info['is_centos'] and major == '8':
            info['needs_appstream'] = True

        return info

    def get_ip_list(self) -> List[str]:
        ips = []
        try:
            result = subprocess.run(
                "ip -o addr show | awk '/inet / && !/127.0.0.1/ {print $4}' | cut -d'/' -f1",
                shell=True, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                ips = [ip.strip() for ip in result.stdout.strip().split() if ip.strip()]
        except Exception:
            pass
        return ips or ['127.0.0.1']

    def scan_isos(self, directory: str) -> List[dict]:
        results = []
        if not os.path.isdir(directory):
            return results
        try:
            for f in sorted(os.listdir(directory)):
                if f.lower().endswith('.iso'):
                    fpath = os.path.join(directory, f)
                    size = os.path.getsize(fpath)
                    results.append({
                        'name': f,
                        'path': fpath,
                        'size': size,
                        'size_str': self._format_size(size),
                    })
        except PermissionError:
            pass
        return results

    REDHAT_KEYS = ['rhel', 'red hat', 'redhat', 'centos', 'rocky', 'alma', 'almalinux', 'oracle', 'ol']
    KYLIN_KEYS = ['kylin', 'ky10', 'ky 10', 'neokylin']

    def match_iso(self, iso_name: str, distro_info: dict) -> Tuple[bool, str]:
        name_lower = iso_name.lower()
        iso_redhat = any(k in name_lower for k in self.REDHAT_KEYS)
        iso_kylin = any(k in name_lower for k in self.KYLIN_KEYS)
        iso_unknown = not iso_redhat and not iso_kylin

        if iso_unknown:
            return True, "未知发行版"

        sys_redhat = distro_info.get('is_rhel', False) or distro_info.get('is_centos', False)
        sys_kylin = distro_info.get('is_kylin', False)

        family_ok = (sys_redhat and iso_redhat) or (sys_kylin and iso_kylin)
        if not family_ok:
            return False, "发行版不匹配"

        sys_ver = distro_info.get('version', '')
        if not sys_ver:
            return True, "无法比较版本"

        iso_nums = re.findall(r'(\d[\d.]*)', name_lower)
        _arch_nums = {'86', '64', '32', '386', '486', '586', '686'}
        iso_nums = [v for v in iso_nums if v not in _arch_nums]
        ver_ok = any(v.startswith(sys_ver) or sys_ver.startswith(v) for v in iso_nums)
        return (True, "版本匹配") if ver_ok else (True, "版本不匹配")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    @staticmethod
    def get_disk_free(path: str) -> str:
        try:
            stat = os.statvfs(path)
            free = stat.f_frsize * stat.f_bavail
            for unit in ('B', 'KB', 'MB', 'GB'):
                if free < 1024:
                    return f"{free:.1f} {unit}"
                free /= 1024
            return f"{free:.1f} TB"
        except Exception:
            return "未知"


# ============================================================
#  SSH 管理器
# ============================================================
class SSHManager:
    def __init__(self):
        self.client: Optional['paramiko.SSHClient'] = None
        self.sftp: Optional['paramiko.SFTPClient'] = None
        self.connected = False
        self.host = ""
        self.port = 22
        self.user = ""
        self._cached_distro: Optional[dict] = None
        self._cached_ips: List[str] = []

    def connect(self, host: str, port: int, user: str, password: str = "",
                key_path: str = "", passphrase: str = "") -> str:
        if not HAS_PARAMIKO:
            return "paramiko 未安装，请运行: pip install paramiko"
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            if key_path:
                pkey = paramiko.RSAKey.from_private_key_file(key_path, password=passphrase)
                self.client.connect(host, port=port, username=user, pkey=pkey, timeout=15)
            else:
                self.client.connect(host, port=port, username=user, password=password, timeout=15)
            self.sftp = self.client.open_sftp()
            self.connected = True
            self.host = host
            self.port = port
            self.user = user
            self._cache_remote_info()
            return ""
        except Exception as e:
            self.connected = False
            self.client = None
            self.sftp = None
            return str(e)

    def disconnect(self):
        if self.sftp:
            try: self.sftp.close()
            except: pass
            self.sftp = None
        if self.client:
            try: self.client.close()
            except: pass
            self.client = None
        self.connected = False
        self._cached_distro = None
        self._cached_ips = []

    def exec_command(self, command: str, timeout: int = 600) -> tuple:
        if not self.connected or not self.client:
            return False, "SSH 未连接"
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode('utf-8', errors='replace').strip()
            err = stderr.read().decode('utf-8', errors='replace').strip()
            if exit_code == 0:
                return True, out if out else "完成"
            return False, err if err else f"退出码: {exit_code}"
        except Exception as e:
            return False, str(e)

    def put_file(self, local_path: str, remote_path: str) -> str:
        if not self.sftp:
            return "SFTP 未连接"
        try:
            self.sftp.put(local_path, remote_path)
            return ""
        except Exception as e:
            return str(e)

    def get_file(self, remote_path: str, local_path: str) -> str:
        if not self.sftp:
            return "SFTP 未连接"
        try:
            self.sftp.get(remote_path, local_path)
            return ""
        except Exception as e:
            return str(e)

    def write_file(self, remote_path: str, content: str) -> str:
        if not self.sftp:
            return "SFTP 未连接"
        try:
            f = self.sftp.open(remote_path, 'w')
            f.write(content)
            f.close()
            return ""
        except Exception as e:
            return str(e)

    def list_dir(self, path: str) -> list:
        if not self.sftp:
            return []
        try:
            return self.sftp.listdir_attr(path)
        except:
            return []

    def file_exists(self, path: str) -> bool:
        if not self.sftp:
            return False
        try:
            self.sftp.stat(path)
            return True
        except:
            return False

    def _cache_remote_info(self):
        """缓存远程系统的发行版信息和 IP 列表"""
        self._cached_distro = None
        self._cached_ips = []

        ok, out = self.exec_command("cat /etc/os-release 2>/dev/null")
        if ok:
            info = {'pretty_name': 'Unknown', 'distro': 'unknown',
                    'version': '', 'version_id': '', 'arch': 'unknown',
                    'needs_appstream': False, 'is_rhel': False,
                    'is_kylin': False, 'is_centos': False}
            for line in out.split('\n'):
                line = line.strip()
                if line.startswith('PRETTY_NAME='):
                    info['pretty_name'] = line.split('=', 1)[1].strip('"\'')
                elif line.startswith('VERSION_ID='):
                    info['version_id'] = line.split('=', 1)[1].strip('"\'')
                elif line.startswith('ID='):
                    info['distro'] = line.split('=', 1)[1].strip('"\'')
            name = info['pretty_name'].lower()
            info['is_rhel'] = 'red hat' in name or 'rhel' in name
            info['is_centos'] = 'centos' in name
            info['is_kylin'] = 'kylin' in name
            nums = re.findall(r'(\d+)', info['version_id'])
            major = nums[0] if nums else ''
            info['version'] = major
            if (info['is_rhel'] and major in ('8', '9')) or (info['is_centos'] and major == '8'):
                info['needs_appstream'] = True
            ok2, arch_out = self.exec_command("uname -m")
            if ok2:
                info['arch'] = arch_out.strip()
            self._cached_distro = info

        ok, out = self.exec_command("ip -o addr show | awk '/inet / && !/127.0.0.1/ {print $4}' | cut -d'/' -f1")
        if ok:
            self._cached_ips = [ip.strip() for ip in out.split() if ip.strip()]
        if not self._cached_ips:
            self._cached_ips = ['127.0.0.1']

    def get_cached_distro(self) -> dict:
        return self._cached_distro or {}

    def get_cached_ips(self) -> list:
        return self._cached_ips or ['127.0.0.1']

    def scan_remote_isos(self, directory: str) -> List[dict]:
        """通过 SFTP 扫描远程目录中的 ISO 文件"""
        results = []
        if not self.sftp:
            return results
        attrs = self.list_dir(directory)
        for attr in attrs:
            if attr.filename.lower().endswith('.iso'):
                results.append({
                    'name': attr.filename,
                    'path': f"{directory}/{attr.filename}",
                    'size': attr.st_size,
                    'size_str': SystemDetector._format_size(attr.st_size),
                })
        return sorted(results, key=lambda x: x['name'])


# ============================================================
#  异步执行器
# ============================================================
class ExecutorThread(QThread):
    log = Signal(str, str)
    progress = Signal(int)
    step = Signal(str)
    finished_signal = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: List[Tuple[str, str]] = []
        self._cancelled = False
        self._mutex = QMutex()
        self._ssh: Optional[SSHManager] = None

    def set_tasks(self, tasks: List[Tuple[str, str]]):
        self._tasks = list(tasks)

    def set_ssh(self, ssh: Optional[SSHManager]):
        self._ssh = ssh

    def cancel(self):
        with QMutexLocker(self._mutex):
            self._cancelled = True

    def run(self):
        total = len(self._tasks)
        for i, (desc, cmd) in enumerate(self._tasks):
            with QMutexLocker(self._mutex):
                if self._cancelled:
                    self.log.emit('warning', '用户取消执行')
                    self.finished_signal.emit(False)
                    return

            pct = int(i / total * 100) if total > 0 else 0
            self.step.emit(desc)
            self.progress.emit(pct)
            self.log.emit('step', f"[{i+1}/{total}] {desc}")
            
            # 打印实际执行的命令
            short_cmd = cmd.strip().split('\n')[0]
            if len(cmd.strip().split('\n')) > 1:
                short_cmd += " ... (多行脚本)"
            self.log.emit('cmd', f"执行命令: {short_cmd}")

            success, output = self._run_cmd(cmd)
            output = output.strip() if output else "完成"
            level = 'success' if success else 'error'
            
            # 显示退出状态和详细输出
            self.log.emit(level, f"exit={'0' if success else '1+'}, {output}")

            if not success:
                self.log.emit('error', f"任务失败: {desc}")
                self.finished_signal.emit(False)
                return

        self.progress.emit(100)
        self.finished_signal.emit(True)

    def _run_cmd(self, cmd: str) -> Tuple[bool, str]:
        if self._ssh and self._ssh.connected:
            return self._ssh.exec_command(cmd, timeout=600)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0:
                out = result.stdout.strip()
                return (True, out) if out else (True, "完成")
            else:
                err = result.stderr.strip()
                return False, err if err else f"退出码: {result.returncode}"
        except subprocess.TimeoutExpired:
            return False, "命令执行超时(600s)"
        except Exception as e:
            return False, str(e)


class YumCheckThread(QThread):
    finished = Signal(bool)  # True=正常, False=异常

    def __init__(self, ssh_manager: SSHManager, parent=None):
        super().__init__(parent)
        self.ssh_manager = ssh_manager

    def run(self):
        if not self.ssh_manager.connected:
            self.finished.emit(False)
            return
        ok, out = self.ssh_manager.exec_command(
            "yum clean all 2>/dev/null; yum makecache 2>&1; yum install -y --downloadonly chrony 2>&1; echo __RC__$?",
            timeout=180
        )
        rc = -1
        for line in reversed(out.strip().split('\n')):
            m = re.match(r'__RC__(\d+)', line.strip())
            if m:
                rc = int(m.group(1))
                break
        self.finished.emit(ok and rc == 0)


# ============================================================
#  拖拽上传区域
# ============================================================
class DropUploadWidget(QWidget):
    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.file_dropped.emit(path)
                break


# ============================================================
#  全选表头（复选框第一列）
# ============================================================
class CheckboxHeader(QHeaderView):
    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._checked = False
        self.setSectionsClickable(True)

    def paintSection(self, painter, rect, logicalIndex):
        if logicalIndex == 0:
            painter.save()
            # 绘制表头背景
            hdr_opt = QStyleOptionHeader()
            self.initStyleOption(hdr_opt)
            hdr_opt.rect = rect
            self.style().drawControl(QStyle.CE_Header, hdr_opt, painter, self)
            # 绘制复选框
            cb_opt = QStyleOptionButton()
            cb_opt.rect = rect.adjusted(6, 6, -6, -6)
            cb_opt.state = QStyle.State_Enabled | (QStyle.State_On if self._checked else QStyle.State_Off)
            self.style().drawControl(QStyle.CE_CheckBox, cb_opt, painter)
            painter.restore()
        else:
            super().paintSection(painter, rect, logicalIndex)

    def mousePressEvent(self, event):
        idx = self.logicalIndexAt(event.pos())
        if idx == 0:
            self._checked = not self._checked
            self.toggled.emit(self._checked)
            self.updateSection(0)
        else:
            super().mousePressEvent(event)


# ============================================================
#  客户端检测线程
# ============================================================
class ClientDetectThread(QThread):
    result = Signal(str, str, str, bool, str, str, bool)  # ip, os_type, version, yum_ok, yum_url, url_type, connected

    def __init__(self, ip: str, port: int, user: str, pwd: str, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.port = port
        self.user = user
        self.pwd = pwd

    def run(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        os_type = "未知"
        version = ""
        yum_ok = False
        yum_url = ""
        url_type = ""
        connected = False
        try:
            ssh.connect(self.ip, port=self.port, username=self.user,
                        password=self.pwd, timeout=15)
            connected = True

            _, stdout, _ = ssh.exec_command("cat /etc/os-release", timeout=10)
            out = stdout.read().decode('utf-8', errors='replace')
            pretty = ""
            ver_id = ""
            for line in out.split('\n'):
                line = line.strip()
                if line.startswith('PRETTY_NAME='):
                    pretty = line.split('=', 1)[1].strip('"\'')
                elif line.startswith('VERSION_ID='):
                    ver_id = line.split('=', 1)[1].strip('"\'')
            name = pretty.lower()
            if 'red hat' in name or 'rhel' in name:
                os_type = "RHEL"
            elif 'centos' in name:
                os_type = "CentOS"
            elif 'rocky' in name:
                os_type = "Rocky"
            elif 'alma' in name:
                os_type = "Alma"
            elif 'oracle' in name or 'ol' in name:
                os_type = "Oracle"
            elif 'kylin' in name or 'neokylin' in name:
                os_type = "Kylin"
            else:
                os_type = pretty.split()[0] if pretty else "未知"
            nums = re.findall(r'(\d[\d.]*)', ver_id)
            version = nums[0] if nums else ver_id

            # 1) 检查 .repo 文件是否存在
            _, stdout_r, _ = ssh.exec_command(
                "ls /etc/yum.repos.d/*.repo 2>/dev/null | wc -l", timeout=10
            )
            repo_count = int(stdout_r.read().decode('utf-8', errors='replace').strip() or 0)

            # 2) 完整检测 yum 是否可用：清缓存 → 下载元数据 → 验证包可获取
            _, stdout2, _ = ssh.exec_command(
                "yum clean all 2>/dev/null; yum makecache 2>&1; yum install -y --downloadonly chrony 2>&1; echo __RC__$?",
                timeout=180
            )
            out2 = stdout2.read().decode('utf-8', errors='replace')
            # 解析最后一行 __RC__N
            exit_code = -1
            for line in reversed(out2.strip().split('\n')):
                m = re.match(r'__RC__(\d+)', line.strip())
                if m:
                    exit_code = int(m.group(1))
                    break

            yum_ok = False
            if repo_count > 0 and exit_code == 0:
                yum_ok = True

            # 检测当前 yum 源地址
            _, stdout3, _ = ssh.exec_command(
                "grep -h '^baseurl=' /etc/yum.repos.d/*.repo 2>/dev/null | head -1",
                timeout=10
            )
            raw = stdout3.read().decode('utf-8', errors='replace').strip()
            if raw:
                # 提取 baseurl= 之后的地址
                url = raw.split('=', 1)[1].strip() if '=' in raw else raw
                yum_url = url
                if url.startswith('http://') or url.startswith('https://'):
                    url_type = "🌐 远程"
                else:
                    url_type = "💻 本地"
            else:
                yum_url = "无 .repo"
                url_type = "未知"

        except Exception:
            connected = False
        finally:
            try: ssh.close()
            except: pass
        self.result.emit(self.ip, os_type, version, yum_ok, yum_url, url_type, connected)


# ============================================================
#  客户端部署工作线程
# ============================================================
class ClientDeployWorker(QThread):
    finished = Signal(str, bool, str)  # ip, success, message

    def __init__(self, ip: str, port: int, user: str, pwd: str,
                 repo_content: str, iso_dir: str, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.port = port
        self.user = user
        self.pwd = pwd
        self.repo_content = repo_content
        self.iso_dir = iso_dir

    def run(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(self.ip, port=self.port, username=self.user,
                        password=self.pwd, timeout=15)

            # 备份已有 .repo
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            stdin, stdout, stderr = ssh.exec_command(
                f"mkdir -p /etc/yum.repos.d/bak_{ts} && "
                f"mv /etc/yum.repos.d/*.repo /etc/yum.repos.d/bak_{ts}/ 2>/dev/null || true",
                timeout=30
            )
            exit_code = stdout.channel.recv_exit_status()

            # 写入 .repo
            repo_path = f"/etc/yum.repos.d/{self.iso_dir}.repo"
            with ssh.open_sftp() as sftp:
                f = sftp.open(repo_path, 'w')
                f.write(self.repo_content)
                f.close()

            # 验证 yum 可用性
            stdin, stdout, stderr = ssh.exec_command(
                "yum clean all 2>/dev/null; yum makecache 2>&1; yum install -y --downloadonly chrony 2>&1; echo __RC__$?",
                timeout=180
            )
            out = stdout.read().decode('utf-8', errors='replace')
            rc = -1
            for line in reversed(out.strip().split('\n')):
                m = re.match(r'__RC__(\d+)', line.strip())
                if m:
                    rc = int(m.group(1))
                    break
            success = rc == 0
            msg = f"部署完成" if success else f"部署完成但 yum 异常"
            self.finished.emit(self.ip, success, msg)

        except Exception as e:
            self.finished.emit(self.ip, False, str(e))
        finally:
            try: ssh.close()
            except: pass


# ============================================================
#  并发部署池
# ============================================================
class ClientDeployPool(QObject):
    all_finished = Signal()
    one_finished = Signal(str, bool, str)  # ip, success, message

    def __init__(self, clients: list, repo_content: str, iso_dir: str, parent=None):
        super().__init__(parent)
        self._queue = list(clients)  # list of (ip, port, user, pwd)
        self.repo_content = repo_content
        self.iso_dir = iso_dir
        self._active: list[ClientDeployWorker] = []
        self._max = 5

    def start(self):
        self._launch()

    def _launch(self):
        while len(self._active) < self._max and self._queue:
            c = self._queue.pop(0)
            w = ClientDeployWorker(c[0], c[1], c[2], c[3],
                                   self.repo_content, self.iso_dir)
            w.finished.connect(self._on_done)
            self._active.append(w)
            w.start()

    def _on_done(self, ip: str, success: bool, msg: str):
        self.one_finished.emit(ip, success, msg)
        self._active = [w for w in self._active if w.isRunning()]
        if self._queue or self._active:
            self._launch()
        else:
            self.all_finished.emit()


# ============================================================
#  主窗口
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.detector = SystemDetector()
        self.ssh_manager = SSHManager()
        self.distro_info = self.detector.detect_distro()
        self.executor = ExecutorThread(self)
        self._yum_check_thread: Optional[YumCheckThread] = None
        self._generated_repos: List[str] = []
        self._env_port_ok = True
        self._http_urls = []
        self._current_iso_dir = "/opt/tar"
        self._client_passwords: dict[str, str] = {}  # ip -> password
        self._selected_repo_content: str = ""
        self._selected_repo_name: str = ""

        self._init_ui()
        self._connect_signals()
        self._refresh_local_isos()
        self._refresh_server_info()
        self._refresh_yum_status()

    # ----------------------------------------------------------
    #  UI 构建 — 纯 Fusion 风格，无全局 stylesheet
    # ----------------------------------------------------------
    def _init_ui(self):
        self.setWindowTitle("Linux YUM 源管理器")
        self.setMinimumSize(1000, 720)
        self.resize(1200, 850)
        self.setStyleSheet("QMainWindow { background: #f5f6fa; }")

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # SSH 连接栏 (Docker 工具风格)
        self._build_connection_bar(main_layout)
        self._build_separator(main_layout)

        # 导航标签
        nav = QFrame()
        nav.setStyleSheet("QFrame { background: white; border-bottom: 1px solid #e0e0e0; }")
        nav_row = QHBoxLayout(nav)
        nav_row.setContentsMargins(12, 4, 12, 4)
        nav_row.setSpacing(1)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        n1 = self._tab_btn("📦  服务器配置", 0)
        n2 = self._tab_btn("📋  客户端配置", 1)
        nav_row.addWidget(n1)
        nav_row.addWidget(n2)
        nav_row.addStretch()

        self.lbl_update = QLabel("")
        self.lbl_update.setStyleSheet("color: #b2bec3; font-size: 11px;")
        nav_row.addWidget(self.lbl_update)
        main_layout.addWidget(nav)

        # 内容区域
        self.stack = QStackedWidget()
        self.page_server = self._build_server_page()
        self.page_client = self._build_client_page()
        self.stack.addWidget(self.page_server)
        self.stack.addWidget(self.page_client)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.stack)
        main_layout.addWidget(content, 1)

        # 底部日志 (Docker 工具风格)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(150)
        self.log_box.setStyleSheet("""
            QTextEdit {
                background: white; color: #333;
                font-family: Consolas, monospace; font-size: 11px;
                border: 1px solid #ddd; padding: 6px;
            }
        """)
        main_layout.addWidget(self.log_box)

        # SSH 断开时禁用服务器配置页
        self.page_server.setEnabled(False)

    # ----------------------------------------------------------
    #  SSH 连接栏 — Docker 工具风格
    # ----------------------------------------------------------
    def _build_connection_bar(self, parent):
        bar = QFrame()
        bar.setStyleSheet("QFrame { background: white; border-bottom: 1px solid #dfe6e9; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)

        layout.addWidget(QLabel("🔗"))

        # 主机
        layout.addWidget(QLabel("主机:"))
        self.ssh_host = QLineEdit()
        self.ssh_host.setPlaceholderText("192.168.1.100")
        self.ssh_host.setFixedHeight(34)
        self.ssh_host.setMinimumWidth(200)
        self.ssh_host.setStyleSheet("""
            QLineEdit { border: 1px solid #dfe6e9; border-radius: 4px;
                         padding: 0 12px; font-size: 13px; background: white; color: #2d3436; }
            QLineEdit:focus { border: 1px solid #0984e3; }
        """)
        layout.addWidget(self.ssh_host)

        # 端口
        layout.addWidget(QLabel("端口:"))
        self.ssh_port = QLineEdit("22")
        self.ssh_port.setFixedWidth(70)
        self.ssh_port.setFixedHeight(34)
        self.ssh_port.setStyleSheet(self.ssh_host.styleSheet())
        layout.addWidget(self.ssh_port)

        # 用户
        layout.addWidget(QLabel("用户:"))
        self.ssh_user = QLineEdit("root")
        self.ssh_user.setFixedWidth(110)
        self.ssh_user.setFixedHeight(34)
        self.ssh_user.setStyleSheet(self.ssh_host.styleSheet())
        layout.addWidget(self.ssh_user)

        # 密码
        layout.addWidget(QLabel("密码:"))
        self.ssh_pass = QLineEdit()
        self.ssh_pass.setPlaceholderText("********")
        self.ssh_pass.setEchoMode(QLineEdit.Password)
        self.ssh_pass.setFixedWidth(140)
        self.ssh_pass.setFixedHeight(34)
        self.ssh_pass.setStyleSheet(self.ssh_host.styleSheet())
        layout.addWidget(self.ssh_pass)

        # 连接按钮
        self.btn_ssh_toggle = QPushButton("连接")
        self.btn_ssh_toggle.setFixedHeight(34)
        self.btn_ssh_toggle.setStyleSheet("""
            QPushButton {
                background: #0984e3; color: white; border: none;
                border-radius: 4px; padding: 0 20px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background: #0873c4; }
            QPushButton:disabled { background: #b2bec3; }
        """)
        self.btn_ssh_toggle.clicked.connect(self._toggle_ssh)
        layout.addWidget(self.btn_ssh_toggle)

        # 刷新 ISO 按钮
        self.btn_ssh_refresh = QPushButton("刷新")
        self.btn_ssh_refresh.setFixedHeight(34)
        self.btn_ssh_refresh.setStyleSheet("""
            QPushButton {
                background: #27ae60; color: white; border: none;
                border-radius: 4px; padding: 0 20px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background: #1e914f; }
            QPushButton:disabled { background: #b2bec3; }
        """)
        self.btn_ssh_refresh.clicked.connect(self._refresh_isos)
        layout.addWidget(self.btn_ssh_refresh)

        layout.addStretch()

        self.ssh_status_label = QLabel("● 未连接")
        self.ssh_status_label.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 13px;")
        layout.addWidget(self.ssh_status_label)

        parent.addWidget(bar)

    def _build_separator(self, parent):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #dfe6e9; max-height: 1px;")
        parent.addWidget(sep)

    def _toggle_ssh(self):
        if self.ssh_manager.connected:
            self._disconnect_ssh()
        else:
            self._connect_ssh()

    def _connect_ssh(self):
        host = self.ssh_host.text().strip()
        if not host:
            QMessageBox.warning(self, "提示", "请输入主机地址")
            return
        try:
            port = int(self.ssh_port.text().strip() or "22")
        except ValueError:
            port = 22
        user = self.ssh_user.text().strip() or "root"
        password = self.ssh_pass.text()

        self._set_ssh_ui_busy(True)
        self._log(f"正在连接 SSH: {user}@{host}:{port}...")

        err = self.ssh_manager.connect(host, port, user, password)
        if err:
            self._log(f"❌ SSH 连接失败: {err}")
            QMessageBox.critical(self, "连接失败", f"SSH 连接失败:\n{err}")
            self._set_ssh_ui_busy(False)
            return

        self._log(f"✅ SSH 连接成功: {user}@{host}:{port}")
        self._on_ssh_connected()

    def _disconnect_ssh(self):
        self.ssh_manager.disconnect()
        self._on_ssh_disconnected()
        self._log("SSH 已断开")

    def _on_ssh_connected(self):
        self._set_ssh_ui_busy(False)
        host_str = f"{self.ssh_manager.user}@{self.ssh_manager.host}"
        self.ssh_status_label.setText(f"● 已连接 {host_str}")
        self.ssh_status_label.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 13px;")
        self.btn_ssh_toggle.setText("断开")
        self.btn_ssh_toggle.setStyleSheet("""
            QPushButton {
                background: #d63031; color: white; border: none;
                border-radius: 4px; padding: 0 20px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background: #b71c1c; }
        """)
        self.ssh_host.setEnabled(False)
        self.ssh_port.setEnabled(False)
        self.ssh_user.setEnabled(False)
        self.ssh_pass.setEnabled(False)
        self._refresh_isos()
        self._refresh_ip_list()
        self._refresh_server_info()
        self._check_mount_path()
        self.page_server.setEnabled(True)
        if self._yum_check_thread and self._yum_check_thread.isRunning():
            self._yum_check_thread.quit()
            self._yum_check_thread.wait(2000)
        self._refresh_yum_status()
        QTimer.singleShot(3000, self._check_web_environment)
        self._refresh_repo_server_list()

    def _on_ssh_disconnected(self):
        self._refresh_repo_server_list()
        self.page_server.setEnabled(False)
        self.btn_web_exec.setEnabled(False)
        self.web_iso_list.setEnabled(False)
        self.btn_add_exec.setEnabled(False)
        self.add_iso_list.setEnabled(False)
        self.ssh_status_label.setText("● 未连接")
        self.ssh_status_label.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 13px;")
        self.btn_ssh_toggle.setText("连接")
        self.btn_ssh_toggle.setStyleSheet("""
            QPushButton {
                background: #0984e3; color: white; border: none;
                border-radius: 4px; padding: 0 20px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background: #0873c4; }
        """)
        self.ssh_host.setEnabled(True)
        self.ssh_port.setEnabled(True)
        self.ssh_user.setEnabled(True)
        self.ssh_pass.setEnabled(True)
        self._refresh_isos()
        self._refresh_ip_list()
        self._refresh_server_info()
        self._check_mount_path()
        if self._yum_check_thread and self._yum_check_thread.isRunning():
            self._yum_check_thread.quit()
            self._yum_check_thread.wait(2000)
        self._refresh_yum_status()

    def _set_ssh_ui_busy(self, busy: bool):
        self.btn_ssh_toggle.setEnabled(not busy)
        self.btn_ssh_toggle.setText("连接中..." if busy else "连接")

    def _refresh_ip_list(self):
        """刷新 IP 下拉列表（SSH 连接/断开时调用）"""
        self.cb_ip.clear()
        if self.ssh_manager.connected:
            ips = self.ssh_manager.get_cached_ips()
        else:
            ips = self.detector.get_ip_list()
        for ip in ips:
            self.cb_ip.addItem(ip)
        if ips:
            self.cb_ip.setCurrentText(ips[0])

    # ----------------------------------------------------------
    #  Tab 按钮
    # ----------------------------------------------------------
    def _tab_btn(self, text: str, idx: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setChecked(idx == 0)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #636e72;
                border: none; border-radius: 4px;
                padding: 6px 16px; font-size: 13px;
            }
            QPushButton:hover { background: #f0f3f5; color: #2d3436; }
            QPushButton:checked {
                background: #e8f0fe; color: #0984e3; font-weight: bold;
            }
        """)
        self.nav_group.addButton(btn, idx)
        if idx == 0:
            self.btn_server_tab = btn
        else:
            self.btn_client_tab = btn
        return btn

    def _switch_tab(self, index: int):
        self.stack.setCurrentIndex(index)
        if index == 1:
            self._on_repo_source_changed()

    # ----------------------------------------------------------
    #  页面构建 — 服务器配置（左1/4 + 右3/4）
    # ----------------------------------------------------------
    def _build_server_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("QWidget { background: #f5f6fa; }")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        split = QHBoxLayout()
        split.setContentsMargins(16, 12, 16, 12)
        split.setSpacing(12)

        # ========== 左栏 ==========
        left = QFrame()
        left.setStyleSheet("QFrame { background: white; border: 1px solid #e0e0e0; border-radius: 8px; }")
        left.setFixedWidth(220)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        # 标题区 — 水平垂直居中
        title_frame = QFrame()
        title_frame.setStyleSheet("QFrame { background: #f8f9fb; border-bottom: 1px solid #e8e8e8; border-radius: 0; }")
        title_frame.setFixedHeight(40)
        tl = QHBoxLayout(title_frame)
        tl.setContentsMargins(0, 0, 0, 0)
        title_lbl = QLabel("操作选择")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("font-size: 13px; color: #2d3436;")
        tl.addWidget(title_lbl)
        ll.addWidget(title_frame)

        # 按钮区
        btn_frame = QFrame()
        bfl = QVBoxLayout(btn_frame)
        bfl.setContentsMargins(8, 10, 8, 10)
        bfl.setSpacing(4)

        self.srv_btn_group = QButtonGroup(self)
        self.srv_btn_group.setExclusive(True)
        self.srv_btn_group.idClicked.connect(self._switch_server_form)

        def _srv_btn(text, icon, idx):
            btn = QPushButton(f"  {icon}  {text}")
            btn.setCheckable(True)
            btn.setChecked(idx == 0)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #555; border: none;
                    border-radius: 6px; padding: 0 12px;
                    font-size: 13px; text-align: left;
                }
                QPushButton:hover { background: #f0f4ff; color: #0984e3; }
                QPushButton:checked {
                    background: #e8f0fe; color: #0984e3; font-weight: bold;
                }
                QPushButton:disabled { background: transparent; color: #ccc; }
            """)
            self.srv_btn_group.addButton(btn, idx)
            bfl.addWidget(btn)
            return btn

        self.btn_srv_local = _srv_btn("创建本地yum源", "📦", 0)
        self.btn_srv_web = _srv_btn("创建webyum源", "🌐", 1)
        self.btn_srv_web_add = _srv_btn("新增webyum源", "➕", 2)
        bfl.addStretch()
        ll.addWidget(btn_frame, 1)

        # 服务器信息区 — 底部
        info_frame = QFrame()
        info_frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        ifl = QVBoxLayout(info_frame)
        ifl.setContentsMargins(12, 10, 12, 10)
        ifl.setSpacing(5)

        def _info_row(icon, label_key):
            row = QHBoxLayout()
            row.setSpacing(6)
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet("font-size: 12px;")
            row.addWidget(icon_lbl)
            val = QLabel("检测中...")
            val.setStyleSheet("font-size: 11px; color: #636e72;")
            val.setWordWrap(True)
            row.addWidget(val, 1)
            setattr(self, f'lbl_srv_{label_key}', val)
            ifl.addLayout(row)

        _info_row("🖥", "version")
        _info_row("💻", "hostname")

        # yum 源状态行
        yum_row = QHBoxLayout()
        yum_row.setSpacing(6)
        self.lbl_yum_icon = QLabel("🟢")
        self.lbl_yum_icon.setStyleSheet("font-size: 12px;")
        yum_row.addWidget(self.lbl_yum_icon)
        self.lbl_yum_status = QLabel("检测中...")
        self.lbl_yum_status.setStyleSheet("font-size: 11px; color: #636e72;")
        yum_row.addWidget(self.lbl_yum_status, 1)
        self.btn_yum_refresh = QPushButton("🔄")
        self.btn_yum_refresh.setFixedSize(26, 26)
        self.btn_yum_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_yum_refresh.setStyleSheet("""
            QPushButton { background: transparent; border: none;
                          font-size: 12px; padding: 0; }
            QPushButton:hover { background: #f0f3f5; border-radius: 13px; }
        """)
        self.btn_yum_refresh.clicked.connect(self._refresh_yum_status)
        yum_row.addWidget(self.btn_yum_refresh)
        ifl.addLayout(yum_row)
        ll.addWidget(info_frame)

        split.addWidget(left)

        # ========== 右栏 (3/4) ==========
        self.srv_stack = QStackedWidget()
        self.srv_stack.addWidget(self._build_local_form())
        self.srv_stack.addWidget(self._build_web_form())
        self.srv_stack.addWidget(self._build_web_add_form())
        split.addWidget(self.srv_stack, 1)

        layout.addLayout(split)
        return page

    # ----------------------------------------------------------
    #  本地 yum 源表单
    # ----------------------------------------------------------
    def _build_local_form(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("QWidget { background: transparent; }")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        _INPUT_H = 40
        _INPUT_W = 400
        _INPUT_STYLE = """
            QLineEdit { border: 1px solid #dfe6e9; border-radius: 4px;
                         padding: 10px 10px; font-size: 13px; background: white; }
            QLineEdit:focus { border: 1px solid #0984e3; }
        """

        # 挂载位置
        mp_grid = QGridLayout()
        mp_grid.setSpacing(4)

        desc_row = QHBoxLayout()
        desc_row.setSpacing(6)
        desc_row.addWidget(QLabel("镜像解压后存放路径",
            styleSheet="font-size: 12px; color: #636e72;"))
        desc_row.addStretch()
        self.lbl_mount_space = QLabel()
        self.lbl_mount_space.setStyleSheet("font-size: 11px; color: #636e72;")
        desc_row.addWidget(self.lbl_mount_space)
        mp_grid.addLayout(desc_row, 0, 0)

        self.local_mount_path = QLineEdit("/var/www/html")
        self.local_mount_path.setFixedHeight(_INPUT_H)
        self.local_mount_path.setFixedWidth(_INPUT_W)
        self.local_mount_path.setStyleSheet(_INPUT_STYLE)
        mp_grid.addWidget(self.local_mount_path, 1, 0)

        self.lbl_mount_warn = QLabel()
        self.lbl_mount_warn.setStyleSheet("font-size: 11px; color: #f39c12;")
        mp_grid.addWidget(self.lbl_mount_warn, 1, 1)

        mp_grid.setColumnStretch(0, 0)
        mp_grid.setColumnStretch(1, 1)
        layout.addLayout(mp_grid)
        self._mount_debounce = QTimer()
        self._mount_debounce.setSingleShot(True)
        self._mount_debounce.timeout.connect(self._check_mount_path)
        self.local_mount_path.textChanged.connect(lambda: self._mount_debounce.start(300))
        QTimer.singleShot(0, self._check_mount_path)

        # 镜像位置
        layout.addSpacing(6)
        layout.addWidget(QLabel("镜像位置（ISO 文件所在目录）",
            styleSheet="font-size: 12px; color: #636e72;"))
        ip_row = QHBoxLayout()
        ip_row.setSpacing(6)
        self.local_iso_dir = QLineEdit(self._current_iso_dir)
        self.local_iso_dir.setFixedHeight(_INPUT_H)
        self.local_iso_dir.setFixedWidth(_INPUT_W)
        self.local_iso_dir.setStyleSheet(_INPUT_STYLE)
        ip_row.addWidget(self.local_iso_dir)
        self.btn_local_refresh = QPushButton("刷新")
        self.btn_local_refresh.setFixedHeight(34)
        self.btn_local_refresh.setStyleSheet("""
            QPushButton { background: white; color: #6b7a7f; border: 1px solid #c8d0d8;
                          border-radius: 4px; padding: 6px 16px; font-size: 12px; }
            QPushButton:hover { background: #f0f3f5; }
        """)
        self.btn_local_refresh.clicked.connect(self._refresh_local_isos)
        ip_row.addWidget(self.btn_local_refresh)
        ip_row.addStretch()
        layout.addLayout(ip_row)

        # ISO 列表
        self.local_iso_list = QTreeWidget()
        self.local_iso_list.setHeaderLabels(["", "文件名", "大小", "匹配状态"])
        self.local_iso_list.setColumnWidth(0, 36)
        self.local_iso_list.setColumnWidth(1, 300)
        self.local_iso_list.setColumnWidth(2, 70)
        self.local_iso_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.local_iso_list.setAlternatingRowColors(True)
        self.local_iso_list.header().setStretchLastSection(True)
        self.local_iso_list.setStyleSheet("""
            QTreeWidget { border: 1px solid #e0e0e0; border-radius: 4px;
                          background: white; font-size: 12px; }
            QTreeWidget::item { padding: 4px 0; }
            QHeaderView::section { background: #f0f2f5; border: none;
                                    padding: 6px; font-weight: normal; font-size: 11px; }
        """)
        layout.addWidget(self.local_iso_list, 1)

        self.local_progress = QProgressBar()
        self.local_progress.setValue(0)
        self.local_progress.setFixedHeight(20)
        self.local_progress.setStyleSheet("""
            QProgressBar { border: 1px solid #dfe6e9; border-radius: 3px;
                           text-align: center; background: #f5f6fa;
                           font-size: 11px; color: #636e72; }
            QProgressBar::chunk { background: #0984e3; border-radius: 2px; }
        """)

        # 底部操作区（与左侧信息面板对齐）
        local_bottom = QFrame()
        local_bottom.setStyleSheet("QFrame { background: #f8f9fb; border: none; border-top: 1px solid #e8eaed; }")
        lbl = QVBoxLayout(local_bottom)
        lbl.setContentsMargins(12, 8, 12, 8)
        lbl.setSpacing(8)

        lbl.addWidget(self.local_progress)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_local_exec = QPushButton("▶  创建本地 yum 源")
        self.btn_local_exec.setStyleSheet("""
            QPushButton { background: #0984e3; color: white; border: none;
                          border-radius: 4px; padding: 8px 28px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background: #0873c4; }
            QPushButton:disabled { background: #b2bec3; color: #dfe6e9; }
        """)
        btn_row.addWidget(self.btn_local_exec)
        btn_row.addSpacing(8)
        self.btn_local_cancel = QPushButton("取消")
        self.btn_local_cancel.setStyleSheet("""
            QPushButton { background: white; color: #6b7a7f; border: 1px solid #c8d0d8;
                          border-radius: 4px; padding: 8px 28px; font-size: 13px; }
            QPushButton:hover { background: #f0f3f5; }
            QPushButton:disabled { color: #b2bec3; border-color: #dfe6e9; }
        """)
        btn_row.addWidget(self.btn_local_cancel)
        btn_row.addStretch()
        lbl.addLayout(btn_row)
        layout.addWidget(local_bottom)

        return page

    def _check_mount_path(self):
        path = self.local_mount_path.text().strip()
        if not path:
            self.lbl_mount_warn.setText("")
            self.lbl_mount_space.setText("")
            return
        if self.ssh_manager.connected:
            ok, out = self.ssh_manager.exec_command(
                f"if [ -d '{path}' ] && ls -A '{path}' 2>/dev/null | head -c1 | grep -q . ; then echo 'nonempty'; else echo 'empty'; fi"
            )
            if ok and 'nonempty' in out:
                self.lbl_mount_warn.setText("⚠ 目录非空")
            else:
                self.lbl_mount_warn.setText("")
        else:
            if os.path.isdir(path):
                items = os.listdir(path)
                if items:
                    self.lbl_mount_warn.setText(f"⚠ 目录非空 ({len(items)} 个文件/子目录)")
                else:
                    self.lbl_mount_warn.setText("")
            else:
                self.lbl_mount_warn.setText("")

        if self.ssh_manager.connected and path:
            ok, out = self.ssh_manager.exec_command(
                f"df -h '{path}' 2>/dev/null | tail -1 | awk '{{print $4}}'"
            )
            free = out.strip() if ok and out.strip() else ""
            self.lbl_mount_space.setText(
                f"剩余: {free}" if free else "剩余: 未知"
            )
        else:
            self.lbl_mount_space.setText("")

    # ----------------------------------------------------------
    #  Web yum 源表单
    # ----------------------------------------------------------
    def _build_env_check_card(self, suffix: str = "") -> QFrame:
        """构建环境预检查卡片，suffix 区分 web / add 两套标签"""
        card = QFrame()
        card.setStyleSheet("QFrame { background: transparent; border: none; }")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)

        # 标题行
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("🔍 环境预检查",
            styleSheet="font-size: 13px; font-weight: bold; color: #2d3436;"))
        title_row.addStretch()

        # web 表单才有关闭按钮
        if not suffix:
            self.btn_env_disable_all = QPushButton("一键关闭防火墙和SELinux")
            self.btn_env_disable_all.setFixedHeight(30)
            self.btn_env_disable_all.setStyleSheet("""
                QPushButton { background: #d63031; color: white; border: none;
                              border-radius: 4px; padding: 0 16px; font-size: 10px; font-weight: bold; }
                QPushButton:hover { background: #b71c1c; }
                QPushButton:disabled { background: #b2bec3; color: #dfe6e9; }
            """)
            self.btn_env_disable_all.clicked.connect(self._disable_all)
            title_row.addWidget(self.btn_env_disable_all)

        btn_refresh = QPushButton("🔄 刷新检查")
        btn_refresh.setFixedHeight(30)
        btn_refresh.setStyleSheet("""
            QPushButton { background: #0984e3; color: white; border: none;
                          border-radius: 4px; padding: 0 16px; font-size: 11px; font-weight: bold; }
            QPushButton:hover { background: #0873c4; }
        """)
        btn_refresh.clicked.connect(self._check_web_environment)
        title_row.addWidget(btn_refresh)
        cl.addLayout(title_row)

        port_lbl = QLabel("⏳ 端口 80: 检测中...")
        httpd_lbl = QLabel("⏳ httpd: 检测中...")
        SS = "font-size: 12px; color: #636e72; padding: 3px 0;"

        # web 表单（双列布局，无行内关闭按钮）
        if not suffix:
            fw_lbl = QLabel("⏳ 防火墙: 检测中...")
            se_lbl = QLabel("⏳ SELinux: 检测中...")

            cols = QHBoxLayout()
            cols.setSpacing(30)
            left = QVBoxLayout()
            left.setSpacing(2)
            for lbl in (port_lbl, httpd_lbl):
                lbl.setStyleSheet(SS)
                left.addWidget(lbl)
            cols.addLayout(left)

            right = QVBoxLayout()
            right.setSpacing(2)
            for lbl in (fw_lbl, se_lbl):
                lbl.setStyleSheet(SS)
                right.addWidget(lbl)
            cols.addLayout(right)
            cl.addLayout(cols)

            setattr(self, f'lbl_env_fw{suffix}', fw_lbl)
            setattr(self, f'lbl_env_se{suffix}', se_lbl)

        # add 表单（双列布局，无关闭按钮）
        else:
            fw_lbl = QLabel("⏳ 防火墙: 检测中...")
            se_lbl = QLabel("⏳ SELinux: 检测中...")

            cols = QHBoxLayout()
            cols.setSpacing(30)
            left = QVBoxLayout()
            left.setSpacing(2)
            for lbl in (port_lbl, httpd_lbl):
                lbl.setStyleSheet(SS)
                left.addWidget(lbl)
            cols.addLayout(left)

            right = QVBoxLayout()
            right.setSpacing(2)
            for lbl in (fw_lbl, se_lbl):
                lbl.setStyleSheet(SS)
                right.addWidget(lbl)
            cols.addLayout(right)
            cl.addLayout(cols)

            setattr(self, f'lbl_env_fw{suffix}', fw_lbl)
            setattr(self, f'lbl_env_se{suffix}', se_lbl)
            setattr(self, f'btn_env_fw{suffix}', None)
            setattr(self, f'btn_env_se{suffix}', None)

        for name, lbl in (('port', port_lbl), ('httpd', httpd_lbl)):
            setattr(self, f'lbl_env_{name}{suffix}', lbl)
        setattr(self, f'btn_env_refresh{suffix}', btn_refresh)

        return card

    def _check_web_environment(self):
        """刷新所有环境预检查标签"""
        for suffix in ('', '_add'):
            port_lbl = getattr(self, f'lbl_env_port{suffix}', None)
            httpd_lbl = getattr(self, f'lbl_env_httpd{suffix}', None)
            fw_lbl = getattr(self, f'lbl_env_fw{suffix}', None)
            se_lbl = getattr(self, f'lbl_env_se{suffix}', None)
            if not port_lbl:
                continue
            is_add = (suffix == '_add')
            SS = "font-size: 12px; padding: 3px 0;"

            if not self.ssh_manager.connected:
                port_lbl.setText("❌ SSH 未连接"); httpd_lbl.setText("❌ SSH 未连接")
                if fw_lbl: fw_lbl.setText("❌ SSH 未连接")
                if se_lbl: se_lbl.setText("❌ SSH 未连接")
                continue

            # 端口 80
            ok, out = self.ssh_manager.exec_command(
                "ss -tlnp 2>/dev/null | grep -q ':80 ' && echo 'occupied' || "
                "netstat -tln 2>/dev/null | grep -q ':80 ' && echo 'occupied' || echo 'free'"
            )
            occupied = 'occupied' in out
            if is_add:
                port_lbl.setText("  ✅ 端口 80: 运行中" if occupied else "  ❌ 端口 80: 未启用")
                port_lbl.setStyleSheet(SS + ("color: #27ae60;" if occupied else "color: #d63031;"))
            else:
                port_lbl.setText("  ✅ 端口 80: 未占用" if not occupied else "  ❌ 端口 80: 已被占用")
                port_lbl.setStyleSheet(SS + ("color: #27ae60;" if not occupied else "color: #d63031;"))
                self._env_port_ok = not occupied

            # httpd 状态（区分未安装 vs 已停止）
            ok, out = self.ssh_manager.exec_command("systemctl is-active httpd 2>&1 || true")
            stat = out.strip()
            if is_add:
                if stat == 'active':
                    httpd_lbl.setText("  ✅ httpd: 运行中")
                    httpd_lbl.setStyleSheet(SS + "color: #27ae60;")
                elif stat == 'inactive':
                    httpd_lbl.setText("  ❌ httpd: 已停止")
                    httpd_lbl.setStyleSheet(SS + "color: #d63031;")
                else:
                    httpd_lbl.setText("  ❌ httpd: 未安装")
                    httpd_lbl.setStyleSheet(SS + "color: #d63031;")
            else:
                if stat == 'active':
                    httpd_lbl.setText("  ✅ httpd: 运行中")
                    httpd_lbl.setStyleSheet(SS + "color: #27ae60;")
                elif stat == 'inactive':
                    httpd_lbl.setText("  ✅ httpd: 已停止（可重启）")
                    httpd_lbl.setStyleSheet(SS + "color: #0984e3;")
                else:
                    httpd_lbl.setText("  ✅ httpd: 未安装（可部署）")
                    httpd_lbl.setStyleSheet(SS + "color: #0984e3;")

            # 防火墙状态
            if fw_lbl:
                ok, out = self.ssh_manager.exec_command("systemctl is-active firewalld 2>/dev/null")
                active = ok and 'active' in out
                fw_good = not active if is_add else True
                fw_lbl.setText(
                    f"  {'✅' if fw_good else '🔴'} 防火墙: {'运行中' if active else '已关闭'}"
                )
                fw_lbl.setStyleSheet(SS + ("color: #27ae60;" if fw_good else "color: #d63031;"))

            # SELinux 状态
            if se_lbl:
                ok, out = self.ssh_manager.exec_command("getenforce 2>/dev/null")
                enforcing = ok and 'Enforcing' in out
                se_good = not enforcing if is_add else True
                se_lbl.setText(
                    f"  {'✅' if se_good else '🔴'} SELinux: {'开启' if enforcing else '已关闭'}"
                )
                se_lbl.setStyleSheet(SS + ("color: #27ae60;" if se_good else "color: #d63031;"))

            # 创建模式：防火墙和 SELinux 均已关闭 → 禁用一键关闭按钮
            if not is_add and hasattr(self, 'btn_env_disable_all'):
                fw_closed = "已关闭" in fw_lbl.text() if fw_lbl else False
                se_closed = "已关闭" in se_lbl.text() if se_lbl else False
                self.btn_env_disable_all.setEnabled(not (fw_closed and se_closed))

        self._update_deploy_btn_state()

    def _disable_firewall(self):
        """一键关闭防火墙"""
        self._log("正在关闭防火墙...")
        self.ssh_manager.exec_command(
            "systemctl stop firewalld 2>/dev/null; systemctl disable firewalld 2>/dev/null || true"
        )
        self._log("✅ 防火墙已关闭")
        self._check_web_environment()

    def _disable_selinux(self):
        """一键关闭 SELinux"""
        self._log("正在关闭 SELinux...")
        self.ssh_manager.exec_command(
            "setenforce 0 2>/dev/null; sed -i 's/^SELINUX=.*/SELINUX=disabled/' /etc/selinux/config || true"
        )
        self._log("✅ SELinux 已关闭")
        self._check_web_environment()

    def _disable_all(self):
        """一键关闭防火墙和 SELinux"""
        self._disable_firewall()
        self._disable_selinux()
        self._log("✅ 防火墙和 SELinux 已全部关闭")

    def _is_add_env_ok(self) -> bool:
        """新增模式环境就绪：port已启 + httpd运行 + fw关闭 + se关闭"""
        if not self.ssh_manager.connected:
            return False
        port = getattr(self, 'lbl_env_port_add', None)
        httpd = getattr(self, 'lbl_env_httpd_add', None)
        fw = getattr(self, 'lbl_env_fw_add', None)
        se = getattr(self, 'lbl_env_se_add', None)
        if not port:
            return False
        port_ok = "运行中" in port.text()
        httpd_ok = "运行中" in httpd.text()
        fw_ok = "已关闭" in fw.text()
        se_ok = "已关闭" in se.text()
        return port_ok and httpd_ok and fw_ok and se_ok

    def _update_deploy_btn_state(self):
        """根据环境检查结果控制部署/新增按钮和 ISO 列表状态"""
        ok = self.ssh_manager.connected and getattr(self, '_env_port_ok', True)
        self.btn_web_exec.setEnabled(ok)
        self.web_iso_list.setEnabled(ok)

        add_ok = self._is_add_env_ok()
        self.btn_add_exec.setEnabled(add_ok)
        self.add_iso_list.setEnabled(add_ok)

    def _build_web_form(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("QWidget { background: transparent; }")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        _INPUT_H = 40
        _INPUT_W = 360
        _INPUT_STYLE = """
            QLineEdit { border: 1px solid #dfe6e9; border-radius: 4px;
                         padding: 10px 10px; font-size: 13px; background: white; }
            QLineEdit:focus { border: 1px solid #0984e3; }
        """

        # 环境预检查（顶部）
        layout.addWidget(self._build_env_check_card(""))

        # HTTP 地址 + 镜像位置（左右平分 50/50）
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        left = QHBoxLayout()
        left.setSpacing(6)
        left.addWidget(QLabel("HTTP 地址:",
            styleSheet="font-size: 12px; color: #636e72;"))
        self.cb_ip = QComboBox()
        self.cb_ip.setEditable(True)
        self.cb_ip.setStyleSheet("""
            QComboBox { border: 1px solid #dfe6e9; border-radius: 4px;
                         padding: 4px 8px; font-size: 12px; background: #f8f9fa; }
            QComboBox:focus { border: 1px solid #0984e3; background: white; }
        """)
        self._refresh_ip_list()
        left.addWidget(self.cb_ip, 1)
        top_row.addLayout(left, 1)

        right = QHBoxLayout()
        right.setSpacing(6)
        right.addWidget(QLabel("镜像位置:",
            styleSheet="font-size: 12px; color: #636e72;"))
        self.web_iso_dir = QLineEdit(self._current_iso_dir)
        self.web_iso_dir.setFixedHeight(_INPUT_H)
        self.web_iso_dir.setStyleSheet(_INPUT_STYLE)
        right.addWidget(self.web_iso_dir, 1)
        self.btn_web_refresh = QPushButton("刷新")
        self.btn_web_refresh.setFixedHeight(34)
        self.btn_web_refresh.setStyleSheet("""
            QPushButton { background: white; color: #6b7a7f; border: 1px solid #c8d0d8;
                          border-radius: 4px; padding: 6px 16px; font-size: 12px; }
            QPushButton:hover { background: #f0f3f5; }
        """)
        self.btn_web_refresh.clicked.connect(self._refresh_web_isos)
        right.addWidget(self.btn_web_refresh)
        top_row.addLayout(right, 1)
        layout.addLayout(top_row)

        # ISO 列表（多选，无版本匹配）
        self.web_iso_list = QTreeWidget()
        self.web_iso_list.setHeaderLabels(["", "文件名", "大小"])
        self.web_iso_list.setColumnWidth(0, 36)
        self.web_iso_list.setColumnWidth(1, 300)
        self.web_iso_list.setColumnWidth(2, 70)
        self.web_iso_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.web_iso_list.setAlternatingRowColors(True)
        self.web_iso_list.header().setStretchLastSection(False)
        self.web_iso_list.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.web_iso_list.setStyleSheet("""
            QTreeWidget { border: 1px solid #e0e0e0; border-radius: 4px;
                          background: white; font-size: 12px; }
            QTreeWidget::item { padding: 4px 0; }
            QHeaderView::section { background: #f0f2f5; border: none;
                                    padding: 6px; font-weight: normal; font-size: 11px; }
        """)
        self.web_iso_list.itemChanged.connect(self._on_web_iso_changed)
        layout.addWidget(self.web_iso_list, 1)

        self.web_progress = QProgressBar()
        self.web_progress.setValue(0)
        self.web_progress.setFixedHeight(20)
        self.web_progress.setStyleSheet("""
            QProgressBar { border: 1px solid #dfe6e9; border-radius: 3px;
                           text-align: center; background: #f5f6fa;
                           font-size: 11px; color: #636e72; }
            QProgressBar::chunk { background: #0984e3; border-radius: 2px; }
        """)

        # 底部操作区
        web_bottom = QFrame()
        web_bottom.setStyleSheet("QFrame { background: #f8f9fb; border: none; border-top: 1px solid #e8eaed; }")
        wbl = QVBoxLayout(web_bottom)
        wbl.setContentsMargins(12, 8, 12, 8)
        wbl.setSpacing(8)

        wbl.addWidget(self.web_progress)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_web_exec = QPushButton("▶  开始部署")
        self.btn_web_exec.setStyleSheet("""
            QPushButton { background: #0984e3; color: white; border: none;
                          border-radius: 4px; padding: 8px 28px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background: #0873c4; }
            QPushButton:disabled { background: #b2bec3; color: #dfe6e9; }
        """)
        btn_row.addWidget(self.btn_web_exec)
        btn_row.addSpacing(8)
        self.btn_web_dl_local = QPushButton("⬇ 下载 .repo文件")
        self.btn_web_dl_local.setStyleSheet("""
            QPushButton { background: white; color: #6b7a7f; border: 1px solid #c8d0d8;
                          border-radius: 4px; padding: 8px 18px; font-size: 12px; }
            QPushButton:hover { background: #f0f3f5; }
        """)
        self.btn_web_dl_local.clicked.connect(self._on_download_repos)
        btn_row.addWidget(self.btn_web_dl_local)
        btn_row.addStretch()
        wbl.addLayout(btn_row)
        layout.addWidget(web_bottom)

        return page

    # ----------------------------------------------------------
    #  新增 web yum 源表单
    # ----------------------------------------------------------
    def _build_web_add_form(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("QWidget { background: transparent; }")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        _INPUT_H = 40
        _INPUT_STYLE = """
            QLineEdit { border: 1px solid #dfe6e9; border-radius: 4px;
                         padding: 10px 10px; font-size: 13px; background: white; }
            QLineEdit:focus { border: 1px solid #0984e3; }
        """

        # 环境预检查
        layout.addWidget(self._build_env_check_card("_add"))

        # 镜像位置（占整行）
        self.add_cb_ip = QComboBox()
        self._refresh_ip_list()
        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        dir_row.addWidget(QLabel("镜像位置:",
            styleSheet="font-size: 12px; color: #636e72;"))
        self.add_iso_dir = QLineEdit(self._current_iso_dir)
        self.add_iso_dir.setFixedHeight(_INPUT_H)
        self.add_iso_dir.setStyleSheet(_INPUT_STYLE)
        dir_row.addWidget(self.add_iso_dir, 1)
        self.btn_add_refresh = QPushButton("刷新")
        self.btn_add_refresh.setFixedHeight(34)
        self.btn_add_refresh.setStyleSheet("""
            QPushButton { background: white; color: #6b7a7f; border: 1px solid #c8d0d8;
                          border-radius: 4px; padding: 6px 16px; font-size: 12px; }
            QPushButton:hover { background: #f0f3f5; }
        """)
        self.btn_add_refresh.clicked.connect(self._refresh_add_isos)
        dir_row.addWidget(self.btn_add_refresh)
        layout.addLayout(dir_row)

        # ISO 列表（多选，无版本匹配）
        self.add_iso_list = QTreeWidget()
        self.add_iso_list.setHeaderLabels(["", "文件名", "大小"])
        self.add_iso_list.setColumnWidth(0, 36)
        self.add_iso_list.setColumnWidth(1, 300)
        self.add_iso_list.setColumnWidth(2, 70)
        self.add_iso_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.add_iso_list.setAlternatingRowColors(True)
        self.add_iso_list.header().setStretchLastSection(False)
        self.add_iso_list.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.add_iso_list.setStyleSheet("""
            QTreeWidget { border: 1px solid #e0e0e0; border-radius: 4px;
                          background: white; font-size: 12px; }
            QTreeWidget::item { padding: 4px 0; }
            QHeaderView::section { background: #f0f2f5; border: none;
                                    padding: 6px; font-weight: normal; font-size: 11px; }
        """)
        self.add_iso_list.itemChanged.connect(self._on_add_iso_changed)
        layout.addWidget(self.add_iso_list, 1)

        self.add_progress = QProgressBar()
        self.add_progress.setValue(0)
        self.add_progress.setFixedHeight(20)
        self.add_progress.setStyleSheet("""
            QProgressBar { border: 1px solid #dfe6e9; border-radius: 3px;
                           text-align: center; background: #f5f6fa;
                           font-size: 11px; color: #636e72; }
            QProgressBar::chunk { background: #0984e3; border-radius: 2px; }
        """)

        # 底部操作区
        add_bottom = QFrame()
        add_bottom.setStyleSheet("QFrame { background: #f8f9fb; border: none; border-top: 1px solid #e8eaed; }")
        abl = QVBoxLayout(add_bottom)
        abl.setContentsMargins(12, 8, 12, 8)
        abl.setSpacing(8)

        abl.addWidget(self.add_progress)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_add_exec = QPushButton("▶  新增 Web yum 源")
        self.btn_add_exec.setStyleSheet("""
            QPushButton { background: #0984e3; color: white; border: none;
                          border-radius: 4px; padding: 8px 28px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background: #0873c4; }
            QPushButton:disabled { background: #b2bec3; color: #dfe6e9; }
        """)
        btn_row.addWidget(self.btn_add_exec)
        btn_row.addSpacing(8)
        self.btn_add_dl_local = QPushButton("⬇ 下载 .repo")
        self.btn_add_dl_local.setStyleSheet("""
            QPushButton { background: white; color: #6b7a7f; border: 1px solid #c8d0d8;
                          border-radius: 4px; padding: 8px 18px; font-size: 12px; }
            QPushButton:hover { background: #f0f3f5; }
        """)
        self.btn_add_dl_local.clicked.connect(self._on_download_repos)
        btn_row.addWidget(self.btn_add_dl_local)
        btn_row.addStretch()
        abl.addLayout(btn_row)
        layout.addWidget(add_bottom)

        return page

    # ----------------------------------------------------------
    #  服务器配置 — 表单切换 & ISO 刷新
    # ----------------------------------------------------------
    def _switch_server_form(self, index: int):
        self.srv_stack.setCurrentIndex(index)
        if index == 0:
            self._refresh_local_isos()
        elif index == 1:
            self._refresh_web_isos()
            self._refresh_ip_list()
            if self.ssh_manager.connected:
                self._check_web_environment()
        else:
            self._refresh_add_isos()
            self._refresh_ip_list()
            if self.ssh_manager.connected:
                self._check_web_environment()

    def _refresh_local_isos(self):
        directory = self.local_iso_dir.text().strip() or self._current_iso_dir
        self._populate_iso_list(self.local_iso_list, self._scan_isos(directory))

    def _refresh_web_isos(self):
        directory = self.web_iso_dir.text().strip() or self._current_iso_dir
        self._populate_iso_list(self.web_iso_list, self._scan_isos(directory), show_match=False)

    def _refresh_add_isos(self):
        directory = self.add_iso_dir.text().strip() or self._current_iso_dir
        self._populate_iso_list(self.add_iso_list, self._scan_isos(directory), show_match=False)

    def _scan_isos(self, directory: str) -> list:
        if self.ssh_manager.connected:
            return self.ssh_manager.scan_remote_isos(directory)
        return self.detector.scan_isos(directory)

    @staticmethod
    def _shorten_distro(name: str) -> str:
        name = name.replace("Red Hat Enterprise Linux", "RHEL")
        name = name.replace("Linux Advanced Server", "")
        name = re.sub(r'\s+', ' ', name).strip()
        parts = name.split()
        nums = re.findall(r'\d+[\d.]*', name)
        ver = nums[0] if nums else ''
        if ver:
            return f"{parts[0]} {ver}"
        return parts[0] if parts else name

    def _refresh_server_info(self):
        """刷新左侧服务器信息面板"""
        if self.ssh_manager.connected:
            info = self.ssh_manager.get_cached_distro()
            ver = self._shorten_distro(info.get('pretty_name', 'Unknown'))
            self.lbl_srv_version.setText(f"版本: {ver}")

            ok, out = self.ssh_manager.exec_command("hostname")
            self.lbl_srv_hostname.setText(f"名称: {out.strip() if ok else 'Unknown'}")
        else:
            self.lbl_srv_version.setText("版本: 未知")
            self.lbl_srv_version.setStyleSheet("font-size: 12px; color: #b2bec3;")
            self.lbl_srv_hostname.setText("名称: 未知")
            self.lbl_srv_hostname.setStyleSheet("font-size: 12px; color: #b2bec3;")

    def _refresh_yum_status(self):
        if self.ssh_manager.connected:
            self.lbl_yum_icon.setText("🟡")
            self.lbl_yum_status.setText("yum 源: 检测中...")
            self.lbl_yum_status.setStyleSheet("font-size: 12px; color: #fdcb6e;")

            if self._yum_check_thread and self._yum_check_thread.isRunning():
                self._yum_check_thread.quit()
                self._yum_check_thread.wait(2000)
            self._yum_check_thread = YumCheckThread(self.ssh_manager)
            self._yum_check_thread.finished.connect(self._on_yum_check_done)
            self._yum_check_thread.start()
        else:
            self.lbl_yum_icon.setText("🟡")
            self.lbl_yum_status.setText("yum 源: 未知")
            self.lbl_yum_status.setStyleSheet("font-size: 12px; color: #fdcb6e;")

    def _on_yum_check_done(self, ok: bool):
        if ok:
            self.lbl_yum_icon.setText("🟢")
            self.lbl_yum_status.setText("yum 源: 正常")
            self.lbl_yum_status.setStyleSheet("font-size: 12px; color: #27ae60;")
        else:
            self.lbl_yum_icon.setText("🔴")
            self.lbl_yum_status.setText("yum 源: 异常")
            self.lbl_yum_status.setStyleSheet("font-size: 12px; color: #d63031;")

    def _on_web_iso_changed(self, item, column):
        selected_count = sum(
            1 for i in range(self.web_iso_list.topLevelItemCount())
            if self.web_iso_list.topLevelItem(i).checkState(0) == Qt.Checked
        )
        self.btn_web_exec.setEnabled(selected_count > 0)

    def _on_add_iso_changed(self, item, column):
        selected_count = sum(
            1 for i in range(self.add_iso_list.topLevelItemCount())
            if self.add_iso_list.topLevelItem(i).checkState(0) == Qt.Checked
        )
        self.btn_add_exec.setEnabled(selected_count > 0)

    # ----------------------------------------------------------
    #  页面构建 — 客户端配置
    # ----------------------------------------------------------
    def _build_client_page(self) -> QWidget:
        page = QWidget()
        pal = page.palette()
        pal.setColor(page.backgroundRole(), QColor("#f5f6fa"))
        page.setPalette(pal)
        page.setAutoFillBackground(True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # ── 1. Repo 文件选择卡片 ──
        repo_card = QFrame()
        repo_card.setObjectName("repo_card")
        repo_card.setStyleSheet("#repo_card { background: white; border: 1px solid #e0e0e0; border-radius: 6px; }")
        rl = QVBoxLayout(repo_card)
        rl.setContentsMargins(14, 10, 14, 10)
        rl.setSpacing(8)

        title = QLabel("📦 选择要分发的 .repo 文件")
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #2d3436; background: transparent;")
        rl.addWidget(title)

        # 来源切换
        src_row = QHBoxLayout()
        src_row.setSpacing(20)
        self.repo_source_server = QRadioButton("从服务器选择")
        self.repo_source_upload = QRadioButton("本地上传")
        self.repo_source_server.setChecked(True)
        for rb in (self.repo_source_server, self.repo_source_upload):
            rb.setStyleSheet("QRadioButton { font-size: 12px; color: #2d3436; }")
        src_row.addWidget(self.repo_source_server)
        src_row.addWidget(self.repo_source_upload)
        src_row.addStretch()
        rl.addLayout(src_row)

        # 服务器 repo 列表 + 本地上传 → QStackedWidget 共享空间
        self.repo_content_stack = QStackedWidget()
        self.repo_content_stack.setMaximumHeight(80)

        # page 0: 服务器列表（单选钮组）
        self._repo_radio_group = QButtonGroup(self)
        self._repo_radio_group.setExclusive(True)
        self._repo_radio_group.buttonClicked.connect(self._on_repo_server_selected)
        self._repo_radio_map = {}  # id -> (remote_path, basename)

        self.repo_server_scroll = QScrollArea()
        self.repo_server_scroll.setWidgetResizable(True)
        self.repo_server_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.repo_server_container = QWidget()
        self.repo_server_layout = QVBoxLayout(self.repo_server_container)
        self.repo_server_layout.setContentsMargins(0, 0, 0, 0)
        self.repo_server_layout.setSpacing(2)
        self.repo_server_layout.addStretch()
        self.repo_server_scroll.setWidget(self.repo_server_container)
        self.repo_content_stack.addWidget(self.repo_server_scroll)

        # page 1: 本地上传（支持拖拽）
        upload_page = DropUploadWidget()
        upload_page.file_dropped.connect(self._on_repo_file_dropped)
        upload_col = QVBoxLayout(upload_page)
        upload_col.setContentsMargins(0, 2, 0, 2)
        upload_col.setSpacing(2)
        # 按钮左对齐
        self.repo_upload_btn = QPushButton("📁 选择 .repo 文件")
        self.repo_upload_btn.setStyleSheet("""
            QPushButton { background: white; color: #6b7a7f; border: 1px solid #c8d0d8;
                          border-radius: 4px; padding: 6px 14px; font-size: 12px; }
            QPushButton:hover { background: #f0f3f5; }
        """)
        upload_col.addWidget(self.repo_upload_btn, alignment=Qt.AlignLeft)
        # 拖拽提示 + 文件信息
        self.repo_upload_label = QLabel("支持拖拽 .repo 文件到此处")
        self.repo_upload_label.setStyleSheet("font-size: 12px; color: #b2bec3; background: transparent;")
        upload_col.addWidget(self.repo_upload_label, alignment=Qt.AlignLeft)
        upload_col.addStretch()
        self.repo_content_stack.addWidget(upload_page)

        rl.addWidget(self.repo_content_stack)

        repo_hint = QLabel("提示：服务器 repo 单选，本地上传重复上传以最后一次为准")
        repo_hint.setStyleSheet("font-size: 11px; color: #b2bec3; background: transparent;")
        rl.addWidget(repo_hint)

        layout.addWidget(repo_card)

        # ── 2. 操作按钮条 ──
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)

        self.btn_client_import = QPushButton("📥 导入 Excel")
        self.btn_client_add = QPushButton("+ 手动添加")
        self.btn_client_delete = QPushButton("🗑 删除选中")
        self.cb_client_system_filter = QComboBox()
        self.cb_client_system_filter.addItem("按系统勾选 ▼", "")
        self.cb_client_system_filter.setMinimumWidth(160)

        for btn in (self.btn_client_import, self.btn_client_add, self.btn_client_delete):
            btn.setStyleSheet("""
                QPushButton { background: white; color: #6b7a7f; border: 1px solid #c8d0d8;
                              border-radius: 4px; padding: 6px 14px; font-size: 12px; }
                QPushButton:hover { background: #f0f3f5; }
            """)


        action_bar.addWidget(self.btn_client_import)
        action_bar.addWidget(self.btn_client_add)
        action_bar.addWidget(self.btn_client_delete)
        action_bar.addStretch()
        action_bar.addWidget(self.cb_client_system_filter)
        layout.addLayout(action_bar)

        # ── 3. 客户端列表表格 ──
        self.client_table = QTreeWidget()
        self.client_table.setColumnCount(9)
        self.client_table.setHeaderLabels([
            "", "IP 地址", "端口", "用户名", "系统类型", "版本", "yum 状态", "YUM 路径", "连接状态"
        ])
        self.client_table.setRootIsDecorated(False)
        self.client_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.client_table.setAnimated(True)
        chk_header = CheckboxHeader()
        self.client_table.setHeader(chk_header)
        chk_header.toggled.connect(self._on_select_all_toggled)
        chk_header.setStretchLastSection(False)
        chk_header.setDefaultAlignment(Qt.AlignCenter)
        chk_header.setSectionResizeMode(0, QHeaderView.Fixed)
        chk_header.resizeSection(0, 30)
        chk_header.resizeSection(1, 140)
        chk_header.resizeSection(2, 60)
        chk_header.resizeSection(3, 100)
        chk_header.resizeSection(4, 100)
        chk_header.resizeSection(5, 80)
        chk_header.resizeSection(6, 100)
        chk_header.setSectionResizeMode(7, QHeaderView.Stretch)
        chk_header.setSectionResizeMode(8, QHeaderView.Fixed)
        chk_header.resizeSection(8, 98)
        self.client_table.setStyleSheet("""
            QTreeWidget { border: 1px solid #e0e0e0; border-radius: 4px;
                          background: white; font-size: 12px; }
            QTreeWidget::item { padding: 4px 6px; border-bottom: 1px solid #f5f5f5; }
            QTreeWidget::item:selected { background: transparent; }
        """)
        layout.addWidget(self.client_table, 1)

        # ── 4. 底部按钮 ──
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        self.btn_client_detect = QPushButton("🔄 检测选中客户端")
        self.btn_client_detect.setStyleSheet("""
            QPushButton { background: #0984e3; color: white; border: none;
                          border-radius: 4px; padding: 8px 24px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background: #0873c4; }
            QPushButton:disabled { background: #b2bec3; color: #dfe6e9; }
        """)
        self.btn_client_deploy = QPushButton("🚀 部署到选中客户端")
        self.btn_client_deploy.setStyleSheet("""
            QPushButton { background: #27ae60; color: white; border: none;
                          border-radius: 4px; padding: 8px 24px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background: #1e914f; }
            QPushButton:disabled { background: #b2bec3; color: #dfe6e9; }
        """)
        self.btn_client_deploy.setEnabled(False)
        self.btn_client_detect.setEnabled(False)
        bottom_row.addWidget(self.btn_client_detect)
        bottom_row.addSpacing(12)
        bottom_row.addWidget(self.btn_client_deploy)
        bottom_row.addStretch()
        layout.addLayout(bottom_row)

        return page

    # ----------------------------------------------------------
    #  信号连接
    # ----------------------------------------------------------
    def _connect_signals(self):
        self.nav_group.idClicked.connect(self._switch_tab)
        self.local_iso_list.itemChanged.connect(self._on_local_iso_toggled)
        self.btn_local_exec.clicked.connect(self._on_exec_local)
        self.btn_local_cancel.clicked.connect(self._on_cancel)
        self.btn_web_exec.clicked.connect(self._on_exec_web)
        self.btn_add_exec.clicked.connect(self._on_exec_web_add)
        self.btn_add_dl_local.clicked.connect(self._on_download_repos)

        # 客户端页面信号
        self.repo_source_server.toggled.connect(self._on_repo_source_changed)
        self.repo_source_upload.toggled.connect(self._on_repo_source_changed)
        self.repo_upload_btn.clicked.connect(self._on_repo_upload)
        self.btn_client_import.clicked.connect(self._on_client_import_excel)
        self.btn_client_add.clicked.connect(self._on_client_manual_add)
        self.btn_client_delete.clicked.connect(self._on_client_delete)
        self.client_table.itemClicked.connect(
            lambda item, col: self._update_client_action_buttons())
        self.cb_client_system_filter.currentIndexChanged.connect(self._on_client_system_filter)
        self.btn_client_detect.clicked.connect(self._on_client_detect)
        self.btn_client_deploy.clicked.connect(self._on_client_deploy)

        self.executor.log.connect(lambda level, msg: self._log(f"[{level}] {msg}"))
        self.executor.progress.connect(self._on_progress)
        self.executor.step.connect(self._log)
        self.executor.finished_signal.connect(self._on_exec_finished)

        # 初始化客户端页面状态（setChecked 触发时信号还没连上，这里补一次）
        self._on_repo_source_changed()

    # ----------------------------------------------------------
    #  客户端 — Repo 来源切换
    # ----------------------------------------------------------
    def _on_repo_source_changed(self):
        server_mode = self.repo_source_server.isChecked()
        self.repo_content_stack.setCurrentIndex(0 if server_mode else 1)
        if server_mode:
            self._refresh_repo_server_list()
        else:
            # 切换到本地上传时取消服务器 repo 选中
            self._repo_radio_group.setExclusive(False)
            for rb in self._repo_radio_group.buttons():
                rb.setChecked(False)
            self._repo_radio_group.setExclusive(True)
            self._selected_repo_content = ""
            self._selected_repo_name = ""
            self._update_client_action_buttons()

    def _refresh_repo_server_list(self):
        # 清除所有旧控件（单选按钮 + 提示标签）
        for rb in self._repo_radio_group.buttons():
            self._repo_radio_group.removeButton(rb)
        while self.repo_server_layout.count() > 1:  # 保留最后的 stretch
            item = self.repo_server_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._repo_radio_map.clear()

        if self.ssh_manager.connected:
            ok, out = self.ssh_manager.exec_command(f"ls {YUM_REPO_DIR}/*.repo 2>/dev/null")
            if ok and out.strip():
                for idx, line in enumerate(out.strip().split('\n')):
                    path = line.strip()
                    if path:
                        rb = QRadioButton(os.path.basename(path))
                        rb.setStyleSheet("QRadioButton { font-size: 12px; color: #2d3436; }")
                        self._repo_radio_group.addButton(rb, idx)
                        self._repo_radio_map[idx] = (path, os.path.basename(path))
                        # 插入到 stretch 之前
                        self.repo_server_layout.insertWidget(
                            self.repo_server_layout.count() - 1, rb)
            else:
                # 无文件时显示提示
                lbl = QLabel("（无可用 .repo 文件）")
                lbl.setStyleSheet("font-size: 12px; color: #b2bec3;")
                self.repo_server_layout.insertWidget(
                    self.repo_server_layout.count() - 1, lbl)

    def _on_repo_server_selected(self, button):
        rid = self._repo_radio_group.id(button)
        if rid < 0 or rid not in self._repo_radio_map:
            self._selected_repo_content = ""
            self._selected_repo_name = ""
        else:
            remote_path, name = self._repo_radio_map[rid]
            if self.ssh_manager.connected:
                ok, out = self.ssh_manager.exec_command(f"cat '{remote_path}'")
                if ok:
                    self._selected_repo_content = out
                    self._selected_repo_name = name
                    self._log(f"📄 已选择 repo: {name}")
                else:
                    self._selected_repo_content = ""
                    self._selected_repo_name = ""
                    self._log(f"❌ 读取 {remote_path} 失败")
        self._update_client_action_buttons()

    def _load_repo_file(self, path: str):
        """读取 .repo 文件内容"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._selected_repo_content = f.read()
            self._selected_repo_name = os.path.basename(path)
            self.repo_upload_label.setText(f"已选择: {self._selected_repo_name}")
            self.repo_upload_label.setStyleSheet("font-size: 12px; color: #27ae60;")
            self._log(f"📄 已上传 repo: {self._selected_repo_name}")
        except Exception as e:
            self._selected_repo_content = ""
            self._selected_repo_name = ""
            self.repo_upload_label.setText(f"读取失败: {e}")
            self.repo_upload_label.setStyleSheet("font-size: 12px; color: #d63031;")
        self._update_client_action_buttons()

    def _on_repo_upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 .repo 文件", "", "repo 文件 (*.repo);;所有文件 (*)"
        )
        if not path:
            return
        self._load_repo_file(path)

    def _on_repo_file_dropped(self, path: str):
        """拖拽文件后的回调"""
        self.repo_source_upload.setChecked(True)
        self._on_repo_source_changed()
        if not path.lower().endswith('.repo'):
            self.repo_upload_label.setText("仅支持 .repo 文件")
            self.repo_upload_label.setStyleSheet("font-size: 12px; color: #d63031;")
            return
        self._load_repo_file(path)

    # ----------------------------------------------------------
    #  客户端 — 导入 / 添加 / 删除
    # ----------------------------------------------------------
    def _on_client_import_excel(self):
        if not HAS_OPENPYXL:
            QMessageBox.warning(self, "提示", "请先安装 openpyxl:\npip install openpyxl")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 Excel", "", "Excel 文件 (*.xlsx *.xls);;所有文件 (*)"
        )
        if not path:
            return
        try:
            wb = openpyxl.load_workbook(path)
            ws = wb.active
            if not ws:
                QMessageBox.warning(self, "提示", "Excel 文件为空")
                return
            added = 0
            skipped = 0
            detect_targets = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or not row[0]:
                    continue
                host = str(row[0]).strip()
                port = int(row[1]) if len(row) > 1 and row[1] else 22
                user = str(row[2]).strip() if len(row) > 2 and row[2] else "root"
                pwd = str(row[3]) if len(row) > 3 and row[3] else ""
                if not host:
                    continue
                if self._client_ip_exists(host):
                    skipped += 1
                    continue
                self._add_client_row(host, port, user)
                row_idx = self.client_table.topLevelItemCount() - 1
                self._client_passwords[host] = pwd
                self.client_table.topLevelItem(row_idx).setCheckState(0, Qt.Checked)
                detect_targets.append((row_idx, host, port, user, pwd))
                added += 1
            self._log(f"📥 已导入 {added} 个客户端{'，跳过 ' + str(skipped) + ' 个重复 IP' if skipped else ''}，开始自动检测...")
            self._update_client_action_buttons()
            self._refresh_system_filter()
            self._start_detection(detect_targets)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _on_client_manual_add(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("手动添加客户端")
        dialog.setMinimumWidth(380)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        fields = {}
        for label, key, default, echo in [
            ("IP 地址", "ip", "", False),
            ("端口", "port", "22", False),
            ("用户名", "user", "root", False),
            ("密码", "pwd", "", True),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label, styleSheet="font-size: 12px; color: #636e72; min-width: 60px;"))
            le = QLineEdit(default)
            le.setStyleSheet("QLineEdit { border: 1px solid #dfe6e9; border-radius: 4px; padding: 6px 8px; font-size: 12px; }")
            if echo:
                le.setEchoMode(QLineEdit.Password)
            row.addWidget(le, 1)
            fields[key] = le
            layout.addLayout(row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet("QPushButton { background: #0984e3; color: white; border: none; border-radius: 4px; padding: 6px 20px; font-size: 12px; } QPushButton:hover { background: #0873c4; }")
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("QPushButton { background: white; color: #6b7a7f; border: 1px solid #c8d0d8; border-radius: 4px; padding: 6px 20px; font-size: 12px; } QPushButton:hover { background: #f0f3f5; }")
        btn_row.addWidget(btn_ok)
        btn_row.addSpacing(8)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        def on_ok():
            ip = fields["ip"].text().strip()
            if not ip:
                QMessageBox.warning(dialog, "提示", "IP 地址不能为空")
                return
            if self._client_ip_exists(ip):
                QMessageBox.warning(dialog, "提示", f"IP {ip} 已存在列表中")
                return
            port = int(fields["port"].text().strip() or "22")
            user = fields["user"].text().strip() or "root"
            pwd = fields["pwd"].text()
            self._add_client_row(ip, port, user)
            row_idx = self.client_table.topLevelItemCount() - 1
            self._client_passwords[ip] = pwd
            self.client_table.topLevelItem(row_idx).setCheckState(0, Qt.Checked)
            self._log(f"+ 已添加客户端: {ip}，开始自动检测...")
            self._update_client_action_buttons()
            self._refresh_system_filter()
            dialog.accept()
            self._start_detection([(row_idx, ip, port, user, pwd)])

        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(dialog.reject)
        dialog.exec()

    def _on_client_delete(self):
        removed = 0
        for i in range(self.client_table.topLevelItemCount() - 1, -1, -1):
            item = self.client_table.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                ip = item.text(1)
                self._client_passwords.pop(ip, None)
                self.client_table.takeTopLevelItem(i)
                removed += 1
        if removed:
            self._log(f"🗑 已删除 {removed} 个客户端")
            self._refresh_system_filter()
            self._update_client_action_buttons()

    def _on_select_all_toggled(self, checked: bool):
        for i in range(self.client_table.topLevelItemCount()):
            self.client_table.topLevelItem(i).setCheckState(0,
                Qt.Checked if checked else Qt.Unchecked)
        self._update_client_action_buttons()

    def _client_ip_exists(self, ip: str) -> bool:
        for i in range(self.client_table.topLevelItemCount()):
            if self.client_table.topLevelItem(i).text(1) == ip:
                return True
        return False

    def _add_client_row(self, ip: str, port: int, user: str):
        item = QTreeWidgetItem()
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked)
        item.setText(1, ip)
        item.setText(2, str(port))
        item.setText(3, user)
        item.setText(4, "待检测")
        item.setText(5, "")
        item.setText(6, "⏳")
        item.setText(7, "")
        item.setText(8, "⏳")
        for col in range(9):
            item.setTextAlignment(col, Qt.AlignLeft if col == 7 else Qt.AlignCenter)
        self.client_table.addTopLevelItem(item)

    # ----------------------------------------------------------
    #  客户端 — 系统类型筛选
    # ----------------------------------------------------------
    def _refresh_system_filter(self):
        current = self.cb_client_system_filter.currentData()
        self.cb_client_system_filter.blockSignals(True)
        self.cb_client_system_filter.clear()
        self.cb_client_system_filter.addItem("按系统勾选 ▼", "")
        systems = set()
        for i in range(self.client_table.topLevelItemCount()):
            item = self.client_table.topLevelItem(i)
            os_type = item.text(4)
            ver = item.text(5)
            if os_type and os_type != "待检测" and os_type != "未知":
                key = f"{os_type} {ver}".strip()
                if key:
                    systems.add(key)
        for s in sorted(systems):
            self.cb_client_system_filter.addItem(s, s)
        # 恢复选中
        if current:
            idx = self.cb_client_system_filter.findData(current)
            if idx >= 0:
                self.cb_client_system_filter.setCurrentIndex(idx)
        self.cb_client_system_filter.blockSignals(False)

    def _on_client_system_filter(self, index):
        target = self.cb_client_system_filter.itemData(index)
        if not target:
            return
        for i in range(self.client_table.topLevelItemCount()):
            item = self.client_table.topLevelItem(i)
            os_type = item.text(4)
            ver = item.text(5)
            key = f"{os_type} {ver}".strip()
            item.setCheckState(0, Qt.Checked if key == target else Qt.Unchecked)
        self._update_client_action_buttons()

    # ----------------------------------------------------------
    #  客户端 — 检测
    # ----------------------------------------------------------
    def _on_client_detect(self):
        targets = []
        for i in range(self.client_table.topLevelItemCount()):
            item = self.client_table.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                ip = item.text(1)
                port = int(item.text(2))
                user = item.text(3)
                pwd = self._client_passwords.get(ip, "")
                targets.append((i, ip, port, user, pwd))
        if not targets:
            QMessageBox.information(self, "提示", "请先勾选要检测的客户端")
            return
        self._start_detection(targets)

    def _start_detection(self, targets: list):
        """启动检测，targets 为 [(row_idx, ip, port, user, pwd), ...]"""
        if not targets:
            return
        for ri, ip, port, user, pwd in targets:
            item = self.client_table.topLevelItem(ri)
            if item:
                item.setText(8, "⏳ 检测中...")
        self.btn_client_detect.setEnabled(False)
        self._detect_queue = list(targets)
        self._detect_active = 0
        self._detect_max = 5
        self._detect_threads = []
        self._launch_detect()

    def _launch_detect(self):
        while self._detect_active < self._detect_max and self._detect_queue:
            row_idx, ip, port, user, pwd = self._detect_queue.pop(0)
            t = ClientDetectThread(ip, port, user, pwd)
            t.result.connect(lambda ip2, ot, ver, yum_ok, url, url_t, conn: self._on_detect_done(ip2, ot, ver, yum_ok, url, url_t, conn))
            self._detect_threads.append(t)
            self._detect_active += 1
            t.start()

    def _on_detect_done(self, ip: str, os_type: str, version: str, yum_ok: bool, yum_url: str, url_type: str, connected: bool):
        self._detect_active -= 1
        for i in range(self.client_table.topLevelItemCount()):
            item = self.client_table.topLevelItem(i)
            if item.text(1) == ip:
                item.setText(4, os_type)
                item.setText(5, version)
                item.setText(6, "🟢" if yum_ok else "🔴")
                item.setText(7, f"{url_type} {yum_url}" if url_type else yum_url)
                item.setText(8, "✅" if connected else "❌")
                break

        if connected:
            self._log(f"🌐 {ip} → {os_type} {version}, yum: {'🟢' if yum_ok else '🔴'}, 源: {url_type or '无'}")
        else:
            self._log(f"❌ {ip} → 连接失败")

        if self._detect_queue or self._detect_active > 0:
            self._launch_detect()
        else:
            self._log("✅ 客户端检测完成")
            self._refresh_system_filter()
            self._update_client_action_buttons()
            self.btn_client_detect.setEnabled(True)

    # ----------------------------------------------------------
    #  客户端 — 部署
    # ----------------------------------------------------------
    def _on_client_deploy(self):
        if not self._selected_repo_content:
            QMessageBox.warning(self, "提示", "请先选择一个 .repo 文件")
            return

        targets = []
        for i in range(self.client_table.topLevelItemCount()):
            item = self.client_table.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                ip = item.text(1)
                port = int(item.text(2))
                user = item.text(3)
                pwd = self._client_passwords.get(ip, "")
                targets.append((ip, port, user, pwd))

        if not targets:
            QMessageBox.information(self, "提示", "请先勾选要部署的客户端")
            return

        iso_dir = os.path.splitext(self._selected_repo_name)[0]
        self._log(f"🚀 开始部署到 {len(targets)} 个客户端（5 并发）...")

        self.btn_client_deploy.setEnabled(False)
        self.btn_client_detect.setEnabled(False)

        self._deploy_pool = ClientDeployPool(
            targets, self._selected_repo_content, iso_dir, self
        )
        self._deploy_pool.one_finished.connect(self._on_deploy_one_done)
        self._deploy_pool.all_finished.connect(self._on_deploy_all_done)
        self._deploy_pool.start()

    def _on_deploy_one_done(self, ip: str, success: bool, msg: str):
        icon = "✅" if success else "❌"
        self._log(f"  {icon} {ip}: {msg}")
        for i in range(self.client_table.topLevelItemCount()):
            item = self.client_table.topLevelItem(i)
            if item.text(1) == ip:
                item.setText(6, "🟢" if success else "🔴")
                item.setText(8, "✅" if success else "❌")
                break

    def _on_deploy_all_done(self):
        self._log("✅ 客户端部署全部完成")
        self._update_client_action_buttons()
        self.btn_client_deploy.setEnabled(bool(self._selected_repo_content))
        self.btn_client_detect.setEnabled(True)

    # ----------------------------------------------------------
    #  客户端 — 按钮状态
    # ----------------------------------------------------------
    def _update_client_action_buttons(self):
        has_repo = bool(self._selected_repo_content)
        has_checked = any(
            self.client_table.topLevelItem(i).checkState(0) == Qt.Checked
            for i in range(self.client_table.topLevelItemCount())
        )
        self.btn_client_deploy.setEnabled(has_repo and has_checked)
        self.btn_client_detect.setEnabled(has_checked)

    # ----------------------------------------------------------
    #  ISO 刷新
    # ----------------------------------------------------------
    def _refresh_isos(self):
        """刷新当前活跃表单的 ISO 列表"""
        idx = self.srv_stack.currentIndex()
        if idx == 0:
            self._refresh_local_isos()
        elif idx == 1:
            self._refresh_web_isos()
        else:
            self._refresh_add_isos()

    def _populate_iso_list(self, tree: QTreeWidget, isos: List[dict],
                           distro_info: Optional[dict] = None,
                           show_match: bool = True):
        tree.blockSignals(True)
        tree.clear()
        cols = 3 if not show_match else 4
        if distro_info is None:
            distro_info = self.ssh_manager.get_cached_distro() if self.ssh_manager.connected else self.distro_info
        for iso in isos:
            item = QTreeWidgetItem()
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setText(1, iso['name'])
            item.setText(2, iso['size_str'])
            item.setData(0, Qt.UserRole, iso['path'])
            item.setToolTip(1, iso['path'])

            if show_match:
                match_ok, match_desc = self.detector.match_iso(iso['name'], distro_info)
                if match_desc == "版本匹配":
                    icon, color = "✅", '#27ae60'
                elif match_desc == "版本不匹配":
                    icon, color = "⚠️", '#f39c12'
                elif match_desc == "发行版不匹配":
                    icon, color = "❌", '#d63031'
                else:
                    icon, color = "❓", '#b2bec3'
                item.setText(3, f"{icon} {match_desc}")
                if color != '#b2bec3':
                    for col in range(4):
                        item.setForeground(col, QColor(color))

            tree.addTopLevelItem(item)
        tree.blockSignals(False)

    # ----------------------------------------------------------
    #  执行 - 本地源
    # ----------------------------------------------------------
    def _write_repo_file(self, path: str, content: str):
        """用 Python 直接写入 .repo 文件（绕过 shell heredoc）"""
        if self.ssh_manager.connected:
            err = self.ssh_manager.write_file(path, content)
            if err:
                self._log(f"❌ 写入 {path} 失败: {err}")
            else:
                self._log(f"  📄 已写入: {path}")
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            self._log(f"  📄 已写入: {path}")

    def _on_exec_local(self):
        self.log_box.clear()

        if self.lbl_yum_status.text() == "yum 源: 正常":
            QMessageBox.information(self, "提示", "yum 源正常，无需创建")
            return

        selected = self._get_selected_isos(self.local_iso_list)
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择一个 ISO 镜像文件")
            return

        mount_path = (self.local_mount_path.text().strip() or HTTP_DIR).rstrip("/")
        iso_path = selected[0]
        iso_name = os.path.basename(iso_path)
        iso_dir = os.path.splitext(iso_name)[0].replace('\r', '')
        http_target = f"{mount_path}/{iso_dir}"
        repo_file = f"{YUM_REPOS_DIR}/{iso_dir}.repo"

        # 检查目标目录是否已存在
        if self.ssh_manager.connected:
            ok, _ = self.ssh_manager.exec_command(f"test -d '{http_target}'")
            dir_exists = ok
        else:
            dir_exists = os.path.isdir(http_target)
        if dir_exists:
            self._log(f"  📁 目标目录 {http_target} 已存在，跳过挂载和复制")

        # 备份全部已有 .repo 文件（移动到备份目录，只剩新文件）
        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        if self.ssh_manager.connected:
            self.ssh_manager.exec_command(
                f"mkdir -p '{YUM_REPOS_DIR}/bak_{ts}' && "
                f"mv {YUM_REPOS_DIR}/*.repo '{YUM_REPOS_DIR}/bak_{ts}/' 2>/dev/null || true"
            )
        else:
            bak_dir = f"{YUM_REPOS_DIR}/bak_{ts}"
            os.makedirs(bak_dir, exist_ok=True)
            for f in glob.glob(f"{YUM_REPOS_DIR}/*.repo"):
                shutil.move(f, bak_dir)

        # 根据 ISO 文件名判断目录结构（而非服务器自身 distro）
        needs_as = self._iso_has_appstream(iso_name)

        base = f"file://{http_target}/BaseOS" if needs_as else f"file://{http_target}"
        repo_content = f"[LocalRepo_BaseOS]\nname=LocalRepository_BaseOS\nbaseurl={base}\nenabled=1\ngpgcheck=0\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n"
        if needs_as:
            repo_content += f"\n[LocalRepo_AppStream]\nname=LocalRepository_AppStream\nbaseurl=file://{http_target}/AppStream\nenabled=1\ngpgcheck=0\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n"

        self._write_repo_file(repo_file, repo_content)

        if dir_exists:
            tasks = [
                ("检测 yum 可用性", "yum clean all 2>/dev/null; yum makecache 2>&1; yum install -y --downloadonly chrony 2>&1"),
            ]
        else:
            tasks = self._build_local_tasks(iso_path, iso_name, iso_dir, http_target)
        self._start_execution(tasks)

    def _build_local_tasks(self, iso_path: str, iso_name: str, iso_dir: str,
                           http_target: str = None) -> List[Tuple[str, str]]:
        mount_dir = f"{MOUNT_BASE}/{iso_dir}".replace('\r', '')
        http_target = (http_target or f"{HTTP_DIR}/{iso_dir}").replace('\r', '')

        tasks = []

        _danger = {'/', '/root', '/etc', '/usr', '/var', '/home', '/boot', '/opt', '/tmp'}
        http_target_clean = http_target.rstrip('/') if http_target else ''
        if http_target_clean in _danger:
            return [("❌ 危险路径", f"echo '错误: 目标路径 {http_target} 为系统关键目录，已拒绝执行' && exit 1")]

        tasks.append(("检查 ISO 文件", f"test -f '{iso_path}'"))
        tasks.append(("强制清理已有挂载", f"umount -fl '{mount_dir}' 2>/dev/null || true"))
        tasks.append(("创建挂载点", f"mkdir -p '{mount_dir}'"))
        tasks.append(("清空并创建 HTTP 目录", f"rm -rf '{http_target}' && mkdir -p '{http_target}'"))
        tasks.append((f"挂载 ISO: {iso_name}", f"mount -o loop '{iso_path}' '{mount_dir}'"))
        tasks.append(("检查挂载状态", f"mount | grep -q '{iso_name}'"))
        tasks.append((f"复制系统文件到 {http_target}", f"cp -rpf '{mount_dir}/'* '{http_target}'"))
        tasks.append(("卸载 ISO", f"umount '{mount_dir}' 2>/dev/null || true"))
        tasks.append(("检测 yum 可用性", "yum clean all 2>/dev/null; yum makecache 2>&1; yum install -y --downloadonly chrony 2>&1"))

        return tasks

    # ----------------------------------------------------------
    #  执行 - Web 源
    # ----------------------------------------------------------
    @staticmethod
    def _iso_has_appstream(iso_name: str) -> bool:
        """通过 ISO 文件名判断是否包含 BaseOS/AppStream 子目录"""
        name = iso_name.lower()
        if not any(k in name for k in ('rhel', 'red hat', 'centos', 'rocky', 'alma', 'oracle')):
            return False
        m = re.search(r'[-.](\d+)\.', name)
        if m:
            return int(m.group(1)) >= 8
        return True

    def _on_exec_web(self):
        self.log_box.clear()
        self._http_urls = []
        if not self.ssh_manager.connected:
            QMessageBox.warning(self, "提示", "SSH 未连接，请先连接服务器")
            return
        self._log("⏳ 正在检查环境...")
        self._check_web_environment()
        QApplication.processEvents()

        selected = self._get_selected_isos(self.web_iso_list)
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择至少一个 ISO 镜像文件")
            return

        http_ip = self.cb_ip.currentText().strip()
        if not http_ip:
            QMessageBox.warning(self, "提示", "请输入 HTTP 地址")
            return

        tasks = []
        self._generated_repos = []

        if self.ssh_manager.connected:
            self.ssh_manager.exec_command(f"mkdir -p '{YUM_REPO_DIR}' 2>/dev/null || true")

        for i, iso_path in enumerate(selected):
            iso_name = os.path.basename(iso_path)
            iso_dir = os.path.splitext(iso_name)[0].replace('\r', '')
            mount_dir = f"{MOUNT_BASE}/{iso_dir}"
            http_target = f"{HTTP_DIR}/{iso_dir}"
            has_as = self._iso_has_appstream(iso_name)

            if http_target.rstrip('/') in {'/', '/root', '/etc', '/usr', '/var', '/home', '/boot', '/opt', '/tmp'}:
                tasks.append(("❌ 危险路径", f"echo '错误: 目标路径危险' && exit 1"))
                continue

            # 目标目录已存在则跳过挂载复制
            if self.ssh_manager.connected:
                ok, _ = self.ssh_manager.exec_command(f"test -d '{http_target}'")
                dir_exists = ok
            else:
                dir_exists = os.path.isdir(http_target)
            if dir_exists:
                self._log(f"  📁 {http_target} 已存在，跳过挂载和复制")

            if dir_exists:
                # 已存在 → 不需要 mount/copy 任务
                pass
            elif i == 0:
                tasks.append(("检查 ISO 文件", f"test -f '{iso_path}'"))
                tasks.append(("强制清理已有挂载", f"umount -fl '{mount_dir}' 2>/dev/null || true"))
                tasks.append(("创建挂载点", f"mkdir -p '{mount_dir}'"))
                tasks.append(("清空并创建 HTTP 目录", f"rm -rf '{http_target}' && mkdir -p '{http_target}'"))
                tasks.append((f"挂载 ISO: {iso_name}", f"mount -o loop '{iso_path}' '{mount_dir}'"))
                tasks.append(("检查挂载状态", f"mount | grep -q '{iso_name}'"))
                tasks.append(("复制系统文件（约 1-3 分钟，请等待）...", f"cp -rpf '{mount_dir}/'* '{http_target}'"))
                tasks.append(("卸载 ISO", f"umount '{mount_dir}' 2>/dev/null || true"))
            else:
                tasks.append((f"强制清理已有挂载: {iso_dir}", f"umount -fl '{mount_dir}' 2>/dev/null || true"))
                tasks.append((f"创建挂载点: {iso_dir}", f"mkdir -p '{mount_dir}'"))
                tasks.append((f"清空并创建 HTTP 目录: {iso_dir}", f"rm -rf '{http_target}' && mkdir -p '{http_target}'"))
                tasks.append((f"挂载 ISO: {iso_name}", f"mount -o loop '{iso_path}' '{mount_dir}'"))
                tasks.append((f"检查挂载: {iso_name}", f"mount | grep -q '{iso_name}'"))
                tasks.append(("复制（约 1-3 分钟，请等待）...", f"cp -rpf '{mount_dir}/'* '{http_target}'"))
                tasks.append((f"卸载 ISO: {iso_name}", f"umount '{mount_dir}' 2>/dev/null || true"))

            # 客户端 repo（http://，写入 /opt/tar/yum.repo/，覆盖旧文件）
            if has_as:
                baseurl = f"http://{http_ip}/{iso_dir}/BaseOS"
                baseurl_as = f"http://{http_ip}/{iso_dir}/AppStream"
            else:
                baseurl = f"http://{http_ip}/{iso_dir}"
                baseurl_as = baseurl

            repo_content = f"[LocalRepo_BaseOS]\nname=LocalRepository_BaseOS\nbaseurl={baseurl}\nenabled=1\ngpgcheck=0\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n"
            if has_as:
                repo_content += f"\n[LocalRepo_AppStream]\nname=LocalRepository_AppStream\nbaseurl={baseurl_as}\nenabled=1\ngpgcheck=0\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n"

            client_repo = f"{iso_dir}.repo"
            repo_path = f"{YUM_REPO_DIR}/{client_repo}" if self.ssh_manager.connected else os.path.join(os.getcwd(), client_repo)
            self._write_repo_file(repo_path, repo_content)
            self._generated_repos.append(repo_path)
            if i == 0:
                self._http_urls.append(f"http://{http_ip}/{iso_dir}")

        # 安装 httpd
        tasks.append(("安装 httpd", "yum install -y httpd"))
        tasks.append(("启动 httpd", "systemctl restart httpd && systemctl enable httpd"))

        info = self.ssh_manager.get_cached_distro() if self.ssh_manager.connected else self.distro_info
        if info.get('is_rhel'):
            tasks.append(("屏蔽 RHEL 未注册提示",
                'for f in /etc/yum/pluginconf.d/product-id.conf /etc/yum/pluginconf.d/subscription-manager.conf; do '
                'if [ -f "$f" ]; then sed -i "s/^enabled=1/enabled=0/" "$f"; fi; done'))

        self._start_execution(tasks)

    # ----------------------------------------------------------
    #  执行控制
    # ----------------------------------------------------------
    def _start_execution(self, tasks: List[Tuple[str, str]]):
        self._set_ui_enabled(False)
        self._log("开始执行部署...")
        mode = "远程" if self.ssh_manager.connected else "本地"
        info = self.ssh_manager.get_cached_distro() if self.ssh_manager.connected else self.distro_info
        self._log(f"系统: {info.get('pretty_name', 'Unknown')} ({mode})")
        self._log(f"共 {len(tasks)} 个步骤")

        self.executor.set_tasks(tasks)
        self.executor.set_ssh(self.ssh_manager if self.ssh_manager.connected else None)
        self.executor.start()

    def _on_exec_finished(self, success: bool):
        self._set_ui_enabled(True)
        self.local_progress.setValue(0)
        self.web_progress.setValue(0)
        self.add_progress.setValue(0)
        if success:
            self._log("✅ 全部任务执行完成")
            self._refresh_yum_status()
            QTimer.singleShot(2000, self._check_web_environment)

            if self._http_urls:
                urls_str = "\n".join(self._http_urls)
                dlg = QDialog(self)
                dlg.setWindowTitle("部署成功")
                dlg.setMinimumWidth(600)
                layout = QVBoxLayout(dlg)
                layout.setSpacing(16)
                layout.addWidget(QLabel(
                    f"Web yum 源已就绪\n\n{urls_str}\n\n.repo 文件已保存到 /opt/tar/yum.repo/",
                    styleSheet="font-size: 13px;"))
                btn = QPushButton("确定")
                btn.setStyleSheet("""
                    QPushButton { background: #0984e3; color: white; border: none;
                                  border-radius: 4px; padding: 6px 30px; font-size: 12px; }
                    QPushButton:hover { background: #0873c4; }
                """)
                btn.clicked.connect(dlg.accept)
                row = QHBoxLayout()
                row.addStretch()
                row.addWidget(btn)
                layout.addLayout(row)
                dlg.exec()

            if self._generated_repos:
                self._log(f"✅ 已生成 {len(self._generated_repos)} 个客户端 .repo 文件")
        else:
            self._log("❌ 部署失败，请检查日志")

    def _on_exec_web_add(self):
        self.log_box.clear()
        self._http_urls = []
        if not self.ssh_manager.connected:
            QMessageBox.warning(self, "提示", "SSH 未连接，请先连接服务器")
            return
        self._log("⏳ 正在检查环境...")
        self._check_web_environment()
        QApplication.processEvents()

        selected = self._get_selected_isos(self.add_iso_list)
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择至少一个 ISO 镜像文件")
            return

        http_ip = self.add_cb_ip.currentText().strip() or self.cb_ip.currentText().strip()
        if not http_ip:
            QMessageBox.warning(self, "提示", "无法获取 HTTP 地址，请先在「创建 Webyum 源」中设置")
            return

        tasks = []
        self._generated_repos = []

        if self.ssh_manager.connected:
            self.ssh_manager.exec_command(f"mkdir -p '{YUM_REPO_DIR}' 2>/dev/null || true")

        for iso_path in selected:
            iso_name = os.path.basename(iso_path)
            iso_dir = os.path.splitext(iso_name)[0].replace('\r', '')
            mount_dir = f"{MOUNT_BASE}/{iso_dir}"
            http_target = f"{HTTP_DIR}/{iso_dir}"
            has_as = self._iso_has_appstream(iso_name)

            if http_target.rstrip('/') in {'/', '/root', '/etc', '/usr', '/var', '/home', '/boot', '/opt', '/tmp'}:
                tasks.append(("❌ 危险路径", f"echo '错误: 目标路径危险' && exit 1"))
                continue

            # 目录已存在则跳过挂载复制
            if self.ssh_manager.connected:
                ok, _ = self.ssh_manager.exec_command(f"test -d '{http_target}'")
                if ok:
                    self._log(f"  📁 {http_target} 已存在，跳过挂载和复制")
                else:
                    tasks.append((f"强制清理已有挂载: {iso_dir}", f"umount -fl '{mount_dir}' 2>/dev/null || true"))
                    tasks.append((f"创建挂载点: {iso_dir}", f"mkdir -p '{mount_dir}'"))
                    tasks.append((f"清空并创建 HTTP 目录: {iso_dir}", f"rm -rf '{http_target}' && mkdir -p '{http_target}'"))
                    tasks.append((f"挂载 ISO: {iso_name}", f"mount -o loop '{iso_path}' '{mount_dir}'"))
                    tasks.append((f"检查挂载: {iso_name}", f"mount | grep -q '{iso_name}'"))
                    tasks.append(("复制（约 1-3 分钟，请等待）...", f"cp -rpf '{mount_dir}/'* '{http_target}'"))
                    tasks.append((f"卸载 ISO: {iso_name}", f"umount '{mount_dir}' 2>/dev/null || true"))

            # 客户端 repo（http://，写入 /opt/tar/yum.repo/，覆盖旧文件）
            client_repo = f"{iso_dir}.repo"
            if has_as:
                baseurl = f"http://{http_ip}/{iso_dir}/BaseOS"
                baseurl_as = f"http://{http_ip}/{iso_dir}/AppStream"
            else:
                baseurl = f"http://{http_ip}/{iso_dir}"
                baseurl_as = baseurl

            repo_content = f"[LocalRepo_BaseOS]\nname=LocalRepository_BaseOS\nbaseurl={baseurl}\nenabled=1\ngpgcheck=0\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n"
            if has_as:
                repo_content += f"\n[LocalRepo_AppStream]\nname=LocalRepository_AppStream\nbaseurl={baseurl_as}\nenabled=1\ngpgcheck=0\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n"

            repo_path = f"{YUM_REPO_DIR}/{client_repo}" if self.ssh_manager.connected else os.path.join(os.getcwd(), client_repo)
            self._write_repo_file(repo_path, repo_content)
            self._generated_repos.append(repo_path)
            self._http_urls.append(f"http://{http_ip}/{iso_dir}")

        self._start_execution(tasks)

    def _on_cancel(self):
        self.executor.cancel()

    def _on_progress(self, value: int):
        form_idx = self.srv_stack.currentIndex()
        if form_idx == 0:
            self.local_progress.setValue(value)
        elif form_idx == 1:
            self.web_progress.setValue(value)
        else:
            self.add_progress.setValue(value)

    def _set_ui_enabled(self, enabled: bool):
        self.btn_local_exec.setEnabled(enabled)
        self.btn_local_cancel.setEnabled(not enabled)
        self.btn_web_exec.setEnabled(enabled and self._env_port_ok)
        self.btn_add_exec.setEnabled(enabled and self._is_add_env_ok())
        self.btn_add_dl_local.setEnabled(enabled)
        self.btn_server_tab.setEnabled(enabled)
        self.btn_client_tab.setEnabled(enabled)
        self.btn_srv_local.setEnabled(enabled)
        self.btn_srv_web.setEnabled(enabled)
        self.btn_srv_web_add.setEnabled(enabled)
        self.local_iso_list.setEnabled(enabled)
        self.web_iso_list.setEnabled(enabled and self._env_port_ok)
        self.add_iso_list.setEnabled(enabled)
        self.local_mount_path.setEnabled(enabled)
        self.local_iso_dir.setEnabled(enabled)
        self.web_iso_dir.setEnabled(enabled)
        self.add_iso_dir.setEnabled(enabled)
        self.btn_local_refresh.setEnabled(enabled)
        self.btn_web_refresh.setEnabled(enabled)
        self.btn_add_refresh.setEnabled(enabled)
        self.cb_ip.setEnabled(enabled)
        self.add_cb_ip.setEnabled(enabled)
        self.btn_ssh_toggle.setEnabled(enabled)

        # 进度条显示/隐藏
        show_progress = not enabled
        self.local_progress.setVisible(show_progress and self.srv_stack.currentIndex() == 0)
        self.web_progress.setVisible(show_progress and self.srv_stack.currentIndex() == 1)
        self.add_progress.setVisible(show_progress and self.srv_stack.currentIndex() == 2)

    # ----------------------------------------------------------
    #  下载 .repo 文件
    # ----------------------------------------------------------
    def _on_download_repos(self):
        if not self._generated_repos:
            if self.ssh_manager.connected:
                ok, out = self.ssh_manager.exec_command(f"ls {YUM_REPO_DIR}/*.repo 2>/dev/null")
                if ok and out.strip():
                    for line in out.strip().split('\n'):
                        path = line.strip()
                        if path:
                            self._generated_repos.append(path)
            if not self._generated_repos:
                QMessageBox.information(self, "提示", "服务器上没有 .repo 文件，请先部署 Web 源")
                return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存 .repo 文件包", f"yum_repos_{datetime.datetime.now():%Y%m%d%H%M%S}.zip",
            "ZIP 文件 (*.zip)"
        )
        if not save_path:
            return

        try:
            temp_dir = tempfile.mkdtemp()
            local_files = []
            for repo_path in self._generated_repos:
                local_path = os.path.join(temp_dir, os.path.basename(repo_path))
                if os.path.exists(repo_path):
                    shutil.copy2(repo_path, local_path)
                elif self.ssh_manager.connected:
                    err = self.ssh_manager.get_file(repo_path, local_path)
                    if err:
                        self._log(f"❌ 下载 {repo_path} 失败: {err}")
                        continue
                else:
                    self._log(f"❌ 文件不可达: {repo_path}")
                    continue
                local_files.append(local_path)

            if not local_files:
                QMessageBox.warning(self, "提示", "没有可下载的 .repo 文件")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return

            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in local_files:
                    zf.write(f, os.path.basename(f))
            shutil.rmtree(temp_dir, ignore_errors=True)
            self._log(f"✅ 已打包 {len(local_files)} 个 .repo 文件到 {save_path}")

            reply = QMessageBox.question(
                self, "下载完成",
                f"已保存到:\n{save_path}\n\n是否打开所在目录？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._open_file_location(save_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打包失败: {e}")

    @staticmethod
    def _open_file_location(path: str):
        try:
            subprocess.Popen(['xdg-open', os.path.dirname(os.path.abspath(path))])
        except Exception:
            try:
                subprocess.Popen(['explorer', '/select,', os.path.abspath(path)])
            except Exception:
                pass

    # ----------------------------------------------------------
    #  日志
    # ----------------------------------------------------------
    def _log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {msg}")
        scrollbar = self.log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    def _on_local_iso_toggled(self, item):
        """本地 yum ISO 列表：勾选一个时自动取消其他（单选）"""
        if item.checkState(0) != Qt.Checked:
            return
        tree = self.local_iso_list
        tree.blockSignals(True)
        for i in range(tree.topLevelItemCount()):
            other = tree.topLevelItem(i)
            if other is not item and other.checkState(0) == Qt.Checked:
                other.setCheckState(0, Qt.Unchecked)
        tree.blockSignals(False)

    @staticmethod
    def _get_selected_isos(tree: QTreeWidget) -> List[str]:
        paths = []
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                path = item.data(0, Qt.UserRole)
                if path:
                    paths.append(path)
        return paths


# ============================================================
#  CLI 模式（供 launcher 静默调用）
# ============================================================
def run_cli_mode(args, ssh_manager: SSHManager = None):
    detector = SystemDetector()
    if ssh_manager and ssh_manager.connected:
        distro_info = ssh_manager.get_cached_distro()
    else:
        distro_info = detector.detect_distro()

    def _cli_run(cmd: str) -> Tuple[bool, str]:
        if ssh_manager and ssh_manager.connected:
            return ssh_manager.exec_command(cmd)
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, r.stderr.strip()

    if args.mode == 'local':
        iso_path = args.iso
        if not iso_path:
            if ssh_manager and ssh_manager.connected:
                isos = ssh_manager.scan_remote_isos(args.iso_dir or "/opt/tar")
            else:
                isos = detector.scan_isos(args.iso_dir or "/opt/tar")
            if not isos:
                print("❌ 未找到 ISO 文件")
                return 1
            iso_path = isos[0]['path']
        iso_name = os.path.basename(iso_path)
        iso_dir = os.path.splitext(iso_name)[0]
        mount_dir = f"{MOUNT_BASE}/{iso_dir}"
        http_target = f"{HTTP_DIR}/{iso_dir}"
        repo_file = os.path.join(YUM_REPOS_DIR, f"{iso_dir}.repo")

        cmds = [
            (f"挂载 {iso_name}", f"mkdir -p '{mount_dir}' && mount -o loop '{iso_path}' '{mount_dir}'"),
            (f"复制到 {http_target}", f"mkdir -p '{http_target}' && cp -rpf '{mount_dir}/'* '{http_target}'"),
            ("卸载 ISO", f"umount '{mount_dir}' 2>/dev/null || true"),
        ]

        baseurl = f"file://{http_target}"
        gpgcheck = 0 if distro_info['is_kylin'] else 1
        if distro_info['needs_appstream']:
            repo = f"[LocalRepo_BaseOS]\nname=LocalRepository_BaseOS\nbaseurl={baseurl}\nenabled=1\ngpgcheck={gpgcheck}\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n\n[LocalRepo_AppStream]\nname=LocalRepository_AppStream\nbaseurl={baseurl}/AppStream\nenabled=1\ngpgcheck={gpgcheck}\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n"
        else:
            repo = f"[LocalRepo_BaseOS]\nname=LocalRepository_BaseOS\nbaseurl={baseurl}\nenabled=1\ngpgcheck={gpgcheck}\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n\n[LocalRepo_AppStream]\nname=LocalRepository_AppStream\nbaseurl={baseurl}\nenabled=1\ngpgcheck={gpgcheck}\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n"

        cmds.append((f"写入 {repo_file}", f"cat > '{repo_file}' << 'EOF'\n{repo}\nEOF"))
        cmds.append(("检测 yum 可用性", "yum clean all 2>/dev/null; yum makecache 2>&1; yum install -y --downloadonly chrony 2>&1"))

        for desc, cmd in cmds:
            print(f"[{desc}]...", end=" ")
            ok, out = _cli_run(cmd)
            if ok:
                print("✅")
            else:
                print(f"❌ {out}")
                return 1
        print(f"\n✅ 本地 yum 源创建完成: {iso_dir}")
        return 0

    elif args.mode == 'web':
        iso_paths = []
        if args.iso:
            iso_paths = [args.iso]
        else:
            if ssh_manager and ssh_manager.connected:
                isos = ssh_manager.scan_remote_isos(args.iso_dir or "/opt/tar")
            else:
                isos = detector.scan_isos(args.iso_dir or "/opt/tar")
            iso_paths = [iso['path'] for iso in isos]
        if not iso_paths:
            print("❌ 未找到 ISO 文件")
            return 1

        if distro_info['is_rhel']:
            _cli_run(
                'for f in /etc/yum/pluginconf.d/product-id.conf /etc/yum/pluginconf.d/subscription-manager.conf; do '
                'if [ -f "$f" ]; then sed -i "s/^enabled=1/enabled=0/" "$f"; fi; done'
            )

        http_ip = args.ip or (
            (ssh_manager.get_cached_ips() if ssh_manager and ssh_manager.connected else detector.get_ip_list()) or ['127.0.0.1']
        )[0]
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        generated = []

        for iso_path in iso_paths:
            iso_name = os.path.basename(iso_path)
            iso_dir = os.path.splitext(iso_name)[0]
            mount_dir = os.path.join(MOUNT_BASE, iso_dir)
            http_target = os.path.join(HTTP_DIR, iso_dir)

            cmds = [
                (f"挂载 {iso_name}", f"mkdir -p '{mount_dir}' && mount -o loop '{iso_path}' '{mount_dir}'"),
                (f"复制到 {http_target}", f"mkdir -p '{http_target}' && cp -rpf '{mount_dir}/'* '{http_target}'"),
                ("卸载 ISO", f"umount '{mount_dir}' 2>/dev/null || true"),
            ]
            for desc, cmd in cmds:
                print(f"[{desc}]...", end=" ")
                ok, out = _cli_run(cmd)
                if ok:
                    print("✅")
                else:
                    print(f"❌ {out}")
                    return 1
                print("✅")

            needs_as = distro_info['needs_appstream']
            client_repo = f"{iso_dir}_{timestamp}.repo"
            baseurl = f"http://{http_ip}/{iso_dir}/BaseOS" if needs_as else f"http://{http_ip}/{iso_dir}"
            baseurl_as = f"http://{http_ip}/{iso_dir}/AppStream" if needs_as else baseurl
            gpgcheck = 0 if 'kylin' in iso_name.lower() else 1
            repo = f"[LocalRepo_BaseOS]\nname=LocalRepository_BaseOS\nbaseurl={baseurl}\nenabled=1\ngpgcheck={gpgcheck}\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n\n[LocalRepo_AppStream]\nname=LocalRepository_AppStream\nbaseurl={baseurl_as}\nenabled=1\ngpgcheck={gpgcheck}\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release\n"

            if ssh_manager and ssh_manager.connected:
                ok, _ = _cli_run(f"cat > '{client_repo}' << 'EOF'\n{repo}\nEOF")
                if ok:
                    local_path = os.path.join(os.getcwd(), client_repo)
                    err = ssh_manager.get_file(client_repo, local_path)
                    if err:
                        print(f"❌ 下载 {client_repo} 失败: {err}")
                    else:
                        generated.append(local_path)
                        print(f"✅ 生成 {local_path}")
                else:
                    print(f"❌ 写入 {client_repo} 失败")
                    return 1
            else:
                with open(client_repo, 'w') as f:
                    f.write(repo)
                generated.append(client_repo)
                print(f"✅ 生成 {client_repo}")

        print(f"\n✅ Web yum 源部署完成，共 {len(generated)} 个客户端 repo 文件")
        for r in generated:
            print(f"   📄 {os.path.abspath(r)}")
        return 0

    elif args.mode == 'install-pkg':
        print("安装基础软件包...")
        pkgs = args.packages or "gdb chrony"
        ok, out = _cli_run(f"yum install -y {pkgs}")
        if ok:
            print("✅ 安装完成")
            return 0
        print(f"❌ 安装失败: {out}")
        return 1

    return 1

#
# ============================================================
#  入口
# ============================================================
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Linux YUM 源管理器")
    parser.add_argument('--mode', choices=['local', 'web', 'install-pkg'],
                        help='运行模式（GUI模式无需此参数）')
    parser.add_argument('--iso', help='ISO 文件路径')
    parser.add_argument('--ip', help='HTTP 服务 IP 地址')
    parser.add_argument('--iso-dir', default='/opt/tar', help='ISO 目录路径')
    parser.add_argument('--packages', help='要安装的软件包名（空格分隔）')
    parser.add_argument('--ssh-host', help='SSH 服务器地址')
    parser.add_argument('--ssh-port', type=int, default=22, help='SSH 端口')
    parser.add_argument('--ssh-user', default='root', help='SSH 用户名')
    parser.add_argument('--ssh-pass', help='SSH 密码')

    args = parser.parse_args()

    # CLI 模式下支持 SSH 连接
    ssh_manager = SSHManager()
    if args.mode and args.ssh_host:
        print(f"连接 SSH: {args.ssh_user}@{args.ssh_host}:{args.ssh_port}...")
        err = ssh_manager.connect(args.ssh_host, args.ssh_port,
                                  args.ssh_user, args.ssh_pass or "")
        if err:
            print(f"❌ SSH 连接失败: {err}")
            return 1
        print("✅ SSH 连接成功")

    if args.mode:
        sys.exit(run_cli_mode(args, ssh_manager))

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
