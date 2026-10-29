import type { RuntimeTask, EventsPage, ModelTaskResponse, GenerationTaskResponse, OriginalGLBTaskResponse, ModelTaskRequest, AssetRecord, PrinterProfile, CreateTask } from './contracts.generated';

export interface Capabilities {
  schema_version: 'runtime-v1'; default_backend: string | null; configured_backends: string[];
  inspection_configured: boolean; llm_configured: boolean; llm_model: string | null;
  confirmation_origin: 'human' | 'test_fixture'; worker_concurrency: number;
  input_review_policy?: 'automatic' | 'manual';
  backend_profiles?: Record<string, ('official'|'course_fast')[]>;
  workflow_policy?: 'guided'|'automatic_glb';
  face_budget_policy?: 'image-complexity-v1'|null;
  appearance_policy?: 'official-pbr-v1'|'original-glb-v1'|'repaired-glb-v1';
  delivery_stl_download?: boolean;
  export_options?: {policy_version:string;min_target_faces:number;max_target_faces:number;min_texture_size:number;max_texture_size:number;default_texture_size:number};
}
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}
// 访问令牌只留当前页面内存。模型/语言模型的密钥永不交给浏览器。
let accessToken = '';
export function setAccessToken(value: string) { accessToken = value; }
export async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  const response = await fetch(url, { ...init, headers, signal: init.signal || AbortSignal.timeout(20000) });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail)
      ? data.detail.map((d: {loc?: unknown[]; msg?: string}) => `${d.loc?.join('.')}: ${d.msg}`).join('；') : '';
    throw new ApiError(response.status, data.error?.code || `HTTP_${response.status}`, data.error?.message || detail || '服务请求失败，请检查连接后重试');
  }
  return response.json();
}
const base = '/api/v1';
export const taskUrl = (id: string) => `${base}/model-tasks/${encodeURIComponent(id)}`;
export const artifactUrl = (id: string, artifact: string) => `${taskUrl(id)}/artifacts/${encodeURIComponent(artifact)}`;
export const api = {
  configuration: () => request<Capabilities>(`${base}/configuration`),
  profiles: () => request<PrinterProfile[]>(`${base}/printer-profiles`),
  runtime: (id: string) => request<RuntimeTask>(`${taskUrl(id)}/runtime`),
  events: (id: string, after: number) => request<EventsPage>(`${taskUrl(id)}/events?after=${after}&limit=200`),
  create: (body: ModelTaskRequest, backend: string, key: string, profile?: string, options:Pick<CreateTask,'export_target_faces'|'texture_size'>={}) => request<ModelTaskResponse|GenerationTaskResponse|OriginalGLBTaskResponse>(`${base}/model-tasks`, {
    method: 'POST', headers: {'Content-Type':'application/json', 'Idempotency-Key':key}, body: JSON.stringify({request:body, backend,...(profile?{reconstruction_profile:profile}:{}),...options}) }),
  input: (id: string, body: Record<string, unknown>, slicer = false) => request<ModelTaskResponse|GenerationTaskResponse|OriginalGLBTaskResponse>(`${taskUrl(id)}/${slicer ? 'slicer-confirmation' : 'inputs'}`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) }),
  cancel: (id: string) => request<ModelTaskResponse|GenerationTaskResponse|OriginalGLBTaskResponse>(`${taskUrl(id)}/cancel`, {method:'POST'}),
  upload: async (file: File, query = '') => {
    const data = new FormData(); data.append('file',file);
    return request<AssetRecord | {asset:AssetRecord;artifact:{artifact_id:string}}>(`${base}/assets${query}`, {method:'POST',body:data});
  },
};
export type ArtifactProgress = {loaded:number;total:number|null};
export type ArtifactTransferOptions = {signal?:AbortSignal;onProgress?:(progress:ArtifactProgress)=>void};
export const ARTIFACT_TIMEOUT_MS = 10*60*1000;
export function transferLabel(progress:ArtifactProgress):string {
  const amount=(bytes:number)=>(bytes/1000000).toFixed(1)+'MB';
  return progress.total&&progress.total>0
    ?`已读取${amount(progress.loaded)}/${amount(progress.total)}（${Math.min(100,Math.floor(progress.loaded/progress.total*100))}%）`
    :`已读取${amount(progress.loaded)}，总大小未知`;
}
export function artifactBlob(run: string, id: string, options:ArtifactTransferOptions={}): Promise<Blob> {
  return fileBlob(artifactUrl(run,id),options);
}
function fileBlob(url:string,options:ArtifactTransferOptions={}):Promise<Blob>{
  // 文件采用独立时限，XHR覆盖整个二进制响应体并提供真实传输进度。
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();let settled=false;
    function finish(error?:Error,blob?:Blob){
      if(settled)return;settled=true;options.signal?.removeEventListener('abort',abort);
      xhr.onload=xhr.onerror=xhr.ontimeout=xhr.onabort=xhr.onprogress=null;
      if(error)reject(error);else if(blob)resolve(blob);
    }
    function abort(){xhr.abort();finish(new DOMException('已停止读取文件','AbortError'));}
    xhr.open('GET',url);xhr.responseType='blob';xhr.timeout=ARTIFACT_TIMEOUT_MS;
    if(accessToken)xhr.setRequestHeader('Authorization',`Bearer ${accessToken}`);
    xhr.onprogress=event=>options.onProgress?.({loaded:event.loaded,total:event.lengthComputable?event.total:null});
    xhr.onload=async()=>{
      if(xhr.status<200||xhr.status>=300){
        let detail='该任务文件不可读取，请检查连接或访问权限后重试';let code='ARTIFACT_UNAVAILABLE';
        try{const value=JSON.parse(await (xhr.response as Blob).text());detail=value.error?.message||detail;code=value.error?.code||code;}catch{/* 非JSON错误保留通用说明。 */}
        finish(new ApiError(xhr.status,code,detail));return;
      }
      const blob=xhr.response as Blob;
      options.onProgress?.({loaded:blob.size,total:blob.size});finish(undefined,blob);
    };
    xhr.onerror=()=>finish(new ApiError(0,'ARTIFACT_NETWORK_ERROR','文件传输中断，请检查计算服务连接后重试；无需重新生成模型'));
    xhr.ontimeout=()=>finish(new ApiError(408,'ARTIFACT_TIMEOUT','文件读取超过10分钟，请检查连接后重试；无需重新生成模型'));
    xhr.onabort=()=>finish(new DOMException('已停止读取文件','AbortError'));
    options.signal?.addEventListener('abort',abort,{once:true});
    if(options.signal?.aborted){abort();return;}
    options.onProgress?.({loaded:0,total:null});
    xhr.send();
  });
}
export async function download(run: string, id: string, name: string, options:ArtifactTransferOptions={}) {
  saveBlob(await artifactBlob(run,id,options),name);
}
export async function downloadSTL(run:string,version:string,options:ArtifactTransferOptions={}){
  saveBlob(await deliverySTLBlob(run,version,options),`candidate-${run}.stl`);
}
export function deliverySTLBlob(run:string,version:string,options:ArtifactTransferOptions={}){
  return fileBlob(`${taskUrl(run)}/delivery.stl?mesh_version=${encodeURIComponent(version)}`,options);
}
function saveBlob(blob:Blob,name:string){
  const url=URL.createObjectURL(blob);
  const anchor=document.createElement('a');anchor.href=url;anchor.download=name.split('/').at(-1) || 'artifact';anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
