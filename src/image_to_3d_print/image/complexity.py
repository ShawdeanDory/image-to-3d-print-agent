"""CPU图像复杂度启发式；仅估计网格预算，不识别物体语义或不可见几何。"""
from typing import Literal
import numpy as np
from PIL import Image,ImageOps
from scipy import ndimage
from pydantic import Field,model_validator
from ..schemas.common import ContractModel,Text


class ImageComplexity(ContractModel):
    policy_version:Literal['image-complexity-v1']='image-complexity-v1'
    classification:Literal['simple','medium','complex','uncertain']
    target_faces:Literal[10000,30000,100000]
    semantic_recognition:Literal[False]=False
    mask_method:Literal['alpha','uniform_border','unavailable']
    features:dict[str,float|int]=Field(default_factory=dict)
    reasons:list[Text]

    @model_validator(mode='after')
    def matching_budget(self):
        if self.target_faces!={'simple':10000,'medium':30000,'complex':100000,'uncertain':100000}[self.classification]:
            raise ValueError('复杂度分类与策略面数不一致')
        return self


def analyze_image(image:Image.Image):
    """分析副本最长边256；不改变传给重建模型的原图。"""
    image=ImageOps.exif_transpose(image).convert('RGBA');image.thumbnail((256,256))
    pixels=np.asarray(image);rgb=pixels[:,:,:3].astype(float)/255;alpha=pixels[:,:,3]
    def result(kind,method,features,reasons):
        return ImageComplexity(classification=kind,target_faces={'simple':10000,'medium':30000,'complex':100000,'uncertain':100000}[kind],
            mask_method=method,features=features,reasons=reasons)
    if min(image.size)<16:return result('uncertain','unavailable',{},['图像过小，不能可靠估计细节'])
    if np.any(alpha<128):mask=alpha>=128;method='alpha'
    else:
        border=np.concatenate([rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]])
        background=np.median(border,axis=0)
        spread=float(np.quantile(np.max(np.abs(border-background),axis=1),.9))
        if spread>35/255:return result('uncertain','unavailable',{'border_spread':spread},['边缘背景不一致，保守使用高面数预算'])
        mask=np.max(np.abs(rgb-background),axis=2)>40/255;method='uniform_border'
    area=int(mask.sum());coverage=area/mask.size
    touches=int(mask[0].sum()+mask[-1].sum()+mask[:,0].sum()+mask[:,-1].sum())
    if coverage<.02 or coverage>.85 or touches>2:
        return result('uncertain',method,{'foreground_fraction':coverage},['前景为空、过小、接近满图或被边界裁切，保守保留细节'])
    labels,count=ndimage.label(mask);sizes=np.bincount(labels.ravel())[1:]
    components=int(np.sum(sizes>=max(16,area*.005)))
    # 填孔只用于统计外轮廓；孔洞数和内部边缘仍保留，不拿文字纹理当已知3D结构。
    filled=ndimage.binary_fill_holes(mask);holes,n=ndimage.label(filled&~mask)
    hole_sizes=np.bincount(holes.ravel())[1:];hole_count=int(np.sum(hole_sizes>=max(16,area*.002)))
    padded=np.pad(filled.astype(int),1)
    perimeter=float(np.abs(np.diff(padded,axis=0)).sum()+np.abs(np.diff(padded,axis=1)).sum())
    compactness=perimeter**2/(4*np.pi*max(int(filled.sum()),1))
    gray=ndimage.gaussian_filter(rgb@np.array([.299,.587,.114]),1.)
    gradient=np.hypot(ndimage.sobel(gray,axis=0),ndimage.sobel(gray,axis=1))/4
    interior=ndimage.binary_erosion(filled,iterations=3)
    density=float(np.mean(gradient[interior]>.10)) if interior.any() else 1.
    features={'foreground_fraction':coverage,'significant_components':components,'significant_holes':hole_count,
        'contour_compactness':compactness,'interior_edge_density':density}
    if components<=1 and hole_count<=1 and compactness<=3.5 and density<=.12:kind='simple'
    elif components<=3 and hole_count<=3 and compactness<=6.0 and density<=.23:kind='medium'
    else:kind='complex'
    return result(kind,method,features,['按前景轮廓、组件、孔洞和内部边缘估计；纹理不等于几何细节，须由网格保形验证'])
