# -*- coding: utf-8 -*-
'''启动编排：日志、隐藏控制台、提权重启、单实例锁、main。'''
import os
import sys
import ctypes
import logging
import tkinter as tk

# 项目根目录（本包 autoclaw_mod 的上一级）
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logger = logging.getLogger("autoclaw")

from .app import App
from .win32ops import is_elevated, relaunch_as_admin
from .notify import windows_notify  # noqa: F401

def acquire_single_instance():
    """Windows 命名互斥锁，保证进程唯一。

    返回锁句柄（须全程持有）；若已存在其它实例则返回 None，调用方应退出。
    失败时返回非 None 的空句柄，不阻塞启动（宽松降级）。"""
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False,
            "Local\\AutoClawContinue_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
            return None
        return handle
    except Exception:
        logger.exception("创建单实例锁失败，降级为允许多开")
        return True   # 宽松降级，非 None


def setup_logging():
    """把运行日志写入脚本同目录的 autoclaw.log，便于排查启动/托盘等问题。"""
    try:
        logfile = os.path.join(PROJECT_DIR, "autoclaw.log")
        handler = logging.FileHandler(logfile, encoding="utf-8")
    except Exception:
        return
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        root.addHandler(handler)


def hide_console():
    """隐藏本程序附带的黑色终端（控制台）窗口。

    仅对 python.exe 运行时附带的控制台生效；GetConsoleWindow 返回 0（如
    已用 pythonw.exe 或已打包为窗口程序）时不产生副作用。"""
    try:
        cw = ctypes.windll.kernel32.GetConsoleWindow()
        if cw:
            ctypes.windll.user32.ShowWindow(cw, 0)   # 0 = SW_HIDE
    except Exception:
        pass


def main():
    setup_logging()             # 先落库日志，任何异常都可追溯
    hide_console()              # 尽早隐藏黑框终端，减少闪烁
    logger.info("AutoClaw 自动继续启动")
    # 若当前前台可能是管理员进程（UIPI 前台锁定），普通权限无法把 AutoClaw 切到前台。
    # 未提权时自动以管理员身份重启一次，保证激活与输入有效。
    if not is_elevated() and relaunch_as_admin():
        logger.info("将以管理员身份重启")
        return
    # 单实例锁：放在提权判断之后，避免与管理员提权重启相互抢占锁；
    # 句柄保存在 main 局部变量中，mainloop 期间一直被持有，进程退出时才释放
    _mutex = acquire_single_instance()
    if _mutex is None:
        logger.info("已有一个实例在运行，本次启动直接退出")
        return
    root = tk.Tk()
    root.withdraw()             # 创建后立即隐藏，避免启动瞬间闪现 UI
    root.update_idletasks()
    App(root)
    root.mainloop()
