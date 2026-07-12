"""四模拟器并行总控面板（tkinter + 独立 worker 子进程）。"""

from __future__ import annotations

import base64
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import cv2
import numpy as np

from utils.logger import GuiLogFormatter, attach_log_handler, detach_log_handler, get_logger
from utils.runtime_context import (
    RuntimePaths,
    build_runtime_paths,
    discover_adb_devices,
    ensure_runtime_dirs,
    validate_unique_serials,
)
from utils.user_settings import (
    SETTING_SCHEMA,
    SLOT_COUNT,
    load_settings,
    normalize_instances,
    save_settings,
)


PROJECT_ROOT = Path(__file__).resolve().parent
BACKGROUND_IMAGE = PROJECT_ROOT / "assets" / "app_background.png"
logger = get_logger(__name__)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_LEVEL_RE = re.compile(r"(?:自动识别关卡|使用手动指定关卡):\s*(\d+)")
_AMMO_RE = re.compile(r"当前蓝弹药数量:\s*(\d+)")
_STATUS_PREFIX = "@@BBMA_STATUS "
_MAX_LOG_LINES = 5000
_REGION_TO_LABEL = {"international": "国际服", "cn": "国服"}
_LABEL_TO_REGION = {label: region for region, label in _REGION_TO_LABEL.items()}


class ManagerLogHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue[tuple[str, str]]):
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(GuiLogFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_queue.put(("manager", self.format(record)))
        except Exception:
            self.handleError(record)


@dataclass
class WorkerProcess:
    slot: str
    serial: str
    runtime: RuntimePaths
    process: subprocess.Popen[str]
    started_at: float
    state: str = "启动中"
    stop_requested_at: float | None = None
    restart_pending: bool = False


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("海岛奇兵声呐自动化 - 四模拟器总控")
        self.geometry("1380x820")
        self.minsize(1120, 680)

        self._background_source = cv2.imread(str(BACKGROUND_IMAGE))
        self._background_photo: tk.PhotoImage | None = None
        self._surface_panel_photos: dict[tk.Label, tk.PhotoImage] = {}
        self._surface_panels: list[tuple[tk.Label, tk.Widget]] = []
        self._background_resize_job: str | None = None
        self._background_label = tk.Label(self, borderwidth=0, highlightthickness=0)
        self._background_label.place(x=0, y=0, relwidth=1, relheight=1)
        self._log_visibility = tk.StringVar(value="隐藏日志")
        self._logs_visible = True

        self.settings = load_settings()
        self.workers: dict[str, WorkerProcess] = {}
        self.device_list: list[str] = []
        self._closing = False
        self._close_deadline: float | None = None
        self._log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._manager_handler = ManagerLogHandler(self._log_queue)
        self._global_vars: dict[str, tk.Variable] = {}
        self._slot_vars: dict[str, dict[str, tk.Variable]] = {}
        self._slot_widgets: dict[str, dict[str, Any]] = {}
        self._log_views: dict[str, tk.Text] = {}

        self._build_ui()
        self._toggle_logs()
        self.bind("<Configure>", self._on_window_resize)
        self.after_idle(self._render_background)
        attach_log_handler(self._manager_handler)
        self._load_settings_into_ui()
        self.after(100, self._drain_logs)
        self.after(500, self._poll_workers)
        self.after(50, self.refresh_devices)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        logger.info("四模拟器总控已就绪")

    # ---------- UI ----------

    def _build_ui(self) -> None:
        self.content_panel = tk.Frame(self, borderwidth=0, highlightthickness=0)
        self.content_panel.pack(fill=tk.X, padx=28, pady=(24, 0))
        content_background = tk.Label(
            self.content_panel,
            borderwidth=0,
            highlightthickness=0,
        )
        content_background.place(x=0, y=0, relwidth=1, relheight=1)
        self._surface_panels.append((content_background, self.content_panel))

        toolbar = ttk.Frame(self.content_panel, padding=(8, 8, 8, 4))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="刷新设备", command=self.refresh_devices).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="保存配置", command=self.save_all_settings).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="全部启动", command=self.start_all).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="全部停止", command=self.stop_all).pack(side=tk.LEFT, padx=3)
        self.device_summary = ttk.Label(toolbar, text="ADB 设备：未刷新")
        self.device_summary.pack(side=tk.RIGHT, padx=8)
        log_selector = ttk.Combobox(
            toolbar,
            textvariable=self._log_visibility,
            values=("显示日志", "隐藏日志"),
            state="readonly",
            width=9,
        )
        log_selector.pack(side=tk.RIGHT, padx=5)
        log_selector.bind("<<ComboboxSelected>>", self._toggle_logs)
        ttk.Label(toolbar, text="日志：").pack(side=tk.RIGHT)

        self.main_paned = ttk.Panedwindow(self.content_panel, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.X, padx=8, pady=(4, 8))
        self.main_paned.configure(height=520)

        left_notebook = ttk.Notebook(self.main_paned)
        self.main_paned.add(left_notebook, weight=3)

        devices_page = tk.Frame(left_notebook, borderwidth=0, highlightthickness=0)
        devices_background = tk.Label(
            devices_page,
            borderwidth=0,
            highlightthickness=0,
        )
        devices_background.place(x=0, y=0, relwidth=1, relheight=1)
        self._surface_panels.append((devices_background, devices_page))
        settings_page = ttk.Frame(left_notebook, padding=6)
        left_notebook.add(devices_page, text="设备总控")
        left_notebook.add(settings_page, text="全局设置")

        for index in range(1, SLOT_COUNT + 1):
            self._build_slot_card(devices_page, f"slot{index}", index)
        devices_background.lower()

        self._build_global_settings(settings_page)

        self.logs_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.logs_frame, weight=4)
        self.logs_notebook = ttk.Notebook(self.logs_frame)
        self.logs_notebook.pack(fill=tk.BOTH, expand=True)
        for key, title in [("all", "全部"), ("manager", "总控")] + [
            (f"slot{i}", f"槽位{i}") for i in range(1, SLOT_COUNT + 1)
        ]:
            page = ttk.Frame(self.logs_notebook)
            text = tk.Text(
                page,
                wrap=tk.WORD,
                bg="#1e1e1e",
                fg="#d4d4d4",
                insertbackground="#d4d4d4",
                font=("Consolas", 9),
            )
            scrollbar = ttk.Scrollbar(page, orient=tk.VERTICAL, command=text.yview)
            text.configure(yscrollcommand=scrollbar.set)
            text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self.logs_notebook.add(page, text=title)
            self._log_views[key] = text

        bottom = ttk.Frame(self.logs_frame)
        bottom.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(bottom, text="清空当前日志", command=self._clear_current_log).pack(side=tk.RIGHT)
        content_background.lower()

    def _toggle_logs(self, _event: tk.Event | None = None) -> None:
        should_show = self._log_visibility.get() == "显示日志"
        if should_show and not self._logs_visible:
            self.main_paned.add(self.logs_frame, weight=4)
            self.main_paned.configure(height=520)
            self._logs_visible = True
        elif not should_show and self._logs_visible:
            self.main_paned.forget(self.logs_frame)
            self.main_paned.configure(height=520)
            self._logs_visible = False

    def _on_window_resize(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._background_resize_job is not None:
            self.after_cancel(self._background_resize_job)
        self._background_resize_job = self.after(100, self._render_background)

    def _render_background(self) -> None:
        self._background_resize_job = None
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        if self._background_source is None:
            self._background_label.configure(bg="#d8ece8")
            return

        faded_image = self._make_faded_image(
            width,
            height,
            opacity=0.34,
            cover=True,
        )
        self._background_photo = self._photo_from_image(faded_image)
        if self._background_photo is not None:
            self._background_label.configure(image=self._background_photo)

        root_x = self.winfo_rootx()
        root_y = self.winfo_rooty()
        for label, panel in self._surface_panels:
            panel_width = max(1, panel.winfo_width())
            panel_height = max(1, panel.winfo_height())
            x1 = max(0, panel.winfo_rootx() - root_x)
            y1 = max(0, panel.winfo_rooty() - root_y)
            x2 = min(width, x1 + panel_width)
            y2 = min(height, y1 + panel_height)
            if x2 <= x1 or y2 <= y1:
                continue
            cropped = faded_image[y1:y2, x1:x2]
            photo = self._photo_from_image(cropped)
            if photo is not None:
                self._surface_panel_photos[label] = photo
                label.configure(image=photo)

    def _make_faded_image(
        self,
        width: int,
        height: int,
        *,
        opacity: float,
        cover: bool = False,
    ) -> np.ndarray:
        source = self._background_source
        if source is None:
            return np.full((height, width, 3), (236, 244, 242), dtype=np.uint8)
        source_height, source_width = source.shape[:2]
        scale = (
            max(width / source_width, height / source_height)
            if cover
            else min(width / source_width, height / source_height)
        )
        target_width = max(1, int(round(source_width * scale)))
        target_height = max(1, int(round(source_height * scale)))
        resized = cv2.resize(
            source,
            (target_width, target_height),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
        )
        if cover:
            y1 = max(0, (target_height - height) // 2)
            x1 = max(0, (target_width - width) // 2)
            full_image = resized[y1:y1 + height, x1:x1 + width]
        else:
            full_image = np.full((height, width, 3), (236, 244, 242), dtype=np.uint8)
            y1 = max(0, (height - target_height) // 2)
            x1 = max(0, (width - target_width) // 2)
            full_image[y1:y1 + target_height, x1:x1 + target_width] = resized
        return cv2.addWeighted(
            full_image,
            opacity,
            np.full_like(full_image, 255),
            1.0 - opacity,
            0,
        )

    @staticmethod
    def _photo_from_image(image: np.ndarray) -> tk.PhotoImage | None:
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            return None
        data = base64.b64encode(encoded.tobytes()).decode("ascii")
        return tk.PhotoImage(data=data, format="png")

    def _build_slot_card(self, parent: ttk.Frame, slot: str, index: int) -> None:
        card = ttk.LabelFrame(parent, text=f"槽位 {index}", padding=8)
        card.pack(fill=tk.X, padx=3, pady=5)

        enabled = tk.BooleanVar(value=index == 1)
        game_region = tk.StringVar(value="国际服")
        serial = tk.StringVar()
        manual_level = tk.StringVar()
        state = tk.StringVar(value="已停止")
        level = tk.StringVar(value="-")
        ammo = tk.StringVar(value="-")
        elapsed = tk.StringVar(value="00:00:00")
        self._slot_vars[slot] = {
            "enabled": enabled,
            "game_region": game_region,
            "serial": serial,
            "manual_level": manual_level,
            "state": state,
            "level": level,
            "ammo": ammo,
            "elapsed": elapsed,
        }

        ttk.Checkbutton(card, text="启用", variable=enabled).grid(row=0, column=0, padx=4)
        ttk.Label(card, text="版本：").grid(row=0, column=1, sticky=tk.E)
        ttk.Combobox(
            card,
            textvariable=game_region,
            values=("国际服", "国服"),
            state="readonly",
            width=7,
        ).grid(row=0, column=2, padx=4)
        ttk.Label(card, text="ADB：").grid(row=0, column=3, sticky=tk.E)
        serial_box = ttk.Combobox(card, textvariable=serial, width=20)
        serial_box.grid(row=0, column=4, sticky=tk.EW, padx=4)
        ttk.Label(card, text="指定关卡：").grid(row=0, column=5, sticky=tk.E)
        ttk.Entry(card, textvariable=manual_level, width=7).grid(row=0, column=6, padx=4)

        ttk.Label(card, text="状态：").grid(row=1, column=0, sticky=tk.E, pady=(7, 0))
        ttk.Label(card, textvariable=state, width=13).grid(row=1, column=1, sticky=tk.W, pady=(7, 0))
        ttk.Label(card, text="关卡：").grid(row=1, column=3, sticky=tk.E, pady=(7, 0))
        ttk.Label(card, textvariable=level, width=5).grid(row=1, column=4, sticky=tk.W, pady=(7, 0))
        ttk.Label(card, text="弹药：").grid(row=1, column=5, sticky=tk.E, pady=(7, 0))
        ttk.Label(card, textvariable=ammo, width=5).grid(row=1, column=6, sticky=tk.W, pady=(7, 0))
        ttk.Label(card, text="时间：").grid(row=1, column=7, sticky=tk.E, pady=(7, 0))
        ttk.Label(card, textvariable=elapsed, width=10).grid(row=1, column=8, sticky=tk.W, pady=(7, 0))

        start_btn = ttk.Button(card, text="启动", command=lambda s=slot: self.start_slot(s))
        stop_btn = ttk.Button(card, text="停止", command=lambda s=slot: self.stop_slot(s))
        restart_btn = ttk.Button(card, text="重启", command=lambda s=slot: self.restart_slot(s))
        start_btn.grid(row=0, column=7, padx=3)
        stop_btn.grid(row=0, column=8, padx=3)
        restart_btn.grid(row=0, column=9, padx=3)
        stop_btn.state(["disabled"])
        card.columnconfigure(4, weight=1)
        self._slot_widgets[slot] = {
            "serial_box": serial_box,
            "start": start_btn,
            "stop": stop_btn,
            "restart": restart_btn,
        }

    def _build_global_settings(self, parent: ttk.Frame) -> None:
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        container = ttk.Frame(canvas)
        container.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=container, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        groups: dict[str, ttk.LabelFrame] = {}
        rows: dict[str, int] = {}
        for item in SETTING_SCHEMA:
            if item["key"] in {"adb_serial", "game_package_name", "manual_level"}:
                continue
            group = item["group"]
            if group not in groups:
                box = ttk.LabelFrame(container, text=group, padding=8)
                box.pack(fill=tk.X, padx=5, pady=5)
                groups[group] = box
                rows[group] = 0
            row = rows[group]
            ttk.Label(groups[group], text=item["label"]).grid(row=row, column=0, sticky=tk.W, pady=3)
            var, editor = self._make_setting_editor(groups[group], item)
            self._global_vars[item["key"]] = var
            editor.grid(row=row, column=1, sticky=tk.EW, padx=8, pady=3)
            groups[group].columnconfigure(1, weight=1)
            rows[group] += 1

    def _make_setting_editor(
        self,
        parent: ttk.Frame,
        item: dict[str, Any],
    ) -> tuple[tk.Variable, tk.Widget]:
        kind = item["type"]
        if kind == "bool":
            var = tk.BooleanVar()
            return var, ttk.Checkbutton(parent, variable=var)
        if kind == "choice":
            var = tk.StringVar()
            return var, ttk.Combobox(
                parent,
                textvariable=var,
                values=item["choices"],
                state="readonly",
                width=25,
            )
        var = tk.StringVar()
        return var, ttk.Entry(parent, textvariable=var, width=28)

    # ---------- 配置 ----------

    def _load_settings_into_ui(self) -> None:
        self.settings = load_settings()
        schema_by_key = {item["key"]: item for item in SETTING_SCHEMA}
        for key, var in self._global_vars.items():
            value = self.settings.get(key)
            if schema_by_key[key]["type"] == "bool":
                var.set(bool(value))
            else:
                var.set("" if value is None else str(value))

        for item in normalize_instances(self.settings.get("instances")):
            slot = item["slot"]
            variables = self._slot_vars[slot]
            variables["enabled"].set(item["enabled"])
            variables["game_region"].set(
                _REGION_TO_LABEL.get(item["game_region"], "国际服")
            )
            variables["serial"].set(item["serial"])
            variables["manual_level"].set(
                "" if item["manual_level"] is None else str(item["manual_level"])
            )

    def _read_global_settings(self) -> dict[str, Any]:
        result = dict(self.settings)
        schema_by_key = {item["key"]: item for item in SETTING_SCHEMA}
        for key, var in self._global_vars.items():
            kind = schema_by_key[key]["type"]
            value = var.get()
            if kind == "bool":
                result[key] = bool(value)
            elif kind == "float":
                result[key] = float(str(value).strip())
            elif kind == "optional_int":
                text = str(value).strip()
                result[key] = int(text) if text else None
            else:
                result[key] = str(value).strip()
        return result

    def _read_instances(self) -> list[dict[str, Any]]:
        instances: list[dict[str, Any]] = []
        for index in range(1, SLOT_COUNT + 1):
            slot = f"slot{index}"
            variables = self._slot_vars[slot]
            level_text = str(variables["manual_level"].get()).strip()
            instances.append(
                {
                    "slot": slot,
                    "enabled": bool(variables["enabled"].get()),
                    "game_region": _LABEL_TO_REGION.get(
                        str(variables["game_region"].get()),
                        "international",
                    ),
                    "serial": str(variables["serial"].get()).strip(),
                    "manual_level": int(level_text) if level_text else None,
                }
            )
        return instances

    def save_all_settings(self, show_message: bool = True) -> bool:
        try:
            settings = self._read_global_settings()
            settings["instances"] = self._read_instances()
            enabled_serials = [
                item["serial"]
                for item in settings["instances"]
                if item["enabled"] and item["serial"]
            ]
            validate_unique_serials(enabled_serials)
            save_settings(settings)
            self.settings = settings
            if show_message:
                messagebox.showinfo("保存成功", "全局配置和四个槽位已保存。")
            return True
        except Exception as exc:
            messagebox.showerror("配置无效", str(exc))
            return False

    # ---------- ADB 发现 ----------

    def refresh_devices(self) -> None:
        try:
            self.device_list = discover_adb_devices()
        except Exception as exc:
            self.device_summary.configure(text=f"ADB 刷新失败：{exc}")
            logger.error("刷新 ADB 设备失败: %s", exc)
            return

        values = self.device_list
        for slot, widgets in self._slot_widgets.items():
            widgets["serial_box"].configure(values=values)

        # 空槽位自动分配尚未占用的在线设备，但不自动启用。
        selected = {
            str(variables["serial"].get()).strip()
            for variables in self._slot_vars.values()
            if str(variables["serial"].get()).strip()
        }
        available = [serial for serial in values if serial not in selected]
        for slot in [f"slot{i}" for i in range(1, SLOT_COUNT + 1)]:
            var = self._slot_vars[slot]["serial"]
            if not str(var.get()).strip() and available:
                var.set(available.pop(0))

        self.device_summary.configure(
            text=f"ADB 在线 {len(values)} 台：" + (", ".join(values) if values else "无")
        )
        logger.info("发现 ADB 设备 %d 台: %s", len(values), values)

    # ---------- Worker 生命周期 ----------

    def start_all(self) -> None:
        if not self.save_all_settings(show_message=False):
            return
        enabled = [
            item for item in self._read_instances() if item["enabled"] and item["serial"]
        ]
        if not enabled:
            messagebox.showwarning("没有设备", "请至少启用并选择一个在线设备。")
            return
        try:
            validate_unique_serials(item["serial"] for item in enabled)
        except ValueError as exc:
            messagebox.showerror("设备重复", str(exc))
            return
        for offset, item in enumerate(enabled):
            self.after(offset * 2500, lambda slot=item["slot"]: self.start_slot(slot))

    def start_slot(self, slot: str) -> None:
        existing = self.workers.get(slot)
        if existing is not None and existing.process.poll() is None:
            return
        if not self.save_all_settings(show_message=False):
            return

        variables = self._slot_vars[slot]
        serial = str(variables["serial"].get()).strip()
        if not serial:
            messagebox.showwarning("未选择设备", f"{slot} 尚未选择 ADB 设备。")
            return
        if serial not in self.device_list:
            messagebox.showwarning("设备不在线", f"{serial} 当前不在 adb devices 在线列表。")
            return
        for other_slot, worker in self.workers.items():
            if other_slot != slot and worker.process.poll() is None and worker.serial == serial:
                messagebox.showerror("设备重复", f"{serial} 已由 {other_slot} 运行。")
                return

        runtime = build_runtime_paths(PROJECT_ROOT, slot)
        ensure_runtime_dirs(runtime)
        runtime.stop_file.unlink(missing_ok=True)
        command = [
            sys.executable,
            "-u",
            str(PROJECT_ROOT / "worker.py"),
            "--slot",
            slot,
            "--serial",
            serial,
            "--runtime-dir",
            str(runtime.root),
            "--settings",
            str(PROJECT_ROOT / "settings.json"),
            "--game-region",
            _LABEL_TO_REGION.get(
                str(variables["game_region"].get()),
                "international",
            ),
        ]
        level_text = str(variables["manual_level"].get()).strip()
        if level_text:
            command.extend(["--manual-level", level_text])

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creationflags,
            )
        except Exception as exc:
            messagebox.showerror("启动失败", f"{slot}: {exc}")
            return

        worker = WorkerProcess(
            slot=slot,
            serial=serial,
            runtime=runtime,
            process=process,
            started_at=time.monotonic(),
        )
        self.workers[slot] = worker
        self._set_slot_state(slot, "启动中", running=True)
        threading.Thread(
            target=self._read_worker_output,
            args=(worker,),
            name=f"log-{slot}",
            daemon=True,
        ).start()
        logger.info("[%s][%s] worker 已启动 pid=%s", slot, serial, process.pid)

    def stop_all(self) -> None:
        for slot in list(self.workers):
            self.stop_slot(slot)

    def stop_slot(self, slot: str) -> None:
        worker = self.workers.get(slot)
        if worker is None or worker.process.poll() is not None:
            return
        ensure_runtime_dirs(worker.runtime)
        worker.runtime.stop_file.write_text("stop\n", encoding="utf-8")
        worker.stop_requested_at = time.monotonic()
        worker.state = "停止中"
        self._set_slot_state(slot, "停止中", running=True)
        logger.warning("[%s][%s] 已发送优雅停止请求", slot, worker.serial)

    def restart_slot(self, slot: str) -> None:
        worker = self.workers.get(slot)
        if worker is None or worker.process.poll() is not None:
            self.start_slot(slot)
            return
        worker.restart_pending = True
        self.stop_slot(slot)

    def _read_worker_output(self, worker: WorkerProcess) -> None:
        stream = worker.process.stdout
        if stream is None:
            return
        for raw_line in stream:
            line = _ANSI_RE.sub("", raw_line.rstrip())
            if line:
                self._log_queue.put((worker.slot, line))

    def _poll_workers(self) -> None:
        now = time.monotonic()
        for slot, worker in list(self.workers.items()):
            code = worker.process.poll()
            if code is None:
                elapsed = max(0, int(now - worker.started_at))
                hours, rem = divmod(elapsed, 3600)
                minutes, seconds = divmod(rem, 60)
                self._slot_vars[slot]["elapsed"].set(
                    f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                )
                if worker.stop_requested_at is not None:
                    waited = now - worker.stop_requested_at
                    if waited > 35:
                        worker.process.kill()
                        logger.error("[%s] 优雅停止超时，已强制结束", slot)
                    elif waited > 30:
                        worker.process.terminate()
                continue

            was_running = str(self._slot_vars[slot]["state"].get()) not in {
                "已停止",
                "错误",
            }
            if code == 0:
                self._set_slot_state(slot, "已停止", running=False)
            else:
                self._set_slot_state(slot, f"错误({code})", running=False)
            if was_running:
                logger.info("[%s][%s] worker 退出 code=%s", slot, worker.serial, code)
            restart = worker.restart_pending
            self.workers.pop(slot, None)
            if restart and not self._closing:
                self.after(500, lambda s=slot: self.start_slot(s))

        if self._closing:
            alive = [w for w in self.workers.values() if w.process.poll() is None]
            if not alive:
                self._destroy_now()
                return
            if self._close_deadline is not None and now >= self._close_deadline:
                for worker in alive:
                    worker.process.terminate()
                self._destroy_now()
                return

        self.after(500, self._poll_workers)

    def _set_slot_state(self, slot: str, state: str, *, running: bool) -> None:
        self._slot_vars[slot]["state"].set(state)
        widgets = self._slot_widgets[slot]
        if running:
            widgets["start"].state(["disabled"])
            widgets["stop"].state(["!disabled"])
        else:
            widgets["start"].state(["!disabled"])
            widgets["stop"].state(["disabled"])

    # ---------- 日志与状态 ----------

    def _drain_logs(self) -> None:
        while True:
            try:
                slot, line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._consume_worker_status(slot, line)
            prefix = f"[{slot}] " if slot != "manager" else "[总控] "
            self._append_log("all", prefix + line)
            self._append_log(slot if slot in self._log_views else "manager", line)
        self.after(100, self._drain_logs)

    def _consume_worker_status(self, slot: str, line: str) -> None:
        if line.startswith(_STATUS_PREFIX):
            try:
                payload = json.loads(line[len(_STATUS_PREFIX):])
            except json.JSONDecodeError:
                return
            state_map = {
                "starting": "启动中",
                "ready": "设备就绪",
                "running": "运行中",
                "stopped": "已停止",
                "error": "错误",
            }
            state = state_map.get(str(payload.get("state")), str(payload.get("state")))
            self._slot_vars[slot]["state"].set(state)
            return
        level_match = _LEVEL_RE.search(line)
        if level_match:
            self._slot_vars[slot]["level"].set(level_match.group(1))
        ammo_match = _AMMO_RE.search(line)
        if ammo_match:
            self._slot_vars[slot]["ammo"].set(ammo_match.group(1))

    def _append_log(self, key: str, line: str) -> None:
        view = self._log_views.get(key)
        if view is None:
            return
        view.insert(tk.END, line + "\n")
        line_count = int(view.index("end-1c").split(".")[0])
        if line_count > _MAX_LOG_LINES:
            view.delete("1.0", f"{line_count - _MAX_LOG_LINES}.0")
        view.see(tk.END)

    def _clear_current_log(self) -> None:
        tab_id = self.logs_notebook.select()
        index = self.logs_notebook.index(tab_id)
        key = list(self._log_views)[index]
        self._log_views[key].delete("1.0", tk.END)

    # ---------- 关闭 ----------

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._close_deadline = time.monotonic() + 10.0
        self.stop_all()
        self.title("正在停止所有 worker...")
        if not any(worker.process.poll() is None for worker in self.workers.values()):
            self._destroy_now()

    def _destroy_now(self) -> None:
        detach_log_handler(self._manager_handler)
        self.destroy()


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
