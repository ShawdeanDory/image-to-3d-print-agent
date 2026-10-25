"""仅Linux进程回归使用的假引擎；生产入口没有此模式，不加载GPU。"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from image_to_3d_print.adapters.resident_protocol import process_identity
from image_to_3d_print.adapters.resident_server import serve_model


class FixtureEngine:
    def __init__(self, delay):self.loaded=False;self.delay=delay;self.calls=0
    def resources(self):return {'allocated_mib':None,'evidence_origin':'test_fixture'}
    def release_temporary(self):pass
    def __call__(self,request,context):
        reused=self.loaded;self.loaded=True;self.calls+=1
        time.sleep(self.delay)
        if request['input'].read_bytes()==b'RAISE':raise RuntimeError('fixed_failure_fixture')
        report={'resident':{**context,'model_reused':reused,'weight_load_count':1},
                'input_sha256':request['input_sha256'],'evidence_origin':'test_fixture','calls':self.calls}
        (request['output']/'model.json').write_text(json.dumps(report))
        return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--socket',type=Path,required=True);p.add_argument('--storage',type=Path,required=True)
    p.add_argument('--owner',type=int,required=True);p.add_argument('--delay',type=float,default=.01);args=p.parse_args()
    serve_model(args.socket,args.storage,'75fbf0183001ed9876c8dbb35de6b68552ee08bd',args.owner,process_identity(args.owner),lambda:FixtureEngine(args.delay))
