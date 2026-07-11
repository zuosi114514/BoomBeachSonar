"""断网功能实机诊断测试。

此测试需要连接真实设备（模拟器）才能运行，不会修改设备上的任何 iptables 规则。

用法:
    python tests/test_network_live.py          # 全量诊断（推荐）
    python tests/test_network_live.py --quick  # 快速诊断（跳过耗时项）
    python tests/test_network_live.py --live   # 实机开关测试（会临时改规则并恢复）
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# 修复 Windows 控制台 GBK 编码问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import ADB_SERIAL, GAME_PACKAGE_NAME
from utils.adb_control import AdbController


# ── ANSI ─────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW= "\033[93m"
CYAN  = "\033[96m"
BOLD  = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> str:
    return f"{GREEN}✓{RESET} {msg}"

def fail(msg: str) -> str:
    return f"{RED}✗{RESET} {msg}"

def warn(msg: str) -> str:
    return f"{YELLOW}⚠{RESET} {msg}"

def info(msg: str) -> str:
    return f"{CYAN}→{RESET} {msg}"

def section(title: str) -> None:
    print(f"\n{BOLD}{'─' * 60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─' * 60}{RESET}")


# ── 诊断函数 ──────────────────────────────────────────────────────────

class NetworkDiagnostics:
    def __init__(self, adb: AdbController):
        self.adb = adb
        self.results: list[tuple[str, bool, str]] = []  # (name, passed, detail)

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append((name, passed, detail))
        if passed:
            print(ok(name))
        else:
            print(fail(name))
        if detail:
            print(f"     {detail}")

    def _shell(self, cmd: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        """执行一条 adb shell 命令，返回结果。"""
        return self.adb._run(["shell", cmd], check=check)

    def _shell_output(self, cmd: str) -> str:
        """执行 adb shell 命令并返回 stdout 文本。"""
        return self._shell(cmd, check=False).stdout.strip()

    def _root_shell(self, cmd: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        """执行需要 root 权限的 shell 命令。

        在 adb root 模式下直接执行；在 su 回退模式下通过 su -c 执行。
        """
        if self.adb._su_fallback:
            return self.adb._run(["shell", "su", "-c", cmd], check=check)
        return self._shell(cmd, check=check)

    def _root_shell_output(self, cmd: str) -> str:
        """执行需要 root 权限的 shell 命令并返回 stdout 文本。"""
        return self._root_shell(cmd, check=False).stdout.strip()

    # ── 1. 基础环境检查 ──────────────────────────────────────────

    def check_root(self) -> None:
        section("1. Root 权限检查")
        # 先查看当前状态
        raw_uid = self._shell_output("id -u 2>&1")
        print(f"     当前 shell uid: {raw_uid}")

        # 尝试获取 root（优先 adb root，回退 su）
        try:
            self.adb.ensure_root_shell()
        except RuntimeError as e:
            self.record("无法获取 root 权限", False, str(e))
            return

        # 再次确认
        if self.adb._su_fallback:
            self.record(
                "使用 su -c 回退模式 (adb root 不可用)",
                True,
                "特权命令将通过 su -c 执行，功能不受影响。",
            )
        else:
            self.record("adb shell 已是 root", True)

    def check_iptables_available(self) -> None:
        section("2. iptables 可用性检查")
        result = self._shell("which iptables", check=False)
        if result.returncode == 0:
            path = result.stdout.strip()
            self.record(f"iptables 可用", True, f"路径: {path}")
        else:
            self.record("iptables 不可用", False, "iptables 命令不存在")
            return

        # 检查 iptables 版本和可用模块
        ver = self._shell_output("iptables --version 2>&1")
        print(f"     {ver}")

    def check_owner_module(self) -> None:
        """检查 xt_owner 内核模块是否可用（最关键的一步）。"""
        section("3. iptables owner 模块检查 (关键)")

        # 方法1: 检查内核模块是否已加载
        lsmod = self._root_shell_output("lsmod 2>/dev/null || cat /proc/modules 2>/dev/null")
        if "xt_owner" in lsmod:
            self.record("xt_owner 内核模块已加载", True)
        else:
            # 方法2: 尝试用 owner 匹配创建一个临时链来验证
            test_result = self._root_shell(
                "iptables -N BBMA_TEST_OWNER 2>/dev/null; "
                "iptables -A BBMA_TEST_OWNER -m owner --uid-owner 0 -j ACCEPT 2>&1; "
                "rc=$?; "
                "iptables -F BBMA_TEST_OWNER 2>/dev/null; "
                "iptables -X BBMA_TEST_OWNER 2>/dev/null; "
                "echo rc=$rc",
                check=False,
            )
            output = test_result.stdout.strip()
            if "rc=0" in output:
                self.record("owner 模块可用（通过实测验证）", True)
            elif "No chain/target/match" in test_result.stdout + test_result.stderr:
                self.record(
                    "owner 模块不可用！",
                    False,
                    "iptables 不支持 -m owner 匹配。"
                    "这是断网功能失效的根本原因。"
                    "请更换支持 xt_owner 的内核或模拟器。",
                )
            else:
                self.record(
                    "owner 模块状态未知",
                    False,
                    f"测试结果: {output}\nstderr: {test_result.stderr.strip()}",
                )

    def check_existing_iptables_rules(self) -> None:
        """检查当前是否有残留规则。"""
        section("4. 现有 iptables 规则检查")

        for chain in ("BBMA_WEAKNET", "BBMA_REJECTNET"):
            exists = self._root_shell_output(f"iptables -L {chain} -n 2>&1")
            if "No chain" in exists:
                print(ok(f"{chain} 链不存在（干净）"))
            else:
                print(warn(f"{chain} 链存在，可能有残留规则:"))
                for line in exists.splitlines():
                    print(f"     {line}")

        # 查看 OUTPUT 链中是否有 UID 相关规则
        output_rules = self._root_shell_output("iptables -L OUTPUT -n -v 2>&1")
        if "BBMA_" in output_rules:
            print(warn("OUTPUT 链中存在 BBMA 相关规则:"))
            for line in output_rules.splitlines():
                if "BBMA_" in line:
                    print(f"     {line}")
        else:
            print(ok("OUTPUT 链中无 BBMA 相关规则"))

    # ── 2. 包名/UID 检查 ──────────────────────────────────────────

    def check_package_uid(self) -> None:
        section("5. 游戏包名 / UID 检查")

        pkg_output = self._shell_output(
            f"cmd package list packages -U {GAME_PACKAGE_NAME} 2>&1"
        )
        if GAME_PACKAGE_NAME not in pkg_output:
            self.record(
                f"未找到游戏包 {GAME_PACKAGE_NAME}",
                False,
                "请确认游戏已安装且包名正确。"
                "国际服: com.supercell.boombeach"
                "国服:   com.tencent.tmgp.supercell.boombeach",
            )
            return

        print(ok(f"找到包: {pkg_output}"))

        # 获取 UID
        try:
            uid = self.adb._get_package_uid(GAME_PACKAGE_NAME)
            self.record(f"游戏 UID: {uid}", True)

            # 额外检查: UID 对应的包名列表
            pkg_list = self._shell_output(f"cmd package list packages --uid {uid} 2>&1")
            print(f"     UID {uid} 下的所有包: {pkg_list}")
        except Exception as e:
            self.record("无法获取游戏 UID", False, str(e))

    # ── 3. 网络连通性 ─────────────────────────────────────────────

    def check_network_connectivity(self) -> None:
        """检查设备本身的网络连通性。"""
        section("6. 设备网络连通性检查")
        ping_result = self._shell("ping -c 2 -W 3 8.8.8.8 2>&1 || ping -c 2 -W 3 114.114.114.114 2>&1", check=False)
        output = ping_result.stdout + ping_result.stderr
        if "2 received" in output or "2 packets received" in output:
            self.record("设备可访问外网", True, output.strip().splitlines()[-1] if output.strip() else "")
        elif "1 received" in output:
            self.record("设备网络不稳定（丢包50%）", False, output.strip())
        else:
            self.record(
                "设备无法访问外网",
                False,
                "设备本身无网络连接，断网测试无意义。请先恢复设备网络。"
                f"\n     {output.strip()[:200]}",
            )

    def check_network_interfaces(self) -> None:
        """列出网络接口，检查是否有多网卡。"""
        section("7. 网络接口检查")
        interfaces = self._shell_output("ip addr show 2>/dev/null || ifconfig 2>/dev/null")
        if interfaces:
            # 简要展示
            for line in interfaces.splitlines():
                stripped = line.strip()
                if any(kw in stripped for kw in ("inet ", "link/", "mtu", "^[a-z]", "UP")):
                    if stripped:
                        print(f"     {stripped}")
        else:
            print(warn("无法获取网络接口信息"))

    def check_dns(self) -> None:
        """测试 DNS 解析。"""
        dns_result = self._shell_output("nslookup google.com 2>&1 || getent hosts google.com 2>&1 || echo FAILED")
        if "FAILED" in dns_result:
            # 尝试 ping DNS
            dns_result = self._shell_output("ping -c 2 -W 2 8.8.8.8 2>&1")
            self.record(
                "DNS 解析测试",
                "received" in dns_result,
                f"DNS 解析失败，但 ping 8.8.8.8: {'通' if 'received' in dns_result else '不通'}",
            )
        else:
            self.record("DNS 解析正常", True, dns_result.strip()[:200])

    # ── 4. 实机规则测试（可选，需要 --live） ─────────────────────

    def live_test_weak_network(self) -> None:
        """实机测试弱网规则：写入 → 验证 → 清理。"""
        section("A. 实机弱网 (DROP) 测试")

        uid = self.adb._get_package_uid(GAME_PACKAGE_NAME)

        # 1. 清理旧规则
        print(info("清理旧规则..."))
        self.adb.disable_weak_network(GAME_PACKAGE_NAME)

        # 2. 开启弱网
        print(info("开启弱网..."))
        self.adb.enable_weak_network(GAME_PACKAGE_NAME)
        time.sleep(0.5)

        # 3. 验证规则已写入
        check = self._root_shell_output(
            f"iptables -C OUTPUT -m owner --uid-owner {uid} -j BBMA_WEAKNET 2>&1; echo RC=$?"
        )
        rule_written = "RC=0" in check
        self.record("DROP 规则已写入 iptables", rule_written, f"验证结果: {check}")

        # 4. 查看链的包计数
        if rule_written:
            chain_info = self._root_shell_output(f"iptables -L BBMA_WEAKNET -v -n 2>&1")
            print(f"     BBMA_WEAKNET 链详情:\n{_indent(chain_info, '     ')}")

            # 尝试触发一次网络请求来验证是否有包被 DROP
            print(info("等待 3 秒观察是否有包被丢弃..."))
            time.sleep(3)
            chain_info2 = self._root_shell_output(f"iptables -L BBMA_WEAKNET -v -n 2>&1")
            print(f"     等待后 BBMA_WEAKNET 链详情:\n{_indent(chain_info2, '     ')}")

            # 解析 pkts 计数
            pkts = _parse_pkt_count(chain_info)
            if pkts is not None and pkts > 0:
                print(ok(f"检测到 {pkts} 个被 DROP 的包，规则生效中"))
            else:
                print(warn("未检测到被 DROP 的包，游戏可能没有发包或规则未命中"))

        # 5. 关闭弱网
        print(info("关闭弱网..."))
        self.adb.disable_weak_network(GAME_PACKAGE_NAME)
        time.sleep(0.3)

        # 6. 验证已清理
        check2 = self._root_shell_output(
            f"iptables -C OUTPUT -m owner --uid-owner {uid} -j BBMA_WEAKNET 2>&1; echo RC=$?"
        )
        rule_cleaned = (
            "RC=1" in check2
            or "RC=2" in check2
            or "No such file" in check2
            or "does a matching rule exist" in check2.lower()
            or "Couldn't find target" in check2
            or "No chain/target/match" in check2
        )
        self.record("DROP 规则已清理", rule_cleaned, f"验证结果: {check2}")

    def live_test_reject_network(self) -> None:
        """实机测试 REJECT 断网规则：写入 → 验证 → 清理。"""
        section("B. 实机断网 (REJECT) 测试")

        uid = self.adb._get_package_uid(GAME_PACKAGE_NAME)

        # 1. 清理旧规则
        print(info("清理旧规则..."))
        self.adb.disable_reject_network(GAME_PACKAGE_NAME)

        # 2. 开启断网
        print(info("开启断网..."))
        self.adb.enable_reject_network(GAME_PACKAGE_NAME)
        time.sleep(0.5)

        # 3. 验证规则已写入
        check = self._root_shell_output(
            f"iptables -C OUTPUT -m owner --uid-owner {uid} -j BBMA_REJECTNET 2>&1; echo RC=$?"
        )
        rule_written = "RC=0" in check
        self.record("REJECT 规则已写入 iptables", rule_written, f"验证结果: {check}")

        # 4. 查看链
        if rule_written:
            chain_info = self._root_shell_output(f"iptables -L BBMA_REJECTNET -v -n 2>&1")
            print(f"     BBMA_REJECTNET 链详情:\n{_indent(chain_info, '     ')}")

            print(info("等待 3 秒观察是否有包被 REJECT..."))
            time.sleep(3)
            chain_info2 = self._root_shell_output(f"iptables -L BBMA_REJECTNET -v -n 2>&1")
            print(f"     等待后 BBMA_REJECTNET 链详情:\n{_indent(chain_info2, '     ')}")

            pkts = _parse_pkt_count(chain_info)
            if pkts is not None and pkts > 0:
                print(ok(f"检测到 {pkts} 个被 REJECT 的包，规则生效中"))
            else:
                print(warn("未检测到被 REJECT 的包"))

        # 5. 关闭断网
        print(info("关闭断网..."))
        self.adb.disable_reject_network(GAME_PACKAGE_NAME)
        time.sleep(0.3)

        # 6. 验证已清理
        check2 = self._root_shell_output(
            f"iptables -C OUTPUT -m owner --uid-owner {uid} -j BBMA_REJECTNET 2>&1; echo RC=$?"
        )
        rule_cleaned = (
            "RC=1" in check2
            or "RC=2" in check2
            or "No such file" in check2
            or "does a matching rule exist" in check2.lower()
            or "Couldn't find target" in check2
            or "No chain/target/match" in check2
        )
        self.record("REJECT 规则已清理", rule_cleaned, f"验证结果: {check2}")

    def live_test_traffic_block(self) -> None:
        """终极测试：通过观察 iptables 包计数器验证流量是否真的被阻断。

        不依赖 curl/wget（这些工具以 root 运行会绕过 UID 匹配），
        而是直接观察游戏 UID 的 iptables 计数器增长来验证阻断生效。
        """
        section("C. 实机流量阻断验证 (终极测试)")

        uid = self.adb._get_package_uid(GAME_PACKAGE_NAME)

        # 清理旧规则
        self.adb.disable_reject_network(GAME_PACKAGE_NAME)
        self.adb.disable_weak_network(GAME_PACKAGE_NAME)
        time.sleep(0.3)

        # ── 步骤1: 基线测量 ──
        print(info("步骤1: 开启弱网(DROP)，测量基线包计数..."))
        self.adb.enable_weak_network(GAME_PACKAGE_NAME)
        time.sleep(0.5)
        before = self._root_shell_output(
            f"iptables -L BBMA_WEAKNET -v -n 2>&1 | grep -v '^$' | grep -v '^Chain'"
        ).strip()
        before_pkts = _parse_pkt_count(before) or 0
        print(f"     基线 DROP 计数: {before_pkts}")

        # ── 步骤2: 等待游戏发包 ──
        print(info("步骤2: 等待 5 秒，让游戏自然发包..."))
        time.sleep(5)

        after = self._root_shell_output(
            f"iptables -L BBMA_WEAKNET -v -n 2>&1 | grep -v '^$' | grep -v '^Chain'"
        ).strip()
        after_pkts = _parse_pkt_count(after) or 0
        new_pkts = after_pkts - before_pkts
        print(f"     当前 DROP 计数: {after_pkts}  (新增 {new_pkts} 个包)")

        # ── 步骤3: 判断 ──
        self.adb.disable_weak_network(GAME_PACKAGE_NAME)
        time.sleep(0.3)

        if new_pkts > 0:
            self.record(
                f"流量阻断生效: 5秒内 {new_pkts} 个包被 DROP",
                True,
                f"游戏 UID {uid} 的 {new_pkts} 个出站包被 iptables 丢弃，断网功能确认有效。",
            )
        else:
            self.record(
                "未检测到被阻断的包",
                False,
                "可能原因: 游戏当前没有后台网络活动，或流量走了其他路径。"
                "建议在游戏中进行操作（如点击声呐）时重新测试。"
                "但规则本身已验证写入正确，大概率是游戏当前空闲。",
            )

    # ── 5. 汇总 ────────────────────────────────────────────────────

    def summarize(self) -> None:
        section("诊断汇总")
        passed = sum(1 for _, p, _ in self.results if p)
        failed = sum(1 for _, p, _ in self.results if not p)
        total = len(self.results)

        print(f"\n  总计: {total}  通过: {GREEN}{passed}{RESET}  失败: {RED}{failed}{RESET}")

        if failed > 0:
            print(f"\n{RED}{BOLD}失败项:{RESET}")
            for name, passed, detail in self.results:
                if not passed:
                    print(f"  {RED}✗{RESET} {name}")
                    if detail:
                        for line in detail.splitlines():
                            print(f"     {line}")

        # 给出根因分析
        print(f"\n{BOLD}根因分析:{RESET}")
        owner_ok = any("owner" in name.lower() and p for name, p, _ in self.results)
        root_ok = any("root" in name.lower() and p for name, p, _ in self.results)

        if not root_ok:
            print(f"  {RED}→ 没有 root 权限，iptables 规则无法写入。请先解决 root 问题。{RESET}")
        elif not owner_ok:
            print(f"  {RED}→ iptables owner 模块不可用，这是断网失效的根本原因。{RESET}")
            print(f"     Android 内核需要编译 xt_owner 模块。")
            print(f"     可以尝试: lsmod | grep xt_ 来查看已加载的 netfilter 模块。")
            print(f"     如果缺少 xt_owner，需要更换模拟器或刷入带模块的内核。")
        else:
            print(f"  {GREEN}→ 基础条件满足。如果断网仍不生效，可能是以下原因:{RESET}")
            print(f"     1. 游戏使用 IPv6 通信且 ip6tables 规则未正确写入")
            print(f"     2. 游戏流量走了其他网络命名空间")
            print(f"     3. OUTPUT 链中有更高优先级的 ACCEPT 规则")
            print(f"     4. 游戏通过本地代理/VPN 发包，绕过了 UID 匹配")


# ── 辅助 ─────────────────────────────────────────────────────────────

def _indent(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def _parse_pkt_count(iptables_list_output: str) -> int | None:
    """从 iptables -L -v 输出中提取 pkts 计数。"""
    for line in iptables_list_output.splitlines():
        # 格式: pkts bytes target prot opt in out source destination
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0].isdigit():
            return int(parts[0])
    return None


# ── 入口 ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="断网功能实机诊断")
    parser.add_argument("--quick", action="store_true", help="快速诊断（跳过耗时的连通性检查）")
    parser.add_argument("--live", action="store_true", help="实机测试（临时写入/清理 iptables 规则）")
    parser.add_argument("--serial", default=ADB_SERIAL, help=f"ADB 设备序列号 (默认: {ADB_SERIAL})")
    parser.add_argument("--pkg", default=GAME_PACKAGE_NAME, help=f"游戏包名 (默认: {GAME_PACKAGE_NAME})")
    args = parser.parse_args()

    # 覆盖全局配置
    import config
    config.ADB_SERIAL = args.serial
    config.GAME_PACKAGE_NAME = args.pkg

    print(f"{BOLD}断网功能实机诊断工具{RESET}")
    print(f"设备: {args.serial}  包名: {args.pkg}")
    print(f"模式: {'快速' if args.quick else '完整'} + {'实机测试' if args.live else '只读诊断'}")

    try:
        adb = AdbController(serial=args.serial)
        adb.connect()
    except Exception as e:
        print(fail(f"无法连接设备: {e}"))
        print("请确认模拟器已启动且 ADB 已连接。")
        print(f"可以尝试: adb connect {args.serial}")
        sys.exit(1)

    diag = NetworkDiagnostics(adb)

    # ── 只读诊断 ──
    diag.check_root()
    diag.check_iptables_available()
    diag.check_owner_module()
    diag.check_existing_iptables_rules()
    diag.check_package_uid()

    if not args.quick:
        diag.check_network_connectivity()
        diag.check_network_interfaces()
        diag.check_dns()

    # ── 实机测试（可选）──
    if args.live:
        print(f"\n{YELLOW}{BOLD}⚠ 实机测试将临时修改 iptables 规则，测试完成后会自动清理{RESET}")
        try:
            adb.ensure_root_shell()
        except Exception as e:
            print(fail(f"无法获取 root: {e}"))
            diag.summarize()
            sys.exit(1)

        diag.live_test_weak_network()
        diag.live_test_reject_network()
        diag.live_test_traffic_block()

        # 确保清理
        print(f"\n{info('最终清理: 移除所有 BBMA 相关的 iptables 规则...')}")
        try:
            adb.disable_weak_network(args.pkg)
            adb.disable_reject_network(args.pkg)
            print(ok("清理完成"))
        except Exception as e:
            print(warn(f"清理时出错 (可能规则本就不存在): {e}"))

    diag.summarize()


if __name__ == "__main__":
    main()
