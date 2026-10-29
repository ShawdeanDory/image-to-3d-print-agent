import {expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import PreviewToolbar from './PreviewToolbar';

it('结果工具栏包含参考交互，自动旋转默认关闭；渲染不触发下载',()=>{
  let calls=0;
  const html=renderToStaticMarkup(<PreviewToolbar disabled={false} rotate={false} wireframe={false}
    background="#dddddd" onAction={()=>calls++} onBackground={()=>calls++}/>);
  for(const label of ['放大','缩小','自动旋转','线框模式','重置视图','截图','切换环境','光照配置','背景颜色'])expect(html).toContain(label);
  expect(html).toContain('aria-pressed="false"');expect(calls).toBe(0);
});
