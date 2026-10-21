from image_to_3d_print.inspection.service import inspect_mesh, InspectionConfig
from image_to_3d_print.adapters.reconstruction import ReconstructionAdapter, BackendConfig
from image_to_3d_print.geometry.structure import propose, confirm, apply_proposal
from image_to_3d_print.artifacts.export import export_mesh
from image_to_3d_print.geometry.core import MeshStore,load_mesh,topology
from image_to_3d_print.geometry.structure import StructureRequest
from image_to_3d_print.tools import ToolFailure,digest
from image_to_3d_print.schemas import PrinterProfile
from pathlib import Path
from uuid import uuid4
import numpy as np
import pytest

FIXTURES=Path(__file__).resolve().parents[2]/'fixtures/p1/geometry'
PROFILE=PrinterProfile.model_validate_json((FIXTURES.parent/'printer_profile.json').read_text())

def imported(tmp_path,name='cube_10mm.stl',unit='mm'):
    (tmp_path/name).write_bytes((FIXTURES/name).read_bytes())
    store=MeshStore(tmp_path);record=store.import_mesh(name,uuid4(),unit)
    return store,record

def test_tools_importable():
    assert all(callable(value) for value in [inspect_mesh,ReconstructionAdapter,propose,confirm,apply_proposal,export_mesh])

def test_missing_checker_blocks(tmp_path):
    store,record=imported(tmp_path)
    result=inspect_mesh(tmp_path,record.run_id,record.mesh_version,PROFILE,height_mm=10)
    assert not result.tool.succeeded and result.tool.error.code=='TOOL_UNAVAILABLE'
    checks={c['name']:c for c in result.tool.data['inspection']['checks']}
    assert checks['self_intersection']['status']=='not_run'
    assert checks['wall_thickness']['value'] is None
    assert result.tool.data['verdict']=='blocked'

def test_unknown_space_and_scale(tmp_path):
    store,record=imported(tmp_path,unit='unitless')
    result=inspect_mesh(tmp_path,record.run_id,record.mesh_version,PROFILE.model_copy(update={'build_volume_mm':None}))
    checks={c['name']:c for c in result.tool.data['inspection']['checks']}
    assert all(checks[name]['status']=='not_run' for name in ['dimensions','build_volume','bed_contact'])
    assert not export_mesh(tmp_path,record.run_id,record.mesh_version).tool.succeeded

def test_export_mm_gltf_roundtrip(tmp_path):
    store,record=imported(tmp_path)
    result=export_mesh(tmp_path,record.run_id,record.mesh_version)
    assert result.tool.succeeded and result.tool.data['independent_readback']
    assert np.allclose(result.tool.data['glb_reread_dimensions_mm'],[10,10,10])
    assert next(a for a in result.artifacts if a.kind=='candidate_stl').unit=='mm'
    assert not result.tool.data['task_success']

def test_hole_confirmation_and_idempotency(tmp_path):
    store,record=imported(tmp_path,'open_cube.obj')
    proposal=propose(tmp_path,record.run_id,record.mesh_version,StructureRequest(operation='fill_small_holes'))
    assert proposal.changes['after']['watertight']
    assert not apply_proposal(tmp_path,record.run_id,proposal.proposal_id).tool.succeeded
    confirm(tmp_path,record.run_id,proposal.proposal_id,'fixture_test',True,origin='test_fixture')
    result=apply_proposal(tmp_path,record.run_id,proposal.proposal_id)
    assert result.tool.succeeded and result.tool.data['confirmation_origin']=='test_fixture'
    duplicate=apply_proposal(tmp_path,record.run_id,proposal.proposal_id)
    assert duplicate.tool.data['already_applied'] and duplicate.tool.data['mesh_version']==result.tool.data['mesh_version']
    assert digest(tmp_path/record.relative_path)==record.sha256

def test_rejected_and_changed_preview(tmp_path):
    store,record=imported(tmp_path,'open_cube.obj')
    proposal=propose(tmp_path,record.run_id,record.mesh_version,StructureRequest(operation='fill_small_holes'))
    confirm(tmp_path,record.run_id,proposal.proposal_id,'fixture_test',False,origin='test_fixture')
    assert not apply_proposal(tmp_path,record.run_id,proposal.proposal_id).tool.succeeded
    with pytest.raises(ToolFailure):confirm(tmp_path,record.run_id,proposal.proposal_id,'fixture_test',True,origin='test_fixture')

def test_explicit_component_removal(tmp_path):
    store,record=imported(tmp_path,'multiple_components.obj')
    with pytest.raises(ToolFailure):propose(tmp_path,record.run_id,record.mesh_version,StructureRequest(operation='remove_components'))
    proposal=propose(tmp_path,record.run_id,record.mesh_version,StructureRequest(operation='remove_components',remove_components=[1]))
    assert proposal.changes['before']['component_count']==2 and proposal.changes['after']['component_count']==1
    assert topology(load_mesh(tmp_path/record.relative_path))['component_count']==2

def test_no_unnecessary_simplification(tmp_path):
    store,record=imported(tmp_path)
    with pytest.raises(ToolFailure):propose(tmp_path,record.run_id,record.mesh_version,StructureRequest(operation='simplify',target_faces=100))

def test_missing_model_config(tmp_path):
    from image_to_3d_print.image.assets import InputReview
    review=InputReview(asset_id='asset',foreground_artifact_id='foreground',decision='accepted',reviewer='fixture',
        complete_subject=True,simple_nonfunctional_ornament=True,foreground_correct=True,origin='test_fixture')
    result=ReconstructionAdapter(tmp_path,None).reconstruct(uuid4(),None,review)
    assert not result.tool.succeeded and result.tool.error.code=='MODEL_NOT_CONFIGURED'
