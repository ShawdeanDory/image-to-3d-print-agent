export default function MaterialInfo({value}:{value:unknown}){
  if(!value||typeof value!=='object')return null;
  const appearance=value as Record<string,unknown>;
  if(appearance.policy_version!=='official-pbr-v1')return null;
  return <section className="sheet"><h3>处理模型外观</h3><p>{appearance.status==='pbr_rebaked'?'PBR纹理已重烘焙至本次处理网格':'顶点底色'}</p>{appearance.status==='pbr_rebaked'&&<p className="muted">保留底色、粗糙度和金属度纹理，并烘焙法线细节。原始PBR单独保留。</p>}{typeof appearance.texture_size==='number'&&<p>实际纹理：{appearance.texture_size}×{appearance.texture_size}</p>}{typeof appearance.warning==='string'&&<p role="status">{appearance.warning}</p>}{typeof appearance.reason==='string'&&<p className="muted">{appearance.reason}</p>}</section>;
}
