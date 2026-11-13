import {checkNames} from './domain';

export function printNotice(status:string|undefined,checks:{name:string;status:string}[]){
  if(status==='passed')return '几何检查通过；仍需按实际打印机切片并核对支撑，尚未实物打印。';
  const unresolved=checks.filter(c=>c.status==='fail'||c.status==='not_run')
    .map(c=>(checkNames[c.name]||c.name)+(c.status==='not_run'?'未执行':'失败')).join('、');
  return (status==='failed'?'打印检查未通过':'打印检查未完整执行')+'：'+(unresolved||'尚无完整检查证据')+'。可以预览和下载当前模型，送印前请处理上述问题。';
}

export default function DeliveryDownloads({busy,stlAvailable,onGLB,onSTL}:{
  busy:boolean;stlAvailable:boolean;onGLB:()=>void;onSTL:()=>void;
}){
  return <div className="actions"><button className="primary" disabled={busy} onClick={onGLB}>下载GLB</button>
    <button disabled={busy||!stlAvailable} onClick={onSTL}>下载模型STL</button></div>;
}
