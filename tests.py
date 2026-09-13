# -*- coding: utf-8 -*-
"""鲸鱼挂件 —— 全面边界测试"""
import importlib.util, datetime, os, tempfile, json

spec = importlib.util.spec_from_file_location("whale_widget", r"D:\deepseek\whale-widget\whale_widget.pyw")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TZ8 = datetime.timezone(datetime.timedelta(hours=8))
def dt(month, day, hour, weekday):
    # 构造一个指定 weekday 的日期：2026-09-07 是周一
    base = datetime.datetime(2026, 9, 7 + weekday, hour, 0, tzinfo=TZ8)  # 周一起算
    return base

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
check("周一 10:00 峰", mod.is_peak(dt(9,7,10,0)), True)
check("周一 15:00 峰", mod.is_peak(dt(9,7,15,0)), True)
check("周一 13:00 谷(午休)", mod.is_peak(dt(9,7,13,0)), False)
check("周一 20:00 谷(晚)", mod.is_peak(dt(9,7,20,0)), False)
check("周一 08:59 谷", mod.is_peak(dt(9,7,8,0)), False)
check("周一 12:00 谷(峰尾)", mod.is_peak(dt(9,7,12,0)), False)
check("周六 10:00 谷(周末)", mod.is_peak(dt(9,12,10,5)), False)
check("周日 15:00 谷(周末)", mod.is_peak(dt(9,13,15,6)), False)

print("\n=== 2. 价格表 ===")
# 直接测 PRO_PRICE 输出价
peak, price = mod.current_price()
check("current_price 返回 (bool,float)", (isinstance(peak,bool) and isinstance(price,(int,float))), True)

print("\n=== 3. API key 读取 ===")
tmpd = tempfile.mkdtemp()
def set_cred(content):
    p = os.path.join(tmpd, ".credentials.yaml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    mod.CRED_FILE = p
set_cred("DEEPSEEK_API_KEY: sk-test1234567890")
check("正常读取", mod.read_api_key(), "sk-test1234567890")
set_cred("records:\n  DEEPSEEK_API_KEY: sk-abc")
check("缩进格式", mod.read_api_key(), "sk-abc")
set_cred("nothing here")
check("无 key", mod.read_api_key(), None)

print("\n=== 4. 记账逻辑（临时账本）===")
tmp_ledger = os.path.join(tmpd, "ledger.json")
mod.LEDGER_FILE = tmp_ledger

def ledger():
    with open(tmp_ledger, encoding="utf-8") as f:
        return json.load(f)

# 初始
led = mod.record_ledger(10.0, "CNY")
check("首次记账 todayUsage=0", led["todayUsage"], 0)
check("首次记账 lastBalance=10", led["lastBalance"], 10.0)
# 余额下降
led = mod.record_ledger(9.5, "CNY")
check("余额下降 10->9.5 记 0.5", round(led["todayUsage"],4), 0.5)
# 余额上升（充值）不记
led = mod.record_ledger(12.0, "CNY")
check("余额上升不记消费", round(led["todayUsage"],4), 0.5)
check("充值后 lastBalance=12", led["lastBalance"], 12.0)
# 再下降
led = mod.record_ledger(11.0, "CNY")
check("12->11 记 1.0", round(led["todayUsage"],4), 1.5)
# 币种切换（不记差值）
led = mod.record_ledger(5.0, "USD")
check("币种切换不记差值", round(led["todayUsage"],4), 1.5)
check("币种切换后 lastCurrency=USD", led["lastCurrency"], "USD")
# 跨天（手动改日期字段模拟）
with open(tmp_ledger, encoding="utf-8") as f:
    d = json.load(f)
d["date"] = "2020-01-01"
with open(tmp_ledger, "w", encoding="utf-8") as f:
    json.dump(d, f)
led = mod.record_ledger(10.0, "CNY")
check("跨天归零", led["todayUsage"], 0)
check("跨天归档 history", led["history"].get("2020-01-01"), 1.5)
check("跨天后 lastBalance=10", led["lastBalance"], 10.0)

print("\n=== 5. 余额接口解析 ===")
def pick(infos):
    # 复制 fetch_balance 里的选择逻辑
    def num(x):
        try:
            v = x.get("total_balance")
            return float(v) if v is not None else float("nan")
        except Exception:
            return float("nan")
    info = None
    for x in infos:
        if x.get("currency") == "CNY" and num(x) > 0:
            info = x; break
    if info is None:
        for x in infos:
            if num(x) > 0:
                info = x; break
    if info is None:
        info = next((x for x in infos if x.get("currency") == "CNY"), infos[0] if infos else None)
    return info

check("多币种选CNY", pick([{"currency":"USD","total_balance":"5"},{"currency":"CNY","total_balance":"10"}])["total_balance"], "10")
check("空列表", pick([]), None)
check("单币种", pick([{"currency":"CNY","total_balance":"3.14"}])["total_balance"], "3.14")

print("\n=== 6. 上一轮对话消耗 ===")
last = mod.read_last_turn_cost()
if last is not None:
    check("读取到上一轮消耗(数值>=0)", last >= 0, True)
    print("   上一轮消耗 = ¥%.6f" % last)
else:
    check("无会话数据时返回 None", last, None)

print("\n=== 结果 ===")
print("通过 %d 项，失败 %d 项" % (passed, failed))
import sys
sys.exit(1 if failed else 0)
