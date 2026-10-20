"""只检查固定缓存、权重头和官方输入，不实例化模型或调用GPU。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    os.environ["HF_HOME"] = str(root / "runtime/cache/huggingface")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    from huggingface_hub import hf_hub_download
    from PIL import Image
    import cv2

    plan = json.loads((root / "locks/p2a-source-plan.json").read_text(encoding="utf-8"))
    revisions = {item["repo"]: item["revision"] for item in plan["models"]}
    files = []

    def cached(repo, filename):
        path = Path(hf_hub_download(repo, filename, revision=revisions[repo], local_files_only=True))
        info = {"repo": repo, "revision": revisions[repo], "filename": filename, "bytes": path.stat().st_size}
        if filename.endswith(".json"):
            json.loads(path.read_text(encoding="utf-8"))
        elif filename.endswith(".safetensors"):
            with path.open("rb") as stream:
                length = struct.unpack("<Q", stream.read(8))[0]
                assert 0 < length <= 16 * 1024 * 1024, "权重头大小异常"
                header = json.loads(stream.read(length))
            tensors = [value for key, value in header.items() if key != "__metadata__"]
            assert tensors and max(value["data_offsets"][1] for value in tensors) == path.stat().st_size - 8 - length
            info["tensor_count"] = len(tensors)
            info["header_check"] = "passed"
        files.append(info)
        return path

    main_repo = "microsoft/TRELLIS.2-4B"
    pipeline = json.loads(cached(main_repo, "pipeline.json").read_text(encoding="utf-8"))
    for prefix in pipeline["args"]["models"].values():
        if prefix.startswith("ckpts/"):
            repo, filename = main_repo, prefix
        else:
            namespace, name, filename = prefix.split("/", 2)
            repo = namespace + "/" + name
        cached(repo, filename + ".json")
        cached(repo, filename + ".safetensors")
    for repo in ["facebook/dinov3-vitl16-pretrain-lvd1689m", "briaai/RMBG-2.0"]:
        for name in ["config.json", "preprocessor_config.json", "model.safetensors"]:
            cached(repo, name)
    for name in ["BiRefNet_config.py", "birefnet.py"]:
        cached("briaai/RMBG-2.0", name)

    cache = root / "runtime/cache/huggingface/hub"
    refs = {}
    for repo in sorted({item["repo"] for item in files}):
        actual = (cache / ("models--" + repo.replace("/", "--")) / "refs/main").read_text().strip()
        assert actual == revisions[repo], "离线main引用与固定revision不一致"
        refs[repo] = actual
    upstream = root / "runtime/upstream/TRELLIS.2"
    image_path = upstream / "assets/example_image/T.png"
    with Image.open(image_path) as image:
        image_info = {"size": list(image.size), "mode": image.mode}
        image.verify()
    image_info["sha256"] = hashlib.sha256(image_path.read_bytes()).hexdigest()
    hdri_path = upstream / "assets/hdri/forest.exr"
    hdri = cv2.imread(str(hdri_path), cv2.IMREAD_UNCHANGED)
    assert hdri is not None, "官方HDRI输入不可解码"
    report = {"status": "passed", "cache_file_count": len(files), "files": files,
              "fixed_main_refs": refs, "official_input": image_info,
              "official_hdri_shape": list(hdri.shape), "pipeline_type": pipeline["args"]["default_pipeline_type"],
              "model_loading": "not_run", "gpu_operations": "not_run",
              "integrity_scope": "本步检查缓存/JSON/权重头，完整摘要分别引用已有公开组和本轮受限组验证"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
