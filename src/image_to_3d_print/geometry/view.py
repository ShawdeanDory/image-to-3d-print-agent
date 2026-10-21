"""运行时只消费服务端登记的共享映射，不接受逐例自由旋转。"""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from ..measurement import load_policy,render_silhouette,normalize_mask,mask_iou,MeasurementError
from ..schemas.experiment import MetricValue
from ..schemas.validation import resolve_artifact_path
from ..adapters.reconstruction import REVISIONS
from ..tools import ToolSession,ToolFailure
from .core import MeshStore,load_mesh

def measure_view(root,run,version,mask_path,backend,mapping_file):
    session=ToolSession(root,run,'inspect',version)
    metric=MetricValue(name='silhouette_iou',status='not_run',unit='ratio',reason='backend_view_mapping_not_registered')
    if mapping_file is None:return session.finish({'metric':metric.model_dump(mode='json')})
    try:
        mapping=json.loads(resolve_artifact_path(root,mapping_file).read_text(encoding='utf-8'))
        if mapping['backend']!=backend or mapping['upstream_revision']!=REVISIONS[backend] or mapping['protocol_version']!='1.0.0':
            raise ToolFailure('STATE_CONFLICT','固定映射的后端、版本或协议不一致')
        if mapping['status']!='development_calibrated' or mapping['human_review']!='passed':
            return session.finish({'metric':metric.model_copy(update={'reason':'development_view_mapping_pending_review'}).model_dump(mode='json')})
        store=MeshStore(root);source=store.get(run,version);current=source;pose=np.eye(3)
        while current.parent is not None:
            if current.operation=='orient_scale_place':
                transform=np.array(current.parameters['matrix'])[:3,:3]
                pose=pose@(transform/np.linalg.norm(transform[:,0]))
            current=store.get(run,current.parent)
        if current.parameters.get('backend')!=backend or current.parameters.get('coordinate_system')!='z_up_unitless':
            raise ToolFailure('STATE_CONFLICT','映射只能用于对应后端的已登记原生坐标网格')
        rotation=np.asarray(mapping['rotation'])@pose.T
        policy=load_policy(root);mesh=load_mesh(Path(root)/source.relative_path)
        projection,_=render_silhouette(mesh.vertices,mesh.faces,rotation.tolist(),policy)
        with Image.open(resolve_artifact_path(root,mask_path)) as image:mask=normalize_mask(image,policy)
        projected=normalize_mask(projection,policy);metric=mask_iou(mask,projected)
        overlay=Image.merge('RGB',(mask,projected,Image.new('L',mask.size)));path=session.directory/'view-overlay.png';overlay.save(path)
        session.add('overlay',path,'inspection_report')
        return session.finish({'metric':metric.model_dump(mode='json'),'mapping_file':mapping_file,'rotation':rotation.tolist(),
            'source_sha256':source.sha256,'quality_scope':'registered_single_view_silhouette_not_printability'})
    except (ToolFailure,MeasurementError) as exc:return session.fail(exc.code,str(exc))
    except (OSError,ValueError,KeyError) as exc:return session.fail('INVALID_ARGUMENT','映射或蒙版无效')
