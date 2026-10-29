const levels:Record<string,string>={simple:'简单',medium:'中等',complex:'复杂',uncertain:'不确定'};
export default function MeshBudgetInfo({value,original=false}:{value:unknown;original?:boolean}){
  if(!value||typeof value!=='object')return null;
  const budget=value as Record<string,unknown>;
  if(budget.policy_version!=='image-complexity-v1'||typeof budget.target_faces!=='number')return null;
  const target=typeof budget.effective_target_faces==='number'?budget.effective_target_faces:budget.target_faces;
  return <section className="sheet"><h3>{budget.selection_source==='manual'?'手动':'自动'}面数预算</h3><p>图片复杂度：{levels[String(budget.classification)]||'未确定'} · 目标不超过{target.toLocaleString('zh-CN')}面</p><p>{original?'原始交付面数':'交付版本面数'}：{typeof budget.actual_faces==='number'?budget.actual_faces.toLocaleString('zh-CN')+'面':'处理中'}</p>{typeof budget.fallback_reason==='string'&&<p>{budget.fallback_reason}</p>}<p className="muted">手动设置优先；留空依据轮廓与细节密度估计。预算在首次生成导出时应用，后续最多2轮受控修复，未达到目标会说明原因。面数不代表重建准确或打印合格。</p></section>;
}
