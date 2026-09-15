"""安卓模拟器（MuMu）支持

阴阳师手机版在模拟器里无法沿用桌面版的方式：

- 设备画面是 GPU 渲染，BitBlt / PrintWindow 抓到的是黑屏；
- 后台 PostMessage 对模拟器无效，而且 MuMu 窗口比例不是 16:9，会被视口检测直接拒绝。

因此模拟器模式改走 adb：截图用 ``screencap``，点击/滑动用 ``input``，
再把画面归一化到项目标准的 1136×640，这样上层的识别与点击逻辑不用改动。
"""

import io
import os
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image

from .config import config
from .log import logger
from .viewport import CANONICAL_SIZE

WINDOWS_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
"""隐藏 adb 的子进程窗口"""

MUMU_ADB_PATTERNS = (
    r"MuMuPlayer\nx_main\adb.exe",
    r"MuMuPlayer\nx_device\*\shell\adb.exe",
    r"MuMuPlayer-12.0\shell\adb.exe",
    r"MuMuPlayer-12.0\nx_main\adb.exe",
)
"""MuMu 自带 adb 的常见相对路径"""

MUMU_ROOTS = (
    r"C:\Program Files\Netease",
    r"C:\Program Files (x86)\Netease",
    r"D:\Program Files\Netease",
    r"D:\Netease",
    r"D:\apps\exe\moniqi",
    r"C:\Program Files\MuMuPlayer",
)
"""MuMu 常见安装目录"""

DEVICE_PORTS = tuple(range(16384, 16480, 32))
"""MuMu 各开号的 adb 端口（16384、16416、16448…）"""

DEFAULT_PACKAGE = "com.netease.onmyoji"
"""阴阳师手机版包名前缀"""


class EmulatorError(Exception):
    """模拟器操作失败"""


def _run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
        creationflags=WINDOWS_NO_WINDOW,
    )


def _emulator_config():
    """取模拟器配置（测试里 config.user 可能是替身，做防御性读取）"""
    return getattr(config.user, "emulator", None)


def _config_value(name: str, default):
    return getattr(_emulator_config(), name, default)


