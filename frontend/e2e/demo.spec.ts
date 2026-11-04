import { expect, test, type Page } from "@playwright/test";
import { readdirSync, readFileSync } from "node:fs";
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
  for (const path of ["/", "/investigations", "/investigations/new", "/network", "/assurance", "/reports", "/sources", "/sources/import", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("main")).toBeVisible();
  }
  expect(problems).toEqual([]);
});

const stage = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Investigation stages" }).getByRole("button", { name: new RegExp(`^${name}\\b`) });

test("the full demonstration: investigate, conclude, mitigate, verify", async ({ page }) => {
  await signIn(page);
  await shot(page, "01-overview");

  await page.getByRole("region", { name: "What we are investigating" }).getByRole("link", { name: /Security claim analysis/ }).click();
  const heading = page.getByRole("heading", { level: 1, name: "Security claim analysis" });
  await expect(heading).toBeVisible();
  await expect(page.getByText("UNDERDETERMINED").first()).toBeVisible();
  await expect(page.getByText("Review recommended tests")).toBeVisible();
  await expect(stage(page, "Tests")).toHaveAttribute("aria-current", "step");
  await expect(page.getByText("Recommended, not yet run")).toBeVisible();
  await expect(page.getByText("Executed", { exact: true })).toHaveCount(0);
  await shot(page, "02-workspace-underdetermined");

  await stage(page, "Explanations").click();
  await expect(page).toHaveURL(/#explanations$/);
  await expect(page.getByText("Undetected intrusion on an unmonitored endpoint").first()).toBeVisible();
  await expect(page.getByRole("table", { name: /Predictions of each explanation/ })).toBeVisible();

  await stage(page, "Evidence").click();
  await expect(page.getByText("Restricted. Not read until an approved test reads it")).toBeVisible();
  await expect(page.getByText("Disconnected, not read")).toBeVisible();

  await page.getByRole("button", { name: "EV-0001" }).first().click();
  await expect(page.getByText("SHA-256 of cited records")).toBeVisible();
  await shot(page, "03-evidence-drawer", false);
  await page.getByRole("button", { name: "Close" }).click();

  await stage(page, "Tests").click();
  await page.getByRole("button", { name: "Review Investigation" }).click();
  const approve = page.getByRole("button", { name: "Approve and run" });
  await expect(approve).toBeDisabled();
  await page.getByLabel(/I authorize these procedures/).check();
  await shot(page, "04-review-dialog", false);
  await approve.click();

  await expect(page.getByText("CONTRADICTED", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Concluded", { exact: true })).toBeVisible();
  await expect(page.getByText("Unexplained logon on FIN-WS-0014").first()).toBeVisible();
  await expect(page.getByText("Executed", { exact: true })).toBeVisible();
  await expect(page.getByText("Recommended, not yet run")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Hourly egress from FIN-WS-0014" })).toBeVisible();
  await shot(page, "05-workspace-contradicted");

  await stage(page, "Explanations").click();
  await expect(page.getByText("Excluded").first()).toBeVisible();

  await stage(page, "Evidence").click();
  await expect(page.getByText("Restricted. Not read until an approved test reads it")).toHaveCount(0);

  await stage(page, "Findings").click();
  await page.getByRole("button", { name: "Reveal demo answer key" }).click();
  await expect(page.getByText("NULL's conclusion matches the answer key.")).toBeVisible();

  await page.getByText("Statistical analysis", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "Failed sign-ins per hour" })).toBeVisible();

  await page.getByRole("button", { name: "Export report" }).click();
  await expect(page).toHaveURL(/\/reports\/[0-9a-f]+/);
  await expect(page.getByRole("heading", { name: /Competing explanations/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Verification and assurance/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence coverage by source and hour" })).toBeVisible();
  await shot(page, "06-report");

  await page.goto("/assurance#mitigation");
  const row = page.locator("li", { hasText: "Enroll or repair the EDR agent" }).first();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Approve" }).click();
  await row.getByRole("button", { name: "Execute", exact: true }).click();
  await page.getByRole("button", { name: "Execute simulated change" }).click();
  await row.getByRole("button", { name: "Run verification" }).click();
  await expect(row.getByText(/Not reporting:/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Failed or recurred/ })).toContainText("1");
  await shot(page, "07-assurance-failed-verification");

  await row.getByRole("button", { name: "Execute again" }).click();
  await page.getByRole("button", { name: "Execute simulated change" }).click();
  await row.getByRole("button", { name: "Run verification" }).click();
  const verification = page.locator("section", { has: page.getByRole("heading", { name: "Continuous verification" }) });
  await expect(verification.getByText("Passed", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^1\s*Verified/ })).toBeVisible();
  await shot(page, "08-assurance-verified");

  await verification.getByRole("button", { name: "Simulate recurrence" }).click();
  await verification.getByRole("button", { name: "Run now" }).click();
  await expect(verification.getByText("Recurred", { exact: true })).toBeVisible();

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What we have resolved" })).toBeVisible();
  await expect(page.getByText(/has recurred/).first()).toBeVisible();
});

test("the next action opens the stage it names", async ({ page }) => {
  await signIn(page);
  await page.goto("/investigations");
  await page.getByRole("link", { name: /MFA enforcement review/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "MFA enforcement review" })).toBeVisible();
  await expect(page.getByText("Decide on corrective actions")).toBeVisible();
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page).toHaveURL(/#actions$/);
  await expect(page.getByRole("heading", { name: "Corrective actions" })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Corrective actions" })).toBeVisible();
});

test("the report prints without the application around it", async ({ page }) => {
  await signIn(page);
  await page.goto("/investigations");
  await page.getByRole("link", { name: /Weekly access assurance/ }).click();
  await page.getByRole("button", { name: "Export report" }).click();
  await expect(page.getByRole("heading", { name: "Evidence coverage by source and hour" })).toBeVisible();
  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("navigation", { name: "Main" }).first()).toBeHidden();
  await expect(page.getByRole("link", { name: "Reports", exact: true })).toBeHidden();
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe("rgb(255, 255, 255)");
  if (shots) await page.pdf({ path: join(shots, "print.pdf"), format: "A4", printBackground: true });
  await page.emulateMedia({ media: "screen" });
  const response = await page.request.get(`${page.url().replace(/\/reports.*/, "")}/api/v1/reports/${page.url().split("/").pop()}/export.pdf`);
  expect(response.ok()).toBeTruthy();
  expect((await response.body()).subarray(0, 4).toString()).toBe("%PDF");
});

test("a new investigation runs through the workflow", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Start Investigation" }).click();
  await page.getByLabel("Claim").fill("No unauthorized access occurred during the last 24 hours.");
  await expect(page.getByText("How NULL reads this")).toBeVisible();
  await shot(page, "09-new-claim", false);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Dataset").selectOption("C");
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
  await page.getByRole("button", { name: "Everything", exact: true }).click();
  await expect.poll(() => page.locator(".react-flow__node").count()).toBeGreaterThan(19);
  const everything = await page.locator(".react-flow__node").count();
  await page.getByRole("button", { name: "Explanations", exact: true }).click();
  await expect.poll(() => page.locator(".react-flow__node").count()).toBeLessThan(everything);
  await page.waitForTimeout(400);
  await shot(page, "11-network", false);
  await page.locator(".react-flow__node", { hasText: "Reality B" }).first().click();
  await expect(page.getByRole("complementary", { name: "Selection details" }).getByText(/Relationships \(\d+\)/)).toBeVisible();
  await page.waitForTimeout(350);
  await shot(page, "12-network-selected", false);
  const before = await page.locator(".react-flow__node").count();
  await page.getByRole("button", { name: "Focus on this" }).click();
  await expect.poll(() => page.locator(".react-flow__node").count()).toBeLessThanOrEqual(before);
  await page.getByRole("button", { name: "Clear focus" }).click();
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await expect.poll(() => page.locator(".react-flow__node").count()).toBeLessThan(before);
  await page.getByLabel("Search the network").fill("EV-0001");
  await page.getByRole("complementary", { name: "Selection details" }).getByRole("button", { name: /EV-0001/ }).first().click();
  await expect(page.getByRole("button", { name: "Clear focus" })).toBeVisible();
});

test("exported logs can be uploaded and investigated", async ({ page }) => {
  const data = join(__dirname, "../../docs/datasets/tallowmere-synthetic");
  const snapshot = join(data, "snapshot-G");
  await signIn(page);
  await page.goto("/sources");
  await page.getByRole("link", { name: "Upload evidence" }).click();
  await page.getByLabel("Dataset name").fill("Tallowmere browser check");
  await page.getByText("Test or synthetic data").click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("button", { name: "Choose CSV files" })).toBeVisible();
  await shot(page, "upload-empty");
  const files = readdirSync(snapshot).map((name) => join(snapshot, name));
  await page.getByLabel("CSV files to upload").setInputFiles([join(data, "asset_register.csv"), ...files]);
  await expect(page.getByText("20,160 of 20,160 rows readable")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/rows readable/)).toHaveCount(9);
  await expect(page.getByText(/rejected:/)).toHaveCount(0);
  await shot(page, "upload-files");
  await page.getByRole("button", { name: "Add to evidence" }).click();
  await expect(page.getByText("Added to evidence. These records can't be changed.")).toBeVisible({ timeout: 60_000 });
  await shot(page, "upload-done");
  await page.getByRole("button", { name: "Start an investigation" }).click();
  await expect(page.getByRole("heading", { name: "What is being claimed?" })).toBeVisible();
  await expect(page.getByText("SYNTHETIC UPLOAD")).toBeVisible();
  await page.getByLabel("Claim").fill("MFA was enforced on every sign-in.");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("combobox", { name: "Dataset" })).toHaveValue(/^up-/);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Begin investigation" }).click();
  await expect(page.getByText("Tallowmere browser check (synthetic)").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Reveal demo answer key" })).toHaveCount(0);
  await page.goto("/sources");
  await page.getByRole("combobox", { name: "Dataset" }).selectOption("A");
  await expect(page.getByText("DEMONSTRATION WORKSPACE")).toBeVisible();
});

