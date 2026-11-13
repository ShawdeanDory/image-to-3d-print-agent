import {it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {finalDeliveryModel,previewModel} from './domain';
import DeliveryDownloads from './DeliveryDownloads';
import PreviewToolbar from './PreviewToolbar';
import type {ArtifactRecord} from './contracts.generated';

it('建模结果与打印检查独立，优先显示交付模型并允许原始模型预览',()=>{
  const artifacts=[{artifact_id:'original',run_id:'r',mesh_version:'m0',kind:'raw_mesh',relative_path:'original.glb',unit:'unitless'},
    {artifact_id:'final',run_id:'r',mesh_version:'m1',kind:'repaired_mesh',relative_path:'final.glb',unit:'mm'}] as ArtifactRecord[];
  for(const print_check of ['passed','failed','not_run']){
    expect(previewModel(artifacts,'r',{artifact_id:'final',mesh_version:'m1',print_check})?.artifact_id).toBe('final');
  }
  expect(previewModel(artifacts,'r',null)?.artifact_id).toBe('original');
  expect(previewModel([],'r',null)).toBeUndefined();
  expect(()=>previewModel(artifacts,'other',null)).toThrow('产物与任务不一致');
  expect(()=>previewModel(artifacts,'r',{artifact_id:'final',mesh_version:'wrong'})).toThrow('网格版本不一致');
});

it('最终预览不能选择原始或中间产物',()=>{
  const artifacts=[{artifact_id:'original',run_id:'r',mesh_version:'m0',kind:'raw_mesh',relative_path:'original.glb',unit:'unitless'},
    {artifact_id:'final',run_id:'r',mesh_version:'m1',kind:'repaired_mesh',relative_path:'final.glb',unit:'mm'}] as ArtifactRecord[];
  expect(finalDeliveryModel(artifacts,'r',{artifact_id:'original',mesh_version:'m0'})).toBeUndefined();
  expect(finalDeliveryModel(artifacts,'r',{artifact_id:'final',mesh_version:'m1'})?.artifact_id).toBe('final');
});
it('只提供两个最终文件下载入口，渲染不会下载',()=>{
  let calls=0;const html=renderToStaticMarkup(<DeliveryDownloads busy={false} stlAvailable onGLB={()=>calls++} onSTL={()=>calls++}/>);
  expect(html.match(/<button/g)).toHaveLength(2);expect(html).toContain('下载GLB');expect(html).toContain('下载模型STL');expect(calls).toBe(0);
});
it('预览工具不再提供PNG或JSON额外下载',()=>{
  const html=renderToStaticMarkup(<PreviewToolbar disabled={false} rotate={false} wireframe={false} background="#dddddd" onAction={()=>{}} onBackground={()=>{}}/>);
  expect(html).not.toContain('截图');expect(html).not.toContain('导出JSON');expect(html).toContain('缩小');
});
