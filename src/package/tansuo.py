from ..utils.adapter import KeyBoard, Mouse
from ..utils.config import config
from ..utils.decorator import log_function_call
from ..utils.emulator import emulator
from ..utils.event import event_thread
from ..utils.exception import CustomException, DailyLimitException, GUIStopException
from ..utils.function import finish_random_left_right, random_normal, random_num, sleep, wait_until
from ..utils.image import RuleImage, check_image_once
from ..utils.log import logger
from ..utils.paddleocr import RuleOcr
from ..utils.point import Point
from ..utils.screenshot import ScreenShot
from ..utils.viewport import CANONICAL_SIZE
from .base_package import BasePackage

CHINESE_DIGITS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def parse_chapter_number(text: str) -> int | None:
    """从「第X章」文本解析章节号

    Args:
        text (str): OCR 文本，例如「第二十八章」

    Returns:
        int | None: 章节号，无法解析时返回 None
    """
    if "章" not in text or "第" not in text:
        return None

    body = text.split("第", 1)[1].split("章", 1)[0].strip()
    if not body:
        return None
    if body.isdigit():
        return int(body)

    total = 0
    unit = 1
    for char in reversed(body):
        if char == "十":
            unit = 10
            continue
        digit = CHINESE_DIGITS.get(char)
        if digit is None:
            return None
        total += digit * unit
        unit *= 10

    if total == 0 and "十" in body:
        total = 10
    return total or None


