import type { RuntimeTask, EventsPage, ModelTaskResponse, ModelTaskRequest, AssetRecord, PrinterProfile } from './contracts.generated';

export interface Capabilities {
  schema_version: 'runtime-v1'; default_backend: string | null; configured_backends: string[];
  inspection_configured: boolean; llm_configured: boolean; llm_model: string | null;
  confirmation_origin: 'human' | 'test_fixture'; worker_concurrency: number;
  input_review_policy?: 'automatic' | 'manual';
  backend_profiles?: Record<string, ('official'|'course_fast')[]>;
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
  create: (body: ModelTaskRequest, backend: string, key: string, profile?: string) => request<ModelTaskResponse>(`${base}/model-tasks`, {
    method: 'POST', headers: {'Content-Type':'application/json', 'Idempotency-Key':key}, body: JSON.stringify({request:body, backend,...(profile?{reconstruction_profile:profile}:{})}) }),
  input: (id: string, body: Record<string, unknown>, slicer = false) => request<ModelTaskResponse>(`${taskUrl(id)}/${slicer ? 'slicer-confirmation' : 'inputs'}`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) }),
  cancel: (id: string) => request<ModelTaskResponse>(`${taskUrl(id)}/cancel`, {method:'POST'}),
  upload: async (file: File, query = '') => {
    const data = new FormData(); data.append('file',file);
    return request<AssetRecord | {asset:AssetRecord;artifact:{artifact_id:string}}>(`${base}/assets${query}`, {method:'POST',body:data});
  },
};
export async function artifactBlob(run: string, id: string): Promise<Blob> {
  const headers: Record<string,string> = {}; if(accessToken) headers.Authorization=`Bearer ${accessToken}`;
  const result = await fetch(artifactUrl(run,id), {headers,signal:AbortSignal.timeout(30000)});
  if (!result.ok) throw new ApiError(result.status,'ARTIFACT_UNAVAILABLE','该任务产物不可读取，请刷新任务后重试');
  return result.blob();
}
export async function download(run: string, id: string, name: string) {
  const url=URL.createObjectURL(await artifactBlob(run,id));
  const anchor=document.createElement('a');anchor.href=url;anchor.download=name.split('/').at(-1) || 'artifact';anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
