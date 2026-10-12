let studyStatus=null, liveState=null;
const selectedRecords=new Set();
const archive=document.querySelector('main');
const mergeNotice=el('p','','merge-notice');mergeNotice.hidden=true;mergeNotice.setAttribute('role','status');archive.append(mergeNotice);
let draggedRecording='',mergingRecords=false;
async function mergeByDrop(source,target){
 if(mergingRecords||source===target||!cards.has(source)||!cards.has(target))return;
 mergingRecords=true;mergeNotice.hidden=false;mergeNotice.textContent='Объединяю отрывки по времени…';
 try{
  const value=await post('/merge',{files:[target,source],chronological:true,folder:cards.get(target).lesson?.folder});
  await update();window.revealCalendarFile?.(value.file);
  const card=cards.get(value.file);if(card){card.details.open=true;card.li.scrollIntoView({block:'center'});await update()}
  mergeNotice.textContent='Готово: одна запись с главами. Исходники сохранены.';
 }catch(error){mergeNotice.textContent=error.message}finally{mergingRecords=false}
}
function renderChapters(card){
 const parts=card.lesson?.merged_parts||[];const stamp=JSON.stringify(parts);if(card.chapterStamp===stamp)return;card.chapterStamp=stamp;card.audioTools.querySelectorAll('.source-audio-links').forEach(v=>v.remove());
 card.chapters.replaceChildren();card.chapters.hidden=!parts.length;
 if(!parts.length)return;
 for(const part of parts){const row=el('details',undefined,'temporal-section');row.append(el('summary',timeLabel(part.start)+' — '+(part.topic||'Отрывок занятия')));card.chapters.append(row);
  row.ontoggle=async()=>{if(!row.open||row.dataset.loaded)return;row.dataset.loaded='yes';const body=el('div',undefined,'temporal-body');row.append(body);if(part.summary)body.append(el('p',part.summary));body.append(jumpButton(part.start,card.audio));
   const localAudio={closest:selector=>card.audio.closest(selector),play:()=>card.audio.play(),get currentTime(){return card.audio.currentTime-part.start},set currentTime(value){card.audio.currentTime=part.start+value}};
   try{const response=await fetch('/analysis/'+encodeURIComponent(part.file));if(!response.ok){body.append(el('p','Полная расшифровка пока не готова.','muted'));return}const result=await response.json();for(const segment of result.segments||[]){const text=el('p',undefined,'segment');text.append(el('small',timeLabel(part.start+segment.start)+' · '),el('span',segment.text));body.append(text)}formulaRows(body,result,{audio:localAudio});const moments=el('section');body.append(moments);renderLearningMoments(moments,{audio:localAudio},result,part.file).catch(studyError);
    const notesResponse=await fetch('/notes?file='+encodeURIComponent(card.file));if(notesResponse.ok){const notes=await notesResponse.json();for(const photo of (notes.photos||[]).filter(p=>p.start>=part.start&&p.start<part.start+part.duration)){const figure=el('figure',undefined,'section-photo'),image=el('img');image.src='/photos/'+photo.id;image.alt='Фото к отрывку';image.loading='lazy';figure.append(image,el('figcaption',timeLabel(photo.start)));body.append(figure)}}
   }catch(e){body.append(el('p','Не удалось загрузить материалы.','muted'));row.dataset.loaded='';}
  };
 }
 const originals=el('details',undefined,'source-audio-links');originals.append(el('summary','Исходные отрывки сохранены'));
 for(const part of parts){const link=el('a',(part.file.slice(19,24).replace('-',':'))+' · '+(part.topic||'Отрывок'));link.href='/recordings/'+encodeURIComponent(part.file);link.download=part.file;originals.append(link)}card.audioTools.append(originals);
}
const studyPanel=el('section',undefined,'card');
studyPanel.append(el('h2','Поиск по содержанию'));
const searchInput=el('input');searchInput.placeholder='Опиши, что объяснял преподаватель';searchInput.maxLength=1000;
const searchButton=el('button','Найти по смыслу');const searchOutput=el('div');
searchButton.onclick=async()=>{searchButton.disabled=true;searchOutput.textContent='Ищу на этом Mac…';try{
 const response=await fetch('/search?q='+encodeURIComponent(searchInput.value));const data=await response.json();if(!response.ok)throw Error(data.error);
 searchOutput.replaceChildren(el('p',data.message||'','muted'));
 for(const item of data.results||[]){const card=cards.get(item.file);if(!card)continue;const row=el('div');const go=el('button',timeLabel(item.start)+' · '+(card.lesson?.topic||item.file),'secondary');go.onclick=()=>{window.revealCalendarFile?.(item.file);card.details.open=true;card.li.closest('ul').parentElement.open=true;card.li.scrollIntoView({block:'center'});card.audio.currentTime=item.start;card.audio.play().catch(()=>{})};row.append(go,el('p',item.text));searchOutput.append(row)}
 if(!data.results?.length)searchOutput.append(el('p','Подходящих фрагментов не найдено.'));
}catch(e){searchOutput.textContent=e.message}finally{searchButton.disabled=false}};
searchInput.onkeydown=e=>{if(e.key==='Enter')searchButton.click()};studyPanel.append(searchInput,searchButton,searchOutput);
const mergeButton=el('button','Объединить выбранные отрывки');mergeButton.disabled=true;
const mergeStatus=el('p','','muted');
mergeButton.onclick=async()=>{mergeButton.disabled=true;try{
 const files=[...selectedRecords];const value=await post('/merge',{files});selectedRecords.clear();await update();mergeStatus.textContent='Создана запись '+value.file+'. Исходные отрывки сохранены.'+(value.warning?' '+value.warning:'');
 for(const card of cards.values())if(card.choice)card.choice.checked=false;
}catch(e){mergeStatus.textContent=e.message}finally{mergeButton.disabled=selectedRecords.size<2}};
studyPanel.append(el('h3','Собрать занятие из отрывков'),el('p','Отметь записи галочками в порядке соединения. Получится новый файл с перенесёнными метками и фото.','muted'),mergeButton,mergeStatus);
archive.insertBefore(studyPanel,document.querySelector('#files').previousElementSibling);
const livePanel=el('section',undefined,'card');const liveToggle=el('input');liveToggle.type='checkbox';liveToggle.style='display:inline;width:auto;margin:0 8px';
const liveLabel=el('label','Контроль ESP · обновление каждую секунду');liveLabel.prepend(liveToggle);const liveMessage=el('p','','muted');const liveText=el('div');const liveVoice=el('div');const recallBox=el('section',undefined,'lecture-recall');recallBox.hidden=true;let recallStamp='';const activeNotes=el('div');
const liveReview=el('p','','muted');liveReview.hidden=true;
const liveFormulas=el('section',undefined,'live-formulas');liveFormulas.hidden=true;let liveFormulaStamp='';
function renderLiveFormulas(items){
 const stamp=JSON.stringify(items||[]);if(stamp===liveFormulaStamp)return;liveFormulaStamp=stamp;liveFormulas.replaceChildren();liveFormulas.hidden=!items?.length;if(!items?.length)return;
 liveFormulas.append(el('h3','Формулы по ходу решения'));
 for(const item of items){const box=el('article',undefined,'formula-row');box.append(el('small',timeLabel(item.start),'muted'));const expression=el('div');expression.style='overflow-x:auto';try{if(!window.katex)throw Error();katex.render(item.latex,expression,{displayMode:true,throwOnError:false,trust:false,strict:'ignore'})}catch{expression.textContent=item.latex}box.append(expression);if(item.explanation)box.append(el('p',item.explanation));const evidence=el('details');evidence.append(el('summary','Слова из записи'),el('blockquote',item.quote));box.append(evidence);liveFormulas.append(box)}
}
// Fixed viewport; a five-minute RAM history can be scrolled without interrupting follow mode.
liveText.id='live-text';liveText.className='live-stream';liveText.setAttribute('role','log');liveText.setAttribute('aria-label','Расшифровка за последние пять минут');liveText.setAttribute('aria-live','off');
const liveTrack=el('div',undefined,'live-stream-track');liveText.append(liveTrack);
let liveStreamFile='',liveStreamRows=new Map();
function appendLivePreview(data){
 if(data.file&&data.file!==liveStreamFile){liveStreamFile=data.file;liveStreamRows.clear();liveTrack.replaceChildren()}
 const follow=liveText.scrollHeight-liveText.clientHeight-liveText.scrollTop<40;
 const cutoff=(data.seconds||0)-300,oldHeight=liveTrack.offsetHeight;
 for(const [key,row] of liveStreamRows){if(Number(row.dataset.end)<=cutoff){row.remove();liveStreamRows.delete(key)}}
 const removedHeight=oldHeight-liveTrack.offsetHeight;if(!follow&&removedHeight>0)liveText.scrollTop=Math.max(0,liveText.scrollTop-removedHeight);
 for(const segment of data.history||data.segments||[]){
  if(!segment.text||segment.end<=cutoff)continue;
  const key=data.history?'id:'+segment.id:segment.start+'|'+segment.text;
  let row=liveStreamRows.get(key);const added=!row;
  if(!row){row=el('p',undefined,'live-stream-row');liveStreamRows.set(key,row);liveTrack.append(row)}
  const teacher=(data.passive_teacher?.teacher_ranges||[]).some(r=>Math.min(segment.end,r.end)-Math.max(segment.start,r.start)>=Math.max(1,(segment.end-segment.start)*.5));
  const text=timeLabel(segment.start)+' · '+segment.text+(teacher?' · вероятно преподаватель':'');
  if(row.textContent!==text)row.textContent=text;
  row.dataset.start=segment.start;row.dataset.end=segment.end;row.classList.toggle('teacher-voice',teacher);row.title='';
  if(added&&follow&&liveText.offsetParent&&!matchMedia('(prefers-reduced-motion: reduce)').matches)row.animate([{opacity:.35,transform:'translateY(6px)'},{opacity:1,transform:'translateY(0)'}],{duration:400,easing:'ease-out'});
 }
 for(const marker of data.markers||[]){
  if(marker.start<=cutoff)continue;const key='marker:'+marker.id;let row=liveStreamRows.get(key);
  if(!row){row=el('p',undefined,'live-stream-row live-marker mythic-card');liveStreamRows.set(key,row);liveTrack.append(row)}
  row.dataset.start=marker.start;row.dataset.end=marker.start;row.textContent=timeLabel(marker.start)+' · ◆ '+(marker.title||'Метка');
 }
 const ordered=[...liveStreamRows.values()].sort((a,b)=>Number(a.dataset.start)-Number(b.dataset.start));
 for(let i=0;i<ordered.length;i++)if(liveTrack.children[i]!==ordered[i])liveTrack.insertBefore(ordered[i],liveTrack.children[i]||null);
 if(follow)liveText.scrollTo({top:liveText.scrollHeight,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
}
livePanel.append(liveLabel,el('p','Текст появляется целыми фразами; последние 5 минут можно прокручивать. Самопроверка учитывает 4 соседних фрагмента и уточняет недавние строки. Формулы собираются целиком из соседних фраз. Полная аудиозапись сохраняется отдельно.','muted'),liveMessage,liveReview,liveVoice,recallBox,liveText,liveFormulas,activeNotes);archive.insertBefore(livePanel,document.querySelector('#timer').closest('section').nextSibling);
liveToggle.onchange=async()=>{try{await post('/live-settings',{live:liveToggle.checked})}catch(e){liveMessage.textContent=e.message}};
function renderRecall(recall,target=recallBox){
 const stamp=JSON.stringify(recall||{});if(stamp===target.dataset.stamp)return;target.dataset.stamp=stamp;target.replaceChildren();target.hidden=!recall?.status;if(target.hidden)return;
 target.append(el('h3','Это было на прошлой лекции'));
 if(recall.status!=='ready'){target.append(el('p',recall.status==='searching'?'Ищу тему в предыдущих записях…':recall.status==='not_found'?'Подходящий отрывок пока не найден в доступных расшифровках.':'Поиск временно недоступен.','muted'));return}
 target.append(el('p','Похожие отрывки из прошлых занятий — проверь соответствие вопросу.','muted'));
 for(const item of recall.results||[]){const row=el('article');row.append(el('small',(item.subject||'Прошлая лекция')+' · '+item.file.slice(8,18),'muted'),el('p',item.text));const go=el('button','Открыть лекцию · '+timeLabel(item.start),'secondary');go.onclick=async()=>{window.showLectureView?.('library');window.revealCalendarFile?.(item.file);const card=cards.get(item.file);if(card){card.details.open=true;card.li.scrollIntoView({block:'center'});card.audio.currentTime=item.start;card.audioTools.open=true}else{const audio=new Audio('/recordings/'+encodeURIComponent(item.file));audio.currentTime=item.start;audio.play().catch(studyError)}};const source=el('a','Исходная запись');source.href='/recordings/'+encodeURIComponent(item.file)+'#t='+item.start;row.append(go,source);target.append(row)}
}

function studyError(error){$('#error').textContent=error.message}
async function renderNotes(box,name,audio,active=false){
 const response=await fetch('/notes?file='+encodeURIComponent(name));if(!response.ok)return;const data=await response.json();
 const stamp=JSON.stringify(data);if(box.dataset.stamp===stamp)return;
 if(box.contains(document.activeElement))return;
 box.dataset.stamp=stamp;box.replaceChildren();
 for(const item of data.markers||[]){const row=el('div',undefined,'row');const input=el('input');input.value=item.title;input.placeholder='Назвать метку позже';input.maxLength=500;input.style='width:55%;margin:4px';const save=el('button','Сохранить название','secondary ai-button');save.onclick=async()=>{try{await post('/marker',{file:name,id:item.id,start:item.start,title:input.value});box.dataset.stamp='';await renderNotes(box,name,audio,active)}catch(e){studyError(e)}};row.append(audio?jumpButton(item.start,audio):el('span',timeLabel(item.start)),input,save);box.append(row)}
 for(const photo of data.photos||[]){const row=el('figure');const image=el('img');image.src='/photos/'+photo.id;image.alt='Фото к занятию на '+timeLabel(photo.start);image.loading='lazy';image.style='max-width:100%;max-height:400px;border-radius:12px';row.append(image,el('figcaption',timeLabel(photo.start)));const time=el('input');time.type='number';time.min=0;time.step='.1';time.value=photo.start;time.setAttribute('aria-label','Время фотографии, секунды');const save=el('button','Изменить время фото','secondary ai-button');save.onclick=async()=>{try{await post('/photo-time',{file:name,id:photo.id,start:Number(time.value)});box.dataset.stamp='';await renderNotes(box,name,audio,active)}catch(e){studyError(e)}};row.append(time,save);if(audio)row.append(jumpButton(photo.start,audio));box.append(row)}
 if(!active&&!data.markers?.length&&!data.photos?.length)box.append(el('p','Метки и фотографии пока не добавлены.','muted'));
}
function noteControls(parent,name,audio,active=false){
 if(active){
  const controls=el('div',undefined,'quick-note-actions'),box=el('div');
  const marker=el('button','Поставить метку','secondary'),photoButton=el('button','Добавить фото','secondary');
  const picker=el('input');picker.type='file';picker.accept='image/jpeg,image/png,image/webp';picker.hidden=true;
  const now=()=>Number(studyStatus?.seconds??liveState?.seconds??0);let photoTime=0;
  marker.onclick=async()=>{marker.disabled=true;try{await post('/marker',{file:name,start:now(),title:''});pollStudy.lastPoll=0;pollStudy();box.dataset.stamp='';await renderNotes(box,name,audio,true)}catch(e){studyError(e)}finally{marker.disabled=false}};
  photoButton.onclick=()=>{photoTime=now();picker.click()};
  picker.onchange=async()=>{const photo=picker.files[0];if(!photo)return;photoButton.disabled=true;try{
   const response=await fetch('/photo?file='+encodeURIComponent(name)+'&start='+photoTime,{method:'POST',headers:{'Content-Type':photo.type},body:photo});const value=await response.json();if(!response.ok)throw Error(value.error);box.dataset.stamp='';await renderNotes(box,name,audio,true);
  }catch(e){studyError(e)}finally{picker.value='';photoButton.disabled=false}};
  controls.append(marker,photoButton,picker);parent.append(controls,box);renderNotes(box,name,audio,true).catch(studyError);return box;
 }

 const controls=el('div');const time=el('input');time.type='number';time.min='0';time.step='.1';time.value=active?String(studyStatus?.seconds||liveState?.seconds||0):'0';time.oninput=()=>time.dataset.edited='yes';time.setAttribute('aria-label','Время метки или фото, секунды');time.style='width:130px;display:inline-block;margin:4px';
 const current=el('button','Текущее время','secondary ai-button');current.onclick=()=>{time.value=(active?(studyStatus?.seconds||0):audio.currentTime).toFixed(1)};
 const marker=el('button','Поставить метку','secondary ai-button');const photos=el('input');photos.type='file';photos.accept='image/jpeg,image/png,image/webp';photos.style='margin:8px 0';const label=el('label','Добавить фото · время указано в секундах');label.append(photos);
 const box=el('div');marker.onclick=async()=>{try{await post('/marker',{file:name,start:active?(studyStatus?.seconds||0):Number(time.value),title:''});box.dataset.stamp='';await renderNotes(box,name,audio,active)}catch(e){studyError(e)}};
 photos.onchange=async()=>{const photo=photos.files[0];if(!photo)return;const start=active&&!time.dataset.edited?(studyStatus?.seconds||liveState?.seconds||0):Number(time.value);try{
  const response=await fetch('/photo?file='+encodeURIComponent(name)+'&start='+start,{method:'POST',headers:{'Content-Type':photo.type},body:photo});const value=await response.json();if(!response.ok)throw Error(value.error);box.dataset.stamp='';await renderNotes(box,name,audio,active);
 }catch(e){studyError(e)}finally{photos.value=''}};
 controls.append(el('h4','Метки и фотографии'),time,current,marker,label,box);parent.append(controls);if(active)renderNotes(box,name,audio,active).catch(studyError);else parent.ontoggle=()=>{if(parent.open)renderNotes(box,name,audio,active).catch(studyError)};return box;
}
function renderSummaryPreview(card){
 const meta=card.lesson||{},parts=meta.merged_parts||[];
 const text=meta.overview||(meta.has_draft?'Идёт запись · предварительный текст':'')||meta.key_points?.[0]||parts.find(p=>p.summary)?.summary||'Краткий конспект ещё не готов. Открой занятие, чтобы составить его.';
 const preview=text.length>250?text.slice(0,247)+'…':text;
 if(card.preview.textContent!==preview)card.preview.textContent=preview;
}
function initStudyCard(card,name){
 card.file=name;
 const details=el('details');const header=el('summary');const choice=el('input');choice.type='checkbox';choice.style='display:inline;width:auto;margin:0 8px 0 0';choice.setAttribute('aria-label','Выбрать отрывок '+name);choice.onclick=e=>e.stopPropagation();choice.onchange=()=>{if(choice.checked)selectedRecords.add(name);else selectedRecords.delete(name);mergeButton.disabled=selectedRecords.size<2;mergeStatus.textContent=[...selectedRecords].map((v,i)=>(i+1)+'. '+(cards.get(v)?.lesson?.topic||v)).join(' → ')};
 choice.className='record-choice';const topic=el('span','Тема пока не определена');topic.className='record-topic';const clock=el('small',name.slice(19,24).replace('-',':'),'record-time');const grip=el('span','⋮⋮','drag-grip');grip.setAttribute('aria-hidden','true');const preview=el('span',undefined,'summary-preview');const copy=el('span',undefined,'record-copy');copy.append(topic,preview);header.append(grip,choice,copy,clock);header.draggable=true;header.title='Перетащи эту запись на другую, чтобы объединить';
 header.ondragstart=e=>{draggedRecording=name;document.body.classList.add('drag-in-progress');e.dataTransfer.setData('application/x-lecture-recording',name);e.dataTransfer.effectAllowed='copy';card.li.classList.add('is-dragging')};
 header.ondragend=()=>{draggedRecording='';document.body.classList.remove('drag-in-progress');document.querySelectorAll('.drop-target,.is-dragging').forEach(v=>v.classList.remove('drop-target','is-dragging'))};
 header.ondragover=e=>{if(draggedRecording&&draggedRecording!==name&&!mergingRecords){e.preventDefault();e.dataTransfer.dropEffect='copy';card.li.classList.add('drop-target')}};
 header.ondragleave=()=>card.li.classList.remove('drop-target');
 header.ondrop=e=>{e.preventDefault();e.stopPropagation();card.li.classList.remove('drop-target');const source=e.dataTransfer.getData('application/x-lecture-recording');mergeByDrop(source,name)};
 const body=el('div',undefined,'record-body');body.append(...card.li.childNodes);details.append(header,body);card.li.append(details);const chapters=el('section',undefined,'chapter-list');chapters.hidden=true;body.insertBefore(chapters,card.result);const audioTools=el('details',undefined,'audio-tools');audioTools.append(el('summary','Аудиозапись и отрывки'),card.audio,body.querySelector('a'));body.append(audioTools);body.insertBefore(card.result,body.firstChild);body.insertBefore(chapters,card.result.nextSibling);Object.assign(card,{details,topic,choice,clock,chapters,preview,audioTools});initBoardPhotoCard(card,name);audioTools.ontoggle=()=>{if(audioTools.open&&card.audio.preload==='none'){card.audio.preload='metadata';card.audio.load()}};
 details.ontoggle=()=>{if(details.open)update()};

}
async function renderLearningMoments(box,card,result,name,range=null,paper=false){
 const generation=box.dataset.materialGeneration;const response=await fetch('/learning-moments?file='+encodeURIComponent(name));if(!response.ok)return;const data=await response.json();if(!box.isConnected||box.dataset.materialGeneration!==generation)return;
 const moments=data.moments||[];if(!moments.length)return;
 if(!paper)box.append(el('h4','Даты, события и понятия'));
 for(const [index,item] of moments.entries()){
  if(range&&(item.start<range.start||item.start>=range.end))continue;
  const row=el('article',undefined,'learning-moment');const copy=el('div');if(item.date)copy.append(el('strong',item.date,'event-date'));copy.append(el('h5',item.title),el('p',item.description));const evidence=el('details',undefined,'point-evidence');evidence.append(el('summary','Слова преподавателя'),el('blockquote',item.quote));if(!paper)copy.append(evidence,jumpButton(item.start,card.audio));row.append(copy);const anchor=paper?[...box.querySelectorAll('.segment[data-start]')].find(p=>item.start>=Number(p.dataset.start)&&item.start<Number(p.dataset.end)):null;if(anchor)anchor.after(row);else box.append(row);
  if(item.image_query){const figure=el('figure',undefined,'topic-illustration');figure.append(el('figcaption','Подбираю иллюстрацию…'));row.append(figure);const load=async()=>{try{const r=await fetch('/illustration?file='+encodeURIComponent(name)+'&moment='+index);const image=await r.json();if(!figure.isConnected)return;if(image.status!=='ready'){figure.remove();return}const img=el('img');img.src=image.image_url;img.alt=image.title;img.loading='lazy';img.referrerPolicy='no-referrer';img.onerror=()=>figure.remove();const caption=el('figcaption');const source=el('a','Иллюстрация: '+image.title);source.href=image.source_url;source.target='_blank';source.rel='noopener noreferrer';caption.append(source,el('small',(image.author?image.author+' · ':'')+image.license));figure.replaceChildren(img,caption)}catch{figure.remove()}};
   const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){observer.disconnect();load()}},{rootMargin:'150px'});observer.observe(figure);
  }
 }
}
function formulaRows(box,result,card){
 if(!result.formulas?.length)return;
 box.append(el('h4','Формулы'));
 for(const item of result.formulas){const formula=el('div');try{if(!window.katex)throw Error('Рендер формул ещё загружается');katex.render(item.latex.replace(/\u000crac/g,'\\frac'),formula,{displayMode:true,throwOnError:false,trust:false,strict:'ignore'})}catch{formula.textContent=item.latex}box.append(formula,el('p',item.explanation||''),el('blockquote',item.quote),jumpButton(item.start,card.audio))}
}
async function voiceControls(){return}
let activeNoteName='';
async function pollStudy(){
 if(document.hidden||pollStudy.busy)return;if(!studyStatus?.recording&&Date.now()-(pollStudy.lastPoll||0)<5000)return;pollStudy.lastPoll=Date.now();pollStudy.busy=true;try{
  const response=await fetch('/live');const data=await response.json();if(!response.ok)throw Error(data.error);liveState=data;liveToggle.checked=data.enabled;listen.disabled=!data.recording&&!monitorAudio;const previewCaption=document.querySelector('#live-preview-caption');if(previewCaption)previewCaption.textContent=data.recording?'Последние 5 минут текущей записи · текст предварительный.':'Последние фрагменты предыдущей записи. Новая расшифровка появится после начала записи.';liveMessage.textContent=data.message||'';
  const review=data.self_review;liveReview.hidden=!review||!data.enabled;liveReview.textContent=review?(review.state==='checking'?'Самопроверка · уточняю по контексту':review.state==='unavailable'?'Самопроверка временно недоступна · исходный текст сохранён':'Самопроверка · память на 4 фрагмента')+(review.changed_rows?' · уточнено фрагментов: '+review.changed_rows:''):'';
  renderLiveFormulas(data.formulas);
  renderRecall(data.recall);const library=document.querySelector('#view-library');if(library){let mirror=document.querySelector('#library-recall');if(!mirror){mirror=el('section',undefined,'lecture-recall');mirror.id='library-recall';mirror.hidden=true;library.prepend(mirror)}renderRecall(data.recall,mirror)}liveVoice.textContent=data.passive_teacher?.message||'';liveVoice.className='muted';appendLivePreview(data);
  if(data.recording&&data.file!==activeNoteName){activeNoteName=data.file;activeNotes.replaceChildren(el('h3','Метки текущей записи'));noteControls(activeNotes,data.file,null,true)}
  if(!data.recording&&activeNoteName){activeNoteName='';activeNotes.replaceChildren()}
  if(Date.now()-(pollStudy.lastVoices||0)<8000)return;pollStudy.lastVoices=Date.now();const names=[...cards].filter(([name,card])=>card.loaded&&card.details.open&&card.li.offsetParent).map(([name])=>name);for(const name of names)await voiceControls(cards.get(name),name);
 }catch(e){liveMessage.textContent=e.message}finally{pollStudy.busy=false}
}
setInterval(pollStudy,1000);pollStudy();
const listen=el('button','Слушать звук ESP','secondary');listen.disabled=true;listen.title='Прослушивание доступно во время записи';livePanel.insertBefore(listen,liveMessage);
let monitorContext=null,monitorAudio=false,monitorFrame=0,monitorFile='',monitorNext=0;
listen.onclick=async()=>{try{monitorAudio=!monitorAudio;if(monitorAudio){monitorContext=monitorContext||new (window.AudioContext||window.webkitAudioContext)();await monitorContext.resume();monitorFrame=0;monitorNext=0;listen.textContent='Выключить прослушивание';await hearESP()}else{await monitorContext?.suspend();listen.textContent='Слушать звук ESP'}}catch(e){monitorAudio=false;listen.textContent='Слушать звук ESP';studyError(e)}};
async function hearESP(){if(!monitorAudio||hearESP.busy)return;hearESP.busy=true;try{
 const response=await fetch('/monitor-frame?after='+monitorFrame);const value=await response.json();if(!response.ok)throw Error(value.error);if(!value.recording||!value.pcm)return;
 if(value.file!==monitorFile){monitorFile=value.file;monitorNext=0}monitorFrame=value.to_frame;
 const bytes=Uint8Array.from(atob(value.pcm),c=>c.charCodeAt(0));const view=new DataView(bytes.buffer);const buffer=monitorContext.createBuffer(1,bytes.length/2,value.rate);const signal=buffer.getChannelData(0);for(let i=0;i<signal.length;i++)signal[i]=view.getInt16(i*2,true)/32768;
 const source=monitorContext.createBufferSource();source.buffer=buffer;source.connect(monitorContext.destination);const next=Math.max(monitorNext,monitorContext.currentTime+.04);source.start(next);monitorNext=next+buffer.duration;
}catch(e){liveMessage.textContent=e.message}finally{hearESP.busy=false}}
setInterval(hearESP,1000);

