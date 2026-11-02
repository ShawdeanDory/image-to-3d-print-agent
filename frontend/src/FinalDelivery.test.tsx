import {it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {finalDeliveryModel} from './domain';
import DeliveryDownloads from './DeliveryDownloads';
import PreviewToolbar from './PreviewToolbar';
import type {ArtifactRecord} from './contracts.generated';

it('最终预览不能选择原始或中间产物',()=>{
  const artifacts=[{artifact_id:'original',run_id:'r',mesh_version:'m0',kind:'raw_mesh',relative_path:'original.glb',unit:'unitless'},
    {artifact_id:'final',run_id:'r',mesh_version:'m1',kind:'repaired_mesh',relative_path:'final.glb',unit:'mm'}] as ArtifactRecord[];
  expect(finalDeliveryModel(artifacts,'r',{artifact_id:'original',mesh_version:'m0'})).toBeUndefined();
  expect(finalDeliveryModel(artifacts,'r',{artifact_id:'final',mesh_version:'m1'})?.artifact_id).toBe('final');
});
it('只提供两个最终文件下载入口，渲染不会下载',()=>{
  let calls=0;const html=renderToStaticMarkup(<DeliveryDownloads busy={false} stlAvailable onGLB={()=>calls++} onSTL={()=>calls++}/>);
  expect(html.match(/<button/g)).toHaveLength(2);expect(html).toContain('下载最终彩色GLB');expect(html).toContain('下载STL');expect(calls).toBe(0);
});
it('预览工具不再提供PNG或JSON额外下载',()=>{
  const html=renderToStaticMarkup(<PreviewToolbar disabled={false} rotate={false} wireframe={false} background="#dddddd" onAction={()=>{}} onBackground={()=>{}}/>);
  expect(html).not.toContain('截图');expect(html).not.toContain('导出JSON');expect(html).toContain('缩小');
});
