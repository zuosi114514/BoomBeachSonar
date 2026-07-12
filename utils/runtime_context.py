"""四模拟器并行运行所需的轻量运行上下文工具。"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class StopRequestedError(Exception):
    """总控请求 worker 停止时用于快速退出当前等待。"""


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    screenshots: Path
    logs: Path
    outputs: Path
    stop_file: Path


def sanitize_name(value: str) -> str:
    """把槽位/设备名转换为可安全用作目录名的文本。"""
    cleaned = _SAFE_NAME_RE.sub("_", value.strip()).strip("._")
    return cleaned or "unknown"


def build_runtime_paths(project_root: Path, slot: str) -> RuntimePaths:
    """为指定槽位生成独立运行目录。"""
    root = project_root / "runtime" / sanitize_name(slot)
    return RuntimePaths(
        root=root,
        screenshots=root / "screenshots",
        logs=root / "logs",
        outputs=root / "outputs",
        stop_file=root / "stop.flag",
    )


def ensure_runtime_dirs(paths: RuntimePaths) -> None:
    for path in (paths.root, paths.screenshots, paths.logs, paths.outputs):
        path.mkdir(parents=True, exist_ok=True)


def configure_worker_environment(slot: str, serial: str, runtime_dir: Path) -> None:
    """在导入 config/main 前设置 worker 的进程环境。"""
    os.environ["BBMA_INSTANCE_ID"] = slot
    os.environ["BBMA_ADB_SERIAL"] = serial
    os.environ["BBMA_RUNTIME_DIR"] = str(runtime_dir.resolve())
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")


def get_process_stop_file() -> Path | None:
    runtime_dir = os.environ.get("BBMA_RUNTIME_DIR", "").strip()
    return Path(runtime_dir) / "stop.flag" if runtime_dir else None


def is_stop_requested(stop_file: Path | None = None) -> bool:
    target = stop_file if stop_file is not None else get_process_stop_file()
    return target is not None and target.exists()


def interruptible_sleep(
    seconds: float,
    *,
    stop_file: Path | None = None,
    interval: float = 0.1,
) -> None:
    """短周期检查停止文件，避免长延时导致停止/重启失效。"""
    deadline = time.monotonic() + max(0.0, float(seconds))
    while True:
        if is_stop_requested(stop_file):
            raise StopRequestedError("收到总控停止请求")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(max(0.01, interval), remaining))


def parse_adb_devices_output(output: str) -> list[str]:
    """解析 `adb devices`，只返回处于 device 状态的序列号。"""
    devices: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def discover_adb_devices(timeout: float = 8.0) -> list[str]:
    result = subprocess.run(
        ["adb", "devices"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "adb devices failed"
        raise RuntimeError(message)
    return parse_adb_devices_output(result.stdout)


def validate_unique_serials(serials: Iterable[str]) -> None:
    values = [value.strip() for value in serials if value.strip()]
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"ADB 设备不能重复绑定: {', '.join(duplicates)}")
