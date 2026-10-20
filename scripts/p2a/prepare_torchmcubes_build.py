"""保留固定上游，在独立目录准备PyTorch2.5的C++17构建变体。"""
import difflib
import json
from pathlib import Path
import subprocess


root = Path(__file__).resolve().parents[2]
source = root / "runtime/upstream/torchmcubes"
target = root / "runtime/build/torchmcubes-cxx17"
revision = "879926d0ef58e6ce0ac2630fdecb5e53af7ed3ff"
assert subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() == revision
original = (source / "CMakeLists.txt").read_text(encoding="utf-8")
changed = original
for language in ["CXX", "CUDA"]:
    before = f"set(CMAKE_{language}_STANDARD 20)"
    assert changed.count(before) == 1
    changed = changed.replace(before, f"set(CMAKE_{language}_STANDARD 17)")
if not target.exists():
    files = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"]).decode().split("\0")
    for name in filter(None, files):
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source / name).read_bytes())
    (target / "CMakeLists.txt").write_text(changed, encoding="utf-8")
else:
    assert (target / "CMakeLists.txt").read_text(encoding="utf-8") == changed
diff = "".join(difflib.unified_diff(original.splitlines(True), changed.splitlines(True),
                                 fromfile="upstream/CMakeLists.txt", tofile="cxx17/CMakeLists.txt"))
(target / "cxx17-build.patch").write_text(diff, encoding="utf-8")
print(json.dumps({"source_revision": revision, "build_variant": "cxx17_cuda17", "diff": diff}))
