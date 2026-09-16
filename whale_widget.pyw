# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring>=25", "Pillow>=10"]
# ///
"""DeepSeek balance widget."""

import datetime
import hashlib
import json
import math
import os
import queue
import threading
import urllib.request
from pathlib import Path

import keyring

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "whale-widget-standalone"
)
SETTINGS_FILE = DATA_DIR / "settings.json"
LEDGER_FILE = DATA_DIR / "usage.json"
LEGACY_CONFIG = APP_DIR / "config.json"
WHALE_IMG = APP_DIR / "assets" / "DSniang1.png"
SESSION_CACHE_DIR = Path.home() / ".dsh" / "storages" / "session_projcache" / "sessions"
BALANCE_URL = "https://api.deepseek.com/user/balance"
KEYRING_SERVICE = "whale-widget-standalone"
REFRESH_MS = 60_000
PEAK_HOURS = ((9, 12), (14, 18))
PRO_PRICE = {"hit": (0.15, 0.3), "miss": (4.5, 9.0), "out": (13.5, 27.0)}
SIZE_PRESETS = {"小": 0.7, "默认": 1.0, "大": 1.4}
BASE_IMG_W = 240


class Store:
    """Keep non-secret settings and per-account balance observations."""

    def __init__(self, settings_file=SETTINGS_FILE, ledger_file=LEDGER_FILE):
        self.settings_file = Path(settings_file)
        self.ledger_file = Path(ledger_file)

    def read(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def settings(self):
        return self.read(self.settings_file)

    def save_settings(self, data):
        self.write(self.settings_file, data)

    def ledger(self):
        return self.read(self.ledger_file)

    def save_ledger(self, data):
        self.write(self.ledger_file, data)


class Account:
    """One credential and its current displayed state."""

    def __init__(self, account_id):
        self.id = account_id
        self.name = f"deepseek-api-key-{account_id}"
        self.balance = None
        self.currency = "CNY"
        self.today_usage = 0.0
        self.session_start = None
        self.session_recharges = 0.0
        self.session_last = None
        self.session_usage = 0.0
        self.last_turn = None


class SessionTracker:
    """Track DSH session updates observed while an account is selected."""

    def __init__(self, cache_dir=SESSION_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.last_seen = None
        self.last_cost = None

    def mark_existing(self):
        latest = self.latest_file()
        self.last_seen = latest[1] if latest else None

    def latest_file(self):
        try:
            return max(
                (
                    (path, path.stat().st_mtime_ns)
                    for path in self.cache_dir.glob("*.json")
                ),
                key=lambda item: item[1],
                default=None,
            )
        except OSError:
            return None

    def refresh(self, price_index):
        latest = self.latest_file()
        if latest is None or latest[1] == self.last_seen:
            return self.last_cost
        self.last_seen = latest[1]
        try:
            data = json.loads(latest[0].read_text(encoding="utf-8"))
            buckets = data["record"]["rows"]["tokenUsage"]["val"]["last"]["buckets"]
            miss = int(buckets.get("uncachedInputTokens") or 0)
            hit = int(buckets.get("cacheReadTokens") or 0)
            out = int(buckets.get("outputTokens") or 0)
            if not any((miss, hit, out)):
                return self.last_cost
            self.last_cost = (
                miss * PRO_PRICE["miss"][price_index]
                + hit * PRO_PRICE["hit"][price_index]
                + out * PRO_PRICE["out"][price_index]
            ) / 1_000_000
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return self.last_cost


class WidgetManager:
    """Manage credentials, balances, settings, and account histories."""

    def __init__(
        self,
        store=None,
        credentials=None,
        session_dir=SESSION_CACHE_DIR,
        legacy_config=LEGACY_CONFIG,
    ):
        self.store = store or Store()
        self.credentials = credentials or keyring
        self.session_dir = Path(session_dir)
        self.legacy_config = Path(legacy_config)
        self.settings = self.store.settings()
        ids = self.settings.get("accounts", [])
        self.accounts = {item: Account(item) for item in ids if isinstance(item, str)}
        self.sessions = {
            item: SessionTracker(self.session_dir) for item in self.accounts
        }
        self.active_id = self.settings.get("active_key")
        if self.active_id not in self.accounts:
            self.active_id = next(iter(self.accounts), None)
        self.migrate_legacy_config()
        if self.active_id:
            self.sessions[self.active_id].mark_existing()

    @property
    def active(self):
        return self.accounts.get(self.active_id)

    def save_settings(self):
        self.settings["accounts"] = list(self.accounts)
        self.settings["active_key"] = self.active_id
        self.store.save_settings(self.settings)

    def migrate_legacy_config(self):
        if not self.legacy_config.exists():
            return
        old = self.store.read(self.legacy_config)
        key = old.pop("api_key", None)
        if key:
            self.add_key(key)
            self.store.write(self.legacy_config, old)
        for field in ("size", "image"):
            if field in old and field not in self.settings:
                self.settings[field] = old[field]
        if old:
            self.save_settings()

    def add_key(self, key):
        key = key.strip()
        if not key:
            raise ValueError("API Key 不能为空")
        account_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
        if account_id in self.accounts:
            existing = self.credentials.get_password(KEYRING_SERVICE, account_id)
            if existing != key:
                raise ValueError("Key 摘要冲突，请联系维护者")
        self.credentials.set_password(KEYRING_SERVICE, account_id, key)
        if account_id not in self.accounts:
            self.accounts[account_id] = Account(account_id)
            self.sessions[account_id] = SessionTracker(self.session_dir)
        self.active_id = account_id
        self.sessions[account_id].mark_existing()
        self.save_settings()
        return self.accounts[account_id]

    def switch_key(self, account_id):
        if account_id not in self.accounts:
            raise KeyError(account_id)
        self.active_id = account_id
        self.sessions[account_id].mark_existing()
        self.save_settings()

    def remove_key(self, account_id):
        if account_id not in self.accounts:
            return
        self.credentials.delete_password(KEYRING_SERVICE, account_id)
        del self.accounts[account_id]
        del self.sessions[account_id]
        ledger = self.store.ledger()
        ledger.pop(account_id, None)
        self.store.save_ledger(ledger)
        if self.active_id == account_id:
            self.active_id = next(iter(self.accounts), None)
        self.save_settings()

    def credential(self, account_id):
        return self.credentials.get_password(KEYRING_SERVICE, account_id)

    def record_balance(self, account_id, balance, currency, date=None):
        if not math.isfinite(balance) or balance < 0:
            raise ValueError("余额接口返回了无效金额")
        account = self.accounts[account_id]
        day = date or beijing_now().strftime("%Y-%m-%d")
        ledger = self.store.ledger()
        records = ledger.setdefault(account_id, {})
        state = records.get(day)
        if not isinstance(state, dict) or state.get("currency") != currency:
            state = {
                "currency": currency,
                "first": balance,
                "last": balance,
                "recharges": 0.0,
            }
        else:
            previous = float(state["last"])
            if balance > previous:
                state["recharges"] = (
                    float(state.get("recharges", 0)) + balance - previous
                )
            state["last"] = balance
        records[day] = state
        for old_day in sorted(records)[:-30]:
            records.pop(old_day, None)
        self.store.save_ledger(ledger)
        if account.session_start is not None and account.currency != currency:
            account.session_start = None
            account.session_last = None
            account.session_recharges = 0.0
        account.balance = balance
        account.currency = currency
        account.today_usage = max(
            0.0, float(state["first"]) - balance + float(state["recharges"])
        )
        if account.session_start is None:
            account.session_start = balance
        elif account.session_last is not None and balance > account.session_last:
            account.session_recharges += balance - account.session_last
        account.session_last = balance
        account.session_usage = max(
            0.0, account.session_start - balance + account.session_recharges
        )
        account.last_turn = self.sessions[account_id].refresh(1 if is_peak() else 0)
        return account

    def total_usage(self, currency, date=None):
        day = date or beijing_now().strftime("%Y-%m-%d")
        total = 0.0
        for records in self.store.ledger().values():
            state = records.get(day) if isinstance(records, dict) else None
            if isinstance(state, dict) and state.get("currency") == currency:
                total += max(
                    0.0,
                    float(state["first"])
                    - float(state["last"])
                    + float(state.get("recharges", 0)),
                )
        return total


def beijing_now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def is_peak(moment=None):
    moment = moment or beijing_now()
    return moment.weekday() < 5 and any(
        start <= moment.hour < end for start, end in PEAK_HOURS
    )


def fetch_balance(key):
    request = urllib.request.Request(
        BALANCE_URL, headers={"Authorization": "Bearer " + key}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    infos = payload.get("balance_infos") or []
    info = next((item for item in infos if item.get("currency") == "CNY"), None)
    if info is None:
        info = next(iter(infos), None)
    if info is None:
        raise ValueError("余额接口没有返回余额信息")
    return float(info["total_balance"]), info.get("currency") or "CNY"


BG = "#12151f"
PANEL = "#1a1f2e"
FG = "#e8ecf5"
DIM = "#8a93a8"
ACCENT = "#7fd0ff"
GREEN = "#5ad0a0"
GOLD = "#f0c060"


class WhaleWidget:
    """Existing widget view and its user interactions."""

    def __init__(self):
        import tkinter as tk

        self.tk = tk
        self.manager = WidgetManager()
        self.results = queue.Queue()
        self.in_flight = {}
        self.request_number = 0
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.size_scale = self._size()
        self.image_path = Path(self.manager.settings.get("image", WHALE_IMG))
        self._build_ui()
        self._build_menu()
        self._position_bottom_right()
        self._drag = None
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<Escape>", lambda event: self.root.destroy())
        self.root.after(100, self._consume_results)
        self._refresh(force=True)
        self.root.after(REFRESH_MS, self._auto_refresh)

    def _size(self):
        try:
            scale = float(self.manager.settings.get("size", 1.0))
            return scale if 0.5 <= scale <= 2 else 1.0
        except (TypeError, ValueError):
            return 1.0

    def _font(self, size, bold=False):
        return (
            "Microsoft YaHei UI",
            max(7, int(size * self.size_scale)),
            "bold" if bold else "normal",
        )

    def _build_ui(self):
        tk = self.tk
        outer = tk.Frame(self.root, bg=BG, bd=0)
        outer.pack(fill="both", expand=True)
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(
            head, text="🐋 鲸鱼娘 · 余额", bg=BG, fg=FG, font=self._font(11, True)
        ).pack(side="left")
        close = tk.Label(head, text="✕", bg=BG, fg=DIM, font=self._font(12))
        close.pack(side="right")
        close.bind("<Button-1>", lambda event: self.root.destroy())
        panel = tk.Frame(outer, bg=PANEL)
        panel.pack(fill="x", padx=12, pady=8)
        self.lbl_price = self._row(panel, "Token价格", "…")
        self.lbl_today = self._row(panel, "今日消费", "…")
        self.lbl_bal = self._row(panel, "剩余额度", "…")
        self.lbl_turn = self._row(panel, "本轮消耗", "…")
        self.lbl_lastturn = self._row(panel, "上一轮对话", "…")
        self.status = tk.Label(
            outer, text="正在加载…", bg=BG, fg=DIM, font=self._font(8)
        )
        self.status.pack(fill="x", padx=12, pady=(0, 4))
        self.photo = None
        self.img_label = tk.Label(outer, bg=BG, bd=0, cursor="hand2")
        self.img_label.pack(side="bottom", fill="x")
        self.img_label.bind("<Button-1>", self._manual_refresh)
        self._load_image()

    def _row(self, parent, label, value):
        tk = self.tk
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=12, pady=6)
        tk.Label(row, text=label, bg=PANEL, fg=DIM, font=self._font(9)).pack(
            side="left"
        )
        result = tk.Label(row, text=value, bg=PANEL, fg=FG, font=self._font(10, True))
        result.pack(side="right")
        return result

    def _build_menu(self):
        tk = self.tk
        menu = tk.Menu(self.root, tearoff=0)
        size_menu = tk.Menu(menu, tearoff=0)
        for label, scale in SIZE_PRESETS.items():
            size_menu.add_command(
                label=label, command=lambda s=scale: self._set_size(s)
            )
        menu.add_cascade(label="大小", menu=size_menu)
        menu.add_command(label="更换图片", command=self._change_image)
        menu.add_command(label="恢复默认图片", command=self._reset_image)
        self.key_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="API Key", menu=self.key_menu)
        menu.add_command(label="立即刷新", command=self._manual_refresh)
        menu.add_separator()
        menu.add_command(label="关闭", command=self.root.destroy)
        self.menu = menu
        self.root.bind("<Button-3>", self._popup_menu)

    def _populate_key_menu(self):
        self.key_menu.delete(0, "end")
        self.key_menu.add_command(label="添加 API Key", command=self._add_key)
        if self.manager.accounts:
            self.key_menu.add_separator()
        for account_id, account in self.manager.accounts.items():
            marker = "✓ " if account_id == self.manager.active_id else ""
            self.key_menu.add_command(
                label=marker + account.name,
                command=lambda selected=account_id: self._switch_key(selected),
            )
        if self.manager.active:
            self.key_menu.add_separator()
            self.key_menu.add_command(
                label="删除当前 API Key", command=self._remove_key
            )

    def _popup_menu(self, event):
        self._populate_key_menu()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _load_image(self):
        try:
            from PIL import Image, ImageTk

            with Image.open(self.image_path) as source:
                image = source.convert("RGBA")
            width = int(BASE_IMG_W * self.size_scale)
            height = int(image.height * width / image.width)
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(image)
            self.img_label.configure(image=self.photo, text="")
        except (OSError, ValueError, ImportError):
            self.photo = None
            self.img_label.configure(image="", text="(图片加载失败)", fg=DIM)

    def _set_size(self, scale):
        self.size_scale = scale
        self.manager.settings["size"] = scale
        self.manager.save_settings()
        self._rebuild_ui()

    def _change_image(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.bmp"), ("所有文件", "*.*")],
        )
        if path:
            self.image_path = Path(path)
            self.manager.settings["image"] = path
            self.manager.save_settings()
            self._load_image()

    def _reset_image(self):
        self.image_path = WHALE_IMG
        self.manager.settings.pop("image", None)
        self.manager.save_settings()
        self._load_image()

    def _add_key(self):
        from tkinter import messagebox, simpledialog

        key = simpledialog.askstring(
            "添加 API Key", "请输入 DeepSeek API Key：", parent=self.root, show="*"
        )
        if key is None:
            return
        try:
            self.manager.add_key(key)
        except (ValueError, OSError, RuntimeError) as error:
            messagebox.showerror("保存失败", str(error), parent=self.root)
            return
        self._clear_display()
        self._refresh(force=True)

    def _switch_key(self, account_id):
        from tkinter import messagebox

        try:
            self.manager.switch_key(account_id)
        except (OSError, RuntimeError) as error:
            messagebox.showerror("切换失败", str(error), parent=self.root)
            return
        self._clear_display()
        self._refresh(force=True)

    def _remove_key(self):
        from tkinter import messagebox

        account = self.manager.active
        if not account or not messagebox.askyesno(
            "删除 API Key", f"删除 {account.name} 及其消费记录？", parent=self.root
        ):
            return
        try:
            self.manager.remove_key(account.id)
        except (OSError, RuntimeError) as error:
            messagebox.showerror("删除失败", str(error), parent=self.root)
            return
        self._clear_display()
        self._refresh(force=True)

    def _clear_display(self):
        for label in (
            self.lbl_price,
            self.lbl_today,
            self.lbl_bal,
            self.lbl_turn,
            self.lbl_lastturn,
        ):
            label.configure(text="…")

    def _rebuild_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        self._build_ui()
        self._position_bottom_right()
        if self.manager.active and self.manager.active.balance is not None:
            self._apply_data(self.manager.active)

    def _position_bottom_right(self):
        self.root.update_idletasks()
        x = self.root.winfo_screenwidth() - self.root.winfo_width() - 24
        y = self.root.winfo_screenheight() - self.root.winfo_height() - 24
        self.root.geometry(f"+{x}+{y}")

    def _start_drag(self, event):
        self._drag = (
            event.x_root - self.root.winfo_x(),
            event.y_root - self.root.winfo_y(),
        )

    def _do_drag(self, event):
        if self._drag:
            self.root.geometry(
                f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}"
            )

    def _manual_refresh(self, event=None):
        self._refresh()

    def _auto_refresh(self):
        self._refresh()
        self.root.after(REFRESH_MS, self._auto_refresh)

    def _refresh(self, force=False):
        account = self.manager.active
        if account is None:
            self.status.configure(text="请右键添加 DeepSeek API Key")
            return
        if account.id in self.in_flight and not force:
            return
        self.request_number += 1
        request_number = self.request_number
        self.in_flight[account.id] = request_number
        self.status.configure(text=f"正在更新 · {account.name}")
        threading.Thread(
            target=self._fetch_worker,
            args=(account.id, request_number),
            daemon=True,
        ).start()

    def _fetch_worker(self, account_id, request_number):
        try:
            key = self.manager.credential(account_id)
            if not key:
                raise ValueError("系统凭据库中找不到此 API Key")
            balance, currency = fetch_balance(key)
            self.results.put((account_id, request_number, balance, currency, None))
        except Exception as error:  # noqa: BLE001 - relay worker failures to the UI
            self.results.put((account_id, request_number, None, None, str(error)))

    def _consume_results(self):
        while not self.results.empty():
            account_id, request_number, balance, currency, error = (
                self.results.get_nowait()
            )
            if self.in_flight.get(account_id) != request_number:
                continue
            del self.in_flight[account_id]
            if account_id not in self.manager.accounts:
                continue
            if error is None:
                try:
                    account = self.manager.record_balance(account_id, balance, currency)
                except (OSError, ValueError, KeyError) as failure:
                    error = str(failure)
            if account_id != self.manager.active_id:
                continue
            if error:
                self.status.configure(text=f"拉取失败: {error[:60]}")
            else:
                self._apply_data(account)
        self.root.after(100, self._consume_results)

    def _apply_data(self, account):
        peak = is_peak()
        price = PRO_PRICE["out"][1 if peak else 0]
        period = "峰价" if peak else "谷价"
        symbol = "¥" if account.currency == "CNY" else "$"
        total = self.manager.total_usage(account.currency)
        self.lbl_price.configure(text=f"{period} ¥{price:.2f}/M", fg=GOLD)
        self.lbl_today.configure(
            text=f"{symbol}{account.today_usage:.4f} / 总 {symbol}{total:.4f}", fg=FG
        )
        self.lbl_bal.configure(text=f"{symbol}{account.balance:.2f}", fg=GREEN)
        self.lbl_turn.configure(text=f"{symbol}{account.session_usage:.4f}", fg=ACCENT)
        last = f"¥{account.last_turn:.4f}" if account.last_turn is not None else "--"
        self.lbl_lastturn.configure(
            text=last, fg=ACCENT if account.last_turn is not None else DIM
        )
        time = beijing_now().strftime("%H:%M:%S")
        self.status.configure(
            text=f"已更新 {time} · {account.name} · {account.currency}"
        )

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    WhaleWidget().run()
