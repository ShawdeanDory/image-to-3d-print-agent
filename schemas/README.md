# 公共契约导出

唯一机器可执行定义在[src/image_to_3d_print/schemas](../src/image_to_3d_print/schemas/__init__.py)，契约v1.0.0，Python包版本0.1.0。[JSONSchema](contracts-v1.schema.json)由20个公共模型自动导出，包含`$defs`与`x-public-models`索引。

```powershell
& runtime/envs/contracts/Scripts/python.exe scripts/p1/export_schemas.py
& runtime/envs/contracts/Scripts/python.exe scripts/p1/export_schemas.py --check
```

JSONSchema表达字段、枚举和结构约束；Pydantic跨字段validator、磁盘文件存在、任务引用与预算前置校验仍须执行Python定义。导出成功不代表网格、模型、切片或API已经验证。修改模型后重新导出并运行契约测试，不直接编辑生成文件。
