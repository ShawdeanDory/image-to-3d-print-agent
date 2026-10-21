import {useCallback,useEffect,useRef,useState} from 'react';
import type {ArtifactRecord,AssetRecord,ModelTaskRequest,PrinterProfile,RuntimeEvent,RuntimeTask} from './contracts.generated';
import {api,ApiError,artifactBlob,download,setAccessToken,type Capabilities} from './api';
import {artifactGroups,checkLabel,checkNames,checkMeasure,display,heightNumber,id,mergeEvents,stageNames,statusNames,validateImage} from './domain';
import PendingForm,{AxisSelect} from './PendingForm';
import ModelView from './ModelView';
import ReconstructionTiming from './ReconstructionTiming';

const initialRun=()=>new URL(location.href).searchParams.get('task')||localStorage.getItem('i3d:last-run')||'';
export default function App(){
  const [cap,setCap]=useState<Capabilities|null>(null);const [profiles,setProfiles]=useState<PrinterProfile[]>([]);
  const [run,setRun]=useState(initialRun);const [task,setTask]=useState<RuntimeTask|null>(null);const [events,setEvents]=useState<RuntimeEvent[]>([]);
  const [error,setError]=useState('');const [connected,setConnected]=useState(false);const [busy,setBusy]=useState(false);
  const [selected,setSelected]=useState('');const [compare,setCompare]=useState('');const [notice,setNotice]=useState('');
  const [preview,setPreview]=useState('');const lock=useRef(false);const createKey=useRef(id('create'));const cursor=useRef(0);
  const fileRef=useRef<File|null>(null);const assetRef=useRef<AssetRecord|null>(null);
  const [fileName,setFileName]=useState('');const [draftValid,setDraftValid]=useState(false);
  const currentRun=useRef(run);currentRun.current=run;
  async function connect(){try{const [configuration,printerProfiles]=await Promise.all([api.configuration(),api.profiles()]);setCap(configuration);setProfiles(printerProfiles);setConnected(true);setError('');}catch(exc){setConnected(false);setError(message(exc));}}
  useEffect(()=>{void connect();},[]);
  const fetchTask=useCallback(async()=>{
    if(!run)return;
    const [current,page]=await Promise.all([api.runtime(run),api.events(run,cursor.current)]);
    if(currentRun.current!==run)return;
    if(current.response.run_id!==run)throw Error('响应属于其他任务，已拒绝显示');
    setTask(current);setEvents(old=>mergeEvents(old,page.events,run));cursor.current=page.next_after;setError('');setConnected(true);
  },[run]);
  useEffect(()=>{
    cursor.current=0;setTask(null);setEvents([]);setSelected('');setCompare('');setNotice('');
    if(!run)return;
    localStorage.setItem('i3d:last-run',run);const url=new URL(location.href);url.searchParams.set('task',run);history.replaceState(null,'',url);
    let stopped=false;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{if(!stopped)await fetchTask();}catch(exc){if(!stopped){setError(message(exc));setConnected(false);}}finally{if(!stopped)timer=setTimeout(poll,1500);}};
    void poll();return()=>{stopped=true;clearTimeout(timer);};
  },[run,fetchTask]);
  useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview);},[preview]);
  const response=task?.response;const groups=response?artifactGroups(response.artifacts??[],response.run_id):{models:[],files:[]};
  const active=groups.models.find(a=>a.artifact_id===selected)||[...groups.models].reverse().find(a=>a.mesh_version===response?.data.state.mesh_version)||groups.models.at(-1);
  const delivery=response?.schema_version==='generation-v1'?response.delivery:null;
  async function act(fn:()=>Promise<void>){if(lock.current)return;lock.current=true;setBusy(true);setError('');try{await fn();}catch(exc){setError(message(exc));}finally{lock.current=false;setBusy(false);}}
  async function create(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();const data=new FormData(event.currentTarget);
    await act(async()=>{
      const file=fileRef.current;if(!file)throw Error('请先选择图片');validateImage(file);
      const height=heightNumber(String(data.get('height')||''));
      if(height===null)throw Error('请在首次提交时填写目标高度');
      if(!assetRef.current)assetRef.current=await api.upload(file) as AssetRecord;
      let evidence:string|null=null;const source=String(data.get('source')||'');const measurement=data.get('measurement') as File;
      if(source==='measured_object'){if(!measurement?.size)throw Error('实物测量需要上传测量依据');validateImage(measurement);evidence=(await api.upload(measurement,'?purpose=measurement') as AssetRecord).asset_id;}
      const axis=String(data.get('axis')||'') as NonNullable<ModelTaskRequest['orientation']>['up_axis'];
      const body:ModelTaskRequest={schema_version:'1.0.0',image_asset_id:assetRef.current.asset_id,printer_profile_id:String(data.get('profile')),
        height_value:height,height_unit:(data.get('unit')||null) as 'mm'|'cm'|null,scale_source:(source||null) as 'user_target'|'measured_object'|null,scale_evidence_id:evidence,
        orientation:{up_axis:axis||null,confirmed:false},description:String(data.get('description')||'')};
      const created=await api.create(body,String(data.get('backend')),createKey.current);setRun(created.run_id);setNotice('任务已创建，后台将自动检查并最多修复2轮，结束后交付GLB。');
    });
  }
  async function submit(body:Record<string,unknown>,slicer=false){await api.input(run,body,slicer);setNotice('已提交，继续原任务。');await fetchTask();}
  function newTask(){setRun('');setTask(null);setEvents([]);setSelected('');setCompare('');cursor.current=0;createKey.current=id('create');assetRef.current=null;localStorage.removeItem('i3d:last-run');history.replaceState(null,'',location.pathname);}
  return <><header><a className="brand" href="/" onClick={e=>{e.preventDefault();newTask();}}><span className="brand-mark">造</span><span>造物工坊<small>图像到3D打印模型</small></span></a><div className="connection"><span className={connected?'dot online':'dot'}/>{connected?'已连接计算服务':'计算服务未连接'}<button className="text-button" onClick={()=>void connect()}>重新连接</button></div></header>
  <main><section className="intro"><div><p className="eyebrow">单张图片 · 简单摆件</p><h1>{run?'让每一步都有依据':'从一张图片，开始造物'}</h1><p className="lede">上传图片并填写参数，提交后自动生成、检查和有限修复，最后交付GLB。</p></div><div className="scope-note">适用于非功能性简单摆件<br/><strong>GLB生成完成与打印检查结果分别展示</strong></div></section>
  {cap?.confirmation_origin==='test_fixture'&&<p className="fixture-banner">固定验证服务：表单自动提交来源为test_fixture，不作为真实人工验收。</p>}
  {error&&<div role="alert" className="error-banner"><strong>操作未完成</strong><p>{error}</p><button onClick={()=>void (run?fetchTask().catch(e=>setError(message(e))):connect())}>重新读取状态</button></div>}
  {!run?<div className="workspace create-workspace"><section className="sheet"><span className="eyebrow">01 / 新建任务</span><h2>图片与建模要求</h2><form onSubmit={create} onChange={()=>{createKey.current=id('create');setNotice('');}}><fieldset disabled={busy}>
    <label className="upload-area"><span className="upload-icon">＋</span><strong>{fileName||'选择一张物体图片'}</strong><span>PNG或JPEG · 最大10MiB · 最长边4096px</span><input aria-label="输入图片" type="file" accept="image/png,image/jpeg" onChange={e=>{const f=e.target.files?.[0];assetRef.current=null;fileRef.current=null;setDraftValid(false);if(!f)return;try{validateImage(f);fileRef.current=f;setFileName(f.name);setPreview(URL.createObjectURL(f));setDraftValid(true);setError('');}catch(exc){setError(message(exc));}}}/></label>
    {preview&&<img className="input-preview" src={preview} alt="本次选择的输入图片"/>}
    <div className="form-grid"><label>目标高度<input name="height" aria-label="目标高度" required type="number" min="0.000001" step="any" placeholder="例如100"/></label><label>高度单位<select name="unit" defaultValue="mm"><option value="">待补充</option><option value="mm">毫米(mm)</option><option value="cm">厘米(cm)</option></select></label><label>尺度来源<select name="source" defaultValue="user_target"><option value="">待补充</option><option value="user_target">设计目标</option><option value="measured_object">实物测量</option></select></label><label>朝上方向<AxisSelect defaultValue="z"/></label></div>
    <label>测量依据（实物测量时需要）<input name="measurement" type="file" accept="image/png,image/jpeg"/></label>
    <div className="form-grid"><label>打印配置<select name="profile" required>{profiles.map(p=><option key={p.profile_id} value={p.profile_id}>{p.profile_id} · {p.material} · {p.nozzle_mm}mm喷嘴{p.profile_kind==='demo'?'（演示）':''}</option>)}</select></label><label>重建后端<select name="backend" required defaultValue={cap?.default_backend||''} key={cap?.default_backend}>{(cap?.configured_backends.length?cap.configured_backends:cap?.default_backend?[cap.default_backend]:[]).map(b=><option value={b} key={b}>{b==='triposr'?'TripoSR':b==='trellis2_candidate'?'TRELLIS.2候选':b}</option>)}</select></label></div>
    <label>补充描述<textarea name="description" maxLength={2000} placeholder="例如：做一个高8厘米的摆件。留空则仅使用填写的约束。"/></label>
    {cap&&!cap.llm_configured&&<p className="muted">语言模型未配置。请使用结构化约束并将描述留空。</p>}
    <button className="primary wide" disabled={!connected||!draftValid||!profiles.length}>{busy?'正在保存与创建…':'创建建模任务'}<span>↗</span></button>
  </fieldset></form></section><aside className="guide"><span className="eyebrow">工作流</span><h2>提交后自动完成</h2><ol><li><strong>准备图片</strong><p>保留清晰原图，自动进入快速重建。</p></li><li><strong>生成与定标</strong><p>使用本次图片重建，保留原始版本。</p></li><li><strong>打印检查与修复</strong><p>后台逐项检查，按受限策略修复。</p></li><li><strong>结果与下载</strong><p>完成后交付GLB，保留打印检查结论。</p></li></ol><label>恢复已有任务<input id="resume-id" placeholder="输入任务UUID"/></label><button onClick={()=>{const v=(document.getElementById('resume-id') as HTMLInputElement).value.trim();if(/^[0-9a-f-]{36}$/i.test(v))setRun(v);else setError('请输入有效任务UUID');}}>读取原任务</button></aside></div>:
  <><div className="task-bar"><div><span className={'badge '+response?.status}>{statusNames[response?.status||'']||'正在读取'}</span><strong>{stageNames[response?.data.state.stage||'']||'读取任务'}</strong><small>任务：{run}</small></div><div className="actions"><button onClick={newTask}>新建任务</button>{response&&!['failed','cancelled','succeeded'].includes(response.status)&&<button disabled={busy} onClick={()=>void act(async()=>{await api.cancel(run);await fetchTask();})}>取消任务</button>}</div></div>
  {notice&&<p role="status" className="notice">{notice}</p>}
  {task&&response&&<div className="workspace task-workspace"><div className="main-column">
    <section className="sheet model-sheet"><div className="section-title"><div><span className="eyebrow">模型与版本</span><h2>查看本次产物</h2></div><span className="muted">原始版本始终保留</span></div>
      {groups.models.length?<><div className="model-selectors"><label>当前模型<select value={active?.artifact_id||''} onChange={e=>setSelected(e.target.value)}>{groups.models.map(a=><option key={a.artifact_id} value={a.artifact_id}>{modelLabel(a)}</option>)}</select></label><label>对照版本<select value={compare} onChange={e=>setCompare(e.target.value)}><option value="">不显示对照</option>{groups.models.filter(a=>a.artifact_id!==active?.artifact_id).map(a=><option value={a.artifact_id} key={a.artifact_id}>{modelLabel(a)}</option>)}</select></label></div><div className={compare?'model-pair':'model-single'}>{active&&<ModelView run={run} artifact={active} frame={task.artifact_frames?.[active.artifact_id]}/>} {compare&&groups.models.find(a=>a.artifact_id===compare)&&<ModelView run={run} artifact={groups.models.find(a=>a.artifact_id===compare)!} frame={task.artifact_frames?.[compare]}/>}</div></>:<div className="empty-model"><span>◎</span><h3>模型将在真实重建后显示</h3><p>当前{statusNames[response.status]}，页面不会加载预存模型作为结果。</p></div>}
      {response.data.inspection?.dimensions_mm&&<div className="dimensions"><span>当前检查版本尺寸</span><strong>{response.data.inspection.dimensions_mm.map(n=>n.toFixed(2)).join(' × ')}<small>mm</small></strong><span>网格：{response.data.inspection.mesh_version}</span></div>}
      <ArtifactImages run={run} artifacts={(response.artifacts??[]).filter(a=>['input_image','foreground_image'].includes(a.kind)||a.artifact_id===task.pending?.details?.preview_artifact_id)}/>
    </section>
    <ReconstructionTiming value={task.resources?.reconstruction}/>
    {delivery&&response.status==='succeeded'&&<section className="sheet"><h2>GLB生成完成</h2><p>打印检查：{delivery.print_check==='passed'?'已通过自动检查':delivery.print_check==='failed'?'未通过':'未完整执行'}；自动修复尝试{delivery.repair_attempts}轮。</p><p className="muted">文件已可下载。自动检查不代表已实际切片或打印。</p><button className="primary" onClick={()=>void act(()=>download(run,delivery.artifact_id,`model-${run}.glb`))}>下载GLB</button></section>}
    {task.pending&&response.schema_version!=='generation-v1'&&<PendingForm key={task.pending.pending_input_id} task={task} onSubmit={submit}/>}
    <section className="sheet"><span className="eyebrow">质量与证据</span><h2>打印检查报告</h2><p className="muted">结论来自服务端检查。“未执行”表示没有取得结果，不能视为通过。</p>
    {response.error&&<p className="error" role="alert"><strong>{response.error.code}</strong>：{response.error.message}</p>}
    {response.data.inspection?<div className="table-scroll"><table><thead><tr><th>检查项</th><th>状态</th><th>实际值</th><th>阈值 / 原因</th></tr></thead><tbody>{(response.data.inspection.checks??[]).map(c=><tr key={c.name}><td>{checkNames[c.name]||c.name}</td><td><span className={'check-status '+c.status}>{checkLabel(c.status)}</span></td><td>{c.status==='not_run'?'未知':checkMeasure(c.name,c.value,c.unit)}</td><td>{c.status==='not_run'?display(c.details?.reason):checkMeasure(c.name,c.threshold,c.unit,true)}</td></tr>)}</tbody></table></div>:<p className="empty">打印检查尚未执行。</p>}
    <h3>本任务文件</h3><div className="downloads">{groups.files.map(a=><button key={a.artifact_id} onClick={()=>void act(()=>download(run,a.artifact_id,a.relative_path))}>{fileLabel(a)}<small>{a.mesh_version||'输入/任务'} · {a.relative_path.split('/').at(-1)}</small><span>↓</span></button>)}</div>{!groups.files.length&&<p className="empty">暂无已登记产物</p>}</section>
  </div><aside><section className="sheet trajectory"><span className="eyebrow">来自服务端</span><h2>任务轨迹</h2><p className="muted">后台自动处理，最多2轮修复。刷新页面可恢复本任务。</p><ol>{events.map(e=><li key={e.event_id}><span>{stageNames[e.stage]||e.stage}</span><strong>{eventNames[e.kind]||e.kind}</strong><small>{statusNames[e.status]||e.status} · {new Date(e.created_at).toLocaleTimeString('zh-CN')}</small></li>)}</ol></section><section className="sheet resource"><h3>运行记录</h3><dl><dt>活动时间</dt><dd>{display(task.resources?.active_seconds)}秒</dd><dt>工具调用</dt><dd>{display(task.resources?.tool_calls)}</dd><dt>语言模型调用</dt><dd>{display((task.resources?.llm as Record<string,unknown>)?.calls)}</dd><dt>打印配置</dt><dd>{response.data.printer_profile.profile_id}{response.data.printer_profile.profile_kind==='demo'?'（演示）':''}</dd></dl><p className="muted">等待不计入活动时间。费用未知时不填0。</p></section></aside></div>}</>}
  <details className="access"><summary>本地服务访问设置</summary><label>服务访问令牌（仅当前页面内存）<input type="password" autoComplete="off" onChange={e=>setAccessToken(e.target.value)} placeholder="服务启用访问保护时填写"/></label><button onClick={()=>void connect()}>验证连接</button></details>
  </main><footer><strong>造物工坊</strong><span>图像重建 · 受控修复 · 打印检查</span><span>近似形状生成，不用于精密机械复原</span></footer></>;
}
function ArtifactImages({run,artifacts}:{run:string;artifacts:ArtifactRecord[]}){
  const images=artifacts.filter(a=>/\.(png|jpe?g)$/i.test(a.relative_path));
  return <div className="artifact-images">{images.map(a=><ArtifactImage key={a.artifact_id} run={run} artifact={a}/>)}</div>;
}
function ArtifactImage({run,artifact}:{run:string;artifact:ArtifactRecord}){
  const [url,setUrl]=useState('');const [error,setError]=useState('');
  useEffect(()=>{let alive=true;let address='';void artifactBlob(run,artifact.artifact_id).then(b=>{address=URL.createObjectURL(b);if(alive)setUrl(address);else URL.revokeObjectURL(address);}).catch(()=>setError('图片读取失败'));return()=>{alive=false;if(address)URL.revokeObjectURL(address);};},[run,artifact.artifact_id]);
  return <figure>{url?<img src={url} alt={artifact.kind==='foreground_image'?'本次前景复核图':'本次任务输入或预览'}/>:<p>{error||'读取图片…'}</p>}<figcaption>{artifact.kind==='foreground_image'?'本次前景':'输入/预览'}<small>{artifact.artifact_id}</small></figcaption></figure>;
}
function modelLabel(a:ArtifactRecord){return `${a.kind==='raw_mesh'?'原始模型':a.kind==='candidate_stl'?'候选STL':'处理/提案模型'} · ${a.mesh_version||'未知版本'} · ${a.relative_path.split('.').at(-1)?.toUpperCase()}`;}
function fileLabel(a:ArtifactRecord){return ({log:'内部日志',quality_report:'质量报告',candidate_stl:'候选STL',raw_mesh:'原始模型',repaired_mesh:'处理/预览模型',inspection_report:'检查/确认记录',slicer_preview:'分层证据',slicer_confirmation:'切片确认',input_image:'输入图片',foreground_image:'前景图片'}[a.kind]||a.kind);}
function message(exc:unknown){return exc instanceof ApiError?`${exc.message}（${exc.code}）`:exc instanceof Error?exc.message:'连接失败，请检查服务和SSH隧道';}
const eventNames:Record<string,string>={node_completed:'步骤完成',node_failed:'步骤失败',completed:'处理结束',created:'任务已保存',queued:'进入队列',started:'开始处理',waiting:'等待补充',input_submitted:'确认已接收',tool_started:'工具开始',tool_finished:'工具结束',progress:'步骤更新',finished:'处理结束',llm_started:'语言模型请求',llm_finished:'语言模型已返回',cancelled:'任务已取消',recovered:'恢复检查点'};
