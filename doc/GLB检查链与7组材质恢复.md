# GLB检查链与7组副本材质恢复

版本glb-preserve-v1，对比页pbr-preserved-v3。用户明确要求检查流程保留GLB的UV和PBR、恢复7组已有副本、更新页面/下载包，不重新生成模型。

## 完成内容

- 首次生成GLB读回后保存raw_mesh.glb，不转成PLY；清理、定标及结构提案均保存GLB。
- 内存检查网格按完全相同的位置焊接，避免把UV接缝误判成孔洞；磁盘GLB保留各角点UV和材质顶点。
- 材质、纹理/采样器定义和嵌入图像字节保留。清理删面和定标通过原三角面/角点对应更新，不重烘焙。
- GLB文件采用米/Y朝上的显示坐标，extras.i3d.logical_from_gltf声明毫米/Z朝上检查变换；单位/坐标只换算一次。
- 新增补片保留已有面的材质，补片单独标为untextured_patch；纹理网格重网格后没有精确UV对应时明确拒绝，不静默转顶点色。旧PLY版本兼容只读。
- 此处“无PLY”指首次GLB之后的检查链；模型原生几何和首次导出前GPU诊断快照仍沿用原诊断格式，不属于本轮检查中转。

## 7组已有副本恢复

7份原GLB、7份历史检查PLY保持，恢复结果写为各目录inspection-pbr.glb。6组恢复原PBR，TripoSR原件本来只有顶点色，保留原始COLOR_0和材质信息，不伪造PBR。

| 序号 | 任务前缀 | 检查副本面数 | 恢复外观 | 最大几何读回误差mm |
| --- | --- | ---: | --- | ---: |
| 1 | b614e847 | 94,035 | 原始PBR | 0.00002074 |
| 2 | 9285b61d | 170,506 | 原始顶点色 | 0.00001707 |
| 3 | cdd10795 | 986,650 | 原始PBR | 0.00001962 |
| 4 | e7caaaac | 975,163 | 原始PBR | 0.00003554 |
| 5 | 0d92b552 | 945,883 | 原始PBR | 0.00006238 |
| 6 | fec7619d | 95,821 | 原始PBR | 0.00000413 |
| 7 | da159af6 | 992,873 | 原始PBR | 0.00003295 |

逐组核对：已检查面集合/位置保持，UV或颜色角点与原始几何配对一致，材质参数相同，12张嵌入PBR图像逐字节SHA256保持。误差来自GLB浮点存储，最大约0.0000624mm。没有新增三角面，没有重新生成或重烘焙。旧质量报告和打印失败结论不改写。

## 实际验证

- 本机最终几何/契约/测量等191项通过、6项平台跳过；新增常量PBR材质检查后，最终几何91项通过、5项平台跳过。
- Linux最终197项通过；8项新增检查覆盖UV接缝、清理/定标、多primitive材质、补片标记、变化点拒绝、外部贴图拒绝、常量材质保持及多对象明确拒绝。
- 已有猫原GLB真实CPU执行：导入GLB→清理→100mm定标→Blender4.5.14/3D Print Toolbox检查→副本GLB导出；94088→94035面，中间PLY为0，原UV/PBR保持，源摘要保持，打印结论blocked。
- Edge/Playwright实际加载7组14模型，所有恢复副本有法线、未启用flatShading；6组的底色/金属度/粗糙度贴图均已实际加载，页面异常0。材质、灰模及近景截图已更新。
- AI视觉核对翼兽和猫近景，颜色、反射与原件一致；尚未取得用户本轮人工复核，不能代填。

## 回归边界与首次失败

旧工作流测试存在11项失败，主要是旧测试/fixture仍按generation-v1完成语义和缺原始来源的模型替身编写；本轮在HEAD的隔离副本复跑，修改前与最终失败集合完全一致（均50通过/11失败），新增失败0。不把这组测试宣称全通过，也不借本轮改写原始GLB交付契约。

本轮首次出现：GLB带材质/COLOR_0时Trimesh未返回显式颜色，已改为读取访问器并转换供内存几何使用；单位读回发生二次换算，已按GLB逻辑变换兼容；第7组近邻坐标量化产生配对歧义，独立核对增加候选原角点验证，UV仍逐值精确匹配。Linux验证包首次漏装既有fixture/脚本、验证器读取配置层级错误均在未发布前阻断并修正。Windows子进程编码统一用PYTHONUTF8=1。最终静态复核发现快速入口统计仍引用已移除的几何对象，补固定失败用例后改为GLB读回返回面数/顶点数；两份统计兼容补丁已备份发布，最终Linux197项通过。

## 云端发布与交付

已在同一部署备份并更新9份检查链代码；33个旧任务状态保持，两个模型环境的轻量GLB模块CPU导入均通过。API/worker发布前均未运行，发布后保持停止，下次原启动器启动时使用新代码。没有创建模型/LLM任务，不运行GPU、不安装依赖、不烘焙，不改用户开关机状态。

对比页：http://127.0.0.1:17731/?v=pbr-preserved-v3。更新包：最近7次原始与副本.zip。旧法线修订ZIP另存最近7次原始与副本-法线修订版.zip；原始GLB、历史PLY和检查报告继续留存用于追溯。ZIP大小/CRC以包旁package-check.json及精简证据为准。

## 实现与命令

实现位置：geometry/glb_preserve.py、geometry/core.py、geometry/structure.py、adapters/reconstruction.py、scripts/tools/model_worker.py、artifacts/pbr.py和artifacts/export.py。公共Pydantic业务schema未改，原始GLB主预览/下载规则未改。

```powershell
$env:PYTHONUTF8='1'
& 'runtime/envs/backend/Scripts/python.exe' -m pytest tests/geometry tests/unit tests/contract tests/measurement tests/evaluation -q
& 'runtime/envs/backend/Scripts/python.exe' scripts/tools/restore_glb_copies.py --directory 'runs/recent-seven-20261023'
node 'runs/recent-seven-20261023/render.cjs'
& 'runtime/envs/backend/Scripts/python.exe' 'runs/recent-seven-20261023/package.py'
```

云端实际命令和完整日志保存在runs/glb-preserve-20261025；生产文件/SQLite备份仅在云端保留，不入Git。没有重新执行图片推理、保留集或切片，不能将本轮材质保留称为打印合格。
