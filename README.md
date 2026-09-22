# 鲸鱼娘余额挂件（独立版）🐋

一只住在屏幕右下角的鲸鱼娘，帮你盯着 DeepSeek 账户的**余额与消费**。

**不依赖 DeepSeek Harness（DSH）**，可单独运行。沿用原挂件 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget) 的鲸鱼娘图片素材、峰谷价格表与记账逻辑。

## 功能

无边框、置顶、可拖动的悬浮窗，实时显示：

| 项目 | 说明 |
|---|---|
| **Token 价格** | 当前时段的峰价 / 谷价（deepseek-v4-pro） |
| **今日消费** | 余额差值记账，跨天自动归档（保留 30 天） |
| **剩余额度** | DeepSeek 账户余额 |
| **本轮消耗** | 本次打开挂件以来的余额下降 |
| **上一轮对话** | 最近一次 DSH 对话的 token 消耗金额 |

交互：

- **60 秒自动刷新**，点击鲸鱼娘手动刷新
- 拖动标题栏移动，点 ✕ 或按 `Esc` 关闭
- **右键菜单**：
  - **大小**：小 / 默认 / 大三档缩放（图片 + 字体）
  - **更换图片**：选择任意 PNG/JPG/GIF 图片替换鲸鱼娘
  - **恢复默认图片**：换回自带鲸鱼娘素材
  - **设置 API Key**：手动填入 DeepSeek API Key（无需 DSH）
  - 立即刷新 / 关闭

大小、图片与 API Key 都会**自动保存**到 `%APPDATA%\whale-widget\config.json`，下次打开沿用。

> 个人配置**存放在用户目录，不在本项目文件夹内**：这样即使你把项目提交 / 上传到 Git，API Key 也不会被一起带出去。首次运行会自动迁移旧版留在项目目录里的 `config.json`。

## 环境要求

- Windows
- Python 3.8+（含 tkinter，Anaconda / 官方 Python 均可）
- Pillow（PIL，用于缩放图片）

安装 Pillow：

```powershell
pip install pillow
```

## 使用

1. 双击 `鲸鱼余额挂件.bat` 启动（也可直接运行 `pythonw whale_widget.pyw`）
   - 启动器用 `%~dp0` 定位**同目录**下的脚本，不写死任何绝对路径，整个文件夹可以随意移动 / 改名
   - 依次尝试 `pythonw` → `pyw` → `python`，都没找到时给出安装提示
2. **配置 API Key（二选一）**：
   - 右键 → **设置 API Key**，手动填入（推荐，无需 DSH）
   - 或使用 `~/.dsh/.credentials.yaml` 里的 `DEEPSEEK_API_KEY`（如果装了 DSH）
3. 右键可调整大小、更换图片

> 完全不依赖 DSH：图片素材已内置，API Key 可手动配置。想开机自启，把 `.bat` 快捷方式放进「启动」文件夹即可。

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

每次观测余额后，用余额下降的差值累计当天消费；跨天自动归档，币种切换不记差值。

账本位置：

| 情况 | 账本文件 | 说明 |
|---|---|---|
| 手动填写的 API Key | `~/.dsh/.dshw-usage-<Key指纹>.json` | **按账户隔离**，换 Key 不会把两个账户的余额差算成消费 |
| 来自 DSH 凭据 / 未配置 | `~/.dsh/.dshw-usage.json` | 与原 DSH 挂件共享同一账本 |

- `~/.dsh` 不存在或不可写时，自动改用脚本同目录存放，并**自动创建**所需文件夹（无需 DSH 也能记账）
- 账本写入失败时状态栏会显示 `账本写入失败`，不会静默丢数据

### 上一轮对话消耗

读取 DSH 会话投影缓存 `~/.dsh/storages/session_projcache/sessions/*.json` 中最近一次会话的 `tokenUsage.last.buckets`（未命中输入 / 命中缓存 / 输出 token），按当前峰谷价折算金额。无 DSH 会话数据时显示 `--`。

## 自检 / 测试

仓库自带三个**可移植**的自检脚本（不含任何硬编码路径，克隆到任意目录都能跑）：

```powershell
python tests.py            # 38 项逻辑自检（价格表、峰谷判定、账本、币种选择、路径隔离）
python test_fresh_user.py  # 14 项「全新用户」模拟：拷到临时目录、清空环境，验证无 DSH 也能记账
python test_gui_nokey.py   # 无 Key 时启动 GUI，确认不崩溃并给出「未找到 API Key」提示
```

`tests.py` / `test_fresh_user.py` 直接调用 `whale_widget.pyw` 里的真实函数（不是复制的副本），所有路径都相对脚本自身解析，并把 `DSH_HOME` 等环境重定向到临时目录，不会污染你本机的配置与账本。

## 借物 / 致谢

- 鲸鱼娘图片素材（`assets/DSniang1.png` 等）
- 峰谷价格表与「小鲸鱼记账」逻辑

以上均来自 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)（MIT License，Copyright (c) 2026 MeteorNOX）。

## 许可

[MIT](LICENSE)
