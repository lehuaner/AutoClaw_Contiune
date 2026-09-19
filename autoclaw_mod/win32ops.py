# -*- coding: utf-8 -*-
'''win32 助手：键盘 / 鼠标 / 剪贴板 / 窗口。全部基于 ctypes，无需 pywin32。'''
import ctypes
import time
import os
import sys

# win32 助手（ctypes），不需要 pywin32
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.SetProcessDPIAware()

# 常量
GWL_HINSTANCE = -6
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
VK_RETURN = 0x0D
VK_CONTROL = 0x11
VK_A = 0x41
VK_V = 0x56
VK_MENU = 0x12

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
HARDWAREID = 0
GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13

# 剪贴板相关的 64 位句柄/指针必须显式声明，否则被截断为 32 位
user32.OpenClipboard.argtypes = [ctypes.c_void_p]
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [ctypes.c_uint]
user32.GetClipboardData.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]


# 完整 INPUT 结构（64 位下必须 40 字节，union 按 MOUSEINPUT 对齐）。
# 结构体大小不对时 SendInput 会返回 0，键盘事件完全发不出去。
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUTS(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", INPUTUNION)]


assert ctypes.sizeof(INPUTS) == 40, "INPUT 结构大小应为 40"


def send_key(vk, down=True):
    """发送单个按键事件。"""
    k = KEYBDINPUT(wVk=vk, wScan=0,
                   dwFlags=0 if down else KEYEVENTF_KEYUP,
                   time=0, dwExtraInfo=None)
    inp = INPUTS(type=INPUT_KEYBOARD, u=INPUTUNION(ki=k))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUTS))


def type_unicode_char(ch):
    """通过 UNICODE 扫描码输入一个字符（支持中文）。"""
    n = ord(ch)
    for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
        k = KEYBDINPUT(wVk=0, wScan=n, dwFlags=flags, time=0, dwExtraInfo=None)
        inp = INPUTS(type=INPUT_KEYBOARD, u=INPUTUNION(ki=k))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUTS))


def paste_unicode(text):
    """把文本放入系统剪贴板（Unicode），再发送 Ctrl+V 粘贴。

    相比逐字 UNICODE 键事件，剪贴板粘贴对 Electron/WebView 类输入框更可靠，
    中文也不易丢失。"""
    data = text.encode("utf-16-le") + b"\x00\x00"
    if user32.OpenClipboard(None):
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if h:
            p = kernel32.GlobalLock(h)
            if p:
                ctypes.memmove(p, data, len(data))
                kernel32.GlobalUnlock(h)
                user32.SetClipboardData(CF_UNICODETEXT, h)
        user32.CloseClipboard()
    # Ctrl+V
    send_key(VK_CONTROL, True)
    send_key(VK_V, True)
    send_key(VK_V, False)
    send_key(VK_CONTROL, False)


def set_cursor_pos(x, y):
    user32.SetCursorPos(int(x), int(y))


def mouse_click():
    """左键单击当前鼠标位置（按下+抬起）。"""
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


def find_windows_by_title(needle):
    """返回所有顶层可见窗口的 (hwnd, 标题, 类名)。"""
    result = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_cb(hwnd, lParam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        title = buf.value
        cls = cls_buf.value
        if needle.lower() in title.lower() or needle.lower() in cls.lower():
            result.append((hwnd, title, cls))
        return True

    user32.EnumWindows(enum_cb, 0)
    return result


def get_window_rect(hwnd):
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long)]
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def set_foreground(hwnd, retries=5):
    """把窗口置顶激活，最多重试 retries 次，成功后返回 True。

    若当前前台窗口属于提权(管理员)进程，普通权限进程无法抢走前台
    （UIPI 前台锁定），此时必须让本程序也以管理员身份运行。"""
    for _ in range(retries):
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        me = user32.GetWindowThreadProcessId(fg, None)
        tgt = user32.GetWindowThreadProcessId(hwnd, None)
        if me != tgt:
            user32.AttachThreadInput(me, tgt, True)
            user32.BringWindowToTop(hwnd)
        # ALT 键技巧：模拟一次用户按键，绕过系统的前台锁定限制
        send_key(VK_MENU, True)
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        send_key(VK_MENU, False)
        if me != tgt:
            user32.AttachThreadInput(me, tgt, False)
        time.sleep(0.3)
        if user32.GetForegroundWindow() == hwnd:
            return True
    return False


def is_elevated():
    """当前进程是否以管理员权限运行。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """以管理员权限重新启动本脚本；成功返回 True（随后应退出当前进程）。"""
    try:
        import sys
        # 提权需重启的是项目入口脚本，而非本模块（本模块在 autoclaw_mod/ 内）
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(project_dir, "autoclaw_continue.py")
        args = " ".join('"%s"' % a for a in sys.argv[1:])
        params = ('"%s"' % script) if not args else ('"%s" %s' % (script, args))
        code = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1)
        return int(code) > 32
    except Exception:
        return False


# ---------------------------------------------------------------------------
