export default function MaterialInfo({original=false,printCopy=false}:{original?:boolean;printCopy?:boolean}){
  if(printCopy)return <section className="sheet"><h3>打印副本与原始外观</h3><p>自动打印修复适用于100～150mm高的简单摆件。打印副本允许必要重网格、填实内腔和有限厚度补偿/底部切平，不含原UV/PBR，以单色显示；原始彩色GLB完整保留，可切换预览及单独下载。没有重烘焙。检查失败或未执行仍会明确列出；实际颜色由打印机与耗材决定。</p></section>;
  return <section className="sheet"><h3>模型外观</h3><p>{original?'此历史任务交付首次导出的原始GLB，检查和定标在副本上执行。':'交付经过清理、毫米定标和复检的版本，保留已有UV、PBR材质及贴图，不重烘焙。新增补片没有原始纹理依据，报告会单独注明。'}补洞不保证修正所有结构或眼部外观；原始文件始终保留。</p></section>;
}
