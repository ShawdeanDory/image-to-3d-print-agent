# 原始GLB直接交付说明

日期：2026-10-22；任务MID-ORIGINAL-001；代码基线8f0975b。用户要求停用重烘焙、网页只输出原始PBR，并取回刚生成的文件。本轮延续用户自行网页测试，不运行自动测试、模型生成、烘焙或浏览器用例；实现与实际网页验收分别记录。

## 1.现在交付什么

刷新网页后，只显示本任务真实原始GLB并提供“下载原始GLB”按钮，不再提供处理网格/版本对比。原UV、贴图、材质和文件字节保持；没有原始GLB就显示缺失，不用处理版冒充。TripoSR原始GLB实际使用顶点色，页面不伪称它有PBR纹理。

“原始”指重建后端第一次导出的可用GLB。TRELLIS.2自身为生成该文件所需的重网格/UV/纹理导出保持，取消的是项目后处理对它的第二次UV展开和重烘焙。手动面数最高1000000、纹理最高4096方形、默认2048保持；留空自动面数时，新任务把已分析的自动目标直接传给TRELLIS.2第一次导出，不再依赖处理版来体现面数目标。目标预算与实际面数分别记录，未达目标保留真实原件。

后台仍按既有流程在独立几何副本上清理、定标、逐项检查与最多2次受控结构尝试，保留记录；**这些变化不写回原始GLB。**因此原始下载文件未应用用户填写的目标高度/朝向或副本修复；表单明确标为检查副本参数，页面尺寸/打印表也注明属于副本，不能用其结论认证原始文件。

完成、刷新和恢复都不自动下载，点击按钮才下载。旧任务数据/已下载文件保持；网页对旧任务也只选择其已经登记的原始GLB，隐藏旧处理版，不重算历史结果或补填人工通过。报告/输入图片等非模型资料仍可查看。

## 2.为什么增加独立响应版本

旧generation-v1要求交付网格等于毫米检查版本，直接把原始文件塞进该字段会误导。新任务以original-glb-v1返回OriginalGLBTaskResponse，原始交付模型由公共Pydantic来源自动导出，公共1.0.0及旧generation-v1保持。

- delivery.mesh_version、artifact_id：原始网格及其真实GLB。
- delivery.inspection_mesh_version：实际检查副本，与data.state.mesh_version、data.inspection及质量报告关联。
- source_sha256、original_unchanged=true、target_scale_applied=false、independent_readback=true：原始文件归属/摘要/只读读回。
- print_check固定not_run、print_certified固定false：不能套用副本检查给原件；inspection_print_check单列副本实际结论。
- repair_attempts：副本的受控尝试次数；无自动切片确认。新字段不重写旧持久化响应或请求幂等摘要。

运行时配置appearance_policy=original-glb-v1。新任务创建时持久化delivery_policy；原guided与旧generation任务保留快照。已关闭PBR调用路径：write_processed_glb不再调用Blender烘焙，底层pbr_export明确拒绝。旧独立处理导出若被调用，仅保留实际顶点底色，网页不展示/下载它。

## 3.实现位置

- [export.py](../src/image_to_3d_print/artifacts/export.py)：export_original_glb定位同任务版本链根记录，校验路径/摘要，独立读取GLB，登记原文件而不重新写出；缺源/坏文件明确失败。
- [runtime_contracts.py](../src/image_to_3d_print/runtime_contracts.py)、[state.py](../src/image_to_3d_print/workflow/state.py)、[service.py](../src/image_to_3d_print/jobs/service.py)：独立交付契约、任务快照、旧响应兼容。
- [automatic.py](../src/image_to_3d_print/workflow/automatic.py)：副本处理与原始交付分别绑定；面数记录使用实际原文件面数，另存inspection_actual_faces，不用副本减面结果当原件结果。
- [pbr.py](../src/image_to_3d_print/artifacts/pbr.py)、[blender_worker.py](../scripts/tools/blender_worker.py)：停止重烘焙；原始来源登记保留。
- [App.tsx](../frontend/src/App.tsx)：仅选择同任务raw_mesh的GLB，去重、预览和按钮下载；原始与副本说明同步。[预算](../frontend/src/MeshBudgetInfo.tsx)区分旧副本统计和新原件面数，旧记录不改写。
- [接口](接口与字段.md)/[架构](架构设计.md)维护字段与模块权威定义，Schema/前端类型由原导出脚本重新生成。

## 4.已取回的实际文件

用户刚完成任务e524638a-f707-4cb3-9be2-3bc85b1d334e的原始GLB已下载到本机runs/downloads/trellis2-e524638a/TRELLIS2_e524638a_original.glb，共68998464字节；文件头/声明长度与远端长度一致。文件不入Git，精简取回记录见[implementation.json](evidence/original-glb-20261022/implementation.json)。此前01504c4c原件也仍在本机原下载目录，不覆盖。

这只是读取/取回已经存在的用户产物，不运行新生成或用它替代本次代码验收；没有修改原文件或代填打印通过。开始准备部署时另有用户任务运行，本轮不取消、不修改执行中的代码，待空闲后备份更新。

## 5.实际检查与发布状态

已完成11份改动Python的静态AST解析；执行export_runtime_schemas.py、export_tool_schemas.py、export_frontend_types.py导出定义与类型。`cd frontend`后`npm run build`退出0，含TypeScript静态检查：45模块、JS867.63kB，保留原大包提示。未运行pytest、模型/LLM、烘焙或浏览器验证，构建不等于业务通过。

云端有用户任务时未停止服务或覆盖运行代码。任务进入终态、确认无运行/排队项后逐文件核对8f0975b基线，备份原代码/配置/两份SQLite，更新13个明确后端/Schema/工具文件，恢复同一API/单worker。仅GET配置确认appearance_policy=original-glb-v1；21旧任务状态保持，未创建生成或LLM任务、不代关机。现有5173前端发布构建及启动器路径保持。

[发布记录](evidence/original-glb-20261022/deployment.json)；原服务/SQLite备份在云端runs/original-glb-20261022-01，不提交完整产物、环境或凭据。

## 6.待用户验证与停止点

待验证：新任务原始预览/按钮下载、文件摘要不变、缺源/坏摘要/跨任务拒绝、原始/副本版本与报告、自动/手动目标、旧任务/幂等/取消/恢复及新增人工复核；均未执行，不以旧测试或代码阅读代填通过。对当前效果的评价仍以用户实际反馈为准；本轮没有再改照明。

实现/静态构建、空闲发布、文件取回及授权Git同步后停止，不自行提交生成任务或开关机，不扩展多图、第三模型、PPT/PDF或保留集。
