"""导出内部工具schema；公共contracts-v1.schema.json不变。"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from pydantic import TypeAdapter
from typing import Union
from image_to_3d_print.geometry.commands import Command,ToolConfiguration
from image_to_3d_print.tools import ToolOutcome
from image_to_3d_print.geometry.core import MeshVersion
from image_to_3d_print.geometry.structure import Proposal

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    schema=TypeAdapter(Union[Command,ToolConfiguration,ToolOutcome,MeshVersion,Proposal]).json_schema()
    schema['$id']='geometry-tools-v0.1.schema.json'
    content=json.dumps(schema,ensure_ascii=False,indent=2,sort_keys=True)+'\n'
    target=ROOT/'schemas/geometry-tools-v0.1.schema.json'
    if args.check:
        if not target.exists() or target.read_text(encoding='utf-8')!=content:raise SystemExit('内部工具schema未同步')
    else:
        target.parent.mkdir(exist_ok=True)
        target.write_text(content,encoding='utf-8')
    print('geometry tool schema consistent')

if __name__=='__main__':main()
