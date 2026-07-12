import atexit
import sys
import signal
import time
from pathlib import Path

import cv2
import numpy as np

import config
from save_points.points import read_saved_points, read_saved_quad
from utils import AdbController, MatchResult, find_template, get_logger, is_diamond_hit
from utils.diamond_centers import detect_diamond_centers, write_image
from utils.logger import get_run_elapsed_text, mark_run_start
from utils.ocr_helper import detect_activity_level, read_blue_ammo_count
from utils.reward_helper import refill_ammo_from_rewards
from utils.runtime_context import interruptible_sleep
from utils.submarine_strategy import Cell, SubmarineStrategy, get_configured_submarines

logger = get_logger(__name__)
# 保留旧测试/外部脚本使用的模块级别别名。
GAME_PACKAGE_NAME = config.GAME_PACKAGE_NAME
ACTIVITY_TAP_TO_START_POINT = config.ACTIVITY_TAP_TO_START_POINT
adb = AdbController(auto_connect=False)
_weak_network_cleanup_done = False
_stop_requested = False


def request_stop() -> None:
    """请求主循环在下一关边界停止。"""
    global _stop_requested
    _stop_requested = True
    if config.RUNTIME_DIR is not None:
        stop_file = config.RUNTIME_DIR / "stop.flag"
        stop_file.parent.mkdir(parents=True, exist_ok=True)
        stop_file.write_text("stop\n", encoding="utf-8")
    logger.warning("已请求停止，将在当前关卡流程合适节点退出")


def clear_stop_request() -> None:
    global _stop_requested
    _stop_requested = False
    if config.RUNTIME_DIR is not None:
        (config.RUNTIME_DIR / "stop.flag").unlink(missing_ok=True)


def should_stop() -> bool:
    if _stop_requested:
        return True
    return (
        config.RUNTIME_DIR is not None
        and (config.RUNTIME_DIR / "stop.flag").exists()
    )


def configure_adb(serial: str) -> AdbController:
    """显式创建当前进程专用的 ADB 控制器。"""
    global adb
    adb = AdbController(serial)
    return adb

def enable_weak_network(second: float = 0) -> None:
    """开启游戏弱网，并按需等待网络状态生效。"""
    adb.enable_weak_network(config.GAME_PACKAGE_NAME)
    if second > 0:
        interruptible_sleep(second)

def disable_weak_network(second: float = 0) -> None:
    """关闭游戏弱网，并按需等待网络状态恢复。"""
    adb.disable_weak_network(config.GAME_PACKAGE_NAME)
    if second > 0:
        interruptible_sleep(second)

def cleanup_weak_network(reason: str = "脚本退出") -> None:
    """脚本退出时关闭游戏弱网，防止影响游戏正常运行。"""
    global _weak_network_cleanup_done
    if _weak_network_cleanup_done:
        return
    _weak_network_cleanup_done = True
    try:
        logger.info("%s，正在关闭弱网", reason)
        disable_weak_network()
    except Exception as exc:
        logger.error("关闭弱网失败: %s", exc)

def cleanup_reject_network(reason: str = "脚本退出") -> None:
    """关闭游戏 REJECT 断网残留，避免影响本次或下次运行。"""
    try:
        logger.info("%s，正在清理 REJECT 断网", reason)
        adb.disable_reject_network(config.GAME_PACKAGE_NAME)
    except Exception as exc:
        logger.error("清理 REJECT 断网失败: %s", exc)

def handle_exit_signal(signum: int, _frame) -> None:
    """收到退出信号时先关闭弱网再退出。"""
    cleanup_weak_network(f"收到退出信号 {signum}")
    raise SystemExit(128 + signum)

def register_exit_cleanup() -> None:
    """注册脚本退出清理，尽量避免弱网规则残留。"""
    atexit.register(cleanup_weak_network)
    for signame in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, signame, None)
        if signum is not None:
            signal.signal(signum, handle_exit_signal)

def wait_until_occur(
    template_path: str,
    timeout: float = 30.0,
    threshold: float | None = None,
) -> MatchResult | None:
    """等待直到指定模板出现，返回匹配结果或 None（超时）。"""
    logger.info("正在等待模板 '%s' 出现，超时时间 %s 秒...", template_path, timeout)
    start_time = time.time()
    while time.time() - start_time < timeout:
        screenshot = adb.read_screenshot()
        match_result = find_template(screenshot, template_path, threshold=threshold)
        if match_result is not None:
            return match_result
        interruptible_sleep(0.5)
    logger.warning("等待模板 '%s' 超时 (%s 秒)", template_path, timeout)
    return None

