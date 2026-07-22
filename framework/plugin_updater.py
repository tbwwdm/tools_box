# -*- coding: utf-8 -*-
"""
Plugin Updater: 从 GitHub 读取 plugins.json，
对比本地插件版本，有更新则下载对应 .pyd 文件替换。
支持逐插件检查、进度回调。
"""
import json
import os
import sys
import logging
import urllib.request
import urllib.error
import shutil
from typing import Optional, Callable

logger = logging.getLogger("toolbox")

ProgressCallback = Callable[[int, int], None]  # (downloaded_bytes, total_bytes)


class PluginUpdater:
    """插件自动更新器。"""

    def __init__(self, version_url: str, plugins_dir: str = None,
                 timeout: int = 15):
        """
        Args:
            version_url: GitHub 上 plugins.json 的 RAW 地址
            plugins_dir: 本地插件目录（None=自动）
            timeout:     HTTP 请求超时（秒）
        """
        self._version_url = version_url
        self._plugins_dir = plugins_dir or self._default_plugins_dir()
        self._timeout = timeout
        self._update_results: list[dict] = []

    @staticmethod
    def _default_plugins_dir() -> str:
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "plugins")

    # ── 远程 plugins.json 解析 ─────────────────────────────

    def fetch_remote_manifest(self) -> Optional[dict]:
        """从 GitHub 获取远程插件清单。"""
        try:
            req = urllib.request.Request(
                self._version_url,
                headers={"User-Agent": "Toolbox-Updater/1.0"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            logger.info("Fetched remote manifest: %d plugins",
                        len(data.get("plugins", [])))
            return data
        except urllib.error.HTTPError as exc:
            logger.warning("HTTP %d fetching manifest: %s", exc.code, exc.reason)
        except urllib.error.URLError as exc:
            logger.warning("URL error fetching manifest: %s", exc.reason)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to parse manifest: %s", exc)
        return None

    # ── 本地版本读写 ────────────────────────────────────────

    def get_local_version(self, plugin_name: str) -> Optional[str]:
        """读取本地插件的版本标记文件。"""
        version_file = os.path.join(self._plugins_dir, f".{plugin_name}.version")
        if os.path.isfile(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        return None

    def set_local_version(self, plugin_name: str, version: str):
        """写入本地版本标记文件。"""
        version_file = os.path.join(self._plugins_dir, f".{plugin_name}.version")
        os.makedirs(self._plugins_dir, exist_ok=True)
        with open(version_file, "w", encoding="utf-8") as f:
            f.write(version.strip())

    # ── 检查单个插件更新 ───────────────────────────────────

    def check_plugin_update(self, plugin_name: str,
                            manifest: dict = None) -> Optional[dict]:
        """检查指定插件是否有更新。

        Args:
            plugin_name: 插件模块名
            manifest: 远程清单（None=自动拉取）

        Returns:
            {name, local_version, remote_version, download_url, display_name}
            无更新或失败返回 None
        """
        if manifest is None:
            manifest = self.fetch_remote_manifest()
        if manifest is None:
            return None

        for info in manifest.get("plugins", []):
            if info.get("name") != plugin_name:
                continue
            remote_ver = info.get("version", "0.0.0")
            local_ver = self.get_local_version(plugin_name)

            if local_ver != remote_ver:
                return {
                    "name": plugin_name,
                    "local_version": local_ver or "(not installed)",
                    "remote_version": remote_ver,
                    "download_url": info.get("download_url", ""),
                    "display_name": info.get("display_name", plugin_name),
                }
            return None  # 版本一致
        return None  # 未在远程清单中找到

    # ── 带进度回调的下载 ──────────────────────────────────

    def download_plugin(self, name: str, download_url: str,
                        progress_callback: ProgressCallback = None) -> bool:
        """下载单个插件 .pyd 文件，支持进度回调。

        Args:
            name: 插件模块名
            download_url: .pyd 下载 URL
            progress_callback: fn(downloaded, total)

        Returns:
            True 成功 / False 失败
        """
        if not download_url:
            logger.error("No download URL for plugin '%s'", name)
            return False

        os.makedirs(self._plugins_dir, exist_ok=True)
        target_path = os.path.join(self._plugins_dir, f"{name}.pyd")
        tmp_path = os.path.join(self._plugins_dir, f".{name}.download.tmp")

        try:
            logger.info("Downloading plugin '%s' from %s ...", name, download_url)
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "Toolbox-Updater/1.0"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 8192
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback(downloaded, total)

            # 原子替换
            if os.path.exists(target_path):
                os.remove(target_path)
            shutil.move(tmp_path, target_path)
            logger.info("Downloaded plugin '%s' -> %s", name, target_path)
            return True

        except (urllib.error.HTTPError, urllib.error.URLError,
                OSError, Exception) as exc:
            logger.error("Failed to download plugin '%s': %s", name, exc)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return False

    # ── 批量操作 ───────────────────────────────────────────

    def check_updates(self) -> list[dict]:
        """检查所有插件更新。"""
        manifest = self.fetch_remote_manifest()
        if manifest is None:
            return []

        updates = []
        for info in manifest.get("plugins", []):
            name = info.get("name")
            remote_ver = info.get("version", "0.0.0")
            local_ver = self.get_local_version(name)
            if local_ver != remote_ver:
                updates.append({
                    "name": name,
                    "local_version": local_ver or "(not installed)",
                    "remote_version": remote_ver,
                    "download_url": info.get("download_url", ""),
                    "display_name": info.get("display_name", name),
                })
        self._update_results = updates
        return updates

    def apply_updates(self, updates: list[dict] = None,
                      progress_callback: ProgressCallback = None) -> list[str]:
        """下载并版本标记所有待更新插件。"""
        if updates is None:
            updates = self.check_updates()
        successful = []
        for i, item in enumerate(updates):
            version = item.get("remote_version", "0.0.0")

            def _cb(d, t, idx=i):
                if progress_callback:
                    offset = idx
                    total_items = len(updates)
                    progress_callback(d + offset * t, total_items * t if t else 0)

            ok = self.download_plugin(item["name"], item["download_url"],
                                      progress_callback=_cb)
            if ok:
                self.set_local_version(item["name"], version)
                successful.append(item["name"])
        return successful
