import type {ReactNode} from 'react';
export type PreviewAction='in'|'out'|'rotate'|'wireframe'|'reset'|'snapshot'|'environment'|'lighting';
const paths:Record<PreviewAction|string,ReactNode>={
  in:<><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5M7 10h6M10 7v6"/></>,
  out:<><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5M7 10h6"/></>,
  rotate:<><path d="m8 5 4-2 4 2v5l-4 2-4-2zM12 7v5M8 5l4 2 4-2M20 8c3 6-9 12-16 6M4 10v4h4"/></>,
  wireframe:<><path d="m12 3 8 5v9l-8 5-8-5V8zM4 8l8 5 8-5M12 13v9M12 3v10"/></>,
  reset:<><path d="M4 11a8 8 0 1 1 2 7M4 4v7h7"/></>,
  snapshot:<><path d="M3 7h5l2-3h4l2 3h5v13H3z"/><circle cx="12" cy="13" r="4"/></>,
  environment:<><circle cx="12" cy="12" r="4"/><path d="M12 1v3M12 20v3M1 12h3M20 12h3M4 4l2 2M18 18l2 2M4 20l2-2M18 6l2-2"/></>,
  lighting:<><path d="m9 4 8 5-5 8-8-5zM12 17v4M7 21h10M17 9l4-3M7 6 4 3"/></>,
  fullscreen:<path d="M9 3H3v6M3 3l7 7M15 21h6v-6M21 21l-7-7"/>,
};
export function ViewerIcon({name}:{name:string}){return <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;}

export default function PreviewToolbar({disabled,rotate,wireframe,background,onAction,onBackground}:{
  disabled:boolean;rotate:boolean;wireframe:boolean;background:string;onAction:(value:PreviewAction)=>void;onBackground:(value:string)=>void;
}){
  const buttons:[PreviewAction,string][]=[['in','放大'],['out','缩小'],['rotate','自动旋转'],['wireframe','线框模式'],['reset','重置视图'],['snapshot','截图'],['environment','切换环境'],['lighting','光照配置']];
  return <div className="result-tools" role="toolbar" aria-label="模型预览工具栏">
    {buttons.map(([action,label])=><button key={action} type="button" aria-label={label} title={label} disabled={disabled}
      aria-pressed={action==='rotate'?rotate:action==='wireframe'?wireframe:undefined} onClick={()=>onAction(action)}><ViewerIcon name={action}/></button>)}
    <label className="result-color" title="选择背景色"><span style={{backgroundColor:background}}/>
      <input type="color" aria-label="背景颜色" value={background} disabled={disabled} onInput={event=>onBackground(event.currentTarget.value)} onChange={event=>onBackground(event.target.value)}/></label>
  </div>;
}
