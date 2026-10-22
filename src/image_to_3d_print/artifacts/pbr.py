"""把同任务官方材质烘焙到最终网格；几何检查仍使用不可变PLY版本。"""
import json
import struct
from pathlib import Path
from typing import Literal
from uuid import UUID
import numpy as np
from pydantic import Field
from ..schemas.common import ContractModel,RelativePath
from ..tools import ToolFailure,digest


class AppearanceSource(ContractModel):
    relative_path:RelativePath
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    frame:Literal['z_up','y_up']
    texture_size:int=Field(default=2048,ge=256,le=4096)


def source_record(root,file,metadata):
    return AppearanceSource(relative_path=file.relative_to(root).as_posix(),sha256=digest(file),
        frame=metadata['official_export_frame'],
        texture_size=metadata.get('parameters',{}).get('texture_size',2048)).model_dump(mode='json')


def _pbr_document(file):
    with file.open('rb') as stream:
        header=stream.read(20)
        if len(header)!=20:raise ValueError('官方GLB头无效')
        magic,version,total,length,kind=struct.unpack('<4sIIII',header)
        if magic!=b'glTF' or version!=2 or kind!=0x4e4f534a or length>16*1024*1024:
            raise ValueError('官方GLB格式无效')
        tree=json.loads(stream.read(length))
    if any(item.get('uri') and not item['uri'].startswith('data:')
           for item in [*tree.get('buffers',[]),*tree.get('images',[])]):
        raise ValueError('PBR来源含外部资源，拒绝加载')
    return tree


def write_processed_glb(root,run,version,mesh,file,session,config=None):
    from ..geometry.core import MeshStore
    from ..geometry.appearance import export_base_color_glb
    from ..inspection.service import blender_call
    root=Path(root).resolve();store=MeshStore(root);chain=[];current=store.get(run,version)
    while True:
        chain.append(current)
        if current.parent is None:break
        current=store.get(run,current.parent)
    source_data=current.parameters.get('appearance_source')
    appearance={'policy_version':'official-pbr-v1','status':'vertex_base_color',
        'mesh_version':version,'approximation':True,'pbr_available':False}
    if source_data:
        source=AppearanceSource.model_validate(source_data)
        original=(root/source.relative_path).resolve()
        if not original.is_relative_to(root/f'runs/{UUID(str(run))}/tools'):
            raise ToolFailure('STATE_CONFLICT','PBR来源不属于本任务')
        appearance.update(source=source.model_dump(mode='json'),source_version=current.mesh_version)
        try:
            if not original.is_file():raise OSError('官方PBR来源文件缺失')
            if digest(original)!=source.sha256:raise ToolFailure('STATE_CONFLICT','PBR来源摘要已改变')
            document=_pbr_document(original)
            textured=any(any(k in material.get('pbrMetallicRoughness',{}) for k in
                ['baseColorTexture','metallicRoughnessTexture']) for material in document.get('materials',[]))
            if textured:
                if any(m.get('alphaMode','OPAQUE')!='OPAQUE' for m in document.get('materials',[])):
                    raise ValueError('当前重烘焙仅支持官方默认OPAQUE材质')
                matrix=np.eye(4)
                for record in reversed(chain[:-1]):
                    if record.operation=='orient_scale_place':matrix=np.asarray(record.parameters['matrix'],dtype=float)@matrix
                    elif record.operation not in {'basic_clean','fill_small_holes','remove_components','simplify'}:
                        raise ValueError('PBR来源到当前版本存在未知变换')
                if matrix.shape!=(4,4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3],[0,0,0,1]):
                    raise ValueError('PBR坐标变换无效')
                result=blender_call(config,'pbr_export',mesh,session.directory,{'unit':'mm','source_glb':str(original),
                    'source_frame':source.frame,'source_to_mm':matrix.tolist(),'texture_size':source.texture_size})
                if result.get('pbr_file')!='pbr-model.glb' or result.get('coverage',0)<.99:
                    raise ValueError('PBR纹理投射覆盖不足99%')
                exported=session.directory/'pbr-model.glb';proof=_pbr_document(exported)
                primitives=[primitive for item in proof.get('meshes',[]) for primitive in item.get('primitives',[])]
                for primitive in primitives:
                    material=proof.get('materials',[])[primitive.get('material',-1)]
                    pbr=material.get('pbrMetallicRoughness',{})
                    if ('baseColorTexture' not in pbr or 'metallicRoughnessTexture' not in pbr
                        or 'normalTexture' not in material or 'TEXCOORD_0' not in primitive['attributes']):
                        raise ValueError('GLB未完整导出PBR纹理/UV，不能认定纹理转移成功')
                if not primitives:raise ValueError('PBR导出没有网格')
                import shutil
                shutil.copyfile(exported,file)
                appearance.update(status='pbr_rebaked',pbr_available=True,coverage=result['coverage'],
                    channels=result['channels'],texture_size=result['texture_size'],
                    method='blender_cpu_selected_to_active',original_materials_reused=False)
                return appearance
            appearance['reason']='所选后端原始GLB没有PBR纹理，保留其真实顶点底色'
        except (ToolFailure,OSError,ValueError,KeyError,IndexError) as exc:
            if isinstance(exc,ToolFailure) and exc.code=='STATE_CONFLICT':raise
            appearance.update(status='fallback_vertex_color',warning='PBR纹理转移未完成，当前GLB使用顶点底色：'+str(exc)[:180])
        finally:
            for name,kind in [('blender-result.json','inspection_report'),('blender.log','log')]:
                if (session.directory/name).is_file():session.add('pbr_'+name.replace('.','_'),session.directory/name,kind)
    else:appearance['reason']='此网格版本未记录官方PBR来源，保留真实顶点底色'
    file.write_bytes(export_base_color_glb(_gltf_mesh(mesh)))
    return appearance


def _gltf_mesh(mesh):
    result=mesh.copy()
    result.vertices=(result.vertices@np.array([[1,0,0],[0,0,1],[0,-1,0]]).T)*.001
    return result
