const {test} = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const {chromium} = require("playwright-core");
require("../site/library-storage.js");

const storage=globalThis.ZuLibraryStorage;
const base=process.env.SITE_URL || "http://127.0.0.1:4173/";
const address=new URL("library.html",base).href;
const subtitles="1\n00:00:01,000 --> 00:00:03,000\nПервая проверочная фраза.\n\n2\n00:00:07,000 --> 00:00:10,000\nРешили оставить второй срок.\n";

function wav(alternate=false) {
  const frames=8000*12;
  const buffer=Buffer.alloc(44+frames,128);
  buffer.write("RIFF",0);buffer.writeUInt32LE(frames+36,4);buffer.write("WAVEfmt ",8);buffer.writeUInt32LE(16,16);
  buffer.writeUInt16LE(1,20);buffer.writeUInt16LE(1,22);buffer.writeUInt32LE(8000,24);buffer.writeUInt32LE(8000,28);
  buffer.writeUInt16LE(1,32);buffer.writeUInt16LE(8,34);buffer.write("data",36);buffer.writeUInt32LE(frames,40);
  if(alternate) buffer[buffer.length-65]=129;
  return buffer;
}
async function prepare(t,init) {
  const browser=await chromium.launch({executablePath:process.env.CHROME_BIN || undefined});
  t.after(()=>browser.close());
  const context=await browser.newContext({viewport:{width:390,height:844}});
  if(init) await context.addInitScript(init);
  const page=await context.newPage();
  const errors=[];page.on("pageerror",e=>errors.push(e.message));
  page.on("dialog",d=>d.accept());
  await page.goto(address);
  t.after(()=>assert.deepEqual(errors,[]));
  return {page,context};
}
async function open(page,alternate=false,name="Разговор.wav",mtime=11) {
  await page.waitForFunction(()=>typeof document.querySelector("#files").onchange==="function");
  await page.locator("#files").evaluate((input,{content,name,mtime})=>{
    const bytes=Uint8Array.from(atob(content),c=>c.charCodeAt(0));
    const transfer=new DataTransfer();
    transfer.items.add(new File([bytes],name,{type:"audio/wav",lastModified:mtime}));
    input.files=transfer.files;input.dispatchEvent(new Event("change"));
  },{name,mtime,content:wav(alternate).toString("base64")});
  await page.waitForFunction(()=>document.querySelector("audio").readyState>=1 && document.querySelector("#storage-mode").dataset.mode!=="checking");
}
const mode=(p,m)=>p.locator('#storage-mode[data-mode="'+m+'"]').waitFor();
async function captions(p,text=subtitles) {
  await p.locator("#captions").setInputFiles({name:"Контроль.srt",mimeType:"text/plain",buffer:Buffer.from(text)});
  await p.locator("#cue-query").waitFor();
}
async function at(p,t) {
  await p.locator("#seek").evaluate((input,value)=>{input.value=value;input.dispatchEvent(new Event("input"));},String(t));
  await p.waitForFunction(value=>Math.abs(document.querySelector("audio").currentTime-value)<.06,t);
}
async function note(p,text) {await p.locator("#note-text").fill(text);await p.locator("#add-note").click();}
async function saveJSON(p) {
  const event=p.waitForEvent("download");await p.locator("#export-work").click();
  return JSON.parse(await fs.readFile(await (await event).path(),"utf8"));
}
async function importJSON(p,object) {await p.locator("#notes-file").setInputFiles({name:"запись.zu.json",mimeType:"application/json",buffer:Buffer.from(JSON.stringify(object))});}
async function retained(p) {
  await p.waitForFunction(()=>document.querySelector("#cue-total").textContent.includes("2"));
  assert.equal(await p.locator("#marks .mark-time").count(),1);
  assert.equal(await p.locator("#favorite-file").getAttribute("aria-pressed"),"true");
  assert.equal(await p.locator("#notes-list .item-note p").textContent(),"Моя ручная заметка.");
}

