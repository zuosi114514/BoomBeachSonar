import os
from pathlib import Path
from typing import Final

# Base 路径，指向项目根目录
BASE_DIR = Path(__file__).resolve().parent

# 多实例 worker 会在导入本模块前设置这些环境变量。
INSTANCE_ID = os.environ.get("BBMA_INSTANCE_ID", "").strip()
_runtime_dir_text = os.environ.get("BBMA_RUNTIME_DIR", "").strip()
RUNTIME_DIR = Path(_runtime_dir_text).resolve() if _runtime_dir_text else None

# ADB 连接的默认设备 IP 地址
ADB_SERIAL = os.environ.get("BBMA_ADB_SERIAL", "127.0.0.1:5555")

# 游戏版本与包名
INTERNATIONAL_GAME_PACKAGE = "com.supercell.boombeach"
CN_GAME_PACKAGE = "com.tencent.tmgp.supercell.boombeach"
GAME_REGION = os.environ.get("BBMA_GAME_REGION", "international")
GAME_PACKAGE_NAME = (
    CN_GAME_PACKAGE
    if GAME_REGION == "cn"
    else INTERNATIONAL_GAME_PACKAGE
)

# 国服启动页「登陆岛屿」按钮固定点击点（1280x720）
CN_LOGIN_ISLAND_POINT: Final[tuple[int, int]] = (640, 595)

# 模板图片目录和截图保存目录
TEMPLATE_DIR = BASE_DIR / "template"
SCREENSHOT_DIR = (
    RUNTIME_DIR / "screenshots"
    if RUNTIME_DIR is not None
    else BASE_DIR / "_debug" / "screenshots"
)
LOG_DIR = RUNTIME_DIR / "logs" if RUNTIME_DIR is not None else BASE_DIR / "_debug" / "logs"
LOG_FILE = LOG_DIR / "bbma.log"
OUTPUT_DIR = RUNTIME_DIR / "outputs" if RUNTIME_DIR is not None else BASE_DIR / "outputs"

# 目前支持的最大关卡
MAX_LEVEL: Final[int] = 36

# 第 10 海域及以上关卡使用的默认潜艇长度列表
DEFAULT_SUBMARINES: Final[tuple[int, ...]] = (2, 2, 3, 4, 5)

# 固定关卡对应的潜艇长度列表，供前 10 个关卡使用
SPECIAL_SUBMARINES: Final[dict[int, tuple[int, ...]]] = {
    1:  (3,),
    2:  (2, 2),
    3:  (2, 2, 3),
    4:  (2, 3, 4),
    5:  (2, 3, 3, 4),
    6:  (2, 2, 3, 3, 5),
    7:  (2, 2, 3, 3, 4, 5),
    8:  (2, 2, 3, 3, 4, 4, 5),
    9:  (2, 3, 3, 4, 4, 5),
    10: (2, 2, 3, 4, 4, 5),
}

# 固定关卡对应的菱形网格边长
LEVEL_GRID_SIZES: Final[dict[int, int]] = {
    1: 3,
    2: 4,
    3: 5,
    4: 6,
    5: 7,
    6: 8,
    7: 9,
    8: 10,
    9: 10,
    10: 10,
    **{
        level: 10
        for level in range(11, MAX_LEVEL + 1)
    },
}

# Level 对应的潜艇长度列表
SUBMARINES: Final[dict[int, tuple[int, ...]]] = {
    **SPECIAL_SUBMARINES,
    **{
        level: DEFAULT_SUBMARINES
        for level in range(11, MAX_LEVEL + 1)
    },
}

# 是否优先使用人工校准后的固定点位
USE_SAVED_POINTS = True
SAVED_POINTS_FILE = BASE_DIR / "save_points" / "points.json"

# 默认的截图文件名和模板匹配的默认阈值
DEFAULT_SCREENSHOT_NAME = "screen.png"
DEFAULT_MATCH_THRESHOLD = 0.85
DEFAULT_TEMPLATE_SHAPE_WEIGHT = 0.9
DEFAULT_TEMPLATE_SHAPE_POWER = 3.0

