"""本机/云端可信操作者CLI；服务层应直接调用commands.dispatch。"""
import argparse,json,signal
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from image_to_3d_print.geometry.commands import COMMANDS,ToolConfiguration,dispatch

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--request',type=Path,required=True);parser.add_argument('--config',type=Path)
    parser.add_argument('--human-action',action='store_true',help='仅可信操作者在实际人工复核后使用；Agent工具不得设置')
    args=parser.parse_args()
    def interrupted(signum,frame):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,interrupted)
    command=COMMANDS.validate_json(args.request.read_text(encoding='utf-8'))
    config=ToolConfiguration.model_validate_json(args.config.read_text(encoding='utf-8')) if args.config else ToolConfiguration()
    try:outcome=dispatch(args.root,command,config,human_action=args.human_action)
    except KeyboardInterrupt:
        print(json.dumps({'error':{'code':'STATE_CONFLICT','message':'操作者已中断工具，本次子进程组已清理'}},ensure_ascii=False))
        return 130
    print(outcome.model_dump_json(indent=2))
    return 0 if outcome.tool.succeeded else 1

if __name__=='__main__':raise SystemExit(main())
