# 网页PBR环境资源

forest.exr直接复制自已锁定的TRELLIS.2源码：

- 仓库：https://github.com/microsoft/TRELLIS.2
- revision：75fbf0183001ed9876c8dbb35de6b68552ee08bd
- 路径：assets/hdri/forest.exr（官方example.py使用同一文件）
- 原作者：Greg Zaal，PolyHaven；原图：https://polyhaven.com/a/ninomaru_teien
- HDR资源许可：CC0，原仓库说明原文保存在HDRI-LICENSE.txt；仓库MIT许可保存在TRELLIS.2-LICENSE.txt。

浏览器从本地发布资源读取，不在用户查看模型时访问第三方网站。EXR线性HDR经Three.js的PMREM提供PBR环境照明，强度1，无额外定向/半球灯；使用Three.js的ACESFilmic色调映射和sRGB输出。官方CUDA渲染器采用自己的ACES近似、gamma2.2、SSAO等，网页不是该渲染器移植，效果尚待用户验证，不宣称逐像素相同。坐标与经度旋转见ModelView.tsx。
