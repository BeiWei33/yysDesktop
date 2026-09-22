from ..utils.adapter import Mouse
from ..utils.event import event_thread
from ..utils.exception import GUIStopException
from ..utils.function import sleep
from ..utils.image import RuleImage
from ..utils.log import logger
from ..utils.paddleocr import RuleOcr
from ..utils.point import Point
from .base_package import BasePackage
from .jiejietupo import JieJieTuPoGeRen
from .tansuo import TanSuo
from .utils import get_image_asset, load_asset


class HuiJuan(BasePackage):
    """绘卷"""

    scene_name = "绘卷刷分"
    resource_path: str = "huijuan"

    def __init__(
        self,
        n: int = 0,
        loop_count: int = 1,
        flag_refresh_rule: int = 3,
        flag_current_level: int = 57,
        flag_target_level: int = 57,
        flag_first_round_failure: bool = True,
        has_temp_pop: bool = True,
    ) -> None:
        """
        Args:
            n (int): 次数
            loop_count (int): 单次循环轮数
            flag_refresh_rule (int): 刷新规则
            flag_current_level (int): 当前等级
            flag_target_level (int): 目标等级
            flag_first_round_failure (bool):  首轮失败标志
            has_temp_pop (bool): 是否关闭临时弹窗
        """
        super().__init__(n)
        self.loop_count: int = loop_count
        self.flag_refresh_rule: int = flag_refresh_rule
        self.flag_current_level: int = flag_current_level
        self.flag_target_level: int = flag_target_level
        self.flag_first_round_failure: bool = flag_first_round_failure
        self.has_temp_pop: bool = has_temp_pop

    @staticmethod
    def description() -> None:
        logger.ui(
            """提前准备好自动轮换和加成，独立预设御魂，采取探索 + 个人突破的方式，突破券是自动识别。"""
            """上方的一次功能为一轮，先探索再个人突破，探索次数为单轮循环中完成挑战探索boss的次数。"""
            """比如你要刷100次探索，每5次探索清理一次突破，如此循环20轮。那么你上面的次数填写20，下面填写5。"""
        )

    def load_asset(self):
        self.IMAGE_MAP_JIEJIETUPO = self.get_image_asset("map_jiejietupo")

    def close_tansuo(self):
        """关闭探索入口界面

        目标章节不一定是 28 章，所以除了 28 章标题素材，也用与章节无关的
        「探索」按钮和「出战消耗」判断当前是否停在探索入口。
        """
        asset_image_list = load_asset(TanSuo.resource_path, "image")
        candidates = [
            get_image_asset(asset_image_list, "title_28"),
            get_image_asset(asset_image_list, "start"),
            get_image_asset(asset_image_list, "chuzhanxiaohao"),
        ]
        if any(RuleImage(asset_image).match() for asset_image in candidates):
            logger.ui("当前在探索入口处，尝试关闭")
            self.check_click(self.global_assets.IMAGE_QUIT, point_type="center")
        else:
            logger.ui("当前不在探索入口处，无需关闭")

    def get_current_number(self, max_attempts: int = 3):
        """识别突破券数量

        Args:
            max_attempts (int): 识别失败时的重试次数

        Returns:
            int: 突破券数量，未识别到时返回 -1
        """
        number = -1
        for attempt in range(max_attempts):
            if bool(event_thread):
                raise GUIStopException

            result = RuleOcr(region=(650, 0, 100, 55)).get_raw_result()
            for item in result:
                if "/30" != item.text[-3:]:
                    continue

                try:
                    number = int(item.text[:-3])
                except ValueError:
                    logger.ui_error(f"突破券识别失败: {item.text}")
                    continue
                logger.ui(f"突破券: {number}")
                return number

            if attempt < max_attempts - 1:
                sleep(1, 2)

        logger.ui_error("未识别到突破券数量，请确认画面中显示突破券数量")
        return number

    def get_jiejietupo_scene(self) -> Point | None:
        # 优先使用图像识别
        result = RuleImage(self.IMAGE_MAP_JIEJIETUPO)
        if result.match(logger_lever="ERROR"):
            logger.info("使用图像识别结界突破成功")
            return result.center_point()

        result = RuleOcr(region=(40, 600, 940, 35)).get_raw_result()
        for item in result:
            if "结界突破" in item.text:
                logger.info("使用文字识别结界突破成功")
                return item.center

        return None

    def run(self):
        while self.n < self.max:
            if bool(event_thread):
                raise GUIStopException

            logger.ui(f"第{self.n + 1}轮")
            sleep(2)

            tansuo_count = self.loop_count
            logger.ui(f"探索{tansuo_count}次")
            TanSuo(tansuo_count, temp_pop=self.has_temp_pop).run()
            self.close_tansuo()

            sleep(2)
            number = self.get_current_number()

            # 原来这里是三处连续的 sleep(2)（共 6 秒），中间只夹了一句日志；
            # 合并成一个：等待界面切换 2 秒足够，省下 4 秒/轮。
            logger.ui("正在前往 结界突破")
            sleep(2)

            point = self.get_jiejietupo_scene()
            if point:
                Mouse.click(point)
            else:
                logger.ui_error("未识别到结界突破")
                return

            sleep(2)

            if number < 0:
                # 探索次数为0时，入场前的画面可能读不到突破券，进入结界突破后再识别一次
                number = self.get_current_number(max_attempts=1)

            # TODO 判断机制
            logger.ui(f"个人突破{number}次")
            JieJieTuPoGeRen(
                number,
                flag_refresh_rule=self.flag_refresh_rule,
                flag_current_level=self.flag_current_level,
                flag_target_level=self.flag_target_level,
                flag_first_round_failure=self.flag_first_round_failure,
            ).run()
            self.close_current_scene()

            self.n += 1
