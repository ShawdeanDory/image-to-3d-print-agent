const levels:Record<string,string>={simple:'简单',medium:'中等',complex:'复杂',uncertain:'不确定'};
export default function MeshBudgetInfo({value}:{value:unknown}){
  if(!value||typeof value!=='object')return null;
  const budget=value as Record<string,unknown>;
  if(budget.policy_version!=='image-complexity-v1'||typeof budget.target_faces!=='number')return null;
  return <section className="sheet"><h3>自动面数预算</h3><p>图片复杂度：{levels[String(budget.classification)]||'未确定'} · 目标不超过{budget.target_faces.toLocaleString('zh-CN')}面</p><p>实际交付：{typeof budget.actual_faces==='number'?budget.actual_faces.toLocaleString('zh-CN')+'面':'处理中'}</p>{typeof budget.fallback_reason==='string'&&<p>{budget.fallback_reason}</p>}<p className="muted">依据轮廓与细节密度估计，减面后验证形状和网格缺陷。面数不代表重建准确或打印合格。</p></section>;
}
