# -*- coding: utf-8 -*-
"""全新用户模拟测试：只 clone 仓库、无原插件、无 DSH，挂件能否自包含运行

用法：在仓库目录直接运行 `python test_fresh_user.py`（不依赖任何绝对路径）。
"""
import importlib.util, os, shutil, tempfile, sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 1. 模拟"全新 clone"：把代码+assets 复制到一个干净临时目录
fresh = tempfile.mkdtemp(prefix="whale_fresh_")
shutil.copy(os.path.join(HERE, "whale_widget.pyw"), os.path.join(fresh, "whale_widget.pyw"))
shutil.copytree(os.path.join(HERE, "assets"), os.path.join(fresh, "assets"))
print("模拟全新 clone 目录:", fresh)

# 2. 从干净目录导入模块
spec = importlib.util.spec_from_file_location("whale_fresh", os.path.join(fresh, "whale_widget.pyw"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# 3. 把 DSH 相关路径指向不存在的深层目录（模拟"根本没有 DSH"）
fake_dsh = os.path.join(fresh, "no_dsh_here", "deep")
mod.DSH_HOME = fake_dsh
mod.CRED_FILE = os.path.join(fake_dsh, ".credentials.yaml")
mod.DEFAULT_LEDGER = os.path.join(fake_dsh, ".dshw-usage.json")
mod.SESSION_CACHE_DIR = os.path.join(fake_dsh, "storages", "session_projcache", "sessions")
mod.CONFIG_FILE = os.path.join(fresh, "user_config", "config.json")
mod.LEGACY_CONFIG_FILE = os.path.join(fresh, "legacy_config.json")

passed = failed = 0
def check(name, cond):
    global passed, failed
    if cond:
        passed += 1; print("  PASS %s" % name)
    else:
        failed += 1; print("  FAIL %s" % name)

print("\n=== 自包含性 ===")
check("图片在挂件自己的 assets 里", os.path.exists(os.path.join(fresh, "assets", "DSniang1.png")))
check("代码不依赖原插件路径（无 node_modules 引用）",
      "node_modules" not in open(os.path.join(fresh, "whale_widget.pyw"), encoding="utf-8").read())

print("\n=== 无 DSH 时的优雅降级 ===")
check("无 key 文件 -> read_api_key 返回 None", mod.read_api_key() is None)
check("无会话缓存 -> read_last_turn_cost 返回 None", mod.read_last_turn_cost() is None)
led = mod.load_ledger(mod.DEFAULT_LEDGER)
check("无账本 -> load_ledger 返回空账本", led.get("todayUsage") == 0)

print("\n=== 回归：无 DSH 时「今日消费」必须能累计（原 bug #2）===")
led = mod.record_ledger(10.0, "CNY", mod.DEFAULT_LEDGER)
check("账本目录被自动创建", os.path.isdir(os.path.dirname(mod.DEFAULT_LEDGER)))
check("首笔 lastBalance=10", led.get("lastBalance") == 10.0)
led = mod.record_ledger(9.0, "CNY", mod.DEFAULT_LEDGER)
check("余额 10->9 今日消费累计为 1", round(led.get("todayUsage") or 0, 4) == 1.0)
check("账本文件确实落盘", os.path.exists(mod.DEFAULT_LEDGER))
check("写入未失败（_saved=True）", led.get("_saved") is True)

print("\n=== 回归：个人配置写在仓库外（原 bug #4）===")
ok = mod.save_config({"size": 1.0})
check("save_config 成功（自动建目录）", ok is True)
check("配置文件路径不在仓库内",
      os.path.abspath(mod.CONFIG_FILE) != os.path.abspath(os.path.join(HERE, "config.json")))
check("仓库根目录没有被写入 config.json",
      not os.path.exists(os.path.join(fresh, "config.json")))

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
sys.exit(1 if failed else 0)
