// 已有真实网格的CPU重放页面验证；不创建任务、不推理、不提交确认。
import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
if(process.env.I3D_ADAPTIVE_REAL_BROWSER!=='1')throw Error('需显式启用已有真实网格验证');
const folder=path.resolve('../runs/adaptive-mesh-20261022-01');
const run='2ccbf4de-d91c-420e-8875-1a06d8f08539';
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1100}});let downloads=0;const mutations=[];
page.on('download',()=>downloads++);page.on('request',r=>{if(r.method()!=='GET')mutations.push(r.method());});
const result={validation_mode:'existing_real_mesh_replay',run_id:run,new_reconstruction:false};
try{
 await page.goto((process.env.I3D_UI_URL||'http://127.0.0.1:5174')+'/?task='+run);
 await expect(page.getByRole('heading',{name:'自动面数预算'})).toBeVisible();
 await expect(page.getByText('实际交付：9,992面',{exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'GLB生成完成'})).toBeVisible();
 await expect(page.locator('.viewer-caption').first()).toContainText('拖动旋转');
 const body=await (await page.request.get(new URL('/api/v1/model-tasks/'+run+'/runtime',page.url()).href)).json();
 const original=body.response.artifacts.find(a=>a.artifact_id.endsWith('_existing_source'));
 await page.locator('.model-selectors select').last().selectOption(original.artifact_id);
 await expect(page.locator('.viewer-caption').last()).toContainText('拖动旋转');
 await page.screenshot({path:path.join(folder,'adaptive-comparison.png'),fullPage:true});
 result.downloads_before_click=downloads;await page.reload();
 await expect(page.getByRole('heading',{name:'自动面数预算'})).toBeVisible();result.downloads_after_refresh=downloads;
 const next=page.waitForEvent('download');await page.getByRole('button',{name:'下载GLB',exact:true}).click();
 await (await next).saveAs(path.join(folder,'adaptive-duck.glb'));
 result.downloads_after_click=downloads;result.mutations=mutations;
 result.passed=downloads===1&&result.downloads_before_click===0&&result.downloads_after_refresh===0&&mutations.length===0;
}catch(e){result.passed=false;result.error=String(e);}
finally{await fs.writeFile(path.join(folder,'real-browser.json'),JSON.stringify(result,null,2)+'\n');await page.goto('about:blank');await browser.close();}
console.log(JSON.stringify(result));if(!result.passed)process.exitCode=1;