def click_template(template_path: str, screenshot_path: str | None = None, threshold: float = 0.85) -> bool:
    """查找模板并点击中心点，找不到时返回 False。"""
    img = adb.read_screenshot(screenshot_path)
    match_result = find_template(img, template_path, threshold=threshold)
    if match_result is None:
        return False
    adb.delay(0.5).click(*match_result.center)
    return True

def _restart_game_for_activity_retry(load_delay: float | None = None) -> None:
    """杀APP -> 启动 -> 等待加载。"""
    delay = config.GAME_RESTART_LOAD_DELAY if load_delay is None else load_delay
    disable_weak_network()
    cleanup_reject_network()
    adb.close_app(config.GAME_PACKAGE_NAME)
    adb.delay(1.5).open_app(config.GAME_PACKAGE_NAME)
    if config.GAME_REGION == "cn":
        logger.info(
            "国服启动：等待 %.1f 秒后点击「登陆岛屿」...",
            config.LOGIN_WAIT_TIMEOUT,
        )
        adb.delay(config.LOGIN_WAIT_TIMEOUT)
        adb.click(*config.CN_LOGIN_ISLAND_POINT)
        logger.info("已点击国服「登陆岛屿」: %s", config.CN_LOGIN_ISLAND_POINT)
    logger.info("游戏已重启，等待 %s 秒加载...", delay)
    adb.delay(delay)


def swipe_home_up(pixels: int | None = None) -> None:
    """主岛上划，露出海边声纳浮标。"""
    distance = config.HOME_SWIPE_UP_PIXELS if pixels is None else pixels
    x = 640
    start_y = 500
    end_y = max(50, start_y - distance)
    duration_ms = int(config.HOME_SWIPE_DURATION_MS)
    logger.info(
        "主岛上划 %s 像素，持续 %s 毫秒: (%s,%s)->(%s,%s)",
        distance,
        duration_ms,
        x,
        start_y,
        x,
        end_y,
    )
    adb.drag(x, start_y, x, end_y, duration_ms)
    adb.delay(0.5)


def wait_home_island_ready(timeout: float = 45.0) -> bool:
    """等待回到主岛（出现活动按钮），避免加载中误上划。"""
    logger.info("等待主岛就绪（活动按钮），超时 %s 秒...", timeout)
    match = wait_until_occur("./template/activity_button.png", timeout=timeout)
    if match is None:
        logger.warning("等待主岛就绪超时，未出现活动按钮")
        return False
    logger.info("主岛已就绪，活动按钮位于 %s", match.center)
    return True


def _match_sonar(screenshot) -> MatchResult | None:
    """用声纳专用阈值匹配浮标或「参加」标签。"""
    th = config.SONAR_MATCH_THRESHOLD
    match = find_template(screenshot, config.SONAR_TEMPLATE, threshold=th)
    if match is not None:
        return match
    return find_template(screenshot, config.SONAR_LABEL_TEMPLATE, threshold=th)


def wait_sonar_ready(timeout: float | None = None) -> bool:
    """主岛就绪后上划一次，并等待海里「参加」声纳浮标出现。"""
    timeout = config.SONAR_WAIT_TIMEOUT if timeout is None else timeout
    if not wait_home_island_ready():
        return False

    if _match_sonar(adb.read_screenshot()) is not None:
        logger.info("声纳图标已在画面中，无需上划")
        return True

    swipe_home_up()
    logger.info(
        "等待声纳图标出现，超时 %s 秒（阈值 %.2f）...",
        timeout,
        config.SONAR_MATCH_THRESHOLD,
    )
    deadline = time.time() + timeout
    best_score = -1.0
    while time.time() < deadline:
        screenshot = adb.read_screenshot()
        match = _match_sonar(screenshot)
        if match is not None:
            logger.info("已检测到声纳图标: %s score=%.3f", match.center, match.score)
            return True
        # 记录最佳分便于排查
        for path in (config.SONAR_TEMPLATE, config.SONAR_LABEL_TEMPLATE):
            probe = find_template(screenshot, path, threshold=0.01)
            if probe is not None and probe.score > best_score:
                best_score = probe.score
        interruptible_sleep(0.5)

    logger.warning(
        "未找到声纳图标（超时 %s 秒，最佳相似度约 %.3f，阈值 %.2f）",
        timeout,
        best_score,
        config.SONAR_MATCH_THRESHOLD,
    )
    return False


