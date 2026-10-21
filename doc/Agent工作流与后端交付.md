# Agent工作流与后端交付

日期：2026-10-21。范围为中期第6、25～40、49～51共20项；包0.3.0，运行时扩展runtime-v1。调用方从[启动与调用说明](Agent后端调用与启动说明.md)和[自动Schema](../schemas/runtime-v1.schema.json)接入。

## 1.本轮范围、基线和依赖

修改前HEAD951bfb5，工作区保留上一轮几何成果；不存在workflow/jobs/api/reports运行时。缺模块失败基线已实际保存（1失败），首轮公共契约回归57通过。工作期间几何方向提交0a32f1e落入本地，包含已写入的本轮任务规划；本轮接续该提交，没有回滚或重写其内容。

本轮授权一次完成本方向，覆盖旧“单个子项完成即停止”和“几何工具层后不实现Agent/API”的边界。实现按模块连接和验证，本轮交付止于后端；前端、整套云端部署、正式后端比较和保留集没有启动。历史P2-A、几何人工确认及具体提案/映射状态保持。

服务隔离环境为本机Windows/Python3.11.17，独立于已通过的两个模型环境。新增依赖用途见[当前任务](../spec/当前开发任务.md)及本报告；FastAPI0.115.12、uvicorn0.34.3、multipart0.0.20、httpx0.28.1、LangGraph0.6.7、checkpoint2.1.2/sqlite2.0.11及psutil7.0.0已实际安装，pip check通过。psutil用于回收含独立进程组的工具子树，不能只终止父runner。完整服务环境快照见[backend-windows.txt](../locks/backend-windows.txt)，不是Linux模型环境锁定。

## 2.20项实现矩阵

“固定验证”使用tests/workflow明确标注的重建/Blender/LLM替身；CPU网格清理、定标、结构提案/应用、导出读回、LangGraph、SQLite和HTTP实际执行。真实模型及供应商LLM证据独立列出，不用固定验证填充。

| 编号 | 实现与位置 | 实际验证及剩余依赖 |
| --- | --- | --- |
| 6 | workflow/llm.py严格JSON解析，建议字段只限公共约束，方向必须人工确认 | 解析建议不能自动设置confirmed，额外command/confirmed字段拒绝；HTTP供应商响应为测试替身，真实LLM未执行 |
| 25 | workflow/graph.py的真实StateGraph连接准备、确认、重建、清理、定标、检查、结构修复、导出、切片和报告 | 固定几何完整成功/失败/修复链通过；真实云端模型联调未执行 |
| 26 | LanguageModel显式地址、模型、环境密钥、超时、usage及费用 | 实际适配器+MockTransport、缺配置及超时测试；无配置返回MODEL_NOT_CONFIGURED，不存在固定回答兜底；真实供应商尚缺配置 |
| 27 | req.pending_inputs驱动高度、单位、尺度来源、方向追问，结合已保存LLM问题 | 缺4项不调用工具；允许分次补充；实测依据必须真实存在 |
| 28 | SqliteSaver持久化，同run_id作为thread_id，独立interrupt节点和Command(resume) | 新建服务/图实例接续、版本保持；恢复后重建次数为1 |
| 29 | repair_request→propose→interrupt→confirm→apply→preview/inspect | 同源网格与具体提案绑定；拒绝不应用，重复确认不生成第二版本 |
| 30 | MeshInspection.ready_for_print及公共成功validator决定分支；基础清理也计轮数 | 薄壁/检查未执行阻断，基础清理+结构修复共2轮后仍失败正确停止 |
| 31 | jobs/worker.py父进程监视、完整进程树回收、活动预算、重启失败 | 真实runner取消/超时/进程树/父worker强杀测试；重启保留结果，不重放LLM或重建；中断资源未知单列 |
| 32 | SQLite创建幂等键、提交ID及每等待项唯一约束 | 同内容返回现有结果；冲突409，已处理输入不会再次排队 |
| 33 | 公共响应/证据validator、工具产物引用校验、当前等待/前景/提案/网格核对 | 跨任务/旧版本/缺切片证据阻断；检查/预览/导出版本必须匹配当前网格 |
| 34 | 300/120/900秒工具/活动预算、32工具调用、4次/12000token与0自动重试 | 工具额度、token预留、4次上限、未知usage、供应商超时及实际runner超时通过；未知费用保持null |
| 35 | api/app.py全部既定REST端点，新增配置/打印配置/运行时详情 | TestClient及真实uvicorn/HTTP调用；422/404/409、创建202、下载范围及输入分支验证 |
| 36 | jobs/store.py的SQLite任务、事件、提交和公共响应，另有检查点数据库 | 服务重建后可查询接续；事件全局自增ID并按run过滤分页 |
| 37 | API快速保存排队，独立worker及每次执行runner，系统锁限制单worker | 本机两个任务顺序处理；第二worker锁拒绝；API不执行模型 |
| 38 | interrupt保存后runner退出，worker继续处理其他queued任务 | 两任务都进入等待且runner_pid为空，等待不累加活动秒数；本轮没有GPU，未填造显存数值 |
| 39 | AssetStore字节上传、服务端配置、受限下载、操作者确认入口 | 伪格式/坏图/越界路径/命令字段/跨版本/未注册引用拒绝；配置响应无凭据与执行路径，日志不公开下载 |
| 40 | jobs/config.py、api/__main__.py、jobs/worker.py及配置样例 | 本机两个实际进程启动/退出通过；真实Linux模型/Blender使用已有工具配置，未重装/下载 |
| 49 | reports/quality.py新增JSON/Markdown，等待切片和终态分别保存 | 来源、尺度、操作参数、逐版检查、未解决问题、导出读回、资源/LLM/切片及证据关联可读取；测试报告标test_fixture |
| 50 | SlicerInput、指定任务/网格的分层图片上传、服务端生成确认产物 | 缺图拒绝；软件/配置/尺寸及预览/底面/支撑核对；失败SLICER_VALIDATION_FAILED。自动化确认不算人工切片验收 |
| 51 | 检查、预览人工输入、独立读回及同版本切片记录齐全后写succeeded | 固定链通过公共最终校验；真实摆件完整成功交付未取得，不把STL可导出当作成功 |

