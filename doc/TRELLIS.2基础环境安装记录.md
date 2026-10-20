# TRELLIS.2基础环境安装记录

- 任务：P2A-BASE-001，第2步基础依赖；日期2026-10-20。
- 用户新授权：最多3600秒、GPU计算费不超过2元；本轮从15:10:49+08:00开始，截止16:10:49+08:00。用户手动关机，安装进程结束不会停止实例计费。
- 范围：Python3.10、Torch2.6.0+cu124/torchvision0.21.0、triton3.2.0及官方basic组；不编译CUDA扩展、不下载完整权重、不运行模型。
- 状态：基础安装与CPU技术检查已完成；本轮按用户新指令仅完成本机文档归档，不上传GitHub。主要脚本/结果待人工复核，P2-A未完整验收。

## 1.输入与修改前基线

本机基线dd5a9b4ea6352776641197ad2970d12662987502，工作树干净。云端Git基线仍为056e4df90a981d0d971e9534be8fe1b4102c7b8c，本轮通过SSH上传辅助脚本，不将它称为最新提交的干净检出。

TRELLIS.2固定源码75fbf0183001ed9876c8dbb35de6b68552ee08bd，utils3d固定9a4eb15e4021b67b12c460c7057d642626897ec8。安装前两目录HEAD及工作树检查通过。现有Python3.10.22前缀存在，但torch、torchvision、triton、numpy、trimesh均未安装；数据盘100G、已用37G、可用64G，GPU查询0MiB/0%。已成功的TripoSR环境和样例保留，不重装、不重跑。

公共Pydantic业务契约没有变化。预算使用现有BudgetPlan.require_ready()校验通过，安装证据单独保存，不创建official_inference成功记录。完整P2-A验收仍引用[当前任务](../spec/当前开发任务.md)，不能用基础安装替代模型样例。

## 2.安装入口与依赖用途

```bash
cd /root/autodl-tmp/image-to-3d-print-agent
export P2A_RUN_DIR="$PWD/runs/p2a-base-20261020-01"
bash scripts/p2a/install_trellis2_base.sh
```

实际后台执行通过screen和剩余总秒数的timeout包围。脚本只执行本步；整体install_trellis2.sh含CUDA编译，不用于本轮。用途和影响如下：

| 组别 | 用途和本轮处理 |
| --- | --- |
| Python/Torch/torchvision/triton | 独立框架与预编译运行时轮子；Torch固定官方URL/摘要，triton按PyPI官方摘要续传 |
| 图像/网格/数值库 | 官方basic组及utils3d依赖；普通轮子使用实测可用的中科大镜像索引 |
| transformers4.57.6 | 提供DINOv3ViTModel、AutoModelForImageSegmentation；只验收类导入，不加载权重 |
| gradio6.0.1/tensorboard/pandas/lpips/kornia/timm | 官方basic依赖；安装和导入，不启动服务或下载预训练参数 |
| 固定utils3d/setuptools80.9.0/wheel | 纯Python源码打包及构建后端；上游目录保持原样 |
| Pillow-SIMD/libjpeg-dev | 官方CPU图像依赖；libjpeg-dev已存在，按条件复用。Pillow-SIMD为CPU编译，不调用CUDA编译器 |

## 3.下载基线与修订

第一次pip未复用旧239599616字节triton临时文件，重新下载253090354字节轮子。对同一1MiB Range，官方文件主机11.27秒、阿里云18.16秒；完整平台代理22.61秒，本机仅下载测试12.96秒。清华1.165秒、中科大0.529秒、腾讯0.573秒；没有因为检测而切换模型执行机器。

先保留基线并记录P2A-BUG-011，再停止本轮精确匹配的下载进程组，两次退出143。切到中科大镜像续传相同文件，246939648字节继续到253090354字节，完整SHA256为b3e54983cd51875855da7c68ec05c05cf8bb08df361b1d5b69e05e40b0c9bd62，与PyPI官方JSON一致，最终续传及校验1.681秒。triton3.2.0实际安装成功；不是用Range测试代替安装。

## 4.验收与交接

最终安装步骤base_mirror退出0；此前base_install和base_resume均因明确停止低速下载而退出143，原始日志保留。不是模型推理失败，也没有用缺失退出码代替成功。

