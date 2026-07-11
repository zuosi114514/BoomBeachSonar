"""带可改配置与实时日志窗口的主流程启动器（Windows / tkinter）。"""

from __future__ import annotations

import logging
import queue
import threading
import traceback
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from utils.logger import GuiLogFormatter, attach_log_handler, detach_log_handler, get_logger, get_run_elapsed_text, mark_run_start
from utils.user_settings import (
    SETTING_SCHEMA,
    apply_settings,
    load_settings,
    save_settings,
)

logger = get_logger(__name__)


class QueueLogHandler(logging.Handler):
    """把日志写入线程安全队列，由 UI 主线程刷新。"""

    def __init__(self, log_queue: queue.Queue[str]):
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(GuiLogFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("海岛奇兵声呐自动化")
        self.geometry("1100x720")
        self.minsize(900, 560)

        self._editors: dict[str, Any] = {}
        self._vars: dict[str, tk.Variable] = {}
        self._worker: threading.Thread | None = None
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._log_handler = QueueLogHandler(self._log_queue)

        self._build_ui()
        attach_log_handler(self._log_handler)
        self._load_into_form(load_settings())
        self.after(120, self._drain_logs)
        logger.info("启动器已就绪，可修改配置后点击「开始运行」")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=2)
        paned.add(right, weight=3)

        ttk.Label(left, text="运行配置（可改，保存后生效）").pack(anchor=tk.W)
        canvas = tk.Canvas(left, highlightthickness=0)
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=canvas.yview)
        self.settings_frame = ttk.Frame(canvas)
        self.settings_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.settings_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._build_settings_form(self.settings_frame)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=8)
        self.btn_save = ttk.Button(btn_row, text="保存配置", command=self._on_save)
        self.btn_reload = ttk.Button(btn_row, text="重新加载", command=self._on_reload)
        self.btn_start = ttk.Button(btn_row, text="开始运行", command=self._on_start)
        self.btn_stop = ttk.Button(btn_row, text="请求停止", command=self._on_stop)
        self.btn_clear = ttk.Button(btn_row, text="清空日志", command=self._clear_log)
        self.btn_stop.state(["disabled"])
        for btn in (
            self.btn_save,
            self.btn_reload,
            self.btn_start,
            self.btn_stop,
            self.btn_clear,
        ):
            btn.pack(side=tk.LEFT, padx=3)

        ttk.Label(right, text="运行日志").pack(anchor=tk.W)
        self.log_view = tk.Text(
            right,
            wrap=tk.WORD,
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            font=("Consolas", 10),
        )
        log_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.log_view.yview)
        self.log_view.configure(yscrollcommand=log_scroll.set)
        self.log_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_settings_form(self, parent: ttk.Frame) -> None:
        groups: dict[str, ttk.LabelFrame] = {}
        row_in_group: dict[str, int] = {}
        for item in SETTING_SCHEMA:
            group_name = item["group"]
            if group_name not in groups:
                box = ttk.LabelFrame(parent, text=group_name, padding=8)
                box.pack(fill=tk.X, pady=6, padx=4)
                groups[group_name] = box
                row_in_group[group_name] = 0
            box = groups[group_name]
            row = row_in_group[group_name]
            ttk.Label(box, text=item["label"]).grid(row=row, column=0, sticky=tk.W, pady=3)
            editor = self._make_editor(box, item)
            editor.grid(row=row, column=1, sticky=tk.EW, padx=6, pady=3)
            box.columnconfigure(1, weight=1)
            self._editors[item["key"]] = editor
            row_in_group[group_name] = row + 1

    def _make_editor(self, parent: ttk.Frame, item: dict[str, Any]) -> tk.Widget:
        kind = item["type"]
        key = item["key"]
        if kind == "bool":
            var = tk.BooleanVar(value=False)
            self._vars[key] = var
            return ttk.Checkbutton(parent, variable=var)
        if kind == "choice":
            var = tk.StringVar(value=item["choices"][0])
            self._vars[key] = var
            return ttk.Combobox(
                parent,
                textvariable=var,
                values=item["choices"],
                state="readonly",
                width=28,
            )
        var = tk.StringVar(value="")
        self._vars[key] = var
        entry = ttk.Entry(parent, textvariable=var, width=30)
        if kind == "optional_int":
            # 提示写在 label 里已有
            pass
        return entry

    def _load_into_form(self, settings: dict[str, Any]) -> None:
        for item in SETTING_SCHEMA:
            key = item["key"]
            value = settings.get(key)
            var = self._vars[key]
            if item["type"] == "bool":
                var.set(bool(value))
            elif item["type"] == "optional_int":
                var.set("" if value is None else str(value))
            else:
                var.set("" if value is None else str(value))

    def _read_form(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for item in SETTING_SCHEMA:
            key = item["key"]
            kind = item["type"]
            var = self._vars[key]
            if kind == "bool":
                data[key] = bool(var.get())
            elif kind == "optional_int":
                text = str(var.get()).strip()
                data[key] = int(text) if text else None
            elif kind == "float":
                data[key] = float(str(var.get()).strip())
            else:
                data[key] = str(var.get()).strip()
        return data

    def _on_save(self) -> None:
        try:
            settings = self._read_form()
            save_settings(settings)
            apply_settings(settings)
            messagebox.showinfo("保存成功", "配置已写入 settings.json 并生效。")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def _on_reload(self) -> None:
        self._load_into_form(load_settings())
        logger.info("已从 settings.json 重新加载配置")

    def _on_start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showwarning("正在运行", "主流程仍在运行中。")
            return
        try:
            settings = self._read_form()
            save_settings(settings)
            apply_settings(settings)
        except Exception as exc:
            messagebox.showerror("配置无效", str(exc))
            return

        level = settings.get("manual_level")
        if level is not None:
            level = int(level)

        self.btn_start.state(["disabled"])
        self.btn_stop.state(["!disabled"])
        mark_run_start()
        logger.info("========== 开始运行 ==========")

        self._worker = threading.Thread(
            target=self._run_main,
            args=(level,),
            daemon=True,
        )
        self._worker.start()

    def _run_main(self, level: int | None) -> None:
        ok = True
        message = "主流程已结束"
        try:
            import config
            import main as main_mod

            main_mod.register_exit_cleanup()
            main_mod.clear_stop_request()
            main_mod.adb.serial = config.ADB_SERIAL
            main_mod.adb.ensure_root_shell()
            main_mod.cleanup_reject_network("GUI 主流程启动")
            main_mod.main(level)
        except SystemExit as exc:
            ok = False
            message = f"进程退出: {exc}"
        except Exception as exc:
            ok = False
            message = f"{exc}\n{traceback.format_exc()}"
            logger.error("主流程异常: %s", exc, exc_info=True)
        finally:
            try:
                import main as main_mod

                main_mod.cleanup_weak_network("GUI 主流程结束")
                main_mod.cleanup_reject_network("GUI 主流程结束")
            except Exception as cleanup_exc:
                logger.warning("清理弱网失败: %s", cleanup_exc)
            self.after(0, lambda: self._on_finished(ok, message))

    def _on_stop(self) -> None:
        try:
            import main as main_mod

            main_mod.request_stop()
            logger.warning("已发送停止请求（本关结束后退出）")
        except Exception as exc:
            messagebox.showwarning("停止失败", str(exc))

    def _on_finished(self, ok: bool, message: str) -> None:
        self.btn_start.state(["!disabled"])
        self.btn_stop.state(["disabled"])
        self._worker = None
        logger.info("脚本结束，总运行时间 %s", get_run_elapsed_text())
        if ok:
            logger.info("%s", message)
        else:
            logger.error("运行结束（失败）: %s", message)
            messagebox.showwarning("运行结束", message[:800])

    def _clear_log(self) -> None:
        self.log_view.delete("1.0", tk.END)

    def _drain_logs(self) -> None:
        while True:
            try:
                line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_view.insert(tk.END, line + "\n")
            self.log_view.see(tk.END)
        self.after(120, self._drain_logs)

    def _on_close(self) -> None:
        detach_log_handler(self._log_handler)
        if self._worker is not None and self._worker.is_alive():
            try:
                import main as main_mod

                main_mod.request_stop()
            except Exception:
                pass
        self.destroy()


def main() -> int:
    apply_settings()
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
