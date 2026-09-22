import time
from typing import Literal

from ..utils.adapter import Mouse
from ..utils.application import SCREENSHOT_DIR_PATH
from ..utils.assets import AssetOcr
from ..utils.config import InteractionMode, config
from ..utils.decorator import log_function_call, run_in_thread
from ..utils.emulator import emulator
from ..utils.event import event_thread
from ..utils.exception import CustomException, GUIStopException
from ..utils.function import finish_random_left_right, prevent_sleep, sleep, wait_until
from ..utils.image import AssetImage, RuleImage
from ..utils.log import logger
from ..utils.mysignal import global_ms as ms
from ..utils.paddleocr import RuleOcr
from ..utils.screenshot import ScreenShot
from ..utils.toast import toast
from ..utils.window import window_manager
from .global_resource import GlobalResource
from .utils import get_image_asset, get_ocr_asset, load_asset


class BasePackage:
    scene_name: str = ""
    """名称"""
    resource_path: str = ""
    """路径"""
    resource_list: list = []
    """资源列表"""
    init: bool = False
    """初始化"""

    @log_function_call
    def __init__(self, n: int = 0) -> None:
        self.n: int = 0
        """当前次数"""
        self.max: int = n
        """总次数"""
        self.current_resource_list: list = []
        """当前使用的资源列表"""
        self.current_asset_list: list = []
        """当前使用的资源列表"""
        self.current_scene: str = ""
        """当前场景"""

        self.global_assets = GlobalResource()
        """通用资源"""
        self.load_asset_list()
        try:
            self.load_asset()
            self.init = True
        except Exception as e:
            logger.error(f"{self.resource_path}/assets.json 资源加载失败：{e}")
            logger.ui_error(f"{self.resource_path}/assets.json 资源加载失败，请检查资源文件")

    @staticmethod
    def description() -> None:
        """功能描述，支持重写"""
        pass

    def load_asset_list(self):
        self.asset_image_list = load_asset(self.resource_path, "image")
        self.asset_ocr_list = load_asset(self.resource_path, "ocr")

    def load_asset(self):
        pass

    def get_image_asset(self, name: str) -> AssetImage:
        return get_image_asset(self.asset_image_list, name)

    def get_ocr_asset(self, name: str) -> AssetOcr:
        return get_ocr_asset(self.asset_ocr_list, name)

    def title_error_msg(self):
        logger.ui_warn("请检查游戏场景")

    def soul_overflow_warn_msg(self):
        logger.ui_warn("御魂上限提醒")

    def scene_handle(self, scene: str = "") -> str:
        if not scene:
            scene = self.current_scene
        logger.info(f"current scene: {scene}.png")
        if "/" in scene:
            scene = scene.split("/")[-1]
        self.current_scene = scene
        return scene

    def log_current_asset_list(self):
        """记录当前匹配的资源列表"""
        if not self.current_asset_list:
            return
        logger.info(f"current_image_list: {len(self.current_asset_list)}")
        for item in self.current_asset_list:
            logger.info(item)

    @log_function_call
    def check_title(self):
        """检查主场景"""
        msg_title: bool = True
        asset = None

        # 判断标题采用何种识别方法
        if hasattr(self, "OCR_TITLE"):
            asset = self.OCR_TITLE
        elif hasattr(self, "IMAGE_TITLE"):
            asset = self.IMAGE_TITLE
        else:
            logger.error("no title asset defined")

        while True:
            if bool(event_thread):
                raise GUIStopException

            if isinstance(asset, AssetOcr):
                if RuleOcr(asset).match():
                    logger.ui_hint(self.scene_name)
                    return
            elif isinstance(asset, AssetImage):
                if RuleImage(asset).match():
                    logger.ui_hint(self.scene_name)
                    return
            else:
                logger.error("no title asset")
                return

            if msg_title:
                self.title_error_msg()
                msg_title = False

    def check_click(
        self,
        asset: AssetImage | AssetOcr | None = None,
        timeout: float = 0,
        point_type: Literal["random", "center"] = "random",
        *args,
        **kwargs,
    ) -> bool:
        if isinstance(asset, str):
            raise TypeError("asset must be AssetImage or AssetOcr")

        if timeout:
            _start = time.time()
        while True:
            if bool(event_thread):
                raise GUIStopException

            if timeout and (time.time() - _start > timeout):
                # 带上素材名：曾经只打一句 "check_click timeout"，排查时无法判断是哪个素材没匹配到
                name = getattr(asset, "description", "") or getattr(asset, "name", "") or "未知素材"
                logger.ui_error(f"check_click 超时未找到：{name}")
                return False

            if isinstance(asset, AssetImage):
                image = RuleImage(asset)
                if image.match():
                    if point_type == "random":
                        Mouse.click(image.random_point(), *args, **kwargs)
                    elif point_type == "center":
                        Mouse.click(image.center_point(), *args, **kwargs)
                    return True
            elif isinstance(asset, AssetOcr):
                ocr = RuleOcr(asset)
                if result := ocr.match():
                    Mouse.click(result.center, *args, **kwargs)
                    return True

    def check_scene(
        self,
        asset: AssetImage | AssetOcr | None = None,
        timeout: float = 0,
    ) -> bool:
        if timeout:
            _start = time.time()
        while True:
            if bool(event_thread):
                raise GUIStopException

            if timeout and (time.time() - _start > timeout):
                logger.error("check_scene timeout")
                return False

            if isinstance(asset, AssetImage):
                if RuleImage(asset).match():
                    return True
            elif isinstance(asset, AssetOcr):
                if RuleOcr(asset).match():
                    return True

    @log_function_call
    def wait_passengers_on_position(self, passengers: int = 2):
        """等待队员就位，需要在组队界面，
        没有匹配到对应的背景说明该位置被玩家模型占用，
        其中队员3的位置消失表示3个人都就位
        """
        logger.ui("等待队员就位")
        while True:
            if bool(event_thread):
                raise GUIStopException

            # 优先判断3人组队
            if passengers == 3:
                if not RuleImage(self.global_assets.IMAGE_PASSENGER_3).match():
                    logger.ui("队员3 就位")
                    return True
            elif not RuleImage(self.global_assets.IMAGE_PASSENGER_2).match():
                logger.ui("队员2 就位")
                return True

    def start(self, *args, **kwargs) -> None:
        """挑战开始"""
        # coor = random_coor(1067 - 50, 1067 + 50, 602 - 50, 602 + 50)
        # click(coor, sleeptime=sleeptime)
        self.check_click(self.IMAGE_START, *args, **kwargs)

    def screenshot(self) -> None:
        """截图，保存在当前功能的名称截图目录"""
        screenshot_path = "cache" if self.resource_path is None else self.resource_path
        screenshot_path = SCREENSHOT_DIR_PATH / screenshot_path
        if not screenshot_path.exists():
            screenshot_path.mkdir(parents=True)

        screenshot_file = screenshot_path / f"screenshot-{time.strftime('%Y%m%d%H%M%S')}.png"
        ScreenShot().save(str(screenshot_file))
        logger.info(f"screenshot: {screenshot_file}")

    def done(self) -> None:
        """更新一次完成情况"""
        self.n += 1
        logger.progress(f"{self.n}/{self.max}")

    @log_function_call
    def check_result(self) -> bool:
        """结果判断

        Returns:
            bool: 返回结果
                 - True: 胜利/结束
                 - False: 失败
        """
        while True:
            if bool(event_thread):
                raise GUIStopException

            _screenshot = ScreenShot()

            if RuleImage(self.global_assets.IMAGE_VICTORY).match(_screenshot):
                logger.ui("战斗胜利")
                return True
            if RuleImage(self.global_assets.IMAGE_FINISH).match(_screenshot):
                logger.ui("战斗结束")
                return True
            if RuleImage(self.global_assets.IMAGE_FAIL).match(_screenshot):
                logger.ui_warn("战斗失败")
                return False

            if config.user.battle_theme_recognition:
                # 特殊战斗主题-胜利
                rule = RuleImage(self.global_assets.IMAGE_VICTORY_DENGYUNWENCUI)
                if rule.match(_screenshot):
                    logger.ui(f"战斗胜利（{rule.description}）")
                    return True
                rule = RuleImage(self.global_assets.IMAGE_VICTORY_RONGCIYUEONG)
                if rule.match(_screenshot):
                    logger.ui(f"战斗胜利（{rule.description}）")
                    return True
                rule = RuleImage(self.global_assets.IMAGE_VICTORY_ZANGJINTAIGE)
                if rule.match(_screenshot):
                    logger.ui(f"战斗胜利（{rule.description}）")
                    return True
                rule = RuleImage(self.global_assets.IMAGE_VICTORY_ZHAOCAINAFU)
                if rule.match(_screenshot):
                    logger.ui(f"战斗胜利（{rule.description}）")
                    return True

                # 特殊战斗主题-失败
                rule = RuleImage(self.global_assets.IMAGE_FAIL_DENGYUNWENCUI)
                if rule.match(_screenshot):
                    logger.ui_warn(f"战斗失败（{rule.description}）")
                    return False
                rule = RuleImage(self.global_assets.IMAGE_FAIL_RONGCIYUEONG)
                if rule.match(_screenshot):
                    logger.ui_warn(f"战斗失败（{rule.description}）")
                    return False
                rule = RuleImage(self.global_assets.IMAGE_FAIL_ZANGJINTAIGE)
                if rule.match(_screenshot):
                    logger.ui_warn(f"战斗失败（{rule.description}）")
                    return False
                rule = RuleImage(self.global_assets.IMAGE_FAIL_ZHAOCAINAFU)
                if rule.match(_screenshot):
                    logger.ui_warn(f"战斗失败（{rule.description}）")
                    return False

    @log_function_call
    def check_finish(self, timeout: int = 0) -> bool:
        """结束判断（不判断胜利）

        Args:
            timeout (int): 超时时间，单位秒。

        Returns:
            bool: 返回结果
                 - True: 结束
                 - False: 失败
        """
        if timeout:
            _start = time.time()

        while True:
            if bool(event_thread):
                raise GUIStopException

            if timeout and (time.time() - _start > timeout):
                logger.error(f"结束判断超时，超时{timeout}秒")
                return False

            _screenshot = ScreenShot()
            if RuleImage(self.global_assets.IMAGE_FINISH).match(_screenshot):
                logger.ui("战斗结束")
                return True
            if RuleImage(self.global_assets.IMAGE_FAIL).match(_screenshot):
                logger.ui_warn("战斗失败")
                return False

            if config.user.battle_theme_recognition:
                # 特殊战斗主题-失败
                rule = RuleImage(self.global_assets.IMAGE_FAIL_DENGYUNWENCUI)
                if rule.match(_screenshot):
                    logger.ui_warn(f"战斗失败（{rule.description}）")
                    return False
                rule = RuleImage(self.global_assets.IMAGE_FAIL_RONGCIYUEONG)
                if rule.match(_screenshot):
                    logger.ui_warn(f"战斗失败（{rule.description}）")
                    return False
                rule = RuleImage(self.global_assets.IMAGE_FAIL_ZANGJINTAIGE)
                if rule.match(_screenshot):
                    logger.ui_warn(f"战斗失败（{rule.description}）")
                    return False
                rule = RuleImage(self.global_assets.IMAGE_FAIL_ZHAOCAINAFU)
                if rule.match(_screenshot):
                    logger.ui_warn(f"战斗失败（{rule.description}）")
                    return False

    def wait_frame(
        self,
        assets: list,
        timeout: float = 3.0,
        interval: float = 0.3,
    ) -> "ScreenShot":
        """轮询截图直到任一素材出现，返回那一帧

        用来替代"固定睡眠 N 秒再判断界面"：界面一出现就立刻继续，最多等到 timeout 秒
        （上限与原来的固定睡眠一致，只是提前结束等待）。

        截图复用规则：每次轮询都是**新抓的帧**，不跨时间复用；返回的帧在调用方
        立即使用（判定→点击之间不再插入截图）是安全的。
        属于"动作后会变"或"会动"的目标（例如探索小怪、结界突破的结界状态），
        不要在动作之后拿这里返回的旧帧继续判断。

        Args:
            assets (list): 素材列表（AssetImage）
            timeout (float): 总等待上限，单位秒
            interval (float): 轮询间隔，单位秒

        Returns:
            ScreenShot: 命中素材时的帧；超时则返回最后一帧
        """
        screenshot = ScreenShot()
        deadline = time.time() + timeout
        while True:
            if bool(event_thread):
                raise GUIStopException

            for asset in assets:
                if RuleImage(asset).match(screenshot, logger_lever="NONE"):
                    return screenshot

            if time.time() >= deadline:
                return screenshot

            sleep(max(interval * 0.8, 0.05), interval * 1.2)
            screenshot = ScreenShot()

    def click_ready_once(self) -> bool:
        """识别到准备按钮则点击一次

        上阵阶段结束后需要点击准备才会开始战斗，部分玩法不会自动准备。

        Returns:
            bool: 是否识别到并点击了准备按钮
        """
        # 准备按钮是静止元素（不属于"会动的小怪"或"动作后会变的结界"），
        # 所以截一帧同时匹配新旧两种素材，省掉一次截图（模拟器模式下约 0.35 秒）。
        screenshot = ScreenShot()
        for image in (self.global_assets.IMAGE_READY_NEW, self.global_assets.IMAGE_READY_OLD):
            rule = RuleImage(image)
            if rule.match(screenshot):
                logger.ui("点击准备")
                Mouse.click(rule.center_point())
                sleep(1.0, 1.5)
                return True
        return False

    @log_function_call
    def ensure_finish(self):
        """确保结束"""
        logger.ui("结束")
        sleep(0.4, 0.8)
        finish_random_left_right()
        while True:
            if bool(event_thread):
                raise GUIStopException

            # 未重复检测到，表示成功点击
            if not RuleImage(self.global_assets.IMAGE_FINISH).match():
                self.done()
                break
            Mouse.click()
            sleep(0.4, 0.8)

    def close_current_scene(self):
        """关闭当前场景"""
        logger.ui("准备关闭当前场景")
        sleep()
        if self.check_click(self.global_assets.IMAGE_CLOSE, timeout=5):
            logger.ui("关闭当前场景成功")
        else:
            logger.ui_warn("关闭当前场景失败")

    def run(self):
        """任务内容，支持重写"""
        pass

    def task_finish_info(self):
        """任务结束信息，支持重写"""
        pass

    def _format_time_cost(self, cost: int):
        """格式化用时为可读字符串，支持小时/分钟/秒

        Args:
            cost (int): 秒数
        """
        try:
            s = int(cost)
            if s >= 3600:
                hours = s // 3600
                minutes = (s % 3600) // 60
                seconds = s % 60
                logger.ui(f"用时 {hours}时{minutes}分{seconds}秒")
            elif s >= 60:
                logger.ui(f"用时 {(s // 60)}分{(s % 60)}秒")
            else:
                logger.ui(f"用时 {s}秒")
        except Exception:
            logger.error("用时统计计算失败")

    @run_in_thread
    def task_start(self):
        """任务开始"""

        # 禁用按钮
        ms.main.is_fighting_update.emit(True)
        _start = time.perf_counter()
        if self.max:
            logger.progress(f"0/{self.max}")
        else:
            logger.progress(0)

        config.runtime.xuanshangfengyin.reset()

        need_prevent_sleep: bool = False  # 是否需要防止休眠
        if emulator.enabled:
            # 每次任务开始时把当前设备打出来，方便确认操作的是哪一块屏幕
            if emulator.ensure_ready():
                logger.ui(f"模拟器模式：当前设备 {emulator.serial}")
            else:
                logger.ui_error("模拟器模式：设备未就绪，请确认模拟器已启动")
        elif config.user.interaction_mode.mode == InteractionMode.FRONTEND:
            if config.user.interaction_mode.frontend.force_window:
                window_manager.set_foreground()
        else:
            if config.user.interaction_mode.backend.prevent_sleep:
                if prevent_sleep(True):
                    need_prevent_sleep = True

        try:
            self.run()
        except Exception as e:
            if not isinstance(e, CustomException):
                import traceback

                logger.ui_error(f"任务出错: {e}")
                logger.error(traceback.format_exception(e))

        if need_prevent_sleep:
            prevent_sleep(False)

        _end = time.perf_counter()
        self._format_time_cost(int(_end - _start))

        self.task_finish_info()
        if config.runtime.xuanshangfengyin.get():
            logger.ui_hint(f"收到 {config.runtime.xuanshangfengyin.get()} 个悬赏封印")
            config.runtime.xuanshangfengyin.reset()

        # 启用按钮
        ms.main.is_fighting_update.emit(False)
        logger.ui(f"已完成 {self.scene_name} {self.n}次")
        # 系统通知
        # 5s结束，保留至通知中心
        toast("任务已完成")
