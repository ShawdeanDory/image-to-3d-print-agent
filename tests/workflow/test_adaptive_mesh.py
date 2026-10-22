"""模型/Blender为显式几何替身；CPU保形、版本、自动图和导出实际执行。"""
import pytest
import trimesh
import numpy as np
from image_to_3d_print.geometry.core import MeshStore
from image_to_3d_print.tools import ToolSession
from image_to_3d_print.runtime_contracts import CreateTask
from .test_automatic_generation import automatic
from .conftest import FixtureTools,pump


@pytest.mark.parametrize('reject',[False,True,'first'])
def test_simple_budget_applied_or_original_preserved(setup_service,monkeypatch,reject):
    service,settings,request=automatic(setup_service);fixture=FixtureTools(monkeypatch)
    def model(root,command,config,**kw):
        if command['operation']=='reconstruct':
            fixture.calls.append('reconstruct');path=root/'source-sphere.ply'
            sphere=trimesh.creation.icosphere(subdivisions=6 if reject=='first' else 5);sphere.vertices[:,2]=np.maximum(sphere.vertices[:,2],-.99);sphere.export(path)
            version=MeshStore(root).import_mesh(path.name,command['run_id'])
            session=ToolSession(root,command['run_id'],'reconstruct',version.mesh_version)
            session.add('raw',root/version.relative_path,'raw_mesh','unitless')
            return session.finish({'mesh_version':version.mesh_version,'evidence_origin':'test_fixture'})
        return fixture(root,command,config,**kw)
    def blender(config,operation,mesh,directory,parameters=None):
        if operation=='simplify':
            output=trimesh.creation.icosphere(subdivisions=5 if parameters['target_faces']==30000 else 4);output.vertices[:,2]=np.maximum(output.vertices[:,2],-.99)
            output.apply_scale(mesh.extents[0]/2);output.apply_translation([0,0,-output.bounds[0,2]])
            if reject is True or reject=='first' and parameters['target_faces']==10000:output.vertices[:,0]*=.5
            return {'vertices':output.vertices.tolist(),'faces':output.faces.tolist()}
        return {'self_intersection_faces':[],'thin_faces_low':[],'thin_faces_high':[]}
    monkeypatch.setattr('image_to_3d_print.geometry.structure.blender_call',blender)
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,model);ctx=row['context']
    assert row['status']=='succeeded' and not ctx['pending'] and fixture.calls.count('reconstruct')==1
    budget=ctx['mesh_budget'];assert budget['target_faces']==10000
    assert budget['target_met'] is (not reject),ctx.get('repair_attempt_log')
    assert budget['actual_faces']==(20480 if reject else 5120)
    assert ctx['repair_attempts']==(2 if reject=='first' else 1) and not ctx.get('human_reviews')
    assert (settings.root/'source-sphere.ply').exists()
    assert ctx['repair_attempt_log'][0]['adaptive_budget']
    if reject:assert budget['fallback_reason'] and ctx['repair_attempt_log'][0]['status']=='failed'
    else:assert ctx['repair_attempt_log'][0]['status']=='applied'
    if reject=='first':assert budget['attempted_targets']==[10000,30000] and ctx['repair_attempt_log'][1]['status']=='applied'


def test_old_policy_does_not_gain_new_analysis(setup_service,monkeypatch):
    service,settings,request=automatic(setup_service);run=service.create(CreateTask(request=request))['run_id']
    ctx=service.store.row(run)['context'];ctx.pop('face_budget_policy')
    from image_to_3d_print.workflow.state import save_context
    save_context(service.store,ctx)
    tools=FixtureTools(monkeypatch);row=pump(service,settings,run,tools)
    assert row['status']=='succeeded' and 'analyze_complexity' not in tools.calls
    assert not row['context'].get('mesh_budget')
