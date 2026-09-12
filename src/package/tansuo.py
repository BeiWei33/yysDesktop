from ..utils.adapter import Mouse
from ..utils.decorator import log_function_call
from ..utils.event import event_thread
from ..utils.exception import CustomException, DailyLimitException, GUIStopException
from ..utils.function import finish_random_left_right, random_normal, random_num, sleep
from ..utils.image import RuleImage, check_image_once
from ..utils.log import logger
from ..utils.point import Point
from ..utils.viewport import CANONICAL_SIZE
from .base_package import BasePackage


class TanSuoChapterUnavailable(CustomException):
    """未能切换到28章"""

    def __init__(self, *args):
        super().__init__(*args)
        logger.ui_error("异常捕获：未能切换到28章，请手动切换后重试")


class TanSuo(BasePackage):
    """探索"""

    scene_name = "探索"
    resource_path: str = "tansuo"
    resource_list = [
        "chuzhanxiaohao",
        "fighting",
        "fighting_boss",
        "quit_true",
        "tansuo",
        "tansuo_28",
        "tansuo_28_0",
        "tansuo_28_title",
        "treasure_box",
    ]
    chapter_scroll_point: tuple[int, int] = (1000, 460)
    """章节列表滑动起点（标准化坐标），取自28章列表项的历史点击位置"""
    chapter_scroll_distance: int = 240
    """章节列表每次滚轮/拖动的距离"""
    chapter_scroll_attempts: int = 6
    """每个方向、每种滑动方式的最大尝试次数"""
    chapter_fix_interval: int = 12
    """连续多少次未识别到探索界面后尝试切换28章"""
    chapter_fix_max_failures: int = 2
    """连续多少次切换28章失败后停止任务"""

    @log_function_call
    def __init__(self, n: int = 0, temp_pop: bool = False) -> None:
        super().__init__(n)
        self.has_temp_pop = temp_pop
        if self.has_temp_pop:
            logger.ui("已启用临时弹窗关闭功能")
        self.start_click_count = 0  # 连续点击IMAGE_START的次数
        self.chapter_miss_count = 0  # 连续未识别到探索界面的次数
        self.chapter_fix_failures = 0  # 连续切换28章失败的次数

    @staticmethod
    def description() -> None:
        logger.ui("提前准备好自动轮换和加成，仅单人探索")

    @staticmethod
    def view_drag_bounds() -> tuple[int, int]:
        width = CANONICAL_SIZE[0]
        return width // 2, int(width * 0.9)

    def load_asset(self):
        self.IMAGE_START = self.get_image_asset("start")
        self.IMAGE_CHUZHANXIAOHAO = self.get_image_asset("chuzhanxiaohao")
        self.IMAGE_FIGHT_BOSS = self.get_image_asset("fight_boss")
        self.IMAGE_FIGHT_LITTLE_MONSTER = self.get_image_asset("fight_little_monster")
        self.IMAGE_QUIT = self.get_image_asset("quit")
        self.IMAGE_QUIT_TRUE = self.get_image_asset("quit_true")
        self.IMAGE_TREASURE_BOX = self.get_image_asset("treasure_box")
        self.IMAGE_TANSUO_28 = self.get_image_asset("tansuo_28")
        self.IMAGE_TITLE_28 = self.get_image_asset("title_28")

    @log_function_call
    def check_title(self) -> None:
        msg_title = True
        self.current_asset_list = [
            self.IMAGE_CHUZHANXIAOHAO,
            self.IMAGE_TANSUO_28,
            self.IMAGE_TITLE_28,
        ]
        self.log_current_asset_list()

        while True:
            if bool(event_thread):
                raise GUIStopException

            if image := check_image_once(self.current_asset_list):
                logger.info(f"current image name: {image.name}")
                self.chapter_miss_count = 0
                return
            if msg_title:
                msg_title = False
                self.title_error_msg()

            self.try_fix_chapter()

    def chapter_ready(self) -> bool:
        """28章是否已经就绪

        已经显示28章标题，或点击章节列表中的28章后显示出标题，都视为就绪。

        Returns:
            bool: 是否已处于28章
        """
        if RuleImage(self.IMAGE_TITLE_28).match():
            return True

        entry = RuleImage(self.IMAGE_TANSUO_28)
        if not entry.match():
            return False

        logger.ui("点击章节列表中的28章")
        Mouse.click(entry.center_point())
        sleep(2, 3)  # 等待切换章节的动画
        return RuleImage(self.IMAGE_TITLE_28).match()

    def scroll_chapter_list(self, direction: int, use_drag: bool = False) -> None:
        """在章节列表上滑动

        Args:
            direction (int): -1 向列表末尾（28章方向）翻，1 向列表开头翻
            use_drag (bool): 使用拖动代替滚轮
        """
        Mouse.move(point=Point(*self.chapter_scroll_point))
        sleep(0.2, 0.4)
        if use_drag:
            logger.info(f"拖动章节列表 direction={direction}")
            Mouse.drag(0, direction * self.chapter_scroll_distance, random_num(0.4, 0.6))
        else:
            logger.info(f"滚动章节列表 direction={direction}")
            Mouse.scroll(direction * self.chapter_scroll_distance)

    def ensure_chapter_28(self) -> bool | None:
        """确保当前选择的是28章

        游戏有时会停留在其它章节，此时识别不到28章，需要滑动右侧章节列表
        找到并点击28章。拖动和滚轮都会尝试，且两个方向都会尝试，避免方向判断错误。

        Returns:
            bool | None: True 已切换到28章，False 在探索界面但切换失败，
                None 当前不在探索界面（不做处理，继续等待）
        """
        if self.chapter_ready():
            return True

        for use_drag in (True, False):
            for direction in (-1, 1):
                for _ in range(self.chapter_scroll_attempts):
                    if bool(event_thread):
                        raise GUIStopException

                    if self.chapter_ready():
                        return True

                    # 不在探索界面时不要乱滑，避免影响其它界面的列表
                    if not RuleImage(self.IMAGE_START).match():
                        logger.ui_warn("当前不在探索界面，停止滑动章节列表")
                        return None

                    self.scroll_chapter_list(direction, use_drag=use_drag)
                    sleep(0.6, 1.0)

        logger.ui_error("未识别到28章，请手动切换章节")
        return False

    def try_fix_chapter(self) -> None:
        """连续多次未识别到探索界面时，尝试切换到28章"""
        self.chapter_miss_count += 1
        if self.chapter_miss_count < self.chapter_fix_interval:
            return

        self.chapter_miss_count = 0
        result = self.ensure_chapter_28()
        if result is None:  # 还没进入探索界面，继续等待
            return
        if result:
            self.chapter_fix_failures = 0
            return

        self.chapter_fix_failures += 1
        if self.chapter_fix_failures >= self.chapter_fix_max_failures:
            raise TanSuoChapterUnavailable("未识别到28章，已停止探索任务")

    @log_function_call
    def fight(self) -> None:
        flag_done: bool = False  # 是否已经结束
        point = None
        sleep(2)
        while True:
            if bool(event_thread):
                raise GUIStopException

            # 如果匹配到小怪的按钮，返回上一级
            if not flag_done and RuleImage(self.IMAGE_FIGHT_LITTLE_MONSTER).match():
                logger.ui_warn("未进入战斗，重新匹配")
                return
            # 如果匹配到临时弹窗，点击关闭
            if self.has_temp_pop and RuleImage(self.global_assets.IMAGE_TEMP_POP).match():
                finish_random_left_right()
                logger.ui("关闭临时弹窗")
                sleep(2)
                continue

            _result = check_image_once(
                [
                    # self.global_image.IMAGE_VICTORY,
                    self.global_assets.IMAGE_FINISH,
                    *self.global_assets.ALL_FAIL_IMAGES,
                ]
            )
            if _result:
                flag_done = True
                logger.ui_warn(f"战斗结束{('（' + _result.description + '）') if _result.description else ''}")
                if point is None:
                    point = finish_random_left_right()
                else:
                    Mouse.click(point)
                sleep(2)
            elif flag_done:  # 没有匹配到图像，说明已经结束结算
                logger.ui("战斗结束")
                return

    @log_function_call
    def finish(self) -> None:
        """boss战后的结束阶段

        1.有掉落物，不需要点击，直接左上角退出即可

        2.无掉落物，系统自动跳转出去

        3.1、2出来之后，存在宝箱/妖气封印的可能，当前章节的小界面被关闭，需要右侧列表重新点开
        """
        while True:
            if bool(event_thread):
                raise GUIStopException

            # 等待加载完毕
            sleep(1.5, 2)

            # 如果还在探索里，说明有掉落物，直接退出
            if RuleImage(self.IMAGE_CHUZHANXIAOHAO).match():
                logger.ui("有掉落物，直接退出")
                self.check_click(self.IMAGE_QUIT, timeout=3)
                sleep(1)
                self.check_click(self.IMAGE_QUIT_TRUE, timeout=5)

            # 在探索进入的前置界面
            else:
                image_start = RuleImage(self.IMAGE_START)
                image_treasure_box = RuleImage(self.IMAGE_TREASURE_BOX)
                if image_start.match():
                    logger.ui("探索结束")
                # 宝箱
                elif image_treasure_box.match():
                    Mouse.click(image_treasure_box.center_point())
                    logger.info("获得宝箱")
                    Mouse.click(wait=2)
                # 不管有没有宝箱，都退出这次探索
                return

    def run(self):
        self.check_title()
        self.current_asset_list = [
            self.IMAGE_CHUZHANXIAOHAO,
            self.IMAGE_TANSUO_28,
            self.IMAGE_TITLE_28,
            self.IMAGE_START,
        ]

        while self.n < self.max:
            if bool(event_thread):
                raise GUIStopException

            result = check_image_once(self.current_asset_list)
            if result is None:
                # 游戏可能停留在其它章节，导致识别不到28章
                self.try_fix_chapter()
                continue

            self.chapter_miss_count = 0
            logger.info(f"current result name: {result.name}")
            match result.name:
                case self.IMAGE_TANSUO_28.name:  # 右侧列表按钮
                    Mouse.click(result.center_point())
                    sleep(3)  # 等待行动动画

                case self.IMAGE_TITLE_28.name:
                    logger.ui("准备进入探索")
                    self.check_click(self.IMAGE_START)
                    self.start_click_count += 1
                    if self.start_click_count >= 3:
                        logger.ui_warn("尝试进入探索失败3次")
                        self.start_click_count = 0  # 重置计数器
                        raise DailyLimitException("探索次数已达本日上限")
                    sleep(2)

                case self.IMAGE_CHUZHANXIAOHAO.name:
                    self.start_click_count = 0  # 成功进入探索，重置计数器
                    # 先判断boss面灵气
                    sleep()
                    result = RuleImage(self.IMAGE_FIGHT_BOSS)
                    if result.match():
                        Mouse.click(result.center_point())
                        logger.ui("BOSS")
                        self.fight()
                        self.finish()
                        self.done()

                    else:
                        result = RuleImage(self.IMAGE_FIGHT_LITTLE_MONSTER)
                        if result.match(score=0.6):
                            Mouse.click(result.center_point())
                            logger.ui("小怪")
                            self.fight()
                        else:
                            logger.ui("移动视角")
                            sleep()
                            y1 = 300
                            y2 = 550
                            x_middle, x_right = self.view_drag_bounds()
                            x = random_normal(x_middle, x_right)
                            # 移动到窗口中心线右侧
                            Mouse.move(
                                point=Point(x, random_num(y1, y2)),
                                duration=random_num(0.5, 0.8),
                            )
                            Mouse.drag((x_middle - x) * 2, 0, random_num(0.5, 0.8))
                            logger.info(f"move width: {(x_middle - x) * 2}")
