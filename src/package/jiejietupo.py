import contextlib
import time
from enum import Enum
from typing import Literal

from PIL import Image

from ..utils.adapter import KeyBoard, Mouse
from ..utils.decorator import log_function_call
from ..utils.event import event_thread
from ..utils.emulator import emulator
from ..utils.exception import CustomException, GUIStopException
from ..utils.function import finish_random_left_right, random_point, sleep
from ..utils.image import RuleImage
from ..utils.log import logger
from ..utils.paddleocr import RuleOcr
from ..utils.point import Point
from ..utils.screenshot import ScreenShot
from .base_package import BasePackage


class LineupState(Enum):
    """阵容锁定状态"""

    NONE = 0
    LOCK = 1
    UNLOCK = 2


class LiaoTuPoFullException(CustomException):
    """寮突破已满"""

    def __init__(self, *args):
        super().__init__(*args)
        logger.ui_warn("异常捕获：寮突破已满")


class JieJieTuPoTargetUnavailable(Exception):
    """目标结界已经进入不可挑战状态。"""


class JieJieTuPoLineupStateError(CustomException):
    """无法确认个人突破阵容的锁定状态。"""


class JieJieTuPoReadyTimeout(CustomException):
    """主动退级时未在限定时间内识别到准备界面。"""


class JieJieTuPoBattleResultTimeout(CustomException):
    """未能稳定确认卡级战斗的结算状态。"""