test("Потоковый SHA-256 совпадает с node:crypto для пустого файла, границ блока и длинного аудио",async()=>{
  for(const size of [0,1,55,56,63,64,65,127,193,1048576,2250001]) {
    const bytes=Buffer.alloc(size);
    for(let i=0;i<size;i++) bytes[i]=(i*11+3)%251;
    const digest=crypto.createHash("sha256").update(bytes).digest("hex");
    assert.equal(await storage.hashFile(new Blob([bytes]),undefined,true),digest);
  }
});
test("WAV → SRT → поиск → закладка, ручная заметка, сохранение и возврат после перезагрузки",async t=>{
  const {page}=await prepare(t);
  await page.locator("#transcribe-help summary").click();
  assert.match(await page.locator("#transcribe-help").innerText(),/Android/);
  assert.match(await page.locator("#transcribe-help").innerText(),/Mac/);
  await page.locator("#transcribe-help summary").click();
  await open(page);await mode(page,"temporary");await captions(page);
  await page.locator("#cue-query").fill("второй");assert.equal(await page.locator(".cue-row").count(),1);
  await page.locator(".cue-row").click();await page.waitForFunction(()=>!document.querySelector("audio").paused);
  await page.locator("#play").click();await at(page,7);
  await page.locator("#add-mark").click();await page.locator("#favorite-file").click();await note(page,"Моя ручная заметка.");
  await page.locator("#map-panel summary").first().click();
  await page.locator('[data-group="decisions"] .zu-map-pin').click();
  await page.locator("#save-work").click();await mode(page,"saved");
  const initial=await saveJSON(page);
  assert.equal(initial.audio.sha256,crypto.createHash("sha256").update(wav()).digest("hex"));
  assert.deepEqual(initial.work.pins,[7]);assert.equal(initial.work.time,7);
  await page.reload();await open(page,false,"Переименовано.wav",45500);await mode(page,"saved");await retained(page);
  await page.waitForFunction(()=>Math.abs(document.querySelector("audio").currentTime-7)<.05);
  const after=await saveJSON(page);assert.deepEqual(after.work,initial.work);
  await open(page,true,"Переименовано.wav",45500);await mode(page,"temporary");
  assert.equal(await page.locator("#marks .mark-time").count(),0);assert.equal(await page.locator(".cue-row").count(),0);
  assert.equal(await page.locator("#favorite-file").getAttribute("aria-pressed"),"false");
  await importJSON(page,initial);await page.getByText(/JSON относится к другой записи/).waitFor();
  await open(page,false,"Переименовано.wav",45500);
  await mode(page,"saved");assert.equal(await page.locator(".file-row").count(),2);
  await retained(page);
  const data=await page.evaluate(()=>({width:document.documentElement.scrollWidth,pins:localStorage.getItem("zu-map:pins:1")}));
  assert.deepEqual(data,{width:390,pins:null});
  await page.locator("#save-work").click();await mode(page,"temporary");
  await page.reload();await open(page,false,"Переименовано.wav",45500);await mode(page,"temporary");
  assert.equal(await page.locator("#notes-list .item-note").count(),0);
});
test("При запрете IndexedDB переносимый JSON сохраняет правки и отличается от другой записи",async t=>{
  const {page}=await prepare(t,()=>Object.defineProperty(window,"indexedDB",{get(){throw new DOMException("blocked","SecurityError");}}));
  await open(page);await mode(page,"blocked");await captions(page);await at(page,4.5);await page.locator("#add-mark").click();await note(page,"Первая версия заметки");
  const exported=await saveJSON(page);
  await page.reload();await open(page);await mode(page,"blocked");
  await importJSON(page,exported);await page.getByText("Первая версия заметки",{exact:true}).waitFor();
  await page.locator("#notes-list button").filter({hasText:"Изменить"}).click();await note(page,"Моя новая редакция");
  await importJSON(page,exported);await page.getByText("Первая версия заметки",{exact:true}).waitFor();
  await importJSON(page,exported);
  assert.equal(await page.locator("#marks .mark-time").count(),1);
  assert.equal(await page.locator("#notes-list .item-note").count(),2);
  assert.equal(await page.locator(".cue-row").count(),2);
  const changed={...exported,version:888};await importJSON(page,changed);await page.getByText(/версия файла заметок пока/).waitFor();
  changed.version=1;changed.work={...exported.work,marks:[-2]};await importJSON(page,changed);await page.getByText(/повреждён или содержит/).waitFor();
  await open(page,true);await importJSON(page,exported);await page.getByText(/JSON относится к другой/).waitFor();
  assert.equal(await page.locator("#notes-list .item-note").count(),0);
});
test("Явный временный сеанс сохраняет JSON без записи и не открывает уже сохранённые заметки",async t=>{
  const {page}=await prepare(t);
  await open(page);await note(page,"Дома");await page.locator("#save-work").click();await mode(page,"saved");
  await page.reload();await page.locator("#temporary-only").check();await open(page);await mode(page,"temporary");
  assert.equal(await page.locator("#notes-list .item-note").count(),0);assert.equal(await page.locator("#save-work").isVisible(),false);
  await note(page,"Временная заметка");const backup=await saveJSON(page);
  assert.equal(backup.work.notes[0].text,"Временная заметка");
  await page.reload();await open(page);await mode(page,"saved");assert.equal(await page.locator("#notes-list .item-note p").textContent(),"Дома");
});
test("Длинный файл проверяется целиком вне потока интерфейса",async t=>{
  const {page}=await prepare(t);
  const bytes=256*1024*1024;
  const checked=await page.evaluate(async bytes=>{
    const chunk=new Blob([new Uint8Array(1024*1024)]);
    const source=new Blob(Array.from({length:bytes/chunk.size},()=>chunk));const start=performance.now();
    let ticks=0,progress=0;const timer=setInterval(()=>ticks++,10);
    try { const digest=await ZuLibraryStorage.identify(source,n=>{progress=Math.max(progress,n);});return {ticks,digest,progress,elapsed:Math.round(performance.now()-start)};}
    finally {clearInterval(timer);}
  },bytes);
  const zero=Buffer.alloc(1024*1024),hash=crypto.createHash("sha256");
  for(let i=0;i<256;i++) hash.update(zero);
  assert.equal(checked.digest,hash.digest("hex"));assert.ok(checked.ticks>=2);
  t.diagnostic("256 МиБ, "+checked.elapsed+" мс для SHA-256, тактов интерфейса по 10 мс: "+checked.ticks);
});
test("Две вкладки объединяют независимые ручные заметки и не воскрешают удалённую копию",async t=>{
  const {page,context}=await prepare(t);
  await open(page);await page.locator("#save-work").click();await mode(page,"saved");
  const other=await context.newPage();other.on("dialog",d=>d.accept());await other.goto(address);await open(other);await mode(other,"saved");
  await Promise.all([note(page,"Заметка в первой вкладке"),note(other,"Заметка во второй вкладке")]);
  const id=crypto.createHash("sha256").update(wav()).digest("hex");
  await page.waitForFunction(async id=>(await ZuLibraryStorage.read(id))?.work.notes.length===2,id);
  await page.locator("#save-work").click();await mode(page,"temporary");await mode(other,"temporary");
  await note(other,"После удаления");assert.equal(await other.evaluate(id=>ZuLibraryStorage.read(id),id),null);
  const a=await saveJSON(other);assert.ok(a.work.notes.find(n=>n.text==="После удаления"));
});
test("Ошибка записи после согласия оставляет ручную правку и экспорт, повторное сохранение восстанавливает запись",async t=>{
  const {page}=await prepare(t);
  await open(page);await note(page,"Удалить после сбоя");await page.locator("#save-work").click();await mode(page,"saved");
  await page.evaluate(()=>{
    const put=IDBObjectStore.prototype.put;window.allowStore=()=>{IDBObjectStore.prototype.put=put;};
    IDBObjectStore.prototype.put=function(){
      if(this.name==="records") throw new DOMException("quota","QuotaExceededError");
      return put.apply(this,arguments);
    };
  });
  await page.locator("#notes-list button").filter({hasText:"Удалить"}).click();await mode(page,"blocked");
  await note(page,"Текст после ошибки");const backup=await saveJSON(page);assert.deepEqual(backup.work.notes.map(n=>n.text),["Текст после ошибки"]);
  await page.evaluate(()=>window.allowStore());await page.locator("#save-work").click();await mode(page,"saved");
  await page.reload();await open(page);await mode(page,"saved");assert.deepEqual(await page.locator(".item-note p").allTextContents(),["Текст после ошибки"]);
});
test("Неподтверждённый старый ключ по имени, размеру и дате требует явного переноса",async t=>{
  const {page}=await prepare(t);
  const key=JSON.stringify(["Разговор.wav",wav().length,11]);
  await page.evaluate(key=>{localStorage.setItem("zu-library:favorite:"+key,"1");localStorage.setItem("zu-map:pins:"+key,"[2.1]");},key);
  await open(page);assert.equal(await page.locator("#favorite-file").getAttribute("aria-pressed"),"false");
  await page.locator("#legacy-work").click();assert.equal(await page.locator("#favorite-file").getAttribute("aria-pressed"),"true");
  const out=await saveJSON(page);assert.deepEqual(out.work.pins,[2.1]);
});
test("Последнюю фразу можно найти на узком экране без вывода тысяч строк сразу",async t=>{
  const {page}=await prepare(t);await open(page);
  const timestamp=sec=>new Date(sec*1000).toISOString().slice(11,23).replace(".",",");
  const lines=Array.from({length:6000},(_,i)=>(i+1)+"\n"+timestamp(i)+" --> "+timestamp(i+.85)+"\n"+(i===5999?"Финишная цитата":"Учебный отрывок "+i)+"\n").join("\n");
  await captions(page,lines);await page.getByText("Фраз: 6000",{exact:true}).waitFor();assert.equal(await page.locator(".cue-row").count(),120);
  await page.locator("#cue-query").fill("Финишная");assert.equal(await page.locator(".cue-row").count(),1);
  await page.locator(".cue-row").click();assert.equal(await page.locator(".cue-row time").textContent(),"99:59");
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);
});
test("Локальный оригинал сохраняет контрольную сумму, на сервер уходят только GET статических файлов",async t=>{
  const {page}=await prepare(t), dir=await fs.mkdtemp(require("node:path").join(require("node:os").tmpdir(),"zu-library-"));
  t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const source=require("node:path").join(dir,"Оригинал.wav"), input=wav(), sum=b=>crypto.createHash("sha256").update(b).digest("hex");
  await fs.writeFile(source,input);const initial=sum(await fs.readFile(source)), requests=[];
  page.on("request",r=>{if(/^https?:/.test(r.url())) requests.push([r.method(),new URL(r.url())]);});
  await page.locator("#files").setInputFiles(source);await mode(page,"temporary");await captions(page);
  await note(page,"Проверка сохранности");await page.locator("#save-work").click();await mode(page,"saved");
  await page.reload();await page.locator("#files").setInputFiles(source);await mode(page,"saved");
  assert.equal((await saveJSON(page)).audio.sha256,initial);
  await page.locator("#save-work").click();await mode(page,"temporary");
  const after=sum(await fs.readFile(source));assert.equal(after,initial);
  for(const [method,url] of requests) {assert.equal(method,"GET");assert.equal(url.origin,new URL(base).origin);assert.match(url.pathname,/\.(html|js|css|woff2|svg)$/);assert.equal(url.search,"");}
  t.diagnostic(initial+" · SHA-256 оригинала до и после");
});
test("Уже открытая библиотека работает после отключения сети и на ширине 320 пикселей",async t=>{
  const {page,context}=await prepare(t);
  await page.setViewportSize({width:320,height:680});
  await context.setOffline(true);
  await open(page);await mode(page,"temporary");
  await captions(page);await at(page,3);await page.locator("#add-mark").click();await note(page,"Без сети");
  const out=await saveJSON(page);
  assert.equal(out.work.notes[0].text,"Без сети");assert.equal(out.work.cues.length,2);assert.deepEqual(out.work.marks,[3]);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),320);
});