function temporalSections(result,parts=[],markers=[]){
 const segments=[...(result.segments||[])].sort((a,b)=>a.start-b.start);
 let sections=(result.sections?.length?result.sections:parts).map(p=>({start:Number(p.start)||0,title:p.title||p.topic||p.summary||'Фрагмент занятия'})).sort((a,b)=>a.start-b.start);
 if(!sections.length){for(const segment of segments){if(!sections.length||segment.start-sections.at(-1).start>=120)sections.push({start:segment.start,title:segment.text.split(/[.!?]/)[0].slice(0,100)})}}
 for(const marker of markers)sections.push({start:Number(marker.start),title:'◆ '+(marker.title||'Метка'),marker:true});
 sections.sort((a,b)=>a.start-b.start||Number(b.marker||false)-Number(a.marker||false));
 sections=sections.filter((s,i)=>!i||s.start>sections[i-1].start);
 if(sections.length&&!result.draft&&!sections[0].marker)sections[0].start=0;
 return sections.map((s,i)=>({...s,end:sections[i+1]?.start??Infinity}));
}
const proofreadingRequests=new Map();
async function applyProofreading(timeline,name){
 const generation=timeline.dataset.materialGeneration;
 let pending=proofreadingRequests.get(name);if(!pending){pending=fetch('/proofread?file='+encodeURIComponent(name)).then(r=>r.ok?r.json():{corrections:[]}).finally(()=>proofreadingRequests.delete(name));proofreadingRequests.set(name,pending)}const data=await pending;if(!timeline.isConnected||generation!==timeline.dataset.materialGeneration)return;
 for(const correction of data.corrections||[]){
  const row=[...timeline.querySelectorAll('.segment[data-segment]')].find(r=>Number(r.dataset.segment)===correction.segment_id);if(!row)continue;
  const copy=el('span',correction.text);const evidence=el('details',undefined,'correction-evidence');evidence.append(el('summary','Уточнено по источнику'),el('p','Распознано: '+correction.original));for(const reference of correction.sources||[correction.source]){const source=el('a',reference.title);source.href=reference.url;source.target='_blank';source.rel='noopener noreferrer';evidence.append(source)}row.replaceChildren(...(row.dataset.role?[el('strong',row.dataset.role+': ','speaker-label')]:[]),copy,evidence);
 }
}

