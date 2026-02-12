# -*- coding: utf-8 -*-
import ctypes
import json
import os
import re
import threading
from dataclasses import dataclass

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ctypes import wintypes
from pynput import keyboard


@dataclass
class KeyItem:
    key: str
    interval: float


@dataclass
class RowState:
    enabled: tk.BooleanVar
    key_var: tk.StringVar
    interval_var: tk.DoubleVar


SPECIAL_ALIASES = {
    "escape": "esc",
    "return": "enter",
    "pgup": "page_up",
    "pgdn": "page_down",
    "del": "delete",
}


user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
PM_NOREMOVE = 0x0000
PM_REMOVE = 0x0001
WM_QUIT = 0x0012

VK_CODES = {
    "esc": 0x1B,
    "enter": 0x0D,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "page_up": 0x21,
    "page_down": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}
for i in range(1, 13):
    VK_CODES[f"f{i}"] = 0x6F + i


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


user32.RegisterHotKey.argtypes = [wintypes.HWND, wintypes.INT, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, wintypes.INT]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]
user32.PeekMessageW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    vk: int


def parse_hotkey(text: str) -> Hotkey | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    tokens = re.split(r"[+ ]+", cleaned)
    modifiers = 0
    key_token = None
    for token in tokens:
        if not token:
            continue
        key = token.strip().lower()
        if key in ("ctrl", "control", "ctl"):
            modifiers |= MOD_CONTROL
            continue
        if key in ("alt", "option"):
            modifiers |= MOD_ALT
            continue
        if key == "shift":
            modifiers |= MOD_SHIFT
            continue
        if key in ("win", "cmd", "meta", "super", "windows"):
            modifiers |= MOD_WIN
            continue
        if key_token is not None:
            raise ValueError("热键只能包含一个主键。")
        key_token = key

    if not key_token:
        raise ValueError("热键缺少主键。")

    key_token = SPECIAL_ALIASES.get(key_token, key_token)
    if len(key_token) == 1 and key_token.isalnum():
        vk = ord(key_token.upper())
    else:
        vk = VK_CODES.get(key_token)
    if not vk:
        raise ValueError(f"不支持的热键：{key_token}")
    return Hotkey(modifiers, vk)


class HotkeyManager:
    def __init__(self, root: tk.Tk, on_start, on_stop):
        self.root = root
        self.on_start = on_start
        self.on_stop = on_stop
        self.thread = None
        self.thread_id = None
        self.stop_event = threading.Event()
        self.start_id = 1
        self.stop_id = 2
        self.start_hotkey = None
        self.stop_hotkey = None

    def register(self, start_text: str, stop_text: str) -> bool:
        self.unregister()

        start_hotkey = parse_hotkey(start_text) if start_text.strip() else None
        stop_hotkey = parse_hotkey(stop_text) if stop_text.strip() else None

        if start_hotkey and stop_hotkey and start_hotkey == stop_hotkey:
            raise ValueError("启动热键和停止热键不能相同。")

        if not start_hotkey and not stop_hotkey:
            return False

        self.start_hotkey = start_hotkey
        self.stop_hotkey = stop_hotkey
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def unregister(self):
        self.stop_event.set()
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.thread = None
        self.thread_id = None

    def _run(self):
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)

        try:
            if self.start_hotkey:
                if not user32.RegisterHotKey(
                    None,
                    self.start_id,
                    self.start_hotkey.modifiers,
                    self.start_hotkey.vk,
                ):
                    raise OSError("无法注册启动热键，可能与其他软件冲突。")
            if self.stop_hotkey:
                if not user32.RegisterHotKey(
                    None,
                    self.stop_id,
                    self.stop_hotkey.modifiers,
                    self.stop_hotkey.vk,
                ):
                    if self.start_hotkey:
                        user32.UnregisterHotKey(None, self.start_id)
                    raise OSError("无法注册停止热键，可能与其他软件冲突。")
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showwarning("热键错误", f"{exc}"))
            return

        while not self.stop_event.is_set():
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == WM_HOTKEY:
                if msg.wParam == self.start_id:
                    self.root.after(0, self.on_start)
                elif msg.wParam == self.stop_id:
                    self.root.after(0, self.on_stop)

        user32.UnregisterHotKey(None, self.start_id)
        user32.UnregisterHotKey(None, self.stop_id)


