"""File-based desktop controller. Training owns status/checkpoint files exclusively."""
from __future__ import annotations

import contextlib
import ctypes
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from .atomic_io import atomic_json

DEFAULT_CONFIG = dict(workers=1, rounds=10, games_per_round=8,
    eval_every_games=40, eval_games=16, eval_opponent="scripted",
    learning_rate=0.0001, ppo_epochs=2, model_preset="small", device="cpu",
    seed=42, resume_from=None,continue_on_episode_error=True,max_consecutive_failed_lobbies=10)
TERMINAL = {"paused", "completed", "failed", "stopped"}


def apply_eval_opponent_choice(config, previous_mode):
    """Changing the UI mode must also replace its inherited explicit pool."""
    result = dict(config)
    mode = result.get('eval_opponent', DEFAULT_CONFIG['eval_opponent'])
    if mode == previous_mode or previous_mode is None:
        return result
    if mode in ('scripted', 'random', 'mixed'):
        result['eval_opponent_pool'] = None
    elif mode == 'history':
        spec = result.get('eval_opponent_pool')
        if isinstance(spec, str):
            path = Path(spec).resolve()
            doc = json.loads(path.read_text('utf-8-sig'))
            entries = doc['opponents'] if isinstance(doc, dict) else doc
            entries = [dict(e, path=str((path.parent/e['path']).resolve())) if e.get('kind')=='checkpoint' else dict(e) for e in entries]
        else:
            entries = spec or []
        pinned = [dict(e) for e in entries if e.get('kind')=='checkpoint' and e.get('sha256')]
        if not pinned:
            raise ValueError('当前配置没有可用的固定历史模型对手，请选择 scripted、random 或 mixed。')
        result['eval_opponent_pool'] = pinned
    else:
        raise ValueError('未知评估对手模式')
    return result


def validate_config(config: dict) -> dict:
    result = {**DEFAULT_CONFIG, **config}
    if type(result['continue_on_episode_error']) is not bool:
        raise ValueError('单局报错继续必须为勾选或取消')
    if type(result['max_consecutive_failed_lobbies']) is not int or result['max_consecutive_failed_lobbies']<1:
        raise ValueError('连续失败保护上限必须为正整数')
    for name, minimum, maximum in [("workers", 1, 256), ("rounds", 1, 1000000),
            ("games_per_round", 1, 1000000), ("eval_every_games", 1, 1000000000),
            ("eval_games", 2, 1000000), ("ppo_epochs", 1, 100), ("seed", 0, 2**32-1)]:
        value = result[name]
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{name} 必须是整数") from None
        if isinstance(value, bool) or str(value).strip() != str(parsed):
            raise ValueError(f"{name} 必须是整数")
        if not minimum <= parsed <= maximum:
            raise ValueError(f"{name} 允许范围 {minimum}～{maximum}")
        result[name] = parsed
    try:
        rate = float(result["learning_rate"])
    except (TypeError, ValueError):
        raise ValueError("学习率必须是数值") from None
    if not math.isfinite(rate) or not 0 < rate <= 1:
        raise ValueError("学习率须大于 0 且不超过 1")
    result["learning_rate"] = rate
    if result["model_preset"] not in {"small", "main"}:
        raise ValueError("模型规格须为 small 或 main")
    if result["device"] not in {"cpu", "cuda"}:
        raise ValueError("设备须为 cpu 或 cuda")
    if not isinstance(result["eval_opponent"], str) or not result["eval_opponent"].strip():
        raise ValueError("请填写有效的评估对手")
    if result.get("resume_from"):
        checkpoint = Path(result["resume_from"]).expanduser().resolve()
        if not checkpoint.is_file():
            raise ValueError("续训检查点不存在")
        result["resume_from"] = str(checkpoint)
    else:
        result["resume_from"] = None
    return result


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def process_identity(pid: int) -> str | None:
    """Creation time identifies our child even after PID reuse or UI restart."""
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None
            created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
                return None
            return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return None


