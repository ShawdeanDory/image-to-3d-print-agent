"""导出独立运行时扩展，不改变公共1.0.0Schema。"""
import argparse
import json
from pathlib import Path
import sys
from pydantic.json_schema import models_json_schema

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from image_to_3d_print.runtime_contracts import (CreateTask, ConstraintsInput, ImageReviewInput,
    PrintReviewInput, RepairRequestInput, RepairConfirmInput, SlicerInput, EventsPage, RuntimeTask, ParsedRequirements)


def serialized_schema():
    models = [CreateTask, ConstraintsInput, ImageReviewInput, PrintReviewInput, RepairRequestInput,
        RepairConfirmInput, SlicerInput, EventsPage, RuntimeTask, ParsedRequirements]
    _, doc = models_json_schema([(model, 'validation') for model in models], title='Agent运行时扩展')
    doc.update({'$schema': 'https://json-schema.org/draft/2020-12/schema', 'x-runtime-version': 'runtime-v1',
        'x-public-contract-version': '1.0.0', 'x-runtime-models': [m.__name__ for m in models]})
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'schemas/runtime-v1.schema.json'
    text = serialized_schema()
    if args.check:
        if not path.exists() or path.read_text(encoding='utf-8') != text: parser.exit(1, '运行时Schema与定义不一致\n')
        print('runtime-v1扩展Schema一致')
    else:
        path.write_text(text, encoding='utf-8')
        print('已导出runtime-v1扩展Schema')
