(() => {
 const reduced=matchMedia('(prefers-reduced-motion: reduce)'), bound=new WeakSet();
 const selector='.pair-button,.calendar-date,.card:not(.calendar-card),#files ul>li>details>summary';
 function bind(card){
  if(bound.has(card))return;bound.add(card);card.classList.add('tilt-card');
  if(card.matches('.has-recordings,#files ul>li>details>summary,.is-today'))card.classList.add('mythic-card');
  let frame=0,position=null;
  const reset=()=>{if(frame)cancelAnimationFrame(frame);frame=0;position=null;card.style.removeProperty('--rotate-x');card.style.removeProperty('--rotate-y');card.style.removeProperty('--shine-x');card.style.removeProperty('--shine-y');card.classList.remove('pointer-over')};
  card.addEventListener('pointermove',event=>{
   if(reduced.matches||event.pointerType==='touch'||document.body.classList.contains('drag-in-progress'))return;
   if(event.target.closest('.tilt-card')!==card){reset();return}
   position=[event.clientX,event.clientY];if(frame)return;
   frame=requestAnimationFrame(()=>{
    frame=0;if(!position||reduced.matches||!card.isConnected){reset();return}const rect=card.getBoundingClientRect();
    const x=Math.max(0,Math.min(1,(position[0]-rect.left)/rect.width)),y=Math.max(0,Math.min(1,(position[1]-rect.top)/rect.height));
    card.style.setProperty('--rotate-x',((.5-y)*5).toFixed(2)+'deg');card.style.setProperty('--rotate-y',((x-.5)*7).toFixed(2)+'deg');
    card.style.setProperty('--shine-x',(x*100).toFixed(1)+'%');card.style.setProperty('--shine-y',(y*100).toFixed(1)+'%');card.classList.add('pointer-over');
   });
  });
  card.addEventListener('pointerleave',reset);card.addEventListener('dragstart',reset);
 }
 function scan(root){if(root.nodeType!==1)return;if(root.matches(selector))bind(root);root.querySelectorAll(selector).forEach(bind)}
 scan(document.body);
 reduced.addEventListener('change',()=>{document.querySelectorAll('.tilt-card').forEach(card=>{for(const property of ['--rotate-x','--rotate-y','--shine-x','--shine-y'])card.style.removeProperty(property);card.classList.remove('pointer-over')})});
 new MutationObserver(records=>{for(const record of records)for(const root of record.addedNodes)scan(root)}).observe(document.querySelector('main'),{childList:true,subtree:true});
})();