@contextlib.contextmanager
def launch_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("另一个窗口正在启动训练，请稍后刷新") from None
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class TrainingService:
    def __init__(self, runs_root: str | Path, python: str | None = None,
                 *, training_module="bgagent10.training"):
        self.root = Path(runs_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.python = python or sys.executable
        self.training_module = training_module
        self.children: dict[Path, subprocess.Popen] = {}

    def runs(self) -> list[Path]:
        return sorted((p for p in self.root.iterdir() if p.is_dir() and (p / "config.json").is_file()),
                      key=lambda p: (p / "config.json").stat().st_mtime_ns, reverse=True)

    def alive(self, run: Path) -> bool:
        child = self.children.get(run)
        if child is not None:
            return child.poll() is None
        info = read_json(run / "desktop_process.json", {})
        pid, identity = info.get("pid"), info.get("identity")
        return bool(pid and identity and process_identity(pid) == identity)

    def active_runs(self) -> list[Path]:
        return [p for p in self.runs() if self.alive(p)]

    def start(self, config: dict) -> Path:
        config = validate_config(config)
        with launch_lock(self.root / ".desktop-launch.lock"):
            active = self.active_runs()
            if active:
                raise RuntimeError(f"已有训练在运行：{active[0].name}。请先暂停或停止。")
            from .training_recovery import prepare_config
            config, recovery = prepare_config(config, self.root.parent.parent)
            from .policy_recovery import prepare_policy_config
            config, policy_recovery = prepare_policy_config(config, self.root.parent.parent)
            config = validate_config(config)
            run = self.root / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
            run.mkdir()
            atomic_json(run / "config.json", config)
            if recovery is not None:
                atomic_json(run / "rule_recovery.json", recovery)
            if policy_recovery is not None:
                atomic_json(run / "policy_recovery.json", policy_recovery)
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            command = [self.python, "-m", self.training_module, "--config", str(run / "config.json"), "--run-dir", str(run)]
            with (run / "process.log").open("ab", buffering=0) as log:
                try:
                    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                        stderr=subprocess.STDOUT, creationflags=flags, close_fds=True,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
                except OSError as error:
                    atomic_json(run / "desktop_launch_error.json", {"message": str(error)})
                    raise RuntimeError(f"无法启动训练：{error}") from error
            self.children[run] = child
            atomic_json(run / "desktop_process.json", dict(pid=child.pid,
                identity=process_identity(child.pid), command=command, started=time.time()))
            return run

    def control(self, run: Path, command: str) -> None:
        if command not in {"pause", "stop"}:
            raise ValueError("不支持的训练指令")
        if not self.alive(run):
            raise RuntimeError("训练进程已退出，请选择检查点续训")
        atomic_json(run / "control.json", {"command": command})

    def resume(self, run: Path, checkpoint: str | Path | None = None, overrides: dict | None = None) -> Path:
        if self.alive(run):
            raise RuntimeError("请等待训练进程在安全边界保存并退出后续训")
        config = read_json(run / "config.json")
        if not isinstance(config, dict):
            raise ValueError("原运行配置缺失或损坏")
        if overrides:
            if set(overrides) - {"workers", "rounds", "games_per_round", "eval_every_games", "eval_games", "eval_opponent", "device", "learning_rate", "ppo_epochs", "continue_on_episode_error", "max_consecutive_failed_lobbies"}:
                raise ValueError("续训必须保留原模型结构与随机种子")
            previous_mode=config.get('eval_opponent',DEFAULT_CONFIG['eval_opponent'])
            config.update(overrides)
            config=apply_eval_opponent_choice(config,previous_mode)
        status = read_json(run / "status.json", {})
        candidate = checkpoint or status.get("checkpoint")
        if not candidate:
            raise ValueError("尚无已保存的检查点，不能续训")
        candidate = Path(candidate)
        if not candidate.is_absolute():
            candidate = run / candidate
        config["resume_from"] = str(candidate.resolve())
        return self.start(config)

    def snapshot(self, run: Path) -> dict:
        live = self.alive(run)
        raw = read_json(run / "status.json")
        status = dict(raw) if isinstance(raw, dict) else {"state": "starting", "message": "等待训练器写入状态"}
        if not live and status.get("state") not in TERMINAL:
            status.update(state="failed", message="训练进程已退出且未写入终态，请查看 process.log 与异常报告")
        pending = read_json(run / "control.json", {}).get("command")
        if live and pending in {"pause", "stop"} and status.get("state") not in TERMINAL:
            status["message"] = "已请求" + ("暂停" if pending == "pause" else "停止") + "，等待安全边界与检查点落盘"
        status["process_alive"] = live
        status["progress"] = read_json(run / "progress.json", {})
        return status

    @staticmethod
    def evaluations(run: Path) -> list[dict]:
        output = []
        try:
            with (run / "evaluations.jsonl").open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        item = json.loads(line)
                        if isinstance(item, dict):
                            method = str(item.get("ci_method", "")).lower()
                            if ("normal" in method or not method) and ("ci_low" in item or "ci_high" in item):
                                item["legacy_ci_warning"] = "旧版小样本正态区间仅探索性，已弃用"
                            output.append(item)
                    except ValueError:
                        continue  # An append in progress is retried on the next refresh.
        except OSError:
            pass
        return output

    @staticmethod
    def checkpoints(run: Path) -> list[Path]:
        directory = run / "checkpoints"
        return sorted((p for p in directory.glob("*") if p.is_file() and not p.name.endswith((".tmp", ".json"))),
            key=lambda p: p.stat().st_mtime, reverse=True)

    @staticmethod
    def reports(run: Path) -> list[Path]:
        files = list((run / "errors").glob("**/*"))
        files += [run / "process.log"]
        return sorted((p for p in files if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
