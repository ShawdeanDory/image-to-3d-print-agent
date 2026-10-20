"""从唯一公共模型导出JSONSchema；--check只核对，不改写文件。"""
import argparse
import json
from pathlib import Path
import sys

from pydantic.json_schema import models_json_schema

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from image_to_3d_print.schemas import PUBLIC_MODELS, SCHEMA_VERSION


def schema_document():
    _, document = models_json_schema(
        [(model, "validation") for model in PUBLIC_MODELS],
        title="image_to_3d_print公共契约",
    )
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["x-contract-version"] = SCHEMA_VERSION
    document["x-public-models"] = [model.__name__ for model in PUBLIC_MODELS]
    document["description"] = "结构导出；跨字段、引用与文件校验仍须执行Pydantic及validation模块。"
    return document


def serialized_schema():
    return json.dumps(schema_document(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "schemas/contracts-v1.schema.json"
    expected = serialized_schema()
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != expected:
            parser.exit(1, "JSONSchema缺失或与公共模型不一致，请重新导出。\n")
        print("JSONSchema与20个公共模型一致。")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(expected, encoding="utf-8")
        print("已导出schemas/contracts-v1.schema.json。")


if __name__ == "__main__":
    main()
