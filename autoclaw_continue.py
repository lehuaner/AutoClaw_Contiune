# -*- coding: utf-8 -*-
"""
AutoClaw 自动"继续"工具
========================
场景：AutoClaw（zcode 编码代理）运行中会话被后端限流，界面出现"当前使用人数较多"
类提示并停止。本程序监控其本地日志 gateway.log，一旦发现疑似限流的请求状态码
（默认 403，可配 429/503 等），就自动激活 AutoClaw 窗口、聚焦输入框、键入
"继续"并回车发送，让会话继续跑。

依赖：Python 3 本体自带 tkinter；win32 操作用 ctypes（无需第三方库）。
运行：python autoclaw_continue.py
"""
import ctypes
import threading
import time
import os
import json
import urllib.parse
import re
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# 系统托盘（pystray 可选，缺失时不影响主功能）
try:
    import pystray
    from PIL import Image, ImageDraw
    _HAS_TRAY = True
except Exception:
    _HAS_TRAY = False

# uiautomation 用于 UIA 可访问性树定位输入框（优先）；缺失时回退坐标模拟。
try:
    import uiautomation as uia
except ImportError:
    uia = None

# ---------------------------------------------------------------------------
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
        script = os.path.abspath(__file__)
        args = " ".join('"%s"' % a for a in sys.argv[1:])
        params = ('"%s"' % script) if not args else ('"%s" %s' % (script, args))
        code = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1)
        return int(code) > 32
    except Exception:
        return False