function renderTeacherRemarks(box,card,result){
 if(!result.teacher_remarks?.length)return;
 const panel=el('section',undefined,'teacher-remarks');panel.append(el('h4','Замечания преподавателя'),el('p','Предварительный отбор по формулировкам: требования к работе и организационные реплики.','muted'));box.append(panel);
 for(const [category,title] of [['important','Важное: требования и рекомендации'],['other','Организационные реплики']]){
  const rows=result.teacher_remarks.filter(r=>r.category===category);if(!rows.length)continue;
  const list=el('details',undefined,'remark-list');list.open=category==='important';list.append(el('summary',title+' · '+rows.length));panel.append(list);
  for(const item of rows){const row=el('div',undefined,'remark-list-row');row.append(el('p',item.quote));const go=el('button','Показать в тексте','secondary');go.onclick=()=>{const target=[...box.querySelectorAll('.full-lecture .segment[data-segment]')].find(p=>Number(p.dataset.segment)==item.segment_id);target?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});if(target&&!matchMedia('(prefers-reduced-motion: reduce)').matches)target.animate([{opacity:.4},{opacity:1}],{duration:600})};row.append(go);list.append(row)}
 }
}

function speakerLabel(result,segment){const role=result.speaker_roles?.[segment.id]?.role;return role==='teacher'?'Преподаватель':role==='student'?'Одногруппник':'Говорящий не определён'}
const telegramStates=new Map();
function renderTelegramExport(box,result,lesson,name){
 let state=telegramStates.get(name);if(!state){state={open:false,index:0,mode:'summary',prepared:null,message:''};telegramStates.set(name,state)}
 const panel=el('details',undefined,'telegram-export');panel.open=state.open;panel.append(el('summary','Копировать в Telegram'));panel.ontoggle=()=>state.open=panel.open;
 const actions=el('div',undefined,'row'),summary=el('button','Конспект для Telegram'),full=el('button','Вся лекция','secondary');actions.append(summary,full);panel.append(actions);
 const info=el('p','','muted'),controls=el('div',undefined,'row'),choice=el('select'),copy=el('button','Скопировать'),next=el('button','Следующая часть','secondary'),preview=el('textarea'),status=el('p',state.message,'muted'),save=el('button','Сохранить всю лекцию .txt','secondary');preview.readOnly=true;preview.rows=9;preview.setAttribute('aria-label','Текст для Telegram');preview.style='width:100%;white-space:pre-wrap;resize:vertical';controls.append(choice,copy,next);panel.append(info,controls,preview,status,save);box.append(panel);
 const show=()=>{const data=state.prepared;if(!data){info.textContent='Выбери конспект или полный текст. Длинная лекция делится на сообщения без обрезки.';controls.hidden=true;preview.hidden=true;save.hidden=true;return}controls.hidden=false;preview.hidden=false;save.hidden=false;state.index=Math.min(state.index,data.parts.length-1);choice.replaceChildren(...data.parts.map((text,i)=>{const option=el('option','Часть '+(i+1)+' из '+data.parts.length);option.value=String(i);return option}));choice.value=String(state.index);const text=data.parts[state.index]||'';preview.value=text;info.textContent=(state.mode==='full'?'Полная лекция':'Конспект')+' · сообщений: '+data.parts.length+' · '+text.length+' символов в этой части';copy.textContent=data.parts.length===1?'Скопировать':'Скопировать часть '+(state.index+1);copy.disabled=!text;next.hidden=data.parts.length<2;next.disabled=state.index>=data.parts.length-1;status.textContent=state.message};
 const choose=async mode=>{state.mode=mode;state.prepared=LectureTelegram.prepare(result,lesson,name,mode==='full');state.index=0;state.message='';state.open=true;panel.open=true;show();if(state.prepared.parts.length===1)await copyText()};
 const copyText=async()=>{const text=state.prepared?.parts[state.index];if(!text)return;let done=false;try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(text);done=true}}catch{}if(!done){preview.focus();preview.select();try{done=document.execCommand('copy')}catch{}}state.message=done?'Скопировано '+(state.index+1)+'/'+state.prepared.parts.length+' · вставь в Telegram'+(state.index+1<state.prepared.parts.length?', затем выбери следующую часть.':'.'):'Текст выделен: нажми ⌘C, затем вставь в Telegram.';status.textContent=state.message};
 summary.onclick=()=>choose('summary');full.onclick=()=>choose('full');copy.onclick=copyText;choice.onchange=()=>{state.index=Number(choice.value);show()};next.onclick=()=>{state.index=Math.min(state.index+1,state.prepared.parts.length-1);show()};save.onclick=async()=>{if(!state.prepared)return;save.disabled=true;try{const value=await post('/telegram-export',{file:name,text:state.prepared.text});state.message='Сохранено в Загрузки · '+value.filename;status.textContent=state.message}catch(e){state.message=e.message;status.textContent=state.message}finally{save.disabled=false}};
 show();
}
function renderPresentations(box,card,result,name){
 if(!result.presentations?.length)return;
 const area=el('section',undefined,'presentation-list');area.append(el('h4','Выступления одногруппников'),el('p','Роли определены предварительно по речевым переходам и образцам голоса.','muted'));box.append(area);
 for(const talk of result.presentations){const details=el('details',undefined,'presentation-card');details.dataset.start=talk.start;details.append(el('summary',talk.title+(talk.ongoing?' · граница окончания пока не определена':'')));area.append(details);
  details.ontoggle=async()=>{if(!details.open||details.dataset.loaded)return;details.dataset.loaded='yes';const body=el('div',undefined,'presentation-body');details.append(body);const inRange=v=>v.start>=talk.start&&v.start<talk.end;for(const segment of (result.segments||[]).filter(inRange)){const row=el('p',undefined,'segment');row.dataset.segment=segment.id;row.dataset.role=speakerLabel(result,segment);row.append(el('strong',row.dataset.role+': ','speaker-label'),el('span',segment.text));body.append(row)}
   formulaRows(body,{formulas:(result.formulas||[]).filter(inRange)},card);renderLearningMoments(body,card,result,name,talk).catch(studyError);
   try{const r=await fetch('/notes?file='+encodeURIComponent(name));const notes=await r.json();for(const marker of (notes.markers||[]).filter(inRange))body.append(el('p','◆ '+(marker.title||'Метка'),'emphasis'));for(const photo of (notes.photos||[]).filter(inRange)){const figure=el('figure',undefined,'section-photo'),image=el('img');image.src='/photos/'+photo.id;image.alt='Фото к выступлению';image.loading='lazy';figure.append(image);body.append(figure)}await applyProofreading(body,name)}catch(e){studyError(e)}
  };
 }
}

