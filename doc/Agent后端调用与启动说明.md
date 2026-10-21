# Agent后端调用与启动说明

Windows使用者优先按[桌面一键启动说明](桌面一键启动与连接说明.md)双击根目录exe，自动补启动既有API/单worker、隧道及网页；以下命令保留为手工启动/排障入口。实例开机不会自动恢复这些应用进程，本机网页按钮也无法替代SSH/服务启动。

版本：包0.3.0、运行时扩展runtime-v1、公共契约1.0.0。实现矩阵及验证边界见[交付报告](Agent工作流与后端交付.md)。

## 1.安装与两个进程

从仓库根目录启动，Python3.11以上。服务环境与现有模型环境分离；模型、源码、权重和Blender不会随Git克隆。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[test,geometry,backend]"
$env:I3D_CONFIG = "$PWD/config/backend.example.json"
.venv/Scripts/python -m image_to_3d_print.api
```

另一个终端使用相同配置和存储目录启动worker：

```powershell
$env:I3D_CONFIG = "$PWD/config/backend.example.json"
.venv/Scripts/python -m image_to_3d_print.jobs.worker
```

Linux使用对应环境的python，并用`export I3D_CONFIG="$PWD/config/backend.example.json"`指定同一配置。默认API地址为`http://127.0.0.1:8000`，交互文档为`/docs`，OpenAPI为`/openapi.json`。API不启动内嵌worker、不在HTTP请求内重建。`worker --once`只处理一个已排队任务；正常交互演示使用持续worker。

