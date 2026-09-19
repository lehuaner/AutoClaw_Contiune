# -*- coding: utf-8 -*-
'''Windows 系统通知（Toast）。可选依赖 winotify，缺失时静默跳过。'''
def windows_notify(title, message):
    """弹出 Windows 系统通知（Toast）。

    使用可选依赖 winotify；未安装时静默跳过，不影响主功能。"""
    try:
        from winotify import Notification
        Notification(app_id="AutoClaw 自动继续",
                     title=title, msg=message).show()
    except Exception:
        pass
