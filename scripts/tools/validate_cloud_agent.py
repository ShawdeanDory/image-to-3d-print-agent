"""同一云端的真实模型/LLM/HTTP验证；自动确认明确为固定样例，不作人工验收。"""
import argparse,json,os,secrets,socket,sqlite3,subprocess,sys,time
from pathlib import Path
import httpx,psutil

REPO=Path(__file__).resolve().parents[2]

def secret_environment(file):
    if file.stat().st_mode & 0o077:
        raise ValueError('密钥文件必须仅当前用户可读写')
    token=file.read_text(encoding='utf-8-sig').strip()
    if len(token)<20 or any(c.isspace() for c in token):
        raise ValueError('密钥文本必须为一行有效配置')
    return {**os.environ,'I3D_LLM_API_KEY':token,'LANGSMITH_TRACING':'false','LANGCHAIN_TRACING_V2':'false'}

def stop(process):
    if process is None or process.poll() is not None:return
    process.terminate()
    try:process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        from image_to_3d_print.jobs.processes import kill_tree
        kill_tree(process.pid);process.wait(timeout=10)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,required=True)
    parser.add_argument('--secret-file',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--llm-model',default='deepseek-flash')
    parser.add_argument('--automated-fixture-confirmations',action='store_true',required=True)
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    project=args.project_root.resolve();started=time.perf_counter()
    config={'root':str(output/'storage'),'default_backend':'triposr','background_backend':'trellis2_candidate',
        'confirmation_origin':'test_fixture','operator_name':'cloud_fixture_automation','input_review_policy':'manual',
        'profile_files':[str(REPO/'fixtures/p1/printer_profile.json')],
        'tools':{'backends':{key:{'backend':key,'python':str(project/f'runtime/envs/{env}/bin/python'),
            'execution_root':str(project)} for key,env in [('triposr','triposr'),('trellis2_candidate','trellis2')]},
            'inspection':{'blender':str(project/'runtime/tools/blender-4.5.14-linux-x64/blender'),
                'addon_dir':str(project/'runtime/upstream/blender-addons')},'view_mappings':{}},
        'llm':{'base_url':'https://api.deepseek.com','model':args.llm_model,'thinking_mode':'disabled'}}
    config_path=output/'settings.json';config_path.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    environment=secret_environment(args.secret_file);environment['I3D_CONFIG']=str(config_path)
    api_token=secrets.token_urlsafe(24);environment['I3D_API_TOKEN']=api_token
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    log=(output/'service.log').open('wb');server=worker=None;cases=[]
    report={'kind':'real_cloud_agent_http','confirmation_origin':'test_fixture','human_acceptance':False,
        'model_execution':'not_run','llm_execution':'not_run','physical_printing':False,'formal_model_comparison':False,
        'cases':cases,'source_case':'development/block.png'}
    def save():
        report['seconds']=time.perf_counter()-started
        (output/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    def start_processes():
        nonlocal server,worker
        server=subprocess.Popen([sys.executable,'-m','uvicorn','image_to_3d_print.api.app:create_app','--factory',
            '--host','127.0.0.1','--port',str(port)],cwd=REPO,env=environment,stdout=log,stderr=log,start_new_session=True)
        worker=subprocess.Popen([sys.executable,'-m','image_to_3d_print.jobs.worker'],cwd=REPO,env=environment,
            stdout=log,stderr=log,start_new_session=True)
    try:
        start_processes()
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'Authorization':'Bearer '+api_token},timeout=10,trust_env=False) as client:
            def ready():
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    try:
                        response=client.get('/api/v1/configuration')
                        if response.status_code==200:return response.json()
                    except httpx.TransportError:pass
                    time.sleep(.2)
                raise RuntimeError('API启动失败')
            def runtime(run):
                response=client.get(f'/api/v1/model-tasks/{run}/runtime');response.raise_for_status();return response.json()
            def wait(run,kinds=(),terminal=True,seconds=360):
                deadline=time.monotonic()+seconds
                while time.monotonic()<deadline:
                    result=runtime(run)
                    status=result['response']['status'];pending=result.get('pending')
                    if terminal and status in {'failed','cancelled','succeeded'}:return result
                    if status=='waiting_for_input' and pending and pending['kind'] in kinds:return result
                    time.sleep(.25)
                raise RuntimeError('等待指定工作流步骤超时')
            def submit(run,value,fields):
                pending=value['pending']
                body={'submission_id':'s_'+secrets.token_hex(12),'kind':pending['kind'],
                    'pending_input_id':pending['pending_input_id'],'mesh_version':pending['mesh_version'],**fields}
                response=client.post(f'/api/v1/model-tasks/{run}/inputs',json=body);response.raise_for_status()
                duplicate=client.post(f'/api/v1/model-tasks/{run}/inputs',json=body);duplicate.raise_for_status()
                return body
            report['configuration']=ready()
            image=(REPO/'fixtures/p1/procedural/block.png').read_bytes()
            bad=client.post('/api/v1/assets',files={'file':('bad.png',b'not an image','image/png')})
            report['invalid_upload_http']=bad.status_code;assert bad.status_code==422
            uploaded=client.post('/api/v1/assets',files={'file':('block.png',image,'image/png')});uploaded.raise_for_status()
            asset=uploaded.json()['asset_id'];base={'image_asset_id':asset,'printer_profile_id':'demo_v1'}
            natural=client.post('/api/v1/model-tasks',json=base|{'description':'这是简单的方块摆件，目标高度8厘米。其他不明确的地方请追问，不要猜。'})
            natural.raise_for_status();run=natural.json()['run_id']
            value=wait(run,['constraints']);cases.append({'kind':'natural_language','run_id':run,'first':value});save()
            if value['response']['status']=='failed':
                # 明确记录真实LLM失败；新建结构化路径验证其余工具，不伪造LLM回答或静默换供应商。
                report['llm_execution']='failed';report['llm_failure']=value['response']['error']
                stop(worker);stop(server)
                config['llm']={};config_path.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
                start_processes();ready()
                response=client.post('/api/v1/model-tasks',json=base);response.raise_for_status();run=response.json()['run_id']
                value=wait(run,['constraints']);cases.append({'kind':'explicit_structured_without_llm','run_id':run,'first':value})
            else:report['llm_execution']='succeeded'
            # 第一任务等待时第二任务也能进入等待，证明worker未被占住。
            response=client.post('/api/v1/model-tasks',json=base);response.raise_for_status();second=response.json()['run_id']
            second_value=wait(second,['constraints']);assert second_value['pending']['kind']=='constraints'
            report['second_waiting_task']=second_value
            cancel=client.post(f'/api/v1/model-tasks/{second}/cancel');cancel.raise_for_status()
            assert cancel.json()['status']=='cancelled'
            submit(run,value,{'height_value':80.,'height_unit':'mm','scale_source':'user_target',
                'orientation':{'up_axis':'z','confirmed':True},'accept_suggestions':report['llm_execution']=='succeeded'})
            value=wait(run,['input_review']);assert (value.get('pending') or {}).get('kind')=='input_review',value['response'].get('error')
            submit(run,value,{'foreground_artifact_id':value['pending']['details']['foreground_artifact_id'],
                'decision':'accepted','complete_subject':True,'simple_nonfunctional_ornament':True,'foreground_correct':True})
            value=wait(run,['print_review','repair_request']);report['after_reconstruction']=value;save()
            if value['response']['status']=='failed':raise RuntimeError('真实工具链未到达复核步骤，错误已记录')
            report['model_execution']='succeeded'
            # 实际重启两个服务，等待项和已生成网格保持；不重复昂贵重建。
            original_pending=value['pending']['pending_input_id'];original_mesh=value['response']['data']['state']['mesh_version']
            deadline=time.monotonic()+30
            while True:
                with sqlite3.connect(Path(config['root'])/'tasks.sqlite3') as db:
                    pid=db.execute('SELECT runner_pid FROM tasks WHERE run=?',(run,)).fetchone()[0]
                if pid is None:break
                if time.monotonic()>deadline:raise RuntimeError('进入等待后runner未及时退出')
                time.sleep(.1)
            report['waiting_runner_released']=True
            stop(worker);stop(server);start_processes();ready();value=runtime(run)
            if not value.get('pending'):raise RuntimeError('重启未保留等待项：'+str(value['response'].get('error')))
            assert value['pending']['pending_input_id']==original_pending
            assert value['response']['data']['state']['mesh_version']==original_mesh
            report['waiting_restart_preserved']=True
            if value['pending']['kind']=='print_review':
                details=value['pending']['details']
                submit(run,value,{'preview_artifact_id':details['preview_artifact_id'],'bed_confirmed':True,
                    'components_confirmed':True,'component_count':details['component_count']})
                value=wait(run,['repair_request','slicer']);report['after_inspection']=value;save()
            if (value.get('pending') or {}).get('kind')=='repair_request':
                submit(run,value,{'stop':True});value=wait(run,[])
            elif (value.get('pending') or {}).get('kind')=='slicer':
                # 未实际切片，不生成虚假确认；保留等待，交付人工接续。
                report['awaiting_actual_slicer']=True
            report['final']=value
            events=client.get(f'/api/v1/model-tasks/{run}/events?limit=200').json()['events']
            count=sum(e['kind']=='tool_started' and e['data'].get('operation')=='reconstruct' for e in events)
            report['reconstruction_calls']=count;assert count==1
            report['events']=events
            report['reports_downloaded']=[]
            for artifact in value['response']['artifacts']:
                if artifact['kind']=='quality_report':
                    response=client.get(f'/api/v1/model-tasks/{run}/artifacts/{artifact["artifact_id"]}');response.raise_for_status()
                    target=output/(artifact['artifact_id']+Path(artifact['relative_path']).suffix);target.write_bytes(response.content)
                    report['reports_downloaded'].append(target.name)
            report['passed']=True
    except Exception as exc:
        report.update(passed=False,error={'type':type(exc).__name__,'message':str(exc)[:500]})
    finally:
        stop(worker);stop(server);log.close()
        report['service_processes_stopped']=all(p is None or p.poll() is not None for p in [server,worker])
        report['gpu_after']=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader'],text=True).strip()
        save()
    print(json.dumps({k:report.get(k) for k in ['passed','model_execution','llm_execution','error','seconds','gpu_after']}))
    return not report.get('passed',False)

if __name__=='__main__':raise SystemExit(main())
