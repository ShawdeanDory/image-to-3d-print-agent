# 修复版GLB交付与验证

- 日期：2026-10-29；任务：MID-DELIVERY-002；修改前版本：84c7a98。
- 本轮用户已授权实现、验证、同一云端更新及提交推送。2026-10-25暂停后，2026-10-29明确恢复；原暂停日志保留。
- 技术交付完成；2026-10-29用户明确“已核对，本轮人工复核通过”。本轮没有新模型推理、LLM调用、重烘焙、安装或开关机。

## 1.这次改变什么

新任务一次提交图片及参数后，使用已有TRELLIS.2常驻路径重建，在保留原件的副本上清理、毫米定标、检查并做最多2轮受控修复，最后交付检查较好的有效GLB。预览和主下载严格使用服务端`delivery.artifact_id`与`mesh_version`，不再从文件顺序中选原件。

保留已有UV、PBR材质、嵌入贴图字节，不做二次烘焙。新增补片没有原始纹理依据，会单独标记和说明。复杂非流形、自交、语义缺失等仍可能无法自动修好；无法安全修复可提前停止，有效GLB仍交付，失败和未执行项目不改为通过。没有有效GLB则任务失败。

完成和刷新都不自动下载，用户点击“下载GLB”才保存。原始GLB在“本任务文件”保留次级下载入口。

## 2.契约、兼容和实现

| 位置 | 本轮行为 |
| --- | --- |
| `jobs/service.py` | 新自动任务保存内部`repaired-glb-v1`；先匹配旧幂等键，旧快照不迁移 |
| `workflow/automatic.py` | 沿已有检查/修复/最佳版本分支导出GLB；自动与手动预算送首次生成；GPU补片计入总计2轮；失败原因写交付说明 |
| `artifacts/export.py`、`artifacts/pbr.py` | 同版本毫米几何独立读回、UV/PBR保留、无纹理补片说明；不改原件 |
| `reports/quality.py` | 报告对应交付版本，保留历史原件任务语义；保材质不再误称顶点底色 |
| `frontend/src/domain.ts`、`App.tsx` | 按交付ID/版本校验主模型，缺失或不匹配停止预览/主下载；尺寸、报告、修复轮数和文件说明一致 |
| `scripts/tools/verify_repaired_delivery.py` | 明确复用已有生成模型，在生产存储外回放真实CPU/Blender链，禁止覆盖已有输出，不调用重建模型或LLM |

公共Pydantic定义与生成Schema不变，复用现有`GenerationTaskResponse/generation-v1`和`GenerationDelivery`；内部策略不是新增HTTP字段。交付与检查、状态、质量报告绑定同一网格，`print_certified=false`。GLB显示坐标按glTF采用米/Y朝上，逻辑检查与尺寸报告为毫米/Z朝上，读回仅转换一次。

旧`original-glb-v1`任务仍按原快照交付原件，原件打印状态`not_run`，副本检查单列。没有静默重写旧报告或人工验收。常驻模型、固定源码/权重、预处理和low_vram策略均保持，服务重启后的首张需要冷加载。

## 3.固定回归与11项失败

修改前完整工作流52通过/11失败，用时65.20秒。10项在`export_original_glb`处因fixture没有原始GLB来源而失败，1项HTTP测试期待`generation-v1`。本轮按新交付要求接通实际处理版分支，没有删除来源校验或把断言改成原件来清零。

新增带UV接缝/PBR立方体、可补孔、原件摘要、旧快照幂等、自动/手动面数与4K参数传递；已有薄壁、无改善2轮、缺检查器、导出失败、跨任务、取消/超时/重启等继续验证。导出缺失测试现在确认确实调用了`export_glb`；两轮无改善确认交付较早的最佳版本。模型/Blender替身只在测试目录使用，不能作为真实推理或打印证据。

| 检查 | 实际结果 |
| --- | --- |
| 本机完整离线，显式`pytest tests` | 281通过/11个平台条件跳过，98.58秒 |
| 云端Linux完整离线 | 292通过，59.74秒 |
| 收尾单位/补片说明补丁相关回归 | 本机22通过，Linux22通过 |
| 前端Vitest | 7通过 |
| TypeScript/Vite | 构建完成，46模块；保留既有JS大包提示 |
| Edge浏览器/API/CPU固定路径 | 2通过，14.1秒；一次创建、无中途确认、真实交付ID预览/下载、刷新恢复、0次自动下载/点击后1次下载 |

实际命令：

```powershell
$env:PYTHONUTF8='1'
runtime/envs/backend/Scripts/python.exe -m pytest tests -q
runtime/envs/backend/Scripts/python.exe -m pytest tests/workflow/test_repaired_delivery.py tests/workflow/test_automatic_generation.py -q
cd frontend
npm test -- --reporter=dot
npm run build
# 使用8011隔离fixture服务和5183测试页面；不能指向生产提交测试图片。
$env:I3D_UI_URL='http://127.0.0.1:5183'
$env:I3D_BROWSER_EVIDENCE_DIR='C:/Users/Lenovo/Desktop/大数据实训/runs/repaired-delivery-20261025-01/browser-final'
npx playwright test tests/fast-profile.spec.ts
```

