"""通过已授权SSH的标准输入执行；只补启动既有服务，不提交任务或读取密钥内容。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.request


def is_our_api(value):
    return isinstance(value,dict) and value.get('schema_version')=='runtime-v1' and isinstance(value.get('configured_backends'),list)


def probe_api():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:8000/api/v1/configuration',timeout=2) as response:
            value=json.load(response)
        if not is_our_api(value):raise RuntimeError('云端8000端口运行其他服务，请人工检查，不自动终止它')
        return value
    except urllib.error.HTTPError as exc:
        if exc.code==401:raise RuntimeError('云端API要求访问凭据，请在网页配置服务访问令牌；启动器不读取或绕过认证') from exc
        raise RuntimeError('云端API返回HTTP'+str(exc.code)+'，请检查应用日志') from exc
    except urllib.error.URLError:
        return None


def worker_running(storage):
    import fcntl
    lock=storage/'worker.lock'
    if not lock.exists():return False
    with lock.open('r+b') as file:
        try:fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        fcntl.flock(file,fcntl.LOCK_UN)
    return False


def start_component(project,code,component):
    if shutil.which('screen') is None:raise RuntimeError('云端缺少screen；不会自动安装环境')
    logs=project/'runtime/launcher';logs.mkdir(parents=True,exist_ok=True)
    subprocess.run(['screen','-L','-Logfile',str(logs/(component+'.log')),'-dmS','i3d-backend-'+component,
        'bash',str(code/'scripts/tools/start_cloud_backend.sh'),component,str(project)],cwd=code,check=True,timeout=10)


def ensure(project,code):
    project=project.resolve();code=code.resolve()
    if not code.is_relative_to(project/'deployments'):raise RuntimeError('只能使用项目现有deployments内的明确部署')
    script=code/'scripts/tools/start_cloud_backend.sh'
    if not script.is_file():raise RuntimeError('未找到已部署启动脚本，不自动切换到其他后端或目录')
    settings=json.loads((project/'runtime/config/backend.json').read_text())
    storage=Path(settings['root']).resolve()
    if not storage.is_relative_to(project):raise RuntimeError('服务存储不在当前项目，拒绝启动')
    result={'kind':'desktop_cloud_services','api':'already_running','worker':'already_running','model_submitted':False}
    if probe_api() is None:
        start_component(project,code,'api');result['api']='started'
        deadline=time.monotonic()+40
        while probe_api() is None:
            if time.monotonic()>deadline:raise RuntimeError('云端API启动超时，请检查runtime/launcher/api.log')
            time.sleep(.4)
    if not worker_running(storage):
        start_component(project,code,'worker');result['worker']='started'
        deadline=time.monotonic()+15
        while not worker_running(storage):
            if time.monotonic()>deadline:raise RuntimeError('云端worker启动超时，请检查runtime/launcher/worker.log')
            time.sleep(.3)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--deployment',required=True)
    args=parser.parse_args()
    # 序列化启动，不以过期screen名字判断存活，也不杀已有worker。
    import fcntl
    folder=args.project/'runtime/launcher';folder.mkdir(parents=True,exist_ok=True)
    with (folder/'start.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:print(json.dumps(ensure(args.project,args.project/args.deployment),ensure_ascii=False))
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
            print(json.dumps({'kind':'desktop_cloud_services','error':str(exc),'model_submitted':False},ensure_ascii=False))
            raise SystemExit(2)


if __name__=='__main__':main()
