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
- 冷却 / 错误寿命控制，防止重复发送与误触发
- 系统托盘常驻（pystray 可选，缺失不阻塞主功能）
- 仅依赖 Windows 标准库 + ctypes，无需 pywin32

## 依赖

- Python 3（自带 tkinter/ctypes）
- 可选：`uiautomation`、`pystray`、`Pillow`（缺失时自动降级）

安装可选依赖：

```bash
pip install -r requirements.txt
```

## 运行

```bash
python autoclaw_continue.py
```

## 配置

配置文件 `autoclaw_continue.json` 支持按需调整，主要字段：

| 字段 | 说明 | 默认 |
|---|---|---|
| `log_path` | gateway 日志路径。**支持相对路径**，相对路径将按脚本所在目录解析；也可填写 `%USERPROFILE%` / `~` 或绝对路径 | `logs/gateway.log` |
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