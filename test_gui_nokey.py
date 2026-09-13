# -*- coding: utf-8 -*-
import importlib.util

spec = importlib.util.spec_from_file_location("whale_fresh_gui", r"D:\deepseek\whale-widget\whale_widget.pyw")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# 模拟没有 key / 没有会话
mod.CRED_FILE = r"D:\deepseek\whale-widget\no_such_cred.yaml"
mod.SESSION_CACHE_DIR = r"D:\deepseek\whale-widget\no_such_session"

w = mod.WhaleWidget()
status = {}

def grab():
    status["text"] = w.status.cget("text")

w.root.after(2000, grab)      # 2 秒时抓取状态
w.root.after(3000, w.root.destroy)  # 3 秒关闭
w.run()
print("GUI_NO_KEY_OK 状态提示:", status.get("text"))
