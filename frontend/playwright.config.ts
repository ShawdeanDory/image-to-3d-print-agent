import {defineConfig} from '@playwright/test';
import path from 'node:path';
const evidence=process.env.I3D_BROWSER_EVIDENCE_DIR||'../runs/mid-frontend-20261021-01';
export default defineConfig({
  testDir:'./tests',timeout:90000,workers:1,
  reporter:[['list'],['json',{outputFile:path.join(evidence,'browser-results.json')}]],
  outputDir:path.join(evidence,'browser-artifacts'),
  use:{baseURL:process.env.I3D_UI_URL||'http://127.0.0.1:5173',channel:'msedge',headless:true,viewport:{width:1440,height:1000},
    screenshot:'only-on-failure',video:'on',trace:'retain-on-failure'},
});
