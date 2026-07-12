from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from utils.runtime_context import (
    StopRequestedError,
    build_runtime_paths,
    interruptible_sleep,
    parse_adb_devices_output,
    validate_unique_serials,
)
from utils.user_settings import load_settings, save_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MultiInstanceTest(unittest.TestCase):
    def test_parse_adb_devices_only_returns_online_devices(self):
        output = """List of devices attached
127.0.0.1:5555 device
emulator-5554 device
emulator-5556 offline
abc unauthorized
"""
        self.assertEqual(
            parse_adb_devices_output(output),
            ["127.0.0.1:5555", "emulator-5554"],
        )

    def test_runtime_paths_are_isolated_for_four_slots(self):
        roots = {
            build_runtime_paths(PROJECT_ROOT, f"slot{index}").root
            for index in range(1, 5)
        }
        self.assertEqual(len(roots), 4)
        for index, root in enumerate(sorted(roots), start=1):
            self.assertIn("runtime", root.parts)
            self.assertTrue(root.name.startswith("slot"))

    def test_duplicate_serial_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_unique_serials(["emulator-5554", "emulator-5554"])
        validate_unique_serials(["emulator-5554", "emulator-5556"])

    def test_worker_delay_is_interrupted_by_stop_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stop_file = Path(temp_dir) / "stop.flag"
            stop_file.write_text("stop\n", encoding="utf-8")
            started = time.monotonic()
            with self.assertRaises(StopRequestedError):
                interruptible_sleep(30, stop_file=stop_file)
            self.assertLess(time.monotonic() - started, 0.5)

    def test_settings_preserve_four_instances(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            settings = load_settings(path)
            settings["instances"][1]["enabled"] = True
            settings["instances"][1]["serial"] = "emulator-5554"
            settings["instances"][1]["game_region"] = "cn"
            save_settings(settings, path)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["instances"]), 4)
            self.assertEqual(saved["instances"][1]["serial"], "emulator-5554")
            self.assertEqual(saved["instances"][1]["game_region"], "cn")

    def test_config_paths_are_isolated_in_four_processes(self):
        observed: set[tuple[str, str, str]] = set()
        with tempfile.TemporaryDirectory() as temp_dir:
            processes: list[subprocess.Popen[str]] = []
            for index in range(1, 5):
                runtime = Path(temp_dir) / f"slot{index}"
                env = os.environ.copy()
                env.update(
                    {
                        "BBMA_INSTANCE_ID": f"slot{index}",
                        "BBMA_ADB_SERIAL": f"emulator-{5552 + index * 2}",
                        "BBMA_RUNTIME_DIR": str(runtime),
                    }
                )
                code = (
                    "import config, json; "
                    "config.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True); "
                    "(config.SCREENSHOT_DIR / 'screen.png').write_text("
                    "config.INSTANCE_ID, encoding='utf-8'); "
                    "print(json.dumps([str(config.SCREENSHOT_DIR), "
                    "str(config.LOG_FILE), str(config.OUTPUT_DIR)]))"
                )
                processes.append(subprocess.Popen(
                    [sys.executable, "-c", code],
                    cwd=PROJECT_ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ))
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
                observed.add(tuple(json.loads(stdout.strip())))
            for index in range(1, 5):
                marker = Path(temp_dir) / f"slot{index}" / "screenshots" / "screen.png"
                self.assertEqual(marker.read_text(encoding="utf-8"), f"slot{index}")
        self.assertEqual(len(observed), 4)


if __name__ == "__main__":
    unittest.main()
