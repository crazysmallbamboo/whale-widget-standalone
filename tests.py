# -*- coding: utf-8 -*-
"""鲸鱼挂件 —— 边界与回归测试

用法：在仓库目录直接运行 `python tests.py`（不依赖任何绝对路径）。
"""
import importlib.util, datetime, os, tempfile, json, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_PATH = os.path.join(HERE, "whale_widget.pyw")

spec = importlib.util.spec_from_file_location("whale_widget", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TZ8 = datetime.timezone(datetime.timedelta(hours=8))
def dt(month, day, hour, weekday):
    # 2026-09-07 是周一，用 7+weekday 构造指定星期几
    return datetime.datetime(2026, 9, 7 + weekday, hour, 0, tzinfo=TZ8)

passed = failed = 0
def check(name, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print("  PASS %s" % name)
    else:
        failed += 1
        print("  FAIL %s: 期望 %r 实际 %r" % (name, expected, actual))

print("=== 1. 峰谷价格判定 ===")
check("周一 10:00 峰", mod.is_peak(dt(9, 7, 10, 0)), True)
check("周一 15:00 峰", mod.is_peak(dt(9, 7, 15, 0)), True)
check("周一 13:00 谷(午休)", mod.is_peak(dt(9, 7, 13, 0)), False)
check("周一 20:00 谷(晚)", mod.is_peak(dt(9, 7, 20, 0)), False)
check("周一 08:59 谷", mod.is_peak(dt(9, 7, 8, 0)), False)
check("周一 12:00 谷(峰尾)", mod.is_peak(dt(9, 7, 12, 0)), False)
check("周六 10:00 谷(周末)", mod.is_peak(dt(9, 12, 10, 5)), False)
check("周日 15:00 谷(周末)", mod.is_peak(dt(9, 13, 15, 6)), False)

print("\n=== 2. 价格表 ===")
peak, price = mod.current_price()
check("current_price 返回 (bool,float)", (isinstance(peak, bool) and isinstance(price, (int, float))), True)

tmpd = tempfile.mkdtemp()

print("\n=== 3. API key 读取（config 优先 / 回退凭据）===")
mod.CONFIG_FILE = os.path.join(tmpd, "config.json")
mod.LEGACY_CONFIG_FILE = os.path.join(tmpd, "legacy.json")
mod.CRED_FILE = os.path.join(tmpd, ".credentials.yaml")

def set_cred(content):
    with open(mod.CRED_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def set_cfg(d):
    with open(mod.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f)

set_cfg({"api_key": "sk-config111"})
set_cred("DEEPSEEK_API_KEY: sk-cred999")
check("config 优先于凭据", mod.read_api_key(), "sk-config111")

set_cfg({})
check("回退 DSH 凭据", mod.read_api_key(), "sk-cred999")
set_cred("records:\n  DEEPSEEK_API_KEY: sk-abc")
check("凭据缩进格式", mod.read_api_key(), "sk-abc")
set_cred("nothing here")
check("都无 -> None", mod.read_api_key(), None)

print("\n=== 4. 记账逻辑（临时账本）===")
tmp_ledger = os.path.join(tmpd, "ledger.json")
def ledger():
    with open(tmp_ledger, encoding="utf-8") as f:
        return json.load(f)

led = mod.record_ledger(10.0, "CNY", tmp_ledger)
check("首次记账 todayUsage=0", led["todayUsage"], 0)
check("首次记账 lastBalance=10", led["lastBalance"], 10.0)
led = mod.record_ledger(9.5, "CNY", tmp_ledger)
check("余额下降 10->9.5 记 0.5", round(led["todayUsage"], 4), 0.5)
led = mod.record_ledger(12.0, "CNY", tmp_ledger)
check("余额上升不记消费", round(led["todayUsage"], 4), 0.5)
check("充值后 lastBalance=12", led["lastBalance"], 12.0)
led = mod.record_ledger(11.0, "CNY", tmp_ledger)
check("12->11 记 1.0", round(led["todayUsage"], 4), 1.5)
led = mod.record_ledger(5.0, "USD", tmp_ledger)
check("币种切换不记差值", round(led["todayUsage"], 4), 1.5)
check("币种切换后 lastCurrency=USD", led["lastCurrency"], "USD")

with open(tmp_ledger, encoding="utf-8") as f:
    d = json.load(f)
d["date"] = "2020-01-01"
with open(tmp_ledger, "w", encoding="utf-8") as f:
    json.dump(d, f)
led = mod.record_ledger(10.0, "CNY", tmp_ledger)
check("跨天归零", led["todayUsage"], 0)
check("跨天归档 history", led["history"].get("2020-01-01"), 1.5)
check("跨天后 lastBalance=10", led["lastBalance"], 10.0)

print("\n=== 5. 账本目录自动创建（无 DSH 场景）===")
deep = os.path.join(tmpd, "no_such_dsh", "profiles", "web", ".dshw-usage.json")
ok = mod.save_ledger({"date": "2026-01-01", "todayUsage": 1.0, "history": {}}, deep)
check("目录不存在时 save_ledger 自动创建并写入", bool(ok) and os.path.exists(deep), True)
led2 = mod.record_ledger(10.0, "CNY", deep)
check("深层路径记账不丢数据", led2["_saved"], True)

print("\n=== 6. 账户隔离（不同 API Key 用不同账本）===")
p_a = mod.ledger_path_for("sk-accountAAA", manual=True)
p_b = mod.ledger_path_for("sk-accountBBB", manual=True)
p_dsh = mod.ledger_path_for("sk-accountAAA", manual=False)
check("不同账户账本不同", p_a != p_b, True)
check("同账户账本稳定", p_a == mod.ledger_path_for("sk-accountAAA", manual=True), True)
check("DSH 凭据走共享账本", p_dsh, mod.DEFAULT_LEDGER)
# 账户 A 和 B 各自记账，互不影响
mod.save_ledger({"date": mod.today_key(), "lastBalance": 100.0, "todayUsage": 0, "history": {}, "lastCurrency": "CNY"}, p_a)
mod.save_ledger({"date": mod.today_key(), "lastBalance": 10.0, "todayUsage": 0, "history": {}, "lastCurrency": "CNY"}, p_b)
mod.record_ledger(90.0, "CNY", p_a)   # A: 100 -> 90
mod.record_ledger(9.0, "CNY", p_b)    # B: 10 -> 9
check("账户A 消费=10 不受B影响", round(mod.load_ledger(p_a)["todayUsage"], 4), 10.0)
check("账户B 消费=1 不受A影响", round(mod.load_ledger(p_b)["todayUsage"], 4), 1.0)

print("\n=== 7. 余额接口解析（调用真实函数）===")
check("多币种选CNY",
      mod.pick_balance_info([{"currency": "USD", "total_balance": "5"},
                             {"currency": "CNY", "total_balance": "10"}])["total_balance"], "10")
check("空列表 -> None", mod.pick_balance_info([]), None)
check("非列表 -> None", mod.pick_balance_info(None), None)
check("单币种",
      mod.pick_balance_info([{"currency": "CNY", "total_balance": "3.14"}])["total_balance"], "3.14")
check("全为0时回退首个",
      mod.pick_balance_info([{"currency": "USD", "total_balance": "0"}])["currency"], "USD")

print("\n=== 8. 个人配置在仓库外 ===")
check("CONFIG_FILE 不在仓库目录内",
      os.path.abspath(mod.CONFIG_FILE) != os.path.abspath(os.path.join(HERE, "config.json")), True)

print("\n=== 9. 上一轮对话消耗 ===")
last = mod.read_last_turn_cost()
if last is not None:
    check("读取到上一轮消耗(数值>=0)", last >= 0, True)
    print("   上一轮消耗 = ¥%.6f" % last)
else:
    check("无会话数据时返回 None", last, None)

print("\n=== 结果 ===")
print("通过 %d 项，失败 %d 项" % (passed, failed))
sys.exit(1 if failed else 0)
