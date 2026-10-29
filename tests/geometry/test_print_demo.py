"""简单摆件打印副本门槛；本机只验证确定性规则，不冒充原生算法执行。"""
import numpy as np
import pytest
import trimesh
from image_to_3d_print.print_demo import shape_gate,gcode_summary,prepare_demo,PrintDemoConfig


def test_closed_body_and_filled_internal_cavity_preserve_outer_shape():
    outer=trimesh.creation.box(extents=[80,70,120]);inner=trimesh.creation.box(extents=[79,69,119]);inner.invert()
    source=trimesh.util.concatenate([outer,inner])
    result=shape_gate(source,outer)
    assert result['accepted'] and min(result['three_view_iou'])==1.


def test_watertight_but_lost_external_part_is_rejected():
    source=trimesh.creation.box(extents=[80,70,120]);part=source.copy();part.apply_translation([100,0,0])
    assert not shape_gate(trimesh.util.concatenate([source,part]),source)['accepted']


def test_large_dimension_change_is_rejected_even_without_holes():
    source=trimesh.creation.box(extents=[80,70,120]);smaller=source.copy();smaller.vertices[:,0]*=.85
    assert smaller.is_watertight and not shape_gate(source,smaller)['accepted']


@pytest.mark.parametrize('content',[
    ';Z:0.2\n;LAYER_CHANGE\nG1 X1 Y1\n',
    ';Z:120\nG1 X1 Y1 E1\n',
    ';Z:200\n;LAYER_CHANGE\nG1 X1 Y1 E1\n',
])
def test_empty_extrusion_missing_layers_and_wrong_height_do_not_pass(content):
    assert not gcode_summary(content,120)['passed']


def test_slicing_evidence_cannot_claim_physical_print():
    content=';Z:0.2\n;LAYER_CHANGE\nG1 X1 Y1 E1\n;Z:120\n;LAYER_CHANGE\nG1 X2 Y2 E2\n'
    result=gcode_summary(content,120)
    assert result['passed'] and result['layers']==2 and result['physical_print'] is False


def test_wrong_height_or_missing_source_does_not_create_output(tmp_path):
    from image_to_3d_print.tools import ToolFailure
    output=tmp_path/'out'
    with pytest.raises(ToolFailure):prepare_demo(tmp_path/'missing.glb',output,None,None,80)
    assert not output.exists()


def test_internal_config_rejects_commands_and_unbounded_runtime():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):PrintDemoConfig(native_python='python',native_paths=['deps'],command='anything')
    with pytest.raises(ValidationError):PrintDemoConfig(native_python='python',native_paths=['deps'],timeout_s=9999)


def test_support_intermediate_layers_are_allowed_but_empty_z_gaps_are_not():
    content=''.join(f';Z:{z}\n;LAYER_CHANGE\nG1 X1 Y1 E1\n' for z in [.2,.3,.4,.5,.6,.8,1.])
    assert gcode_summary(content,1.,.2,supports=True)['passed']
    assert not gcode_summary(content,1.,.2,supports=False)['passed']
    skipped=''.join(f';Z:{z}\n;LAYER_CHANGE\nG1 X1 Y1 E1\n' for z in [.2,.25,.3,.4,.5,.6,1.])
    assert not gcode_summary(skipped,1.,.2,supports=True)['passed']
    assert not gcode_summary(content.replace(' E1',' E-1'),1.,.2,supports=True)['passed']
