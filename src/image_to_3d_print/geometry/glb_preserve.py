"""检查几何与材质顶点分离；保留原UV/材质/嵌入图像，不重烘焙。"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import numpy as np
import trimesh
from scipy.spatial import cKDTree

POLICY='glb-preserve-v1'
_DT={5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}
_WIDTH={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}


def _fail(message):
    from ..tools import ToolFailure
    raise ToolFailure('INVALID_ARGUMENT',message)


class GLBDocument:
    def __init__(self,path):
        raw=Path(path).read_bytes()
        if len(raw)<28:_fail('GLB不完整')
        magic,version,total,length,kind=struct.unpack_from('<4sIIII',raw)
        if magic!=b'glTF' or version!=2 or total!=len(raw) or kind!=0x4e4f534a:_fail('GLB头无效')
        self.tree=json.loads(raw[20:20+length]);offset=20+length
        size,kind=struct.unpack_from('<II',raw,offset)
        if kind!=0x004e4942 or offset+8+size!=len(raw):_fail('GLB二进制块无效')
        self.binary=bytearray(raw[offset+8:])
        if len(self.tree.get('buffers',[]))!=1 or self.tree['buffers'][0].get('uri'):_fail('检查GLB必须自包含')
        for image in self.tree.get('images',[]):
            if image.get('uri') and not image['uri'].startswith('data:'):_fail('拒绝GLB外部贴图引用')
        nodes=self.tree.get('nodes',[])
        if (len(self.tree.get('meshes',[]))!=1 or sum('mesh' in n for n in nodes)!=1
                or self.tree.get('skins') or self.tree.get('animations')):
            _fail('当前检查保材质入口仅支持单对象静态GLB，不静默合并多对象')
        for node in nodes:
            if ('skin' in node or 'weights' in node
                or not np.allclose(node.get('matrix',np.eye(4).T.reshape(-1)),np.eye(4).T.reshape(-1))
                or not np.allclose(node.get('translation',[0,0,0]),[0,0,0])
                or not np.allclose(node.get('scale',[1,1,1]),[1,1,1])
                or not np.allclose(node.get('rotation',[0,0,0,1]),[0,0,0,1])):
                _fail('带节点变换/骨骼的GLB需先明确展开规则')
        self.primitives=self.tree['meshes'][0]['primitives']
        for p in self.primitives:
            if p.get('mode',4)!=4 or p.get('targets') or p.get('extensions'):_fail('不支持压缩/形变或非三角GLB')
        self.positions=np.vstack([self.accessor(p['attributes']['POSITION']) for p in self.primitives])
        if not len(self.positions) or not np.isfinite(self.positions).all():_fail('GLB坐标无效')
        self.has_uv=any('TEXCOORD_0' in p['attributes'] for p in self.primitives)
        self.logical_matrix=np.asarray(self.tree.get('extras',{}).get('i3d',{}).get('logical_from_gltf',np.eye(4)),dtype=float)
        if self.logical_matrix.shape!=(4,4) or not np.isfinite(self.logical_matrix).all():_fail('GLB逻辑坐标变换无效')

    def accessor(self,index):
        a=self.tree['accessors'][index]
        if a.get('sparse'):_fail('不支持稀疏访问器')
        view=self.tree['bufferViews'][a['bufferView']]
        if view.get('buffer',0)!=0:_fail('GLB访问器引用非嵌入缓冲')
        width=_WIDTH[a['type']];dtype=np.dtype(_DT[a['componentType']])
        start=view.get('byteOffset',0)+a.get('byteOffset',0);stride=view.get('byteStride',dtype.itemsize*width)
        return np.ndarray((a['count'],width),dtype=dtype,buffer=self.binary,offset=start,strides=(stride,dtype.itemsize)).copy()

    def faces(self,primitive):
        if 'indices' in primitive:faces=self.accessor(primitive['indices']).reshape(-1,3).astype(np.int64)
        else:faces=np.arange(len(self.accessor(primitive['attributes']['POSITION']))).reshape(-1,3)
        count=self.tree['accessors'][primitive['attributes']['POSITION']]['count']
        if not len(faces) or faces.min()<0 or faces.max()>=count:_fail('GLB面索引无效')
        return faces

    def material_signature(self):
        images=[]
        for item in self.tree.get('images',[]):
            if 'bufferView' in item:
                view=self.tree['bufferViews'][item['bufferView']];start=view.get('byteOffset',0)
                data=self.binary[start:start+view['byteLength']]
            else:data=base64.b64decode(item['uri'].split(',',1)[1])
            images.append(hashlib.sha256(data).hexdigest())
        return {'materials':copy.deepcopy(self.tree.get('materials',[])),'textures':copy.deepcopy(self.tree.get('textures',[])),
            'samplers':copy.deepcopy(self.tree.get('samplers',[])),'images_sha256':images}

    def append(self,array,kind,component=5126,normalized=None):
        array=np.asarray(array,dtype=np.dtype(_DT[component]));self.binary.extend(b'\0'*(-len(self.binary)%4))
        view={'buffer':0,'byteOffset':len(self.binary),'byteLength':array.nbytes}
        self.binary.extend(array.tobytes());vi=len(self.tree['bufferViews']);self.tree['bufferViews'].append(view)
        a={'bufferView':vi,'componentType':component,'count':len(array),'type':kind}
        if normalized is not None:a['normalized']=normalized
        if kind=='VEC3':a.update(min=array.min(axis=0).tolist(),max=array.max(axis=0).tolist())
        ai=len(self.tree['accessors']);self.tree['accessors'].append(a);return ai

    def save(self,path):
        self.tree['buffers'][0]['byteLength']=len(self.binary)
        data=json.dumps(self.tree,ensure_ascii=False,separators=(',',':')).encode('utf-8');data+=b' '*(-len(data)%4)
        binary=bytes(self.binary);binary+=b'\0'*(-len(binary)%4)
        Path(path).write_bytes(struct.pack('<4sII',b'glTF',2,28+len(data)+len(binary))
            +struct.pack('<II',len(data),0x4e4f534a)+data+struct.pack('<II',len(binary),0x004e4942)+binary)


def display_matrix(unit):
    matrix=trimesh.transformations.rotation_matrix(-np.pi/2,[1,0,0])
    matrix[:3,:3]*=.001 if unit=='mm' else 1.
    return matrix


def prepare_inspection_glb(source,output,frame):
    """首次GLB字节属性保持，只声明检查逻辑坐标；不经PLY中转。"""
    if frame not in {'y_up','z_up'}:_fail('未知生成GLB朝向')
    doc=GLBDocument(source)
    matrix=trimesh.transformations.rotation_matrix(np.pi/2,[1,0,0]) if frame=='y_up' else np.eye(4)
    doc.tree.setdefault('extras',{})['i3d']={'policy':POLICY,'logical_from_gltf':matrix.tolist(),'unit':'unitless','frame':'z_up'}
    doc.save(output)
    return {'face_count':sum(len(doc.faces(p)) for p in doc.primitives),'vertex_count':len(doc.positions)}


def write_plain_glb(mesh,output,unit):
    from .appearance import export_base_color_glb
    display=mesh.copy();matrix=display_matrix(unit);display.apply_transform(matrix)
    Path(output).write_bytes(export_base_color_glb(display));doc=GLBDocument(output)
    doc.tree.setdefault('extras',{})['i3d']={'policy':POLICY,'logical_from_gltf':np.linalg.inv(matrix).tolist(),'unit':unit,'frame':'z_up','appearance':'vertex_color_or_plain'}
    doc.save(output)


def _keys(faces):
    rows=np.ascontiguousarray(np.sort(faces,axis=1),dtype='<i8')
    return rows.view(np.dtype([('a','<i8'),('b','<i8'),('c','<i8')])).reshape(-1)


def preserve_glb(source,mesh,output,*,source_to_logical=None,logical_to_output=None,unit='unitless',allow_new_faces=False):
    """已有三角面的每角UV和材质保持；新增补片显式独立，不推测纹理。"""
    doc=GLBDocument(source);before=doc.material_signature()
    transform=doc.logical_matrix if source_to_logical is None else np.asarray(source_to_logical,dtype=float)
    out_matrix=np.eye(4) if logical_to_output is None else np.asarray(logical_to_output,dtype=float)
    points=trimesh.transform_points(doc.positions,transform)
    unique,inverse=np.unique(points,axis=0,return_inverse=True)
    distance,mapped=cKDTree(unique).query(np.asarray(mesh.vertices))
    tolerance=max(float(np.ptp(unique,axis=0).max())*2e-6,1e-8)
    if distance.max()>tolerance:_fail('几何点已改变，无法精确保留原UV对应；拒绝静默丢弃PBR')
    source_faces=[];original_faces=[];offsets=[];offset=0
    for p in doc.primitives:
        faces=doc.faces(p);original_faces.append(faces);source_faces.append(inverse[faces+offset]);offsets.append(offset)
        offset+=doc.tree['accessors'][p['attributes']['POSITION']]['count']
    face_ids=np.vstack(source_faces);source_keys=_keys(face_ids);unique_keys,first=np.unique(source_keys,return_index=True)
    target_ids=mapped[np.asarray(mesh.faces)];target_keys=_keys(target_ids)
    found=np.searchsorted(unique_keys,target_keys);safe=np.minimum(found,len(unique_keys)-1)
    matched=(found<len(unique_keys))&(unique_keys[safe]==target_keys)
    if not matched.all() and not allow_new_faces:_fail('副本含原件没有的三角面，不能冒充原材质已完整恢复')
    chosen=np.full(len(mesh.faces),-1,dtype=np.int64);chosen[matched]=first[safe[matched]]
    point_to_target=np.zeros(len(unique),dtype=np.int64);point_to_target[mapped]=np.arange(len(mapped))
    transformed=trimesh.transform_points(np.asarray(mesh.vertices),out_matrix)
    out_primitives=[];face_start=0;retained=0
    normal_matrix=np.linalg.inv((out_matrix@transform)[:3,:3]).T
    for i,p in enumerate(doc.primitives):
        faces=original_faces[i];count=len(faces);rows=np.flatnonzero((chosen>=face_start)&(chosen<face_start+count))
        if not len(rows):face_start+=count;continue
        selection=chosen[rows]-face_start;selected=faces[selection];ids=source_faces[i][selection]
        # 顶点顺序按已检查面的绕向，UV仍跟随其原始角点。
        permutation=np.argmax(ids[:,None,:]==target_ids[rows,:,None],axis=2)
        selected=np.take_along_axis(selected,permutation,axis=1)
        used,compact=np.unique(selected,return_inverse=True);global_ids=inverse[used+offsets[i]]
        attributes={}
        for semantic,index in p['attributes'].items():
            a=doc.tree['accessors'][index];values=doc.accessor(index)[used]
            if semantic=='POSITION':values=transformed[point_to_target[global_ids]]
            elif semantic=='NORMAL':
                values=values@normal_matrix.T
                lengths=np.linalg.norm(values,axis=1);valid=np.isfinite(values).all(axis=1)&(lengths>1e-12)
                if not valid.all():values[~valid]=[0,1,0];lengths=np.linalg.norm(values,axis=1)
                values=values/lengths[:,None]
            elif semantic=='TANGENT':
                values=values.copy();values[:,:3]=values[:,:3]@(out_matrix@transform)[:3,:3].T
                values[:,:3]/=np.maximum(np.linalg.norm(values[:,:3],axis=1)[:,None],1e-12)
            attributes[semantic]=doc.append(values,a['type'],a['componentType'],a.get('normalized'))
        if 'NORMAL' not in attributes:
            from .appearance import smooth_vertex_normals
            normals=smooth_vertex_normals(mesh)[point_to_target[global_ids]]@np.linalg.inv(out_matrix[:3,:3])
            normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-12)
            attributes['NORMAL']=doc.append(normals,'VEC3')
        new=copy.deepcopy(p);new['attributes']=attributes;new['indices']=doc.append(compact.reshape(-1,1),'SCALAR',5125)
        out_primitives.append(new);retained+=len(rows);face_start+=count
    patches=np.asarray(mesh.faces)[~matched]
    if len(patches):
        from .appearance import smooth_vertex_normals
        used,indices=np.unique(patches,return_inverse=True);normals=smooth_vertex_normals(mesh)[used]@np.linalg.inv(out_matrix[:3,:3])
        normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-12)
        material=len(doc.tree.setdefault('materials',[]));doc.tree['materials'].append({'name':'untextured_inspection_patch','doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[.65,.65,.65,1.],'metallicFactor':0.,'roughnessFactor':.85}})
        out_primitives.append({'attributes':{'POSITION':doc.append(transformed[used],'VEC3'),'NORMAL':doc.append(normals,'VEC3')},
            'indices':doc.append(indices.reshape(-1,1),'SCALAR',5125),'material':material,'extras':{'appearance':'untextured_patch'}})
    doc.tree['meshes'][0]['primitives']=out_primitives
    doc.tree['meshes'][0].pop('weights',None)
    untextured=sum(len(doc.faces(p)) for p in out_primitives if p.get('extras',{}).get('appearance')=='untextured_patch')
    facts={'policy':POLICY,'retained_faces':retained,'new_patch_faces':len(patches),'untextured_patch_faces':untextured,'source_images_sha256':before['images_sha256'],
        'uv_preserved':True,'original_materials_preserved':True,'texture_bytes_preserved':True,'rebaked':False,
        'appearance':('original_pbr_with_untextured_patches' if untextured else 'original_pbr') if before['images_sha256'] else 'original_vertex_color'}
    doc.tree.setdefault('extras',{})['i3d']={**facts,'logical_from_gltf':np.linalg.inv(out_matrix).tolist(),'unit':unit,'frame':'z_up'}
    doc.save(output)
    return facts
