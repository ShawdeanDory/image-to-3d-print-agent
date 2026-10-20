# P1固定fixture

版本1.0.0。fixture只用于契约、引用、固定输入和后续实验准备；本轮没有模型推理、业务几何检查或切片结果。

## 来源与许可

| 路径 | 来源与用途 | 许可/限制 |
| --- | --- | --- |
| ../p0/hamburger.png、robot.png | 固定TripoSR提交的既有P0输入，仅development | 沿用[P0来源说明](../p0/README.md)；源码仓库MIT，原始图片作者没有另行核实，不扩称全部图片版权已获独立确认 |
| procedural/ | 16个项目自产简单对象，Blender4.5.14LTS、Cycles CPU、seed0、8samples、256×256RGBA | 项目自产fixture按CC0-1.0提供；配方和相机见source_index.json，不涉及模型权重 |
| masks/ | 18张输入alpha通道阈值128生成的二值蒙版 | 沿用相应输入的许可；是输入蒙版，不能作为生成结果的测量成绩 |
| boundary/ | 损坏文件、真实BMP伪装PNG、人物示意、复杂背景、遮挡变体 | 项目自产异常样例CC0-1.0；同源物体不跨划分 |
| geometry/ | 3个既有P0几何文件+9个项目自产解析OBJ | CC0-1.0；P0历史验证与P1新准备明确区分，12项工具回归待P3 |
| contracts/ | 人工设计的请求/响应/实验JSON、矩形预览、长方体STL | CC0-1.0；成功状态只是结构正例，**没有对应真实模型、用户切片确认或实验成绩** |
| assets.json | 21张有效输入的ID、路径、实际尺寸/字节数 | 仅本地fixture注册表，没有上传服务 |
| printer_profile*.json | FDM/PLA、0.4毫米喷嘴、0.2毫米层高，完整/未知空间两种配置 | `profile_kind=demo`，220×220×250毫米仅为演示空间，不声称小组已有对应打印机 |

契约正例里的重复字符SHA、固定UUID、`offline_fixture`、`offline_fixture_v1`和measured0均为测试数据，不能并入实际实验表。预览方框没有分层含义，STL没有经过本轮几何检查，JSON中的human来源只是人工确认字段的结构样例。实际报告必须引用真实工具产物和真实用户确认。

损坏/伪装上传使用`pending_upload_*`占位ID，明确不加入有效asset表；这表示“上传前的失败输入”，不是可发给现有API的已注册请求。真实上传成功后才分配ID，上传服务在P5实现。范围、背景、遮挡和工具故障的`expected`是后续行为预期，本轮没有实现图像语义识别或调用故障工具。

## 重建fixture

日常测试使用已入库文件，无需Blender。确需重新生成自产图片时使用既有Blender的CPU路径，不能将重生成文件与旧评估成绩混用：

```powershell
& runtime/tools/blender/blender-4.5.14-windows-x64/blender.exe --background --factory-startup --python-exit-code 1 --python scripts/p1/build_fixture_images.py -- "$PWD"
& runtime/envs/contracts/Scripts/python.exe scripts/p1/prepare_fixture_manifest.py
& runtime/envs/contracts/Scripts/python.exe scripts/p1/prepare_geometry_fixtures.py
& runtime/envs/contracts/Scripts/python.exe scripts/p1/check_prepared_data.py
```

P0几何文件已入库，几何准备脚本不要求队友持有原始runs目录；只有首次缺文件时才从本机P0既有结果复制。不同Blender版本/平台重新渲染可能变化，需记录版本并在进入正式模型比较前冻结新数据版本。本轮只查看development/evaluation的自产输入预览；没有使用holdout结果挑模型或调参。
