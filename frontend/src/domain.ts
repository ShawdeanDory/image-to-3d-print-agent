import type { PendingInput, RuntimeEvent, ArtifactRecord } from './contracts.generated';

export const statusNames: Record<string,string> = {queued:'已排队',running:'正在处理',waiting_for_input:'等待你的确认',succeeded:'交付完成',failed:'已停止',cancel_requested:'正在取消',cancelled:'已取消'};
export const stageNames: Record<string,string> = {input:'需求确认',preprocess:'图片准备',reconstruct:'图像重建',repair:'修复处理',scale:'毫米定标',inspect:'打印检查',export:'文件导出',slicer:'切片确认',complete:'完成'};
export const checkNames: Record<string,string> = {finite_coordinates:'坐标有效',watertight:'水密性',normals:'法线方向',boundary_edges:'边界边',non_manifold_edges:'非流形边',non_manifold_vertices:'非流形顶点',self_intersection:'自交',wall_thickness:'薄壁',dimensions:'尺寸',build_volume:'打印空间',overhang:'悬垂',bed_contact:'底面接触',components:'组件'};
export const checkLabel = (status: string) => ({pass:'通过',fail:'失败',warn:'风险',not_run:'未执行'}[status] || '未知');
export const id = (prefix = 's') => `${prefix}_${crypto.randomUUID().replaceAll('-','')}`;
export function heightNumber(value: string): number | null {
  if (!value.trim()) return null;
  const result=Number(value);if(!Number.isFinite(result)||result<=0) throw Error('高度必须为大于0的有限数值');return result;
}
export function validateImage(file: Pick<File,'name'|'type'|'size'>) {
  if(!['image/png','image/jpeg'].includes(file.type)||!/^.+\.(png|jpe?g)$/i.test(file.name)) throw Error('请选择PNG或JPEG图片');
  if(file.size===0||file.size>10485760) throw Error('图片须为非空文件且不超过10MiB');
}
export function mergeEvents(old: RuntimeEvent[], incoming: RuntimeEvent[], run: string) {
  if(incoming.some(e=>e.run_id!==run)) throw Error('事件与当前任务不一致，已拒绝显示');
  return [...new Map([...old,...incoming].map(e=>[e.event_id,e])).values()].sort((a,b)=>a.event_id-b.event_id);
}
export function newSubmission(pending: PendingInput, values: Record<string,unknown>, submission = id()) {
  return {...values,kind:pending.kind,pending_input_id:pending.pending_input_id,mesh_version:pending.mesh_version ?? null,submission_id:submission};
}
export function artifactGroups(artifacts: ArtifactRecord[], run: string) {
  if(artifacts.some(a=>a.run_id!==run)) throw Error('产物与任务不一致');
  const publicFiles=artifacts.filter(a=>a.kind!=='log');
  return {files:publicFiles,models:publicFiles.filter(a=>['raw_mesh','repaired_mesh','candidate_stl'].includes(a.kind)&&/\.(glb|ply|stl)$/i.test(a.relative_path))};
}
export function deliveryModel(artifacts: ArtifactRecord[], run: string, delivery?: {artifact_id:string;mesh_version:string}|null) {
  if(artifacts.some(a=>a.run_id!==run))throw Error('产物与任务不一致');
  if(!delivery)return undefined;
  const artifact=artifacts.find(a=>a.artifact_id===delivery.artifact_id);
  if(!artifact||artifact.mesh_version!==delivery.mesh_version||!['raw_mesh','repaired_mesh'].includes(artifact.kind)||!artifact.relative_path.toLowerCase().endsWith('.glb'))
    throw Error('交付GLB与登记产物或网格版本不一致，已停止预览和下载');
  return artifact;
}
export function display(value: unknown) { return value == null ? '未知' : typeof value==='object' ? JSON.stringify(value) : String(value); }
export function checkMeasure(name:string,value:unknown,unit?:string|null,threshold=false){
  if(value==null)return '未知';if(typeof value==='boolean')return value?'是':'否';
  if(name==='overhang'&&typeof value==='number')return String(value)+(threshold?'°':'面');
  return display(value)+(unit&&unit!=='count'?' '+unit:unit==='count'?'个':'');
}
