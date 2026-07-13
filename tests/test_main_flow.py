import importlib
import sys
import unittest
from unittest.mock import patch


class FakeAdb:
    instances = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        FakeAdb.instances.append(self)

    def delay(self, seconds):
        self.calls.append(("delay", seconds))
        return self

    def close_app(self, package_name):
        self.calls.append(("close_app", package_name))

    def open_app(self, package_name):
        self.calls.append(("open_app", package_name))
        return self

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def read_screenshot(self, output_path=None):
        self.calls.append(("read_screenshot", output_path))
        import numpy as np
        return np.zeros((720, 1280, 3), dtype=np.uint8)

    def swipe(self, start_x, start_y, end_x, end_y):
        self.calls.append(("swipe", start_x, start_y, end_x, end_y))
        return self

    def drag(self, start_x, start_y, end_x, end_y, duration_ms=800):
        self.calls.append(
            ("drag", start_x, start_y, end_x, end_y, duration_ms)
        )
        return self

    def enable_weak_network(self, package_name):
        self.calls.append(("enable_weak_network", package_name))

    def disable_weak_network(self, package_name):
        self.calls.append(("disable_weak_network", package_name))

    def enable_reject_network(self, package_name):
        self.calls.append(("enable_reject_network", package_name))

    def disable_reject_network(self, package_name):
        self.calls.append(("disable_reject_network", package_name))


class DummyMatch:
    def __init__(self, center):
        self.center = center


