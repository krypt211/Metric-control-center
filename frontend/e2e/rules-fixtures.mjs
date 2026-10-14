import {fixtureInput,fixtureSessionLogin} from "./session-fixture.mjs";
import { test as base, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
const root = path.resolve(import.meta.dirname, "../.."),
  docker =
    process.env.DOCKER_EXE ??
    path.join(
      process.env.LOCALAPPDATA,
      "Programs/DockerDesktop/resources/bin/docker.exe",
    );
function fixture(mode, nonce) {
  return JSON.parse(
    execFileSync(
      docker,
      [
        "compose",
        "--project-directory",
        root,
        "--env-file",
        path.join(root, ".env"),
        "-f",
        process.env.UI_COMPOSE_FILE ?? path.join(root, "docker-compose.yml"),
        "-p",
        process.env.UI_COMPOSE_PROJECT ?? "metric-control-center",
        "exec",
        "-T",
        "-e",
        "UI_FIXTURE_MODE=" + mode,
        "-e",
        "UI_SESSION_FIXTURES="+(process.env.UI_SESSION_FIXTURES??"false"),
        "-e",
        "UI_FIXTURE_NONCE=" + nonce,
        "backend",
        "python",
        "-c",
        "import sys;exec(sys.stdin.read())",
      ],
      {
        input: fixtureInput(new URL("./rules_accounts.py", import.meta.url)),
        encoding: "utf8",
        windowsHide: true,
      },
    ),
  );
}
export async function login(page, user) {
  if(await fixtureSessionLogin(page,user)){await expect(page).toHaveURL(/\/$/);return;}
  await page.goto("/login");
  await page.getByLabel("Логин или email").fill(user.login);
  await page.getByLabel("Пароль", { exact: true }).fill(user.password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}
let nextLocalApiAt = 0;
export function watch(page, audit) {
  if (process.env.UI_SESSION_FIXTURES === "true" && process.env.UI_COMPOSE_PROJECT === "mcc-integration-acceptance") {
    // Pace browser traffic below the unchanged local auth API limit; no server
    // quota bypass. Synthetic credentials exist only in the restored test DB.
    void page.route("**/api/**", async route => {
      const delay = Math.max(0, nextLocalApiAt - Date.now());
      nextLocalApiAt = Math.max(Date.now(), nextLocalApiAt) + 500;
      if (delay) await new Promise(resolve => setTimeout(resolve, delay));
      await route.continue();
    });
  }
  page.on("console", (m) => {
    if (m.type() === "error") audit.errors.push(m.text());
  });
  page.on("pageerror", (e) => audit.errors.push(e.message));
  page.on("request", (r) => {
    if (
      !["GET", "HEAD", "OPTIONS"].includes(r.method()) &&
      /^\/api\/(actions|ai|automation)(\/|$)/.test(new URL(r.url()).pathname)
    )
      audit.advertising.push(r.url());
  });
}
export const test = base.extend({
  accounts: [
    async ({}, use) => {
      const nonce = randomUUID().replaceAll("-", "");
      try {
        await use(fixture("create", nonce));
      } finally {
        fixture("cleanup", nonce);
      }
    },
    { scope: "worker" },
  ],
  audit: [
    async ({ page, context }, use, info) => {
      const audit = { errors: [], advertising: [] };
      watch(page, audit);
      context.on("page", (p) => watch(p, audit));
      await use(audit);
      await info.attach("rule-browser-audit", {
        body: Buffer.from(JSON.stringify(audit)),
        contentType: "application/json",
      });
      expect(audit.errors).toEqual([]);
      expect(audit.advertising).toEqual([]);
    },
    { auto: true },
  ],
});
