"""
OCR 关卡数字识别模块

使用 EasyOCR 从游戏截图中识别关卡数字，
替代原有的根据菱形网格大小推断关卡的方式。

使用方式:
    from utils.ocr_helper import ocr_level_number
    level = ocr_level_number(screenshot)
    if level is not None:
        print(f"识别到第 {level} 关")
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import (
    AMMO_DETECT_DEBUG_DIR,
    AMMO_OCR_UPSCALE,
    AMMO_ROI,
    DEFAULT_DETECTED_LEVEL,
    LEVEL_DETECT_DEBUG_DIR,
    LEVEL_DETECT_ENABLED,
    LEVEL_MATCH_MIN_MARGIN,
    LEVEL_MATCH_ROI,
    LEVEL_MATCH_THRESHOLD,
    LEVEL_REF_DIR,
    LEVEL_TEXT_BINARY_THRESHOLD,
    OCR_LANGUAGE,
    OCR_LABEL_BLACKLIST,
    OCR_ROI,
    SCREENSHOT_DIR,
)
import config as config_module
import warnings
warnings.filterwarnings("ignore", message=".*pin_memory.*")

from utils.logger import get_logger

logger = get_logger(__name__)

# EasyOCR reader 实例（懒加载，只初始化一次）
_reader = None


def _patch_easyocr_mirror():
    """将 EasyOCR 模型下载地址替换为 ghproxy.com 国内镜像。"""
    import easyocr
    original = easyocr.utils.download_and_unzip

    def _mirror_download(url, *args, **kwargs):
        mirrored = url.replace(
            "https://github.com/JaidedAI/EasyOCR/releases/download",
            "https://mirror.ghproxy.com/https://github.com/JaidedAI/EasyOCR/releases/download",
        )
        logger.info("EasyOCR 通过镜像下载: %s", mirrored.rsplit("/", 1)[-1])
        return original(mirrored, *args, **kwargs)

    easyocr.utils.download_and_unzip = _mirror_download


def _get_reader() -> object:
    """获取 EasyOCR Reader 单例，延迟初始化以加速模块导入。"""
    global _reader
    if _reader is None:
        logger.info("正在初始化 EasyOCR（首次运行会下载模型，请稍候）...")
        import easyocr
        _patch_easyocr_mirror()
        _reader = easyocr.Reader(
            OCR_LANGUAGE,
            gpu=False,
            verbose=False,
        )
        logger.info("EasyOCR 初始化完成")
    return _reader


def _extract_roi(screenshot: np.ndarray) -> np.ndarray:
    """从截图中裁剪出关卡数字所在的感兴趣区域（ROI）。
    
    Args:
        screenshot: OpenCV 图像 (H, W, 3)
    
    Returns:
        裁剪后的 ROI 图像区域
    """
    h, w = screenshot.shape[:2]
    
    # ROI 使用相对坐标（百分比），以适应不同分辨率的屏幕
    x1 = int(w * OCR_ROI["x1_pct"])
    y1 = int(h * OCR_ROI["y1_pct"])
    x2 = int(w * OCR_ROI["x2_pct"])
    y2 = int(h * OCR_ROI["y2_pct"])
    
    # 边界保护
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)
    
    roi = screenshot[y1:y2, x1:x2]
    logger.debug("OCR ROI: (%d,%d)-(%d,%d), size=%s", x1, y1, x2, y2, roi.shape)
    return roi


def _extract_number_from_text(text: str) -> Optional[int]:
    """从 OCR 识别文本中提取数字，过滤掉标签文字。
    
    例如 "关卡12" -> 12, "Level5" -> 5, "12" -> 12
    
    Args:
        text: OCR 识别出的原始文本
    
    Returns:
        提取出的数字，或 None（若无有效数字）
    """
    # 去掉黑名单标签文本（如 "关卡", "Level" 等）
    cleaned = text.strip()
    for label in OCR_LABEL_BLACKLIST:
        cleaned = cleaned.replace(label, "")
    
    # 提取数字
    digits = ""
    for ch in cleaned:
        if ch.isdigit():
            digits += ch
    
    if not digits:
        return None
    from config import MAX_LEVEL
    
    # 优先尝试完整数字
    full_number = int(digits)
    if 1 <= full_number <= MAX_LEVEL:
        return full_number
    
    # 若完整数字超出范围，尝试子字符串提取（处理 EasyOCR 乱码问题）
    # 例如 "15i19" 中的子序列 "1" 或 "15"
    candidates = set()
    for i in range(len(digits)):
        for j in range(i + 1, min(i + 3, len(digits) + 1)):
            try:
                n = int(digits[i:j])
                if 1 <= n <= MAX_LEVEL:
                    candidates.add(n)
            except ValueError:
                pass
    
    if candidates:
        return min(candidates, key=lambda x: (len(str(x)), x))
    
    return None


def _level_match_roi_box(image: np.ndarray) -> tuple[int, int, int, int]:
    """按 LEVEL_MATCH_ROI 百分比计算标题带像素坐标。"""
    h, w = image.shape[:2]
    x1 = max(0, int(w * LEVEL_MATCH_ROI["x1_pct"]))
    y1 = max(0, int(h * LEVEL_MATCH_ROI["y1_pct"]))
    x2 = min(w, int(w * LEVEL_MATCH_ROI["x2_pct"]))
    y2 = min(h, int(h * LEVEL_MATCH_ROI["y2_pct"]))
    return x1, y1, x2, y2


def _title_text_mask(bgr_roi: np.ndarray) -> np.ndarray:
    """提取「N号海域」白色标题文字掩膜，开运算去海浪噪点（不用闭运算，避免粘连「号」）。"""
    gray = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, LEVEL_TEXT_BINARY_THRESHOLD, 255, cv2.THRESH_BINARY)
    kernel = np.ones((2, 2), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)


def _trim_mask(mask: np.ndarray | None) -> np.ndarray | None:
    """去掉掩膜四周空白，只保留有白像素的紧致外框。"""
    if mask is None or mask.size == 0:
        return None
    cols = np.where(mask.max(axis=0) > 0)[0]
    rows = np.where(mask.max(axis=1) > 0)[0]
    if len(cols) == 0 or len(rows) == 0:
        return None
    return mask[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]


def _find_char_segments(mask: np.ndarray) -> list[tuple[int, int]]:
    """按列投影切分字符段；仅合并 1px 间隙，过滤过窄噪点。"""
    col_sum = (mask > 0).sum(axis=0)
    active = col_sum > 0
    raw: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            raw.append((start, index))
            start = None
    if start is not None:
        raw.append((start, len(active)))

    merged: list[tuple[int, int]] = []
    for seg_start, seg_end in raw:
        if merged and seg_start - merged[-1][1] <= 1:
            merged[-1] = (merged[-1][0], seg_end)
        else:
            merged.append((seg_start, seg_end))

    return [(s, e) for s, e in merged if e - s >= 4]


# 「号/海/域」等汉字段宽度约 40+，数字段通常 < 30
_DIGIT_SEGMENT_MAX_WIDTH = 34
# 斜体数字（如 7）易与「号」粘连；在此宽度范围内找列投影低谷切开
_DIGIT_SPLIT_MIN_WIDTH = 8
_DIGIT_SPLIT_MAX_WIDTH = 30


def _split_glued_digit_segment(mask: np.ndarray, seg_start: int, seg_end: int) -> tuple[int, int] | None:
    """宽段若是「数字+号」粘连，按列投影低谷切出左侧数字。"""
    width = seg_end - seg_start
    if width <= _DIGIT_SEGMENT_MAX_WIDTH:
        return seg_start, seg_end

    col_sum = (mask[:, seg_start:seg_end] > 0).sum(axis=0)
    search_lo = _DIGIT_SPLIT_MIN_WIDTH
    search_hi = min(_DIGIT_SPLIT_MAX_WIDTH, width - 8)
    if search_hi <= search_lo:
        return None

    best_i = None
    best_val = 10**9
    for i in range(search_lo, search_hi + 1):
        val = int(col_sum[i])
        # 局部低谷，且明显低于两侧
        left = int(col_sum[i - 1]) if i > 0 else val
        right = int(col_sum[i + 1]) if i + 1 < width else val
        if val <= left and val <= right and val < best_val:
            best_val = val
            best_i = i

    if best_i is None or best_val > 10:
        return None
    return seg_start, seg_start + best_i


def _extract_digit_mask(image: np.ndarray, digit_count: int | None = None) -> np.ndarray | None:
    """从标题带裁出关卡数字掩膜（遇到「号」等宽字符段即停止）。

    digit_count:
      - None: 自动取「号」前全部数字段
      - 1/2: 最多取前 N 个数字段（兼容旧调用）
    """
    x1, y1, x2, y2 = _level_match_roi_box(image)
    if x2 <= x1 or y2 <= y1:
        return None

    crop = image[y1:y2, x1:x2]
    mask = _title_text_mask(crop)
    trimmed = _trim_mask(mask)
    if trimmed is None:
        return None

    segments = _find_char_segments(trimmed)
    if not segments:
        return None

    digit_segs: list[tuple[int, int]] = []
    for seg_start, seg_end in segments:
        width = seg_end - seg_start
        if width > _DIGIT_SEGMENT_MAX_WIDTH:
            # 斜体 7 等会与「号」粘成一段，尝试切开左侧数字
            if not digit_segs:
                split = _split_glued_digit_segment(trimmed, seg_start, seg_end)
                if split is not None:
                    digit_segs.append(split)
            break
        digit_segs.append((seg_start, seg_end))
        if digit_count is not None and len(digit_segs) >= digit_count:
            break

    if not digit_segs:
        return None

    left = digit_segs[0][0]
    right = digit_segs[-1][1]
    return _trim_mask(trimmed[:, left:right])


def _count_title_digits(image: np.ndarray) -> int:
    """统计标题中「号」之前的数字字符段数量。"""
    x1, y1, x2, y2 = _level_match_roi_box(image)
    crop = image[y1:y2, x1:x2]
    trimmed = _trim_mask(_title_text_mask(crop))
    if trimmed is None:
        return 0
    count = 0
    for seg_start, seg_end in _find_char_segments(trimmed):
        width = seg_end - seg_start
        if width > _DIGIT_SEGMENT_MAX_WIDTH:
            if count == 0 and _split_glued_digit_segment(trimmed, seg_start, seg_end) is not None:
                return 1
            break
        count += 1
    return count


def _score_digit_masks(query: np.ndarray, ref: np.ndarray) -> float:
    """去边后归一化到固定尺寸再比对，消除上下错位影响。"""
    query_t = _trim_mask(query)
    ref_t = _trim_mask(ref)
    if query_t is None or ref_t is None:
        return -1.0

    target_w, target_h = 40, 48
    query_n = cv2.resize(query_t, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
    ref_n = cv2.resize(ref_t, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
    return float(
        cv2.matchTemplate(
            query_n.astype(np.float32),
            ref_n.astype(np.float32),
            cv2.TM_CCOEFF_NORMED,
        )[0, 0]
    )


def _iter_unique_level_refs() -> list[tuple[int, Path]]:
    """枚举参考图；跳过与已有关卡完全相同的重复文件（如 15-36 复制图）。"""
    if not LEVEL_REF_DIR.exists():
        return []

    seen_hashes: set[int] = set()
    refs: list[tuple[int, Path]] = []
    paths = sorted(
        LEVEL_REF_DIR.glob("*.png"),
        key=lambda p: int(p.stem) if p.stem.isdigit() else 10**9,
    )
    for path in paths:
        if not path.stem.isdigit():
            continue
        level = int(path.stem)
        file_hash = hash(path.read_bytes())
        if file_hash in seen_hashes:
            continue
        seen_hashes.add(file_hash)
        refs.append((level, path))
    return refs


def _save_level_match_debug(
    screenshot: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    query_by_digits: dict[int | str, np.ndarray | None],
    scores: list[tuple[float, int]] | None = None,
    result_level: int | None = None,
) -> Path:
    """保存本次关卡识别的全部中间图，供人工 debug。

    输出目录: _debug/screenshots/level_detect/
    """
    out_dir = LEVEL_DETECT_DEBUG_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_dir = out_dir / "ref_digits"
    ref_dir.mkdir(parents=True, exist_ok=True)

    roi = screenshot[y1:y2, x1:x2]
    title_mask = _title_text_mask(roi)

    cv2.imwrite(str(out_dir / "00_full_screenshot.png"), screenshot)
    cv2.imwrite(str(out_dir / "01_title_roi.png"), roi)
    cv2.imwrite(str(out_dir / "02_title_mask.png"), title_mask)

    marked = screenshot.copy()
    cv2.rectangle(marked, (x1, y1), (x2, y2), (0, 255, 0), 2)
    label = f"ROI + result={result_level}" if result_level is not None else "Level Title ROI"
    cv2.putText(
        marked,
        label,
        (x1, max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2,
    )
    cv2.imwrite(str(out_dir / "03_full_marked.png"), marked)

    for key, digit_mask in query_by_digits.items():
        if digit_mask is None:
            continue
        cv2.imwrite(str(out_dir / f"04_query_digit_{key}.png"), digit_mask)
        scaled = cv2.resize(
            digit_mask,
            (digit_mask.shape[1] * 4, digit_mask.shape[0] * 4),
            interpolation=cv2.INTER_NEAREST,
        )
        cv2.imwrite(str(out_dir / f"04_query_digit_{key}_x4.png"), scaled)

    for level, ref_path in _iter_unique_level_refs():
        ref = cv2.imread(str(ref_path))
        if ref is None:
            continue
        ref_digit = _extract_digit_mask(ref)
        if ref_digit is None:
            continue
        cv2.imwrite(str(ref_dir / f"ref_{level:02d}_digit.png"), ref_digit)
        scaled = cv2.resize(
            ref_digit,
            (ref_digit.shape[1] * 4, ref_digit.shape[0] * 4),
            interpolation=cv2.INTER_NEAREST,
        )
        cv2.imwrite(str(ref_dir / f"ref_{level:02d}_digit_x4.png"), scaled)

    score_path = out_dir / "05_scores.txt"
    lines = [
        f"result_level={result_level}",
        f"roi=({x1},{y1})-({x2},{y2})",
        f"threshold={LEVEL_MATCH_THRESHOLD}",
        f"min_margin={LEVEL_MATCH_MIN_MARGIN}",
        "",
        "rank score level",
    ]
    if scores:
        for rank, (score, level) in enumerate(sorted(scores, reverse=True), start=1):
            lines.append(f"{rank:4d} {score:7.3f} {level}")
    score_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(SCREENSHOT_DIR / "tmpl_roi_debug.png"), roi)
    cv2.imwrite(str(SCREENSHOT_DIR / "tmpl_roi_mask.png"), title_mask)
    cv2.imwrite(str(SCREENSHOT_DIR / "tmpl_roi_marked.png"), marked)
    digit1 = query_by_digits.get("auto")
    if digit1 is None:
        digit1 = query_by_digits.get(1)
    if digit1 is not None:
        cv2.imwrite(str(SCREENSHOT_DIR / "tmpl_digit_mask.png"), digit1)

    logger.info("关卡识别调试图已保存: %s", out_dir)
    return out_dir


def match_level_by_template(screenshot: np.ndarray) -> int:
    """对比标题数字掩膜与 save_points/imgs 参考图，识别关卡号。

    只匹配「N号海域」中的数字，忽略倒计时和海浪背景。
    未匹配或异常时返回 DEFAULT_DETECTED_LEVEL（默认第 10 关）。
    """
    if not LEVEL_DETECT_ENABLED:
        logger.info("关卡模板匹配未启用，默认第 %d 关", DEFAULT_DETECTED_LEVEL)
        return DEFAULT_DETECTED_LEVEL

    try:
        refs = _iter_unique_level_refs()
        if not refs:
            logger.warning("无可用参考图，默认第 %d 关", DEFAULT_DETECTED_LEVEL)
            return DEFAULT_DETECTED_LEVEL

        x1, y1, x2, y2 = _level_match_roi_box(screenshot)
        if x2 <= x1 or y2 <= y1:
            logger.warning("关卡匹配 ROI 无效，默认第 %d 关", DEFAULT_DETECTED_LEVEL)
            return DEFAULT_DETECTED_LEVEL

        query_digit_count = _count_title_digits(screenshot)
        query_digit = _extract_digit_mask(screenshot)
        query_by_digits = {
            "auto": query_digit,
            query_digit_count: query_digit,
        }

        if query_digit is None or query_digit_count <= 0:
            _save_level_match_debug(screenshot, x1, y1, x2, y2, query_by_digits)
            logger.info("标题区未提取到数字掩膜，默认第 %d 关", DEFAULT_DETECTED_LEVEL)
            return DEFAULT_DETECTED_LEVEL

        scores: list[tuple[float, int]] = []
        best_lvl: int | None = None
        best_score = -1.0
        second_score = -1.0

        for level, ref_path in refs:
            # 位数不一致直接跳过，避免「11」与「1」同分
            if len(str(level)) != query_digit_count:
                continue
            ref = cv2.imread(str(ref_path))
            if ref is None:
                continue
            ref_digit = _extract_digit_mask(ref)
            score = _score_digit_masks(query_digit, ref_digit)
            scores.append((score, level))
            if score > best_score:
                second_score = best_score
                best_score = score
                best_lvl = level
            elif score > second_score:
                second_score = score

        margin = best_score - second_score
        # 高置信度下允许并列第一（参考图数字掩膜重复时，如 13/14）
        confident = best_lvl is not None and best_score >= LEVEL_MATCH_THRESHOLD and (
            margin >= LEVEL_MATCH_MIN_MARGIN or best_score >= 0.999
        )
        if confident:
            result = best_lvl
            logger.info(
                "模板匹配识别到关卡: %d (相似度: %.3f, 分差: %.3f)",
                best_lvl,
                best_score,
                margin,
            )
        else:
            result = DEFAULT_DETECTED_LEVEL
            logger.info(
                "模板未匹配到已知关卡，默认第 %d 关 (best=%s score=%.3f margin=%.3f)",
                DEFAULT_DETECTED_LEVEL,
                best_lvl,
                best_score,
                margin,
            )

        _save_level_match_debug(
            screenshot,
            x1,
            y1,
            x2,
            y2,
            query_by_digits,
            scores=scores,
            result_level=result,
        )
        return result
    except Exception as exc:
        logger.warning("模板匹配失败: %s，默认第 %d 关", exc, DEFAULT_DETECTED_LEVEL)
        return DEFAULT_DETECTED_LEVEL


def detect_activity_level(screenshot: np.ndarray) -> int:
    """进入活动后识别当前关卡；失败时返回默认关卡。"""
    return match_level_by_template(screenshot)


def ocr_level_number(screenshot: np.ndarray) -> Optional[int]:
    """从截图中使用 OCR 识别关卡数字。
    
    流程：
    1. 裁剪 ROI 区域
    2. 使用 EasyOCR 识别文字
    3. 从结果中提取数字
    4. 校验数字范围
    
    Args:
        screenshot: OpenCV 图像 (H, W, 3)，BGR 格式
    
    Returns:
        关卡数字 (1~99)，识别失败返回 None
    """
    if not config_module.OCR_ENABLED:
        logger.debug("OCR 功能未启用")
        return None
    
    try:
        # 裁剪 ROI
        roi = _extract_roi(screenshot)
        
        if roi.size == 0:
            logger.warning("OCR ROI 为空，无法识别")
            return None
        
        # 转为 RGB（EasyOCR 需要 RGB）
        roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        
        # EasyOCR 识别
        reader = _get_reader()
        results = reader.readtext(roi_rgb, allowlist="0123456789")
        
        if not results:
            logger.debug("OCR 未识别到任何文字")
            return None
        
        # 调试日志：打印所有识别结果
        for bbox, text, conf in results:
            logger.debug("OCR 识别: text=%r conf=%.3f", text, conf)
        
        # 从识别结果中提取数字（优先用高置信度的）
        candidates = []
        for bbox, text, conf in results:
            number = _extract_number_from_text(text)
            if number is not None and 1 <= number <= 99:
                candidates.append((conf, number))
        
        if not candidates:
            logger.debug("OCR 未识别到有效数字")
            return None
        
        # 按置信度排序，取最高
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_conf, best_number = candidates[0]
        
        logger.info("OCR 识别到关卡数字: %d (置信度: %.3f)", best_number, best_conf)
        return best_number
        
    except ImportError:
        logger.warning("EasyOCR 未安装，请执行: pip install easyocr")
        return None
    except Exception as exc:
        logger.warning("OCR 识别失败: %s", exc, exc_info=True)
        return None


def ocr_level_number_from_path(image_path: str | Path) -> Optional[int]:
    """从图片文件路径使用 OCR 识别关卡数字。
    
    Args:
        image_path: 截图文件路径
    
    Returns:
        关卡数字，识别失败返回 None
    """
    screenshot = cv2.imread(str(image_path))
    if screenshot is None:
        logger.error("无法读取图片: %s", image_path)
        return None
    return ocr_level_number(screenshot)


def _ammo_roi_box(image: np.ndarray) -> tuple[int, int, int, int]:
    """按 AMMO_ROI 百分比计算蓝弹药数字区域像素坐标。"""
    h, w = image.shape[:2]
    x1 = max(0, int(w * AMMO_ROI["x1_pct"]))
    y1 = max(0, int(h * AMMO_ROI["y1_pct"]))
    x2 = min(w, int(w * AMMO_ROI["x2_pct"]))
    y2 = min(h, int(h * AMMO_ROI["y2_pct"]))
    return x1, y1, x2, y2


def _save_ammo_ocr_debug(
    screenshot: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    roi: np.ndarray,
    roi_upscaled: np.ndarray | None,
    ammo: int | None,
    raw_texts: list[str] | None = None,
) -> Path:
    """保存弹药 OCR 用到的裁剪图与标注图，供人工 debug。"""
    out_dir = AMMO_DETECT_DEBUG_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    marked = screenshot.copy()
    cv2.rectangle(marked, (x1, y1), (x2, y2), (0, 255, 0), 2)
    label = f"ammo={ammo}" if ammo is not None else "ammo=?"
    cv2.putText(
        marked,
        label,
        (max(0, x1 - 40), max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
    )

    # 固定最新一份 + 带时间戳备份
    cv2.imwrite(str(out_dir / "00_full_screenshot.png"), screenshot)
    cv2.imwrite(str(out_dir / "01_ammo_roi.png"), roi)
    cv2.imwrite(str(out_dir / "03_full_marked.png"), marked)
    cv2.imwrite(str(out_dir / f"{stamp}_full.png"), screenshot)
    cv2.imwrite(str(out_dir / f"{stamp}_roi.png"), roi)
    cv2.imwrite(str(out_dir / f"{stamp}_marked.png"), marked)

    if roi_upscaled is not None:
        cv2.imwrite(str(out_dir / "02_ammo_roi_upscaled.png"), roi_upscaled)
        cv2.imwrite(str(out_dir / f"{stamp}_roi_upscaled.png"), roi_upscaled)

    meta = out_dir / f"{stamp}_result.txt"
    meta.write_text(
        "\n".join(
            [
                f"ammo={ammo}",
                f"roi=({x1},{y1})-({x2},{y2})",
                f"raw_texts={raw_texts or []}",
                f"upscale={AMMO_OCR_UPSCALE}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "04_latest_result.txt").write_text(meta.read_text(encoding="utf-8"), encoding="utf-8")

    logger.info("弹药 OCR 调试图已保存: %s (ammo=%s)", out_dir, ammo)
    return out_dir


def read_blue_ammo_count(screenshot: np.ndarray) -> Optional[int]:
    """OCR 识别右下角蓝色鱼雷按钮上的弹药数量。

    裁剪 AMMO_ROI（仅蓝按钮数字区，不含右侧灰色弹药），放大后 EasyOCR 识别。
    每次识别都会把 ROI / 标注图保存到 AMMO_DETECT_DEBUG_DIR。

    Returns:
        弹药数量（含 0）；识别失败返回 None。
    """
    if not config_module.OCR_ENABLED:
        logger.warning("OCR 未启用，无法读取弹药数量")
        return None

    x1, y1, x2, y2 = _ammo_roi_box(screenshot)
    if x2 <= x1 or y2 <= y1:
        logger.warning("弹药 ROI 无效: (%s,%s)-(%s,%s)", x1, y1, x2, y2)
        return None

    roi = screenshot[y1:y2, x1:x2]
    if roi.size == 0:
        logger.warning("弹药 ROI 为空")
        return None

    scale = AMMO_OCR_UPSCALE
    roi_upscaled = cv2.resize(
        roi,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )

    ammo: int | None = None
    raw_texts: list[str] = []
    try:
        reader = _get_reader()
        roi_rgb = cv2.cvtColor(roi_upscaled, cv2.COLOR_BGR2RGB)
        results = reader.readtext(roi_rgb, allowlist="0123456789")
        best_conf = -1.0
        for _bbox, text, conf in results:
            raw_texts.append(f"{text!r}:{conf:.3f}")
            digits = "".join(ch for ch in text if ch.isdigit())
            if not digits:
                continue
            value = int(digits)
            if conf > best_conf:
                best_conf = conf
                ammo = value
        if ammo is not None:
            logger.info("OCR 识别蓝弹药数量: %d (置信度: %.3f)", ammo, best_conf)
        else:
            logger.warning("弹药 OCR 未识别到数字，raw=%s", raw_texts)
    except ImportError:
        logger.warning("EasyOCR 未安装，请执行: pip install easyocr")
    except Exception as exc:
        logger.warning("弹药 OCR 失败: %s", exc, exc_info=True)

    _save_ammo_ocr_debug(
        screenshot,
        x1,
        y1,
        x2,
        y2,
        roi,
        roi_upscaled,
        ammo,
        raw_texts=raw_texts,
    )
    return ammo
