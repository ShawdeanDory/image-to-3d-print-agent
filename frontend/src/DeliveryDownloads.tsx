import {checkNames} from './domain';

export function printNotice(status:string|undefined,checks:{name:string;status:string}[]){
  if(status==='passed')return '几何检查通过；仍需按实际打印机切片并核对支撑，尚未实物打印。';
  const unresolved=checks.filter(c=>c.status==='fail'||c.status==='not_run')
    .map(c=>(checkNames[c.name]||c.name)+(c.status==='not_run'?'未执行':'失败')).join('、');
  return (status==='failed'?'打印检查未通过':'打印检查未完整执行')+'：'+(unresolved||'尚无完整检查证据')+'。最终文件暂不可下载。';
}

export default function DeliveryDownloads({busy,stlAvailable,supportStatus,onGLB,onSTL}:{
  busy:boolean;stlAvailable:boolean;supportStatus?:string;onGLB:()=>void;onSTL:()=>void;
}){
  const stlLabel=supportStatus==='not_required'?'下载STL（无需支撑）':'下载带支撑STL';
  return <div className="actions"><button className="primary" disabled={busy} onClick={onGLB}>下载最终彩色GLB</button>
    <button disabled={busy||!stlAvailable} onClick={onSTL}>{stlLabel}</button></div>;
}
