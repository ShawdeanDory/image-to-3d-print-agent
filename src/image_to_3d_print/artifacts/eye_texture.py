"""可回退的眼部底色投射试用；不生成新几何、不烘焙全身PBR。

没有人脸模型：肤色连通域/对称暗区仅作候选，配准及遮挡不可靠即拒绝。
直接追加GLB嵌入图像，原BIN、几何访问器、UV和其他材质通道保持。
"""
import copy
import io
import json
import math
import struct
import time
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import Field, model_validator
from scipy import ndimage

from ..schemas.common import ContractModel, Id
from ..tools import ToolFailure, ToolSession, digest


class EyeTexturePolicy(ContractModel):
    version: Literal['eye-local-v1','eye-local-v2'] = 'eye-local-v1'
    timeout_s: float = Field(default=90, gt=0, le=180)
    min_silhouette_iou: float = Field(default=.70, ge=.70, le=1)
    min_view_margin: float = Field(default=.025, ge=.025, le=1)
    max_changed_fraction: float = Field(default=.025, gt=0, le=.45)

    @model_validator(mode='after')
    def legacy_limits(self):
        if self.version=='eye-local-v1' and (self.timeout_s>90 or self.max_changed_fraction>.025):
            raise ValueError('v1仍保持90秒和2.5%眼部纹素预算')
        return self


class EyeTextureResult(ContractModel):
    policy_version: Literal['eye-local-v1','eye-local-v2'] = 'eye-local-v1'
    status: Literal['applied', 'skipped', 'failed']
    reason: str
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    enhanced_sha256: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')
    original_artifact_id: Id
    enhanced_artifact_id: Id | None = None
    mesh_version: Id
    geometry_unchanged: Literal[True] = True
    uv_unchanged: Literal[True] = True
    other_pbr_channels_unchanged: Literal[True] = True
    details: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def applied_has_copy(self):
        if (self.status=='applied')!=(self.enhanced_artifact_id is not None and self.enhanced_sha256 is not None):
            raise ValueError('仅实际生成独立增强件时才能记录applied')
        return self


class Declined(ValueError):
    pass


def _bbox(mask):
    y, x = np.nonzero(mask)
    if not len(x): raise Declined('没有可靠前景或脸部候选')
    return np.array([x.min(), y.min(), x.max()+1, y.max()+1], dtype=float)


