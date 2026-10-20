"""P1测试默认禁止联网和加载模型/服务库。"""
import importlib.abc
import socket
import sys

import pytest


class NoModelLibraries(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "transformers", "bpy", "rembg", "fastapi", "langgraph"}:
            raise AssertionError("P1不得加载模型、GPU或服务依赖:" + fullname)
        return None


sys.meta_path.insert(0, NoModelLibraries())


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("P1离线测试不得联网")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