## 3.实际验证记录

全量最终186 passed、5 skipped、2 warnings，45.10秒；其中工作流后端32项全部通过。两个warning是依赖库弃用提示。逐项测试摘要见[精简证据](agent-evidence/validation.json)。原始命令/日志/数据库/报告在被忽略的runs/mid-agent-20261021-01，不将运行数据库、完整模型、权重、环境或凭据入库。

实际执行命令（均在独立backend环境）：

```text
python -m pytest tests -q --tb=short --junitxml=runs/mid-agent-20261021-01/tests.xml
python scripts/p1/export_schemas.py --check
python scripts/tools/export_tool_schemas.py --check
python scripts/tools/export_runtime_schemas.py --check
python scripts/p1/check_prepared_data.py
python -m pip check
python scripts/tools/validate_backend.py --output runs/mid-agent-20261021-01/http-smoke-01
```

本机真实HTTP与worker验证为17.578秒：两任务顺序进入缺尺度等待，其中一条补尺度并重复提交后到前景复核；随后取消并退出服务。创建请求各自快速返回202，具体秒数见精简证据。只使用本机回环和固定图片，没有GPU重建、真实LLM、实际切片或人工批准。

故障及修订：历史离线保护拦截服务导入/Windows事件循环；超大测试参数ID超过Windows环境变量上限；worker强杀后活动区间/供应商用量不完整；已提交工具源码的Schema快照漏项。各自保存失败后修订，见AGENT-BUG-001～004。第三项真实父进程强杀基线已确认runner自行退出及不重放，新增未知资源断言实际失败后才修正。第四项仅按原有导出脚本同步preview/measure_view/组件复核/映射定义，不改工具实现或公共Schema。

公共20模型及JSONSchema1.0.0保持；运行时Schema独立导出，不手改生成文件。数据/测量协议/质量门槛保持，30例只做静态准备核验；evaluation/holdout模型执行仍未运行。平台跳过仅为Linux进程组4例及本机无权限建立符号链接1例；对应历史Linux结果不冒充本轮Windows复测。

## 4.未执行项与人工复核

- 本机未检测到已配置的供应商LLM；已向用户请求地址、模型名和保存密钥的环境变量名，未要求在聊天发送密钥。真实理解/追问/解释调用及其实际费用保持not_run，不能用MockTransport记录替代。
- 本轮没有连接实例、执行GPU、重建模型或重新安装已通过环境。现有真实几何成果可供后续配置接入，但不是本轮Agent云端全链验证；之前全部真实模型仍有打印缺陷，不改成成功。
- 没有前端页面、真实分层确认、物理打印或主后端选型结论；本方向接口已可交给前端成员。中期完整原型仍需其本次真实用户路径证据。
- 新增主要代码及结果尚待组员人工阅读，重点核对graph.py的独立等待节点、service.py的确认事务、worker.py/runner.py的取消重启、quality.py及公共最终成功门槛。AI自查和自动化fixture不记人工通过。

## 5.交接与停止

先读[调用说明](Agent后端调用与启动说明.md)，按实际机器填写配置，保持同一存储目录及单worker。前端使用公共任务状态和运行时pending.kind，不能自建状态或以计时器推进；模型适配、结构提案与打印证据按现有几何门面接入。

本轮20项实现、固定回归及本机HTTP/worker证据交付后停止；真实LLM/云端全链依赖保持明确，不在缺配置时编造完成。Git同步与人工验收分别记录，不因此启动前端、云端部署、正式比较或最终批量评估。
