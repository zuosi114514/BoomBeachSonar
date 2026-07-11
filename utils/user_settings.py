"""用户可改配置：读写 settings.json，并应用到 config 模块。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import config as config_module
from utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

SETTINGS_FILE = config_module.BASE_DIR / "settings.json"

# GUI / 文档用：字段说明与类型
SETTING_SCHEMA: list[dict[str, Any]] = [
    {
        "key": "adb_serial",
        "label": "ADB 设备地址",
        "type": "str",
        "group": "连接",
    },
    {
        "key": "game_package_name",
        "label": "游戏包名",
        "type": "str",
        "group": "连接",
    },
    {
        "key": "log_level",
        "label": "日志级别",
        "type": "choice",
        "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
        "group": "连接",
    },
    {
        "key": "manual_level",
        "label": "手动指定关卡（空=自动识别）",
        "type": "optional_int",
        "group": "流程",
    },
    {
        "key": "activity_button_timeout",
        "label": "等待活动按钮超时（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "activity_detail_ready_timeout",
        "label": "等待活动详情就绪超时（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "probe_detail_ready_timeout",
        "label": "探测前等待详情超时（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "retry_button_timeout",
        "label": "等待重试按钮超时（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "victory_wait_timeout",
        "label": "等待胜利界面超时（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "victory_check_timeout",
        "label": "进关后胜利短检查（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "level_pre_detect_victory_timeout",
        "label": "识别关卡前等待延迟胜利（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "level_after_victory_delay",
        "label": "跳过胜利后关卡稳定等待（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "login_wait_timeout",
        "label": "等待登录按钮超时（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "game_restart_load_delay",
        "label": "通用重启游戏后加载等待（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "sonar_not_found_restart_delay",
        "label": "找不到声纳时重启后等待（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "sonar_wait_timeout",
        "label": "等待声纳图标超时（秒）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "reenter_activity_delay",
        "label": "点活动按钮前等待（秒，旧项保留）",
        "type": "float",
        "group": "等待时间",
    },
    {
        "key": "match_threshold",
        "label": "模板匹配阈值",
        "type": "float",
        "group": "识别",
    },
    {
        "key": "use_saved_points",
        "label": "优先使用校准点位",
        "type": "bool",
        "group": "识别",
    },
    {
        "key": "ocr_enabled",
        "label": "启用弹药 OCR",
        "type": "bool",
        "group": "识别",
    },
    {
        "key": "claim_rewards_when_ammo_empty",
        "label": "弹药用尽时领取活动奖励",
        "type": "bool",
        "group": "识别",
    },
    {
        "key": "hit_click_interval",
        "label": "点击命中格间隔（秒）",
        "type": "float",
        "group": "流程",
    },
]

DEFAULT_SETTINGS: dict[str, Any] = {
    "adb_serial": "127.0.0.1:5555",
    "game_package_name": "com.supercell.boombeach",
    "log_level": "INFO",
    "manual_level": None,
    "activity_button_timeout": 20.0,
    "activity_detail_ready_timeout": 15.0,
    "probe_detail_ready_timeout": 6.0,
    "retry_button_timeout": 20.0,
    "victory_wait_timeout": 12.0,
    "victory_check_timeout": 1.2,
    "level_pre_detect_victory_timeout": 3.0,
    "level_after_victory_delay": 1.0,
    "login_wait_timeout": 10.0,
    "game_restart_load_delay": 30.0,
    "sonar_not_found_restart_delay": 15.0,
    "sonar_wait_timeout": 60.0,
    "reenter_activity_delay": 17.0,
    "match_threshold": 0.85,
    "use_saved_points": True,
    "ocr_enabled": True,
    "claim_rewards_when_ammo_empty": True,
    "hit_click_interval": 1.0,
}

# settings.json key -> config 模块属性名
_CONFIG_MAP: dict[str, str] = {
    "adb_serial": "ADB_SERIAL",
    "game_package_name": "GAME_PACKAGE_NAME",
    "log_level": "LOG_LEVEL",
    "activity_button_timeout": "ACTIVITY_BUTTON_TIMEOUT",
    "activity_detail_ready_timeout": "ACTIVITY_DETAIL_READY_TIMEOUT",
    "probe_detail_ready_timeout": "PROBE_DETAIL_READY_TIMEOUT",
    "retry_button_timeout": "RETRY_BUTTON_TIMEOUT",
    "victory_wait_timeout": "VICTORY_WAIT_TIMEOUT",
    "victory_check_timeout": "VICTORY_CHECK_TIMEOUT",
    "level_pre_detect_victory_timeout": "LEVEL_PRE_DETECT_VICTORY_TIMEOUT",
    "level_after_victory_delay": "LEVEL_AFTER_VICTORY_DELAY",
    "login_wait_timeout": "LOGIN_WAIT_TIMEOUT",
    "game_restart_load_delay": "GAME_RESTART_LOAD_DELAY",
    "sonar_not_found_restart_delay": "SONAR_NOT_FOUND_RESTART_DELAY",
    "sonar_wait_timeout": "SONAR_WAIT_TIMEOUT",
    "reenter_activity_delay": "REENTER_ACTIVITY_DELAY",
    "match_threshold": "DEFAULT_MATCH_THRESHOLD",
    "use_saved_points": "USE_SAVED_POINTS",
    "ocr_enabled": "OCR_ENABLED",
    "claim_rewards_when_ammo_empty": "CLAIM_REWARDS_WHEN_AMMO_EMPTY",
    "hit_click_interval": "HIT_CLICK_INTERVAL",
}


def default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """读取 settings.json；不存在则写入默认值。"""
    settings_path = path or SETTINGS_FILE
    merged = default_settings()
    if not settings_path.exists():
        save_settings(merged, settings_path)
        return merged

    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取 settings.json 失败，使用默认值: %s", exc)
        return merged

    if not isinstance(raw, dict):
        logger.warning("settings.json 格式无效，使用默认值")
        return merged

    for key in DEFAULT_SETTINGS:
        if key in raw:
            merged[key] = raw[key]
    return merged


def save_settings(settings: dict[str, Any], path: Path | None = None) -> Path:
    """保存配置到 settings.json。"""
    settings_path = path or SETTINGS_FILE
    cleaned = default_settings()
    for key in cleaned:
        if key in settings:
            cleaned[key] = settings[key]
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("已保存配置: %s", settings_path)
    return settings_path


def apply_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """把配置写到 config 模块，并刷新日志级别。"""
    data = load_settings() if settings is None else {**default_settings(), **settings}

    for key, attr in _CONFIG_MAP.items():
        if key not in data:
            continue
        value = data[key]
        if key in {
            "activity_button_timeout",
            "activity_detail_ready_timeout",
            "probe_detail_ready_timeout",
            "retry_button_timeout",
            "victory_wait_timeout",
            "victory_check_timeout",
            "level_pre_detect_victory_timeout",
            "level_after_victory_delay",
            "login_wait_timeout",
            "game_restart_load_delay",
            "sonar_not_found_restart_delay",
            "sonar_wait_timeout",
            "reenter_activity_delay",
            "match_threshold",
            "hit_click_interval",
        }:
            value = float(value)
        elif key == "manual_level":
            continue  # 不写入 config，由调用方使用
        elif key in {"use_saved_points", "ocr_enabled", "claim_rewards_when_ammo_empty"}:
            value = bool(value)
        setattr(config_module, attr, value)

    setup_logging(config_module.LOG_LEVEL)
    logger.info(
        "已应用配置: adb=%s package=%s victory_wait=%.1fs reenter_delay=%.1fs",
        config_module.ADB_SERIAL,
        config_module.GAME_PACKAGE_NAME,
        config_module.VICTORY_WAIT_TIMEOUT,
        config_module.REENTER_ACTIVITY_DELAY,
    )
    return data
