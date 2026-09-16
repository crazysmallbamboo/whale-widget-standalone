# 鲸鱼娘余额挂件（独立版）🐋

一只住在屏幕右下角的鲸鱼娘，帮你盯着 DeepSeek 账户的**余额与消费**。

**不依赖 DeepSeek Harness（DSH）**，可单独运行。沿用原挂件 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget) 的鲸鱼娘图片素材、峰谷价格表与记账逻辑。

## 功能

无边框、置顶、可拖动的悬浮窗，实时显示：

| 项目 | 说明 |
|---|---|
| **Token 价格** | 当前时段的峰价 / 谷价（deepseek-v4-pro） |
| **今日消费** | 显示当前 Key 与全部 Key 的消费；余额差值记账，跨天自动归档（保留 30 天） |
| **剩余额度** | DeepSeek 账户余额 |
| **本轮消耗** | 当前 Key 在本次打开挂件以来的余额下降 |
| **上一轮对话** | 当前 Key 被选中期间观测到的最近一次 DSH 对话 token 消耗金额 |

交互：

- **60 秒自动刷新**，点击鲸鱼娘手动刷新
- 拖动标题栏移动，点 ✕ 或按 `Esc` 关闭
- **右键菜单**：
  - **大小**：小 / 默认 / 大三档缩放（图片 + 字体）
  - **更换图片**：选择任意 PNG/JPG/GIF 图片替换鲸鱼娘
  - **恢复默认图片**：换回自带鲸鱼娘素材
  - **API Key**：添加、切换或删除多个 DeepSeek API Key；切换后立即刷新
  - 立即刷新 / 关闭

大小、图片与消费记录会自动保存到用户目录的 `.config/whale-widget-standalone/`。API Key 保存在操作系统凭据库中，挂件只展示 `deepseek-api-key-xxxxxxxx` 形式的摘要名称。

## 环境要求

- Windows
- Python 3.10+（含 tkinter，Anaconda / 官方 Python 均可）
- Pillow（PIL，用于缩放图片）
- keyring（用于安全保存 API Key）

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 使用

1. 运行 `python whale_widget.pyw`（不显示终端窗口可用 `pythonw whale_widget.pyw`）；也可使用 `uv run whale_widget.pyw` 自动安装脚本依赖
2. 右键 → **API Key → 添加 API Key**，填入 DeepSeek API Key；可以继续添加、切换或删除 Key
3. 右键可调整大小、更换图片

> 查询余额不依赖 DSH：图片素材已内置，API Key 可手动配置。若使用旧版 `config.json`，首次启动会迁移其中的 Key 并移除明文；请另行检查备份和 Git 历史。想开机自启，可把启动命令的快捷方式放进「启动」文件夹。

## 工作原理

### 余额

调用 `https://api.deepseek.com/user/balance`，用 `DEEPSEEK_API_KEY` 拉取账户余额（优先选 CNY 币种）。

### Token 峰谷价格

沿用原挂件的价格表（CNY / 百万 token）：

| 模型 | 命中缓存 | 未命中缓存 | 输出 |
|---|---|---|---|
| deepseek-v4-pro | 0.15 / 0.30 | 4.5 / 9.0 | 13.5 / 27.0 |
| deepseek-v4-flash 等 | 0.05 / 0.10 | 1.5 / 3.0 | 4.5 / 9.0 |

（每项为「谷价 / 峰价」）

峰谷判定：工作日 9:00–12:00、14:00–18:00（北京时间）为峰价，其余及周末全天为谷价。

### 今日消费（小鲸鱼记账）

每次观测余额后，按每个 Key 当天最早与最近的余额计算消费；余额增加时视为充值或重置，不计为消费。窗口同时显示当前 Key 与全部 Key 的今日消费，合计只包含当前显示的币种，不做汇率换算。跨天自动归档，保留最近 30 天。账本存于用户目录的 `.config/whale-widget-standalone/usage.json`。

两次查询之间同时发生的充值和消费无法分别识别，消费数字是余额变化估算值。

### 上一轮对话消耗

读取 DSH 会话投影缓存 `~/.dsh/storages/session_projcache/sessions/*.json` 中的 `tokenUsage.last.buckets`（未命中输入 / 命中缓存 / 输出 token），按当前峰谷价折算金额。只把 Key 被选中期间新出现的记录归给该 Key；无可归属的会话数据时显示 `--`。

## 测试

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## 借物 / 致谢

- 鲸鱼娘图片素材（`assets/DSniang1.png` 等）
- 峰谷价格表与「小鲸鱼记账」逻辑

以上均来自 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)（MIT License，Copyright (c) 2026 MeteorNOX）。

## 许可

[MIT](LICENSE)
