"""只读云端GLB改造预检，不读取凭据、不提交任务。"""
import json,os,pathlib,sqlite3
project=pathlib.Path('/root/autodl-tmp/image-to-3d-print-agent')
config=json.loads((project/'runtime/config/backend.json').read_text());root=pathlib.Path(config['root'])
processes=[]
for folder in pathlib.Path('/proc').iterdir():
    if not folder.name.isdigit():continue
    try:
        args=(folder/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        if ' -m image_to_3d_print.api' not in args and ' -m image_to_3d_print.jobs.worker' not in args:continue
        env=dict(x.split(b'=',1) for x in (folder/'environ').read_bytes().split(b'\0') if b'=' in x)
        processes.append({'pid':int(folder.name),'command':args,'code':env.get(b'PYTHONPATH',b'').decode(),'config':env.get(b'I3D_CONFIG',b'').decode()})
    except (OSError,PermissionError):pass
connection=sqlite3.connect((root/'tasks.sqlite3').as_uri()+'?mode=ro',uri=True)
print(json.dumps({'root':str(root),'processes':processes,'task_status_counts':connection.execute('select status,count(*) from tasks group by status').fetchall(),
    'inspection':config.get('tools',{}).get('inspection',config.get('inspection'))},ensure_ascii=False))
