# P2-A云端安装与验证结果

- 日期：2026-10-20；恢复轮次p2a-20261020-03。
- 授权：用户明确恢复安装并取消账单核对前置要求；原累计7200秒活动准备时限继续，上一轮1240.91秒，不进入P2-B。云端仍由用户手动关机。
- 本文件记录实际子成果，P2-A完整验收仍须TripoSR两例、新候选至少一例及独立读回；人工复核单独记录。

## 1.来源与执行环境

- 云端代码基线056e4df90a981d0d971e9534be8fe1b4102c7b8c；辅助安装文件由本机5d69309后的工作树上传，不能将基线提交当作本轮全部脚本内容。
- RTX4090D24564MiB、16核CPU配额、80GiB内存，Ubuntu22.04.4，驱动580.76.05、nvcc12.4.131；数据盘100G。恢复查询GPU0MiB，数据盘已用11G。
- 固定官方源码和模型revision以[来源计划](../locks/p2a-source-plan.json)为准；本轮浅取TRELLIS.2及依赖的固定提交/子模块成功，完整版本纳入精简证据。
- 三套环境位于云端项目的runtime/envs/triposr、trellis2、probe；权重/缓存/构建放数据盘。Windows的历史环境未复制到Linux。

## 2.公开权重与访问缺项

- 9份公开大文件共16644709244字节全部下载并通过官方元数据的SHA256核验，下载步骤退出0；其中3份复用了暂停前的partial。
- TripoSR的model.ckpt为1677246742字节，SHA256为429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee。
- TRELLIS.2主模型只获取推理配置/权重，旧TRELLIS只取所需decoder；没有重复下载训练encoder、bin或ONNX副本。
- 用户最新报告DINOv3/RMBG均已获批，并在云端配置只读令牌、权限600；两项官方HEAD均约8.10秒URLError，未取得实际下载验证。随后聊天暴露的令牌已要求撤销重建，秘密不入库。完整TRELLIS.2加载和官方样例未执行。
- 原始下载报告在runs/p2a-20261020-03/public_weights_verified.json；临时签名链接只在被忽略的runs中，未写入公开报告。

## 3.实际验证

| 项目 | 本轮结果 |
| --- | --- |
| CDN续传修改前基线 | 固定测试5项失败，保留实际日志 |
| CDN续传修订后 | 7项通过，含正常续传、错误Range、腐坏partial和完整文件复用 |
| 全部相关离线测试 | tests/unit、tests/contract、tests/p2a共64项通过，0.92秒 |
| TripoSR依赖/扩展 | pip check、CUDA矩阵数值与真实CUDA等值面提取均通过；CXX/CUDA17构建变体 |
| TripoSR两张固定输入 | 2/2通过并独立读回，hamburger13404顶点/26699面，robot19111顶点/38049面 |
| TRELLIS.2环境/扩展 | 时间窗口结束后停止；只有Python前缀，Torch及原生扩展未完成 |
| TRELLIS.2完整加载/官方样例 | 未执行；权限现已验证，但候选环境和受限完整权重仍未完成 |
| 正式比较、质量指标、保留集、打印检查 | 未执行；不属于本轮安装交付 |

离线命令：

```powershell
& runtime/envs/contracts/Scripts/python.exe -m pytest tests/unit tests/contract tests/p2a -q
```

真实模型将继续使用原P0低显存配置：chunk_size2048、mc_resolution128、float32、seed0、已有透明前景。该配置单列为迁移验证，不冒充官方默认配置或P2-B比较。

## 4.问题、交接与人工复核

- P2A-BUG-008～012记录下载续传、OpenCV解析、构建后端缺项和官方PyTorch节点速度问题；每项先保留基线再修订，实际回归范围见[Bug记录](../spec/bug调试文档.md)。
- 本轮主要脚本和实际结果尚未取得用户人工复核；P1的历史结论不覆盖本轮代码。
- P2-A完整阶段尚未验收，P2-B未启动；后续从本轮真实检查点接续，不重跑已经成功的样例、不自动获得新预算。


## 5.TripoSR实际时间、显存与限制

| 输入 | 模型内部总计时 | allocated峰值 | reserved峰值 | 独立读回 |
| --- | --- | --- | --- | --- |
| hamburger | 7.170536秒 | 1939.77MiB | 2346MiB | 有限坐标/合法索引，通过；非封闭 |
| robot | 6.848372秒 | 1940.98MiB | 2346MiB | 有限坐标/合法索引，通过；非封闭 |

内部计时从模型加载开始，不含Python启动与模块导入；不是完整命令的壁钟，也不是nvidia-smi峰值。原始网格均watertight=false，未定标、修复、切片或验证可打印。

[精简证据](p2a-resume-evidence.json)、[真实ExperimentRecord](../evals/results/p2a-20261020-triposr.json)及[Linux依赖](../locks/p2a-triposr-linux.txt)已保存；两份ExperimentRecord通过P1公共Pydantic模型校验。原始日志/GLB本机备份为runs/p2a-20261020-03/verified-results.zip，约0.8MB。

提交前检查：本轮25份授权文件、145处本地文件链接、Python AST/JSON/UTF-8及常见凭据/签名URL模式检查无错误；云端5份Bash脚本经bash -n返回0。主要代码的人工复核仍待完成。

本轮于2026-10-20约14:20:41停止最后一个候选安装进程，退出143；复查本轮活动timeout进程0、GPU0MiB/0%，数据盘100G/已用37G/可用64G。按恢复起点保守计入第二次关机的未知间隔，累计窗口约7186.72秒，未越过原7200秒；这不是GPU实付计费时长。TRELLIS.2仅有Python3.10.22前缀，Torch/triton及原生扩展未安装完成。原始最终日志/网格已备份至runs/p2a-20261020-03/verified-results-final.zip（796869字节/47份文件），没有代用户关机。后续长安装须明确下一轮准备时限，P2-A仍未完整验收、不进入P2-B。

## 6.凭据配置更新与当前停止点

2026-10-20用户通过云端文件编辑保存新令牌；格式核对通过，与旧配置不同，已替换为项目凭据并设置600权限。秘密未输出或入库。两项固定revision的官方config.json HEAD检查分别约8.10秒URLError，仍未取得权限响应；不能据此认定授权失败或下载验证通过。用户随后明确选择“暂不继续安装”，本轮仅配置/检查/归档，没有重新安装、下载权重、运行模型或进入P2-B，也未代关机。


## 7.HF网络子项已完成

2026-10-20，P2A-NET-001完成。官方代理配合官方CA配置解决HF子进程连接；DINOv3/RMBG固定revision均为未认证401、认证配置200、权重Range206，各只读1024字节，探针退出0/4.378秒。11项P2-A离线测试通过（其中新增4项），Bash语法检查返回0。默认直连仍不可用，后续HF命令需用with_hf_network.sh；凭据和签名URL不输出。

实际命令、根因和适用条件见[网络专项报告](HuggingFace网络排查与权限验证.md)。权限通过不改变候选尚未安装完成的状态，其他步骤保持停止。
