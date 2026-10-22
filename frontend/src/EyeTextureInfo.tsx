export default function EyeTextureInfo({value,enabled}:{value:unknown;enabled:boolean}){
  if(!value||typeof value!=='object')return null;
  const eye=value as Record<string,unknown>;
  const status=String(eye.status||'');
  const details=eye.details&&typeof eye.details==='object'?eye.details as Record<string,unknown>:{};
  return <section className="sheet"><h3>眼部局部贴图试用</h3>
    <p>{!enabled?'后台已关闭试用，当前预览和主下载使用原始GLB。':status==='applied'?'已生成局部修正版，视觉效果待你检查。':status==='failed'?'处理失败，保留原始GLB。':'未应用修正，保留原始GLB。'}</p>
    <p className="muted">{String(eye.reason||'没有处理证据')}</p>
    {status==='applied'&&<p className="muted">只改变眼部底色，修改纹素：{typeof details.modified_texels==='number'?details.modified_texels:'未知'}。几何、UV和其他材质保持；不会修正眼眶结构。</p>}
  </section>;
}
