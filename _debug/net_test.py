"""断网功能手动测试工具。

运行后通过按键控制游戏网络，到模拟器里观察游戏是否断网：
  w → 开启弱网(DROP)    s → 关闭弱网
  r → 开启断网(REJECT)  f → 关闭断网
  q → 退出（自动清理所有规则）

用法:
    python _debug/net_test.py
    python _debug/net_test.py --serial 127.0.0.1:5555
    python _debug/net_test.py --pkg com.tencent.tmgp.supercell.boombeach
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import ADB_SERIAL, GAME_PACKAGE_NAME
from utils.adb_control import AdbController

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="断网手动测试")
    parser.add_argument("--serial", default=ADB_SERIAL)
    parser.add_argument("--pkg", default=GAME_PACKAGE_NAME)
    args = parser.parse_args()

    print(f"{BOLD}断网手动测试工具{RESET}")
    print(f"设备: {args.serial}  游戏包: {args.pkg}")
    print()

    # 连接 + root
    adb = AdbController(serial=args.serial)
    try:
        adb.ensure_root_shell()
    except RuntimeError as e:
        print(f"{RED}无法获取 root: {e}{RESET}")
        print("请在模拟器设置中开启 ROOT 权限后重试。")
        return

    if adb._su_fallback:
        print(f"{YELLOW}使用 su -c 回退模式{RESET}")
    else:
        print(f"{GREEN}adb shell 已是 root{RESET}")

    # 显示 UID
    uid = adb._get_package_uid(args.pkg)
    print(f"游戏 UID: {uid}")
    print()

    # 状态
    weak_on = False
    reject_on = False

    def show_status():
        print(f"\n{BOLD}当前状态:{RESET} 弱网={'🟢开启' if weak_on else '⚪关闭'}  断网={'🔴开启' if reject_on else '⚪关闭'}")
        print()

    def show_help():
        print(f"""
{BOLD}操作键:{RESET}
  {CYAN}w{RESET} → 开启弱网(DROP)    {CYAN}s{RESET} → 关闭弱网
  {CYAN}r{RESET} → 开启断网(REJECT)  {CYAN}f{RESET} → 关闭断网
  {CYAN}c{RESET} → 查看规则数据包计数
  {CYAN}h{RESET} → 显示帮助
  {CYAN}q{RESET} → 退出（自动清理）
        """)

    def show_counters():
        weak_info = adb._run_privileged_script(
            "iptables -L BBMA_WEAKNET -v -n 2>&1 | grep -E '^[[:space:]]*[0-9]+' || echo '(空)'",
            check=False,
        ).stdout.strip()
        reject_info = adb._run_privileged_script(
            "iptables -L BBMA_REJECTNET -v -n 2>&1 | grep -E '^[[:space:]]*[0-9]+' || echo '(空)'",
            check=False,
        ).stdout.strip()

        print(f"\n{BOLD}iptables 包计数:{RESET}")
        print(f"  BBMA_WEAKNET:   {weak_info or '(空)'}")
        print(f"  BBMA_REJECTNET: {reject_info or '(空)'}")
        print()

    show_help()

    try:
        while True:
            key = input(f"{BOLD}> {RESET}").strip().lower()
            if not key:
                continue

            if key == "w":
                print(f"{CYAN}开启弱网(DROP)...{RESET}")
                adb.enable_weak_network(args.pkg)
                weak_on = True
                show_status()
                print(f"{YELLOW}👉 去模拟器观察游戏：网络请求应被静默丢弃，不弹重试框{RESET}")

            elif key == "s":
                print(f"{CYAN}关闭弱网(DROP)...{RESET}")
                adb.disable_weak_network(args.pkg)
                weak_on = False
                show_status()
                print(f"{GREEN}👉 游戏网络应恢复正常{RESET}")

            elif key == "r":
                print(f"{CYAN}开启断网(REJECT)...{RESET}")
                adb.enable_reject_network(args.pkg)
                reject_on = True
                show_status()
                print(f"{YELLOW}👉 去模拟器观察游戏：网络请求应被拒绝，游戏可能弹重试框{RESET}")

            elif key == "f":
                print(f"{CYAN}关闭断网(REJECT)...{RESET}")
                adb.disable_reject_network(args.pkg)
                reject_on = False
                show_status()
                print(f"{GREEN}👉 游戏网络应恢复正常{RESET}")

            elif key == "c":
                show_counters()

            elif key == "h":
                show_help()

            elif key == "q":
                break

            else:
                print(f"{RED}未知按键 '{key}'，按 h 查看帮助{RESET}")

    except KeyboardInterrupt:
        print()

    finally:
        # 清理
        print(f"\n{CYAN}正在清理所有网络规则...{RESET}")
        try:
            if weak_on:
                adb.disable_weak_network(args.pkg)
            if reject_on:
                adb.disable_reject_network(args.pkg)
            print(f"{GREEN}清理完成{RESET}")
        except Exception as e:
            print(f"{RED}清理失败: {e}{RESET}")

    print("退出。")


if __name__ == "__main__":
    main()
