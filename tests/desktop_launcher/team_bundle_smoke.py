"""解压便携包，使用固定本机HTTP替身检查网页/代理；不调用SSH或云端。"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.request
import uuid
import zipfile


DATA = bytes(range(256)) * 8


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/api/v1/configuration':
            body = b'{"schema_version":"runtime-v1","configured_backends":["fixture_only"]}'
            self.send_response(200)
        elif self.path == '/api/v1/fixture-range':
            body = DATA[10:26]
            if self.headers.get('Range') != 'bytes=10-25':
                self.send_error(400)
                return
            self.send_response(206)
            self.send_header('Content-Range', f'bytes 10-25/{len(DATA)}')
        else:
            self.send_error(404)
            return
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        if body != b'fixed-upload-fixture':
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'OK')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    folder = project / 'runs' / ('队友解压 检查-' + uuid.uuid4().hex)
    folder.mkdir()
    with zipfile.ZipFile(args.archive) as archive:
        for entry in archive.infolist():
            if not (folder / entry.filename).resolve().is_relative_to(folder):
                raise ValueError('ZIP路径越界')
        archive.extractall(folder)
        bundle = folder / Path(archive.namelist()[0]).parts[0]
    result = {'cloud_called': False, 'model_called': False, 'fixture_only': True, 'checks': []}
    # 未配置包必须先提示首次配置，不能尝试读取本机其他SSH凭据。
    process = subprocess.run([str(bundle / '启动造物工坊.exe'), '--smoke'], cwd=bundle, capture_output=True, timeout=15)
    state = json.loads((bundle / 'runtime/launcher/last-result.json').read_text(encoding='utf-8-sig'))
    assert process.returncode == 2 and state['status'] == 'failed' and '首次配置.cmd' in state['error']['message']
    result['checks'].append('unconfigured_exe_stops_before_ssh')
    fixture = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as lease:
        lease.bind(('127.0.0.1', 0))
        port = lease.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if key.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    env['PATH'] = ''
    env['I3D_API_TARGET'] = f'http://127.0.0.1:{fixture.server_port}'
    log = (folder / 'vite.log').open('wb')
    web = subprocess.Popen([str(bundle / 'tools/node/node.exe'), str(bundle / 'frontend/node_modules/vite/bin/vite.js'), 'preview', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=bundle / 'frontend', env=env, stdout=log, stderr=subprocess.STDOUT)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f'http://127.0.0.1:{port}'

    def read(path, **options):
        with opener.open(urllib.request.Request(base + path, **options), timeout=5) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()

    try:
        deadline = time.monotonic() + 25
        while True:
            try:
                status, _, html = read('/')
                break
            except OSError:
                if web.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('便携网页未启动，查看' + str(folder / 'vite.log'))
                time.sleep(.2)
        assert status == 200 and '造物工坊' in html.decode()
        result['checks'].append('unicode_space_directory_without_system_node')
        assert json.loads(read('/api/v1/configuration')[2])['configured_backends'] == ['fixture_only']
        result['checks'].append('same_origin_api_proxy_fixture')
        status, headers, body = read('/api/v1/fixture-range', headers={'Range': 'bytes=10-25'})
        assert status == 206 and body == DATA[10:26] and headers['content-range'] == f'bytes 10-25/{len(DATA)}'
        result['checks'].append('range_and_binary_body_preserved')
        assert read('/api/v1/fixture-upload', data=b'fixed-upload-fixture', method='POST')[2] == b'OK'
        result['checks'].append('post_upload_body_preserved')
        assert read('/environment/forest.exr')[2] == (bundle / 'frontend/dist/environment/forest.exr').read_bytes()
        result['checks'].append('official_environment_file_served')
        assert '造物工坊' in read('/?task=fixture-task')[2].decode()
        result['checks'].append('task_url_served')
        for asset in (bundle / 'frontend/dist/assets').iterdir():
            assert read('/assets/' + asset.name)[2] == asset.read_bytes()
        result['checks'].append('javascript_and_css_served')
    finally:
        web.terminate()
        web.wait(timeout=10)
        log.close()
        fixture.shutdown()
        fixture.server_close()
    result['passed'] = len(result['checks'])
    result['processes_stopped'] = True
    (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