test("a file that can't be read is explained, not imported", async ({ page }) => {
  await signIn(page);
  await page.goto("/sources/import");
  await page.getByLabel("Dataset name").fill("Unreadable rows");
  await page.getByText("Real logs").click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("CSV files to upload").setInputFiles({
    name: "signins.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Date (UTC),Request ID,Username,Application,Status,MFA\n2026-03-02 10:00:00,r1,ana,erp,Success,true\n"),
  });
  await expect(page.getByText("0 of 1 rows readable")).toBeVisible();
  await expect(page.getByText(/1 rejected: A timestamp has no time zone/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Add to evidence" })).toBeDisabled();
  await page.getByText("Columns and time zone").click();
  await page.getByLabel("Time zone of unmarked times").selectOption("Asia/Manila");
  await expect(page.getByText("1 of 1 rows readable")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add to evidence" })).toBeEnabled();
  await page.getByRole("button", { name: "Discard upload" }).click();
  await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible();
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
  for (const path of ["/", "/investigations", "/investigations/new", "/assurance", "/reports", "/sources", "/sources/import", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
  await page.goto("/investigations");
  await page.getByRole("link", { name: /Weekly access assurance/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot(page, "18-mobile-workspace");
  const rail = page.getByRole("navigation", { name: "Investigation stages" });
  await rail.scrollIntoViewIfNeeded();
  await expect(rail.locator('[aria-current="step"]')).toBeInViewport();
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
