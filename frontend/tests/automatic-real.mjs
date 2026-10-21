// 真实模型/检查/API：只创建一次；不提交任何中途确认，点击按钮才下载。
import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
if(process.env.I3D_AUTO_REAL_BROWSER!=='1')throw Error('需显式启用本轮真实云端验证');
const folder=path.resolve('../runs/automatic-glb-20261021-01');
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1100}});page.setDefaultTimeout(30000);
const posts=[];let downloads=0;let submitted;
page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
page.on('download',()=>downloads++);
const existing=process.env.I3D_AUTO_REAL_RUN;
const result={test_fixture:false,model_real:true,confirmation_source:'automatic_policy',read_only_existing:!!existing};
try{
 await page.goto((process.env.I3D_UI_URL||'http://127.0.0.1:5174')+(existing?'/?task='+existing:''));
 await expect(page.getByText('已连接计算服务')).toBeVisible();
 if(!existing){
 await expect(page.locator('[name=reconstruction_profile]')).toHaveCount(0);
 await expect(page.locator('[name=orientation_confirmed]')).toHaveCount(0);
 await page.getByLabel('输入图片').setInputFiles(path.join(folder,'duck.jpg'));
 await page.getByLabel('目标高度',{exact:true}).fill('100');
 const created=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/model-tasks'));
 await page.getByRole('button',{name:'创建建模任务'}).click();submitted=await (await created).json();
 result.run_id=submitted.run_id;await fs.writeFile(path.join(folder,'run-id.txt'),result.run_id);
 await page.screenshot({path:path.join(folder,'automatic-running.png'),fullPage:true});
 }else result.run_id=existing;
 await expect(page.getByRole('heading',{name:'GLB生成完成'})).toBeVisible({timeout:900000});
 await expect(page.locator('.confirmation')).toHaveCount(0);
 await expect(page.locator('.viewer-caption').first()).toContainText('拖动旋转');
 result.downloads_before_click=downloads;
 await page.reload();await expect(page.getByRole('heading',{name:'GLB生成完成'})).toBeVisible();
 result.refresh_same_task=new URL(page.url()).searchParams.get('task')===result.run_id;
 result.downloads_after_refresh=downloads;
 await page.screenshot({path:path.join(folder,'automatic-complete.png'),fullPage:true});
 const next=page.waitForEvent('download');await page.getByRole('button',{name:'下载GLB',exact:true}).click();
 const file=await next;await file.saveAs(path.join(folder,'downloaded-model.glb'));
 result.downloads_after_click=downloads;result.posts=posts;
 result.passed=downloads===1&&result.downloads_before_click===0&&result.downloads_after_refresh===0&&result.refresh_same_task&&posts.filter(p=>p.endsWith('/model-tasks')).length===(existing?0:1)&&!posts.some(p=>/\/(inputs|slicer-confirmation)$/.test(p));
}catch(e){result.passed=false;result.error=String(e);}
finally{await fs.writeFile(path.join(folder,'real-browser.json'),JSON.stringify(result,null,2)+'\n');await page.goto('about:blank');await browser.close();}
console.log(JSON.stringify(result));if(!result.passed)process.exitCode=1;