def dismiss_tap_to_start() -> None:
    """点击空白处关掉「点击任意地方开始」遮罩。

    坐标取自 1280x720 下第 1 关截图的开阔海面，避开按钮与网格。
    """
    x, y = config.ACTIVITY_TAP_TO_START_POINT
    logger.info("点击空白处关闭开始提示: (%s, %s)", x, y)
    adb.delay(0.4).click(x, y)
    adb.delay(0.5)


def advance_from_victory_if_present(timeout: float = 0) -> bool:
    """若出现胜利图标，说明当前阶段已完成：点击任意处进入下一阶段。

    timeout > 0 时轮询等待；否则只检查当前一帧。
    上次胜利后直接退游戏时，重进活动仍可能残留胜利界面。
    Returns:
        True 表示检测到胜利并已点击继续；False 表示未出现胜利界面。
    """
    match = None
    if timeout > 0:
        deadline = time.time() + timeout
        while time.time() < deadline:
            match = find_template(adb.read_screenshot(), config.VICTORY_TEMPLATE)
            if match is not None:
                break
            interruptible_sleep(0.3)
    else:
        match = find_template(adb.read_screenshot(), config.VICTORY_TEMPLATE)

    if match is None:
        return False

    x, y = config.ACTIVITY_TAP_TO_START_POINT
    logger.info("检测到胜利界面，点击任意处进入下一阶段: (%s, %s)", x, y)
    adb.delay(0.3).click(x, y)
    adb.delay(1.0)
    # 下一阶段可能再次出现「点击任意地方开始」
    dismiss_tap_to_start()
    return True


def skip_victory_overlay(timeout: float = 0, max_rounds: int = 3) -> bool:
    """关键流程前统一调用：跳过可能出现的胜利画面（每次进活动都可能遇到）。

    可连续处理多轮，避免跳过后立刻又弹出。
    """
    skipped = False
    remaining_timeout = timeout
    for _ in range(max_rounds):
        if not advance_from_victory_if_present(timeout=remaining_timeout):
            break
        skipped = True
        remaining_timeout = 0.5
    return skipped


