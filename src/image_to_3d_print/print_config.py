"""打印副本原生工具配置，仅由服务端加载。"""
from pathlib import Path
from pydantic import Field
from .schemas.common import ContractModel


class PrintRepairConfig(ContractModel):
    native_python:Path
    native_paths:list[Path]=Field(min_length=1,max_length=4)
    timeout_s:float=Field(default=180,gt=0,le=300)
