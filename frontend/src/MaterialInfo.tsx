export default function MaterialInfo({original=false}:{original?:boolean}){
  return <section className="sheet"><h3>模型外观</h3><p>{original?'此历史任务交付首次导出的原始GLB，检查和定标在副本上执行。':'交付经过清理、毫米定标和复检的版本，保留已有UV、PBR材质及贴图，不重烘焙。新增补片没有原始纹理依据，报告会单独注明。'}补洞不保证修正所有结构或眼部外观；原始文件始终保留。</p></section>;
}