# 进入活动后「点击任意地方开始」的安全点击坐标（1280x720）
# 参考 save_points/imgs/1.png：左上开阔海面，避开退出键/标题/网格/底部按钮
ACTIVITY_TAP_TO_START_POINT: Final[tuple[int, int]] = (300, 140)

# 胜利界面模板（金色星星 + 「胜利」蓝条）
VICTORY_TEMPLATE: Final[str] = "./template/victory.png"

# 等待胜利界面出现的超时（秒）；点完命中格后用较长等待
VICTORY_WAIT_TIMEOUT = 12.0

# 进入活动后检查是否已在胜利界面的短超时（秒）
VICTORY_CHECK_TIMEOUT = 1.2

# 识别关卡标题前，等待延迟出现的胜利界面（秒）
LEVEL_PRE_DETECT_VICTORY_TIMEOUT = 3.0

# 跳过胜利后等待新关卡标题稳定（秒）
LEVEL_AFTER_VICTORY_DELAY = 1.0

# 进入活动最大重试次数
ACTIVITY_ENTER_MAX_RETRIES = 11

# 等待活动按钮出现的超时（秒）
ACTIVITY_BUTTON_TIMEOUT = 20.0

# 进入活动详情后等待退出按钮/胜利界面就绪（秒）
ACTIVITY_DETAIL_READY_TIMEOUT = 15.0

# 探测点击前等待活动详情就绪（秒）
PROBE_DETAIL_READY_TIMEOUT = 6.0

# 等待重试按钮超时（秒）
RETRY_BUTTON_TIMEOUT = 20.0

# 重启游戏后等待加载（秒）——通用失败重试
GAME_RESTART_LOAD_DELAY = 30.0

# 因找不到声纳而重启游戏后的加载等待（秒）
SONAR_NOT_FOUND_RESTART_DELAY = 15.0

# 上划后等待海里「参加」声纳浮标出现的超时（秒）
SONAR_WAIT_TIMEOUT = 60.0

# 主岛上划像素（手指上移，露出海边声纳）
HOME_SWIPE_UP_PIXELS = 300

# 主岛上划持续时间（毫秒）；增大后滑动更慢
HOME_SWIPE_DURATION_MS = 800

# 声纳「参加」浮标模板
SONAR_TEMPLATE = "./template/sonar_join.png"
SONAR_LABEL_TEMPLATE = "./template/sonar_join_label.png"

# 声纳匹配阈值（水面动画会导致分数低于通用 0.85）
SONAR_MATCH_THRESHOLD = 0.60

# 探测断网恢复后不再盲等；改为等声纳出现（见 enter_activity）
# 保留配置项兼容 settings.json，默认不再用于 restart_process
REENTER_ACTIVITY_DELAY = 17.0

# 日志级别，可选 DEBUG、INFO、WARNING、ERROR
LOG_LEVEL = "INFO"

# 重启游戏后等待登录按钮的超时时间（秒）
LOGIN_WAIT_TIMEOUT = 10.0

# ============================================================
# 关卡模板匹配识别配置（对比 save_points/imgs 同区域）
# ============================================================

# 是否在进入活动后自动截图识别关卡
LEVEL_DETECT_ENABLED: Final[bool] = True

# 关卡参考截图目录（文件名如 1.png、10.png）
LEVEL_REF_DIR: Final[Path] = BASE_DIR / "save_points" / "imgs"

# 顶部「N号海域」标题带 ROI（只含标题，不含下方倒计时；百分比适配分辨率）
# 高度相对原配置下扩 1/4：原高 0.065 → 现高约 0.081
LEVEL_MATCH_ROI: Final[dict[str, float]] = {
    "x1_pct": 0.375,
    "y1_pct": 0.005,
    "x2_pct": 0.625,
    "y2_pct": 0.086,
}

# 数字掩膜匹配最低相似度；低于此值视为未识别
LEVEL_MATCH_THRESHOLD: Final[float] = 0.65

# 第一名与第二名最低分差，过小则视为不确定
LEVEL_MATCH_MIN_MARGIN: Final[float] = 0.04

# 白色标题文字二值化阈值
LEVEL_TEXT_BINARY_THRESHOLD: Final[int] = 195