def eye_pair(rgb, foreground, *, require_white=True):
    """正面双眼启发式；不是通用/已训练的人脸识别器。返回分析图像坐标。"""
    h, w = foreground.shape; subject = _bbox(foreground)
    r, g, b = rgb.astype(float).transpose(2, 0, 1)
    y = .299*r+.587*g+.114*b
    cb = 128-.168736*r-.331264*g+.5*b
    cr = 128+.5*r-.418688*g-.081312*b
    skin = foreground & (y>105) & (cb>76) & (cb<(136 if require_white else 140)) & (cr>(130 if require_white else 124)) & (cr<180)
    skin[int(subject[1]+.44*(subject[3]-subject[1])):] = False
    skin = ndimage.binary_closing(skin, iterations=max(1, h//550))
    labels, _ = ndimage.label(skin)
    faces=[]
    for index, sl in enumerate(ndimage.find_objects(labels), 1):
        if sl is None: continue
        sy, sx = sl; fw=sx.stop-sx.start; fh=sy.stop-sy.start
        area=int(np.count_nonzero(labels[sl]==index))
        if (fw<20 or fh<20 or not .48<fw/fh<2.0 or area<120
                or abs((sx.start+sx.stop)/2-(subject[0]+subject[2])/2)>.22*(subject[2]-subject[0])): continue
        face=ndimage.binary_fill_holes(labels==index)
        # 暗眼线必须处于脸内部；白眼及虹膜可以形成内部孔。
        envelope=ndimage.binary_dilation(face, iterations=max(2, int(fw*.035)))
        dark=(y<105)&envelope
        dark[:sy.start+int(.12*fh)]=False;dark[sy.start+int(.68*fh):]=False
        dark=ndimage.binary_closing(dark, iterations=1)
        dl, _=ndimage.label(dark);candidates=[]
        for k, ds in enumerate(ndimage.find_objects(dl), 1):
            if ds is None:continue
            dy, dx=ds;ew=dx.stop-dx.start;eh=dy.stop-dy.start
            if .10*fw<ew<.46*fw and .045*fh<eh<.43*fh and .65<ew/eh<5:
                candidates.append(np.array([dx.start,dy.start,dx.stop,dy.stop],float))
        for a in candidates:
            for c in candidates:
                if c[0]<=a[0]:continue
                ca=(a[:2]+a[2:])/2;cc=(c[:2]+c[2:])/2
                widths=[a[2]-a[0],c[2]-c[0]];heights=[a[3]-a[1],c[3]-c[1]]
                distance=cc[0]-ca[0]
                if not (.25*fw<distance<.78*fw and abs(cc[1]-ca[1])<.13*fh
                        and min(widths)/max(widths)>.55 and min(heights)/max(heights)>.35):continue
                if abs((ca[0]+cc[0])/2-(sx.start+sx.stop)/2)>.15*fw:continue
                boxes=[];white=[]
                for box in (a,c):
                    bw,bh=box[2:]-box[:2]
                    expanded=box+np.array([-.10*bw,-.12*bh,.10*bw,.12*bh])
                    expanded[[0,2]]=np.clip(expanded[[0,2]],0,w-1)
                    expanded[[1,3]]=np.clip(expanded[[1,3]],0,h-1)
                    x0,y0,x1,y1=expanded.astype(int);patch=rgb[y0:y1,x0:x1].astype(float)
                    white.append(float(np.mean((patch.min(2)>165)&(np.ptp(patch,axis=2)<60))))
                    boxes.append(expanded)
                if require_white and min(white)<.035:continue
                score=min(widths)/max(widths)-abs(cc[1]-ca[1])/fh+min(white)
                faces.append((score, boxes, [sx.start,sy.start,sx.stop,sy.stop]))
    if not faces:raise Declined('未找到可靠的正面双眼；小眼、侧脸或遮挡保持原件')
    faces.sort(key=lambda item:item[0],reverse=True)
    best=faces[0]
    # 不从不同位置的多组眼睛中擅自挑一个人。
    if any(np.linalg.norm(np.array(f[2][:2])-best[2][:2])>20 and f[0]>best[0]-.12 for f in faces[1:]):
        raise Declined('存在多个脸部候选，停止自动眼部投射')
    return best[1], best[2]


class EmbeddedGLB:
    def __init__(self, file):
        raw=file.read_bytes()
        if len(raw)<28:raise Declined('GLB不完整')
        magic,version,total,length,kind=struct.unpack_from('<4sIIII',raw)
        if magic!=b'glTF' or version!=2 or total!=len(raw) or kind!=0x4e4f534a or length>16*1024*1024:
            raise Declined('GLB头或长度无效')
        self.doc=json.loads(raw[20:20+length]);offset=20+length
        size,kind=struct.unpack_from('<II',raw,offset)
        if kind!=0x004e4942 or offset+8+size!=len(raw):raise Declined('只支持单个内嵌BIN块')
        self.bin=raw[offset+8:];doc=self.doc
        if len(doc.get('buffers',[]))!=1 or any('uri' in i for i in doc.get('buffers',[])+doc.get('images',[])):
            raise Declined('不接受外部资源或数据URI')
        if doc.get('skins') or doc.get('animations') or doc.get('extensionsRequired'):
            raise Declined('暂不支持骨骼、动画或必需扩展')
        if len(doc.get('meshes',[]))!=1 or len(doc['meshes'][0]['primitives'])!=1:
            raise Declined('试用版只处理单个纹理三角网格')
        primitive=doc['meshes'][0]['primitives'][0]
        if primitive.get('mode',4)!=4 or primitive.get('targets') or primitive.get('extensions'):
            raise Declined('不支持的三角形/形态或压缩表示')
        self.positions=self.accessor(primitive['attributes']['POSITION']).astype(float)
        self.uv=self.accessor(primitive['attributes']['TEXCOORD_0']).astype(float)
        self.faces=self.accessor(primitive['indices']).reshape(-1,3).astype(np.int64)
        if (not np.isfinite(self.positions).all() or not np.isfinite(self.uv).all()
                or len(self.positions)>2000000 or len(self.faces)>1100000 or self.faces.min()<0
                or self.faces.max()>=len(self.positions) or np.any(self.uv<0) or np.any(self.uv>1)):
            raise Declined('网格/UV越界或超过试用预算')
        self.material=primitive['material'];pbr=doc['materials'][self.material]['pbrMetallicRoughness']
        if pbr.get('baseColorFactor',[1,1,1,1])!=[1,1,1,1]:raise Declined('非单位底色因子暂不投射，避免颜色偏移')
        info=pbr['baseColorTexture']
        if info.get('texCoord',0)!=0 or info.get('extensions'):raise Declined('暂不支持变换UV或多组UV')
        self.texture_index=info['index'];texture=doc['textures'][self.texture_index]
        self.image_index=texture['source'];record=doc['images'][self.image_index]
        self.image=Image.open(io.BytesIO(self.view(record['bufferView']))).convert('RGBA')
        if max(self.image.size)>4096:raise Declined('底色贴图超过4096')
        # 只接受单实例，应用节点刚性/缩放变换供配准；原文件节点不变。
        instances=[];scene=doc.get('scenes',[{}])[doc.get('scene',0)]
        def walk(index,parent,ancestors):
            if index in ancestors:raise Declined('节点存在循环')
            node=doc['nodes'][index];matrix=np.eye(4)
            if 'rotation' in node:
                x,y,z,w=node['rotation'];matrix[:3,:3]=np.array([
                    [1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                    [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                    [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
            matrix[:3,:3]=matrix[:3,:3]@np.diag(node.get('scale',[1,1,1]));matrix[:3,3]=node.get('translation',[0,0,0])
            if 'matrix' in node:matrix=np.array(node['matrix'],float).reshape(4,4).T
            matrix=parent@matrix
            if 'mesh' in node:
                if node['mesh']!=0:raise Declined('节点网格不匹配')
                instances.append(matrix)
            for child in node.get('children',[]):walk(child,matrix,ancestors|{index})
        for index in scene.get('nodes',[]):walk(index,np.eye(4),set())
        if len(instances)!=1:raise Declined('需要唯一可见网格实例')
        matrix=instances[0];self.vertices=self.positions@matrix[:3,:3].T+matrix[:3,3]

    def view(self,index):
        v=self.doc['bufferViews'][index];start=v.get('byteOffset',0);end=start+v['byteLength']
        if v.get('buffer',0)!=0 or end>len(self.bin):raise Declined('BIN引用越界')
        return self.bin[start:end]

    def accessor(self,index):
        a=self.doc['accessors'][index]
        if a.get('sparse') or a.get('normalized'):raise Declined('暂不支持稀疏或归一化访问器')
        dtype={5121:'u1',5123:'<u2',5125:'<u4',5126:'<f4'}[a['componentType']]
        width={'SCALAR':1,'VEC2':2,'VEC3':3}[a['type']];item=np.dtype(dtype).itemsize
        view=self.doc['bufferViews'][a['bufferView']];data=self.view(a['bufferView'])
        stride=view.get('byteStride',width*item);offset=a.get('byteOffset',0)
        if stride<width*item or a['count']<=0 or offset+(a['count']-1)*stride+width*item>len(data):raise Declined('访问器越界')
        return np.ndarray((a['count'],width),dtype=dtype,buffer=data,offset=offset,strides=(stride,item)).copy()

    def save_patch(self,image,output):
        doc=copy.deepcopy(self.doc);buf=io.BytesIO();image.save(buf,format='PNG')
        data=buf.getvalue();binary=self.bin+b'\0'*((-len(self.bin))%4)
        vi=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':len(binary),'byteLength':len(data)})
        binary+=data;binary+=b'\0'*((-len(binary))%4)
        ii=len(doc['images']);doc['images'].append({'bufferView':vi,'mimeType':'image/png'})
        texture=copy.deepcopy(doc['textures'][self.texture_index]);texture['source']=ii
        ti=len(doc['textures']);doc['textures'].append(texture)
        doc['materials'][self.material]['pbrMetallicRoughness']['baseColorTexture']['index']=ti
        doc['buffers'][0]['byteLength']=len(binary)
        text=json.dumps(doc,separators=(',',':'),ensure_ascii=False).encode();text+=b' '*((-len(text))%4)
        output.write_bytes(struct.pack('<4sII',b'glTF',2,28+len(text)+len(binary))+struct.pack('<II',len(text),0x4e4f534a)+text+struct.pack('<II',len(binary),0x004e4942)+binary)
        # 独立解析并逐字节确认原二进制及非底色定义没有变。
        reread=EmbeddedGLB(output)
        self.assert_patch_only(reread)

    def assert_patch_only(self,reread):
        if reread.bin[:len(self.bin)]!=self.bin:raise Declined('原始几何/UV二进制发生变化')
        allowed=copy.deepcopy(reread.doc)
        allowed['bufferViews']=allowed['bufferViews'][:-1];allowed['images']=allowed['images'][:-1];allowed['textures']=allowed['textures'][:-1]
        allowed['buffers']=copy.deepcopy(self.doc['buffers'])
        allowed['materials'][self.material]['pbrMetallicRoughness']['baseColorTexture']['index']=self.texture_index
        if allowed!=self.doc:raise Declined('底色以外的GLB定义发生变化')


def _pixels(triangle,width,height):
    low=np.maximum(np.floor(triangle.min(0)).astype(int),0);high=np.minimum(np.ceil(triangle.max(0)).astype(int),[width-1,height-1])
    if np.any(high<low):return None
    x,y=np.meshgrid(np.arange(low[0],high[0]+1),np.arange(low[1],high[1]+1))
    a,b,c=triangle;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if abs(den)<1e-10:return None
    u=((b[1]-c[1])*(x+.5-c[0])+(c[0]-b[0])*(y+.5-c[1]))/den
    v=((c[1]-a[1])*(x+.5-c[0])+(a[0]-c[0])*(y+.5-c[1]))/den
    weights=np.stack([u,v,1-u-v],axis=-1);inside=weights.min(2)>=1e-6
    return x[inside],y[inside],weights[inside]


def _prepare_input(original,prepared):
    with Image.open(original) as source:
        source=source.convert('RGBA');source.thumbnail((1800,1800));rgba=np.array(source)
    rgb=rgba[:,:,:3]
    if rgba[:,:,3].min()<128:mask=rgba[:,:,3]>=128
    else:
        border=np.concatenate([rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]]);background=np.median(border,axis=0)
        similar=np.max(np.abs(rgb.astype(float)-background),axis=2)<30
        seed=np.zeros(similar.shape,bool);seed[[0,-1],:]=similar[[0,-1],:];seed[:,[0,-1]]=similar[:,[0,-1]]
        mask=~ndimage.binary_propagation(seed,mask=similar)
    mask=ndimage.binary_fill_holes(mask);box=_bbox(mask)
    eyes,face=eye_pair(rgb,mask)
    with Image.open(prepared) as source:prgb=np.array(source.convert('RGB'))
    pmask=prgb.max(2)>8;pbox=_bbox(pmask)
    if abs((box[2]-box[0])/(box[3]-box[1])-(pbox[2]-pbox[0])/(pbox[3]-pbox[1]))>.10:
        raise Declined('原图与官方前景范围不一致，停止配准')
    return rgb,mask,eyes,face


def project_eyes(glb,rgb,mask,source_eyes,face,policy,checkpoint):
    """先有限视角/点云配准，再对眼部三角形精确深度与UV光栅化。"""
    h,w=mask.shape;box=_bbox(mask);vertices=glb.vertices;faces=glb.faces;uv=glb.uv
    sample=np.arange(0,len(vertices),max(1,math.ceil(len(vertices)/180000)))
    texture=np.array(glb.image);th,tw=texture.shape[:2]
    # glTF的UV原点在图像左上角，纹素中心为(i+.5)/size，不翻转V。
    colors=texture[np.clip((uv[sample,1]*th).astype(int),0,th-1),np.clip((uv[sample,0]*tw).astype(int),0,tw-1),:3]
    # glTF为Y朝上；这里只估计外观投射相机，不登记为质量测量的已批准映射。
    candidates=[]
    for yaw in (-30,-15,0,15,30,150,165,180,195,210):
        for pitch in (-10,0,10):
            checkpoint();a,b=np.deg2rad([yaw,pitch]);cy,sy=np.cos(a),np.sin(a);cx,sx=np.cos(b),np.sin(b)
            rotation=np.array([[cy,0,sy],[sx*sy,cx,-sx*cy],[-cx*sy,sx,cx*cy]])
            points=vertices@rotation.T;lo=points.min(0);hi=points.max(0)
            scale=(box[3]-box[1])/(hi[1]-lo[1]);center=(lo+hi)/2
            projected=np.column_stack(((points[:,0]-center[0])*scale+(box[0]+box[2])/2,
                -(points[:,1]-center[1])*scale+(box[1]+box[3])/2,points[:,2]))
            small=projected[sample];xi=np.rint(small[:,0]).astype(int);yi=np.rint(small[:,1]).astype(int)
            good=(xi>=0)&(xi<w)&(yi>=0)&(yi<h);order=np.argsort(small[good,2],kind='stable')
            render=np.zeros_like(rgb);occupied=np.zeros((h,w),bool)
            xx=xi[good][order];yy=yi[good][order]
            _,last=np.unique((yy*w+xx)[::-1],return_index=True);last=len(xx)-1-last
            xx=xx[last];yy=yy[last];render[yy,xx]=colors[good][order][last];occupied[yy,xx]=True
            distance,nearest=ndimage.distance_transform_edt(~occupied,return_indices=True)
            rendered=render[nearest[0],nearest[1]];render_mask=distance<=max(2,h/350)
            score_mask=ndimage.binary_fill_holes(render_mask)
            intersection=np.count_nonzero(score_mask&mask);union=np.count_nonzero(score_mask|mask);iou=intersection/union
            x0,y0,x1,y1=np.array(face,int);region=mask[y0:y1,x0:x1]&render_mask[y0:y1,x0:x1]
            if not region.any():continue
            color_error=np.mean(np.abs(rendered[y0:y1,x0:x1].astype(float)-rgb[y0:y1,x0:x1])[region])/255
            candidates.append((iou-.75*color_error,iou,yaw,pitch,rotation,scale,center,rendered,render_mask))
    candidates.sort(key=lambda x:x[0],reverse=True)
    if not candidates:raise Declined('没有可配准的视图')
    best=candidates[0];opposite=next((c for c in candidates if abs((c[2]-best[2]+180)%360-180)>75),None)
    margin=best[0]-opposite[0] if opposite else 0
    if best[1]<policy.min_silhouette_iou or margin<policy.min_view_margin:raise Declined('正背面或轮廓配准不可靠，保持原件')
    target_eyes,_=eye_pair(best[7],best[8],require_white=False);source_centers=np.array([(e[:2]+e[2:])/2 for e in source_eyes]);target_centers=np.array([(e[:2]+e[2:])/2 for e in target_eyes])
    if np.max(np.linalg.norm(source_centers-target_centers,axis=1))>.25*(face[2]-face[0]):raise Declined('生成眼睛与原图位置偏差过大，贴图不能修正几何')
    for source,target in zip(source_eyes,target_eyes):
        ratio=(target[2:]-target[:2])/(source[2:]-source[:2])
        if np.any(ratio<.5) or np.any(ratio>2):raise Declined('眼型比例差异过大，保持原件')
    points=vertices@best[4].T;screen=np.column_stack(((points[:,0]-best[6][0])*best[5]+(box[0]+box[2])/2,
        -(points[:,1]-best[6][1])*best[5]+(box[1]+box[3])/2));depth=points[:,2]
    low=np.min(np.array(target_eyes)[:,:2],axis=0)-3;high=np.max(np.array(target_eyes)[:,2:],axis=0)+3
    tri=screen[faces];selected=np.flatnonzero(np.all(tri.max(1)>=low,axis=1)&np.all(tri.min(1)<=high,axis=1))
    origin=np.maximum(np.floor(low).astype(int),0);end=np.minimum(np.ceil(high).astype(int),[w,h]);rw,rh=end-origin
    z=np.full((rh,rw),-np.inf);visible=np.full((rh,rw),-1,np.int64)
    for j,index in enumerate(selected):
        if j%128==0:checkpoint()
        hit=_pixels(tri[index]-origin,rw,rh)
        if hit is None:continue
        x,y,weight=hit;d=weight@depth[faces[index]];front=d>z[y,x];z[y[front],x[front]]=d[front];visible[y[front],x[front]]=index
    ids=np.unique(visible[visible>=0]);candidate=texture.copy();painted=np.zeros((th,tw),bool);owners=np.full((th,tw),-1,np.int32)
    texture_tri=uv[faces]*[tw,th]
    eye_counts=[0,0]
    for j,index in enumerate(ids):
        if j%128==0:checkpoint()
        if np.prod(np.ptp(texture_tri[index],axis=0)+1)>262144:raise Declined('单个UV三角形过大，超出局部投射预算')
        hit=_pixels(texture_tri[index],tw,th)
        if hit is None:continue
        tx,ty,weight=hit;xy=weight@tri[index];d=weight@depth[faces[index]]
        local=np.floor(xy-origin).astype(int);inside=(local[:,0]>=0)&(local[:,0]<rw)&(local[:,1]>=0)&(local[:,1]<rh)
        lx=np.clip(local[:,0],0,rw-1);ly=np.clip(local[:,1],0,rh-1)
        front=inside&np.isfinite(z[ly,lx])&(np.abs(d-z[ly,lx])<max(np.ptp(depth)*.003,1e-7))
        for eye_index,(source,target) in enumerate(zip(source_eyes,target_eyes)):
            relative=(xy-target[:2])/(target[2:]-target[:2]);radius=np.linalg.norm((relative-.5)*2,axis=1)
            chosen=front&(radius<1)
            if not chosen.any():continue
            px,py=tx[chosen],ty[chosen]
            if np.any((owners[py,px]>=0)&(owners[py,px]!=index)):raise Declined('眼部UV互相重叠，不能只改眼睛')
            source_xy=source[:2]+relative[chosen]*(source[2:]-source[:2])
            sampled=np.stack([ndimage.map_coordinates(rgb[:,:,channel],(source_xy[:,::-1]-.5).T,order=1,mode='nearest') for channel in range(3)],axis=1)
            alpha=np.clip((1-radius[chosen])/.15,0,1)[:,None]
            candidate[py,px,:3]=np.rint(texture[py,px,:3]*(1-alpha)+sampled*alpha).astype(np.uint8)
            painted[py,px]=True;owners[py,px]=index
            eye_counts[eye_index]+=len(px)
    changed=np.any(candidate[:,:,:3]!=texture[:,:,:3],axis=2);count=int(changed.sum())
    if min(eye_counts)<16 or count<32 or count/(th*tw)>policy.max_changed_fraction:raise Declined('双眼UV覆盖过少或修改区域过大')
    # 查所有其他三角形是否共享待改纹素；不把背面/衣物共用纹理一起改色。
    summed=np.pad(painted.astype(np.int32).cumsum(0).cumsum(1),((1,0),(1,0)))
    lo=np.clip(np.floor(texture_tri.min(1)).astype(int),0,[tw-1,th-1]);hi=np.clip(np.ceil(texture_tri.max(1)).astype(int)+1,0,[tw,th])
    sums=summed[hi[:,1],hi[:,0]]-summed[lo[:,1],hi[:,0]]-summed[hi[:,1],lo[:,0]]+summed[lo[:,1],lo[:,0]]
    for j,index in enumerate(np.flatnonzero(sums)):
        if j%128==0:checkpoint()
        if np.prod(np.ptp(texture_tri[index],axis=0)+1)>262144:raise Declined('共享UV核验超过局部预算')
        hit=_pixels(texture_tri[index],tw,th)
        if hit is None:continue
        x,y,weight=hit
        if np.any(painted[y,x]&(owners[y,x]!=index)&(weight.min(1)>.015)):
            raise Declined('待改纹素同时属于其他表面，拒绝镜像/重叠UV投射')
    return Image.fromarray(candidate),{'source_eye_boxes': [e.tolist() for e in source_eyes],
        'target_eye_boxes':[e.tolist() for e in target_eyes],'analysis_size':[w,h],
        'yaw_deg':best[2],'pitch_deg':best[3],'silhouette_iou':best[1],'opposite_view_margin':margin,
        'modified_texels':count,'per_eye_texels':eye_counts,'texture_size':[tw,th],'method':'skin_dark_pair_bounded_ortho_uv_projection',
        'camera_scope':'appearance_estimate_not_approved_quality_mapping'}


def _enhance_v2(session,result,file,original,prepared,frame,policy,gpu_config,cancel_event):
    import os
    import subprocess
    import shutil
    from pathlib import Path
    from ..tools import stop_process_group
    if os.name!='posix' or gpu_config is None or gpu_config.backend!='trellis2_candidate' or not gpu_config.python.is_file():
        raise ToolFailure('TOOL_UNAVAILABLE','未配置同实例候选GPU环境，外观修正不静默切换机器')
    directory=session.directory;output=directory/'appearance-enhanced.glb';report=directory/'appearance-result.json'
    policy_file=directory/'appearance-policy.json';policy_file.write_text(policy.model_dump_json(indent=2)+'\n',encoding='utf-8')
    script=Path(__file__).resolve().parents[3]/'scripts/tools/appearance_worker.py'
    if not script.is_file():raise ToolFailure('TOOL_UNAVAILABLE','缺少外观worker')
    args=[str(gpu_config.python),str(script),'--source',str(file),'--original',str(original),'--prepared',str(prepared),
          '--output',str(output),'--report',str(report),'--policy',str(policy_file)]
    watchdog=shutil.which('timeout')
    if watchdog is None:raise ToolFailure('TOOL_UNAVAILABLE','Linux缺少外观worker超时守护')
    args=[watchdog,'--signal=TERM','--kill-after=5s',str(policy.timeout_s)+'s',*args]
    environment={**os.environ,'CUDA_VISIBLE_DEVICES':'0','OMP_NUM_THREADS':'4','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
    environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
    started=time.monotonic();error=None
    with (directory/'process.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,env=environment,start_new_session=True)
        try:
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():error=('STATE_CONFLICT','任务已取消，停止外观worker')
                elif time.monotonic()-started>policy.timeout_s:error=('TOOL_TIMEOUT','外观worker达到技术超时')
                if error:stop_process_group(process);break
                time.sleep(.1)
        except BaseException:
            stop_process_group(process);raise
    if error:raise ToolFailure(*error)
    if process.returncode or not report.is_file():raise ToolFailure('TOOL_UNAVAILABLE','外观worker失败，详细信息见本任务日志')
    data=json.loads(report.read_text(encoding='utf-8'))
    details={**data['details'],'input_sha256':digest(original),'prepared_sha256':digest(prepared),
             'policy':policy.model_dump(mode='json'),'process_exit_code':process.returncode,'process_seconds':time.monotonic()-started}
    if digest(file)!=result.source_sha256:raise ToolFailure('STATE_CONFLICT','执行中原始文件摘要改变')
    for name in ('alignment.json','appearance-result.json','appearance-policy.json'):
        if (directory/name).is_file():session.add(name.replace('.','_'),directory/name,'inspection_report',parents=[result.original_artifact_id])
    # 在父进程再次独立检查，不信任worker的applied标志。
    if data['status']=='applied':
        before,after=EmbeddedGLB(file),EmbeddedGLB(output)
        if after.bin[:len(before.bin)]!=before.bin:raise ToolFailure('STATE_CONFLICT','原始BIN保持检查失败')
        before.assert_patch_only(after)
        artifact=session.add('appearance_glb',output,'repaired_mesh','unitless',parents=[result.original_artifact_id])
        result=EyeTextureResult.model_validate({**result.model_dump(),'status':'applied','reason':data['reason'],
            'enhanced_artifact_id':artifact.artifact_id,'enhanced_sha256':digest(output),'details':details})
        return session.finish({'eye_texture':result.model_dump(mode='json'),'artifact_frames':{artifact.artifact_id:frame}})
    result=EyeTextureResult.model_validate({**result.model_dump(),'status':data['status'],'reason':data['reason'],'details':details})
    if result.status=='failed':return session.fail('TOOL_UNAVAILABLE',result.reason,{'eye_texture':result.model_dump(mode='json')})
    return session.finish({'eye_texture':result.model_dump(mode='json')})


def enhance_eye_texture(root,run,version,original_artifact_id,expected_sha,policy=None,*,gpu_config=None,cancel_event=None):
    from pathlib import Path
    from ..geometry.core import MeshStore
    from ..image.assets import AssetStore
    from .pbr import AppearanceSource
    from ..schemas.validation import resolve_artifact_path
    policy=policy or EyeTexturePolicy();session=ToolSession(root,run,'export',version)
    result=EyeTextureResult(policy_version=policy.version,status='skipped',reason='未执行',source_sha256=expected_sha,
        original_artifact_id=original_artifact_id,mesh_version=version)
    started=time.monotonic()
    def checkpoint():
        if time.monotonic()-started>policy.timeout_s:raise TimeoutError('眼部试用达到90秒技术超时')
    try:
        root=Path(root).resolve();record=MeshStore(root).get(run,version)
        if record.parent is not None:raise ToolFailure('STATE_CONFLICT','眼部投射必须绑定原始根版本')
        source=AppearanceSource.model_validate(record.parameters['appearance_source'])
        file=resolve_artifact_path(root,source.relative_path)
        if not file.is_relative_to(root/f'runs/{session.run_id}/tools') or source.sha256!=expected_sha or digest(file)!=expected_sha:
            raise ToolFailure('STATE_CONFLICT','原始GLB归属或摘要不一致')
        if record.parameters.get('backend')!='trellis2_candidate':raise Declined('仅对TRELLIS.2纹理PBR试用，TripoSR保留原件')
        if source.frame!='y_up':raise Declined('原始GLB坐标不支持此次投射')
        asset=AssetStore(root).get(record.parameters['input_asset_id']);original=resolve_artifact_path(root,asset.relative_path)
        prepared=file.parent/'backend_input.png'
        if not prepared.is_file():raise Declined('缺少同任务官方准备图，不猜测另一张图片')
        if policy.version=='eye-local-v2':
            return _enhance_v2(session,result,file,original,prepared,source.frame,policy,gpu_config,cancel_event)
        rgb,mask,eyes,face=_prepare_input(original,prepared);checkpoint()
        import PIL, scipy
        result=result.model_copy(update={'details':{'input_asset_id':asset.asset_id,
            'input_sha256':digest(original),'prepared_sha256':digest(prepared),'policy':policy.model_dump(mode='json'),
            'numpy_version':np.__version__,'pillow_version':PIL.__version__,'scipy_version':scipy.__version__}})
        glb=EmbeddedGLB(file);checkpoint();image,details=project_eyes(glb,rgb,mask,eyes,face,policy,checkpoint)
        output=session.directory/'eye-enhanced.glb';glb.save_patch(image,output);checkpoint()
        if digest(file)!=expected_sha:raise ToolFailure('STATE_CONFLICT','执行中原始GLB摘要改变')
        artifact=session.add('eye_glb',output,'repaired_mesh','unitless',parents=[original_artifact_id])
        result=EyeTextureResult.model_validate({**result.model_dump(),'status':'applied','reason':'眼部底色局部投射已生成；视觉效果待用户检查',
            'enhanced_artifact_id':artifact.artifact_id,'enhanced_sha256':digest(output),
            'details':{**result.details,**details,'original_bin_prefix_unchanged':True,'non_basecolor_definitions_unchanged':True}})
        return session.finish({'eye_texture':result.model_dump(mode='json'),'artifact_frames':{artifact.artifact_id:source.frame}})
    except Declined as exc:result=result.model_copy(update={'status':'skipped','reason':str(exc)})
    except ToolFailure as exc:return session.fail(exc.code,str(exc),{'eye_texture':result.model_copy(update={'status':'failed','reason':str(exc)}).model_dump(mode='json')})
    except (OSError,ValueError,KeyError,IndexError,TypeError,TimeoutError,MemoryError) as exc:
        result=result.model_copy(update={'status':'failed','reason':type(exc).__name__+'：'+str(exc)[:220]})
        return session.fail('TOOL_TIMEOUT' if isinstance(exc,TimeoutError) else 'TOOL_UNAVAILABLE',result.reason,{'eye_texture':result.model_dump(mode='json')})
    return session.finish({'eye_texture':result.model_dump(mode='json')})
