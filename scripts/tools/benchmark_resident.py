"""同一已用开发图、同一导出配置，比较逐任务冷加载与驻留冷/热请求。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from image_to_3d_print.adapters.reconstruction import BackendConfig,execute_worker
from image_to_3d_print.geometry.core import load_mesh
from image_to_3d_print.geometry.commands import ToolConfiguration
from image_to_3d_print.jobs.config import Settings
from image_to_3d_print.jobs.model_pool import ResidentModels


def gpu():
    return subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,memory.used,utilization.gpu','--format=csv,noheader'],text=True).strip()


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    storage=args.output/'application';storage.mkdir()
    images=storage/'assets';images.mkdir();source=images/'fixed-development-duck.jpg';shutil.copyfile(args.input,source)
    expected='1d6ac093c18648fc9568f58e310db3d1666d942cb0a2ea36b21be8384993f4ff'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==expected
    base=BackendConfig(backend='trellis2_candidate',python=args.root/'runtime/envs/trellis2/bin/python',execution_root=args.root,
        inference_profile='course_fast',export_target_faces=100000,texture_size=2048,gpu_hole_repair=True,timeout_s=1200)
    script=Path(__file__).with_name('model_worker.py')
    result={'kind':'real_gpu_fixed_development_benchmark','input_sha256':expected,'new_dataset_or_holdout':False,
        'configuration':{'pipeline_type':'1024_cascade','seed':42,'target_faces':100000,'texture_size':2048,'gpu_hole_repair':True},
        'gpu_before':gpu(),'trials':[],'new_llm_calls':0,'full_agent_or_print_test':False}
    def save():
        (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    def trial(label,config):
        run=str(uuid4());output=storage/'runs'/run/'tools'/('t_'+uuid4().hex[:16]);output.mkdir(parents=True)
        started=time.perf_counter()
        execution=execute_worker(config,'reconstruct',source,output,script)
        seconds=time.perf_counter()-started
        model=json.loads((output/'model.json').read_text())
        mesh=load_mesh(output/'raw_mesh.glb')
        record={'label':label,'run_id':run,'relative_output':output.relative_to(args.output).as_posix(),
            'caller_seconds':seconds,'execution':execution,'model':model,
            'readback':{'faces':len(mesh.faces),'vertices':len(mesh.vertices),'glb_bytes':(output/'fast_export.glb').stat().st_size},'gpu_after':gpu()}
        result['trials'].append(record);save()
        print(json.dumps({'trial':label,'seconds':seconds,'stages':model['seconds'],'resident':model.get('resident'),'readback':record['readback']},ensure_ascii=False),flush=True)
    pool=None
    try:
        trial('per_task_cold_baseline',base)
        settings=Settings(root=storage,tools=ToolConfiguration(backends={'trellis2_candidate':base.model_copy(update={'execution_mode':'resident'})}))
        pool=ResidentModels(settings);pool.ensure()
        resident=pool.settings.tools.backends['trellis2_candidate']
        trial('resident_first_cold',resident)
        trial('resident_second_warm',resident)
        first,second=result['trials'][1:]
        assert first['model']['resident']['model_reused'] is False
        assert second['model']['resident']['model_reused'] is True
        assert first['model']['resident']['instance_id']==second['model']['resident']['instance_id']
        assert first['model']['resident']['pid']==second['model']['resident']['pid']
        assert second['model']['resident']['weight_load_count']==1
        assert second['model']['resident']['request_index']==2
        result['resident_idle_state']=json.loads(resident.resident_socket.with_suffix('.json').read_text())
    except BaseException as exc:
        result['error']={'type':type(exc).__name__,'message':str(exc)};save();raise
    finally:
        if pool:pool.stop()
        result['gpu_after_owned_processes_stopped']=gpu();save()
    print(json.dumps({'status':'complete','trials':len(result['trials']),'gpu_after':result['gpu_after_owned_processes_stopped']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