样例配置可以启动服务和缺配置/追问分支；其中模型、检查器、LLM为空，不能执行真实重建与合格打印交付。实际部署时将配置复制到被忽略的runtime目录，按[几何工具接手说明](几何工具接口与接手说明.md#4linux部署和复现)填写既有Linux环境。不要重新安装已通过的模型环境。`profile_files`必须载入实际登记配置；样例使用demo_v1演示配置，不能称为实机认证参数。相对路径以启动时仓库根目录解析。

独立worker使用存储目录的操作系统文件锁；同一存储只能有一个worker。两个独立存储不能共用一张GPU来规避并发1约定。停止worker用Ctrl+C或SIGTERM，运行中的计算会回收，任务记录WORKER_RESTARTED；等待任务保持，可在重启后补充输入。

## 2.服务配置

[Settings](../src/image_to_3d_print/jobs/config.py)是唯一配置模型，[配置样例](../config/backend.example.json)可直接核对字段。前端不能提交工具路径、shell命令、超时上限或密钥。

- `tools.backends`登记triposr/trellis2_candidate的固定解释器及执行根目录；创建可显式选择后端，未选择时使用`default_backend`，不自动换模型或机器。
- `background_backend`仅用于普通不透明PNG/JPEG的RMBG准备，透明前景图可直接准备；没有对应环境就明确失败。
- `tools.inspection`指定LinuxBlender和已锁定打印工具；缺失时检查保留not_run并阻断交付。Windows开发机不会被当作Linux模型环境。
- `tools.view_mappings`只使用已登记且实际批准的映射；本轮不自动批准已有开发映射，不把轮廓分数缺失改成0。
- `llm.base_url`为兼容ChatCompletions的服务根路径，例如服务端实际提供的`https://服务域名/v1`；适配器追加`/chat/completions`。模型名由`llm.model`明确设置。密钥只从`llm.api_key_env`指定的环境变量读取，默认I3D_LLM_API_KEY。也可用I3D_LLM_BASE_URL/I3D_LLM_MODEL覆盖地址和模型。非回环地址必须HTTPS。
- `I3D_API_TOKEN`可保护本地操作者入口，所有业务调用带`Authorization: Bearer <本机配置值>`。不要把此值写进Git、前端源码或截图。未设置时仅按本地单操作者原型使用，默认绑定回环地址；本轮没有公网部署或多用户权限系统。
- `operator_name`来自服务端实际操作者配置；请求不能自填reviewer/origin或human_action。前端界面触发的确认由这些人工接口持久化，LLM没有确认/命令权限。
- `cors_origins`只列实际开发页面来源；默认样例为localhost:5173。runner执行图时关闭自动LangSmith追踪，未配置的追踪服务不会接收任务。

语言模型单次总时限最多60秒、自动重试0次、每任务最多4次/12000token。发送前按输入字节保守预留，供应商必须返回usage；未知用量保留null和未完成标记，禁止继续消耗额度。未配置单价时费用为null；配置的两项单价应采用同一币种/百万token，报告金额沿用该币种。原模型300秒、Blender120秒及任务累计活动900秒门槛保持；等待时间不计活动预算。每任务工具调用最多32次。

自然语言描述非空时会真实请求LLM解析；没有配置返回MODEL_NOT_CONFIGURED。描述为空时可走用户明确填写的结构化约束路径，报告标明LLM未配置/未调用。确定性待补字段提示不是语言模型回复。解析结果只作为建议展示，必须由用户接受，姿态仍须显式confirmed；LLM不确认图片、结构修改、底面或切片，也不判打印成功。

## 3.调用顺序与公共响应

所有ID、联合请求及字段定义见[运行时Schema](../schemas/runtime-v1.schema.json)；状态和检查枚举继续使用[公共定义](../src/image_to_3d_print/schemas)。普通任务查询仍返回ModelTaskResponse1.0.0，events仍为文字列表；新增运行时详情和事件页独立提供，不改变旧字段类型。

| 方法与路径 | 请求/响应 |
| --- | --- |
| GET /api/v1/configuration | 只返回已配置能力、模型名和限制，不返回密钥或执行路径 |
| GET /api/v1/printer-profiles | 服务端已登记的公共PrinterProfile |
| POST /api/v1/assets | multipart的file；返回合法AssetRecord，HTTP201 |
| POST /api/v1/model-tasks | 原ModelTaskRequest，或`{"request":公共请求,"backend":"triposr"}`；HTTP202快速返回queued |
| GET /api/v1/model-tasks/{run_id} | 公共ModelTaskResponse；查到queued不等于开始推理 |
| GET /api/v1/model-tasks/{run_id}/runtime | response、pending、resources；页面据pending.kind选择表单 |
| GET /api/v1/model-tasks/{run_id}/events?after=0&limit=100 | EventsPage；event_id严格递增，下一次传next_after；limit最多200 |
| POST /api/v1/model-tasks/{run_id}/inputs | 补约束、图片复核、打印复核、修复参数或结构确认 |
| POST /api/v1/model-tasks/{run_id}/slicer-confirmation | 专用SlicerInput，不能由其他输入种类代替 |
| POST /api/v1/model-tasks/{run_id}/cancel | 可重复；queued/waiting直接cancelled，运行中先cancel_requested再回收进程树 |
| GET /api/v1/model-tasks/{run_id}/artifacts/{artifact_id} | 仅下载该任务已登记文件；不接受路径，服务端日志不公开下载 |

创建可带`Idempotency-Key`请求头：同键同请求返回同run_id，同键不同内容返回409，键在当前存储中全局唯一。终态不恢复；重试创建新run_id。

HTTP422为非法内容，404为不存在的任务/引用，409为等待项、版本、提案或重复内容冲突。异步工具失败在任务ErrorInfo中返回，HTTP查询仍200，不能仅凭HTTP200显示任务成功。

上传示例（本机调用方使用自身凭据环境，示例不含凭据）：

```python
import httpx
with httpx.Client(base_url="http://127.0.0.1:8000") as client:
    with open("input.png", "rb") as image:
        asset = client.post("/api/v1/assets", files={"file": ("input.png", image, "image/png")}).json()
    created = client.post("/api/v1/model-tasks", json={
        "image_asset_id": asset["asset_id"], "printer_profile_id": "demo_v1"
    }).json()
    run_id = created["run_id"]
    details = client.get(f"/api/v1/model-tasks/{run_id}/runtime").json()
```

API只保存/排队；worker未启动时不会自行执行。页面应轮询真实状态，不在创建后立即假定pending已生成。

## 4.所有等待项的输入

公共状态始终为waiting_for_input；pending_input_type沿用公共枚举。精确表单使用运行时pending.kind：图片复核沿用replacement_image，打印复核沿用orientation，并由kind细分，不增加同义任务状态。每次输入必填submission_id、pending_input_id、kind及当时mesh_version（尚无网格为null）。submission_id采用合法Id，例如`s_`加UUID十六进制。

| pending.kind | 额外字段与行为 |
| --- | --- |
| constraints | height_value/height_unit/scale_source/scale_evidence_id/orientation；accept_suggestions仅接受已保存的LLM建议，不确认方向。允许分次补齐，仍缺项继续等待 |
| input_review | foreground_artifact_id、decision、complete_subject、simple_nonfunctional_ornament、foreground_correct。必须对应本次前景；拒绝或不确定结束，换图创建新任务 |
| print_review | preview_artifact_id、bed_confirmed、components_confirmed及component_count。关联当前版本；不确认底面停止交付 |
| repair_request | request为内部StructureRequest，或stop=true。只接受待补详情allowed_operations；先生成具体提案，不直接应用 |
| repair_confirmation | proposal_id、accepted。对应当前源网格和提案；拒绝后不应用，接受后独立confirm/apply节点创建新版本，再预览和检查 |
| slicer | 专用切片接口，字段见下一节 |

示例补尺度：

```json
{
  "submission_id": "s_example",
  "pending_input_id": "i_example",
  "mesh_version": null,
  "kind": "constraints",
  "height_value": 80,
  "height_unit": "mm",
  "scale_source": "user_target",
  "orientation": {"up_axis": "z", "confirmed": true}
}
```

上例等待ID是合法格式的说明占位，实际必须直接使用GET返回的真实ID。实测高度的scale_evidence_id引用已上传的测量图片资产，创建/补充时核对并登记本任务Measurement证据；不能只提交一个不存在的字符串。测量图片上传时可用purpose=measurement，文件检查仍与普通图片相同。

同一等待项相同内容重复提交返回当前结果，不重复排队/重建；不同内容或重复使用旧submission_id返回409。补充输入先返回queued，worker才消费检查点中的输入。不能把其他任务/旧网格/旧前景/旧提案的确认用于当前任务。

基础清理计第1轮修复，结构apply继续计轮数，总计最多2轮。超过50万面的当前网格会先请求受控简化提案，不能自动删面后假装原始检查通过。任何修复都不再次重建；原始版本保留。支持范围外的缺陷正确停止。

## 5.分层证据与最终交付

1. 当前版本检查通过、预览已人工复核、候选GLB/STL已独立重读后，任务等待slicer。
2. 操作者下载当前STL，在指定版本切片软件及已登记配置中复核尺寸、分层、底面和支撑。
3. 将真实分层PNG/JPEG上传至`POST /api/v1/assets?purpose=slicer_preview&run_id=实际任务UUID&mesh_version=当前版本`。响应含asset和artifact；确认时使用artifact.artifact_id，不能直接使用普通输入图asset_id冒充本版本分层。
4. 提交SlicerInput：kind=slicer，加公共等待/提交/网格ID、result、slicer_version、printer_profile_id、dimensions_mm、supports_enabled、layer_preview_asset_id、model_preview_confirmed、bed_confirmed、support_reviewed、notes。人工确认文件和confirmation_artifact_id由服务端生成，客户端不得自填。
5. pass必须同时满足预览/底面/支撑复核，软件/配置及尺寸匹配；悬垂warn要求实际启用并复核支撑。fail进入SLICER_VALIDATION_FAILED，保留现有网格、检查和候选文件。

只有公共ModelTaskResponse最终成功validator、同版本检查/预览/导出重读及切片证据全部满足才写succeeded。能下载STL、某个工具succeeded或JSON能解析均不代表任务成功。JSON/Markdown质量报告为quality_report产物，按每个等待切片/终态新增，包含来源、尺寸、操作、逐版检查、未解决项、资源、LLM用量与切片证据。

## 6.验证与交接

```powershell
python -m pytest tests -q --tb=short
python scripts/p1/export_schemas.py --check
python scripts/tools/export_tool_schemas.py --check
python scripts/tools/export_runtime_schemas.py --check
python scripts/p1/check_prepared_data.py
python scripts/tools/validate_backend.py --output runs/自选新的验证目录
```

最后一条启动真实本机HTTP与独立worker，但输入和确认是自动化fixture，只验证排队/等待/恢复/幂等/取消及退出，不发起重建或LLM调用。tests/workflow中的重建、Blender和LLM替身仅在测试内注入；CPU几何、LangGraph、SQLite及导出重读实际执行。真实LLM和云端完整模型联调需具备实际配置，当前证据状态见[交付报告](Agent工作流与后端交付.md)。

工作流持久化按[LangGraph官方中断说明](https://docs.langchain.com/oss/python/langgraph/interrupts)使用同一thread_id和Command(resume)，独立等待节点只含interrupt，重放不会触发重建。检查点数据库和任务数据库均在同一存储目录；原始产物不随报告覆盖。中断中的running任务重启后明确失败，不自动昂贵重跑。

## 7.已验证的AutoDL部署与DeepSeek

2026-10-21已在同一实例部署并验证，详见[云端验收报告](Agent云端部署与联调验收.md)。人工服务配置runtime/config/backend.json已生成，confirmation_origin=human；模型/工具解释器及路径见config/backend.autodl.example.json。自动化验证必须使用独立配置的test_fixture，任务报告/确认记录不得当人工；API能力查询也返回该来源标记，客户端不能覆盖服务端设置。

DeepSeek配置base_url=https://api.deepseek.com、model=deepseek-flash、thinking_mode=disabled；后者是显式可选供应商字段，默认None不向其他服务发送。仍使用严格JSON、公共约束、固定预算及0重试。密钥已通过用户文本配置，启动器只从云端权限600文本加载到I3D_LLM_API_KEY，不写配置JSON或回显。

当前API和worker已分别在screen的i3d-backend-api/i3d-backend-worker中空闲运行，不重复启动第二worker。需要停服务时进入对应screen，按Ctrl+C结束程序；重新启动可在两个云端终端分别执行：

```bash
cd /root/autodl-tmp/image-to-3d-print-agent/deployments/official-20261021-01
bash scripts/tools/start_cloud_backend.sh api
# 另一个终端，同目录执行：
bash scripts/tools/start_cloud_backend.sh worker
```

两进程使用同一持久存储，默认只监听127.0.0.1:8000；通过SSH隧道访问/docs或供前端连接，不修改AutoDL公网端口。关机后服务会停止，数据盘文件保留；再次启动后核对环境再启动上述两个进程，在途计算按原重启规则明确失败，不自动重跑。真实模型尚有打印缺陷，当前服务可供交互和失败路径演示，不能宣称已取得打印合格交付。

2026-10-21已切换为固定官方推理部署，默认input_review_policy=automatic，初始图片复核自动继续且语义标not_checked；其他确认保持。官方模型工具超时分别300/1200秒，任务活动上限1800秒。启动器明确加载当前部署src，旧backend目录保留但不作为当前启动目录。官方外观GLB与打印几何分别保存，见[本轮报告](官方推理对齐与自动图片准备.md)。历史验证器显式manual以复现原人工路径，不能把它们的自动fixture确认用于实际人工任务。
