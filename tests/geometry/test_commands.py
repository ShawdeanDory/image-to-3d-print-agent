import io,json,subprocess,sys
from pathlib import Path
from uuid import uuid4
import pytest
from PIL import Image
from image_to_3d_print.geometry.commands import dispatch,ToolConfiguration
from image_to_3d_print.geometry.core import MeshStore
from image_to_3d_print.schemas import ModelTaskRequest
from image_to_3d_print.tools import ToolOutcome

def test_cli_import_and_prepare(tmp_path):
    source=tmp_path/'toy.png';image=Image.new('RGBA',(32,32));image.paste('red',(8,8,24,24));image.save(source)
    run=str(uuid4());request=tmp_path/'request.json'
    request.write_text(json.dumps({'operation':'import_image','run_id':run,'source':'toy.png'}))
    cli=Path(__file__).resolve().parents[2]/'scripts/tools/geometry_cli.py'
    result=subprocess.run([sys.executable,str(cli),'--root',str(tmp_path),'--request',str(request)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    imported=ToolOutcome.model_validate_json(result.stdout)
    asset=imported.tool.data['asset']['asset_id']
    prepared=dispatch(tmp_path,{'operation':'prepare_image','run_id':run,'asset_id':asset},ToolConfiguration())
    assert prepared.tool.succeeded
    with Image.open(tmp_path/next(a.relative_path for a in prepared.artifacts if a.artifact_id==prepared.tool.data['foreground_artifact_id'])) as image:
        assert image.size==(256,256)

def test_model_cannot_approve_structure(tmp_path):
    outcome=dispatch(tmp_path,{'operation':'confirm','run_id':str(uuid4()),'proposal_id':'p_unknown','reviewer':'language_model','accepted':True},ToolConfiguration())
    assert not outcome.tool.succeeded and outcome.tool.error.code=='STATE_CONFLICT'

def test_unknown_asset_returns_public_error(tmp_path):
    outcome=dispatch(tmp_path,{'operation':'prepare_image','run_id':str(uuid4()),'asset_id':'a_missing'},ToolConfiguration())
    assert not outcome.tool.succeeded and outcome.tool.error.code=='REFERENCE_NOT_FOUND'

@pytest.mark.parametrize('operation',['reconstruct','scale','bed_review','component_review'])
def test_model_cannot_invent_confirmation(tmp_path,operation):
    run=str(uuid4());call={'run_id':run,'operation':operation,'mesh_version':'missing_mesh'}
    if operation=='reconstruct':
        call.pop('mesh_version');call.update(backend='triposr',prepared_outcome='missing.json',review={
            'asset_id':'asset','foreground_artifact_id':'fg','decision':'accepted','reviewer':'invented',
            'origin':'human','complete_subject':True,'simple_nonfunctional_ornament':True,'foreground_correct':True})
    elif operation=='scale':
        call['request']={'image_asset_id':'asset','printer_profile_id':'demo_v1','height_value':80.,'height_unit':'mm',
            'scale_source':'user_target','orientation':{'up_axis':'z','confirmed':True}}
    else:
        call['operation']='inspect';call['profile']=json.loads((Path(__file__).resolve().parents[2]/'fixtures/p1/printer_profile.json').read_text())
        call[operation]={'mesh_version':'missing_mesh','confirmed':True,'reviewer':'invented','origin':'human'}
        if operation=='component_review':call[operation]['component_count']=2
    outcome=dispatch(tmp_path,call,ToolConfiguration())
    assert not outcome.tool.succeeded and outcome.tool.error.code=='STATE_CONFLICT'

@pytest.mark.parametrize('axis',['x','y','z','-x','-y','-z'])
def test_all_confirmed_up_axes(tmp_path,axis):
    from image_to_3d_print.geometry.core import orient_and_scale,load_mesh
    mesh=load_mesh(Path(__file__).resolve().parents[2]/'fixtures/p1/geometry/cube_10mm.stl')
    request=ModelTaskRequest(image_asset_id='asset',printer_profile_id='profile',height_value=20.,height_unit='mm',scale_source='user_target',orientation={'confirmed':True,'up_axis':axis})
    output,matrix=orient_and_scale(mesh,request)
    assert output.extents[2]==pytest.approx(20.) and output.bounds[0,2]==pytest.approx(0.)
