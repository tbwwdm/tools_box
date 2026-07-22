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
                 config_path: str = None, timeout: int = 15):
        """
        Args:
            version_url: GitHub 上 plugins.json 的 RAW 地址
            plugins_dir: 本地插件目录（None=自动）
            config_path: 本地 config/plugins.json 路径（None=从 plugins_dir 推导）
            timeout:     HTTP 请求超时（秒）
        """
        self._version_url = version_url
        self._plugins_dir = plugins_dir or self._default_plugins_dir()
        self._config_path = config_path
        self._timeout = timeout
        self._update_results: list[dict] = []

    @staticmethod
    def _default_plugins_dir() -> str:
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "plugins")

    # ── 下载 URL 自动生成 ─────────────────────────────────

    @staticmethod
    def _build_download_url(plugin_name: str, version: str) -> str:
        """根据插件名和版本自动生成 GitHub Release 下载链接。"""
        return (
            f"https://github.com/LegendaryScriptGenew/"
            f"tools_box/releases/download/v{version}/{plugin_name}.pyd"
        )

    # ── 远程 plugins.json 解析 ─────────────────────────────

    def fetch_remote_manifest(self) -> Optional[dict]:
        """从 GitHub 获取远程插件清单。"""
        try:
            # 加随机参数绕过 CDN 缓存
            import random
            url = f"{self._version_url}?_={random.randint(0, 999999)}"
            req = urllib.request.Request(
                url,
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

    # ── 本地版本读写（基于 config/plugins.json） ───────────

    @property
    def _local_config_path(self) -> str:
        """config/plugins.json 路径。"""
        if self._config_path:
            return self._config_path
        base = os.path.dirname(self._plugins_dir)  # plugins/ 的上一级
        return os.path.join(base, "config", "plugins.json")

    def get_local_version(self, plugin_name: str) -> Optional[str]:
        """从本地 config/plugins.json 中读取插件版本。"""
        cfg_path = self._local_config_path
        if not os.path.isfile(cfg_path):
            logger.warning("Local config not found: %s", cfg_path)
            return None
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for p in data.get("plugins", data if isinstance(data, list) else []):
                if isinstance(p, dict) and p.get("name") == plugin_name:
                    return p.get("version")
        except Exception as exc:
            logger.warning("Failed to read local config: %s", exc)
        return None

    def set_local_version(self, plugin_name: str, version: str):
        """更新本地 config/plugins.json 中的插件版本。"""
        cfg_path = self._local_config_path
        if not os.path.isfile(cfg_path):
            logger.warning("Local config not found: %s", cfg_path)
            return
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for p in data.get("plugins", data if isinstance(data, list) else []):
                if isinstance(p, dict) and p.get("name") == plugin_name:
                    p["version"] = version
                    break
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            logger.info("Updated local version: %s -> %s", plugin_name, version)
        except Exception as exc:
            logger.warning("Failed to update local config: %s", exc)

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
                    "download_url": self._build_download_url(plugin_name, remote_ver),
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
                    "download_url": self._build_download_url(name, remote_ver),
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
