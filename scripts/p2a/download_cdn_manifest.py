"""下载本机从固定官方revision解析的公开CDN文件，不输出临时签名URL。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.request


def download_file(item, root):
    root = root.resolve()
    target = (root / item["destination"]).resolve()
    if not target.is_relative_to(root):
        raise ValueError("下载目标超出项目目录")
    started = time.perf_counter()
    temporary = target.with_name(target.name + ".cdn-partial")
    source = target if target.exists() else temporary
    count = source.stat().st_size if source.exists() else 0
    resumed = count
    if count > item["bytes"]:
        raise RuntimeError("已有文件超过预期大小，不覆盖")
    digest = hashlib.sha256()
    if source.exists():
        with source.open("rb") as existing:
            while chunk := existing.read(1024 * 1024):
                digest.update(chunk)
    if target.exists() and (count != item["bytes"] or digest.hexdigest() != item["sha256"]):
        raise RuntimeError("已有完整文件校验失败，不覆盖")
    existing_complete = target.exists()
    if count < item["bytes"]:
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(item["url"], headers={"Range": f"bytes={count}-"} if count else {})
        with urllib.request.urlopen(request, timeout=30) as response:
            if count:
                expected = f"bytes {count}-{item['bytes']-1}/{item['bytes']}"
                if response.status != 206 or response.headers.get("Content-Range") != expected:
                    raise RuntimeError("Range响应不匹配，不追加已有partial")
            elif response.status != 200:
                raise RuntimeError("完整下载响应必须为200")
            with temporary.open("ab" if temporary.exists() else "xb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    count += len(chunk)
    if count != item["bytes"] or digest.hexdigest() != item["sha256"]:
        raise RuntimeError(f"文件完整性不符：{item['destination']}")
    if not existing_complete:
        temporary.replace(target)
    result = {"repo": item["repo"], "revision": item["revision"],
              "filename": item["filename"], "bytes": count, "sha256": digest.hexdigest(),
              "status": "verified_existing" if existing_complete else "verified",
              "resumed_bytes": resumed, "seconds": time.perf_counter() - started}
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    plan = json.loads(args.manifest.read_text(encoding="utf-8"))

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda item: download_file(item, root), plan["files"]))
    for item in plan["cache_refs"]:
        path = root / item["ref_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["revision"], encoding="utf-8")
    args.report.write_text(json.dumps({"files": results, "status": "verified"}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
