"""同实例既有CUDA光栅上的可见面底色修正；只在独立worker加载GPU库。"""
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .eye_texture import EmbeddedGLB, Declined, eye_pair


def silhouette_correspondence(source_mask, rendered_mask):
    """有界、单调的行轮廓对应，避免裙摆/腿部边界发生整段错位。"""
    import cv2
    from scipy.ndimage import gaussian_filter1d
    size=400
    def profiles(mask):
        small=cv2.resize(mask.astype(np.uint8),(size,size),interpolation=cv2.INTER_NEAREST)>0
        widths=small.sum(1).astype(float)
        # 同一行可能包含两腿/头发空隙，以外包络及占比共同限制匹配。
        left=np.argmax(small,1);right=size-np.argmax(small[:,::-1],1)
        span=np.where(widths>0,right-left,0)
        return gaussian_filter1d(np.stack((span/size,widths/size),1),1,axis=0)
    a,b=profiles(rendered_mask),profiles(source_mask)
    cost=np.full((size,size),np.inf);prev=np.zeros((size,size),np.uint8)
    for i in range(size):
        for j in range(max(0,i-20),min(size,i+21)):
            local=float(np.abs(a[i]-b[j]).sum())+.12*abs(i-j)/size
            if i==j==0:cost[i,j]=local;continue
            options=(cost[i-1,j-1] if i and j else np.inf,
                     cost[i-1,j]+.008 if i else np.inf,
                     cost[i,j-1]+.008 if j else np.inf)
            step=int(np.argmin(options));cost[i,j]=local+options[step];prev[i,j]=step
    i=j=size-1;pairs=[]
    while i or j:
        pairs.append((i,j));step=prev[i,j]
        if step==0:i-=1;j-=1
        elif step==1:i-=1
        else:j-=1
    pairs.append((0,0));rows=np.arange(size)
    mapped=np.array([np.mean([y for x,y in pairs if x==r]) for r in rows])
    mapped=gaussian_filter1d(mapped,6)
    h,w=source_mask.shape;sy=np.interp(np.arange(h)*size/h,rows,mapped)*h/size
    def envelope(mask):
        occupied=mask.any(1);left=np.argmax(mask,1).astype(float);right=w-np.argmax(mask[:,::-1],1)
        indices=np.flatnonzero(occupied)
        if len(indices)<h*.6:raise Declined('有效轮廓行不足，拒绝颜色投射')
        return np.interp(np.arange(h),indices,left[indices]),np.interp(np.arange(h),indices,right[indices])
    sl,sr=envelope(source_mask);dl,dr=envelope(rendered_mask)
    sl=np.interp(sy,np.arange(h),sl);sr=np.interp(sy,np.arange(h),sr)
    scale=(sr-sl)/np.maximum(1,dr-dl)
    scale=gaussian_filter1d(scale,max(1,h*.008))
    reliable=(np.abs(sy-np.arange(h))<=h*.05)&(scale>=.75)&(scale<=1.3)
    xx=np.arange(w)[None,:]
    shift=gaussian_filter1d((sl+sr)/2-(dl+dr)*scale/2,max(1,h*.008))
    mx=xx*scale[:,None]+shift[:,None]
    my=np.broadcast_to(sy[:,None],(h,w))
    return mx.astype(np.float32),my.astype(np.float32),reliable