class ClickerThread(threading.Thread):
    def __init__(self, items, stop_event):
        super().__init__(daemon=True)
        self.items = items
        self.stop_event = stop_event
        self.controller = keyboard.Controller()
        self.special_map = self._build_special_map()

    @staticmethod
    def _build_special_map():
        mapping = {
            "enter": keyboard.Key.enter,
            "return": keyboard.Key.enter,
            "space": keyboard.Key.space,
            "tab": keyboard.Key.tab,
            "esc": keyboard.Key.esc,
            "escape": keyboard.Key.esc,
            "backspace": keyboard.Key.backspace,
            "delete": keyboard.Key.delete,
            "insert": keyboard.Key.insert,
            "home": keyboard.Key.home,
            "end": keyboard.Key.end,
            "page_up": keyboard.Key.page_up,
            "page_down": keyboard.Key.page_down,
            "up": keyboard.Key.up,
            "down": keyboard.Key.down,
            "left": keyboard.Key.left,
            "right": keyboard.Key.right,
        }
        for i in range(1, 13):
            mapping[f"f{i}"] = getattr(keyboard.Key, f"f{i}")
        return mapping

    def _send_key(self, key_text: str) -> None:
        raw = key_text.strip()
        if not raw:
            return
        normalized = re.sub(r"[\\s-]+", "_", raw.lower())
        if normalized in self.special_map:
            key_obj = self.special_map[normalized]
            self.controller.press(key_obj)
            self.controller.release(key_obj)
            return
        if len(raw) == 1:
            self.controller.press(raw)
            self.controller.release(raw)
            return
        # Treat multi-character input as text.
        self.controller.type(raw)

    def run(self):
        while not self.stop_event.is_set():
            for item in self.items:
                if self.stop_event.is_set():
                    break
                self._send_key(item.key)
                if self.stop_event.wait(item.interval):
                    break


class KeyBurstApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("多功能键盘连点器")
        self.root.geometry("820x560")
        self.root.minsize(780, 520)

        self.current_path = ""
        self.rows = []
        self.running = False
        self.stop_event = None
        self.worker = None
        self.hotkey_manager = HotkeyManager(self.root, self.start_clicking, self.stop_clicking)

        self.status_var = tk.StringVar(value="状态：已停止")

        self._apply_style()
        self._build_ui()
        self.register_hotkeys()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _apply_style(self):
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=2)
        style.configure("TEntry", padding=4)
        style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        items_group = ttk.Labelframe(main, text="按键配置（最多 9 项）", padding=10)
        items_group.pack(fill=tk.BOTH, expand=True)

        left_col = ttk.Frame(items_group)
        right_col = ttk.Frame(items_group)
        left_col.grid(row=0, column=0, sticky="nsew")
        right_col.grid(row=0, column=2, sticky="nsew")

        sep = ttk.Separator(items_group, orient=tk.VERTICAL)
        sep.grid(row=0, column=1, sticky="ns", padx=10)

        items_group.columnconfigure(0, weight=1)
        items_group.columnconfigure(2, weight=1)

        for i in range(9):
            row_state = self._create_row(left_col if i < 5 else right_col)
            self.rows.append(row_state)

        hotkey_group = ttk.Labelframe(main, text="热键设置", padding=10)
        hotkey_group.pack(fill=tk.X, pady=(10, 0))

        self.start_hotkey_var = tk.StringVar(value="F1")
        self.stop_hotkey_var = tk.StringVar(value="F2")

        start_row = ttk.Frame(hotkey_group)
        start_row.pack(fill=tk.X, pady=2)
        ttk.Label(start_row, text="启用连点热键").pack(side=tk.LEFT)
        self.start_hotkey_entry = ttk.Entry(start_row, textvariable=self.start_hotkey_var, width=22)
        self.start_hotkey_entry.pack(side=tk.LEFT, padx=8)

        stop_row = ttk.Frame(hotkey_group)
        stop_row.pack(fill=tk.X, pady=2)
        ttk.Label(stop_row, text="禁用连点热键").pack(side=tk.LEFT)
        self.stop_hotkey_entry = ttk.Entry(stop_row, textvariable=self.stop_hotkey_var, width=22)
        self.stop_hotkey_entry.pack(side=tk.LEFT, padx=8)

        for entry in (self.start_hotkey_entry, self.stop_hotkey_entry):
            entry.bind("<FocusOut>", lambda _event: self.register_hotkeys())
            entry.bind("<Return>", lambda _event: self.register_hotkeys())

        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(12, 0))

        ttk.Button(btn_row, text="保存配置", command=self.save_config).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="另存配置", command=self.save_config_as).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="读取配置", command=self.load_config).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="使用说明", command=self.show_help).pack(side=tk.RIGHT)

        status = ttk.Label(main, textvariable=self.status_var)
        status.pack(fill=tk.X, pady=(10, 0))

    def _create_row(self, parent: ttk.Frame) -> RowState:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=4)

        enabled_var = tk.BooleanVar(value=False)
        key_var = tk.StringVar()
        interval_var = tk.DoubleVar(value=0.01)

        ttk.Checkbutton(row, text="有效", variable=enabled_var).pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=key_var, width=8, justify="center")
        entry.pack(side=tk.LEFT, padx=(6, 8))

        ttk.Label(row, text="间隔").pack(side=tk.LEFT)
        spin = ttk.Spinbox(
            row,
            from_=0.01,
            to=60.0,
            increment=0.01,
            textvariable=interval_var,
            width=8,
            justify="center",
        )
        spin.pack(side=tk.LEFT, padx=6)
        ttk.Label(row, text="秒").pack(side=tk.LEFT)

        return RowState(enabled_var, key_var, interval_var)

    def register_hotkeys(self):
        try:
            registered = self.hotkey_manager.register(
                self.start_hotkey_var.get(), self.stop_hotkey_var.get()
            )
            if not self.running:
                if registered:
                    self.status_var.set("状态：已停止（热键已启用）")
                else:
                    self.status_var.set("状态：已停止（未启用热键）")
        except Exception as exc:
            messagebox.showwarning("热键错误", f"{exc}")

    def collect_items(self):
        items = []
        for row in self.rows:
            if row.enabled.get():
                key = row.key_var.get().strip()
                if not key:
                    continue
                interval = float(row.interval_var.get())
                items.append(KeyItem(key, interval))
        return items

    def start_clicking(self):
        if self.running:
            return
        items = self.collect_items()
        if not items:
            messagebox.showinfo("提示", "没有可用的按键配置。")
            return
        self.stop_event = threading.Event()
        self.worker = ClickerThread(items, self.stop_event)
        self.worker.start()
        self.running = True
        self.status_var.set("状态：运行中")

    def stop_clicking(self):
        if not self.running:
            return
        if self.stop_event:
            self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=1.5)
        self.running = False
        self.status_var.set("状态：已停止")

    def build_config(self):
        items = []
        for row in self.rows:
            items.append(
                {
                    "enabled": row.enabled.get(),
                    "key": row.key_var.get().strip(),
                    "interval": float(row.interval_var.get()),
                }
            )
        return {
            "start_hotkey": self.start_hotkey_var.get().strip(),
            "stop_hotkey": self.stop_hotkey_var.get().strip(),
            "items": items,
        }

    def apply_config(self, data):
        items = data.get("items", [])
        for idx, row in enumerate(self.rows):
            if idx < len(items):
                item = items[idx]
                row.enabled.set(bool(item.get("enabled", False)))
                row.key_var.set(str(item.get("key", "")))
                try:
                    row.interval_var.set(float(item.get("interval", 0.01)))
                except (TypeError, ValueError):
                    row.interval_var.set(0.01)
            else:
                row.enabled.set(False)
                row.key_var.set("")
                row.interval_var.set(0.01)

        self.start_hotkey_var.set(data.get("start_hotkey", "F1"))
        self.stop_hotkey_var.set(data.get("stop_hotkey", "F2"))
        self.register_hotkeys()

    def write_config(self, path: str):
        data = self.build_config()
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        self.status_var.set(f"状态：配置已保存（{os.path.basename(path)}）")

    def save_config(self):
        if not self.current_path:
            self.save_config_as()
            return
        self.write_config(self.current_path)

    def save_config_as(self):
        path = filedialog.asksaveasfilename(
            title="另存配置",
            defaultextension=".json",
            filetypes=[("JSON 配置", "*.json")],
        )
        if not path:
            return
        self.current_path = path
        self.write_config(path)

    def load_config(self):
        path = filedialog.askopenfilename(
            title="读取配置",
            filetypes=[("JSON 配置", "*.json")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.apply_config(data)
            self.current_path = path
            self.status_var.set(f"状态：配置已读取（{os.path.basename(path)}）")
        except Exception as exc:
            messagebox.showwarning("读取失败", f"无法读取配置：{exc}")

    def show_help(self):
        messagebox.showinfo(
            "使用说明",
            "1. 勾选“有效”，填写按键（如 A、1、F1、Space）。\n"
            "2. 设置间隔（单位：秒），越小连点越快。\n"
            "3. 热键格式示例：F1、Ctrl+Alt+S、Shift+F2。\n"
            "4. 启动热键会循环发送已启用按键；停止热键立即终止。",
        )

    def on_close(self):
        self.stop_clicking()
        self.hotkey_manager.unregister()
        self.root.destroy()


def main():
    root = tk.Tk()
    KeyBurstApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
