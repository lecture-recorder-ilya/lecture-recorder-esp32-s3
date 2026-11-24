const { test } = require("node:test");
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const { chromium } = require("playwright-core");

const url = process.env.SITE_URL || "http://127.0.0.1:4173/";

async function scrollScene(page, progress, checkProgress = true) {
  await page.evaluate(fraction => {
    const scene = document.querySelector(".model-sequence");
    const pin = scene.querySelector(".model-pin");
    const start = window.scrollY + scene.getBoundingClientRect().top - parseFloat(getComputedStyle(pin).top);
    window.scrollTo({top: start + (scene.offsetHeight - pin.offsetHeight) * fraction, behavior: "instant"});
  }, progress);
  if (!checkProgress) return;
  await page.waitForFunction(fraction => {
    const scene = document.querySelector(".model-sequence");
    return Math.abs(Number(getComputedStyle(scene).getPropertyValue("--model-progress")) - fraction) < .03;
  }, progress);
}

async function frameDigest(page, selector = "#device-model") {
  const pixels = await page.locator(selector).evaluate(canvas => canvas.toDataURL());
  return createHash("sha256").update(pixels).digest("hex");
}

async function showRibbon(page) {
  const ribbon = page.locator("#sound-ribbon");
  await ribbon.evaluate(canvas => canvas.scrollIntoView({block: "center", behavior: "instant"}));
  await page.waitForFunction(() => {
    const canvas = document.querySelector("#sound-ribbon");
    if (!canvas.closest(".source-panel").classList.contains("in-view")) return false;
    const center = Math.floor(canvas.width / 2);
    const pixels = canvas.getContext("2d").getImageData(center, 0, 1, canvas.height).data;
    return pixels.some((channel, i) => i % 4 === 3 && channel > 0);
  });
}

async function silhouette(page) {
  return page.locator("#device-model").evaluate(canvas => {
    const pixels = canvas.getContext("2d").getImageData(0, Math.floor(canvas.height / 2), canvas.width, 1).data;
    let width = 0;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 190) width++;
    return width;
  });
}

test("Прокрутка поворачивает корпус на компьютере и телефоне", async t => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN || undefined});
  t.after(() => browser.close());
  for (const [width, height, phone] of [[1280, 820, false], [390, 820, true], [844, 390, true]]) {
    await t.test(width + " × " + height, async () => {
      const context = await browser.newContext({viewport: {width, height}, isMobile: phone, hasTouch: phone});
      try {
        const page = await context.newPage();
        await page.goto(url);
        await page.waitForSelector('.model-stage[data-rendered="true"]');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
        const widths = [];
        for (const fraction of [.08, .22, .38, .5, .62, .78, .94]) {
          await scrollScene(page, fraction);
          await page.waitForTimeout(450);
          widths.push(await silhouette(page));
        }
        assert.ok(Math.min(...widths) < Math.max(...widths) * .7, "При виде сбоку силуэт должен заметно сужаться");
        const pinTop = await page.locator(".model-pin").evaluate(pin => pin.getBoundingClientRect().top);
        assert.ok(pinTop >= 0 && pinTop <= 16);
        await scrollScene(page, .5);
        await page.waitForTimeout(550);
        assert.ok(Math.abs(await silhouette(page) - widths[3]) < Math.max(...widths) * .14, "Обратная прокрутка возвращает тот же ракурс");

        await page.locator("[data-model-view=detail]").click();
        await page.waitForFunction(() => document.querySelector("#model-angle").textContent === "Дисплей и кнопка");
        await scrollScene(page, .87);
        await page.waitForFunction(() => document.querySelector("#model-angle").textContent === "Спинка");
        assert.equal(await page.locator("[data-model-view=detail]").getAttribute("aria-pressed"), "false");

        await page.locator("#model-motion").click();
        await page.waitForTimeout(230);
        const paused = await frameDigest(page);
        await scrollScene(page, .77, false);
        await page.waitForTimeout(280);
        assert.equal(await frameDigest(page), paused);
        await page.locator("[data-model-view=detail]").click();
        await page.waitForTimeout(1000);
        assert.notEqual(await frameDigest(page), paused);

        await showRibbon(page);
        const moving = await frameDigest(page, "#sound-ribbon");
        await page.waitForTimeout(180);
        assert.notEqual(await frameDigest(page, "#sound-ribbon"), moving);
        await page.locator("[data-source=file]").click();
        assert.equal(await page.locator(".source-panel").getAttribute("data-mode"), "file");
        await page.locator("footer").evaluate(footer => footer.scrollIntoView({behavior: "instant"}));
        await page.waitForFunction(() => !document.querySelector(".source-panel").classList.contains("in-view"));
        const hidden = await frameDigest(page, "#sound-ribbon");
        await page.waitForTimeout(160);
        assert.equal(await frameDigest(page, "#sound-ribbon"), hidden);

        await page.emulateMedia({reducedMotion: "reduce"});
        await page.goto("about:blank");
        await page.goto(url);
        await page.waitForSelector('.model-stage[data-rendered="true"]');
        const still = await frameDigest(page);
        await page.evaluate(() => window.scrollBy({top: 200, behavior: "instant"}));
        await page.waitForTimeout(250);
        assert.equal(await frameDigest(page), still);
        await showRibbon(page);
        const quiet = await frameDigest(page, "#sound-ribbon");
        await page.waitForTimeout(220);
        assert.equal(await frameDigest(page, "#sound-ribbon"), quiet);
      } finally {
        await context.close();
      }
    });
  }
});
