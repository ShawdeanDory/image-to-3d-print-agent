import json
from uuid import uuid4
from pathlib import Path
from PIL import Image
from image_to_3d_print.geometry.core import MeshStore
from image_to_3d_print.geometry.view import measure_view

def test_unconfirmed_mapping_never_gets_quality_score(tmp_path):
    file=tmp_path/'cube.stl';file.write_bytes((Path(__file__).resolve().parents[2]/'fixtures/p1/geometry/cube_10mm.stl').read_bytes())
    source=MeshStore(tmp_path).import_mesh('cube.stl',uuid4(),parameters={'backend':'triposr','coordinate_system':'z_up_unitless'})
    Image.new('L',(10,10),255).save(tmp_path/'mask.png')
    mapping={'backend':'triposr','upstream_revision':'107cefdc244c39106fa830359024f6a2f1c78871','status':'development_calibrated',
        'human_review':'pending','rotation':[[1,0,0],[0,1,0],[0,0,1]],'protocol_version':'1.0.0'}
    (tmp_path/'mapping.json').write_text(json.dumps(mapping))
    # 使用原固定测量协议，模拟数据只验证权限分支。
    (tmp_path/'evals').mkdir();(tmp_path/'evals/protocol_v1.json').write_bytes((Path(__file__).resolve().parents[2]/'evals/protocol_v1.json').read_bytes())
    result=measure_view(tmp_path,source.run_id,source.mesh_version,'mask.png','triposr','mapping.json')
    assert result.tool.data['metric']['status']=='not_run' and result.tool.data['metric']['value'] is None
    mapping['human_review']='passed';(tmp_path/'mapping.json').write_text(json.dumps(mapping))
    accepted=measure_view(tmp_path,source.run_id,source.mesh_version,'mask.png','triposr','mapping.json')
    assert accepted.tool.succeeded and accepted.tool.data['metric']['value']==1
    wrong_backend=measure_view(tmp_path,source.run_id,source.mesh_version,'mask.png','trellis2_candidate','mapping.json')
    assert not wrong_backend.tool.succeeded and wrong_backend.tool.error.code=='STATE_CONFLICT'

def test_missing_mapping_is_explicit(tmp_path):
    result=measure_view(tmp_path,uuid4(),'m_unknown','mask.png','triposr',None)
    assert result.tool.data['metric']['status']=='not_run'
