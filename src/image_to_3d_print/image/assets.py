"""接收上传字节，不接受客户端任意磁盘路径。"""
import io
from pathlib import Path
from typing import Literal
from uuid import uuid4
from PIL import Image, ImageOps
from pydantic import Field
from ..schemas.common import AssetRecord, ContractModel, Id, Text
from ..schemas.validation import resolve_artifact_path
from ..tools import ToolFailure, ToolSession, new_directory

class InputReview(ContractModel):
    asset_id: Id
    foreground_artifact_id: Id
    decision: Literal['accepted','replace_image','uncertain']
    reviewer: Text
    complete_subject: bool
    simple_nonfunctional_ornament: bool
    foreground_correct: bool
    origin: Literal['human','ai_review','test_fixture']='human'

    @property
    def accepted(self):
        return self.decision=='accepted' and self.complete_subject and self.simple_nonfunctional_ornament and self.foreground_correct

class AssetStore:
    def __init__(self,root):self.root=Path(root).resolve()

    def save(self,payload:bytes,filename:str):
        if not filename or '/' in filename or '\\' in filename or ':' in filename:
            raise ToolFailure('INVALID_IMAGE','文件名无效')
        suffix=Path(filename).suffix.lower()
        if suffix not in {'.png','.jpg','.jpeg'} or not 0<len(payload)<=10485760:
            raise ToolFailure('INVALID_IMAGE','只接受10MiB以内PNG/JPEG')
        try:
            with Image.open(io.BytesIO(payload)) as image:
                fmt=image.format; width,height=image.size
                if (fmt not in {'PNG','JPEG'} or fmt!=('PNG' if suffix=='.png' else 'JPEG')
                        or not 0<width<=4096 or not 0<height<=4096):
                    raise ValueError('真实格式、扩展名或分辨率不符合约定')
                image.verify()
            with Image.open(io.BytesIO(payload)) as image:image.load()
        except (OSError,ValueError,SyntaxError,Image.DecompressionBombError) as exc:
            raise ToolFailure('INVALID_IMAGE','图片损坏、伪格式或超出像素限制') from exc
        asset_id='a_'+uuid4().hex
        relative=f'assets/{asset_id}'
        folder=new_directory(self.root,relative)
        target=folder/('original'+suffix); target.write_bytes(payload)
        asset=AssetRecord(asset_id=asset_id,relative_path=target.relative_to(self.root).as_posix(),
            content_type='image/png' if fmt=='PNG' else 'image/jpeg',byte_count=len(payload),width=width,height=height)
        (folder/'asset.json').write_text(asset.model_dump_json(indent=2)+'\n',encoding='utf-8')
        return asset

    def get(self,asset_id):
        if not isinstance(asset_id,str) or not asset_id.startswith('a_') or not asset_id[2:].isalnum() or len(asset_id)!=34:
            raise ToolFailure('REFERENCE_NOT_FOUND','必须提供已注册资产ID')
        try:
            file=resolve_artifact_path(self.root,f'assets/{asset_id}/asset.json')
            asset=AssetRecord.model_validate_json(file.read_text(encoding='utf-8'))
            image=resolve_artifact_path(self.root,asset.relative_path)
            if asset.asset_id!=asset_id or image.parent!=file.parent or image.stat().st_size!=asset.byte_count:
                raise ValueError('资产记录与原图不一致')
            return asset
        except (OSError,ValueError) as exc:raise ToolFailure('REFERENCE_NOT_FOUND','资产不存在或记录不一致') from exc

    def prepare(self,asset_id,run_id,background_runner=None):
        session=ToolSession(self.root,run_id,'preprocess')
        try:
            asset=self.get(asset_id)
            source=resolve_artifact_path(self.root,asset.relative_path)
            original=session.add('original',source,'input_image')
            with Image.open(source) as image:image=ImageOps.exif_transpose(image).convert('RGBA')
            alpha=image.getchannel('A'); method='existing_alpha'
            if alpha.getbbox() is None:raise ToolFailure('INVALID_IMAGE','图片没有前景')
            if alpha.getextrema()[0]==255:
                if background_runner is None:raise ToolFailure('MODEL_NOT_CONFIGURED','普通图片需要显式RMBG环境配置')
                image=background_runner(source,session.directory).convert('RGBA')
                method='rmbg_2_offline'
                if image.size!=(asset.height,asset.width) and image.size!=(asset.width,asset.height):
                    raise ToolFailure('INVALID_IMAGE','去背景输出尺寸与输入不符')
                alpha=image.getchannel('A')
            mask=alpha.point(lambda value:255 if value>=128 else 0)
            bbox=mask.getbbox()
            if bbox is None or alpha.getextrema()[0]==255:
                raise ToolFailure('INVALID_IMAGE','去背景未得到有效透明主体，请更换图片')
            # 公共预处理保持等比，彩色双线性、蒙版最近邻；原图单独保留。
            crop=image.crop(bbox);ratio=224/max(crop.size)
            size=tuple(max(1,int(v*ratio+.5)) for v in crop.size)
            canvas=Image.new('RGBA',(256,256),(255,255,255,0))
            canvas.paste(crop.resize(size,Image.Resampling.BILINEAR),tuple((256-v)//2 for v in size))
            prepared_mask=Image.new('L',(256,256))
            prepared_mask.paste(mask.crop(bbox).resize(size,Image.Resampling.NEAREST),tuple((256-v)//2 for v in size))
            foreground=session.directory/'foreground.png'; canvas.save(foreground)
            mask_path=session.directory/'mask.png'; prepared_mask.save(mask_path)
            fg=session.add('foreground',foreground,'foreground_image',parents=[original.artifact_id])
            ma=session.add('mask',mask_path,'foreground_image',parents=[original.artifact_id])
            touches=bbox[0]==0 or bbox[1]==0 or bbox[2]==mask.width or bbox[3]==mask.height
            return session.finish({'asset_id':asset_id,'method':method,'foreground_artifact_id':fg.artifact_id,
                'mask_artifact_id':ma.artifact_id,'review_required':True,'touches_image_border':touches,
                'semantic_suitability':'human_review_required','original_preserved':True})
        except ToolFailure as exc:return session.fail(exc.code,str(exc))
        except (OSError,ValueError) as exc:return session.fail('INVALID_IMAGE','图片处理失败：'+str(exc)[:300])
