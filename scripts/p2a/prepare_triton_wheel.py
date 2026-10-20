"""复用中断的同版本轮子，并按PyPI官方摘要校验后交给pip。"""
from pathlib import Path
import shutil

from download_cdn_manifest import download_file


def main():
    root = Path(__file__).resolve().parents[2]
    filename = "triton-3.2.0-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
    item = {
        "repo": "pypi/triton", "revision": "3.2.0", "filename": filename,
        "destination": "runtime/wheels/" + filename,
        # 同一文件经实测可用的中科大镜像续传，摘要来自PyPI官方JSON。
        "url": "https://mirrors.ustc.edu.cn/pypi/packages/01/65/3ffa90e158a2c82f0716eee8d26a725d241549b7d7aaf7e4f44ac03ebd89/" + filename,
        "bytes": 253090354,
        "sha256": "b3e54983cd51875855da7c68ec05c05cf8bb08df361b1d5b69e05e40b0c9bd62",
    }
    target = root / item["destination"]
    partial = target.with_name(target.name + ".cdn-partial")
    if not target.exists() and not partial.exists():
        candidates = [p for p in (root / "runtime/tmp").rglob(filename)
                      if 0 < p.stat().st_size <= item["bytes"]]
        if candidates:
            source = max(candidates, key=lambda p: p.stat().st_size)
            partial.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, partial)
    download_file(item, root)


if __name__ == "__main__":
    main()
