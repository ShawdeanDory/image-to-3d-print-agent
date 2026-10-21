"""开发测试替身仅在tests内；实际CPU几何/SQLite/LangGraph仍真实执行。"""
import io
import json
from pathlib import Path
from uuid import uuid4
import pytest
from PIL import Image
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from image_to_3d_print.jobs.config import Settings
from image_to_3d_print.jobs.service import TaskService
from image_to_3d_print.workflow.graph import build_graph
from image_to_3d_print.geometry.commands import dispatch
from image_to_3d_print.geometry.core import MeshStore
from image_to_3d_print.tools import ToolSession

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def setup_service(tmp_path):
    settings = Settings(root=tmp_path, default_backend='triposr',
        profile_files=[REPO / 'fixtures/p1/printer_profile.json'])
    service = TaskService(settings)
    payload = io.BytesIO()
    image = Image.new('RGBA', (64, 64))
    image.paste((30, 100, 180, 255), (10, 10, 54, 54))
    image.save(payload, 'PNG')
    asset = service.assets.save(payload.getvalue(), 'input.png')
    request = {'image_asset_id': asset.asset_id, 'printer_profile_id': 'demo_v1',
        'height_value': 10., 'height_unit': 'mm', 'scale_source': 'user_target',
        'orientation': {'up_axis': 'z', 'confirmed': True}}
    return service, settings, request, payload.getvalue()


class FixtureTools:
    def __init__(self, monkeypatch, mesh='cube_10mm.stl', thin=False, hole_unchanged=False):
        self.calls = []
        self.mesh = mesh
        self.hole_unchanged = hole_unchanged
        self.thin = thin
        def fixture_blender(config, operation, mesh, directory, parameters=None):
            if operation == 'preview':
                Image.new('RGB', (32, 32), (100, 20, 80)).save(directory / 'preview.png')
                return {'operation': operation, 'blender_version': 'TEST_FIXTURE'}
            result = {'operation': operation, 'blender_version': 'TEST_FIXTURE',
                'self_intersection_faces': [], 'thin_faces_low': [0] if self.thin else [],
                'thin_faces_high': [], 'overhang_faces': [], 'critical_overhang_faces': []}
            (directory / 'blender-result.json').write_text(json.dumps(result), encoding='utf-8')
            return result
        monkeypatch.setattr('image_to_3d_print.inspection.service.blender_call', fixture_blender)

    def __call__(self, root, command, config, **kwargs):
        op = command['operation']
        self.calls.append(op)
        if op == 'reconstruct':
            path = root / ('fixture-mesh' + Path(self.mesh).suffix)
            path.write_bytes((REPO / 'fixtures/p1/geometry' / self.mesh).read_bytes())
            version = MeshStore(root).import_mesh(path.name, command['run_id'])
            session = ToolSession(root, command['run_id'], 'reconstruct', version.mesh_version)
            session.add('raw', root / version.relative_path, 'raw_mesh', 'unitless')
            return session.finish({'mesh_version': version.mesh_version, 'evidence_origin': 'test_fixture'})
        result = dispatch(root, command, config, **kwargs)
        return result


def pump(service, settings, run, tools=None, language_model=None):
    row = service.store.row(run)
    ctx = row['context']
    with service.store.connect() as db:
        db.execute("UPDATE tasks SET status='running' WHERE run=?", (run,))
    with SqliteSaver.from_conn_string(str(service.store.root / 'checkpoints.sqlite3')) as saver:
        graph = build_graph(settings, service.store, saver, tool_dispatch=tools or dispatch, language_model=language_model)
        config = {'configurable': {'thread_id': run}, 'recursion_limit': 160}
        if ctx['status'] == 'waiting_for_input':
            graph.invoke(Command(resume=service.store.pending_submission(run, ctx['pending']['pending_input_id'])), config)
        else:
            ctx['status'] = 'running'
            ctx['evidence_origin'] = 'test_fixture' if tools else 'runtime'
            graph.invoke({'ctx': ctx}, config)
    return service.store.row(run)


def answer(service, run, kind, **values):
    ctx = service.store.row(run)['context']
    pending = ctx['pending']
    body = {'submission_id': 's_' + uuid4().hex, 'pending_input_id': pending['pending_input_id'],
        'mesh_version': ctx['mesh_version'], 'kind': kind, **values}
    service.submit(run, body)
    return body


def review_image(service, run):
    ctx = service.store.row(run)['context']
    return answer(service, run, 'input_review', foreground_artifact_id=ctx['pending']['details']['foreground_artifact_id'],
        decision='accepted', complete_subject=True, simple_nonfunctional_ornament=True, foreground_correct=True)


def review_print(service, run):
    ctx = service.store.row(run)['context']
    return answer(service, run, 'print_review', preview_artifact_id=ctx['pending']['details']['preview_artifact_id'],
        bed_confirmed=True, components_confirmed=False)