# ---------------------------------------------------------------------------
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
class App:
    LOG_PATH_DEFAULT = os.path.expandvars(
        r"%USERPROFILE%\.openclaw-autoclaw\logs\gateway.log")
    WINDOW_MATCH_DEFAULT = "AutoClaw"
    # 参数持久化文件：与本程序同目录的 JSON，启动时回填、开始时保存
    CONFIG_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "autoclaw_continue.json")

    def __init__(self, root):
        self.root = root
        self.running = False
        self.monitor_thread = None
        self.last_trigger_time = {}
        self.log_counter = 0
        self.session_stats = {}      # (agent,session) -> [总请求, 403数, 最近时间]
        self.view_raw = False      # False=程序日志/限流动态；True=原始 gateway.log
        # UIA 缓存：避免每次操作重复枚举窗口/全树遍历（性能优化，方案A）
        self._uia_cache = {}        # {key: value}，key 见 _uia_get_cached
        self.raw_pos = None        # 原始日志增量读取偏移
        root.title("AutoClaw 自动继续")
        root.resizable(False, False)

        self._build_ui()
        self.cfg = self._default_cfg()
        self._load_cfg_file()       # 用磁盘上保存的参数回填 UI 控件（若有）
        self._load_from_ui()
        self._stats_dirty = False       # 后台线程置位，主线程轮询刷新树
        self._seed_from_log()           # 打开即同步播种，树不再为空
        self._append_log("就绪。设置参数后点击「开始监控」。")
        self.root.after(500, self._poll_tree)   # 启动主线程树刷新轮询
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)  # 关闭→托盘
        self.root.bind("<Unmap>", self._on_minimize)   # 最小化→托盘
        self._tray = None
        self._setup_tray()

    # ---------------- UI ----------------
    def _default_cfg(self):
        return {
            "log_path": self.LOG_PATH_DEFAULT,
            "status_codes": "403",
            "window_match": self.WINDOW_MATCH_DEFAULT,
            "target_agent": "",       # 留空=监控全部会话；可填指定代理名精确过滤
            "interval": 5,
            "continue_text": "继续",
            "send_enter": True,
            "cooldown": 60,
            "error_max_age": 300,     # 限流错误时效阈值（秒）：超过此时间的错误不触发自动继续
            "input_ratio": 0.58,       # 输入框在窗口中的水平比例（实测校准）
            "input_offset_y": -64,     # 距窗口底部的向上偏移（像素，实测校准）
        }

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self.root, padding=10)
        frm.grid(sticky="nsew")

        # 日志路径
        ttk.Label(frm, text="日志文件").grid(row=0, column=0, sticky="w", **pad)
        self.var_log = tk.StringVar(value=self.LOG_PATH_DEFAULT)
        ttk.Entry(frm, textvariable=self.var_log, width=64).grid(
            row=0, column=1, columnspan=3, sticky="we", **pad)

        # 状态码、窗口匹配
        ttk.Label(frm, text="限流状态码").grid(row=1, column=0, sticky="w", **pad)
        self.var_codes = tk.StringVar(value="403")
        ttk.Entry(frm, textvariable=self.var_codes, width=12).grid(
            row=1, column=1, sticky="w", **pad)
        ttk.Label(frm, text="窗口标题匹配").grid(row=1, column=2, sticky="w", **pad)
        self.var_wmatch = tk.StringVar(value=self.WINDOW_MATCH_DEFAULT)
        ttk.Entry(frm, textvariable=self.var_wmatch, width=16).grid(
            row=1, column=3, sticky="w", **pad)

        # 检测间隔、冷却
        ttk.Label(frm, text="检测间隔(秒)").grid(row=2, column=0, sticky="w", **pad)
        self.var_interval = tk.StringVar(value="5")
        ttk.Spinbox(frm, from_=1, to=120, textvariable=self.var_interval,
                    width=8).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(frm, text="目标代理(留空=全部)").grid(row=3, column=0, sticky="w", **pad)
        self.var_agent = tk.StringVar(value="honor")
        ttk.Entry(frm, textvariable=self.var_agent, width=10).grid(
            row=3, column=1, sticky="w", **pad)
        ttk.Label(frm, text="冷却(秒)").grid(row=3, column=2, sticky="w", **pad)
        self.var_cooldown = tk.StringVar(value="60")
        ttk.Spinbox(frm, from_=0, to=3600, textvariable=self.var_cooldown,
                    width=8).grid(row=3, column=3, sticky="w", **pad)

        # 继续文本、回车
        ttk.Label(frm, text="继续文本").grid(row=4, column=0, sticky="w", **pad)
        self.var_text = tk.StringVar(value="继续")
        ttk.Entry(frm, textvariable=self.var_text, width=16).grid(
            row=4, column=1, sticky="w", **pad)
        self.var_enter = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="输入后回车发送", variable=self.var_enter).grid(
            row=4, column=2, columnspan=2, sticky="w", **pad)

        # 限流错误时效阈值（秒）
        ttk.Label(frm, text="错误时效(秒)").grid(row=5, column=0, sticky="w", **pad)
        self.var_maxage = tk.StringVar(value="300")
        ttk.Spinbox(frm, from_=0, to=86400, increment=30,
                    textvariable=self.var_maxage, width=8).grid(
            row=5, column=1, sticky="w", **pad)
        ttk.Label(frm, text="超过该时间的限流错误不触发自动继续").grid(
            row=5, column=2, columnspan=2, sticky="w", **pad)

        # 输入框位置（自动 + 手动比例）
        ttk.Label(frm, text="输入框水平比例").grid(row=6, column=0, sticky="w", **pad)
        self.var_ratio = tk.StringVar(value="0.5")
        ttk.Spinbox(frm, from_=0.1, to=0.9, increment=0.05,
                    textvariable=self.var_ratio, width=8).grid(
            row=6, column=1, sticky="w", **pad)
        ttk.Label(frm, text="距底部偏移Y").grid(row=6, column=2, sticky="w", **pad)
        self.var_offy = tk.StringVar(value="-60")
        ttk.Spinbox(frm, from_=-400, to=-10, increment=10,
                    textvariable=self.var_offy, width=8).grid(
            row=6, column=3, sticky="w", **pad)

        # 控制按钮
        self.btn_start = ttk.Button(frm, text="开始监控", command=self.toggle)
        self.btn_start.grid(row=7, column=0, columnspan=2, sticky="we", **pad)
        self.btn_test = ttk.Button(frm, text="测试继续动作",
                                   command=self.test_action)
        self.btn_test.grid(row=7, column=2, columnspan=2, sticky="we", **pad)

        # 状态与日志
        self.var_state = tk.StringVar(value="未运行")
        ttk.Label(frm, textvariable=self.var_state,
                  foreground="#b45309").grid(row=8, column=0, columnspan=4,
                                             sticky="w", **pad)
        self.txt_log = tk.Text(frm, height=12, width=78, state="disabled")
        self.txt_log.grid(row=9, column=0, columnspan=4, sticky="nsew", **pad)
        self.btn_view = ttk.Button(frm, text="切换到原始日志",
                                   command=self.toggle_view)
        self.btn_view.grid(row=10, column=0, columnspan=2, sticky="w", **pad)
        self.btn_clear = ttk.Button(frm, text="清空日志",
                                    command=self.clear_log)
        self.btn_clear.grid(row=10, column=2, columnspan=2, sticky="e", **pad)

        # 会话分类树（agent -> session，含 403 计数）
        ttk.Label(frm, text="会话监控（代理 → 会话）").grid(
            row=11, column=0, columnspan=4, sticky="w", **pad)
        self.tree = ttk.Treeview(frm, columns=("total", "err", "latest"),
                                 show="tree headings", height=6)
        self.tree.heading("#0", text="代理 / 会话")
        self.tree.heading("total", text="请求")
        self.tree.heading("err", text="403")
        self.tree.heading("latest", text="最新请求")
        self.tree.column("total", width=50, anchor="center")
        self.tree.column("err", width=40, anchor="center")
        self.tree.column("latest", width=100, anchor="center")
        self.tree.grid(row=12, column=0, columnspan=4, sticky="nsew", **pad)
        self.tree_agents = {}   # agent -> tree item id
        self.tree_sessions = {} # (session) -> tree item id
        self.tree.bind("<Double-1>", self._on_tree_double)

    # ---------------- 配置读取 ----------------
    def _load_from_ui(self):
        try:
            self.cfg["log_path"] = self.var_log.get().strip() or self.LOG_PATH_DEFAULT
            self.cfg["status_codes"] = {int(s.strip())
                                        for s in self.var_codes.get().split(",")
                                        if s.strip().isdigit()}
            self.cfg["window_match"] = self.var_wmatch.get().strip() or self.WINDOW_MATCH_DEFAULT
            self.cfg["target_agent"] = self.var_agent.get().strip()
            self.cfg["interval"] = max(1, int(float(self.var_interval.get() or 5)))
            self.cfg["cooldown"] = max(0, int(float(self.var_cooldown.get() or 60)))
            self.cfg["continue_text"] = self.var_text.get() or "继续"
            self.cfg["send_enter"] = self.var_enter.get()
            self.cfg["error_max_age"] = max(
                0, int(float(self.var_maxage.get() or 300)))
            self.cfg["input_ratio"] = float(self.var_ratio.get() or 0.5)
            self.cfg["input_offset_y"] = int(float(self.var_offy.get() or -60))
        except Exception as e:
            raise ValueError("参数有误：%s" % e)

    # ---------------- 参数持久化 ----------------
    def _load_cfg_file(self):
        """读取磁盘配置文件，把保存过的参数回填到 UI 控件。

        任何解析失败都静默忽略（视为首次运行，保持默认值）。"""
        try:
            with open(self.CONFIG_PATH, encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            return
        if not isinstance(saved, dict):
            return
        mapping = {
            "log_path": self.var_log,
            "status_codes": self.var_codes,
            "window_match": self.var_wmatch,
            "target_agent": self.var_agent,
            "interval": self.var_interval,
            "cooldown": self.var_cooldown,
            "continue_text": self.var_text,
            "send_enter": self.var_enter,
            "error_max_age": self.var_maxage,
            "input_ratio": self.var_ratio,
            "input_offset_y": self.var_offy,
        }
        for key, var in mapping.items():
            if key not in saved:
                continue
            val = saved[key]
            if key == "status_codes" and isinstance(val, (list, tuple)):
                val = ",".join(str(x) for x in val)
            try:
                if isinstance(var, tk.BooleanVar):
                    var.set(bool(val))
                else:
                    var.set(str(val))
            except Exception:
                pass

    def _save_cfg(self):
        """把当前 self.cfg 写入磁盘配置文件（status_codes 集合转列表）。"""
        try:
            data = dict(self.cfg)
            codes = data.get("status_codes", set())
            if isinstance(codes, (set, frozenset)):
                data["status_codes"] = sorted(codes)
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close_request(self):
        """点击关闭按钮：有托盘则隐藏到托盘（后台驻留），无托盘则真正退出。"""
        if _HAS_TRAY:
            self._hide_to_tray()
        else:
            self._on_close()

    def _on_minimize(self, event=None):
        """窗口最小化：隐藏到系统托盘，取消任务栏按钮。"""
        if not _HAS_TRAY:
            return
        # tkinter 最小化触发 <Unmap>，在此隐藏主窗口至托盘
        self.root.withdraw()
        if self._tray is not None:
            self._update_tray_menu()

    def _hide_to_tray(self):
        """把主窗口隐藏到系统托盘。"""
        self.root.withdraw()
        self._update_tray_menu()

    def _tray_show(self, icon=None, item=None):
        """托盘命令：显示主窗口。"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _tray_toggle(self, icon=None, item=None):
        """托盘命令：开始/停止监控（与界面按钮同一开关）。"""
        self.root.after(0, self.toggle)

    def _tray_quit(self, icon=None, item=None):
        """托盘命令：真正退出程序。"""
        try:
            self._load_from_ui()
            self._save_cfg()
        except Exception:
            pass
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        self.running = False
        self.root.destroy()

    def _update_tray_menu(self):
        """刷新托盘右键菜单（显示窗口 / 启停 / 退出）。"""
        if not _HAS_TRAY or self._tray is None:
            return
        toggle_label = "停止监控" if self.running else "开始监控"
        try:
            self._tray.menu = pystray.Menu(
                pystray.MenuItem("显示窗口", self._tray_show, default=True),
                pystray.MenuItem(toggle_label, self._tray_toggle),
                pystray.MenuItem("退出", self._tray_quit))
        except Exception:
            pass

    def _setup_tray(self):
        """创建系统托盘图标（需 pystray，缺失则跳过）。"""
        if not _HAS_TRAY:
            return
        try:
            # 生成 64x64 的简单图标（绿圆点）
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((4, 4, 60, 60), fill=(34, 177, 76, 255))
            d.ellipse((22, 22, 32, 32), fill=(255, 255, 255, 255))
            d.ellipse((34, 22, 44, 32), fill=(255, 255, 255, 255))
            icon = pystray.Icon(
                "autoclaw_continue", img, "AutoClaw 自动继续",
                menu=pystray.Menu(
                    pystray.MenuItem("显示窗口", self._tray_show, default=True),
                    pystray.MenuItem("开始监控", self._tray_toggle),
                    pystray.MenuItem("退出", self._tray_quit)))
            icon.run_detached()
            self._tray = icon
        except Exception:
            self._tray = None

    def _on_close(self):
        """真正退出：保存当前参数，再销毁主窗口。"""
        try:
            self._load_from_ui()
            self._save_cfg()
        except Exception:
            pass
        self.root.destroy()

    # ---------------- 日志显示 ----------------
    def _append_log(self, msg):
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", "[%s] %s\n" %
                            (time.strftime("%H:%M:%S"), msg))
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def clear_log(self):
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.config(state="disabled")

    def _read_raw_new(self):
        """增量读取原始 gateway.log 的全部新增行（含窗口轮转处理）。"""
        path = self.cfg.get("log_path")
        try:
            size = os.path.getsize(path)
        except OSError:
            return []
        if self.raw_pos is None:
            self.raw_pos = size
            return []
        if size < self.raw_pos:          # 日志被重置/轮转
            self.raw_pos = 0
        if size == self.raw_pos:
            return []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(self.raw_pos)
            data = f.read()
            self.raw_pos = f.tell()
        return data.splitlines()

    def _show_raw_snapshot(self):
        """切换到原始日志时：清空并加载文件末尾若干行作为起始快照。"""
        path = self.cfg.get("log_path")
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        tail_n = lines[-400:]          # 初始只显示末尾 400 行，避免卡顿
        self.raw_pos = None            # 强制偏移指向当前文件末尾
        try:
            self.raw_pos = os.path.getsize(path)
        except OSError:
            self.raw_pos = 0
        self.txt_log.insert("end", "\n".join(tail_n))
        if tail_n:
            self.txt_log.insert("end", "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")
        # 界面上方状态栏已提示当前为原始日志视图，此处不加额外标记避免混格式

    def _append_raw_lines(self, rows):
        self.txt_log.config(state="normal")
        for line in rows:
            self.txt_log.insert("end", line + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def _refresh_tree(self):
        """刷新 代理 -> 会话 分类树，显示各自 总请求 / 403 / 最新请求。"""
        for agent, item in self.tree_agents.items():
            try:
                self.tree.delete(item)
            except Exception:
                pass
        self.tree_agents.clear()
        self.tree_sessions.clear()
        # 按代理分组
        by_agent = {}
        for (agent, session), (total, err, _t) in self.session_stats.items():
            a = agent or "(未知)"
            s = session or "(未知)"
            d = by_agent.setdefault(a, {})
            d[s] = [total, err, _t]
        for a in sorted(by_agent.keys()):
            aid = self.tree.insert("", "end", text="%s  [%d]" % (
                a, sum(v[0] for v in by_agent[a].values())))
            self.tree_agents[a] = aid
            for s in sorted(by_agent[a].keys(), reverse=False):
                total, err, tstamp = by_agent[a][s]
                latest = time.strftime("%H:%M:%S", time.localtime(tstamp)) \
                    if tstamp else "-"
                sid = self.tree.insert(aid, "end", text="   %s" % s,
                                       values=("%d" % total, "%d" % err,
                                               latest))
                self.tree_sessions[(self.tree_agents[a], s)] = sid
        # 展开所有代理节点
        for _, aid in self.tree_agents.items():
            try:
                self.tree.item(aid, open=True)
            except Exception:
                pass

    def toggle_view(self):
        """在 程序日志(限流动态) 与 原始 gateway.log 之间切换。"""
        if not self.view_raw:
            self.view_raw = True
            self.btn_view.config(text="切换到程序日志")
            self.var_state.set("查看原始日志（实时）")
            self._show_raw_snapshot()
        else:
            self.view_raw = False
            self.btn_view.config(text="切换到原始日志")
            if self.running:
                self.var_state.set("运行中 …")
            else:
                self.var_state.set("未运行")
            self.clear_log()
            self._append_log("已切回程序日志（限流动态）。")

    # ---------------- 线程运行 ----------------
    def toggle(self):
        if not self.running:
            try:
                self._load_from_ui()
            except ValueError as e:
                messagebox.showerror("参数错误", str(e))
                return
            if not os.path.exists(self.cfg["log_path"]):
                messagebox.showerror("找不到日志",
                                     "日志文件不存在：\n%s" % self.cfg["log_path"])
                return
            self._save_cfg()        # 参数合法且日志存在，则持久化当前设置
            self.running = True
            self.btn_start.config(text="停止监控")
            self.var_state.set("运行中 …")
            self.monitor_thread = threading.Thread(target=self._monitor_loop,
                                                   daemon=True)
            self.monitor_thread.start()
            self._append_log("开始监控日志：%s" % self.cfg["log_path"])
        else:
            self.running = False
            self.btn_start.config(text="开始监控")
            self.var_state.set("已停止")
            self._append_log("已停止监控。")

    def _monitor_loop(self):
        # 后台线程使用 uiautomation 需先初始化 COM（STA 线程模型），否则 UIA 全部失败
        try:
            ole32 = ctypes.windll.ole32
            ole32.CoInitializeEx(None, 0)   # 0 = COINIT_APARTMENTTHREADED(STA)
        except Exception:
            pass
        watcher = LogWatcher(self.cfg["log_path"])
        # 注：历史播种已由主线程 _seed_from_log 完成，这里仅增量处理新行
        while self.running:
            try:
                items = watcher.scan()
            except Exception:
                items = []
            # 原始日志视图下，把新增行实时追加显示
            if self.view_raw:
                try:
                    self._append_raw_lines(self._read_raw_new())
                except Exception:
                    pass
            # 本轮新增行：全部计入总数统计
            batch = []
            for status, agent, session, ts, line in items:
                batch.append((status, agent, session, ts))
            for status, agent, session, _ts in batch:
                self._record_stats_only(status, agent, session)
            # 只对每个会话的最后一条记录判断 403 / 超时，而非常条都判断
            last_by_key = {}
            for status, agent, session, ts in batch:
                last_by_key[(agent, session)] = (status, agent, session, ts)
            for (_a, _s), (status, agent, session, ts) in last_by_key.items():
                self._record_last(status, agent, session, ts)
            time.sleep(self.cfg["interval"])

    def _seed_from_log(self):
        """启动时同步读全量日志，播种会话统计并刷新树（主线程，立即显示）。"""
        try:
            watcher = LogWatcher(self.cfg["log_path"])
            for status, agent, session, ts, line in watcher.scan():
                self._record_stats_only(status, agent, session)
            self._refresh_tree()
        except Exception:
            pass

    def _poll_tree(self):
        """主线程轮询：若后台线程置了脏标记，则刷新树。"""
        if self._stats_dirty:
            self._stats_dirty = False
            try:
                self._refresh_tree()
            except Exception:
                pass
        if self.running:
            self.root.after(500, self._poll_tree)

    def _record_stats_only(self, status, agent, session):
        """仅累计会话请求总数与最近时间，不做 403 判断、不触发「继续」。"""
        key = (agent, session)
        stat = self.session_stats.setdefault(key, [0, 0, 0])
        stat[0] += 1
        stat[2] = time.time()

    def _record_last(self, status, agent, session, ts=None):
        """只对会话的最后一条记录判断 403 与时效；命中则触发「继续」。

        每轮监控只调用一次（每会话），避免会话内多条 403 重复触发。"""
        key = (agent, session)
        if status not in self.cfg["status_codes"]:
            return
        # 目标代理过滤：指定了代理时，仅在匹配该代理时才继续
        target = self.cfg.get("target_agent", "")
        if target and agent != target:
            return
        stat = self.session_stats.setdefault(key, [0, 0, 0])
        stat[1] += 1                      # 该会话的末条为 403，计入 403 计数
        # 限流错误时效阈值：错误发生时间距今超过该阈值，视为陈旧，不触发自动继续
        max_age = self.cfg.get("error_max_age", 300)
        if ts is not None and max_age > 0:
            age = time.time() - ts
            if age > max_age:
                self._append_log(
                    "状态 %s（代理=%s 会话=%s）已过去 %.0f 秒，超过时效阈值 %d 秒，忽略。"
                    % (status, agent or "-", (session or "")[:8], age, max_age))
                return
        now = time.time()
        if now - self.last_trigger_time.get(key, float("-inf")) < self.cfg["cooldown"]:
            self._append_log("状态 %s（%s/%s）在冷却期，忽略。"
                             % (status, agent or "-", (session or "")[:8] or "-"))
            return
        self.last_trigger_time[key] = now
        self.log_counter += 1
        self._append_log(
            ">>> 状态 %s（代理=%s 会话=%s），累计 %d 次，执行自动继续…"
            % (status, agent or "-", (session or "")[:12], self.log_counter))
        self._do_continue(agent, session)
        self._stats_dirty = True

    def _on_tree_double(self, event):
        """双击会话节点 -> 弹出该会话的所有请求详情。"""
        item = self.tree.focus()
        if not item:
            return
        # 由 tree_sessions 反查 (agent_node, session)
        for (aud, s), sid in self.tree_sessions.items():
            if sid == item:
                agent = self.tree.item(aud, "text").split("  [")[0]
                self._show_session_detail(agent, s)
                return

    def _show_session_detail(self, agent, session):
        """从 gateway.log 过滤该 代理/会话 的请求，按 requestId 配对展示。"""
        win = tk.Toplevel(self.root)
        win.title("会话详情 - %s / %s" % (agent, session))
        win.geometry("980x700")
        # 概览行
        sv = tk.StringVar()
        tk.Label(win, textvariable=sv, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=6, pady=2)
        # 垂直分栏：上方聊天区（默认占满），下方可折叠请求区
        paned = ttk.Panedwindow(win, orient="vertical")
        paned.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
        # 用户消息区（聊天框，默认显示完整）
        ulab = tk.LabelFrame(paned, text="用户发送的内容")
        # 聊天区：Text 气泡，左=模型，右=用户；模型标题双击展开详情
        utxt = tk.Text(ulab, wrap="word", background="#eef2f7",
                       font=("Microsoft YaHei UI", 10),
                       highlightthickness=0, bd=0, cursor="hand2")
        uska = ttk.Scrollbar(ulab, orient="vertical", command=utxt.yview)
        utxt.configure(yscrollcommand=uska.set)
        utxt.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        uska.pack(side="right", fill="y")
        utxt.tag_configure("user_r",
                           background="#dcf0ff", lmargin1=330, lmargin2=330,
                           rmargin=8, spacing1=2, spacing3=3, justify="right",
                           font=("Microsoft YaHei UI", 10))
        utxt.tag_configure("bot_title",
                           background="#ffffff", lmargin1=8, rmargin=330,
                           spacing1=2, spacing3=3, justify="left",
                           font=("Microsoft YaHei UI", 10, "bold"),
                           foreground="#1a1a2e")
        utxt.tag_configure("bot_detail",
                           background="#ffffff", lmargin1=8, rmargin=330,
                           spacing1=2, spacing3=3, justify="left",
                           font=("Microsoft YaHei UI", 10))
        utxt.tag_configure("meta_l", foreground="#999999",
                           font=("Microsoft YaHei UI", 8))
        utxt.tag_configure("meta_r", foreground="#999999",
                           font=("Microsoft YaHei UI", 8),
                           justify="right")
        utxt.bind("<Button-1>", self._on_bot_click)
        paned.add(ulab, weight=5)          # 聊天区占大头
        # 请求区（可折叠请求树）
        rlab = tk.LabelFrame(paned, text="底层请求 / 限流（可折叠）")
        frame = ttk.Frame(rlab)
        frame.pack(fill="both", expand=True, padx=4, pady=2)
        cols = ("ts", "status", "model", "method", "url")
        tree = ttk.Treeview(frame, columns=cols, show="tree headings")
        for c, w, t in (("ts", 90, "时间"), ("status", 60, "状态"),
                        ("model", 180, "模型"), ("method", 60, "方法"),
                        ("url", 480, "地址")):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="w", stretch=(c == "url"))
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        paned.add(rlab, weight=2)          # 请求区默认较矮，聊天优先
        win.rowconfigure(1, weight=1)
        win.columnconfigure(0, weight=1)

        # 用户真实输入写入上方面板（聊天框样式）
        slog = self._find_session_log(agent, session)
        self._chat_data = []          # 展开功能所需的原始 chat
        self._expanded_bots = set()
        self._chat_utxt = utxt
        self._model_details = {}   # bid -> (title, detail行)
        utxt.config(state="normal")
        if slog:
            chat = self._load_chat(slog)
            self._chat_data = chat
            users = sum(1 for x in chat if x[0] == "user")
            ulab.config(text="完整会话（用户 %d · 模型 %d 条 · 单击模型标题展开）" %
                        (users, len(chat) - users))
            self._fill_chat_section(utxt)
            utxt.config(state="disabled")
        else:
            utxt.insert("end", "未找到该会话的轨迹文件（%s）。\n" % slog)
            utxt.config(state="disabled")

        path = self.cfg.get("log_path")
        pairs = []                      # 按出现顺序的一条请求
        by_id = {}                      # requestId -> dict
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    # 403 响应体藏在 [embedded]/[diagnostic] 行，可能有也可能没有 AutoClawRequestTrace
                    resp_body = self._extract_403_body(line)
                    if resp_body is not None:
                        sid = resp_body.get("sessionId") or ""
                        agt = resp_body.get("agentId") or ""
                        message = resp_body.get("message") or ""
                        rid = resp_body.get("requestId") or ""
                        rec = by_id.get(rid)
                        if rec is None:
                            rec = {"ts": self._line_hm(line), "model": "-",
                                   "status": "403", "method": "-", "url": "",
                                   "resp_line": line}
                            by_id[rid] = rec
                            pairs.append(rec)
                        rec["status"] = "403"
                        rec["message"] = message or rec.get("message", "")
                        if sid and sid == session:
                            rec["resp_line"] = line
                        continue
                    # 普通 AutoClawRequestTrace 行
                    if "AutoClawRequestTrace" not in line:
                        continue
                    if ("xAgentId=%s" % agent) not in line:
                        continue
                    if ("xSessionId=%s" % session) not in line:
                        continue
                    rid = line.split("requestId=")[1].split(" ")[0] \
                        if "requestId=" in line else line
                    ts = (line.split("] ")[0].split("T")[-1])[:8] \
                        if "] " in line else ""
                    is_resp = " response " in line
                    rec = by_id.get(rid)
                    if rec is None:
                        rec = {"ts": ts, "model": "-", "status": "-",
                               "method": "-", "url": ""}
                        by_id[rid] = rec
                        pairs.append(rec)
                    if not is_resp:      # request 行
                        rec["ts"] = ts or rec["ts"]
                        rec["model"] = line.split("model.id=")[1].split(" ")[0] \
                            if "model.id=" in line else rec["model"]
                        rec["method"] = line.split("method=")[1].split(" ")[0] \
                            if "method=" in line else rec["method"]
                        if "url=" in line:
                            rec["url"] = line.split("url=")[1].split(" ")[0][:80]
                    else:                # response 行 -> 状态
                        rec["status"] = line.split("status=")[1].split(" ")[0] \
                            if "status=" in line else rec["status"]
                    # 记录完整原始行，供展开查看
                    if is_resp:
                        rec["resp_line"] = line
                    else:
                        rec["req_line"] = line
        except Exception as e:
            sv.set("读取日志失败：%s" % e)
            return

        # 概览与可折叠请求节点
        errs = [p for p in pairs if p["status"] != "200" and p["status"] != "-"]
        sv.set("代理: %s   会话: %s   请求: %d   非200/403: %d    (双击行展开/折叠详情)"
               % (agent, session, len(pairs), len(errs)))
        for i, p in enumerate(pairs):
            if p["status"] != "200" and p["status"] != "-":
                tag = "err"
            else:
                tag = ""
            pid = tree.insert("", "end",
                              values=(p["ts"], p["status"], p["model"][:24],
                                      p["method"], p["url"]),
                              tags=(tag,), open=False)
            # 请求 + 响应两个子节点，完整原文放入 url 列（最宽），默认折叠
            # 403 的响应体（已解码）作为最高优先子节点展示
            if p.get("message"):
                tree.insert(pid, "end", text=("  响应体(已解码) message"),
                            values=("", "", "", "", p["message"]))
                tree.item(pid, open=True)
            for label, key in (("请求 Request", "req_line"),
                               ("响应 Response", "resp_line")):
                line = p.get(key)
                if line:
                    tree.insert(pid, "end", text=("  "+label),
                                values=("", "", "", "", line.strip()))
        tree.tag_configure("err", background="#ffe9e6")
        # 让 summary 列展示子节点的完整原文：仅第一列足够宽
        tree.column("ts", width=90)
        tree.column("method", width=60)
        tree.column("url", width=480)

    def _fill_chat_section(self, utxt):
        """重建聊天区内容（用户右侧、模型左侧，模型标题可展开）。"""
        utxt.delete("1.0", "end")
        bid = 0
        for role, text, ts in self._chat_data:
            hm = ""
            try:
                hm = ts.split("T")[-1][:8]
            except Exception:
                pass
            if role == "user":
                utxt.insert("end", hm + "  你\n", "meta_r")
                utxt.insert("end", text + "\n", "user_r")
            else:
                # 拆标题与详情
                lines = text.split("\n")
                title = ""
                detail = []
                for ln in lines:
                    if ln.startswith("[思考]") or ln.startswith("[调用工具]"):
                        detail.append(ln)
                    elif ln.strip():
                        if not title:
                            title = ln.strip()
                        else:
                            detail.append("[正文] " + ln)
                if not title and detail:
                    title = "[仅有内部动作]"
                utxt.insert("end", "模型  %s\n" % hm, "meta_l")
                bt = "bt_%d" % bid
                if bid in self._expanded_bots:
                    utxt.insert("end", "▼ " + title + "\n", ("bot_title", bt))
                    for d in detail:
                        utxt.insert("end", d + "\n", "bot_detail")
                else:
                    utxt.insert("end", "▶ " + title + "\n", ("bot_title", bt))
                self._model_details[bid] = (title, detail)
                bid += 1

    def _on_bot_click(self, event):
        """单击模型标题：在该行下方局部插入/删除细节，不重建，避免错位。"""
        utxt = self._chat_utxt
        idx = utxt.index("@%d,%d" % (event.x, event.y))
        # 精确命中：该位置若带 bt_<bid> 的唯一 tag，即为目标模型
        cur = None
        for t in utxt.tag_names(idx):
            if t.startswith("bt_"):
                try:
                    cur = int(t.split("_")[1])
                except ValueError:
                    cur = None
                break
        if cur is None:
            return
        title, detail = self._model_details.get(cur, ("", []))
        btag = "bt_%d" % cur
        dtag = "bd_%d" % cur

        utxt.config(state="normal")

        def _set_title_arrow(arrow):
            # arrow 为单字符（▶/▼），箭头后的空格已存在于行内
            first = utxt.index(btag + ".first")
            if not utxt.compare(first, "<", first + " +1 c"):
                return
            utxt.delete(first, first + " +1 c")
            utxt.insert(first, arrow)
            end = utxt.index(first + " lineend")
            # 用单独调用分别打标签，确保箭头字符也带上 bt_<bid>，
            # tag 从行首重新覆盖整行，避免 .first 错位导致点击/收回失败
            utxt.tag_add(btag, first, end)
            utxt.tag_add("bot_title", first, end)

        try:
            t0, t1 = utxt.tag_ranges(btag)
            if cur in self._expanded_bots:
                # 收起：一次性删除细节 tag 覆盖的区域，再点会重新插入
                dr = utxt.tag_ranges(dtag)
                if dr and len(dr) >= 2:
                    try:
                        utxt.delete(str(dr[0]), str(dr[-1]))
                    except Exception:
                        pass
                utxt.tag_delete(dtag)
                self._expanded_bots.discard(cur)
                _set_title_arrow("▶")
            else:
                # 展开：在标题行下一行一次性插入全部细节为一个 tag 段
                self._expanded_bots.add(cur)
                block = "".join(d + "\n" for d in detail)
                # 先定位细节插入点（标题行换行符之后），再插细节，最后改箭头
                ins = utxt.index(str(t0) + " lineend +1 c")
                if block:
                    utxt.insert(ins, block, ("bot_detail", dtag))
                _set_title_arrow("▼")
        finally:
            utxt.config(state="disabled")

    def _extract_403_body(self, line):
        """从行中提取 <autoclaw-403-response> 块并双重URL解码成 dict。

        返回 dict（含 status/url/requestId/sessionId/agentId/rawBody/message）
        或 None（该行无此块）。"""
        if "<autoclaw-403-response>" not in line:
            return None
        try:
            raw = line.split("<autoclaw-403-response>", 1)[1]
            raw = raw.split("</autoclaw-403-response>", 1)[0]
            # 双重 URL 解码到外层 JSON 字符串
            d1 = urllib.parse.unquote(raw)
            d2 = urllib.parse.unquote(d1)
            obj = json.loads(d2)
            if not isinstance(obj, dict):
                return None
            # rawBody 内层（也可能还是编码的）再做一次 JSON 解析
            msg = ""
            if obj.get("rawBody"):
                inner_raw = obj["rawBody"]
                try:
                    inner = json.loads(inner_raw)
                    if isinstance(inner, dict):
                        msg = inner.get("message") or inner.get("error") or ""
                        if not msg:
                            msg = json.dumps(inner, ensure_ascii=False)[:500]
                except Exception:
                    msg = str(inner_raw)[:500]
            obj["message"] = msg
            return obj
        except Exception:
            return None

    def _line_hm(self, line):
        """从行首 ISO 时间戳截取 HH:MM:SS。"""
        try:
            return (line.split("] ")[0].split("T")[-1])[:8]
        except Exception:
            return ""

    def _find_session_log(self, agent, session):
        """定位 代理/会话 的 jsonl 轨迹文件，不存在返回 None。"""
        base = os.path.expandvars(r"%USERPROFILE%\.openclaw-autoclaw\agents")
        for cand in (os.path.join(base, agent, "sessions", session + ".jsonl"),
                     os.path.join(base, "main", "sessions", session + ".jsonl")):
            if os.path.exists(cand):
                return cand
        return None

    def _extract_user_requests(self, path):
        """从会话 jsonl 中提取用户真实输入（AUTOCLAW_USER_AUTHORED_REQUEST 标记内）。"""
        import re
        pat = re.compile(
            r"<<<AUTOCLAW_USER_AUTHORED_REQUEST_START>>>\s*(.*?)\s*"
            r"<<<AUTOCLAW_USER_AUTHORED_REQUEST_END>>>", re.S)
        out = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    for m in pat.finditer(line):
                        t = m.group(1).strip()
                        if t:
                            out.append(t)
        except Exception:
            pass
        return out

    def _load_chat(self, path):
        """从轨迹 jsonl 重建完整对话流：按时间排序的 (角色, 文本, 时间) 列表。

        角色：user=用户真实输入；bot=模型文字回复。跳过 those 无正文数据。
        注意：user.content 是字符串（内含 AUTOCLAW_USER_AUTHORED_REQUEST 标记），
              assistant.content 是块列表（thinking/text/toolCall）。
        """
        import re
        out = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    if o.get("type") != "message":
                        continue
                    ts = o.get("timestamp", "")
                    if isinstance(ts, (int, float)):
                        ts = time.strftime("%Y-%m-%dT%H:%M:%S",
                                           time.localtime(ts / 1000.0)) \
                            if ts > 1e12 else time.strftime(
                            "%Y-%m-%dT%H:%M:%S", time.localtime(ts))
                    m = o.get("message") or {}
                    role = m.get("role")
                    content = m.get("content")
                    if role == "user":
                        # content 为字符串，提取 AUTHORED 标记内的真实用户输入
                        user_texts = re.findall(
                            r"<<<AUTOCLAW_USER_AUTHORED_REQUEST_START>>>\s*"
                            r"(.*?)\s*<<<AUTOCLAW_USER_AUTHORED_REQUEST_END>>>",
                            str(content), re.S)
                        if not user_texts:
                            continue        # 系统注入的上下文(无AUTHORED)，跳过
                        for ut in user_texts:
                            ut = ut.strip()
                            # 过滤噪音：系统提醒英文句中的短英文词(如 and)，真实输入通常是中文/长句
                            if not ut \
                               or (len(ut) <= 6 and ut.isascii()
                                   and " " not in ut):
                                continue
                            out.append(("user", ut, str(ts)))
                        continue
                    # assistant / 其它：content 为块列表
                    texts = []
                    if isinstance(content, list):
                        for b in content:
                            if not isinstance(b, dict):
                                continue
                            bt = b.get("type")
                            if bt == "text" and b.get("text"):
                                texts.append(b["text"])
                            elif bt == "thinking" and b.get("thinking"):
                                texts.append("[思考] " + b["thinking"])
                            elif bt == "toolCall":
                                fn = b.get("name") or ""
                                texts.append("[调用工具] " + fn)
                            elif bt == "toolResult":
                                texts.append("[工具结果]")
                    elif isinstance(content, str) and content.strip():
                        texts.append(content)
                    if not texts:
                        continue
                    txt = "\n".join(texts)
                    if role in ("assistant", "bot"):
                        out.append(("bot", txt, str(ts)))
        except Exception:
            pass
        out.sort(key=lambda x: x[2])       # 按时间戳升序
        return out

    # ---------------- 执行"继续" ----------------
    def _find_autoclaw(self):
        """找到最合适的 AutoClaw 窗口。优先标题匹配的 chrome 主窗口。"""
        matches = find_windows_by_title(self.cfg["window_match"])
        if not matches:
            return None
        # 优先选类名含 RenderWidgetHost 或主 chrome 窗口；退而选第一个
        for hwnd, title, cls in matches:
            if "RenderWidget" in cls or "Chrome_WidgetWin" in cls:
                return hwnd
        return matches[0][0]

    def _find_render_host(self, hwnd):
        """枚举子窗口，返回 Chrome_RenderWidgetHostHWND 句柄（AutoClaw 的网页渲染层）。

        结果按 hwnd 缓存，避免每次操作重复枚举。"""
        cached = self._uia_cache.get(("render_host", hwnd))
        if cached is not None:
            return cached
        handles = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def cb(h, l):
            handles.append(h)
            return True
        user32.EnumChildWindows(hwnd, cb, 0)
        host = None
        for h in handles:
            buf = ctypes.create_unicode_buffer(512)
            user32.GetClassNameW(h, buf, 512)
            if "Chrome_Render" in buf.value:
                host = h
                break
        self._uia_cache[("render_host", hwnd)] = host
        return host

    def _uia_get_doc(self, hwnd):
        """返回缓存的 AutoClaw 渲染层 UIA Document 控件；失效则重建。"""
        if uia is None:
            return None
        cached = self._uia_cache.get(("doc", hwnd))
        if cached is not None:
            try:
                cached.Name
                return cached
            except Exception:
                pass
        host = self._find_render_host(hwnd)
        if not host:
            return None
        doc = uia.ControlFromHandle(host)
        if doc is not None:
            self._uia_cache[("doc", hwnd)] = doc
        return doc

    def _uia_set_continue(self, hwnd, text):
        """通过 UIA 定位底部输入框并直接写入文本。返回 True 表示成功。

        输入框按 hwnd 缓存，成功一次后不再重复全树遍历。"""
        if uia is None:
            return False
        try:
            edit = self._uia_get_edit(hwnd)
            if edit is None or not edit.IsEnabled:
                return False
            edit.GetValuePattern().SetValue(text)
            return True
        except Exception:
            # 元素失效，清缓存让下次重建
            self._uia_cache.pop(("edit", hwnd), None)
            return False

    def _uia_get_edit(self, hwnd):
        """返回缓存的底部输入框 EditControl；未缓存则全树遍历一次并缓存。"""
        if uia is None:
            return None
        cached = self._uia_cache.get(("edit", hwnd))
        if cached is not None:
            try:
                cached.Name
                return cached
            except Exception:
                pass
        doc = self._uia_get_doc(hwnd)
        if doc is None:
            return None
        candidates = []

        def walk(node, d=0):
            if d > 16:
                return
            try:
                if (node.ControlTypeName == "EditControl"
                        and "使用技能" in (node.Name or "")):
                    candidates.append(node)
                    return
            except Exception:
                pass
            for ch in node.GetChildren():
                walk(ch, d + 1)
        walk(doc)
        if not candidates:
            return None
        self._uia_cache[("edit", hwnd)] = candidates[0]
        return candidates[0]

    def _coordinate_continue(self, hwnd):
        """坐标兜底方案：激活窗口 + 点击输入框 + 全选 + 剪贴板粘贴 + 回车。"""
        if not set_foreground(hwnd):
            self._append_log("ERROR: 无法将 AutoClaw 窗口切到前台（可能被管理员窗口遮挡）。"
                             "请以管理员身份运行本程序。")
            return
        time.sleep(0.4)
        rect = get_window_rect(hwnd)
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        ratio = self.cfg["input_ratio"]
        x = rect.left + int(w * ratio)
        y = rect.bottom + self.cfg["input_offset_y"]
        # 点击输入框聚焦
        set_cursor_pos(x, y)
        time.sleep(0.15)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.15)
        mouse_click()
        time.sleep(0.25)
        # Esc 取消可能存在的中文输入法组合状态（否则 Ctrl+V 会被 IME 拦截）
        send_key(0x1B, True)
        send_key(0x1B, False)
        time.sleep(0.1)
        # 全选清空既有内容
        send_key(VK_CONTROL, True)
        send_key(VK_A, True)
        send_key(VK_A, False)
        send_key(VK_CONTROL, False)
        time.sleep(0.1)
        # 键入继续文本（剪贴板粘贴，对中文输入更可靠）
        paste_unicode(self.cfg["continue_text"])
        time.sleep(0.2)
        if self.cfg["send_enter"]:
            time.sleep(0.05)
            send_key(VK_RETURN, True)
            send_key(VK_RETURN, False)
        self._append_log("OK(坐标): 已向 AutoClaw 输入 “%s”%s"
                         % (self.cfg["continue_text"],
                            " 并回车" if self.cfg["send_enter"] else ""))

    def _session_title(self, agent, session, maxlen=24):
        """从该会话 jsonl 提取首条真实用户消息作为左侧列表匹配关键词。

        结果按 (agent, session) 缓存，避免每次触发都重读 jsonl。"""
        ck = ("title", agent, session, maxlen)
        if ck in self._uia_cache:
            return self._uia_cache[ck]
        val = self._session_title_impl(agent, session, maxlen)
        self._uia_cache[ck] = val
        return val

    def _session_title_impl(self, agent, session, maxlen):
        try:
            sj = self._find_session_log(agent, session)
            if not sj or not os.path.exists(sj):
                return ""
            pat = re.compile(
                r"<<<AUTOCLAW_USER_AUTHORED_REQUEST_START>>>\s*(.*?)\s*"
                r"<<<AUTOCLAW_USER_AUTHORED_REQUEST_END>>>", re.S)
            with open(sj, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = pat.search(line)
                    if not m:
                        continue
                    text = m.group(1)
                    text = text.replace("\\n", " ").replace("\\t", " ")
                    text = re.sub(r"\s+", " ", text)
                    text = text.strip().lstrip(">").strip()
                    if text:
                        return text[:maxlen]
            return ""
        except Exception:
            return ""

    def _click_session_button(self, hwnd, agent, session):
        """在左侧列表中定位并点击目标会话。返回 True 表示已点击。

        会话按钮按 (hwnd, keyword) 缓存：目标会话不变时无需重建整棵树。"""
        if uia is None:
            return False
        try:
            keyword = self._session_title(agent, session, 12)
            kw_norm = (keyword or "").replace(" ", "").lower()
            if not kw_norm:
                return False
            doc = self._uia_get_doc(hwnd)
            if doc is None:
                return False

            # 若会话已在前台（主区内容含关键词），无需点击
            try:
                if kw_norm in (doc.Name or "").lower():
                    return False
            except Exception:
                pass

            bc = ("session_btn", hwnd, kw_norm)
            btn = self._uia_cache.get(bc)
            if btn is not None:
                try:
                    btn.Name
                except Exception:
                    btn = None
            if btn is None:
                candidates = []
                def walk(node, d=0):
                    if d > 16:
                        return
                    try:
                        if node.ControlTypeName == "ButtonControl":
                            nm = (node.Name or "")
                            n = nm.replace(" ", "").lower()
                            if kw_norm and (kw_norm in n or n in kw_norm or
                                            nm[:6].replace(" ", "").lower() in kw_norm):
                                candidates.append((node, nm))
                    except Exception:
                        pass
                    for ch in node.GetChildren():
                        walk(ch, d + 1)
                walk(doc)
                if not candidates:
                    return False
                btn = candidates[0][0]
                self._uia_cache[bc] = btn

            r = btn.BoundingRectangle
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.15)
            user32.SetCursorPos((r.left + r.right) // 2, r.top + 10)
            time.sleep(0.1)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.5)   # 等待会话切换加载
            return True
        except Exception:
            return False

    def _do_continue(self, agent="", session=""):
        hwnd = self._find_autoclaw()
        if not hwnd:
            self._append_log("ERROR: 未找到 AutoClaw 窗口（标题匹配=%s）"
                             % self.cfg["window_match"])
            return
        try:
            text = self.cfg["continue_text"]
            # 若非前台会话，先切到目标会话（403 触发时会话可能不在前台）
            if agent and session:
                if self._click_session_button(hwnd, agent, session):
                    self._append_log("已切换到会话 %s/%s" % (agent, session[:8]))
            # 优先 UIA 注入（不抢焦点、不依赖坐标，最可靠）
            if self._uia_set_continue(hwnd, text):
                if self.cfg["send_enter"]:
                    time.sleep(0.1)
                    # 发送后焦点可能不在输入框，用 UIA 聚焦到输入框再回车
                    self._uia_focus_and_enter(hwnd)
                self._append_log("OK: 已向 AutoClaw 输入 “%s”%s"
                                 % (text,
                                    " 并回车" if self.cfg["send_enter"] else ""))
                return
            # UIA 不可用时回退坐标方案
            self._append_log("UIA 定位失败，回退坐标方案…")
            self._coordinate_continue(hwnd)
        except Exception as e:
            self._append_log("ERROR: 执行失败 - %s" % e)

    def _uia_focus_and_enter(self, hwnd):
        """UIA 聚焦输入框并发回车（发送）。失败静默，由上层兜底。"""
        if uia is None:
            return
        try:
            edit = self._uia_get_edit(hwnd)
            if edit is None:
                return
            edit.SetFocus()
            set_foreground(hwnd)
            time.sleep(0.1)
            send_key(VK_RETURN, True)
            send_key(VK_RETURN, False)
        except Exception:
            pass

    def test_action(self):
        """手动触发一次继续动作（不动监控）。"""
        try:
            self._load_from_ui()
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return
        hwnd = self._find_autoclaw()
        if not hwnd:
            messagebox.showerror("找不到窗口",
                                 "未找到匹配“%s”的窗口"
                                 % self.cfg["window_match"])
            return
        self._append_log("手动测试：执行一次继续动作…")
        self._do_continue()


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
    # 若当前前台可能是管理员进程（UIPI 前台锁定），普通权限无法把 AutoClaw 切到前台。
    # 未提权时自动以管理员身份重启一次，保证激活与输入有效。
    if not is_elevated() and relaunch_as_admin():
        return
    hide_console()              # 隐藏本脚本的黑框终端
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()