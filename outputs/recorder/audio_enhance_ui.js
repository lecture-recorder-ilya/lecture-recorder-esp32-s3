(() => {
 'use strict';
 const element=(tag,text,cls)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(cls)item.className=cls;return item};
 function attach(card,name){
  const section=element('details',undefined,'audio-enhancement');section.setAttribute('aria-label','Очистка звука');
  const heading=element('summary',undefined,'enhancement-heading');heading.append(element('strong','Улучшить звук'),element('span','На этом Mac','enhancement-local'));section.append(heading);
  const description=element('p','Меньше фонового шума, ровнее громкость. Длительность и таймкоды сохраняются.','muted');section.append(description);
  const actions=element('div',undefined,'enhancement-actions');
  const profile=element('select');profile.setAttribute('aria-label','Режим очистки');
  for(const [key,title] of [['gentle','Бережная очистка'],['strong','Усиленная очистка']]){const option=element('option',title);option.value=key;profile.append(option)}
  const prepare=element('button','Очистить звук','secondary');prepare.type='button';actions.append(profile,prepare);section.append(actions);
  const compare=element('div',undefined,'enhancement-compare');compare.setAttribute('role','group');compare.setAttribute('aria-label','Сравнить оригинал и очищенный звук');
  const original=element('button','Оригинал','secondary'),clean=element('button','Очищенный','secondary');original.type=clean.type='button';original.setAttribute('aria-pressed','true');clean.setAttribute('aria-pressed','false');clean.disabled=true;compare.append(original,clean);section.append(compare);
  const download=element('a','Скачать очищенную запись');download.hidden=true;download.download=name.replace(/\.wav$/,'-clean.wav');section.append(download);
  const notice=element('p','','enhancement-status');notice.setAttribute('role','status');section.append(notice);card.playerDock.after(section);
  let processed=null,timer=null,checking=false,started=false,switchHandler=null,sequence=0;
  const source='/recordings/'+encodeURIComponent(name);
  function switchAudio(url,isClean){
   const audio=card.audio,time=Number.isFinite(audio.currentTime)?audio.currentTime:0,playing=!audio.paused,rate=audio.playbackRate;
   if(switchHandler)audio.removeEventListener('loadedmetadata',switchHandler);
   audio.pause();card.pendingSeek=null;
   switchHandler=()=>{audio.currentTime=Math.min(time,Number.isFinite(audio.duration)?audio.duration:time);audio.playbackRate=rate;if(playing)audio.play().catch(()=>{notice.textContent='Нажми воспроизведение в плеере.'});switchHandler=null};
   audio.addEventListener('loadedmetadata',switchHandler,{once:true});audio.src=url;audio.load();
   original.setAttribute('aria-pressed',String(!isClean));clean.setAttribute('aria-pressed',String(isClean));
  }
  original.onclick=()=>switchAudio(source,false);clean.onclick=()=>{if(processed)switchAudio(processed,true)};
  function show(value){
   const busy=['queued','processing'].includes(value.status);prepare.disabled=busy;profile.disabled=busy;
   notice.textContent=value.message||'Оригинал всегда доступен для сравнения.';
   prepare.textContent=busy?'Очищаю…':value.status==='error'?'Повторить очистку':value.status==='ready'?'Готово':'Очистить звук';
   prepare.disabled=busy||value.status==='ready';clean.disabled=value.status!=='ready';download.hidden=value.status!=='ready';
   processed=value.status==='ready'?value.url:null;if(processed)download.href=processed;
   clearTimeout(timer);if(busy&&section.isConnected)timer=setTimeout(check,1500);
  }
  async function check(){
   if(checking||!section.isConnected)return;checking=true;const request=sequence;
   try{const response=await fetch('/audio-enhancement?'+new URLSearchParams({file:name,profile:profile.value}),{cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(value.error||'Не удалось проверить очистку.');if(request===sequence)show(value)}
   catch(error){if(request===sequence){notice.textContent=error.message;prepare.disabled=false;profile.disabled=false;prepare.textContent='Повторить очистку'}}finally{checking=false;if(request!==sequence)check()}
  }
  prepare.onclick=async()=>{prepare.disabled=true;profile.disabled=true;notice.textContent='Добавляю запись в очередь…';try{const value=await post('/audio-enhancement',{file:name,profile:profile.value});show(value)}catch(error){notice.textContent=error.message;prepare.disabled=false;profile.disabled=false}};
  profile.onchange=()=>{sequence++;processed=null;clean.disabled=true;download.hidden=true;prepare.disabled=false;prepare.textContent='Очистить звук';if(clean.getAttribute('aria-pressed')==='true')switchAudio(source,false);check()};
  card.details.addEventListener('toggle',()=>{if(card.details.open&&!started){started=true;check()}});
 }
 window.AudioEnhancement={attach};
})();
