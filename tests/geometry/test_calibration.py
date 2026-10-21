from image_to_3d_print.geometry.calibration import choose_mapping

def test_one_global_mapping_not_per_case():
    scores={'a':[.9,.8,.8],'b':[.7,.8,1.]}
    result=choose_mapping(scores)
    assert result['selected']=='a'
    assert result['status']=='development_calibrated'

def test_tied_or_failed_validation_stays_unknown():
    assert choose_mapping({'a':[.8,.8,.8],'b':[.8,.8,.8]})['status']=='needs_view_review'
    assert choose_mapping({'a':[.9,.9,.5],'b':[.7,.7,.8]})['status']=='needs_view_review'
