"""原始GLB来源登记与只读材质检查；处理导出不再重烘焙。"""
import json
import struct
from typing import Literal
import numpy as np
from pydantic import Field
from ..schemas.common import ContractModel,RelativePath
from ..tools import digest


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
    """GLB检查版本直接保留原材质导出；不重烘焙。"""
    from pathlib import Path
    from ..geometry.core import MeshStore
    from ..geometry.glb_preserve import preserve_glb,display_matrix
    source=MeshStore(root).get(run,version);path=Path(root)/source.relative_path
    if path.suffix.lower()=='.glb':
        facts=preserve_glb(path,mesh,file,logical_to_output=display_matrix(source.unit),unit=source.unit)
        warning=(f"{facts['untextured_patch_faces']}个补片三角面没有原始纹理依据；已有UV/PBR及贴图保持，未重烘焙。"
            if facts['untextured_patch_faces'] else None)
        return {'policy_version':'glb-preserve-v1','status':facts['appearance'],'mesh_version':version,
            'approximation':bool(facts['untextured_patch_faces']),'pbr_available':bool(facts['source_images_sha256']),
            'warning':warning,**facts}
    from ..geometry.appearance import export_base_color_glb
    file.write_bytes(export_base_color_glb(_gltf_mesh(mesh)))
    return {'policy_version':'official-pbr-v1','status':'vertex_base_color','mesh_version':version,
        'approximation':True,'pbr_available':False,'reason':'此历史检查网格没有UV/PBR，仅保留顶点底色近似；不重烘焙。'}


def _gltf_mesh(mesh):
    result=mesh.copy()
    result.vertices=(result.vertices@np.array([[1,0,0],[0,0,1],[0,-1,0]]).T)*.001
    return result
