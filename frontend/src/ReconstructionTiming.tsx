const names: Record<string,string>={load_and_prepare:'加载与准备',preprocess:'图片预处理',inference:'模型推理',native_export:'原生网格保存',geometry_uv_texture_export:'重网格、UV与纹理导出',independent_readback:'独立读回',total:'重建工具合计'};
export default function ReconstructionTiming({value}:{value:unknown}){
  if(!value||typeof value!=='object')return null;
  const metrics=value as Record<string,unknown>;
  const seconds=metrics.seconds&&typeof metrics.seconds==='object'?metrics.seconds as Record<string,unknown>:{};
  const resident=metrics.resident&&typeof metrics.resident==='object'?metrics.resident as Record<string,unknown>:null;
  return <section className="sheet"><h3>本次重建用时</h3><p>{metrics.inference_profile==='course_fast'?'快速生成':'官方/历史模式'}{resident?resident.model_reused===true?' · 已复用常驻模型':' · 常驻模型首次加载':''}</p><dl>{Object.entries(names).map(([key,label])=><div key={key}><dt>{label}</dt><dd>{typeof seconds[key]==='number'&&Number.isFinite(seconds[key])?(seconds[key] as number).toFixed(2)+'秒':'未记录'}</dd></div>)}</dl><p className="muted">用时为实际完成记录，仅包含重建工具内部步骤，后续检查与修复另计。网页按服务端交付记录选择GLB，保留已有材质，不重烘焙。{resident?'复用的是模型权重，每张图片仍会重新推理；首次启动、取消或服务重启后需要重新加载。':''}</p></section>;
}
