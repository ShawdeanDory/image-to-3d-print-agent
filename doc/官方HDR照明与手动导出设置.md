# 官方HDR照明与手动导出设置

日期：2026-10-22；任务MID-EXPORT-001；基线5a2b876。代码、静态检查、前端发布构建和同一云端服务更新已完成；按用户要求不运行自动测试、模型生成、真实烘焙或浏览器验证。实际效果、速度及新增人工复核待用户网页反馈，上一轮PBR未测项也未改为通过。

## 1.网页使用

Ctrl+F5刷新网页后点击“新建任务”。上传图片，填写原有高度等参数，新增两个可选输入：

| 输入 | 留空 | 手动范围 | 示例 |
| --- | --- | --- | --- |
| 导出目标面数 | 按图片复杂度估计10000/30000/100000 | 整数100～1000000 | 1000000 |
| 方形纹理边长（像素） | 2048×2048 | 整数256～4096，宽高相同 | 填4096表示4096×4096 |

纹理分辨率仅用于TRELLIS.2的PBR导出；TripoSR当前提供顶点色，网页禁用该项，直接API对TripoSR指定纹理大小会明确拒绝。手动面数适用于两个后端；只控制减面预算，不给已有低面数网格补造细节。默认TRELLIS.2生成阶段仍以100000面为后处理输入，随后自动选择预算；手动时生成导出和后处理使用同一目标，不再被固定10万或自动1万覆盖。贴图清晰度不能修复没有生成的结构。

提交一次后由后台继续检查及最多2次受控结构尝试，完成后点击按钮下载GLB。新选项不增加中途操作。原始文件、网格版本及打印检查保持；打印不通过/工具未执行仍如实展示。

目标是预算，不保证实际恰好等于填写面数；候选未过保形/缺陷门槛会保留较好的有效版本，并记录实际面数和未达目标原因。手动目标失败不擅自改成另一个更低目标；自动预算仍可在原1万→3万→10万之间有界回退。更高面数/4K会增加内存、文件和耗时，未实测本轮速度。PBR重烘焙沿用既有单次120秒限制，超时会明确回退顶点底色，不能冒称已完成4K/PBR。

旧任务及已下载GLB不重写；手动参数只影响新任务，网页HDR照明对当前显示的任意版本生效，不改文件内部颜色或几何。

## 2.展示照明

网页直接加载固定官方[example.py](https://github.com/microsoft/TRELLIS.2/blob/75fbf0183001ed9876c8dbb35de6b68552ee08bd/example.py)使用的forest.exr，经Three.js的EXRLoader/PMREM提供PBR环境照明，强度1；移除RoomEnvironment、半球灯与定向灯。资源从本地前端发布目录加载，不依赖用户浏览时访问国外网站；加载失败显示错误，不偷偷回退其他环境。

HDR原作者GregZaal/PolyHaven，原图[ninomaru_teien](https://polyhaven.com/a/ninomaru_teien)，许可CC0；上游许可原文与MIT许可一并放在[环境资源目录](../frontend/public/environment/README.md)。来源和文件摘要见[静态记录](evidence/export-options-20261022/implementation.json)。资源本身为上游压缩后的1K环境图，与用户模型2K/4K材质分辨率是两回事。

预览继续显式转换网格Z/Y朝向，环境查找矩阵补偿官方经度零点和网页Y朝上；曝光1，使用Three.js的ACESFilmic/sRGB。官方CUDA渲染器使用自己的ACES近似、gamma2.2和SSAO，网页不是该渲染器移植。**本轮对齐同一HDR和PBR照明路径，不声称像素完全相同**；方向、明暗和材质效果待用户实际确认。HDR不会写入GLB，其他软件打开GLB时使用其自身环境照明。

## 3.契约与实现

CreateTask兼容增加export_target_faces、texture_size，可省略/null；严格整数校验，布尔、字符串、小数及越界拒绝。两项定义见[export_options.py](../src/image_to_3d_print/export_options.py)。未设置的新增字段不计入旧幂等摘要；公共1.0.0/generation-v1保持。仅新automatic_glb支持这些设置，旧guided不静默迁移。

- [service.py](../src/image_to_3d_print/jobs/service.py)保存export_options；[工具门面](../src/image_to_3d_print/geometry/commands.py)/[适配器](../src/image_to_3d_print/adapters/reconstruction.py)向任务独立模型进程传递参数，不修改公共环境配置。
- [model_worker.py](../scripts/tools/model_worker.py)仅改变固定模型的to_glb导出预算/贴图大小；seed42、1024_cascade、权重及无转台策略保持，不修改历史official入口。model.json.parameters记录实际使用值和来源。
- [automatic.py](../src/image_to_3d_print/workflow/automatic.py)保留复杂度原始target_faces，另外保存requested_target_faces/effective_target_faces/selection_source；使用有效预算减面并报告实际面数，不再次落入固定10万简化。结构请求上限同步1000000，保形检查和2次上限保持。
- 上轮[PBR实现](处理模型PBR外观说明.md)通过原GLB的model.json登记纹理边长，最终重烘焙继续使用同一大小；失败/缺源保持明确降级，页面显示实际成功纹理大小。
- [ModelView.tsx](../frontend/src/ModelView.tsx)加载官方EXR并保留GLTF材质；[App.tsx](../frontend/src/App.tsx)提供可空输入，[预算](../frontend/src/MeshBudgetInfo.tsx)/[外观](../frontend/src/MaterialInfo.tsx)分别展示请求、实际与回退。运行时与内部Schema、前端类型由原脚本重新导出。

API示例（其余原有request参数省略）：

```json
{"request":{"image_asset_id":"本次注册图片及其他必需字段"},"backend":"trellis2_candidate","export_target_faces":1000000,"texture_size":4096}
```

上例说明增量字段，request须仍符合公共ModelTaskRequest，不能将省略示例直接作为完整请求。

## 4.实际执行与发布

- 10份改动Python静态AST解析完成；未执行pytest、模型/LLM、烘焙或浏览器用例。
- 执行原有export_runtime_schemas.py、export_tool_schemas.py、export_frontend_types.py重新导出机器契约与类型。
- `cd frontend`后`npm run build`退出0，含TypeScript静态检查；45模块、JS868.60kB，保留既有大包提示。构建不是业务/效果验收。首次收尾脚本错误使用frontend作为工作目录却拼了frontend/src，FileNotFoundError后在仓库根目录修正；未写错误位置，修正后重新构建。
- 只读SSH确认同部署无运行/排队任务，18个旧任务；逐项核对5a2b876源码基线，备份原代码/配置/两份SQLite后更新12个明确后端/Schema文件，恢复同一API/单worker，仅GET配置核对export-options-v1、1000000/4096和official-forest-hdr-v1；18个旧任务状态保持。未提交生成任务、不代关机。
- [发布记录](evidence/export-options-20261022/deployment.json)；云端私有备份runs/export-options-20261022-01。前端资源已随本机dist发布，现有5173与启动器入口保持。

## 5.未测项与停止点

以下均未执行：空值默认及边界的运行时回归、100万/4K真实生成与最终重烘焙、性能/显存、手动目标保形拒绝、HDR浏览器加载/方向/曝光、取消/恢复、下载重读和新增人工复核。没有填成功率、实际面数/时间或PBR覆盖率。保留集、多图、第三模型、训练、PPT/PDF仍暂缓。

代码/发布交接完成后停止。用户可先新建TRELLIS.2任务填写1000000/4096观察，再根据实际结果反馈；本轮AI不主动运行该任务，不代填人工通过或打印合格。
