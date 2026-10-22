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
    """历史独立处理导出仅保留顶点色；重烘焙入口已停用。"""
    from ..geometry.appearance import export_base_color_glb
    file.write_bytes(export_base_color_glb(_gltf_mesh(mesh)))
    return {'policy_version':'official-pbr-v1','status':'vertex_base_color','mesh_version':version,
        'approximation':True,'pbr_available':False,'reason':'重烘焙已停用；网页展示和下载使用原始GLB。'}


def _gltf_mesh(mesh):
    result=mesh.copy()
    result.vertices=(result.vertices@np.array([[1,0,0],[0,0,1],[0,-1,0]]).T)*.001
    return result
