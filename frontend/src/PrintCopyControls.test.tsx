import {it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import PrintCopyControls from './PrintCopyControls';
import MaterialInfo from './MaterialInfo';

it('打印版与原彩色版分开，渲染不会下载或提交任务',()=>{
  let calls=0;
  const html=renderToStaticMarkup(<PrintCopyControls original={false} busy={false} onPreview={()=>calls++} onDownload={()=>calls++}/>);
  expect(html).toContain('aria-pressed="true">打印修复版');
  expect(html).toContain('原始彩色版');expect(html).toContain('下载原始彩色GLB');expect(calls).toBe(0);
});
it('打印副本明确不含原UV/PBR，不冒称保留颜色',()=>{
  const html=renderToStaticMarkup(<MaterialInfo printCopy/>);
  expect(html).toContain('不含原UV/PBR');expect(html).toContain('原始彩色GLB');
  expect(html).not.toContain('保留已有UV');
});
