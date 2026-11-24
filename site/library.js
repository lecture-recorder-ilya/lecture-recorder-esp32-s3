"use strict";

const get = id => document.getElementById(id);
const audio = get("audio");
const items = new Map();
const speeds = [1, 1.25, 1.5, 2, .75];
let selected = null;
let speed = 1;
let cueButtons = [];
let previousCue = null;
let analyser, context, samples, frame;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");

function stamp(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.floor(seconds));
  return String(Math.floor(total / 60)) + ":" + String(total % 60).padStart(2, "0");
}
function button(label, action, className) {
  const node = document.createElement("button");
  node.type = "button";
  node.textContent = label;
  node.className = className;
  node.addEventListener("click", action);
  return node;
}
function importFiles(files) {
  const additions = Array.from(files).filter(file => file.type.startsWith("audio/") || /\.(mp3|m4a|aac|wav|ogg|oga|opus|flac|aif|aiff|caf|webm)$/i.test(file.name));
  if (!additions.length) { get("notice").textContent = "Выбери аудиофайл с устройства."; return; }
  let first;
  for (const file of additions) {
    const key = JSON.stringify([file.name, file.size, file.lastModified]);
    if (!items.has(key)) items.set(key, {file, audioURL: URL.createObjectURL(file), time: 0, marks: [], cues: []});
    first ??= items.get(key);
  }
  openItem(first);
}
function openItem(item) {
  const changed = selected !== item;
  const restoreFocus = get("file-list").contains(document.activeElement);
  if (selected && selected !== item && audio.readyState >= 1 && Number.isFinite(audio.currentTime)) selected.time = audio.currentTime;
  if (changed) {
    audio.pause();
    selected = item;
    audio.src = item.audioURL;
    audio.load();
    audio.playbackRate = speed;
    get("cue-query").value = "";
  }
  get("notice").textContent = "";
  get("empty").hidden = true;
  get("workspace").hidden = false;
  get("file-title").textContent = item.file.name;
  get("file-list").replaceChildren(...Array.from(items.values(), entry => {
    const row = button(entry.file.name, () => openItem(entry), "file-row");
    row.setAttribute("aria-pressed", String(entry === selected));
    return row;
  }));
  if (restoreFocus) get("file-list").querySelector('[aria-pressed="true"]').focus({preventScroll: true});
  if (changed && !reduceMotion.matches) {
    get("file-title").animate([{opacity: .55, transform: "translateY(5px)"}, {opacity: 1, transform: "none"}],
                              {duration: 220, easing: "ease-out"});
  }
  renderCues();
  renderMarks();
  updatePlayer();
}
function readTime(value) {
  const parts = value.replace(",", ".").split(":").map(Number);
  return parts.reduce((sum, part) => sum * 60 + part, 0);
}
function readCues(text) {
  const cues = [];
  const pattern = /^(?:(?:\d+):)?[0-5]?\d:[0-5]\d[.,]\d{1,3}$/;
  for (const block of text.replace(/^\uFEFF/, "").replace(/\r/g, "").split(/\n[ \t]*\n/)) {
    const lines = block.trim().split("\n");
    if (/^(NOTE(?:\s|$)|STYLE$|REGION$|WEBVTT(?:\s|$))/.test(lines[0])) continue;
    const index = lines.findIndex((line, i) => i <= 1 && line.includes("-->"));
    if (index < 0) continue;
    const match = lines[index].trim().match(/^(\S+)\s+-->\s+(\S+)/);
    if (!match || !pattern.test(match[1]) || !pattern.test(match[2])) continue;
    const start = readTime(match[1]), end = readTime(match[2]);
    const phrase = lines.slice(index + 1).join(" ").replace(/<[^>]+>/g, "").trim();
    if (end > start && phrase) cues.push({start, end, phrase});
  }
  return cues.sort((a, b) => a.start - b.start);
}
async function loadCaptions(file) {
  const item = selected;
  if (!file || !item) return;
  try {
    if (file.size > 8 * 1024 * 1024) throw new Error("Файл субтитров больше 8 МБ.");
    const cues = readCues(await file.text());
    if (!cues.length) throw new Error("Не нашёл фраз с таймкодами. Подойдут файлы SRT и WebVTT.");
    item.cues = cues;
    if (selected === item) { get("cue-query").value = ""; get("notice").textContent = ""; renderCues(); }
  } catch (error) {
    if (selected === item) get("notice").textContent = error.message;
  }
}
function renderCues() {
  const query = get("cue-query").value.toLocaleLowerCase("ru").trim();
  get("cue-query").hidden = !selected.cues.length;
  get("cue-total").textContent = selected.cues.length ? "Фраз: " + selected.cues.length : "";
  get("text-help").hidden = !!selected.cues.length;
  previousCue = null;
  cueButtons = selected.cues.filter(cue => cue.phrase.toLocaleLowerCase("ru").includes(query)).map(cue => {
    const row = button("", () => playAt(cue.start), "cue-row");
    const time = document.createElement("time");
    time.textContent = stamp(cue.start);
    const words = document.createElement("span");
    words.textContent = cue.phrase;
    row.append(time, words);
    return {cue, row};
  });
  get("cues").replaceChildren(...cueButtons.map(entry => entry.row));
  if (query && !cueButtons.length) get("cues").textContent = "Совпадений нет.";
  highlightCue();
}
function highlightCue() {
  const time = audio.currentTime;
  const current = cueButtons.find(entry => time >= entry.cue.start && time < entry.cue.end);
  if (current === previousCue) return;
  previousCue?.row.removeAttribute("aria-current");
  current?.row.setAttribute("aria-current", "true");
  previousCue = current;
}
function renderMarks() {
  const marks = get("marks");
  marks.replaceChildren(...selected.marks.map(time => button(stamp(time), () => playAt(time), "mark-time")));
  if (!selected.marks.length) marks.textContent = "Пока пусто.";
}
function updatePlayer() {
  const ready = Number.isFinite(audio.duration) && audio.duration > 0;
  get("play").disabled = !!audio.error;
  get("add-mark").disabled = !ready;
  get("seek").disabled = !ready;
  get("seek").max = ready ? String(audio.duration) : "0";
  get("seek").value = String(audio.currentTime || 0);
  get("seek").setAttribute("aria-valuetext", stamp(audio.currentTime));
  get("elapsed").textContent = stamp(audio.currentTime);
  get("length").textContent = stamp(audio.duration);
  get("play").classList.toggle("playing", !audio.paused);
  get("play").setAttribute("aria-label", audio.paused ? "Слушать" : "Пауза");
  highlightCue();
}
function createMeter() {
  const AudioEngine = window.AudioContext || window.webkitAudioContext;
  if (!AudioEngine) return;
  try {
    context ??= new AudioEngine();
    if (context.state === "suspended") context.resume().catch(() => {});
    if (context.state !== "running" || analyser) return;
    const meter = context.createAnalyser();
    meter.fftSize = 256;
    const source = context.createMediaElementSource(audio);
    source.connect(context.destination);
    source.connect(meter);
    samples = new Uint8Array(meter.fftSize);
    analyser = meter;
  } catch {}
}
function drawSignal() {
  cancelAnimationFrame(frame);
  const canvas = get("signal"), ctx = canvas.getContext("2d");
  if (!ctx || !selected || document.hidden) return;
  const width = Math.max(1, Math.round(canvas.clientWidth)), height = 18;
  const ratio = Math.min(devicePixelRatio || 1, 2);
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
  }
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const live = !audio.paused && analyser && !reduceMotion.matches;
  if (live) analyser.getByteTimeDomainData(samples);
  ctx.beginPath();
  for (let i = 0; i < 128; i++) {
    const x = i * width / 127, y = live ? height / 2 - (samples[2*i] - 128) / 128 * height * .48 : height / 2;
    if (i === 0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  }
  ctx.strokeStyle = live ? "#ffbe75" : "#758e8f"; ctx.lineWidth = 1.5; ctx.stroke();
  if (live) frame = requestAnimationFrame(drawSignal);
}
function playAt(time) {
  if (!selected) return;
  if (Number.isFinite(audio.duration) && Number.isFinite(time)) audio.currentTime = Math.max(0, Math.min(time, audio.duration));
  createMeter();
  audio.play().then(() => { createMeter(); drawSignal(); }).catch(() => {
    get("notice").textContent = "Браузер не воспроизвёл этот файл. Попробуй MP3, WAV или M4A.";
  });
}
get("choose").onclick = () => get("files").click();
get("files").onchange = event => { importFiles(event.target.files); event.target.value = ""; };
get("import-text").onclick = () => get("captions").click();
get("captions").onchange = event => { loadCaptions(event.target.files[0]); event.target.value = ""; };
get("cue-query").oninput = renderCues;
get("play").onclick = () => { if (audio.paused) playAt(); else audio.pause(); };
get("rate").onclick = () => {
  speed = speeds[(speeds.indexOf(speed) + 1) % speeds.length]; audio.playbackRate = speed;
  get("rate").textContent = String(speed).replace(".", ",") + "×";
  get("rate").setAttribute("aria-label", "Скорость " + get("rate").textContent + ". Изменить");
};
get("seek").oninput = () => { if (Number.isFinite(audio.duration)) audio.currentTime = Number(get("seek").value); };
get("add-mark").onclick = () => {
  const time = Math.floor(audio.currentTime);
  if (!selected.marks.includes(time)) selected.marks.push(time);
  selected.marks.sort((a,b) => a-b);
  renderMarks();
};
audio.addEventListener("loadedmetadata", () => {
  if (selected && Number.isFinite(audio.duration)) audio.currentTime = Math.min(selected.time, audio.duration);
  updatePlayer(); drawSignal();
});
for (const event of ["play","pause","ended","timeupdate","durationchange","seeked"]) audio.addEventListener(event, updatePlayer);
for (const event of ["play","pause","ended"]) audio.addEventListener(event, drawSignal);
audio.addEventListener("error", () => { get("notice").textContent = "Не удалось открыть аудио. Попробуй MP3, WAV или M4A."; updatePlayer(); });
document.addEventListener("visibilitychange", drawSignal);
reduceMotion.addEventListener("change", drawSignal);
window.addEventListener("resize", drawSignal);
for (const event of ["dragover","drop"]) window.addEventListener(event, e => {
  if (!e.dataTransfer.types.includes("Files")) return;
  e.preventDefault();
  if (event === "drop") importFiles(e.dataTransfer.files);
});
window.addEventListener("pagehide", event => {
  audio.pause(); cancelAnimationFrame(frame);
  if (!event.persisted) for (const entry of items.values()) URL.revokeObjectURL(entry.audioURL);
});
