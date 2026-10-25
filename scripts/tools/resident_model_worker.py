"""TRELLIS.2专用常驻入口；懒加载一次，逐请求重新预处理/推理/导出。"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import gc
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from image_to_3d_print.adapters.resident_server import serve_model


class TrellisEngine:
    def __init__(self, root):
        self.root = root
        self.cache = {}
        self.torch = None

    @property
    def loaded(self):
        return bool(self.cache.get('pipeline') is not None)

    def resources(self):
        return {'weight_load_count': self.cache.get('weight_load_count', 0),
                'allocated_mib': self.torch.cuda.memory_allocated() / 2**20 if self.torch is not None else None}

    def __call__(self, request, context):
        started = time.perf_counter()
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('cuda_unavailable')
        self.torch = torch
        torch.set_num_threads(4)
        torch.cuda.reset_peak_memory_stats()
        source = self.root / 'runtime/upstream/TRELLIS.2'
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        from model_worker import course_fast_inference
        args = SimpleNamespace(root=self.root, input=request['input'], output=request['output'],
                               backend='trellis2_candidate', mode='reconstruct', profile='course_fast',
                               export_target_faces=request['export_target_faces'], texture_size=request['texture_size'],
                               gpu_hole_repair=request['gpu_hole_repair'])
        with (request['output'] / 'process.log').open('a', encoding='utf-8') as log:
            with redirect_stdout(log), redirect_stderr(log):
                return course_fast_inference(args, source, torch, started, pipeline_cache=self.cache, resident_context=context)

    def release_temporary(self):
        gc.collect()
        if self.torch is not None:
            self.torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--storage', type=Path, required=True)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--owner-pid', type=int, required=True)
    parser.add_argument('--owner-identity', required=True)
    args = parser.parse_args()
    serve_model(args.socket, args.storage, args.revision, args.owner_pid, args.owner_identity, lambda: TrellisEngine(args.root))


if __name__ == '__main__':
    main()
