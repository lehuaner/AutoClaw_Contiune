# -*- coding: utf-8 -*-
"""AutoClaw 自动"继续"工具 —— 模块化包。

目录结构
--------
- win32ops.py : win32 / 键盘 / 鼠标 / 剪贴板 / 窗口 助手（纯 ctypes，无外部依赖）
- logwatcher.py: gateway.log 增量解析，提取响应状态码及所属会话
- notify.py    : Windows 系统通知（Toast）
- app.py       : 主界面 + 监控 / 自动"继续"逻辑（大部分业务）
- entry.py     : 启动编排（日志、提权重启、单实例锁、main）
"""

# AutoClaw（桌面端应用）版本信息：本工具针对该版本实测制作 / 适配。
# 若 AutoClaw 升级导致组件映射或日志格式变化，需同步更新 AUTO 定位与适配参数。
AUTOCLAW_VERSION = "1.18.4"
AUTOCLAW_APP_NAME = "AutoClaw"