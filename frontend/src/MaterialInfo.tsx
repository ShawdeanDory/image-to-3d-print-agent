export default function MaterialInfo({original=false,enhanced=false}:{original?:boolean;enhanced?:boolean}){
  return original?<section className="sheet"><h3>模型外观</h3><p>{enhanced?'当前显示独立的眼部底色修正副本；模型几何、UV及其余材质保持，原始GLB另存。':'显示本次流水线首次导出的GLB，不做二次烘焙。'}新任务在首次材质导出前进行GPU几何复查；TripoSR保留顶点色，TRELLIS.2保留PBR。局部改色不能修正错误的眼眶几何，也不代表打印合格。</p></section>:null;
}
