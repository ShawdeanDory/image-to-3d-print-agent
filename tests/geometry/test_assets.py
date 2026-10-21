import io
from pathlib import Path
from uuid import uuid4
import pytest
from PIL import Image
from image_to_3d_print.image.assets import AssetStore
from image_to_3d_print.tools import ToolFailure

def picture(mode='RGBA', size=(32,32), kind='PNG'):
    image=Image.new(mode,size,(255,0,0,0) if mode=='RGBA' else 'white')
    if mode=='RGBA':
        image.paste((255,0,0,255),(8,8,24,24))
    stream=io.BytesIO(); image.save(stream,format=kind)
    return stream.getvalue()

def test_import_and_alpha(tmp_path):
    store=AssetStore(tmp_path)
    asset=store.save(picture(),'toy.png')
    assert store.get(asset.asset_id)==asset
    assert (tmp_path/asset.relative_path).read_bytes()==picture()
    outcome=store.prepare(asset.asset_id,uuid4())
    assert outcome.tool.succeeded
    assert outcome.tool.data['method']=='existing_alpha'
    assert outcome.tool.data['review_required'] is True
    assert {a.kind for a in outcome.artifacts}>={'input_image','foreground_image'}

@pytest.mark.parametrize('payload,name',[(b'bad','x.png'),(picture(),'x.jpg'),(picture(),'../x.png'),(picture(),'x.svg'),(b'a'*10485761,'x.png')],ids=['corrupt','mismatched_format','path_escape','unsupported_suffix','over_10mib'])
def test_reject_invalid(tmp_path,payload,name):
    with pytest.raises(ToolFailure): AssetStore(tmp_path).save(payload,name)

def test_empty_and_oversize(tmp_path):
    store=AssetStore(tmp_path)
    with pytest.raises(ToolFailure):store.save(picture(size=(4097,1)),'x.png')
    stream=io.BytesIO(); Image.new('RGBA',(20,20)).save(stream,format='PNG')
    a=store.save(stream.getvalue(),'empty.png')
    assert not store.prepare(a.asset_id,uuid4()).tool.succeeded

def test_rgb_needs_config(tmp_path):
    store=AssetStore(tmp_path)
    a=store.save(picture(mode='RGB'),'x.png')
    result=store.prepare(a.asset_id,uuid4())
    assert not result.tool.succeeded and result.tool.error.code=='MODEL_NOT_CONFIGURED'

def test_path_is_not_asset_id(tmp_path):
    with pytest.raises(ToolFailure):AssetStore(tmp_path).get('../outside')
