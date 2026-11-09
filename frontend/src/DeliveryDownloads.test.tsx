import {describe,it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import DeliveryDownloads,{printNotice} from './DeliveryDownloads';

describe('同版本文件交付和打印状态',()=>{
  it('GLB和STL分别提供按钮，渲染本身不下载',()=>{
    let calls=0;
    const html=renderToStaticMarkup(<DeliveryDownloads busy={false} stlAvailable={true} onGLB={()=>calls++} onSTL={()=>calls++}/>);
    expect(html).toContain('下载最终彩色GLB');expect(html).toContain('下载带支撑STL');expect(calls).toBe(0);
    expect(html).not.toContain('disabled');
  });
  it('历史无单位原件或旧服务不能静默导出错误尺度',()=>{
    const html=renderToStaticMarkup(<DeliveryDownloads busy={false} stlAvailable={false} onGLB={()=>{}} onSTL={()=>{}}/>);
    expect(html).toMatch(/disabled[^>]*>下载带支撑STL/);
  });
  it('无需支撑时说明STL为本体',()=>{
    const html=renderToStaticMarkup(<DeliveryDownloads busy={false} stlAvailable supportStatus="not_required" onGLB={()=>{}} onSTL={()=>{}}/>);
    expect(html).toContain('下载STL（无需支撑）');
  });
  it('failed和not_run突出显示，不能因任务succeeded写成可打印',()=>{
    expect(printNotice('failed',[{name:'boundary_edges',status:'fail'},{name:'wall_thickness',status:'not_run'}]))
      .toContain('打印检查未通过');
    expect(printNotice('failed',[{name:'boundary_edges',status:'fail'}])).toContain('边界边');
    expect(printNotice('not_run',[])).toContain('未完整执行');
    expect(printNotice('passed',[])).toContain('尚未实物打印');
  });
});
