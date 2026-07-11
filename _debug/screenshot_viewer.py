from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from config import SCREENSHOT_DIR, TEMPLATE_DIR
from utils.adb_control import AdbController


def main():
    print("正在连接 ADB...")
    adb = AdbController()

    win_name = "Screenshot Viewer - 左键=坐标 | S=截图 | T=模板匹配 | R=刷新 | Q=退出"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, 1200, 700)

    screenshot = None
    mouse_x, mouse_y = 0, 0

    def mouse_callback(event, x, y, flags, param):
        nonlocal mouse_x, mouse_y
        mouse_x, mouse_y = x, y
        if event == cv2.EVENT_LBUTTONDOWN and screenshot is not None:
            h, w = screenshot.shape[:2]
            scale = display_w / w if screenshot is not None else 1.0
            orig_x = int(round(x / scale))
            orig_y = int(round(y / scale))
            print(f"点击坐标: ({orig_x}, {orig_y})")

    cv2.setMouseCallback(win_name, mouse_callback)

    while True:
        key = cv2.waitKey(100) & 0xFF

        if key == ord("q"):
            break
        elif key == ord("s"):
            screenshot = adb.read_screenshot()
            path = SCREENSHOT_DIR / "screen.png"
            cv2.imwrite(str(path), screenshot)
            print(f"截图已保存: {path}")
        elif key == ord("t"):
            if screenshot is None:
                print("请先按 S 截图")
                continue
            template_path = input("输入模板路径 (如 template/quit_activity.png): ").strip()
            if not Path(template_path).exists():
                print(f"文件不存在: {template_path}")
                continue
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
            result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            h, w = template.shape[:2]
            print(f"模板匹配: 相似度={max_val:.3f}, 位置=({max_loc[0]}, {max_loc[1]}), 中心=({max_loc[0]+w//2}, {max_loc[1]+h//2})")
            if max_val > 0.8:
                cv2.rectangle(screenshot, max_loc, (max_loc[0]+w, max_loc[1]+h), (0, 255, 0), 2)
        elif key == ord("r") and screenshot is not None:
            pass  # just redraw

        if screenshot is not None:
            h, w = screenshot.shape[:2]
            max_display_w = 1200
            scale = min(max_display_w / w, 1.0)
            display_w = int(w * scale)
            display_h = int(h * scale)
            display = cv2.resize(screenshot, (display_w, display_h))

            # Draw crosshair
            cx, cy = mouse_x, mouse_y
            cv2.line(display, (cx - 20, cy), (cx + 20, cy), (0, 255, 255), 1)
            cv2.line(display, (cx, cy - 20), (cx, cy + 20), (0, 255, 255), 1)

            # Show coordinates
            orig_x = int(round(cx / scale))
            orig_y = int(round(cy / scale))
            info = f"({orig_x}, {orig_y})"
            cv2.putText(display, info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            cv2.imshow(win_name, display)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
