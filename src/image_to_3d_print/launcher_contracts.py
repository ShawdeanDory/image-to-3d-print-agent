"""桌面启动配置与结果；不包含凭据，不扩展公共业务契约。"""
from typing import Literal
from pydantic import Field, model_validator
from .schemas.common import ContractModel, RelativePath
from .schemas import ErrorInfo


class LauncherConfig(ContractModel):
    ssh_config: RelativePath = 'runtime/ssh/p2a_config'
    ssh_alias: str = Field(default='p2a-autodl', pattern=r'^[A-Za-z0-9_.-]+$')
    remote_project: str = Field(default='/root/autodl-tmp/image-to-3d-print-agent', pattern=r'^/[A-Za-z0-9_./-]+$')
    deployment: str = Field(default='deployments/official-20261021-01', pattern=r'^deployments/[A-Za-z0-9_./-]+$')
    tunnel_port: int = Field(default=9000, ge=1024, le=65535)
    ui_port: int = Field(default=5173, ge=1024, le=65535)

    @model_validator(mode='after')
    def local_and_remote_paths(self):
        if self.tunnel_port == self.ui_port:
            raise ValueError('网页与SSH隧道端口不能相同')
        if '..' in self.remote_project.split('/') or '..' in self.deployment.split('/') or self.deployment.startswith('/'):
            raise ValueError('云端路径不能越界')
        return self


class LauncherResult(ContractModel):
    kind: Literal['desktop_launcher'] = 'desktop_launcher'
    status: Literal['succeeded', 'failed']
    phase: str
    page_url: str | None = None
    error: ErrorInfo | None = None
    model_submitted: Literal[False] = False
