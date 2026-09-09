from .log import logger


class CustomException(Exception):
    """自定义异常"""


class ViewportDetectionError(CustomException):
    """无法从原始截图中建立可信的有效画面。"""

    def __init__(self, raw_size, candidate_rect, reason):
        self.raw_size = raw_size
        self.candidate_rect = candidate_rect
        self.reason = reason
        super().__init__(
            f"raw_size={raw_size}, candidate_rect={candidate_rect}, reason={reason}"
        )


class CaptureUnavailableError(CustomException):
    """Raw capture did not produce an image after bounded retries."""

    def __init__(self, handle, attempts, reason):
        self.handle = handle
        self.attempts = attempts
        self.reason = reason
        super().__init__(
            f"handle={handle}, attempts={attempts}, reason={reason}"
        )


class GUIStopException(CustomException):
    """GUI停止按钮"""

    def __init__(self, *args):
        super().__init__(*args)
        logger.ui_error("手动停止")


class TimesNotEnoughException(CustomException):
    """次数不足"""

    def __init__(self, *args):
        super().__init__(*args)
        logger.ui_error("异常捕获：次数不足")


class TimeoutException(CustomException):
    """超时"""

    def __init__(self, *args):
        super().__init__(*args)
        logger.ui_error("异常捕获：超时")


class DailyLimitException(CustomException):
    """该玩法次数已达本日上限"""

    def __init__(self, *args):
        super().__init__(*args)
        logger.ui_error("异常捕获：该玩法次数已达本日上限")
