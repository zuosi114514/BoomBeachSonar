"""断网/弱网效果测试脚本。

用法（先启动雷电并打开游戏到主界面）:
    python _debug/test_network.py check
    python _debug/test_network.py reject-on
    python _debug/test_network.py reject-off
    python _debug/test_network.py weak-on
    python _debug/test_network.py weak-off
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import ADB_SERIAL, GAME_PACKAGE_NAME
from utils.adb_control import AdbController


def print_section(title: str, content: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print('=' * 60)
    print(content)


def run_check(adb: AdbController) -> None:
    root = adb._run(["shell", "id", "-u"], check=False)
    print_section("Root 检查", f"adb shell id -u => {root.stdout.strip() or root.stderr.strip()}")
    if root.stdout.strip() != "0":
        print("❌ 需要 root。雷电请在设置里开启 root，并确认 adb root 可用。")

    pkg = adb._run(
        ["shell", "cmd", "package", "list", "packages", "-U", GAME_PACKAGE_NAME],
        check=False,
    )
    print_section("包名 / UID", pkg.stdout.strip() or pkg.stderr.strip())
    if GAME_PACKAGE_NAME not in (pkg.stdout or ""):
        print(f"❌ 未找到包 {GAME_PACKAGE_NAME}，请检查 config.py 里的 GAME_PACKAGE_NAME")

    print_section("REJECT 断网诊断", adb.get_reject_network_diagnostics(GAME_PACKAGE_NAME))
    print_section("DROP 弱网诊断", adb.get_weak_network_diagnostics(GAME_PACKAGE_NAME))

    print(
        "\n说明: 诊断里 ipv4_rule=1 表示规则已写入 iptables。"
        "\n若规则存在但游戏仍能联网，可能是雷电网络不走该 UID 的 OUTPUT 链。"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)

    action = sys.argv[1].lower()
    adb = AdbController(ADB_SERIAL)
    adb.ensure_root_shell()

    if action == "check":
        run_check(adb)
        return

    if action == "reject-on":
        adb.enable_reject_network(GAME_PACKAGE_NAME)
        print("已开启 REJECT 断网。请在游戏里做一个需要联网的操作（如点声呐格），观察是否断网。")
        run_check(adb)
        return

    if action == "reject-off":
        adb.disable_reject_network(GAME_PACKAGE_NAME)
        print("已关闭 REJECT 断网。")
        run_check(adb)
        return

    if action == "weak-on":
        adb.enable_weak_network(GAME_PACKAGE_NAME)
        print("已开启 DROP 弱网。请在游戏里测试联网行为。")
        run_check(adb)
        return

    if action == "weak-off":
        adb.disable_weak_network(GAME_PACKAGE_NAME)
        print("已关闭 DROP 弱网。")
        run_check(adb)
        return

    print(f"未知命令: {action}")
    print(__doc__)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
