"""用显式模型替身验证真实入口的种子传递，不执行GPU推理。"""
from contextlib import nullcontext
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

from image_to_3d_print.adapters.reconstruction import recorded_seed


def test_random_seed_reaches_pipeline_on_cold_and_reused_requests(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / 'scripts/tools/model_worker.py'
    spec = importlib.util.spec_from_file_location('seed_test_worker', script)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    calls = []

    class Pipeline:
        @classmethod
        def from_pretrained(cls, name):
            return cls()

        def cuda(self):
            return self

        def preprocess_image(self, image):
            return image

        def run(self, image, **kwargs):
            calls.append(kwargs)
            raise RuntimeError('test_fixture_stop_before_inference')

    monkeypatch.setitem(sys.modules, 'trellis2.pipelines', SimpleNamespace(Trellis2ImageTo3DPipeline=Pipeline))
    monkeypatch.setitem(sys.modules, 'o_voxel', SimpleNamespace(postprocess=object()))
    values = iter([0, 2147483647])
    monkeypatch.setattr(worker.secrets, 'randbelow', lambda upper: next(values))
    source = tmp_path / 'input.png'
    Image.new('RGB', (16, 16)).save(source)
    torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: None), inference_mode=nullcontext)
    cache = {}
    for expected in [0, 2147483647]:
        output = tmp_path / str(expected)
        output.mkdir()
        args = SimpleNamespace(output=output, input=source, export_target_faces=None, texture_size=None)
        with pytest.raises(RuntimeError, match='test_fixture_stop'):
            worker.course_fast_inference(args, None, torch, 0, pipeline_cache=cache)
        assert recorded_seed(output) == expected
    assert cache['weight_load_count'] == 1
    assert calls == [{'seed': seed, 'preprocess_image': False, 'pipeline_type': '1024_cascade'}
                     for seed in [0, 2147483647]]


def test_missing_seed_record_is_unknown(tmp_path):
    assert recorded_seed(tmp_path) is None
