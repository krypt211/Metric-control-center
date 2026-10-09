import {defineConfig,devices} from "@playwright/test";
export default defineConfig({
 testDir:"./e2e",fullyParallel:false,workers:1,retries:0,timeout:60000,
 expect:{timeout:15000},reporter:[["list"],["json",{outputFile:"test-results/browser-acceptance.json"}]],
 use:{...devices["Desktop Chrome"],baseURL:process.env.UI_BASE_URL??"http://127.0.0.1:3000",trace:"off",video:"off",screenshot:"only-on-failure"},
});