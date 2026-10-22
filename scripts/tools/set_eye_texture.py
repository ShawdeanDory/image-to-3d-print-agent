"""运营开关：不修改任务、原GLB、模型环境或实例状态。"""
import argparse
import json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--mode',choices=['on','off'],required=True)
    args=parser.parse_args();settings=json.loads(args.config.read_text(encoding='utf-8'))
    root=Path(settings['root']).resolve()
    if not (root/'tasks.sqlite3').is_file():raise SystemExit('未找到原任务数据库，拒绝写入其他目录')
    marker=root/'eye-texture.disabled'
    if args.mode=='off':marker.write_text('用户要求回退眼部试用；网页及新任务使用原件。\n',encoding='utf-8')
    else:marker.unlink(missing_ok=True)
    print(json.dumps({'eye_texture_enabled':args.mode=='on' and settings.get('eye_texture_enabled',True),
        'tasks_changed':False,'original_glb_changed':False},ensure_ascii=False))

if __name__=='__main__':main()
