"""下载本机从固定官方revision解析的公开CDN文件，不输出临时签名URL。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    plan = json.loads(args.manifest.read_text(encoding="utf-8"))

    def download(item):
        target = (root / item["destination"]).resolve()
        if not target.is_relative_to(root):
            raise ValueError("下载目标超出项目目录")
        if target.exists():
            raise RuntimeError(f"目标已存在，先核对：{item['destination']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".cdn-partial")
        started = time.perf_counter()
        digest = hashlib.sha256()
        count = 0
        with urllib.request.urlopen(item["url"], timeout=30) as response, temporary.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                count += len(chunk)
        if count != item["bytes"] or digest.hexdigest() != item["sha256"]:
            raise RuntimeError(f"文件完整性不符：{item['destination']}")
        temporary.replace(target)
        result = {"repo": item["repo"], "revision": item["revision"],
                  "filename": item["filename"], "bytes": count, "sha256": digest.hexdigest(),
                  "status": "verified", "seconds": time.perf_counter() - started}
        print(json.dumps(result), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(download, plan["files"]))
    for item in plan["cache_refs"]:
        path = root / item["ref_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["revision"], encoding="utf-8")
    args.report.write_text(json.dumps({"files": results, "status": "verified"}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
