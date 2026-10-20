# HuggingFace网络排查与权限验证

- 日期：2026-10-20；任务P2A-NET-001，仅完成P2-A剩余清单第1步。
- 结论：通过AutoDL官方代理及其配套CA，云端已验证DINOv3和RMBG的实际文件访问权限。原来的默认直连路径仍不可用，后续HF命令须使用本报告的包装入口。
- 本轮未安装依赖、未下载完整权重、未运行模型，P2-A尚未完整验收，不进入P2-B。

## 1.修改前基线与定位

| 检查 | 实际结果 | 意义 |
| --- | --- | --- |
| 云端默认解析huggingface.co | 103.42.176.244，TCP连接被拒绝 | 请求尚未到达权限判断阶段 |
| PyPI和HF权重CDN直连 | TCP/TLS均正常 | 实例并非完全不能联网 |
| 本机可信DoH查询的4个HF地址 | 云端TCP可连，TLS均被重置 | 只换DNS地址不足以解决 |
| 只向进程传入平台代理 | 证书链校验失败，verify_code=19 | 配置不完整，不能关闭校验来掩盖 |
| 同一代理配合系统CA文件 | HF首页HEAD200，约0.93秒 | 配套CA能解决该代理连接的证书链问题 |
| 完整加载官方网络配置的curl | HTTP200、ssl_verify_result=0 | 官方代理和CA配置一起使用可行 |

`/etc/network_turbo`不仅提供http_proxy/https_proxy，还提供SSL_CERT_FILE与REQUESTS_CA_BUNDLE。先前诊断只提取代理变量，遗漏了CA配置。本次未手动改系统DNS、hosts或系统信任库，也未关闭TLS/主机名校验。

原始脱敏诊断保存在本机runs/p2a-net-20261020-01；[精简证据](p2a-hf-network-evidence.json)包含修改前基线、CA对照和实际权限回归。

## 2.两个受限仓库的真实访问结果

| 模型 | 固定revision | 未认证配置HEAD | 认证配置GET | 认证权重Range |
| --- | --- | --- | --- | --- |
| facebook/dinov3-vitl16-pretrain-lvd1689m | ea8dc2863c51be0a264bab82070e3e8836b02d51 | 401 | 200，745字节，有效JSON | 206，读取1024字节 |
| briaai/RMBG-2.0 | 5df4c9c76d8170882c34f6986e848ee07fd0ba43 | 401 | 200，405字节，有效JSON | 206，读取1024字节 |

两次权重请求的Content-Range分别为bytes 0-1023/1212559808与bytes 0-1023/884878856，最终响应来自us.aws.cdn.hf.co。只读取了开头1KiB，没有保存或下载完整权重，也没有加载模型。

探针实际退出码0、壁钟4.378秒，stderr为空。该结果证明本次云端凭据对上述固定版本文件具有实际读取权限；不再仅依据网页获批提示或令牌文件存在推断。

## 3.可复用的云端命令

在云端项目目录执行：

```bash
cd /root/autodl-tmp/image-to-3d-print-agent
bash scripts/p2a/with_hf_network.sh /root/miniconda3/bin/python scripts/p2a/check_hf_permissions.py --report runs/hf-permissions.json
```

- [with_hf_network.sh](../scripts/p2a/with_hf_network.sh)完整加载官方网络配置，仅作用于传入命令的子进程；不依赖本机转发服务。
- [check_hf_permissions.py](../scripts/p2a/check_hf_permissions.py)使用标准库与已存在的云端凭据，检查固定版本配置和1KiB权重Range；不安装包、不执行仓库模型代码。
- 以后获准执行HF下载时，用相同包装入口启动对应下载命令及参数。新的裸SSH终端不会自动继承本次子进程设置。
- 不要只复制代理变量而遗漏配套CA；包装入口发现CA不可读时会停止，不通过忽略证书校验继续。

本轮检查已经完成，当前未留下后台代理或安装进程，也未代用户关机。

## 4.验证与归档

修改前保留真实DNS/TCP/TLS和证书错误基线，随后才增加最小包装入口与权限探针。公共Pydantic业务契约及模型版本不变，网络证据使用内部JSON报告，不冒充模型ExperimentRecord。

新增4项离线测试覆盖跨域移除Authorization、拒绝非官方HTTPS重定向、服务器忽略Range时不读取整文件，以及成功Range只读取1KiB。与既有续传测试一起运行：

```powershell
& runtime/envs/contracts/Scripts/python.exe -m pytest tests/p2a -q
```

实际11项通过/0.20秒；云端包装脚本bash -n返回0。凭据和临时签名URL不输出、不入库；应用层跨域跳转会移除Authorization。主要新脚本与结果的人工复核仍待完成。

相关记录：P2A-BUG-013、P2A-EVAL-005、AI-014及当前任务。第2步依赖安装、完整受限权重下载、模型加载/官方样例和P2-A人工验收仍未完成。

官方认证规则参考：[HuggingFace受限模型文件访问](https://huggingface.co/docs/hub/models-gated#download-files)。本次通过实际401→200/206对照验证权限。

提交前检查：本轮14份授权文件、113处本地文件链接及Python AST/JSON/UTF-8/常见凭据模式检查无错误，git diff --check通过。
