# P2-A正常模式编译与官方样例结果

- 日期：2026-10-20，子项P2A-GPU-001，轮次p2a-gpu-20261020-01。
- **本轮4项技术目标通过：5项扩展编译、GPU冒烟、完整模型加载、官方样例生成及独立读回。**P2-A整阶段仍待相机映射/测量口径核验和人工复核，不进入P2-B。
- 本报告对应技术执行轮次，当时用户要求不上传；后续DOC-006已另行授权提交推送，原运行时点与实测不改写。云端执行已结束并备份，用户已自行关机。
- DOC-006用途澄清：复杂官方T样例超出第一版简单摆件的正常输入范围，仅作为环境、权重、推理和导出路径的验证；不计入简单摆件成功率/质量汇总、切片或打印验收，不因外观复杂而扩大产品目标。后续只比较TripoSR基线和TRELLIS.2候选在范围内样例上的表现，重点转回自研工作流。

## 1.实际执行与版本

正常模式复查RTX4090D24564MiB、16核CPU/80GiB内存、Ubuntu22.04.4、驱动580.76.05、nvcc12.4.131；数据盘100G，结束时已用47G/可用54G。无卡准备的环境、权重和源码均复用，未重复下载权重。

候选环境Python3.10.22、Torch2.6.0+cu124、torchvision0.21.0+cu124；FlashAttention2.7.3沿用官方轮子，OpenCV4.10.0.84沿用已验证EXR修订。完整110条pip记录及32个conda包见[Linux快照](../locks/p2a-trellis2-linux.txt)、[conda清单](../locks/p2a-trellis2-conda-linux.txt)。原base/prepared快照保留为历史。

| 扩展 | 固定源码revision | 结果/安装版本 |
| --- | --- | --- |
| nvdiffrast | 253ac4fcea7de5f396371124af597e6cc957bfae | 构建安装通过，0.4.0 |
| nvdiffrec_render | b296927cc7fd01c2ac1087c8065c4d7248f72da4 | 构建安装通过，0.0.0 |
| CuMesh | 12289e1062f0603f2f0d0771b02e1395d247f26f | 构建安装通过，0.0.1 |
| FlexGEMM | 6dd94a859c26ee8246888502eada3dd8ad85532e | 构建安装通过，1.0.0 |
| o-voxel | TRELLIS.2的75fbf0183001ed9876c8dbb35de6b68552ee08bd | 构建安装通过，0.0.1 |

子模块沿用[来源计划](../locks/p2a-source-plan.json)，编译目标8.9、MAX_JOBS=4、--no-deps/--no-build-isolation，不升级基础环境；pip check退出0。5项扩展的跟踪源码未修改。nvdiffrast构建后多出未跟踪build/和nvdiffrast.egg-info/，已记录并保留，不能把构建后的目录称为完全空白工作树。

云端项目HEAD为056e4df90a981d0d971e9534be8fe1b4102c7b8c；本机HEAD为dd5a9b4，未提交辅助文件通过SSH上传。基线提交不能代替本次脚本版本；实际脚本副本位于本机备份的helper-sources及steps目录。

## 2.GPU与官方样例结果

| 验证 | 实际结果 |
| --- | --- |
| FlashAttention | FP16输出对照CPU双精度参考，rtol/atol均0.02，通过 |
| nvdiffrast | CUDA三角形16×16光栅化，有覆盖且数值有限，通过 |
| CuMesh | 四面体GPU初始化、面法线计算及读回，通过 |
| 其余模块 | FlexGEMM、o_voxel、nvdiffrec_render及管线导入通过；随后官方例实际执行稀疏计算、渲染和导出路径 |
| 完整加载与推理 | 固定官方example.py原样运行，退出0，首次即完成，无模型重试 |
| GLB独立读取 | probe/trimesh4.0.5：801210顶点、965545面，非空、有限坐标、有效索引，通过 |
| 水密/打印 | watertight=false；未定标、未做本项目打印检查或切片，不能认定可打印 |
| 视频 | H.264，2048×1536、15fps、120帧、8秒，读取通过 |

官方输入为固定assets/example_image/T.png及forest.exr；主权重revision为af44b45f2e35a493886929c6d786e563ec68364d，DINOv3/RMBG固定revision沿用无卡报告。默认1024_cascade、low_vram=True、seed42、各阶段12步；导出保持1000000面目标、4096纹理、remesh=True/band1/project0及extension_webp=True。官方代码自带的补洞、重网格和简化照常执行，不属于本项目P3修复实现。

执行前发现评估设计笼统写seed0，已明确：P2-A官方默认组保留seed42；P2-B比较协议仍为seed0，不混合统计。官方T样例不属于P1的30例清单，本轮未使用evaluation或holdout。

## 3.时间、显存和费用口径

