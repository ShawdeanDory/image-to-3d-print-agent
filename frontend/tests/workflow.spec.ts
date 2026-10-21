import {test,expect} from '@playwright/test';
import path from 'node:path';

const root=path.resolve('..');const image=path.join(root,'fixtures/p1/procedural/block.png');
const evidence=path.resolve(process.env.I3D_BROWSER_EVIDENCE_DIR||path.join(root,'runs/mid-frontend-20261021-01'));
test.beforeEach(async({page})=>{await page.goto('/');await page.evaluate(()=>localStorage.clear());await page.reload();});
test.afterEach(async({page})=>{await page.goto('about:blank');});
test('真实API与CPU工具fixture：缺尺度、刷新、确认、修复预览、下载和切片失败',async({page})=>{
  await expect(page.getByText('固定验证服务：',{exact:false})).toBeVisible();
  await page.getByLabel('输入图片').setInputFiles(image);
  await page.getByRole('button',{name:'创建建模任务'}).click();
  await expect(page.getByRole('heading',{name:'补充建模要求'})).toBeVisible();
  const url=page.url();await page.reload();await expect(page.getByRole('heading',{name:'补充建模要求'})).toBeVisible();expect(page.url()).toBe(url);
  const form=page.locator('.confirmation');await form.locator('[name=height]').fill('10');await form.locator('[name=unit]').selectOption('mm');
  await form.locator('[name=source]').selectOption('user_target');await form.locator('[name=axis]').selectOption('z');await form.locator('[name=orientation_confirmed]').check();
  let submits=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/inputs'))submits++;});
  await form.getByRole('button',{name:'补充并继续原任务'}).dblclick();
  await expect(page.getByRole('heading',{name:'复核前景与适用范围'})).toBeVisible();expect(submits).toBe(1);expect(page.url()).toBe(url);
  for(const name of ['complete_subject','simple_nonfunctional_ornament','foreground_correct'])await form.locator(`[name=${name}]`).check();
  await form.getByRole('button',{name:'确认图片并重建'}).click();
  await expect(page.getByRole('heading',{name:'确认姿态与底面'})).toBeVisible();await expect(page.locator('canvas').first()).toBeVisible();
  await page.locator('.model-selectors select').last().selectOption({index:1});
  await expect(page.locator('canvas')).toHaveCount(2);
  await page.waitForFunction(()=>{const pair=document.querySelector('.model-pair')!.getBoundingClientRect();return [...document.querySelectorAll('.model-pair canvas')].every(c=>c.getBoundingClientRect().right<=pair.right+1);});
  await page.screenshot({path:path.join(evidence,'fixture-preview.png'),fullPage:true});
  await form.locator('[name=bed_confirmed]').check();await form.getByRole('button',{name:'提交本版本复核'}).click();
  await expect(page.getByRole('heading',{name:'选择受控修复或停止'})).toBeVisible();
  await expect(page.getByText('失败',{exact:true}).first()).toBeVisible();
  await form.getByRole('button',{name:'生成修复提案'}).click();await expect(page.getByRole('heading',{name:'确认具体结构修改'})).toBeVisible();
  await form.getByRole('button',{name:'接受本提案'}).click();await expect(page.getByRole('heading',{name:'确认姿态与底面'})).toBeVisible();
  await form.locator('[name=bed_confirmed]').check();await form.getByRole('button',{name:'提交本版本复核'}).click();
  await expect(page.getByRole('heading',{name:'提交切片证据'})).toBeVisible();
  const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:/候选STL/}).last().click();const downloaded=await downloadPromise;expect(downloaded.suggestedFilename()).toMatch(/\.stl$/);await downloaded.saveAs(path.join(evidence,'fixture-candidate.stl'));
  await form.locator('[name=result]').selectOption('fail');for(const n of ['sx','sy','sz'])await form.locator(`[name=${n}]`).fill('10');
  await form.locator('[name=slice]').setInputFiles(image);await form.getByRole('button',{name:'提交实际切片结论'}).click();
  await expect(page.getByText('SLICER_VALIDATION_FAILED',{exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'提交切片证据'})).toHaveCount(0);
  await page.screenshot({path:path.join(evidence,'fixture-stopped.png'),fullPage:true});
});
test('取消等待任务，刷新不恢复计算',async({page})=>{
  await page.getByLabel('输入图片').setInputFiles(image);await page.getByRole('button',{name:'创建建模任务'}).click();
  await expect(page.getByRole('heading',{name:'补充建模要求'})).toBeVisible();await page.getByRole('button',{name:'取消任务',exact:true}).click();
  await expect(page.locator('.badge')).toHaveText('已取消');await page.reload();await expect(page.locator('.badge')).toHaveText('已取消');
});
test('损坏上传与断网可理解，后端字符串只作为文本',async({page})=>{
  await page.getByLabel('输入图片').setInputFiles({name:'bad.png',mimeType:'image/png',buffer:Buffer.from('<script>bad</script>')});
  await page.getByRole('button',{name:'创建建模任务'}).click();await expect(page.getByRole('alert')).toContainText('操作未完成');
  await page.route('**/api/v1/configuration',route=>route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({error:{code:'TEST_FIXTURE',message:'<script>window.pwned=1</script>'}})}));
  await page.getByRole('button',{name:'重新连接',exact:true}).click();await expect(page.getByRole('alert')).toContainText('<script>');expect(await page.evaluate(()=>Object.hasOwn(window,'pwned'))).toBe(false);
});

test('网络失败后重试保持同一提交内容与幂等ID',async({page})=>{
  await page.getByLabel('输入图片').setInputFiles(image);await page.getByRole('button',{name:'创建建模任务'}).click();
  await expect(page.getByRole('heading',{name:'补充建模要求'})).toBeVisible();
  const form=page.locator('.confirmation');await form.locator('[name=height]').fill('10');
  const bodies:string[]=[];let first=true;
  await page.route('**/inputs',async route=>{bodies.push(route.request().postData()||'');if(first){first=false;await route.abort('connectionfailed');}else await route.continue();});
  await form.getByRole('button',{name:'补充并继续原任务'}).click();await expect(form.getByRole('alert')).toBeVisible();
  await form.getByRole('button',{name:'补充并继续原任务'}).click();
  await expect(form.getByRole('alert')).toHaveCount(0);expect(bodies).toHaveLength(2);expect(bodies[0]).toBe(bodies[1]);
  await page.getByRole('button',{name:'取消任务',exact:true}).click();await expect(page.locator('.badge')).toHaveText('已取消');
});
