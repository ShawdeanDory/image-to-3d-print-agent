from pathlib import Path
from uuid import uuid4
import numpy as np
import pytest
from image_to_3d_print.geometry.core import MeshStore, topology, orient_and_scale, load_mesh
from image_to_3d_print.geometry.core import _large_topology
from image_to_3d_print.schemas import ModelTaskRequest
from image_to_3d_print.tools import ToolFailure, digest

FIXTURES=Path(__file__).resolve().parents[2]/'fixtures/p1/geometry'

@pytest.mark.parametrize('name,key,expect',[
    ('cube_10mm.stl','watertight',True),('open_cube.obj','boundary_edge_count',4),
    ('duplicate_face.obj','non_manifold_edge_count',3),('non_manifold_vertex.obj','non_manifold_vertex_count',1),
    ('reversed_face.obj','normals_consistent',False),('multiple_components.obj','component_count',2)])
def test_topology(name,key,expect):assert topology(load_mesh(FIXTURES/name))[key]==expect

@pytest.mark.parametrize('name',['cube_10mm.stl','open_cube.obj','non_manifold_vertex.obj','duplicate_face.obj','multiple_components.obj','reversed_face.obj'])
def test_sparse_topology_matches_reference(name):
    mesh=load_mesh(FIXTURES/name)
    sparse,reference=_large_topology(mesh),topology(mesh)
    if reference['volume'] is not None:assert sparse.pop('volume')==pytest.approx(reference.pop('volume'))
    assert sparse==reference

def request(**kw):
    return ModelTaskRequest(image_asset_id='asset',printer_profile_id='demo',height_value=2.,height_unit='cm',
        scale_source='user_target',orientation={'up_axis':'z','confirmed':True},**kw)

def test_orientation_scale():
    mesh=load_mesh(FIXTURES/'cube_10mm.stl'); before=mesh.vertices.copy()
    result,matrix=orient_and_scale(mesh,request())
    assert np.allclose(result.extents,[20,20,20]) and result.bounds[0,2]==0
    assert np.array_equal(mesh.vertices,before) and np.array(matrix).shape==(4,4)

def test_missing_constraints():
    req=ModelTaskRequest(image_asset_id='asset',printer_profile_id='demo')
    with pytest.raises(ToolFailure):orient_and_scale(load_mesh(FIXTURES/'cube_10mm.stl'),req)

def test_millimeter_conversion_overflow():
    req=ModelTaskRequest(image_asset_id='asset',printer_profile_id='demo',height_value=1e308,height_unit='cm',scale_source='user_target',orientation={'up_axis':'z','confirmed':True})
    with pytest.raises(ToolFailure):orient_and_scale(load_mesh(FIXTURES/'cube_10mm.stl'),req)

def test_scale_rejects_other_image(tmp_path):
    (tmp_path/'cube.stl').write_bytes((FIXTURES/'cube_10mm.stl').read_bytes())
    store=MeshStore(tmp_path);raw=store.import_mesh('cube.stl',uuid4(),parameters={'input_asset_id':'actual_image'})
    result=store.scale(raw.run_id,raw.mesh_version,request())
    assert not result.tool.succeeded and result.tool.error.code=='STATE_CONFLICT'

def test_version_and_clean(tmp_path):
    source=tmp_path/'in.obj';source.write_bytes((FIXTURES/'duplicate_face.obj').read_bytes())
    store=MeshStore(tmp_path); run=uuid4()
    original=store.import_mesh('in.obj',run)
    before=digest(tmp_path/original.relative_path)
    result=store.clean(run,original.mesh_version)
    assert result.tool.succeeded
    cleaned=store.get(run,result.tool.data['mesh_version'])
    assert cleaned.mesh_version!=original.mesh_version
    assert topology(load_mesh(tmp_path/cleaned.relative_path))['non_manifold_edge_count']==0
    assert digest(tmp_path/original.relative_path)==before

def test_cross_run_and_modified_mesh(tmp_path):
    (tmp_path/'mesh.stl').write_bytes((FIXTURES/'cube_10mm.stl').read_bytes())
    store=MeshStore(tmp_path); v=store.import_mesh('mesh.stl',uuid4())
    with pytest.raises(ToolFailure):store.get(uuid4(),v.mesh_version)
    (tmp_path/v.relative_path).write_bytes(b'bad')
    with pytest.raises(ToolFailure):store.get(v.run_id,v.mesh_version)
