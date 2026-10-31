import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const shots = process.env.NULL_SHOTS;
const password =
  process.env.NULL_DEMO_PASSWORD ??
  /^NULL_DEMO_PASSWORD=(.*)$/m.exec(readFileSync(join(__dirname, "../../.env"), "utf8"))?.[1] ??
  "";

async function signIn(page: Page, email = "ada@cobalt.example") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /What do we know\?/ })).toBeVisible();
}

async function shot(page: Page, name: string, fullPage = true) {
  if (shots) await page.screenshot({ path: join(shots, `${name}.png`), fullPage });
}

test("console stays clean across every page", async ({ page }) => {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  await signIn(page);
  for (const path of ["/", "/investigations", "/investigations/new", "/network", "/assurance", "/reports", "/sources", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("main")).toBeVisible();
  }
  expect(problems).toEqual([]);
});

test("the full demonstration: investigate, conclude, mitigate, verify", async ({ page }) => {
  await signIn(page);
  await shot(page, "01-overview");

  await page.getByRole("link", { name: "Security claim analysis" }).first().click();
  const heading = page.getByRole("heading", { level: 1, name: "Security claim analysis" });
  await expect(heading).toBeVisible();
  await expect(page.getByText("UNDERDETERMINED").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Competing realities" })).toBeVisible();
  await expect(page.getByText("Undetected intrusion on an unmonitored endpoint").first()).toBeVisible();
  await shot(page, "02-workspace-underdetermined");

  await page.getByRole("button", { name: "EV-0001" }).click();
  await expect(page.getByText("SHA-256 of cited records")).toBeVisible();
  await shot(page, "03-evidence-drawer", false);
  await page.getByRole("button", { name: "Close" }).click();

  await page.getByRole("button", { name: "Review Investigation" }).click();
  const approve = page.getByRole("button", { name: "Approve and run" });
  await expect(approve).toBeDisabled();
  await page.getByLabel(/I authorize these procedures/).check();
  await shot(page, "04-review-dialog", false);
  await approve.click();

  await expect(page.getByText("CONTRADICTED", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Concluded", { exact: true })).toBeVisible();
  await expect(page.getByText("Excluded").first()).toBeVisible();
  await expect(page.getByText("Unexplained logon on FIN-WS-0014")).toBeVisible();
  await shot(page, "05-workspace-contradicted");

  await page.getByRole("button", { name: "Reveal demo answer key" }).click();
  await expect(page.getByText("NULL's conclusion matches the answer key.")).toBeVisible();

  await page.getByRole("button", { name: "Export report" }).click();
  await expect(page).toHaveURL(/\/reports\/[0-9a-f]+/);
  await expect(page.getByRole("heading", { name: /Evidence provenance/ })).toBeVisible();
  await shot(page, "06-report");

  await page.goto("/assurance#mitigation");
  const row = page.locator("li", { hasText: "Enroll or repair the EDR agent" }).first();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Approve" }).click();
  await row.getByRole("button", { name: "Execute", exact: true }).click();
  await page.getByRole("button", { name: "Execute simulated change" }).click();
  await row.getByRole("button", { name: "Run verification" }).click();
  await expect(row.getByText(/Not reporting:/)).toBeVisible();
  await shot(page, "07-assurance-failed-verification");

  await row.getByRole("button", { name: "Execute again" }).click();
  await page.getByRole("button", { name: "Execute simulated change" }).click();
  await row.getByRole("button", { name: "Run verification" }).click();
  const verification = page.locator("section", { has: page.getByRole("heading", { name: "Continuous verification" }) });
  await expect(verification.getByText("Passed")).toBeVisible();
  await shot(page, "08-assurance-verified");
});

test("a new investigation runs through the workflow", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Start Investigation" }).click();
  await page.getByLabel("Claim").fill("No unauthorized access occurred during the last 24 hours.");
  await expect(page.getByText("How NULL reads this")).toBeVisible();
  await shot(page, "09-new-claim", false);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Demo snapshot").selectOption("C");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("SaaS audit trail")).toBeVisible();
  await shot(page, "10-new-sources", false);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Begin investigation" }).click();
  await expect(page).toHaveURL(/\/investigations\/[0-9a-f]+/);
  await expect(page.getByText("UNDERDETERMINED").first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Review Investigation" }).click();
  await page.getByLabel(/I authorize these procedures/).check();
  await page.getByRole("button", { name: "Approve and run" }).click();
  await expect(page.getByText("SUPPORTED", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Concluded", { exact: true })).toBeVisible();
});

test("the evidence network is interactive", async ({ page }) => {
  await signIn(page);
  await page.goto("/network");
  const card = page.locator(".react-flow__node").first();
  await expect(card).toBeVisible();
  expect(await page.locator(".react-flow__node").count()).toBeGreaterThan(19);
  await page.waitForTimeout(400);
  await shot(page, "11-network", false);
  await page.locator(".react-flow__node", { hasText: "Reality B" }).first().click();
  await expect(page.getByRole("complementary", { name: "Selection details" }).getByText(/Relationships \(\d+\)/)).toBeVisible();
  await page.waitForTimeout(350);
  await shot(page, "12-network-selected", false);
  const before = await page.locator(".react-flow__node").count();
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await expect.poll(() => page.locator(".react-flow__node").count()).toBeLessThan(before);
});

test("a viewer can read but not act", async ({ page }) => {
  await signIn(page, "mina@cobalt.example");
  await expect(page.getByRole("link", { name: "Start Investigation" })).toHaveCount(0);
  await page.goto("/sources");
  await expect(page.getByRole("button", { name: "Disconnect" })).toHaveCount(0);
});

test("dialogs work from the keyboard", async ({ page }) => {
  await signIn(page);
  await page.goto("/sources");
  await page.getByRole("button", { name: "Disconnect" }).first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("no page scrolls sideways at phone width", async ({ page }) => {
  await signIn(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/", "/investigations", "/investigations/new", "/assurance", "/reports", "/sources", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
  await page.goto("/investigations");
  await page.getByRole("link", { name: /Security claim analysis/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot(page, "18-mobile-workspace");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "workspace").toBeLessThanOrEqual(0);
});

test("remaining pages for visual review", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await shot(page, "13-overview-after");
  await page.goto("/investigations");
  await page.waitForLoadState("networkidle");
  await shot(page, "14-investigations");
  await page.goto("/sources");
  await page.waitForLoadState("networkidle");
  await shot(page, "15-sources");
  await page.goto("/settings#ai");
  await page.waitForLoadState("networkidle");
  await shot(page, "16-settings-ai");
  await page.goto("/login");
  await shot(page, "17-login", false);
});
