// Captures docs/screenshots/{listing,search,detail}.png from a running dev server (see docs/week4-frontend.md).
//   npx playwright install chromium   (once)
//   npm run screenshots               (APP_URL=http://localhost:5173 SEARCH_QUERY=bicep)
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const appUrl = (process.env.APP_URL ?? "http://localhost:5173").replace(/\/$/, "");
const query = process.env.SEARCH_QUERY ?? "bicep";
const outDir = resolve(import.meta.dirname, "../../docs/screenshots");
await mkdir(outDir, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
const shot = async (name) => {
  await page.screenshot({ path: resolve(outDir, `${name}.png`), fullPage: true });
  console.log(`saved docs/screenshots/${name}.png`);
};

try {
  await page.goto(`${appUrl}/`);
  await page.locator(".mcl-card").first().waitFor();
  await page.locator(".mcl-facet").first().waitFor();
  await shot("listing");

  await page.getByRole("searchbox", { name: "Search minicodes" }).fill(query);
  await page.getByRole("button", { name: "Search" }).click();
  await page.locator(".mcl-hit").first().waitFor();
  await shot("search");

  await page.locator(".mcl-hit").first().click();
  await page.getByRole("heading", { level: 1 }).waitFor();
  const video = page.locator("video");
  if (await video.count()) {
    // wait until the player has seeked to ?t= so the frame shows the jump target
    await page.waitForFunction(() => {
      const v = document.querySelector("video");
      return v && v.readyState >= 2 && !v.seeking && v.currentTime > 0;
    });
    await video.evaluate((v) => v.pause());
  }
  await page.waitForTimeout(300);
  await shot("detail");
  console.log(`detail URL: ${page.url()}`);
} finally {
  await browser.close();
}
