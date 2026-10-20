"""确定性引用及本地文件校验，不下载、预处理或运行模型。"""
from pathlib import Path
from .common import safe_relative_path
from .task import ModelTaskResponse


def resolve_artifact_path(root, relative_path):
    safe_relative_path(relative_path)
    root = Path(root).resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("文件不存在或越过所属执行目录")
    return target


def validate_request_references(request, asset_ids, profiles, measurement_ids):
    if request.image_asset_id not in asset_ids or request.printer_profile_id not in profiles:
        raise ValueError("图片或打印配置引用不存在")
    if request.scale_source == "measured_object" and request.scale_evidence_id not in measurement_ids:
        raise ValueError("测量证据引用不存在")
    return request


def validate_response_references(response, root):
    response = ModelTaskResponse.model_validate_json(response.model_dump_json())
    for artifact in response.artifacts:
        resolve_artifact_path(root, artifact.relative_path)
    return response


def validate_dataset_files(manifest, root, assets):
    """只检查清单与文件格式，不执行保留集生成、指标或成败评估。"""
    from PIL import Image
    catalog = {asset.asset_id: asset for asset in assets}
    if len(catalog) != len(assets): raise ValueError("asset注册表ID重复")
    for case in manifest.cases:
        path = resolve_artifact_path(root, case.asset_path)
        try:
            with Image.open(path) as image:
                if image.format not in {"PNG", "JPEG"}: raise ValueError("不支持真实图像类型")
                if image.width > 4096 or image.height > 4096: raise ValueError("图像超过约定尺寸")
                size = image.size
                image.verify()
            decodes = True
        except (OSError, ValueError, SyntaxError):
            decodes = False
        if decodes != case.image_should_decode:
            raise ValueError("样例实际格式与声明不符:" + case.case_id)
        asset = catalog.get(case.request["image_asset_id"])
        if decodes:
            if asset is None or asset.relative_path != case.asset_path or asset.byte_count != path.stat().st_size or (asset.width, asset.height) != size:
                raise ValueError("图像文件与asset注册信息不一致:" + case.case_id)
        elif asset is not None:
            raise ValueError("非法上传不能引用已注册asset")
        if case.mask_path is not None:
            with Image.open(resolve_artifact_path(root, case.mask_path)) as mask:
                if mask.mode not in {"1", "L"} or mask.size != size: raise ValueError("蒙版必须是单通道")
                mask.verify()
        if case.reference_mesh is not None: resolve_artifact_path(root, case.reference_mesh)
    return manifest


def validate_experiment_references(record, artifact_ids, evidence_ids, budget):
    if record.status != "not_run":
        budget.require_ready()
        if record.budget_ref != budget.budget_id: raise ValueError("预算引用不符")
        if not set(record.artifact_ids) <= set(artifact_ids) or not set(record.evidence_ids) <= set(evidence_ids):
            raise ValueError("实验产物或证据引用不存在")
    return record


def http_status_for_boundary_error(code):
    mapping = {"INVALID_IMAGE": 422, "INVALID_ARGUMENT": 422, "REFERENCE_NOT_FOUND": 404, "STATE_CONFLICT": 409}
    if code not in mapping: raise ValueError("运行工具错误应进入任务状态，不能伪造HTTP边界错误")
    return mapping[code]
