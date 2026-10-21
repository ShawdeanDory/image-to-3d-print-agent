from uuid import uuid4
from pathlib import Path
from image_to_3d_print.geometry.core import MeshStore
from image_to_3d_print.inspection.service import preview_mesh

def test_preview_never_fakes_missing_blender(tmp_path):
    file=tmp_path/'cube.stl';file.write_bytes((Path(__file__).resolve().parents[2]/'fixtures/p1/geometry/cube_10mm.stl').read_bytes())
    source=MeshStore(tmp_path).import_mesh('cube.stl',uuid4(),'mm')
    result=preview_mesh(tmp_path,source.run_id,source.mesh_version,None)
    assert not result.tool.succeeded and result.tool.error.code=='TOOL_UNAVAILABLE'
