export default function GPURepairInfo({value}:{value:unknown}){
  if(!value||typeof value!=='object')return null;
  const result=value as Record<string,unknown>;
  const number=(v:unknown)=>typeof v==='number'?String(v):'未知';
  const status=result.status==='applied'?'已应用受控补片':result.status==='failed'?'工具失败，保留原几何':'未应用补片';
  return <section className="sheet"><h3>GPU几何复查与补片</h3><p>{status}。首次材质导出前执行，未进行二次烘焙。开放边界：{number(result.boundary_before)}→{number(result.boundary_after)}；补片：{number(result.added_patches)}处；实际尝试：{number(result.attempts)}轮。</p><p className="muted">{String(result.warning||'检查记录尚未完整返回。')}</p><p className="muted">边界减少不等于所有缺口消失；异常拓扑和带内壁的错误缺口仍可能需要局部结构补全。</p></section>;
}
