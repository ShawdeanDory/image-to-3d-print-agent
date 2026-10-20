# 2D图像到3D打印模型Agent工作流

大数据实训课程P05。第一版面向简单摆件，将单张物体图片转换为经过受限修复、尺寸校准、打印检查和人工切片确认的STL，并提供GLB预览与质量报告。

## 当前进度

**P1已完成：57项离线测试通过，2026-10-20用户明确确认人工阶段验收通过。**实际导读范围见人工复核记录，其他条目未逐项导读；当前保留P1已完成，下一项只保留P2-A。本轮停止，不进入P2，不安装模型；P1只使用本机CPU，云端GPU可以关机。

已交付20个公共Pydantic契约及自动JSONSchema，30例固定任务、12个几何fixture，以及官方推理、同机模型、修复和Agent工作流四类实验设计。模型质量、IoU/Chamfer、正式保留集和新云端模型均未执行。数据以受控合成输入为主，不能据契约测试通过声称自然图片生成或打印合格。

- [P1验收报告](doc/P1契约与实验设计验收.md)：实际命令、基线、57项测试、限制与停止点。
- [P1人工复核清单](doc/P1人工复核清单.md)：原清单及本轮实际导读范围、用户明确验收结论。
- [当前任务P1](spec/当前开发任务.md)、[下一任务P2-A](spec/未来规划.md)：唯一当前/下一阶段及启动条件。

## 运行P1离线检查

环境安装与精确版本见[CPU环境交接](locks/README.md#p1本机cpu契约环境)，无需安装torch或重建模型。已准备本机环境后，在根目录PowerShell运行：

```powershell
& runtime/envs/contracts/Scripts/python.exe -m pytest tests/unit tests/contract -q
& runtime/envs/contracts/Scripts/python.exe scripts/p1/export_schemas.py --check
& runtime/envs/contracts/Scripts/python.exe scripts/p1/check_prepared_data.py
```

[公共契约](src/image_to_3d_print/schemas/__init__.py)是唯一可执行定义，[JSONSchema](schemas/contracts-v1.schema.json)是导出文件；[数据与协议](evals/README.md)、[fixture来源](fixtures/p1/README.md)明确区分预期与实测。HTTP服务、重建适配器、Agent运行时、前端及完整流程尚未实现；小组自己的Agent主要在P4制作。

## 本机原始模型试用

双击[双击生成3D模型.cmd](双击生成3D模型.cmd)选PNG/JPEG，复用既有P0环境生成原始GLB并用Blender查看。[试用说明](doc/本机双击试用说明.md)包含结果和日志位置。该入口属于历史LOCAL-001，需要本机既有模型/GPU环境，与P1离线检查分开；输出未经完整定标、修复和打印确认。

P0已于2026-10-18完成本机技术及用户人工验收，两张图片、已知几何和演示切片真实通过；[历史报告](doc/P0环境与工具验证.md)和[历史任务](spec/P0历史任务记录.md)保持。小组没有打印机，物理打印未验证。

## 工作与长期记录

- [工作前必读约定](工作前必读约定.md)、[AGENTS.md](AGENTS.md)：每轮先读，按9步流程、阶段边界、真实证据和人工复核推进。
- [已完成任务](spec/已完成任务.md)、[Bug记录](spec/bug调试文档.md)：P1已按用户明确的阶段验收结论归档，实际导读范围单独记录。
- [架构设计](doc/架构设计.md)、[接口与字段](doc/接口与字段.md)：模块和契约的权威说明。
- [评估设计与记录](doc/评估设计.md)、[AI协作记录](doc/AI协作记录.md)：实际结果、失败、未知值和复核状态。
- [技术方案与分阶段开发计划](技术方案与分阶段开发计划.md)：v0.5.1，P2-A/B/C、P3/P4/P7顺序和阶段验收。
- [论文调研](doc/论文调研与推荐路线.md)、[云端准备](doc/云端复现实验准备.md)、[用户云端查询](doc/云端环境检查记录.md)：RTX4090D24GB、数据盘100G的基础查询已归档；云端模型/配额/预算仍待后续验证。
- [课程原始规范](<Agent开发课程实验课题总体规划与开发规范(3).md>)：原文保持。

## 仓库约定

仓库由用户于2026-10-19设为public，保持该设置。只提交源代码、文档、精简证据和小型授权fixture；密钥、权重、环境、本地数据库及完整运行产物不入库。Git不复制队友的GPU和安装环境；换机器按锁定重建CPU环境并重跑检查，实际模型迁移在P2-A另行授权。
