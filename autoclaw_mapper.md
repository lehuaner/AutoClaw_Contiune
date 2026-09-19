# autoclaw 组件映射表

探测日期：2026-09-19 | 目标程序：AutoClaw（Chromium/Electron 网页应用）

## 窗口定位
| 项 | 值 |
|---|---|
| 窗口标题 | `AutoClaw` |
| 窗口类名 | `Chrome_WidgetWin_1` |
| 渲染子窗口 | `Chrome_RenderWidgetHostHWND` |
| 挂载方式 | 枚举子窗口定位 render host → `uiautomation.ControlFromHandle(renderHost)` 挂到 Document |

## 组件映射
| 组件 | 用途 | 定位条件 | 实测属性 |
|---|---|---|---|
| 聊天输入框 | 填入"继续"并回车 | ControlType=`EditControl` 且 Name 含 `使用技能` | b=(781,831,1779,855) en=True，ValuePattern.IsReadOnly=False |

## 关键验证结论
- 输入框支持 **ValuePattern.SetValue**（可直接注入"继续"，读回成功）。
- 支持 **TextPattern**（DocumentRange.GetText(-1) 读到注入文本）。
- 无需坐标点击、无需剪贴板、无需键盘模拟。

## 主控脚本接入点（autoclaw_continue.py）
- `_find_render_host(hwnd)`：定位 render host 句柄
- `_uia_set_continue(hwnd, text)`：UIA 注入输入框文本（主方案）
- `_uia_focus_and_enter(hwnd)`：UIA 聚焦输入框并发回车（发送）
- `_coordinate_continue(hwnd)`：坐标+剪贴板兜底（UIA 不可用时回退）
- `_do_continue()`：编排以上，UIA 优先、坐标兜底