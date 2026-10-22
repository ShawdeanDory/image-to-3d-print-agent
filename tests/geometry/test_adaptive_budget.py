"""固定图像/几何验证；没有新模型或语言模型调用。"""
import io
from pathlib import Path
from uuid import uuid4
import numpy as np
import pytest
from PIL import Image,ImageDraw


def picture(kind):
    image=Image.new('RGBA',(256,256),'white');draw=ImageDraw.Draw(image)
    if kind=='simple':draw.ellipse((45,35,210,215),fill=(240,180,0,255))
    elif kind=='detailed':
        draw.rectangle((40,40,215,215),fill='black')
        for x in range(40,216,8):
            for y in range(40,216,8):
                if (x+y)//8%2:draw.rectangle((x,y,x+3,y+3),fill='white')
    elif kind=='uncertain':
        rng=np.random.default_rng(42);image=Image.fromarray(rng.integers(0,256,(256,256,3),dtype=np.uint8))
    elif kind=='transparent':
        image=Image.new('RGBA',(256,256));ImageDraw.Draw(image).ellipse((45,35,210,215),fill='yellow')
    return image


@pytest.mark.parametrize('kind,expected',[('simple',10000),('transparent',10000),('detailed',100000),('uncertain',100000)])
def test_fixed_picture_budget_is_deterministic(kind,expected):
    from image_to_3d_print.image.complexity import analyze_image
    first=analyze_image(picture(kind));second=analyze_image(picture(kind))
    assert first==second and first.target_faces==expected
    assert first.semantic_recognition is False and first.policy_version=='image-complexity-v1'


def test_uniform_blank_is_not_claimed_simple_object():
    from image_to_3d_print.image.complexity import analyze_image
    result=analyze_image(Image.new('RGB',(64,64),'white'))
    assert result.classification=='uncertain' and result.target_faces==100000


def test_two_significant_holes_use_medium_budget():
    from image_to_3d_print.image.complexity import analyze_image
    image=Image.new('RGB',(256,256),'white');draw=ImageDraw.Draw(image)
    draw.rectangle((35,35,220,220),fill='orange')
    for x in (65,150):draw.ellipse((x,80,x+35,150),fill='white')
    result=analyze_image(image)
    assert result.classification=='medium' and result.target_faces==30000


def test_complexity_cannot_claim_inconsistent_budget():
    from pydantic import ValidationError
    from image_to_3d_print.image.complexity import ImageComplexity
    with pytest.raises(ValidationError):
        ImageComplexity(classification='complex',target_faces=10000,mask_method='unavailable',reasons=['invalid test'])


def test_private_budget_permission_is_required(tmp_path):
    from image_to_3d_print.geometry.commands import dispatch,ToolConfiguration
    outcome=dispatch(tmp_path,{'run_id':uuid4(),'operation':'propose','mesh_version':'m_'+'a'*24,
        'request':{'operation':'simplify','target_faces':10000},'adaptive_budget':True},ToolConfiguration())
    assert not outcome.tool.succeeded and outcome.tool.error.code=='STATE_CONFLICT'
