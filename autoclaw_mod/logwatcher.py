# -*- coding: utf-8 -*-
'''gateway.log 增量解析：提取响应状态码 (status) 及所属 代理/会话。'''
import os
from datetime import datetime

# 日志监控
# ---------------------------------------------------------------------------
class LogWatcher:
    """增量读取 gateway.log，提取响应状态码及所属会话。"""

    def __init__(self, path):
        self.path = path
        self.pos = 0

    def scan(self):
        """返回新增的 (状态码, 代理, 会话, 时间戳, 行) 列表；文件被截断/切换则重定位。

        时间戳解析自该行行首的 ISO 时间（如 2026-09-16T13:07:32.040+08:00），
        用于判断限流错误的时效，解析失败则取 None。"""
        new_items = []
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return new_items
        if size < self.pos:          # 日志被重置/轮转
            self.pos = 0
        if size == self.pos:
            return new_items
        with open(self.path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(self.pos)
            data = f.read()
            self.pos = f.tell()
        for line in data.splitlines():
            if "AutoClawRequestTrace" not in line:
                continue
            if "response" not in line:
                continue
            # 提取 status=NNN
            try:
                status = int(line.split("status=")[1].split(" ")[0])
            except (IndexError, ValueError):
                continue
            agent = ""
            if "xAgentId=" in line:
                try:
                    agent = line.split("xAgentId=")[1].split(" ")[0]
                except (IndexError, ValueError):
                    agent = ""
            session = ""
            if "xSessionId=" in line:
                try:
                    session = line.split("xSessionId=")[1].split(" ")[0]
                except (IndexError, ValueError):
                    session = ""
            ts = None
            try:
                ts = datetime.fromisoformat(line.split(" ")[0]).timestamp()
            except Exception:
                pass
            new_items.append((status, agent, session, ts, line))
        return new_items


# ---------------------------------------------------------------------------
# 主程序：界面 + 执行
# ---------------------------------------------------------------------------