def target_eye_boxes(rgb,source_boxes):
    import cv2
    from scipy.ndimage import binary_fill_holes
    boxes=[]
    for source in source_boxes:
        center=(source[:2]+source[2:])/2;size=source[2:]-source[:2]
        low=np.maximum(np.floor(center-size*[.75,.9]).astype(int),0)
        high=np.minimum(np.ceil(center+size*[.75,2.0]).astype(int),[rgb.shape[1],rgb.shape[0]])
        crop=rgb[low[1]:high[1],low[0]:high[0]]
        gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
        dark=(gray<min(90,float(np.median(gray))*.70)).astype(np.uint8)
        dark=cv2.morphologyEx(dark,cv2.MORPH_CLOSE,np.ones((2,2),np.uint8))
        holes=binary_fill_holes(dark>0)&~(dark>0)
        _,_,hole_stats,_=cv2.connectedComponentsWithStats(holes.astype(np.uint8))
        interiors=[]
        for x,y,w,h,area in hole_stats[1:]:
            if area>20 and .35*size[0]<w<1.5*size[0] and .6*size[1]<h<2.5*size[1]:
                candidate=np.array([x+low[0]-2,y+low[1]-2,x+w+low[0]+2,y+h+low[1]+2],float)
                interiors.append((np.linalg.norm(((candidate[:2]+candidate[2:])/2-center)/size),candidate))
        # 生成失败的灰色眼底可能与刘海黑边相连；找不接触裁切边的封闭中灰内部。
        neutral=(gray>55)&(gray<155)&(np.ptp(crop.astype(float),axis=2)<65)
        _,_,neutral_stats,_=cv2.connectedComponentsWithStats(neutral.astype(np.uint8))
        for x,y,w,h,area in neutral_stats[1:]:
            if (x==0 or y==0 or x+w>=crop.shape[1] or y+h>=crop.shape[0]
                    or not (.35*size[0]<w<1.5*size[0] and .6*size[1]<h<2.5*size[1] and area>30)):continue
            candidate=np.array([x+low[0]-3,y+low[1]-3,x+w+low[0]+3,y+h+low[1]+3],float)
            interiors.append((np.linalg.norm(((candidate[:2]+candidate[2:])/2-center)/size),candidate))
        count,labels,stats,centroids=cv2.connectedComponentsWithStats(dark)
        candidates=[]
        for x,y,w,h,area in stats[1:]:
            if .35*size[0]<w<1.8*size[0] and .3*size[1]<h<2.8*size[1] and area>8:
                box=np.array([x+low[0],y+low[1],x+w+low[0],y+h+low[1]],float)
                displacement=np.linalg.norm(((box[:2]+box[2:])/2-center)/size)
                candidates.append((displacement,box))
        if not (interiors or candidates):return None
        boxes.append(min(interiors or candidates,key=lambda item:item[0])[1])
    centers=np.array([(b[:2]+b[2:])/2 for b in boxes])
    source_centers=(source_boxes[:,:2]+source_boxes[:,2:])/2
    if (centers[1,0]-centers[0,0]<.6*(source_centers[1,0]-source_centers[0,0])
            or boxes[0][2]>=boxes[1][0]
            or abs(centers[0,1]-centers[1,1])>np.mean(source_boxes[:,3]-source_boxes[:,1])):return None
    return np.array(boxes)


