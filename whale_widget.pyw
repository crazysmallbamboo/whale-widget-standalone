# -*- coding: utf-8 -*-
"""
鲸鱼娘余额挂件（独立版）
- 不依赖 DeepSeek Harness，可单独运行
- 沿用原挂件的鲸鱼娘图片素材与价格/记账逻辑
- 显示：当前时段 token 价格、今日消费、剩余额度、本轮消耗、上一轮对话消耗
- 支持：右键菜单调整大小、更换图片、设置 API Key（配置存仓库外）
"""
import hashlib
import json
import os
import re
import threading
import time
import datetime
import urllib.request
import tkinter as tk
from tkinter import filedialog

# ---------------- 路径 ----------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
WHALE_IMG = os.path.join(APP_DIR, "assets", "DSniang1.png")

DSH_HOME = os.path.join(os.path.expanduser("~"), ".dsh")
CRED_FILE = os.path.join(DSH_HOME, ".credentials.yaml")
SESSION_CACHE_DIR = os.path.join(DSH_HOME, "storages", "session_projcache", "sessions")
DEFAULT_LEDGER = os.path.join(DSH_HOME, ".dshw-usage.json")

BALANCE_URL = "https://api.deepseek.com/user/balance"
REFRESH_MS = 60000  # 60 秒自动刷新

MODEL = "deepseek-v4-pro"
# DeepSeek CNY 价格每百万 token：[谷价, 峰价]
PEAK_HOURS = [(9, 12), (14, 18)]  # 工作日 9:00-12:00、14:00-18:00（北京时间），周末全天谷价
PRO_PRICE = {"hit": (0.15, 0.3), "miss": (4.5, 9.0), "out": (13.5, 27.0)}

SIZE_PRESETS = {"小": 0.7, "默认": 1.0, "大": 1.4}
BASE_IMG_W = 240

# ---- 边框拖拽缩放 ----
MIN_SCALE = 0.4          # 缩放下限（240 * 0.4 = 96px 宽）
MAX_SCALE = 3.0          # 缩放上限
RESIZE_MARGIN = 6        # 距窗口边缘多少像素内算「抓住了边框」
BORDER_W = 1             # 可见边框粗细
# 拖动边框时的最小重绘间隔。Tk 每帧要重排整棵控件树并重建图片（几十毫秒），
# 不节流的话鼠标事件会排在队列里，表现为「松手之后挂件还在继续缩放」。
RESIZE_INTERVAL_MS = 33
# 八个方向对应的鼠标指针
ZONE_CURSORS = {
    "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
    "e": "sb_h_double_arrow", "w": "sb_h_double_arrow",
    "ne": "size_ne_sw", "sw": "size_ne_sw",
    "nw": "size_nw_se", "se": "size_nw_se",
}


def _user_config_path():
    """个人配置（可能含 API Key）放在仓库外，避免被 git 误提交。"""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "whale-widget", "config.json")


CONFIG_FILE = _user_config_path()
LEGACY_CONFIG_FILE = os.path.join(APP_DIR, "config.json")  # 旧版位置，仅供迁移读取


# ---------------- 配置 ----------------
def load_config():
    """读取个人配置：优先仓库外的新位置，其次迁移旧版（仓库内 config.json）。"""
    for path, migrate in ((CONFIG_FILE, False), (LEGACY_CONFIG_FILE, True)):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                if migrate:
                    save_config(d)  # 从旧位置迁移到新位置
                return d
        except Exception:
            continue
    return {}


def save_config(cfg):
    """写入个人配置（仓库外）。返回是否成功。"""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def read_api_key():
    # 1. 优先读挂件自己的配置（不依赖 DSH）
    try:
        cfg = load_config()
        if cfg.get("api_key"):
            return str(cfg["api_key"])
    except Exception:
        pass
    # 2. 回退到 DSH 凭据文件
    try:
        with open(CRED_FILE, encoding="utf-8") as f:
            # 值可能被引号包起来（DEEPSEEK_API_KEY: "sk-..."），两种引号都要认
            m = re.search(r"""DEEPSEEK_API_KEY:\s*["']?(sk-[^\s"']+)["']?""", f.read())
            return m.group(1) if m else None
    except Exception:
        return None


