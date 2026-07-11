import importlib
import importlib.util
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils.adb_control import (
    _build_reject_network_diagnostics_script,
    _build_reject_network_script,
    _build_weak_network_diagnostics_script,
    _build_weak_network_script,
)


class IptablesScriptTest(unittest.TestCase):
    def test_weak_network_enable_uses_uid_and_drop_chain(self):
        script = _build_weak_network_script("iptables", 10050, enabled=True)

        self.assertIn("BBMA_WEAKNET", script)
        self.assertIn("--uid-owner 10050", script)
        self.assertIn("-j DROP", script)
        self.assertIn("-I OUTPUT", script)

    def test_weak_network_disable_removes_output_jump(self):
        script = _build_weak_network_script("iptables", 10050, enabled=False)

        self.assertIn("--uid-owner 10050", script)
        self.assertIn("-D OUTPUT", script)
        self.assertIn("BBMA_WEAKNET", script)

    def test_reject_network_enable_uses_tcp_reset(self):
        script = _build_reject_network_script("iptables", 10050, enabled=True)

        self.assertIn("BBMA_REJECTNET", script)
        self.assertIn("--uid-owner 10050", script)
        self.assertIn("REJECT --reject-with tcp-reset", script)
        self.assertIn("icmp-port-unreachable", script)

    def test_reject_network_enable_ipv6_uses_icmp6(self):
        script = _build_reject_network_script("ip6tables", 10050, enabled=True)

        self.assertIn("icmp6-port-unreachable", script)
        self.assertNotIn("icmp-port-unreachable", script)

    def test_reject_network_disable_flushes_chain(self):
        script = _build_reject_network_script("iptables", 10050, enabled=False)

        self.assertIn("-F BBMA_REJECTNET", script)
        self.assertIn("-X BBMA_REJECTNET", script)

    def test_diagnostics_scripts_reference_uid(self):
        weak_diag = _build_weak_network_diagnostics_script(10050)
        reject_diag = _build_reject_network_diagnostics_script(10050)

        self.assertIn("--uid-owner 10050", weak_diag)
        self.assertIn("BBMA_WEAKNET", weak_diag)
        self.assertIn("--uid-owner 10050", reject_diag)
        self.assertIn("BBMA_REJECTNET", reject_diag)
        self.assertIn("ipv4_rule=", weak_diag)
        self.assertIn("ipv4_rule=", reject_diag)


class FakeNetworkAdb:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.calls = []
        FakeNetworkAdb.instances.append(self)

    def ensure_root_shell(self):
        self.calls.append("ensure_root_shell")

    def enable_reject_network(self, package_name):
        self.calls.append(("enable_reject_network", package_name))

    def disable_reject_network(self, package_name):
        self.calls.append(("disable_reject_network", package_name))

    def enable_weak_network(self, package_name):
        self.calls.append(("enable_weak_network", package_name))

    def disable_weak_network(self, package_name):
        self.calls.append(("disable_weak_network", package_name))

    def get_reject_network_diagnostics(self, package_name):
        self.calls.append(("get_reject_network_diagnostics", package_name))
        return "ipv4_rule=1"

    def get_weak_network_diagnostics(self, package_name):
        self.calls.append(("get_weak_network_diagnostics", package_name))
        return "ipv4_rule=0"

    def _run(self, _args, check=True):
        return SimpleNamespace(stdout="0", stderr="", returncode=0)


class TestNetworkCliTest(unittest.TestCase):
    def setUp(self):
        FakeNetworkAdb.instances.clear()
        self.utils = importlib.import_module("utils")
        self.original_adb_controller = self.utils.AdbController
        self.utils.AdbController = FakeNetworkAdb

        sys.modules.pop("test_network", None)
        debug_dir = __import__("pathlib").Path(__file__).resolve().parents[1] / "_debug"
        spec = importlib.util.spec_from_file_location("test_network", debug_dir / "test_network.py")
        self.test_network = importlib.util.module_from_spec(spec)
        sys.modules["test_network"] = self.test_network
        spec.loader.exec_module(self.test_network)
        self.test_network.AdbController = FakeNetworkAdb

    def tearDown(self):
        self.utils.AdbController = self.original_adb_controller
        sys.modules.pop("test_network", None)
        FakeNetworkAdb.instances.clear()

    @patch.object(sys, "argv", ["test_network.py", "reject-on"])
    @patch("builtins.print")
    def test_cli_reject_on_enables_network_and_runs_check(self, _print):
        with patch.object(self.test_network, "run_check") as run_check:
            self.test_network.main()

        adb = FakeNetworkAdb.instances[0]
        package_name = self.test_network.GAME_PACKAGE_NAME
        self.assertIn("ensure_root_shell", adb.calls)
        self.assertIn(("enable_reject_network", package_name), adb.calls)
        run_check.assert_called_once()

    @patch.object(sys, "argv", ["test_network.py", "reject-off"])
    @patch("builtins.print")
    def test_cli_reject_off_disables_network(self, _print):
        with patch.object(self.test_network, "run_check") as run_check:
            self.test_network.main()

        adb = FakeNetworkAdb.instances[0]
        package_name = self.test_network.GAME_PACKAGE_NAME
        self.assertIn(("disable_reject_network", package_name), adb.calls)
        run_check.assert_called_once()

    @patch.object(sys, "argv", ["test_network.py", "check"])
    @patch("builtins.print")
    def test_cli_check_reads_diagnostics(self, _print):
        adb = FakeNetworkAdb()
        with patch.object(self.test_network, "AdbController", lambda *_a, **_k: adb):
            with patch.object(self.test_network, "print_section") as print_section:
                self.test_network.run_check(adb)

        self.assertEqual(
            adb.calls.count(("get_reject_network_diagnostics", self.test_network.GAME_PACKAGE_NAME)),
            1,
        )
        self.assertEqual(
            adb.calls.count(("get_weak_network_diagnostics", self.test_network.GAME_PACKAGE_NAME)),
            1,
        )
        self.assertGreaterEqual(print_section.call_count, 3)


if __name__ == "__main__":
    unittest.main()
