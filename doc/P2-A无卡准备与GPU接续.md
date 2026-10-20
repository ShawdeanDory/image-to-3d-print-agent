# P2-A无卡准备与GPU接续

- 日期：2026-10-20，子项P2A-CPU-001；本文件保留无卡阶段快照及当时的接续计划。后续正常模式5项编译、GPU冒烟和官方样例已通过，最新以[正常模式报告](P2-A正常模式编译与官方样例结果.md)为准，不再按下文历史“等待GPU”状态启动任务。
- 用户明确取消本轮及后续整体工作时限，由用户任务结束后自行关机。本轮不设整体计时停止，不把原3600秒/2元窗口重置为新预算；仍保留单个网络请求的技术超时和明确失败行为。
- 继续遵循“先不上传GitHub”：文件保存在本地，未暂存、提交或推送；不进入P2-B。

## 1.哪些可以无卡做

| 工作 | 是否需要GPU运算 | 本轮结果 |
| --- | --- | --- |
| Python依赖、源码/子模块、版本核对 | 不需要 | 8个固定源码目录均一致，相关子模块已就绪 |
| 权重下载、大小/摘要、缓存引用检查 | 不需要 | 补齐DINOv3/RMBG的8个文件，合计2097532491字节，完整性检查通过 |
| 现成CUDA扩展轮子安装/不调用GPU的导入 | 不需要GPU运算，要求版本匹配 | 官方FlashAttention2.7.3轮子已安装，导入和pip check通过 |
| CPU数值、PNG/JPEG、配置/模型类、官方输入解码 | 不需要 | 28项基础依赖检查通过；RMBG配置/模型类离线导入通过，未实例化模型 |
| CUDA扩展源码编译 | 通常主要使用CPU、内存和nvcc | 余下5项移到正常实例配额后，当前无卡仅0.5核/2GiB，不做重型编译 |
| CUDA算子、完整候选模型和官方示例、显存测量 | 需要GPU | 本轮未执行，等待GPU启动 |

