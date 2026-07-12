"""单模拟器无界面 worker，由四槽总控 GUI 启动。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BoomBeach 单设备 worker")
    parser.add_argument("--slot", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--settings", type=Path, default=PROJECT_ROOT / "settings.json")
    parser.add_argument(
        "--game-region",
        choices=("international", "cn"),
        default="international",
    )
    parser.add_argument("--manual-level", type=int)
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def _emit_status(slot: str, state: str, **extra) -> None:
    payload = {"slot": slot, "state": state, **extra}
    print("@@BBMA_STATUS " + json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> int:
    args = _parse_args()

    # 必须早于 config/logger/main 导入，以确保所有导入期路径都指向本槽位。
    runtime_root = args.runtime_dir.resolve()
    os.environ["BBMA_INSTANCE_ID"] = args.slot
    os.environ["BBMA_ADB_SERIAL"] = args.serial
    os.environ["BBMA_RUNTIME_DIR"] = str(runtime_root)
    os.environ["BBMA_GAME_REGION"] = args.game_region
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

    from utils.runtime_context import (
        ensure_runtime_dirs,
        RuntimePaths,
    )

    paths = RuntimePaths(
        root=runtime_root,
        screenshots=runtime_root / "screenshots",
        logs=runtime_root / "logs",
        outputs=runtime_root / "outputs",
        stop_file=runtime_root / "stop.flag",
    )
    ensure_runtime_dirs(paths)

    import config
    import main as main_mod
    from utils.logger import get_logger, get_run_elapsed_text, mark_run_start
    from utils.runtime_context import StopRequestedError
    from utils.user_settings import apply_settings, load_settings

    logger = get_logger(f"worker.{args.slot}")
    settings = load_settings(args.settings)
    settings["adb_serial"] = args.serial
    settings["game_package_name"] = (
        config.CN_GAME_PACKAGE
        if args.game_region == "cn"
        else config.INTERNATIONAL_GAME_PACKAGE
    )
    apply_settings(settings)
    mark_run_start()
    _emit_status(
        args.slot,
        "starting",
        serial=args.serial,
        game_region=args.game_region,
        pid=os.getpid(),
    )

    try:
        main_mod.register_exit_cleanup()
        if paths.stop_file.exists():
            raise StopRequestedError("收到总控停止请求")
        adb = main_mod.configure_adb(args.serial)
        adb.ensure_root_shell()
        width, height = adb.get_screenshot_size()
        if (width, height) != (1280, 720):
            logger.warning(
                "设备分辨率为 %sx%s，模板按 1280x720 校准",
                width,
                height,
            )

        package_result = adb._run(
            ["shell", "pm", "path", config.GAME_PACKAGE_NAME],
            check=False,
        )
        if package_result.returncode != 0 or not package_result.stdout.strip():
            raise RuntimeError(f"设备未安装游戏包: {config.GAME_PACKAGE_NAME}")

        _emit_status(
            args.slot,
            "ready",
            serial=args.serial,
            resolution=f"{width}x{height}",
        )
        if args.check_only:
            logger.info("设备检查通过，check-only 退出")
            return 0

        level = args.manual_level
        if level is None and settings.get("manual_level") is not None:
            level = int(settings["manual_level"])

        _emit_status(args.slot, "running", serial=args.serial)
        main_mod.cleanup_reject_network("worker 主流程启动")
        main_mod.main(level)
        _emit_status(
            args.slot,
            "stopped",
            serial=args.serial,
            elapsed=get_run_elapsed_text(),
        )
        return 0
    except StopRequestedError:
        logger.info("收到总控停止请求，worker 正常退出")
        _emit_status(
            args.slot,
            "stopped",
            serial=args.serial,
            elapsed=get_run_elapsed_text(),
        )
        return 0
    except BaseException as exc:
        logger.error("worker 运行失败: %s", exc, exc_info=True)
        _emit_status(
            args.slot,
            "error",
            serial=args.serial,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        return 1
    finally:
        try:
            main_mod.cleanup_weak_network("worker 结束")
            main_mod.cleanup_reject_network("worker 结束")
        except Exception as cleanup_exc:
            logger.error("worker 清理失败: %s", cleanup_exc)


if __name__ == "__main__":
    raise SystemExit(main())
