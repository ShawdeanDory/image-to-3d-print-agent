# 造物工坊前端

React/TypeScript/Vite与Three.js。默认连接真实API，不内置模拟进度或演示模型。模型、报告和确认均引用同一任务登记的产物。

## 启动

Node24.14.1/npm11.11.0已验证，依赖版本固定在package-lock.json。首次：

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

打开http://127.0.0.1:5173。API默认http://127.0.0.1:8000。连接现有云端时，在另一个项目根目录终端建立隧道：

```powershell
ssh -F runtime/ssh/p2a_config -N -L 8000:127.0.0.1:8000 p2a-autodl
```

换电脑须使用自己的授权SSH配置，不复制私钥。两个云端服务须已启动，见[后端说明](../doc/Agent后端调用与启动说明.md)。也可在启动Vite前设置I3D_API_TARGET为实际本地隧道地址。该值仅在Vite服务侧使用，不写入前端构建产物。没有公网发布或新增端口映射。

页面访问保护的令牌只在当前页面内存；DeepSeek/HF密钥不进入浏览器。服务不可达显示明确错误，不自动换模型或机器。生产静态文件由npm.cmd run build生成，若另行部署静态服务器，须把/api反向代理到同一真实API；当前仅验证Vite开发/预览服务。

## 验证

```powershell
npm.cmd test
npm.cmd run build
npm.cmd run test:browser
```

浏览器回归使用本机Edge和Playwright配套FFmpeg。先在根目录启动固定服务：

```powershell
runtime/envs/backend/Scripts/python.exe tests/frontend/serve_fixture.py --root runs/新的浏览器验证目录
```

另一个终端启动前端，目标设为该测试API：

```powershell
$env:I3D_API_TARGET='http://127.0.0.1:8001'
npm.cmd run dev
```

该固定服务真实运行API/SQLite/工作流/CPU几何，但重建与Blender返回测试替身，页面有test_fixture横幅，不能作为真实模型或实际切片通过证据。测试不会默认调用云端/API。已有云端真实页面验证入口tests/real-cloud.mjs必须显式设置I3D_REAL_CLOUD=1，只能在获授权且隔离test_fixture服务已启动时使用，不可对人工服务自动提交确认。

类型由公共Schema自动生成，在根目录运行python scripts/tools/export_frontend_types.py --check核对；不能手改contracts.generated.ts。公共状态、等待项及最终门槛仍由后端定义。

输入约束、刷新恢复、幂等、模型对比、逐项报告和切片提交说明见[前端与评估交付](../doc/初步前端与评估交付.md)。

2026-10-21实际官方推理更新见[报告](../doc/官方推理对齐与自动图片准备.md)：图片准备默认自动继续，原图送官方入口；PLY保留顶点色，GLB使用原材质和服务端轴向。官方外观可在“当前模型”中选择原始GLB；打印版本和确认门槛仍独立。现有本机5173使用9000隧道时保持原I3D_API_TARGET配置，不重复占用同一端口。自动政策浏览器回归需在独立fixture加--input-policy automatic，并设置I3D_AUTOMATIC_BROWSER=1及新的I3D_BROWSER_EVIDENCE_DIR，避免覆盖历史证据。
