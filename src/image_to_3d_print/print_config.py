"""打印副本原生工具配置，仅由服务端加载。"""
from pathlib import Path
from typing import Literal
from pydantic import Field
from .schemas.common import ContractModel


class PrintRepairConfig(ContractModel):
    native_python:Path
    native_paths:list[Path]=Field(min_length=1,max_length=4)
    timeout_s:float=Field(default=180,gt=0,le=300)
    policy:Literal['legacy','wall05-components-v2']='legacy'


def wall_probe_tolerance(profile):
    """新配置精确探测0.5mm；已保存的旧配置维持原±0.02mm口径。"""
    return 0. if profile.profile_id=='demo_wall05_v2' and profile.version=='2.0.0' else .02
