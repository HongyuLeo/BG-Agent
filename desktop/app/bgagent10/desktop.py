"""Chinese Windows desktop. Run with python -m bgagent10.desktop."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .service import DEFAULT_CONFIG, TrainingService, atomic_json, read_json

STATE_TEXT = dict(starting="正在启动", running="训练中", pausing="等待暂停", paused="已暂停",
    evaluating="独立评估中", completed="本次训练完成", failed="训练异常", stopped="已停止")
BG, PANEL, INK, MUTED, ACCENT = "#eef2f7", "#ffffff", "#15243d", "#65748b", "#1765d1"


class StrengthChart(tk.Canvas):
    def __init__(self, master):
        super().__init__(master, bg=PANEL, highlightthickness=0, height=330)
        self.records = []
        self.bind("<Configure>", lambda event: self.draw())

    def update_records(self, records):
        self.records = records
        self.draw()

    def draw(self):
        self.delete("all")
        width, height = max(500, self.winfo_width()), max(220, self.winfo_height())
        left, right, top, bottom = 65, width - 65, 35, height - 48
        self.create_text(left, 16, text="平均名次与置信区间 · 越高越强", fill=INK, anchor="w", font=("Microsoft YaHei UI", 11, "bold"))
        points = []
        by_training_games = bool(self.records) and all("completed_games" in r for r in self.records)
        for index, record in enumerate(self.records, 1):
            try:
                x, rank = float(record["completed_games"] if by_training_games else index), float(record["mean_rank"])
                if math.isfinite(x) and math.isfinite(rank) and 1 <= rank <= 8:
                    points.append((x, rank, record))
            except (KeyError, TypeError, ValueError):
                pass
        maximum = max((p[0] for p in points), default=1) or 1
        px = lambda value: left + (right-left)*value/maximum
        py = lambda rank: top + (bottom-top)*(rank-1)/7
        for rank in range(1, 9):
            y = py(rank)
            self.create_line(left, y, right, y, fill="#e6ebf2")
            self.create_text(left-15, y, text=str(rank), fill=MUTED)
        self.create_text(left, bottom+28, text="0", fill=MUTED)
        self.create_text(right, bottom+28, text=f"{maximum:g} " + ("训练完整局" if by_training_games else "评估序号"), anchor="e", fill=MUTED)
        if not points:
            self.create_text((left+right)/2, (top+bottom)/2, text="尚无真实独立评估\n训练器产生结果后将在此显示", fill=MUTED, justify="center", font=("Microsoft YaHei UI", 12))
            return
        previous = None
        for games, rank, record in points:
            x, y = px(games), py(rank)
            try:
                if record.get("legacy_ci_warning"):
                    raise ValueError("legacy normal interval is no longer displayed")
                low, high = float(record["ci_low"]), float(record["ci_high"])
                if all(math.isfinite(v) for v in (low, high)) and 1 <= low <= high <= 8:
                    self.create_line(x, py(low), x, py(high), fill="#90b9f2", width=3)
                    self.create_line(x-4, py(low), x+4, py(low), fill=ACCENT)
                    self.create_line(x-4, py(high), x+4, py(high), fill=ACCENT)
            except (KeyError, TypeError, ValueError):
                pass
            if previous:
                self.create_line(*previous, x, y, fill=ACCENT, width=2)
            self.create_oval(x-4, y-4, x+4, y+4, fill=ACCENT, outline=PANEL)
            previous = (x, y)


class Desktop:
    def __init__(self, root: tk.Tk, data_root: Path):
        self.root, self.data_root = root, data_root.resolve()
        self.service = TrainingService(self.data_root / "runs")
        self.run = None
        self.run_paths = []
        self.checkpoint_paths = []
        self.report_paths = []
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bgagent-ui")
        self.task = None
        self.close_when_safe = False
        self.live_busy = False
        self.live_preflight = None
        self.prepared_live_config = None
        self.last_live_signature = None
        self.extra_config = {}
        self.root.title("BGagent 正式版 1.0 · 实战验收版")
        self.root.geometry("1240x900")
        self.root.minsize(1000, 720)
        self.root.configure(bg=BG)
        self.style()
        header = ttk.Frame(root, padding=(24, 16))
        header.pack(fill="x")
        ttk.Label(header, text="BGagent", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  正式版 1.0  /  训练已验收 · 实战待您验收", style="Muted.TLabel").pack(side="left", padx=10)
        self.head_state = tk.StringVar(value="就绪")
        ttk.Label(header, textvariable=self.head_state, style="Accent.TLabel").pack(side="right")
        self.footer = tk.StringVar(value=f"本地数据：{self.data_root}  ·  仅显示真实训练与评估记录")
        ttk.Label(root, textvariable=self.footer, style="Muted.TLabel", padding=(24, 0, 20, 12)).pack(side="bottom", fill="x")
        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self.training_tab()
        self.checkpoint_tab()
        self.error_tab()
        self.live_tab()
        self.data_tab()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh()

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), foreground=INK, background=BG)
        style.configure("TButton", padding=(12, 8))
        style.configure("TNotebook.Tab", padding=(20, 11))
        style.configure("TEntry", fieldbackground=PANEL, padding=6)
        style.configure("TCombobox", fieldbackground=PANEL, padding=5)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Accent.TLabel", foreground=ACCENT, font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Big.TLabel", font=("Microsoft YaHei UI", 22, "bold"), background=PANEL)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("Card.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Accent.TButton", background=ACCENT, foreground="white")
        style.map("Accent.TButton", background=[("active", "#0b4da9")])
        style.configure("Treeview", rowheight=28, fieldbackground=PANEL, background=PANEL)

    def tab(self, title):
        frame = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(frame, text=title)
        return frame

    def training_tab(self):
        tab = self.tab("训练与强度")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)
        settings = ttk.Frame(tab, width=305)
        settings.grid(row=0, column=0, sticky="ns", padx=(0, 22))
        ttk.Label(settings, text="训练配置", style="Accent.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.config_vars = {}
        fields = [("workers", "独立环境进程"), ("rounds", "本次新增轮数"), ("games_per_round", "每轮完整局数"),
            ("eval_every_games", "评估间隔 / 局"), ("eval_games", "独立评估局数"),
            ("eval_opponent", "固定评估对手"), ("model_preset", "模型规格"), ("device", "训练设备"),
            ("learning_rate", "学习率"), ("ppo_epochs", "每批 PPO 轮数"), ("seed", "随机种子")]
        options = dict(eval_opponent=["scripted", "random", "mixed", "history"], model_preset=["small", "main"], device=["cpu", "cuda"])
        for row, (key, label) in enumerate(fields, 1):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            variable = tk.StringVar(value=str(DEFAULT_CONFIG[key]))
            self.config_vars[key] = variable
            if key in options:
                entry = ttk.Combobox(settings, textvariable=variable, values=options[key], state="readonly", width=14)
            else:
                entry = ttk.Entry(settings, textvariable=variable, width=16)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Label(settings, text="small：低成本验证；main：主模型\n续训保留原模型与种子\n其余设置用于本次新增训练", style="Muted.TLabel", justify="left").grid(row=12, column=0, columnspan=2, sticky="w", pady=12)
        ttk.Button(settings, text="开始新训练", command=self.start, style="Accent.TButton").grid(row=13, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Button(settings, text="导入配置…", command=self.import_config).grid(row=14, column=0, sticky="ew", pady=4)
        ttk.Button(settings, text="导出配置…", command=self.export_config).grid(row=14, column=1, sticky="ew", pady=4)
        main = ttk.Frame(tab)
        main.grid(row=0, column=1, sticky="nsew")
        bar = ttk.Frame(main)
        bar.pack(fill="x")
        ttk.Label(bar, text="训练记录").pack(side="left", padx=(0, 10))
        self.run_var = tk.StringVar()
        self.run_picker = ttk.Combobox(bar, textvariable=self.run_var, state="readonly")
        self.run_picker.pack(side="left", fill="x", expand=True)
        self.run_picker.bind("<<ComboboxSelected>>", self.select_run)
        ttk.Button(bar, text="打开文件夹", command=self.open_run).pack(side="right", padx=(8, 0))
        cards = ttk.Frame(main)
        cards.pack(fill="x", pady=16)
        self.metrics = {}
        for title, key in [("完整训练局", "games"), ("优化器更新", "updates"), ("独立平均名次", "rank"), ("前四 / 吃鸡", "rates")]:
            frame = ttk.Frame(cards, style="Card.TFrame", padding=12)
            frame.pack(side="left", fill="both", expand=True, padx=(0, 8))
            ttk.Label(frame, text=title, style="Card.TLabel").pack(anchor="w")
            value = tk.StringVar(value="—")
            ttk.Label(frame, textvariable=value, style="Big.TLabel").pack(anchor="w", pady=(6, 0))
            self.metrics[key] = value
        self.chart = StrengthChart(main)
        self.chart.pack(fill="both", expand=True)
        self.eval_info = tk.StringVar(value="独立评估：等待真实记录")
        ttk.Label(main, textvariable=self.eval_info, style="Muted.TLabel", wraplength=700).pack(anchor="w", pady=8)
        self.progress = ttk.Progressbar(main, maximum=100)
        self.progress.pack(fill="x", pady=(0, 8))
        self.status_text = tk.StringVar(value="尚未开始训练")
        ttk.Label(main, textvariable=self.status_text, wraplength=700).pack(anchor="w")
        controls = ttk.Frame(main)
        controls.pack(fill="x", pady=(14, 0))
        self.pause_button = ttk.Button(controls, text="安全暂停", command=lambda: self.control("pause"))
        self.pause_button.pack(side="left")
        self.resume_button = ttk.Button(controls, text="从检查点续训", command=self.resume)
        self.resume_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(controls, text="保存并停止", command=lambda: self.control("stop"))
        self.stop_button.pack(side="left")
        self.config_vars['continue_on_episode_error']=tk.BooleanVar(value=True)
        ttk.Checkbutton(controls,text='单局报错后继续',variable=self.config_vars['continue_on_episode_error']).pack(side='left',padx=10)

    def checkpoint_tab(self):
        tab = self.tab("模型检查点")
        ttk.Label(tab, text="显示所选训练记录保存的模型。选中后可用于实战或继续训练。", style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
        self.checkpoints = ttk.Treeview(tab, columns=("name", "size", "path"), show="headings")
        for key, text, width in [("name", "检查点", 220), ("size", "文件大小", 100), ("path", "完整路径", 650)]:
            self.checkpoints.heading(key, text=text)
            self.checkpoints.column(key, width=width)
        self.checkpoints.pack(fill="both", expand=True)
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=12)
        ttk.Button(bar, text="使用所选模型续训", command=self.resume_selected).pack(side="left")
        ttk.Button(bar, text="设为实战模型", command=self.use_live_checkpoint).pack(side="left", padx=10)

    def error_tab(self):
        tab = self.tab("异常与日志")
        ttk.Label(tab, text="异常轨迹应隔离复核；此处直接读取训练器报告和启动日志。", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.report_var = tk.StringVar()
        self.report_picker = ttk.Combobox(tab, textvariable=self.report_var, state="readonly")
        self.report_picker.pack(fill="x", pady=(0, 8))
        self.report_picker.bind("<<ComboboxSelected>>", lambda event: self.show_report())
        self.report_text = self.text_area(tab)

    def live_tab(self):
        tab = self.tab("实战控制")
        ttk.Label(tab, text="打开炉石酒馆战棋菜单 → 连接并开始实战 → 5秒内切回游戏", style="Accent.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(tab, text="训练规则 255130 · 实战客户端 255790。模型整局保持固定，出现未知状态或操作不一致即停止。", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        form = ttk.Frame(tab)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        advanced = ttk.Frame(tab)
        advanced.columnconfigure(1, weight=1)
        advanced_toggle = ttk.Button(tab, text="展开连接设置")
        advanced_toggle.pack(anchor="w", pady=(6, 0))
        def toggle_advanced():
            if advanced.winfo_manager():
                advanced.pack_forget()
                advanced_toggle.configure(text="展开连接设置")
            else:
                advanced.pack(fill="x", after=advanced_toggle)
                advanced_toggle.configure(text="收起连接设置")
        advanced_toggle.configure(command=toggle_advanced)
        self.live_vars = {}
        saved = read_json(self.data_root / "live-settings.json", {})
        self.live_extra_config = dict(saved)
        fields = [("checkpoint", "实战使用的模型", ""), ("data_root", "实战数据目录", str(self.data_root / "live-data")),
            ("session_root", "会话目录", str(self.data_root / "live-sessions" / str(time.time_ns()))), ("window_title", "游戏窗口标题", "炉石传说"),
            ("log_path", "游戏日志", ""), ("client_path", "游戏程序", ""), ("expected_build", "实战客户端版本", "37.0.0.255790"),
            ("adapter_manifest", "适配资料", str(self.data_root / "live-config" / "adapter.json")),
            ("calibration_path", "窗口校准", str(self.data_root / "live-config" / "calibration-255790.json")),
            ("release_path", "模型验证记录", str(self.data_root / "live-config" / "release.json")),
            ("deployment_contract_path", "实战兼容记录", str(self.data_root / "live-config" / "deployment.json"))]
        for index, (key, label, default) in enumerate(fields):
            variable = tk.StringVar(value=saved.get(key, default) if key != "session_root" else default)
            self.live_vars[key] = variable
            parent = form if key in {"checkpoint", "window_title", "client_path"} else advanced
            ttk.Label(parent, text=label).grid(row=index, column=0, sticky="w", padx=(0, 18), pady=3)
            ttk.Entry(parent, textvariable=variable).grid(row=index, column=1, sticky="ew", pady=3)
            if key not in {"window_title", "expected_build"}:
                ttk.Button(parent, text="选择…", command=lambda k=key: self.browse_live(k)).grid(row=index, column=2, padx=(8, 0))
        options = ttk.Frame(tab)
        options.pack(fill="x", pady=(8, 0))
        self.live_auto_queue = tk.BooleanVar(value=bool(saved.get("auto_queue", True)))
        self.live_max_games = tk.StringVar(value=str(saved.get("max_games", 10)))
        ttk.Checkbutton(options, text="结束后自动下一局", variable=self.live_auto_queue).pack(side="left")
        ttk.Label(options, text="本次最多局数").pack(side="left", padx=(16, 5))
        ttk.Spinbox(options, from_=1, to=10000, textvariable=self.live_max_games, width=6).pack(side="left")
        ttk.Button(options, text="识别本机路径", command=lambda: self.guard(self.discover_live_paths)).pack(side="right")
        ttk.Button(options, text="保存设置", command=lambda: self.guard(self.save_live_settings)).pack(side="right", padx=6)
        ttk.Button(options, text="窗口校准", command=lambda: self.guard(self.calibrate_live)).pack(side="right")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=12)
        self.quick_start_button = ttk.Button(bar, text="连接并开始实战", command=self.quick_start_live)
        self.quick_start_button.pack(side="left", padx=(0, 10))
        self.preflight_button = ttk.Button(bar, text="检查模型与连接", command=lambda: self.live_countdown(self.preflight))
        self.preflight_button.pack(side="left")
        self.live_start_button = ttk.Button(bar, text="开始实战", command=lambda: self.live_countdown(self.start_live), state="disabled")
        self.live_start_button.pack(side="left", padx=10)
        ttk.Button(bar, text="紧急停止", command=self.stop_live).pack(side="left")
        ttk.Button(bar, text="解除紧停", command=lambda: self.guard(self.clear_live_stop)).pack(side="left", padx=5)
        ttk.Button(bar, text="刷新会话状态", command=self.live_status).pack(side="left", padx=10)
        ttk.Button(bar, text="复制问题报告", command=lambda: self.guard(self.copy_live_report)).pack(side="left")
        self.live_text = self.text_area(tab)
        self.write_text(self.live_text, "将炉石停在酒馆战棋的『开始』菜单，点击『连接并开始实战』并在5秒内切回游戏。\n实战使用日志读取和旧体验版窗口坐标方案，无需截图校准；菜单沿用旧版轻量识别。\n实战效果尚待您手动验收；当前模型仅做过短训练，未证明棋力。")
        self.discover_live_paths()

    def data_tab(self):
        tab = self.tab("实战数据")
        ttk.Label(tab, text="原始实战记录保持不可变；合格、隔离与独立评估按整局划分。", style="Accent.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(tab, text="历史实战仅进入经过验证的辅助用途；优先采样不改变 PPO 的近期采样约束。", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Button(tab, text="刷新真实入库统计", command=self.refresh_data).pack(anchor="w", pady=(0, 10))
        self.data_text = self.text_area(tab)
        self.write_text(self.data_text, "尚未读取实战数据库。")

    @staticmethod
    def text_area(parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", bg=PANEL, fg=INK, font=("Microsoft YaHei UI", 10), relief="flat", padx=14, pady=12, state="disabled")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        return text

    @staticmethod
    def write_text(widget, content):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def guard(self, function):
        try:
            return function()
        except Exception as error:
            messagebox.showerror("操作未完成", str(error), parent=self.root)
            return None

    def start(self):
        from .service import apply_eval_opponent_choice
        run = self.guard(lambda: self.service.start(apply_eval_opponent_choice(
            {**self.extra_config, **{key: variable.get() for key, variable in self.config_vars.items()}},
            getattr(self,'loaded_eval_mode',None))))
        if run:
            self.run = run
            self.close_when_safe = False
            self.refresh_view()

    def control(self, command):
        if self.run:
            self.guard(lambda: self.service.control(self.run, command))
            self.refresh_view()

    def resume(self, checkpoint=None):
        if self.run:
            overrides = {key: variable.get() for key, variable in self.config_vars.items() if key not in {"model_preset", "seed"}}
            run = self.guard(lambda: self.service.resume(self.run, checkpoint, overrides))
            if run:
                self.run = run
                self.close_when_safe = False
                self.refresh_view()

    def selected_checkpoint(self):
        selected = self.checkpoints.selection()
        if not selected:
            raise ValueError("请先选择已落盘的检查点")
        return self.checkpoint_paths[int(selected[0])]

    def resume_selected(self):
        checkpoint = self.guard(self.selected_checkpoint)
        if checkpoint:
            self.resume(checkpoint)

    def use_live_checkpoint(self):
        checkpoint = self.guard(self.selected_checkpoint)
        if checkpoint:
            self.live_vars["checkpoint"].set(str(checkpoint))
            self.tabs.select(3)

    def select_run(self, event=None):
        index = self.run_picker.current()
        if index >= 0:
            self.run = self.run_paths[index]
            self.load_run_config()
            self.refresh_view()

    def load_run_config(self):
        config = read_json(self.run / "config.json", {})
        self.loaded_eval_mode=config.get('eval_opponent',DEFAULT_CONFIG['eval_opponent'])
        self.extra_config = {key: value for key, value in config.items() if key not in DEFAULT_CONFIG or key=='max_consecutive_failed_lobbies'}
        for key, variable in self.config_vars.items():
            if key in config:
                variable.set(str(config[key]))
        self.config_vars['continue_on_episode_error'].set(config.get('continue_on_episode_error',True))

    def open_run(self):
        if self.run and os.name == "nt":
            self.guard(lambda: os.startfile(str(self.run)))

    def import_config(self):
        path = filedialog.askopenfilename(filetypes=[("JSON 配置", "*.json")])
        if path:
            def load():
                from .service import validate_config
                config = validate_config(json.loads(Path(path).read_text(encoding="utf-8")))
                self.loaded_eval_mode=config.get('eval_opponent',DEFAULT_CONFIG['eval_opponent'])
                self.extra_config = {key: value for key, value in config.items() if key not in DEFAULT_CONFIG or key=='max_consecutive_failed_lobbies'}
                for key, variable in self.config_vars.items():
                    variable.set(str(config[key]))
            self.guard(load)

    def export_config(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON 配置", "*.json")])
        if path:
            def save():
                from .service import atomic_json, validate_config, apply_eval_opponent_choice
                atomic_json(Path(path), validate_config(apply_eval_opponent_choice(
                    {**self.extra_config, **{key: value.get() for key, value in self.config_vars.items()}},getattr(self,'loaded_eval_mode',None))))
            self.guard(save)

    def refresh(self):
        try:
            self.refresh_view()
            if self.task and self.task[0].done():
                future, widget, callback = self.task
                self.task = None
                try:
                    result = future.result()
                    self.write_text(widget, self.format_result(result, widget))
                    if callback:
                        callback(result)
                except Exception as error:
                    self.write_text(widget, f"组件调用失败：{error}")
            signature = json.dumps(self.live_config(), sort_keys=True)
            if signature != self.last_live_signature:
                self.live_preflight = None
                self.live_start_button.configure(state="disabled")
            self.preflight_button.configure(state="disabled" if self.task else "normal")
            self.quick_start_button.configure(state="disabled" if self.task or getattr(self, "live_countdown_pending", False) else "normal")
            if not self.task and not getattr(self, "live_countdown_pending", False):
                path = Path(self.live_vars["session_root"].get()) / "status.json"
                if path.exists():
                    stamp = path.stat().st_mtime_ns
                    if stamp != getattr(self, "last_live_status_stamp", None):
                        self.last_live_status_stamp = stamp
                        self.write_text(self.live_text, self.format_result(read_json(path, {}), self.live_text))
            if self.close_when_safe and not self.service.active_runs():
                self.destroy()
                return
        except Exception as error:
            self.footer.set(f"刷新失败（稍后重试）：{error}")
        self.root.after(1000, self.refresh)

    def refresh_view(self):
        paths = self.service.runs()
        if paths != self.run_paths:
            self.run_paths = paths
            self.run_picker.configure(values=[p.name for p in paths])
        if self.run is None and paths:
            self.run = next(iter(self.service.active_runs()), paths[0])
            self.load_run_config()
        if not self.run:
            for button in (self.pause_button, self.resume_button, self.stop_button):
                button.configure(state="disabled")
            return
        self.run_var.set(self.run.name)
        status = self.service.snapshot(self.run)
        alive = status["process_alive"]
        self.head_state.set(STATE_TEXT.get(status.get("state"), str(status.get("state", "未知状态"))))
        message = f"第 {status.get('round', '—')} 轮 · {status.get('message', '')}"
        detail = status.get("progress", {})
        if alive and detail:
            phase = "独立评估" if detail.get("phase") == "evaluation" else "训练采样"
            message += f"\n最近{phase}进度：{detail.get('active_lobbies', '—')} 局进行中 · {detail.get('decisions_in_active_lobbies', '—')} 次决策 · {len(detail.get('worker_pids', []))} 个环境进程"
        if status.get('isolated_error_lobbies'):
            message+=f" · 已隔离 {status['isolated_error_lobbies']} 局错误（详见异常与日志）"
        usage=status.get('ppo_sample_usage')
        if usage:
            message+=f"\n最近一批：采样 {usage['sampled_decisions']} 条决策，实际用于训练 {usage['unique_optimized_decisions']} 条（去重，{usage['sample_usage_fraction']:.0%}）"
            if usage.get('early_stop_kl') is not None:message+=' · 策略变化超限，已提前结束本批更新'
        self.status_text.set(message)
        self.metrics["games"].set(str(status.get("completed_games", 0)))
        self.metrics["updates"].set(str(status.get("updates", 0)))
        config = read_json(self.run / "config.json", {})
        total = int(config.get("rounds", 1)) * int(config.get("games_per_round", 1))
        self.progress["value"] = min(100, float(status.get("completed_games", 0)) * 100/max(1, total))
        records = self.service.evaluations(self.run)
        # Each curve uses a single fixed opponent. Never connect incomparable opponents.
        opponent = config.get("eval_opponent")
        comparable = [r for r in records if r.get("opponent") == opponent]
        self.chart.update_records(comparable)
        if comparable:
            latest = comparable[-1]
            self.metrics["rank"].set(f"{float(latest['mean_rank']):.2f}")
            rate = lambda key: f"{float(latest[key]):.0%}" if latest.get(key) is not None else "—"
            self.metrics["rates"].set(f"{rate('top4_rate')} / {rate('win_rate')}")
            method = str(latest.get("ci_method", "未记录"))
            ci = "已弃用，不展示" if latest.get("legacy_ci_warning") else f"{latest.get('ci_low', '—')} ～ {latest.get('ci_high', '—')}"
            if "hoeffding" in method.lower():
                method = "有界 Hoeffding 95% 区间"
            elif latest.get("legacy_ci_warning"):
                method = latest["legacy_ci_warning"]
            legacy_count = sum(bool(r.get("legacy_ci_warning")) for r in comparable)
            legacy = f" · {legacy_count} 条旧区间已隐藏" if legacy_count else ""
            self.eval_info.set(f"固定对手：{opponent} · {len(comparable)} 次真实评估 · 本次样本 {latest.get('games', '—')} 局{legacy}\n{method}：{ci} · 模型：{Path(latest.get('checkpoint') or '未记录').name}")
            if latest.get('quarantined_games'):
                self.eval_info.set(self.eval_info.get()+f"\n本次另隔离 {latest['quarantined_games']} 局错误并补采样；统计仅含正常终局。")
        else:
            self.metrics["rank"].set("—")
            self.metrics["rates"].set("—")
            self.eval_info.set(f"固定对手：{opponent} · 尚无可比较的真实独立评估")
        for button in (self.pause_button, self.stop_button):
            button.configure(state="normal" if alive else "disabled")
        self.resume_button.configure(state="normal" if not alive and status.get("checkpoint") else "disabled")
        checkpoints = self.service.checkpoints(self.run)
        if checkpoints != self.checkpoint_paths:
            self.checkpoint_paths = checkpoints
            self.checkpoints.delete(*self.checkpoints.get_children())
            for i, path in enumerate(checkpoints):
                self.checkpoints.insert("", "end", iid=str(i), values=(path.name, f"{path.stat().st_size/1048576:.1f} MB", str(path)))
        reports = self.service.reports(self.run)
        if reports != self.report_paths:
            self.report_paths = reports
            self.report_picker.configure(values=[str(p.relative_to(self.run)) for p in reports])
            if reports:
                self.report_picker.current(0)
        if reports:
            self.show_report()
        else:
            self.write_text(self.report_text, "当前运行未产生异常报告或日志。")

    def show_report(self):
        index = self.report_picker.current()
        if 0 <= index < len(self.report_paths):
            try:
                path = self.report_paths[index]
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 150000))
                    content = stream.read().decode("utf-8", errors="replace")
                self.write_text(self.report_text, content or "日志当前为空。")
            except OSError as error:
                self.write_text(self.report_text, str(error))

    def format_result(self, result, widget):
        if widget is self.data_text:
            lines = [f"新增实战对局：{result.get('new_live_games', '—')}",
                f"合格对局：{result.get('qualified_games', '—')}",
                f"辅助训练实际使用：{result.get('actual_used_sequences', '—')} 条序列 / {result.get('actual_used_steps', '—')} 个步骤",
                f"实际有效来源：{result.get('effective_sources', '—')} 局",
                f"PPO 历史实战样本：{result.get('ppo_live_samples', '—')}", "", "按整局用途划分："]
            translations = {"qualified": "合格", "quarantined": "隔离", "quarantine": "隔离", "train": "训练", "evaluation": "独立评估", "eval": "独立评估"}
            for group in result.get("groups", []):
                state = translations.get(group.get("status"), group.get("status", "未知"))
                split = translations.get(group.get("split"), group.get("split", "待划分"))
                lines.append(f"  {state} · {split}：{group.get('games', '—')} 局，{group.get('decisions', '—')} 次决策")
            if not result.get("groups"):
                lines.append("  当前数据库尚无实战记录。")
            if result.get("quarantine_reasons"):
                lines += ["", "隔离原因：", json.dumps(result["quarantine_reasons"], ensure_ascii=False, indent=2)]
            return "\n".join(lines)
        if widget is self.live_text and "checks" in result:
            labels = dict(target_build="训练规则版本", client_target="实战适配版本", deployment_contract="版本兼容记录", model_compatibility="模型兼容检查", checkpoint="本局固定模型", client_build="客户端版本", log_available="公开日志", window_calibration="窗口校准", emergency_stop="紧急停止", public_mapping_adapter="观察与动作映射", real_adapter="真实执行适配", exclusive_client="独占控制", commander_release="模型验证记录", adapter_probe="适配器自检", public_producer="当前公开状态", queue_entry="自动匹配入口")
            lines = ["预检通过，可以开始。" if result.get("ok") else "预检未通过，实战保持停止。", ""]
            for check in result["checks"]:
                lines.append(("✓ " if check.get("ok") else "✕ ") + labels.get(check.get("name"), str(check.get("name"))))
                detail = check.get("detail", "")
                lines.append("  " + (detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)))
            return "\n".join(lines)
        if widget is self.live_text and result.get("state"):
            names = dict(idle="尚未开始", starting="正在准备", queueing="正在匹配下一局", running="模型自动操作中", waiting_window="等待游戏窗口恢复", waiting_public_state="等待可读取的对局状态", waiting_receipt="等待操作结果", paused="已暂停，需要检查", failed="已停止并保存错误", completed="本次实战结束", blocked="连接检查未通过", stopping="正在安全停止")
            lines = [names.get(result["state"], result["state"]), result.get("message", "")]
            if "completed_live_games" in result:
                lines.append(f"本次已完成：{result['completed_live_games']} 局")
            if result.get("error_report"):
                lines.append("错误报告：" + str(result["error_report"]))
            if result.get("gaps"):
                lines.append("缺少的公开信息：" + json.dumps(result["gaps"][:8], ensure_ascii=False))
            if result.get("preflight", {}).get("blockers"):
                lines.extend(str(x.get("detail", x)) for x in result["preflight"]["blockers"])
            return "\n".join(x for x in lines if x)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    def browse_live(self, key):
        path = filedialog.askdirectory() if key.endswith("root") else filedialog.askopenfilename()
        if path:
            self.live_vars[key].set(path)

    def live_config(self):
        config = {**self.live_extra_config, **{key: variable.get().strip() for key, variable in self.live_vars.items()}}
        config["model_rules_target"] = "37.0.0.255130"
        config["client_target"] = config["expected_build"]
        config["auto_queue"] = self.live_auto_queue.get()
        # Validation happens before start; editing a field must not break UI polling.
        count = self.live_max_games.get().strip()
        config["max_games"] = int(count) if count.isdecimal() else count
        if not config["auto_queue"]:
            config["max_games"] = 1
        config.setdefault("queue_timeout", 180)
        config.setdefault("turn_wait_seconds", 180)
        config["emergency_stop_path"] = str(Path(config["session_root"]) / "EMERGENCY_STOP")
        return config

    def save_live_settings(self):
        config = self.live_config()
        if type(config["max_games"]) is not int or not 1 <= config["max_games"] <= 10000:
            raise ValueError("本次最多局数须为1～10000的整数")
        atomic_json(self.data_root / "live-settings.json", config)
        self.footer.set("实战设置已保存。保存设置不会启动游戏或发送操作。")

    def discover_live_paths(self):
        candidates = [Path(self.live_vars["client_path"].get()), Path("D:/Hearthstone/Hearthstone.exe"),
                      Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Hearthstone/Hearthstone.exe"]
        client = next((p for p in candidates if p.is_file() and p.suffix.lower() == ".exe"), None)
        if client:
            self.live_vars["client_path"].set(str(client))
            logs = list((client.parent / "Logs").glob("*/Power.log"))
            if logs:
                self.live_vars["log_path"].set(str(max(logs, key=lambda p: p.stat().st_mtime_ns)))
        if not self.live_vars["checkpoint"].get():
            for run in self.service.runs():
                checkpoint = read_json(run / "status.json", {}).get("checkpoint")
                if checkpoint and Path(checkpoint).is_file():
                    self.live_vars["checkpoint"].set(checkpoint)
                    break
        self.live_preflight = None
        self.live_start_button.configure(state="disabled")
        self.footer.set("已填写发现的本机路径。最新日志仍须核对为本次酒馆战棋会话，不能用旧日志开始实战。")

    def calibrate_live(self):
        self.save_live_settings()
        config = self.live_config()
        output = self.data_root / "live-config" / "calibration-session.json"
        atomic_json(output, config)
        command = [sys.executable, "-m", "bgagent10.live_calibration", "--config", str(output), "--capture"]
        output.parent.mkdir(parents=True, exist_ok=True)
        with (output.parent / "calibration.log").open("ab") as log:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.footer.set("已打开窗口校准工具；它读取截图供定位。若未出现，请查看 live-config/calibration.log。")

    def async_call(self, function, widget, callback=None):
        if self.task:
            self.write_text(widget, "后台任务进行中，请稍候。")
            return
        self.task = (self.executor.submit(function), widget, callback)
        self.write_text(widget, "正在读取与验证真实组件…")

    def preflight(self):
        config = self.live_config()
        signature = json.dumps(config, sort_keys=True)
        self.prepared_live_config = None
        self.live_start_button.configure(state="disabled")
        def check():
            try:
                connected = importlib.import_module("bgagent10.live_quick_setup").prepare_connection(config)
                prepared = importlib.import_module("bgagent10.live_setup").prepare_model(connected)
            except Exception as exc:
                return {"state": "blocked", "ok": False, "checks": [{"name": "model_compatibility", "ok": False, "detail": str(exc)}]}
            report = importlib.import_module("bgagent10.live").preflight(prepared)
            return dict(report, _prepared_config=prepared)
        def done(result):
            self.prepared_live_config = result.pop("_prepared_config", None)
            self.live_preflight = result
            self.last_live_signature = signature
            # The live component independently checks again on start.
            ready = result.get("ok") is True and result.get("state") != "blocked"
            self.live_start_button.configure(state="normal" if ready else "disabled")
        self.async_call(check, self.live_text, done)

    def quick_start_live(self):
        if self.task or getattr(self, "live_countdown_pending", False):
            return
        self.discover_live_paths()
        try:
            self.save_live_settings()
        except Exception as exc:
            self.write_text(self.live_text, str(exc))
            return
        self.live_countdown(self.connect_and_start)

    def connect_and_start(self):
        config = self.live_config()
        def work():
            from .live_setup import prepare_model
            from .live_quick_setup import prepare_connection
            from .live import start, _SESSIONS, record_failure
            from .service import atomic_json
            active = _SESSIONS.get(str(Path(config["session_root"]).resolve()))
            if active and active[1].is_alive():
                return {"state": "blocked", "message": "已有实战会话运行，请先停止。"}
            try:
                if Path(config["emergency_stop_path"]).exists():
                    raise ValueError("紧急停止仍有效；请先点击『解除紧停』，再手动开始。")
                prepared = prepare_model(prepare_connection(config))
                return start(prepared)
            except Exception as exc:
                return record_failure(config["session_root"], exc, state="blocked", stage="connection_setup",
                    connection_evidence=getattr(exc, "connection_evidence", None),
                    checkpoint=config.get("checkpoint"))
        self.async_call(work, self.live_text)

    def live_countdown(self, action, remaining=5):
        if remaining == 5:
            if self.task or getattr(self, "live_countdown_pending", False):
                self.footer.set("当前检查或倒计时尚未结束。")
                return
            self.live_countdown_pending = True
        if not getattr(self, "live_countdown_pending", False):
            return
        if remaining:
            self.write_text(self.live_text, f"{remaining} 秒后{('检查连接' if action.__name__ == 'preflight' else '连接并开始实战')}。\n请切换到炉石窗口并保持画面无遮挡。点击紧急停止可取消。")
            self.root.after(1000, lambda: self.live_countdown(action, remaining - 1))
        else:
            self.live_countdown_pending = False
            action()

    def clear_live_stop(self):
        from . import live
        config = self.live_config()
        active = live._SESSIONS.get(str(Path(config["session_root"]).resolve()))
        if active and active[1].is_alive():
            raise ValueError("操作尚未安全停止，请稍后再解除紧停。")
        Path(config["emergency_stop_path"]).unlink(missing_ok=True)
        (Path(config["session_root"]) / "control.json").unlink(missing_ok=True)
        self.live_preflight = None
        self.prepared_live_config = None
        self.live_start_button.configure(state="disabled")
        self.write_text(self.live_text, "已解除紧停。软件保持停止；重新检查后可手动开始。")

    def start_live(self):
        if not self.live_preflight or json.dumps(self.live_config(), sort_keys=True) != self.last_live_signature:
            self.write_text(self.live_text, "配置发生改变，请重新预检。")
            return
        config = self.prepared_live_config
        if not config:
            self.write_text(self.live_text, "模型尚未通过兼容检查，请先检查模型与连接。")
            return
        self.async_call(lambda: importlib.import_module("bgagent10.live").start(config), self.live_text)

    def stop_live(self):
        # Emergency signal is immediate even when an unrelated background task is busy.
        self.live_countdown_pending = False
        config = self.live_config()
        def stop():
            from .service import atomic_json
            atomic_json(Path(config["emergency_stop_path"]), {"command": "stop", "source": "desktop"})
            result = importlib.import_module("bgagent10.live").stop(config["session_root"])
            self.write_text(self.live_text, self.format_result(result, self.live_text))
        self.guard(stop)
        self.live_start_button.configure(state="disabled")
        self.live_preflight = None

    def live_status(self):
        session = self.live_vars["session_root"].get()
        self.async_call(lambda: importlib.import_module("bgagent10.live").status(session), self.live_text)

    def copy_live_report(self):
        session = Path(self.live_vars["session_root"].get())
        report = dict(software="BGagent正式版1.0 实战验收版", session=str(session), status=read_json(session / "status.json", {}))
        failures = list((session / "errors").glob("*.json"))
        if failures:
            latest = max(failures, key=lambda path: path.stat().st_mtime_ns)
            report["latest_error"] = read_json(latest, {})
        self.root.clipboard_clear()
        self.root.clipboard_append(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        self.footer.set("已复制当前实战状态与最新错误报告，可直接粘贴到聊天。")

    def refresh_data(self):
        data = self.live_vars["data_root"].get()
        self.async_call(lambda: importlib.import_module("bgagent10.live_data").summarize(data), self.data_text)

    def on_close(self):
        active = self.service.active_runs()
        if active:
            answer = messagebox.askyesnocancel("训练仍在运行", "是否安全暂停后关闭？\n\n是：请求暂停，等待检查点保存后自动关闭。\n否：关闭窗口，训练在后台继续；重开工作台自动连接。\n取消：继续使用工作台。", parent=self.root)
            if answer is None:
                return
            if answer:
                for run in active:
                    self.guard(lambda r=run: self.service.control(r, "pause"))
                self.close_when_safe = True
                self.footer.set("等待训练器在安全边界保存并退出，届时自动关闭；可以继续查看进度。")
                return
        # No live operation is allowed to continue unintentionally after a UI close.
        self.stop_live_on_close()
        self.destroy()

    def stop_live_on_close(self):
        config = self.live_config()
        session = Path(config["session_root"])
        if session.exists():
            from .service import atomic_json
            atomic_json(Path(config["emergency_stop_path"]), {"command": "stop", "source": "desktop_close"})

    def destroy(self):
        self.stop_live_on_close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="BGagent 正式版 1.0 中文工作台")
    parser.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parents[2] / "data")
    args = parser.parse_args()
    root = tk.Tk()
    from .training_desktop import TrainingDesktop
    TrainingDesktop(root, args.data_root)
    root.mainloop()


if __name__ == "__main__":
    main()
