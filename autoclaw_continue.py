# -*- coding: utf-8 -*-
"""AutoClaw 自动"继续"工具 —— 启动入口。

程序已按模块拆分到 autoclaw_mod/ 包：
  - win32ops.py : win32 / 键盘 / 鼠标 / 剪贴板 / 窗口 助手（ctypes）
  - logwatcher.py: gateway.log 增量解析
  - notify.py    : Windows 系统通知
  - app.py       : 主界面 + 监控 / 自动"继续"逻辑
  - entry.py     : 启动编排（日志 / 隐藏控制台 / 提权重启 / 单实例锁 / main）

依赖：Python 3 自带 tkinter；win32 操作用 ctypes（无需第三方库）。
运行：python autoclaw_continue.py（推荐双击 autoclaw_continue.pyw）
"""
from autoclaw_mod.entry import main

if __name__ == "__main__":
    main()