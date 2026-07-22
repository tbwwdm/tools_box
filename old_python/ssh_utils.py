# -*- coding: utf-8 -*-
"""Shared SSH connection utilities for toolbox modules."""
import os, sys, json, logging

import paramiko

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))


def load_hosts():
    cfg = os.path.join(BASE_DIR, "config", "hosts.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def create_ssh_client(host, port, user, pwd, timeout=10):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, int(port), user, pwd, timeout=timeout)
    return c


def ssh_exec(client, cmd, timeout=10):
    chan = client.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    out = chan.makefile("rb", -1).read()
    err = chan.makefile_stderr("rb", -1).read().decode("utf-8", errors="replace").strip()
    for enc in ("utf-8", "gbk"):
        try:
            return out.decode(enc).strip(), err
        except UnicodeDecodeError:
            continue
    return out.decode("utf-8", errors="replace").strip(), err


def exec_command(host, port, user, pwd, cmd, timeout=10):
    c = create_ssh_client(host, port, user, pwd)
    try:
        return ssh_exec(c, cmd, timeout)
    finally:
        c.close()