| 检查 | 实际结果 |
| --- | --- |
| Python/框架 | Python3.10.22，Torch2.6.0+cu124，torchvision0.21.0+cu124，triton3.2.0 |
| 数值/网格/图像 | NumPy2.2.6、SciPy1.15.3、trimesh5.1.1、OpenCV5.0.0.93 |
| 主要其余依赖 | transformers4.57.6、gradio6.0.1、utils3d0.0.2、setuptools80.9.0 |
| 基础包检查 | 28项通过：27项实际模块导入，setuptools仅检查安装元数据；不是28项模型测试 |
| pip check | 退出0，No broken requirements found. |
| CPU数值与图像 | 2×2矩阵乘法结果正确；4×4红色PNG内存往返一致；JPEG支持为True |
| 模型接口类 | DINOv3ViTModel、AutoModelForImageSegmentation可导入，未实例化或加载模型 |
| 基础包构建 | utils3d和Pillow-SIMD的CPU构建完成；libjpeg-dev已存在，未新增系统包 |
| 源码与语法 | TRELLIS.2/utils3d固定HEAD一致且工作树干净；安装入口及environment.sh的bash -n均返回0 |
| 安装轮次离线回归 | tests/p2a共11项通过，0.17秒；这是安装轮次的本机结果，文档收尾未重跑 |
| 未执行范围 | CUDA扩展编译/算子、GPU张量、完整权重下载、模型加载、候选官方样例、P2-B |

实际CPU验收命令如下，由安装入口执行并保存至base-check.json；检查器开启HF/Transformers离线模式并关闭Gradio分析，不因导入依赖隐式获取模型：

```bash
python -m pip check
python scripts/p2a/check_trellis2_base.py --phase installed --report "$P2A_RUN_DIR/base-check.json"
python -m pip freeze > "$P2A_RUN_DIR/trellis2-base-pip-freeze.txt"
conda list --explicit > "$P2A_RUN_DIR/trellis2-base-conda-explicit.txt"
```

从15:10:49至15:34:24+08:00，安装准备及云端收尾共1415.18秒，约23分35秒，未超过3600秒。按既有1.88元/小时报价估算约0.74元，实际账单未知，不能把该估算当作平台扣费证明。结束查询本轮活动timeout进程0、GPU0MiB/0%，数据盘100G、已用44G、可用57G，cgroup仍为16核/80GiB。以上是安装结束时的观测；用户切换无卡模式后的状态本轮没有重新查询。

## 5.依赖快照与证据

- [pip完整快照](../locks/p2a-trellis2-base-linux.txt)：103条实际freeze记录；[conda前缀清单](../locks/p2a-trellis2-base-conda-linux.txt)：32个包。两份均从本机备份逐字节复制，不改写成计划版本。
- [脱敏证据](p2a-trellis2-base-evidence.json)：修改前基线、安装后版本与检查、源码、进程退出码、预算、结束资源查询及归档解释。baseline中的passed仅表示采集成功，包版本为null仍表示未安装。
- 原始日志ZIP已备份至本机runs/p2a-base-20261020-01/cloud-backup.zip，16382字节、22份文件，ZIP读取检查通过；完整final.json和解包目录同样保留在runs内，不纳入Git。

这是基础依赖快照，尚不是完整TRELLIS.2推理环境锁定。freeze含triton轮子和utils3d的云端file路径，换机器须按安装入口先准备相同轮子/固定源码；不能在Windows直接照抄。conda清单保留setuptools84.0.0的前缀包记录，随后pip已将实际元数据版本改为80.9.0，重建顺序应先conda前缀、再pip依赖。

按官方basic顺序先安装Pillow、再安装Pillow-SIMD，freeze同时存在pillow12.3.0和pillow-simd12.1.1.post0；本次实际导入PIL版本为12.1.1.post0，PNG/JPEG检查通过。移交或后续增装依赖时须保留该顺序并复查实际导入版本，不能仅凭Pillow分发元数据断言运行版本。

## 6.本轮文档收尾与停止点

用户在安装完成后要求暂停以切换无卡模式，随后明确恢复剩余文档收尾，并要求先不上传GitHub。本轮只读取上述本机备份、导出两份快照和证据、同步任务/方案/长期记录，不连接云端，不验证无卡模式是否已启动，不增加新一轮GPU或安装预算。

本项技术结果已归档，人工复核仍待完成。人工复核可先阅读本报告第4～5节，再核对安装入口、CPU检查器、triton续传脚本和脱敏JSON；没有新的人工结论前保持pending。下一步CUDA扩展编译/算子、完整受限权重和候选官方样例须另获授权，P2-A完整门槛不变，P2-B未启动。本轮改动只保存在本地，不暂存、提交或推送GitHub。

本机收尾检查覆盖20份交付文件、128处本地链接和18处锚点，UTF-8/JSON/Python AST/常见凭据模式均无错误；两份快照逐字节对应备份，脱敏证据保留原始报告全部字段，ZIP22份文件可读。纯文档工作没有业务实现变更，不新增业务测试或重跑云端，未执行项保持原状态。

后续状态：本报告保留第2步当时快照。用户随后授权无卡准备并取消整体工作时限；受限权重已齐，FlashAttention轮子已安装，OpenCV已固定4.10.0.84修复官方HDRI支持。最新快照和已获授权的正常模式接续见[无卡报告](P2-A无卡准备与GPU接续.md)，不再把第2步当时“须另获授权”作为重复索取工作时限的理由。