# 关卡识别调试图输出目录
LEVEL_DETECT_DEBUG_DIR: Final[Path] = SCREENSHOT_DIR / "level_detect"

# 未识别出关卡时的默认关卡号
DEFAULT_DETECTED_LEVEL: Final[int] = 14

# ============================================================
# OCR 关卡数字识别配置
# ============================================================

# 是否启用 OCR 识别关卡数字
OCR_ENABLED: Final[bool] = True

# EasyOCR 识别语言：'ch_sim'=中文简体 'en'=英文
OCR_LANGUAGE: Final[list[str]] = ["en"]

# OCR 感兴趣区域（ROI），相对于截图宽高的百分比坐标
# 在 1280x720 的 Boom Beach 活动详情界面中，
# 关卡数字通常显示在画面顶部偏左区域
OCR_ROI: Final[dict[str, float]] = {
    "x1_pct": 0.398,  # ROI 左边界（占宽度百分比）
    "y1_pct": 0.010,  # ROI 上边界（占高度百分比）
    "x2_pct": 0.480,  # ROI 右边界（占宽度百分比）
    "y2_pct": 0.110,  # ROI 下边界（占高度百分比）
}

# OCR 文本黑名单：识别结果中包含这些文字时会被过滤掉
# 用于去掉 "关卡"、"Level"、"Stage" 等标签，只保留数字
OCR_LABEL_BLACKLIST: Final[list[str]] = [
    "\u5173\u5361", "\u5173", "\u7b2c",
    "Level", "level", "LEVEL",
    "Stage", "stage", "STAGE",
    "Lv.", "lv.", "LV.",
]

# ============================================================
# 蓝色鱼雷弹药数量 OCR（右下角蓝按钮右下角数字）
# 参考 save_points/imgs/1.png：蓝色鱼雷按钮上的白色数字，不为灰色弹药
# ============================================================

# 蓝弹药数字 ROI（1280x720 约 (1120,650)-(1200,705)）
# 左边界留宽一些，避免三位数的百位被裁掉
AMMO_ROI: Final[dict[str, float]] = {
    "x1_pct": 0.875,
    "y1_pct": 0.903,
    "x2_pct": 0.938,
    "y2_pct": 0.979,
}

# OCR 前放大倍数（小数字需放大才稳）
AMMO_OCR_UPSCALE: Final[float] = 3.0

# 弹药 OCR 调试图目录
AMMO_DETECT_DEBUG_DIR: Final[Path] = SCREENSHOT_DIR / "ammo_detect"

# ============================================================
# 活动奖励领取（左下角潜艇 → 蓝炮弹 / 黄金币）
# ============================================================

# 左下角潜艇进度按钮固定点击点（1280x720，参考 save_points/imgs/1.png）
SUB_REWARD_BUTTON_POINT = (55, 660)

# 奖励弹窗关闭按钮兜底坐标
REWARD_CLOSE_POINT = (945, 120)

# 奖励弹窗内 ROI（百分比）
REWARD_PANEL_X1_PCT = 0.23
REWARD_PANEL_Y1_PCT = 0.20
REWARD_PANEL_X2_PCT = 0.77
REWARD_PANEL_Y2_PCT = 0.82

# 点击潜艇入口后等待奖励界面出现的固定延时（秒），不再做界面识别
REWARD_PANEL_OPEN_DELAY = 1.5

# 单次打开奖励界面最多领取轮数
REWARD_CLAIM_MAX_ROUNDS = 15

# 探测完成后逐个点击命中格之间的间隔（秒）
HIT_CLICK_INTERVAL = 1.0

# 探测完成、关闭弱网后，开始统一点击命中格前的等待（秒）
# 给游戏界面/网络恢复一点缓冲，避免首击落空
HIT_CLICK_START_DELAY = 1.0

# 弹药识别连续失败多少次后停止脚本（识别失败视为 0 触发领取，反复失败才停）
AMMO_DETECT_FAIL_LIMIT = 3

# 弹药为 0 时是否尝试领取活动奖励
CLAIM_REWARDS_WHEN_AMMO_EMPTY = True

