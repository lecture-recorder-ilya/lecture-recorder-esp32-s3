"use strict";

globalThis.ZuMind = (() => {
  const roles={decisions:"Решение",changes:"Изменение",superseded:"Отменённое решение",actions:"Задача",questions:"Вопрос",review:"Проверить на слух",explanations:"Объяснение",examples:"Пример",proposal:"Предложение",speech:"Цитата",mark:"Отметка"};
  const starts=/^(?:ну[, ]+)?(?:теперь (?:поговорим |перейд[её]м )?(?:о|об|к|про)|перейд[её]м (?:к|ко)|(?:перв(?:ая|ый)|втор(?:ая|ой)|следующ(?:ая|ий)|отдельн(?:ая|ый)|нов(?:ая|ый)) (?:тема|вопрос)|что касается|обсудим)\s*[:—–-]?\s+/iu;
  const stop=new Set("когда какой какая какую какие этот этого этой этом здесь тогда нужно будет будет сейчас сегодня давайте обсудим теперь давайте очень если даже просто можно одного потому также такой такая вроде вообще дальше значит после перед надо были быть есть про без или только давайте согласен решили согласовали договорились четверг пятниц пятницу среду субботу понедельник вторник пятницы кто мне тебя нас они уже этого пока".split(" "));
  const filler=/^(?:\s|[\p{P}\p{S}]|э+|м+|а+|ну|угу|ага|да|нет|тишина|шум|музыка|неразборчиво)+$/iu;
  const stamp=t=>Math.floor(t/60)+":"+String(Math.floor(t%60)).padStart(2,"0");
  function terms(text) {
    const words=text.toLowerCase().replaceAll("ё","е").match(/[а-яa-z0-9]{3,}/gu) || [];
    return new Set(words.filter(w=>!stop.has(w)).map(w=>w.length>5?w.slice(0,5):w));
  }
  function shares(first,second){ for(const word of first) if(second.has(word)) return true; return false; }
  function short(text,n=7) {
    const words=text.trim().replace(/[.!?;:,]+$/u,"").split(/\s+/u);
    return words.slice(0,n).join(" ")+(words.length>n?"…":"");
  }
  function groups(input) {
    const rows=input.filter(row=>!filler.test(row.text.toLowerCase()));
    if(!rows.length) return [];
    const bag=rows.map(r=>terms(r.text));
    const parts=[];let from=0;
    for(let i=1;i<rows.length;i++) {
      const size=i-from, row=rows[i], last=rows[i-1];
      const explicit=starts.test(row.text) && (size>=2 || !starts.test(last.text)) && !/^обсудим (?:в|во|на|через) /iu.test(row.text);
      const earlier=new Set([...(bag[i-2] || []),...bag[i-1]]);
      const later=new Set([...bag[i],...(bag[i+1] || [])]);
      const separate=size>=3 && rows.length-i>=2 && shares(bag[i],bag[i+1] || new Set()) && !shares(earlier,later);
      const continuation=Boolean(row.references?.includes(last) || last.kind==="proposal" || row.kind==="changes");
      if(explicit || (!continuation && (separate || size>=18 || row.start-last.end>=45))) {
        parts.push(rows.slice(from,i));from=i;
      }
    }
    parts.push(rows.slice(from));
    return parts.map((part,i)=>{
      const lead=part[0];let title;
      if(starts.test(lead.text)) {
        const preposition=lead.text.match(/^(?:ну[, ]+)?(?:теперь (?:поговорим |перейд[её]м )?|перейд[её]м )(о|об|к|ко|про)\s+/iu);
        title=short((preposition?preposition[1]+" ":"")+lead.text.replace(starts,""));
      }
      if(!title) {
        const freq=new Map();
        for(const row of part)for(const term of terms(row.text))freq.set(term,(freq.get(term)||0)+1);
        let chosen=lead, best=-Infinity;
        for(const row of part){
          if(row.kind==="review" || row.kind==="superseded")continue;
          const ws=terms(row.text),overlap=[...ws].reduce((n,w)=>n+(freq.get(w)-1),0);
          const score=overlap/Math.sqrt(1+ws.size)+(row.kind==="decisions"?.4:0);
          if(score>best){best=score;chosen=row;}
        }
        title=short(chosen.text);
      }
      const id="topic-"+i;
      return {id,title:title[0].toLocaleUpperCase("ru")+title.slice(1),start:lead.start,end:part.at(-1).end,rows:part};
    });
  }

  function outline(title, topics, extra, key) {
    const quote=r=>({title:r.text,start:r.start,end:r.end??r.start,kind:r.kind||"speech",recording:key,status:r.kind==="review"?"needs_review":"transcript",note:r.reason || r.note || "",children:(r.references || []).map(x=>({title:x.text,start:x.start,end:x.end,kind:"speech",children:[]}))});
    const branches=topics.map(topic=>{
      const children=[],byKind=new Map();
      for(const row of topic.rows){
        const role=row.kind==="speech"?"speech":row.kind;
        if(!byKind.has(role)){const group={title:roles[role] || "Цитаты",children:[]};byKind.set(role,group);children.push(group);}
        byKind.get(role).children.push(quote(row));
      }
      return {title:topic.title,ref:topic.id,start:topic.start,end:topic.end,children};
    });
    for(const group of extra.filter(g=>g.rows.length)) branches.push({title:group.title,ref:group.id,children:group.rows.map(quote)});
    return {version:1,recording:key,title,children:branches};
  }

  function archive(tree) {
    const zip=globalThis.fflate;
    let serial=0;
    const convert=node=>{
      const timed=Number.isFinite(node.start) && node.kind;
      const topic={id:"zu-"+(++serial),class:"topic",title:timed?stamp(node.start)+"  "+node.title:node.title};
      if(timed)topic.notes={plain:{content:[tree.title,stamp(node.start)+"–"+stamp(node.end),roles[node.kind],node.note].filter(Boolean).join("\n")}};
      if(node.children?.length)topic.children={attached:node.children.map(convert)};
      return topic;
    };
    const root=convert(tree);root.structureClass="org.xmind.ui.map.unbalanced";
    const files={"content.json":[{id:"zu-sheet",class:"sheet",title:tree.title,rootTopic:root}],
      "metadata.json":{creator:{name:"зу"},dataStructureVersion:"2"},
      "manifest.json":{"file-entries":{"content.json":{},"metadata.json":{}}}};
    return zip.zipSync(Object.fromEntries(Object.entries(files).map(([name,value])=>[name,zip.strToU8(JSON.stringify(value))])),{level:1});
  }

  function element(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n;}
  const palette=["#e9b89d","#a3c4b7","#acc3e8","#d2b5db","#d5c888","#a5ced7"];
  function graphical(title,topics,go,play,state,canPlay) {
    const section=element("section","zu-canvas");section.setAttribute("aria-label","Интеллект-карта по темам");
    const tools=element("div","zu-canvas-controls"),status=element("span","","Темы · "+topics.length);
    const viewport=element("div","zu-viewport");viewport.tabIndex=0;viewport.setAttribute("aria-label","Схема тем. Стрелки перемещают схему.");
    viewport.addEventListener("scroll",()=>{state.y=viewport.scrollTop;state.x=viewport.scrollLeft;},{passive:true});
    const frame=element("div","zu-map-frame"),world=element("div","zu-world");frame.append(world);viewport.append(frame);
    let scale=state.scale || 1, count=state.count || 6;
    function action(label,fn){const b=element("button","",label);b.type="button";b.onclick=fn;return b;}
    const less=action("−",()=>zoom(-.15)),more=action("+",()=>zoom(.15)),all=action("Ещё темы",()=>{count+=6;state.count=count;draw();});
    less.setAttribute("aria-label","Уменьшить карту");more.setAttribute("aria-label","Увеличить карту");
    let width=0,height=0,fromSize=0;
    function zoom(delta){
      scale=Math.min(2,Math.max(.65,Math.round((scale+delta)*100)/100));state.scale=scale;
      world.style.transform="scale("+scale+")";frame.style.width=width*scale+"px";frame.style.height=height*scale+"px";
      less.disabled=scale<=.65;more.disabled=scale>=2;
    }
    const svgNS="http://www.w3.org/2000/svg";
    function draw(){
      const actual=viewport.clientWidth || 760;fromSize=actual;const wide=actual>=710;
      const visible=topics.slice(0,count),cols=wide?2:1,lanes=Math.ceil(visible.length/cols);
      width=wide?Math.max(actual,840):Math.max(actual,315);
      const laneH=wide?112:126;
      height=lanes*laneH+(wide?32:92);
      world.replaceChildren();world.style.width=width+"px";world.style.height=height+"px";
      const svg=document.createElementNS(svgNS,"svg");svg.setAttribute("aria-hidden","true");svg.setAttribute("width",width);svg.setAttribute("height",height);world.append(svg);
      function line(x,y,u,v,color,vertical=false){
        const curve=document.createElementNS(svgNS,"path"),mx=(x+u)/2,my=(y+v)/2;
        curve.setAttribute("d",vertical?`M${x} ${y} Q${x} ${v} ${u} ${v}`:`M${x} ${y} C${mx} ${y},${mx} ${v},${u} ${v}`);curve.setAttribute("stroke",color);curve.setAttribute("fill","none");curve.setAttribute("stroke-width","2");svg.append(curve);
      }
      function box(cls,text,x,y,w,h,color,fn,label){
        const n=fn?action(text,fn):element("span","",text);n.className=cls;n.title=label || text;
        if(label)n.setAttribute("aria-label",label);
        Object.assign(n.style,{left:x+"px",top:y+"px",width:w+"px",height:h+"px","--branch-color":color});n.style.setProperty("--branch-color",color);world.append(n);return n;
      }
      const rootW=wide?124:Math.min(240,width-35),rootH=58,rootX=wide?(width-rootW)/2:12,rootY=wide?(height-rootH)/2:8;
      box("zu-node-root",title,rootX,rootY,rootW,rootH,"#f2bd9a",null);
      visible.forEach((topic,i)=>{
        const right=wide && i%2===1, lane=wide?Math.floor(i/2):i;
        const color=palette[i%palette.length],h=54;
        const topicW=wide?Math.max(116,Math.floor((width-rootW)/2*.37)):Math.max(110,Math.floor((width-57)*.47));
        const tx=wide?(right?rootX+rootW+24:rootX-24-topicW):29,ty=(wide?18:83)+lane*laneH+(laneH-h)/2;
        if(wide)line(right?rootX+rootW:rootX,rootY+rootH/2,right?tx:tx+topicW,ty+h/2,color);
        else {line(16,rootY+rootH,16,ty+h/2,color);line(16,ty+h/2,tx,ty+h/2,color);}
        box("zu-node-topic",topic.title,tx,ty,topicW,h,color,()=>go(topic.id),topic.title+". Открыть все цитаты темы");
        const useful=topic.rows.filter(r=>["decisions","actions","questions","changes","examples","explanations","review"].includes(r.kind));
        const picks=(useful.length?useful:topic.rows).slice(0,2);
        const x=wide?(right?tx+topicW+18:8):tx+topicW+14;
        const w=wide?(right?width-x-8:tx-26):width-x-6;
        picks.forEach((row,k)=>{
          const y=ty+(h-44)/2+(k-(picks.length-1)/2)*49;
          line(wide && !right?tx:tx+topicW,ty+h/2,wide && !right?x+w:x,y+22,color);
          const b=box("zu-node-quote",short(row.text,7),x,y,w,44,color,()=>play(row.start),roles[row.kind]+" · "+stamp(row.start)+". "+row.text);
          b.disabled=!canPlay;
        });
      });
      all.hidden=count>=topics.length;zoom(0);viewport.scrollTop=state.y || 0;viewport.scrollLeft=state.x || 0;
    }
    tools.append(status,less,more,all);section.append(tools,viewport);
    requestAnimationFrame(()=>{if(section.isConnected)draw();});
    const observer=new ResizeObserver(()=>{if(section.isConnected && Math.abs(viewport.clientWidth-fromSize)>1)draw();});observer.observe(viewport);
    section.dispose=()=>observer.disconnect();
    return section;
  }
  return {groups,outline,archive,graphical,roles};
})();
