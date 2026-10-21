// 显式运行才调用同一云端真实模型/LLM。所有自动表单提交为test_fixture。
import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
if(process.env.I3D_REAL_CLOUD!=='1')throw Error('需要显式I3D_REAL_CLOUD=1，禁止默认测试消耗GPU/API');
const root=path.resolve('..');const output=path.join(root,'runs/mid-frontend-20261021-01');
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000},recordVideo:{dir:path.join(output,'real-video'),size:{width:1280,height:888}}});
const page=await context.newPage();const start=Date.now();const result={origin:'test_fixture',tools:'real_cloud_model_and_blender',human_acceptance:false};
page.setDefaultTimeout(30000);
try{
  await page.goto(process.env.I3D_UI_URL||'http://127.0.0.1:5174');await page.evaluate(()=>localStorage.clear());await page.reload();
  await expect(page.locator('.connection')).toContainText('已连接计算服务');
  await page.screenshot({path:path.join(output,'real-home.png'),fullPage:true});
  const input=path.join(root,'fixtures/p1/procedural/block.png');
  await page.getByLabel('输入图片').setInputFiles(input);
  await page.locator('[name=description]').fill('这是简单方块摆件，目标高8厘米，请核对缺少的信息，不要猜测方向。');
  await page.getByRole('button',{name:'创建建模任务'}).click();
  await expect(page.getByRole('heading',{name:'补充建模要求'})).toBeVisible({timeout:90000});
  const run=new URL(page.url()).searchParams.get('task');result.run_id=run;
  await page.reload();await expect(page.getByRole('heading',{name:'补充建模要求'})).toBeVisible();result.refresh_same_run=new URL(page.url()).searchParams.get('task')===run;
  const form=page.locator('.confirmation');await form.locator('[name=height]').fill('80');await form.locator('[name=unit]').selectOption('mm');await form.locator('[name=source]').selectOption('user_target');
  await form.locator('[name=axis]').selectOption('z');await form.locator('[name=orientation_confirmed]').check();await form.locator('[name=accept_suggestions]').check();
  await form.getByRole('button',{name:'补充并继续原任务'}).click();await expect(page.getByRole('heading',{name:'复核前景与适用范围'})).toBeVisible({timeout:90000});
  for(const n of ['complete_subject','simple_nonfunctional_ornament','foreground_correct'])await form.locator(`[name=${n}]`).check();
  await form.getByRole('button',{name:'确认图片并重建'}).click();
  await expect(page.getByRole('heading',{name:'确认姿态与底面'})).toBeVisible({timeout:360000});
  await expect(page.locator('canvas').first()).toBeVisible({timeout:30000});
  await page.screenshot({path:path.join(output,'real-model.png'),fullPage:true});
  await page.locator('.model-selectors select').last().selectOption({index:1});
  await expect(page.locator('canvas')).toHaveCount(2);
  await page.screenshot({path:path.join(output,'real-compare.png'),fullPage:true});
  await page.reload();await expect(page.getByRole('heading',{name:'确认姿态与底面'})).toBeVisible();
  await form.locator('[name=bed_confirmed]').check();await form.locator('[name=components_confirmed]').check();await form.getByRole('button',{name:'提交本版本复核'}).click();
  await expect(page.getByRole('heading',{name:'选择受控修复或停止'})).toBeVisible({timeout:120000});
  await expect(page.locator('tr').filter({hasText:'薄壁'})).toContainText('未执行');
  await form.getByRole('button',{name:'停止并保留报告'}).click();await expect(page.locator('.badge')).toHaveText('已停止');
  await expect(page.getByText('MESH_NOT_PRINTABLE',{exact:true})).toBeVisible();
  await page.screenshot({path:path.join(output,'real-stopped.png'),fullPage:true});
  const reports=page.getByRole('button',{name:/质量报告.*quality\.json/});
  const promise=page.waitForEvent('download');await reports.last().click();const downloaded=await promise;await downloaded.saveAs(path.join(output,'real-quality.json'));
  result.quality=JSON.parse(await fs.readFile(path.join(output,'real-quality.json'),'utf8'));
  const events=await page.request.get(new URL(`/api/v1/model-tasks/${run}/events?limit=200`,page.url()).href);result.events=(await events.json()).events;
  result.reconstruction_calls=result.events.filter(e=>e.kind==='tool_started'&&e.data.operation==='reconstruct').length;
  result.passed=result.refresh_same_run&&result.reconstruction_calls===1&&result.quality.status==='failed';
  await page.goto('/');await page.evaluate(()=>{localStorage.clear();history.replaceState(null,'','/');});await page.reload();
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'real-mobile.png'),fullPage:true});
}catch(exc){result.passed=false;result.error=String(exc);await page.screenshot({path:path.join(output,'real-error.png'),fullPage:true}).catch(()=>{});}
finally{
  result.seconds=(Date.now()-start)/1000;
  await fs.writeFile(path.join(output,'real-browser.json'),JSON.stringify(result,null,2)+'\n');
  // 先离开WebGL页面，避免Edge录屏在GPU页面销毁时阻塞关闭。
  await page.goto('about:blank');await context.close();await browser.close();
}
console.log(JSON.stringify({passed:result.passed,run_id:result.run_id,seconds:result.seconds,error:result.error}));
if(!result.passed)process.exitCode=1;
