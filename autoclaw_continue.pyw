# -*- coding: utf-8 -*-
"""pythonw 无控制台启动入口。

双击本文件（或用 pythonw.exe 运行）即在后台启动 AutoClaw 自动继续，
不会出现任何黑色终端窗口。内部直接引入 autoclaw_continue.py 主程序。

注意：请用本文件启动，而不要用 `python autoclaw_continue.py`
（python.exe 是控制台程序，必然有终端；pythonw/.pyw 才没有）。"""
import os
import runpy

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "autoclaw_continue.py")
runpy.run_path(_SRC, run_name="__main__")