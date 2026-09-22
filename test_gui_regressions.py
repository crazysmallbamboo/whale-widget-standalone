# -*- coding: utf-8 -*-
"""挂件 GUI 交互回归测试。

覆盖这几类曾经踩过（或差点踩到）的交互问题：
  1. 没有 API Key 时，数据行必须显示 --，而不是永远停在「…」
  2. 改「大小」不能把用户拖好的窗口位置弹回右下角
  3. 拖动结束要把位置写进配置，位置没变则不写盘
  4. 重启后要恢复上次的位置
  5. 拉取失败要保留上一次的余额/消费（调暗），不能清成 --
  6. 后台线程交不回主线程时要能被报告出来，不能静默吞掉
  7. 配置写不进去时要提示，不能无声失败

用法：在仓库目录直接运行 `python test_gui_regressions.py`
所有路径都相对本脚本解析，并把配置 / 账本 / 凭据重定向到临时目录，
不会碰你本机的 %APPDATA%\\whale-widget\\config.json 与真实账本。
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_PATH = os.path.join(HERE, "whale_widget.pyw")

spec = importlib.util.spec_from_file_location("whale_widget", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TMP = tempfile.mkdtemp(prefix="whale_gui_regress_")
# 把一切会落盘的位置都改到临时目录，别污染真实环境
mod.CONFIG_FILE = os.path.join(TMP, "config.json")
mod.LEGACY_CONFIG_FILE = os.path.join(TMP, "legacy-config.json")
mod.CRED_FILE = os.path.join(TMP, "no-such-cred.yaml")
mod.DSH_HOME = TMP
mod.DEFAULT_LEDGER = os.path.join(TMP, ".dshw-usage.json")
mod.SESSION_CACHE_DIR = os.path.join(TMP, "no-such-sessions")

passed = failed = 0


def check(name, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print("  PASS %s" % name)
    else:
        failed += 1
        print("  FAIL %s: 期望 %r 实际 %r" % (name, expected, actual))


class FakeClick:
    """伪造一次鼠标事件，用来驱动拖动逻辑。"""

    def __init__(self, x_root, y_root):
        self.x_root = x_root
        self.y_root = y_root


def read_saved_config():
    try:
        with open(mod.CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


print("=== 1. 没有 API Key 时的界面 ===")
w = mod.WhaleWidget()
w.root.update()
check("剩余额度显示 --", w.lbl_bal.cget("text"), "--")
check("今日消费显示 --", w.lbl_today.cget("text"), "--")
check("本轮消耗显示 --", w.lbl_turn.cget("text"), "--")
check("上一轮对话显示 --", w.lbl_lastturn.cget("text"), "--")
check("价格行仍显示当期价格（价格是本地算的，不需要 Key）",
      w.lbl_price.cget("text").startswith(("峰价", "谷价")), True)
check("状态栏提示去设置 Key", w.status.cget("text"), "未找到 API Key（右键可设置）")

print("\n=== 2. 改「大小」不再把窗口弹回右下角 ===")
w.root.geometry("+120+90")
w.root.update()
before = (w.root.winfo_x(), w.root.winfo_y())
w._set_size(1.4)
w.root.update()
after = (w.root.winfo_x(), w.root.winfo_y())
check("改大小后窗口位置不变", after, before)
check("改大小后图片重新加载成功", w.photo is not None, True)
check("改大小后状态栏没被重置成「正在加载…」",
      w.status.cget("text") == "正在加载…", False)

print("\n=== 3. 拖动结束把位置写进配置 ===")
w.root.geometry("+260+180")
w.root.update()
w._start_drag(FakeClick(300, 220))          # 按下（记录起点）
w.root.geometry("+300+210")                  # 拖动中移动
w.root.update()
w._end_drag()                                # 松开
check("配置里写入了拖动后的位置", read_saved_config().get("pos"), [300, 210])

print("\n=== 4. 位置没变就不必反复写盘 ===")
os.remove(mod.CONFIG_FILE)
w._start_drag(FakeClick(340, 250))
w._end_drag()
check("位置未变化时不写配置", os.path.exists(mod.CONFIG_FILE), False)

print("\n=== 5. 重启后恢复上次的位置 ===")
w._save_pos()
w.root.destroy()
w = mod.WhaleWidget()
w.root.update()
check("重启后位置被恢复（没有回到右下角）",
      (w.root.winfo_x(), w.root.winfo_y()), (300, 210))

print("\n=== 6. 拉取失败保留上一次的数据 ===")
w._apply_data(9.99, "CNY", 1.23, 0.5)
check("成功时余额显示正确", w.lbl_bal.cget("text"), "¥9.99")
check("成功时今日消费显示正确", w.lbl_today.cget("text"), "¥1.2300")
check("成功时上一轮对话显示正确", w.lbl_lastturn.cget("text"), "¥0.5000")
w._apply_error("网络开小差")
check("失败后余额数字仍保留", w.lbl_bal.cget("text"), "¥9.99")
check("失败后今日消费仍保留", w.lbl_today.cget("text"), "¥1.2300")
check("失败后上一轮对话仍保留", w.lbl_lastturn.cget("text"), "¥0.5000")
check("失败后价格行仍显示价格",
      w.lbl_price.cget("text").startswith(("峰价", "谷价")), True)
check("失败后状态栏报错", w.status.cget("text").startswith("拉取失败"), True)

print("\n=== 7. 后台线程交不回主线程时不再静默 ===")
real_after = w.root.after


def boom(*a, **k):
    raise RuntimeError("main thread is not in main loop")


w.root.after = boom
ok = w._safe_after(lambda: None)
w.root.after = real_after
check("_safe_after 返回 False 表示投递失败", ok, False)
check("失败被记录下来", w._ui_error is not None, True)
w._report_ui_error()
check("失败被显示到状态栏", w.status.cget("text").startswith("界面更新失败"), True)
check("报告之后清空记录，不会反复刷屏", w._ui_error, None)

print("\n=== 8. 配置写不进去时明确提示 ===")
good_config = mod.CONFIG_FILE
mod.CONFIG_FILE = TMP  # 指向目录，写文件必然失败
w._set_size(0.7)
check("配置保存失败有提示", w.status.cget("text").startswith("配置保存失败"), True)
mod.CONFIG_FILE = good_config

w.root.destroy()
shutil.rmtree(TMP, ignore_errors=True)

print("\n=== 结果 ===")
print("通过 %d 项，失败 %d 项" % (passed, failed))
sys.exit(1 if failed else 0)
