"""仅浏览器回归使用：真实API/SQLite/图/CPU几何，重建和Blender为显式测试替身。"""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
import uvicorn
from pytest import MonkeyPatch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'tests'))
from workflow.conftest import FixtureTools,pump
from image_to_3d_print.api.app import create_app
from image_to_3d_print.jobs.config import Settings
from image_to_3d_print.jobs.service import TaskService

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--port',type=int,default=8001)
    args=parser.parse_args()
    settings=Settings(root=args.root.resolve(),default_backend='triposr',confirmation_origin='test_fixture',
        operator_name='browser_test_fixture',profile_files=[ROOT/'fixtures/p1/printer_profile.json'])
    app=create_app(settings);service=app.state.service;patch=MonkeyPatch();tools=FixtureTools(patch,mesh='open_cube.obj')
    def worker():
        while True:
            with service.store.connect() as db:
                queued=[r[0] for r in db.execute("SELECT run FROM tasks WHERE status='queued'")]
            for run in queued:
                try:pump(service,settings,run,tools)
                except Exception as exc:print(type(exc).__name__,str(exc),flush=True)
                (args.root/'fixture-calls.json').write_text(json.dumps({'origin':'test_fixture','calls':tools.calls})+'\n',encoding='utf-8')
            time.sleep(.15)
    threading.Thread(target=worker,daemon=True).start()
    uvicorn.run(app,host='127.0.0.1',port=args.port)