class Emulator:
    """模拟器会话（adb 通道）"""

    def __init__(self) -> None:
        self.adb_path: Path | None = None
        self.serial: str | None = None
        self.width: int = 0
        self.height: int = 0

    @property
    def enabled(self) -> bool:
        return bool(_config_value("enabled", False))

    def _adb(self, *args: str, timeout: int = 20) -> subprocess.CompletedProcess:
        if self.adb_path is None:
            raise EmulatorError("未找到 adb")
        return _run([str(self.adb_path), *args], timeout=timeout)

    def find_adb(self) -> Path | None:
        """查找 adb：先用配置，再找 MuMu 自带，最后用 PATH 里的"""
        configured = _config_value("adb_path", "") or ""
        if configured and Path(configured).exists():
            return Path(configured)

        for root in MUMU_ROOTS:
            base = Path(root)
            if not base.exists():
                continue
            for pattern in MUMU_ADB_PATTERNS:
                for path in base.glob(pattern):
                    if path.exists():
                        return path

        found = shutil.which("adb")
        return Path(found) if found else None

    def _devices(self) -> list[str]:
        result = self._adb("devices")
        devices = []
        for line in result.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def _focused_package(self, serial: str) -> str:
        result = self._adb("-s", serial, "shell", "dumpsys", "window")
        text = result.stdout.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if "mCurrentFocus" in line and "Window{" in line:
                focus = line.split("Window{", 1)[1].split("}", 1)[0]
                parts = focus.split()
                if parts:
                    return parts[-1].split("/")[0]
        return ""

    def ensure_ready(self) -> bool:
        """准备 adb 与设备连接，返回是否可用"""
        if not self.enabled:
            return False

        prefix = _config_value("package_name", "") or DEFAULT_PACKAGE

        if self.adb_path is None:
            self.adb_path = self.find_adb()
        if self.adb_path is None:
            logger.ui_error("模拟器模式：未找到 adb，请在设置里填写 adb 路径")
            return False

        want_serial = _config_value("device_serial", "") or ""
        if want_serial and want_serial not in self._devices():
            self._adb("connect", want_serial)

        serials = self._devices()
        if want_serial and want_serial in serials:
            candidates = [want_serial]
        else:
            candidates = serials

        if not candidates:
            for port in DEVICE_PORTS:
                target = f"127.0.0.1:{port}"
                result = self._adb("connect", target)
                if b"connected" in result.stdout:
                    candidates.append(target)
                    break
            candidates = candidates or self._devices()

        if not candidates:
            logger.ui_error("模拟器模式：没有找到可用的模拟器设备")
            return False

        # 优先选择阴阳师在前台的设备
        chosen = ""
        for serial in candidates:
            if prefix and prefix.split(".")[-1][:6] in self._focused_package(serial):
                chosen = serial
                break
        if not chosen:
            for serial in candidates:
                package = self._focused_package(serial)
                if prefix and package.startswith(prefix.split("_")[0][:16]):
                    chosen = serial
                    break
        chosen = chosen or candidates[0]

        if chosen != self.serial:
            self.serial = chosen
            self.width = self.height = 0
            logger.ui(f"模拟器模式：使用设备 {chosen}")

        # 设备尺寸以截图为准（见 screenshot()）：wm size 报的是自然方向，
        # 横屏游戏的截图尺寸与之不同，用它会算错点击坐标。
        return self.serial is not None

    def screenshot(self) -> Image.Image:
        """截取模拟器画面并归一化到 1136×640"""
        if not self.ensure_ready():
            raise EmulatorError("模拟器不可用")

        result = self._adb("-s", self.serial, "exec-out", "screencap", "-p", timeout=30)
        raw = result.stdout
        if not raw:
            raise EmulatorError("模拟器截图返回空数据")

        image = Image.open(io.BytesIO(raw)).convert("RGB")
        # 以实际截图尺寸为准：wm size 报的是设备自然方向（可能是竖屏），
        # 横屏游戏的截图是 1920×1080，用错会让点击坐标整体偏移。
        self.width, self.height = image.size
        if image.size != CANONICAL_SIZE:
            image = image.resize(CANONICAL_SIZE, Image.LANCZOS)
        return image

    def scale(self) -> tuple[float, float]:
        """返回归一化坐标到设备坐标的缩放系数"""
        if not self.width or not self.height:
            self.screenshot()
        return self.width / CANONICAL_SIZE[0], self.height / CANONICAL_SIZE[1]

    def tap(self, x: int, y: int) -> None:
        """按归一化坐标点击"""
        scale_x, scale_y = self.scale()
        device_x = int(round(x * scale_x))
        device_y = int(round(y * scale_y))
        self._adb("-s", self.serial, "shell", "input", "tap", str(device_x), str(device_y))
        logger.info(f"emulator tap ({x},{y}) -> ({device_x},{device_y})")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """按归一化坐标滑动"""
        scale_x, scale_y = self.scale()
        args = [
            "-s",
            self.serial,
            "shell",
            "input",
            "swipe",
            str(int(round(x1 * scale_x))),
            str(int(round(y1 * scale_y))),
            str(int(round(x2 * scale_x))),
            str(int(round(y2 * scale_y))),
            str(max(int(duration_ms), 1)),
        ]
        self._adb(*args)
        logger.info(f"emulator swipe ({x1},{y1}) -> ({x2},{y2}) {duration_ms}ms")

    def keyevent(self, key: str | int) -> None:
        """发送按键事件，例如 esc/enter 对应的返回键/回车键"""
        mapping = {"esc": 4, "back": 4, "enter": 66, "space": 62}
        code = mapping.get(str(key).lower(), key)
        self._adb("-s", self.serial, "shell", "input", "keyevent", str(code))

    def sleep_until_game_foreground(self, timeout: float = 10.0) -> bool:
        """等待阴阳师回到前台"""
        prefix = _config_value("package_name", "") or DEFAULT_PACKAGE
        deadline = time.time() + timeout
        while time.time() < deadline:
            package = self._focused_package(self.serial or "")
            if package.startswith(prefix.split("_")[0][:16]):
                return True
            time.sleep(0.5)
        return False


emulator = Emulator()
"""全局模拟器会话"""
