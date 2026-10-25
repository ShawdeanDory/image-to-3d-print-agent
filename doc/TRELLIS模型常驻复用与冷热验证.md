# TRELLIS.2模型常驻复用与冷热验证

## 1.本轮变化与使用方式

本轮MID-RESIDENT-001将TRELLIS.2快速入口从每任务新进程/重新加载权重，改为单worker持有的串行模型进程。首次图片懒加载固定pipeline，后续图片复用同一对象和权重，仍独立预处理、推理、解码、生成网格与首次PBR导出。输入、任务目录及GLB仍属于本次请求，不返回上次模型作为新结果。

同一AutoDL部署的新任务只启用TRELLIS.2；已有TripoSR任务、产物及幂等重试保持，源码和环境没有删除。原桌面启动器/SSH配置继续使用，不需新增密钥或网页参数；后台单worker启动监听，第一张图才加载模型。页面用实际model.resident显示“常驻模型首次加载”或“已复用常驻模型”。原始PBR下载、手动/自动面数、2048默认/4096可选、GLB保材质检查及打印门槛保持。

## 2.固定输入、环境与比较口径

- 基线代码：dc549d46e7a6fa82c87a29c1bfbe62ccb1b03d14；同实例RTX4090D24564MiB、16核/80GiB。模型Python3.10，backend Python3.11，复用原环境/权重，无安装或训练。
- 固定上游：TRELLIS.2的75fbf0183001ed9876c8dbb35de6b68552ee08bd；仍调用原preprocess_image和pipeline.run，没有改变最长边或背景处理。
- 图片：已用于开发的910×609鸭子JPEG，SHA256为1d6ac093c18648fc9568f58e310db3d1666d942cb0a2ea36b21be8384993f4ff。非新数据、非最终保留集。
- 三次固定相同1024_cascade/seed42、目标100000面/纹理2048、GPU受控边界修复开关开启、不生成转台视频。每次独立目录和真实产物；目标面数不冒充实际面数。
- 用调用方壁钟比较：逐任务包含解释器/导入/进程退出，驻留请求包含IPC、首请求导入或热请求、推理导出及临时内存回收。模型内分段为CUDA同步后的独立区间，两者不混为同一计时范围。
- 历史171.8秒和99.2秒仅作问题来源，不拿算术72.6秒当保证。冷热各1次不是统计性能基准；系统文件缓存、CUDA/JIT初始化和机器波动也会影响速度。

## 3.真实GPU结果

| 同配置调用 | 调用方壁钟 | 加载与准备 | 推理与解码 | 重网格/UV/纹理 | 实际面数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 旧逐任务冷启动 | 174.732秒 | 103.293844秒 | 42.753秒 | 22.217秒 | 99495 |
| 驻留首次冷请求 | 176.614秒 | 106.311242秒 | 44.209秒 | 23.427秒 | 98921 |
| 同进程第二次热请求 | 68.903秒 | 0.000469秒 | 41.941秒 | 24.836秒 | 99391 |

第二次热请求比旧逐任务路径缩短60.57%，同进程冷到热缩短约61%。驻留两次PID7130、instance_id相同，request_index为1/2、weight_load_count均为1。热请求加载准备约0.000469秒，推理仍约41.94秒，不是跳过生成。第一轮兼容失败前另取得175.423秒旧路径基线，保留在原目录，不替换本表的修订后同轮比较。

三份GLB均独立读回：有限坐标/UV、有效索引、底色和金属度/粗糙度PBR纹理，两张2048×2048嵌入图像可解码；检查GLB与各自原始GLB的材质参数和贴图字节相同。三份backend_input.png摘要相同，未因驻留改变图片预处理。面数/字节并非逐次相同，不能将相同seed当GPU/重网格逐位确定性保证；本轮没有外观质量消融或统计显著性结论。

两次完成后驱动GPU占用465MiB，pipeline存活、PyTorch allocated约8.17MiB；这不是模型全部权重仅占8MiB，而是low_vram模式大部分权重保存在CPU。停止所属benchmark模型进程后GPU为0MiB/0%。生产新worker仅懒监听、尚未处理图片，发布后也是0MiB；用户下一张仍是首次冷加载，之后连续生成才能复用。

[精简实证](evidence/resident-20261025/result.json)。完整结果在云端runs/resident-20261025-01/gpu-benchmark-fixed/result.json；原始失败轮次gpu-benchmark保持。实际只调用模型工具，没有新的LLM/API生产任务或完整打印链。


## 4.资源、停止与错误行为

保持官方low_vram分阶段CPU/GPU迁移策略。常驻复用指pipeline和权重在进程中复用，并不强行让全部权重永久占用24GB显存；每阶段仍可能发生CPU→GPU传输。等待和任务正常结束后释放执行槽与临时张量，但保留模型缓存，空闲RAM/显存可能非零。实际占用以快照为准。