# ---------------- 时间 / 价格 ----------------
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


# ---------------- 账本 ----------------
def today_key(dt=None):
    return (dt or beijing_now()).strftime("%Y-%m-%d")


def ledger_base_dir():
    """账本目录：优先 ~/.dsh（与原 DSH 挂件共享），不可写则退回程序目录。"""
    for d in (DSH_HOME, APP_DIR):
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".dshw-probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return d
        except Exception:
            continue
    return APP_DIR


def ledger_path_for(key=None, manual=False):
    """账本文件路径。

    - 手动 API Key（config.json 里配置的）：按 Key 指纹隔离，切换账户互不污染
    - DSH 凭据 / 无 Key：沿用 ~/.dsh/.dshw-usage.json（与原 DSH 挂件共享）
    """
    base = ledger_base_dir()
    if manual and key:
        fp = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:10]
        return os.path.join(base, ".dshw-usage-%s.json" % fp)
    return os.path.join(base, ".dshw-usage.json")


def load_ledger(path=None):
    path = path or DEFAULT_LEDGER
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("date"), str):
            return d
    except Exception:
        pass
    return {"date": today_key(), "lastBalance": None, "todayUsage": 0,
            "history": {}, "lastCurrency": ""}


def save_ledger(led, path=None):
    """写入账本；目录不存在会创建。返回是否成功（不再静默吞掉失败）。"""
    path = path or DEFAULT_LEDGER
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(led, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def record_ledger(balance, currency="CNY", path=None):
    """按余额差值累计当天消费；跨天归档，币种切换只换基准不记差值。"""
    path = path or DEFAULT_LEDGER
    led = load_ledger(path)
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
    led["_saved"] = save_ledger(led, path)
    return led


# ---------------- 余额 ----------------
def pick_balance_info(infos):
    """从 balance_infos 里挑出最合适的账户余额条目（供 fetch_balance 与测试复用）。"""
    if not isinstance(infos, list) or not infos:
        return None

    def num(x):
        try:
            v = x.get("total_balance")
            return float(v) if v is not None else float("nan")
        except Exception:
            return float("nan")

    for x in infos:
        if x.get("currency") == "CNY" and num(x) > 0:
            return x
    for x in infos:
        if num(x) > 0:
            return x
    return next((x for x in infos if x.get("currency") == "CNY"), infos[0])


def fetch_balance(key):
    req = urllib.request.Request(BALANCE_URL, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    info = pick_balance_info(data.get("balance_infos"))
    if info is None:
        raise ValueError("balance_infos 为空")
    return float(info["total_balance"]), str(info.get("currency") or "CNY")


def read_last_turn_cost():
    """读取 DSH 最近一次对话（上一轮）的消耗金额。"""
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
        miss = int(buckets.get("uncachedInputTokens") or 0)
        hit = int(buckets.get("cacheReadTokens") or 0)
        out = int(buckets.get("outputTokens") or 0)
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
BORDER = "#2b3550"   # 常态边框颜色（比面板略亮，能看出边界）


class WhaleWidget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)

        # 配置：大小 + 图片 + 可选 API Key
        self.config = load_config()
        self.image_path = self.config.get("image", WHALE_IMG)
        try:
            self.size_scale = float(self.config.get("size", 1.0))
        except Exception:
            self.size_scale = 1.0
        self.size_scale = max(MIN_SCALE, min(MAX_SCALE, self.size_scale))

        self.api_key = read_api_key()
        # 账本：手动 Key 按账户隔离；DSH 凭据沿用共享账本
        self.ledger_file = ledger_path_for(self.api_key, manual=bool(self.config.get("api_key")))

        self.balance = None
        self.currency = "CNY"
        self.today_usage = None
        self.last_turn = None
        self.session_start = None
        self.session_usage = 0.0
        self.error = None
        self._fetching = False
        self._ledger_saved = True
        self._ui_error = None

        # 会随缩放变化的字体控件表：(控件, 基准字号, 是否加粗)
        self._font_widgets = []
        # 原图缓存，避免拖动边框时反复从磁盘读图
        self._src_img = None
        self._src_path = None
        self._photo_key = None   # (图片路径, 渲染宽度) —— 变了才重建 PhotoImage

        self._build_ui()
        self._build_menu()
        # 位置：优先恢复上次拖到的位置，没有（或无效）才放到右下角
        if not self._restore_pos():
            self._position_bottom_right()

        # 拖动 / 边框缩放
        self._drag = None
        self._drag_origin = None
        self._resize = None
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)
        self.root.bind("<Motion>", self._on_motion)
        self.root.bind("<Leave>", self._on_leave)
        self.root.bind("<Escape>", lambda e: self._close())
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self._refresh()
        self.root.after(REFRESH_MS, self._auto_refresh)

    def _px(self, size):
        """把基准字号换算成当前缩放下的像素字号。"""
        return max(7, int(size * self.size_scale))

    def _font(self, size, bold=False):
        weight = "bold" if bold else "normal"
        return ("Microsoft YaHei UI", self._px(size), weight)

    def _build_ui(self):
        # 可见边框：常态是暗色描边，鼠标移到边缘准备缩放时高亮成 ACCENT
        self.border = tk.Frame(self.root, bg=BORDER, bd=0)
        self.border.pack(fill="both", expand=True)

        outer = tk.Frame(self.border, bg=BG, bd=0)
        outer.pack(fill="both", expand=True, padx=BORDER_W, pady=BORDER_W)

        self._font_widgets = []

        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 0))
        self._mk_label(head, "🐋 鲸鱼娘 · 余额", 11, True, bg=BG, fg=FG).pack(side="left")
        close = self._mk_label(head, "✕", 12, False, bg=BG, fg=DIM)
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self._close())
        self.close_btn = close

        panel = tk.Frame(outer, bg=PANEL)
        panel.pack(fill="x", padx=12, pady=8)

        self.lbl_price = self._row(panel, "Token价格", "…", 0)
        self.lbl_today = self._row(panel, "今日消费", "…", 1)
        self.lbl_bal = self._row(panel, "剩余额度", "…", 2)
        self.lbl_turn = self._row(panel, "本轮消耗", "…", 3)
        self.lbl_lastturn = self._row(panel, "上一轮对话", "…", 4)

        self.status = self._mk_label(outer, "正在加载…", 8, False, bg=BG, fg=DIM)
        self.status.pack(fill="x", padx=12, pady=(0, 4))

        self.photo = None
        self.img_label = tk.Label(outer, bg=BG, bd=0, cursor="hand2")
        self.img_label.pack(side="bottom", fill="x")
        self.img_label.bind("<Button-1>", self._manual_refresh)
        self._load_image()

    def _mk_label(self, parent, text, size, bold=False, **kw):
        """建一个会随缩放改变字号的 Label，并登记到 _font_widgets。"""
        lbl = tk.Label(parent, text=text, font=self._font(size, bold), **kw)
        # 第四项是「当前已应用的像素字号」，用来判断是否真的需要重设
        self._font_widgets.append([lbl, size, bold, self._px(size)])
        return lbl

    def _rescale_fonts(self):
        """只对字号真的变了的控件调 configure。

        Tk 每次改字体都会让整棵控件树重排，逐帧无脑重设会把拖动边框拖成幻灯片；
        而字号只取整数像素，缩放过程中大部分帧其实没有任何一个控件需要改。
        """
        changed = False
        for entry in self._font_widgets:
            widget, size, bold = entry[0], entry[1], entry[2]
            px = self._px(size)
            if px == entry[3]:
                continue
            entry[3] = px
            try:
                widget.configure(font=("Microsoft YaHei UI", px, "bold" if bold else "normal"))
                changed = True
            except Exception:
                pass
        return changed

    def _build_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        size_menu = tk.Menu(menu, tearoff=0)
        for label, scale in SIZE_PRESETS.items():
            size_menu.add_command(label=label, command=lambda s=scale: self._set_size(s))
        menu.add_cascade(label="大小", menu=size_menu)
        menu.add_command(label="更换图片", command=self._change_image)
        menu.add_command(label="恢复默认图片", command=self._reset_image)
        menu.add_command(label="设置 API Key", command=self._set_api_key)
        menu.add_command(label="立即刷新", command=self._manual_refresh)
        menu.add_command(label="回到右下角", command=self._position_bottom_right)
        menu.add_separator()
        menu.add_command(label="关闭", command=self._close)
        self.menu = menu
        self.root.bind("<Button-3>", self._popup_menu)

    def _popup_menu(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _row(self, parent, label, value, idx):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=12, pady=6)
        self._mk_label(row, label, 9, False, bg=PANEL, fg=DIM).pack(side="left")
        val = self._mk_label(row, value, 10, True, bg=PANEL, fg=FG)
        val.pack(side="right")
        return val

    def _open_source(self, path):
        """读入一张图并缓存，失败返回 None。

        太大的先降采样：渲染宽度最大只有 BASE_IMG_W * MAX_SCALE，
        把手机照片那种几千万像素的原图整张留着没有意义 —— 拖动边框时
        每帧都要从全分辨率重采样，实测 4000x3000 每帧 130ms、
        6000x4500 每帧 254ms 并常驻 100MB。
        """
        try:
            from PIL import Image
            img = Image.open(path).convert("RGBA")
        except Exception:
            return None
        cap = int(BASE_IMG_W * MAX_SCALE * 2)
        if img.width > cap:
            img = img.resize((cap, max(1, int(round(img.height * cap / float(img.width))))),
                             Image.LANCZOS)
        return img

    def _load_image(self):
        """把当前 image_path 渲染到界面上，返回是否成功。

        读不到时自动退回自带素材：配置里可能留着一个失效路径
        （上次选了非图片文件，或那个文件被删了/移走了），
        不兜底的话挂件会一直显示「图片加载失败」。
        """
        try:
            from PIL import Image, ImageTk
        except Exception:
            self.photo = None
            self._photo_key = None
            self.img_label.configure(image="", text="(缺少 Pillow)", fg=DIM)
            return False

        if self._src_img is None or self._src_path != self.image_path:
            img = self._open_source(self.image_path)
            if img is None and self.image_path != WHALE_IMG:
                # 配置里的图用不了 → 退回自带鲸鱼，并顺手把坏路径从内存配置里去掉
                self.image_path = WHALE_IMG
                self.config.pop("image", None)
                img = self._open_source(WHALE_IMG)
            if img is None:
                self.photo = None
                self._photo_key = None
                self._src_img = None
                self._src_path = None
                self.img_label.configure(image="", text="(图片加载失败)", fg=DIM)
                return False
            self._src_img = img
            self._src_path = self.image_path
            self._photo_key = None

        img = self._src_img
        w = max(24, int(BASE_IMG_W * self.size_scale))
        # 缓存的 key 必须同时包含「哪张图」和「渲染宽度」：
        # 只比宽度的话，换图后宽度没变会直接 return，画面根本不会更新
        # （「更换图片」「恢复默认图片」都会失效）。
        key = (self.image_path, w)
        if self.photo is not None and self._photo_key == key:
            return True  # 同一张图、同一个尺寸，不必重建 PhotoImage
        try:
            h = max(24, int(img.height * w / img.width))
            self.photo = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))
            self._photo_key = key
            self.img_label.configure(image=self.photo, text="")
            return True
        except Exception:
            self.photo = None
            self._photo_key = None
            self.img_label.configure(image="", text="(图片加载失败)", fg=DIM)
            return False

    def _apply_scale(self, scale):
        """按比例缩放整个挂件（图片 + 字号）。

        以前是销毁重建整棵控件树，拖动边框时既慢又会闪；
        现在只改字号和图片，控件树保持不变。
        """
        scale = max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        if abs(scale - self.size_scale) < 1e-4:
            return False
        self.size_scale = scale
        self._rescale_fonts()
        self._load_image()
        # 立刻重算几何，保证调用方随后读到的 winfo_width/height 是新的
        self.root.update_idletasks()
        return True

    def _save_config_or_warn(self):
        """写配置；失败时明确提示，不要像以前那样无声无息。"""
        if not save_config(self.config):
            self._set_status("配置保存失败，下次打开可能不生效")

    def _set_size(self, scale):
        self._apply_scale(scale)
        self.config["size"] = round(self.size_scale, 4)
        self._save_config_or_warn()

    def _use_image(self, path, keep_key=None):
        """把挂件图片换成 path。

        先确认真能读出来再改 —— 否则选了非图片文件会把坏路径存进配置，
        下次启动就只剩「图片加载失败」。读图只做一次，结果直接塞进缓存。
        """
        img = self._open_source(path)
        if img is None:
            self._set_status("这个文件不是能用的图片，已保持原图")
            return False
        self.image_path = path
        self._src_img = img          # 直接复用刚读到的，不再重复解码
        self._src_path = path
        self._photo_key = None
        if keep_key is None:
            self.config["image"] = path
        else:
            self.config.pop(keep_key, None)
        self._save_config_or_warn()
        self._load_image()
        return True

    def _change_image(self):
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.bmp"), ("所有文件", "*.*")])
        if path:
            self._use_image(path)

    def _reset_image(self):
        self._use_image(WHALE_IMG, keep_key="image")

    def _ask_api_key(self):
        """自建输入对话框：输入掩码显示，且不预填现有 Key（避免明文暴露）。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("设置 API Key")
        dlg.configure(bg=BG)
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        holder = {"value": None}

        tk.Label(dlg, text="请输入 DeepSeek API Key（sk-...）", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 9)).pack(padx=16, pady=(12, 2))
        tk.Label(dlg, text="留空确定 = 清除，改用 DSH 凭据", bg=BG, fg=DIM,
                 font=("Microsoft YaHei UI", 8)).pack(padx=16)
        entry = tk.Entry(dlg, width=44, show="*", font=("Consolas", 10))
        entry.pack(padx=16, pady=8)
        entry.focus_set()

        def ok(_=None):
            holder["value"] = entry.get()
            dlg.destroy()

        def cancel(_=None):
            holder["value"] = None
            dlg.destroy()

        btns = tk.Frame(dlg, bg=BG)
        btns.pack(pady=(0, 12))
        tk.Button(btns, text="确定", width=8, command=ok).pack(side="left", padx=6)
        tk.Button(btns, text="取消", width=8, command=cancel).pack(side="left", padx=6)
        entry.bind("<Return>", ok)
        dlg.bind("<Escape>", cancel)

        dlg.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dlg.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry("+%d+%d" % (max(0, x), max(0, y)))
        dlg.grab_set()
        self.root.wait_window(dlg)
        return holder["value"]

    def _set_api_key(self):
        key = self._ask_api_key()
        if key is None:
            return  # 取消
        key = key.strip()
        if key:
            self.config["api_key"] = key
            save_config(self.config)
        else:
            # 清空则回退到 DSH 凭据
            self.config.pop("api_key", None)
            save_config(self.config)
        self.api_key = read_api_key()
        # 账户可能已切换：重新定位账本，并重置本轮基准
        self.ledger_file = ledger_path_for(self.api_key, manual=bool(self.config.get("api_key")))
        self.session_start = None
        self.session_usage = 0.0
        self._refresh()

    def _position_bottom_right(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        self._move_to((sw - w - 24, sh - h - 24))

    def _move_to(self, pos):
        try:
            self.root.geometry("+%d+%d" % (int(pos[0]), int(pos[1])))
        except Exception:
            pass

    def _current_pos(self):
        return [self.root.winfo_x(), self.root.winfo_y()]

    def _restore_pos(self):
        """恢复上次的窗口位置；没有或明显损坏时返回 False（交给右下角兜底）。"""
        pos = self.config.get("pos")
        if not (isinstance(pos, (list, tuple)) and len(pos) == 2):
            return False
        try:
            x, y = int(pos[0]), int(pos[1])
        except Exception:
            return False
        # 允许副屏的负坐标，只挡掉明显损坏的值
        if not (-20000 < x < 20000 and -20000 < y < 20000):
            return False
        self._move_to((x, y))
        return True

    def _save_pos(self):
        self.config["pos"] = self._current_pos()
        return save_config(self.config)

    def _close(self):
        self._save_pos()
        self.root.destroy()

    # ---------------- 拖动移动 / 拖边框缩放 ----------------
    def _local_xy(self, e):
        """把屏幕坐标换算成相对挂件左上角的坐标。

        事件可能是被子控件收到的（Tk 会把事件继续传给 toplevel），
        那种情况下 e.x / e.y 是相对子控件的，不能用来判断边框位置。
        """
        return (e.x_root - self.root.winfo_rootx(), e.y_root - self.root.winfo_rooty())

    def _zone_at(self, x, y):
        """判断 (x, y) 落在哪条边/角上；不在边缘则返回 None。"""
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w <= 2 * RESIZE_MARGIN or h <= 2 * RESIZE_MARGIN:
            return None
        left, right = x < RESIZE_MARGIN, x > w - RESIZE_MARGIN
        top, bottom = y < RESIZE_MARGIN, y > h - RESIZE_MARGIN
        if top and left:
            return "nw"
        if top and right:
            return "ne"
        if bottom and left:
            return "sw"
        if bottom and right:
            return "se"
        if top:
            return "n"
        if bottom:
            return "s"
        if left:
            return "w"
        if right:
            return "e"
        return None

    def _hover(self, zone):
        """鼠标压在边框上时换指针并点亮边框，给用户一个「这里能拖」的提示。"""
        cur = ZONE_CURSORS.get(zone) if zone else ""
        try:
            self.root.configure(cursor=cur)
            # 图片控件自己设了 hand2，会盖住窗口指针，缩放时要一起改
            self.img_label.configure(cursor=cur or "hand2")
            self.border.configure(bg=ACCENT if zone else BORDER)
        except Exception:
            pass

    def _on_motion(self, e):
        """没有按键时的移动：只负责悬停反馈。"""
        if self._resize or self._drag:
            return
        x, y = self._local_xy(e)
        self._hover(self._zone_at(x, y))

    def _on_leave(self, e):
        """鼠标直接从边框滑出挂件时，<Motion> 就不会再触发了，必须在这里复位。

        否则边框会一直亮着、指针也一直停在缩放箭头上，看起来像卡住了。
        """
        if self._resize or self._drag:
            return  # 拖动过程中指针短暂移出窗口是正常的，别把高亮清掉
        self._hover(None)

    def _start_drag(self, e):
        x, y = self._local_xy(e)
        zone = self._zone_at(x, y)
        if zone:
            # 抓在边框上 → 缩放，而不是移动整个挂件
            self._resize = {
                "zone": zone,
                "scale": self.size_scale,
                "pos": self._current_pos(),
                "size": (self.root.winfo_width(), self.root.winfo_height()),
                "origin": (e.x_root, e.y_root),
                "t": None,
                "last": (e.x_root, e.y_root),
            }
            self._drag = None
            # 再点亮一次：不管鼠标是怎么来到边框上的，一开始拖就必须有反馈
            self._hover(zone)
            return
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())
        self._drag_origin = self._current_pos()

    def _do_drag(self, e):
        if self._resize:
            self._do_resize(e.x_root, e.y_root)
            return
        if self._drag:
            self.root.geometry("+%d+%d" % (e.x_root - self._drag[0], e.y_root - self._drag[1]))

    def _do_resize(self, x_root, y_root, force=False):
        """等比缩放：拖哪条边就以对边为锚点，锚点位置保持不动。"""
        r = self._resize
        if not r:
            return
        r["last"] = (x_root, y_root)
        now = time.monotonic()
        if not force and r["t"] is not None and (now - r["t"]) * 1000 < RESIZE_INTERVAL_MS:
            return  # 节流：这一帧丢掉，松手时还会用最后的位置补一次
        r["t"] = now

        dx = x_root - r["origin"][0]
        dy = y_root - r["origin"][1]
        zone = r["zone"]
        west = zone in ("w", "nw", "sw")
        east = zone in ("e", "ne", "se")
        north = zone in ("n", "ne", "nw")
        south = zone in ("s", "se", "sw")
        sw, sh = r["size"]
        if sw <= 0 or sh <= 0:
            return

        if east:
            target_w = sw + dx
        elif west:
            target_w = sw - dx
        else:
            # 只拖上下边时按高度换算成宽度，保持等比
            target_h = (sh + dy) if south else (sh - dy)
            target_w = sw * (target_h / float(sh))

        if not self._apply_scale(r["scale"] * (target_w / float(sw))):
            return

        # _apply_scale 里已经 update_idletasks 过，这里直接读新尺寸，
        # 把锚点挪回去让对边钉在原地（不必再排一次版）
        nw = self.root.winfo_width()
        nh = self.root.winfo_height()
        x, y = r["pos"]
        if west:
            x = r["pos"][0] + sw - nw
        if north:
            y = r["pos"][1] + sh - nh
        self._move_to((x, y))

    def _end_drag(self, e=None):
        """松手才写配置，且没变就不写（避免每次点击都落盘）。"""
        if self._resize:
            start_scale = self._resize["scale"]
            last = self._resize.get("last")
            if last:
                # 补一次最终位置，把被节流丢掉的那一小段补上
                self._do_resize(last[0], last[1], force=True)
            changed = abs(self.size_scale - start_scale) > 1e-4
            self._resize = None
            self._hover(None)
            if changed:
                self.config["size"] = round(self.size_scale, 4)
                self._save_config_or_warn()
            return  # 只是在边框上点了一下、尺寸没变，就不必写盘
        if self._drag is None:
            return
        self._drag = None
        if self._current_pos() != self._drag_origin:
            self._save_pos()

    def _manual_refresh(self, e=None):
        if e is not None:
            x, y = self._local_xy(e)
            if self._zone_at(x, y):
                return  # 点在边框上是在缩放，不是要刷新
        self._refresh()

    def _auto_refresh(self):
        self._report_ui_error()
        self._refresh()
        self.root.after(REFRESH_MS, self._auto_refresh)

    def _report_ui_error(self):
        """把后台线程交不回主线程的失败显示出来（以前是静默吞掉）。"""
        if self._ui_error:
            msg, self._ui_error = self._ui_error, None
            self._set_status("界面更新失败: %s" % msg[:60])

    def _show_placeholder(self):
        """没有 API Key 时：价格是本地按时间算的，仍显示；余额类显示 --。"""
        peak, price = current_price()
        self.lbl_price.configure(text="%s ¥%.2f/M" % ("峰价" if peak else "谷价", price), fg=GOLD)
        for lbl in (self.lbl_today, self.lbl_bal, self.lbl_turn, self.lbl_lastturn):
            lbl.configure(text="--", fg=DIM)

    def _refresh(self):
        if self._fetching:
            return
        if not self.api_key:
            self._show_placeholder()
            self._set_status("未找到 API Key（右键可设置）")
            return
        self._fetching = True
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _safe_after(self, fn, *args):
        """把回调交给主线程。失败时记录下来由主线程报告——
        不能像以前那样 except: pass，否则界面会永远不更新且毫无提示。"""
        try:
            self.root.after(0, fn, *args)
            return True
        except Exception as e:
            self._ui_error = "%s: %s" % (type(e).__name__, e)
            return False

    def _fetch_worker(self):
        try:
            try:
                bal, cur = fetch_balance(self.api_key)
                led = record_ledger(bal, cur, self.ledger_file)
                self._ledger_saved = led.get("_saved", True)
                if self.session_start is None:
                    self.session_start = bal
                self.session_usage = max(0.0, self.session_start - bal)
                self.last_turn = read_last_turn_cost()
                self._safe_after(self._apply_data, bal, cur,
                                 led.get("todayUsage") or 0, self.last_turn)
            except Exception as e:
                self._safe_after(self._apply_error, str(e))
        finally:
            self._fetching = False

    def _apply_data(self, bal, cur, today, last_turn=None):
        self.balance = bal
        self.currency = cur
        self.today_usage = today
        self.last_turn = last_turn
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
        warn = "" if self._ledger_saved else " · 账本写入失败"
        self._set_status("已更新 %s · %s%s" % (t, self.currency, warn))

    def _apply_error(self, msg):
        self.error = msg
        # 价格是本地按时间算的，与 API 无关，失败时照样显示
        peak, price = current_price()
        self.lbl_price.configure(text="%s ¥%.2f/M" % ("峰价" if peak else "谷价", price), fg=DIM)
        # 保留上一次成功拿到的数字，只调暗表示「已过期」——
        # 一次网络抖动不该把已经显示出来的余额和消费清成 --。
        for lbl in (self.lbl_today, self.lbl_bal, self.lbl_turn, self.lbl_lastturn):
            lbl.configure(fg=DIM)
        self._set_status("拉取失败: %s" % msg[:60])

    def _set_status(self, text):
        self.status.configure(text=text)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    WhaleWidget().run()
