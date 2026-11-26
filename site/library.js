"use strict";

const get = id => document.getElementById(id);
const audio = get("audio");
const store = globalThis.ZuLibraryStorage;
const items = new Map();
const speeds = [1, 1.25, 1.5, 2, .75];
let selected = null, favoritesOnly = false, counter = 0;
let pendingTime = null, speed = 1, cueButtons = [], previousCue = null, cueLimit=120;
let fingerprintQueue=Promise.resolve(), savedListRequest=0;
let analyser, context, samples, frame;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");

function importFiles(files) {
  const additions=Array.from(files).filter(file=>file.type.startsWith("audio/") || /\.(mp3|m4a|aac|wav|ogg|oga|opus|flac|aif|aiff|caf|webm)$/i.test(file.name));
  if(!additions.length) {get("notice").textContent="Выбери аудиофайл с устройства.";return;}
  const entries=additions.map(file=>{
    const item={...store.empty(),file,key:++counter,id:null,audioURL:URL.createObjectURL(file),mode:"checking",percent:0,
      private:get("temporary-only").checked,pending:[],retries:[],waiting:0,revision:0,exported:0,feedback:"",timeTouched:false,draft:"",editing:null};
    items.set(item.key,item);
    item.ready=fingerprintQueue.then(()=>identifyItem(item));
    fingerprintQueue=item.ready.catch(()=>{});
    return item;
  });
  favoritesOnly=false;
  openItem(entries[0]);
}
function legacyFor(file) {
  try {
    const key=JSON.stringify([file.name,file.size,file.lastModified]);
    const raw=JSON.parse(localStorage.getItem("zu-map:pins:"+key) || "[]");
    const pins=Array.isArray(raw)?raw.filter(n=>Number.isFinite(n)&&n>=0):[];
    const favorite=localStorage.getItem("zu-library:favorite:"+key)==="1";
    return favorite||pins.length?{...store.empty(),favorite,pins}:null;
  } catch {return null;}
}
async function identifyItem(item) {
  try {
    item.id=await store.identify(item.file,percent=>{
      item.percent=percent;
      if(selected===item && item.mode==="checking") storageUI(item);
    });
  } catch {
    item.mode="unidentified";item.pending=[];storageUI(item);return item;
  }
  const same=Array.from(items.values()).find(other=>other!==item && other.id===item.id && other.file.size===item.file.size && other.private===item.private);
  if(same) {
    for(const action of item.pending) change(same,action);
    if(item.draft) same.draft=item.draft;
    items.delete(item.key);
    if(selected===item) {selected=null;openItem(same);}
    else if(selected) renderFiles();
    URL.revokeObjectURL(item.audioURL);
    return same;
  }
  try {
    const record=item.private ? null : await store.read(item.id);
    const pending=item.pending.splice(0);
    if(record) {
      Object.assign(item,record.work); item.mode="saved";item.epoch=record.epoch;
      for(const action of pending) {store.apply(item,action);persist(item,action);}
      item.feedback="Открыты сохранённые заметки этой записи.";
      if(selected===item && !item.timeTouched) restorePosition(item);
    } else {
      item.mode="temporary";
      if(!item.private) item.legacy=legacyFor(item.file);
    }
  } catch {item.pending=[];item.mode="blocked";}
  if(selected===item) renderWork(item);
  return item;
}
function restorePosition(item) {
  if(selected!==item) return;
  if(audio.readyState>=1 && Number.isFinite(audio.duration)) audio.currentTime=Math.min(item.time,audio.duration);
  else pendingTime=item.time;
}
function openItem(item) {
  const changed=selected!==item;
  const restoreFocus=get("file-list").contains(document.activeElement);
  if(changed) {
    if(selected) {capturePosition(true);selected.draft=get("note-text").value;}
    audio.pause();pendingTime=null;selected=item;
    audio.src=item.audioURL;audio.load();audio.playbackRate=speed;
    get("cue-query").value="";cueLimit=120;
    get("note-text").value=item.draft;
    get("cancel-note").hidden=!item.editing;
    get("add-note").textContent=item.editing?"Сохранить правку":"Добавить к этой секунде";
  }
  get("notice").textContent="";
  get("empty").hidden=true;get("workspace").hidden=false;
  get("file-title").textContent=item.file.name;
  renderWork(item);updatePlayer();
  if(restoreFocus) get("file-list").querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});
  if(changed && !reduceMotion.matches) get("file-title").animate([{opacity:.55,transform:"translateY(5px)"},{opacity:1,transform:"none"}],{duration:220,easing:"ease-out"});
}
function renderWork(item) {
  if(item!==selected) return;
  renderFiles();renderCues();renderMarks();renderNotes();storageUI(item);
}
function storageUI(item) {
  if(item!==selected) return;
  const labels={checking:"Проверяем файл",temporary:"Только в этой вкладке",blocked:"Хранилище недоступно",unidentified:"Не удалось проверить файл",saving:"Сохраняем заметки",saved:"Сохранение на этом устройстве включено"};
  const messages={
    checking:"Сверяем содержимое записи"+(item.percent?" · "+item.percent+"%":"")+". Уже можно слушать и делать заметки.",
    temporary:"Сейчас текст и отметки доступны до закрытия вкладки. Включи сохранение или скачай заметки в JSON.",
    blocked:"Вкладка продолжает работать. Скачай заметки в JSON перед выходом. Их можно открыть вместе с исходным аудио.",
    unidentified:"Чтение записи прервалось. Проверь доступ к исходному файлу. Можно скачать заметки без отпечатка аудио и позже вручную подтвердить привязку.",
    saving:"Сохраняем текст, позицию, закладки, свои заметки, избранное и отметки карты.",
    saved:"Здесь остаются текст, позиция, закладки, свои заметки, избранное и отметки карты. В следующий раз выбери исходное аудио. При очистке данных сайта или закрытии приватного окна копия может исчезнуть."
  };
  const heading=get("storage-mode");
  if(heading.dataset.mode!==item.mode) {heading.dataset.mode=item.mode;heading.textContent=labels[item.mode];}
  const explanation=messages[item.mode];
  if(get("storage-explain").textContent!==explanation) get("storage-explain").textContent=explanation;
  const save=get("save-work");
  save.hidden=item.mode==="unidentified" || item.private;
  save.disabled=item.mode==="checking" || item.mode==="saving";
  save.textContent=item.mode==="saved"?"Удалить сохранённую копию":item.mode==="blocked"?"Повторить сохранение":"Сохранять на этом устройстве";
  get("import-work").disabled=!item.id || item.mode==="checking";
  get("export-work").disabled=item.mode==="checking";
  get("legacy-work").hidden=!item.legacy;
  if(get("storage-feedback").textContent!==item.feedback) get("storage-feedback").textContent=item.feedback;
  get("import-text").textContent=item.cues.length?"Заменить субтитры":"Добавить субтитры";
}
function change(item,action) {
  try {store.apply(item,action);} catch(err) {item.feedback=err.message;storageUI(item);return false;}
  item.revision++;
  if(item.mode==="checking" || item.mode==="saving") item.pending.push(action);
  if(item.mode==="saved") persist(item,action);
  else if(item.mode==="blocked" && item.epoch) rememberRetry(item,action);
  updateExitWarning();return true;
}
function rememberRetry(item,action) {
  if(action.kind==="time") return;
  item.retries.push(action);
}
function persist(item,action) {
  item.waiting++;
  const epoch=item.epoch;
  store.update(item.id,epoch,action).catch(err=>{
    if(item.epoch!==epoch) return;
    rememberRetry(item,action);
    item.mode=err.message==="removed"?"temporary":"blocked";
    item.feedback=err.message==="removed"?"Сохранённая копия удалена в другой вкладке. Здесь осталась открытая работа.":"Сохрани текущую работу в файл заметок.";
    storageUI(item);
  }).finally(()=>{item.waiting--;updateExitWarning();});
}
async function enableSave(item) {
  item.mode="saving";item.pending=[];item.feedback="";storageUI(item);
  try {
    const record=await store.save(item.id,item.file,store.snapshot(item),item.retries);
    item.retries=[];
    const pending=item.pending.splice(0);
    Object.assign(item,record.work);item.mode="saved";item.epoch=record.epoch;
    for(const action of pending) {store.apply(item,action);persist(item,action);}
    item.feedback="Готово. Аудио остаётся в исходном файле.";
    if(get("saved-library").open) renderSaved();
  } catch {item.mode="blocked";item.pending=[];item.feedback="Скачай JSON, чтобы перенести заметки.";}
  renderWork(item);updateExitWarning();
}
function capturePosition(force=false) {
  const item=selected;
  if(!item || !item.timeTouched || audio.readyState<1 || audio.currentSrc!==item.audioURL || !Number.isFinite(audio.currentTime)) return;
  const value=store.milliseconds(audio.currentTime);
  if(Math.abs(value-item.time)<(force ? .001 : 3)) return;
  change(item,{kind:"time",value});
}
function checkpoint() {
  capturePosition(true);
  const item=selected;
  if(item?.mode==="saved" && item.epoch && item.timeTouched) store.journal(store.point(item.id,item.epoch,item.time));
}
function markPoint(time) {
  const item=selected;
  item.timeTouched=true;
  if(Number.isFinite(time)) change(item,{kind:"time",value:store.milliseconds(Math.max(0,time))});
}
let hasExitWarning=false;
function beforeExit(event) {event.preventDefault();event.returnValue="";}
function updateExitWarning() {
  const dirty=Array.from(items.values()).some(item=>(item.mode!=="saved" && item.revision>item.exported) || item.waiting || item.mode==="saving" || item.draft.trim());
  if(!!dirty===hasExitWarning) return;
  hasExitWarning=!!dirty;
  if(dirty) window.addEventListener("beforeunload",beforeExit);
  else window.removeEventListener("beforeunload",beforeExit);
}
function downloadBackup(id,file,work) {
  const data=new Blob([JSON.stringify(store.backup(id,file,work))],{type:"application/json"});
  const url=URL.createObjectURL(data);
  const link=document.createElement("a");link.href=url;link.download=file.name.replace(/\.[^.]+$/,"")+".zu.json";
  document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),60000);
}
async function loadBackup(file,item) {
  if(!file || !item?.id) return;
  try {
    if(file.size>128*1024*1024) throw Error("Размер JSON больше 128 МБ.");
    let raw;
    try {raw=JSON.parse(await file.text());} catch {throw Error("Не удалось прочитать JSON заметок.");}
    const incoming=store.unpack(raw);
    if(incoming.size!==item.file.size || (incoming.id!==null && incoming.id!==item.id)) throw Error("Этот JSON относится к другой записи. Содержимое аудио отличается.");
    if(incoming.id===null) {
      if(incoming.name!==item.file.name) throw Error("У JSON нет отпечатка аудио. Для ручной сверки нужны исходное имя и размер записи.");
      if(!confirm("Отпечаток аудио в этом JSON отсутствует. Совпали только имя и размер. Это точно твоя запись «"+item.file.name+"»?")) return;
    }
    const allowTime=!item.timeTouched && !item.time;
    if(!change(item,{kind:"merge",value:incoming.work,allowTime})) return;
    if(allowTime) restorePosition(item);
    item.feedback="Заметки объединены. Текущие фразы и ручные правки сохранены.";
    renderWork(item);
  } catch(err) {item.feedback=err.message;storageUI(item);}
}
async function deleteSaved(id) {
  if(!confirm("Удалить сохранённые заметки этой записи из браузера? Аудиофайл останется на устройстве. Открытая работа останется во вкладке.")) return;
  try {
    await store.remove(id);
    forgetOpen(id);
    changes?.postMessage({removed:id});
    await renderSaved();
  } catch {get("notice").textContent="Браузер не подтвердил удаление. Попробуй ещё раз.";}
}
let changes;
try {changes=new BroadcastChannel("zu-library-record-changes");} catch {}
function forgetOpen(id) {
  for(const item of items.values()) if(item.id===id && !item.private) {
    item.epoch=null;item.retries=[];item.mode="temporary";item.revision++;
    item.feedback="Сохранённая копия удалена. Открытую работу можно скачать в JSON.";storageUI(item);
  }
  updateExitWarning();
}
if(changes) changes.onmessage=event=>{
  if(typeof event.data?.removed==="string") {forgetOpen(event.data.removed);if(get("saved-library").open) renderSaved();}
};
async function renderSaved() {
  const version=++savedListRequest;
  const area=get("saved-list");
  if(!get("saved-library").open) return;
  try {
    const rows=await store.list();
    if(version!==savedListRequest) return;
    area.replaceChildren();
    if(!rows.length) {area.textContent="Сохранённых заметок пока нет.";return;}
    const info=document.createElement("p");info.textContent="Чтобы продолжить слушать, открой исходное аудио. Его можно переименовать.";area.append(info);
    for(const row of rows) {
      const section=document.createElement("div");section.className="saved-work-row";
      const title=document.createElement("strong");title.textContent=row.name+(rows.some(other=>other!==row && other.name===row.name)?" · "+row.id.slice(0,8):"");
      section.append(title,button("Скачать JSON",async()=>{
        try {const full=await store.read(row.id);if(!full) return renderSaved();downloadBackup(row.id,{name:full.name,size:full.size},full.work);}
        catch {get("notice").textContent="Не удалось получить заметки из хранилища.";}
      },"text-action"),button("Удалить",()=>deleteSaved(row.id),"text-action"));
      area.append(section);
    }
  } catch {area.textContent="Хранилище браузера недоступно. Можно работать с файлами заметок JSON.";}
}
function renderNotes() {
  const item=selected;
  get("notes-list").replaceChildren(...[...item.notes].sort((a,b)=>a.time-b.time).map(note=>{
    const box=document.createElement("div");box.className="item-note";
    const text=document.createElement("p");text.textContent=note.text;
    const actions=document.createElement("div");actions.className="note-actions";
    const listen=button(stamp(note.time),()=>playAt(note.time),"mark-time");listen.setAttribute("aria-label","Слушать с "+stamp(note.time));
    actions.append(listen,button("Изменить",()=>{
      item.editing=note.id;item.draft=note.text;get("note-text").value=note.text;get("cancel-note").hidden=false;
      get("add-note").textContent="Сохранить правку";get("note-text").focus();updateExitWarning();
    },"text-action"),button("Удалить",()=>{
      change(item,{kind:"note",id:note.id,before:note,value:null});if(item.editing===note.id) resetDraft(item);renderNotes();renderMap();
    },"text-action"));
    box.append(text,actions);return box;
  }));
}
function resetDraft(item) {
  item.editing=null;item.draft="";get("note-text").value="";get("cancel-note").hidden=true;get("add-note").textContent="Добавить к этой секунде";updateExitWarning();
}
get("inline-transcribe").onclick=()=>{get("transcribe-help").open=true;get("transcribe-help").querySelector("summary").focus();};
get("save-work").onclick=()=>{if(selected?.mode==="saved") deleteSaved(selected.id);else if(selected?.id) enableSave(selected);};
get("export-work").onclick=async()=>{
  const item=selected;
  if(!item || item.mode==="checking") return;
  capturePosition(true);
  const revision=item.revision;
  let work=store.snapshot(item);
  if(item.mode==="saved") {
    try {
      const saved=await store.read(item.id);
      if(saved?.epoch===item.epoch && item.mode==="saved" && item.revision===revision) work=saved.work;
    } catch {}
  }
  downloadBackup(item.id,item.file,work);item.exported=revision;
  item.feedback="Файл заметок передан браузеру для скачивания.";storageUI(item);updateExitWarning();
};
get("import-work").onclick=()=>get("notes-file").click();
get("notes-file").onchange=e=>{loadBackup(e.target.files[0],selected);e.target.value="";};
get("saved-library").ontoggle=renderSaved;
get("legacy-work").onclick=()=>{
  const item=selected;
  if(!item?.legacy || !confirm("Прежняя версия связывала отметки с именем, размером и датой файла. Перенести их в текущую запись?")) return;
  change(item,{kind:"merge",value:item.legacy,allowTime:false});item.legacy=null;
  item.feedback="Прежние отметки перенесены в открытую запись.";renderWork(item);
};
get("note-form").onsubmit=event=>{
  event.preventDefault();
  const item=selected,text=get("note-text").value.trim();if(!item || !text) return;
  const old=item.notes.find(note=>note.id===item.editing);
  const value={id:old?.id||store.token(),time:old?.time??store.milliseconds(audio.currentTime||0),text};
  if(!change(item,{kind:"note",id:value.id,before:old,conflictId:store.token(),value})) return;
  resetDraft(item);renderNotes();renderMap();get("note-text").focus();
};
get("note-text").oninput=()=>{selected.draft=get("note-text").value;updateExitWarning();};
get("cancel-note").onclick=()=>resetDraft(selected);

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
function renderFiles() {
  const star=get("favorite-file");
  star.setAttribute("aria-pressed",String(selected.favorite));
  star.setAttribute("aria-label",selected.favorite?"Убрать разговор из избранного":"Добавить разговор в избранное");
  star.title=star.getAttribute("aria-label");
  star.textContent=selected.favorite?"★":"☆";
  get("only-favorites").setAttribute("aria-pressed",String(favoritesOnly));
  get("file-list").replaceChildren(...Array.from(items.values()).filter(entry => !favoritesOnly || entry.favorite).map(entry => {
    const row = button(entry.file.name, () => openItem(entry), "file-row");
    if(Array.from(items.values()).some(other=>other!==entry && other.file.name===entry.file.name)) {
      const detail=document.createElement("small");detail.textContent=entry.id?"Файл · "+entry.id.slice(0,8):"Открыт "+entry.key+"-м";
      row.append(detail);
    }
    row.setAttribute("aria-pressed", String(entry === selected));
    return row;
  }));
  if(!get("file-list").childElementCount) get("file-list").textContent="Среди открытых файлов избранных пока нет.";
}
get("favorite-file").onclick=()=>{
  change(selected,{kind:"favorite",value:!selected.favorite});
  renderFiles();
};
get("only-favorites").onclick=()=>{favoritesOnly=!favoritesOnly;renderFiles();};
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
    const ready=store.readWork({...store.empty(),cues}).cues;
    change(item,{kind:"cues",value:ready});
    storageUI(item);
    if (selected === item) { get("cue-query").value = ""; cueLimit=120; get("notice").textContent = ""; renderCues(); renderMap(); }
  } catch (error) {
    if (selected === item) get("notice").textContent = error.message;
  }
}
function renderCues() {
  const query = get("cue-query").value.toLocaleLowerCase("ru").trim();
  get("cue-query").hidden = !selected.cues.length;
  get("cue-context").hidden = !selected.cues.length;
  get("cue-total").textContent = selected.cues.length ? "Фраз: " + selected.cues.length : "";
  get("text-help").hidden = !!selected.cues.length;
  previousCue = null;
  const matches=query ? selected.cues.filter(cue => cue.phrase.toLocaleLowerCase("ru").includes(query)) : selected.cues;
  cueButtons = matches.slice(0,cueLimit).map(cue => {
    const row = button("", () => playAt(Math.max(0, cue.start - (get("lead-in").checked ? 2 : 0))), "cue-row");
    const time = document.createElement("time");
    time.textContent = stamp(cue.start);
    const words = document.createElement("span");
    words.textContent = cue.phrase;
    row.append(time, words);
    return {cue, row};
  });
  get("cues").replaceChildren(...cueButtons.map(entry => entry.row));
  if(matches.length>cueLimit) {
    const more=button("Ещё фразы · "+(matches.length-cueLimit),()=>{
      const first=cueLimit;cueLimit+=120;renderCues();cueButtons[first]?.row.focus();
    },"sheet-link");
    get("cues").append(more);
  }
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
function renderMap() {
  if (!selected || !get("map-panel").open) return;
  const item=selected;
  ZuConversation.mount(get("conversation-map"), {
    key:selected.id || "temporary-"+selected.key, pins:selected.pins,
    onPin:(time,add)=>change(item,{kind:"pins",time,add}), title:selected.file.name.replace(/\.[^.]+$/, ""), segments:selected.cues,
    marks:[...selected.marks.map(time=>({time})),...selected.notes.map(note=>({time:note.time,name:note.text}))], play:playAt,
    empty:"Добавь субтитры SRT или WebVTT, и здесь появятся темы разговора. Уже сейчас можно поставить закладку в плеере."
  });
}
get("map-panel").addEventListener("toggle", renderMap);
function renderMarks() {
  renderMap();
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
  ctx.strokeStyle = live ? "#ff9e86" : "#929187"; ctx.lineWidth = 1.5; ctx.stroke();
  if (live) frame = requestAnimationFrame(drawSignal);
}
function playAt(time) {
  if (!selected) return;
  const item = selected;
  markPoint(time);
  if (Number.isFinite(time)) {
    if (audio.readyState >= 1 && Number.isFinite(audio.duration)) audio.currentTime = Math.max(0, Math.min(time, audio.duration));
    else pendingTime = time;
  }
  createMeter();
  audio.play().then(() => { createMeter(); drawSignal(); }).catch(error => {
    if (item === selected && error.name !== "AbortError") get("notice").textContent = "Браузер не воспроизвёл этот файл. Попробуй MP3, WAV или M4A.";
  });
}
get("choose").onclick = () => get("files").click();
get("choose").disabled=false;
get("files").onchange = event => { importFiles(event.target.files); event.target.value = ""; };
get("import-text").onclick = () => get("captions").click();
get("captions").onchange = event => { loadCaptions(event.target.files[0]); event.target.value = ""; };
get("cue-query").oninput = () => {cueLimit=120;renderCues();};
get("play").onclick = () => { if (audio.paused) playAt(); else audio.pause(); };
get("rate").onclick = () => {
  speed = speeds[(speeds.indexOf(speed) + 1) % speeds.length]; audio.playbackRate = speed;
  get("rate").textContent = String(speed).replace(".", ",") + "×";
  get("rate").setAttribute("aria-label", "Скорость " + get("rate").textContent + ". Изменить");
};
get("seek").oninput=()=>{if(Number.isFinite(audio.duration)) {const target=Number(get("seek").value);markPoint(target);audio.currentTime=target;} };
get("add-mark").onclick = () => {
  const time = Math.floor(audio.currentTime);
  if(!selected.marks.includes(time)) change(selected,{kind:"marks",time,add:true});
  renderMarks();
};
audio.addEventListener("loadedmetadata", () => {
  if (selected && Number.isFinite(audio.duration)) audio.currentTime = Math.min(pendingTime ?? selected.time, audio.duration);
  pendingTime = null;
  updatePlayer(); drawSignal();
});
for (const event of ["play","pause","ended","timeupdate","durationchange","seeked"]) audio.addEventListener(event, updatePlayer);
for (const event of ["play","pause","ended"]) audio.addEventListener(event, drawSignal);
audio.addEventListener("error", () => { get("notice").textContent = "Не удалось открыть аудио. Попробуй MP3, WAV или M4A."; updatePlayer(); });
audio.addEventListener("timeupdate",()=>capturePosition());
for(const event of ["seeked","pause","ended"]) audio.addEventListener(event,()=>capturePosition(true));
document.addEventListener("visibilitychange",()=>{drawSignal();if(document.hidden) checkpoint();});
reduceMotion.addEventListener("change", drawSignal);
window.addEventListener("resize", drawSignal);
for (const event of ["dragover","drop"]) window.addEventListener(event, e => {
  if (!e.dataTransfer.types.includes("Files")) return;
  e.preventDefault();
  if (event === "drop") importFiles(e.dataTransfer.files);
});
window.addEventListener("pagehide", event => {
  checkpoint();audio.pause(); cancelAnimationFrame(frame);
  if (!event.persisted) for (const entry of items.values()) URL.revokeObjectURL(entry.audioURL);
});
