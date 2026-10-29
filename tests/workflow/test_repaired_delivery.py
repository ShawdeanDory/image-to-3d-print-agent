"""当前修复版交付；模型/Blender为明确fixture，CPU图/材质/导出真实执行。"""
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
import trimesh
from .conftest import FixtureTools,pump
from .test_automatic_generation import automatic
from image_to_3d_print.runtime_contracts import CreateTask
from image_to_3d_print.geometry.core import MeshStore,load_mesh
from image_to_3d_print.geometry.glb_preserve import GLBDocument,prepare_inspection_glb
from image_to_3d_print.artifacts.pbr import source_record
from image_to_3d_print.tools import ToolSession,digest
from image_to_3d_print.workflow.state import save_context


class TexturedFixture(FixtureTools):
    def __call__(self,root,command,config,**kwargs):
        if command['operation']!='reconstruct':return super().__call__(root,command,config,**kwargs)
        self.calls.append('reconstruct');session=ToolSession(root,command['run_id'],'reconstruct')
        box=trimesh.creation.box();faces=box.faces[:-2] if self.mesh=='open_cube.obj' else box.faces
        mesh=trimesh.Trimesh(vertices=box.vertices[faces].reshape(-1,3),faces=np.arange(len(faces)*3).reshape(-1,3),process=False)
        mesh.visual=trimesh.visual.TextureVisuals(uv=np.tile([[0.,0.],[1.,0.],[0.,1.]],(len(faces),1)),material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new('RGB',(8,8),(70,140,220)),metallicFactor=.2,roughnessFactor=.6))
        original=session.directory/'fixture-original.glb';original.write_bytes(trimesh.exchange.gltf.export_glb(mesh,include_normals=True))
        self.original=original;self.original_sha=digest(original)
        raw=session.directory/'raw_mesh.glb';prepare_inspection_glb(original,raw,'y_up')
        metadata={'official_export_frame':'y_up','parameters':{'texture_size':2048}}
        version=MeshStore(root).import_mesh(raw.relative_to(root).as_posix(),command['run_id'],parameters={'appearance_source':source_record(root,original,metadata)})
        session.mesh_version=version.mesh_version;session.add('original',original,'raw_mesh','unitless')
        return session.finish({'mesh_version':version.mesh_version,'model':metadata,'evidence_origin':'test_fixture'})


def test_new_tasks_choose_repaired_delivery_and_old_idempotency_keeps_snapshot(setup_service):
    service,settings,request=automatic(setup_service)
    run=service.create(CreateTask(request=request),'old-snapshot')['run_id']
    assert service.store.row(run)['context']['delivery_policy']=='repaired-glb-v1'
    ctx=service.store.row(run)['context'];ctx['delivery_policy']='original-glb-v1';save_context(service.store,ctx)
    previous=service.create(CreateTask(request=request),'old-snapshot')
    assert previous['schema_version']=='original-glb-v1' and previous['run_id']==run
    new=service.create(CreateTask(request=request),'new')['run_id']
    assert service.store.row(new)['response']['schema_version']=='generation-v1'


def test_final_checked_glb_retains_pbr_original_and_target_scale(setup_service,monkeypatch):
    service,settings,request=automatic(setup_service);tools=TexturedFixture(monkeypatch)
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    assert row['status']=='succeeded',row['context'].get('error')
    response=row['response'];delivery=response['delivery'];version=row['context']['mesh_version']
    artifact=next(a for a in response['artifacts'] if a['artifact_id']==delivery['artifact_id'])
    assert artifact['kind']=='repaired_mesh' and artifact['mesh_version']==version==response['data']['inspection']['mesh_version']
    assert artifact['unit']=='mm'
    final=GLBDocument(settings.root/artifact['relative_path']);original=GLBDocument(tools.original)
    assert final.has_uv and final.material_signature()==original.material_signature()
    np.testing.assert_allclose(load_mesh(settings.root/artifact['relative_path']).extents,[10,10,10],atol=.001)
    assert digest(tools.original)==tools.original_sha and tools.calls.count('reconstruct')==1
    assert tools.calls.count('export_glb')==1 and 'export_original_glb' not in tools.calls
    assert delivery['print_certified'] is False
    report=next(a for a in response['artifacts'] if a['kind']=='quality_report' and a['relative_path'].endswith('.md'))
    assert '已有UV/PBR和纹理字节保持' in (settings.root/report['relative_path']).read_text(encoding='utf-8')


def test_legacy_original_snapshot_still_delivers_original_glb(setup_service,monkeypatch):
    service,settings,request=automatic(setup_service);run=service.create(CreateTask(request=request))['run_id']
    ctx=service.store.row(run)['context'];ctx['delivery_policy']='original-glb-v1';save_context(service.store,ctx)
    tools=TexturedFixture(monkeypatch);row=pump(service,settings,run,tools)
    assert row['status']=='succeeded',row['context'].get('error')
    assert row['response']['schema_version']=='original-glb-v1'
    assert row['response']['delivery']['print_check']=='not_run' and 'export_original_glb' in tools.calls
    assert digest(tools.original)==tools.original_sha


def test_textured_hole_keeps_existing_uv_and_marks_untextured_patch(setup_service,monkeypatch):
    service,settings,request=automatic(setup_service);tools=TexturedFixture(monkeypatch,mesh='open_cube.obj')
    run=service.create(CreateTask(request=request))['run_id'];row=pump(service,settings,run,tools)
    assert row['status']=='succeeded',row['context'].get('error')
    ctx=row['context'];assert ctx['repair_attempts']==1
    artifact=next(a for a in row['response']['artifacts'] if a['artifact_id']==ctx['delivery']['artifact_id'])
    original=GLBDocument(tools.original);final=GLBDocument(settings.root/artifact['relative_path'])
    assert final.material_signature()['images_sha256']==original.material_signature()['images_sha256']
    assert final.material_signature()['materials'][:1]==original.material_signature()['materials']
    assert final.tree['extras']['i3d']['untextured_patch_faces']==2
    assert ctx['export_data']['appearance']['rebaked'] is False
    assert any('补片三角面没有原始纹理依据' in w for w in ctx['delivery']['warnings'])
    assert any('untextured_patch'==p.get('extras',{}).get('appearance') for p in final.primitives)
    assert digest(tools.original)==tools.original_sha


@pytest.mark.parametrize('manual',[None,50000])
def test_export_budget_reaches_first_trellis_reconstruction(setup_service,monkeypatch,manual):
    service,settings,request=automatic(setup_service);fixture=TexturedFixture(monkeypatch);commands=[]
    def tools(root,command,config,**kw):
        commands.append(command);return fixture(root,command,config,**kw)
    run=service.create(CreateTask(request=request,backend='trellis2_candidate',export_target_faces=manual,texture_size=4096))['run_id']
    row=pump(service,settings,run,tools);assert row['status']=='succeeded'
    command=next(c for c in commands if c['operation']=='reconstruct')
    assert command['export_target_faces']==(manual or row['context']['mesh_budget']['effective_target_faces'])
    assert command['texture_size']==4096 and command['gpu_hole_repair'] is True
    assert command['reconstruction_profile']=='course_fast'
    assert len([c for c in commands if c['operation']=='reconstruct'])==1
