"""日志文件名规则：模拟器模式下按设备分文件，桌面版保持不变。"""

from src.utils.log import log_file_name


def test_desktop_keeps_original_name():
    """未开启模拟器时文件名必须和以前完全一样。"""
    assert log_file_name("yysDesktop", False, "", 1234) == "yysDesktop.log"
    assert log_file_name("yysDesktop", False, "127.0.0.1:16448", 1234) == "yysDesktop.log"


def test_emulator_uses_device_port():
    assert log_file_name("yysDesktop", True, "127.0.0.1:16448", 1234) == "yysDesktop-16448.log"
    assert log_file_name("yysDesktop", True, "127.0.0.1:16416", 1234) == "yysDesktop-16416.log"


def test_emulator_sanitizes_serial_without_port():
    """没有端口（例如 emulator-5556）时做安全化处理，不能出现非法文件名字符。"""
    name = log_file_name("yysDesktop", True, "emulator-5556", 1234)

    assert name == "yysDesktop-emulator_5556.log"
    assert not set(name) & set(':\\/*?"<>|')


def test_emulator_without_device_falls_back_to_pid():
    """配置里没指定设备（自动选择）时用进程号区分多个实例。"""
    assert log_file_name("yysDesktop", True, "", 4242) == "yysDesktop-pid4242.log"
    assert log_file_name("yysDesktop", True, "   ", 4242) == "yysDesktop-pid4242.log"


def test_emulator_serial_only_separators_falls_back_to_pid():
    assert log_file_name("yysDesktop", True, ":", 777) == "yysDesktop-pid777.log"