def wait_activity_detail_ready(timeout: float = 15.0) -> bool:
    """等待进入活动详情：出现退出按钮，或先出现胜利则跳过后再确认。

    胜利遮罩下 quit 模板经常匹配失败，必须同时识别胜利界面。
    """
    logger.info("等待活动详情就绪（退出按钮或胜利界面），超时 %s 秒...", timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        screenshot = adb.read_screenshot()
        if find_template(screenshot, config.VICTORY_TEMPLATE) is not None:
            logger.info("详情等待中检测到胜利界面，先跳过")
            skip_victory_overlay(timeout=0)
            screenshot = adb.read_screenshot()
            if find_template(screenshot, "./template/quit_activity.png") is not None:
                return True
            # 跳过胜利后可能还要等界面稳定
            interruptible_sleep(0.4)
            continue
        if find_template(screenshot, "./template/quit_activity.png") is not None:
            return True
        interruptible_sleep(0.4)
    logger.warning("等待活动详情就绪超时 (%s 秒)", timeout)
    return False


def _finish_activity_detail_entry() -> None:
    """进入活动详情后的收尾：优先处理胜利，否则关掉开始提示。"""
    if not skip_victory_overlay(timeout=config.VICTORY_CHECK_TIMEOUT):
        dismiss_tap_to_start()


def enter_activity(re_enter: bool = False, max_retries: int | None = None) -> None:
    if max_retries is None:
        max_retries = config.ACTIVITY_ENTER_MAX_RETRIES
    if max_retries <= 0:
        raise ValueError(f"max_retries 必须大于 0: {max_retries}")

    last_failure = "进入活动失败"
    for attempt in range(1, max_retries + 1):
        adb.delay(0.5)

        # 从主岛进入：先上划并等声纳出现，确认活动入口已加载
        if not re_enter:
            if not wait_sonar_ready():
                last_failure = "未找到声纳图标"
                logger.warning(
                    "%s，重启游戏并等待 %s 秒 (%s/%s)",
                    last_failure,
                    config.SONAR_NOT_FOUND_RESTART_DELAY,
                    attempt,
                    max_retries,
                )
                _restart_game_for_activity_retry(config.SONAR_NOT_FOUND_RESTART_DELAY)
                continue

        res = wait_until_occur("./template/activity_button.png", timeout=config.ACTIVITY_BUTTON_TIMEOUT)
        if res is None:
            last_failure = "未找到活动按钮"
            logger.warning("%s，无法进入活动界面，正在重试 (%s/%s)", last_failure, attempt, max_retries)
            _restart_game_for_activity_retry()
            continue

        adb.click(*res.center)  # 点击活动按钮进入活动界面
        adb.delay(0.4)

        if not re_enter:
            enable_weak_network(0.2)
            adb.delay(0.4).swipe(1000, 660, 1000, 180)  # 上滑展示全部选项（仅第一次进入需要）
            adb.delay(0.2).swipe(1000, 660, 1000, 180)

        adb.delay(0.7).click(1205, 644)  # 点击进入活动详情界面
        if wait_activity_detail_ready(timeout=config.ACTIVITY_DETAIL_READY_TIMEOUT):
            _finish_activity_detail_entry()
            return

        last_failure = "进入活动详情界面失败"
        logger.warning("%s，正在重试进入活动 (%s/%s)", last_failure, attempt, max_retries)
        _restart_game_for_activity_retry()

    message = f"{last_failure}，已达到最大重试次数 {max_retries}"
    logger.error(message)
    raise RuntimeError(message)

def get_level_grid_size(level: int) -> int:
    if level not in config.LEVEL_GRID_SIZES:
        raise ValueError(f"Level {level} not found in config.LEVEL_GRID_SIZES")
    return config.LEVEL_GRID_SIZES[level]

def get_click_points(level: int, grid_img: np.ndarray) -> tuple[list[tuple[int, int]], np.ndarray]:
    grid_size = get_level_grid_size(level)
    if config.USE_SAVED_POINTS:
        try:
            saved_points = read_saved_points(level, expected_n=grid_size)
            saved_quad = read_saved_quad(level)
        except Exception as exc:
            logger.warning("加载保存坐标失败 level %d: %s", level, exc)
        else:
            if saved_points is not None and saved_quad is not None:
                logger.info("使用已校准的点位坐标 level %d", level)
                return saved_points, saved_quad
            logger.warning("保存的点位不完整 level %d", level)
    grid_result = detect_diamond_centers(grid_img, grid_size)
    logger.info("自动检测到 %d 个点位 level %d", len(grid_result.points), level)
    return grid_result.points, grid_result.global_quad

def _build_cell_polygons(quad: np.ndarray, n: int) -> list[list[np.ndarray]]:
    src = np.array([[0, 0], [n, 0], [n, n], [0, n]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(src, quad.astype(np.float32))
    polygons: list[list[np.ndarray]] = []
    for row in range(n):
        poly_row: list[np.ndarray] = []
        for col in range(n):
            cell = np.array([[[col, row]], [[col + 1, row]], [[col + 1, row + 1]], [[col, row + 1]]], dtype=np.float32)
            projected = cv2.perspectiveTransform(cell, matrix).reshape(4, 2)
            poly_row.append(np.round(projected).astype(np.int32))
        polygons.append(poly_row)
    return polygons

def save_hit_map_image(base_img: np.ndarray, quad: np.ndarray, hit_map: list[list[int]], out_path: str | Path) -> None:
    n = len(hit_map)
    if n == 0 or any(len(row) != n for row in hit_map):
        raise ValueError(f"Hit map is not square or empty: {n}x?")
    out = base_img.copy()
    overlay = out.copy()
    polygons = _build_cell_polygons(quad, n)
    for row in range(n):
        for col in range(n):
            if hit_map[row][col] == 1:
                cv2.fillConvexPoly(overlay, polygons[row][col], (0, 0, 255), lineType=cv2.LINE_AA)
    out = cv2.addWeighted(overlay, 0.38, out, 0.62, 0)
    for row in range(n):
        for col in range(n):
            is_hit = hit_map[row][col] == 1
            cv2.polylines(out, [polygons[row][col]], True,
                          (0, 0, 255) if is_hit else (255, 255, 255),
                          3 if is_hit else 1, cv2.LINE_AA)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    write_image(out_path, out)

def restart_process() -> None:
    """断网重试后恢复网络，再重新进入活动。

    不再盲等固定秒数；enter_activity 会先上划并等待声纳出现。
    """
    disable_weak_network()
    cleanup_reject_network()
    enter_activity()
    skip_victory_overlay()

def _scan_level_by_grid_order(level: int, hit_map: list[list[int]], click_points: list[tuple[int, int]],
                               skip_cells: set[Cell] | None = None) -> None:
    """没有潜艇配置时，按顺序逐格探测。"""
    grid_size = get_level_grid_size(level)
    skip_cells = skip_cells or set()
    for index, point in enumerate(click_points):
        cell = (index // grid_size, index % grid_size)
        if cell in skip_cells:
            continue
        if not _ensure_ammo_before_probe():
            logger.info("弹药耗尽，中止本关剩余逐格探测")
            return
        _probe_cell(level, hit_map, cell, point, index)

def _scan_level_by_strategy(level: int, hit_map: list[list[int]], click_points: list[tuple[int, int]],
                             submarines: list[int]) -> None:
    """使用 SubmarineStrategy 策略优化探测顺序。"""
    grid_size = get_level_grid_size(level)
    strategy = SubmarineStrategy(grid_size, submarines)
    max_attempts = grid_size * grid_size
    attempts = 0
    logger.info("第 %s 关开始探测 (grid=%d, subs=%s)", level, grid_size, submarines)

    while not strategy.done and attempts < max_attempts:
        if not _ensure_ammo_before_probe():
            logger.info("弹药耗尽，中止本关剩余策略探测")
            return
        cell = strategy.choose_next_cell()
        if cell is None:
            break
        row, col = cell
        index = row * grid_size + col
        hit = _probe_cell(level, hit_map, cell, click_points[index], index)
        attempts += 1
        if hit is None:
            continue
        strategy.report_result(cell, hit)

    if strategy.done:
        logger.info("第 %s 关策略已确认全部潜艇，探测次数：%s", level, attempts)
    else:
        if should_stop():
            logger.info("第 %s 关因停止请求不再回退逐格扫描", level)
            return
        logger.warning("第 %s 关策略未能确认全部潜艇，回退逐格扫描未探测方格", level)
        _scan_level_by_grid_order(level, hit_map, click_points, skip_cells=set(strategy.shots))

def _probe_cell(
    level: int,
    hit_map: list[list[int]],
    cell: Cell,
    point: tuple[int, int],
    index: int,
) -> bool | None:
    """执行一次单格探测。
    流程: 确认在活动内 -> 点击前截图 -> 点击目标格 ->
    点击退出 -> 重新进入 -> 点击后截图 -> 判断命中 ->
    断网触发重试 -> 恢复网络。
    返回: True=命中, False=未命中, None=页面异常。
    """
    x, y = point
    skip_victory_overlay()
    if not wait_activity_detail_ready(timeout=config.PROBE_DETAIL_READY_TIMEOUT):
        logger.warning("点击方格前不在活动详情界面，重新进入活动后跳过本次点击")
        enter_activity()
        skip_victory_overlay()
        return None

    before_img = adb.read_screenshot()  # 点击前截图
    adb.click(x, y)
    adb.delay(0.3)
    if not click_template("./template/quit_activity.png"):
        logger.warning("点击方格后未找到退出按钮，当前页面可能已离开活动详情界面")
        enter_activity()
        skip_victory_overlay()
        return None

    enter_activity(re_enter=True)  # 重新进入活动界面
    skip_victory_overlay()
    after_img = adb.delay(1).read_screenshot()  # 点击后截图

    if is_diamond_hit(before_img, after_img, (x, y)):
        row, col = cell
        hit_map[row][col] = 1
        logger.info("第 %s 关，点击方格 %s 结果：击中！", level, index)
        hit = True
    else:
        logger.info("第 %s 关，点击方格 %s 结果：未击中", level, index)
        hit = False

    # 断网 -> 等重试按钮 -> 点击重试 -> 恢复网络
    adb.enable_reject_network(config.GAME_PACKAGE_NAME)
    retry = wait_until_occur("./template/retry.png", timeout=config.RETRY_BUTTON_TIMEOUT)
    adb.disable_reject_network(config.GAME_PACKAGE_NAME)
    adb.delay(0.8).click(*retry.center)
    adb.disable_weak_network(config.GAME_PACKAGE_NAME)
    
    restart_process()
    skip_victory_overlay()
    return hit

def handle_game_level(level: int, hit_map: list[list[int]]) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
    skip_victory_overlay()
    adb.delay(1.5)
    skip_victory_overlay()
    grid_img = adb.read_screenshot()
    click_points, grid_quad = get_click_points(level, grid_img)
    submarines = get_configured_submarines(level, config.SUBMARINES)

    # 上一关统一点击命中格前会关闭弱网；新关开始探测前必须重新开启，
    # 否则首个未命中点击会真实消耗一颗弹药。
    logger.info("第 %s 关探测前开启弱网保护", level)
    enable_weak_network(0.2)

    if submarines is None:
        logger.warning("没有潜艇配置，按顺序逐格扫描 level %d", level)
        _scan_level_by_grid_order(level, hit_map, click_points)
    else:
        _scan_level_by_strategy(level, hit_map, click_points, submarines)

    return grid_img, grid_quad, click_points


def _find_connected_components(hit_map):
    """BFS找命中格的连通分量"""
    n = len(hit_map)
    visited = [[False] * n for _ in range(n)]
    components = []
    for row in range(n):
        for col in range(n):
            if hit_map[row][col] == 1 and not visited[row][col]:
                component = []
                queue = [(row, col)]
                visited[row][col] = True
                while queue:
                    r, c = queue.pop(0)
                    component.append((r, c))
                    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < n and 0 <= nc < n and hit_map[nr][nc] == 1 and not visited[nr][nc]:
                            visited[nr][nc] = True
                            queue.append((nr, nc))
                components.append(component)
    logger.info("Found %d connected components", len(components))
    return components


def _ammo_is_empty() -> bool:
    """读取蓝弹药数量；为 0 返回 True。识别失败时不停止，继续跑。"""
    ammo = read_blue_ammo_count(adb.read_screenshot())
    if ammo is None:
        logger.warning(
            "弹药数量识别失败，继续运行（调试图见 %s）",
            config.AMMO_DETECT_DEBUG_DIR,
        )
        return False
    logger.info("当前蓝弹药数量: %d", ammo)
    return ammo == 0


def _ensure_ammo_before_probe() -> bool:
    """每格探测前检查蓝弹药；为 0 则领奖励，仍为 0 则请求停止并返回 False。"""
    if should_stop():
        return False
    if not _ammo_is_empty():
        return True

    logger.warning("探测过程中蓝弹药为 0，尝试领取活动奖励...")
    if _try_refill_or_stop(0):
        request_stop()
        return False
    logger.info("探测中已补充弹药，继续本关")
    return True


def _try_refill_or_stop(round_index: int) -> bool:
    """弹药为 0 时尝试领取活动奖励；仍为 0 则应停止。

    Returns:
        True = 应当停止主循环；False = 已补充弹药（或识别失败），继续跑。
    """
    if not config.CLAIM_REWARDS_WHEN_AMMO_EMPTY:
        logger.info("蓝弹药为 0，停止脚本（已完成 %d 轮）", round_index)
        return True

    logger.info("蓝弹药为 0，尝试领取活动奖励补充弹药...")
    disable_weak_network(0.2)
    skip_victory_overlay()
    opened = refill_ammo_from_rewards(adb)
    if not opened:
        logger.info("无法打开活动奖励，停止脚本（已完成 %d 轮）", round_index)
        return True

    if _ammo_is_empty():
        logger.info("领取后仍无蓝弹药，真正耗尽，停止脚本（已完成 %d 轮）", round_index)
        return True

    logger.info("已从活动奖励补充弹药，继续运行")
    return False


def _play_one_level(level: int) -> None:
    """完成单关：探测命中 → 点命中格 → 等待胜利进入下一阶段。"""
    grid_size = get_level_grid_size(level)
    hit_map = [[0 for _ in range(grid_size)] for _ in range(grid_size)]
    base_img, quad, click_points = handle_game_level(level, hit_map)
    out_path = config.OUTPUT_DIR / f"hit_map_level_{level}.png"
    save_hit_map_image(base_img, quad, hit_map, out_path)
    logger.info("命中矩阵：%s", hit_map)
    logger.info("命中可视化图片已保存：%s", out_path)

    total_hits = sum(sum(row) for row in hit_map)
    if total_hits == 0:
        logger.info("没有命中格，无需点击")
        return

    logger.info("共 %d 个命中格，开始点击命中格子...", total_hits)
    disable_weak_network(0.2)
    skip_victory_overlay()
    for row in range(grid_size):
        for col in range(grid_size):
            if hit_map[row][col] != 1:
                continue
            skip_victory_overlay()
            index = row * grid_size + col
            x, y = click_points[index]
            logger.warning("点击命中格 row=%d col=%d index=%d (%d, %d)", row, col, index, x, y)
            adb.click(x, y)
            adb.delay(config.HIT_CLICK_INTERVAL)
    logger.info("命中格点击完成，共 %d 个", total_hits)

    if skip_victory_overlay(timeout=config.VICTORY_WAIT_TIMEOUT):
        logger.info("本阶段胜利，已进入下一阶段")


def ensure_game_started() -> None:
    """脚本启动时确保游戏在跑：未启动则启动，已启动则重启。"""
    logger.info("脚本启动：强制重启游戏（未运行则启动）...")
    _restart_game_for_activity_retry()


def prepare_level_detection() -> None:
    """在截图识别关卡前处理延迟出现的胜利界面，并等待新标题稳定。"""
    logger.info(
        "识别关卡前检查延迟胜利界面，等待 %.1f 秒...",
        config.LEVEL_PRE_DETECT_VICTORY_TIMEOUT,
    )
    if skip_victory_overlay(timeout=config.LEVEL_PRE_DETECT_VICTORY_TIMEOUT):
        logger.info(
            "已跳过延迟胜利界面，等待新关卡稳定 %.1f 秒...",
            config.LEVEL_AFTER_VICTORY_DELAY,
        )
        wait_activity_detail_ready(timeout=config.ACTIVITY_DETAIL_READY_TIMEOUT)
        adb.delay(config.LEVEL_AFTER_VICTORY_DELAY)


def main(level: int | None = None):
    disable_weak_network()

    ensure_game_started()
    enter_activity()
    skip_victory_overlay()

    manual_level = level
    round_index = 0
    while True:
        if should_stop():
            logger.info("收到停止请求，退出主循环（已完成 %d 轮）", round_index)
            break

        round_index += 1
        skip_victory_overlay()

        # 开局 / 每关开始前检查弹药；为 0 则先领奖励，仍为 0 才停
        if _ammo_is_empty():
            if _try_refill_or_stop(round_index - 1):
                break
            continue

        # 必须紧贴关卡截图执行，防止识别旧关卡后胜利界面才延迟出现。
        prepare_level_detection()

        if manual_level is not None and round_index == 1:
            current_level = manual_level
            logger.info("使用手动指定关卡: %d", current_level)
        else:
            current_level = detect_activity_level(adb.read_screenshot())
            logger.info("第 %d 轮自动识别关卡: %d", round_index, current_level)

        logger.info("========== 开始第 %d 轮：第 %d 关 ==========", round_index, current_level)
        _play_one_level(current_level)

        if should_stop():
            logger.info("收到停止请求，退出主循环（已完成 %d 轮）", round_index)
            break

        # 关卡结束后再读弹药；为 0 先领奖励
        if _ammo_is_empty():
            if _try_refill_or_stop(round_index):
                break
            continue
        logger.info("弹药仍有剩余，继续下一关...")


if __name__ == "__main__":
    register_exit_cleanup()
    mark_run_start()
    try:
        from utils.user_settings import apply_settings

        settings = apply_settings()
        configure_adb(config.ADB_SERIAL)

        # 有参数则手动指定关卡；否则读 settings，再否则自动识别
        if len(sys.argv) >= 2:
            level = int(sys.argv[1])
            logger.info("命令行指定关卡: %d", level)
        elif settings.get("manual_level") is not None:
            level = int(settings["manual_level"])
            logger.info("配置指定关卡: %d", level)
        else:
            level = None
            logger.info("未指定关卡，将在进入活动后自动识别")

        adb.ensure_root_shell()
        cleanup_reject_network("主流程启动")
        main(level)
    finally:
        logger.info("脚本结束，总运行时间 %s", get_run_elapsed_text())
        cleanup_weak_network("主流程结束")
        cleanup_reject_network("主流程结束")
