"""关卡模板匹配识别测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import DEFAULT_DETECTED_LEVEL, LEVEL_REF_DIR
from utils.ocr_helper import _extract_digit_mask, match_level_by_template


class LevelTemplateMatchTest(unittest.TestCase):
    def test_match_known_reference_images(self):
        """用 save_points/imgs 中的参考图自测，应识别出对应关卡号。"""
        samples = [1, 2, 5, 8, 9, 10, 11, 12, 13]
        for level in samples:
            path = LEVEL_REF_DIR / f"{level}.png"
            if not path.exists():
                self.skipTest(f"缺少参考图: {path}")
            img = cv2.imread(str(path))
            self.assertIsNotNone(img, f"无法读取 {path}")
            detected = match_level_by_template(img)
            self.assertEqual(detected, level, f"{path.name} 应识别为第 {level} 关")

    def test_digit_mask_excludes_hao(self):
        """数字掩膜不应包含「号」。"""
        img = cv2.imread(str(LEVEL_REF_DIR / "2.png"))
        self.assertIsNotNone(img)
        digit = _extract_digit_mask(img)
        self.assertIsNotNone(digit)
        # 「2」单独宽度约 20~30，「2号」会到 60+
        self.assertLess(digit.shape[1], 40, f"digit too wide: {digit.shape}")

    def test_ignores_countdown_and_water_noise(self):
        """倒计时变化不应影响 2 号海域识别。"""
        path = LEVEL_REF_DIR / "2.png"
        if not path.exists():
            self.skipTest(f"缺少参考图: {path}")
        img = cv2.imread(str(path))
        self.assertIsNotNone(img)

        noisy = img.copy()
        noisy[70:100, 480:820] = np.random.randint(
            0, 120, noisy[70:100, 480:820].shape, dtype=np.uint8
        )

        detected = match_level_by_template(noisy)
        self.assertEqual(detected, 2)

    def test_unmatched_returns_default_level(self):
        """纯色图无法匹配时，应回退到默认第 10 关。"""
        blank = np.zeros((720, 1280, 3), dtype=np.uint8)
        detected = match_level_by_template(blank)
        self.assertEqual(detected, DEFAULT_DETECTED_LEVEL)


if __name__ == "__main__":
    unittest.main()
