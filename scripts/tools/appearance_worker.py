"""同实例既有TRELLIS.2环境的底色修正worker；不加载生成模型或联网。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from image_to_3d_print.artifacts.appearance_projection import run_projection
from image_to_3d_print.artifacts.eye_texture import Declined,EyeTexturePolicy


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','original','prepared','output','report','policy'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() or args.source.resolve()==args.output.resolve():raise ValueError('拒绝覆盖源或已有候选')
    policy=EyeTexturePolicy.model_validate_json(args.policy.read_text(encoding='utf-8'))
    if policy.version!='eye-local-v2':raise ValueError('此worker只执行v2策略')
    try:
        details=run_projection(args.source,args.original,args.prepared,args.output,policy=policy)
        result={'status':'applied','reason':'已生成眼部及有依据的可见皮肤/服装底色副本；可见头发按原图参考色校正，背面未恢复，视觉待检查','details':details}
    except Declined as exc:
        result={'status':'skipped','reason':str(exc),'details':{}}
    except Exception as exc:
        result={'status':'failed','reason':type(exc).__name__+'：'+str(exc)[:220],'details':{}}
    # 拒绝/失败仍保留配准证据，但不能登记未通过的候选。
    alignment=args.output.parent/'alignment.json'
    if alignment.exists() and not result['details']:
        result['details']=json.loads(alignment.read_text(encoding='utf-8'))
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'reason':result['reason']},ensure_ascii=False))


if __name__=='__main__':main()
