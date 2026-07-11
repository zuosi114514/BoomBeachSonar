"""
OCR 关卡数字识别测试

用法:
    python tests/test_ocr_recognition.py                  # 实时截图测试
    python tests/test_ocr_recognition.py --file <图片路径>  # 使用已有截图测试
    python tests/test_ocr_recognition.py --list            # 遍历测试 save_points 中的截图
"""

import argparse
import sys
from pathlib import Path

import cv2

# 添加项目根目录到路径
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from utils.ocr_helper import ocr_level_number
from config import OCR_ROI, SCREENSHOT_DIR


def _save_debug_images(screenshot: cv2.Mat, label: str = "test"):
    """\u4fdd\u5b58\u8c03\u8bd5\u56fe\u7247\uff1a\u539f\u56fe\u3001ROI\u3001\u6807\u8bb0\u56fe\u3002"""
    import os
    h, w = screenshot.shape[:2]
    x1 = int(w * OCR_ROI["x1_pct"]); y1 = int(h * OCR_ROI["y1_pct"])
    x2 = int(w * OCR_ROI["x2_pct"]); y2 = int(h * OCR_ROI["y2_pct"])
    os.makedirs(str(SCREENSHOT_DIR), exist_ok=True)
    roi = screenshot[y1:y2, x1:x2]
    cv2.imwrite(str(SCREENSHOT_DIR / f"ocr_{label}_roi.png"), roi)
    marked = screenshot.copy()
    cv2.rectangle(marked, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.imwrite(str(SCREENSHOT_DIR / f"ocr_{label}_marked.png"), marked)
    print(f"[\u8c03\u8bd5] ROI: ({x1},{y1})-({x2},{y2}), \u5df2\u4fdd\u5b58\u5230 {SCREENSHOT_DIR}/")


def test_live_screenshot():
    """从手机实时截图测试 OCR 识别。"""
    print("=" * 50)
    print("[测试模式] 实时截图")
    print("=" * 50)
    
    from utils.adb_control import AdbController
    adb = AdbController()
    
    print("正在截图...")
    screenshot = adb.read_screenshot()
    print(f"截图尺寸: {screenshot.shape}")
    
    _save_debug_images(screenshot, "live")
    
    level = ocr_level_number(screenshot)
    
    if level is not None:
        print(f"\n[成功] OCR 识别到第 {level} 关")
        return 0
    else:
        print(f"\n[失败] OCR 未识别出关卡数字")
        print("  可能原因:")
        print("  - 当前不在游戏活动详情页面")
        print("  - ROI 区域未对准关卡数字")
        print("  - EasyOCR 未安装 (pip install easyocr)")
        return 1


def test_image_file(image_path: str):
    """使用指定截图文件测试 OCR 识别。"""
    path = Path(image_path)
    if not path.exists():
        print(f"[错误] 文件不存在 {path}")
        return 1
    
    print(f"[测试模式] 图片文件")
    print(f"[文件] {path}")
    print("=" * 50)
    
    screenshot = cv2.imread(str(path))
    if screenshot is None:
        print(f"[错误] 无法读取图片 {path}")
        return 1
    
    print(f"[尺寸] {screenshot.shape}")
    
    _save_debug_images(screenshot, path.stem)
    
    level = ocr_level_number(screenshot)
    
    if level is not None:
        print(f"\n[成功] OCR 识别到第 {level} 关")
        return 0
    else:
        print(f"\n[失败] OCR 未识别出关卡数字")
        print("  可能原因:")
        print("  - 图片中不包含关卡数字")
        print("  - ROI 区域未对准")
        print("  - EasyOCR 未安装 (pip install easyocr)")
        return 1


def test_save_points():
    """遍历测试 save_points 目录中的所有截图。"""
    save_points_dir = BASE_DIR / "save_points" / "imgs"
    if not save_points_dir.exists():
        print(f"[错误] 目录不存在 {save_points_dir}")
        return 1
    
    png_files = sorted(save_points_dir.glob("*.png"))
    if not png_files:
        print(f"[错误] {save_points_dir} 中没有 PNG 图片")
        return 1
    
    print(f"[测试模式] 批量遍历 save_points 截图 ({len(png_files)} 张)")
    print("=" * 50)
    
    success = 0
    fail = 0
    
    for f in png_files:
        screenshot = cv2.imread(str(f))
        if screenshot is None:
            print(f"  [ERR] {f.name} -> 无法读取")
            fail += 1
            continue
        
        _save_debug_images(screenshot, f"batch_{f.stem}")
        
        level = ocr_level_number(screenshot)
        
        if level is not None:
            print(f"  [OK]  {f.name} -> 第 {level} 关")
            success += 1
        else:
            print(f"  [FAIL] {f.name} -> 未识别")
            fail += 1
    
    print("\n" + "=" * 50)
    print(f"结果: 成功 {success}, 失败 {fail}, 总计 {success + fail}")


def main():
    parser = argparse.ArgumentParser(description="OCR 关卡数字识别测试")
    parser.add_argument("--file", "-f", help="指定截图文件路径进行测试")
    parser.add_argument("--list", "-l", action="store_true", help="遍历测试 save_points 目录")
    args = parser.parse_args()
    
    if args.list:
        return test_save_points()
    elif args.file:
        return test_image_file(args.file)
    else:
        return test_live_screenshot()


if __name__ == "__main__":
    sys.exit(main())
