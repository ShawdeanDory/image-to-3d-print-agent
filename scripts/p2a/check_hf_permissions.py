"""读取小配置及1KiB权重Range验证权限；不加载模型、不保存权重或秘密。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = parsed.hostname or ""
        allowed = host == "huggingface.co" or host.endswith(".hf.co") or host.endswith(".huggingface.co")
        if parsed.scheme != "https" or not allowed:
            raise RuntimeError("拒绝非官方HTTPS重定向")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if host != urllib.parse.urlsplit(req.full_url).hostname:
            redirected.remove_header("Authorization")
        return redirected


def read_config(response):
    if response.status != 200:
        raise RuntimeError("配置响应不是200")
    payload = response.read(65537)
    if len(payload) > 65536:
        raise RuntimeError("配置超过64KiB上限")
    if not isinstance(json.loads(payload), dict):
        raise RuntimeError("配置不是JSON对象")
    return len(payload)


def read_weight_range(response):
    content_range = response.headers.get("Content-Range", "")
    if response.status != 206 or not re.fullmatch(r"bytes 0-1023/[0-9]+", content_range):
        raise RuntimeError("权重Range响应不符，不读取响应体")
    payload = response.read(1024)
    if len(payload) != 1024:
        raise RuntimeError("权重Range读取不完整")
    return {"bytes_read": len(payload), "content_range": content_range}


def check_model(item, token, opener):
    repo, revision = item["repo"], item["revision"]
    result = {"repo": repo, "revision": revision}
    config_url = f"https://huggingface.co/{repo}/resolve/{revision}/config.json"
    started = time.perf_counter()
    try:
        try:
            request = urllib.request.Request(config_url, method="HEAD")
            with opener.open(request, timeout=8) as response:
                result["unauthenticated_config_status"] = response.status
        except urllib.error.HTTPError as error:
            result["unauthenticated_config_status"] = error.code
        request = urllib.request.Request(config_url, headers={"Authorization": "Bearer " + token})
        with opener.open(request, timeout=8) as response:
            result["authenticated_config"] = {"http_status": response.status, "bytes_read": read_config(response)}
        weight_url = f"https://huggingface.co/{repo}/resolve/{revision}/model.safetensors"
        request = urllib.request.Request(weight_url, headers={"Authorization": "Bearer " + token, "Range": "bytes=0-1023"})
        with opener.open(request, timeout=8) as response:
            result["authenticated_weight_range"] = {"http_status": response.status, **read_weight_range(response),
                                                     "final_host": urllib.parse.urlsplit(response.url).hostname}
        result["status"] = "passed"
    except urllib.error.HTTPError as error:
        result.update(status="failed", http_status=error.code, error_type="HTTPError")
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__,
                      reason_type=type(getattr(error, "reason", error)).__name__)
    result["seconds"] = time.perf_counter() - started
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    token_file = root / "runtime/cache/huggingface/token"
    token = token_file.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"hf_[A-Za-z0-9]{20,}", token):
        raise RuntimeError("云端凭据格式不正确")
    plan = json.loads((root / "locks/p2a-source-plan.json").read_text(encoding="utf-8"))
    repos = {"facebook/dinov3-vitl16-pretrain-lvd1689m", "briaai/RMBG-2.0"}
    items = [item for item in plan["models"] if item["repo"] in repos]
    opener = urllib.request.build_opener(SafeRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: check_model(item, token, opener), items))
    passed = len(results) == 2 and all(item["status"] == "passed" for item in results)
    report = {"schema": "p2a_hf_network_evidence_v1", "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "passed" if passed else "failed", "tls_verification": True,
              "route": "autodl_official_proxy_with_official_ca", "models": results,
              "model_loading": "not_run", "dependency_installation": "not_run", "full_weight_download": "not_run"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
