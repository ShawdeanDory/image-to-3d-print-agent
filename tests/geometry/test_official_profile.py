import io
from pathlib import Path
from uuid import uuid4
import numpy as np
import pytest
import trimesh
from PIL import Image
from pydantic import ValidationError
from image_to_3d_print.adapters.reconstruction import BackendConfig
from image_to_3d_print.image.assets import AssetStore, AutomaticInputAcceptance
from image_to_3d_print.geometry.commands import dispatch, ToolConfiguration
from image_to_3d_print.adapters.official import read_official_geometry
from image_to_3d_print.geometry.core import load_mesh


def test_official_defaults():
    config = BackendConfig(backend='triposr', python=Path('/python'), execution_root=Path('/project'))
    assert config.inference_profile == 'official'
    assert config.mc_resolution == 256 and config.chunk_size == 8192


@pytest.mark.parametrize('mode', ['RGB', 'RGBA'])
def test_original_resolution_and_bytes_reach_official_input(tmp_path, mode):
    stream = io.BytesIO()
    Image.new(mode, (1280, 720), 'orange').save(stream, 'PNG')
    assets = AssetStore(tmp_path)
    asset = assets.save(stream.getvalue(), 'duck.png')
    prepared = assets.prepare(asset.asset_id, uuid4(), preprocessing='official_input')
    assert prepared.tool.succeeded
    data = prepared.tool.data
    assert data['review_required'] is False and data['semantic_suitability'] == 'not_checked'
    original = next(a for a in prepared.artifacts if a.artifact_id == data['foreground_artifact_id'])
    assert (tmp_path / original.relative_path).read_bytes() == stream.getvalue()
    with Image.open(tmp_path / original.relative_path) as image:
        assert image.size == (1280, 720)


def test_automatic_acceptance_is_not_a_human_review(tmp_path):
    review = AutomaticInputAcceptance(asset_id='asset', foreground_artifact_id='input')
    assert review.origin == 'automatic' and review.semantic_suitability == 'not_checked'
    with pytest.raises(ValidationError):
        AutomaticInputAcceptance(asset_id='asset', foreground_artifact_id='input', reviewer='human')
    result = dispatch(tmp_path, {'run_id': str(uuid4()), 'operation': 'reconstruct', 'backend': 'triposr',
        'prepared_outcome': 'missing.json', 'review': review.model_dump()}, ToolConfiguration())
    assert not result.tool.succeeded and result.tool.error.code == 'STATE_CONFLICT'


@pytest.mark.parametrize('axis', ['z_up', 'y_up'])
def test_official_readback_preserves_asymmetric_geometry(tmp_path, axis):
    mesh = trimesh.creation.box(extents=[1., 2., 3.])
    mesh.visual.vertex_colors = [255, 150, 0, 255]
    shown = mesh.copy()
    if axis == 'y_up':
        shown.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    file = tmp_path / 'official.glb'
    shown.export(file)
    result = read_official_geometry(file, axis)
    assert np.allclose(result.extents, mesh.extents, atol=1e-6)
    assert len(result.faces) == len(mesh.faces)


def test_missing_official_export_cannot_fall_back(tmp_path):
    with pytest.raises((OSError, ValueError)):
        read_official_geometry(tmp_path / 'missing.glb', 'y_up')


def test_geometry_readback_retains_vertex_colors(tmp_path):
    mesh=trimesh.creation.box()
    mesh.visual.vertex_colors=[255,180,0,255]
    file=tmp_path/'colored.ply';mesh.export(file)
    read=load_mesh(file)
    assert read.visual.kind=='vertex'
    assert np.all(read.visual.vertex_colors==[255,180,0,255])
    assert np.allclose(read.extents,mesh.extents)


def test_official_profile_rejects_silent_parameter_changes():
    with pytest.raises(ValidationError):
        BackendConfig(backend='triposr',python=Path('/p'),execution_root=Path('/r'),mc_resolution=128)
    with pytest.raises(ValidationError):
        BackendConfig(backend='trellis2_candidate',python=Path('/p'),execution_root=Path('/r'),seed=0)
