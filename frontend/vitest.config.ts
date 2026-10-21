import {defineConfig} from 'vitest/config';
// 浏览器回归单独由Playwright运行，避免两个测试运行器互相收集。
export default defineConfig({test:{include:['src/**/*.test.ts']}});
