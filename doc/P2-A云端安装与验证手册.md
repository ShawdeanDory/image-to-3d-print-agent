# P2-A云端安装与验证手册

- 日期：2026-10-20；对应[当前任务](../spec/当前开发任务.md)。这是预训练模型的推理环境安装，不训练模型。
- 已实际验证：SSH公钥登录、[只读采集脚本](../scripts/p2a/collect_environment.py)；RTX4090D24564MiB、16核、80GiB内存、100G数据盘，详细证据见[云端检查](云端环境检查记录.md#5cloud-env-002ssh只读复查2026-10-20)。
- 安装状态：TripoSR两例迁移保留；TRELLIS.2基础/权重、5项源码扩展、GPU冒烟、完整模型/原官方例和独立读回现已通过，见[正常模式报告](P2-A正常模式编译与官方样例结果.md)。云端本轮工作已结束、产物已备份，用户随后明确已关机；不重跑已通过项。相机/测量及人工复核待完成，P2-A未整阶段验收，继续不上传GitHub；第9节保留历史暂停快照。
- 来源计划：[p2a-source-plan.json](../locks/p2a-source-plan.json)。源码/权重revision已列明，Linux传递依赖锁定须在实际安装验证后生成。

DOC-006边界：已有安装/官方复杂例只作环境成果保留，不再扩展安装其他调研模型；后续仅围绕简单摆件作两后端选型，并优先完成自己的Agent工作流。用户已明确本轮提交推送，覆盖历史暂缓上传；本轮只调整文档，不运行手册中的命令、不连接云端或进入P2-B。

## 1.执行前与目录

历史[确认预算](../evals/budgets/p2a_confirmed.json)为7200秒/4元，[第2步预算](../evals/budgets/p2a_base_confirmed.json)为3600秒/2元，均保留对应历史；[draft](../evals/budgets/p2a_draft.json)保留为拒绝样例。用户现已授权无卡准备/正常模式接续，并明确取消本轮及后续工作整体时限，由其自行关机；不再重复索取准备时限，不把旧窗口重置为新预算。时限取消不修改业务BudgetPlan及产品超时契约，单个网络请求仍有技术超时；账单不虚构。

历史限时窗口从实际安装计时，各段共享剩余预算；本次用户已取消整体时限，因此P2A-GPU-001仅使用screen保活，不施加历史整体timeout，不把旧限额重新当作当前停止点。单个网络/SSH请求仍有技术超时。停止进程后GPU计费是否结束以平台实例状态为准，本项目由用户自行关机，数据盘费用另计。

云端统一布局如下；首次将项目代码克隆到数据盘，并记录实际项目提交。后续已有目录先检查Git状态再同步，不覆盖他人修改。

```bash
cd /root/autodl-tmp
git clone https://github.com/ShawdeanDory/image-to-3d-print-agent.git image-to-3d-print-agent
git -C image-to-3d-print-agent rev-parse HEAD
```

```text
/root/autodl-tmp/image-to-3d-print-agent/
├── scripts/p0/、scripts/p2a/、fixtures/p0/、locks/   Git代码与小样例
├── runtime/envs/triposr/                          Python3.11隔离环境
├── runtime/envs/trellis2/                         Python3.10隔离环境
├── runtime/envs/probe/                           独立网格读回环境
├── runtime/upstream/                             固定源码与子模块
├── runtime/cache/                                conda、pip、HF缓存
├── runtime/tmp/、runtime/torch_extensions/         临时与编译产物
├── weights/TripoSR/                              TripoSR本地权重
└── runs/p2a-20261020-01/                          原始日志与结果
```

连接命令、私钥只在本机runtime/ssh/保存。本机使用专用配置连接p2a-autodl别名，真实地址不写入公开仓库。非交互SSH的默认PATH未包含Python，已验证基础解释器为/root/miniconda3/bin/python。

## 2.云端公共环境变量

以下Bash命令仅在预算确认后执行；需在每个新的screen/SSH会话加载相同设置。

```bash
set -euo pipefail
export PROJECT_ROOT=/root/autodl-tmp/image-to-3d-print-agent
cd "$PROJECT_ROOT"
export HF_HOME="$PROJECT_ROOT/runtime/cache/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export PIP_CACHE_DIR="$PROJECT_ROOT/runtime/cache/pip"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/runtime/cache/conda"
export TMPDIR="$PROJECT_ROOT/runtime/tmp"
export TORCH_EXTENSIONS_DIR="$PROJECT_ROOT/runtime/torch_extensions"
export CUDA_HOME=/usr/local/cuda
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TORCH_CUDA_ARCH_LIST=8.9
export MAX_JOBS=4
mkdir -p "$HF_HUB_CACHE" "$PIP_CACHE_DIR" "$CONDA_PKGS_DIRS" "$TMPDIR" "$TORCH_EXTENSIONS_DIR" runtime/envs runtime/upstream runs/p2a-20261020-01
source /root/miniconda3/etc/profile.d/conda.sh
```

实际执行发现并行conda创建会争用共同缓存，安装辅助脚本已改为各自的conda-triposr、conda-probe、conda-trellis2目录。恢复不照抄共同缓存并发创建。Windows发送Bash脚本需使用LF字节；后台入口从项目内规范脚本路径exec，保持相对依赖位置。

已存在的screen会话用screen -ls查询、screen -r会话名恢复；Ctrl+A后按D离开。screen只能防SSH断开，关机后进程仍会停止。安装的stdout/stderr保存至runs，不用终端滚屏作为唯一记录。

## 3.获取固定官方源码

在公共环境变量已加载的终端运行。实际使用prepare_source.py按固定完整revision浅取并初始化固定子模块；已有目录先核对HEAD/状态，版本一致才复用，不删除或重置。

```bash
for source_name in TripoSR torchmcubes TRELLIS.2 utils3d nvdiffrast nvdiffrec CuMesh FlexGEMM; do
    /root/miniconda3/bin/python scripts/p2a/prepare_source.py "$source_name"
done
```

实际执行可以先只获取TripoSR和torchmcubes，再处理TRELLIS.2，避免候选依赖阻碍已有基线。记录完整源码/子模块版本，不把分支名当作固定版本。

## 4.TripoSR独立环境

依赖选择沿用已验证P0版本，CUDA轮子改为cu124以匹配本机nvcc12.4；属于新的Linux组合，仍需实际验证。下面不直接安装上游浮动Git依赖，torchmcubes使用第3节固定源码。

```bash
conda create -y -p "$PROJECT_ROOT/runtime/envs/triposr" python=3.11 pip
conda activate "$PROJECT_ROOT/runtime/envs/triposr"
python -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
python -m pip install numpy==1.26.4 omegaconf==2.3.0 Pillow==10.1.0 einops==0.7.0 transformers==4.35.0 trimesh==4.0.5 rembg==2.0.57 huggingface-hub==0.17.3 onnxruntime==1.18.1 opencv-python-headless==4.10.0.84 xatlas==0.0.9 moderngl==5.10.0 'imageio[ffmpeg]' setuptools==69.5.1 cmake==3.29.6 pybind11==3.1.0 scikit-build-core==1.1.1 ninja
python scripts/p2a/prepare_torchmcubes_build.py
python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/build/torchmcubes-cxx17"
python -m pip check
python -c "import torch, torchmcubes; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torchmcubes.HAS_CUDA)"
```

检查点：CUDA可见、torchmcubes.HAS_CUDA为True，实际CUDA张量及扩展调用通过。若构建失败，先保留日志并更新Bug，不悄悄改成P0的CPU表面提取。本轮不启动Gradio界面。实际固定上游的C++20构建遇到lerp声明冲突，原始失败保留；prepare_torchmcubes_build.py只复制Git跟踪文件到独立目录，显式把CXX/CUDA标准改为17并保存差异，上游源码目录不变。这是已验证的构建兼容变体，不称为未修改上游。

权重下载在此环境完成，使用第6节代码并选择MODEL_GROUP=triposr。读取来源计划的固定revision，将config.yaml/model.ckpt复制至weights/TripoSR；facebook/dino-vitb16只下载config.json到HF缓存，不另下DINO模型。不要从Windows复制虚拟环境或CUDA二进制。

## 5.TRELLIS.2独立环境与原生扩展

第2步基础依赖现使用独立入口，不能在基础安装授权下执行本节后面的CUDA扩展命令：

```bash
cd /root/autodl-tmp/image-to-3d-print-agent
export P2A_RUN_DIR="$PWD/runs/p2a-base-20261020-01"
bash scripts/p2a/install_trellis2_base.sh
```

实际执行由screen和本轮共享截止时间包围；上面仅为安装入口，不会自行延长预算。入口复用现有Python3.10前缀，按PyPI官方SHA256经中科大镜像续传triton轮子，普通依赖使用同一镜像索引；Torch保持原官方固定URL及摘要，安装Torch2.6.0+cu124/torchvision0.21.0及官方basic组。额外明确固定transformers4.57.6和构建后端setuptools80.9.0，前者检查DINOv3类可导入，后者供utils3d/Pillow-SIMD的构建使用。除这两个本地CPU构建外，依赖只允许现成轮子；系统libjpeg-dev已存在时不重装。实际版本以本轮快照为准。

基础验收只运行pip check、CPU导入、小矩阵乘法、PNG内存读写及JPEG能力查询，不加载DINOv3/RMBG/TRELLIS模型、不执行GPU算子。check_trellis2_base.py记录各包版本、导入结果和明确未执行项。flash-attn/nvdiffrast/nvdiffrec/CuMesh/FlexGEMM/o-voxel仍留给后续CUDA扩展步骤。

基础安装现已退出0，28项依赖检查及pip check/CPU冒烟通过；[pip快照](../locks/p2a-trellis2-base-linux.txt)和[conda前缀清单](../locks/p2a-trellis2-base-conda-linux.txt)已从本机备份原样归档。快照包含云端file路径及conda/pip覆盖记录，复建顺序和Pillow-SIMD实际导入版本见基础安装报告第5节。以下整体环境命令仅作后续参考，不表示已经执行或已获本轮启动授权。

此环境和TripoSR分离。安装顺序根据[官方setup.sh](https://github.com/microsoft/TRELLIS.2/blob/75fbf0183001ed9876c8dbb35de6b68552ee08bd/setup.sh)整理；原脚本包含系统目录临时构建和sudo，不直接把整体返回码当作每步都成功。项目缓存/构建使用数据盘，每条命令出错即停止。

```bash
conda create -y -p "$PROJECT_ROOT/runtime/envs/trellis2" python=3.10 pip
conda activate "$PROJECT_ROOT/runtime/envs/trellis2"
python -m pip install triton==3.2.0
# 实际安装入口固定官方Torch轮子及其SHA256，避免r2节点低速。
python -m pip install 'https://download.pytorch.org/whl/cu124/torch-2.6.0%2Bcu124-cp310-cp310-linux_x86_64.whl#sha256=7f2ba7f7c0459320a521696f6b5bccc187f59890b23c9dfb6c49b0b87c6bfc97' torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
python -m pip install imageio imageio-ffmpeg tqdm easydict opencv-python-headless==4.10.0.84 ninja trimesh transformers==4.57.6 gradio==6.0.1 tensorboard pandas lpips zstandard kornia timm packaging psutil wheel
python -m pip install "$PROJECT_ROOT/runtime/upstream/utils3d"
```

Pillow-SIMD需要libjpeg开发头文件。先用dpkg-query核对libjpeg-dev；确有缺失再安装系统头文件并记录影响，本实例以root运行，不依赖sudo。随后按官方依赖安装pillow-simd。浮动Python包在安装成功后以实际freeze锁定；此处不是已验收锁定。

```bash
python -m pip install pillow-simd
python -m pip install flash-attn==2.7.3 --no-build-isolation
python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/upstream/nvdiffrast"
python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/upstream/nvdiffrec"
python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/upstream/CuMesh"
python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/upstream/FlexGEMM"
python -m pip install --no-build-isolation "$PROJECT_ROOT/runtime/upstream/TRELLIS.2/o-voxel"
python -m pip check
python -c "import torch, flash_attn, nvdiffrast.torch, cumesh, flex_gemm, o_voxel; print(torch.__version__, torch.version.cuda)"
```

CUDA轮子安装、扩展编译、导入和真实算子分别记录。首次运行可能有JIT编译；不能只因import成功就声明扩展算子或模型通过。构建错误先分类定位，按剩余预算处理，不无限重试。

## 6.下载模型与访问授权

TRELLIS.2的完整推理依赖如下，revision和文件过滤在来源计划中统一维护：

| 模型 | 用途 | 访问条件 |
| --- | --- | --- |
| microsoft/TRELLIS.2-4B | 主要生成模型与pipeline配置 | 公开 |
| microsoft/TRELLIS-image-large | sparse_structure_decoder | 公开，只取所需decoder |
| facebook/dinov3-vitl16-pretrain-lvd1689m | 图像条件编码 | 用户登录并申请访问 |
| briaai/RMBG-2.0 | 官方去背景 | 用户登录并确认模型页条件 |

用户先自行访问[DINOv3模型页](https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m)和[RMBG模型页](https://huggingface.co/briaai/RMBG-2.0)，确认账号权限。AI不代签模型条件；未获访问时保留明确错误。

在已激活trellis2且已加载公共缓存变量的云端终端执行下面命令，以交互隐藏输入方式填写只读令牌；不要把令牌粘贴到聊天、写入命令参数或提交Git。

```bash
python -c "from huggingface_hub import login; login(add_to_git_credential=False)"
```

下载使用huggingface_hub.snapshot_download(repo_id,revision=固定值,allow_patterns=计划过滤,ignore_patterns=可选过滤)。主模型仅取pipeline和推理checkpoint，旧TRELLIS仓库仅取decoder，RMBG只取一份safetensors及所需配置/官方Python代码，避免重复下载bin和ONNX格式。HF缓存统一在数据盘，不再复制一份完整TRELLIS权重。

下面代码在对应独立环境执行。将MODEL_GROUP依次设为triposr、trellis_public或trellis_gated；先下载公开组，受限组只在账号获授权并登录后执行。下载异常直接停止，固定引用只在该snapshot下载成功后建立。

```bash
MODEL_GROUP=triposr python - <<'PY'
import json, os, pathlib, shutil
from huggingface_hub import snapshot_download
root = pathlib.Path(os.environ['PROJECT_ROOT'])
plan = json.loads((root / 'locks/p2a-source-plan.json').read_text())
group = os.environ['MODEL_GROUP']
groups = {
    'triposr': {'stabilityai/TripoSR', 'facebook/dino-vitb16'},
    'trellis_public': {'microsoft/TRELLIS.2-4B', 'microsoft/TRELLIS-image-large'},
    'trellis_gated': {'facebook/dinov3-vitl16-pretrain-lvd1689m', 'briaai/RMBG-2.0'},
}
for item in plan['models']:
    if item['repo'] not in groups[group]:
        continue
    snapshot = pathlib.Path(snapshot_download(
        repo_id=item['repo'], revision=item['revision'],
        allow_patterns=item['allow_patterns'], ignore_patterns=item.get('ignore_patterns'),
        max_workers=2))
    refs = snapshot.parent.parent / 'refs'
    refs.mkdir(exist_ok=True)
    (refs / 'main').write_text(item['revision'], encoding='utf-8')
    if item['local_dir']:
        target = root / item['local_dir']
        target.mkdir(parents=True, exist_ok=True)
        for filename in item['allow_patterns']:
            destination = target / filename
            if destination.exists():
                raise SystemExit(f'目标已存在，请核对后复用：{destination}')
            shutil.copy2(snapshot / filename, destination)
    print(item['repo'], item['revision'], 'downloaded')
PY
```

主权重按官方文件清单过滤后约14.8GB，另有约1.21GB的DINOv3、约0.885GB的RMBG及其他模型/环境；100G可作为首轮容量，但每段下载/编译前查df，不把权重大小当作全部磁盘需求。文件大小是公开元数据估算，不是本次下载或磁盘实测。

加载时使用已固定的本地snapshot或固定缓存引用，并启用HF_HUB_OFFLINE=1，防止内部from_pretrained在验证时解析浮动main。RMBG会执行其仓库的模型代码，需对应已固定且已阅读的官方代码。权限未齐时可以先完成公开模型下载和环境构建，不能宣称TRELLIS.2已完整加载。

## 7.验证顺序与验收

1. 在每个独立环境验证小CUDA张量运算，记录框架/运行时、设备、返回码；TripoSR再实际调用CUDA表面提取扩展，TRELLIS.2分别记录原生扩展导入/算子和模型加载结果。
2. 先使用P0原样脚本迁移TripoSR。固定chunk_size2048、mc_resolution128、float32、seed0，输入已有透明前景；只比较迁移可行性，不称官方默认配置或正式同机比较。
3. TRELLIS.2使用固定源码内assets/example_image/T.png及官方pipeline配置，先加载，再在约定单次上限内验证。官方默认与任何低显存变体分别记录；本轮不自动修改官方参数重跑。
4. 输出由独立probe环境读回，核对可解析、非空顶点/面、有限坐标与有效索引。生成有效网格不等于完成修复、定标、切片或可打印验收。

TripoSR两张迁移样例的计划命令如下；每次必须用确认的单次超时包裹，并记录实际返回码、nvidia-smi及脚本产生的耗时/峰值显存。示例不直接无限运行。

```bash
conda activate "$PROJECT_ROOT/runtime/envs/triposr"
python scripts/p0/reconstruct_case.py --root "$PROJECT_ROOT" --image "$PROJECT_ROOT/fixtures/p0/hamburger.png" --output "$PROJECT_ROOT/runs/p2a-20261020-01/triposr-hamburger"
python scripts/p0/reconstruct_case.py --root "$PROJECT_ROOT" --image "$PROJECT_ROOT/fixtures/p0/robot.png" --output "$PROJECT_ROOT/runs/p2a-20261020-01/triposr-robot"
```

完整P2-A门槛保持为TripoSR两例2/2有效、新候选至少1例有效、独立读回及版本/原命令/资源/错误证据完整。若本轮只完成安装或加载，只归档对应子成果，P2-A继续进行，不进入P2-B。

## 8.锁定、下载结果与恢复

每个环境安装后保存python -m pip freeze、pip check、conda list --explicit，以及git rev-parse HEAD、git submodule status --recursive、模型revision/文件清单。日志与完整网格留在runs；Linux实际锁定与脱敏摘要经检查后入库，不改写P0历史锁定。

在云端只打包本轮结果，不把环境、缓存、权重或令牌一起打包：

```bash
cd "$PROJECT_ROOT"
tar -czf runs/p2a-20261020-01-results.tar.gz runs/p2a-20261020-01
```

在本机PowerShell使用专用SSH配置下载；将配置路径指向当前项目，p2a-autodl为本机别名：

```powershell
$p2aConfig = Join-Path $PWD 'runtime/ssh/p2a_config'
scp -F $p2aConfig p2a-autodl:/root/autodl-tmp/image-to-3d-print-agent/runs/p2a-20261020-01-results.tar.gz runs/
```

恢复前先重新阅读工作前必读约定、当前任务、实际日志与预算剩余量；已完成步骤核对后复用，未完整下载按第9节核对partial和获取方式，不自动删除重下，不重新运行已经成功的模型。普通关机后的数据保留、GPU空闲限制和备份规则见[云端检查第4节](云端环境检查记录.md#4关机数据与交接)。

## 9.本轮暂停与恢复入口

2026-10-20约11:30按用户明确要求暂停，用户自行关闭云端和本机。本轮活动安装/下载进程组均已停止，剩余本轮timeout进程0、GPU占用0MiB；日志/检查点已经备份到本机runs/p2a-20261020-02/cloud-pause-logs.zip。普通关机保留数据盘已落盘文件，恢复以实际文件核对为准。

| 内容 | 暂停时状态 |
| --- | --- |
| probe独立环境 | Python3.11.17、numpy1.26.4、trimesh4.0.5、huggingface-hub0.36.0安装，pip check通过；freeze已保存，网格读取尚未执行 |
| TripoSR环境 | Python前缀建立；PyTorch/CUDA包下载中被停止，尚未安装成可用模型环境 |
| TRELLIS.2环境 | 尚未建立；完整历史克隆已取消，Git清理了未完成目录；浅取固定提交脚本尚未实际运行 |
| 公开权重 | 10份小配置已复制；9份大文件计划总计16644709244字节，当前仅部分文件，完整性校验尚未通过 |
| CUDA与模型 | 张量、扩展、加载、2+1样例和独立读回均未执行，P2-A未验收 |
| 受限模型 | DINOv3/RMBG账号访问条件尚待用户处理，无令牌传入聊天或仓库 |

恢复须用户明确发起，不自动重新启动。先核对原2小时/4元预算已用量和实例实际账单，不把暂停当作新预算；再核对环境和缓存。暂停时的CDN脚本尚未实现续传；本次恢复已加入Range/Content-Range及SHA256校验并实际完成全部公开大文件。临时链接须刷新，不能把partial改名当作完成。临时签名URL只保存在被忽略的runs，公开记录不含它们。

本轮新增scripts/p2a/中的安装、来源、下载和检查辅助入口，属于P2-A内部工具；仅probe安装及部分获取路径实际执行，其他入口不得当作已经完整验证。不进入P2-B。


## 10.本次恢复的已验证入口与接续

- TripoSR安装入口为scripts/p2a/install_triposr.sh，固定OpenCV4.10.0.84和scikit-build-core1.1.1，C++17独立构建副本；安装及pip check退出0。
- 验证入口为scripts/p2a/verify_triposr.sh；P2A_RUN_DIR指向本轮runs目录，外层只使用剩余总预算，内部每次CUDA/模型验证上限300秒。它拒绝已有输出目录，不自动重跑成功样例。
- 本次两张P0图片均通过，独立probe读回成功；Linux依赖、模型版本、耗时/显存和限制见[结果报告](P2-A云端安装与验证结果.md)。9份公开大文件16644709244字节均经官方SHA256验证。
- TRELLIS.2仍未完成。用户再次关机后旧screen为Dead，不能把无exit文件理解为仍在运行；只有本轮新启动的作业才按剩余deadline继续。
- 用户报告两项受限模型已获批；令牌仅在云端runtime/cache/huggingface/token配置，权限600，不回显。两项官方HEAD访问仍超时；配置文件存在不等于访问验证通过。聊天中暴露的令牌须用户撤销重建，新令牌不再发送到聊天。
- P2-A完整门槛和P2-B启动条件保持。主要AI代码及结果仍待人工复核，不把下载完成或TripoSR子成果写成整阶段验收。


## 11.HF网络修复后的执行方式

最新P2A-NET-001已验证：AutoDL官方网络配置必须同时包含代理与配套CA，不能只复制http_proxy/https_proxy。新增包装入口只影响传入的子进程，不需要重新安装包或更改系统DNS。DINOv3/RMBG实际权限已通过，详细结果见[专项报告](HuggingFace网络排查与权限验证.md)。

以下为已实际运行通过的权限检查，仅访问小配置及各1KiB权重，不安装依赖或运行模型：

```bash
cd /root/autodl-tmp/image-to-3d-print-agent
bash scripts/p2a/with_hf_network.sh /root/miniconda3/bin/python scripts/p2a/check_hf_permissions.py --report runs/hf-permissions.json
```

后续获准执行HF下载命令时，同样用bash scripts/p2a/with_hf_network.sh包裹命令及参数；不要仅设置代理后丢弃SSL_CERT_FILE/REQUESTS_CA_BUNDLE，也不要关闭证书校验。本轮第1步完成即停止，其他依赖安装/完整权重下载/模型验证尚未启动。
