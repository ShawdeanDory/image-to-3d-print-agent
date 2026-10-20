"""固定小文件验证暂停恢复与拒绝不正确响应，不连接公网。"""
import hashlib
import importlib.util
import io
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "cdn_installer", Path(__file__).resolve().parents[2] / "scripts/p2a/download_cdn_manifest.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONTENT = b"fixed-public-model-fixture"


def item():
    return {"repo": "fixture/model", "revision": "a" * 40, "filename": "model.bin",
            "destination": "weights/model.bin", "url": "https://example.invalid/public",
            "bytes": len(CONTENT), "sha256": hashlib.sha256(CONTENT).hexdigest()}


class Response(io.BytesIO):
    def __init__(self, content, status, content_range=None):
        super().__init__(content)
        self.status = status
        self.headers = {"Content-Range": content_range} if content_range else {}


def prepare_partial(root, data):
    path = root / "weights/model.bin.cdn-partial"
    path.parent.mkdir()
    path.write_bytes(data)
    return path


def test_valid_partial_uses_range_and_verifies(tmp_path, monkeypatch):
    partial = prepare_partial(tmp_path, CONTENT[:5])
    def opened(request, timeout):
        assert request.get_header("Range") == "bytes=5-"
        return Response(CONTENT[5:], 206, f"bytes 5-{len(CONTENT)-1}/{len(CONTENT)}")
    monkeypatch.setattr(MODULE.urllib.request, "urlopen", opened)
    result = MODULE.download_file(item(), tmp_path)
    assert result["resumed_bytes"] == 5
    assert (tmp_path / "weights/model.bin").read_bytes() == CONTENT
    assert not partial.exists()


def test_ignored_range_never_appends(tmp_path, monkeypatch):
    partial = prepare_partial(tmp_path, CONTENT[:5])
    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *a, **k: Response(CONTENT, 200))
    with pytest.raises(RuntimeError, match="Range"):
        MODULE.download_file(item(), tmp_path)
    assert partial.read_bytes() == CONTENT[:5]
    assert not (tmp_path / "weights/model.bin").exists()


def test_wrong_content_range_never_appends(tmp_path, monkeypatch):
    partial = prepare_partial(tmp_path, CONTENT[:5])
    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *a, **k: Response(CONTENT[5:], 206, "bytes 0-2/3"))
    with pytest.raises(RuntimeError, match="Range"):
        MODULE.download_file(item(), tmp_path)
    assert partial.read_bytes() == CONTENT[:5]


def test_corrupt_partial_never_becomes_complete(tmp_path, monkeypatch):
    prepare_partial(tmp_path, b"XXXXX")
    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *a, **k: Response(CONTENT[5:], 206, f"bytes 5-{len(CONTENT)-1}/{len(CONTENT)}"))
    with pytest.raises(RuntimeError, match="完整性"):
        MODULE.download_file(item(), tmp_path)
    assert not (tmp_path / "weights/model.bin").exists()


def test_complete_existing_file_is_reused(tmp_path, monkeypatch):
    path = tmp_path / "weights/model.bin"
    path.parent.mkdir()
    path.write_bytes(CONTENT)
    def forbidden(*a, **k):
        raise AssertionError("完整文件无需联网")
    monkeypatch.setattr(MODULE.urllib.request, "urlopen", forbidden)
    result = MODULE.download_file(item(), tmp_path)
    assert result["status"] == "verified_existing"
    assert path.read_bytes() == CONTENT


@pytest.mark.parametrize("empty_partial", [False, True])
def test_fresh_or_empty_partial_download(tmp_path, monkeypatch, empty_partial):
    if empty_partial:
        prepare_partial(tmp_path, b"")
    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *a, **k: Response(CONTENT, 200))
    result = MODULE.download_file(item(), tmp_path)
    assert result["resumed_bytes"] == 0
    assert (tmp_path / "weights/model.bin").read_bytes() == CONTENT
