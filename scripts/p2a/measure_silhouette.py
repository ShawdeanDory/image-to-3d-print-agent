"""可信操作者的CPU离线入口；路径受项目根目录约束，不是HTTP服务。"""
import argparse
import os
from pathlib import Path
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = ""
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from image_to_3d_print.measurement import MeasurementRequest, measure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", required=True, help="项目内尚不存在的相对目录")
    args = parser.parse_args()
    request = MeasurementRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
    report = measure(args.root, request, args.output)
    print(report.model_dump_json(indent=2))
    return 0 if report.tool.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
