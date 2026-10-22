export default function MaterialInfo({original=false}:{original?:boolean}){
  return original?<section className="sheet"><h3>模型外观</h3><p>显示本次流水线首次导出的GLB，不做二次烘焙。新任务在首次材质导出前进行GPU几何复查；TripoSR保留顶点色（新增点使用近邻颜色近似），TRELLIS.2使用首次PBR属性采样。补洞不保证修正所有结构或眼部外观。</p></section>:null;
}
