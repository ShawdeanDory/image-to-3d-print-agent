"""白名单构建Windows队友启动包；不复制项目runtime，不读取任何私钥/API密钥。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile


SECRET = re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC |ENCRYPTED )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{20,}|(?<![A-Za-z0-9_-])(?:hf_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{25,}|gh[pousr]_[A-Za-z0-9]{30,})(?![A-Za-z0-9_-])')


def scan_bundle(root):
    files = sorted(p for p in root.rglob('*') if p.is_file())
    allowed = ('config/', 'frontend/', 'scripts/desktop_launcher/', 'tools/node/', 'licenses/')
    root_files = {'启动造物工坊.exe', '首次配置.cmd', '先读我-队友启动说明.md', '使用说明.txt', '文件清单.json'}
    for file in files:
        relative = file.relative_to(root).as_posix()
        if relative not in root_files and not relative.startswith(allowed):
            raise ValueError('非白名单文件：' + relative)
        if file.is_symlink() or any(part in {'.git', 'runtime', 'secrets', '__pycache__'} for part in file.relative_to(root).parts):
            raise ValueError('禁止分发的目录：' + relative)
        if file.name.startswith('.env') or file.suffix.lower() in {'.key', '.pem', '.sqlite', '.sqlite3', '.log', '.glb', '.pth', '.pt', '.safetensors'}:
            raise ValueError('禁止分发的文件：' + relative)
        data = file.read_bytes()
        if SECRET.search(data) or b'C:\\Users\\Lenovo' in data or b'C:/Users/Lenovo' in data:
            raise ValueError('凭据或个人路径扫描未通过：' + relative)
    return files


def copy_package_closure(frontend, destination):
    """只复制Vite运行依赖闭包，保留嵌套布局及许可证，不复制开发插件/整个node_modules。"""
    pending = [('vite', frontend)]
    copied = set()
    versions = {}
    while pending:
        name, parent = pending.pop()
        current = parent
        while True:
            source = current / 'node_modules' / name
            if (source / 'package.json').is_file():
                break
            if current == frontend or current.parent == current:
                raise FileNotFoundError('缺少已安装的运行依赖：' + name)
            current = current.parent
        source = source.resolve()
        if not source.is_relative_to(frontend / 'node_modules'):
            raise ValueError('依赖不在当前前端目录：' + name)
        if source in copied:
            continue
        manifest = json.loads((source / 'package.json').read_text(encoding='utf-8'))
        if manifest.get('os') and 'win32' not in manifest['os'] and '!win32' not in manifest['os']:
            continue
        if manifest.get('cpu') and 'x64' not in manifest['cpu']:
            continue
        copied.add(source)
        target = destination / source.relative_to(frontend)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('node_modules', '.git', '.env', '.env.*', '__pycache__'))
        versions[str(source.relative_to(frontend)).replace('\\', '/')] = manifest['version']
        pending.extend((dependency, source) for dependency in manifest.get('dependencies', {}))
        for dependency in manifest.get('optionalDependencies', {}):
            # 平台可选包仅带上当前已安装的Windows版本。
            if (frontend / 'node_modules' / dependency / 'package.json').is_file():
                pending.append((dependency, source))
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--node-license', type=Path, required=True)
    parser.add_argument('--known-hosts', type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if not output.is_relative_to(project / 'runs') or output.exists() or output.with_suffix('.zip').exists():
        raise ValueError('输出必须为runs内的新目录，不覆盖旧交付')
    frontend = project / 'frontend'
    output.mkdir(parents=True)

    def copy(source, relative):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    config = json.loads((project / 'config/team-connection.example.json').read_text(encoding='utf-8'))
    if args.known_hosts:
        address = f'[{config["host"]}]:{config["port"]}'
        found = subprocess.run(['ssh-keygen', '-F', address, '-f', str(args.known_hosts)], capture_output=True, text=True, check=True)
        records = [line.split() for line in found.stdout.splitlines() if line and not line.startswith('#')]
        if not records:
            raise ValueError('现有known_hosts未找到目标服务器公钥')
        selected = next((entry for entry in records if entry[1] == 'ssh-ed25519'), records[0])
        config['host_key'] = ' '.join(selected[1:3])
    (output / 'config').mkdir()
    (output / 'config/team-connection.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    copy(project / 'config/launcher.example.json', 'config/launcher.example.json')
    for name in ('Launcher.cs', 'ensure_cloud_service.py'):
        copy(project / 'scripts/desktop_launcher' / name, 'scripts/desktop_launcher/' + name)
    # Windows PowerShell5需要BOM；源代码仍保持普通UTF-8。
    setup = (project / 'scripts/desktop_launcher/setup_team.ps1').read_text(encoding='utf-8-sig')
    (output / 'scripts/desktop_launcher/setup_team.ps1').write_text(setup, encoding='utf-8-sig')
    (output / '首次配置.cmd').write_bytes(b'@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\\desktop_launcher\\setup_team.ps1"\r\npause\r\n')
    guide = (project / 'doc/队友启动包使用说明.md').read_text(encoding='utf-8')
    (output / '先读我-队友启动说明.md').write_text(guide, encoding='utf-8-sig')
    (output / '使用说明.txt').write_text(guide, encoding='utf-8-sig')
    copy(args.node, 'tools/node/node.exe')
    copy(args.node_license, 'tools/node/LICENSE.txt')
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/codepage:65001', '/target:winexe', '/platform:x64', '/out:' + str(output / '启动造物工坊.exe'), '/r:System.Core.dll', '/r:System.Drawing.dll', '/r:System.Windows.Forms.dll', '/r:System.Web.Extensions.dll', str(project / 'scripts/desktop_launcher/Launcher.cs')], check=True, capture_output=True)
    shutil.copytree(frontend / 'dist', output / 'frontend/dist')
    copy(project / 'scripts/desktop_launcher/team-vite.config.mjs', 'frontend/vite.config.mjs')
    (output / 'frontend/package.json').write_text('{"name":"image3d-team-preview","private":true,"type":"module"}\n', encoding='utf-8')
    versions = copy_package_closure(frontend, output / 'frontend')
    for name in ('react', 'react-dom', 'three'):
        copy(frontend / 'node_modules' / name / 'LICENSE', 'licenses/' + name + '-LICENSE.txt')
    node_version = subprocess.check_output([str(args.node), '--version'], text=True).strip()
    manifest = {
        'kind': 'team-launcher-bundle-v1', 'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=project, text=True).strip(),
        'includes_task_changes': 'MID-BUNDLE-001', 'node': node_version, 'runtime_dependencies': versions,
        'private_keys_included': False, 'api_keys_included': False,
        'cloud_test': 'not_run', 'new_teammate_test': 'not_run',
        'files': [p.relative_to(output).as_posix() for p in scan_bundle(output)],
    }
    (output / '文件清单.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    files = scan_bundle(output)
    archive = output.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for file in files:
            zipped.write(file, output.name + '/' + file.relative_to(output).as_posix())
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:
            raise ValueError('ZIP完整性检查失败')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'files': len(files), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'node': node_version, 'dependencies': len(versions), 'secret_scan': 'passed', 'cloud_called': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
