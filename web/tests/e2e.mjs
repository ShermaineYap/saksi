// End-to-end check of every flow. Usage: node tests/e2e.mjs [baseUrl] [outDir]
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require("playwright"); } catch { pw = require(process.env.PW_PATH); }
const { chromium } = pw;

const base = process.argv[2] || "http://localhost:3123";
const out = process.argv[3] || ".";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

const ok = (c, m) => { if (!c) { console.error("FAIL:", m); process.exitCode = 1; } else console.log("ok:", m); };

await page.goto(base, { waitUntil: "networkidle" });
await page.waitForSelector(".matrix .cell.no", { timeout: 15000 });
ok((await page.locator(".hero .cell.no").count()) === 4, "hero: forged share 2 rejected by all 4 witnesses");
await page.screenshot({ path: `${out}/01-hero.png` });

// split a credential
await page.getByRole("button", { name: /Split into 5 shares/ }).click();
await page.waitForSelector("text=Shares issued");
await page.waitForSelector("text=ledger credential was issued");
ok(true, "credential split");

// reveal all honest
await page.getByRole("button", { name: "Run the two-round reveal" }).click();
await page.waitForSelector(".verdict.good");
ok((await page.locator("#reveal .verdict").innerText()).includes("Key rebuilt correctly"), "honest reveal rebuilds the key");

// custodian 2 forged + custodian 4 lying
const c2 = page.locator(".cust").nth(1); await c2.getByRole("button", { name: "Forged" }).click();
const c4 = page.locator(".cust").nth(3); await c4.getByRole("button", { name: "Lying" }).click();
await page.getByRole("button", { name: "Run the two-round reveal" }).click();
await page.waitForTimeout(600);
const v = await page.locator("#reveal .verdict").innerText();
ok(v.includes("Key rebuilt correctly") && v.includes("2 (") && v.includes("4 ("), "two liars named, key still correct");
ok((await page.locator("#reveal .compare").innerText()).includes("silently wrong key"), "plain Shamir fooled");
await page.locator("#reveal").screenshot({ path: `${out}/02-reveal.png` });

// agent (scripted if no LLM key)
await page.getByRole("button", { name: "Which customers are overdue, and by how much?" }).click();
await page.waitForSelector("#agent .msg.tool", { timeout: 60000 });
await page.waitForTimeout(1500);
const chat = await page.locator("#agent .chat").innerText();
ok(chat.includes("fetch_ledger(overdue"), "agent called the tool");
ok((await page.locator("#agent .zero").innerText()).trim() === "0", "zero credential fragments in LLM traffic");
await page.locator("#agent").screenshot({ path: `${out}/03-agent.png` });

// three liars -> fail closed
await page.locator(".cust").nth(0).getByRole("button", { name: "Forged" }).click();
await page.getByRole("button", { name: "Run the two-round reveal" }).click();
await page.waitForTimeout(600);
ok((await page.locator("#reveal .verdict").innerText()).includes("Refused"), "three bad custodians: fail closed");

// attack lab
await page.locator("#lab").getByRole("button", { name: "Run" }).first().click();
await page.waitForFunction(() => !document.querySelector("#lab")?.textContent?.includes("Running"), null, { timeout: 120000 });
const lab = await page.locator("#lab .lab-table").first().innerText();
ok(/0\.0%/.test(lab), "attack lab: SAKSI 0.0% wrong");
await page.locator("#lab").screenshot({ path: `${out}/04-lab.png` });

// mobile
const m = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
await m.goto(base, { waitUntil: "networkidle" });
await m.waitForSelector(".matrix .cell.no");
const overflow = await m.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
ok(overflow <= 0, `mobile: no horizontal scroll (${overflow}px)`);
await m.screenshot({ path: `${out}/05-mobile.png`, fullPage: false });

const real = errors.filter((e) => !e.includes("503"));
ok(real.length === 0, `no console errors other than the expected 503 when no LLM key is set ${real.join(" | ")}`);
await browser.close();
