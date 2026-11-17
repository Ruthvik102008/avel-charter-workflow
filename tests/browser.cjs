const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { once } = require("node:events");
const { mkdtemp, rm } = require("node:fs/promises");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const { chromium } = require("playwright");

async function main() {
  const stateDir = await mkdtemp(join(tmpdir(), "charter-browser-"));
  const server = spawn("python", ["serve.py", "--port", "0", "--state-dir", stateDir], {
    stdio: ["ignore", "pipe", "inherit"],
  });
  let browser;
  try {
    const announced = once(server.stdout, "data");
    const stopped = once(server, "exit").then(([code]) => {
      throw new Error("Dashboard server exited early with code " + code);
    });
    const [message] = await Promise.race([announced, stopped]);
    const url = message.toString().match(/http:\/\/127\.0\.0\.1:\d+/)[0];

    browser = await chromium.launch({ channel: "chrome" });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url);
    await page.getByRole("button", { name: "Run demo" }).click();
    await page.locator("#status").filter({ hasText: "Awaiting approval" }).waitFor();
    await page.getByText("Temporary availability API timeout").waitFor();
    await page.getByText("Check aircraft availability (attempt 2)").waitFor();
    await page.getByText("$18,500", { exact: true }).waitFor();
    assert.equal(await page.getByText(/Mock send completed/).count(), 0);
    const draft = await page.locator("#quote-id").innerText();
    const requestId = await page.locator("#request-id").inputValue();

    await page.getByRole("button", { name: "Keep pending" }).click();
    await page.getByText("Approval withheld. Quote remains pending.").waitFor();
    assert.equal(await page.getByText(/Mock send completed/).count(), 0);

    await page.reload();
    await page.locator("#status").filter({ hasText: "Awaiting approval" }).waitFor();
    assert.equal(await page.locator("#quote-id").innerText(), draft);
    await page.getByRole("button", { name: "Approve & mock send" }).click();
    await page.getByText("Receipt MOCK-" + draft).waitFor();

    await page.getByRole("button", { name: "Repeat approval check" }).click();
    await page.locator("#feedback").filter({ hasText: "Workflow already complete" }).waitFor();
    assert.equal(await page.getByText(/Mock send completed/).count(), 1);

    const phone = await browser.newPage({ viewport: { width: 375, height: 812 } });
    await phone.goto(url);
    await phone.getByLabel("Open a saved request").fill(requestId);
    await phone.getByRole("button", { name: "Open", exact: true }).click();
    await phone.getByText("Receipt MOCK-" + draft).waitFor();
    assert.equal(await phone.evaluate(() => document.documentElement.scrollWidth), 375);
    assert.deepEqual(errors, []);
    console.log("Verified browser retry, approval, reload, repeat approval, and mobile lookup.");
  } finally {
    try {
      if (browser) await browser.close();
    } finally {
      if (server.exitCode === null) {
        const exited = once(server, "exit");
        server.kill();
        await exited;
      }
      await rm(stateDir, { recursive: true, force: true });
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