首次失败保留：新增后端2失败/1通过、前端6通过/1失败；TypeScript可空warnings访问；Linux验证包漏配置导致291通过/1失败；浏览器缺轮数说明导致1通过/1失败。补齐原资料和实际字段展示后再验证，不改业务门槛。默认不带`tests`的pytest只运行契约集，不当成全套。

## 4.云端已有真实模型回放

在同一实例的独立存储中，复用历史任务`63326f65-f3fb-4631-85bf-14fd497643c1`的已生成GLB及输入，实际运行清理→100mm定标→Blender4.5.14/锁定Toolbox检查→受控修复→最佳版本导出与HTTP读取。

- 回放任务：`1d88ad9d-f85f-4af0-8c35-7baab52ea0cd`，只存在隔离验证存储，没有加入生产33任务。
- 39.738秒，最终95877面，外形约148.337×80.700×100.000mm。
- 交付与检查网格：`m_df5dea5339d048a3974c7a17`；原始文件SHA256、已有UV、PBR材质/纹理/采样器和嵌入图像摘要保持，未烘焙，HTTP文件与最终文件字节一致。
- 实际1轮小孔补洞尝试因“边界不是简单闭环”拒绝，未制造补片。80条边界边、172条非流形边、344个非流形顶点、6个自交面仍存在，薄壁未执行，底面接触失败，20组件为风险；打印状态`failed`，不是打印合格。
- 原始GPU补片记录作为历史来源保留；本次新模型调用0、LLM调用0，不把复用登记称为新图片推理或性能改进测量。
- 第一轮隔离目录漏锁文件，返回检查`not_run`；验证脚本拒绝通过。补齐原锁定清单后另建目录重跑，首轮文件保留。

Linux回放命令（从含`src/scripts/locks`的验证代码目录执行）：

```bash
CUDA_VISIBLE_DEVICES='' PYTHONPATH=src /root/autodl-tmp/image-to-3d-print-agent/runtime/envs/backend/bin/python \
  scripts/tools/verify_repaired_delivery.py \
  --config /root/autodl-tmp/image-to-3d-print-agent/runtime/config/backend.json \
  --source-run 63326f65-f3fb-4631-85bf-14fd497643c1 \
  --output /root/autodl-tmp/image-to-3d-print-agent/runs/repaired-delivery-20261029-01/replay-final
```

输出目录已存在时该脚本会拒绝，复现须另取新目录。原件和回放各版文件均保留。

## 5.发布、资源与证据

同一`official-20261021-01`部署先核对无活动/排队任务、API和worker停止，再备份6份源码、配置及SQLite快照，发布6文件。前后逐任务上下文/响应摘要及状态核对：33任务完全保持；常驻模块源码与`execution_mode=resident`配置未改。

已启动API、1个worker及其1个懒加载模型监听。GET配置为`repaired-glb-v1`、新任务仅TRELLIS.2；旧任务响应仍`original-glb-v1`。结束查询GPU0MiB/0%，未提交生产任务。没有自行关机；实例仍由用户处理。

本机网页构建已更新，原项目exe继续启动本机页面/隧道，浏览器刷新后新任务采用新交付规则。历史任务不会自动变为修复版；队友旧ZIP内嵌的是旧页面，需要更新前端构建，不能以旧包判断新界面。

- 精简实证：[result.json](evidence/repaired-delivery-20261029/result.json)。
- 本机详细日志/录屏/源码发布清单/云端备份：`runs/repaired-delivery-20261025-01/`；完整网格、数据库及备份不入Git。云端备份118785580字节/67项，本机完整读取且SHA256与云端相同。
- 未执行：新的真实图片GPU全链、所有大孔/非流形自动修好、实际切片/打印、最终保留集、PPT/PDF。历史冷热性能不充作本轮重新测量。

## 6.本轮人工复核

状态：2026-10-29用户通过本轮复核请求明确回复“已核对，本轮人工复核通过”，据此记录本轮代码/结果人工复核通过；不补写未实际展开的逐行阅读，不覆盖历史待人工或打印结论。

1. 阅读本报告第1～5节，确认交付版和原始文件的区别、打印失败仍可下载有效GLB、最多2轮并可安全提前停止。
2. 核对主要代码：`jobs/service.py`、`workflow/automatic.py`、`artifacts/export.py`、`artifacts/pbr.py`、`reports/quality.py`、`frontend/src/domain.ts`与`App.tsx`，确认未重烘焙、旧快照保持、主产物绑定ID与版本。
3. 核对精简实证和浏览器截图/录屏，确认最终文件与检查版本及尺寸对应，完成/刷新不下载，按钮才下载，原件另存。
4. 核对本报告明确保留的真实缺陷及未执行项，不把本轮通过理解为实际模型打印合格。

收到用户明确结论后按其原话记录，不引用上一轮人工通过代填本轮。未复核时仍按已有授权提交推送，并保持人工待验收。
