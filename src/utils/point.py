from .exception import ViewportDetectionError
from .log import logger
from .viewport import viewport_registry
from .window import window_manager


class Point:
    """坐标点类，用于表示窗口客户区坐标"""

    def __init__(
        self,
        client_x: int | float,
        client_y: int | float,
        click_bounds: tuple[int, int, int, int] | None = None,
    ):
        """窗口客户区坐标

        Args:
            client_x (int | float): 客户区横坐标
            client_y (int | float): 客户区纵坐标
            click_bounds (tuple[int, int, int, int] | None): 可选安全点击区域，
                格式为(left, top, right, bottom)。识别结果可携带该区域，
                输入适配层会在其中进行中心偏向采样。
        """
        self.client_x: int = int(client_x)
        self.client_y: int = int(client_y)
        self.click_bounds = click_bounds

    @classmethod
    def from_screen(
        cls,
        screen_x: int | float,
        screen_y: int | float,
        handle: int | None = None,
    ) -> "Point":
        """从屏幕坐标反向映射到 canonical 客户区坐标。"""
        logger.info(f"from_screen: ({screen_x}, {screen_y})")
        transform = cls._transform_for_handle(handle)
        client_x, client_y = transform.screen_to_canonical((screen_x, screen_y))
        return cls(client_x, client_y)

    @staticmethod
    def _transform_for_handle(handle: int | None):
        target_handle = handle if handle is not None else window_manager.get_current_handle()
        transform = viewport_registry.current(target_handle) if target_handle is not None else None
        if transform is None:
            raise ViewportDetectionError(
                (0, 0),
                (0, 0, 0, 0),
                f"no viewport transform for handle={target_handle}",
            )
        return transform

    def to_screen(self, handle: int | None = None) -> tuple[int, int]:
        """将 canonical 客户区坐标映射为屏幕坐标。"""
        logger.info(f"to_screen: ({self.client_x}, {self.client_y})")
        return self._transform_for_handle(handle).canonical_to_screen(
            (self.client_x, self.client_y)
        )

    def set_x(self, x_offset: int | float):
        """设置X坐标偏移

        Args:
            x_offset (int | float): X轴偏移量，正值向右，负值向左
        """
        self.client_x = int(self.client_x + x_offset)
        self.click_bounds = None

    def set_y(self, y_offset: int | float):
        """设置Y坐标偏移

        Args:
            y_offset (int | float): Y轴偏移量，正值向下，负值向上
        """
        self.client_y = int(self.client_y + y_offset)
        self.click_bounds = None

    def __repr__(self) -> str:
        return f"Point({self.client_x}, {self.client_y})"


class Rectangle:
    """矩形区域"""

    def __init__(
        self,
        x: int = 0,
        y: int = 0,
        width: int = None,
        height: int = None,
        x2: int = None,
        y2: int = None,
    ):
        """初始化矩形

        Args:
            x (int): 左上角X坐标
            y (int): 左上角Y坐标
            width (int | None): 宽度
            height (int | None): 高度
            x2 (int | None): 右下角X坐标
            y2 (int | None): 右下角Y坐标

        Raises:
            ValueError: 当参数不合法时抛出
        """
        if (width is None or height is None) and (x2 is None or y2 is None):
            raise ValueError("必须提供width, height或x2, y2其中一组参数")

        if width is not None and x2 is not None:
            raise ValueError("不能同时指定width和x2")

        if height is not None and y2 is not None:
            raise ValueError("不能同时指定height和y2")

        self.x1 = x
        self.y1 = y

        if width is not None and height is not None:
            self.width = width
            self.height = height
            self.x2 = x + width
            self.y2 = y + height
        elif x2 is not None and y2 is not None:
            self.x2 = x2
            self.y2 = y2
            self.width = x2 - x
            self.height = y2 - y

    def get_box(self) -> tuple[int, int, int, int]:
        """获取box格式

        Returns:
            tuple[int, int, int, int]: (x, y, width, height)
        """
        return (self.x1, self.y1, self.width, self.height)

    def get_center_point(self) -> Point:
        """获取中心点

        Returns:
            Point: 中心点
        """
        center_x = self.x1 + self.width / 2
        center_y = self.y1 + self.height / 2
        return Point(center_x, center_y)
