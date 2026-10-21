"""导出独立桌面启动契约；不修改公共业务Schema。"""
import argparse
import json
from pathlib import Path
from pydantic import TypeAdapter
from image_to_3d_print.launcher_contracts import LauncherConfig,LauncherResult

parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
target=Path(__file__).resolve().parents[2]/'schemas/desktop-launcher-v1.schema.json'
value=TypeAdapter(LauncherConfig|LauncherResult).json_schema()
value['$schema']='https://json-schema.org/draft/2020-12/schema'
content=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
if args.check:
    if not target.exists() or target.read_text(encoding='utf-8')!=content:raise SystemExit('desktop launcher schema mismatch')
    print('desktop launcher schema consistent')
else:target.write_text(content,encoding='utf-8')
