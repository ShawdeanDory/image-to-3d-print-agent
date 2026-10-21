// 只读取已完成的真实开发任务；不提交模型/LLM任务或人工确认。
import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
if(process.env.I3D_FAST_REAL_BROWSER!=='1')throw Error('需显式启用真实任务只读页面验证');
const folder=path.resolve('../runs/course-fast-20261021-01');
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1100}});const mutations=[];
page.on('request',r=>{if(r.method()!=='GET')mutations.push({method:r.method(),url:new URL(r.url()).pathname});});
const result={real_task:'9aeb2c3c-c00f-4c00-837d-c5dc686c41c7',test_fixture:false,posted_confirmations:0};
try{
 await page.goto((process.env.I3D_UI_URL||'http://127.0.0.1:5174')+'/?task='+result.real_task);
 await expect(page.getByText('已连接计算服务')).toBeVisible();
 await expect(page.getByRole('heading',{name:'本次重建用时'})).toBeVisible();
 await expect(page.getByText('课程快速模式',{exact:true})).toBeVisible();
 await expect(page.locator('.viewer-caption').first()).toContainText('拖动旋转',{timeout:30000});
 await page.screenshot({path:path.join(folder,'fast-colored-model.png'),fullPage:true});
 await page.reload();await expect(page.getByRole('heading',{name:'本次重建用时'})).toBeVisible();
 result.refresh_same_task=new URL(page.url()).searchParams.get('task')===result.real_task;
 result.mutations=mutations;result.passed=result.refresh_same_task&&mutations.length===0;
}catch(e){result.passed=false;result.error=String(e);}
finally{await fs.writeFile(path.join(folder,'real-browser.json'),JSON.stringify(result,null,2)+'\n');await page.goto('about:blank');await browser.close();}
console.log(JSON.stringify(result));if(!result.passed)process.exitCode=1;