class MainFlowTest(unittest.TestCase):
    def setUp(self):
        FakeAdb.instances.clear()
        self.utils = importlib.import_module("utils")
        self.original_adb_controller = self.utils.AdbController
        self.utils.AdbController = FakeAdb
        sys.modules.pop("main", None)
        self.main = importlib.import_module("main")
        self.adb = self.main.adb

    def tearDown(self):
        sys.modules.pop("main", None)
        self.utils.AdbController = self.original_adb_controller
        FakeAdb.instances.clear()

    def _patch_enter_helpers(self, waits):
        return (
            patch.object(self.main, "wait_until_occur", side_effect=lambda *args, **kwargs: next(waits)),
            patch.object(self.main, "wait_sonar_ready", return_value=True),
            patch.object(self.main, "skip_victory_overlay", return_value=False),
            patch.object(self.main, "find_template", return_value=None),
            patch.object(self.main, "wait_activity_detail_ready", return_value=True),
        )

    def test_enter_activity_recovers_after_activity_button_missing(self):
        waits = iter(
            [
                None,
                DummyMatch((10, 20)),
            ]
        )
        patches = self._patch_enter_helpers(waits)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            self.main.enter_activity(max_retries=2)

        package_name = self.main.GAME_PACKAGE_NAME
        self.assertEqual(self.adb.calls.count(("close_app", package_name)), 1)
        self.assertEqual(self.adb.calls.count(("open_app", package_name)), 1)
        self.assertIn(("click", 10, 20), self.adb.calls)
        self.assertIn(("click", 1205, 644), self.adb.calls)
        self.assertIn(("click", *self.main.ACTIVITY_TAP_TO_START_POINT), self.adb.calls)
        self.assertEqual(
            [
                call for call in self.adb.calls
                if call == ("swipe", 1000, 660, 1000, 180)
            ],
            [
                ("swipe", 1000, 660, 1000, 180),
                ("swipe", 1000, 660, 1000, 180),
            ],
        )

    def test_enter_activity_stops_after_max_retries(self):
        with patch.object(self.main, "wait_sonar_ready", return_value=True):
            with patch.object(self.main, "wait_until_occur", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "最大重试次数 2"):
                    self.main.enter_activity(max_retries=2)

        package_name = self.main.GAME_PACKAGE_NAME
        self.assertEqual(self.adb.calls.count(("close_app", package_name)), 2)
        self.assertEqual(self.adb.calls.count(("open_app", package_name)), 2)

    def test_re_enter_skips_first_enter_only_actions(self):
        waits = iter([DummyMatch((30, 40))])
        patches = self._patch_enter_helpers(waits)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            self.main.enter_activity(re_enter=True, max_retries=1)

        package_name = self.main.GAME_PACKAGE_NAME
        self.assertNotIn(("enable_weak_network", package_name), self.adb.calls)
        self.assertNotIn(("swipe", 1000, 660, 1000, 180), self.adb.calls)
        self.assertIn(("click", 30, 40), self.adb.calls)
        self.assertIn(("click", 1205, 644), self.adb.calls)
        self.assertIn(("click", *self.main.ACTIVITY_TAP_TO_START_POINT), self.adb.calls)

    def test_cn_restart_clicks_login_island(self):
        package_name = "com.tencent.tmgp.supercell.boombeach"
        with patch.object(self.main.config, "GAME_REGION", "cn"):
            with patch.object(self.main.config, "GAME_PACKAGE_NAME", package_name):
                with patch.object(self.main.config, "LOGIN_WAIT_TIMEOUT", 4.0):
                    self.main._restart_game_for_activity_retry(load_delay=1.0)

        self.assertIn(("close_app", package_name), self.adb.calls)
        self.assertIn(("open_app", package_name), self.adb.calls)
        self.assertIn(
            ("click", *self.main.config.CN_LOGIN_ISLAND_POINT),
            self.adb.calls,
        )
        self.assertIn(("delay", 4.0), self.adb.calls)

    def test_home_swipe_uses_configured_slow_duration(self):
        with patch.object(self.main.config, "HOME_SWIPE_DURATION_MS", 800):
            self.main.swipe_home_up(300)
        self.assertIn(("drag", 640, 500, 640, 200, 800), self.adb.calls)

    def test_wait_activity_detail_ready_skips_victory(self):
        """胜利遮罩下应先跳过胜利，再视为详情就绪。"""
        calls = {"n": 0}

        def fake_find(screenshot, template_path, **kwargs):
            path = str(template_path)
            calls["n"] += 1
            if "victory" in path and calls["n"] <= 2:
                return DummyMatch((640, 322))
            if "quit_activity" in path and calls["n"] > 2:
                return DummyMatch((40, 40))
            return None

        with patch.object(self.main, "find_template", side_effect=fake_find):
            with patch.object(self.main, "skip_victory_overlay", return_value=True) as skip:
                ready = self.main.wait_activity_detail_ready(timeout=2)

        self.assertTrue(ready)
        skip.assert_called()

    def test_try_refill_restores_full_network_before_claiming(self):
        """领取奖励前必须关闭弱网并清理 REJECT 断网。"""
        with patch.object(self.main, "skip_victory_overlay", return_value=False):
            with patch.object(self.main, "refill_ammo_from_rewards", return_value=True):
                with patch.object(self.main, "_ammo_is_empty", return_value=False):
                    should_stop = self.main._try_refill_or_stop(1)

        package_name = self.main.config.GAME_PACKAGE_NAME
        self.assertFalse(should_stop)
        self.assertIn(("disable_weak_network", package_name), self.adb.calls)
        self.assertIn(("disable_reject_network", package_name), self.adb.calls)

    def test_ensure_ammo_before_probe_reenables_weak_network_after_refill(self):
        """探测中补充弹药后应重新开启弱网，避免下一格真实消耗弹药。"""
        with patch.object(self.main, "should_stop", return_value=False):
            with patch.object(self.main, "_ammo_is_empty", side_effect=[True, False]):
                with patch.object(self.main, "_try_refill_or_stop", return_value=False):
                    can_probe = self.main._ensure_ammo_before_probe()

        package_name = self.main.config.GAME_PACKAGE_NAME
        self.assertTrue(can_probe)
        self.assertIn(("enable_weak_network", package_name), self.adb.calls)

    def test_click_hits_retries_when_victory_missing(self):
        """首次点击后未出现胜利界面时，应重试统一点击一次。"""
        hit_map = [[1, 0], [0, 1]]
        click_points = [(10, 20), (30, 40), (50, 60), (70, 80)]
        wait_calls = {"n": 0}

        def fake_skip_victory(timeout=0, max_rounds=3):
            if timeout > 0:
                wait_calls["n"] += 1
                return wait_calls["n"] == 2
            return False

        with patch.object(self.main, "skip_victory_overlay", side_effect=fake_skip_victory):
            self.main._click_hits_and_wait_victory(hit_map, 2, click_points, total_hits=2)

        click_coords = [call for call in self.adb.calls if call[:1] == ("click",)]
        self.assertEqual(len(click_coords), 4)
        self.assertEqual(wait_calls["n"], 2)
        self.assertIn(("click", 10, 20), click_coords)
        self.assertIn(("click", 70, 80), click_coords)


if __name__ == "__main__":
    unittest.main()
