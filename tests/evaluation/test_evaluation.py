"""评估只归档实际证据，冻结前不得执行保留集。"""
import pytest
from image_to_3d_print.evaluation import EvaluationPlan, FreezeApproval, gate, compare_reports, summarize

def test_holdout_requires_real_frozen_approval():
    plan=EvaluationPlan(dataset_version='1.0.0',backend='triposr',model_revision='fixed',code_revision='fixed',protocol_version='1.0.0',split='holdout')
    assert not gate(plan,None)['allowed']
    approval=FreezeApproval(dataset_version='1.0.0',backend='triposr',model_revision='fixed',code_revision='fixed',protocol_version='1.0.0',
        reviewer='test_fixture',origin='test_fixture',backend_selected=True,camera_approved=True,successful_print_paths=3,slicer_objects=1)
    assert not gate(plan,approval)['allowed']

def report(backend='triposr',run='r',status='failed'):
    return {'schema_version':'runtime-v1','run_id':run,'status':status,'evidence_origin':'runtime','backend':backend,
        'operations':[{'operation':'reconstruct','result':{'data':{'backend':backend,'mesh_version':'m_original'}}}], 'inspection':None,'inspection_history':[],
        'export_readback':None,'llm':{'calls':0,'input_tokens':None,'output_tokens':None,'cost':None},'active_seconds':None}

def test_same_backend_original_required_for_comparison():
    with pytest.raises(ValueError):compare_reports(report(),report('trellis2_candidate'))
    with pytest.raises(ValueError):compare_reports(report(),report(run='other'))
    result=compare_reports(report(),report())
    assert result['mesh_error'] is None
    assert result['input_view_iou'] is None

def test_unknown_and_fixture_not_in_real_success_denominator():
    a=report();b=report(run='fixture',status='succeeded');b['evidence_origin']='test_fixture'
    result=summarize([a,b])
    assert result['real_runs']==1 and result['fixture_runs']==1
    assert result['real_succeeded']==0
    assert result['cost_total'] is None

def test_duplicates_rejected():
    with pytest.raises(ValueError):summarize([report(),report()])

def test_actual_tool_result_shape_is_supported():
    a=report();a.pop('backend');data=a['operations'][0]['result']['data'];data.pop('backend');data['execution']={'backend':'triposr'}
    assert compare_reports(a,a)['backend']=='triposr'
