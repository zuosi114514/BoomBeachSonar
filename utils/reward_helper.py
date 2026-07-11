"""活动奖励领取：左下角潜艇入口 → 点击可领取的蓝炮弹 / 黄金币。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import config
from utils.image_match import find_template
from utils.logger import get_logger

logger = get_logger(__name__)

REWARD_TITLE_TEMPLATE = "./template/reward_title.png"
REWARD_CLOSE_TEMPLATE = "./template/reward_close.png"
SUB_REWARD_BTN_TEMPLATE = "./template/sub_reward_btn.png"


def _save_reward_debug(screenshot: np.ndarray, tag: str, marked: np.ndarray | None = None) -> None:
    out_dir = config.SCREENSHOT_DIR / "reward_claim"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cv2.imwrite(str(out_dir / f"{stamp}_{tag}.png"), screenshot)
    if marked is not None:
        cv2.imwrite(str(out_dir / f"{stamp}_{tag}_marked.png"), marked)
    cv2.imwrite(str(out_dir / f"latest_{tag}.png"), screenshot)
    if marked is not None:
        cv2.imwrite(str(out_dir / f"latest_{tag}_marked.png"), marked)


def find_claimable_reward_points(screenshot: np.ndarray) -> list[tuple[int, int]]:
    """在活动奖励弹窗内，用青色高亮框找出可领取奖励中心点。"""
    h, w = screenshot.shape[:2]
    x1 = int(w * getattr(config, "REWARD_PANEL_X1_PCT", 0.23))
    y1 = int(h * getattr(config, "REWARD_PANEL_Y1_PCT", 0.20))
    x2 = int(w * getattr(config, "REWARD_PANEL_X2_PCT", 0.77))
    y2 = int(h * getattr(config, "REWARD_PANEL_Y2_PCT", 0.82))

    hsv = cv2.cvtColor(screenshot, cv2.COLOR_BGR2HSV)
    # 可领取奖励外圈青色/蓝色高光
    glow = cv2.inRange(hsv, np.array([85, 60, 140]), np.array([115, 255, 255]))
    roi = glow[y1:y2, x1:x2]
    kernel = np.ones((3, 3), np.uint8)
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    points: list[tuple[int, int]] = []
    marked = screenshot.copy()
    cv2.rectangle(marked, (x1, y1), (x2, y2), (255, 255, 0), 1)

    for contour in contours:
        area = cv2.contourArea(contour)
        rx, ry, rw, rh = cv2.boundingRect(contour)
        abs_x, abs_y = rx + x1, ry + y1
        # 过滤标题装饰等过大区域，只保留单个奖励格大小
        if not (800 < area < 12000 and 40 < rw < 120 and 40 < rh < 120):
            continue
        cx, cy = abs_x + rw // 2, abs_y + rh // 2
        points.append((cx, cy))
        cv2.rectangle(marked, (abs_x, abs_y), (abs_x + rw, abs_y + rh), (0, 255, 0), 2)
        cv2.circle(marked, (cx, cy), 4, (0, 0, 255), -1)

    # 去重：过近的点合并
    unique: list[tuple[int, int]] = []
    for px, py in sorted(points, key=lambda p: (p[1], p[0])):
        if any(abs(px - ux) < 25 and abs(py - uy) < 25 for ux, uy in unique):
            continue
        unique.append((px, py))

    _save_reward_debug(screenshot, "claimable", marked)
    logger.info("检测到可领取奖励 %d 个: %s", len(unique), unique)
    return unique


def find_reward_icon_points(screenshot: np.ndarray) -> list[tuple[int, int, str]]:
    """在奖励弹窗内找出蓝色炮弹与黄色金币图标中心（含尚未高亮的）。"""
    h, w = screenshot.shape[:2]
    x1, y1 = int(w * 0.23), int(h * 0.20)
    x2, y2 = int(w * 0.77), int(h * 0.82)
    hsv = cv2.cvtColor(screenshot, cv2.COLOR_BGR2HSV)

    blue = cv2.inRange(hsv, np.array([95, 120, 120]), np.array([115, 255, 255]))
    gold = cv2.inRange(hsv, np.array([15, 100, 120]), np.array([35, 255, 255]))
    blue[:y1, :] = 0
    blue[y2:, :] = 0
    blue[:, :x1] = 0
    blue[:, x2:] = 0
    gold[:y1, :] = 0
    gold[y2:, :] = 0
    gold[:, :x1] = 0
    gold[:, x2:] = 0

    results: list[tuple[int, int, str]] = []
    for name, mask, min_area in (("blue", blue, 300), ("gold", gold, 400)):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(contour)
            if not (25 <= bw <= 100 and 25 <= bh <= 100):
                continue
            results.append((x + bw // 2, y + bh // 2, name))

    results.sort(key=lambda t: (t[1], t[0]))
    return results


def is_reward_panel_open(screenshot: np.ndarray) -> bool:
    return find_template(screenshot, REWARD_TITLE_TEMPLATE, threshold=0.75) is not None


def open_reward_panel(adb) -> bool:
    """点击左下角潜艇进度条，打开活动奖励。"""
    screenshot = adb.read_screenshot()
    match = find_template(screenshot, SUB_REWARD_BTN_TEMPLATE, threshold=0.75)
    if match is not None:
        x, y = match.center
    else:
        x, y = config.SUB_REWARD_BUTTON_POINT
        logger.warning("未匹配到潜艇奖励按钮模板，使用固定坐标 (%s, %s)", x, y)

    logger.info("点击左下角潜艇奖励入口: (%s, %s)", x, y)
    adb.delay(0.3).click(x, y)
    adb.delay(1.0)

    for _ in range(10):
        shot = adb.read_screenshot()
        if is_reward_panel_open(shot):
            _save_reward_debug(shot, "panel_open")
            logger.info("活动奖励界面已打开")
            return True
        adb.delay(0.4)
    logger.warning("点击潜艇后未出现活动奖励界面")
    _save_reward_debug(adb.read_screenshot(), "panel_open_fail")
    return False


def close_reward_panel(adb) -> None:
    """关闭活动奖励弹窗。"""
    screenshot = adb.read_screenshot()
    match = find_template(screenshot, REWARD_CLOSE_TEMPLATE, threshold=0.75)
    if match is not None:
        x, y = match.center
    else:
        x, y = config.REWARD_CLOSE_POINT
        logger.warning("未匹配到奖励关闭按钮，使用固定坐标 (%s, %s)", x, y)
    logger.info("关闭活动奖励: (%s, %s)", x, y)
    adb.delay(0.2).click(x, y)
    adb.delay(0.8)


def claim_visible_rewards(adb, max_rounds: int | None = None) -> int:
    """反复点击可领取高亮奖励（蓝炮弹/黄金币），返回点击次数。"""
    max_rounds = max_rounds if max_rounds is not None else config.REWARD_CLAIM_MAX_ROUNDS
    clicks = 0
    for round_index in range(1, max_rounds + 1):
        screenshot = adb.read_screenshot()
        if not is_reward_panel_open(screenshot):
            logger.warning("奖励界面已关闭，停止领取 round=%d", round_index)
            break

        points = find_claimable_reward_points(screenshot)
        if not points:
            logger.info("没有更多可领取奖励")
            break

        for x, y in points:
            logger.info("领取奖励 #%d at (%d, %d)", clicks + 1, x, y)
            adb.click(x, y)
            clicks += 1
            adb.delay(0.7)
        adb.delay(0.4)

    logger.info("本轮共点击领取 %d 次", clicks)
    return clicks


def refill_ammo_from_rewards(adb) -> bool:
    """弹药用尽时：打开活动奖励并领取蓝炮弹/黄金币。

    Returns:
        True 表示至少成功打开界面并尝试领取；False 表示入口失败。
    """
    logger.info("尝试从活动奖励补充弹药...")
    if not open_reward_panel(adb):
        return False
    claimed = claim_visible_rewards(adb)
    close_reward_panel(adb)
    logger.info("活动奖励流程结束，领取点击 %d 次", claimed)
    return True