无卡模式并非原16核/80GiB配额只移除GPU：本轮cgroup实测为0.5核/2GiB，Torch设备数0、CUDA可用False，nvcc12.4.131仍存在；数据盘和既有环境保留。该配置与[AutoDL无卡模式说明](https://backup.autodl.com/docs/save_money/)一致。[PyTorch扩展文档](https://docs.pytorch.org/docs/stable/cpp_extension.html)说明可显式设置目标CUDA架构；本项目恢复编译时沿用8.9，不把“编译CUDA代码”与“运行GPU算子”混为一项。

## 2.实际完成及证据

1. DINOv3固定ea8dc2863c51be0a264bab82070e3e8836b02d51，RMBG固定5df4c9c76d8170882c34f6986e848ee07fd0ba43。两份safetensors分别1212559808/884878856字节，完整SHA256均与官方LFS元数据一致；其余6个配置/代码文件核对Git blob摘要，8/8通过。没有重复下载原先已校验的公开大权重。
2. 基础依赖和CPU矩阵/PNG/JPEG检查通过，首次无卡检查24.494秒、进程峰值679.46MiB；这不是模型推理耗时或GPU显存。修正OpenCV后再次执行基础导入与pip check，均通过。
3. FlashAttention使用[官方v2.7.3发布](https://github.com/Dao-AILab/flash-attention/releases/tag/v2.7.3)的cu12/torch2.6/cp310/cxx11abiFALSE轮子，191345582字节；Torch实测ABI为False。新增纯Python依赖einops0.8.1，未编译FlashAttention源码、未运行其GPU函数。轮子自算SHA256为64ba4ed4a8c4c9b79d8a0959ebe3ffd6f7ea707ae222dbebe6a864237ac0e475；旧官方发布没有提供digest，该值用于本项目锁定，不称为官方摘要验证。
4. RMBG固定代码经AST/导入检查，AutoConfig与BiRefNet类离线导入成功，配置bb_pretrained=False；未构造模型、未把完整权重载入内存。两处timm弃用警告不影响本次导入，上游代码未改。
5. 完整候选缓存25个文件可离线解析，10个safetensors头及数据偏移检查通过，4个仓库main缓存引用与固定revision一致。既有公开组完整SHA256沿用先前验证；本步不重复把头检查说成全部权重重新验哈希。
6. 官方T.png为1024×1024RGBA，SHA256为db468bad8a04f1474a8d68140c07501b013b3ec6124b911fb7852675d64c05ee；官方forest.exr可读为512×1024×3。固定pipeline仍为1024_cascade，未更换图片、HDRI、采样或导出参数。

[脱敏证据](p2a-no-gpu-evidence.json)保存修改前/后、源码、下载/校验、CPU检查、失败与回归、停止状态。[当前pip快照](../locks/p2a-trellis2-prepared-linux.txt)及[conda前缀清单](../locks/p2a-trellis2-prepared-conda-linux.txt)从真实备份原样复制；[FlashAttention轮子来源与摘要](../locks/p2a-flash-attn-wheel.json)单独锁定。原基础快照保留历史，不覆盖；file路径及conda/pip覆盖注意事项沿用[基础安装报告第5节](TRELLIS.2基础环境安装记录.md#5依赖快照与证据)。

## 3.修订与实际回归

- 初始两个后台入口保留CRLF，均返回2；统一UTF-8/LF后下载成功，CPU检查进入执行。原错误与新步骤分开保存，未覆盖日志。
- 无卡镜像缺少/usr/bin/time，附属计时步骤返回127；改用Python标准库resource/time，CPU检查返回0，不为计时安装系统包。
- 首次离线预检返回1：OpenCV5.0.0.93构建信息为OpenEXR:NO，原HDRI文件存在但读取None。同一原图在已有4.10.0.84环境可读。候选环境仅将OpenCV固定到4.10.0.84后，25文件/官方PNG/HDRI预检、基础导入和pip check均返回0，NumPy2.2.6与Torch2.6.0保持不变。安装入口已同步约束，未用另一HDRI兜底。
- 新官方示例封装在无卡模式返回2/not_run，且未创建输出目录，确认在导入候选管线、加载权重前阻断；该边界检查通过，不是模型生成失败。后续GPU分支尚未实际执行。

## 4.恢复正常模式后的顺序

以下为已准备但尚未执行的接续命令。由用户正常模式启动并告知后继续；不自行切换实例模式，不重新下载已验证权重或重装基础依赖。

```bash
cd /root/autodl-tmp/image-to-3d-print-agent
export P2A_RUN_DIR="$PWD/runs/p2a-native-next"
source scripts/p2a/environment.sh
conda activate "$PROJECT_ROOT/runtime/envs/trellis2"
nvidia-smi
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# 复查GPU、正常CPU/内存配额、磁盘及固定来源后，才执行编译。
bash scripts/p2a/install_trellis2_extensions.sh
HF_HUB_OFFLINE=1 python scripts/p2a/check_trellis_cuda.py

# 保持原官方example.py，输出另存，原源码/资源不改。
python scripts/p2a/run_trellis2_official.py --output "$P2A_RUN_DIR/official-default"

# 成功后使用独立probe读取具体GLB，不用导出成功代替几何有效。
runtime/envs/probe/bin/python scripts/p2a/read_mesh.py \
  "$P2A_RUN_DIR/official-default/sample.glb" \
  --output "$P2A_RUN_DIR/official-default/independent-read.json"
```

剩余源码编译包括nvdiffrast、nvdiffrec_render、CuMesh、FlexGEMM和o-voxel。新入口复用已装FlashAttention，固定既定源码并用--no-deps避免升级基础环境；目前仅通过Bash语法检查，尚不能声明编译通过。运行官方示例的封装保持原默认参数，同时计时/采集allocated与reserved峰值；其耗时含加载、生成、PBR视频和GLB导出，不含Python启动/Torch导入。首次失败保留原始结果，不静默换参数或后端。

官方样例有效并独立读回后，还须按P2-A约定完成相机/测量口径、完整Linux环境快照及真实运行记录、人工复核，才能讨论P2-B；本轮不提前验收。

## 5.交接与停止

本轮观测窗口15:46:00至16:09:37+08:00，记录耗时而不设整体上限。结束时本轮后台进程0、数据盘100G/已用47G/可用54G；日志已备份本机runs/p2a-cpu-20261020-01/cloud-backup.zip，34977字节/62文件，权重和令牌不在ZIP或Git中。

当前等待用户正常GPU模式启动。P2-A完整验收和本轮主要代码/结果的人工复核仍待完成，P2-B未启动；本轮不暂存、提交或推送GitHub，不代关机。任务时限约定已写入AGENTS.md，不修改产品业务schema或把历史预算改造成“已确认无限预算”。
