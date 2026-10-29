import {afterEach,expect,it,vi} from 'vitest';
import {downloadSTL} from './api';

afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});

function transport(status:number,body:Blob){
  const click=vi.fn();const anchor={href:'',download:'',click};let address='';
  class XHR{
    response=body;status=status;timeout=0;responseType='';
    onload:(()=>void)|null=null;onerror:(()=>void)|null=null;ontimeout:(()=>void)|null=null;
    onabort:(()=>void)|null=null;onprogress:unknown=null;
    open(_method:string,url:string){address=url;}
    setRequestHeader(){}
    send(){queueMicrotask(()=>this.onload?.());}
    abort(){this.onabort?.();}
  }
  vi.stubGlobal('XMLHttpRequest',XHR);vi.stubGlobal('document',{createElement:()=>anchor});
  vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:fixture');
  return {anchor,click,address:()=>address};
}

it('点击下载请求明确任务和版本，保存STL扩展名',async()=>{
  const t=transport(200,new Blob(['fixture-stl']));
  expect(t.click).not.toHaveBeenCalled();
  await downloadSTL('run1','m_123');
  expect(t.address()).toBe('/api/v1/model-tasks/run1/delivery.stl?mesh_version=m_123');
  expect(t.anchor.download).toBe('candidate-run1.stl');expect(t.click).toHaveBeenCalledOnce();
});

it('服务端拒绝版本时显示具体错误，不保存错误JSON为STL',async()=>{
  const t=transport(409,new Blob([JSON.stringify({error:{code:'STATE_CONFLICT',message:'请求版本不一致'}})]));
  await expect(downloadSTL('run1','m_old')).rejects.toMatchObject({code:'STATE_CONFLICT',message:'请求版本不一致'});
  expect(t.click).not.toHaveBeenCalled();
});
