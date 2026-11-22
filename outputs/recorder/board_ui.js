/* Phone snapshots stay visible even when no confident lecture match is available. */
function boardPhotoFigure(photo,source){
 const figure=el('figure',undefined,'board-photo'),analysis=photo.analysis||{},image=el('img');image.src=source||'/photos/'+photo.id;image.alt=analysis.title||'Фото доски';image.loading='lazy';figure.append(image);
 figure.append(el('figcaption',analysis.title||'Фото доски'));if(photo.start!==undefined)figure.append(el('small','Момент лекции · '+timeLabel(photo.start),'muted'));
 if(photo.matching?.method)figure.append(el('small',photo.matching.method==='manual'?'Момент выбран вручную':photo.matching.method.includes('+content')?'Момент найден по времени и надписям':'Момент выбран по времени съёмки','muted'));
 if(analysis.description)figure.append(el('p',analysis.description));
 for(const item of analysis.formulas||[]){const formula=el('div',undefined,'board-photo-formula');try{katex.render(item.latex,formula,{displayMode:true,throwOnError:false,trust:false})}catch{formula.textContent=item.latex}figure.append(formula)}
 if(analysis.formulas?.length)figure.append(el('small','Формулы распознаны с фото','muted'));
 if(analysis.visible_text){const text=el('details');text.append(el('summary','Прочитанные надписи'),el('p',analysis.visible_text));figure.append(text)}
 const zoom=el('button','Увеличить фото','secondary');zoom.onclick=()=>{const large=image.classList.toggle('expanded');zoom.textContent=large?'Уменьшить фото':'Увеличить фото'};figure.append(zoom);return figure;
}
function initBoardPhotoCard(card,name){
 const panel=el('details',undefined,'board-attachments'),title=el('summary','Фото доски'),gallery=el('div');panel.append(title,gallery);card.result.before(panel);card.boardPhotos={panel,title,gallery,stamp:''};
 panel.ontoggle=()=>{if(panel.open)updateBoardPhotoCard(card,name)};
}
function updateBoardPhotoCard(card,name){
 const view=card.boardPhotos;if(!view)return;const photos=card.lesson?.photos||[],stamp=JSON.stringify(photos);view.title.textContent='Фото доски'+(photos.length?' · '+photos.length:'');if(view.stamp===stamp)return;view.stamp=stamp;view.gallery.replaceChildren();
 if(!photos.length)view.gallery.append(el('p','Сфотографируй доску кнопкой «Фото доски» на телефоне. После переноса Mac подберёт момент лекции.','muted'));
 for(const photo of photos){const figure=boardPhotoFigure(photo),position=el('input');position.value=timeLabel(photo.start);position.setAttribute('aria-label','Момент фото, минуты и секунды');const move=el('button','Изменить момент','secondary');move.onclick=async()=>{try{await post('/photo-time',{file:name,id:photo.id,start:boardPhotoSeconds(position.value)});await update()}catch(e){studyError(e)}};figure.append(position,move);view.gallery.append(figure)}
}
function boardPhotoSeconds(value){const parts=value.trim().split(':');if(!parts.length||parts.length>3||parts.some(v=>!/^\d+(?:\.\d+)?$/.test(v)))throw Error('Укажи время как 12:30');if(parts.length>1&&parts.slice(1).some(v=>Number(v)>=60))throw Error('Минуты и секунды после двоеточия должны быть от 0 до 59');return parts.reduce((sum,v)=>sum*60+Number(v),0)}
const boardInbox=el('details',undefined,'card board-inbox');const boardHeading=el('summary'),boardCount=el('span','','board-count');boardHeading.append(el('span','Фото с телефона','board-inbox-title'),boardCount);boardInbox.append(boardHeading);const boardStatus=el('p','','muted'),boardList=el('div');boardInbox.append(boardStatus,boardList);document.querySelector('#view-library .view-intro').after(boardInbox);
const boardShortcut=el('button','Фото с телефона','secondary');
boardShortcut.type='button';
boardShortcut.onclick=()=>{
 window.showLectureView?.('library');
 boardInbox.open=true;
 boardHeading.focus({preventScroll:true});
 boardInbox.scrollIntoView({block:'nearest'});
};
document.querySelector('#view-record .record-shortcuts')?.append(boardShortcut);
let boardPollTimer,boardPolling=false;const boardDrafts=new Map();
async function pollBoardPhotos(){
 if(boardPolling)return;boardPolling=true;
 clearTimeout(boardPollTimer);
 try{if(document.hidden)return;const response=await fetch('/board-photos');if(!response.ok)return;const data=await response.json();const pending=(data.photos||[]).filter(p=>p.state!=='linked');boardCount.textContent=pending.length?String(pending.length):'';boardStatus.textContent=data.processing?data.message:pending.length?'Ожидают обработки или выбора занятия: '+pending.length:(data.photos||[]).length?'Все снимки прикреплены к занятиям.':'Снимки появятся здесь после переноса с телефона.';
  const stamp=JSON.stringify(pending);if(boardList.dataset.stamp===stamp)return;boardList.dataset.stamp=stamp;boardList.replaceChildren();
  for(const photo of pending){const card=el('div',undefined,'board-inbox-card');card.append(boardPhotoFigure(photo,'/board-photo-image/'+photo.id));const states={queued:'Ожидает разбора на Mac',reading:'Читаю надписи и формулы…',waiting_lecture:'Фото прочитано. Подходящее занятие пока не найдено.',error:'Фото сохранено. Не удалось прочитать надписи.'};card.append(el('p',states[photo.state]||'Фото сохранено','muted'));
   const select=el('select');select.setAttribute('aria-label','Занятие для фото');select.append(new Option('Выбери занятие',''));for(const name of studyStatus?.files||[]){const lesson=studyStatus.lessons?.[name]||{};select.append(new Option((lesson.date||name.slice(8,18))+' · '+(lesson.subject||lesson.topic||'Вне расписания')+' · '+name.slice(19,24).replace('-',':'),name))}const time=el('input');time.placeholder='Момент лекции, например 12:30';const draft=boardDrafts.get(photo.id)||{file:'',time:'00:00'};select.value=draft.file;time.value=draft.time;select.onchange=time.oninput=()=>{boardDrafts.set(photo.id,{file:select.value,time:time.value});attach.disabled=!select.value;};time.setAttribute('aria-label','Момент лекции для фото');const attach=el('button','Прикрепить к этому моменту');attach.disabled=!select.value;attach.onclick=async()=>{if(!select.value)return;attach.disabled=true;try{await post('/board-photo-assign',{id:photo.id,file:select.value,start:boardPhotoSeconds(time.value)});boardList.dataset.stamp='';await update();pollBoardPhotos()}catch(e){studyError(e)}finally{attach.disabled=!select.value}};card.append(select,time,attach);boardList.append(card)}
 }catch{}finally{boardPolling=false;boardPollTimer=setTimeout(pollBoardPhotos,5000)}
}
pollBoardPhotos();
