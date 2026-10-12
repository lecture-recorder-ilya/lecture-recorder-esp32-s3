(() => {
 const box=document.createElement('section');box.className='card settings-card';
 const title=document.createElement('h2');title.textContent='Обновления';
 const message=document.createElement('p');message.className='muted';message.setAttribute('role','status');
 const button=document.createElement('button');button.textContent='Проверить новую версию';
 button.onclick=async()=>{button.disabled=true;try{await post('/check-updates');message.textContent='Проверяю…'}catch(error){message.textContent='Не удалось проверить: '+error.message}finally{button.disabled=false}};
 box.append(title,message,button);document.querySelector('#view-settings').append(box);
 let generation=null;
 async function poll(){try{const r=await fetch('/app-info',{cache:'no-store',signal:AbortSignal.timeout(3000)});if(!r.ok)return;const value=await r.json();const status=value.updates?.message||'';message.textContent=/HTTP|SSL|Errno|urlopen|timed out|Offline|certificate/i.test(status)?'Не удалось проверить обновления. Попробуй позже.':status;if(generation&&generation!==value.generation){if(!document.querySelector('input:focus,textarea:focus'))location.reload();return}generation=value.generation}catch{}finally{setTimeout(poll,5000)}}
 poll();document.addEventListener('visibilitychange',()=>{if(!document.hidden)update()});
})();
