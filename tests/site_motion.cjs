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
    const gl = canvas.getContext("webgl");
    const pixels = new Uint8Array(canvas.width * 4);
    gl.readPixels(0, Math.floor(canvas.height / 2), canvas.width, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let width = 0;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 190) width++;
    return width;
  });
}

test("Прокрутка поворачивает корпус на компьютере и телефоне", async t => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN || undefined,
    args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]});
  t.after(() => browser.close());
  for (const [width, height, phone] of [[1280, 820, false], [390, 820, true], [844, 390, true]]) {
    await t.test(width + " × " + height, async () => {
      const context = await browser.newContext({viewport: {width, height}, isMobile: phone, hasTouch: phone});
      try {
        const page = await context.newPage();
        await page.addInitScript(() => {
          const getContext = HTMLCanvasElement.prototype.getContext;
          HTMLCanvasElement.prototype.getContext = function (type, options) {
            return getContext.call(this, type, type === "webgl" ? {...options, preserveDrawingBuffer: true} : options);
          };
        });
        const mesh = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/assets/zu-prototype.glb"));
        await page.goto(url);
        const response = await mesh;
        assert.ok(response.ok());
        const body = await response.body();
        assert.equal(body.toString("ascii", 0, 4), "glTF");
        const gltf = JSON.parse(body.toString("utf8", 20, 20 + body.readUInt32LE(12)));
        assert.ok(gltf.meshes.length > 0 && gltf.materials.length > 1);
        await page.waitForSelector('.model-stage[data-rendered="true"]');
        const typefaces = await page.evaluate(async () => {
          await document.fonts.ready;
          return Array.from(document.fonts)
            .filter(font => font.family.replaceAll('"', '') === "Zu Forma" && font.status === "loaded")
            .map(font => font.weight).sort();
        });
        assert.deepEqual(typefaces, ["400", "600"]);
        assert.equal(await page.locator(".top .brand").innerText(), "зу");
        assert.match(await page.locator("#product-title").innerText(), /Слушай сейчас\.\s*К словам — потом\./);
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
        await page.waitForFunction(() => document.querySelector("#model-angle").textContent === "Платы микрофонов");
        await scrollScene(page, .62);
        await page.waitForFunction(() => document.querySelector("#model-angle").textContent === "Обратная сторона");
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
        const moving = await page.locator("#sound-ribbon").evaluate(canvas => canvas.toDataURL());
        await page.waitForFunction(previous => document.querySelector("#sound-ribbon").toDataURL() !== previous,
          moving, {polling: 120, timeout: 6000});
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

test("Без WebGL доступны четыре ракурса той же сборки", async t => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN || undefined, args: ["--disable-webgl"]});
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.goto(url);
  const stage = page.locator('.model-stage[data-rendered="static"]');
  await stage.waitFor();
  for (const view of ["side", "back", "detail", "front"]) {
    const button = page.locator('[data-model-view=' + view + ']');
    await button.click();
    assert.equal(await button.getAttribute("aria-pressed"), "true");
    await page.waitForFunction(() => {
      const img = document.querySelector(".model-poster");
      return img.complete && img.naturalWidth > 0;
    });
  }
});

test("Таймкод работает до загрузки метаданных и учитывает начало файла", async t => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN || undefined});
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.addInitScript(() => {
    const create = URL.createObjectURL.bind(URL);
    URL.createObjectURL = file => file.name === "позиции.wav" ? new URL("slow-position.wav", location.href).href : create(file);
  });
  await page.goto(new URL("library.html", url).href);
  const audio = page.locator("#audio");
  await audio.evaluate(element => {
    element.preload = "none";
    element.muted = true;
    element.addEventListener("loadedmetadata", () => { element.dataset.firstPosition = String(element.currentTime); }, {once: true});
  });
  const rate = 8000, frames = rate * 6;
  const wav = Buffer.alloc(44 + frames, 128);
  wav.write("RIFF", 0); wav.writeUInt32LE(frames + 36, 4); wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate, 28); wav.writeUInt16LE(1, 32); wav.writeUInt16LE(8, 34);
  wav.write("data", 36); wav.writeUInt32LE(frames, 40);
  let releaseAudio;
  const available = new Promise(resolve => { releaseAudio = resolve; });
  await page.route("**/slow-position.wav", async route => {
    await available;
    const range = route.request().headers().range?.match(/^bytes=(\d+)-(\d*)$/);
    const first = range ? Number(range[1]) : 0;
    const last = range?.[2] ? Math.min(Number(range[2]), wav.length - 1) : wav.length - 1;
    const headers = {"Accept-Ranges": "bytes", "Content-Type": "audio/wav", "Content-Length": String(last - first + 1)};
    if (range) headers["Content-Range"] = `bytes ${first}-${last}/${wav.length}`;
    await route.fulfill({status: range ? 206 : 200, headers, body: wav.subarray(first, last + 1)});
  });
  await page.locator("#files").setInputFiles({name: "позиции.wav", mimeType: "audio/wav", buffer: wav});
  const captions = "1\n00:00:00,400 --> 00:00:01,400\nНачало\n\n2\n00:00:04,000 --> 00:00:05,000\nКонец\n";
  await page.locator("#captions").setInputFiles({name: "позиции.srt", mimeType: "application/x-subrip", buffer: Buffer.from(captions)});
  const cues = page.locator(".cue-row");
  await cues.nth(1).waitFor();
  assert.equal(await audio.evaluate(element => element.readyState), 0);
  await cues.nth(1).click();
  releaseAudio();
  await page.waitForFunction(() => document.querySelector("#audio").dataset.firstPosition !== undefined);
  assert.equal(Number(await audio.getAttribute("data-first-position")), 4);
  await page.locator("#lead-in").check();
  const position = async index => {
    await cues.nth(index).click();
    return audio.evaluate(element => { element.pause(); return element.currentTime; });
  };
  const earlier = await position(1);
  assert.ok(earlier >= 2 && earlier < 2.7);
  assert.ok(await position(0) < .7);
});
