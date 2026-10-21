import {test,expect} from '@playwright/test';
import path from 'node:path';

test('自动图片政策：不显示前景复核，保留底面确认与刷新恢复',async({page})=>{
  test.skip(process.env.I3D_AUTOMATIC_BROWSER!=='1','本项只对显式automatic固定服务执行');
  await page.goto('/');await page.evaluate(()=>localStorage.clear());await page.reload();
  await expect(page.getByText('固定验证服务：',{exact:false})).toBeVisible();
  await page.getByLabel('输入图片').setInputFiles(path.resolve('../fixtures/p1/procedural/block.png'));
  await page.getByRole('button',{name:'创建建模任务'}).click();
  await expect(page.getByRole('heading',{name:'补充建模要求'})).toBeVisible();
  const form=page.locator('.confirmation');
  await form.locator('[name=height]').fill('10');await form.locator('[name=unit]').selectOption('mm');
  await form.locator('[name=source]').selectOption('user_target');await form.locator('[name=axis]').selectOption('z');
  await form.locator('[name=orientation_confirmed]').check();
  const imageWaits:string[]=[];
  page.on('response',async response=>{if(response.url().endsWith('/runtime')){
    const value=await response.json().catch(()=>null);if(value?.pending?.kind==='input_review')imageWaits.push(value.pending.pending_input_id);
  }});
  await form.getByRole('button',{name:'补充并继续原任务'}).click();
  await expect(page.getByRole('heading',{name:'确认姿态与底面'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'复核前景与适用范围'})).toHaveCount(0);
  expect(imageWaits).toHaveLength(0);
  const url=page.url();await page.reload();
  await expect(page.getByRole('heading',{name:'确认姿态与底面'})).toBeVisible();expect(page.url()).toBe(url);
  await expect(page.locator('canvas').first()).toBeVisible();
  await page.screenshot({path:path.join(process.env.I3D_BROWSER_EVIDENCE_DIR!,'automatic-wait.png'),fullPage:true});
  await page.goto('about:blank');
});
