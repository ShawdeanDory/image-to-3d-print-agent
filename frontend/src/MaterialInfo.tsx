export default function MaterialInfo({original=false}:{original?:boolean}){
  return original?<section className="sheet"><h3>原始模型外观</h3><p>直接使用模型生成的原始GLB，不重烘焙、不重建UV、不替换材质。TripoSR保留其真实顶点色，TRELLIS.2保留原始PBR。</p></section>:null;
}
