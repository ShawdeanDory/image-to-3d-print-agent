"""从已有JSONSchema生成前端类型，不另维护一套公共字段。"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ts(schema):
    if '$ref' in schema:
        return schema['$ref'].rsplit('/', 1)[-1]
    if 'const' in schema:
        return json.dumps(schema['const'], ensure_ascii=False)
    if 'enum' in schema:
        return ' | '.join(json.dumps(v, ensure_ascii=False) for v in schema['enum'])
    if 'anyOf' in schema or 'oneOf' in schema:
        return '(' + ' | '.join(ts(s) for s in schema.get('anyOf', schema.get('oneOf'))) + ')'
    kind = schema.get('type')
    if kind == 'null': return 'null'
    if kind == 'boolean': return 'boolean'
    if kind in {'integer', 'number'}: return 'number'
    if kind == 'string': return 'string'
    if kind == 'array':
        if 'prefixItems' in schema:
            return '[' + ', '.join(ts(s) for s in schema['prefixItems']) + ']'
        return f'Array<{ts(schema.get("items", {}))}>'
    if kind == 'object':
        fields = schema.get('properties', {})
        if not fields:
            additional = schema.get('additionalProperties', {})
            return 'Record<string, ' + (ts(additional) if isinstance(additional, dict) else 'unknown') + '>'
        required = set(schema.get('required', []))
        return '{\n' + '\n'.join('  ' + json.dumps(k) + ('' if k in required else '?') + ': ' + ts(v) + ';' for k, v in fields.items()) + '\n}'
    return 'unknown'


def render():
    defs = {}
    for name in ['contracts-v1.schema.json', 'runtime-v1.schema.json']:
        document = json.loads((ROOT / 'schemas' / name).read_text(encoding='utf-8'))
        for key, value in document['$defs'].items():
            if key in defs and defs[key] != value: raise ValueError('公共/运行时定义冲突：' + key)
            defs[key] = value
    return '// 自动生成：python scripts/tools/export_frontend_types.py；不要手改。\n' + '\n\n'.join(
        f'export type {key} = {ts(value)};' for key, value in sorted(defs.items())) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'frontend/src/contracts.generated.ts'
    expected = render()
    if args.check:
        if not path.exists() or path.read_text(encoding='utf-8') != expected: parser.exit(1, '前端类型与公共Schema不一致\n')
        print('前端类型与公共1.0.0/runtime-v1一致')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding='utf-8')
