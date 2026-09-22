# -*- coding: utf-8 -*-
"""GUI 无 DSH 场景测试：没有 API key / 没有 DSH 时窗口能否正常启动并提示

用法：在仓库目录直接运行 `python test_gui_nokey.py`（不依赖任何绝对路径）。
"""
import importlib.util, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_PATH = os.path.join(HERE, "whale_widget.pyw")

spec = importlib.util.spec_from_file_location("whale_widget", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# 模拟完全没有 DSH：所有相关路径指向不存在的临时位置
tmp = tempfile.mkdtemp(prefix="whale_nokey_")
mod.DSH_HOME = os.path.join(tmp, "no_dsh")
mod.CRED_FILE = os.path.join(mod.DSH_HOME, ".credentials.yaml")
mod.DEFAULT_LEDGER = os.path.join(mod.DSH_HOME, ".dshw-usage.json")
mod.SESSION_CACHE_DIR = os.path.join(mod.DSH_HOME, "storages", "session_projcache", "sessions")
mod.CONFIG_FILE = os.path.join(tmp, "config", "config.json")
mod.LEGACY_CONFIG_FILE = os.path.join(tmp, "legacy.json")

w = mod.WhaleWidget()
status = {}

def grab():
    status["text"] = w.status.cget("text")

w.root.after(2000, grab)               # 2 秒时抓取状态
w.root.after(3000, w.root.destroy)     # 3 秒关闭
w.run()
print("GUI_NO_KEY_OK 状态提示:", status.get("text"))