| 项目 | 数值 | 口径 |
| --- | --- | --- |
| 扩展安装步骤 | 695.620秒 | 包含5项构建、安装、依赖检查及快照 |
| GPU冒烟步骤 | 8.765秒 | 含解释器/导入；内部实际算子区间0.395秒，不是模型耗时 |
| 官方例内部总区间 | 583.329秒 | 含模型加载、首次运行、采样、解码、120帧渲染和GLB导出；不含Python启动/Torch导入 |
| 官方例整个步骤 | 589.838秒 | 含外层初始化及采样器启动/退出 |
| Torch峰值allocated | 8729.473MiB | cuda.reset_peak_memory_stats后采集 |
| Torch峰值reserved | 10364MiB | 与allocated分开保留 |
| nvidia-smi进程采样峰值 | 14132MiB | PID4744，579个样本，约1Hz |
| nvidia-smi设备采样峰值 | 14177MiB | 589个设备样本，约1Hz；不是连续峰值 |
| 实付GPU费用 | 未知 | 没有读取平台账单，不填0 |

两类显存口径分别记录，不能相互替代。本次没有插入加载/纯推理/导出的独立计时，也没有重复运行官方例测热启动；这些分项保持not_run，不从总时长推算。用户已取消整体工作时限，[操作者授权记录](../evals/budgets/p2a_user_execution_policy.json)不属于产品BudgetPlan，未修改其缺配置阻断或宣称require_ready通过。

## 4.实际命令与产物

以下入口均在本轮实际执行，单GPU顺序运行，没有并发模型任务：

```bash
export P2A_RUN_DIR="$PWD/runs/p2a-gpu-20261020-01"
bash scripts/p2a/install_trellis2_extensions.sh
source scripts/p2a/environment.sh
conda activate "$PROJECT_ROOT/runtime/envs/trellis2"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/p2a/check_trellis_cuda.py
python scripts/p2a/run_trellis2_official.py --output "$P2A_RUN_DIR/official-default"
runtime/envs/probe/bin/python scripts/p2a/read_mesh.py \
  "$P2A_RUN_DIR/official-default/sample.glb" \
  --output "$P2A_RUN_DIR/official-default/independent-read.json"
```

实际后台步骤还包含1Hz的设备/进程显存采样、视频读取和计帧；完整命令与退出码在ZIP的steps目录。原始官方例没有改写。封装只增加离线配置、独立输出、计时/显存、失败报告；本轮补充异常栈和PID记录。

- [GLB模型](../runs/p2a-gpu-20261020-01/cloud-backup/official-default/sample.glb)：42860708字节，可用本机Blender导入。
- [官方转台视频](../runs/p2a-gpu-20261020-01/cloud-backup/official-default/sample.mp4)：3858673字节。
- [原始输入](../runs/p2a-gpu-20261020-01/cloud-backup/official-default/input-T.png)、[视频第30帧](../runs/p2a-gpu-20261020-01/preview-frame030.png)、[视频第90帧](../runs/p2a-gpu-20261020-01/preview-frame090.png)。两帧由本机既有CPU解码工具提取，AI已查看；这是导出GLB前的官方视频渲染，不是打印质量证明。
- [原始日志/产物ZIP](../runs/p2a-gpu-20261020-01/cloud-backup.zip)：34845820字节、41文件，下载及CRC检查通过。权重、环境和凭据不在ZIP或Git内。
- [精简证据](p2a-gpu-evidence.json)、[真实ExperimentRecord](../evals/results/p2a-20261020-trellis2.json)：已按P1模型校验1条通过；产物引用均对应本机实际文件。

完整运行产物受Git忽略；当前文件链接在本机可打开，后续Git同步只携带源代码、文档、锁定和精简证据，不会把43MB模型自动推送到仓库。

## 5.问题、回归与剩余验收

模型、GPU检查和5项编译均成功。附属归档问题已处理并保留原始证据：视频读取器nframes=Infinity改用实际计数120并严格序列化；归档检查将未跟踪构建目录与跟踪源码差异分开；本机默认GBK读取问题改显式UTF-8。详见BUG-006复发及BUG-016/017。第一次单条契约验证命令遗漏src路径，按源码检出布局加入sys.path后校验通过，未安装或改动业务包。

本机实际执行68项离线测试通过/1.15秒，20模型Schema导出检查退出0，30例静态清单检查退出0；这些不是模型质量或保留集成绩。

本轮请求的编译、GPU算子、加载和官方样例目标已完成。TripoSR两例已有迁移证据不重复运行。**整阶段仍待后端到输入视角的固定映射/测量口径核验，以及[本轮人工复核](P2-A人工复核清单.md)。**本次不计算IoU/Chamfer，不进行同机对比，不把单例生成成功写成论文表格复现或可打印验收通过。

本轮云端工作已停止且产物已备份，后续文档归档只在本机执行；不进入P2-B，不暂存、提交或推送GitHub，不代关机。
