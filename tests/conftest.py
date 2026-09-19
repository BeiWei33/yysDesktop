"""pytest 全局配置

测试不依赖本机的 data/config.yaml：这里把与运行环境相关的设置固定成默认值。
否则用户在应用里改了设置（例如开启「使用模拟器(MuMu)」）就会让一批和该功能无关的
测试莫名其妙地失败——曾经因为本机开启了模拟器模式，12 个视口/截图测试同时挂掉。
"""

import pytest

from src.utils.config import config


@pytest.fixture(autouse=True)
def isolate_runtime_config(monkeypatch):
    """把运行环境相关配置固定为默认值（桌面版、目标章节 28）"""
    monkeypatch.setattr(config.user.emulator, "enabled", False)
    monkeypatch.setattr(config.user.emulator, "device_serial", "")
    monkeypatch.setattr(config.user, "tansuo_target_chapter", 28)
