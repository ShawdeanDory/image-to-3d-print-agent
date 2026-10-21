"""离线测试禁止模型/GPU与公网；服务库已由后端实现授权启用。"""
import importlib.abc
import socket
import sys

import pytest


class NoModelLibraries(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "transformers", "bpy", "rembg"}:
            raise AssertionError("离线测试不得加载模型或GPU依赖:" + fullname)
        return None


sys.meta_path.insert(0, NoModelLibraries())


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    original_connect = socket.socket.connect
    original_create = socket.create_connection
    backend = 'workflow' in request.node.path.parts
    def local(address):
        return backend and isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1', 'localhost'}
    def denied(*args, **kwargs):
        raise AssertionError("P1离线测试不得联网")
    def create(address, *args, **kwargs):
        return original_create(address, *args, **kwargs) if local(address) else denied()
    def connect(sock, address):
        return original_connect(sock, address) if local(address) else denied()
    monkeypatch.setattr(socket, "create_connection", create)
    monkeypatch.setattr(socket.socket, "connect", connect)
