import {useRef,useState} from 'react';
import type {PendingInput,RuntimeTask,AssetRecord} from './contracts.generated';
import {api} from './api';
import {display,heightNumber,newSubmission,validateImage} from './domain';

type Props={task:RuntimeTask;onSubmit:(body:Record<string,unknown>,slicer?:boolean)=>Promise<void>};
const check=(form:FormData,name:string)=>form.get(name)==='on';
const value=(form:FormData,name:string)=>String(form.get(name)||'');
export default function PendingForm({task,onSubmit}:Props) {
  const pending=task.pending!;const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const lock=useRef(false);const stable=useRef<{signature:string;body:Record<string,unknown>}|null>(null);
  const details=pending.details as Record<string,any>;const request=task.response.data.request;
  async function submit(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();if(lock.current)return;lock.current=true;setBusy(true);setError('');
    const data=new FormData(event.currentTarget);const action=(event.nativeEvent as SubmitEvent).submitter?.getAttribute('value');
    const signature=JSON.stringify([action,[...data.entries()].map(([name,v])=>[name,v instanceof File?{name:v.name,size:v.size,...(v.size?{lastModified:v.lastModified}:{})}:v])]);
    try{
      if(stable.current?.signature===signature){await onSubmit(stable.current.body,pending.kind==='slicer');return;}
      let fields:Record<string,unknown>={};
      switch(pending.kind){
        case 'constraints':{
          const height=heightNumber(value(data,'height'));const unit=value(data,'unit');const source=value(data,'source');const axis=value(data,'axis');
          let evidence=request.scale_evidence_id;const file=data.get('measurement') as File|null;
          if(source==='measured_object'&&file?.size){validateImage(file);evidence=(await api.upload(file,'?purpose=measurement') as AssetRecord).asset_id;}
          fields={height_value:height,height_unit:unit||null,scale_source:source||null,scale_evidence_id:evidence??null,
            orientation:{up_axis:axis||null,confirmed:check(data,'orientation_confirmed')},accept_suggestions:check(data,'accept_suggestions')};break;
        }
        case 'input_review':fields={foreground_artifact_id:details.foreground_artifact_id,decision:action||'accepted',complete_subject:check(data,'complete_subject'),simple_nonfunctional_ornament:check(data,'simple_nonfunctional_ornament'),foreground_correct:check(data,'foreground_correct')};break;
        case 'print_review':fields={preview_artifact_id:details.preview_artifact_id,bed_confirmed:check(data,'bed_confirmed'),components_confirmed:check(data,'components_confirmed'),component_count:details.component_count};break;
        case 'repair_request':{
          if(action==='stop'){fields={stop:true};break;}
          const operation=value(data,'operation');
          if(!details.allowed_operations?.includes(operation))throw Error('请选择本版本允许的修复操作');
          const components=value(data,'remove_components').split(',').filter(Boolean).map(Number);
          if(components.some(n=>!Number.isInteger(n)||n<0))throw Error('组件序号须为非负整数，以英文逗号分隔');
          fields={request:{operation,max_perimeter_mm:Number(value(data,'max_perimeter')||40),remove_components:components,target_faces:Number(value(data,'target_faces')||100000),min_wall_mm:task.response.data.printer_profile.min_wall_mm},stop:false};break;
        }
        case 'repair_confirmation':fields={proposal_id:details.proposal_id,accepted:action==='accept'};break;
        case 'slicer':{
          const file=data.get('slice') as File;if(!file?.size)throw Error('请上传本版本实际切片后的分层图片');validateImage(file);
          const uploaded=await api.upload(file,`?purpose=slicer_preview&run_id=${task.response.run_id}&mesh_version=${pending.mesh_version}`) as {artifact:{artifact_id:string}};
          const dimensions=['sx','sy','sz'].map(name=>{const n=heightNumber(value(data,name));if(n===null)throw Error('请填写切片软件中的实际尺寸');return n;});
          fields={result:value(data,'result'),slicer_version:value(data,'slicer_version'),printer_profile_id:request.printer_profile_id,dimensions_mm:dimensions,
            supports_enabled:check(data,'supports_enabled'),layer_preview_asset_id:uploaded.artifact.artifact_id,
            model_preview_confirmed:check(data,'model_preview_confirmed'),bed_confirmed:check(data,'bed_confirmed'),support_reviewed:check(data,'support_reviewed'),notes:value(data,'notes')};break;
        }
      }
      const body=newSubmission(pending,fields);stable.current={signature,body};
      await onSubmit(body,pending.kind==='slicer');
    }catch(exc){setError(exc instanceof Error?exc.message:'确认未提交');}
    finally{lock.current=false;setBusy(false);}
  }
  return <section className="confirmation"><div className="section-title"><span className="eyebrow">需要你的操作</span><h2>{titles[pending.kind]}</h2></div>
    <p className="version">网格版本：{pending.mesh_version||'尚未生成'} · 等待项：{pending.pending_input_id}</p>
    <ul>{(pending.questions??[]).map(q=><li key={q}>{q}</li>)}</ul>
    <form onSubmit={submit}><fieldset disabled={busy}>
    {pending.kind==='constraints'&&<><div className="form-grid"><label>目标高度<input name="height" type="number" step="any" min="0.000001" defaultValue={request.height_value??''}/></label><label>单位<select name="unit" defaultValue={request.height_unit||''}><option value="">待补充</option><option value="mm">毫米(mm)</option><option value="cm">厘米(cm)</option></select></label><label>尺度来源<select name="source" defaultValue={request.scale_source||''}><option value="">待补充</option><option value="user_target">设计目标</option><option value="measured_object">实物测量</option></select></label><label>朝上方向<AxisSelect defaultValue={request.orientation?.up_axis||''}/></label></div><label className="check"><input type="checkbox" name="orientation_confirmed"/>我已核对并确认上述朝上方向</label><label>实测尺度依据（实物测量时需要）<input name="measurement" type="file" accept="image/png,image/jpeg"/></label>{details.suggestions&&<div className="suggestions"><h3>语言模型建议，需你核对</h3><pre>{JSON.stringify(details.suggestions,null,2)}</pre><label className="check"><input type="checkbox" name="accept_suggestions"/>接受尚未填写的高度/单位/来源建议</label></div>}<button className="primary">补充并继续原任务</button></>}
    {pending.kind==='input_review'&&<><label className="check"><input name="complete_subject" type="checkbox" required/>主体完整，无明显裁切或严重遮挡</label><label className="check"><input name="simple_nonfunctional_ornament" type="checkbox" required/>这是简单非功能性摆件</label><label className="check"><input name="foreground_correct" type="checkbox" required/>本次前景正确，主体没有误删</label><div className="actions"><button className="primary" value="accepted">确认图片并重建</button><button value="uncertain" formNoValidate>不确定，停止本任务</button><button value="replace_image" formNoValidate>需要换图</button></div></>}
    {pending.kind==='print_review'&&<><label className="check"><input type="checkbox" name="bed_confirmed"/>已查看当前模型，底面放置稳定</label><label className="check"><input type="checkbox" name="components_confirmed"/>保留当前全部{display(details.component_count)}个组件</label><button className="primary">提交本版本复核</button><p className="muted">不确认底面将停止交付。此操作不等于打印检查通过。</p></>}
    {pending.kind==='repair_request'&&<><div className="form-grid"><label>受支持的结构操作<select name="operation">{(details.allowed_operations||[]).map((op:string)=><option value={op} key={op}>{operations[op]||op}</option>)}</select></label><label>小孔周长上限(mm)<input name="max_perimeter" type="number" step="any" min="0.01" max="40" defaultValue="40"/></label><label>删除组件序号<input name="remove_components" placeholder="例如0,2；不默认保留最大件"/></label><label>简化目标面数<input name="target_faces" type="number" min="100" max="500000" defaultValue="100000"/></label></div><p className="muted">先生成具体预览，下一步确认后才会修改。最多2轮修复。</p><div className="actions"><button className="primary" value="propose">生成修复提案</button><button value="stop" formNoValidate>停止并保留报告</button></div></>}
    {pending.kind==='repair_confirmation'&&<><h3>具体提案：{display(details.proposal_id)}</h3><pre>{JSON.stringify(details.changes,null,2)}</pre><p>请核对提案预览及修改范围，确认将生成新版本并重新检查。</p><div className="actions"><button className="primary" value="accept">接受本提案</button><button value="reject">拒绝，不应用修改</button></div></>}
    {pending.kind==='slicer'&&<><p>请下载当前STL，在登记的切片软件和配置中实际分层。上传的证据只关联当前版本。</p><div className="form-grid"><label>切片结果<select name="result"><option value="pass">通过</option><option value="fail">失败</option></select></label><label>切片软件版本<input required name="slicer_version" defaultValue={task.response.data.printer_profile.slicer_version}/></label>{['X','Y','Z'].map((axis,i)=><label key={axis}>实际{axis}尺寸(mm)<input required name={['sx','sy','sz'][i]} type="number" min="0.0001" step="any"/></label>)}</div><label>本版本分层图片<input required name="slice" type="file" accept="image/png,image/jpeg"/></label><label className="check"><input type="checkbox" name="supports_enabled"/>已在切片软件启用支撑</label>{[['model_preview_confirmed','已复核本版本模型预览'],['bed_confirmed','已复核底面放置'],['support_reviewed','已复核分层和支撑']].map(([name,text])=><label className="check" key={name}><input type="checkbox" name={name}/>{text}</label>)}<label>复核说明<textarea name="notes" maxLength={2000}/></label><button className="primary">提交实际切片结论</button></>}
    </fieldset>{busy&&<p role="status">正在提交，请勿重复点击…</p>}{error&&<p role="alert" className="error">{error}</p>}</form></section>;
}
export function AxisSelect({defaultValue=''}:{defaultValue?:string}){return <select name="axis" defaultValue={defaultValue}><option value="">待确认</option>{['x','y','z','-x','-y','-z'].map(a=><option key={a} value={a}>{a.toUpperCase()}轴朝上</option>)}</select>;}
const titles:Record<PendingInput['kind'],string>={constraints:'补充建模要求',input_review:'复核前景与适用范围',print_review:'确认姿态与底面',repair_request:'选择受控修复或停止',repair_confirmation:'确认具体结构修改',slicer:'提交切片证据'};
const operations:Record<string,string>={fill_small_holes:'受控小孔补洞',remove_components:'删除明确组件',simplify:'受控网格简化'};
