(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.LectureTelegram=api})(typeof globalThis!=='undefined'?globalThis:this,()=>{
 const LIMIT=3900;
 const clean=value=>String(value??'').replace(/\r/g,'').replace(/\*\*([^*]+)\*\*/g,'$1').replace(/^#{1,6}\s+/gm,'').trim();
 function group(text,offset){while(text[offset]===' ')offset++;if(text[offset]!=='{')return null;let depth=1,end=offset+1;for(;end<text.length&&depth;end++){if(text[end]==='{')depth++;if(text[end]==='}')depth--}return depth?null:{text:text.slice(offset+1,end-1),end}}
 function formula(value){
  let text=String(value??'').replace(/\\\\(?=[A-Za-z])/g,'\\').replace(/\\(?:begin|end)\{[^}]+\}/g,'').replace(/\\(?:left|right|displaystyle)/g,'').replace(/\\\\/g,'\n').replace(/&/g,'');
  for(let guard=0;guard<40;guard++){const match=/\\(?:dfrac|tfrac|frac|sqrt)/.exec(text);if(!match)break;const first=group(text,match.index+match[0].length);if(!first)break;const second=match[0]==='\\sqrt'?null:group(text,first.end);if(match[0]!=='\\sqrt'&&!second)break;const replacement=second?'('+formula(first.text)+') / ('+formula(second.text)+')':'√('+formula(first.text)+')';text=text.slice(0,match.index)+replacement+text.slice(second?second.end:first.end)}
  const names={alpha:'α',beta:'β',gamma:'γ',delta:'δ',epsilon:'ε',theta:'θ',lambda:'λ',mu:'μ',sigma:'σ',omega:'ω',pi:'π',infty:'∞',to:'→',rightarrow:'→',sim:'∼',approx:'≈',le:'≤',leq:'≤',ge:'≥',geq:'≥',neq:'≠',cdot:'·',times:'×',div:'÷',pm:'±',int:'∫',sum:'Σ',sin:'sin',cos:'cos',tan:'tan',tg:'tg',log:'log',ln:'ln',lim:'lim',quad:' ',qquad:' '};
  text=text.replace(/\\([A-Za-z]+)/g,(all,key)=>names[key]??key);
  text=text.replace(/lim_\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}/g,(_,body)=>'lim ('+body.replace(/[{}]/g,'')+') ');
  const supers={'0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹','-':'⁻','+':'⁺','n':'ⁿ'};const subs={'0':'₀','1':'₁','2':'₂','3':'₃','4':'₄','5':'₅','6':'₆','7':'₇','8':'₈','9':'₉','-':'₋','+':'₊'};
  text=text.replace(/([_^])(?:\{([^{}]+)\}|([0-9n+-]))/g,(_,sign,a,b)=>{const body=a??b,map=sign==='^'?supers:subs;return [...body].every(c=>map[c])?[...body].map(c=>map[c]).join(''):sign+'('+body+')'});
  return text.replace(/[{}]/g,'').replace(/[ \t]+/g,' ').replace(/ *\n */g,'\n').trim();
 }
 function blocks(result,lesson={},full=false){
  const rows=[];if(result.overview)rows.push(clean(result.overview));
  if(result.summary?.length)rows.push('📝 КОНСПЕКТ\n'+result.summary.map(x=>'• '+clean(x)).join('\n'));
  if(result.highlights?.length)rows.push('📌 ВАЖНОЕ\n'+result.highlights.map(x=>'• '+clean(x.point)).filter(x=>x!=='• ').join('\n'));
  if(result.formulas?.length)rows.push('🧮 ФОРМУЛЫ\n'+result.formulas.map(x=>formula(x.latex)).filter(Boolean).join('\n\n'));
  if(result.homework?.length)rows.push('🏠 ДОМАШНЕЕ ЗАДАНИЕ\n'+result.homework.map(x=>'• '+clean(x.task)+(x.deadline?' · '+clean(x.deadline):'')).join('\n'));
  if(full){
   const texts=(result.segments||[]).map(x=>clean(x.text)).filter(Boolean);let paragraphs=[],current='';
   for(const text of texts){if(current.length+text.length>650&&current){paragraphs.push(current);current=''}current+=(current?' ':'')+text;if(current.length>350&&/[.!?…]$/.test(current)){paragraphs.push(current);current=''}}
   if(current)paragraphs.push(current);
   const body=paragraphs.join('\n\n')||clean(result.transcript).replace(/^\[\d+(?:\.\d+)?\]\s*/gm,'');
   if(body)rows.push('📖 ПОЛНЫЙ ТЕКСТ\n'+body);
  }
  return rows.filter(Boolean).join('\n\n');
 }
 function prefix(result,lesson={},name=''){
  const title=clean(result.topic||lesson.subject||result.subject||'Лекция');const short=[...title].slice(0,100).join('')+(Array.from(title).length>100?'…':'');const lines=['📚 '+short];
  const subject=clean(lesson.subject||result.subject);if(subject&&subject!==title)lines.push(subject.slice(0,80));
  const date=/lecture-(\d{4})-(\d{2})-(\d{2})/.exec(name);if(date)lines.push(date[3]+'.'+date[2]+'.'+date[1]);
  const teacher=clean(lesson.teacher||result.teacher);if(teacher)lines.push('Преподаватель: '+teacher.slice(0,80));
  return lines.join('\n');
 }
 function safeCut(text,limit){let end=limit;if(end<text.length&&/[\uD800-\uDBFF]/.test(text[end-1]))end--;if(typeof Intl.Segmenter==='function'){const segmenter=new Intl.Segmenter('ru',{granularity:'grapheme'});let safe=0;for(const item of segmenter.segment(text.slice(0,limit+32))){if(item.index+item.segment.length>end)break;safe=item.index+item.segment.length}end=safe||end}return end}
 function split(body,cap){const chunks=[];let remaining=body;while(remaining.length>cap){let end=remaining.lastIndexOf('\n\n',cap);if(end<cap*.45)end=remaining.lastIndexOf('\n',cap);if(end<cap*.45)end=remaining.lastIndexOf(' ',cap);if(end<cap*.45)end=safeCut(remaining,cap);chunks.push(remaining.slice(0,end).trim());remaining=remaining.slice(end).trim()}if(remaining)chunks.push(remaining);return chunks}
 function prepare(result,lesson={},name='',full=false){const header=prefix(result,lesson,name),body=blocks(result,lesson,full);if(!body)return {text:'',parts:[],title:header};const text=header+'\n\n'+body;if(text.length<=LIMIT)return {text,parts:[text],title:header};const chunks=split(body,LIMIT-header.length-40);return {text,title:header,parts:chunks.map((part,i)=>header+'\nЧасть '+(i+1)+'/'+chunks.length+'\n\n'+part)}}
 return {LIMIT,formula,blocks,prepare,split};
});