function renderFullLecture(box,card,result,name){
 const section=el('section',undefined,'full-lecture');section.append(el('h4','Полный текст лекции'));
 if(result.draft){const first=result.segments?.[0]?.start||0;section.append(el('p',first>10?'Начальная часть записи ещё не расшифрована. Она появится после полного распознавания аудио.':'Предварительная расшифровка: весь текст, накопленный с начала распознавания.','muted'));}
 if(Object.keys(result.speaker_roles||{}).length)section.append(el('p','Подписи говорящих определены предварительно; неизвестные роли не подставляются.','muted'));
 const timeline=el('div',undefined,'full-lecture-timeline');section.append(timeline);box.append(section);
 const render=notes=>{
  const events=[...(result.segments||[]).map(item=>({kind:'speech',item})),...(result.formulas||[]).map(item=>({kind:'formula',item})),...(result.highlights||[]).map(item=>({kind:'highlight',item})),...(notes.markers||[]).map(item=>({kind:'marker',item})),...(notes.photos||[]).map(item=>({kind:'photo',item}))].sort((a,b)=>a.item.start-b.item.start||(a.kind==='marker'?-1:1));
  timeline.dataset.materialGeneration=String(Number(timeline.dataset.materialGeneration||0)+1);timeline.replaceChildren();
  for(const {kind,item} of events){
   if(kind==='speech'){const row=el('p',undefined,'segment');row.dataset.start=item.start;row.dataset.end=item.end;row.dataset.segment=item.id;const remark=result.teacher_remarks?.find(r=>(r.segment_ids||[r.segment_id]).includes(item.id));if(remark){row.classList.add('teacher-remark-'+remark.category);row.title=remark.category==='important'?'Важное замечание преподавателя · предварительно':'Организационная реплика · предварительно'}if(result.speaker_roles?.[item.id]){row.dataset.role=speakerLabel(result,item);row.append(el('strong',row.dataset.role+': ','speaker-label'))}row.append(el('span',item.text));timeline.append(row)}
   if(kind==='marker'){const row=el('div',undefined,'lecture-marker mythic-card');row.append(el('strong','◆ '+(item.title||'Метка')));timeline.append(row)}
   if(kind==='photo'){timeline.append(boardPhotoFigure(item))}
   if(kind==='formula')formulaRows(timeline,{formulas:[item]},card);
   if(kind==='highlight')timeline.append(el('p',item.point,'emphasis'));
  }
  if(!events.length)timeline.append(el('p','Текст появится после распознавания речи.','muted'));
  renderLearningMoments(timeline,card,result,name,null,true).catch(studyError);
  applyProofreading(timeline,name).catch(studyError);
 };
 render({markers:card.lesson?.markers||[]});
 fetch('/notes?file='+encodeURIComponent(name)).then(r=>r.ok?r.json():null).then(notes=>{if(notes&&timeline.isConnected)render(notes)}).catch(studyError);

}

