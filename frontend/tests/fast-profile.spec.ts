import {test,expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

test('固定界面数据：快速/官方选项按任务提交，TripoSR没有快速选项',async({page})=>{
  const profile=JSON.parse(fs.readFileSync(path.resolve('../fixtures/p1/printer_profile.json'),'utf8'));
  const submissions:Record<string,unknown>[]=[];
  await page.route('**/api/v1/**',async route=>{
    const url=new URL(route.request().url());
    let body:unknown={error:{code:'FIXTURE_ONLY',message:'固定界面验证，不调用真实模型'}};let status=200;
    if(url.pathname.endsWith('/configuration'))body={schema_version:'runtime-v1',default_backend:'triposr',configured_backends:['triposr','trellis2_candidate'],llm_configured:false,confirmation_origin:'test_fixture',backend_profiles:{triposr:['official'],trellis2_candidate:['official','course_fast']}};
    else if(url.pathname.endsWith('/printer-profiles'))body=[profile];
    else if(url.pathname.endsWith('/assets'))body={asset_id:'fixture_duck',relative_path:'assets/fixture.png',content_type:'image/png',byte_count:100,width:64,height:64};
    else if(url.pathname.endsWith('/model-tasks')){submissions.push(route.request().postDataJSON());status=422;}
    else status=404;
    await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto('/');await page.evaluate(()=>localStorage.clear());await page.reload();
  await expect(page.getByText('已连接计算服务')).toBeVisible();
  await expect(page.locator('[name=reconstruction_profile]')).toHaveCount(0);
  await page.locator('[name=backend]').selectOption('trellis2_candidate');
  await expect(page.locator('[name=reconstruction_profile]')).toHaveValue('official');
  await page.locator('[name=reconstruction_profile]').selectOption('official');
  await page.getByLabel('输入图片').setInputFiles(path.resolve('../fixtures/p1/procedural/block.png'));
  await page.getByRole('button',{name:'创建建模任务'}).click();
  await expect.poll(()=>submissions.at(-1)?.reconstruction_profile).toBe('official');
  expect(submissions.at(-1)?.backend).toBe('trellis2_candidate');
  await page.locator('[name=reconstruction_profile]').selectOption('course_fast');
  await page.getByRole('button',{name:'创建建模任务'}).click();
  await expect.poll(()=>submissions.at(-1)?.reconstruction_profile).toBe('course_fast');
  await page.locator('[name=backend]').selectOption('triposr');
  await expect(page.locator('[name=reconstruction_profile]')).toHaveCount(0);
  await page.getByRole('button',{name:'创建建模任务'}).click();
  await expect.poll(()=>submissions.at(-1)?.backend).toBe('triposr');
  expect(submissions.at(-1)).not.toHaveProperty('reconstruction_profile');
});
