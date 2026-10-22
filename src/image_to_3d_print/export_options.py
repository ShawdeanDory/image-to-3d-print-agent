"""首次提交的可选导出预算；不改变模型推理或打印结论。"""
from typing import Annotated
from pydantic import Field, StrictInt

ExportTargetFaces = Annotated[StrictInt, Field(ge=100, le=1000000)]
TextureSize = Annotated[StrictInt, Field(ge=256, le=4096)]
