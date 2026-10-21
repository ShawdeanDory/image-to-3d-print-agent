"""工具产物与公共结果封装；不推进Agent状态。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import os,signal
from uuid import UUID, uuid4
from pydantic import Field
from .schemas.common import ArtifactRecord, ContractModel, ErrorInfo, EvidenceRecord, ToolResult, safe_relative_path

class ToolFailure(ValueError):
    def __init__(self, code, message):
        self.code=code
        super().__init__(message)

def stop_process_group(process):
    if process.poll() is None:
        try:
            if os.name=='posix':os.killpg(process.pid,signal.SIGKILL)
            else:process.kill()
        except ProcessLookupError:pass
        process.wait()

class ToolOutcome(ContractModel):
    tool: ToolResult
    artifacts: list[ArtifactRecord]=Field(default_factory=list)
    evidence: list[EvidenceRecord]=Field(default_factory=list)

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def new_directory(root, relative):
    safe_relative_path(relative)
    root=Path(root).resolve(); target=(root/relative).resolve()
    if not target.is_relative_to(root):
        raise ToolFailure('INVALID_ARGUMENT','路径越过任务存储目录')
    try: target.mkdir(parents=True,exist_ok=False)
    except FileExistsError as exc: raise ToolFailure('STATE_CONFLICT','已有产物不能覆盖') from exc
    return target

class ToolSession:
    def __init__(self, root, run_id: UUID, name, mesh_version=None):
        self.root=Path(root).resolve(); self.run_id=UUID(str(run_id)); self.name=name
        self.mesh_version=mesh_version; self.started=time.perf_counter(); self.now=datetime.now(timezone.utc)
        self.prefix='t_'+uuid4().hex[:16]
        self.relative=f'runs/{self.run_id}/tools/{self.prefix}'
        self.directory=new_directory(self.root,self.relative)
        self.artifacts=[]

    def add(self, name, path, kind, unit=None, parents=()):
        path=Path(path).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ToolFailure('REFERENCE_NOT_FOUND','产物不存在或越界')
        record=ArtifactRecord(artifact_id=f'{self.prefix}_{name}',run_id=self.run_id,
            mesh_version=self.mesh_version,kind=kind,relative_path=path.relative_to(self.root).as_posix(),
            created_at=self.now,unit=unit,derived_from=list(parents))
        self.artifacts.append(record)
        return record

    def finish(self, data, error=None):
        for name,kind in [('process.log','log'),('model.json','inspection_report'),('execution.json','inspection_report'),('invocation.json','inspection_report')]:
            if (self.directory/name).is_file():self.add(name.replace('.','_'),self.directory/name,kind)
        data={**data,'seconds':time.perf_counter()-self.started}
        report=self.directory/'tool-report.json'
        report.write_text(json.dumps({'tool':self.name,'run_id':str(self.run_id),'mesh_version':self.mesh_version,
            'data':data,'error':error.model_dump(mode='json') if error else None},ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        artifact=self.add('report',report,'inspection_report')
        evidence=EvidenceRecord(evidence_id=self.prefix+'_evidence',source_type='tool',source_id=self.prefix,
            run_id=self.run_id,mesh_version=self.mesh_version,artifact_id=artifact.artifact_id,locator='data',
            created_at=self.now,summary='实际工具执行记录；不替代最终预览和切片确认')
        outcome=ToolOutcome(tool=ToolResult(run_id=self.run_id,tool_name=self.name,succeeded=error is None,
            artifact_ids=[a.artifact_id for a in self.artifacts],evidence_ids=[evidence.evidence_id],
            data=data,error=error),artifacts=self.artifacts,evidence=[evidence])
        (self.directory/'outcome.json').write_text(outcome.model_dump_json(indent=2)+'\n',encoding='utf-8')
        return outcome

    def fail(self, code, message, data=None):
        return self.finish(data or {},ErrorInfo(code=code,message=message))
