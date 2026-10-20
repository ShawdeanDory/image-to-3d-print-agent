# 环境版本与交接

## P2-A云端安装准备

2026-10-20恢复安装后，TripoSR的pip check、CUDA扩展和两张固定图片已通过；实际Linux依赖为[p2a-triposr-linux.txt](p2a-triposr-linux.txt)，conda来源清单为[p2a-triposr-conda-linux.txt](p2a-triposr-conda-linux.txt)。torchmcubes使用固定源码的独立C++17构建变体，准确步骤见[安装手册](../doc/P2-A云端安装与验证手册.md)；TRELLIS.2未完成，不能将其来源计划视为已验证环境锁。P0的Windows历史快照保持。

## P1本机CPU契约环境

2026-10-19实际使用Windows、Python3.11.17、Pydantic2.12.5、pytest8.4.2、Pillow10.1.0；精确传递依赖见[p1-contracts.txt](p1-contracts.txt)。Pydantic用于输入/结果校验，pytest用于离线回归，Pillow只读取fixture格式和尺寸；没有torch、模型库或GPU需求，不改P0环境。

在项目根目录准备独立环境；若队友已有Python3.11，可将--python替换为其解释器绝对路径。依赖安装需要网络，安装完成后下面3项检查均离线运行。

```powershell
& runtime/tools/uv/uv.exe venv --python runtime/envs/probe/Scripts/python.exe runtime/envs/contracts
& runtime/tools/uv/uv.exe pip install --python runtime/envs/contracts/Scripts/python.exe -r locks/p1-contracts.txt
& runtime/envs/contracts/Scripts/python.exe -m pytest tests/unit tests/contract -q
& runtime/envs/contracts/Scripts/python.exe scripts/p1/export_schemas.py --check
& runtime/envs/contracts/Scripts/python.exe scripts/p1/check_prepared_data.py
```

接手机器只做P1时无需重建下方GPU环境或下载模型。上述解释器路径是Windows格式；Linux接手使用自己的Python3.11虚拟环境，重新运行检查，不假定本机结果已覆盖Linux。

## P0历史快照

本目录是2026-10-18实际环境的版本快照。所有命令在项目根目录运行；接手机器先核对Windows、NVIDIA驱动和MSVC工具，再重新验证，不能只复制“通过”结论。

- `p0-runtime.json`：模型、上游源码、Blender及切片工具的准确版本。
- `p0-reconstruction.txt`：实际CUDA重建环境依赖；torchmcubes需按下述固定源码单独构建，不从不明轮子替代。
- `p0-probe.txt`：独立读取网格的轻量环境，避免用生成过程自身的读回作为唯一证据。
- `p0-build-cpu.txt`：同一PyTorch2.5.1的CPU构建环境，仅用于torchmcubes，不运行神经重建。

## 准备工具与源码

本次使用项目内uv0.13.1，从[官方发布页](https://github.com/astral-sh/uv/releases/tag/0.13.1)获取Windows压缩包，解压后可执行文件位于`runtime/tools/uv/uv.exe`。不修改系统默认Python或注册表。

```powershell
$env:UV_CACHE_DIR="$PWD/runtime/cache/uv"
$env:UV_PYTHON_INSTALL_DIR="$PWD/runtime/python"
$env:UV_LINK_MODE='copy'
$env:PYTHONIOENCODING='utf-8'
& runtime/tools/uv/uv.exe python install 3.11.17 --install-dir runtime/python --no-bin --no-registry
& runtime/tools/uv/uv.exe venv --python 3.11.17 --seed runtime/envs/reconstruction
& runtime/tools/uv/uv.exe venv --python 3.11.17 --seed runtime/envs/probe
& runtime/tools/uv/uv.exe venv --python 3.11.17 --seed runtime/envs/build-cpu
```

在首次交接的空环境中克隆以下仓库至对应目录，再检出`p0-runtime.json`中的完整提交：

| 仓库 | 本地位置 |
| --- | --- |
| <https://github.com/VAST-AI-Research/TripoSR> | `runtime/upstream/TripoSR` |
| <https://github.com/tatsy/torchmcubes> | `runtime/upstream/torchmcubes` |
| <https://github.com/blender/blender-addons> | `runtime/upstream/blender-addons` |

TripoSR权重与配置从`https://huggingface.co/stabilityai/TripoSR/resolve/<模型revision>/<文件名>`获取，保存为`weights/TripoSR/model.ckpt`与`config.yaml`。本次权重1677246742字节，revision见JSON；不使用浮动main替代。DINO只需要454字节的`config.json`，并不另载DINO权重。

便携工具来源和解压目录：

- [Blender4.5.14官方压缩包](https://download.blender.org/release/Blender4.5/blender-4.5.14-windows-x64.zip)，解压至`runtime/tools/blender/`。
- [PrusaSlicer2.9.6官方发布](https://github.com/prusa3d/PrusaSlicer/releases/tag/version_2.9.6)，Windows压缩包解压至`runtime/tools/prusaslicer/`，保留`PrusaSlicer-2.9.6/`层级。

## 安装锁定依赖和扩展

```powershell
& runtime/tools/uv/uv.exe pip install --python runtime/envs/reconstruction/Scripts/python.exe --index https://download.pytorch.org/whl/cu121 --index-strategy unsafe-best-match -r locks/p0-reconstruction.txt
& runtime/tools/uv/uv.exe pip install --python runtime/envs/probe/Scripts/python.exe -r locks/p0-probe.txt
& runtime/tools/uv/uv.exe pip install --python runtime/envs/build-cpu/Scripts/python.exe --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match -r locks/p0-build-cpu.txt
& runtime/envs/build-cpu/Scripts/python.exe scripts/p0/build_torchmcubes.py
```

本机构建脚本使用Visual Studio2022Community的已核对路径。换机器若安装路径不同，先记录环境差异并调整路径，不宣称原记录已覆盖另一台机器。原生扩展在CPU2.5.1环境编译，安装到CUDA2.5.1环境；上游代码原样保留。实际兼容性以两张图的CUDA验证为准。没有CUDA编译器时，神经网络仍用GPU，只有等值面提取使用CPU。

## 固定DINO配置缓存

在重建环境中先运行以下准备代码。它用固定revision下载配置并建立离线缓存的main引用；后续验证脚本启用`HF_HUB_OFFLINE=1`，不会在推理时获取浮动模型版本。

```python
import os
from pathlib import Path
root = Path.cwd()
os.environ['HF_HOME'] = str(root / 'runtime/cache/huggingface')
from huggingface_hub import hf_hub_download
revision = 'f205d5d8e640a89a2b8ef0369670dfc37cc07fc2'
config = Path(hf_hub_download('facebook/dino-vitb16', 'config.json', revision=revision))
refs = config.parents[2] / 'refs'
refs.mkdir(exist_ok=True)
(refs / 'main').write_text(revision, encoding='utf-8')
```

实际验证命令、结果及人工复核入口见[P0验证报告](../doc/P0环境与工具验证.md)。本目录不承诺跨系统、跨PyTorch版本或跨显卡的二进制兼容；交接后运行同组固定样例确认。
