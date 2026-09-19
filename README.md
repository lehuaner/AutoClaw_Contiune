# AutoClaw 自动"继续"工具

当 AutoClaw（zcode 编码代理）会话因后端限流停止时，自动激活窗口、聚焦输入框、
键入"继续"并回车发送，让会话继续运行。

## 背景

AutoClaw 运行中若被后端限流，界面会弹出"当前使用人数较多"之类提示并停止响应。
本程序后台监控其本地日志 `gateway.log`，一旦发现疑似限流的请求状态码（默认 `403`，
可配置 `429`/`503` 等），就自动帮会话发送"继续"，让任务不被中断。

## 特性

- 实时监控日志，识别限流状态码后自动触发"继续"
- 「UIA 优先、坐标兜底」双通道交互：
  - **UIA**：通过可访问性树直接注入输入框文本并发送回车（主方案）
  - 坐标 + 剪贴板：UIA 不可用时自动回退
- 后台驻留：启动后**自动最小化到托盘**并**自动开始监控**，无需手动操作
- 启动监控时弹出 **Windows 系统通知**，并在日志区展示本次关键参数
- 冷却 / 错误寿命控制，防止重复发送与误触发
- 系统托盘常驻（pystray 可选，缺失不阻塞主功能）
- 仅依赖 Windows 标准库 + ctypes，无需 pywin32

## 依赖

- Python 3（自带 tkinter/ctypes）
- 可选：`uiautomation`、`pystray`、`Pillow`、`winotify`（缺失时自动降级；
  `winotify` 缺失则跳过 Windows 通知）

安装可选依赖：

```bash
pip install -r requirements.txt
```

## 运行

**推荐：双击 `autoclaw_continue.pyw`** —— 用 pythonw 无控制台启动，不会出现黑色终端。

或用命令行：

```bash
pythonw autoclaw_continue.pyw
```

> 不要用 `python autoclaw_continue.py` 启动：`python.exe` 是控制台程序，
> 一定会弹出黑色终端（脚本内的隐藏代码只能藏起来，无法消除）。
> `.pyw`/`pythonw` 本身不带控制台，才会完全不见终端。

- 启动后自动隐藏到系统托盘并自动开始监控；从托盘菜单可「显示窗口 / 停止监控 / 退出」。
- 运行日志（启动、参数、日志定位、异常等）写入脚本同目录的 `autoclaw.log`，
  排查启动闪烁、托盘退出、日志定位等问题时可查看该文件。

## 配置

配置文件 `autoclaw_continue.json` 支持按需调整，主要字段：

| 字段 | 说明 | 默认 |
|---|---|---|
| `log_path` | gateway 日志路径。`AUTO`(或留空) 时自动定位 autoclaw 数据目录下的日志；也可填 `%USERPROFILE%` / `~` / 绝对路径（相对路径按脚本目录解析） | `AUTO` |
| `status_codes` | 视为限流的请求状态码列表 | `[403]` |
| `window_match` | 用于定位 AutoClaw 窗口的标题关键字 | `AutoClaw` |
| `target_agent` | 目标智能体名 | `honor` |
| `interval` | 日志轮询间隔（秒） | `5` |
| `continue_text` | 要发送的文本 | `继续` |
| `send_enter` | 发送时是否回车间 | `true` |
| `cooldown` | 同一会话触发的冷却时间（秒） | `60` |
| `error_max_age` | 错误事件最长寿命（秒），超时视为已处理 | `300` |
| `input_ratio` / `input_offset_y` | 坐标兜底时输入框定位参数 | `0.58` / `-64` |

## 组件映射

输入框的 UIA 定位细节见 [`autoclaw_mapper.md`](autoclaw_mapper.md)。

## 许可证

MIT