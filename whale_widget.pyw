# -*- coding: utf-8 -*-
"""
鲸鱼娘余额挂件（独立版）
- 不依赖 DeepSeek Harness，可单独运行
- 沿用原挂件的鲸鱼娘图片素材与价格/记账逻辑
- 显示：当前时段 token 价格、今日消费、剩余额度、本轮消耗
"""
import json
import os
import re
import threading
import datetime
import urllib.request
import tkinter as tk

# ---------------- 配置与路径 ----------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
WHALE_IMG = os.path.join(APP_DIR, "assets", "DSniang1.png")
DSH_HOME = os.path.join(os.path.expanduser("~"), ".dsh")
CRED_FILE = os.path.join(DSH_HOME, ".credentials.yaml")
LEDGER_FILE = os.path.join(DSH_HOME, ".dshw-usage.json")
SESSION_CACHE_DIR = os.path.join(DSH_HOME, "storages", "session_projcache", "sessions")
BALANCE_URL = "https://api.deepseek.com/user/balance"
REFRESH_MS = 60000  # 60 秒自动刷新

MODEL = "deepseek-v4-pro"
# DeepSeek CNY 价格每百万 token：[谷价, 峰价]
PEAK_HOURS = [(9, 12), (14, 18)]  # 工作日 9:00-12:00、14:00-18:00（北京时间），周末全天谷价
PRO_PRICE = {"hit": (0.15, 0.3), "miss": (4.5, 9.0), "out": (13.5, 27.0)}


def beijing_now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def is_peak(dt=None):
    dt = dt or beijing_now()
    if dt.weekday() >= 5:  # 周六/周日
        return False
    h = dt.hour
    return any(s <= h < e for s, e in PEAK_HOURS)


def current_price():
    peak = is_peak()
    out = PRO_PRICE["out"][1 if peak else 0]
    return peak, out


def read_api_key():
    try:
        with open(CRED_FILE, encoding="utf-8") as f:
            m = re.search(r"DEEPSEEK_API_KEY:\s*(sk-\S+)", f.read())
            return m.group(1) if m else None
    except Exception:
        return None


def today_key(dt=None):
    return (dt or beijing_now()).strftime("%Y-%m-%d")


def load_ledger():
    try:
        with open(LEDGER_FILE, encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("date"), str):
                return d
    except Exception:
        pass
    return {"date": today_key(), "lastBalance": None, "todayUsage": 0,
            "history": {}, "lastCurrency": ""}


def save_ledger(led):
    try:
        with open(LEDGER_FILE, "w", encoding="utf-8") as f:
            json.dump(led, f, ensure_ascii=False)
    except Exception:
        pass


def record_ledger(balance, currency="CNY"):
    led = load_ledger()
    t = today_key()
    cur = str(currency or "")
    if led.get("date") != t:
        if led.get("date") and isinstance(led.get("todayUsage"), (int, float)):
            led.setdefault("history", {})[led["date"]] = led["todayUsage"]
        led["date"] = t
        led["lastBalance"] = balance
        led["lastCurrency"] = cur
        led["todayUsage"] = 0
    elif led.get("lastCurrency") and cur and led["lastCurrency"] != cur:
        led["lastBalance"] = balance
        led["lastCurrency"] = cur
    else:
        prev = led.get("lastBalance")
        if isinstance(prev, (int, float)) and isinstance(balance, (int, float)) and balance < prev:
            led["todayUsage"] = (led.get("todayUsage") or 0) + (prev - balance)
        led["lastBalance"] = balance
        led["lastCurrency"] = cur
    keys = sorted(led.get("history", {}))
    while len(keys) > 30:
        led["history"].pop(keys.pop(0), None)
    save_ledger(led)
    return led


