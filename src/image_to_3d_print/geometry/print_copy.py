"""生产打印副本适配器：复用已验证算法，保留原件，不将导出视为打印认证。"""
import json
from pathlib import Path
import numpy as np
from .core import MeshStore,load_mesh
from .glb_preserve import write_plain_glb
from ..tools import ToolFailure,ToolSession


def repair_copy(root,run,version,reference_version,phase,inspection,height,min_wall,config):
    from ..print_demo import native_call,shape_gate
    session=ToolSession(root,run,'repair',version)
    if config is None:raise ToolFailure('TOOL_UNAVAILABLE','未配置MeshFix/MeshLib打印副本工具')
    if config.policy=='wall05-components-v2' and min_wall!=.5:
        raise ToolFailure('STATE_CONFLICT','0.5mm修复政策需要同任务0.5mm配置')
    store=MeshStore(root);source=store.get(run,version);reference=store.get(run,reference_version)
    if source.unit!='mm' or reference.unit!='mm' or inspection.mesh_version!=version:
        raise ToolFailure('STATE_CONFLICT','打印修复需要同任务/同版本的毫米网格和检查')
    previous=source.parameters.get('print_copy_phase',0)
    if phase!=previous+1 or source.repair_round>=2:
        raise ToolFailure('REPAIR_LIMIT_REACHED','打印副本只允许依次执行两轮')
    # 参考版本必须是当前版本祖先，避免用另一个网格绕过保形门槛。
    ancestor=source
    while ancestor.mesh_version!=reference_version and ancestor.parent:
        ancestor=store.get(run,ancestor.parent)
    if ancestor.mesh_version!=reference_version:raise ToolFailure('STATE_CONFLICT','保形参考不是当前网格祖先')
    if phase==2 and source.parameters.get('print_copy_reference')!=reference_version:
        raise ToolFailure('STATE_CONFLICT','第二轮必须沿用第一轮保形参考')
    if phase==2 and source.parameters.get('print_copy_policy','legacy')!=config.policy:
        raise ToolFailure('STATE_CONFLICT','第二轮必须沿用第一轮打印修复政策')
    mesh=load_mesh(Path(root)/source.relative_path)
    try:
        candidate,facts=native_call(mesh,session.directory,phase,config,inspection,height,min_wall)
    except (ToolFailure,OSError,ValueError) as exc:
        if (session.directory/'native.log').is_file():session.add('native_log',session.directory/'native.log','log')
        return session.fail(exc.code if isinstance(exc,ToolFailure) else 'TOOL_UNAVAILABLE',str(exc)[:300],
            {'phase':phase,'source_mesh_version':version,'original_unchanged':True})
    original=load_mesh(Path(root)/reference.relative_path)
    shape=shape_gate(original,candidate)
    components=facts.get('components',{})
    if config.policy=='wall05-components-v2' and phase==2 and (components.get('removed_components') or facts.get('post_local_components',{}).get('removed_components')):
        from .print_components import main_component
        # 删除已获本轮授权；单列全模型损失，主体保形门槛仍为97%/2%。
        whole_shape=shape
        body,selection=main_component(original)
        shape=shape_gate(body,candidate)
        shape.update(scope='末轮删除副壳体后的主体保形；完整模型变化另列',
            reference_selection=selection,whole_model_comparison=whole_shape)
    for name in ('before-component-removal.stl','after-fusion.stl','native-result.json','post-local-repair/before-component-removal.stl'):
        path=session.directory/name
        if path.is_file():session.add(name.replace('.','_').replace('/','_'),path,'log')
    record={'phase':phase,'method':facts,'shape':shape,'source_mesh_version':version,'reference_version':reference_version}
    details=session.directory/'acceptance.json';details.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    # 保存拒绝候选供诊断，禁止覆盖有效版本。
    file=session.directory/'candidate.glb';write_plain_glb(candidate,file,'mm')
    reread=load_mesh(file)
    if len(reread.faces)!=len(candidate.faces) or not np.allclose(reread.extents,candidate.extents,atol=.01):
        return session.fail('INVALID_ARGUMENT','打印候选独立读回不一致')
    session.add('candidate',file,'repaired_mesh','mm')
    retained=False
    if not shape['accepted']:
        if config.policy!='wall05-components-v2' or phase!=1:
            session.add('acceptance',details,'inspection_report')
            return session.fail('INVALID_ARGUMENT','打印候选外形变化超出保形门槛，保留上一有效版本')
        # 已尝试但未应用候选，保持原几何登记阶段进度，允许末轮从上一有效模型重试。
        retained=True;candidate=mesh.copy();file=session.directory/'retained.glb'
        write_plain_glb(candidate,file,'mm')
        record.update(candidate_applied=False,retained_previous=True)
    else:record['candidate_applied']=True
    details.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    session.add('acceptance',details,'inspection_report')
    result=store._write(run,candidate,'mm','print_copy_repair',version,
        {'print_copy_phase':phase,'print_copy_reference':reference_version,'print_copy_record':record,
         'print_copy_policy':config.policy,'appearance':'print_geometry_without_original_uv','rebaked':False},phase,original_path=file)
    session.mesh_version=result.mesh_version
    return session.finish({'mesh_version':result.mesh_version,'print_copy':record,
        'appearance':'print_geometry_without_original_uv','rebaked':False,'retained_previous':retained})


def export_copy(root,run,version,*,colored=False):
    from ..artifacts.export import _check_same_geometry
    session=ToolSession(root,run,'export',version);source=MeshStore(root).get(run,version)
    if source.unit!='mm':raise ToolFailure('STATE_CONFLICT','打印副本导出需要明确毫米尺度')
    mesh=load_mesh(Path(root)/source.relative_path)
    glb=session.directory/'print-copy.glb'
    if colored:
        from ..artifacts.print_color import reproject_pbr
        from .glb_preserve import GLBDocument
        reference=source
        while True:
            path=Path(root)/reference.relative_path
            if path.suffix.lower()=='.glb' and GLBDocument(path).has_uv:break
            if not reference.parent:raise ToolFailure('REFERENCE_NOT_FOUND','缺少本任务UV/PBR来源，不能把灰版当彩色版')
            reference=MeshStore(root).get(run,reference.parent)
        appearance=reproject_pbr(path,mesh,glb)
        appearance.update(source_mesh_version=reference.mesh_version,source_sha256=reference.sha256)
    else:
        display=mesh.copy();display.visual.vertex_colors=np.tile([180,200,210,255],(len(display.vertices),1))
        write_plain_glb(display,glb,'mm')
        appearance={'status':'print_geometry','pbr_available':False,'rebaked':False,
            'warning':'打印副本允许必要重网格、填实内腔、有限厚度补偿/底部切平，不含原UV/PBR；原始彩色GLB后台保留，未经重烘焙。'}
    stl=session.directory/'print-copy.stl';mesh.export(stl)
    _check_same_geometry(mesh,load_mesh(glb))
    stl_mesh=load_mesh(stl);_check_same_geometry(mesh,stl_mesh)
    main=session.add('glb',glb,'repaired_mesh','mm');stl_record=session.add('stl',stl,'candidate_stl','mm')
    return session.finish({'artifact_id':main.artifact_id,'stl_artifact_id':stl_record.artifact_id,
        'mesh_version':version,'dimensions_mm':mesh.extents.tolist(),'face_count':len(mesh.faces),
        'independent_readback':True,'artifact_frames':{main.artifact_id:'y_up',stl_record.artifact_id:'z_up'},
        'appearance':appearance,'print_certified':False})