function renderTemporalSections(box,card,result,name){
 const sections=temporalSections(result,card.lesson?.merged_parts||[],card.lesson?.markers||[]);
 for(const section of sections){
  const details=el('details',undefined,section.marker?'temporal-section marker-topic mythic-card':'temporal-section');details.dataset.start=section.start;details.append(el('summary',timeLabel(section.start)+' — '+section.title));box.append(details);
  details.ontoggle=async()=>{if(!details.open||details.dataset.loaded)return;details.dataset.loaded='yes';
   const body=el('div',undefined,'temporal-body');details.append(body);body.append(jumpButton(section.start,card.audio));
   const inRange=item=>item.start>=section.start&&item.start<section.end;
   const rows=(result.segments||[]).filter(inRange);
   if(rows.length){const transcript=el('div',undefined,'section-transcript');for(const segment of rows){const row=el('p',undefined,'segment');row.dataset.segment=segment.id;row.append(el('small',timeLabel(segment.start)),el('span',segment.text));transcript.append(row)}body.append(transcript)}else body.append(el('p','Расшифровка этого отрывка пока не готова.','muted'));
   formulaRows(body,{formulas:(result.formulas||[]).filter(inRange)},card);
   for(const item of (result.highlights||[]).filter(inRange))body.append(el('p',item.point,'emphasis'));
   const materials=el('section');body.append(materials);renderLearningMoments(materials,card,result,name,section).catch(studyError);
   try{const response=await fetch('/notes?file='+encodeURIComponent(name));if(!response.ok)return;const notes=await response.json();
    for(const photo of (notes.photos||[]).filter(inRange)){const figure=el('figure',undefined,'section-photo'),image=el('img');image.src='/photos/'+photo.id;image.alt='Фото на '+timeLabel(photo.start);image.loading='lazy';figure.append(image,el('figcaption',timeLabel(photo.start)));body.append(figure)}
    for(const marker of (notes.markers||[]).filter(inRange))body.append(el('p',timeLabel(marker.start)+' — '+(marker.title||'Метка')));
   }catch(e){studyError(e)}
  };
 }
 if(!sections.length)box.append(el('p','Временные темы появятся после расшифровки.','muted'));
}

let voiceSampleAudio=null,voiceSampleButton=null;
function sampleButton(name,speaker,monitor=false){
 const button=el('button','▶ Послушать','secondary');button.onclick=async()=>{
  if(voiceSampleButton===button&&voiceSampleAudio&&!voiceSampleAudio.paused){voiceSampleAudio.pause();button.textContent='▶ Послушать';return}
  voiceSampleAudio?.pause();if(voiceSampleButton)voiceSampleButton.textContent='▶ Послушать';voiceSampleButton=button;
  voiceSampleAudio=new Audio('/voice-sample?file='+encodeURIComponent(name)+'&speaker='+speaker+'&monitor='+(monitor?'1':'0'));button.textContent='Подбираю пример…';voiceSampleAudio.onplaying=()=>button.textContent='■ Остановить';voiceSampleAudio.onended=()=>button.textContent='▶ Послушать';
  try{await voiceSampleAudio.play()}catch(e){button.textContent='▶ Послушать';studyError(new Error('Пример голоса пока недоступен. Попробуй, когда он снова заговорит.'))}
 };return button;
}
