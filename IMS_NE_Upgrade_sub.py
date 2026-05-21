# -*- coding: utf-8 -*-
"""
IMS 网元升级工具 (PySide6)
"""
import sys, os, json, logging, threading, time, difflib, posixpath
from datetime import datetime
from pathlib import Path

import paramiko
from PySide6.QtWidgets import (
    QWidget, QApplication, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QFileDialog, QMessageBox, QComboBox, QGroupBox,
    QFormLayout, QFrame, QDialog, QScrollArea, QSplitter, QCheckBox,
    QGridLayout, QProgressBar, QRadioButton, QListWidget
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)

PATH = os.path.dirname(__file__)
NE_CONFIG_PATH = os.path.join(PATH, "config", "ims_ne_config.json")
IMS_HOSTS_PATH = os.path.join(PATH, "config", "ims_hosts.json")


class SSHWorker(QThread):
    log_signal = Signal(str)
    step_signal = Signal(str)
    finished_signal = Signal(str)
    config_diff_signal = Signal(list)
    kill_residual_signal = Signal(list, str)

    def __init__(self, host, port, username, password, ne_config, patch_local, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.ne = ne_config
        self.patch_local = patch_local
        self.sftp = None
        self.ssh = None
        self._stopped = False
        self._kill_continue = None

    def stop(self):
        self._stopped = True

    def _log(self, msg):
        self.log_signal.emit(msg)

    def _step(self, msg):
        self.step_signal.emit(msg)

    def _exec(self, cmd, timeout=60, user=None, input_str=None):
        full_cmd = cmd
        if user and user != self.username:
            escaped = cmd.replace("'", "'\"'\"'")
            full_cmd = f"su - {user} -c '{escaped}'"
        self._log(f"> {full_cmd}")
        stdin, stdout, stderr = self.ssh.exec_command(full_cmd, timeout=timeout)
        if input_str:
            self._log(f"  <<< 发送输入: {input_str.strip()}")
            stdin.write(input_str)
            stdin.flush()
            stdin.channel.shutdown_write()
        return self._read_result(stdin, stdout, stderr, timeout)

    def _exec_bg(self, cmd, user=None):
        full_cmd = cmd
        if user and user != self.username:
            escaped = cmd.replace("'", "'\"'\"'")
            full_cmd = f"su - {user} -c '{escaped}'"
        self._log(f"> {full_cmd}")
        stdin, stdout, stderr = self.ssh.exec_command(full_cmd, timeout=5)
        stdin.close()
        self._log("  ↻ 后台命令已启动，等待 3 秒确认...")
        time.sleep(1)
        try:
            stdout.channel.close()
        except:
            pass
        try:
            stderr.channel.close()
        except:
            pass
        return 0, "", ""

    def _read_result(self, stdin, stdout, stderr, timeout):
        try:
            out = stdout.read().decode("utf-8", errors="replace").strip()
        except:
            out = ""
        try:
            err = stderr.read().decode("utf-8", errors="replace").strip()
        except:
            err = ""
        try:
            rc = stdout.channel.recv_exit_status()
        except:
            rc = -1
        if out:
            for line in out.split("\n"):
                self._log(f"  {line}")
        if err:
            for line in err.split("\n"):
                self._log(f"  ! {line}")
        return rc, out, err

    def _exec_script_user(self, user, commands, inputs=None):
        self._log(f"> [{user}] 执行命令序列 ({len(commands)} 条)")
        cwd = None
        for i, cmd in enumerate(commands):
            if self._stopped:
                self._log("  ⛔ 用户终止，跳过后续命令")
                return
            if cmd.startswith("WAIT"):
                sec = int(cmd.split()[1])
                self._log(f"  [{i+1}/{len(commands)}] 等待 {sec} 秒 ...")
                for s in range(sec, 0, -1):
                    if self._stopped:
                        return
                    time.sleep(1)
                    if s % 5 == 0 or s <= 3:
                        self._log(f"    剩余 {s} 秒")
                continue
            if cmd.startswith("cd "):
                cwd = cmd[3:].strip().strip('"').strip("'")
                self._log(f"  [{i+1}/{len(commands)}] 记录工作目录: {cwd}")
                continue
            actual_cmd = cmd
            if cwd:
                actual_cmd = f"cd {cwd} && {cmd}"
            inp = inputs.get(str(i)) if inputs else None
            if actual_cmd.strip().endswith("&"):
                bg_cmd = actual_cmd.rstrip()[:-1].rstrip() + " </dev/null >>nohup.out 2>&1 &"
                self._log(f"  [{i+1}/{len(commands)}] 执行(后台): {bg_cmd}")
                rc, out, err = self._exec_bg(bg_cmd, user=user)
            else:
                self._log(f"  [{i+1}/{len(commands)}] 执行: {actual_cmd}")
                rc, out, err = self._exec(actual_cmd, user=user, input_str=inp)
            if rc != 0:
                self._log(f"  ⚠ 返回码: {rc} (命令可能未完全成功)")
            else:
                self._log(f"  ✓ 返回码: {rc}")

    def _check_remote_path(self, path, path_type="路径"):
        rc, out, err = self._exec(f"ls -d '{path}' 2>/dev/null && echo 'EXISTS' || echo 'NOTEXISTS'")
        if "EXISTS" in out:
            rc2, out2, _ = self._exec(f"stat --format='%%F 大小:%%s 字节  修改时间:%%y' '{path}' 2>/dev/null || file '{path}'")
            return True
        self._log(f"  ⚠ {path_type}不存在: {path}")
        return False

    def run(self):
        try:
            self._log("══════════════════════════════════════════════")
            self._log(f"IMS 网元升级开始")
            self._log(f"目标主机: {self.host}:{self.port}")
            self._log(f"网元类型: {self.ne.get('description', '未知')}")
            self._log(f"补丁文件: {os.path.basename(self.patch_local)} ({self._fmt_size(os.path.getsize(self.patch_local))})")
            self._log(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self._log("══════════════════════════════════════════════")

            self._log(f"正在连接 {self.host}:{self.port} ...")
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(self.host, port=self.port, username=self.username,
                            password=self.password, timeout=15)
            self._log(f"✓ SSH 连接成功 ({self.host}:{self.port})")
            self.sftp = self.ssh.open_sftp()
            self._log("✓ SFTP 会话已打开")
            self._log("")

            # 依次执行各步骤，每步检查是否被终止
            steps = [
                ("stop",        self._do_stop),
                ("backup",      self._do_backup),
                ("upload",      self._do_upload),
                ("extract",     self._do_extract),
                ("post_extract", self._do_post_extract),
                ("config_diff", self._do_config_diff),
                ("chown",       self._do_chown),
                ("license",     self._do_license),
                ("start",       self._do_start),
            ]
            for step_key, step_func in steps:
                if self._stopped:
                    self._log("⛔ 用户终止升级")
                    break
                self._step(step_key)
                step_func()
                self._log("")

            if not self._stopped:
                self._log("══════════════════════════════════════════════")
                self._log("✓ 所有升级步骤已完成")
                self._log(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                self._log("══════════════════════════════════════════════")
                self.finished_signal.emit("success")
            else:
                self.finished_signal.emit("stopped")
        except paramiko.AuthenticationException:
            self._log("✗ SSH 认证失败，请检查用户名和密码")
            self.finished_signal.emit("error")
        except paramiko.SSHException as e:
            self._log(f"✗ SSH 连接异常: {e}")
            self.finished_signal.emit("error")
        except Exception as e:
            self._log(f"✗ 意外错误: {e}")
            import traceback
            self._log(traceback.format_exc())
            self.finished_signal.emit("error")
        finally:
            if self.sftp:
                try: self.sftp.close()
                except: pass
            if self.ssh:
                try: self.ssh.close()
                except: pass

    def _fmt_size(self, bytes_val):
        for unit in ("B", "KB", "MB", "GB"):
            if bytes_val < 1024:
                return f"{bytes_val:.1f}{unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f}TB"

    # ── 步骤1: 停止 ──
    def _do_stop(self):
        cfg = self.ne["stop"]
        self._log("━━━ 步骤1/9: 停止程序 ━━━")
        self._log(f"停止方式: {cfg['method']}  执行用户: {cfg['user']}")

        if not cfg.get("commands") and not cfg.get("process_names"):
            self._log("  ⚠ 未配置停止命令和进程名，跳过")
            return

        if cfg["method"] == "script":
            if not cfg.get("commands"):
                self._log("  ⚠ script方式但未配置命令，跳过")
                return
            self._log(f"将执行 {len(cfg['commands'])} 条停止命令")
            inputs = cfg.get("inputs", {})
            if inputs:
                self._log(f"  交互输入配置: 命令索引 {list(inputs.keys())} 需要自动输入")
            self._exec_script_user(cfg["user"], cfg["commands"], inputs=inputs)

        elif cfg["method"] == "kill":
            if not cfg.get("process_names"):
                self._log("  ⚠ kill方式但未配置进程名，跳过")
                return
            for pname in cfg["process_names"]:
                if self._stopped:
                    return
                self._log(f"--- 查找进程关键字: {pname} ---")
                rc, out, _ = self._exec(f"ps -ef | grep '{pname}' | grep -v grep")
                lines = [l.strip() for l in out.split("\n") if l.strip()]
                if not lines:
                    self._log(f"  未找到匹配 '{pname}' 的进程")
                    continue
                self._log(f"  找到 {len(lines)} 个匹配进程:")
                pids = []
                for line in lines:
                    parts = line.split()
                    pid = parts[1] if len(parts) >= 2 else "?"
                    user_proc = parts[0] if len(parts) >= 1 else "?"
                    cmdline = " ".join(parts[7:]) if len(parts) > 8 else parts[-1] if parts else ""
                    self._log(f"    PID={pid}  USER={user_proc}  {cmdline[:80]}")
                    if pid != "?":
                        pids.append(pid)
                if pids:
                    self._log(f"  执行 kill -9 {' '.join(pids)}")
                    rc_k, _, err_k = self._exec(f"kill -9 {' '.join(pids)}")
                    if rc_k == 0:
                        self._log(f"  ✓ 已发送 SIGKILL 给 {len(pids)} 个进程")
                    else:
                        self._log(f"  ⚠ kill 返回码 {rc_k}: {err_k[:100]}")
                    time.sleep(2)
                    rc2, out2, _ = self._exec(f"ps -ef | grep '{pname}' | grep -v grep")
                    remaining = [l.strip() for l in out2.split("\n") if l.strip()]
                    if remaining:
                        self._log(f"  ⚠ 发现 {len(remaining)} 个残余进程，等待用户确认...")
                        self.kill_residual_signal.emit(remaining, pname)
                        self._kill_continue = None
                        while self._kill_continue is None and not self._stopped:
                            time.sleep(0.1)
                        if self._stopped or not self._kill_continue:
                            self._log("  用户选择退出升级")
                            self._stop_upgrade()
                            return
                        self._log("  用户选择继续升级")
        self._log("✓ 步骤1 完成")

    # ── 步骤2: 备份 ──
    def _do_backup(self):
        cfg = self.ne["backup"]
        self._log("━━━ 步骤2/9: 备份原程序路径 ━━━")
        self._log(f"备份用户: {cfg['user']}  基础目录: {cfg['base_dir']}")

        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._backup_map = {}

        for item in cfg["items"]:
            if self._stopped:
                return
            src = posixpath.join(cfg["base_dir"], item["source"])
            backup_name = item["source"] + item["backup_suffix"].replace("{date}", date_str)
            dst = posixpath.join(cfg["base_dir"], backup_name)

            backup_user = item.get("user") or cfg["user"]
            self._log(f"--- 备份项目 ---")
            self._log(f"  源路径:   {src}")
            self._log(f"  目标路径: {dst}")
            self._log(f"  执行用户: {backup_user}")

            exists = self._check_remote_path(src, "源路径")
            if not exists:
                self._log("  ⚠ 源路径不存在，跳过备份")
                continue

            rc, _, _ = self._exec(f"cp -r '{src}' '{dst}'", timeout=120, user=backup_user)
            if rc == 0:
                self._log(f"  ✓ 备份成功")
                self._check_remote_path(dst, "备份路径")
                if item.get("remove_source", False):
                    self._log(f"  配置要求删除原路径: {src}")
                    rc_del, _, _ = self._exec(f"rm -rf '{src}'", timeout=60, user="root")
                    if rc_del == 0:
                        self._log(f"  ✓ 原路径已删除")
                    else:
                        self._log(f"  ⚠ 原路径删除失败 (返回码 {rc_del})")
            else:
                self._log(f"  ✗ 备份失败 (返回码 {rc})")

            self._backup_map[item["source"]] = {"src": src, "dst": dst}
        self._log("✓ 步骤2 完成")

    # ── 步骤3: 上传 ──
    def _do_upload(self):
        self._log("━━━ 步骤3/9: 上传补丁文件 ━━━")
        tar_path = self.ne["patch"].get("tar_path", "/opt/tar")
        remote_name = os.path.basename(self.patch_local)
        remote_path = posixpath.join(tar_path, remote_name)

        self._log(f"本地文件:  {self.patch_local}")
        self._log(f"  大小:     {self._fmt_size(os.path.getsize(self.patch_local))}")
        self._log(f"  修改时间: {datetime.fromtimestamp(os.path.getmtime(self.patch_local)).strftime('%Y-%m-%d %H:%M:%S')}")
        self._log(f"远程目录: {tar_path}")
        self._log(f"远程路径: {remote_path}")

        self._log("创建远程目录(如不存在)...")
        rc, _, _ = self._exec(f"mkdir -p '{tar_path}'")
        if rc != 0:
            self._log(f"  ⚠ 创建目录返回码 {rc}")
        else:
            self._log("  ✓ 目录就绪")

        self._log("开始上传 ...")
        start_time = time.time()
        last_pct = [0]

        def progress(transferred, total):
            if self._stopped:
                raise Exception("用户终止上传")
            if total > 0:
                pct = int(transferred / total * 100)
                elapsed = time.time() - start_time
                if pct >= last_pct[0] + 5 or pct == 100:
                    speed = transferred / elapsed / 1024 if elapsed > 0 else 0
                    self._log(f"  [{pct:3d}%] {self._fmt_size(transferred)}/{self._fmt_size(total)}  {speed:.0f}KB/s")
                    last_pct[0] = pct

        try:
            self.sftp.put(self.patch_local, remote_path, callback=progress)
            elapsed = time.time() - start_time
            speed = os.path.getsize(self.patch_local) / elapsed / 1024 if elapsed > 0 else 0
            self._log(f"✓ 上传完成 ({elapsed:.1f}秒, {speed:.0f}KB/s)")
            self._uploaded_path = remote_path
            self._check_remote_path(remote_path, "补丁文件")
        except Exception as e:
            self._log(f"✗ 上传失败: {e}")
            raise
        self._log("✓ 步骤3 完成")

    # ── 步骤4: 解压 ──
    def _do_extract(self):
        self._log("━━━ 步骤4/9: 解压补丁文件 ━━━")
        user = self.ne["patch"]["extract_user"]
        fname = self._uploaded_path

        self._log(f"解压文件:  {fname}")
        self._log(f"执行用户:  {user}")
        self._log(f"解压参数:  tar -xzf ... -C /")

        self._check_remote_path(fname, "补丁文件")

        self._log("解压中，请稍候 ...")
        rc, out, _ = self._exec(f"cd /opt/tar && tar -xzf '{fname}' -C /", timeout=180, user=user)
        if rc == 0:
            self._log("✓ 解压成功")
            if rc != 0:
                self._log("  ⚠ 可能部分文件解压异常")
            self._log("列出解压后的 /opt/tar 内容:")
            self._exec(f"ls -lh '{posixpath.dirname(fname)}/'")
        else:
            self._log(f"✗ 解压失败 (返回码 {rc})")
            raise RuntimeError(f"tar 解压失败，返回码 {rc}")
        self._log("✓ 步骤4 完成")

    # ── 步骤5: 解压后脚本 ──
    def _do_post_extract(self):
        cfg = self.ne.get("post_extract")
        self._log("━━━ 步骤5/9: 解压后处理脚本 ━━━")
        if not cfg:
            self._log("  此网元无解压后处理脚本，跳过")
            self._log("✓ 步骤5 跳过")
            return

        self._log(f"执行用户: {cfg['user']}")
        self._log(f"命令数:   {len(cfg.get('commands', []))}")
        if cfg.get("commands"):
            for c in cfg["commands"]:
                self._log(f"  · {c}")
        self._exec_script_user(cfg["user"], cfg["commands"])
        self._log("✓ 步骤5 完成")

    # ── 步骤6: 配置文件对比 ──
    def _do_config_diff(self):
        self._log("━━━ 步骤6/9: 配置文件对比 ━━━")
        config_files = self.ne.get("config_files", [])
        if not config_files:
            self._log("  此网元无配置文件需要对比，跳过")
            self._log("✓ 步骤6 跳过")
            return

        self._log(f"需要对比的配置文件 ({len(config_files)} 个):")
        for cf in config_files:
            self._log(f"  · {cf}")

        base_dir = self.ne["backup"]["base_dir"]
        file_items = []
        for cf in config_files:
            if self._stopped:
                return
            self._log(f"--- 处理: {cf} ---")
            old_path = ""
            for source_key, info in self._backup_map.items():
                src_prefix = posixpath.join(base_dir, source_key)
                if cf == src_prefix or cf.startswith(src_prefix + "/"):
                    old_path = cf.replace(src_prefix, info["dst"], 1)
                    break
            if not old_path:
                self._log(f"  ⚠ 无法确定备份路径，跳过此文件")
                continue

            old_content = ""
            old_found = True
            try:
                with self.sftp.open(old_path, "r") as f:
                    old_content = f.read().decode("utf-8", errors="replace")
                self._log(f"  ✓ 读取备份配置成功 ({len(old_content)} 字符)")
            except FileNotFoundError:
                self._log(f"  ⚠ 备份配置不存在: {old_path}")
                old_found = False
            except Exception as e:
                self._log(f"  ⚠ 读取备份配置失败: {e}")
                old_found = False

            new_content = ""
            new_found = True
            try:
                with self.sftp.open(cf, "r") as f:
                    new_content = f.read().decode("utf-8", errors="replace")
                self._log(f"  ✓ 读取新配置成功 ({len(new_content)} 字符)")
            except FileNotFoundError:
                self._log(f"  ⚠ 新配置不存在: {cf}")
                new_found = False
            except Exception as e:
                self._log(f"  ⚠ 读取新配置失败: {e}")
                new_found = False

            # 备份不存在时跳过对比，直接保留新配置
            if not old_found:
                self._log(f"  → 备份配置不可用，直接保留新配置")
                file_items.append({
                    "path": cf,
                    "old_path": old_path,
                    "old_content": "",
                    "new_content": new_content,
                    "diff": [],
                    "hunks": [],
                    "old_lines": 0,
                    "new_lines": len(new_content.splitlines()),
                    "changes": 0,
                    "skip_diff": True
                })
                continue

            old_lines = old_content.splitlines(True)
            new_lines = new_content.splitlines(True)
            diff = list(difflib.unified_diff(
                old_lines, new_lines,
                fromfile="旧配置(备份版)",
                tofile="新配置(tar版)",
                lineterm=""
            ))

            # 解析差异块（hunks）
            hunks = self._parse_hunks(diff)
            total_changes = sum(1 for l in diff if l.startswith("+") or l.startswith("-"))
            self._log(f"  差异行数: {total_changes}, 差异块数: {len(hunks)}")

            file_items.append({
                "path": cf,
                "old_path": old_path,
                "old_content": old_content,
                "new_content": new_content,
                "diff": diff,
                "hunks": hunks,
                "old_lines": len(old_lines),
                "new_lines": len(new_lines),
                "changes": total_changes
            })

        if not file_items:
            self._log("  无有效配置文件需要对比")
            self._log("✓ 步骤6 跳过")
            return

        # 分离无需对比（备份不存在）的文件，直接保留新配置
        skip_items = [it for it in file_items if it.get("skip_diff")]
        diff_items = [it for it in file_items if not it.get("skip_diff")]

        results = []
        for it in skip_items:
            self._log(f"  → {it['path']}: 备份不存在，保留新配置")
            results.append({"path": it["path"], "merged_content": it["new_content"]})

        if not diff_items:
            self._config_diff_result = results
            self._log("  所有文件均无可对比备份，直接保留新配置")
            self._log("✓ 步骤6 完成")
            return

        self._log("等待用户逐块确认差异 ...")
        self.config_diff_signal.emit(diff_items)
        self._config_diff_result = None
        while self._config_diff_result is None and not self._stopped:
            time.sleep(0.1)
        if self._stopped:
            self._log("  ⛔ 用户终止")
            return

        results.extend(self._config_diff_result)

        for result in results:
            path = result["path"]
            merged = result["merged_content"]
            self._log(f"  ▶ 写入合并后的配置: {path}")
            try:
                with self.sftp.open(path, "w") as f:
                    f.write(merged)
                self._log(f"  ✓ 已写入 ({len(merged)} 字符)")
            except Exception as e:
                self._log(f"  ⚠ 写入失败: {e}")
        self._log("✓ 步骤6 完成")

    def _parse_hunks(self, diff_lines):
        """将 unified diff 解析为 hunks 列表"""
        import re
        hunks = []
        current_hunk = None
        for line in diff_lines:
            if line.startswith("@@"):
                if current_hunk:
                    hunks.append(current_hunk)
                m = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@(.*)', line)
                old_start = int(m.group(1)) if m else 0
                new_start = int(m.group(3)) if m else 0
                section = m.group(5).strip() if m and m.group(5) else ""
                current_hunk = {
                    "old_start": old_start,
                    "new_start": new_start,
                    "section": section,
                    "old_lines": [],
                    "new_lines": [],
                    "lines": []
                }
            elif line.startswith("---") or line.startswith("+++"):
                continue
            elif current_hunk is not None:
                current_hunk["lines"].append(line)
                if line.startswith("-") and not line.startswith("---"):
                    current_hunk["old_lines"].append(line[1:])
                elif line.startswith("+") and not line.startswith("+++"):
                    current_hunk["new_lines"].append(line[1:])
                else:
                    current_hunk["old_lines"].append(line[1:])
                    current_hunk["new_lines"].append(line[1:])
        if current_hunk:
            hunks.append(current_hunk)
        return hunks

    def set_config_diff_result(self, results):
        self._config_diff_result = results

    def set_kill_decision(self, decision):
        self._kill_continue = decision

    # ── 步骤7: 修改属组 ──
    def _do_chown(self):
        cfg = self.ne.get("chown")
        self._log("━━━ 步骤7/9: 修改文件属组 ━━━")
        if not cfg:
            self._log("  此网元无需修改文件属组，跳过")
            self._log("✓ 步骤7 跳过")
            return

        self._log(f"属组设置: {cfg['user']}:{cfg['group']}")
        self._log(f"文件数量: {len(cfg.get('paths', []))}")
        success = 0
        for p in cfg["paths"]:
            if self._stopped:
                return
            rc, _, _ = self._exec(f"chown {cfg['user']}:{cfg['group']} '{p}'", user="root")
            if rc == 0:
                self._log(f"  ✓ {p}")
                # 验证
                self._exec(f"ls -l '{p}' | awk '{{print $3\":\"$4}}'")
                success += 1
            else:
                self._log(f"  ⚠ {p} 修改失败 (返回码 {rc})")
        self._log(f"结果: {success}/{len(cfg.get('paths', []))} 个文件修改成功")
        self._log("✓ 步骤7 完成")

    # ── 步骤8: License ──
    def _do_license(self):
        cfg = self.ne.get("license", {})
        self._log("━━━ 步骤8/9: License文件处理 ━━━")
        if not cfg.get("has_license"):
            self._log("  此网元无License文件，跳过")
            self._log("✓ 步骤8 跳过")
            return

        license_path = cfg["file_path"]
        self._log(f"License文件: {license_path}")
        self._check_remote_path(license_path, "License")

        # 从备份中找到对应的旧license
        base_dir = self.ne["backup"]["base_dir"]
        old_license = ""
        for source_key, info in self._backup_map.items():
            src_prefix = posixpath.join(base_dir, source_key)
            if license_path.startswith(src_prefix + "/") or license_path == src_prefix:
                old_license = license_path.replace(src_prefix, info["dst"], 1)
                break

        if not old_license:
            self._log("  ⚠ 无法从备份映射中找到对应的License路径")
        else:
            self._log(f"备份License: {old_license}")
            exists = self._check_remote_path(old_license, "备份License")
            if not exists:
                self._log("  ⚠ 备份中无License文件，无法恢复")
            else:
                rc, _, _ = self._exec(f"cp '{old_license}' '{license_path}'", user=cfg.get("user", "root"))
                if rc == 0:
                    self._log(f"  ✓ License已恢复: {old_license} -> {license_path}")
                    self._check_remote_path(license_path, "License(恢复后)")
                else:
                    self._log(f"  ⚠ License恢复失败 (返回码 {rc})")
        self._log("✓ 步骤8 完成")

    # ── 步骤9: 启动 ──
    def _do_start(self):
        cfg = self.ne["start"]
        self._log("━━━ 步骤9/9: 启动程序 ━━━")
        self._log(f"启动用户: {cfg['user']}")
        self._log(f"启动命令 ({len(cfg.get('commands', []))} 条):")
        for c in cfg.get("commands", []):
            self._log(f"  · {c}")

        self._exec_script_user(cfg["user"], cfg["commands"])
        self._log("")

        # 启动检查（可选）
        check_cfg = cfg.get("check")
        if check_cfg:
            self._log("--- 启动检查 ---")
            cmd = check_cfg["command"]
            expected = check_cfg.get("expected", "")
            wait = check_cfg.get("wait", 0)
            if wait > 0:
                self._log(f"  等待 {wait} 秒后检查 ...")
                time.sleep(wait)
            self._log(f"  检查命令: {cmd}")
            self._log(f"  期望包含: {expected}")
            rc, out, _ = self._exec(cmd, user=cfg["user"])
            if rc == 0 and expected in out:
                self._log(f"  ✓ 启动成功: 输出包含 \"{expected}\"")
            else:
                self._log(f"  ⚠ 启动检查未通过 (rc={rc})")
                self._log(f"  实际输出: {out[:200] if out else '(空)'}")
        else:
            self._log("提示: 请使用 ps -ef 或应用日志确认程序已正常启动")
        self._log("")
        self._log("✓ 步骤9 完成")


class ConfigDiffDialog(QDialog):
    def __init__(self, diff_items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置文件对比 - 逐块确认差异")
        self.resize(1000, 700)
        self.diff_items = diff_items
        self.results = []
        self._file_index = 0
        self._hunk_index = 0
        self._hunk_decisions = []  # bool list per hunk for current file
        self._file_merged = {}     # path -> merged_content
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("font-size: 13px; color: #2d3436; padding: 4px 0;")
        layout.addWidget(self.progress_label)

        self.file_label = QLabel()
        self.file_label.setStyleSheet("font-size: 11px; color: #636e72; padding: 2px 0;")
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        self.diff_view = QTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(QFont("Consolas", 10))
        self.diff_view.setStyleSheet(
            "background: #1e1e1e; color: #d4d4d4; border-radius: 6px; padding: 8px;"
        )
        layout.addWidget(self.diff_view, 1)

        self.btn_layout = QHBoxLayout()
        self.btn_layout.setSpacing(12)

        btn_style_accept = (
            "QPushButton{background:#27ae60;color:white;font-weight:bold;"
            "padding:10px 32px;border:none;border-radius:6px;font-size:14px;}"
            "QPushButton:hover{background:#219a52;}"
        )
        btn_style_reject = (
            "QPushButton{background:#e67e22;color:white;font-weight:bold;"
            "padding:10px 32px;border:none;border-radius:6px;font-size:14px;}"
            "QPushButton:hover{background:#d35400;}"
        )
        btn_style_all = (
            "QPushButton{font-size:11px;padding:6px 16px;border:1px solid #0984e3;"
            "color:#0984e3;border-radius:4px;background:white;}"
            "QPushButton:hover{background:#0984e3;color:white;}"
        )

        self.accept_btn = QPushButton("✅ 接受此修改")
        self.accept_btn.setStyleSheet(btn_style_accept)
        self.accept_btn.clicked.connect(self._on_accept)
        self.btn_layout.addWidget(self.accept_btn)

        self.reject_btn = QPushButton("🔄 保留旧版")
        self.reject_btn.setStyleSheet(btn_style_reject)
        self.reject_btn.clicked.connect(self._on_reject)
        self.btn_layout.addWidget(self.reject_btn)

        self.btn_layout.addStretch()

        self.accept_all_btn = QPushButton("全部接受")
        self.accept_all_btn.setStyleSheet(btn_style_all)
        self.accept_all_btn.clicked.connect(self._on_accept_all)
        self.btn_layout.addWidget(self.accept_all_btn)

        self.reject_all_btn = QPushButton("全部拒绝")
        self.reject_all_btn.setStyleSheet(btn_style_all)
        self.reject_all_btn.clicked.connect(self._on_reject_all)
        self.btn_layout.addWidget(self.reject_all_btn)

        layout.addLayout(self.btn_layout)

        self.status_label = QLabel()
        self.status_label.setStyleSheet("font-size: 12px; color: #636e72; padding: 2px 0;")
        layout.addWidget(self.status_label)

        # 显示第一个文件
        self._show_current()

    def _show_current(self):
        if self._file_index >= len(self.diff_items):
            self._finish()
            return

        item = self.diff_items[self._file_index]
        hunks = item.get("hunks", [])

        # 首次进入此文件，重置决策列表
        if not self._hunk_decisions or self._hunk_index == 0:
            self._hunk_decisions = [None] * len(hunks)

        f = self._file_index + 1
        ft = len(self.diff_items)
        self.progress_label.setText(
            f'<b>文件 {f}/{ft}</b>  —  {"无差异" if not hunks else f"差异块 {self._hunk_index + 1}/{len(hunks)}"}'
        )
        self.file_label.setText(
            f'<span style="color:#636e72;">{item["path"]}</span>'
        )

        if not hunks:
            # 无差异，直接接受整个文件
            self._hunk_decisions = []
            self._apply_and_next()
            return

        hunk = hunks[self._hunk_index]
        self._render_hunk(item, hunk)

        decided_count = sum(1 for d in self._hunk_decisions if d is not None)
        self.status_label.setText(
            f'已处理: {decided_count}/{len(hunks)}  差异块'
        )

    def _render_hunk(self, item, hunk):
        lines = []
        lines.append(f'@@ 区域: {hunk["section"]} @@')
        lines.append("")
        lines.append("--- 旧版 ---")
        for l in hunk["old_lines"]:
            lines.append(f" {l.rstrip()}")
        lines.append("")
        lines.append("+++ 新版 +++")
        for l in hunk["new_lines"]:
            lines.append(f" {l.rstrip()}")

        html_lines = []
        for line in hunk["lines"]:
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if line.startswith("+"):
                html_lines.append(f'<span style="color:#27ae60;">{escaped}</span>')
            elif line.startswith("-"):
                html_lines.append(f'<span style="color:#e74c3c;">{escaped}</span>')
            elif line.startswith("@@"):
                html_lines.append(
                    f'<span style="color:#0984e3;font-weight:bold;">'
                    f'@@ 区域: {hunk["section"]} @@</span>'
                )
            else:
                html_lines.append(escaped)
        self.diff_view.setHtml("<br>".join(html_lines))

    def _on_accept(self):
        self._hunk_decisions[self._hunk_index] = True
        self._hunk_index += 1
        if self._hunk_index >= len(self.diff_items[self._file_index].get("hunks", [])):
            self._apply_and_next()
        else:
            self._show_current()

    def _on_reject(self):
        self._hunk_decisions[self._hunk_index] = False
        self._hunk_index += 1
        if self._hunk_index >= len(self.diff_items[self._file_index].get("hunks", [])):
            self._apply_and_next()
        else:
            self._show_current()

    def _on_accept_all(self):
        item = self.diff_items[self._file_index]
        for i in range(len(item.get("hunks", []))):
            self._hunk_decisions[i] = True
        self._apply_and_next()

    def _on_reject_all(self):
        item = self.diff_items[self._file_index]
        for i in range(len(item.get("hunks", []))):
            self._hunk_decisions[i] = False
        self._apply_and_next()

    def _apply_and_next(self):
        item = self.diff_items[self._file_index]
        hunks = item.get("hunks", [])

        if not hunks:
            merged = item["old_content"]
        else:
            old_lines = item["old_content"].splitlines(True)
            # 从后往前应用，避免行号偏移
            for i in reversed(range(len(hunks))):
                if self._hunk_decisions[i]:
                    h = hunks[i]
                    start = h["old_start"] - 1
                    count_old = len(h["old_lines"])
                    # 确保安全范围
                    end = min(start + count_old, len(old_lines))
                    old_lines[start:end] = h["new_lines"]
            merged = "".join(old_lines)

        self._file_merged[item["path"]] = merged
        self._file_index += 1
        self._hunk_index = 0
        self._hunk_decisions = []
        self._show_current()

    def _finish(self):
        for item in self.diff_items:
            self.results.append({
                "path": item["path"],
                "merged_content": self._file_merged.get(item["path"], item["old_content"])
            })
        self.accept()


class IMSEUpgradeTool(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self._connected = False
        self._hosts = self._load_hosts()
        self.ne_configs = self._load_ne_configs()
        self._build_ui()
        self._init_done = True
        self._refresh_host_combo()
        if self._hosts:
            self._on_host_selected(0)

    def _load_ne_configs(self):
        try:
            with open(NE_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载网元配置失败: {e}")
            return {}

    def _build_ui(self):
        self.setWindowTitle("IMS 网元升级")
        self.resize(920, 740)
        self.setStyleSheet("""
            IMSEUpgradeTool { background:#f5f6fa; }
            QLineEdit, QComboBox {
                border: none; border-bottom: 2px solid #dfe6e9;
                padding: 6px 4px; font-size: 13px; background: #f8f9fa;
                color: #2d3436;
            }
            QComboBox::down-arrow { image: none; }
            QComboBox::drop-down { border: none; width: 0; }
            QLineEdit:focus, QComboBox:focus {
                border-bottom: 2px solid #0984e3;
            }
            QComboBox QAbstractItemView {
                background: white;
                color: #2d3436;
                selection-background-color: #0984e3;
                selection-color: white;
                outline: none;
            }
            QComboBox QAbstractItemView::item:hover {
                background: #dfe6e9;
                color: #2d3436;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 12, 16, 12)

        title = QLabel("IMS 网元升级工具")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2d3436;")
        layout.addWidget(title)

        subtitle = QLabel("支持 MGCF / CCF / SCP 等网元的停止→备份→上传→解压→配置对比→启动 全流程")
        subtitle.setStyleSheet("font-size: 12px; color: #636e72; margin-bottom: 4px;")
        layout.addWidget(subtitle)

        self._group_box_style = """
            QGroupBox { font-weight: bold; border: 1px solid #dfe6e9;
                border-radius: 6px; margin-top: 10px; padding: 16px 12px 12px 12px;
                background: white; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
        """

        # ── 连接栏（下拉选择 + 管理 + 连接） ──
        conn_bar = QFrame()
        conn_bar.setStyleSheet("QFrame { background: white; border: 1px solid #dfe6e9; border-radius: 6px; padding: 8px 12px; }")
        conn_layout = QHBoxLayout(conn_bar)
        conn_layout.setContentsMargins(8, 4, 8, 4)
        conn_layout.setSpacing(8)
        conn_layout.addWidget(QLabel("🔗 主机:"))
        self.host_combo = QComboBox()
        self.host_combo.setMinimumWidth(320)
        self.host_combo.setStyleSheet("""
            QComboBox { border: 1px solid #dfe6e9; border-radius: 4px; padding: 6px 8px; font-size: 13px; background: #f8f9fa; }
            QComboBox:focus { border: 1px solid #0984e3; background: white; }
            QComboBox::down-arrow { image: none; }
            QComboBox::drop-down { border: none; width: 0; }
            QComboBox QAbstractItemView { background: white; color: #1a1a1a; selection-background-color: #e8f0fe; selection-color: #1a1a1a; }
        """)
        self.host_combo.currentIndexChanged.connect(self._on_host_selected)
        conn_layout.addWidget(self.host_combo)
        manage_btn = QPushButton("管理")
        manage_btn.setStyleSheet("QPushButton{background:#f8f9fa;color:#636e72;border:1px solid #dfe6e9;border-radius:4px;padding:6px 12px;font-size:12px;}QPushButton:hover{background:#e8e8e8;}")
        manage_btn.clicked.connect(self._manage_hosts)
        conn_layout.addWidget(manage_btn)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setStyleSheet("QPushButton{background:#0984e3;color:white;border:none;border-radius:4px;padding:6px 18px;font-size:13px;font-weight:bold;}QPushButton:hover{background:#0873c4;}")
        self.connect_btn.clicked.connect(self._toggle_connection)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addStretch()
        self.conn_status = QLabel("● 未连接")
        self.conn_status.setStyleSheet("color:#e74c3c;font-weight:bold;font-size:13px;")
        conn_layout.addWidget(self.conn_status)
        layout.addWidget(conn_bar)

        # ── 升级配置 ──
        ne_group = QGroupBox("升级配置")
        ne_group.setStyleSheet(self._group_box_style)
        nfl = QFormLayout(ne_group)
        nfl.setSpacing(6)
        nfl.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.ne_combo = QComboBox()
        self.ne_combo.addItems(list(self.ne_configs.keys()))
        if self.ne_combo.count() > 0:
            self.ne_combo.setCurrentIndex(0)
        self.ne_combo.currentTextChanged.connect(self._on_ne_changed)
        self._init_done = False
        nfl.addRow("网元类型", self.ne_combo)

        self.ne_desc = QLabel("")
        self.ne_desc.setStyleSheet("font-size: 12px; color: #636e72; padding: 2px 0;")
        self.ne_desc.setWordWrap(True)
        nfl.addRow("", self.ne_desc)

        self.ne_detail = QLabel("")
        self.ne_detail.setStyleSheet("font-size: 11px; color: #0984e3; padding: 2px 0;")
        self.ne_detail.setWordWrap(True)
        nfl.addRow("", self.ne_detail)

        patch_row = QHBoxLayout()
        self.patch_path = QLineEdit()
        self.patch_path.setPlaceholderText("选择本地 *.tar.gz 补丁文件")
        patch_row.addWidget(self.patch_path)
        browse_btn = QPushButton("浏览...")
        browse_btn.setStyleSheet("""
            QPushButton { background:#0984e3; color:white; padding:6px 18px;
                border:none; border-radius:4px; font-size:13px; }
            QPushButton:hover { background:#0873c4; }
        """)
        browse_btn.clicked.connect(self._browse_patch)
        patch_row.addWidget(browse_btn)
        nfl.addRow("补丁文件", patch_row)

        layout.addWidget(ne_group)

        # ── 步骤概览 ──
        steps_group = QGroupBox("升级步骤")
        steps_group.setStyleSheet(self._group_box_style)
        sl = QVBoxLayout(steps_group)
        sl.setSpacing(2)

        self.step_labels = {}
        steps = [
            ("stop",        "1. 停止程序"),
            ("backup",      "2. 备份原路径"),
            ("upload",      "3. 上传补丁文件"),
            ("extract",     "4. 解压补丁"),
            ("post_extract","5. 解压后处理"),
            ("config_diff", "6. 配置文件对比"),
            ("chown",       "7. 修改文件属组"),
            ("license",     "8. License处理"),
            ("start",       "9. 启动程序"),
        ]
        steps_grid = QGridLayout()
        steps_grid.setSpacing(4)
        for i, (key, label) in enumerate(steps):
            lbl = QLabel(f"⬜ {label}")
            lbl.setStyleSheet("font-size: 13px; padding: 3px 6px;")
            self.step_labels[key] = lbl
            steps_grid.addWidget(lbl, i // 3, i % 3)
        sl.addLayout(steps_grid)
        layout.addWidget(steps_group)

        # ── 控制按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.start_btn = QPushButton("开始升级")
        self.start_btn.setStyleSheet("""
            QPushButton { background:#27ae60; color:white; font-weight:bold;
                padding:12px 48px; border:none; border-radius:6px; font-size:15px; }
            QPushButton:hover { background:#219a52; }
            QPushButton:disabled { background:#b2bec3; }
        """)
        self.start_btn.clicked.connect(self._start_upgrade)
        btn_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton { background:#e74c3c; color:white; font-weight:bold;
                padding:12px 32px; border:none; border-radius:6px; font-size:15px; }
            QPushButton:hover { background:#c0392b; }
            QPushButton:disabled { background:#b2bec3; }
        """)
        self.stop_btn.clicked.connect(self._stop_upgrade)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── 日志 ──
        log_group = QGroupBox("执行日志")
        log_group.setStyleSheet(self._group_box_style)
        ll = QVBoxLayout(log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Consolas", 10))
        self.log_output.setStyleSheet(
            "background: #1e1e1e; color: #d4d4d4; border: none; border-radius: 4px; padding: 8px;"
        )
        ll.addWidget(self.log_output)

        layout.addWidget(log_group, 1)

        self._on_ne_changed(self.ne_combo.currentText())

    def _on_ne_changed(self, ne_type):
        cfg = self.ne_configs.get(ne_type, {})
        self.ne_desc.setText(cfg.get("description", ""))
        detail_parts = []
        stop = cfg.get("stop", {})
        detail_parts.append(f"停止: {stop.get('method','?')}")
        detail_parts.append(f"配置对比: {len(cfg.get('config_files',[]))}个文件")
        lic = cfg.get("license", {})
        detail_parts.append(f"License: {'有' if lic.get('has_license') else '无'}")
        start = cfg.get("start", {})
        detail_parts.append(f"启动用户: {start.get('user','?')}")
        self.ne_detail.setText(" | ".join(detail_parts))
        if self._init_done and ne_type in ("CCF", "MGCF", "XCDR", "QUERY_data", "QUERY_opt", "cdrTools"):
            self._browse_patch()

    def _browse_patch(self):
        ne_type = self.ne_combo.currentText()
        default_dirs = {
            "CCF": r"F:\BaiduNetdiskDownload\Bangladesh\ICX_BTCL\实际版本\CCF",
            "MGCF": r"F:\BaiduNetdiskDownload\Bangladesh\ICX_BTCL\实际版本\MGCF",
            "XCDR": r"F:\BaiduNetdiskDownload\Bangladesh\ICX_BTCL\实际版本\CCF",
            "QUERY_data": r"F:\BaiduNetdiskDownload\Bangladesh\ICX_BTCL\实际版本\CCF",
            "QUERY_opt": r"F:\BaiduNetdiskDownload\Bangladesh\ICX_BTCL\实际版本\CCF",
            "cdrTools": r"F:\BaiduNetdiskDownload\Bangladesh\ICX_BTCL\实际版本\CCF",
        }
        keywords = {"CCF": "PSC", "MGCF": "MGCF", "XCDR": "XCDR", "QUERY_data": "QUERY", "QUERY_opt": "QUERY", "cdrTools": "cdrTools"}
        default_dir = default_dirs.get(ne_type, "")
        keyword = keywords.get(ne_type, "")

        fp, _ = QFileDialog.getOpenFileName(
            self, "选择补丁文件", default_dir, "补丁文件 (*.tar.gz *.tgz);;所有文件 (*)")
        if fp:
            basename = os.path.basename(fp)
            if keyword and keyword not in basename:
                QMessageBox.warning(
                    self, "补丁文件不匹配",
                    f"补丁文件与网元类型不匹配\n\n"
                    f"网元: {ne_type}\n文件: {basename}\n\n"
                    f"文件名应包含 \"{keyword}\""
                )
                return
            size = os.path.getsize(fp)
            size_str = self._fmt_size(size)
            self.patch_path.setText(fp)
            self._log(f"已选择补丁文件: {basename} ({size_str})")

    def _fmt_size(self, bytes_val):
        for unit in ("B", "KB", "MB", "GB"):
            if bytes_val < 1024:
                return f"{bytes_val:.1f}{unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f}TB"

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"<span style='color:#888'>{ts}</span> {msg}")
        self.log_output.ensureCursorVisible()

    def _update_step(self, step_key):
        for key, lbl in self.step_labels.items():
            if key == step_key:
                lbl.setText(f"🔄 {lbl.text()[2:]}")
                lbl.setStyleSheet("font-size: 13px; padding: 3px 6px; color: #0984e3; font-weight: bold;")
            elif "✅" in lbl.text():
                continue
            elif "❌" in lbl.text():
                continue
            else:
                lbl.setText(f"⬜ {lbl.text()[2:]}")
                lbl.setStyleSheet("font-size: 13px; padding: 3px 6px;")

    def _complete_step(self, step_key, success=True):
        mark = "✅" if success else "❌"
        for key, lbl in self.step_labels.items():
            if key == step_key:
                lbl.setText(f"{mark} {lbl.text()[2:]}")
                style = "color: #27ae60;" if success else "color: #e74c3c;"
                lbl.setStyleSheet(f"font-size: 13px; padding: 3px 6px; {style} font-weight: bold;")

    def _reset_steps(self):
        for key, lbl in self.step_labels.items():
            lbl.setText(f"⬜ {lbl.text()[2:]}")
            lbl.setStyleSheet("font-size: 13px; padding: 3px 6px;")

    def _load_hosts(self):
        try:
            if os.path.exists(IMS_HOSTS_PATH):
                with open(IMS_HOSTS_PATH, encoding="utf-8") as f:
                    return json.load(f)
            return []
        except:
            return []

    def _save_hosts(self):
        os.makedirs(os.path.dirname(IMS_HOSTS_PATH), exist_ok=True)
        with open(IMS_HOSTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self._hosts, f, ensure_ascii=False, indent=2)

    def _refresh_host_combo(self):
        self.host_combo.blockSignals(True)
        self.host_combo.clear()
        for h in self._hosts:
            label = f"{h.get('desc','?')} — {h['host']}:{h.get('port',22)} ({h['user']})"
            self.host_combo.addItem(label)
        self.host_combo.blockSignals(False)

    def _manage_hosts(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("管理主机")
        dlg.resize(520, 380)
        layout = QVBoxLayout(dlg)
        self._host_list = QListWidget()
        self._refresh_host_list()
        layout.addWidget(QLabel("已保存的主机:"))
        layout.addWidget(self._host_list)
        form = QFormLayout()
        form.setSpacing(6)
        ip_edit = QLineEdit(); ip_edit.setPlaceholderText("192.168.1.100")
        port_edit = QLineEdit("22"); port_edit.setFixedWidth(80)
        user_edit = QLineEdit("root")
        pwd_edit = QLineEdit(); pwd_edit.setEchoMode(QLineEdit.Password)
        desc_edit = QLineEdit(); desc_edit.setPlaceholderText("描述，如: 北京-核心-MGCF")
        form.addRow("IP:", ip_edit)
        p_row = QHBoxLayout(); p_row.addWidget(port_edit); p_row.addStretch()
        form.addRow("端口:", p_row)
        form.addRow("用户:", user_edit)
        form.addRow("密码:", pwd_edit)
        form.addRow("描述:", desc_edit)
        layout.addLayout(form)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加"); add_btn.setStyleSheet("QPushButton{background:#0984e3;color:white;padding:6px 16px;border:none;border-radius:4px;}")
        update_btn = QPushButton("更新"); update_btn.setStyleSheet("QPushButton{background:#f0f3f5;color:#333;border:1px solid #ccc;padding:6px 16px;border-radius:4px;}")
        del_btn = QPushButton("删除"); del_btn.setStyleSheet("QPushButton{background:#e74c3c;color:white;padding:6px 16px;border:none;border-radius:4px;}")
        btn_row.addWidget(add_btn); btn_row.addWidget(update_btn); btn_row.addWidget(del_btn); btn_row.addStretch()
        layout.addLayout(btn_row)
        def on_select():
            row = self._host_list.currentRow()
            if 0 <= row < len(self._hosts):
                h = self._hosts[row]
                ip_edit.setText(h["host"]); port_edit.setText(str(h.get("port",22)))
                user_edit.setText(h["user"]); pwd_edit.setText(h.get("pwd",""))
                desc_edit.setText(h.get("desc",""))
        self._host_list.currentRowChanged.connect(on_select)
        def on_add():
            if not ip_edit.text().strip(): return
            self._hosts.append(dict(host=ip_edit.text().strip(), port=int(port_edit.text().strip() or "22"), user=user_edit.text().strip() or "root", pwd=pwd_edit.text(), desc=desc_edit.text().strip()))
            self._save_hosts(); self._refresh_host_list(); self._refresh_host_combo()
            ip_edit.clear(); pwd_edit.clear(); desc_edit.clear(); port_edit.setText("22"); user_edit.setText("root")
        add_btn.clicked.connect(on_add)
        def on_update():
            row = self._host_list.currentRow()
            if row < 0 or not ip_edit.text().strip(): return
            self._hosts[row] = dict(host=ip_edit.text().strip(), port=int(port_edit.text().strip() or "22"), user=user_edit.text().strip() or "root", pwd=pwd_edit.text(), desc=desc_edit.text().strip())
            self._save_hosts(); self._refresh_host_list(); self._refresh_host_combo()
        update_btn.clicked.connect(on_update)
        def on_del():
            row = self._host_list.currentRow()
            if row < 0: return
            if QMessageBox.question(dlg, "确认", f"删除 {self._hosts[row]['host']}?") == QMessageBox.Yes:
                self._hosts.pop(row); self._save_hosts(); self._refresh_host_list(); self._refresh_host_combo()
        del_btn.clicked.connect(on_del)
        dlg.exec()

    def _refresh_host_list(self):
        if hasattr(self, '_host_list'):
            self._host_list.clear()
            for h in self._hosts:
                self._host_list.addItem(f"{h.get('desc','?')} — {h['host']}:{h.get('port',22)} ({h['user']})")

    def _on_host_selected(self, idx):
        if idx < 0 or idx >= len(self._hosts):
            return
        self._do_connect(idx)

    def _do_connect(self, idx):
        h = self._hosts[idx]
        self._conn_host = h["host"]
        self._conn_port = int(h.get("port", 22))
        self._conn_user = h["user"]
        self._conn_pwd = h.get("pwd", "")
        self._log(f"正在连接 {h.get('desc','?')} ({self._conn_host}:{self._conn_port}) ...")
        self.conn_status.setText("● 连接中...")
        self.conn_status.setStyleSheet("color:#f39c12;font-weight:bold;font-size:13px;")
        self.connect_btn.setEnabled(False)
        self.host_combo.setEnabled(False)

        class ConnThread(QThread):
            result = Signal(bool, str)
            def run(self):
                try:
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(self._conn_host, port=self._conn_port,
                                username=self._conn_user, password=self._conn_pwd,
                                timeout=1)
                    ssh.close()
                    self.result.emit(True, "")
                except Exception as e:
                    self.result.emit(False, str(e))

        self._conn_thread = ConnThread()
        self._conn_thread._conn_host = self._conn_host
        self._conn_thread._conn_port = self._conn_port
        self._conn_thread._conn_user = self._conn_user
        self._conn_thread._conn_pwd = self._conn_pwd
        self._conn_thread.result.connect(self._on_conn_result)
        self._conn_thread.start()

    def _on_conn_result(self, success, err_msg):
        self.connect_btn.setEnabled(True)
        self.host_combo.setEnabled(True)
        if success:
            self._connected = True
            self.connect_btn.setText("断开")
            self.connect_btn.setStyleSheet("QPushButton{background:#e74c3c;color:white;border:none;border-radius:4px;padding:6px 18px;font-size:13px;font-weight:bold;}QPushButton:hover{background:#c0392b;}")
            self.conn_status.setText("● 已连接")
            self.conn_status.setStyleSheet("color:#27ae60;font-weight:bold;font-size:13px;")
            self._log(f"✓ 连接成功 ({self._conn_host}:{self._conn_port})")
        else:
            self._connected = False
            self.connect_btn.setText("连接")
            self.connect_btn.setStyleSheet("QPushButton{background:#0984e3;color:white;border:none;border-radius:4px;padding:6px 18px;font-size:13px;font-weight:bold;}QPushButton:hover{background:#0873c4;}")
            self.conn_status.setText("● 不可达")
            self.conn_status.setStyleSheet("color:#e74c3c;font-weight:bold;font-size:13px;")
            self._log(f"✗ 连接失败: {err_msg}")

    def _toggle_connection(self):
        if getattr(self, '_connected', False):
            self._connected = False
            self.connect_btn.setText("连接")
            self.connect_btn.setStyleSheet("QPushButton{background:#0984e3;color:white;border:none;border-radius:4px;padding:6px 18px;font-size:13px;font-weight:bold;}QPushButton:hover{background:#0873c4;}")
            self.conn_status.setText("● 未连接")
            self.conn_status.setStyleSheet("color:#e74c3c;font-weight:bold;font-size:13px;")
            self._log("已断开连接")
        else:
            idx = self.host_combo.currentIndex()
            if idx < 0 or idx >= len(self._hosts):
                QMessageBox.warning(self, "提示", '请先添加目标主机（点"管理"按钮）')
                return
            self._do_connect(idx)

    def _start_upgrade(self):
        if not getattr(self, '_connected', False) or not hasattr(self, '_conn_host'):
            QMessageBox.warning(self, "提示", "请先选择并确认主机连接")
            return
        host = self._conn_host
        port = self._conn_port
        user = self._conn_user
        pwd = self._conn_pwd
        ne_type = self.ne_combo.currentText()
        ne_config = self.ne_configs.get(ne_type)
        if not ne_config:
            QMessageBox.warning(self, "提示", "请选择网元类型")
            return
        patch_local = self.patch_path.text().strip()
        if not patch_local or not os.path.isfile(patch_local):
            QMessageBox.warning(self, "提示", "请选择有效的补丁文件")
            return
        if not patch_local.endswith((".tar.gz", ".tgz")):
            reply = QMessageBox.question(
                self, "确认", "所选文件不是 .tar.gz 格式，是否继续？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self._reset_steps()
        self.log_output.clear()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._log("准备启动升级线程 ...")
        self._log(f"  目标: {host}:{port}")
        self._log(f"  网元: {ne_type} - {ne_config.get('description','')}")
        self._log(f"  文件: {os.path.basename(patch_local)}")

        self.worker = SSHWorker(host, port, user, pwd, ne_config, patch_local)
        self.worker.log_signal.connect(self._log)
        self.worker.step_signal.connect(self._update_step)
        self.worker.config_diff_signal.connect(self._on_config_diff)
        self.worker.kill_residual_signal.connect(self._on_kill_residual)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()
        self._log("升级线程已启动，请等待执行 ...")

    def _on_config_diff(self, diff_items):
        QTimer.singleShot(0, lambda: self._show_config_diff(diff_items))

    def _show_config_diff(self, diff_items):
        dlg = ConfigDiffDialog(diff_items, self)
        if dlg.exec() == QDialog.Accepted:
            self.worker.set_config_diff_result(dlg.results)
        else:
            self.worker.set_config_diff_result([])
            self._log("用户取消配置对比操作")

    def _on_kill_residual(self, remaining, pname):
        QTimer.singleShot(0, lambda: self._show_kill_residual(remaining, pname))

    def _show_kill_residual(self, remaining, pname):
        lines = "\n".join(f"  · {l}" for l in remaining[:20])
        if len(remaining) > 20:
            lines += f"\n  · ... 等共 {len(remaining)} 个"
        msg = (
            f"以下进程在 kill -9 后仍未终止：\n\n"
            f"关键字: {pname}\n"
            f"{lines}\n\n"
            f"请选择操作："
        )
        dlg = QMessageBox(self)
        dlg.setWindowTitle("⚠ 进程残留警告")
        dlg.setText(msg)
        dlg.setIcon(QMessageBox.Warning)
        continue_btn = dlg.addButton("继续升级", QMessageBox.AcceptRole)
        exit_btn = dlg.addButton("退出升级", QMessageBox.RejectRole)
        dlg.setDefaultButton(exit_btn)
        dlg.exec()
        self.worker.set_kill_decision(dlg.clickedButton() == continue_btn)
        if dlg.clickedButton() == exit_btn:
            self._log("用户选择退出升级（进程残留）")

    def _on_finished(self, status):
        if status == "success":
            self._complete_step("stop", True)
            self._complete_step("backup", True)
            self._complete_step("upload", True)
            self._complete_step("extract", True)
            self._complete_step("post_extract", True)
            self._complete_step("config_diff", True)
            self._complete_step("chown", True)
            self._complete_step("license", True)
            self._complete_step("start", True)
            QMessageBox.information(self, "完成", "✅ 网元升级全部完成！")
        elif status == "stopped":
            QMessageBox.information(self, "已停止", "用户已终止升级流程")
        else:
            QMessageBox.warning(self, "错误", "❌ 升级过程出现错误，请查看下方日志")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.worker = None

    def _stop_upgrade(self):
        if self.worker:
            self.worker.stop()
            self._log("用户请求停止升级，正在等待当前操作完成...")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = IMSEUpgradeTool()
    w.show()
    sys.exit(app.exec())
