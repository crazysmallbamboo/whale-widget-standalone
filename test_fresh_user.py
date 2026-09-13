# -*- coding: utf-8 -*-
"""全新用户模拟测试：只 clone 仓库、无原插件、无 DSH，挂件能否自包含运行"""
import importlib.util, os, shutil, tempfile, json

# 1. 模拟"全新 clone"：把代码+assets 复制到一个干净临时目录
src = r"D:\deepseek\whale-widget"
fresh = tempfile.mkdtemp(prefix="whale_fresh_")
shutil.copy(os.path.join(src, "whale_widget.pyw"), os.path.join(fresh, "whale_widget.pyw"))
shutil.copytree(os.path.join(src, "assets"), os.path.join(fresh, "assets"))
print("模拟全新 clone 目录:", fresh)

# 2. 从干净目录导入模块
spec = importlib.util.spec_from_file_location("whale_fresh", os.path.join(fresh, "whale_widget.pyw"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# 3. 把 DSH_HOME 指向一个不存在的临时目录（模拟"根本没有 DSH"）
fake_dsh = os.path.join(fresh, "no_dsh_here")
mod.DSH_HOME = fake_dsh
mod.CRED_FILE = os.path.join(fake_dsh, ".credentials.yaml")
mod.LEDGER_FILE = os.path.join(fake_dsh, ".dshw-usage.json")
mod.SESSION_CACHE_DIR = os.path.join(fake_dsh, "storages", "session_projcache", "sessions")

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond:
        passed += 1; print("  PASS %s" % name)
    else:
        failed += 1; print("  FAIL %s" % name)

print("\n=== 自包含性 ===")
check("图片在挂件自己的 assets 里", os.path.exists(os.path.join(fresh, "assets", "DSniang1.png")))
check("代码不依赖原插件路径（无 node_modules 引用）", "node_modules" not in open(os.path.join(fresh, "whale_widget.pyw"), encoding="utf-8").read())

print("\n=== 无 DSH 时的优雅降级 ===")
check("无 key 文件 -> read_api_key 返回 None", mod.read_api_key() is None)
check("无会话缓存 -> read_last_turn_cost 返回 None", mod.read_last_turn_cost() is None)
led = mod.load_ledger()
check("无账本 -> load_ledger 返回空账本", led.get("todayUsage") == 0)
led2 = mod.record_ledger(10.0, "CNY")
check("无账本 -> record_ledger 正常记首笔", led2.get("lastBalance") == 10.0)

print("\n=== 图片可用 PIL 加载（缩放）===")
try:
    from PIL import Image
    img = Image.open(os.path.join(fresh, "assets", "DSniang1.png")).convert("RGBA")
    w = 240
    h = int(img.height * w / img.width)
    img2 = img.resize((w, h), Image.LANCZOS)
    check("PIL 能加载并缩放鲸鱼图片", (img2.width == 240 and img2.height > 0))
except Exception as e:
    check("PIL 加载图片", False)
    print("    异常:", e)

print("\n=== 结果 ===")
print("通过 %d 项，失败 %d 项" % (passed, failed))
shutil.rmtree(fresh, ignore_errors=True)
import sys
sys.exit(1 if failed else 0)