def run_projection(source, original, prepared, output, *, diagnose_only=False,policy=None):
    import cv2
    import torch
    import nvdiffrast.torch as dr
    if not torch.cuda.is_available():raise Declined('可见面底色修正需要同实例既有CUDA，不静默切回CPU')
    from .eye_texture import EyeTexturePolicy
    policy=policy or EyeTexturePolicy(version='eye-local-v2',timeout_s=180,max_changed_fraction=.45)
    started=time.monotonic();directory=output.parent;directory.mkdir(exist_ok=True)
    def checkpoint():
        if time.monotonic()-started>policy.timeout_s-5:raise TimeoutError('局部外观处理达到技术时限')
    glb=EmbeddedGLB(source)
    with Image.open(original) as image:raw=np.array(image.convert('RGB'))
    with Image.open(prepared) as image:target=np.array(image.convert('RGB'))
    height,width=target.shape[:2]
    if height!=width or width>2048 or raw.shape[0]*raw.shape[1]>25000000:raise Declined('输入图像超出有界配准尺寸')
    mask=target.max(2)>8
    # 在原图和官方准备图之间寻找同一图像特征，避免用带阴影的外轮廓猜裁切。
    ratio=min(1,1600/max(raw.shape[:2]));small=cv2.resize(raw,None,fx=ratio,fy=ratio)
    detector=cv2.SIFT_create(nfeatures=4000)
    ka,da=detector.detectAndCompute(cv2.cvtColor(small,cv2.COLOR_RGB2GRAY),None)
    kb,db=detector.detectAndCompute(cv2.cvtColor(target,cv2.COLOR_RGB2GRAY),mask.astype(np.uint8)*255)
    if da is None or db is None:raise Declined('原图与官方准备图缺少对应点')
    pairs=[a for a,b in cv2.BFMatcher().knnMatch(da,db,k=2) if a.distance<.72*b.distance]
    if len(pairs)<12:raise Declined('原图与官方准备图对应点不足12个')
    a=np.float32([ka[m.queryIdx].pt for m in pairs])/ratio;b=np.float32([kb[m.trainIdx].pt for m in pairs])
    original_to_prepared,inliers=cv2.estimateAffinePartial2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=1.5)
    if original_to_prepared is None or int(inliers.sum())<12:raise Declined('原始输入裁切映射不可靠')
    residual=np.linalg.norm(a@original_to_prepared[:,:2].T+original_to_prepared[:,2]-b,axis=1)
    if np.median(residual[inliers[:,0]>0])>.8:raise Declined('原始输入映射残差过大')
    target_hd=cv2.warpAffine(raw,original_to_prepared,(width,height),flags=cv2.INTER_CUBIC)
    target_hd[~mask]=0
    eyes,face=eye_pair(target_hd,mask)
    eye_boxes=np.array(eyes)
    cx=float(np.mean((eye_boxes[:,0]+eye_boxes[:,2])/2));ey=float(np.mean((eye_boxes[:,1]+eye_boxes[:,3])/2))
    eye_span=float((eye_boxes[1,0]+eye_boxes[1,2]-eye_boxes[0,0]-eye_boxes[0,2])/2)
    face_box=np.array([cx-eye_span*1.05,ey-eye_span*.9,cx+eye_span*1.05,ey+eye_span*1.45])
    face_box=np.clip(face_box,[0,0,0,0],[width-1,height-1,width,height])
    dev='cuda';ctx=dr.RasterizeCudaContext()
    v=torch.as_tensor(glb.vertices,dtype=torch.float32,device=dev);f=torch.as_tensor(glb.faces,dtype=torch.int32,device=dev)
    uv=torch.as_tensor(glb.uv,dtype=torch.float32,device=dev)[None]
    texture=np.array(glb.image);tex=torch.tensor(texture[:,:,:3].astype(np.float32)/255,device=dev)[None]
    ys,xs=np.nonzero(mask);box=np.array([xs.min(),ys.min(),xs.max()+1,ys.max()+1],float)
    bbox_center=(box[:2]+box[2:])/2
    def camera(yaw,pitch):
        ya,pi=np.deg2rad([yaw,pitch]);cy,sy=np.cos(ya),np.sin(ya);cp,sp=np.cos(pi),np.sin(pi)
        rotation=np.array([[cy,0,sy],[sp*sy,cp,-sp*cy],[-cp*sy,sp,cp*cy]],np.float32)
        points=v@torch.tensor(rotation.T,device=dev);lo=points.amin(0);hi=points.amax(0)
        scale=float((box[3]-box[1])/(hi[1]-lo[1]));center=(lo+hi)/2
        screen=torch.stack(((points[:,0]-center[0])*scale+bbox_center[0],-(points[:,1]-center[1])*scale+bbox_center[1]),1)
        z=-(points[:,2]-center[2])/(hi[2]-lo[2]).clamp_min(1e-8)*1.8
        clip=torch.stack((screen[:,0]/width*2-1,1-screen[:,1]/height*2,z,torch.ones_like(z)),1)
        return clip,screen,z
    def render(yaw,pitch,size=512,need_maps=False):
        clip,screen,z=camera(yaw,pitch);rast,_=dr.rasterize(ctx,clip[None].contiguous(),f,resolution=[size,size])
        texc,_=dr.interpolate(uv,rast,f)
        rgb=dr.texture(tex,texc,filter_mode='linear',boundary_mode='clamp')[0].flip(0)
        raster=rast[0].flip(0);rgb=rgb*(raster[:,:,3:4]>0)
        return (rgb.clamp(0,1).cpu().numpy()*255).astype(np.uint8),raster,screen,z,clip
    target_low=cv2.resize(target,(512,512));mask_low=cv2.resize(mask.astype(np.uint8),(512,512),interpolation=cv2.INTER_NEAREST)>0
    fx0,fy0,fx1,fy1=(face_box*512/width).astype(int)
    candidates=[]
    def evaluate(yaw,pitch):
        checkpoint();rgb,raster,*_=render(yaw,pitch);rm=(raster[:,:,3]>0).cpu().numpy()
        iou=float(np.count_nonzero(rm&mask_low)/max(1,np.count_nonzero(rm|mask_low)))
        overlap=rm&mask_low
        error=float(np.abs(rgb.astype(float)-target_low)[overlap].mean()/255)
        region=overlap[fy0:fy1,fx0:fx1]
        face_error=float(np.abs(rgb[fy0:fy1,fx0:fx1].astype(float)-target_low[fy0:fy1,fx0:fx1])[region].mean()/255) if region.any() else 1
        found=target_eye_boxes(rgb,eye_boxes*512/width)
        # 双眼结构证据单列，不通过降低朝向门槛放行；背发不能算成脸。
        eye_evidence=1. if found is not None else 0.
        candidates.append({'yaw':float(yaw),'pitch':float(pitch),'iou':iou,'color_error':error,'face_error':face_error,
            'eye_pair_detected':bool(eye_evidence),'score':iou-.55*error-.35*face_error+.12*eye_evidence})
    with torch.no_grad():
        for yaw in (-30,-15,0,15,30,150,165,180,195,210):
            for pitch in (-10,0,10):evaluate(yaw,pitch)
        best=max(candidates,key=lambda c:c['score']);first=best.copy()
        for yaw in (first['yaw']-6,first['yaw'],first['yaw']+6):
            for pitch in (first['pitch']-5,first['pitch'],first['pitch']+5):evaluate(yaw,pitch)
        best=max(candidates,key=lambda c:c['score'])
        opposite=max((c for c in candidates if abs((c['yaw']-best['yaw']+180)%360-180)>90),key=lambda c:c['score'])
        margin=best['score']-opposite['score']
        before,raster,screen,z,clip=render(best['yaw'],best['pitch'],width,True)
        valid=(raster[:,:,3]>0).cpu().numpy()
        Image.fromarray(before).save(directory/'dense-before.png');Image.fromarray(target_hd).save(directory/'aligned-input.png')
        details={'method':'cuda_triangle_visible_projection_v2','gpu':torch.cuda.get_device_name(0),
            'torch':torch.__version__,'opencv':cv2.__version__,'candidates':candidates,'best':best,'opposite_margin':margin,
            'input_mapping_inliers':int(inliers.sum()),'input_mapping_median_residual_px':float(np.median(residual[inliers[:,0]>0])),
            'source_eye_boxes':eye_boxes.tolist(),'face_box':face_box.tolist(),'new_model_called':False}
        (directory/'alignment.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n')
        if diagnose_only:return details
        if best['iou']<policy.min_silhouette_iou or margin<policy.min_view_margin:raise Declined('真实面光栅仍不能可靠区分朝向/轮廓，保留原件；详见alignment.json')
        target_eyes=target_eye_boxes(before,eye_boxes)
        if target_eyes is None:raise Declined('真实可见面没有可靠双眼，保留原件')
        mx,my,row_reliable=silhouette_correspondence(mask,valid)
        warped=cv2.remap(target_hd,mx,my,cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT)
        mapped_mask=cv2.remap(mask.astype(np.uint8),mx,my,cv2.INTER_NEAREST)>0
        # 蓝/紫头发及其边界不属于本次皮肤/服装改色范围；保留其原生底色。
        wr,wg,wb=warped.astype(float).transpose(2,0,1)
        source_hair=(wb>wr+7)&(wb>wg+2)
        labels_count,labels,stats,_=cv2.connectedComponentsWithStats(source_hair.astype(np.uint8))
        hair_labels=[index for index,(_,y,_,h,area) in enumerate(stats[1:],1)
                     if y<height*.2 and h>height*.12 and area>100]
        model_rgb=before.astype(float);model_blue=(model_rgb[:,:,2]>model_rgb[:,:,0]+7)&(model_rgb[:,:,2]>model_rgb[:,:,1]+2)
        _,model_labels,model_stats,_=cv2.connectedComponentsWithStats(model_blue.astype(np.uint8))
        model_hair_labels=[index for index,(_,y,_,h,area) in enumerate(model_stats[1:],1)
                           if y<height*.2 and h>height*.12 and area>100]
        source_hair_region=np.isin(labels,hair_labels);model_hair_region=np.isin(model_labels,model_hair_labels)
        excluded=cv2.dilate((source_hair_region|model_hair_region).astype(np.uint8),np.ones((3,3),np.uint8))>0
        support=mapped_mask&valid&row_reliable[:,None]&~excluded
        support=cv2.erode(support.astype(np.uint8),np.ones((3,3),np.uint8))>0
        alpha=np.clip(cv2.distanceTransform(support.astype(np.uint8),cv2.DIST_L2,3)/3,0,1)
        # 头发不能按原图轮廓硬贴到别的表面：只在真实模型头发连通域内转移参考色。
        # 不拉伸原图发丝，不统一提高整张贴图亮度；原有发丝亮暗差保留。
        hair_status='skipped_no_reliable_region'
        if source_hair_region.sum()>100 and model_hair_region.sum()>100:
            reference=np.median(warped[source_hair_region].astype(float),axis=0)
            old_luma=cv2.cvtColor(before,cv2.COLOR_RGB2GRAY).astype(float)
            old_median=float(np.median(old_luma[model_hair_region]))
            contrast=cv2.bilateralFilter(old_luma.astype(np.float32),5,10,3)-old_median
            hair_rgb=np.clip(reference[None,None,:]+contrast[:,:,None],0,255)
            hair_support=cv2.erode(model_hair_region.astype(np.uint8),np.ones((3,3),np.uint8))>0
            hair_weight=np.clip(cv2.distanceTransform(hair_support.astype(np.uint8),cv2.DIST_L2,3)/2,0,1)
            warped=(warped*(1-hair_weight[:,:,None])+hair_rgb*hair_weight[:,:,None]).astype(np.uint8)
            alpha=np.maximum(alpha,hair_weight)
            hair_status='visible_palette_transfer'
        # 双眼使用独立局部对应；整身轮廓不能代替虹膜/眼线对应。
        per_eye=[]
        # 虹膜中心有原图颜色依据时用于局部平移；两眼共用尺度，避免独立拉伸成大小眼。
        source_centers=[]
        for source_box in eye_boxes:
            x0,y0,x1,y1=source_box;pad=y1-y0
            low=np.maximum(np.floor([x0,y0-pad*.3]).astype(int),0)
            high=np.minimum(np.ceil([x1,y1+pad]).astype(int),[width,height])
            crop=target_hd[low[1]:high[1],low[0]:high[0]].astype(float)
            gold=(crop[:,:,0]>crop[:,:,1]+8)&(crop[:,:,1]>crop[:,:,2]+10)&(crop.mean(2)>60)
            _,_,stats,centers=cv2.connectedComponentsWithStats(gold.astype(np.uint8))
            candidates=[(int(s[4]),c+low) for s,c in zip(stats[1:],centers[1:]) if s[4]>4]
            source_centers.append(max(candidates,key=lambda item:item[0])[1] if candidates else (source_box[:2]+source_box[2:])/2)
        target_centers=(target_eyes[:,:2]+target_eyes[:,2:])/2
        common_scale=float((target_centers[1,0]-target_centers[0,0])/(source_centers[1][0]-source_centers[0][0]))
        if not .75<common_scale<1.4:raise Declined('双眼局部尺度不一致，保持原件')
        for source_box,target_box,source_center in zip(eye_boxes,target_eyes,source_centers):
            source_size=source_box[2:]-source_box[:2]
            target_center=(target_box[:2]+target_box[2:])/2;target_size=target_box[2:]-target_box[:2]
            if np.max(np.abs((target_center-source_center)/source_size))>1.5:
                raise Declined('局部眼框偏移超过眼宽预算，拒绝投射')
            low=np.maximum(np.floor(target_center-target_size*.80).astype(int),0)
            high=np.minimum(np.ceil(target_center+target_size*.80).astype(int),[width,height])
            gx,gy=np.meshgrid(np.arange(low[0],high[0]),np.arange(low[1],high[1]))
            scale=common_scale
            ex=(gx-target_center[0])/scale+source_center[0]
            ey=(gy-target_center[1])/scale+source_center[1]
            eye_rgb=cv2.remap(target_hd,ex.astype(np.float32),ey.astype(np.float32),cv2.INTER_CUBIC)
            distance=np.maximum(np.abs((gx-target_center[0])/target_size[0]),np.abs((gy-target_center[1])/target_size[1]))
            weight=np.clip((.80-distance)/.18,0,1)
            region=np.s_[low[1]:high[1],low[0]:high[0]]
            er,eg,eb=eye_rgb.astype(float).transpose(2,0,1)
            eye_valid=(valid[region]&~((eb>er+7)&(eb>eg+2))).astype(float)
            weight*=eye_valid
            if np.count_nonzero(weight>.5)<30:raise Declined('眼部可靠可见像素不足')
            warped[region]=(warped[region]*(1-weight[:,:,None])+eye_rgb*weight[:,:,None]).astype(np.uint8)
            alpha[region]=np.maximum(alpha[region],weight)
            per_eye.append(int(np.count_nonzero(weight>.5)))
        Image.fromarray(warped).save(directory/'source-correspondence.png')
        Image.fromarray((alpha*255).astype(np.uint8)).save(directory/'supported-regions.png')
        checkpoint()
        # UV光栅只用于定位已有纹素；没有新UV、几何重建或完整PBR烘焙。
        th,tw=texture.shape[:2]
        # 唯一的逐面深度使完全重合UV也能被第二层发现；同深度剥离不能证明没有共享UV。
        uv_faces=torch.arange(f.numel(),dtype=torch.int32,device=dev).reshape(-1,3)
        flat_uv=uv[0][f.long()].reshape(-1,2)
        layers=torch.linspace(-.8,.8,len(f),device=dev).repeat_interleave(3)[:,None]
        uvpos=torch.cat((flat_uv*torch.tensor([2.,-2.],device=dev)+torch.tensor([-1.,1.],device=dev),
                         layers,torch.ones_like(layers)),1)
        with dr.DepthPeeler(ctx,uvpos[None].contiguous(),uv_faces,resolution=[th,tw]) as peeler:
            uv_rast,_=peeler.rasterize_next_layer()
            uv_second,_=peeler.rasterize_next_layer()
        attributes=torch.cat((screen,z[:,None]),1)[f.long()].reshape(1,-1,3)
        mapping,_=dr.interpolate(attributes,uv_rast,uv_faces)
        mapping=mapping[0].flip(0);occupied=(uv_rast[0,:,:,3].flip(0)>0)
        overlap=(uv_second[0,:,:,3].flip(0)>0)
        # 原视角深度测试排除背面/遮挡表面；双线性插值采样原图只发生于已支持区域。
        coord=mapping[:,:,:2]/torch.tensor([width,height],device=dev)
        grid=coord[None]*2-1
        def sample(array,mode='bilinear'):
            data=torch.as_tensor(np.ascontiguousarray(array),dtype=torch.float32,device=dev)
            if data.ndim==2:data=data[:,:,None]
            return torch.nn.functional.grid_sample(data.permute(2,0,1)[None],grid,mode=mode,padding_mode='zeros',align_corners=False)[0].permute(1,2,0)
        _,depth_rast,*_=render(best['yaw'],best['pitch'],2048)
        depth=depth_rast[:,:,2].cpu().numpy();depth_valid=(depth_rast[:,:,3]>0).cpu().numpy()
        visibility=sample(depth_valid.astype(float),'nearest')[:,:,0]>.5
        depth_match=(mapping[:,:,2]-sample(depth)[:,:,0]).abs()<.006
        # 深度负责遮挡，极端掠射面单独排除，不按细碎面法线调暗底色。
        triangles=clip[:,:3][f.long()];normal=torch.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0],dim=1)
        facing=normal[:,2].abs()/torch.linalg.vector_norm(normal,dim=1).clamp_min(1e-12)
        owners=uv_rast[0,:,:,3].flip(0).long()-1
        angle=facing[owners.clamp_min(0)]
        weights=sample(alpha)[:,:,0]*occupied*visibility*depth_match*(~overlap)*(angle>.02)
        changed=(weights>.01).cpu().numpy()
        changed_count=int(changed.sum())
        if changed_count<100:raise Declined('可安全修改纹素不足，保持原件')
        if changed_count>th*tw*policy.max_changed_fraction:raise Declined('可见面改色超过纹理预算，保持原件')
        sampled=sample(warped).clamp(0,255)
        base=torch.tensor(texture[:,:,:3].astype(np.float32),device=dev)
        new_rgb=(base*(1-weights[:,:,None])+sampled*weights[:,:,None]).round().to(torch.uint8).cpu().numpy()
        candidate=texture.copy();candidate[:,:,:3]=new_rgb
        # 在空白UV间隙补2纹素采样边，不覆盖任何其他UV表面，避免线性采样露出旧底色。
        from scipy.ndimage import distance_transform_edt
        distances,nearest=distance_transform_edt(~changed,return_indices=True)
        padding=(distances<=2)&~occupied.cpu().numpy()
        candidate[padding,:3]=candidate[nearest[0][padding],nearest[1][padding],:3]
        selected_count=changed_count
        changed_count=int(np.any(candidate[:,:,:3]!=texture[:,:,:3],axis=2).sum())
        if changed_count>th*tw*policy.max_changed_fraction:raise Declined('含采样边的实际改色超过纹理预算')
        patched=Image.fromarray(candidate);glb.save_patch(patched,output);checkpoint()
        corrected_tex=torch.tensor(candidate[:,:,:3].astype(np.float32)/255,device=dev)[None]
        texc,_=dr.interpolate(uv,raster.flip(0)[None].contiguous(),f)
        after=dr.texture(corrected_tex,texc,filter_mode='linear',boundary_mode='clamp')[0].flip(0)
        after=(after.clamp(0,1).cpu().numpy()*255).astype(np.uint8);after[~valid]=0
        Image.fromarray(after).save(directory/'dense-after.png')
        details.update({'target_eye_boxes':target_eyes.tolist(),'modified_texels':changed_count,'texture_size':[tw,th],
            'changed_fraction':changed_count/(th*tw),'per_eye_supported_pixels':per_eye,'source_eye_centers':np.array(source_centers).tolist(),
            'eye_common_scale':common_scale,'uv_padding_texels':int(padding.sum()),'supported_uv_texels':selected_count,
            'input_height_mapping_max_px':float(np.abs(my[:,0]-np.arange(height)).max()),
            'uv_overlap_texels_excluded':int(overlap.sum()),'eyes':'applied','visible_skin_clothing':'applied',
            'back_and_occluded':'unchanged','hair':hair_status,'hair_detail':'source_palette_with_original_strand_contrast','other_pbr_channels':'unchanged',
            'geometry_unchanged':True,'uv_unchanged':True,'original_bin_prefix_unchanged':True,
            'elapsed_s':time.monotonic()-started})
        (directory/'alignment.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return details