单worker取得独占锁后启动模型监听，套接字0700目录/0600文件，无新增TCP或公网端口。固定协议校验同UID/真实请求PID及启动身份、同任务目录/输入摘要/固定源码，不接受任意命令或越界路径。失败不切回TripoSR、不自动用逐任务进程重试同一请求。

活动任务取消、超时或请求进程丢失会回收模型进程；worker正常退出、异常丢失也会回收。失败任务保留日志/已有文件，下一任务才可重新冷启动。页面等待时取消一个已停止计算的任务不会伪造GPU正在运行。关机/worker重启后缓存消失，下一张重新加载；仍由用户自行关机。

内部兼容字段与执行码范围见[接口与字段](接口与字段.md#trellis-resident-v1内部兼容协议2026-10-25)。exit_code=0表示本次驻留请求成功，process_exit_code=null明确模型进程仍存活；不是伪造退出码。模型服务不继承DeepSeek/HF令牌，不运行新的LLM请求。

## 5.实现、验证命令与限制

主要代码：[模型入口](../scripts/tools/resident_model_worker.py)、[pipeline缓存](../scripts/tools/model_worker.py)、[固定协议](../src/image_to_3d_print/adapters/resident_protocol.py)、[服务端](../src/image_to_3d_print/adapters/resident_server.py)、[客户端](../src/image_to_3d_print/adapters/resident.py)、[worker归属](../src/image_to_3d_print/jobs/model_pool.py)、[任务worker](../src/image_to_3d_print/jobs/worker.py)、[创建策略](../src/image_to_3d_print/jobs/service.py)、[实测脚本](../scripts/tools/benchmark_resident.py)。

```powershell
$env:PYTHONUTF8='1'
& runtime/envs/backend/Scripts/python.exe -m pytest tests/geometry tests/contract tests/unit tests/workflow/test_resident_policy.py tests/workflow/test_fast_profile.py -q
& runtime/envs/backend/Scripts/python.exe -m pytest tests/workflow -q --tb=short
& runtime/envs/backend/Scripts/python.exe -m pytest tests/measurement tests/evaluation -q
cd frontend
npm run build
npm test -- --reporter=dot
```

云端使用同一组本地固定测试，额外执行Linux进程组/SO_PEERCRED/Unix IPC回归。引擎替身只在tests/geometry/resident_fixture_server.py中，标记test_fixture；生产入口没有假引擎选项。不同输入摘要、复用、取消/超时退出72、父进程丢失退出71、执行异常不重试等固定结果不能冒充真实GPU生成或整套Agent通过。

本轮检查：Windows相关167通过/10平台跳过，Linux相关177通过；Windows测量/评估及新协议/策略37通过/1平台跳过；前端6通过、TypeScript/Vite构建完成（保留原大包提示）。完整工作流52通过/11旧失败，失败集合与上轮隔离基线一致，新增2项通过；不声称全套通过。

真实比较入口：在隔离代码目录使用backend环境运行scripts/tools/benchmark_resident.py，传--root、--input和一个全新--output目录。测试脚本自己启动/收尾所属驻留进程，不复用生产数据库；完整命令与日志在runs/resident-20261025-01/benchmark-fixed.sh及benchmark-fixed.log。生产发布前备份既有相关文件、配置及SQLite，更新11份文件；33个旧任务状态保持，9取消/1失败/20成功/3等待。API和独立单worker已恢复，模型懒监听已就绪；重复调用原启动辅助器返回already_running，没有第二worker。GET配置仅TRELLIS.2、course_fast，未提交新生产任务。

首次失败：模型Python3.10不支持hashlib.file_digest，在真实驻留加载前退出，修订为分块SHA256并新增兼容回归；Linux验证包缺历史资料9项失败，补齐原样资料后通过。旧工作流原有11项失败保持，不通过改打印语义或测试替身掩盖；详情见[Bug记录](../spec/bug调试文档.md)。

本轮没有新增LLM调用、新图片完整Agent/打印/切片测试、最终保留集或泛化质量评估，也没有修改图片预处理、重建权重、材质修正及补洞算法。性能提高不代表眼睛、厚度或大洞质量得到改善。原GLB检查保材质任务的待人工状态保持。

完整结果备份42文件/39561823字节已下载本机，ZIP的CRC和SHA256核对通过；权重、环境、私钥/API密钥及生产SQLite不包含在该结果包。最终源码/记录UTF-8、Python AST、JSON、本地文档链接、常见凭据模式与Git空白检查通过；检查器首次误判旧合法括号链接后修正，未修改原课程规范。

## 6.人工复核清单与结论

请核对本报告的实际冷热计时/同配置、主要代码及产物读回证据；关注同PID/实例、加载次数1、每图独立输出、取消/超时/worker退出回收及首次仍冷加载。新任务仅TRELLIS.2，旧TripoSR任务不被改写；复用不是跳过推理或返回旧GLB。

人工复核：待用户反馈。AI检查、固定替身和真实GPU工具结果分别记录，不能写成人工通过；此开发复核也不代表模型打印合格。按现有授权完成记录与Git同步，不自动进入下一项。
