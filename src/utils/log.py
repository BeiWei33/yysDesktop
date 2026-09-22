import logging
import os
import re
from datetime import date, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .application import APP_NAME, APP_PATH, LOG_DIR_PATH
from .log_color import LogColorLevel, log_color
from .mysignal import global_ms as ms

LOG_LEVEL_GUI: int = 25
logging.addLevelName(LOG_LEVEL_GUI, "GUI")


def log_file_name(app_name: str, emulator_enabled: bool, device_serial: str, pid: int) -> str:
    """计算日志文件名

    同时开多个实例（每个操作一台 MuMu 模拟器）时，如果都写同一个文件，日志会交错混在
    一起，排查时无法分辨哪条来自哪个实例。所以模拟器模式下文件名带上设备标识。

    桌面版（未开启模拟器）保持原来的 ``<app_name>.log`` 不变。

    Args:
        app_name (str): 应用名，作为文件名前缀
        emulator_enabled (bool): 是否开启模拟器模式
        device_serial (str): 模拟器设备序列号，例如 ``127.0.0.1:16448``
        pid (int): 当前进程号，设备未知时用它兜底

    Returns:
        str: 日志文件名（不含目录）
    """
    if not emulator_enabled:
        return f"{app_name}.log"

    identifier = ""
    serial = (device_serial or "").strip()
    if serial:
        # 127.0.0.1:16448 → 16448；其它形式做安全化处理，避免 : . 等非法文件名字符
        identifier = serial.rsplit(":", 1)[-1] if ":" in serial else serial
        identifier = re.sub(r"[^0-9A-Za-z]+", "_", identifier).strip("_")

    if not identifier:
        # 配置里没指定设备（自动选择）时用进程号，同样能区分开
        identifier = f"pid{pid}"

    return f"{app_name}-{identifier}.log"


def _read_emulator_config() -> tuple[bool, str]:
    """从配置文件读取模拟器开关与设备

    这里不能 ``from .config import config``：config 模块会 import 本模块，会形成循环导入；
    而且日志初始化早于配置加载完成。所以直接读配置文件，失败时按"未开启"处理。

    Returns:
        tuple[bool, str]: (是否开启模拟器, 设备序列号)
    """
    try:
        import yaml

        config_path = Path(APP_PATH) / "data" / "config.yaml"
        if not config_path.exists():
            return False, ""
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        section = data.get("emulator") or {}
        return bool(section.get("enabled", False)), str(section.get("device_serial", "") or "")
    except Exception:
        return False, ""


def send_gui_msg(msg: str = "", level: LogColorLevel = LogColorLevel.INFO):
    """发送消息到GUI日志文本框

    Args:
        msg (str): 消息内容
        level (LogColorLevel): 日志颜色等级
    """
    _now = datetime.now().strftime("%H:%M:%S")
    ms.main.ui_text_info_update.emit(f"{_now} {msg}", log_color(level))


class CustomLogger(logging.Logger):
    def ui(self, msg, *args, **kwargs):
        send_gui_msg(msg, LogColorLevel.INFO)
        super()._log(LOG_LEVEL_GUI, msg, args, **kwargs, stacklevel=2)

    def ui_hint(self, msg, *args, **kwargs):
        send_gui_msg(msg, LogColorLevel.HINT)
        super()._log(logging.INFO, msg, args, **kwargs, stacklevel=2)

    def ui_warn(self, msg, *args, **kwargs):
        send_gui_msg(msg, LogColorLevel.WARN)
        super()._log(logging.WARNING, msg, args, **kwargs, stacklevel=2)

    def ui_error(self, msg, *args, **kwargs):
        send_gui_msg(msg, LogColorLevel.ERROR)
        super()._log(logging.ERROR, msg, args, **kwargs, stacklevel=2)

    def progress(self, msg, *args, **kwargs):
        ms.main.ui_text_progress_update.emit(str(msg))  # 输出至完成情况UI界面
        super()._log(logging.INFO, f"done number: {msg}", args, **kwargs, stacklevel=2)


# 创建日志记录器
logger = CustomLogger(APP_NAME)
logger.setLevel(logging.DEBUG)

# 创建文件处理程序
_emulator_enabled, _device_serial = _read_emulator_config()
LOG_FILE_PATH = Path(LOG_DIR_PATH) / log_file_name(
    APP_NAME, _emulator_enabled, _device_serial, os.getpid()
)
file_handler = TimedRotatingFileHandler(
    LOG_FILE_PATH,
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)

file_handler.setLevel(logging.INFO)

# 创建屏幕处理程序
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)

# 创建日志格式
formatter = logging.Formatter(
    fmt="%(asctime)s.%(msecs)03d %(levelname)-7s %(filename)s[line:%(lineno)d]-%(funcName)s %(message)s",
    datefmt="%H:%M:%S",
)
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

# 将处理程序添加到日志记录器
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

logger.info(f"日志文件：{LOG_FILE_PATH}")


def log_clean_up() -> bool:
    """日志清理"""
    # TODO v2.1.0后移除
    logger.info("log clean up...")
    today = date.today()
    n = 0
    if not LOG_DIR_PATH.is_dir():
        logger.error("Not found log dir.")
        return False
    for item in LOG_DIR_PATH.iterdir():
        try:
            log_date = date(int(item.stem[-8:-4]), int(item.stem[-4:-2]), int(item.stem[-2:]))
            # 自动清理
            if (today - log_date).days > 30:
                try:
                    item.unlink()
                    n += 1
                    logger.info(f"Remove file: {item.absolute()} successfully.")
                except Exception:
                    logger.error(f"Remove file: {item.absolute()} failed.")
        except Exception:
            continue
    logger.info(f"Clean up {n} log files in total.")
    return True
