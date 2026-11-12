// Records the two demo scenes at 1920x1080. Usage: node record.cjs <baseUrl> <scene: s4|s5|all>
const { chromium } = require(process.env.PW_PATH);
const base = process.argv[2] || "http://localhost:3123";
const which = process.argv[3] || "all";
const ZOOM = 1.35;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function scroll(page, sel, block = "start") {
  await page.evaluate(([s, b]) => document.querySelector(s).scrollIntoView({ behavior: "smooth", block: b }), [sel, block]);
  await wait(900);
}

async function open(browser, name) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: `/home/claude/video/rec/${name}`, size: { width: 1920, height: 1080 } } });
  const page = await ctx.newPage();
  await page.goto(base, { waitUntil: "networkidle" });
  await page.evaluate((z) => { document.documentElement.style.zoom = String(z); }, ZOOM);
  await page.waitForSelector(".hero .cell.no");
  return { ctx, page };
}

async function s4(browser) {
  const { ctx, page } = await open(browser, "s4");
  const t0 = Date.now();
  await scroll(page, "#split");
  await wait(1500);
  await page.getByRole("button", { name: /Split into 5 shares/ }).click();       // "I split a credential…"
  await page.waitForSelector("text=ledger credential was issued");
  await wait(2600);
  await scroll(page, "#custodians");
  await wait(1200);
  await page.locator(".cust").nth(1).getByRole("button", { name: "Forged" }).click(); // "custodian two forges"
  await wait(1700);
  await page.locator(".cust").nth(3).getByRole("button", { name: "Lying" }).click();  // "custodian four lies"
  await wait(2200);
  await scroll(page, "#reveal");
  await page.getByRole("button", { name: "Run the two-round reveal" }).click();     // "Run the reveal"
  await wait(1200);
  await page.evaluate(() => window.scrollBy({ top: 300, behavior: "smooth" }));
  await wait(Math.max(0, 27000 - (Date.now() - t0)));
  await ctx.close();
  console.log("s4 recorded", (Date.now() - t0) / 1000);
}

async function s5(browser) {
  const { ctx, page } = await open(browser, "s5");
  // setup off-camera time is cut later: split first, then scroll to the agent
  await page.getByRole("button", { name: /Split into 5 shares/ }).click();
  await page.waitForSelector("text=ledger credential was issued");
  await scroll(page, "#agent");
  const t0 = Date.now();
  console.log("s5 start offset", (t0 - 0));
  await page.evaluate(() => { window.__t0 = performance.now(); });
  await wait(2500);
  await page.getByRole("button", { name: "Which customers are overdue, and by how much?" }).click();
  await page.waitForSelector("#agent .msg.bot", { timeout: 60000 });
  await wait(9000);
  // three liars, then ask again: refused
  await scroll(page, "#custodians");
  for (const k of [0, 1, 3]) {
    await page.locator(".cust").nth(k).getByRole("button", { name: "Forged" }).click();
    await wait(450);
  }
  await scroll(page, "#agent");
  await page.getByRole("button", { name: "Berapa jumlah invois bulan Oktober?" }).click();
  await page.waitForSelector("#agent .msg.tool.fail", { timeout: 60000 });
  await wait(Math.max(2500, 29000 - (Date.now() - t0)));
  const lead = await page.evaluate(() => window.__t0 / 1000);
  await ctx.close();
  require("fs").writeFileSync("/home/claude/video/rec/s5/lead.txt", String(lead));
  console.log("s5 recorded", (Date.now() - t0) / 1000, "lead", lead);
}

(async () => {
  const b = await chromium.launch();
  if (which === "all" || which === "s4") await s4(b);
  if (which === "all" || which === "s5") await s5(b);
  await b.close();
})();
