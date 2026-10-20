"""权限探针保持重定向凭据边界，并拒绝整文件响应。"""
import importlib.util
import io
from pathlib import Path
import urllib.request

import pytest


spec = importlib.util.spec_from_file_location(
    "hf_permissions", Path(__file__).resolve().parents[2] / "scripts/p2a/check_hf_permissions.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_redirect_to_cdn_strips_authorization_preserves_range():
    request = urllib.request.Request("https://huggingface.co/model", headers={"Authorization": "Bearer fixture", "Range": "bytes=0-1023"})
    redirected = module.SafeRedirect().redirect_request(request, None, 302, "Found", {}, "https://us.aws.cdn.hf.co/file")
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Range") == "bytes=0-1023"


def test_redirect_rejects_untrusted_host_and_plain_http():
    request = urllib.request.Request("https://huggingface.co/model", headers={"Authorization": "Bearer fixture"})
    for target in ["https://example.invalid/file", "http://huggingface.co/file"]:
        with pytest.raises(RuntimeError, match="重定向"):
            module.SafeRedirect().redirect_request(request, None, 302, "Found", {}, target)


def test_ignored_range_rejects_before_reading_body():
    class Response:
        status = 200
        headers = {}
        def read(self, *args):
            raise AssertionError("不得读取服务器忽略Range后的整文件响应")
    with pytest.raises(RuntimeError, match="Range"):
        module.read_weight_range(Response())


def test_valid_range_reads_only_one_kib():
    response = io.BytesIO(b"x" * 2048)
    response.status = 206
    response.headers = {"Content-Range": "bytes 0-1023/1000000"}
    assert module.read_weight_range(response)["bytes_read"] == 1024
    assert response.tell() == 1024
