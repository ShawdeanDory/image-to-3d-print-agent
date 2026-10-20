# 固定数据与实验设计v1.0.0

P1只准备并静态检查数据，30个任务的模型结果全部为`not_run`。本目录没有训练脚本、模型安装或评估执行器。[数据清单](dataset_v1.json)由公共`DatasetManifest`校验；[协议清单](protocol_v1.json)是实验配置，详细测量规则以[评估设计](../doc/评估设计.md)为准。

## 数据划分

| 划分 | case_id | 数量 | 用途 |
| --- | --- | --- | --- |
| development | dev_n01～06、dev_b01～04 | 6正常+4边界 | 开发与提示/规则调整；两张已见P0图片仅在这里 |
| evaluation | eval_n01～06、eval_b01～04 | 6正常+4边界 | P2-B同机模型比较、后续回归 |
| holdout | hold_n01～06、hold_b01～04 | 6正常+4边界 | P7冻结后首次完整执行；P1只检查格式与引用 |

按`object_group`隔离：同一物体的背景/遮挡/缺字段变体保持同一划分。16个对象为项目自产CPU渲染，另2个沿用P0授权样例；这是受控教学集，不能据此声称自然图片泛化。许可和生成信息见[fixture说明](../fixtures/p1/README.md)。

正常任务中的80毫米是固定测试目标，不是对输入物体的实际测量；打印配置是演示配置。所有参考网格字段当前为null，Chamfer未测。几何缺陷集独立于30个任务，见[12个几何fixture](../fixtures/p1/geometry/manifest.json)。

## 四类实验

| 类型 | 首次执行阶段 | 固定项与变化项 | 阶段验收 |
| --- | --- | --- | --- |
| official_inference | P2-A | 锁定官方源码/子模块、权重revision、环境、输入、参数、种子；官方默认与低显存变体分开 | TripoSR两张P0输入2/2可独立读回，新候选至少1张官方样例有效；保留原始输出及失败。只称官方推理复现 |
| model_comparison | P2-B | 同一GPU/配额、6个evaluation正常输入与4个边界、前景口径和检查版本；只变后端 | 6个正常输入成对记录，10例均在清单内；按有效网格、已实现质量项、时间/资源和失败解释选型；未实现项not_run，证据不足则待定 |
| repair_comparison | P3 | 同一原始网格、后端、定标、打印配置与检查器；比较原始/基础修复/单项修订 | 12个已知几何fixture分别验证；最多2轮，结构修改有确认；IoU下降超过0.05须说明并确认 |
| workflow_comparison | P4 | 同一后端、输入与几何工具；变化为固定流程/小组自主Agent | 正常、缺尺度恢复、阻断缺陷3类轨迹；超时、取消、上限正确停止；恢复重复重建0次，至少1次真实LLM交互 |

每条实际记录使用`ExperimentRecord`，配对双方以相同`comparison_group_id`关联，修订记录引用`baseline_run_id`并说明`changed_factor`。不删除失败输入；正常成功率和边界正确处理率分别计算。完整验收门槛仍引用主评估文档，不能用某一阶段的有效网格代替最终可打印判定。

## 资源和停止

- P1实际预算：单次离线检查120秒、CPU样例准备10分钟；不使用GPU或模型API。
- [P2-A预算草稿](budgets/p2a_draft.json)保留未确认的null值，`require_ready()`明确拒绝执行。P1交付预算字段和前置检查；实际时间/费用上限及CPU/内存配额由P2-A启动任务确认，本轮不替用户承诺费用。
- 实际推理失败、超时、显存不足和预算耗尽都保留记录；不静默改参数、切换机器/模型或无限重试。
- P7先冻结代码、依赖、权重、配置和协议，再记录`release_frozen=true`与`release_ref`；未冻结的保留集实际执行记录校验失败。

## 本机静态检查

在项目根目录、已准备的CPU契约环境运行：

```powershell
& runtime/envs/contracts/Scripts/python.exe -m pytest tests/unit tests/contract -q
& runtime/envs/contracts/Scripts/python.exe scripts/p1/export_schemas.py --check
& runtime/envs/contracts/Scripts/python.exe scripts/p1/check_prepared_data.py
```

以上命令不运行任何模型、几何质量检查或正式保留集评估。后续实际环境准备、推理和下载命令由P2-A运行成功后形成runbook，P1不编造已验证的云端安装命令。
