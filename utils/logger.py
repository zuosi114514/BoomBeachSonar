import logging
import time

from config import LOG_FILE, LOG_LEVEL


_LOGGING_READY = False
_RUN_START_TS: float | None = None
_RESET = "\033[0m"
_DIM = "\033[2m"
_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",    # 青色
    logging.INFO: "\033[32m",     # 绿色
    logging.WARNING: "\033[33m",  # 黄色
    logging.ERROR: "\033[31m",    # 红色
    logging.CRITICAL: "\033[35m", # 紫色
}


def mark_run_start() -> None:
    """标记脚本开始运行的时间点（用于控制台显示已运行时长）。"""
    global _RUN_START_TS
    _RUN_START_TS = time.monotonic()


def get_run_elapsed_text() -> str:
    """返回已运行时长文本，如 00:12:34；尚未标记开始时返回 --:--:--。"""
    if _RUN_START_TS is None:
        return "--:--:--"
    elapsed = max(0, int(time.monotonic() - _RUN_START_TS))
    hours, rem = divmod(elapsed, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class ColorFormatter(logging.Formatter):
    """控制台彩色日志格式化器（含脚本已运行时长）。"""

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        time_text = self.formatTime(record, self.datefmt)
        level_text = f"{color}{record.levelname:<8}{_RESET}"
        name_text = f"{_DIM}{record.name}{_RESET}"
        message = record.getMessage()
        run_text = get_run_elapsed_text()

        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        return (
            f"{_DIM}{time_text}{_RESET} "
            f"{_DIM}[+{run_text}]{_RESET} "
            f"{level_text} {name_text} | {message}"
        )


class GuiLogFormatter(logging.Formatter):
    """GUI 日志窗口用的纯文本格式（含脚本已运行时长）。"""

    def format(self, record: logging.LogRecord) -> str:
        time_text = self.formatTime(record, "%H:%M:%S")
        run_text = get_run_elapsed_text()
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        return (
            f"{time_text} [+{run_text}] [{record.levelname}] {record.name} | {message}"
        )


def setup_logging(level: str | int | None = None) -> None:
    """初始化项目日志，默认同时输出到控制台和文件。"""
    global _LOGGING_READY

    if _LOGGING_READY:
        if level is None:
            return
        log_level = _normalize_level(level)
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        for handler in root_logger.handlers:
            handler.setLevel(log_level)
        return

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_level = _normalize_level(level or LOG_LEVEL)

    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_formatter = ColorFormatter(datefmt="%H:%M:%S")

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(log_level)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(log_level)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    _LOGGING_READY = True
    if _RUN_START_TS is None:
        mark_run_start()


def attach_log_handler(handler: logging.Handler, level: str | int | None = None) -> None:
    """给 root logger 追加一个 handler（例如 GUI 日志窗口）。"""
    setup_logging()
    root_logger = logging.getLogger()
    log_level = _normalize_level(level or LOG_LEVEL)
    handler.setLevel(log_level)
    if handler.formatter is None:
        handler.setFormatter(GuiLogFormatter())
    if handler not in root_logger.handlers:
        root_logger.addHandler(handler)


def detach_log_handler(handler: logging.Handler) -> None:
    """移除之前附加的 handler。"""
    root_logger = logging.getLogger()
    if handler in root_logger.handlers:
        root_logger.removeHandler(handler)
        handler.close()


def get_logger(name: str) -> logging.Logger:
    """获取项目 logger，首次调用时自动初始化日志系统。"""
    setup_logging()
    return logging.getLogger(name)


def _normalize_level(level: str | int) -> int:
    """把配置中的日志级别转换为 logging 模块使用的整数级别。"""
    if isinstance(level, int):
        return level

    normalized = level.upper()
    log_level = logging.getLevelName(normalized)
    if not isinstance(log_level, int):
        raise ValueError(f"不支持的日志级别: {level}")
    return log_level
