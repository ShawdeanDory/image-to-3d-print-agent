"""配置仅由服务端环境/文件加载，不接受前端路径或命令。"""
import json
import os
from pathlib import Path
from typing import Literal
from pydantic import Field
from ..schemas.common import ContractModel, Text
from ..geometry.commands import ToolConfiguration
from ..runtime_contracts import Backend


class LLMConfig(ContractModel):
    base_url: str | None = None
    model: str | None = None
    api_key_env: str = 'I3D_LLM_API_KEY'
    timeout_s: float = Field(default=60, gt=0, le=60)
    thinking_mode: Literal['enabled', 'disabled'] | None = None
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)

    @property
    def configured(self):
        return bool(self.base_url and self.model and os.environ.get(self.api_key_env))


class Settings(ContractModel):
    root: Path
    tools: ToolConfiguration = Field(default_factory=ToolConfiguration)
    default_backend: Backend | None = None
    background_backend: Backend | None = None
    profile_files: list[Path] = Field(default_factory=list)
    operator_name: Text = 'local_operator'
    confirmation_origin: Literal['human', 'test_fixture'] = 'human'
    input_review_policy: Literal['automatic', 'manual'] = 'automatic'
    api_token_env: str = 'I3D_API_TOKEN'
    cors_origins: list[str] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    active_timeout_s: float = Field(default=1800, gt=0, le=3600)
    max_tool_calls: int = Field(default=32, gt=0, le=32)

    @property
    def database(self):
        return self.root / 'tasks.sqlite3'

    @classmethod
    def from_env(cls):
        file = os.environ.get('I3D_CONFIG')
        data = json.loads(Path(file).read_text(encoding='utf-8')) if file else {}
        data.setdefault('root', os.environ.get('I3D_STORAGE', 'runtime/app'))
        llm = data.setdefault('llm', {})
        if os.environ.get('I3D_LLM_BASE_URL'): llm['base_url'] = os.environ['I3D_LLM_BASE_URL']
        if os.environ.get('I3D_LLM_MODEL'): llm['model'] = os.environ['I3D_LLM_MODEL']
        return cls.model_validate(data)
