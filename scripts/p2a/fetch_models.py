"""下载计划中的固定官方权重组；访问失败直接保留错误，不切换来源。"""
import argparse
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=["triposr", "trellis_public", "trellis_gated"])
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    root = Path(__file__).resolve().parents[2]
    plan = json.loads((root / "locks/p2a-source-plan.json").read_text(encoding="utf-8"))
    groups = {
        "triposr": {"stabilityai/TripoSR", "facebook/dino-vitb16"},
        "trellis_public": {"microsoft/TRELLIS.2-4B", "microsoft/TRELLIS-image-large"},
        "trellis_gated": {"facebook/dinov3-vitl16-pretrain-lvd1689m", "briaai/RMBG-2.0"},
    }
    for item in plan["models"]:
        if item["repo"] not in groups[args.group]:
            continue
        snapshot = Path(snapshot_download(
            repo_id=item["repo"], revision=item["revision"],
            allow_patterns=item["allow_patterns"], ignore_patterns=item.get("ignore_patterns"),
            max_workers=2))
        refs = snapshot.parent.parent / "refs"
        refs.mkdir(exist_ok=True)
        (refs / "main").write_text(item["revision"], encoding="utf-8")
        if item["local_dir"]:
            target = root / item["local_dir"]
            target.mkdir(parents=True, exist_ok=True)
            for filename in item["allow_patterns"]:
                destination = target / filename
                if destination.exists():
                    raise RuntimeError(f"目标已存在，须先核对：{destination}")
                shutil.copy2(snapshot / filename, destination)
        print(json.dumps({"repo": item["repo"], "revision": item["revision"],
                          "snapshot": str(snapshot.relative_to(root)), "status": "downloaded"}))


if __name__ == "__main__":
    main()