class JieJieTuPo(BasePackage):
    """结界突破"""

    scene_name: str = "结界突破"
    resource_path: str = "jiejietupo"
    resource_list: list = [
        "fail",  # 失败
        "fangshoujilu",  # 防守记录-个人突破
        "geren",  # 个人突破
        "jingong",  # 进攻
        "lock",  # 阵容锁定
        "queding",  # 刷新-确定
        "shuaxin",  # 刷新-个人突破
        "title",  # 突破界面
        "tupojilu",  # 突破记录-阴阳寮突破
        "unlock",  # 阵容解锁
        "xunzhang_0",  # 勋章数0
        "xunzhang_1",  # 勋章数1
        "xunzhang_2",  # 勋章数2
        "xunzhang_3",  # 勋章数3
        "xunzhang_4",  # 勋章数4
        "xunzhang_5",  # 勋章数5
        "yinyangliao",  # 阴阳寮突破
    ]

    @log_function_call
    def __init__(self, n: int = 0) -> None:
        super().__init__(n)

    def load_asset(self):
        self.IMAGE_FAIL = self.get_image_asset("fail")
        self.IMAGE_FANGSHOUJILU = self.get_image_asset("fangshoujilu")
        self.IMAGE_GEREN = self.get_image_asset("geren")
        self.IMAGE_JINGONG = self.get_image_asset("jingong")
        self.IMAGE_LOCK = self.get_image_asset("lock")
        self.IMAGE_SUCCESS = self.get_image_asset("success")
        self.IMAGE_TITLE = self.get_image_asset("title")
        self.IMAGE_TUPOJILU = self.get_image_asset("tupojilu")
        self.IMAGE_UNLOCK = self.get_image_asset("unlock")
        self.IMAGE_XUNZHANG_0 = self.get_image_asset("xunzhang_0")
        self.IMAGE_XUNZHANG_1 = self.get_image_asset("xunzhang_1")
        self.IMAGE_XUNZHANG_2 = self.get_image_asset("xunzhang_2")
        self.IMAGE_XUNZHANG_3 = self.get_image_asset("xunzhang_3")
        self.IMAGE_XUNZHANG_4 = self.get_image_asset("xunzhang_4")
        self.IMAGE_XUNZHANG_5 = self.get_image_asset("xunzhang_5")
        self.IMAGE_YINYANGLIAO = self.get_image_asset("yinyangliao")

    def get_lineup_state(self) -> tuple[LineupState, Point | None]:
        result = RuleImage(self.IMAGE_LOCK)
        if result.match(logger_lever="ERROR"):
            logger.ui("阵容状态：锁定")
            return LineupState.LOCK, result.center_point()
        result = RuleImage(self.IMAGE_UNLOCK)
        if result.match(logger_lever="ERROR"):
            logger.ui("阵容状态：解锁")
            return LineupState.UNLOCK, result.center_point()
        logger.ui_warn("阵容状态：未知")
        return LineupState.NONE, None

    def check_title(self) -> None:
        _msg_title = True
        while True:
            if bool(event_thread):
                raise GUIStopException

            if RuleImage(self.IMAGE_TITLE).match(logger_lever="ERROR"):
                logger.ui_hint(JieJieTuPo.scene_name)
                if isinstance(self, JieJieTuPoGeRen):
                    file_1 = self.IMAGE_FANGSHOUJILU
                    file_2 = self.IMAGE_GEREN
                elif isinstance(self, JieJieTuPoYinYangLiao):
                    file_1 = self.IMAGE_TUPOJILU
                    file_2 = self.IMAGE_YINYANGLIAO
                while True:
                    if RuleImage(file_1).match():
                        logger.ui_hint(self.scene_name)
                        return
                    sleep(0.4, 0.8)
                    self.check_click(file_2)
                    sleep()
            elif _msg_title:
                _msg_title = False
                self.title_error_msg()

    def fighting_into(self, x0: int, y0: int) -> None:
        """点击进入战斗

        参数:
            x0 (int): 左侧横坐标
            y0 (int): 顶部纵坐标
        """
        # 优先使用中心坐标
        x = x0 + 185 // 2
        y = y0 + 80 // 2
        Mouse.click(Point(x, y))
        if self.check_click(self.IMAGE_JINGONG, timeout=3):
            return

        for k in range(3):
            # 失败表示没有点到结界
            logger.ui_warn(f"未点到结界，重试第{k + 1}次")
            point = random_point(x0, x0 + 185, y0, y0 + 80)
            Mouse.click(point)
            if self.check_click(self.IMAGE_JINGONG, timeout=3):
                return

        # 三次都没有点到结界
        raise JieJieTuPoTargetUnavailable("未点到结界")

    def confirm_exit_dialog(self, timeout: float = 6) -> bool:
        """点掉退出确认弹窗

        桌面版按 ESC+ENTER 就能退出战斗，但模拟器模式下这两个键被映射成安卓的
        返回键/回车键，返回键能弹出确认框、回车键却点不掉它（确认按钮是触摸按钮），
        所以这里按文字识别找到「确定/确认」再点。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if bool(event_thread):
                raise GUIStopException

            for item in RuleOcr().get_raw_result():
                # 精确匹配按钮文案：弹窗标题「确定退出当前战斗？」也含"确定"，
                # 用包含匹配会点到标题上
                if item.text.strip() in ("确定", "确认", "確定", "確認"):
                    logger.ui("点击退出确认")
                    Mouse.click(item.center)
                    return True
            sleep(0.6, 1.0)
        logger.ui_warn("没找到退出确认按钮，请手动处理")
        return False

    def fighting_proactive_failure_once(self):
        """主动失败一次"""
        KeyBoard.esc()
        sleep()
        if emulator.enabled:
            self.confirm_exit_dialog()
        else:
            KeyBoard.enter()
        logger.ui("手动退出")


class JieJieTuPoGeRen(JieJieTuPo):
    """个人突破
    相对坐标
    宽185
    高90
    间隔宽115
    间隔高30
    """

    scene_name = "个人突破"
    tupo_geren_x = {
        1: 215,
        2: 515,
        3: 815,
    }
    tupo_geren_y = {
        1: 140,
        2: 260,
        3: 380,
    }
    battle_timeout: int = 180
    """单场战斗结算识别超时时间，避免异常界面导致无限等待"""
    max_no_progress_refresh: int = 3
    """连续没有可进攻结界时允许的刷新次数"""

    @classmethod
    def get_level_list(cls) -> list[str]:
        """返回等级列表"""
        return ["57", "58", "59", "60"]

    @log_function_call
    def __init__(
        self,
        n: int = 0,
        flag_refresh_rule: int = 3,
        flag_current_level: int = 57,
        flag_target_level: int = 57,
        flag_first_round_failure: bool = True,
    ) -> None:
        super().__init__(n)
        self.list_xunzhang: list = None  # 勋章列表
        self.tupo_victory: int = None  # 攻破次数
        self.time_refresh: int = 0  # 记录刷新时间
        self.flag_refresh_rule: int = flag_refresh_rule
        self.flag_current_level: int = flag_current_level
        self.flag_target_level: int = flag_target_level
        self.flag_keep_level: bool = flag_first_round_failure  # 首轮失败标志

    @staticmethod
    def description():
        logger.ui("默认3胜刷新，保级第一轮将会刷新，请注意当前的胜利次数")

    def load_asset(self):
        super().load_asset()
        self.IMAGE_REFRESH = self.get_image_asset("shuaxin")
        self.IMAGE_REFRESH_TRUE = self.get_image_asset("queding")
        self.IMAGE_FIGHT_AGAIN = self.get_image_asset("zaicitiaozhan")

    @staticmethod
    def union_region(*regions: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """求多个区域的并集，用于一次截图覆盖多个识别区域"""
        x1 = min(region[0] for region in regions)
        y1 = min(region[1] for region in regions)
        x2 = max(region[0] + region[2] for region in regions)
        y2 = max(region[1] + region[3] for region in regions)
        return (x1, y1, x2 - x1, y2 - y1)

    @staticmethod
    def crop_region(
        image: Image.Image,
        region: tuple[int, int, int, int],
        base: tuple[int, int, int, int],
    ) -> Image.Image:
        """从并集截图里裁出单个区域"""
        x = region[0] - base[0]
        y = region[1] - base[1]
        return image.crop((x, y, x + region[2], y + region[3]))

    def list_num_xunzhang(self, only_victory: bool = False) -> list[int]:
        """返回每个结界的勋章数列表

        每个结界只截一次图（覆盖「已攻破」与「勋章」两个区域），再在内存里裁剪复用。
        原先一个结界最多要截 7 次图，模拟器模式下每次截图都是一次 adb 往返，会非常慢。

        Args:
            only_victory (bool): 是否只返回已攻破的勋章数

        Returns:
            list[int]: 勋章个数列表
                - -1 表示已攻破
                - 0 表示未攻破
                - 其他值表示勋章数
        """
        logger.ui("正在遍历结界勋章")
        alist = [0]  # 第一个数固定为0，方便后续9个计数
        medal_images: list[Image.Image | None] = [None] * 10

        for i in range(1, 10):
            if bool(event_thread):
                raise GUIStopException

            x = self.tupo_geren_x[(i + 2) % 3 + 1]
            y = self.tupo_geren_y[(i + 2) // 3]
            region_success = (x + 40, y - 10, 185 + 20, 90)
            region_xunzhang = (x - 25, y + 40, 185 + 20, 90 - 20)
            base = self.union_region(region_success, region_xunzhang)
            snapshot = ScreenShot(rect=base).get_image()
            medal_images[i] = self.crop_region(snapshot, region_xunzhang, base)

            if RuleImage(self.IMAGE_SUCCESS, region=region_success).match(
                self.crop_region(snapshot, region_success, base)
            ):
                logger.info(f"第{i}个结界：已攻破")
                alist.append(-1)
            else:
                logger.info(f"第{i}个结界：未攻破")
                alist.append(0)

        if only_victory:
            print_str = "当前已攻破："
            for index, number in enumerate(alist):
                if index == 0:
                    continue
                if number == -1:
                    print_str += str(index) + " "
            logger.ui(print_str)

            print_str = "当前未攻破："
            for index, number in enumerate(alist):
                if index == 0:
                    continue
                if number == 0:
                    print_str += str(index) + " "
            logger.ui(print_str)

        else:
            for i in range(1, 10):
                if bool(event_thread):
                    raise GUIStopException

                x = self.tupo_geren_x[(i + 2) % 3 + 1]
                y = self.tupo_geren_y[(i + 2) // 3]
                if alist[i] == -1:
                    logger.info(f"第{i}个结界：已攻破，跳过勋章识别")
                    continue

                region = (x - 25, y + 40, 185 + 20, 90 - 20)
                image = medal_images[i]
                logger.info(f"检测第{i}个结界勋章数")

                if RuleImage(self.IMAGE_XUNZHANG_5, region=region).match(image, logger_lever="ERROR"):
                    alist[i] = 5
                    logger.info(f"第{i}个结界：5")
                    continue
                if RuleImage(self.IMAGE_XUNZHANG_4, region=region).match(image, logger_lever="ERROR"):
                    alist[i] = 4
                    logger.info(f"第{i}个结界：4")
                    continue
                if RuleImage(self.IMAGE_XUNZHANG_3, region=region).match(image, logger_lever="ERROR"):
                    alist[i] = 3
                    logger.info(f"第{i}个结界：3")
                    continue
                if RuleImage(self.IMAGE_XUNZHANG_2, region=region).match(image, logger_lever="ERROR"):
                    alist[i] = 2
                    logger.info(f"第{i}个结界：2")
                    continue
                if RuleImage(self.IMAGE_XUNZHANG_1, region=region).match(image, logger_lever="ERROR"):
                    alist[i] = 1
                    logger.info(f"第{i}个结界：1")
                    continue
                if RuleImage(self.IMAGE_XUNZHANG_0, region=region).match(image, logger_lever="ERROR"):
                    alist[i] = 0
                    logger.info(f"第{i}个结界：0")
                    logger.info(f"第{i}个结界：未攻破")
                    continue

            print_str = "勋章数：["
            for i in range(1, 10):
                if i == 1:
                    print_str += str(alist[i])
                else:
                    print_str = f"{print_str},{str(alist[i])}"
            print_str += "]"
            logger.ui(print_str)

        return alist

    def fighting(self) -> bool:
        """按勋章数进攻；一次扫描中每个结界最多尝试一次。

        Returns:
            bool: 本次扫描是否成功进攻了结界
        """
        attacked = False
        for medal_count in range(5, -1, -1):  # 按勋章数排序
            if bool(event_thread):
                raise GUIStopException

            barrier_indexes = [
                index
                for index, value in enumerate(self.list_xunzhang)
                if index > 0 and value == medal_count
            ]
            for barrier_index in barrier_indexes:
                if bool(event_thread):
                    raise GUIStopException

                logger.ui(f"{barrier_index} 可进攻")
                x = self.tupo_geren_x[(barrier_index + 2) % 3 + 1]
                y = self.tupo_geren_y[(barrier_index + 2) // 3]
                terminal_region = (x, y - 40, 185 + 40, 90)
                success_region = (x + 40, y - 10, 185 + 20, 90)

                if RuleImage(self.IMAGE_FAIL, region=terminal_region).match():
                    logger.ui(f"{barrier_index} 已失败")
                    continue
                if RuleImage(self.IMAGE_SUCCESS, region=success_region).match():
                    logger.ui(f"{barrier_index} 已攻破")
                    continue

                try:
                    # 阵容未锁定时会停留在准备界面，进攻前确认锁定状态
                    self.ensure_lineup_locked()
                    self.fighting_into(x, y)
                except JieJieTuPoTargetUnavailable:
                    logger.ui_warn(f"第{barrier_index}个结界状态已变化，重新扫描")
                    return attacked

                attacked = True
                self.start_battle_from_ready_screen()
                flag_victory = self.check_finish(timeout=self.battle_timeout)

                sleep()
                finish_random_left_right()
                sleep(2)

                if not flag_victory and RuleImage(self.IMAGE_SUCCESS, region=success_region).match():
                    logger.ui_warn(f"战斗结果纠正：第{barrier_index}个结界已攻破")
                    flag_victory = True

                if flag_victory:
                    self.done()

                # 3胜奖励
                if self.tupo_victory == 2 and flag_victory:
                    sleep(2)
                    while True:
                        if bool(event_thread):
                            raise GUIStopException

                        self.check_click(self.global_assets.IMAGE_FINISH, timeout=3)
                        sleep()
                        if not RuleImage(self.global_assets.IMAGE_FINISH).match():
                            break
                    logger.ui("成功攻破3次")

                if flag_victory:
                    return True

        return attacked

    def ensure_lineup_unlocked(self, max_attempts: int = 3) -> None:
        """确认个人突破阵容已经解锁，未知状态下不开始挑战。"""
        for attempt in range(max_attempts):
            state, point = self.get_lineup_state()
            if state == LineupState.UNLOCK:
                return
            if state == LineupState.LOCK and point is not None:
                sleep()
                Mouse.click(point)
            if attempt < max_attempts - 1:
                sleep(0.4, 0.8)

        raise JieJieTuPoLineupStateError("无法确认阵容已解锁，请手动解锁阵容后重试")

    def ensure_lineup_locked(self, max_attempts: int = 3) -> None:
        """确认个人突破阵容已经重新锁定。"""
        for attempt in range(max_attempts):
            state, point = self.get_lineup_state()
            if state == LineupState.LOCK:
                return
            if state == LineupState.UNLOCK and point is not None:
                sleep()
                Mouse.click(point)
            if attempt < max_attempts - 1:
                sleep(0.4, 0.8)

        raise JieJieTuPoLineupStateError("无法确认阵容已锁定，请手动锁定阵容")

    def start_battle_from_ready_screen(self, max_attempts: int = 10) -> bool:
        """兜底处理准备界面

        阵容未锁定时点击进攻会停留在准备界面，游戏不会自动进入战斗，
        战斗结算识别将一直等待，因此在准备界面直接点击准备。

        参数:
            max_attempts (int): 最大检查次数

        Returns:
            bool: True 表示识别到准备界面并已点击准备
        """
        for _ in range(max_attempts):
            if bool(event_thread):
                raise GUIStopException

            # 同一帧截图用于新旧准备按钮识别
            screenshot = ScreenShot()
            for asset in (self.global_assets.IMAGE_READY_NEW, self.global_assets.IMAGE_READY_OLD):
                result = RuleImage(asset)
                if result.match(screenshot):
                    logger.ui_warn("阵容未锁定，识别到准备界面，点击准备进入战斗")
                    Mouse.click(result.center_point())
                    sleep(2, 3)
                    return True

            sleep(0.4, 0.8)

        return False

    def back_to_barrier_list(self, wait_attempts: int = 10, max_attempts: int = 3) -> None:
        """确认已经返回个人突破列表页

        先有限等待列表页出现，仍不出现时再退出结算界面：战斗失败后可能停留在
        结算界面，或被随机点击误入「再次挑战」，此时继续进攻会一直等待。

        参数:
            wait_attempts (int): 每轮等待列表页出现的检查次数
            max_attempts (int): 最大恢复次数

        Raises:
            JieJieTuPoReadyTimeout: 始终无法返回个人突破列表页
        """
        for attempt in range(max_attempts):
            for _ in range(wait_attempts):
                if bool(event_thread):
                    raise GUIStopException

                if RuleImage(self.IMAGE_FANGSHOUJILU).match():
                    return
                sleep(0.4, 0.8)

            logger.ui_warn(f"未返回个人突破页面，尝试退出（第{attempt + 1}次）")
            KeyBoard.esc()
            sleep()
            result = RuleImage(self.global_assets.IMAGE_FINISH)
            if result.match():
                Mouse.click(result.center_point())
            sleep(1, 2)

        raise JieJieTuPoReadyTimeout("未返回个人突破页面，已停止结界突破任务")

    def wait_for_ready(self, max_attempts: int = 30) -> bool:
        """有限等待准备界面，并在同一帧兼容新旧准备按钮。

        图像素材在手机版上不一定命中（渲染有差异），所以再加一层「准备」文字识别兜底。
        """
        for _ in range(max_attempts):
            if bool(event_thread):
                raise GUIStopException

            screenshot = ScreenShot()
            if RuleImage(self.global_assets.IMAGE_READY_NEW).match(screenshot):
                return True
            if RuleImage(self.global_assets.IMAGE_READY_OLD).match(screenshot):
                return True
            # 文字兜底：手机版的准备按钮常常只有文字能对上
            for item in RuleOcr().get_raw_result():
                if item.text.strip() in ("准备", "準備"):
                    return True
            sleep(0.4, 0.8)

        return False

    def fighting_proactive_failure(self, count_max) -> None:
        """主动失败

        参数:
            count_max (int): 次数
        """
        count = 0
        self.ensure_lineup_unlocked()
        sleep()

        self.list_xunzhang = self.list_num_xunzhang(only_victory=True)
        for i in range(1, len(self.list_xunzhang)):
            if self.list_xunzhang[i] != -1:
                logger.ui(f"{i} 可进攻")
                break

        self.fighting_into(self.tupo_geren_x[(i + 2) % 3 + 1], self.tupo_geren_y[(i + 2) // 3])

        sleep(2)
        while True:
            if bool(event_thread):
                raise GUIStopException

            if not self.wait_for_ready():
                raise JieJieTuPoReadyTimeout("未识别到准备界面，已停止主动退级")

            sleep(3)
            self.fighting_proactive_failure_once()
            count += 1
            logger.ui(f"失败次数: {count}")
            sleep(2)
            if count >= count_max:
                if self.check_scene(self.IMAGE_FIGHT_AGAIN):
                    finish_random_left_right()
                break

            self.check_click(self.IMAGE_FIGHT_AGAIN, timeout=5)
            sleep()
            if not emulator.enabled:
                # 桌面版靠回车进入下一场；模拟器模式下点「再次挑战」后游戏自己会
                # 走到准备界面，安卓回车键在这里没有作用
                KeyBoard.enter()

        sleep(2)
        if not self.check_scene(self.IMAGE_FANGSHOUJILU, timeout=15):
            raise JieJieTuPoReadyTimeout("主动退级结束后未返回个人突破页面")
        self.ensure_lineup_locked()
        logger.ui("已锁定阵容")
        sleep()

    def refresh(self) -> None:
        """刷新"""
        flag_refresh = False  # 刷新提醒
        sleep(4, 8)  # 强制等待
        import math

        while True:
            if bool(event_thread):
                raise GUIStopException

            # 第一次刷新 或 冷却时间已过
            timenow = time.perf_counter()
            if self.time_refresh == 0 or self.time_refresh + 5 * 60 < timenow:
                logger.ui("刷新中")
                sleep(3, 6)
                self.check_click(self.IMAGE_REFRESH, wait=2)
                sleep(2, 4)
                self.check_click(self.IMAGE_REFRESH_TRUE, wait=0.5)
                self.time_refresh = timenow
                sleep(2, 6)
                break
            elif not flag_refresh:
                time_wait = math.ceil(self.time_refresh + 5 * 60 - timenow)
                logger.ui(f"等待刷新冷却，约{time_wait}秒")
                flag_refresh = True
                sleep(time_wait, time_wait + 5)

    def lower_level(self):
        """降级，退九刷新"""
        logger.ui("开始降级")
        logger.ui("退九")
        self.fighting_proactive_failure(9)
        logger.ui("开始刷新")
        self.refresh()
        logger.ui("降级完成")

    def keep_level(self):
        """保级，退四打九，只进行退出操作"""
        self.fighting_proactive_failure(4)

    def refresh_task(self):
        no_progress: int = 0
        while self.n < self.max:
            if bool(event_thread):
                raise GUIStopException

            self.list_xunzhang = self.list_num_xunzhang()
            self.tupo_victory = self.list_xunzhang.count(-1)
            if self.tupo_victory >= 3:
                # 3 胜刷新：已经攻破 3 个或更多（列表里本来就攻破了一部分）都刷新
                logger.ui(f"已攻破{self.tupo_victory}个，刷新列表")
                self.refresh()
            else:
                logger.ui(f"已攻破{self.tupo_victory}个")
                if self.fighting():
                    no_progress = 0
                else:
                    # 没有可进攻的结界（全部已失败或已攻破），只能刷新列表
                    no_progress += 1
                    if no_progress > self.max_no_progress_refresh:
                        logger.ui_error("没有可进攻的结界，已停止结界突破")
                        return
                    logger.ui_warn(f"没有可进攻的结界，刷新列表（第{no_progress}次）")
                    self.refresh()

    def resolve_level_failure(self, max_attempts: int = 30) -> bool:
        """稳定失败结果：纠正假失败，或在真失败时开始再次挑战。"""
        for _ in range(max_attempts):
            if bool(event_thread):
                raise GUIStopException

            screenshot = ScreenShot()
            if RuleImage(self.global_assets.IMAGE_FINISH).match(screenshot):
                logger.ui_warn("战斗结果纠正：实际为胜利")
                return True

            if RuleImage(self.IMAGE_FIGHT_AGAIN).match(screenshot):
                logger.ui_warn("战斗失败，不重试当前结界")
                finish_random_left_right()
                return False

            sleep(0.4, 0.8)

        raise JieJieTuPoBattleResultTimeout("未识别到胜利结算或再次挑战，已停止卡级任务")

    def level_task(self, lower_level_count: int):
        # 降级次数由输入给定
        for _ in range(lower_level_count):
            lower_level_count -= 1
            logger.ui(f"第{_}次降级")
            self.lower_level()

        # 保级
        if self.flag_keep_level:
            self.keep_level()
        else:
            self.flag_keep_level = True

        no_progress: int = 0
        while self.n < self.max:
            if bool(event_thread):
                raise GUIStopException

            # 获得每个结界的勋章数
            if self.list_xunzhang is None:
                self.list_xunzhang = self.list_num_xunzhang(only_victory=True)
            self.tupo_victory = self.list_xunzhang.count(-1)  # 已经攻破的次数

            attacked = False
            rescan = False

            # 按顺序打九
            for i in range(1, len(self.list_xunzhang)):
                if self.n >= self.max:
                    return

                if self.list_xunzhang[i] == -1:
                    continue

                # 战斗失败后可能停留在结算界面或误入再次挑战，先确认回到列表页
                self.back_to_barrier_list()
                # 阵容未锁定时点击进攻会停留在准备界面，进攻前确认锁定状态
                self.ensure_lineup_locked()
                logger.ui(f"{i} 可进攻")
                try:
                    self.fighting_into(
                        self.tupo_geren_x[(i + 2) % 3 + 1],
                        self.tupo_geren_y[(i + 2) // 3],
                    )
                except JieJieTuPoTargetUnavailable:
                    # 结界已失效或被抢，重新扫描列表
                    logger.ui_warn(f"第{i}个结界状态已变化，重新扫描")
                    rescan = True
                    break

                attacked = True
                self.start_battle_from_ready_screen()

                # 只有成功才会退出
                while True:
                    if bool(event_thread):
                        raise GUIStopException

                    flag_victory = self.check_finish(timeout=self.battle_timeout)
                    if not flag_victory:
                        flag_victory = self.resolve_level_failure()

                    if flag_victory:
                        self.done()
                        self.tupo_victory += 1
                        sleep()
                        finish_random_left_right()
                    else:
                        logger.ui_warn(f"第{i}个结界战斗失败，跳过")
                    break

                sleep(4)
                if self.tupo_victory in [3, 6, 9]:
                    if not self.check_click(self.global_assets.IMAGE_FINISH, timeout=10):
                        logger.ui_warn("未识别到3/6/9胜奖励界面，跳过")
                    sleep(2)

            if self.n >= self.max:
                return

            if rescan:
                if attacked:
                    no_progress = 0
                else:
                    no_progress += 1
                if no_progress > self.max_no_progress_refresh:
                    logger.ui_error("结界无法进攻，已停止结界突破")
                    return
                self.list_xunzhang = None
                continue

            # 当前列表已打完，刷新后继续，避免绘卷刷分空转
            if attacked:
                no_progress = 0
                logger.ui_warn(f"本轮可进攻结界已全部处理，完成{self.n}/{self.max}次，刷新列表")
            else:
                no_progress += 1
                if no_progress > self.max_no_progress_refresh:
                    logger.ui_error("没有可进攻的结界，已停止结界突破")
                    return
                logger.ui_warn(f"没有可进攻的结界，刷新列表（第{no_progress}次）")

            self.list_xunzhang = None
            self.refresh()

    def run(self):
        # 卡57级和刷新规则互斥
        if self.flag_refresh_rule:
            logger.info("只刷新")
        else:
            logger.info("保级")
            lower_level_count = self.flag_current_level - self.flag_target_level
            if lower_level_count < 0:
                logger.ui_error("当前等级低于目标等级")
                return

        self.check_title()

        if self.flag_refresh_rule:  # 只需要刷新
            self.refresh_task()
        else:
            self.level_task(lower_level_count)


class JieJieTuPoYinYangLiao(JieJieTuPo):
    """阴阳寮突破
    相对坐标
    宽185
    高90
    间隔宽115
    间隔高40
    """

    scene_name = "阴阳寮突破"
    tupo_yinyangliao_x = {
        1: 460,
        2: 760,
    }
    tupo_yinyangliao_y = {
        1: 140,
        2: 260,
        3: 380,
        4: 500,
    }

    @log_function_call
    def __init__(self, n: int = 0) -> None:
        super().__init__(n)
        self.process: float = 0  # 突破进度

    @staticmethod
    def description() -> Literal[100, 6]:
        now = time.strftime("%H:%M:%S")
        if now >= "21:00:00" or now < "05:00:00":
            logger.ui_warn("CD无限，桌面版单账号上限100次")
            return 100
        else:
            logger.ui_warn("CD 6次，可在每日21时后无限挑战")
            return 6

    @log_function_call
    def fighting(self) -> int:
        i = 1  # 1-8
        while True:
            if bool(event_thread):
                raise GUIStopException

            # 当前页结界全部失效
            if i > 8:
                logger.ui_warn("当前页全部失效")
                sleep()
                self.page_down(4)
                i = 1

            x = self.tupo_yinyangliao_x[(i + 1) % 2 + 1]
            y = self.tupo_yinyangliao_y[(i + 1) // 2]
            region = (x, y - 40, 185 + 40, 90)
            if not RuleImage(self.IMAGE_FAIL, region=region).match():
                logger.ui(f"{i} 可进攻")
                _y = y + 35
                if i in [7, 8]:  # 最后一排坐标上移
                    _y -= 20
                    logger.ui(f"{i} 坐标修正")
                self.fighting_into(x, _y)
                # 延迟等待，判断当前寮突是否有效
                sleep(3)
                if RuleImage(self.IMAGE_JINGONG).match():
                    logger.ui_warn("当前结界已被攻破")
                    i += 1
                    KeyBoard.esc()
                    sleep(2)
                    continue
                flag = 1 if self.check_finish() else 0
                sleep()
                # 结束界面
                finish_random_left_right()
                return flag
            else:
                logger.ui(f"{i} 已失败")
                if i < 8:
                    i += 1
                else:
                    # 单页上限8个
                    logger.ui_warn("当前页全部失败")
                    sleep()
                    self.page_down(4)
                    i = 1

    def page_down(self, rows: int = 1):
        """向下翻页

        参数:
            rows (int): 行数，默认1行
        """
        # TODO 操作滚轮需要鼠标在当前区域，目前来说调用该方法时，鼠标在当前区域
        Mouse.scroll(-rows * 240)  # 2*pis(pis=2*120)

    @log_function_call
    def get_current_process(self):
        result = RuleOcr().get_raw_result()
        for item in result:
            if "%" not in item.text:
                continue

            with contextlib.suppress(Exception):
                _process = float(item.text.split("%")[0])
                if _process > 100:  # 防止识别错误
                    continue
                self.process = _process
                logger.ui(f"当前进度：{self.process}%")

            if self.process > 90:
                raise LiaoTuPoFullException

            return

    def run(self):
        self.check_title()
        while self.n < self.max:
            if bool(event_thread):
                raise GUIStopException

            sleep()
            self.get_current_process()
            if flag := self.fighting():
                self.done()
            elif flag == -1:
                break
            sleep()