def fetch_balance(key):
    req = urllib.request.Request(BALANCE_URL, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    infos = data.get("balance_infos") or []

    def num(x):
        try:
            v = x.get("total_balance")
            return float(v) if v is not None else float("nan")
        except Exception:
            return float("nan")

    info = None
    for x in infos:
        if x.get("currency") == "CNY" and num(x) > 0:
            info = x
            break
    if info is None:
        for x in infos:
            if num(x) > 0:
                info = x
                break
    if info is None:
        info = next((x for x in infos if x.get("currency") == "CNY"), infos[0] if infos else None)
    if info is None:
        raise ValueError("balance_infos 为空")
    return float(info["total_balance"]), str(info.get("currency") or "CNY")


def read_last_turn_cost():
    """读取 DSH 最近一次对话（上一轮）的消耗金额。

    从 DSH 的会话投影缓存里取 tokenUsage.last.buckets（上一轮 token 用量），
    按当前峰谷价折算成金额。无数据/解析失败返回 None。
    """
    try:
        if not os.path.isdir(SESSION_CACHE_DIR):
            return None
        files = [os.path.join(SESSION_CACHE_DIR, f) for f in os.listdir(SESSION_CACHE_DIR)
                 if f.endswith(".json")]
        if not files:
            return None
        files.sort(key=os.path.getmtime, reverse=True)
        with open(files[0], encoding="utf-8") as fp:
            data = json.load(fp)
        last = data["record"]["rows"]["tokenUsage"]["val"].get("last")
        if not last:
            return None
        buckets = last.get("buckets") or {}
        miss = int(buckets.get("uncachedInputTokens") or 0)   # 未命中缓存输入
        hit = int(buckets.get("cacheReadTokens") or 0)         # 命中缓存输入
        out = int(buckets.get("outputTokens") or 0)            # 输出
        if miss == 0 and hit == 0 and out == 0:
            return None
        idx = 1 if is_peak() else 0
        cost = (miss * PRO_PRICE["miss"][idx] + hit * PRO_PRICE["hit"][idx]
                + out * PRO_PRICE["out"][idx]) / 1_000_000
        return cost
    except Exception:
        return None


# ---------------- UI ----------------
BG = "#12151f"
PANEL = "#1a1f2e"
FG = "#e8ecf5"
DIM = "#8a93a8"
ACCENT = "#7fd0ff"
GREEN = "#5ad0a0"
RED = "#ff7b7b"
GOLD = "#f0c060"


class WhaleWidget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)  # 无边框
        self.root.attributes("-topmost", True)  # 置顶
        self.root.configure(bg=BG)

        self.api_key = read_api_key()
        self.balance = None
        self.currency = "CNY"
        self.today_usage = None
        self.session_start = None
        self.session_usage = 0.0
        self.error = None
        self._fetching = False  # 防止线程重叠

        self._build_ui()
        self._position_bottom_right()

        # 拖动
        self._drag = None
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)

        # 关闭
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self._refresh()
        self.root.after(REFRESH_MS, self._auto_refresh)

    def _build_ui(self):
        # 外框
        outer = tk.Frame(self.root, bg=BG, bd=0)
        outer.pack(fill="both", expand=True)

        # 标题栏
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(head, text="🐋 鲸鱼娘 · 余额", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        close = tk.Label(head, text="✕", bg=BG, fg=DIM, font=("Microsoft YaHei UI", 12))
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.root.destroy())

        # 信息面板
        panel = tk.Frame(outer, bg=PANEL)
        panel.pack(fill="x", padx=12, pady=8)

        self.lbl_price = self._row(panel, "Token价格", "…", 0)
        self.lbl_today = self._row(panel, "今日消费", "…", 1)
        self.lbl_bal = self._row(panel, "剩余额度", "…", 2)
        self.lbl_turn = self._row(panel, "本轮消耗", "…", 3)
        self.lbl_lastturn = self._row(panel, "上一轮对话", "…", 4)

        # 状态提示（错误/更新时间）
        self.status = tk.Label(outer, text="正在加载…", bg=BG, fg=DIM,
                               font=("Microsoft YaHei UI", 8))
        self.status.pack(fill="x", padx=12, pady=(0, 4))

        # 鲸鱼娘图片
        self.photo = None
        self.img_label = tk.Label(outer, bg=BG, bd=0, cursor="hand2")
        self.img_label.pack(side="bottom", fill="x")
        self.img_label.bind("<Button-1>", self._manual_refresh)
        self._load_image()

    def _row(self, parent, label, value, idx):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=12, pady=6)
        tk.Label(row, text=label, bg=PANEL, fg=DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        val = tk.Label(row, text=value, bg=PANEL, fg=FG,
                       font=("Microsoft YaHei UI", 10, "bold"))
        val.pack(side="right")
        return val

    def _load_image(self):
        try:
            from PIL import Image, ImageTk
            img = Image.open(WHALE_IMG).convert("RGBA")
            w = 240
            h = int(img.height * w / img.width)
            img = img.resize((w, h), Image.LANCZOS)
            self.photo = ImageTk.PhotoImage(img)
            self.img_label.configure(image=self.photo)
        except Exception as e:
            self.img_label.configure(text="(图片加载失败)", fg=DIM)

    def _position_bottom_right(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        self.root.geometry("+%d+%d" % (sw - w - 24, sh - h - 24))

    def _start_drag(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _do_drag(self, e):
        if self._drag:
            self.root.geometry("+%d+%d" % (e.x_root - self._drag[0], e.y_root - self._drag[1]))

    def _manual_refresh(self, e=None):
        self._refresh()

    def _auto_refresh(self):
        self._refresh()
        self.root.after(REFRESH_MS, self._auto_refresh)

    def _refresh(self):
        if self._fetching:
            return
        if not self.api_key:
            self._set_status("未找到 DEEPSEEK_API_KEY")
            return
        self._fetching = True
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _safe_after(self, fn, *args):
        """线程安全地回到主线程刷新 UI；窗口已销毁时静默忽略。"""
        try:
            self.root.after(0, fn, *args)
        except Exception:
            pass

    def _fetch_worker(self):
        try:
            try:
                bal, cur = fetch_balance(self.api_key)
                led = record_ledger(bal, cur)
                if self.session_start is None:
                    self.session_start = bal
                self.session_usage = max(0.0, self.session_start - bal)
                last_turn = read_last_turn_cost()
                self._safe_after(self._apply_data, bal, cur, led.get("todayUsage") or 0, last_turn)
            except Exception as e:
                self._safe_after(self._apply_error, str(e))
        finally:
            self._fetching = False

    def _apply_data(self, bal, cur, today, last_turn=None):
        self.balance = bal
        self.currency = cur
        self.today_usage = today
        self.error = None

        peak, price = current_price()
        period = "峰价" if peak else "谷价"
        self.lbl_price.configure(text="%s ¥%.2f/M" % (period, price), fg=GOLD)

        self.lbl_today.configure(text="¥%.4f" % today, fg=FG)
        self.lbl_bal.configure(text="¥%.2f" % bal, fg=GREEN)
        self.lbl_turn.configure(text="¥%.4f" % self.session_usage, fg=ACCENT)
        if last_turn is not None:
            self.lbl_lastturn.configure(text="¥%.4f" % last_turn, fg=ACCENT)
        else:
            self.lbl_lastturn.configure(text="--", fg=DIM)

        t = beijing_now().strftime("%H:%M:%S")
        self._set_status("已更新 %s · %s" % (t, self.currency))

    def _apply_error(self, msg):
        self.error = msg
        self.lbl_price.configure(text="…", fg=GOLD)
        self.lbl_today.configure(text="--", fg=FG)
        self.lbl_bal.configure(text="--", fg=FG)
        self.lbl_turn.configure(text="--", fg=FG)
        self.lbl_lastturn.configure(text="--", fg=DIM)
        self._set_status("拉取失败: %s" % msg[:60])

    def _set_status(self, text):
        self.status.configure(text=text)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    WhaleWidget().run()
