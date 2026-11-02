export default function MaterialInfo({original=false,printCopy=false}:{original?:boolean;printCopy?:boolean}){
  if(printCopy)return <section className="sheet"><h3>最终修复模型外观</h3><p>最终GLB与STL使用同一份已检查的修复几何。GLB将原贴图/PBR映射到修复表面，未重烘焙；补洞和加厚位置的颜色为近似。STL不含颜色，实际打印颜色由设备和耗材决定。原件与中间版本仅后台保存。</p></section>;
  return <section className="sheet"><h3>模型外观</h3><p>{original?'此历史任务交付首次导出的原始GLB，检查和定标在副本上执行。':'交付经过清理、毫米定标和复检的版本，保留已有UV、PBR材质及贴图，不重烘焙。新增补片没有原始纹理依据，报告会单独注明。'}补洞不保证修正所有结构或眼部外观；原始文件始终保留。</p></section>;
}