class TanSuoChapterUnavailable(CustomException):
    """未能切换到探索目标章节"""

    def __init__(self, *args, chapter: int | None = None):
        super().__init__(*args)
        if chapter:
            logger.ui_error(f"异常捕获：未能切换到{chapter}章，请手动切换后重试")
        else:
            logger.ui_error("异常捕获：未能切换到探索目标章节，请手动切换后重试")


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
        "yard_tansuo",
    ]
    chapter_list_region: tuple[int, int, int, int] = (930, 150, 206, 420)
    """章节列表区域（左, 上, 宽, 高），用于识别「第X章」文字"""
    chapter_number_region: tuple[int, int, int, int] = (140, 0, 280, 55)
    """章节详情页左上角的章节号区域（左, 上, 宽, 高）"""
    chapter_row_spacing: int = 94
    """章节列表行间距（实测），用于推断被截断识别不到的下一行"""
    target_chapter: int = 28
    """目标章节号"""
    chapter_scroll_point: tuple[int, int] = (1000, 360)
    """章节列表滑动起点（标准化坐标），位于列表中间，上下滑动都不会滑出窗口"""
    chapter_drag_distance: int = 200
    """章节列表每次拖动的距离（过大时会拖到窗口外触发回弹）"""
    chapter_scroll_distance: int = 240
    """章节列表每次滚轮的距离（120 的整数倍，实测约移动 1 章）"""
    chapter_drag_attempts: int = 12
    """拖动方式的最大尝试次数（实测一次拖动约移动 3 章）"""
    chapter_scroll_attempts: int = 12
    """滚轮方式的最大尝试次数（实测一次滚轮约移动 1 章，作为兜底手段）"""
    chapter_no_movement_limit: int = 4
    """连续多少次滑动后列表没有变化，就换下一种滑动方式"""
    chapter_click_failure_limit: int = 4
    """识别到目标章节但点击无效多少次后停止尝试（避免一直点同一个位置）"""
    chapter_switch_attempts: int = 5
    """点击目标章节后等待标题出现的检查次数"""
    chapter_fix_interval: int = 12
    """连续多少次未识别到探索界面后尝试切换目标章节"""
    chapter_fix_max_failures: int = 2
    """连续多少次切换目标章节失败后停止任务"""
    chapter_unknown_limit: int = 5
    """连续多少次界面完全无法识别（既不是章节列表也不是详情页）后停止任务"""
    yard_click_limit: int = 3
    """连续点多少次庭院探索入口仍回不到探索界面后停止任务"""
    retreat_limit: int = 3
    """逐层回退时最多退几层（关掉个人突破等场景后可能落在多层子界面里）"""
    back_key_limit: int = 2
    """单次逐层回退里最多按几次安卓返回键（按了必须验证界面变化，没变化立即停）"""
    back_key_total_limit: int = 4
    """多次逐层回退累计按返回键的上限（防止每次调用都按两次而无限循环）"""
    exit_button_texts: tuple[str, ...] = ("返回", "关闭", "退出", "返回庭院", "关闭界面")
    """文字识别找出口按钮时的文案（精确匹配，避免点到含同样字样的标题上）"""
    exit_game_markers: tuple[str, ...] = ("退出游戏", "退出客户端", "退出程序", "结束游戏")
    """按返回键后可能出现的「退出游戏」弹窗特征词"""
    cancel_button_texts: tuple[str, ...] = ("取消", "取消退出")
    """「退出游戏」弹窗里必须点的按钮（绝不能点确定，那会把游戏关掉）"""

    @log_function_call
    def __init__(self, n: int = 0, temp_pop: bool = False) -> None:
        super().__init__(n)
        self.has_temp_pop = temp_pop
        if self.has_temp_pop:
            logger.ui("已启用临时弹窗关闭功能")
        self.target_chapter = self.configured_chapter()
        if self.target_chapter == 0:
            logger.ui("探索目标章节：不校验（跟随当前章节）")
        elif self.target_chapter != type(self).target_chapter:
            logger.ui(f"探索目标章节：第{self.target_chapter}章")
        self.start_click_count = 0  # 连续点击IMAGE_START的次数
        self.chapter_miss_count = 0  # 连续未识别到探索界面的次数
        self.chapter_fix_failures = 0  # 连续切换目标章节失败的次数
        self.chapter_unknown_count = 0  # 连续界面无法识别的次数（空转保护）
        self.yard_click_count = 0  # 连续点庭院探索入口仍回不去探索界面的次数
        self.last_retreat_layers = 0  # 上一次逐层回退实际退了几层（用于日志）
        self.back_key_count = 0  # 本次逐层回退已按了几次返回键
        self.back_key_total_count = 0  # 多次逐层回退累计按返回键的次数（上限保护）

    @staticmethod
    def configured_chapter() -> int:
        """从配置读取探索目标章节，0 表示不做章节校验"""
        try:
            chapter = int(getattr(config.user, "tansuo_target_chapter", 28))
        except (TypeError, ValueError):
            return 28
        return chapter if 0 <= chapter <= 28 else 28

    def chapter_assets(self) -> list:
        """28 章专属素材，目标章节不是 28 时不参与匹配"""
        if self.target_chapter == 28:
            return [self.IMAGE_TANSUO_28, self.IMAGE_TITLE_28]
        return []

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
        self.IMAGE_YARD_TANSUO = self.get_image_asset("yard_tansuo")

    @log_function_call
    def check_title(self) -> None:
        msg_title = True
        self.current_asset_list = [
            self.IMAGE_CHUZHANXIAOHAO,
            self.IMAGE_START,
            *self.chapter_assets(),
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
                # 顺手记一下当前识别到的界面，便于判断落在哪一层
                logger.info(f"check_title 无法识别探索界面，当前识别到：{self.describe_screen()}")

            # 目标章节不是 28 章时没有对应的列表/标题素材，改为按文字识别进入目标章节
            if self.target_chapter not in (0, 28) and self.chapter_ready():
                self.chapter_miss_count = 0
                return

            self.try_fix_chapter()

    def chapter_ready(self) -> bool:
        """目标章节是否已经就绪

        已经显示目标章节标题或当前章节号就是目标章节，说明已经就绪；
        否则在章节列表里按识别到的文字位置点击目标章节，避免图像误匹配到其它章节。
        目标章节为 0 时表示不做章节校验（角色进度只解锁了少数章节时用）。

        Returns:
            bool: 是否已处于目标章节
        """
        if self.target_chapter == 0:
            return True

        if self.on_target_chapter():
            return True

        point = self.find_chapter_entry(self.target_chapter)
        if point is None:
            return False

        return self.click_chapter_entry(point)

    def click_chapter_entry(self, point: Point) -> bool:
        """点击章节条目并等待切换完成

        Args:
            point (Point): 章节条目坐标

        Returns:
            bool: 是否成功切换到目标章节
        """
        logger.ui(f"点击章节列表中的{self.target_chapter}章")
        Mouse.click(point)

        # 切换章节有动画，标题和章节号不是立刻出现
        for _ in range(self.chapter_switch_attempts):
            if bool(event_thread):
                raise GUIStopException

            sleep(1)
            if self.on_target_chapter():
                return True
        return False

    def on_target_chapter(self) -> bool:
        """当前是否已经是目标章节（标题已显示，或章节号就是目标章节）"""
        if self.target_chapter == 28 and RuleImage(self.IMAGE_TITLE_28).match():
            return True
        if self.target_chapter == 0:
            return True
        return self.current_chapter() == self.target_chapter

    def current_chapter(self) -> int | None:
        """识别当前章节号（章节详情页左上角）

        Returns:
            int | None: 章节号，识别不到时返回 None
        """
        for item in RuleOcr(region=self.chapter_number_region).get_raw_result():
            number = parse_chapter_number(item.text)
            if number is not None:
                logger.info(f"当前章节：{number}")
                return number
        return None

    def find_chapter_entry(self, number: int) -> Point | None:
        """在章节列表里按文字识别定位指定章节

        Args:
            number (int): 章节号

        Returns:
            Point | None: 章节条目中心坐标，识别不到时返回 None
        """
        for item in RuleOcr(region=self.chapter_list_region).get_raw_result():
            if parse_chapter_number(item.text) == number:
                logger.info(f"章节列表中找到第{number}章：{item.center}")
                return item.center
        return None

    def chapter_items(self) -> list[tuple[int, Point]]:
        """识别章节列表，返回可见章节的章节号与坐标

        Returns:
            list[tuple[int, Point]]: [(章节号, 条目中心坐标)]，识别不到时为空列表
        """
        items: list[tuple[int, Point]] = []
        for item in RuleOcr(region=self.chapter_list_region).get_raw_result():
            number = parse_chapter_number(item.text)
            if number is not None:
                items.append((number, item.center))

        if items:
            logger.info(f"当前可见章节：{[number for number, _ in items]}")
        return items

    def visible_chapters(self) -> list[int]:
        """识别章节列表当前可见的章节号

        Returns:
            list[int]: 可见的章节号列表，识别不到时为空列表
        """
        return [number for number, _ in self.chapter_items()]

    def chapter_list_visible(self) -> bool:
        """章节列表是否可见（识别到至少一个「第X章」）"""
        return bool(self.chapter_items())

    def scroll_chapter_list(self, direction: int, use_drag: bool = False) -> None:
        """在章节列表上滑动

        Args:
            direction (int): -1 向列表末尾（章节号增大方向）翻，1 向列表开头翻
            use_drag (bool): 使用拖动代替滚轮
        """
        Mouse.move(point=Point(*self.chapter_scroll_point))
        sleep(0.2, 0.4)
        if use_drag:
            logger.info(f"拖动章节列表 direction={direction}")
            Mouse.drag(0, direction * self.chapter_drag_distance, random_num(0.4, 0.6))
        else:
            logger.info(f"滚动章节列表 direction={direction}")
            Mouse.scroll(direction * self.chapter_scroll_distance)

    def back_to_chapter_list(self, max_attempts: int = 3) -> bool:
        """从章节详情页返回章节列表

        章节详情页看不到章节列表，需要点击左上角的返回按钮回到列表。

        Args:
            max_attempts (int): 最大尝试次数

        Returns:
            bool: 是否已返回章节列表
        """
        for _ in range(max_attempts):
            if bool(event_thread):
                raise GUIStopException

            if self.chapter_list_visible():
                return True

            result = RuleImage(self.IMAGE_QUIT)  # 左上角返回按钮
            if not result.match():
                logger.ui_warn("未识别到左上角返回按钮，无法返回章节列表")
                return False

            logger.ui("点击左上角返回章节列表")
            Mouse.click(result.center_point())
            # 等待返回动画：轮询到章节列表出现就继续，最多等 3 秒
            # （与原来的 sleep(2, 3) 上限一致，只是提前结束等待）
            wait_until(self.chapter_list_visible, timeout=3.0, caller_name="back_to_chapter_list")

        return self.chapter_list_visible()

    def chapter_list_bottom(self) -> int:
        """章节列表可视区域的底边（留半行余量）"""
        _, top, _, height = self.chapter_list_region
        return top + height - self.chapter_row_spacing // 2

    def target_entry_point(self, items: list[tuple[int, Point]]) -> Point | None:
        """在识别结果里定位目标章节的坐标

        优先使用直接识别到的目标章节；如果最后一行是目标章节的上一章，且目标行仍落在
        列表可视区域内，说明目标章节就在它下面一行（最后一行常被截断识别，例如
        「第二十八章」只识别出「十八」），按实测行间距推断坐标。

        如果推断出的位置已经超出列表可视区域，说明目标章节还在下面看不见，
        此时返回 None 让调用方继续滑动，等它露出来后再直接按文字识别点击。
        点击后仍会用章节号校验，推断错误不会误切章节。

        Args:
            items (list[tuple[int, Point]]): chapter_items() 的结果

        Returns:
            Point | None: 目标章节坐标，无法定位时返回 None
        """
        for number, point in items:
            if number == self.target_chapter:
                return point

        if not items:
            return None

        last_number, last_point = max(items, key=lambda item: item[1].client_y)
        if last_number != self.target_chapter - 1:
            return None

        inferred_y = last_point.client_y + self.chapter_row_spacing
        if inferred_y > self.chapter_list_bottom():
            logger.info(f"第{self.target_chapter}章还在列表下方看不见，继续滑动")
            return None

        logger.info(f"识别到第{last_number}章，按行间距推断第{self.target_chapter}章位置")
        return Point(last_point.client_x, inferred_y)

    def ensure_target_chapter(self) -> bool | None:
        """确保当前选择的是目标章节

        游戏有时会停留在其它章节，此时识别不到目标章节：
        - 在章节详情界面：先点左上角返回章节列表；
        - 在章节列表界面：滑动列表找到并点击目标章节，拖动和滚轮、两个方向都会尝试。
        目标章节为 0 时不做章节校验，直接返回 True。

        Returns:
            bool | None: True 已处于目标章节，False 在章节列表界面但切换失败，
                None 当前不在可处理的界面（不做处理，继续等待）
        """
        if self.target_chapter == 0:
            return True

        if self.chapter_ready():
            return True

        current = self.current_chapter()
        if current is not None and current != self.target_chapter:
            logger.ui_warn(f"当前是第{current}章详情页，尝试返回章节列表")
            if not self.back_to_chapter_list():
                return None
            if self.chapter_ready():
                return True

        click_failures = 0
        for use_drag, attempts in (
            (True, self.chapter_drag_attempts),
            (False, self.chapter_scroll_attempts),
        ):
            for direction in (-1, 1):
                previous: list[int] = []
                no_movement = 0
                for _ in range(attempts):
                    if bool(event_thread):
                        raise GUIStopException

                    # 目标章节标题已出现（仅 28 章有标题素材，模板匹配开销很小）
                    if self.target_chapter == 28 and RuleImage(self.IMAGE_TITLE_28).match():
                        return True

                    # 看不到章节列表说明不在探索界面，不要乱滑，避免影响其它界面
                    items = self.chapter_items()
                    if not items:
                        logger.ui_warn("当前看不到章节列表，停止滑动")
                        return None

                    numbers = [number for number, _ in items]
                    if numbers == previous:
                        no_movement += 1
                        if no_movement >= self.chapter_no_movement_limit:
                            logger.ui_warn("章节列表没有变化，换一种滑动方式")
                            break
                    else:
                        # 界面日志也记录可见章节，便于只看界面日志时定位问题
                        logger.ui(f"当前可见章节：{numbers}")
                        no_movement = 0
                    previous = numbers

                    # 已经能看到目标章节就直接点击（文字识别定位，避免图像误匹配）
                    target = self.target_entry_point(items)
                    if target is not None:
                        if self.click_chapter_entry(target):
                            return True

                        # 点击无效时不能原地重复点击，否则会一直卡在同一个位置
                        click_failures += 1
                        if click_failures >= self.chapter_click_failure_limit:
                            logger.ui_error(f"识别到{self.target_chapter}章但点击无效，请手动切换章节")
                            return False
                        logger.ui_warn(f"点击{self.target_chapter}章后未切换成功，滑动后重试")

                    self.scroll_chapter_list(direction, use_drag=use_drag)
                    sleep(1.0, 1.3)  # 等待滚动动画结束再识别

        logger.ui_error(f"未识别到{self.target_chapter}章，请手动切换章节")
        return False

    def back_to_exploration_from_yard(self) -> bool:
        """在庭院时点击「探索」入口，尝试回到探索界面

        探索/绘卷跑完一轮退出后，游戏可能直接回到庭院（桌面版会停在章节列表，
        手机版退出层级更深）。庭院里探索入口是一个挂着的灯笼按钮（竖排「探索」文字），
        点它即可回到探索界面。

        Returns:
            bool: 是否识别到庭院并点击了探索入口（不代表一定进入探索界面）
        """
        rule = RuleImage(self.IMAGE_YARD_TANSUO)
        if not rule.match():
            return False

        logger.ui("当前在庭院，点击探索入口")
        Mouse.click(rule.center_point())
        # 等进入探索界面的过场：轮询到不再是庭院就继续，最多 4 秒
        wait_until(
            lambda: not RuleImage(self.IMAGE_YARD_TANSUO).match(),
            timeout=4.0,
            caller_name="back_to_exploration_from_yard",
        )
        return True

    def recognize_current_screen(self) -> str:
        """判断当前落在哪一层界面

        关掉个人突破等场景后，游戏可能停在任意子界面，需要先认清所在位置再决定动作。

        Returns:
            str: "chapter_list"（章节列表）/ "chapter_detail"（章节详情）/ "yard"（庭院）
                / "unknown"（不认识）
        """
        if self.chapter_list_visible():
            return "chapter_list"
        if self.current_chapter() is not None:
            return "chapter_detail"
        if RuleImage(self.IMAGE_YARD_TANSUO).match():
            return "yard"
        return "unknown"

    def describe_screen(self) -> str:
        """把当前界面转成可读文案，方便写进日志"""
        return {
            "chapter_list": "章节列表",
            "chapter_detail": "章节详情页",
            "yard": "庭院",
        }.get(self.recognize_current_screen(), "无法识别的界面")

    def find_exit_button_by_text(self) -> Point | None:
        """文字识别找「返回/关闭/退出」这类出口按钮

        精确匹配短文案：弹窗标题（例如「确定退出游戏吗？」）里也含这些词，
        用包含匹配会点到标题上。

        Returns:
            Point | None: 出口按钮坐标，没找到返回 None
        """
        for item in RuleOcr().get_raw_result():
            if item.text.strip() in self.exit_button_texts:
                logger.info(f"文字识别到出口按钮：{item.text}")
                return item.center
        return None

    def dismiss_exit_game_dialog(self) -> bool:
        """按返回键后可能弹出「确定退出游戏吗？」，这时必须点「取消」

        点确定会把游戏关掉，所以这里只精确匹配「取消」。

        Returns:
            bool: 是否检测到退出游戏弹窗（检测到就算被拦下，调用方应停止回退）
        """
        items = RuleOcr().get_raw_result()
        hit_dialog = any(
            any(marker in item.text for marker in self.exit_game_markers) for item in items
        )
        if not hit_dialog:
            return False

        for item in items:
            if item.text.strip() in self.cancel_button_texts:
                logger.ui("检测到退出游戏弹窗，点击取消")
                Mouse.click(item.center)
                return True

        logger.ui_warn("检测到退出游戏弹窗但没找到取消按钮，已停止回退")
        return True

    def press_back_key(self) -> bool:
        """按一次安卓返回键（仅模拟器模式）

        返回键在多数界面等效于"返回上一层"，但庭院等界面可能弹出「确定退出游戏吗？」，
        所以按完必须立刻检查弹窗，一旦出现就点取消并停止。

        Returns:
            bool: 是否确实按下了返回键（被退出游戏弹窗拦下时返回 False）
        """
        logger.ui("逐层回退：按安卓返回键")
        self.back_key_count += 1
        self.back_key_total_count += 1
        KeyBoard.esc()
        sleep(0.5, 1.0)

        if self.dismiss_exit_game_dialog():
            logger.ui_warn("返回键触发了退出游戏弹窗，已点取消并停止回退")
            return False
        return True

    def screen_changed(self, timeout: float = 3.0) -> bool:
        """验证操作之后界面确实变了（不再处于"不认识"的状态）"""
        return wait_until(
            lambda: self.recognize_current_screen() != "unknown",
            timeout=timeout,
            caller_name="return_home",
        )

    def retreat_once(self, layer: int) -> bool:
        """在不认识的界面上做一次"往上退"的尝试

        按优先级依次尝试，命中即止（每一步点完都要验证界面真的变了）：
        1. 左上角返回素材（IMAGE_QUIT）
        2. 文字识别「返回/关闭/退出」
        3. 安卓返回键（仅模拟器模式，且次数受限）

        Returns:
            bool: 是否成功做了一次动作并且界面确实变了
        """
        # 1. 左上角返回素材
        rule = RuleImage(self.IMAGE_QUIT)
        if rule.match():
            logger.ui(f"逐层回退（第{layer}层）：尝试点击左上角返回")
            Mouse.click(rule.center_point())
            self.last_retreat_layers += 1
            if self.screen_changed():
                return True
            logger.ui_warn("点击返回后界面没有变化，停止回退")
            return False

        # 2. 文字识别出口按钮
        point = self.find_exit_button_by_text()
        if point is not None:
            logger.ui(f"逐层回退（第{layer}层）：尝试文字识别返回")
            Mouse.click(point)
            self.last_retreat_layers += 1
            if self.screen_changed():
                return True
            logger.ui_warn("点击文字识别的出口后界面没有变化，停止回退")
            return False

        # 3. 安卓返回键（桌面版不发，避免把 ESC 当返回键用）
        if emulator.enabled and self.back_key_count < self.back_key_limit:
            acted = self.press_back_key()
            if not acted:
                return False
            self.last_retreat_layers += 1
            if self.screen_changed():
                return True
            logger.ui_warn("按返回键后界面没有变化，停止回退")
            return False

        logger.info(
            f"第{layer}层：界面不认识（{self.describe_screen()}），"
            f"且没有可用的出口（返回素材未命中、文字未识别、返回键不可用）"
        )
        return False

    def return_home(self) -> bool:
        """逐层退回可处理的探索界面

        每层按优先级找出口，命中即止、操作完必须验证界面真的变了：
        - 庭院：点「探索」灯笼（素材命中才点）
        - 章节列表/章节详情：直接算回到家，交给原有流程
        - 其它不认识的界面：左上角返回素材 → 文字识别返回/关闭/退出 → 安卓返回键
        任何一步操作完界面没变化就立刻停止，绝不连点。

        Returns:
            bool: 是否回到了可处理的界面
        """
        self.last_retreat_layers = 0
        self.back_key_count = 0  # 只统计本次调用按了几次返回键

        for layer in range(1, self.retreat_limit + 1):
            if bool(event_thread):
                raise GUIStopException

            screen = self.recognize_current_screen()
            if screen in ("chapter_list", "chapter_detail"):
                if self.last_retreat_layers:
                    logger.ui(f"已回退 {self.last_retreat_layers} 层，回到{self.describe_screen()}")
                self.back_key_total_count = 0
                return True

            if screen == "yard":
                self.yard_click_count += 1
                self.last_retreat_layers += 1
                if not self.back_to_exploration_from_yard():
                    return False
                # 点在庭院这一层只点一次：还在庭院就把结果交回上层按次数上限处理，
                # 避免对着同一个位置连续猛点
                return self.recognize_current_screen() in ("chapter_list", "chapter_detail")

            if not self.retreat_once(layer):
                return False

        screen = self.recognize_current_screen()
        if screen in ("chapter_list", "chapter_detail"):
            return True
        logger.ui_warn(f"已回退{self.last_retreat_layers}层仍未回到探索界面（当前：{self.describe_screen()}）")
        return False

    def try_fix_chapter(self, force: bool = False) -> None:
        """尝试切换到目标章节

        Args:
            force (bool): 忽略连续未识别的计数，立即尝试

        Raises:
            TanSuoChapterUnavailable: 界面长时间无法识别，或逐层回退后仍然回不去
        """
        self.chapter_miss_count += 1
        if not force and self.chapter_miss_count < self.chapter_fix_interval:
            return

        self.chapter_miss_count = 0
        result = self.ensure_target_chapter()
        if result is None:
            # 退出探索/关掉个人突破后可能落到庭院或其它子界面：先逐层回退试试
            if self.return_home():
                self.chapter_unknown_count = 0
                self.yard_click_count = 0
                self.back_key_total_count = 0
                return

            if self.last_retreat_layers:
                # 已经做过回退动作（点了庭院入口/返回按钮/按了返回键），不算"界面不认识"的空转，
                # 但这些动作反复无效仍要停下来，避免一直退不出去
                if self.yard_click_count > self.yard_click_limit:
                    raise TanSuoChapterUnavailable(
                        "点击探索入口后仍未进入探索界面，已停止探索任务（请手动确认游戏画面）"
                    )
                if self.back_key_total_count >= self.back_key_total_limit:
                    raise TanSuoChapterUnavailable(
                        f"多次尝试返回（累计按返回键{self.back_key_total_count}次）仍无法回到探索界面，"
                        f"已停止探索任务（最后识别到：{self.describe_screen()}；请手动确认游戏画面）"
                    )
                return

            # 回退不了就不能无限等下去（原来这里不计失败次数，会一直空转）
            self.chapter_unknown_count += 1
            if self.chapter_unknown_count >= self.chapter_unknown_limit:
                raise TanSuoChapterUnavailable(
                    "连续多次看不到章节列表，已停止探索"
                    f"（已尝试逐层回退{self.last_retreat_layers}层，最后识别到：{self.describe_screen()}；"
                    "请确认游戏在探索界面，或目标章节设置是否正确）"
                )
            return

        self.chapter_unknown_count = 0
        self.yard_click_count = 0
        self.back_key_total_count = 0
        if result:
            self.chapter_fix_failures = 0
            return

        self.chapter_fix_failures += 1
        if self.chapter_fix_failures >= self.chapter_fix_max_failures:
            raise TanSuoChapterUnavailable(
                f"未识别到{self.target_chapter}章，已停止探索任务", chapter=self.target_chapter
            )

    @log_function_call
    def fight(self) -> None:
        flag_done: bool = False  # 是否已经结束
        point = None
        sleep(2)
        while True:
            if bool(event_thread):
                raise GUIStopException

            # 一次截图复用给本轮三个判断：中间没有点击，帧不会变（战斗轮询很密集，
            # 每次少截两帧，模拟器模式下每轮大约省 0.7 秒）
            screenshot = ScreenShot()
            # 如果匹配到小怪的按钮，返回上一级
            if not flag_done and RuleImage(self.IMAGE_FIGHT_LITTLE_MONSTER).match(screenshot):
                logger.ui_warn("未进入战斗，重新匹配")
                return
            # 如果匹配到临时弹窗，点击关闭
            if self.has_temp_pop and RuleImage(self.global_assets.IMAGE_TEMP_POP).match(screenshot):
                finish_random_left_right()
                logger.ui("关闭临时弹窗")
                sleep(2)
                continue

            _result = None
            for asset in (self.global_assets.IMAGE_FINISH, *self.global_assets.ALL_FAIL_IMAGES):
                rule = RuleImage(asset)
                if rule.match(screenshot):
                    _result = rule
                    break
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

            # 这里必须等结算界面彻底稳定再判断：曾经用「等到素材出现就立刻继续」替代固定等待，
            # 结果动画没结束就点了「退出」，确认框没弹出来，后面 quit_true 必然超时
            # （提速改动踩了自己定的规则：等到的这一帧本身可能来得太早）。
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
            self.IMAGE_START,
            *self.chapter_assets(),
        ]

        while self.n < self.max:
            if bool(event_thread):
                raise GUIStopException

            result = check_image_once(self.current_asset_list)
            if result is None:
                if self.target_chapter != 0 and self.chapter_ready():
                    # 章节列表界面：点进目标章节后继续循环
                    continue
                # 游戏可能停留在其它章节，导致识别不到目标章节
                self.try_fix_chapter()
                continue

            self.chapter_miss_count = 0
            logger.info(f"current result name: {result.name}")
            match result.name:
                case self.IMAGE_TANSUO_28.name:  # 右侧列表按钮
                    # 图像匹配可能误命中「第二十X章」，用文字识别确认后再点击
                    point = self.find_chapter_entry(self.target_chapter)
                    if point is None:
                        logger.ui_warn(f"列表图像匹配到但未识别到{self.target_chapter}章，改为滑动章节列表")
                        self.try_fix_chapter(force=True)
                        continue
                    Mouse.click(point)
                    # 等待行动动画：轮询到章节详情/探索入口出现就继续，最多等 3 秒
                    # （与原来的 sleep(3) 上限一致）。这里只等"目标界面"，不等刚点过的
                    # 章节列表按钮，避免动画还没结束就重复点击同一处。
                    self.wait_frame(
                        [self.IMAGE_START, self.IMAGE_CHUZHANXIAOHAO, *self.chapter_assets()],
                        timeout=3.0,
                    )

                case self.IMAGE_TITLE_28.name | self.IMAGE_START.name:
                    logger.ui("准备进入探索")
                    self.check_click(self.IMAGE_START)
                    self.start_click_count += 1
                    if self.start_click_count >= 3:
                        logger.ui_warn("尝试进入探索失败3次")
                        self.start_click_count = 0  # 重置计数器
                        raise DailyLimitException("探索次数已达本日上限")
                    # 等待进入探索：轮询到探索地图出现就继续，最多等 2 秒（原来固定 sleep(2)）
                    self.wait_frame([self.IMAGE_CHUZHANXIAOHAO], timeout=2.0)

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
