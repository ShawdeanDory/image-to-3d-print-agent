export default function PrintCopyControls({original,busy,onPreview,onDownload}:{
  original:boolean;busy:boolean;onPreview:(original:boolean)=>void;onDownload:()=>void;
}){
  return <div className="actions" aria-label="打印副本与原始彩色版">
    <button aria-pressed={!original} onClick={()=>onPreview(false)}>打印修复版</button>
    <button aria-pressed={original} onClick={()=>onPreview(true)}>原始彩色版</button>
    <button disabled={busy} onClick={onDownload}>下载原始彩色GLB</button>
  </div>;
}
