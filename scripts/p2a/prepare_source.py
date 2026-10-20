"""按来源计划获取一份官方源码；已有目录只核对，不覆盖修改。"""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    plan = json.loads((root / "locks/p2a-source-plan.json").read_text(encoding="utf-8"))
    item = next(item for item in plan["sources"] if item["name"] == args.name)
    target = root / "runtime/upstream" / item["name"]

    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(target), *arguments], text=True).strip()

    if target.exists():
        if git("rev-parse", "HEAD") != item["revision"] or git("status", "--porcelain"):
            raise RuntimeError(f"已有目录版本或状态不符，请人工核对：{target}")
    else:
        target.mkdir(parents=True)
        subprocess.run(["git", "init", str(target)], check=True)
        subprocess.run(["git", "-C", str(target), "remote", "add", "origin", item["url"]], check=True)
        subprocess.run(["git", "-C", str(target), "fetch", "--depth=1", "origin", item["revision"]], check=True)
        subprocess.run(["git", "-C", str(target), "checkout", "--detach", item["revision"]], check=True)
    subprocess.run(["git", "-C", str(target), "submodule", "update", "--init", "--recursive", "--depth=1"], check=True)
    print(json.dumps({"name": args.name, "revision": git("rev-parse", "HEAD"),
                      "submodules": git("submodule", "status", "--recursive")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
